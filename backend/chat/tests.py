import datetime as dt
from decimal import Decimal
from unittest import mock

from django.utils import timezone
from rest_framework.test import APITestCase

from accounts import services as accounts
from accounts.models import Connection, Device, User
from bookings.models import Session
from teams.models import Group, GroupMember
from venues.models import Club, ClubMember, Court, Discount, Sport

from . import services
from .models import Chat, ChatMember, Message

PASSWORD = "court-side-42"
FRIEND, COACHING = Connection.Type.FRIEND, Connection.Type.COACHING


class ChatBase(APITestCase):
    def setUp(self):
        accounts.outbox.clear()

    def user(self, name, **fields):
        user = User.objects.create_user(f"{name}@example.com", PASSWORD, full_name=name.title(), **fields)
        Device.objects.create(user=user, token=f"tok-{name}", platform="web")  # so pushes reach them
        return user

    def befriend(self, a, b):
        Connection.objects.create(user=a, other_user=b, type=FRIEND, status="accepted")

    def call(self, method, path, user, data=None, expect=None, push=False):
        self.client.force_authenticate(user)
        if push:
            with self.captureOnCommitCallbacks(execute=True):
                r = getattr(self.client, method)(f"/api/{path}", data, format="json")
        else:
            r = getattr(self.client, method)(f"/api/{path}", data, format="json")
        if expect:
            self.assertEqual(r.status_code, expect, (method, path, data, getattr(r, "data", None)))
        return r

    def send(self, chat_id, user, body="hi", expect=201, push=False):
        return self.call("post", f"chats/{chat_id}/messages/", user, {"body": body}, expect, push)

    def unread(self, chat_id, user):
        return self.call("get", f"chats/{chat_id}/", user, expect=200).data["unread_count"]

    def chat_ids(self, user):
        return [c["id"] for c in self.call("get", "chats/", user, expect=200).data["results"]]

    def pushed_to(self, user, kind="chat_message"):
        return [p for p in accounts.outbox if p["user_id"] == user.id and p["data"]["type"] == kind]

    def club(self, owner, name="Beirut Hoops"):
        return Club.objects.create(owner=owner, name=name, timezone="Asia/Beirut", currency="USD")

    def member(self, club, user, role, **fields):
        return ClubMember.objects.create(club=club, user=user, role=role, status="active", **fields)


class DirectChatTests(ChatBase):
    def test_direct_journey(self):
        """CHAT-1, CHAT-2, CHAT-3, CHAT-10, CHAT-11, CHAT-12, CHAT-13, CHAT-14, CHAT-15, CHAT-16, CHAT-17, GEN-5, NOTE-20:
        friends open a chat from either side, send, poll, scroll back, read, and keep their history after a block."""
        ann, bob = self.user("ann"), self.user("bob")
        self.befriend(ann, bob)

        # CHAT-2: 201 then 200, the same chat from either side, with both as members
        r = self.call("post", "chats/direct/", ann, {"user": bob.id}, 201)
        cid = r.data["id"]
        self.assertEqual((r.data["type"], r.data["title"], r.data["last_message"], r.data["unread_count"]),
                         ("direct", "Bob", None, 0))
        self.assertEqual(self.call("post", "chats/direct/", ann, {"user": bob.id}, 200).data["id"], cid)
        r = self.call("post", "chats/direct/", bob, {"user": ann.id}, 200)
        self.assertEqual((r.data["id"], r.data["title"]), (cid, "Ann"))
        self.assertEqual(set(ChatMember.objects.filter(chat_id=cid).values_list("user_id", flat=True)), {ann.id, bob.id})
        self.assertEqual(Chat.objects.count(), 1)
        self.call("post", "chats/direct/", ann, {"user": 99999}, 400)  # GEN-18
        self.call("post", "chats/direct/", ann, {}, 400)

        # CHAT-10, NOTE-20: the other member is pushed, the sender is not
        r = self.send(cid, ann, "  hello bob  ", push=True)
        self.assertEqual((r.data["body"], r.data["sender"], r.data["session"]),
                         ("hello bob", {"id": ann.id, "full_name": "Ann"}, None))
        self.assertEqual([(p["title"], p["body"], p["data"]) for p in self.pushed_to(bob)],
                         [("Ann", "hello bob", {"id": str(cid), "type": "chat_message"})])
        self.assertEqual(self.pushed_to(ann), [])
        first = r.data["id"]
        second = self.send(cid, bob, "hi ann").data["id"]
        third = self.send(cid, ann, "see you at 6").data["id"]

        # CHAT-13: unread counts ignore the viewer's own messages
        self.assertEqual((self.unread(cid, ann), self.unread(cid, bob)), (1, 2))
        # CHAT-15: last message in the list
        row = self.call("get", "chats/", bob, expect=200).data["results"][0]
        self.assertEqual((row["last_message"]["id"], row["last_message"]["body"], row["unread_count"]), (third, "see you at 6", 2))

        # CHAT-14: poll with after (oldest first), scroll back with before (newest first), limits
        ids = lambda user, q: [m["id"] for m in self.call("get", f"chats/{cid}/messages/{q}", user, expect=200).data]
        self.assertEqual(ids(bob, ""), [first, second, third])
        self.assertEqual(ids(bob, f"?after={first}"), [second, third])
        self.assertEqual(ids(bob, f"?after={third}"), [])
        self.assertEqual(ids(bob, "?after=0&limit=2"), [first, second])
        self.assertEqual(ids(bob, f"?before={third}"), [second, first])
        self.assertEqual(ids(bob, f"?before={third}&limit=1"), [second])
        for bad in ("limit=0", "limit=201", "limit=x", "after=-1", "before=x", f"after=1&before={third}"):
            self.call("get", f"chats/{cid}/messages/?{bad}", bob, expect=400)

        # CHAT-12, GEN-5: mark read twice; the other side's count is untouched
        for _ in range(2):
            self.assertEqual(self.call("post", f"chats/{cid}/read/", bob, expect=200).data["unread_count"], 0)
        self.assertEqual(self.unread(cid, ann), 1)
        self.send(cid, ann, "ping")
        self.assertEqual(self.unread(cid, bob), 1)

        # CHAT-16, CHAT-17: no edit or delete, no attachments
        for method in ("put", "patch", "delete"):
            self.call(method, f"chats/{cid}/messages/{first}/", ann, {"body": "x"}, 404)
            self.call(method, f"chats/{cid}/messages/", ann, {"body": "x"}, 405)
        self.assertEqual(self.send(cid, ann, "text", expect=201).data["session"], None)
        self.assertEqual(set(self.call("get", f"chats/{cid}/messages/", ann).data[0]),
                         {"id", "chat", "sender", "body", "session", "created_at"})

        # CHAT-3: unfriend or block: history is readable, sending is refused, nobody is pushed
        Connection.objects.all().delete()
        self.assertEqual(len(ids(ann, "")), 5)
        accounts.outbox.clear()
        self.assertEqual(self.send(cid, ann, "still there?", expect=400, push=True).data["code"], "cannot_chat")
        self.assertEqual(self.send(cid, bob, "hello?", expect=400).data["code"], "cannot_chat")
        self.assertEqual((accounts.outbox, Message.objects.filter(chat_id=cid).count()), ([], 5))
        self.befriend(ann, bob)
        Connection.objects.create(user=bob, other_user=ann, type=FRIEND, status="blocked")
        Connection.objects.filter(status="accepted").delete()
        self.assertEqual(self.send(cid, bob, "blocked", expect=400).data["code"], "cannot_chat")
        self.assertEqual(len(ids(bob, "")), 5)
        self.call("post", "chats/direct/", ann, {"user": bob.id}, 400)  # CHAT-2 again: now refused

        # another user's chat is a 404 (GEN-3)
        eve = self.user("eve")
        for method, path in (("get", f"chats/{cid}/"), ("get", f"chats/{cid}/messages/"), ("post", f"chats/{cid}/read/")):
            self.call(method, path, eve, expect=404)
        self.send(cid, eve, expect=404)

    def test_who_may_chat(self):
        """CHAT-1, CHAT-2, ACC-1, ACC-12: refusals are 400 cannot_chat; a coach and their player may chat."""
        ann, stranger, coach = self.user("ann"), self.user("stranger"), self.user("carl", is_coach=True)
        player, shadow_friend = self.user("pat"), User.objects.create_user(email=None, full_name="Kid", managed_by=coach)
        gone, blocked, linked = self.user("gone"), self.user("blocked"), self.user("linked")
        self.befriend(ann, gone)
        gone.is_active = False
        gone.save()
        Connection.objects.create(user=ann, other_user=blocked, type=FRIEND, status="blocked")
        Connection.objects.create(user=coach, other_user=linked, type=COACHING, status="accepted")
        Connection.objects.create(user=player, other_user=coach, type=COACHING, status="pending")

        def refused(user, other):
            r = self.call("post", "chats/direct/", user, {"user": other.id}, 400)
            self.assertEqual(r.data["code"], "cannot_chat")

        for other in (stranger, ann, gone, blocked, coach):  # stranger, self, inactive, blocked pair, no link
            refused(ann, other)
        refused(coach, player)  # a pending coaching link is not a player
        refused(coach, shadow_friend)  # ACC-12: a shadow player is the coach's player but never a chat member
        refused(ann, shadow_friend)
        self.assertEqual(Chat.objects.count(), 0)

        # CHAT-1: either side may open it, and send
        cid = self.call("post", "chats/direct/", coach, {"user": linked.id}, 201).data["id"]
        self.assertEqual(self.call("post", "chats/direct/", linked, {"user": coach.id}, 200).data["id"], cid)
        self.send(cid, linked)
        self.send(cid, coach)
        # the coach stops coaching them: reading stays, sending stops (CHAT-3)
        Connection.objects.filter(user=coach, other_user=linked).delete()
        self.send(cid, coach, expect=400)
        self.call("get", f"chats/{cid}/messages/", linked, expect=200)

        # a team member is a coach's player too
        team = Group.objects.create(type="team", name="Tigers", created_by=coach, coach=coach)
        GroupMember.objects.create(group=team, user=player, status="active")
        self.call("post", "chats/direct/", player, {"user": coach.id}, 201)


class GroupChatTests(ChatBase):
    def test_group_chat(self):
        """CHAT-4, CHAT-10, CHAT-13, CHAT-30, CHAT-31, NOTE-20, TEAM-28: only current members read and send."""
        owner, fran, outsider = self.user("owner"), self.user("fran"), self.user("outsider")
        self.befriend(owner, fran)
        gid = self.call("post", "groups/", owner, {"name": "Friday ballers", "type": "play_group"}, 201).data["id"]
        self.call("post", f"groups/{gid}/members/", owner, {"user": fran.id}, 201)
        self.call("post", f"groups/{gid}/accept/", fran, expect=200)
        cid = Chat.objects.get(group_id=gid).id

        accounts.outbox.clear()
        self.send(cid, owner, "ball at 6?", push=True)
        self.assertEqual(len(self.pushed_to(fran)), 1)
        self.assertEqual(self.pushed_to(owner), [])
        self.assertEqual(self.call("get", f"chats/{cid}/", fran).data["title"], "Friday ballers")
        self.assertEqual(self.chat_ids(fran), [cid])

        # CHAT-30, CHAT-31: a session card is a message with no sender, no body and the session
        court = Court.objects.create(club=self.club(owner), name="C1", slot_minutes=60)
        start = timezone.now() + dt.timedelta(days=1)
        session = Session.objects.create(
            court=court, sport=Sport.objects.create(name="Hoops"), booked_by=owner, group_id=gid, kind="play",
            status="confirmed", starts_at=start, ends_at=start + dt.timedelta(hours=1), currency="USD", price=Decimal("50"))
        services.post_session_card(session)
        services.post_session_card(session)  # once only
        rows = self.call("get", f"chats/{cid}/messages/", fran, expect=200).data
        self.assertEqual((len(rows), rows[-1]["sender"], rows[-1]["body"], rows[-1]["session"]), (2, None, "", session.id))
        self.assertEqual(self.unread(cid, fran), 2)  # the card counts as unread for everyone
        self.assertEqual(self.unread(cid, owner), 1)

        # a non-member cannot read or send
        for method, path in (("get", f"chats/{cid}/"), ("get", f"chats/{cid}/messages/"), ("post", f"chats/{cid}/read/")):
            self.call(method, path, outsider, expect=404)
        self.send(cid, outsider, expect=404)
        self.assertEqual(self.chat_ids(outsider), [])

        # TEAM-28: a member who leaves can no longer read it, and gets no push
        self.call("delete", f"groups/{gid}/members/{fran.id}/", fran, expect=204)
        self.call("get", f"chats/{cid}/messages/", fran, expect=404)
        self.send(cid, fran, expect=404)
        self.assertEqual(self.chat_ids(fran), [])
        accounts.outbox.clear()
        self.send(cid, owner, "bye", push=True)
        self.assertEqual(self.pushed_to(fran), [])


class InquiryChatTests(ChatBase):
    def test_inquiry_journey(self):
        """CHAT-5, CHAT-6, CHAT-8, CHAT-10, CHAT-11, CHAT-12, CHAT-13, CHAT-15, ACC-2, ACC-6, NOTE-20:
        a user asks a club, the owner and staff answer from one shared inbox."""
        owner, staff, other_staff, expired = self.user("owner"), self.user("sam"), self.user("sue"), self.user("old")
        pat, pia = self.user("pat"), self.user("pia")
        club = self.club(owner)
        Court.objects.create(club=club, name="C1", slot_minutes=60)  # makes the club public (CLUB-30)
        today = timezone.now().date()
        self.member(club, staff, "staff")
        self.member(club, other_staff, "staff", expires_on=today + dt.timedelta(days=30))
        old = self.member(club, expired, "staff", expires_on=today + dt.timedelta(days=5))
        path = f"clubs/{club.id}/inquiries/"

        # CHAT-6: one chat per (user, club); a second club gets its own
        r = self.call("post", path, pat, {}, 201)
        cid = r.data["id"]
        self.assertEqual((r.data["type"], r.data["club"], r.data["title"]), ("inquiry", club.id, "Beirut Hoops"))
        self.assertEqual(self.call("post", path, pat, {}, 200).data["id"], cid)
        other_club = Court.objects.create(club=self.club(owner, "Saida"), name="C", slot_minutes=60).club
        self.assertNotEqual(self.call("post", f"clubs/{other_club.id}/inquiries/", pat, {}, 201).data["id"], cid)
        self.assertEqual(list(ChatMember.objects.filter(chat_id=cid).values_list("user_id", flat=True)), [pat.id])  # CHAT-5
        self.call("post", "clubs/99999/inquiries/", pat, {}, 404)
        self.call("post", path, pat, {"user": pia.id}, 400)  # only the club side names a user
        # CHAT-6: the club side cannot open one with their own club
        for who in (owner, staff):
            self.assertEqual(self.call("post", path, who, {}, 400).data["code"], "cannot_chat")

        # CHAT-10, NOTE-20: the member writes, the whole club side is pushed
        accounts.outbox.clear()
        self.send(cid, pat, "Do you rent shoes?", push=True)
        self.assertEqual([len(self.pushed_to(u)) for u in (owner, staff, other_staff, expired, pat)], [1, 1, 1, 1, 0])

        # CHAT-8, CHAT-13: the club side reads it; the member's own message is not unread for the member
        self.assertEqual([self.unread(cid, u) for u in (owner, staff, other_staff, pat)], [1, 1, 1, 0])
        self.assertEqual(self.chat_ids(staff), [cid])
        self.assertEqual(self.call("get", "chats/", staff).data["results"][0]["title"], "Pat")  # the inquirer's name
        self.assertEqual(len(self.call("get", f"chats/{cid}/messages/", other_staff, expect=200).data), 1)

        # CHAT-11, CHAT-12, GEN-5: one staff member reads, it is read for the owner and all staff
        for _ in range(2):
            self.assertEqual(self.call("post", f"chats/{cid}/read/", staff, expect=200).data["unread_count"], 0)
        self.assertEqual([self.unread(cid, u) for u in (owner, staff, other_staff)], [0, 0, 0])
        self.assertIsNotNone(Chat.objects.get(pk=cid).club_last_read_at)
        self.assertIsNone(ChatMember.objects.get(chat_id=cid).last_read_at)  # the member's marker is separate

        # a club-side reply: the member is pushed (not the other staff), and it counts for the member only
        accounts.outbox.clear()
        self.send(cid, owner, "Yes, 2 USD", push=True)
        self.assertEqual([len(self.pushed_to(u)) for u in (owner, staff, other_staff, pat)], [0, 0, 0, 1])
        self.assertEqual([self.unread(cid, u) for u in (pat, owner, staff)], [1, 0, 0])  # CHAT-13: staff replies are not unread for the club
        self.send(cid, staff, "Pat, shoes are at the desk")
        self.assertEqual((self.unread(cid, pat), self.unread(cid, other_staff)), (2, 0))
        self.call("post", f"chats/{cid}/read/", pat, expect=200)
        self.assertEqual(self.unread(cid, pat), 0)
        self.send(cid, pat, "thanks")
        self.assertEqual(self.unread(cid, owner), 1)

        # a stranger sees nothing
        self.call("get", f"chats/{cid}/", pia, expect=404)
        self.send(cid, pia, expect=404)

        # ACC-2: an expired staff member loses the club's inquiry chats at once; extending restores it
        self.assertEqual(self.chat_ids(expired), [cid])
        old.expires_on = today - dt.timedelta(days=1)
        old.save()
        self.assertEqual(self.chat_ids(expired), [])
        self.call("get", f"chats/{cid}/messages/", expired, expect=404)
        self.send(cid, expired, expect=404)
        old.expires_on = None
        old.save()
        self.assertEqual(self.chat_ids(expired), [cid])
        # a staff member of another club has no access
        self.assertEqual(self.chat_ids(self.club(self.user("rival")).owner), [])

        # a pending or non-staff membership is not the club side
        pending = self.user("pending")
        ClubMember.objects.create(club=club, user=pending, role="staff", status="pending")
        self.member(club, self.user("plr"), "player")
        self.assertEqual(self.chat_ids(pending), [])

    def test_club_opens_inquiry(self):
        """CHAT-7, CHAT-5, CHAT-8, ACC-12: the club side writes first only to users with a session, a membership or an offer."""
        owner, staff, rival = self.user("owner"), self.user("sam"), self.user("rival")
        booker, participant, cancelled, member, expired, offered, nobody = (
            self.user(n) for n in ("booker", "pam", "cancelled", "mia", "exp", "oli", "nobody"))
        club = self.club(owner)
        self.member(club, staff, "staff")
        court = Court.objects.create(club=club, name="C1", slot_minutes=60)
        sport = Sport.objects.create(name="Hoops")
        start = timezone.now() + dt.timedelta(days=1)

        def session(booked_by, status="confirmed"):
            return Session.objects.create(court=court, sport=sport, booked_by=booked_by, kind="play", status=status,
                                          starts_at=start, ends_at=start + dt.timedelta(hours=1), currency="USD",
                                          price=Decimal("50"))

        session(booker)
        session(rival).participants.create(user=participant, status="invited")
        session(cancelled, "cancelled")
        self.member(club, member, "player")
        self.member(club, expired, "player", expires_on=timezone.now().date() - dt.timedelta(days=1))
        Discount.objects.create(club=club, user=offered, percent_off=10, starts_at=start, ends_at=start, message="Hi")
        kid = User.objects.create_user(email=None, full_name="Kid", managed_by=owner)
        session(kid)  # ACC-12: even a shadow player with a session is never a chat member
        path = f"clubs/{club.id}/inquiries/"

        for who, expect in ((owner, 201), (staff, 200)):  # the second of the club side finds the same chat
            for target in (booker, participant, member, offered):
                r = self.call("post", path, who, {"user": target.id}, expect)
                self.assertEqual((r.data["type"], r.data["title"]), ("inquiry", target.full_name))
                self.assertEqual(self.call("post", path, who, {"user": target.id}, 200).data["id"], r.data["id"])
        self.assertEqual(Chat.objects.count(), 4)  # shared between owner and staff (CHAT-5)
        for target in (cancelled, expired, nobody, kid, owner, staff):  # also the club side itself
            self.assertEqual(self.call("post", path, owner, {"user": target.id}, 400).data["code"], "cannot_chat")
        self.call("post", path, owner, {}, 400)  # CHAT-6: the club side asking about itself
        self.call("post", path, owner, {"user": 99999}, 400)
        self.assertEqual(self.call("post", path, nobody, {"user": booker.id}, 400).data["code"], "cannot_chat")  # not the club side
        self.assertEqual(self.call("post", path, rival, {"user": booker.id}, 400).data["code"], "cannot_chat")

        # the member's own inquiry is that same chat, with the club's message waiting
        cid = Chat.objects.get(club=club, members__user=booker).id
        self.send(cid, staff, "We have an offer for you", push=True)
        self.assertEqual(self.unread(cid, booker), 1)
        self.assertEqual(self.call("post", path, booker, {}, 200).data["id"], cid)
        self.assertEqual(self.chat_ids(booker), [cid])


class MessageTests(ChatBase):
    def test_message_rules_and_list(self):
        """CHAT-10, CHAT-13, CHAT-14, CHAT-15, CHAT-16, CHAT-17, GEN-1, GEN-12: validation, list order and paging."""
        ann, bob, cy, di = (self.user(n) for n in ("ann", "bob", "cy", "di"))
        for other in (bob, cy):
            self.befriend(ann, other)
        c1 = self.call("post", "chats/direct/", ann, {"user": bob.id}, 201).data["id"]
        c2 = self.call("post", "chats/direct/", ann, {"user": cy.id}, 201).data["id"]

        # CHAT-10: trimmed, 1-4000 characters
        for body in ("", "   ", "x" * 4001, None):
            r = self.send(c1, ann, body, expect=400)
            self.assertIn("body", r.data)
        self.call("post", f"chats/{c1}/messages/", ann, {}, 400)
        self.assertEqual(len(self.send(c1, ann, " " + "x" * 4000 + " ").data["body"]), 4000)
        self.assertEqual(Message.objects.count(), 1)

        # CHAT-15: newest last message first; a chat with no message sorts by when it was made
        self.assertEqual(self.chat_ids(ann), [c1, c2])
        self.send(c2, cy, "hey")
        self.assertEqual(self.chat_ids(ann), [c2, c1])
        self.assertEqual([c["title"] for c in self.call("get", "chats/", ann).data["results"]], ["Cy", "Bob"])
        c3 = self.call("post", "chats/direct/", ann, {"user": bob.id}, 200).data["id"]
        self.assertEqual(c3, c1)
        self.assertEqual(self.chat_ids(di), [])

        # GEN-12: the chat list is page-number paged
        group_owner = self.user("go")
        for i in range(51):
            self.call("post", "groups/", group_owner, {"name": f"G{i}", "type": "play_group"}, 201)
        page1 = self.call("get", "chats/", group_owner, expect=200).data
        self.assertEqual((page1["count"], len(page1["results"]), bool(page1["next"])), (51, 50, True))
        self.assertEqual(len(self.call("get", "chats/?page=2", group_owner, expect=200).data["results"]), 1)

        # CHAT-14: the default poll window is 50 and the cap is 200 messages
        Message.objects.bulk_create([Message(chat_id=c2, sender=ann, body=str(i)) for i in range(205)])
        self.assertEqual(len(self.call("get", f"chats/{c2}/messages/", ann).data), 50)
        self.assertEqual(len(self.call("get", f"chats/{c2}/messages/?limit=200", ann).data), 200)
        newest = Message.objects.filter(chat_id=c2).order_by("-id")[0].id
        self.assertEqual(len(self.call("get", f"chats/{c2}/messages/?before={newest}&limit=200", ann).data), 200)
        # CHAT-13: unread counts all messages when the marker is empty
        self.assertEqual(self.unread(c2, cy), 205)
        self.assertEqual(self.unread(c2, ann), 1)

    def test_marker_uses_now(self):
        """CHAT-12, CHAT-13: mark read sets the marker to now; only later messages count."""
        ann, bob = self.user("ann"), self.user("bob")
        self.befriend(ann, bob)
        cid = self.call("post", "chats/direct/", ann, {"user": bob.id}, 201).data["id"]
        t0 = timezone.now()
        with mock.patch("django.utils.timezone.now", return_value=t0):
            self.send(cid, ann)
            self.call("post", f"chats/{cid}/read/", bob, expect=200)
            self.assertEqual(ChatMember.objects.get(chat_id=cid, user=bob).last_read_at, t0)
        with mock.patch("django.utils.timezone.now", return_value=t0 + dt.timedelta(minutes=5)):
            self.call("post", f"chats/{cid}/read/", bob, expect=200)  # a repeat only moves the time
            self.assertEqual(ChatMember.objects.get(chat_id=cid, user=bob).last_read_at, t0 + dt.timedelta(minutes=5))
        self.assertEqual(self.unread(cid, bob), 0)

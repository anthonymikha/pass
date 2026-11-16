import datetime as dt

from rest_framework.test import APITestCase

from accounts import services as accounts
from accounts.models import Connection, Device, User
from chat.models import Chat, ChatMember
from venues.models import Club, ClubMember, Court, Sport

from . import services
from .models import Group, GroupMember

PASSWORD = "court-side-42"
FRIEND, COACHING = Connection.Type.FRIEND, Connection.Type.COACHING


class TeamsBase(APITestCase):
    def setUp(self):
        accounts.outbox.clear()

    def user(self, name, **fields):
        user = User.objects.create_user(f"{name}@example.com", PASSWORD, full_name=name.title(), **fields)
        Device.objects.create(user=user, token=f"tok-{name}", platform="web")  # so pushes reach them
        return user

    def befriend(self, a, b):
        Connection.objects.create(user=a, other_user=b, type=FRIEND, status="accepted")

    def block(self, a, b):
        Connection.objects.create(user=a, other_user=b, type=FRIEND, status="blocked")

    def call(self, method, path, user, data=None, expect=None, push=False):
        self.client.force_authenticate(user)
        if push:
            with self.captureOnCommitCallbacks(execute=True):
                r = getattr(self.client, method)(f"/api/{path}", data, format="json")
        else:
            r = getattr(self.client, method)(f"/api/{path}", data, format="json")
        if expect:
            self.assertEqual(r.status_code, expect, (method, path, data, r.data if r.content else None))
        return r

    def chat_members(self, group_id):
        return set(ChatMember.objects.filter(chat__group_id=group_id).values_list("user__full_name", flat=True))

    def pushed_to(self, user, kind):
        return [p for p in accounts.outbox if p["user_id"] == user.id and p["data"]["type"] == kind]


class PlayGroupTests(TeamsBase):
    def test_play_group_journey(self):
        """TEAM-20, TEAM-21, TEAM-22, TEAM-23, TEAM-24, TEAM-25, TEAM-26, TEAM-28, TEAM-30, TEAM-31, CHAT-4, NOTE-20:
        create, invite a friend, accept, ask to join, accept, leave, remove, rename, delete."""
        owner, fran, stranger, joiner, third = (self.user(n) for n in ("owner", "fran", "stranger", "joiner", "third"))
        self.befriend(owner, fran)
        self.befriend(third, owner)  # friendship in the other direction still counts
        hoops = Sport.objects.create(name="Hoops")

        # TEAM-20: create. The owner has an active row and is the chat's only member.
        r = self.call("post", "groups/", owner, {"name": "Friday ballers", "type": "play_group", "sport": hoops.id}, 201)
        gid = r.data["id"]
        self.assertEqual((r.data["type"], r.data["coach"], r.data["owner"]["id"], r.data["member_count"]),
                         ("play_group", None, owner.id, 1))
        self.assertEqual(GroupMember.objects.get(group_id=gid, user=owner).status, "active")
        self.assertEqual(Chat.objects.get(group_id=gid).type, "group")
        self.assertEqual(self.chat_members(gid), {"Owner"})
        for bad in ({}, {"name": "", "type": "play_group"}, {"name": "x" * 256, "type": "play_group"},
                    {"name": "x", "type": "club"}, {"name": "x", "type": "play_group", "sport": 9999}):
            self.assertEqual(self.call("post", "groups/", owner, bad).status_code, 400, bad)

        # TEAM-22: invite a friend (push); a non-friend and a shadow-looking id are refused, nothing written
        r = self.call("post", f"groups/{gid}/members/", owner, {"user": fran.id}, 201, push=True)
        self.assertEqual(r.data["status"], "invited")
        self.assertEqual(len(self.pushed_to(fran, "group_invite")), 1)
        self.assertEqual(self.pushed_to(fran, "group_invite")[0]["data"]["id"], str(gid))
        r = self.call("post", f"groups/{gid}/members/", owner, {"user": stranger.id}, 400)
        self.assertEqual(r.data["code"], "cannot_invite")
        self.assertFalse(GroupMember.objects.filter(group_id=gid, user=stranger).exists())
        self.call("post", f"groups/{gid}/members/", owner, {"user": 99999}, 400)  # GEN-18
        self.call("post", f"groups/{gid}/members/", fran, {"user": third.id}, 403)  # GEN-1: not a manager
        # repeat: the row stays invited, 200, no second push
        accounts.outbox.clear()
        r = self.call("post", f"groups/{gid}/members/", owner, {"user": fran.id}, 200, push=True)
        self.assertEqual((r.data["status"], accounts.outbox), ("invited", []))
        self.assertEqual(self.chat_members(gid), {"Owner"})  # not yet

        # TEAM-23: accept (chat member added); repeat is 200 (GEN-5)
        r = self.call("post", f"groups/{gid}/accept/", fran, expect=200)
        self.assertEqual(r.data["status"], "active")
        self.assertEqual(self.chat_members(gid), {"Owner", "Fran"})
        self.call("post", f"groups/{gid}/accept/", fran, expect=200)
        self.call("post", f"groups/{gid}/accept/", stranger, expect=404)  # no invite

        # TEAM-24: ask to join (push to the managers, not to the asker); repeat 200
        accounts.outbox.clear()
        r = self.call("post", f"groups/{gid}/join/", joiner, expect=201, push=True)
        self.assertEqual(r.data["status"], "requested")
        self.assertEqual(len(self.pushed_to(owner, "join_request")), 1)
        self.assertEqual(self.pushed_to(joiner, "join_request"), [])
        accounts.outbox.clear()
        self.call("post", f"groups/{gid}/join/", joiner, expect=200, push=True)
        self.assertEqual(accounts.outbox, [])
        self.assertEqual(self.chat_members(gid), {"Owner", "Fran"})  # a request is not membership

        # TEAM-25: only a manager accepts
        self.call("post", f"groups/{gid}/members/{joiner.id}/accept/", fran, expect=403)
        r = self.call("post", f"groups/{gid}/members/{joiner.id}/accept/", owner, expect=200)
        self.assertEqual(r.data["status"], "active")
        self.assertEqual(self.chat_members(gid), {"Owner", "Fran", "Joiner"})
        self.call("post", f"groups/{gid}/members/{joiner.id}/accept/", owner, expect=200)  # GEN-5
        self.call("post", f"groups/{gid}/members/{stranger.id}/accept/", owner, expect=404)

        # TEAM-22: an existing request becomes active when the manager invites instead
        self.call("post", f"groups/{gid}/join/", third, expect=201)
        r = self.call("post", f"groups/{gid}/members/", owner, {"user": third.id}, 200)
        self.assertEqual(r.data["status"], "active")
        self.assertIn("Third", self.chat_members(gid))

        # TEAM-21: members see the list with statuses; the summary counts active rows
        r = self.call("get", f"groups/{gid}/members/", fran, expect=200)
        self.assertEqual({m["user"]["full_name"]: m["status"] for m in r.data["results"]},
                         {"Owner": "active", "Fran": "active", "Joiner": "active", "Third": "active"})
        self.assertEqual(self.call("get", f"groups/{gid}/", stranger, expect=200).data["member_count"], 4)

        # TEAM-26: a member leaves (chat member removed); a plain member cannot remove others
        self.call("delete", f"groups/{gid}/members/{joiner.id}/", fran, expect=403)
        self.call("delete", f"groups/{gid}/members/{fran.id}/", fran, expect=204)
        self.assertEqual(self.chat_members(gid), {"Owner", "Joiner", "Third"})
        self.call("delete", f"groups/{gid}/members/{fran.id}/", fran, expect=404)  # already gone
        # a manager removes a member
        self.call("delete", f"groups/{gid}/members/{third.id}/", owner, expect=204)
        self.assertEqual(self.chat_members(gid), {"Owner", "Joiner"})
        # a rejected request just disappears; a declined invite too (TEAM-23)
        self.call("post", f"groups/{gid}/join/", stranger, expect=201)
        self.call("delete", f"groups/{gid}/members/{stranger.id}/", owner, expect=204)
        self.call("post", f"groups/{gid}/members/", owner, {"user": fran.id}, 201)
        self.call("delete", f"groups/{gid}/members/{fran.id}/", fran, expect=204)
        self.assertFalse(GroupMember.objects.filter(group_id=gid, user__in=[fran, stranger]).exists())

        # TEAM-31: the owner can neither leave nor be removed
        r = self.call("delete", f"groups/{gid}/members/{owner.id}/", owner, expect=400)
        self.assertEqual(r.data["code"], "owner_cannot_leave")

        # TEAM-30: only the owner renames or deletes; summary stays readable by anyone
        self.call("patch", f"groups/{gid}/", joiner, {"name": "Mine now"}, 403)
        self.call("delete", f"groups/{gid}/", joiner, expect=403)
        r = self.call("patch", f"groups/{gid}/", owner, {"name": "Saturday ballers", "type": "team"}, 200)
        self.assertEqual((r.data["name"], r.data["type"]), ("Saturday ballers", "play_group"))
        self.call("patch", f"groups/{gid}/", owner, {"name": ""}, 400)
        self.call("patch", f"groups/{gid}/", owner, {"sport": None}, 200)
        chat = Chat.objects.get(group_id=gid)
        self.call("delete", f"groups/{gid}/", owner, expect=204)
        self.assertFalse(Group.objects.filter(pk=gid).exists())
        self.assertFalse(GroupMember.objects.filter(group_id=gid).exists())
        chat.refresh_from_db()  # the chat is kept, detached and empty
        self.assertIsNone(chat.group)
        self.assertEqual(chat.members.count(), 0)
        self.call("get", f"groups/{gid}/", owner, expect=404)
        self.call("delete", f"groups/{gid}/", owner, expect=404)


class MyGroupsTests(TeamsBase):
    def test_my_groups(self):
        """TEAM-32: my groups with my status, the status filter, sorting, and groups I left or never joined are absent."""
        me, owner, other = self.user("me"), self.user("owner"), self.user("other")
        for u in (me, other):
            self.befriend(owner, u)
        make = lambda name, user=owner: self.call("post", "groups/", user, {"name": name, "type": "play_group"}, 201).data["id"]
        active, invited, requested, left, never = make("Bravo"), make("Alpha"), make("Delta"), make("Charlie"), make("Echo")
        self.call("post", f"groups/{active}/members/", owner, {"user": me.id}, 201)
        self.call("post", f"groups/{active}/accept/", me, expect=200)
        self.call("post", f"groups/{invited}/members/", owner, {"user": me.id}, 201)
        self.call("post", f"groups/{requested}/join/", me, expect=201)
        self.call("post", f"groups/{left}/members/", owner, {"user": me.id}, 201)
        self.call("post", f"groups/{left}/accept/", me, expect=200)
        self.call("delete", f"groups/{left}/members/{me.id}/", me, expect=204)
        mine = self.call("post", "groups/", me, {"name": "Aardvark", "type": "play_group"}, 201).data["id"]

        r = self.call("get", "me/groups/", me, expect=200)
        self.assertEqual([(g["name"], g["my_status"]) for g in r.data["results"]],
                         [("Aardvark", "active"), ("Alpha", "invited"), ("Bravo", "active"), ("Delta", "requested")])
        self.assertEqual(r.data["results"][2]["member_count"], 2)  # the summary of TEAM-21
        self.assertEqual(r.data["results"][2]["owner"]["id"], owner.id)
        for status, names in (("active", ["Aardvark", "Bravo"]), ("invited", ["Alpha"]), ("requested", ["Delta"])):
            r = self.call("get", f"me/groups/?status={status}", me, expect=200)
            self.assertEqual([g["name"] for g in r.data["results"]], names)
        self.call("get", "me/groups/?status=banned", me, expect=400)
        self.assertEqual(self.call("get", "me/groups/", other, expect=200).data["count"], 0)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/me/groups/").status_code, 401)
        self.assertIn(mine, [g["id"] for g in self.call("get", "me/groups/", me).data["results"]])


class TeamTests(TeamsBase):
    def test_team_journey(self):
        """TEAM-20, TEAM-27, TEAM-28, TEAM-29, ACC-10, ACC-12: coach-only creation, shadow players, handing the team over."""
        coach, other_coach, player, plain = (self.user(n, **kw) for n, kw in (
            ("coach", {"is_coach": True}), ("rival", {"is_coach": True}), ("player", {}), ("plain", {})))
        kid = User.objects.create_user(email=None, full_name="Kid", managed_by=coach)
        rivals_kid = User.objects.create_user(email=None, full_name="Rival kid", managed_by=other_coach)

        # TEAM-20: a non-coach cannot create a team and nothing is written
        r = self.call("post", "groups/", player, {"name": "Tigers", "type": "team"}, 400)
        self.assertEqual(r.data["code"], "not_a_coach")
        self.assertFalse(Group.objects.exists())
        r = self.call("post", "groups/", coach, {"name": "Tigers", "type": "team"}, 201)
        gid = r.data["id"]
        self.assertEqual((r.data["coach"]["id"], r.data["owner"]["id"]), (coach.id, coach.id))
        self.assertEqual(self.chat_members(gid), {"Coach"})

        # TEAM-27: own shadow player is active at once, with no chat member; repeat is 200
        r = self.call("post", f"groups/{gid}/shadow-players/", coach, {"player": kid.id}, 201)
        self.assertEqual((r.data["status"], r.data["user"]["id"]), ("active", kid.id))
        self.call("post", f"groups/{gid}/shadow-players/", coach, {"player": kid.id}, 200)
        self.assertEqual(self.chat_members(gid), {"Coach"})
        # another coach's shadow player, a normal user, and a non-manager
        r = self.call("post", f"groups/{gid}/shadow-players/", coach, {"player": rivals_kid.id}, 400)
        self.assertEqual(r.data["code"], "not_your_player")
        self.call("post", f"groups/{gid}/shadow-players/", coach, {"player": player.id}, 400)
        self.call("post", f"groups/{gid}/shadow-players/", player, {"player": kid.id}, 403)
        self.assertFalse(GroupMember.objects.filter(user=rivals_kid).exists())

        # ACC-12: a shadow player cannot join a play group, and cannot be invited
        pg = self.call("post", "groups/", player, {"name": "Park", "type": "play_group"}, 201).data["id"]
        r = self.call("post", f"groups/{pg}/shadow-players/", player, {"player": kid.id}, 400)
        self.assertEqual(r.data["code"], "not_a_team")
        self.call("post", f"groups/{pg}/members/", player, {"user": kid.id}, 400)
        own_pg = self.call("post", "groups/", coach, {"name": "Coach park", "type": "play_group"}, 201).data["id"]
        r = self.call("post", f"groups/{own_pg}/shadow-players/", coach, {"player": kid.id}, 400)
        self.assertEqual(r.data["code"], "not_a_team")
        self.assertFalse(GroupMember.objects.filter(group_id__in=[pg, own_pg], user=kid).exists())

        # a team takes invites from a manager without friendship (TEAM-22) and chat follows (TEAM-28)
        self.call("post", f"groups/{gid}/members/", coach, {"user": player.id}, 201)
        self.call("post", f"groups/{gid}/accept/", player, expect=200)
        self.assertEqual(self.chat_members(gid), {"Coach", "Player"})

        # TEAM-29: only the owner changes the coach; the target must be a coach
        self.call("post", f"groups/{gid}/coach/", player, {"coach": other_coach.id}, 403)
        r = self.call("post", f"groups/{gid}/coach/", coach, {"coach": plain.id}, 400)
        self.assertEqual(r.data["code"], "not_a_coach")
        self.call("post", f"groups/{gid}/coach/", coach, {"coach": kid.id}, 400)  # shadow: Not found (GEN-18)
        self.assertEqual(Group.objects.get(pk=gid).coach, coach)
        r = self.call("post", f"groups/{gid}/coach/", coach, {"coach": other_coach.id}, 200)
        self.assertEqual((r.data["coach"]["id"], r.data["owner"]["id"]), (other_coach.id, coach.id))
        self.assertEqual(GroupMember.objects.get(group_id=gid, user=other_coach).status, "active")
        self.assertEqual(self.chat_members(gid), {"Coach", "Player", "Rival"})  # the previous coach stays
        self.assertEqual(GroupMember.objects.get(group_id=gid, user=coach).status, "active")
        # the new coach is now a manager: may invite and add their shadow players; the old one keeps the owner's rights
        self.call("post", f"groups/{gid}/shadow-players/", other_coach, {"player": rivals_kid.id}, 201)
        self.call("post", f"groups/{gid}/members/", other_coach, {"user": plain.id}, 201)
        self.call("delete", f"groups/{gid}/members/{plain.id}/", other_coach, expect=204)
        r = self.call("delete", f"groups/{gid}/members/{coach.id}/", other_coach, expect=400)  # never the owner's row
        self.assertEqual(r.data["code"], "owner_cannot_leave")
        # same coach again: nothing changes
        self.call("post", f"groups/{gid}/coach/", coach, {"coach": other_coach.id}, 200)

        # a play group has no coach to change
        r = self.call("post", f"groups/{own_pg}/coach/", coach, {"coach": other_coach.id}, 400)
        self.assertEqual(r.data["code"], "not_a_team")

    def test_visibility_and_blocks(self):
        """TEAM-21, TEAM-22, TEAM-24, TEAM-4, GEN-3, GEN-5: who sees what, and blocked pairs."""
        owner, member, outsider, blocked_by_owner, blocked_friend = (
            self.user(n) for n in ("owner", "member", "outsider", "blocked", "bfriend"))
        coach = self.user("coach", is_coach=True)
        self.befriend(owner, member)
        self.befriend(owner, blocked_friend)
        gid = self.call("post", "groups/", owner, {"name": "Locals", "type": "play_group"}, 201).data["id"]
        self.call("post", f"groups/{gid}/members/", owner, {"user": member.id}, 201)
        self.call("post", f"groups/{gid}/accept/", member, expect=200)

        # TEAM-21: the summary is open to anyone; the list only to active members and managers
        r = self.call("get", f"groups/{gid}/", outsider, expect=200)
        self.assertEqual(set(r.data), {"id", "name", "type", "sport", "owner", "coach", "member_count"})
        self.call("get", f"groups/{gid}/members/", outsider, expect=404)
        self.call("get", "groups/9999/", outsider, expect=404)
        self.call("get", f"groups/{gid}/members/", member, expect=200)
        # an invited (not yet active) user does not see the list either
        self.call("post", f"groups/{gid}/members/", owner, {"user": blocked_friend.id}, 201)
        self.call("get", f"groups/{gid}/members/", blocked_friend, expect=404)

        # TEAM-22: a blocked pair cannot be invited (either direction), even if they were friends
        self.block(blocked_friend, owner)
        GroupMember.objects.filter(user=blocked_friend).delete()
        r = self.call("post", f"groups/{gid}/members/", owner, {"user": blocked_friend.id}, 400)
        self.assertEqual(r.data["code"], "cannot_invite")
        # TEAM-24: a user blocked by the owner or by the coach cannot ask to join
        self.block(owner, blocked_by_owner)
        r = self.call("post", f"groups/{gid}/join/", blocked_by_owner, expect=400)
        self.assertEqual(r.data["code"], "cannot_join")
        r = self.call("post", f"groups/{gid}/join/", blocked_friend, expect=400)
        self.assertEqual(r.data["code"], "cannot_join")
        team = self.call("post", "groups/", coach, {"name": "Tigers", "type": "team"}, 201).data["id"]
        self.block(coach, outsider)
        self.call("post", f"groups/{team}/join/", outsider, expect=400)
        self.assertFalse(GroupMember.objects.filter(user__in=[blocked_by_owner, outsider]).exists())

        # GEN-5: asking again as an active member, and an invitee asking, are 200s (TEAM-24)
        self.call("post", f"groups/{gid}/join/", member, expect=200)
        self.befriend(owner, outsider)
        self.call("post", f"groups/{gid}/members/", owner, {"user": outsider.id}, 201)
        self.call("post", f"groups/{gid}/join/", outsider, expect=200)  # invited -> active
        self.assertEqual(GroupMember.objects.get(group_id=gid, user=outsider).status, "active")
        self.assertIn("Outsider", self.chat_members(gid))
        self.call("post", f"groups/{gid}/members/", owner, {"user": outsider.id}, 200)  # already active: unchanged


class FindingPeopleTests(TeamsBase):
    def test_search_profile_and_coaches(self):
        """ACC-20, ACC-21, ACC-22, ACC-23, ACC-2, ACC-12: user search, public profile, coach search."""
        me = self.user("me")
        anna = self.user("anna")
        anna.full_name = "Anna Banana"
        anna.phone, anna.weight_kg = "555-0100", "61.5"
        anna.save()
        hanna = self.user("hanna")
        hanna.full_name = "Hanna Montana"
        hanna.save()
        hidden = self.user("hidden")
        hidden.full_name = "Anna Hidden"
        hidden.save()
        gone = self.user("gone", is_active=False)
        gone.full_name = "Anna Gone"
        gone.save()
        shadow = User.objects.create_user(email=None, full_name="Anna Shadow", managed_by=anna)
        self.block(hidden, me)  # blocked either way: hidden from me
        blocker = self.user("blocker")
        blocker.full_name = "Anna Blocker"
        blocker.save()
        self.block(me, blocker)

        def names(path, user=me, expect=200):
            r = self.call("get", path, user, expect=expect)
            return [u["full_name"] for u in r.data["results"]] if expect == 200 else r

        # ACC-20: name contains (case-insensitive), exact email, at least 2 characters
        self.assertEqual(names("users/?q=ann"), ["Anna Banana", "Hanna Montana"])  # no shadow, inactive, blocked
        self.assertEqual(names("users/?q=ANNA B"), ["Anna Banana"])
        self.assertEqual(names("users/?q=Hanna@Example.com"), ["Hanna Montana"])
        self.assertEqual(names("users/?q=hanna@example"), [])  # email must match exactly
        for bad in ("users/", "users/?q=a", "users/?q="):
            self.assertIn("q", self.call("get", bad, me, expect=400).data)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/users/?q=ann").status_code, 401)

        # ACC-21: the public profile. A player has no coach fields; nothing private ever shows.
        r = self.call("get", f"users/{anna.id}/", me, expect=200)
        self.assertEqual(r.data, {"id": anna.id, "full_name": "Anna Banana", "avatar": "", "is_coach": False})

        coach = self.user("coach", is_coach=True, coach_bio="Ex-pro", coach_rate="25.500", coach_currency="USD")
        coach.full_name = "Carl Coach"
        coach.phone = "555-0199"
        coach.save()
        other = self.user("zed", is_coach=True)
        other.full_name = "Zed Coach"
        other.save()
        beirut = Club.objects.create(owner=me, name="Beirut Hoops", timezone="Asia/Beirut", currency="USD")
        saida = Club.objects.create(owner=me, name="Saida Arena", timezone="Asia/Beirut", currency="USD")
        lapsed = Club.objects.create(owner=me, name="Lapsed", timezone="Asia/Beirut", currency="USD")
        pending = Club.objects.create(owner=me, name="Pending", timezone="Asia/Beirut", currency="USD")
        staff_only = Club.objects.create(owner=me, name="Staff only", timezone="Asia/Beirut", currency="USD")
        yesterday = dt.date.today() - dt.timedelta(days=2)
        for club, role, st, expires in (
            (saida, "coach", "active", None), (beirut, "coach", "active", dt.date.today() + dt.timedelta(days=30)),
            (lapsed, "coach", "active", yesterday), (pending, "coach", "pending", None),
            (staff_only, "staff", "active", None),
        ):
            ClubMember.objects.create(club=club, user=coach, role=role, status=st, expires_on=expires)
        ClubMember.objects.create(club=saida, user=other, role="coach", status="active")
        for club in (beirut, saida, lapsed):  # public clubs need an active court (CLUB-30)
            Court.objects.create(club=club, name="C1", slot_minutes=60, is_active=True)

        r = self.call("get", f"users/{coach.id}/", me, expect=200)
        self.assertEqual(r.data, {
            "id": coach.id, "full_name": "Carl Coach", "avatar": "", "is_coach": True, "coach_bio": "Ex-pro",
            "coach_rate": "25.500", "coach_currency": "USD",
            "clubs": [{"id": beirut.id, "name": "Beirut Hoops"}, {"id": saida.id, "name": "Saida Arena"}],  # ACC-2
        })
        self.assertNotIn("email", r.data)
        # search results use the same shape
        r = self.call("get", "users/?q=carl", me, expect=200)
        self.assertEqual(r.data["results"][0]["coach_rate"], "25.500")

        # ACC-23: shadow, inactive, blocked either way, and unknown ids are 404; oneself is fine
        for uid in (shadow.id, gone.id, hidden.id, blocker.id, 99999):
            self.call("get", f"users/{uid}/", me, expect=404)
        self.call("get", f"users/{me.id}/", me, expect=200)

        # ACC-22: coaches only, sorted by name, with q and club filters
        self.assertEqual(names("coaches/"), ["Carl Coach", "Zed Coach"])
        self.assertEqual(names("coaches/?q=zed"), ["Zed Coach"])
        self.assertEqual(names(f"coaches/?club={saida.id}"), ["Carl Coach", "Zed Coach"])
        self.assertEqual(names(f"coaches/?club={beirut.id}&q=carl"), ["Carl Coach"])
        self.assertEqual(names(f"coaches/?club={lapsed.id}"), [])  # expired affiliation (ACC-2)
        self.assertEqual(names(f"coaches/?club={pending.id}"), [])  # not approved yet
        self.assertEqual(names(f"coaches/?club={staff_only.id}"), [])
        self.assertEqual(names("coaches/?club=9999"), [])
        self.call("get", "coaches/?club=x", me, expect=400)
        self.block(other, me)
        self.assertEqual(names("coaches/"), ["Carl Coach"])  # blocked pair: not found
        self.call("get", f"users/{other.id}/", me, expect=404)


class CoachsPlayersTests(TeamsBase):
    def test_coachs_players(self):
        """ACC-1: coach's players are accepted coaching links, active team members and own shadow players."""
        coach = self.user("coach", is_coach=True)
        other_coach = self.user("rival", is_coach=True)
        linked, pending_link, member, invited, requested, ex_member, rival_player, stranger = (
            self.user(n) for n in ("linked", "pending", "member", "invited", "requested", "ex", "rivalp", "stranger"))
        coach2 = self.user("coach2", is_coach=True)
        kid = User.objects.create_user(email=None, full_name="Kid", managed_by=coach)
        User.objects.create_user(email=None, full_name="Rival kid", managed_by=other_coach)

        Connection.objects.create(user=coach, other_user=linked, type=COACHING, status="accepted")
        Connection.objects.create(user=coach, other_user=pending_link, type=COACHING, status="pending")
        Connection.objects.create(user=other_coach, other_user=rival_player, type=COACHING, status="accepted")
        Connection.objects.create(user=linked, other_user=coach, type=COACHING, status="accepted")  # coach as the player

        team = self.call("post", "groups/", coach, {"name": "Tigers", "type": "team"}, 201).data["id"]
        for who, status in ((member, "active"), (invited, "invited"), (requested, "requested")):
            GroupMember.objects.create(group_id=team, user=who, status=status)
        # a team coached by someone else, with the same coach as a second manager
        shared = Group.objects.create(type="team", name="Shared", owner=coach2, coach=coach)
        GroupMember.objects.create(group=shared, user=stranger, status="active")
        # a play group's members are not the coach's players
        pg = Group.objects.create(type="play_group", name="Park", owner=coach)
        GroupMember.objects.create(group=pg, user=ex_member, status="active")
        # the member of a team coached by another coach is not either
        theirs = Group.objects.create(type="team", name="Theirs", owner=other_coach, coach=other_coach)
        GroupMember.objects.create(group=theirs, user=rival_player, status="active")

        got = set(services.coachs_players(coach).values_list("pk", flat=True))
        self.assertEqual(got, {linked.pk, member.pk, kid.pk, stranger.pk})
        self.assertEqual(services.coachs_players(coach).count(), 4)  # each once even with two reasons
        self.assertEqual([u.pk for u in services.group_managers(Group.objects.get(pk=shared.pk))], [coach2.pk, coach.pk])
        self.assertEqual([u.pk for u in services.group_managers(pg)], [coach.pk])
        self.assertTrue(services.is_group_manager(coach, shared))
        self.assertFalse(services.is_group_manager(other_coach, pg))

        # leaving the team drops the player again
        self.call("delete", f"groups/{team}/members/{member.id}/", member, expect=204)
        self.assertNotIn(member.pk, services.coachs_players(coach).values_list("pk", flat=True))

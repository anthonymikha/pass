import datetime
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.db import transaction
from django.test import SimpleTestCase
from rest_framework import exceptions, serializers
from rest_framework.settings import api_settings
from rest_framework.test import APITestCase

from config.api import BusinessError, VisibleRelatedField, exception_handler
from config.money import minor_units, round_money, validate_currency, validate_typed_money

from . import services
from .models import Connection, Device, User, UserBlockout
from .serializers import BlockoutSerializer

PASSWORD = "court-side-42"


class AccountsApiTests(APITestCase):
    def setUp(self):
        cache.clear()  # throttle counters live in the cache

    def post(self, path, data=None):
        return self.client.post(f"/api/{path}", data or {}, format="json")

    def test_register_login_profile_logout(self):
        r = self.post("auth/register/", {"email": "Player@Example.com", "password": PASSWORD, "full_name": "Pat"})
        self.assertEqual(r.status_code, 201, r.data)
        token = r.data["token"]
        self.assertEqual(r.data["user"]["email"], "player@example.com")
        self.assertNotIn("password", r.data["user"])

        # same email in another case is the same account
        r = self.post("auth/register/", {"email": "PLAYER@example.com", "password": PASSWORD, "full_name": "Pat"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.data)

        r = self.post("auth/login/", {"email": "PLAYER@example.com", "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["token"], token)

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.client.get("/api/me/").data["full_name"], "Pat")

        r = self.client.patch("/api/me/", {
            "is_coach": True, "coach_rate": "25.500", "coach_currency": "USD",
            "timezone": "Asia/Beirut", "email": "someone-else@example.com",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["is_coach"])
        self.assertEqual(r.data["timezone"], "Asia/Beirut")
        self.assertEqual(r.data["email"], "player@example.com")  # email is read-only here

        for bad in ({"timezone": "Mars/Phobos"}, {"coach_currency": "usd"}, {"coach_rate": "-1"},
                    {"nationality": "lebanon"}, {"coach_rate": "25.555"}, {"coach_rate": "1.5", "coach_currency": "LBP"}, {"date_of_birth": "2999-01-01"}, {"sex": "x"}, {"height_cm": "5"}):
            self.assertEqual(self.client.patch("/api/me/", bad, format="json").status_code, 400, bad)
        self.assertEqual(self.client.put("/api/me/", {}, format="json").status_code, 405)

        self.assertEqual(self.post("auth/logout/").status_code, 204)
        self.assertEqual(self.client.get("/api/me/").status_code, 401)  # old token is dead

    def test_rejections(self):
        r = self.post("auth/register/", {"email": "a@example.com", "password": "12345678", "full_name": "A"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", r.data)
        self.assertFalse(User.objects.exists())

        User.objects.create_user("a@example.com", PASSWORD)
        self.assertEqual(self.post("auth/login/", {"email": "a@example.com", "password": "wrong"}).status_code, 400)

        inactive = User.objects.create_user("gone@example.com", PASSWORD, is_active=False)
        self.assertEqual(self.post("auth/login/", {"email": inactive.email, "password": PASSWORD}).status_code, 400)

        self.assertEqual(self.client.get("/api/me/").status_code, 401)
        self.assertEqual(self.post("auth/logout/").status_code, 401)

    def test_shadow_players_have_no_login(self):
        coach = User.objects.create_user("coach@example.com", PASSWORD, is_coach=True)
        kid = User.objects.create_user(email="", full_name="Kid", managed_by=coach)
        User.objects.create_user(email="", full_name="Kid 2", managed_by=coach)  # blank emails don't collide
        self.assertIsNone(kid.email)
        self.assertFalse(kid.has_usable_password())
        self.assertEqual(self.post("auth/login/", {"email": "", "password": ""}).status_code, 400)

    def test_login_is_throttled(self):
        attempt = {"email": "a@example.com", "password": "wrong"}
        for _ in range(10):
            self.assertEqual(self.post("auth/login/", attempt).status_code, 400)
        self.assertEqual(self.post("auth/login/", attempt).status_code, 429)


class DeviceTests(APITestCase):
    def setUp(self):
        services.outbox.clear()
        self.pat = User.objects.create_user("pat@example.com", PASSWORD, full_name="Pat")
        self.sam = User.objects.create_user("sam@example.com", PASSWORD, full_name="Sam")

    def as_user(self, user):
        self.client.force_authenticate(user)

    def register(self, token="tok-1", platform="android"):
        return self.client.post("/api/devices/", {"token": token, "platform": platform}, format="json")

    def test_device_journey(self):
        """NOTE-1, NOTE-2, NOTE-3, GEN-5: register, repeat, move to another user, unregister, logout."""
        self.as_user(self.pat)
        r = self.register()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["token"], r.data["platform"]), ("tok-1", "android"))
        r = self.register()  # repeat: same status as "already holds", one row
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Device.objects.count(), 1)

        self.assertEqual(self.register(platform="symbian").status_code, 400)
        self.assertEqual(self.client.post("/api/devices/", {}, format="json").status_code, 400)

        self.as_user(self.sam)  # shared phone: the token moves
        self.assertEqual(self.register().status_code, 200)
        self.assertEqual(Device.objects.get().user, self.sam)

        self.as_user(self.pat)  # Pat can no longer touch it (GEN-3: 404, not 403)
        self.assertEqual(self.client.delete("/api/devices/tok-1/").status_code, 404)
        self.assertEqual(Device.objects.count(), 1)
        self.register("tok-2", "ios")
        own_id = Device.objects.get(token="tok-2").id
        self.assertEqual(self.client.delete(f"/api/devices/{own_id}/").status_code, 204)  # by id
        self.register("tok-2", "ios")
        self.assertEqual(self.client.delete("/api/devices/tok-2/").status_code, 204)  # by token
        self.assertEqual(self.client.delete("/api/devices/tok-2/").status_code, 404)

        self.register("tok-3", "web")
        self.register("tok-4", "web")
        self.as_user(self.sam)
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 204)  # NOTE-3
        self.assertEqual(Device.objects.filter(user=self.sam).count(), 0)
        self.assertEqual(Device.objects.filter(user=self.pat).count(), 2)  # others keep theirs

        self.client.force_authenticate(None)
        self.assertEqual(self.register().status_code, 401)

    def test_notify_goes_out_only_after_commit(self):
        """NOTE-13, NOTE-14, NOTE-11: one push per device, after commit, with type and id in data."""
        Device.objects.create(user=self.pat, token="a", platform="ios")
        Device.objects.create(user=self.pat, token="b", platform="android")
        Device.objects.create(user=self.sam, token="c", platform="web")
        gone = User.objects.create_user("gone@example.com", PASSWORD, is_active=False)
        Device.objects.create(user=gone, token="d", platform="web")

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            services.notify([self.pat, gone], "friend_request", "Hi", "Sam wants to play", {"id": 7})
        self.assertEqual(services.outbox, [])  # nothing before commit
        for callback in callbacks:
            callback()
        self.assertEqual(sorted(p["token"] for p in services.outbox), ["a", "b"])  # not Sam's, not the inactive user's
        push = services.outbox[0]
        self.assertEqual((push["title"], push["body"]), ("Hi", "Sam wants to play"))
        self.assertEqual(push["data"], {"type": "friend_request", "id": "7"})

    def test_notify_rolled_back_sends_nothing_and_failures_do_not_raise(self):
        """NOTE-13: a rollback sends nothing; a failing sender is logged, never raised."""
        Device.objects.create(user=self.pat, token="a", platform="ios")
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    services.notify([self.pat], "friend_request", "Hi", "x", {"id": 1})
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
        self.assertEqual(services.outbox, [])

        with mock.patch("accounts.services.send_push", side_effect=RuntimeError("fcm down")):
            with self.assertLogs("accounts.services", "ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    services.notify([self.pat], "friend_request", "Hi", "x", {"id": 1})

    def test_schema_is_public(self):
        """The OpenAPI schema is served without signing in."""
        self.assertEqual(self.client.get("/api/schema/").status_code, 200)


class PeopleTestCase(APITestCase):
    """Shared helpers for the friends, blocking, coaching, block-out and shadow-player journeys."""

    def setUp(self):
        services.outbox.clear()

    def user(self, name, **fields):
        user = User.objects.create_user(f"{name}@example.com", PASSWORD, full_name=name.title(), **fields)
        self.client.force_authenticate(user)
        self.client.post("/api/devices/", {"token": f"tok-{name}", "platform": "android"}, format="json")  # a pushable phone
        return user

    def call(self, user, method, path, data=None):
        """One request as `user`, with after-commit pushes run (they land in services.outbox)."""
        self.client.force_authenticate(user)
        with self.captureOnCommitCallbacks(execute=True):
            return getattr(self.client, method)(f"/api/{path}", data, format="json")

    def ids(self, user, path):
        r = self.call(user, "get", path)
        self.assertEqual(r.status_code, 200, r.data)
        return [row["id"] for row in r.data["results"]]


class FriendTests(PeopleTestCase):
    def test_request_accept_and_lists(self):
        """TEAM-1 steps 2 to 5, TEAM-2, TEAM-6, GEN-5, NOTE-20 friend_request: request, repeat, accept, lists."""
        ann, bob = self.user("ann"), self.user("bob")
        r = self.call(ann, "post", "friends/", {"user": bob.id})
        self.assertEqual((r.status_code, r.data["status"], r.data["id"]), (201, "pending", bob.id))
        row = Connection.objects.get()
        self.assertEqual((row.user, row.other_user, row.type, row.status), (ann, bob, "friend", "pending"))
        self.assertEqual(len(services.outbox), 1)  # push to Bob only
        push = services.outbox[0]
        self.assertEqual((push["user_id"], push["data"]), (bob.id, {"type": "friend_request", "id": str(row.id)}))

        r = self.call(ann, "post", "friends/", {"user": bob.id})  # step 3: repeat
        self.assertEqual((r.status_code, r.data["status"]), (200, "pending"))
        self.assertEqual((Connection.objects.count(), len(services.outbox)), (1, 1))  # no change, no second push

        self.assertEqual(self.ids(bob, "friends/incoming/"), [ann.id])  # TEAM-6
        self.assertEqual(self.ids(ann, "friends/outgoing/"), [bob.id])
        self.assertEqual(self.ids(ann, "friends/incoming/"), [])
        self.assertEqual(self.ids(ann, "friends/"), [])  # pending is not a friendship yet

        self.assertEqual(self.call(ann, "post", f"friends/{bob.id}/accept/").status_code, 404)  # only the other user accepts
        self.assertEqual(self.call(bob, "post", "friends/999/accept/").status_code, 404)
        r = self.call(bob, "post", f"friends/{ann.id}/accept/")
        self.assertEqual((r.status_code, r.data["status"]), (200, "accepted"))
        self.assertEqual(self.call(bob, "post", f"friends/{ann.id}/accept/").status_code, 200)  # GEN-5
        self.assertEqual(Connection.objects.get().status, "accepted")

        for who, friend in ((ann, bob), (bob, ann)):
            self.assertEqual(self.ids(who, "friends/"), [friend.id])
            self.assertEqual(self.ids(who, "friends/incoming/") + self.ids(who, "friends/outgoing/"), [])
        self.assertEqual(list(services.friends_of(ann)), [bob])  # ACC-1 helper
        self.assertEqual(self.call(ann, "post", "friends/", {"user": bob.id}).status_code, 200)  # step 2
        self.assertEqual(self.call(bob, "post", "friends/", {"user": ann.id}).status_code, 200)  # either direction
        self.assertEqual((Connection.objects.count(), len(services.outbox)), (1, 1))

    def test_crossing_request_decline_cancel_unfriend(self):
        """TEAM-1 step 4, TEAM-3, TEAM-7, TEAM-6: crossing requests, decline, cancel, unfriend, double rows."""
        ann, bob, cy, di, ed = (self.user(n) for n in ("ann", "bob", "cy", "di", "ed"))
        self.call(ann, "post", "friends/", {"user": bob.id})
        services.outbox.clear()
        r = self.call(bob, "post", "friends/", {"user": ann.id})  # Bob asks back: this is an acceptance
        self.assertEqual((r.status_code, r.data["status"]), (200, "accepted"))
        self.assertEqual((Connection.objects.get().status, services.outbox), ("accepted", []))
        self.assertEqual(self.ids(ann, "friends/"), [bob.id])

        self.assertEqual(self.call(bob, "delete", f"friends/{ann.id}/").status_code, 204)  # unfriend (either side)
        self.assertEqual(self.call(bob, "delete", f"friends/{ann.id}/").status_code, 404)
        self.assertFalse(Connection.objects.exists())

        self.call(ann, "post", "friends/", {"user": cy.id})  # decline by the other user
        self.assertEqual(self.call(cy, "delete", f"friends/{ann.id}/").status_code, 204)
        self.assertEqual(self.ids(cy, "friends/incoming/"), [])

        self.call(ann, "post", "friends/", {"user": di.id})  # cancel by the requester
        self.assertEqual(self.call(ann, "delete", f"friends/{di.id}/").status_code, 204)
        self.assertEqual(self.ids(di, "friends/incoming/"), [])
        self.assertEqual(self.call(ann, "delete", f"friends/{ed.id}/").status_code, 404)  # strangers: nothing to end

        # TEAM-7: a true race left two pending rows; accepting either makes friends, listed once
        Connection.objects.create(user=ann, other_user=ed, type="friend")
        Connection.objects.create(user=ed, other_user=ann, type="friend")
        self.assertEqual(self.call(ed, "post", f"friends/{ann.id}/accept/").status_code, 200)
        self.assertEqual(self.ids(ann, "friends/"), [ed.id])
        self.assertEqual(self.ids(ed, "friends/"), [ann.id])
        self.assertEqual(self.ids(ann, "friends/incoming/") + self.ids(ann, "friends/outgoing/"), [])
        self.assertEqual(self.call(ann, "delete", f"friends/{ed.id}/").status_code, 204)
        self.assertFalse(Connection.objects.exists())

    def test_requests_that_are_refused(self):
        """TEAM-1, ACC-12, GEN-18: self, shadow player, inactive and missing users; the lists need a login."""
        ann = self.user("ann")
        coach = self.user("coach", is_coach=True)
        shadow = User.objects.create_user(email=None, full_name="Kid", managed_by=coach)
        inactive = User.objects.create_user("gone@example.com", PASSWORD, is_active=False)

        r = self.call(ann, "post", "friends/", {"user": ann.id})
        self.assertEqual((r.status_code, r.data["code"]), (400, "cannot_connect"))
        for target in (shadow.id, inactive.id, 99999):
            r = self.call(ann, "post", "friends/", {"user": target})
            self.assertEqual((r.status_code, r.data), (400, {"user": ["Not found."]}))
        self.assertEqual(self.call(ann, "post", "friends/", {}).status_code, 400)
        self.assertFalse(Connection.objects.exists())
        self.assertTrue(services.is_shadow_player(shadow))
        self.assertFalse(services.is_shadow_player(ann))

        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/friends/").status_code, 401)


class BlockTests(PeopleTestCase):
    def test_block_journey(self):
        """TEAM-4, TEAM-5, TEAM-6, ACC-1, GEN-5: block ends friendship and coaching, both ways refused, only the blocker lifts it."""
        ann, bob = self.user("ann"), self.user("bob", is_coach=True)
        self.call(ann, "post", "friends/", {"user": bob.id})
        self.call(bob, "post", f"friends/{ann.id}/accept/")
        self.call(ann, "post", "coaching/", {"coach": bob.id})
        self.assertEqual(Connection.objects.count(), 2)

        r = self.call(ann, "post", "blocks/", {"user": bob.id})
        self.assertEqual((r.status_code, r.data["status"]), (201, "blocked"))
        row = Connection.objects.get()  # friend and coaching rows are gone, one blocked row remains
        self.assertEqual((row.user, row.other_user, row.type, row.status), (ann, bob, "friend", "blocked"))
        self.assertEqual(self.call(ann, "post", "blocks/", {"user": bob.id}).status_code, 200)  # GEN-5
        self.assertEqual(Connection.objects.count(), 1)
        self.assertTrue(services.is_blocked_pair(ann, bob) and services.is_blocked_pair(bob, ann))

        self.assertEqual(self.ids(ann, "blocks/"), [bob.id])  # TEAM-6
        self.assertEqual(self.ids(bob, "blocks/"), [])  # Bob never sees who blocked him
        for lst in ("friends/", "friends/incoming/", "friends/outgoing/", "coaching/"):
            self.assertEqual((self.ids(ann, lst), self.ids(bob, lst)), ([], []))

        for who, other in ((ann, bob), (bob, ann)):  # blocked both ways
            r = self.call(who, "post", "friends/", {"user": other.id})
            self.assertEqual((r.status_code, r.data["code"]), (400, "cannot_connect"))
        r = self.call(ann, "post", "coaching/", {"coach": bob.id})
        self.assertEqual((r.status_code, r.data["code"]), (400, "cannot_connect"))

        self.assertEqual(self.call(bob, "delete", f"blocks/{ann.id}/").status_code, 404)  # only the blocker unblocks
        self.assertTrue(services.is_blocked_pair(ann, bob))
        self.assertEqual(self.call(ann, "delete", f"blocks/{bob.id}/").status_code, 204)
        self.assertEqual(self.call(ann, "delete", f"blocks/{bob.id}/").status_code, 404)
        self.assertFalse(services.is_blocked_pair(ann, bob))
        self.assertEqual(self.call(bob, "post", "friends/", {"user": ann.id}).status_code, 201)  # allowed again

    def test_both_block_and_block_keeps_other_side(self):
        """TEAM-4, TEAM-5: blocking someone who blocked you keeps their row; lifting yours leaves the pair blocked. Self and shadow refused."""
        ann, bob = self.user("ann"), self.user("bob")
        shadow = User.objects.create_user(email=None, full_name="Kid", managed_by=bob)
        self.call(bob, "post", "blocks/", {"user": ann.id})
        r = self.call(ann, "post", "blocks/", {"user": bob.id})  # looks the same to Ann as any block
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Connection.objects.count(), 2)
        self.call(ann, "delete", f"blocks/{bob.id}/")
        self.assertTrue(services.is_blocked_pair(ann, bob))  # Bob's block still stands
        self.assertEqual(self.ids(bob, "blocks/"), [ann.id])

        self.assertEqual(self.call(ann, "post", "blocks/", {"user": ann.id}).data["code"], "cannot_connect")
        self.assertEqual(self.call(ann, "post", "blocks/", {"user": shadow.id}).status_code, 400)  # not visible (ACC-11)


class CoachingTests(PeopleTestCase):
    def test_coaching_journey(self):
        """TEAM-10, TEAM-11, TEAM-12, GEN-5, NOTE-20 coaching_request: request, repeat, accept, decline, end."""
        pat, coach = self.user("pat"), self.user("coach", is_coach=True)
        r = self.call(pat, "post", "coaching/", {"coach": coach.id})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["coach"]["id"], r.data["player"]["id"], r.data["status"]), (coach.id, pat.id, "pending"))
        row = Connection.objects.get()
        self.assertEqual((row.user, row.other_user, row.type, row.status), (coach, pat, "coaching", "pending"))  # user = coach
        self.assertEqual(len(services.outbox), 1)
        self.assertEqual((services.outbox[0]["user_id"], services.outbox[0]["data"]), (coach.id, {"type": "coaching_request", "id": str(row.id)}))

        self.assertEqual(self.call(pat, "post", "coaching/", {"coach": coach.id}).status_code, 200)  # repeat
        self.assertEqual((Connection.objects.count(), len(services.outbox)), (1, 1))
        for who in (pat, coach):  # the list shows the link to both sides
            self.assertEqual(self.ids(who, "coaching/"), [row.id])

        self.assertEqual(self.call(pat, "post", f"coaching/{row.id}/accept/").status_code, 403)  # only the coach accepts
        self.assertEqual(self.call(pat, "delete", f"coaching/{row.id}/").status_code, 403)  # the player cannot decline for the coach
        stranger = self.user("stranger")
        self.assertEqual(self.call(stranger, "post", f"coaching/{row.id}/accept/").status_code, 404)  # GEN-3
        self.assertEqual(self.call(stranger, "delete", f"coaching/{row.id}/").status_code, 404)

        r = self.call(coach, "post", f"coaching/{row.id}/accept/")
        self.assertEqual((r.status_code, r.data["status"]), (200, "accepted"))
        self.assertEqual(self.call(coach, "post", f"coaching/{row.id}/accept/").status_code, 200)  # GEN-5
        self.assertEqual(self.call(pat, "post", "coaching/", {"coach": coach.id}).status_code, 200)  # already accepted
        self.assertEqual(Connection.objects.get().status, "accepted")

        self.assertEqual(self.call(pat, "delete", f"coaching/{row.id}/").status_code, 204)  # the player ends it (TEAM-12)
        self.assertFalse(Connection.objects.exists())
        self.assertEqual(self.call(pat, "delete", f"coaching/{row.id}/").status_code, 404)

        self.call(pat, "post", "coaching/", {"coach": coach.id})  # asks again; the coach declines (TEAM-11)
        row = Connection.objects.get()
        self.assertEqual(self.call(coach, "delete", f"coaching/{row.id}/").status_code, 204)
        self.assertFalse(Connection.objects.exists())

        self.call(pat, "post", "coaching/", {"coach": coach.id})  # accepted, then the coach ends it
        row = Connection.objects.get()
        self.call(coach, "post", f"coaching/{row.id}/accept/")
        self.assertEqual(self.call(coach, "delete", f"coaching/{row.id}/").status_code, 204)
        self.assertFalse(Connection.objects.exists())

    def test_coaching_requests_that_are_refused(self):
        """TEAM-10, TEAM-13, ACC-12, GEN-18: non-coach target, self, shadow, inactive coach refused; a coach may ask another coach."""
        pat, coach = self.user("pat"), self.user("coach", is_coach=True)
        other_coach = self.user("other", is_coach=True)
        friend = self.user("friend")
        shadow = User.objects.create_user(email=None, full_name="Kid", managed_by=coach)
        idle = User.objects.create_user("idle@example.com", PASSWORD, is_coach=True, is_active=False)

        r = self.call(pat, "post", "coaching/", {"coach": friend.id})
        self.assertEqual((r.status_code, r.data["code"]), (400, "not_a_coach"))
        r = self.call(pat, "post", "coaching/", {"coach": pat.id})
        self.assertEqual((r.status_code, r.data["code"]), (400, "cannot_connect"))
        for target in (shadow.id, idle.id, 99999):
            r = self.call(pat, "post", "coaching/", {"coach": target})
            self.assertEqual((r.status_code, r.data), (400, {"coach": ["Not found."]}))
        self.assertEqual(self.call(pat, "post", "coaching/", {}).status_code, 400)

        self.assertFalse(Connection.objects.exists())
        self.assertEqual(services.outbox, [])

        # TEAM-13: a coach may still ask another coach as a player; the row always has the asked coach as `user`.
        r = self.call(coach, "post", "coaching/", {"coach": other_coach.id})
        self.assertEqual(r.status_code, 201)
        row = Connection.objects.get()
        self.assertEqual((row.user, row.other_user), (other_coach, coach))


class BlockoutTests(PeopleTestCase):
    def test_blockout_journey(self):
        """TEAM-15, ACC-4, CLUB-15, GEN-11, GEN-3: create each repeat kind, list, change, delete; others' are 404."""
        ann, bob = self.user("ann"), self.user("bob")
        base = {"starts_on": "2027-01-04", "start_time": "09:00", "end_time": "17:00"}
        made = {}
        for repeat, extra in (
            ("none", {}),
            ("daily", {"repeat_until": "2027-01-10", "reason": "School"}),
            ("weekly", {}),
            ("monthly", {"repeat_until": "2027-12-31"}),
        ):
            r = self.call(ann, "post", "me/blockouts/", {**base, "repeat": repeat, **extra})
            self.assertEqual(r.status_code, 201, r.data)
            self.assertEqual((r.data["repeat"], r.data["start_time"]), (repeat, "09:00:00"))
            made[repeat] = r.data["id"]
        self.assertEqual(self.call(ann, "post", "me/blockouts/", base).data["repeat"], "none")  # default
        self.assertEqual(self.call(ann, "post", "me/blockouts/", {**base, "end_time": "00:00"}).status_code, 201)  # GEN-11
        self.assertEqual(UserBlockout.objects.filter(user=ann).count(), 6)
        self.assertEqual(self.call(ann, "get", "me/blockouts/").data["count"], 6)
        self.assertEqual(self.call(bob, "get", "me/blockouts/").data["count"], 0)

        daily = f"me/blockouts/{made['daily']}/"
        r = self.call(ann, "patch", daily, {"end_time": "18:30", "reason": "Work"})
        self.assertEqual((r.status_code, r.data["end_time"], r.data["reason"]), (200, "18:30:00", "Work"))
        self.assertEqual(self.call(ann, "get", daily).data["end_time"], "18:30:00")
        self.assertEqual(self.call(ann, "put", daily, base).status_code, 405)

        for method, data in (("get", None), ("patch", {"reason": "x"}), ("delete", None)):  # another user's: 404
            self.assertEqual(self.call(bob, method, daily, data).status_code, 404, method)
        self.assertEqual(UserBlockout.objects.get(pk=made["daily"]).reason, "Work")

        self.assertEqual(self.call(ann, "delete", daily).status_code, 204)
        self.assertEqual(self.call(ann, "delete", daily).status_code, 404)
        self.assertEqual(UserBlockout.objects.filter(user=ann).count(), 5)

    def test_blockout_validation(self):
        """CLUB-15, GEN-11: field errors on create and on PATCH against the stored row."""
        ann = self.user("ann")
        base = {"starts_on": "2027-01-04", "start_time": "09:00", "end_time": "17:00"}
        cases = (
            ({**base, "end_time": "09:00"}, "end_time"),
            ({**base, "end_time": "08:00"}, "end_time"),
            ({**base, "repeat": "weekly", "repeat_until": "2027-01-03"}, "repeat_until"),
            ({**base, "repeat": "yearly"}, "repeat"),
            ({**base, "reason": "x" * 256}, "reason"),
            ({**base, "starts_on": "soon"}, "starts_on"),
            ({"start_time": "09:00", "end_time": "17:00"}, "starts_on"),
        )
        for body, field in cases:
            r = self.call(ann, "post", "me/blockouts/", body)
            self.assertEqual(r.status_code, 400, body)
            self.assertIn(field, r.data)
        self.assertFalse(UserBlockout.objects.exists())

        pk = self.call(ann, "post", "me/blockouts/", base).data["id"]
        r = self.call(ann, "patch", f"me/blockouts/{pk}/", {"start_time": "18:00"})  # after the stored end_time
        self.assertEqual((r.status_code, list(r.data)), (400, ["end_time"]))
        r = self.call(ann, "patch", f"me/blockouts/{pk}/", {"repeat_until": "2026-12-31"})  # before the stored starts_on
        self.assertEqual((r.status_code, list(r.data)), (400, ["repeat_until"]))
        self.assertEqual(self.call(ann, "patch", f"me/blockouts/{pk}/", {"end_time": "00:00"}).status_code, 200)

        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/me/blockouts/").status_code, 401)


class ShadowPlayerTests(PeopleTestCase):
    def test_shadow_player_journey(self):
        """ACC-10, ACC-11, ACC-12, ACC-13: create with defaults, edit, deactivate; others cannot see; no login, friend or coaching."""
        coach = self.user("coach", is_coach=True, timezone="Asia/Beirut")
        other = self.user("other", is_coach=True)
        pat = self.user("pat")

        r = self.call(coach, "post", "shadow-players/", {"full_name": "Little Sam"})  # only the name is required
        self.assertEqual(r.status_code, 201, r.data)
        sam = User.objects.get(pk=r.data["id"])
        self.assertIsNone(sam.email)
        self.assertFalse(sam.has_usable_password())
        self.assertEqual((sam.managed_by, sam.is_coach, sam.timezone, sam.is_active), (coach, False, "Asia/Beirut", True))
        self.assertTrue(services.is_shadow_player(sam))
        self.assertEqual((r.data["sex"], r.data["height_cm"], r.data["is_active"]), ("", None, True))
        self.assertNotIn("email", r.data)

        full = {
            "full_name": "Jo", "date_of_birth": "2015-05-01", "sex": "female", "dominant_hand": "left",
            "height_cm": "140.5", "weight_kg": "35.00", "nationality": "LB",
        }
        r = self.call(coach, "post", "shadow-players/", full)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual({k: r.data[k] for k in full}, full)
        jo = r.data["id"]
        self.assertEqual(User.objects.filter(email__isnull=True).count(), 2)  # blank emails never collide

        for bad in ({}, {"full_name": ""}, {"full_name": "x" * 256}, {"full_name": "A", "nationality": "lebanon"},
                    {"full_name": "A", "date_of_birth": "2999-01-01"}, {"full_name": "A", "sex": "x"},
                    {"full_name": "A", "height_cm": "5"}, {"full_name": "A", "dominant_hand": "feet"}):
            self.assertEqual(self.call(coach, "post", "shadow-players/", bad).status_code, 400, bad)
        r = self.call(coach, "post", "shadow-players/", {"full_name": "A", "managed_by": other.id, "is_coach": True, "email": "a@example.com"})
        self.assertEqual(r.status_code, 201)  # unknown fields are ignored: still ours, still no email
        stray = User.objects.get(pk=r.data["id"])
        self.assertEqual((stray.managed_by, stray.is_coach, stray.email), (coach, False, None))

        self.assertEqual(self.call(pat, "post", "shadow-players/", {"full_name": "Nope"}).status_code, 403)  # not a coach
        self.assertEqual(self.call(pat, "get", "shadow-players/").data["results"], [])

        self.assertEqual(self.call(coach, "get", "shadow-players/").data["count"], 3)
        r = self.call(coach, "patch", f"shadow-players/{jo}/", {"full_name": "Jo Jo", "weight_kg": "36.5"})
        self.assertEqual((r.status_code, r.data["full_name"], r.data["weight_kg"]), (200, "Jo Jo", "36.50"))
        self.assertEqual(self.call(coach, "patch", f"shadow-players/{jo}/", {"full_name": ""}).status_code, 400)
        self.assertEqual(self.call(coach, "patch", f"shadow-players/{jo}/", {"height_cm": "400"}).status_code, 400)

        for method, data in (("get", None), ("patch", {"full_name": "Mine now"})):  # another coach: 404, not 403
            self.assertEqual(self.call(other, method, f"shadow-players/{jo}/", data).status_code, 404)
        self.assertEqual(self.call(other, "get", "shadow-players/").data["results"], [])
        self.assertEqual(User.objects.get(pk=jo).full_name, "Jo Jo")

        r = self.call(coach, "patch", f"shadow-players/{jo}/", {"is_active": False})  # deactivate
        self.assertEqual((r.status_code, r.data["is_active"]), (200, False))
        self.assertFalse(User.objects.get(pk=jo).is_active)
        self.assertEqual(self.call(coach, "get", "shadow-players/").data["count"], 3)  # still listed

        # ACC-12: no login, never a friend, never a coaching target
        self.assertEqual(self.call(coach, "post", "auth/login/", {"email": "", "password": ""}).status_code, 400)
        for who in (pat, coach):
            r = self.call(who, "post", "friends/", {"user": sam.id})
            self.assertEqual((r.status_code, r.data), (400, {"user": ["Not found."]}))
        r = self.call(pat, "post", "coaching/", {"coach": sam.id})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Connection.objects.exists())


class ConventionTests(SimpleTestCase):
    def test_error_shapes(self):
        """GEN-1, GEN-2: business rules and 403 render as {detail, code}."""
        r = exception_handler(BusinessError("slot_taken", "Taken."), {})
        self.assertEqual((r.status_code, r.data), (400, {"detail": "Taken.", "code": "slot_taken"}))
        r = exception_handler(BusinessError("slot_taken", "Taken.", 409), {})
        self.assertEqual((r.status_code, r.data["code"]), (409, "slot_taken"))
        r = exception_handler(exceptions.PermissionDenied("Not yours."), {})
        self.assertEqual((r.status_code, r.data), (403, {"detail": "Not yours.", "code": "forbidden"}))
        r = exception_handler(exceptions.NotFound(), {})
        self.assertEqual(r.status_code, 404)

    def test_pagination_defaults(self):
        """GEN-12: page-number pagination, 50 per page."""
        self.assertEqual(api_settings.PAGE_SIZE, 50)
        self.assertEqual(api_settings.DEFAULT_PAGINATION_CLASS.__name__, "PageNumberPagination")

    def test_timestamps_need_an_offset(self):
        """GEN-7: plain and model serializers both refuse a timestamp without an offset."""
        class Plain(serializers.Serializer):
            at = serializers.DateTimeField()

        class Model(serializers.ModelSerializer):
            class Meta:
                model = User
                fields = ["last_login"]

        for cls, field in ((Plain, "at"), (Model, "last_login")):
            for ok in ("2027-01-11T14:00:00Z", "2027-01-11T16:00:00+02:00"):
                s = cls(data={field: ok})
                self.assertTrue(s.is_valid(), s.errors)
                self.assertEqual(s.validated_data[field].isoformat(), "2027-01-11T14:00:00+00:00")  # stored as UTC
            for bad in ("2027-01-11T14:00:00", "2027-01-11", "nonsense"):
                self.assertFalse(cls(data={field: bad}).is_valid(), bad)

    def test_hidden_ids_read_as_missing(self):
        """GEN-18: an id outside the allowed queryset is "Not found."."""
        class Body(serializers.Serializer):
            user = VisibleRelatedField(queryset=User.objects.none())

        s = Body(data={"user": 1})
        self.assertFalse(s.is_valid())
        self.assertEqual(s.errors["user"][0], "Not found.")

    def test_money(self):
        """GEN-14 to GEN-17: minor units, rounding examples, typed amounts."""
        self.assertEqual([minor_units(c) for c in ("USD", "EUR", "LBP", "JPY", "KWD", "BHD")], [2, 2, 0, 0, 3, 3])
        self.assertEqual(round_money(Decimal("46.17285"), "EUR"), Decimal("46.17"))
        self.assertEqual(round_money(Decimal("8333.4"), "LBP"), Decimal("8333"))
        self.assertEqual(round_money(Decimal("0.125"), "USD"), Decimal("0.13"))
        self.assertEqual(round_money(Decimal("1.2345"), "KWD"), Decimal("1.235"))
        self.assertEqual(round_money(Decimal("-0.125"), "USD"), Decimal("-0.13"))  # half away from zero

        self.assertEqual(validate_typed_money(Decimal("25.500"), "USD"), Decimal("25.500"))  # trailing zeros are fine
        self.assertEqual(validate_typed_money(Decimal("1.234"), "KWD"), Decimal("1.234"))
        for value, currency, message in (
            ("-1", "USD", "Must not be negative."),
            ("1.005", "USD", "Too many decimal places for USD"),
            ("100.5", "LBP", "Too many decimal places for LBP"),
        ):
            with self.assertRaises(serializers.ValidationError) as caught:
                validate_typed_money(Decimal(value), currency)
            self.assertEqual(str(caught.exception.detail[0]), message)

        self.assertEqual(validate_currency("USD"), "USD")
        for bad in ("usd", "US", "USDD", "U1D"):
            with self.assertRaises(serializers.ValidationError):
                validate_currency(bad)

    def test_blockout_serializer_validation(self):
        """CLUB-15, GEN-11: end after start (or 00:00 = end of day); repeat_until not before starts_on."""
        class S(BlockoutSerializer):
            class Meta(BlockoutSerializer.Meta):
                model = UserBlockout

        base = {"starts_on": "2027-01-04", "start_time": "09:00", "end_time": "17:00"}

        def check(**extra):
            s = S(data={**base, **extra})
            s.is_valid()
            return s.errors

        self.assertEqual(check(), {})
        self.assertEqual(check(end_time="00:00", repeat="weekly", repeat_until="2027-01-04"), {})
        self.assertIn("end_time", check(end_time="09:00"))
        self.assertIn("end_time", check(end_time="08:00"))
        self.assertIn("repeat_until", check(repeat="daily", repeat_until="2027-01-03"))
        self.assertIn("repeat", check(repeat="yearly"))
        self.assertIn("reason", check(reason="x" * 256))

        # PATCH: the stored row fills the fields not sent
        stored = UserBlockout(starts_on=datetime.date(2027, 1, 4), start_time=datetime.time(9), end_time=datetime.time(17))
        s = S(stored, data={"start_time": "18:00"}, partial=True)
        self.assertFalse(s.is_valid())
        self.assertIn("end_time", s.errors)

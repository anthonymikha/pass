import datetime
import re
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.db import transaction
from django.test import SimpleTestCase, override_settings
from rest_framework import exceptions, serializers
from rest_framework.authtoken.models import Token
from rest_framework.settings import api_settings
from rest_framework.test import APITestCase

from config.api import BusinessError, VisibleRelatedField, exception_handler
from config.storage import UUID, get_storage
from config.money import minor_units, round_money, validate_currency, validate_typed_money

from bookings import tests as bookings_tests

from . import services
from .models import Connection, Device, User, UserBlockout
from .services import outbox as accounts_outbox
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
        self.assertEqual(self.client.get("/api/me/").status_code, 200)  # ACC-30, ACC-31: the token stays
        self.assertEqual(self.post("auth/login/", {"email": "player@example.com", "password": PASSWORD}).data["token"], token)

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
        """ACC-32: password reset counts against the same limit as register and login, 10 a minute per IP."""
        attempt = {"email": "a@example.com", "password": "wrong"}
        for _ in range(9):
            self.assertEqual(self.post("auth/login/", attempt).status_code, 400)
        self.assertEqual(self.post("auth/password-reset/", {"email": "a@example.com"}).status_code, 200)
        self.assertEqual(self.post("auth/login/", attempt).status_code, 429)
        self.assertEqual(self.post("auth/password-reset/", {"email": "a@example.com"}).status_code, 429)

    @override_settings(PASS_HOST="pass.example.com")
    def test_password_reset_journey(self):
        """ACC-32, ACC-30: the same answer for any email; a link to Django's page on PASS_HOST for an active account
        only; the new password passes the strength checks; success deletes the token (devices stay); the link works
        once and for one hour."""
        pat = User.objects.create_user("pat@example.com", PASSWORD, full_name="Pat")
        token = Token.objects.create(user=pat).key
        Device.objects.create(user=pat, token="phone", platform="ios")
        User.objects.create_user("gone@example.com", PASSWORD, is_active=False)
        User.objects.create_user(email=None, full_name="Kid", managed_by=pat)

        answers = [self.post("auth/password-reset/", {"email": e}) for e in ("nobody@example.com", "gone@example.com", "PAT@example.com")]
        self.assertEqual({(r.status_code, r.data["detail"]) for r in answers}, {(200, answers[0].data["detail"])})
        self.assertIn("email", self.post("auth/password-reset/", {"email": "not-an-email"}).data)
        self.assertEqual([m.to for m in mail.outbox], [["pat@example.com"]])  # nobody else gets mail
        link = re.search(r"https://pass\.example\.com(/account/reset/\S+/\S+/)", mail.outbox[0].body).group(1)

        # Django's page: weak passwords are refused (the register checks), a good one is set
        page = self.client.get(link, follow=True)
        self.assertTrue(page.context["validlink"])
        form_url = page.redirect_chain[-1][0]
        r = self.client.post(form_url, {"new_password1": "12345678", "new_password2": "12345678"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["form"].errors)
        r = self.client.post(form_url, {"new_password1": "new-court-side-43", "new_password2": "new-court-side-43"}, follow=True)
        self.assertContains(r, "Go back to the PASS app")
        # ACC-30: signed out everywhere (the token is gone), devices kept; the old password no longer works
        self.assertFalse(Token.objects.filter(key=token).exists())
        self.assertTrue(Device.objects.filter(user=pat).exists())
        self.assertEqual(self.post("auth/login/", {"email": "pat@example.com", "password": PASSWORD}).status_code, 400)
        self.assertEqual(self.post("auth/login/", {"email": "pat@example.com", "password": "new-court-side-43"}).status_code, 200)
        # once only
        self.assertFalse(self.client.get(link, follow=True).context["validlink"])

        # one hour: a fresh link is dead 3601 seconds later
        cache.clear()
        mail.outbox.clear()
        self.post("auth/password-reset/", {"email": "pat@example.com"})
        link = re.search(r"https://pass\.example\.com(/account/reset/\S+/\S+/)", mail.outbox[0].body).group(1)
        later = datetime.datetime.now() + datetime.timedelta(seconds=3601)
        with mock.patch("django.contrib.auth.tokens.PasswordResetTokenGenerator._now", return_value=later):
            self.assertFalse(self.client.get(link, follow=True).context["validlink"])
        self.assertTrue(self.client.get(link, follow=True).context["validlink"])


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
        """NOTE-1, NOTE-2, NOTE-3, ACC-31, GEN-5: register, repeat, move to another user, unregister, logout."""
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
        self.register("tok-5", "ios")
        # ACC-31, NOTE-3: logout forgets only the device it names, and only the caller's; unknown or none is still 204
        logout = lambda body: self.client.post("/api/auth/logout/", body, format="json").status_code  # noqa: E731
        self.assertEqual(logout({"device_token": "tok-5"}), 204)
        self.assertEqual(logout({"device_token": "tok-3"}), 204)  # Pat's: untouched
        self.assertEqual((logout({"device_token": "nope"}), logout({})), (204, 204))
        self.assertEqual(list(Device.objects.filter(user=self.sam).values_list("token", flat=True)), ["tok-1"])
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

    def fcm(self, *answers):
        """Run one notify() through the real sender with FCM mocked; `answers` are (status, body) per post."""
        def reply(status, body):
            return mock.Mock(ok=status < 300, status_code=status, content=b"x" if body else b"", text=str(body), json=lambda: body)
        session = mock.Mock()
        session.post.side_effect = [reply(*a) for a in answers]
        with override_settings(FCM_CREDENTIALS_FILE="/fake.json"), mock.patch("accounts.services._fcm_session", return_value=(session, "pass-proj")):
            with self.captureOnCommitCallbacks(execute=True):
                services.notify([self.pat], "friend_request", "Hi", "Sam wants to play", {"id": 7})
        return session

    def test_firebase_sender(self):
        """NOTE-10, NOTE-11, NOTE-12, NOTE-14: FCM HTTP v1 request shape, an unregistered token deletes the device,
        any other failure is logged and ignored, and nothing goes to the fake outbox when credentials are set."""
        keep = Device.objects.create(user=self.pat, token="keep", platform="ios")
        Device.objects.create(user=self.pat, token="stale", platform="android")
        unregistered = (404, {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}})

        session = self.fcm((200, {"name": "m1"}), unregistered)
        (url,), first = session.post.call_args_list[0]
        self.assertEqual(url, "https://fcm.googleapis.com/v1/projects/pass-proj/messages:send")
        self.assertEqual(first["json"], {"message": {"token": "keep", "notification": {"title": "Hi", "body": "Sam wants to play"},
                                                     "data": {"type": "friend_request", "id": "7"}}})
        self.assertEqual(list(Device.objects.values_list("token", flat=True)), ["keep"])  # NOTE-12
        self.assertEqual(services.outbox, [])

        with self.assertLogs("accounts.services", "ERROR"):  # NOTE-12: other failures are logged, the device stays
            self.fcm((500, {"error": {"status": "INTERNAL"}}))
        with self.assertLogs("accounts.services", "ERROR"):
            self.fcm((503, None))
        self.assertTrue(Device.objects.filter(pk=keep.pk).exists())

    def test_firebase_credentials_are_read_once_per_process(self):
        """NOTE-11: the service-account file is loaded on the first push only and cached."""
        services._fcm_session.cache_clear()
        self.addCleanup(services._fcm_session.cache_clear)
        creds = mock.Mock(project_id="pass-proj")
        with mock.patch("google.oauth2.service_account.Credentials.from_service_account_file", return_value=creds) as load, \
                mock.patch("google.auth.transport.requests.AuthorizedSession") as session:
            first, second = services._fcm_session("/fake.json"), services._fcm_session("/fake.json")
        self.assertEqual(load.call_count, 1)
        self.assertEqual((first, second), ((session.return_value, "pass-proj"),) * 2)

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


@override_settings(STORAGE_ENDPOINT="")  # REC-3: always the in-memory fake, even where real storage is configured
class AvatarTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        get_storage.cache_clear()
        self.addCleanup(get_storage.cache_clear)
        self.storage = get_storage()
        self.storage.keys.clear()
        self.storage.forms.clear()

    def form(self, user, name="me.PNG", size=1000):
        return self.call(user, "post", "me/avatar/form/", {"file_name": name, "size_bytes": size})

    def test_avatar_journey(self):
        """REC-1, REC-2, REC-3, REC-12, REC-30, ACC-21, GEN-5: form, upload, confirm; the profile and the public profile
        show a signed link; a new avatar deletes the old object; a repeat changes nothing; bad input and keys."""
        ann, bob = self.user("ann"), self.user("bob")
        self.assertEqual(self.call(ann, "get", "me/").data["avatar"], "")  # none yet: empty
        self.assertEqual(self.call(bob, "get", f"users/{ann.id}/").data["avatar"], "")

        r = self.form(ann, size=5 * 1024 * 1024)  # the limit itself
        self.assertEqual(r.status_code, 200, r.data)
        key = r.data["storage_key"]
        self.assertRegex(key, rf"^avatars/{ann.id}/{UUID}\.png$")
        self.assertEqual((set(r.data), self.storage.forms[key]), ({"url", "fields", "storage_key"}, 5 * 1024 * 1024))
        r = self.call(ann, "post", "me/avatar/", {"storage_key": key})
        self.assertEqual((r.status_code, r.data["code"]), (400, "not_uploaded"))
        ann.refresh_from_db()
        self.assertFalse(ann.avatar)

        self.storage.put(key)
        r = self.call(ann, "post", "me/avatar/", {"storage_key": key})
        self.assertEqual((r.status_code, r.data["avatar"]), (200, f"http://storage.test/pass/{key}?expires=3600"))  # REC-2
        ann.refresh_from_db()
        self.assertEqual(ann.avatar.name, key)
        self.assertEqual(self.call(ann, "get", "me/").data["avatar"], r.data["avatar"])
        public = self.call(bob, "get", f"users/{ann.id}/").data  # ACC-21
        self.assertEqual((public["avatar"], "email" in public), (r.data["avatar"], False))
        self.assertEqual(self.call(ann, "post", "me/avatar/", {"storage_key": key}).status_code, 200)  # GEN-5: repeat
        self.assertIn(key, self.storage.keys)  # the repeat did not delete the current object

        second = self.form(ann, name="new.jpeg").data["storage_key"]
        self.storage.put(second)
        self.assertEqual(self.call(ann, "post", "me/avatar/", {"storage_key": second}).status_code, 200)
        ann.refresh_from_db()
        self.assertEqual((ann.avatar.name, self.storage.keys), (second, {second}))  # the old object is gone

        # input: extension and size per field; the key must be the caller's own and well formed
        for name in ("me.gif", "me", "png", "me.png.exe"):
            self.assertIn("file_name", self.form(ann, name=name).data)
        for size in (0, 5 * 1024 * 1024 + 1):
            self.assertEqual(list(self.form(ann, size=size).data), ["size_bytes"])
        for name in ("a.jpg", "a.JPEG", "a.webp"):
            self.assertEqual(self.form(ann, name=name).status_code, 200)
        theirs = self.form(bob).data["storage_key"]
        self.storage.put(theirs)
        uuid_name = second.split("/")[2]
        for bad in (theirs, f"avatars/{ann.id}/x.png", f"avatars/{ann.id}/{uuid_name[:-5]}.gif", f"recordings/1/{uuid_name}"):
            r = self.call(ann, "post", "me/avatar/", {"storage_key": bad})
            self.assertEqual((r.status_code, r.data["code"]), (400, "bad_key"), bad)
        self.assertEqual(self.call(ann, "post", "me/avatar/", {}).status_code, 400)
        ann.refresh_from_db()
        self.assertEqual(ann.avatar.name, second)
        self.assertEqual(self.call(ann, "patch", "me/", {"avatar": "avatars/1/evil.png"}).data["avatar"],
                         f"http://storage.test/pass/{second}?expires=3600")  # not writable through the profile
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post("/api/me/avatar/form/", {}, format="json").status_code, 401)


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


@override_settings(STORAGE_ENDPOINT="")  # REC-3: the in-memory fake
class DeleteAccountTests(bookings_tests.PaymentBase):
    def setUp(self):
        super().setUp()
        get_storage.cache_clear()
        self.addCleanup(get_storage.cache_clear)

    def delete_me(self, user, password=PASSWORD, expect=204, push=False):
        return self.call("delete", "me/", user, {"password": password}, expect, push)

    def test_delete_account_journey(self):
        """ACC-33, ACC-34, ACC-20, ACC-23, TEAM-34, TEAM-35, TEAM-28, TEAM-30, BOOK-22, BOOK-50, PAY-20, PAY-25, NOTE-20:
        the password first, a club owner cannot; then upcoming sessions are cancelled or declined, groups left, data
        deleted, the row scrubbed and deactivated; money and other people's history stay; nobody manages the team
        until an admin gives it a coach."""
        from chat.models import Chat, ChatMember, Message
        from teams.models import Group, GroupMember
        from venues.models import ClubMember
        from wellness.models import Exercise, ExerciseAssignment, SleepLog, SorenessLog, UserAchievement
        Session, SessionParticipant, Payment = bookings_tests.Session, bookings_tests.SessionParticipant, bookings_tests.Payment
        at, MON, TUE = bookings_tests.at, bookings_tests.MON, bookings_tests.TUE
        pat, ann, ben, cora, zed = (self.user(n) for n in ("pat", "ann", "ben", "cora", "zed"))
        for coach in (pat, cora):
            coach.is_coach = True
            coach.save()
        kid = self.shadow("Kid", pat)
        storage = get_storage()
        pat.avatar = f"avatars/{pat.id}/face.jpg"
        pat.phone, pat.coach_bio, pat.nationality, pat.date_of_birth = "555", "Ex-pro", "LB", datetime.date(1990, 1, 1)
        pat.save()
        storage.put(pat.avatar.name)
        self.befriend(pat, ann)
        Connection.objects.create(user=pat, other_user=zed, type="friend", status="blocked")
        Connection.objects.create(user=pat, other_user=ben, type="coaching", status="accepted")
        UserBlockout.objects.create(user=pat, starts_on=MON, start_time=datetime.time(8), end_time=datetime.time(9))
        ClubMember.objects.create(club=self.club, user=pat, role="coach", status="active")

        # sessions: Pat's upcoming booking (Ann accepted), a request to Pat, Ann's booking with Pat, a past one with RPE
        booked = Session.objects.get(pk=self.book(pat, at(MON, 10), at(MON, 11), invitees=[ann.id]).data["id"])
        self.accept(ann, booked)
        asked = Session.objects.get(pk=self.call("post", "training-requests/", ben, {
            "coach": pat.id, "sport": self.basketball.id, "starts_at": bookings_tests.z(at(MON, 12)),
            "ends_at": bookings_tests.z(at(MON, 13))}, 201).data["id"])
        anns = Session.objects.get(pk=self.book(ann, at(MON, 14), at(MON, 15), invitees=[pat.id]).data["id"])
        self.accept(pat, anns)
        past = self.session(self.court1, at(datetime.date(2026, 12, 7), 10), at(datetime.date(2026, 12, 7), 11), ann)
        SessionParticipant.objects.create(session=past, user=pat, status="accepted", checked_in_at=past.starts_at, rpe=7)
        owes = Payment.objects.create(session=past, payer=pat, club=self.club, amount=50, currency="USD", platform_fee=5)
        owed = Payment.objects.create(session=past, payer=ann, coach=pat, amount=40, currency="USD", platform_fee=4)
        # groups: Pat's play group, Pat's team (Ann, Kid), Cora's team with Pat in it
        park = self.call("post", "groups/", pat, {"name": "Park", "type": "play_group"}, 201).data["id"]
        self.call("post", f"groups/{park}/members/", pat, {"user": ann.id}, 201)
        self.call("post", f"groups/{park}/accept/", ann, expect=200)
        team = self.call("post", "groups/", pat, {"name": "Tigers", "type": "team"}, 201).data["id"]
        self.call("post", f"groups/{team}/members/", pat, {"user": ann.id}, 201)
        self.call("post", f"groups/{team}/accept/", ann, expect=200)
        self.call("post", f"groups/{team}/shadow-players/", pat, {"player": kid.id}, 201)
        coras = self.call("post", "groups/", cora, {"name": "Lions", "type": "team"}, 201).data["id"]
        self.call("post", f"groups/{coras}/members/", cora, {"user": pat.id}, 201)
        self.call("post", f"groups/{coras}/accept/", pat, expect=200)
        # wellness and chat
        exercise = Exercise.objects.create(name="Stretch", kind="stretch", min_soreness=0, max_soreness=10)
        ExerciseAssignment.objects.create(exercise=exercise, user=pat, assigned_by=cora)
        given = ExerciseAssignment.objects.create(exercise=exercise, user=ann, assigned_by=pat)
        SleepLog.objects.create(user=pat, sleep_start=at(MON, 0), sleep_end=at(MON, 7), source="manual")
        SorenessLog.objects.create(user=pat, logged_on=MON, period="morning", body_area="neck", level=3)
        UserAchievement.objects.create(user=pat, achievement_code="first", earned_at=at(MON, 9))
        direct = self.call("post", "chats/direct/", pat, {"user": ann.id}, 201).data["id"]
        self.call("post", f"chats/{direct}/messages/", pat, {"body": "See you"}, 201)
        token = Token.objects.get_or_create(user=pat)[0].key

        # ACC-33: the password is checked first, then owning a club
        self.assertIn("password", self.call("delete", "me/", pat, {}, 400).data)
        self.assertIn("password", self.delete_me(pat, "wrong", 400).data)
        self.code(self.delete_me(self.owner, expect=400), 400, "owns_club")
        self.assertTrue(User.objects.get(pk=pat.pk).is_active)

        accounts_outbox.clear()
        self.delete_me(pat, push=True)

        # step 1: Pat's booking cancelled (Ann told), the request declined (Ben told), Pat declined in Ann's; the past stays
        for s in (booked, asked, anns):
            s.refresh_from_db()
        self.assertEqual((booked.status, asked.status, anns.status), ("cancelled", "cancelled", "confirmed"))
        self.assertEqual([len(self.pushed(u, kind)) for u, kind in ((ann, "session_cancelled"), (ben, "training_declined"))], [1, 1])
        self.assertEqual(anns.participants.get(user=pat).status, "declined")
        self.assertEqual(SessionParticipant.objects.get(session=past, user=pat).rpe, 7)
        # step 2: the play group is gone, its chat kept without members; the team has no coach and no creator;
        # Pat left Cora's team and its chat
        self.assertFalse(Group.objects.filter(pk=park).exists())
        tigers = Group.objects.get(pk=team)
        self.assertEqual((tigers.coach, tigers.created_by), (None, None))
        self.assertFalse(GroupMember.objects.filter(user=pat).exists())
        self.assertEqual(set(GroupMember.objects.filter(group=tigers).values_list("user", flat=True)), {ann.pk, kid.pk})
        self.assertFalse(ChatMember.objects.filter(user=pat).exists())
        self.assertTrue(ChatMember.objects.filter(chat__group=tigers, user=ann).exists())
        # step 3: Kid is nobody's now, still on the team
        kid.refresh_from_db()
        self.assertIsNone(kid.managed_by)
        # step 4: deleted
        self.assertFalse(Token.objects.filter(user=pat).exists() or Device.objects.filter(user=pat).exists())
        self.assertFalse(Connection.objects.filter(user=pat).exists() or Connection.objects.filter(other_user=pat).exists())
        self.assertFalse(UserBlockout.objects.filter(user=pat).exists() or ClubMember.objects.filter(user=pat).exists())
        for model in (SleepLog, SorenessLog, ExerciseAssignment, UserAchievement):
            self.assertFalse(model.objects.filter(user=pat).exists(), model)
        # step 5: scrubbed and deactivated; the avatar file is gone after commit
        pat.refresh_from_db()
        self.assertEqual((pat.full_name, pat.email, pat.phone, pat.coach_bio, pat.nationality, pat.date_of_birth, pat.is_coach,
                          pat.timezone, pat.avatar.name, pat.is_active, pat.has_usable_password()),
                         ("Deleted user", f"deleted-{pat.id}@invalid", "", "", "", None, False, "UTC", "", False, False))
        self.assertNotIn(f"avatars/{pat.id}/face.jpg", storage.keys)
        # kept: payments both ways, the assignment Pat made, Pat's message, the chat for Ann
        self.assertTrue(ExerciseAssignment.objects.filter(pk=given.pk).exists())
        self.assertEqual(Message.objects.get(chat_id=direct).sender_id, pat.id)
        self.assertTrue(Chat.objects.filter(pk=direct).exists())
        self.assertEqual(Payment.objects.filter(pk__in=[owes.pk, owed.pk]).count(), 2)

        # ACC-34: signed out everywhere, cannot log in, never found; shown as "Deleted user"; the email is free again
        self.client.force_authenticate(None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.client.get("/api/me/").status_code, 401)
        self.client.credentials()
        self.assertEqual(self.client.post("/api/auth/login/", {"email": "pat@example.com", "password": PASSWORD}).status_code, 400)
        self.call("get", f"users/{pat.id}/", ann, expect=404)
        self.assertEqual(self.call("get", "users/?q=Deleted", ann, expect=200).data["count"], 0)
        r = self.call("get", f"payments/{owes.id}/", self.owner, expect=200).data
        self.assertEqual(r["payer"]["full_name"], "Deleted user")
        self.assertEqual(self.client.post("/api/auth/register/", {"email": "pat@example.com", "password": PASSWORD, "full_name": "Pat"}).status_code, 201)
        # ACC-34: the club may still receive or waive what Pat owes; what is owed to Pat nobody can mark
        self.call("post", f"payments/{owes.id}/waive/", self.owner, expect=200)
        self.call("post", f"payments/{owed.id}/mark-paid/", ann, expect=403)

        # TEAM-34: the team has no manager: nobody can invite, rename or hand it over; members may still leave
        for who in (ann, cora):
            self.call("post", f"groups/{team}/members/", who, {"user": ben.id}, 403)
            self.call("patch", f"groups/{team}/", who, {"name": "Mine"}, 403)
        # TEAM-35: a platform admin gives it a coach in the Django admin; Cora is seated as a member and in the chat
        admin = User.objects.create_superuser("admin@example.com", PASSWORD, full_name="Admin")
        self.client.force_authenticate(None)
        self.client.force_login(admin)
        r = self.client.post(f"/admin/teams/group/{team}/change/", {"type": "team", "name": "Tigers", "coach": cora.id,
                                                                     "created_by": "", "sport": ""})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(GroupMember.objects.get(group_id=team, user=cora).status, "active")
        self.assertTrue(ChatMember.objects.filter(chat__group_id=team, user=cora).exists())
        self.client.logout()
        self.call("post", f"groups/{team}/members/", cora, {"user": ben.id}, 201)
        self.call("delete", f"groups/{team}/members/{ann.id}/", ann, expect=204)

    def test_admin_deactivation_is_not_deletion(self):
        """ACC-35, ACC-30: an admin's deactivation stops sign-in like a wrong password and scrubs nothing; switching it
        back on restores the account."""
        ann = self.user("ann")
        self.client.force_authenticate(None)
        login = {"email": "ann@example.com", "password": PASSWORD}
        token = self.client.post("/api/auth/login/", login).data["token"]
        User.objects.filter(pk=ann.pk).update(is_active=False)
        r = self.client.post("/api/auth/login/", login)
        wrong = self.client.post("/api/auth/login/", {**login, "password": "nope-nope-1"})
        self.assertEqual((r.status_code, r.data), (wrong.status_code, wrong.data))
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.client.get("/api/me/").status_code, 401)
        User.objects.filter(pk=ann.pk).update(is_active=True)
        self.assertEqual(self.client.get("/api/me/").data["full_name"], "Ann")

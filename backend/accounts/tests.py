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
from .models import Device, User, UserBlockout
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

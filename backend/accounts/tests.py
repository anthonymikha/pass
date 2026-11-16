from django.core.cache import cache
from rest_framework.test import APITestCase

from .models import User

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
                    {"nationality": "lebanon"}, {"date_of_birth": "2999-01-01"}, {"sex": "x"}, {"height_cm": "5"}):
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

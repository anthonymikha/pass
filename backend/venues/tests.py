import datetime as dt
from decimal import Decimal
from unittest import mock

from rest_framework.test import APITestCase

from accounts import services
from accounts.models import User
from bookings.models import Session, SessionRental
from venues.models import (
    Club, ClubCurrency, ClubMember, Court, CourtBlockout, CourtRate, Discount, Equipment, PriceOverride, Sport,
)

PASSWORD = "court-side-42"
UTC = dt.timezone.utc
NOW = dt.datetime(2027, 1, 1, 0, 0, tzinfo=UTC)  # a Friday; Beirut is UTC+2 in January


def at(day, hour, minute=0):
    """A Beirut wall-clock time as a UTC instant (January, UTC+2)."""
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=UTC) - dt.timedelta(hours=2)


class VenuesBase(APITestCase):
    def setUp(self):
        services.outbox.clear()
        self.basketball = Sport.objects.get_or_create(name="Basketball")[0]
        self.volleyball = Sport.objects.get_or_create(name="Volleyball")[0]

    def user(self, email, **fields):
        return User.objects.create_user(email, PASSWORD, full_name=email.split("@")[0].title(), **fields)

    def as_user(self, user):
        self.client.force_authenticate(user)

    def call(self, method, path, data=None, expect=None, user=None):
        if user:
            self.as_user(user)
        r = getattr(self.client, method)(f"/api/{path}", data, format="json")
        if expect:
            self.assertEqual(r.status_code, expect, (method, path, data, r.data if r.content else None))
        return r

    def club_with_court(self, owner, name="Hoops", currency="USD", active=True):
        club = Club.objects.create(owner=owner, name=name, timezone="Asia/Beirut", currency=currency)
        court = Court.objects.create(club=club, name="Court 1", slot_minutes=60, is_active=active)
        court.sports.set([self.basketball])
        return club, court

    def session(self, court, start, end, status="confirmed", booker=None, currency="USD"):
        return Session.objects.create(
            court=court, sport=self.basketball, booked_by=booker or court.club.owner, kind="play", status=status,
            starts_at=start, ends_at=end, currency=currency, price=Decimal("50"),
        )


class OwnerSetupTests(VenuesBase):
    def test_owner_journey(self):
        """CLUB-1, CLUB-2, CLUB-5, CLUB-6, CLUB-8, CLUB-9, CLUB-11, CLUB-15, CLUB-17, CLUB-18, CLUB-20, CLUB-21, CLUB-22,
        CLUB-23, CLUB-25, CLUB-26, CLUB-27, CLUB-28, CLUB-29, CLUB-31, PRC-1, PRC-2, PRC-3, ACC-3, ACC-5: an owner sets up
        "Hoops" end to end with the pricing worked example, and the public reads it back."""
        r = self.client.post("/api/auth/register/", {"email": "owner@example.com", "password": PASSWORD, "full_name": "Olga"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {r.data['token']}")
        owner = User.objects.get(email="owner@example.com")

        # CLUB-1, CLUB-2: create (the caller becomes owner), then change the editable fields
        r = self.call("post", "clubs/", {"name": "Hoops", "timezone": "Asia/Beirut", "currency": "USD"}, 201)
        club = r.data["id"]
        self.assertEqual(Club.objects.get(pk=club).owner, owner)
        r = self.call("patch", f"clubs/{club}/", {"name": "Hoops Beirut", "address": "Hamra", "latitude": "33.893800", "longitude": "35.501800", "timezone": "Asia/Beirut"}, 200)
        self.assertEqual((r.data["name"], r.data["address"], r.data["currency"]), ("Hoops Beirut", "Hamra", "USD"))
        self.call("patch", f"clubs/{club}/", {"name": "Hoops"}, 200)

        # CLUB-5, CLUB-6, PRC-1, PRC-2: accepted currencies (units per 1 base)
        r = self.call("post", f"clubs/{club}/currencies/", {"currency": "EUR", "exchange_rate": "0.923457"}, 201)
        eur = r.data["id"]
        self.assertEqual(r.data["exchange_rate"], "0.923457")
        lbp = self.call("post", f"clubs/{club}/currencies/", {"currency": "LBP", "exchange_rate": "89500"}, 201).data["id"]
        r = self.call("patch", f"currencies/{lbp}/", {"exchange_rate": "90000", "currency": "GBP"}, 200)  # currency is not editable
        self.assertEqual((r.data["currency"], r.data["exchange_rate"]), ("LBP", "90000.000000"))
        self.call("patch", f"currencies/{lbp}/", {"exchange_rate": "89500"}, 200)
        self.assertEqual(self.call("get", f"clubs/{club}/currencies/").data["count"], 2)

        # CLUB-8, CLUB-9: a multi-sport court and a one-sport court
        r = self.call("post", f"clubs/{club}/courts/", {"name": "Court 1", "description": "Indoor", "slot_minutes": 60, "sports": [self.basketball.id, self.volleyball.id]}, 201)
        court1 = r.data["id"]
        self.assertTrue(r.data["is_active"])
        court2 = self.call("post", f"clubs/{club}/courts/", {"name": "Court 2", "slot_minutes": 90, "sports": [self.basketball.id]}, 201).data["id"]
        r = self.call("patch", f"courts/{court2}/", {"slot_minutes": 60, "name": "Court B", "sports": [self.volleyball.id, self.basketball.id]}, 200)
        self.assertEqual((r.data["slot_minutes"], r.data["name"]), (60, "Court B"))

        # CLUB-11, PRC-3: day and evening rates on Monday (the worked example), typed in base
        day = self.call("post", f"courts/{court1}/rates/", {"weekday": 0, "start_time": "09:00", "end_time": "17:00", "price": "50.00"}, 201).data
        evening = self.call("post", f"courts/{court1}/rates/", {"weekday": 0, "start_time": "17:00", "end_time": "00:00", "price": "70"}, 201).data
        self.assertEqual((day["price"], evening["price"], evening["end_time"]), ("50.000", "70.000", "00:00:00"))
        self.call("patch", f"rates/{day['id']}/", {"price": "55.00"}, 200)
        self.call("patch", f"rates/{day['id']}/", {"price": "50.00"}, 200)

        # CLUB-20, CLUB-21: the evening rate in EUR is 65.00 by hand
        r = self.call("post", f"clubs/{club}/overrides/", {"court_rate": evening["id"], "currency": "EUR", "price": "65.00"}, 201)
        override = r.data["id"]
        self.assertEqual((r.data["price"], r.data["equipment"]), ("65.000", None))
        self.call("patch", f"overrides/{override}/", {"price": "66.00", "currency": "LBP"}, 200)
        self.call("patch", f"overrides/{override}/", {"price": "65.00"}, 200)
        self.assertEqual(PriceOverride.objects.get().currency, "EUR")

        # CLUB-18: shared rentable item, court-tied included item
        shooting = self.call("post", f"clubs/{club}/equipment/", {"name": "Shooting machine", "quantity": 1, "rental_price": "15.00"}, 201).data
        balls = self.call("post", f"clubs/{club}/equipment/", {"name": "Basketballs", "quantity": 3, "court": court1}, 201).data
        self.assertEqual((shooting["court"], shooting["rental_price"], balls["court"], balls["rental_price"]), (None, "15.000", court1, None))
        self.call("patch", f"equipment/{balls['id']}/", {"quantity": 4}, 200)

        # CLUB-15, CLUB-17: a weekly closure on court 1, changed and kept
        r = self.call("post", f"courts/{court1}/closures/", {"starts_on": "2027-01-05", "start_time": "08:00", "end_time": "10:00", "repeat": "weekly", "reason": "Floor care"}, 201)
        closure = r.data["id"]
        self.assertEqual(r.data["conflicts"], [])
        self.call("patch", f"closures/{closure}/", {"repeat_until": "2027-06-30"}, 200)
        self.assertEqual(self.call("get", f"courts/{court1}/closures/").data["results"][0]["repeat_until"], "2027-06-30")
        self.assertNotIn("conflicts", self.call("get", f"closures/{closure}/").data)

        # CLUB-22, CLUB-23: both kinds of offer
        player = self.user("player@example.com")
        starts, ends = "2027-01-01T00:00:00Z", "2027-02-01T00:00:00+02:00"
        percent = self.call("post", f"clubs/{club}/offers/", {"percent_off": "20", "court": court1, "starts_at": starts, "ends_at": ends, "user": player.id, "message": "Come back"}, 201).data
        amount = self.call("post", f"clubs/{club}/offers/", {"amount_off": "10.00", "min_bookings": 10, "starts_at": starts, "ends_at": ends}, 201).data
        self.assertEqual((percent["percent_off"], percent["amount_off"], amount["amount_off"], amount["min_bookings"]), ("20.00", None, "10.000", 10))
        self.call("patch", f"offers/{amount['id']}/", {"amount_off": "12"}, 200)
        self.call("delete", f"offers/{percent['id']}/", expect=204)
        self.assertEqual(Discount.objects.count(), 1)

        # CLUB-25, CLUB-29: staff and a player by email (any case), then a new expiry
        staff = self.user("staff@example.com")
        r = self.call("post", f"clubs/{club}/members/", {"email": "STAFF@example.com", "role": "staff"}, 201)
        staff_row = r.data["id"]
        self.assertEqual((r.data["status"], r.data["role"], r.data["expires_on"]), ("active", "staff", None))
        r = self.call("post", f"clubs/{club}/members/", {"email": "player@example.com", "role": "player", "expires_on": "2027-12-31"}, 201)
        player_row = r.data["id"]
        self.call("patch", f"members/{player_row}/", {"expires_on": None, "role": "staff"}, 200)
        self.assertEqual(ClubMember.objects.get(pk=player_row).role, "player")
        self.assertIsNone(ClubMember.objects.get(pk=player_row).expires_on)

        # CLUB-26, CLUB-27: a coach asks, the owner approves
        coach = self.user("coach@example.com", is_coach=True)
        r = self.call("post", f"clubs/{club}/coach-requests/", user=coach, expect=201)
        coach_row = r.data["id"]
        self.assertEqual((r.data["role"], r.data["status"]), ("coach", "pending"))
        self.call("post", f"members/{coach_row}/approve/", user=owner, expect=200)
        self.assertEqual(ClubMember.objects.get(pk=coach_row).status, "active")

        # CLUB-29: the owner sees all rows, a staff member the current ones, a stranger nothing
        rows = self.call("get", f"clubs/{club}/members/", user=owner).data
        self.assertEqual(rows["count"], 3)
        self.assertEqual(self.call("get", f"clubs/{club}/members/", user=staff).data["count"], 3)
        self.call("get", f"clubs/{club}/members/", user=self.user("nobody@example.com"), expect=404)

        # CLUB-28: the owner removes a row; a member leaves
        self.call("delete", f"members/{staff_row}/", user=owner, expect=204)
        self.call("delete", f"members/{coach_row}/", user=coach, expect=204)
        self.assertEqual(ClubMember.objects.count(), 1)

        # CLUB-31, ACC-3: the public reads court 1 without signing in
        self.client.credentials()
        self.client.force_authenticate(None)
        d = self.call("get", f"courts/{court1}/", expect=200).data
        self.assertEqual((d["club"]["name"], d["club"]["currency"], d["club"]["timezone"]), ("Hoops", "USD", "Asia/Beirut"))
        self.assertEqual([(c["currency"], c["exchange_rate"]) for c in d["club"]["currencies"]], [("EUR", "0.923457"), ("LBP", "89500.000000")])
        self.assertEqual([(x["weekday"], x["start_time"], x["end_time"], x["price"]) for x in d["rates"]],
                         [(0, "09:00:00", "17:00:00", "50.000"), (0, "17:00:00", "00:00:00", "70.000")])
        self.assertEqual([s["name"] for s in d["court"]["sports"]], ["Basketball", "Volleyball"])
        self.assertEqual([e["name"] for e in d["equipment"]["included"]], ["Basketballs"])
        self.assertEqual([e["name"] for e in d["equipment"]["rentable"]], ["Shooting machine"])

        # the club's own court list: the owner also sees inactive courts
        self.call("patch", f"courts/{court2}/", {"is_active": False}, user=owner, expect=200)
        self.assertEqual(self.call("get", f"clubs/{club}/courts/").data["count"], 2)
        self.assertEqual(self.call("get", f"clubs/{club}/courts/", user=player).data["count"], 1)

    def test_refused_requests_write_nothing(self):
        """ACC-5, ACC-6, GEN-3, GEN-4, CLUB-4 (page intro): another user gets 404 on clubs they cannot see and 403 on public
        ones; staff, coaches and players change no configuration; no token is 401."""
        owner = self.user("owner@example.com")
        stranger = self.user("stranger@example.com")
        staff = self.user("staff@example.com")
        coach = self.user("coach@example.com", is_coach=True)
        player = self.user("player@example.com")
        applicant = self.user("applicant@example.com", is_coach=True)

        def build(public):
            club, court = self.club_with_court(owner, name="Public" if public else "Hidden", active=public)
            f = {"club": club.id, "court": court.id}
            f["inactive"] = Court.objects.create(club=club, name="Closed", slot_minutes=60, is_active=False).id
            f["inactive_rate"] = CourtRate.objects.create(court_id=f["inactive"], weekday=1, start_time=dt.time(9), end_time=dt.time(10), price=1).id
            f["eur"] = ClubCurrency.objects.create(club=club, currency="EUR", exchange_rate=Decimal("0.9")).id
            rate = CourtRate.objects.create(court=court, weekday=0, start_time=dt.time(9), end_time=dt.time(17), price=50)
            f["rate"] = rate.id
            f["closure"] = CourtBlockout.objects.create(court=court, starts_on=dt.date(2027, 3, 1), start_time=dt.time(0), end_time=dt.time(0)).id
            item = Equipment.objects.create(club=club, name="Machine", quantity=1, rental_price=15)
            f["item"] = item.id
            f["override"] = PriceOverride.objects.create(court_rate=rate, currency="EUR", price=45).id
            f["offer"] = Discount.objects.create(club=club, percent_off=10, starts_at=NOW, ends_at=NOW + dt.timedelta(days=9)).id
            for who, role in ((staff, "staff"), (coach, "coach"), (player, "player")):
                f[role] = ClubMember.objects.create(club=club, user=who, role=role, status="active").id
            f["pending"] = ClubMember.objects.create(club=club, user=applicant, role="coach", status="pending").id
            return f

        def snapshot():
            return [list(m.objects.order_by("pk").values()) for m in (Club, ClubCurrency, Court, CourtRate, CourtBlockout, Equipment, PriceOverride, Discount, ClubMember)]

        def writes(f):
            club, court = f["club"], f["court"]
            win = {"starts_at": "2027-01-01T00:00:00Z", "ends_at": "2027-02-01T00:00:00Z"}
            return [
                ("patch", f"clubs/{club}/", {"name": "Mine"}),
                ("post", f"clubs/{club}/currencies/", {"currency": "GBP", "exchange_rate": "0.8"}),
                ("patch", f"currencies/{f['eur']}/", {"exchange_rate": "1"}),
                ("delete", f"currencies/{f['eur']}/", None),
                ("post", f"clubs/{club}/courts/", {"name": "New", "slot_minutes": 60, "sports": [self.basketball.id]}),
                ("patch", f"courts/{court}/", {"name": "New"}),
                ("delete", f"courts/{court}/", None),
                ("post", f"courts/{court}/rates/", {"weekday": 3, "start_time": "09:00", "end_time": "10:00", "price": "5"}),
                ("patch", f"rates/{f['rate']}/", {"price": "1"}),
                ("delete", f"rates/{f['rate']}/", None),
                ("post", f"courts/{court}/closures/", {"starts_on": "2027-05-01", "start_time": "09:00", "end_time": "10:00"}),
                ("patch", f"closures/{f['closure']}/", {"reason": "x"}),
                ("delete", f"closures/{f['closure']}/", None),
                ("post", f"clubs/{club}/equipment/", {"name": "Net", "quantity": 1}),
                ("patch", f"equipment/{f['item']}/", {"quantity": 9}),
                ("delete", f"equipment/{f['item']}/", None),
                ("post", f"clubs/{club}/overrides/", {"equipment": f["item"], "currency": "EUR", "price": "9"}),
                ("patch", f"overrides/{f['override']}/", {"price": "1"}),
                ("delete", f"overrides/{f['override']}/", None),
                ("post", f"clubs/{club}/offers/", {"percent_off": "5", **win}),
                ("patch", f"offers/{f['offer']}/", {"message": "x"}),
                ("delete", f"offers/{f['offer']}/", None),
                ("post", f"clubs/{club}/members/", {"email": "nobody@example.com", "role": "staff"}),
                ("patch", f"members/{f['player']}/", {"expires_on": "2030-01-01"}),
                ("delete", f"members/{f['staff']}/", None),
                ("post", f"members/{f['pending']}/approve/", None),
            ]

        def configuration_reads(f):
            return [f"clubs/{f['club']}/currencies/", f"courts/{f['court']}/rates/", f"courts/{f['court']}/closures/",
                    f"clubs/{f['club']}/equipment/", f"clubs/{f['club']}/overrides/", f"currencies/{f['eur']}/", f"overrides/{f['override']}/"]

        public, hidden = build(True), build(False)
        before = snapshot()
        for label, f, who, expected in (
            ("stranger, public club", public, stranger, 403),
            ("stranger, hidden club", hidden, stranger, 404),
            ("staff, public club", public, staff, 403),
            ("coach", public, coach, 403),
            ("player", public, player, 403),
        ):
            self.as_user(who)
            for method, path, body in writes(f):
                if method == "delete" and path.startswith("members/"):  # a member may leave, so remove someone else's row
                    path = f"members/{f['player'] if who is staff else f['staff']}/"
                with self.subTest(label=label, call=f"{method} {path}"):
                    r = getattr(self.client, method)(f"/api/{path}", body, format="json")
                    want = 404 if who is stranger and path.startswith("members/") else expected  # CLUB-29: rows are for members only
                    self.assertEqual(r.status_code, want, r.data)
                    if want == 403:
                        self.assertEqual(r.data["code"], "forbidden")
            for path in configuration_reads(f):  # ACC-6: staff do not even read configuration
                with self.subTest(label=label, read=path):
                    self.assertEqual(self.client.get(f"/api/{path}").status_code, expected)
        self.assertEqual(snapshot(), before)

        # the applicant's own pending row: they see it (403 on approve, 204 on leave)
        self.as_user(applicant)
        self.call("post", f"members/{public['pending']}/approve/", expect=403)
        self.call("delete", f"members/{public['pending']}/", expect=204)

        # an inactive court does not exist for anyone but the owner, even inside a public club
        for method, path, body in (
            ("patch", f"courts/{public['inactive']}/", {"name": "x"}),
            ("get", f"courts/{public['inactive']}/rates/", None),
            ("post", f"courts/{public['inactive']}/rates/", {"weekday": 3, "start_time": "09:00", "end_time": "10:00", "price": "5"}),
            ("patch", f"rates/{public['inactive_rate']}/", {"price": "2"}),
        ):
            for who in (stranger, staff):
                self.as_user(who)
                self.assertEqual(getattr(self.client, method)(f"/api/{path}", body, format="json").status_code, 404, (who, path))

        # staff of a club with no active court still see it (membership) and still change nothing
        self.as_user(staff)
        self.call("patch", f"clubs/{hidden['club']}/", {"name": "Mine"}, expect=403)
        self.call("get", f"clubs/{hidden['club']}/members/", expect=200)

        # no token: 401 everywhere that is not public (ACC-3)
        self.client.force_authenticate(None)
        for method, path, body in writes(public) + [("post", "clubs/", {"name": "x"}), ("get", f"clubs/{public['club']}/", None)]:
            self.assertEqual(getattr(self.client, method)(f"/api/{path}", body, format="json").status_code, 401, path)

        # clubs are never deleted (CLUB-4), and PUT does not exist
        self.as_user(owner)
        self.call("delete", f"clubs/{public['club']}/", expect=405)
        self.call("put", f"clubs/{public['club']}/", {}, expect=405)
        self.assertEqual(Club.objects.count(), 2)

    def test_club_and_currency_validation(self):
        """CLUB-1, CLUB-3, CLUB-5, CLUB-6, CLUB-8, GEN-1, GEN-2, GEN-4, GEN-14, GEN-17, PRC-2: club, currency and court input rules."""
        owner = self.user("owner@example.com")
        self.as_user(owner)
        good = {"name": "Hoops", "timezone": "Asia/Beirut", "currency": "USD"}
        for bad in (
            {**good, "name": ""}, {**good, "name": "x" * 256}, {**good, "timezone": "Mars/Phobos"}, {**good, "currency": "usd"},
            {**good, "currency": "US"}, {**good, "latitude": "90.5"}, {**good, "latitude": "-91"}, {**good, "longitude": "180.1"},
            {**good, "longitude": "-181"}, {"name": "x"},
        ):
            with self.subTest(bad=bad):
                self.assertEqual(self.call("post", "clubs/", bad).status_code, 400)
        self.assertFalse(Club.objects.exists())
        r = self.call("post", "clubs/", {**good, "latitude": "-90", "longitude": "180"}, 201)
        club = r.data["id"]

        # CLUB-3: the base currency is fixed, the same value is harmless, bad input is still a field error first
        r = self.call("patch", f"clubs/{club}/", {"currency": "EUR"}, 400)
        self.assertEqual(r.data["code"], "base_currency_fixed")
        self.call("patch", f"clubs/{club}/", {"currency": "USD", "name": "Same"}, 200)
        r = self.call("patch", f"clubs/{club}/", {"currency": "EUR", "name": ""}, 400)
        self.assertIn("name", r.data)
        self.assertEqual(Club.objects.get().currency, "USD")
        self.assertEqual(self.call("patch", f"clubs/{club}/", {"timezone": "Nope/Nope"}).status_code, 400)

        # CLUB-5: not the base, not twice; PRC-2: > 0, at most 6 decimals
        r = self.call("post", f"clubs/{club}/currencies/", {"currency": "USD", "exchange_rate": "1"}, 400)
        self.assertEqual(r.data["code"], "currency_exists")
        self.call("post", f"clubs/{club}/currencies/", {"currency": "EUR", "exchange_rate": "0.923457"}, 201)
        r = self.call("post", f"clubs/{club}/currencies/", {"currency": "EUR", "exchange_rate": "0.9"}, 400)
        self.assertEqual(r.data["code"], "currency_exists")
        for bad in ({"currency": "GBP", "exchange_rate": "0"}, {"currency": "GBP", "exchange_rate": "-1"},
                    {"currency": "GBP", "exchange_rate": "1.1234567"}, {"currency": "gbp", "exchange_rate": "1"},
                    {"currency": "GBP", "exchange_rate": "abc"}, {"currency": "GBP"}, {"exchange_rate": "1"},
                    {"currency": "GBP", "exchange_rate": "1000000000000"}):
            with self.subTest(bad=bad):
                r = self.call("post", f"clubs/{club}/currencies/", bad)
                self.assertEqual(r.status_code, 400)
                self.assertNotIn("code", r.data)  # a field error, not a business refusal
        self.call("post", f"clubs/{club}/currencies/", {"currency": "GBP", "exchange_rate": "0.000001"}, 201)
        eur = ClubCurrency.objects.get(currency="EUR")
        self.call("patch", f"currencies/{eur.id}/", {"exchange_rate": "0"}, 400)
        self.call("patch", f"currencies/{eur.id}/", {"exchange_rate": "0.1234567"}, 400)
        self.assertEqual(ClubCurrency.objects.get(currency="EUR").exchange_rate, Decimal("0.923457"))

        # CLUB-8: name, slot length, sports, ids
        court = {"name": "Court 1", "slot_minutes": 60, "sports": [self.basketball.id]}
        for bad in ({**court, "name": ""}, {**court, "slot_minutes": 10}, {**court, "slot_minutes": 485}, {**court, "slot_minutes": 17},
                    {**court, "slot_minutes": 480 + 5}, {**court, "sports": []}, {**court, "sports": [9999]}, {"name": "x", "slot_minutes": 60}):
            with self.subTest(bad=bad):
                self.assertEqual(self.call("post", f"clubs/{club}/courts/", bad).status_code, 400)
        r = self.call("post", f"clubs/{club}/courts/", {**court, "sports": [9999]}, 400)
        self.assertEqual(str(r.data["sports"][0]), "Not found.")  # GEN-18
        for ok in (15, 480, 90):
            self.call("post", f"clubs/{club}/courts/", {**court, "slot_minutes": ok}, 201)
        self.assertEqual(self.call("patch", f"courts/{Court.objects.first().id}/", {"sports": []}).status_code, 400)

    def test_rates_overlap_and_typed_money(self):
        """CLUB-11, CLUB-12, CLUB-13, CLUB-18, GEN-11, GEN-17, GEN-18: windows, overlaps and decimals per currency."""
        owner = self.user("owner@example.com")
        club, court = self.club_with_court(owner)
        other_club, other_court = self.club_with_court(self.user("other@example.com"), name="Other")
        second = Court.objects.create(club=club, name="Court 2", slot_minutes=60)
        self.as_user(owner)
        rates = f"courts/{court.id}/rates/"

        def rate(start, end, weekday=0, price="10"):
            return {"weekday": weekday, "start_time": start, "end_time": end, "price": price}

        for bad in (rate("09:00", "09:00"), rate("10:00", "09:00"), rate("09:07", "10:00"), rate("09:00", "10:03"),
                    rate("09:00:30", "10:00"), rate("09:00", "10:00", weekday=7), rate("09:00", "10:00", weekday=-1),
                    rate("09:00", "10:00", price="-1"), rate("09:00", "10:00", price="10.001"), rate("09:00", "10:00", price="x"),
                    {"weekday": 0, "start_time": "09:00", "price": "1"}):
            with self.subTest(bad=bad):
                self.assertEqual(self.call("post", rates, bad).status_code, 400)
        self.call("post", rates, rate("09:00", "10:00", price="10.5"), 201)

        # CLUB-12: overlap is refused, touching is fine, other weekday and other court are free
        for start, end in (("09:30", "10:30"), ("08:00", "09:05"), ("09:00", "10:00"), ("08:00", "11:00"), ("09:15", "09:45")):
            with self.subTest(start=start, end=end):
                r = self.call("post", rates, rate(start, end), 400)
                self.assertEqual(r.data["code"], "rate_overlap")
        self.call("post", rates, rate("10:00", "11:00"), 201)  # touching after
        self.call("post", rates, rate("08:00", "09:00"), 201)  # touching before
        self.call("post", rates, rate("09:00", "10:00", weekday=1), 201)
        self.call("post", f"courts/{second.id}/rates/", rate("09:00", "10:00"), 201)

        # 00:00 as the end counts as 24:00
        late = self.call("post", rates, rate("22:00", "00:00"), 201).data
        self.assertEqual(self.call("post", rates, rate("23:00", "23:30"), 400).data["code"], "rate_overlap")
        self.assertEqual(self.call("post", rates, rate("21:00", "22:05"), 400).data["code"], "rate_overlap")
        self.call("post", rates, rate("21:00", "22:00"), 201)
        self.call("post", rates, rate("00:00", "08:00"), 201)  # midnight start is a start, not an end
        r = self.call("post", rates, rate("11:00", "00:00"), 400)  # 11:00-24:00 swallows 22:00-24:00
        self.assertEqual(r.data["code"], "rate_overlap")

        # changing a rate: itself is not an overlap, others are
        self.call("patch", f"rates/{late['id']}/", {"start_time": "23:00"}, 200)
        self.call("patch", f"rates/{late['id']}/", {"start_time": "22:00", "end_time": "23:00"}, 200)
        r = self.call("patch", f"rates/{late['id']}/", {"start_time": "21:30"}, 400)
        self.assertEqual(r.data["code"], "rate_overlap")
        self.call("patch", f"rates/{late['id']}/", {"weekday": 2}, 200)
        self.call("patch", f"rates/{late['id']}/", {"end_time": "21:00"}, 400)  # end before the stored start (GEN-11)
        self.call("patch", f"rates/{late['id']}/", {"end_time": "00:00"}, 200)

        # GEN-17 on a rate: decimals follow the base currency's minor units
        lbp_club, lbp_court = self.club_with_court(owner, name="Beirut LBP", currency="LBP")
        kwd_club, kwd_court = self.club_with_court(owner, name="Kuwait", currency="KWD")
        self.call("post", f"courts/{lbp_court.id}/rates/", rate("09:00", "10:00", price="1000.5"), 400)
        self.call("post", f"courts/{lbp_court.id}/rates/", rate("09:00", "10:00", price="1000"), 201)
        self.call("post", f"courts/{kwd_court.id}/rates/", rate("09:00", "10:00", price="1.2345"), 400)
        self.call("post", f"courts/{kwd_court.id}/rates/", rate("09:00", "10:00", price="1.234"), 201)
        r = self.call("post", rates, rate("12:00", "13:00", price="0"), 201)  # PRC-12: free time is allowed
        self.assertEqual(r.data["price"], "0.000")

        # CLUB-13: deleting a rate deletes its overrides, later bookings only
        evening = CourtRate.objects.create(court=court, weekday=5, start_time=dt.time(17), end_time=dt.time(0), price=70)
        ClubCurrency.objects.create(club=club, currency="EUR", exchange_rate=Decimal("0.9"))
        PriceOverride.objects.create(court_rate=evening, currency="EUR", price=65)
        self.call("delete", f"rates/{evening.id}/", expect=204)
        self.assertFalse(PriceOverride.objects.exists())

        # CLUB-18, GEN-17, GEN-18: equipment input
        eq = f"clubs/{club.id}/equipment/"
        for bad in ({"name": "Net", "quantity": 0}, {"name": "", "quantity": 1}, {"name": "Net", "quantity": -1}, {"name": "Net"},
                    {"name": "Net", "quantity": 1, "rental_price": "-1"}, {"name": "Net", "quantity": 1, "rental_price": "1.234"},
                    {"name": "Net", "quantity": 1, "court": other_court.id}, {"name": "Net", "quantity": 1, "court": 9999}):
            with self.subTest(bad=bad):
                self.assertEqual(self.call("post", eq, bad).status_code, 400)
        r = self.call("post", eq, {"name": "Net", "quantity": 1, "court": other_court.id}, 400)
        self.assertEqual(str(r.data["court"][0]), "Not found.")
        net = self.call("post", eq, {"name": "Net", "quantity": 1, "court": court.id, "rental_price": "2.50"}, 201).data
        self.call("patch", f"equipment/{net['id']}/", {"court": None, "rental_price": None}, 200)  # shared and free
        self.call("patch", f"equipment/{net['id']}/", {"court": other_court.id}, 400)
        self.call("post", f"clubs/{lbp_club.id}/equipment/", {"name": "Ball", "quantity": 1, "rental_price": "100.5"}, 400)
        self.call("post", f"clubs/{lbp_club.id}/equipment/", {"name": "Ball", "quantity": 1, "rental_price": "100"}, 201)

        # the other owner's data is invisible: a rate of theirs is 404 for us (GEN-3)
        theirs = CourtRate.objects.create(court=other_court, weekday=0, start_time=dt.time(9), end_time=dt.time(10), price=1)
        self.call("patch", f"rates/{theirs.id}/", {"price": "2"}, 403)  # their club is public, so 403
        other_court.is_active = False
        other_court.save()
        self.call("patch", f"rates/{theirs.id}/", {"price": "2"}, 404)

    def test_overrides_offers_members_validation(self):
        """CLUB-20, CLUB-22, CLUB-25, CLUB-26, CLUB-27, PRC-1, PRC-3, GEN-5, GEN-6, GEN-7, GEN-17, GEN-18: override, offer
        and member input rules and their error codes."""
        owner = self.user("owner@example.com")
        club, court = self.club_with_court(owner)
        other_club, other_court = self.club_with_court(self.user("other@example.com"), name="Other")
        rate = CourtRate.objects.create(court=court, weekday=0, start_time=dt.time(9), end_time=dt.time(17), price=50)
        other_rate = CourtRate.objects.create(court=other_court, weekday=0, start_time=dt.time(9), end_time=dt.time(17), price=50)
        item = Equipment.objects.create(club=club, name="Machine", quantity=1, rental_price=15)
        free_item = Equipment.objects.create(club=club, name="Balls", quantity=3)
        ClubCurrency.objects.create(club=club, currency="EUR", exchange_rate=Decimal("0.9"))
        ClubCurrency.objects.create(club=club, currency="LBP", exchange_rate=Decimal("89500"))
        self.as_user(owner)
        ov = f"clubs/{club.id}/overrides/"

        # CLUB-20: exactly one target, an accepted non-base currency, one per target and currency
        for bad in ({"currency": "EUR", "price": "1"}, {"court_rate": rate.id, "equipment": item.id, "currency": "EUR", "price": "1"},
                    {"court_rate": rate.id, "currency": "EUR", "price": "-1"}, {"court_rate": rate.id, "currency": "EUR", "price": "1.234"},
                    {"court_rate": rate.id, "currency": "LBP", "price": "6000000.5"}, {"court_rate": rate.id, "currency": "eur", "price": "1"},
                    {"court_rate": rate.id, "currency": "EUR"}, {"equipment": free_item.id, "currency": "EUR", "price": "1"},
                    {"court_rate": other_rate.id, "currency": "EUR", "price": "1"}, {"court_rate": 9999, "currency": "EUR", "price": "1"}):
            with self.subTest(bad=bad):
                r = self.call("post", ov, bad)
                self.assertEqual(r.status_code, 400)
                self.assertNotIn("code", r.data)
        r = self.call("post", ov, {"court_rate": other_rate.id, "currency": "EUR", "price": "1"}, 400)
        self.assertEqual(str(r.data["court_rate"][0]), "Not found.")
        for currency in ("USD", "GBP"):  # the base, and a currency the club does not accept
            r = self.call("post", ov, {"court_rate": rate.id, "currency": currency, "price": "1"}, 400)
            self.assertEqual(r.data["code"], "currency_not_accepted")
        self.call("post", ov, {"court_rate": rate.id, "currency": "LBP", "price": "6000000"}, 201)
        self.call("post", ov, {"equipment": item.id, "currency": "LBP", "price": "1300000"}, 201)
        r = self.call("post", ov, {"court_rate": rate.id, "currency": "LBP", "price": "1"}, 400)
        self.assertEqual(r.data["code"], "override_exists")
        r = self.call("post", ov, {"equipment": item.id, "currency": "LBP", "price": "1"}, 400)
        self.assertEqual(r.data["code"], "override_exists")
        self.call("post", ov, {"court_rate": rate.id, "currency": "EUR", "price": "65.25"}, 201)
        mine = PriceOverride.objects.get(court_rate=rate, currency="LBP")
        self.call("patch", f"overrides/{mine.id}/", {"price": "10.5"}, 400)  # LBP has no decimals
        self.call("patch", f"overrides/{mine.id}/", {"price": "-1"}, 400)
        self.call("patch", f"overrides/{mine.id}/", {"price": "7000000"}, 200)
        self.call("delete", f"overrides/{mine.id}/", expect=204)
        self.assertEqual(PriceOverride.objects.count(), 2)

        # CLUB-22: offers, errors per field
        of = f"clubs/{club.id}/offers/"
        win = {"starts_at": "2027-01-01T00:00:00Z", "ends_at": "2027-02-01T00:00:00Z"}
        shadow = User.objects.create_user(email="", full_name="Kid", managed_by=self.user("coach@example.com", is_coach=True))
        gone = self.user("gone@example.com", is_active=False)
        for field_bad in (
            {"percent_off": "0"}, {"percent_off": "100.01"}, {"percent_off": "-5"}, {"percent_off": "10.123"}, {"amount_off": "0"},
            {"amount_off": "-1"}, {"amount_off": "1.234"}, {"percent_off": "5", "min_bookings": 0},
            {"percent_off": "5", "message": "x" * 1001}, {"percent_off": "5", "court": other_court.id},
            {"percent_off": "5", "user": shadow.id}, {"percent_off": "5", "user": gone.id}, {"percent_off": "5", "user": 9999},
            {"percent_off": "5", "ends_at": "2026-12-01T00:00:00Z"}, {"percent_off": "5", "ends_at": win["starts_at"]},
            {"percent_off": "5", "starts_at": "2027-01-01T00:00:00"}, {},
        ):
            with self.subTest(bad=field_bad):
                self.assertEqual(self.call("post", of, {**win, **field_bad}).status_code, 400)
        r = self.call("post", of, {**win, "percent_off": "5", "amount_off": "5"}, 400)
        self.assertNotIn("code", r.data)
        self.assertEqual(str(self.call("post", of, {**win, "percent_off": "5", "court": other_court.id}, 400).data["court"][0]), "Not found.")
        self.call("post", of, {**win, "percent_off": "100", "message": "x" * 1000}, 201)
        offer = self.call("post", of, {**win, "percent_off": "12.5"}, 201).data
        self.assertEqual(offer["percent_off"], "12.50")
        self.call("patch", f"offers/{offer['id']}/", {"amount_off": "3"}, 400)  # both kinds at once
        self.call("patch", f"offers/{offer['id']}/", {"amount_off": "3", "percent_off": None}, 200)
        self.call("patch", f"offers/{offer['id']}/", {"ends_at": "2026-01-01T00:00:00Z"}, 400)  # before the stored start
        lbp_club, _ = self.club_with_court(owner, name="LBP club", currency="LBP")
        self.call("post", f"clubs/{lbp_club.id}/offers/", {**win, "amount_off": "100.5"}, 400)  # PRC-3: base minor units
        self.call("post", f"clubs/{lbp_club.id}/offers/", {**win, "amount_off": "100"}, 201)

        # CLUB-25: members by email
        mem = f"clubs/{club.id}/members/"
        staff = self.user("staff@example.com")
        for bad in ({"email": "staff@example.com"}, {"role": "staff"}, {"email": "nope", "role": "staff"},
                    {"email": "staff@example.com", "role": "coach"}, {"email": "staff@example.com", "role": "owner"},
                    {"email": "owner@example.com", "role": "staff"}, {"email": "staff@example.com", "role": "staff", "expires_on": "2020-01-01"}):
            with self.subTest(bad=bad):
                self.assertEqual(self.call("post", mem, bad).status_code, 400)
        r = self.call("post", mem, {"email": "unknown@example.com", "role": "staff"}, 400)
        self.assertEqual(r.data["code"], "user_not_found")
        r = self.call("post", mem, {"email": "gone@example.com", "role": "player"}, 400)
        self.assertEqual(r.data["code"], "user_not_found")
        self.call("post", mem, {"email": "staff@example.com", "role": "staff"}, 201)
        r = self.call("post", mem, {"email": "Staff@Example.com", "role": "staff"}, 400)
        self.assertEqual(r.data["code"], "member_exists")
        self.call("post", mem, {"email": "staff@example.com", "role": "player"}, 201)  # another role is another row
        self.assertEqual(ClubMember.objects.count(), 2)

        # CLUB-26: only coaches ask; a repeat is member_exists; approval repeats are harmless (GEN-5)
        self.call("post", f"clubs/{club.id}/coach-requests/", user=staff, expect=403)
        coach = User.objects.get(email="coach@example.com")
        self.call("post", f"clubs/{club.id}/coach-requests/", user=coach, expect=201)
        r = self.call("post", f"clubs/{club.id}/coach-requests/", expect=400)
        self.assertEqual(r.data["code"], "member_exists")
        self.call("post", f"clubs/{club.id}/coach-requests/", user=self.user("late@example.com", is_coach=True), expect=201)
        row = ClubMember.objects.get(user=coach)
        self.call("post", f"members/{row.id}/approve/", user=owner, expect=200)
        self.call("post", f"members/{row.id}/approve/", expect=200)
        r = self.call("post", f"clubs/{club.id}/coach-requests/", user=coach, expect=400)  # still member_exists once active
        self.assertEqual(r.data["code"], "member_exists")
        hidden_club, _ = self.club_with_court(self.user("h@example.com"), name="Hidden", active=False)
        self.call("post", f"clubs/{hidden_club.id}/coach-requests/", user=coach, expect=404)  # GEN-18: not visible

        # CLUB-27: the owner rejects a pending coach by deleting the row
        late = ClubMember.objects.get(user__email="late@example.com")
        self.call("delete", f"members/{late.id}/", user=owner, expect=204)
        self.assertFalse(ClubMember.objects.filter(pk=late.id).exists())
        self.call("delete", f"members/{late.id}/", expect=404)

    def test_closure_conflicts_never_cancel(self):
        """CLUB-15, CLUB-16, CLUB-17, AVL-8, GEN-10, GEN-11: a closure lists future sessions in its way and cancels nothing;
        past, cancelled, touching and other-day sessions are not listed."""
        owner = self.user("owner@example.com")
        club, court = self.club_with_court(owner)
        other_court = Court.objects.create(club=club, name="Court 2", slot_minutes=60)
        self.as_user(owner)
        mon = lambda d: dt.date(2027, 1, d)  # noqa: E731  Mondays: 4, 11, 18, 25
        a = self.session(court, at(mon(11), 16), at(mon(11), 18))  # overlaps 17:00-19:00
        touching = self.session(court, at(mon(11), 15), at(mon(11), 17))  # ends when the closure starts
        tuesday = self.session(court, at(dt.date(2027, 1, 12), 17), at(dt.date(2027, 1, 12), 18))
        d = self.session(court, at(mon(18), 18), at(mon(18), 19), status="requested")  # second occurrence
        cancelled = self.session(court, at(mon(11), 17, 30), at(mon(11), 18), status="cancelled")
        past = self.session(court, at(dt.date(2026, 12, 28), 17), at(dt.date(2026, 12, 28), 18))  # starts before now
        elsewhere = self.session(other_court, at(mon(11), 17), at(mon(11), 18))
        before = list(Session.objects.order_by("pk").values())

        with mock.patch("django.utils.timezone.now", return_value=NOW):
            body = {"starts_on": "2026-12-28", "start_time": "17:00", "end_time": "19:00", "repeat": "weekly"}
            r = self.call("post", f"courts/{court.id}/closures/", body, 201)
            closure = r.data["id"]
            self.assertEqual([c["id"] for c in r.data["conflicts"]], [a.id, d.id])
            self.assertEqual(r.data["conflicts"][0]["starts_at"], "2027-01-11T14:00:00Z")
            self.assertEqual(r.data["conflicts"][0]["status"], "confirmed")
            self.assertEqual(self.call("get", f"courts/{court.id}/closures/").data["count"], 1)

            # CLUB-16: changing it lists the conflicts again; ending the series early drops the later session
            r = self.call("patch", f"closures/{closure}/", {"repeat_until": "2027-01-11"}, 200)
            self.assertEqual([c["id"] for c in r.data["conflicts"]], [a.id])
            r = self.call("patch", f"closures/{closure}/", {"repeat": "none", "repeat_until": None, "starts_on": "2027-01-18"}, 200)
            self.assertEqual([c["id"] for c in r.data["conflicts"]], [d.id])

            # a whole-day closure (00:00-00:00) reaches a session that crosses midnight into it
            crossing = self.session(court, at(dt.date(2027, 1, 31), 23), at(dt.date(2027, 2, 1), 1))
            r = self.call("post", f"courts/{court.id}/closures/", {"starts_on": "2027-02-01", "start_time": "00:00", "end_time": "00:00"}, 201)
            self.assertEqual([c["id"] for c in r.data["conflicts"]], [crossing.id])
            r = self.call("post", f"courts/{court.id}/closures/", {"starts_on": "2027-02-02", "start_time": "00:00", "end_time": "00:00"}, 201)
            self.assertEqual(r.data["conflicts"], [])  # the crossing session ended before 02-02

            # AVL-8: a monthly closure from the 31st skips months without that day
            feb = self.session(court, at(dt.date(2027, 2, 28), 10), at(dt.date(2027, 2, 28), 11))
            mar = self.session(court, at(dt.date(2027, 3, 31), 10), at(dt.date(2027, 3, 31), 11))
            r = self.call("post", f"courts/{court.id}/closures/", {"starts_on": "2027-01-31", "start_time": "09:00", "end_time": "12:00", "repeat": "monthly"}, 201)
            self.assertEqual([c["id"] for c in r.data["conflicts"]], [mar.id])

            # CLUB-17: delete at any time; sessions are untouched
            self.call("delete", f"closures/{closure}/", expect=204)

        self.assertEqual(list(Session.objects.order_by("pk").values())[: len(before)], before)  # CLUB-16: nothing cancelled
        self.assertEqual(Session.objects.exclude(status="cancelled").count(), Session.objects.count() - 1)
        for s in (touching, tuesday, cancelled, past, elsewhere, feb):  # kept their status
            s.refresh_from_db()

        # CLUB-15: validation (GEN-11)
        for bad in ({"starts_on": "2027-02-01", "start_time": "10:00", "end_time": "09:00"}, {"starts_on": "2027-02-01", "start_time": "10:00", "end_time": "10:00"},
                    {"starts_on": "2027-02-01", "start_time": "09:00", "end_time": "10:00", "repeat": "yearly"},
                    {"starts_on": "2027-02-01", "start_time": "09:00", "end_time": "10:00", "repeat": "weekly", "repeat_until": "2027-01-31"},
                    {"start_time": "09:00", "end_time": "10:00"}):
            with self.subTest(bad=bad):
                self.assertEqual(self.call("post", f"courts/{court.id}/closures/", bad).status_code, 400)
        self.call("post", f"courts/{court.id}/closures/", {"starts_on": "2027-02-01", "start_time": "09:00", "end_time": "00:00", "repeat": "daily", "repeat_until": "2027-02-01"}, 201)

    def test_deleting_courts_equipment_currencies_and_rates(self):
        """CLUB-7, CLUB-10, CLUB-13, CLUB-19, PRC-11: deletes are refused when sessions or rentals exist and cascade otherwise."""
        owner = self.user("owner@example.com")
        club, busy = self.club_with_court(owner)
        quiet = Court.objects.create(club=club, name="Quiet", slot_minutes=60)
        ClubCurrency.objects.create(club=club, currency="EUR", exchange_rate=Decimal("0.9"))
        ClubCurrency.objects.create(club=club, currency="LBP", exchange_rate=Decimal("89500"))
        self.as_user(owner)

        # CLUB-10: a court with any session (even cancelled) cannot be deleted
        session = self.session(busy, at(dt.date(2027, 1, 11), 10), at(dt.date(2027, 1, 11), 11), status="cancelled")
        busy_rate = CourtRate.objects.create(court=busy, weekday=0, start_time=dt.time(9), end_time=dt.time(17), price=50)
        r = self.call("delete", f"courts/{busy.id}/", expect=400)
        self.assertEqual(r.data["code"], "court_in_use")
        self.assertTrue(Court.objects.filter(pk=busy.pk).exists() and CourtRate.objects.filter(pk=busy_rate.pk).exists())
        self.call("patch", f"courts/{busy.id}/", {"is_active": False}, 200)  # the alternative

        # CLUB-10: a quiet court goes with its rates, closures, tied equipment, overrides and tied offers; the rest stays
        rate = CourtRate.objects.create(court=quiet, weekday=0, start_time=dt.time(9), end_time=dt.time(17), price=50)
        CourtBlockout.objects.create(court=quiet, starts_on=dt.date(2027, 1, 1), start_time=dt.time(0), end_time=dt.time(0))
        tied = Equipment.objects.create(club=club, court=quiet, name="Tied", quantity=1, rental_price=5)
        shared = Equipment.objects.create(club=club, name="Shared", quantity=1, rental_price=5)
        PriceOverride.objects.create(court_rate=rate, currency="EUR", price=45)
        PriceOverride.objects.create(equipment=tied, currency="EUR", price=4)
        PriceOverride.objects.create(equipment=shared, currency="EUR", price=4)
        window = {"starts_at": NOW, "ends_at": NOW + dt.timedelta(days=9)}
        Discount.objects.create(club=club, court=quiet, percent_off=10, **window)
        Discount.objects.create(club=club, percent_off=10, **window)
        self.call("delete", f"courts/{quiet.id}/", expect=204)
        self.assertEqual((CourtRate.objects.count(), CourtBlockout.objects.count(), Equipment.objects.get().name), (1, 0, "Shared"))
        self.assertEqual(list(PriceOverride.objects.values_list("equipment__name", flat=True)), ["Shared"])
        self.assertEqual((Discount.objects.count(), Discount.objects.get().court), (1, None))
        self.call("delete", f"courts/{quiet.id}/", expect=404)

        # CLUB-19: an item that was rented cannot be deleted; emptying its price is allowed and keeps the rental
        SessionRental.objects.create(session=session, equipment=shared, quantity=1, price=Decimal("5"))
        r = self.call("delete", f"equipment/{shared.id}/", expect=400)
        self.assertEqual(r.data["code"], "equipment_in_use")
        self.call("patch", f"equipment/{shared.id}/", {"rental_price": None}, 200)
        self.assertEqual(SessionRental.objects.get().price, Decimal("5.000"))
        free = Equipment.objects.create(club=club, name="Free", quantity=1)
        self.call("delete", f"equipment/{free.id}/", expect=204)

        # CLUB-7: removing a currency deletes the club's overrides in it, and only those; sessions keep their currency
        PriceOverride.objects.all().delete()
        eur_rate = PriceOverride.objects.create(court_rate=busy_rate, currency="EUR", price=45)
        PriceOverride.objects.create(court_rate=busy_rate, currency="LBP", price=4_000_000)
        PriceOverride.objects.create(equipment=shared, currency="EUR", price=4)
        other_club, other_court = self.club_with_court(self.user("other@example.com"), name="Other")
        ClubCurrency.objects.create(club=other_club, currency="EUR", exchange_rate=Decimal("0.8"))
        other_rate = CourtRate.objects.create(court=other_court, weekday=0, start_time=dt.time(9), end_time=dt.time(10), price=5)
        PriceOverride.objects.create(court_rate=other_rate, currency="EUR", price=4)
        paid_in_eur = self.session(busy, at(dt.date(2027, 1, 18), 10), at(dt.date(2027, 1, 18), 11), currency="EUR")
        eur = ClubCurrency.objects.get(club=club, currency="EUR")
        self.call("delete", f"currencies/{eur.id}/", expect=204)
        self.assertEqual(sorted(PriceOverride.objects.values_list("currency", "court_rate__court__club__name")), [("EUR", "Other"), ("LBP", "Hoops")])
        self.assertEqual(Session.objects.get(pk=paid_in_eur.pk).currency, "EUR")
        self.assertEqual(list(club.currencies.values_list("currency", flat=True)), ["LBP"])
        self.assertFalse(PriceOverride.objects.filter(pk=eur_rate.pk).exists())

    def test_offer_pushes_the_targeted_user(self):
        """CLUB-24, NOTE-13, NOTE-14, NOTE-20: a targeted offer sends one `offer` push after commit; an open offer, a change or a
        refused create sends none."""
        owner = self.user("owner@example.com")
        club, court = self.club_with_court(owner)
        player = self.user("player@example.com")
        bystander = self.user("bystander@example.com")
        for who, token in ((player, "tok-player"), (bystander, "tok-bystander")):
            self.call("post", "devices/", {"token": token, "platform": "android"}, 201, user=who)
        self.as_user(owner)
        win = {"starts_at": "2027-01-01T00:00:00Z", "ends_at": "2027-02-01T00:00:00Z", "percent_off": "20"}

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            offer = self.call("post", f"clubs/{club.id}/offers/", {**win, "user": player.id, "message": "We miss you"}, 201).data
        self.assertEqual(len(callbacks), 1)  # sent on commit, not before
        self.assertEqual(len(services.outbox), 1)
        push = services.outbox[0]
        self.assertEqual((push["user_id"], push["token"], push["body"]), (player.id, "tok-player", "We miss you"))
        self.assertEqual(push["data"], {"id": str(offer["id"]), "type": "offer"})

        services.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.call("post", f"clubs/{club.id}/offers/", win, 201)  # for everyone: nobody is notified
            self.call("patch", f"offers/{offer['id']}/", {"message": "Changed"}, 200)
            self.call("post", f"clubs/{club.id}/offers/", {**win, "user": player.id, "percent_off": "500"}, 400)
        self.assertEqual(services.outbox, [])

    def test_public_search(self):
        """CLUB-30, ACC-3: search needs no token, filters by sport, name and location, sorts and pages, and leaves out clubs
        without an active court."""
        owner = self.user("owner@example.com")

        def club(name, lat=None, lng=None, sport=self.basketball, active=True):
            c = Club.objects.create(owner=owner, name=name, timezone="UTC", currency="USD", latitude=lat, longitude=lng)
            court = Court.objects.create(club=c, name="Court", slot_minutes=60, is_active=active)
            court.sports.set([sport])
            return c

        # on the equator, one degree of longitude or latitude is 111.195 km: 0.1 deg = 11.1 km, 0.2 = 22.2, 0.3 = 33.4
        club("Alpha Far", 0.3, 0)
        club("Zulu Near", 0, 0.1, sport=self.volleyball)
        club("Mike Mid", 0.2, 0)
        club("No location")
        club("Hoops Closed", 0, 0.05, active=False)
        Court.objects.create(club=Club.objects.get(name="Hoops Closed"), name="Spare", slot_minutes=60, is_active=False)
        club("Hoops North", 60, 0)
        both = club("Both Courts", 0.1, 0.1)  # two active courts, one per sport: still one row
        extra = Court.objects.create(club=both, name="Second", slot_minutes=60)
        extra.sports.set([self.volleyball])
        self.client.force_authenticate(None)

        r = self.call("get", "clubs/", expect=200)  # no location: sorted by name, no distance
        names = [c["name"] for c in r.data["results"]]
        self.assertEqual(names, ["Alpha Far", "Both Courts", "Hoops North", "Mike Mid", "No location", "Zulu Near"])
        self.assertEqual(r.data["count"], 6)
        self.assertIsNone(r.data["results"][0]["distance_km"])
        self.assertEqual([c["name"] for c in r.data["results"][1]["courts"]], ["Court", "Second"])
        self.assertEqual(sorted(r.data["results"][0]), ["address", "courts", "currency", "distance_km", "id", "latitude", "longitude", "name", "timezone"])

        def search(**params):
            r = self.client.get("/api/clubs/", params)
            self.assertEqual(r.status_code, 200, (params, r.data))
            return [c["name"] for c in r.data["results"]], r.data["results"]

        self.assertEqual(search(sport=self.volleyball.id)[0], ["Both Courts", "Zulu Near"])
        self.assertEqual(search(sport=self.basketball.id)[0], ["Alpha Far", "Both Courts", "Hoops North", "Mike Mid", "No location"])
        self.assertEqual(search(q="hoops")[0], ["Hoops North"])  # case-insensitive contains; the closed club is out
        self.assertEqual(search(q="o")[0], ["Both Courts", "Hoops North", "No location"])
        self.assertEqual(search(q="nothing")[0], [])
        self.assertEqual(search(sport=9999)[0], [])
        self.assertEqual(search(q="far", sport=self.basketball.id)[0], ["Alpha Far"])

        # location: distance sorted, 1 decimal, default radius 25 km, clubs without coordinates left out
        _, rows = search(lat=0, lng=0)
        self.assertEqual([(c["name"], c["distance_km"]) for c in rows], [("Zulu Near", 11.1), ("Both Courts", 15.7), ("Mike Mid", 22.2)])
        self.assertEqual(search(lat=0, lng=0, radius_km=50)[0], ["Zulu Near", "Both Courts", "Mike Mid", "Alpha Far"])
        self.assertEqual(search(lat=0, lng=0, radius_km=22.2)[0], ["Zulu Near", "Both Courts"])  # 22.24 is outside 22.2
        self.assertEqual(search(lat=0, lng=0, radius_km=1)[0], [])
        self.assertEqual(search(lat=0, lng=0, radius_km=200)[0], ["Zulu Near", "Both Courts", "Mike Mid", "Alpha Far"])
        self.assertEqual(search(lat=0, lng=0, sport=self.volleyball.id)[0], ["Zulu Near", "Both Courts"])
        self.assertEqual(search(lat=0, lng=0, q="mid")[0], ["Mike Mid"])
        self.assertEqual(search(lat=60, lng=0)[0], ["Hoops North"])
        self.assertEqual(search(lat=60, lng=0)[1][0]["distance_km"], 0.0)

        # radius bounds and the other bad input are 400s (GEN-1)
        for bad in ({"lat": 0, "lng": 0, "radius_km": 0.9}, {"lat": 0, "lng": 0, "radius_km": 201}, {"lat": 0, "lng": 0, "radius_km": "far"},
                    {"lat": 0}, {"lng": 0}, {"lat": 91, "lng": 0}, {"lat": 0, "lng": 181}, {"lat": "x", "lng": 0}, {"sport": "x"}):
            with self.subTest(bad=bad):
                self.assertEqual(self.client.get("/api/clubs/", bad).status_code, 400)

        # paginated (GEN-12): 50 a page
        for i in range(50):
            club(f"Bulk {i:02d}")
        r = self.client.get("/api/clubs/", {"q": "bulk"})
        self.assertEqual((r.data["count"], len(r.data["results"]), r.data["previous"]), (50, 50, None))
        r = self.client.get("/api/clubs/")
        self.assertEqual((r.data["count"], len(r.data["results"])), (56, 50))
        self.assertEqual(len(self.client.get("/api/clubs/", {"page": 2}).data["results"]), 6)
        self.assertEqual(self.client.get("/api/clubs/", {"page": 3}).status_code, 404)

    def test_public_court_detail(self):
        """CLUB-31, ACC-3, PRC-3: court detail needs no sign-in: club, accepted currencies, rates, and equipment split into
        included and rentable (prices in base only); an inactive court is 404."""
        owner = self.user("owner@example.com")
        club, court = self.club_with_court(owner, name="Hoops")
        court.sports.set([self.basketball, self.volleyball])
        court.description = "Indoor"
        court.save()
        other = Court.objects.create(club=club, name="Court 2", slot_minutes=90)
        ClubCurrency.objects.create(club=club, currency="EUR", exchange_rate=Decimal("0.923457"))
        CourtRate.objects.create(court=court, weekday=1, start_time=dt.time(9), end_time=dt.time(17), price=40)
        evening = CourtRate.objects.create(court=court, weekday=0, start_time=dt.time(17), end_time=dt.time(0), price=70)
        CourtRate.objects.create(court=court, weekday=0, start_time=dt.time(9), end_time=dt.time(17), price=50)
        CourtRate.objects.create(court=other, weekday=0, start_time=dt.time(9), end_time=dt.time(17), price=999)
        PriceOverride.objects.create(court_rate=evening, currency="EUR", price=65)
        Equipment.objects.create(club=club, court=court, name="Basketballs", quantity=3)
        Equipment.objects.create(club=club, name="Cones", quantity=10)
        Equipment.objects.create(club=club, court=court, name="Ball machine", quantity=1, rental_price=Decimal("20"))
        Equipment.objects.create(club=club, name="Shooting machine", quantity=1, rental_price=Decimal("15"))
        Equipment.objects.create(club=club, court=other, name="Other court ball", quantity=1)
        Equipment.objects.create(club=club, court=other, name="Other court rental", quantity=1, rental_price=Decimal("1"))
        elsewhere = Club.objects.create(owner=owner, name="Elsewhere", timezone="UTC", currency="USD")
        Equipment.objects.create(club=elsewhere, name="Not ours", quantity=1)

        self.client.force_authenticate(None)
        d = self.call("get", f"courts/{court.id}/", expect=200).data
        self.assertEqual(d["club"], {
            "id": club.id, "name": "Hoops", "address": "", "latitude": None, "longitude": None, "timezone": "Asia/Beirut", "currency": "USD",
            "currencies": [{"id": mock.ANY, "currency": "EUR", "exchange_rate": "0.923457"}],
        })
        self.assertEqual(d["court"], {
            "id": court.id, "name": "Court 1", "description": "Indoor", "slot_minutes": 60, "is_active": True,
            "sports": [{"id": self.basketball.id, "name": "Basketball"}, {"id": self.volleyball.id, "name": "Volleyball"}],
        })
        self.assertEqual([(r["weekday"], r["start_time"], r["price"]) for r in d["rates"]],
                         [(0, "09:00:00", "50.000"), (0, "17:00:00", "70.000"), (1, "09:00:00", "40.000")])  # base only, no overrides
        self.assertEqual([e["name"] for e in d["equipment"]["included"]], ["Basketballs", "Cones"])
        self.assertEqual([(e["name"], e["rental_price"]) for e in d["equipment"]["rentable"]], [("Ball machine", "20.000"), ("Shooting machine", "15.000")])
        self.assertEqual([e["name"] for e in self.call("get", f"courts/{other.id}/", expect=200).data["equipment"]["included"]], ["Cones", "Other court ball"])

        # inactive: 404 for everyone, the owner included; unknown id too
        other.is_active = False
        other.save()
        for user in (None, owner):
            self.client.force_authenticate(user)
            self.call("get", f"courts/{other.id}/", expect=404)
        self.call("get", "courts/99999/", expect=404)
        self.client.force_authenticate(None)
        club_without_active, court_inactive = self.club_with_court(owner, name="Hidden", active=False)
        self.call("get", f"courts/{court_inactive.id}/", expect=404)

    def test_offers_shown_to_players(self):
        """CLUB-32, CLUB-22: a signed-in player sees running or future offers for them: ends_at after now, for everyone or for
        them, for no court or the given one; frequent-player offers show with min_bookings."""
        owner = self.user("owner@example.com")
        club, court = self.club_with_court(owner)
        court2 = Court.objects.create(club=club, name="Court 2", slot_minutes=60)
        player, other = self.user("player@example.com"), self.user("other@example.com")

        def offer(message, **fields):
            fields = {"starts_at": NOW - dt.timedelta(days=1), "ends_at": NOW + dt.timedelta(days=5), "percent_off": 10, **fields}
            return Discount.objects.create(club=club, message=message, **fields).id

        everyone = offer("everyone")
        mine = offer("for the player", user=player)
        offer("for someone else", user=other)
        frequent = offer("frequent", min_bookings=10)
        offer("ended", ends_at=NOW - dt.timedelta(seconds=1))
        offer("exactly now", ends_at=NOW)
        future = offer("future", starts_at=NOW + dt.timedelta(days=2), ends_at=NOW + dt.timedelta(days=9))
        on_court1 = offer("court 1", court=court)
        on_court2 = offer("court 2", court=court2)
        other_club, _ = self.club_with_court(other, name="Other")
        Discount.objects.create(club=other_club, percent_off=10, starts_at=NOW, ends_at=NOW + dt.timedelta(days=9))

        def seen(user, **params):
            self.as_user(user)
            r = self.client.get(f"/api/clubs/{club.id}/offers/", params)
            self.assertEqual(r.status_code, 200, r.data)
            return [o["id"] for o in r.data["results"]], r.data["results"]

        with mock.patch("django.utils.timezone.now", return_value=NOW):
            ids, rows = seen(player)
            self.assertEqual(ids, [everyone, mine, frequent, future])  # club-wide only when no court is given
            self.assertEqual({o["id"]: o["min_bookings"] for o in rows}[frequent], 10)  # shown whether or not they qualify
            self.assertEqual(seen(player, court=court.id)[0], [everyone, mine, frequent, future, on_court1])
            self.assertEqual(seen(player, court=court2.id)[0], [everyone, mine, frequent, future, on_court2])
            others = seen(other)[0]
            self.assertEqual(others[0], everyone)
            self.assertNotIn(mine, others)
            self.assertEqual(self.client.get(f"/api/clubs/{club.id}/offers/", {"court": "x"}).status_code, 400)

            # the owner sees every offer of the club
            self.assertEqual(len(seen(owner)[0]), Discount.objects.filter(club=club).count())

            # a club the player cannot see is 404; an unsigned caller is 401 (ACC-3)
            hidden, _ = self.club_with_court(owner, name="Hidden", active=False)
            self.as_user(player)
            self.call("get", f"clubs/{hidden.id}/offers/", expect=404)
            self.client.force_authenticate(None)
            self.call("get", f"clubs/{club.id}/offers/", expect=401)

    def test_membership_listing_expiry_and_leaving(self):
        """CLUB-25, CLUB-27, CLUB-28, CLUB-29, ACC-1, ACC-2, GEN-3, GEN-8, GEN-9: an expired row behaves as no membership; who may list, change,
        leave and remove rows; expiry is read in the club's timezone."""
        owner = self.user("owner@example.com")
        club, _ = self.club_with_court(owner)
        staff, coach, player, outsider, expiring = (
            self.user("staff@example.com"), self.user("coach@example.com", is_coach=True), self.user("player@example.com"),
            self.user("outsider@example.com"), self.user("expiring@example.com"),
        )
        # it is 2027-01-10 23:30 UTC, which is already 2027-01-11 01:30 in Beirut
        late = dt.datetime(2027, 1, 10, 23, 30, tzinfo=UTC)

        with mock.patch("django.utils.timezone.now", return_value=late):
            self.as_user(owner)
            m = f"clubs/{club.id}/members/"
            self.call("post", m, {"email": "staff@example.com", "role": "staff", "expires_on": "2027-01-10"}, 400)  # club-local today is the 11th
            staff_row = self.call("post", m, {"email": "staff@example.com", "role": "staff", "expires_on": "2027-01-11"}, 201).data["id"]
            player_row = self.call("post", m, {"email": "player@example.com", "role": "player"}, 201).data["id"]
            expiring_row = self.call("post", m, {"email": "expiring@example.com", "role": "player", "expires_on": "2027-02-01"}, 201).data["id"]
            coach_row = self.call("post", f"clubs/{club.id}/coach-requests/", user=coach, expect=201).data["id"]

            # a pending coach is not affiliated yet: they cannot list, but can see their row and leave
            self.call("get", m, user=coach, expect=404)
            self.call("post", f"members/{coach_row}/approve/", user=owner, expect=200)
            self.assertEqual(self.call("get", m, user=coach).data["count"], 4)

            # CLUB-29: the owner extends and clears expiry; other fields are not editable
            self.call("patch", f"members/{expiring_row}/", {"expires_on": "2027-01-11"}, user=owner, expect=200)
            r = self.call("patch", f"members/{player_row}/", {"expires_on": "2027-03-01", "status": "pending"}, expect=200)
            self.assertEqual((r.data["expires_on"], r.data["status"]), ("2027-03-01", "active"))
            self.call("patch", f"members/{player_row}/", {"expires_on": None}, expect=200)
            self.call("patch", f"members/{player_row}/", {"expires_on": "not a date"}, expect=400)

            # ACC-2: the staff row expires on the 11th (club time), still current today
            self.assertEqual(self.call("get", m, user=staff).data["count"], 4)

        # the next day it has expired: the row stays, but behaves as no membership
        next_day = dt.datetime(2027, 1, 11, 23, 30, tzinfo=UTC)  # the 12th in Beirut
        with mock.patch("django.utils.timezone.now", return_value=next_day):
            self.call("get", m, user=staff, expect=404)  # an expired staff member is not a member (ACC-2)
            listed = [(row["role"], row["user"]["full_name"]) for row in self.call("get", m, user=player).data["results"]]
            self.assertEqual(sorted(listed), [("coach", "Coach"), ("player", "Player")])  # expired rows are not listed to others
            owner_rows = self.call("get", m, user=owner).data["results"]
            self.assertEqual(len(owner_rows), 4)  # the owner still sees them all, to extend them
            self.assertTrue(ClubMember.objects.filter(pk=staff_row).exists())
            r = self.call("patch", f"members/{staff_row}/", {"expires_on": "2027-12-31"}, user=owner, expect=200)  # extend: restored
            self.assertEqual(r.data["expires_on"], "2027-12-31")
            self.assertEqual(self.call("get", m, user=staff).data["count"], 3)  # the expiring player (2027-01-11) is hidden
            self.call("patch", f"members/{staff_row}/", {"expires_on": "2020-01-01"}, user=owner, expect=200)  # the past is allowed on change

            # an outsider cannot list or see rows; a member cannot touch other rows; staff cannot remove anyone
            self.call("get", m, user=outsider, expect=404)
            self.call("delete", f"members/{player_row}/", user=outsider, expect=404)
            self.call("delete", f"members/{player_row}/", user=coach, expect=403)
            self.call("patch", f"members/{player_row}/", {"expires_on": None}, user=player, expect=403)  # not even their own
            self.call("delete", f"members/{player_row}/", user=staff, expect=404)  # expired staff cannot even see it
            self.assertEqual(ClubMember.objects.count(), 4)

            # CLUB-28: a member leaves; the owner removes any row; a gone row is 404
            self.call("delete", f"members/{player_row}/", user=player, expect=204)
            self.call("delete", f"members/{expiring_row}/", user=owner, expect=204)
            self.call("delete", f"members/{player_row}/", user=player, expect=404)
            self.assertEqual(sorted(ClubMember.objects.values_list("role", flat=True)), ["coach", "staff"])
            self.call("get", f"members/{staff_row}/", user=owner, expect=405)
            self.assertEqual(self.call("get", f"clubs/{club.id}/", user=outsider).status_code, 200)  # a public club

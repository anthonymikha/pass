import datetime as dt
import zoneinfo
from collections import Counter
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APITestCase

from accounts import services as accounts
from accounts.models import Connection, Device, User, UserBlockout
from billing.models import CommissionRate, Payment
from chat import services as chat_services
from chat.models import Chat, Message
from config.storage import UUID, get_storage
from teams.models import Group, GroupMember
from teams.services import coachs_players
from venues.models import (
    Club, ClubCurrency, ClubMember, Court, CourtBlockout, CourtRate, Discount, Equipment, PriceOverride, Sport,
)

from .models import Recording, RecordingTag, Session, SessionParticipant, SessionRental

PASSWORD = "court-side-42"
UTC = dt.timezone.utc
NOW = dt.datetime(2027, 1, 1, 0, 0, tzinfo=UTC)  # a Friday; Beirut is UTC+2 in January
MON, TUE = dt.date(2027, 1, 11), dt.date(2027, 1, 12)


def at(day, hour, minute=0):
    """A Beirut wall-clock time as a UTC instant (January, UTC+2)."""
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=UTC) - dt.timedelta(hours=2)


def z(instant):
    return instant.isoformat().replace("+00:00", "Z")


class BookingBase(APITestCase):
    """Club "Hoops" of the pricing worked example: Beirut, base USD, EUR at 0.923457, LBP at 89 500.
    Court 1 (60 min): Monday 09:00-17:00 at 50, 17:00-00:00 at 70, evening override EUR 65. Court 2: same day rate."""

    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=NOW)
        self.clock = patcher.start()
        self.addCleanup(patcher.stop)
        accounts.outbox.clear()
        self.basketball = Sport.objects.get_or_create(name="Basketball")[0]
        self.volleyball = Sport.objects.create(name="Volleyball")
        self.owner = self.user("olga")
        self.club = Club.objects.create(owner=self.owner, name="Hoops", timezone="Asia/Beirut", currency="USD")
        ClubCurrency.objects.create(club=self.club, currency="EUR", exchange_rate=Decimal("0.923457"))
        ClubCurrency.objects.create(club=self.club, currency="LBP", exchange_rate=Decimal("89500"))
        self.court1 = self.court("Court 1")
        self.day_rate = CourtRate.objects.create(
            court=self.court1, weekday=0, start_time=dt.time(9), end_time=dt.time(17), price=Decimal("50"))
        self.evening_rate = CourtRate.objects.create(
            court=self.court1, weekday=0, start_time=dt.time(17), end_time=dt.time(0), price=Decimal("70"))
        PriceOverride.objects.create(court_rate=self.evening_rate, currency="EUR", price=Decimal("65"))
        self.court2 = self.court("Court 2")
        CourtRate.objects.create(court=self.court2, weekday=0, start_time=dt.time(9), end_time=dt.time(17), price=Decimal("50"))
        self.shooting = Equipment.objects.create(club=self.club, name="Shooting machine", quantity=1, rental_price=Decimal("15"))

    # ---- builders ----

    def user(self, name, **fields):
        user = User.objects.create_user(f"{name}@example.com", PASSWORD, full_name=name.title(), **fields)
        Device.objects.create(user=user, token=f"tok-{name}", platform="web")  # so pushes reach them
        return user

    def court(self, name, club=None, slot=60, sports=None, active=True):
        court = Court.objects.create(club=club or self.club, name=name, slot_minutes=slot, is_active=active)
        court.sports.set(sports or [self.basketball])
        return court

    def befriend(self, a, b):
        Connection.objects.create(user=a, other_user=b, type="friend", status="accepted")

    def staff(self, user, club=None, **fields):
        return ClubMember.objects.create(club=club or self.club, user=user, role="staff", status="active", **fields)

    def session(self, court, start, end, booker, status="confirmed", **fields):
        session = Session.objects.create(
            court=court, sport=self.basketball, booked_by=booker, kind="play", status=status, starts_at=start,
            ends_at=end, currency="USD", price=Decimal("50"), **fields)
        SessionParticipant.objects.create(session=session, user=booker, status="accepted")
        return session

    def make_team(self, coach, members=(), name="Wolves"):
        team = Group.objects.create(type="team", name=name, created_by=coach, coach=coach)
        chat_services.create_group_chat(team, coach)
        for member in (coach, *members):
            GroupMember.objects.create(group=team, user=member, status="active")
        return team

    def shadow(self, name, coach):
        return User.objects.create_user(email=None, full_name=name, managed_by=coach)

    def past_bookings(self, user, n, court=None):
        """n confirmed December 2026 sessions of `user` (before NOW)."""
        for i in range(n):
            start = dt.datetime(2026, 12, 1 + i, 10, tzinfo=UTC)
            self.session(court or self.court1, start, start + dt.timedelta(hours=1), user)

    # ---- requests ----

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

    def body(self, start, end, court=None, currency="USD", **extra):
        return {"court": (court or self.court1).id, "sport": self.basketball.id, "starts_at": z(start),
                "ends_at": z(end), "currency": currency, **extra}

    def book(self, user, start, end, expect=201, push=False, **kwargs):
        return self.call("post", "sessions/", user, self.body(start, end, **kwargs), expect, push)

    def pushed(self, user, kind):
        return [p for p in accounts.outbox if p["user_id"] == user.id and p["data"]["type"] == kind]


class SlotTests(BookingBase):
    def slots(self, court, day, currency=None, expect=200):
        self.client.force_authenticate(None)  # public (AVL-10)
        suffix = f"&currency={currency}" if currency else ""
        r = self.client.get(f"/api/courts/{court.id}/slots/?date={day}{suffix}")
        self.assertEqual(r.status_code, expect, r.data)
        return r.data

    def test_free_slots_journey(self):
        """AVL-1, AVL-2, AVL-3, AVL-4, AVL-5, AVL-7, AVL-8, AVL-10, AVL-11, AVL-12, PRC-1, PRC-4, PRC-12, BOOK-3:
        offered slots, prices per currency, closures, sessions, the past, the 60-day horizon, inactive courts."""
        # AVL-1, AVL-4, AVL-11, PRC-4: Monday has 8 day slots and 7 evening slots; no sign-in needed
        data = self.slots(self.court1, MON)
        self.assertEqual(len(data), 15)
        self.assertEqual((data[0]["starts_at"], data[0]["ends_at"], data[0]["price"]),
                         ("2027-01-11T07:00:00Z", "2027-01-11T08:00:00Z", "50.000"))
        self.assertEqual((data[-1]["ends_at"], data[-1]["price"]), ("2027-01-11T22:00:00Z", "70.000"))  # ends at midnight, AVL-3
        # PRC-4: EUR 46.17285 -> 46.17, the evening override 65.00; LBP 50 x 89 500, 70 x 89 500
        eur = self.slots(self.court1, MON, "EUR")
        self.assertEqual((eur[7]["price"], eur[8]["price"]), ("46.170", "65.000"))
        lbp = self.slots(self.court1, MON, "LBP")
        self.assertEqual((lbp[7]["price"], lbp[8]["price"]), ("4475000.000", "6265000.000"))
        self.assertEqual(self.slots(self.court1, MON, "USD")[7]["price"], "50.000")
        # PRC-12: a free rate costs 0
        CourtRate.objects.create(court=self.court1, weekday=2, start_time=dt.time(9), end_time=dt.time(10), price=0)
        self.assertEqual(self.slots(self.court1, dt.date(2027, 1, 13), "LBP")[0]["price"], "0.000")

        # AVL-12: errors
        r = self.client.get(f"/api/courts/{self.court1.id}/slots/?date=2027-01-11&currency=GBP")
        self.assertEqual((r.status_code, r.data["code"]), (400, "currency_not_accepted"))
        for day in ("2026-12-31", "2027-03-03"):  # yesterday and day 61 (today is 2027-01-01 in Beirut)
            r = self.client.get(f"/api/courts/{self.court1.id}/slots/?date={day}")
            self.assertEqual((r.status_code, r.data["code"]), (400, "outside_horizon"), day)
        self.assertEqual(self.slots(self.court1, "2027-03-02"), [])  # day 60 is allowed (no Tuesday rate: empty)
        self.assertEqual(self.client.get(f"/api/courts/{self.court1.id}/slots/").status_code, 400)  # date required
        self.assertEqual(self.client.get(f"/api/courts/{self.court1.id}/slots/?date=11-01-2027").status_code, 400)
        dead = self.court("Closed court", active=False)  # AVL-7
        self.slots(dead, MON, expect=404)
        self.assertEqual(self.client.get("/api/courts/99999/slots/?date=2027-01-11").status_code, 404)

        # AVL-8: a closure 12:00-13:30 blocks the 12:00 and 13:00 slots, touching ones stay (14:00)
        CourtBlockout.objects.create(court=self.court1, starts_on=MON, start_time=dt.time(12), end_time=dt.time(13, 30))
        starts = [s["starts_at"] for s in self.slots(self.court1, MON)]
        self.assertEqual(len(starts), 13)
        for hour in (12, 13):
            self.assertNotIn(z(at(MON, hour)), starts)
        self.assertIn(z(at(MON, 14)), starts)
        self.assertIn(z(at(MON, 11)), starts)
        # AVL-5 item 2, BOOK-3: a confirmed session and a `requested` one on the court block; a cancelled one does not
        self.session(self.court1, at(MON, 15), at(MON, 16), self.owner)
        self.session(self.court1, at(MON, 9), at(MON, 10), self.owner, status="requested")
        self.session(self.court1, at(MON, 10), at(MON, 11), self.owner, status="cancelled")
        starts = [s["starts_at"] for s in self.slots(self.court1, MON)]
        self.assertEqual(len(starts), 11)
        for hour in (9, 15):
            self.assertNotIn(z(at(MON, hour)), starts)
        self.assertIn(z(at(MON, 10)), starts)
        self.assertIn(z(at(MON, 14)), starts)  # touching the session at 15:00
        self.assertIn(z(at(MON, 16)), starts)
        # AVL-5 item 3: at 12:30 Beirut the slots that already started are gone
        self.clock.return_value = at(MON, 12, 30)
        starts = [s["starts_at"] for s in self.slots(self.court1, MON)]
        self.assertEqual(starts[0], z(at(MON, 14)))
        self.assertEqual(len(starts), 9)  # 14, 16, 17 ... 23 (13:00 is closed, 15:00 is booked)

    def test_slot_cutting_and_monthly_closure(self):
        """AVL-2, AVL-8: 09:00-17:00 in 90-minute slots is exactly five slots; a monthly closure from the 31st skips
        months without a 31st and does not move to the last day."""
        court = self.court("Court 90", slot=90)
        CourtRate.objects.create(court=court, weekday=1, start_time=dt.time(9), end_time=dt.time(17), price=80)
        starts = [s["starts_at"] for s in self.slots_of(court, TUE)]
        self.assertEqual(starts, [z(at(TUE, h, m)) for h, m in ((9, 0), (10, 30), (12, 0), (13, 30), (15, 0))])
        self.assertEqual(self.slots_of(court, TUE)[-1]["ends_at"], z(at(TUE, 16, 30)))  # 16:30-17:00 is not offered

        CourtRate.objects.create(court=court, weekday=6, start_time=dt.time(9), end_time=dt.time(12), price=80)
        closure = CourtBlockout.objects.create(
            court=court, starts_on=dt.date(2027, 1, 31), start_time=dt.time(0), end_time=dt.time(0), repeat="monthly")
        occurs = [d for d in (dt.date(2027, 1, 1) + dt.timedelta(n) for n in range(365)) if closure.occurs_on(d)]
        self.assertEqual([(d.month, d.day) for d in occurs], [(1, 31), (3, 31), (5, 31), (7, 31), (8, 31), (10, 31), (12, 31)])
        self.assertEqual(len(self.slots_of(court, dt.date(2027, 1, 24))), 2)  # a Sunday before starts_on
        self.assertEqual(self.slots_of(court, dt.date(2027, 1, 31)), [])  # whole-day closure
        self.assertEqual(len(self.slots_of(court, dt.date(2027, 2, 28))), 2)  # February has no 31st: open

    def slots_of(self, court, day):
        return self.client.get(f"/api/courts/{court.id}/slots/?date={day}").data

    def test_spring_forward_offers_no_slot_in_the_skipped_hour(self):
        """AVL-6, GEN-10: in Berlin on 2027-03-28 the clocks jump from 02:00 to 03:00, so with a 00:00-06:00 window no
        slot touches the hour that does not exist."""
        berlin = Club.objects.create(owner=self.owner, name="Berlin Hoops", timezone="Europe/Berlin", currency="EUR")
        court = self.court("Court B", club=berlin)
        CourtRate.objects.create(court=court, weekday=6, start_time=dt.time(0), end_time=dt.time(6), price=20)
        self.clock.return_value = dt.datetime(2027, 3, 20, tzinfo=UTC)
        data = self.slots_of(court, dt.date(2027, 3, 28))
        self.assertEqual([(s["starts_at"], s["ends_at"]) for s in data], [
            ("2027-03-27T23:00:00Z", "2027-03-28T00:00:00Z"),  # 00:00-01:00 CET
            ("2027-03-28T01:00:00Z", "2027-03-28T02:00:00Z"),  # 03:00-04:00 CEST
            ("2027-03-28T02:00:00Z", "2027-03-28T03:00:00Z"),
            ("2027-03-28T03:00:00Z", "2027-03-28T04:00:00Z"),
        ])  # 01:00-02:00 and 02:00-03:00 local are not offered


class BookingJourneyTests(BookingBase):
    def worked_example(self):
        """Rana with 4 past bookings; offers #7 to #10 of the discounts worked example."""
        rana = self.user("rana")
        self.past_bookings(rana, 4)
        # none of these count (DSC-2): cancelled, in the future
        self.session(self.court1, dt.datetime(2026, 12, 20, 10, tzinfo=UTC), dt.datetime(2026, 12, 20, 11, tzinfo=UTC),
                     rana, status="cancelled")
        self.session(self.court1, at(dt.date(2027, 1, 20), 10), at(dt.date(2027, 1, 20), 11), rana)
        wide = {"starts_at": dt.datetime(2027, 1, 1, tzinfo=UTC), "ends_at": dt.datetime(2027, 12, 31, tzinfo=UTC)}
        Discount.objects.create(pk=7, club=self.club, percent_off=10, message="January promo",
                                starts_at=wide["starts_at"], ends_at=dt.datetime(2027, 2, 1, tzinfo=UTC))
        Discount.objects.create(pk=8, club=self.club, min_bookings=5, percent_off=15, message="Loyalty", **wide)
        Discount.objects.create(pk=9, club=self.club, user=rana, amount_off=10, message="Welcome back Rana", **wide)
        Discount.objects.create(pk=10, club=self.club, court=self.court2, percent_off=50, message="Court 2 happy hour", **wide)
        return rana

    def test_quote_and_booking_journey(self):
        """BOOK-2, BOOK-5, BOOK-6, BOOK-7, BOOK-8, BOOK-9, GEN-6, GEN-13, PRC-4, PRC-5, PRC-6, DSC-1, DSC-2, DSC-3, DSC-4,
        DSC-6, AVL-5, ACC-3: the worked examples, 16:00-18:00 in EUR with the shooting machine."""
        rana, ben = self.worked_example(), self.user("ben")
        body = self.body(at(MON, 16), at(MON, 18), currency="EUR", rentals=[{"equipment": self.shooting.id, "quantity": 1}])
        before = Session.objects.count()

        # BOOK-6: the quote writes nothing. 46.17 + 65.00 = 111.17; best offer #7 = 11.12 (#9 = 9.23, #8 and #10 not eligible)
        r = self.call("post", "sessions/quote/", rana, body, 200)
        self.assertEqual(r.data, {
            "currency": "EUR", "price": "111.170", "offer": {"id": 7, "message": "January promo"},
            "discount_amount": "11.120", "court_amount": "113.900",
            "rentals": [{"equipment": self.shooting.id, "name": "Shooting machine", "quantity": 1, "price": "13.850"}]})
        self.assertEqual(Session.objects.count(), before)
        self.assertEqual(SessionRental.objects.count(), 0)

        # BOOK-8, BOOK-9: booked and confirmed at once
        r = self.call("post", "sessions/", rana, body, 201)
        session = Session.objects.get(pk=r.data["id"])
        self.assertEqual((session.kind, session.status, session.booked_by, session.coach, session.coach_fee, session.group),
                         ("play", "confirmed", rana, None, 0, None))
        self.assertEqual((session.price, session.currency, session.discount_id, session.discount_amount),
                         (Decimal("111.17"), "EUR", 7, Decimal("11.12")))
        self.assertEqual((session.starts_at, session.ends_at), (at(MON, 16), at(MON, 18)))  # 14:00Z-16:00Z
        row = session.participants.get()
        self.assertEqual((row.user, row.status), (rana, "accepted"))
        rental = session.rentals.get()
        self.assertEqual((rental.equipment, rental.quantity, rental.price, rental.status),
                         (self.shooting, 1, Decimal("13.85"), "requested"))  # DSC-6: never discounted
        self.assertEqual((r.data["status"], r.data["price"], r.data["discount_amount"], r.data["rentals"][0]["price"]),
                         ("confirmed", "111.170", "11.120", "13.850"))

        # the slots are gone; a second player gets 409 on an overlapping run, success on touching runs (AVL-5)
        r = self.client.get(f"/api/courts/{self.court1.id}/slots/?date=2027-01-11")
        self.assertNotIn("2027-01-11T14:00:00Z", [s["starts_at"] for s in r.data])
        r = self.book(ben, at(MON, 15), at(MON, 17), expect=409)
        self.assertEqual(r.data["code"], "slot_taken")
        self.call("post", "sessions/quote/", ben, self.body(at(MON, 15), at(MON, 17)), 409)
        self.book(ben, at(MON, 14), at(MON, 16))  # ends exactly where Rana's starts
        self.book(ben, at(MON, 18), at(MON, 19))  # starts exactly where Rana's ends
        # GEN-6: the same user tapping twice
        r = self.call("post", "sessions/", rana, body, 409)
        self.assertEqual(r.data["code"], "slot_taken")
        self.assertEqual(Session.objects.filter(booked_by=rana, starts_at=at(MON, 16)).count(), 1)

        # ACC-3: signed in only
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post("/api/sessions/", body, format="json").status_code, 401)

    def test_offers_journey(self):
        """DSC-1, DSC-2, DSC-3, DSC-4, DSC-5, DSC-6, DSC-7, PRC-12: the frequent-player threshold counts only past
        non-cancelled bookings at this club, ties go to the lowest id, amounts are converted and capped, deleting an
        offer keeps the amount, the offer window is about when the session is played."""
        ben = self.user("ben")
        wide = {"starts_at": dt.datetime(2027, 1, 1, tzinfo=UTC), "ends_at": dt.datetime(2027, 12, 31, tzinfo=UTC)}
        loyal = Discount.objects.create(club=self.club, min_bookings=2, percent_off=10, message="Loyal", **wide)
        plain = Discount.objects.create(club=self.club, percent_off=10, message="Plain", **wide)

        def quote(start, hours=1, currency="USD", user=ben):
            r = self.call("post", "sessions/quote/", user, self.body(start, start + dt.timedelta(hours=hours), currency=currency), 200)
            return r.data["offer"] and r.data["offer"]["id"], r.data["discount_amount"]

        # DSC-2: one past booking here; cancelled, future and other-club bookings do not count
        self.past_bookings(ben, 1)
        self.session(self.court1, dt.datetime(2026, 12, 20, 10, tzinfo=UTC), dt.datetime(2026, 12, 20, 11, tzinfo=UTC), ben, status="cancelled")
        for day in (dt.date(2027, 1, 13), dt.date(2027, 1, 14), dt.date(2027, 1, 15)):  # ten future bookings would not unlock it either
            self.session(self.court1, at(day, 9), at(day, 10), ben)
        other_club = Club.objects.create(owner=self.owner, name="Elsewhere", timezone="Asia/Beirut", currency="USD")
        self.past_bookings(ben, 3, court=self.court("Far court", club=other_club))
        self.assertEqual(quote(at(MON, 9)), (plain.id, "5.000"))  # Loyal needs 2 and Ben has 1
        # now a second past booking: both offers give 5.00, the lowest id wins (DSC-4)
        start = dt.datetime(2026, 12, 25, 10, tzinfo=UTC)
        self.session(self.court2, start, start + dt.timedelta(hours=1), ben)
        self.assertEqual(quote(at(MON, 9)), (loyal.id, "5.000"))

        # DSC-1 item 5: the window is about when the session is played, not when it is booked
        Discount.objects.all().delete()
        late = Discount.objects.create(club=self.club, percent_off=20, starts_at=at(dt.date(2027, 1, 12), 0),
                                       ends_at=at(dt.date(2027, 1, 20), 0))
        self.assertEqual(quote(at(MON, 9)), (None, "0.000"))
        self.assertEqual(quote(at(dt.date(2027, 1, 18), 9)), (late.id, "10.000"))  # 20% of 50.00, played on the 18th
        late.delete()

        # DSC-3: amount_off in base is the amount; converted at the club rate otherwise (overrides do not apply); capped at price
        amount = Discount.objects.create(club=self.club, amount_off=Decimal("10"), **wide)
        self.assertEqual(quote(at(MON, 9)), (amount.id, "10.000"))  # price 50.00
        self.assertEqual(quote(at(MON, 9), currency="EUR"), (amount.id, "9.230"))  # 10 x 0.923457 = 9.23457
        self.assertEqual(quote(at(MON, 9), currency="LBP"), (amount.id, "895000.000"))
        amount.amount_off = Decimal("100")
        amount.save()
        self.assertEqual(quote(at(MON, 9)), (amount.id, "50.000"))  # capped at the price: never below 0
        # percent: 10% of 111.17 -> 11.117 -> 11.12 (rounded half away from zero)
        amount.delete()
        pct = Discount.objects.create(club=self.club, percent_off=Decimal("10"), **wide)
        self.assertEqual(quote(at(MON, 16), 2, "EUR"), (pct.id, "11.120"))
        # PRC-12: a free court gives an amount of 0, so no offer is recorded
        CourtRate.objects.create(court=self.court1, weekday=1, start_time=dt.time(9), end_time=dt.time(10), price=0)
        self.assertEqual(quote(at(TUE, 9)), (None, "0.000"))

        # DSC-5: deleting the offer empties `discount` and keeps `discount_amount`
        r = self.book(ben, at(MON, 16), at(MON, 18), currency="EUR")
        session = Session.objects.get(pk=r.data["id"])
        self.assertEqual((session.discount_id, session.discount_amount), (pct.id, Decimal("11.12")))
        self.call("delete", f"offers/{pct.id}/", self.owner, expect=204)
        session.refresh_from_db()
        self.assertEqual((session.discount_id, session.discount_amount), (None, Decimal("11.12")))
        self.assertEqual(self.call("get", f"sessions/{session.id}/", ben, expect=200).data["discount_amount"], "11.120")

    def test_validation_order_and_codes(self):
        """BOOK-4, BOOK-7, GEN-4, GEN-18, AVL-5: the checks of BOOK-7 in their order and their codes; every refusal
        writes nothing."""
        ann, bob, eve = self.user("ann"), self.user("bob"), self.user("eve")
        self.befriend(ann, bob)
        start, end = at(MON, 9), at(MON, 10)

        def refuse(code=None, field=None, user=ann, **change):
            body = {**self.body(start, end), **change}
            r = self.call("post", "sessions/", user, body, 400)
            if code:
                self.assertEqual(r.data["code"], code, body)
            if field:
                self.assertIn(field, r.data, body)
            self.assertEqual(Session.objects.count(), 0)
            return r

        # court exists and is active; sport; currency
        refuse(field="court", court=99999)
        refuse(field="court", court=self.court("Dead", active=False).id)
        refuse(field="sport", sport=99999)
        refuse("sport_not_offered", sport=self.volleyball.id)
        refuse("currency_not_accepted", currency="GBP")
        refuse(field="currency", currency="usd")
        refuse(field="starts_at", starts_at="2027-01-11T07:00:00")  # GEN-7: no offset
        # the order: sport before currency before the run before rentals, group, invitees
        refuse("sport_not_offered", sport=self.volleyball.id, currency="GBP")
        refuse("currency_not_accepted", currency="GBP", starts_at=z(at(MON, 9, 30)))
        bad_rental = [{"equipment": 99999, "quantity": 1}]
        refuse("not_bookable", starts_at=z(at(MON, 9, 30)), rentals=bad_rental)
        refuse(field="rentals", rentals=bad_rental, group=99999, invitees=[eve.id])

        # BOOK-4: the run
        refuse("not_bookable", starts_at=z(at(MON, 9, 30)), ends_at=z(at(MON, 10, 30)))  # misaligned
        refuse("not_bookable", ends_at=z(at(MON, 9, 30)))  # ends inside a slot
        refuse("not_bookable", ends_at=z(start))  # empty
        refuse("not_bookable", starts_at=z(at(MON, 10)), ends_at=z(at(MON, 9)))  # backwards
        refuse("not_bookable", starts_at=z(at(TUE, 9)), ends_at=z(at(TUE, 10)))  # no rate that day
        gappy = self.court("Gappy")
        for a, b in ((9, 12), (13, 17)):
            CourtRate.objects.create(court=gappy, weekday=1, start_time=dt.time(a), end_time=dt.time(b), price=10)
        refuse("not_bookable", court=gappy.id, starts_at=z(at(TUE, 11)), ends_at=z(at(TUE, 14)))  # 12:00-13:00 missing
        self.book(ann, at(TUE, 11), at(TUE, 12), court=gappy)
        self.book(ann, at(TUE, 9), at(TUE, 11), court=gappy)  # a run of two touching slots is fine
        Session.objects.all().delete()
        refuse("not_bookable", starts_at=z(at(dt.date(2027, 3, 8), 9)), ends_at=z(at(dt.date(2027, 3, 8), 10)))  # beyond 60 days
        CourtBlockout.objects.create(court=self.court1, starts_on=MON, start_time=dt.time(0), end_time=dt.time(0))
        refuse("not_bookable")  # closed
        CourtBlockout.objects.all().delete()
        self.clock.return_value = at(MON, 9, 30)  # AVL-5 item 3: the slot already started
        refuse("not_bookable")
        self.clock.return_value = NOW
        r = self.book(ann, at(dt.date(2027, 3, 1), 9), at(dt.date(2027, 3, 1), 10))  # day 59 is still bookable
        Session.objects.all().delete()

        # rentals: item of this club, court empty or this court, rental_price set, 1 <= quantity <= stock, no item twice
        other_club = Club.objects.create(owner=eve, name="Other", timezone="Asia/Beirut", currency="USD")
        foreign = Equipment.objects.create(club=other_club, name="Foreign", quantity=5, rental_price=1)
        tied = Equipment.objects.create(club=self.club, court=self.court2, name="Court 2 net", quantity=5, rental_price=1)
        free = Equipment.objects.create(club=self.club, name="Balls", quantity=5)
        for rentals in ([{"equipment": foreign.id, "quantity": 1}], [{"equipment": tied.id, "quantity": 1}],
                        [{"equipment": free.id, "quantity": 1}], [{"equipment": self.shooting.id, "quantity": 0}],
                        [{"equipment": self.shooting.id, "quantity": 2}],
                        [{"equipment": self.shooting.id, "quantity": 1}, {"equipment": self.shooting.id, "quantity": 1}],
                        [{"equipment": self.shooting.id}]):
            refuse(field="rentals", rentals=rentals)
        ok_tied = Equipment.objects.create(club=self.club, court=self.court1, name="Court 1 net", quantity=5, rental_price=1)
        self.call("post", "sessions/quote/", ann, self.body(start, end, rentals=[{"equipment": ok_tied.id, "quantity": 5}]), 200)

        # group: the caller must be an active member or a manager of it
        group = Group.objects.create(type="play_group", name="Not mine", created_by=bob)
        GroupMember.objects.create(group=group, user=bob, status="active")
        GroupMember.objects.create(group=group, user=ann, status="invited")  # invited is not active
        refuse(field="group", group=group.id)
        refuse(field="group", group=99999)

        # invitees: friends only, not the caller, no shadow player, no duplicates
        shadow = User.objects.create_user(email=None, full_name="Sam", managed_by=bob)
        self.befriend(ann, shadow)  # cannot happen through the API (ACC-12); the rule is still checked
        for invitees in ([eve.id], [ann.id], [bob.id, bob.id], [shadow.id], [99999]):
            refuse(field="invitees", invitees=invitees)
        r = self.call("post", "sessions/", ann, self.body(start, end, invitees=[bob.id]), 201)
        self.assertEqual({p["user"]["full_name"]: p["status"] for p in r.data["participants"]}, {"Ann": "accepted", "Bob": "invited"})

    def test_run_across_midnight(self):
        """BOOK-4, AVL-3, PRC-5, PRC-4, AVL-5: Monday 23:00 to Tuesday 01:00 takes two slots, each priced from its own
        day's rate; refused when either slot is missing."""
        night = self.court("Night")
        CourtRate.objects.create(court=night, weekday=0, start_time=dt.time(23), end_time=dt.time(0), price=30)
        CourtRate.objects.create(court=night, weekday=1, start_time=dt.time(0), end_time=dt.time(3), price=40)
        half = self.court("Half")  # no Tuesday rate
        CourtRate.objects.create(court=half, weekday=0, start_time=dt.time(23), end_time=dt.time(0), price=30)
        ann = self.user("ann")
        start, end = at(MON, 23), at(TUE, 1)
        r = self.call("post", "sessions/quote/", ann, self.body(start, end, court=night, currency="EUR"), 200)
        self.assertEqual(r.data["price"], "64.640")  # 30 x 0.923457 = 27.70 and 40 x 0.923457 = 36.94
        self.book(ann, start, end, expect=400, court=half)
        self.book(ann, at(MON, 22), end, expect=400, court=night)  # 22:00 is not offered
        r = self.book(ann, start, end, court=night)
        self.assertEqual((r.data["price"], r.data["starts_at"], r.data["ends_at"]), ("70.000", "2027-01-11T21:00:00Z", "2027-01-11T23:00:00Z"))
        self.book(ann, at(TUE, 0), at(TUE, 1), expect=409, court=night)  # the Tuesday half is taken

    def test_group_booking_journey(self):
        """BOOK-10, BOOK-11, BOOK-60, CHAT-30, CHAT-31, NOTE-20, BOOK-15: every active member but the booker is invited,
        shadow players are accepted, later joiners are not added, one card in the group chat, a push per invitee."""
        coach, hal, ian, joy, fay, kim = (self.user(n) for n in ("coach", "hal", "ian", "joy", "fay", "kim"))
        team = Group.objects.create(type="team", name="Wolves", created_by=coach, coach=coach)
        chat_services.create_group_chat(team, coach)
        for member in (coach, hal, ian):
            GroupMember.objects.get_or_create(group=team, user=member, defaults={"status": "active"})
        GroupMember.objects.create(group=team, user=joy, status="invited")  # not active: not added
        sam = User.objects.create_user(email=None, full_name="Sam", managed_by=coach)
        GroupMember.objects.create(group=team, user=sam, status="active")
        self.befriend(coach, fay)

        r = self.book(coach, at(MON, 10), at(MON, 11), group=team.id, invitees=[fay.id], push=True)
        session = Session.objects.get(pk=r.data["id"])
        self.assertEqual(session.group, team)
        rows = {p.user.full_name: p.status for p in session.participants.select_related("user")}
        self.assertEqual(rows, {"Coach": "accepted", "Hal": "invited", "Ian": "invited", "Fay": "invited", "Sam": "accepted"})
        # NOTE-20: a push to each invitee, none to the booker, the shadow player or the member who is only invited to the group
        for user in (hal, ian, fay):
            self.assertEqual([p["data"]["id"] for p in self.pushed(user, "session_invite")], [str(session.id)])
        self.assertEqual({p["user_id"] for p in accounts.outbox}, {hal.id, ian.id, fay.id})
        # BOOK-60, CHAT-30, CHAT-31: one card, no sender, no body, only a link to the session
        card = Message.objects.get(session=session)
        self.assertEqual((card.chat.group, card.sender, card.body), (team, None, ""))
        chat_services.post_session_card(session)  # a second call creates nothing
        self.assertEqual(Message.objects.filter(session=session).count(), 1)

        # BOOK-11: a member who joins later is not added; the booker may invite them (BOOK-15, members of the group)
        GroupMember.objects.create(group=team, user=kim, status="active")
        self.assertFalse(session.participants.filter(user=kim).exists())
        accounts.outbox.clear()
        r = self.call("post", f"sessions/{session.id}/participants/", coach, {"invitees": [kim.id]}, 201, push=True)
        self.assertEqual(len(self.pushed(kim, "session_invite")), 1)
        self.call("post", f"sessions/{session.id}/participants/", coach, {"invitees": [joy.id]}, 400)  # invited-only: not a friend, not active

        # CHAT-30: a group without a chat gets no card, and the booking still works
        chat_services.detach_chat(team)
        r = self.book(coach, at(MON, 11), at(MON, 12), group=team.id)
        self.assertFalse(Message.objects.filter(session_id=r.data["id"]).exists())
        self.assertEqual(Chat.objects.filter(group=team).count(), 0)

    def test_invites_journey(self):
        """BOOK-15, BOOK-16, BOOK-17, NOTE-20, GEN-3, GEN-5: invite after booking, answer, withdraw, change mind,
        the booker cannot leave, remove a participant, nothing changes after the start."""
        ann, bob, cy, dee, eve, zed = (self.user(n) for n in ("ann", "bob", "cy", "dee", "eve", "zed"))
        for friend in (bob, cy, dee):
            self.befriend(ann, friend)
        session = Session.objects.get(pk=self.book(ann, at(MON, 10), at(MON, 11), invitees=[bob.id]).data["id"])
        url = f"sessions/{session.id}/participants/"

        # BOOK-15: invite; someone who already has a row is skipped (200, no push); non-friends are refused
        accounts.outbox.clear()
        r = self.call("post", url, ann, {"invitees": [bob.id]}, 200, push=True)
        self.assertEqual((len(r.data["participants"]), accounts.outbox), (2, []))
        r = self.call("post", url, ann, {"invitees": [bob.id, cy.id, dee.id]}, 201, push=True)
        self.assertEqual(len(r.data["participants"]), 4)
        self.assertEqual([len(self.pushed(u, "session_invite")) for u in (bob, cy, dee)], [0, 1, 1])
        self.assertEqual(self.call("post", url, ann, {"invitees": [eve.id]}).status_code, 400)
        self.assertEqual(self.call("post", url, ann, {"invitees": []}).status_code, 400)
        self.assertEqual(self.call("post", url, bob, {"invitees": [eve.id]}).status_code, 403)  # sees it, may not invite
        self.assertEqual(self.call("post", url, zed, {"invitees": [eve.id]}).status_code, 404)  # GEN-3

        # BOOK-16: the invitee answers, repeats are 200, withdraws, changes their mind
        mine = f"{url}{bob.id}/"
        self.assertEqual(self.call("patch", mine, bob, {"status": "accepted"}, 200).data["status"], "accepted")
        self.call("patch", mine, bob, {"status": "accepted"}, 200)
        self.assertEqual(self.call("patch", mine, bob, {"status": "declined"}, 200).data["status"], "declined")
        self.assertEqual(self.call("patch", mine, bob, {"status": "accepted"}, 200).data["status"], "accepted")
        self.call("patch", f"{url}{cy.id}/", cy, {"status": "declined"}, 200)
        self.call("patch", mine, bob, {"status": "invited"}, 400)  # not an answer
        self.call("patch", f"{url}{cy.id}/", bob, {"status": "accepted"}, 403)  # somebody else's row
        self.call("patch", f"{url}{cy.id}/", zed, {"status": "accepted"}, 404)
        self.call("patch", f"{url}{zed.id}/", ann, {"status": "accepted"}, 404)  # no such row
        r = self.call("patch", f"{url}{ann.id}/", ann, {"status": "declined"}, 400)
        self.assertEqual(r.data["code"], "booker_cannot_leave")
        self.call("patch", f"{url}{ann.id}/", ann, {"status": "accepted"}, 200)  # the booker's own row stays accepted

        # BOOK-17: the booker removes a participant; not themselves, not a checked-in one; others may not
        self.call("delete", f"{url}{bob.id}/", cy, expect=403)
        self.call("delete", f"{url}{cy.id}/", ann, expect=204)
        self.assertFalse(session.participants.filter(user=cy).exists())
        self.call("delete", f"{url}{cy.id}/", ann, expect=404)
        self.assertEqual(self.call("delete", f"{url}{ann.id}/", ann).data["code"], "booker_cannot_leave")
        session.participants.filter(user=dee).update(checked_in_at=NOW)
        self.assertEqual(self.call("delete", f"{url}{dee.id}/", ann).data["code"], "already_checked_in")
        session.participants.filter(user=dee).update(checked_in_at=None)  # undo the setup: a check-in freezes (PAY-8)

        # after the start nothing changes (session_closed); a cancelled session is closed too
        self.clock.return_value = at(MON, 10, 30)
        for call in (("patch", mine, bob, {"status": "declined"}), ("post", url, ann, {"invitees": [cy.id]}),
                     ("delete", f"{url}{bob.id}/", ann, None)):
            r = self.call(*call)
            self.assertEqual((r.status_code, r.data["code"]), (400, "session_closed"), call)
        self.call("patch", mine, bob, {"status": "accepted"}, 200)  # a repeat is still harmless
        self.clock.return_value = NOW
        self.call("post", f"sessions/{session.id}/cancel/", ann, expect=200)
        r = self.call("patch", mine, bob, {"status": "declined"})
        self.assertEqual((r.status_code, r.data["code"]), (400, "session_closed"))
        self.assertEqual(self.call("post", url, ann, {"invitees": [cy.id]}).data["code"], "session_closed")

    def test_rentals_journey(self):
        """BOOK-40, BOOK-41, BOOK-42, BOOK-43, ACC-6, GEN-3, GEN-5: the club side decides, stock is checked only on
        approval across overlapping sessions, other clubs' staff see nothing, rentals freeze once there are payments."""
        ann, bob, cy, sam = (self.user(n) for n in ("ann", "bob", "cy", "sam"))
        self.staff(sam)
        rent = [{"equipment": self.shooting.id, "quantity": 1}]
        # BOOK-43: all three may request the single machine; no stock check at booking
        a = self.book(ann, at(MON, 9), at(MON, 10), rentals=rent).data["rentals"][0]["id"]
        b = self.book(bob, at(MON, 9), at(MON, 10), court=self.court2, rentals=rent).data["rentals"][0]["id"]
        c_session = Session.objects.get(pk=self.book(cy, at(MON, 10), at(MON, 11), rentals=rent).data["id"])
        c = c_session.rentals.get().id

        # who decides: the club side only. A player who sees the session gets 403, a stranger 404
        self.call("patch", f"rentals/{a}/", ann, {"status": "approved"}, 403)
        self.call("patch", f"rentals/{a}/", bob, {"status": "approved"}, 404)
        other = Club.objects.create(owner=bob, name="Other", timezone="Asia/Beirut", currency="USD")
        rival = self.user("rival")
        self.staff(rival, club=other)
        self.call("patch", f"rentals/{a}/", rival, {"status": "approved"}, 404)  # another club's staff
        self.call("patch", f"rentals/{a}/", bob, {"status": "approved"}, 404)
        expired = self.user("expired")
        self.staff(expired, expires_on=dt.date(2026, 12, 31))  # ACC-2
        self.call("patch", f"rentals/{a}/", expired, {"status": "approved"}, 404)
        self.call("patch", "rentals/99999/", sam, {"status": "approved"}, 404)
        self.call("patch", f"rentals/{a}/", sam, {"status": "requested"}, 400)
        self.call("patch", f"rentals/{a}/", ann, {"status": "bogus"}, 403)  # permission before input (GEN-4)

        # BOOK-41: approve one; the overlapping one is out of stock, the touching one is fine
        self.assertEqual(self.call("patch", f"rentals/{a}/", sam, {"status": "approved"}, 200).data["status"], "approved")
        self.call("patch", f"rentals/{a}/", sam, {"status": "approved"}, 200)  # repeat (GEN-5)
        r = self.call("patch", f"rentals/{b}/", self.owner, {"status": "approved"}, 409)
        self.assertEqual(r.data["code"], "out_of_stock")
        self.assertEqual(SessionRental.objects.get(pk=b).status, "requested")
        self.call("patch", f"rentals/{c}/", sam, {"status": "approved"}, 200)
        # approved -> declined and declined -> approved are allowed; the freed stock goes to the other session
        self.assertEqual(self.call("patch", f"rentals/{a}/", self.owner, {"status": "declined"}, 200).data["status"], "declined")
        self.call("patch", f"rentals/{b}/", sam, {"status": "approved"}, 200)
        self.call("patch", f"rentals/{a}/", sam, {"status": "approved"}, 409)
        # a cancelled session's approved rental no longer holds stock
        b_session = SessionRental.objects.get(pk=b).session
        self.call("post", f"sessions/{b_session.id}/cancel/", bob, expect=200)
        self.call("patch", f"rentals/{a}/", sam, {"status": "approved"}, 200)
        r = self.call("patch", f"rentals/{b}/", sam, {"status": "declined"})  # rental on a cancelled session
        self.assertEqual((r.status_code, r.data["code"]), (400, "session_cancelled"))

        # PAY-8: frozen once anyone has checked in; a repeat of the current status is still 200
        c_session.participants.update(checked_in_at=NOW)
        r = self.call("patch", f"rentals/{c}/", sam, {"status": "declined"})
        self.assertEqual((r.status_code, r.data["code"]), (400, "already_payable"))
        self.call("patch", f"rentals/{c}/", sam, {"status": "approved"}, 200)
        # BOOK-42: rentals are not added or changed afterwards (no endpoint)
        self.assertEqual(self.call("post", f"sessions/{c_session.id}/rentals/", cy, rent).status_code, 404)

    def test_cancel_journey(self):
        """BOOK-1, BOOK-50, BOOK-51, GEN-3, GEN-5, NOTE-20: who may cancel, rentals declined, the slot freed, pushes to
        everyone listed except the caller, closed and payable sessions."""
        ann, bob, cy, dee, eve, cora, pat = (self.user(n) for n in ("ann", "bob", "cy", "dee", "eve", "cora", "pat"))
        sam = self.user("sam")
        self.staff(sam)
        for friend in (bob, cy, dee):
            self.befriend(ann, friend)
        racket = Equipment.objects.create(club=self.club, name="Racket", quantity=5, rental_price=Decimal("5"))
        rentals = [{"equipment": self.shooting.id, "quantity": 1}, {"equipment": racket.id, "quantity": 2}]
        r = self.book(ann, at(MON, 9), at(MON, 10), invitees=[bob.id, cy.id, dee.id], rentals=rentals)
        session = Session.objects.get(pk=r.data["id"])
        self.call("patch", f"sessions/{session.id}/participants/{cy.id}/", cy, {"status": "accepted"}, 200)
        self.call("patch", f"sessions/{session.id}/participants/{dee.id}/", dee, {"status": "declined"}, 200)
        session.rentals.filter(equipment=racket).update(status="approved")
        url = f"sessions/{session.id}/cancel/"

        # who may: booker, session coach, club owner. A participant or staff who can see it gets 403, others 404
        self.call("post", url, eve, expect=404)
        self.call("post", url, cy, expect=403)
        self.call("post", url, sam, expect=403)  # staff are not the owner
        self.call("post", "sessions/99999/cancel/", ann, expect=404)
        accounts.outbox.clear()
        r = self.call("post", url, ann, expect=200, push=True)
        self.assertEqual(r.data["status"], "cancelled")
        session.refresh_from_db()
        self.assertEqual(session.status, "cancelled")
        self.assertEqual({x.equipment.name: x.status for x in session.rentals.select_related("equipment")},
                         {"Shooting machine": "declined", "Racket": "approved"})  # only `requested` ones are declined
        # NOTE-20: invited and accepted participants, not the caller, not the one who declined
        self.assertEqual([len(self.pushed(u, "session_cancelled")) for u in (ann, bob, cy, dee)], [0, 1, 1, 0])
        self.assertEqual(self.pushed(bob, "session_cancelled")[0]["data"]["id"], str(session.id))
        # BOOK-51: repeat is 200 and sends nothing; the slot is free again
        accounts.outbox.clear()
        self.call("post", url, ann, expect=200, push=True)
        self.assertEqual(accounts.outbox, [])
        free = [s["starts_at"] for s in self.client.get(f"/api/courts/{self.court1.id}/slots/?date=2027-01-11").data]
        self.assertIn(z(at(MON, 9)), free)
        # the owner cancels someone else's session; the booker hears about it
        again = self.book(eve, at(MON, 9), at(MON, 10)).data["id"]
        accounts.outbox.clear()
        self.call("post", f"sessions/{again}/cancel/", self.owner, expect=200, push=True)
        self.assertEqual(len(self.pushed(eve, "session_cancelled")), 1)
        self.assertEqual(self.pushed(self.owner, "session_cancelled"), [])

        # the session coach may cancel (and is told when someone else does)
        training = Session.objects.create(
            court=self.court1, sport=self.basketball, booked_by=pat, coach=cora, kind="training", status="confirmed",
            starts_at=at(MON, 12), ends_at=at(MON, 13), currency="USD", price=Decimal("50"))
        SessionParticipant.objects.create(session=training, user=pat, status="accepted")
        accounts.outbox.clear()
        self.call("post", f"sessions/{training.id}/cancel/", pat, expect=200, push=True)
        self.assertEqual((len(self.pushed(cora, "session_cancelled")), len(self.pushed(pat, "session_cancelled"))), (1, 0))
        training.status = "confirmed"
        training.save()
        accounts.outbox.clear()
        self.call("post", f"sessions/{training.id}/cancel/", cora, expect=200, push=True)
        self.assertEqual((len(self.pushed(cora, "session_cancelled")), len(self.pushed(pat, "session_cancelled"))), (0, 1))

        # PAY-8: once anyone checked in, refused; ended: refused; a requested session is not cancelled here (BOOK-1)
        paid = self.session(self.court1, at(MON, 14), at(MON, 15), ann)
        SessionParticipant.objects.create(session=paid, user=cy, status="accepted", checked_in_at=at(MON, 13, 50))
        r = self.call("post", f"sessions/{paid.id}/cancel/", ann)
        self.assertEqual((r.status_code, r.data["code"]), (400, "already_payable"))
        waiting = self.session(self.court1, at(MON, 16), at(MON, 17), ann, status="requested")
        self.assertEqual(self.call("post", f"sessions/{waiting.id}/cancel/", ann).data["code"], "invalid_status")
        late = self.session(self.court1, at(MON, 18), at(MON, 19), ann)
        self.clock.return_value = at(MON, 19, 30)
        r = self.call("post", f"sessions/{late.id}/cancel/", ann)
        self.assertEqual((r.status_code, r.data["code"]), (400, "session_closed"))
        self.call("post", url, ann, expect=200)  # already cancelled stays 200 even later (GEN-5)
        session.refresh_from_db()
        self.assertEqual(session.status, "cancelled")

    def test_reading_journey(self):
        """BOOK-55, BOOK-65, BOOK-66, ACC-1, GEN-3, GEN-12: visibility, `completed` is shown and never stored, my
        sessions with filters and pagination."""
        ann, bob, cy, dee, eve, sam = (self.user(n) for n in ("ann", "bob", "cy", "dee", "eve", "sam"))
        self.staff(sam)
        rival = self.user("rival")
        self.staff(rival, club=Club.objects.create(owner=eve, name="Other", timezone="Asia/Beirut", currency="USD"))
        for friend in (bob, cy, dee):
            self.befriend(ann, friend)
        first = self.book(ann, at(MON, 9), at(MON, 10), invitees=[bob.id, cy.id, dee.id]).data["id"]
        self.call("patch", f"sessions/{first}/participants/{dee.id}/", dee, {"status": "declined"}, 200)
        second = self.book(ann, at(MON, 11), at(MON, 12)).data["id"]
        third = self.book(bob, at(MON, 13), at(MON, 14)).data["id"]

        # BOOK-65: participants (any status), the booker, the club side see it; others 404
        for viewer in (ann, bob, cy, dee, sam, self.owner):
            self.assertEqual(self.call("get", f"sessions/{first}/", viewer, expect=200).data["id"], first)
        for viewer in (eve, rival):
            self.call("get", f"sessions/{first}/", viewer, expect=404)
        self.call("get", "sessions/99999/", ann, expect=404)
        detail = self.call("get", f"sessions/{first}/", ann).data
        self.assertEqual((detail["court"]["name"], detail["court"]["club"]["name"], detail["sport"]["name"], detail["booked_by"]["id"]),
                         ("Court 1", "Hoops", "Basketball", ann.id))
        self.assertEqual({p["user"]["full_name"]: p["status"] for p in detail["participants"]},
                         {"Ann": "accepted", "Bob": "invited", "Cy": "invited", "Dee": "declined"})

        # BOOK-66: booker, coach or invited/accepted participant; declined ones are not listed; by starts_at
        ids = lambda user, query="": [s["id"] for s in self.call("get", f"me/sessions/{query}", user, expect=200).data["results"]]
        self.assertEqual(ids(ann), [first, second])
        self.assertEqual(ids(bob), [first, third])  # invited to the first, booker of the third
        self.assertEqual(ids(dee), [])
        self.assertEqual(ids(eve), [])
        self.assertEqual(ids(ann, f"?from={z(at(MON, 11))}"), [second])
        self.assertEqual(ids(ann, f"?to={z(at(MON, 11))}"), [first])  # `to` is exclusive
        self.assertEqual(ids(ann, f"?from={z(at(MON, 9))}&to={z(at(MON, 12))}"), [first, second])
        self.call("get", "me/sessions/?from=2027-01-11T09:00:00", ann, expect=400)  # GEN-7
        self.call("get", "me/sessions/?status=bogus", ann, expect=400)
        self.call("post", f"sessions/{second}/cancel/", ann, expect=200)
        self.assertEqual(ids(ann, "?status=cancelled"), [second])
        self.assertEqual(ids(ann, "?status=confirmed"), [first])
        self.assertEqual(ids(ann, "?status=completed"), [])

        # BOOK-55: after the end a confirmed session is shown as completed, but stored as confirmed
        self.clock.return_value = at(MON, 9, 59)
        self.assertEqual(self.call("get", f"sessions/{first}/", ann).data["status"], "confirmed")
        self.clock.return_value = at(MON, 10)
        self.assertEqual(self.call("get", f"sessions/{first}/", ann).data["status"], "completed")
        self.assertEqual(Session.objects.get(pk=first).status, "confirmed")
        self.assertEqual(ids(ann, "?status=completed"), [first])
        self.assertEqual(ids(ann, "?status=confirmed"), [])
        self.assertEqual(self.call("get", f"sessions/{second}/", ann).data["status"], "cancelled")

        # GEN-12: 50 a page
        Session.objects.bulk_create(
            Session(court=self.court1, sport=self.basketball, booked_by=cy, kind="play", status="confirmed",
                    starts_at=at(dt.date(2027, 2, 1), 9) + dt.timedelta(minutes=n), ends_at=at(dt.date(2027, 2, 1), 9) + dt.timedelta(hours=1, minutes=n),
                    currency="USD", price=Decimal("1")) for n in range(55))
        page1 = self.call("get", "me/sessions/", cy, expect=200).data
        self.assertEqual((page1["count"], len(page1["results"]), bool(page1["next"])), (56, 50, True))
        self.assertEqual(len(self.call("get", "me/sessions/?page=2", cy, expect=200).data["results"]), 6)


class TrainingTests(BookingBase):
    def request(self, user, coach, start, end, expect=201, push=False, **extra):
        body = {"coach": coach.id, "sport": self.basketball.id, "starts_at": z(start), "ends_at": z(end), **extra}
        return self.call("post", "training-requests/", user, body, expect, push)

    def confirm(self, coach, session_id, start, end, currency="USD", fee="30", expect=200, push=False, **extra):
        body = {"starts_at": z(start), "ends_at": z(end), "currency": currency, "coach_fee": fee, **extra}
        return self.call("post", f"sessions/{session_id}/confirm/", coach, body, expect, push)

    def train(self, coach, start, end, currency="USD", fee="40", expect=201, push=False, **extra):
        body = {"sport": self.basketball.id, "starts_at": z(start), "ends_at": z(end), "currency": currency,
                "coach_fee": fee, **extra}
        return self.call("post", "sessions/training/", coach, body, expect, push)

    def code(self, response, code):
        self.assertEqual(response.data["code"], code, response.data)

    def names(self, session):
        return {p.user.full_name: p.status for p in session.participants.select_related("user")}

    def free(self, user, kind, pk, start, end, expect=200, **params):
        """The free intervals as (starts_at, ends_at) strings, or the response when `expect` is not 200."""
        self.client.force_authenticate(user)
        r = self.client.get(f"/api/{kind}/{pk}/availability/", {"from": z(start), "to": z(end), **params})
        self.assertEqual(r.status_code, expect, r.data if r.content else None)
        return [(i["starts_at"], i["ends_at"]) for i in r.data] if expect == 200 else r

    def test_training_request_journey(self):
        """BOOK-1, BOOK-2, BOOK-4, BOOK-20, BOOK-21, BOOK-22, BOOK-23, DSC-1, AVL-20, GEN-5, GEN-7, GEN-17, NOTE-20,
        TEAM-4: request, refusals, confirm with a court (offer for the requester) and without one, decline, withdraw."""
        rana, sam, pat = (self.user(n) for n in ("rana", "sam", "pat"))
        coach, bea = self.user("coach", is_coach=True), self.user("bea", is_coach=True)
        Connection.objects.create(user=bea, other_user=rana, type="friend", status="blocked")
        shadow = self.shadow("Shad", coach)
        start, end = at(MON, 10), at(MON, 11)

        # BOOK-20: refusals write nothing
        self.code(self.request(rana, pat, start, end, 400), "not_a_coach")
        self.code(self.request(rana, rana, start, end, 400), "cannot_request")
        self.code(self.request(rana, bea, start, end, 400), "cannot_request")  # blocked pair, either direction
        self.code(self.request(bea, rana, start, end, 400), "cannot_request")
        self.assertIn("coach", self.request(rana, shadow, start, end, 400).data)  # GEN-18
        self.assertIn("starts_at", self.request(rana, coach, NOW - dt.timedelta(hours=1), end, 400).data)
        self.assertIn("ends_at", self.request(rana, coach, end, start, 400).data)
        self.assertIn("ends_at", self.request(rana, coach, at(MON, 9), at(MON, 17, 1), 400).data)  # 8 h 1 min
        r = self.call("post", "training-requests/", rana, {"coach": coach.id, "sport": self.basketball.id,
                                                          "starts_at": "2027-01-11T08:00:00", "ends_at": z(end)}, 400)
        self.assertIn("starts_at", r.data)  # GEN-7
        self.assertEqual(Session.objects.count(), 0)

        # BOOK-20: the request is a session without a court, owed by the requester, and pushes the coach only
        r = self.request(rana, coach, start, end, push=True)
        asked = Session.objects.get(pk=r.data["id"])
        self.assertEqual((asked.kind, asked.status, asked.court, asked.currency, asked.price, asked.coach_fee),
                         ("training", "requested", None, "", 0, 0))
        self.assertEqual((asked.booked_by, asked.coach, asked.coach_fee_payer), (rana, coach, rana))
        self.assertEqual(self.names(asked), {"Rana": "accepted"})
        self.assertEqual([p["data"]["id"] for p in self.pushed(coach, "training_request")], [str(asked.id)])
        self.assertEqual({p["user_id"] for p in accounts.outbox}, {coach.id})
        self.call("get", f"sessions/{asked.id}/", coach, expect=200)  # BOOK-65: the coach sees it
        self.call("get", f"sessions/{asked.id}/", pat, expect=404)

        # AVL-20: a request does not make the coach busy
        whole = [(z(at(MON, 8)), z(at(MON, 14)))]
        self.assertEqual(self.free(coach, "users", coach.id, at(MON, 8), at(MON, 14)), whole)

        # BOOK-21 refusals: only the session's coach (404), then the body, then the booking rules
        self.confirm(rana, asked.id, start, end, expect=404)
        self.confirm(pat, asked.id, start, end, expect=404)
        self.confirm(coach, 99999, start, end, expect=404)
        r = self.call("post", f"sessions/{asked.id}/confirm/", coach,
                      {"starts_at": z(start), "ends_at": z(end), "currency": "USD"}, 400)
        self.assertIn("coach_fee", r.data)
        self.assertIn("coach_fee", self.confirm(coach, asked.id, start, end, fee="-1", expect=400).data)
        self.assertIn("coach_fee", self.confirm(coach, asked.id, start, end, fee="10.005", expect=400).data)  # GEN-17
        self.assertIn("currency", self.confirm(coach, asked.id, start, end, currency="usd", expect=400).data)
        court = self.court1.id
        volleyball_only = self.court("Court V", sports=[self.volleyball])
        self.code(self.confirm(coach, asked.id, start, end, expect=400, court=volleyball_only.id), "sport_not_offered")
        self.code(self.confirm(coach, asked.id, start, end, currency="GBP", expect=400, court=court), "currency_not_accepted")
        self.code(self.confirm(coach, asked.id, at(MON, 8), at(MON, 10), expect=400, court=court), "not_bookable")  # BOOK-4
        self.code(self.confirm(coach, asked.id, NOW, at(MON, 10), expect=400, court=court), "not_bookable")
        self.assertIn("court", self.confirm(coach, asked.id, start, end, expect=400, court=99999).data)
        asked.refresh_from_db()
        self.assertEqual(asked.status, "requested")

        # BOOK-21 with a court: the times may differ from the proposal; the offer is the requester's, not the coach's
        wide = {"starts_at": dt.datetime(2027, 1, 1, tzinfo=UTC), "ends_at": dt.datetime(2027, 12, 31, tzinfo=UTC)}
        mine = Discount.objects.create(club=self.club, user=rana, percent_off=20, message="For Rana", **wide)
        Discount.objects.create(club=self.club, user=coach, percent_off=50, message="For the coach", **wide)
        later = self.request(sam, coach, start, end).data["id"]  # a second request for the same hour
        accounts.outbox.clear()
        r = self.confirm(coach, asked.id, at(MON, 10), at(MON, 12), "EUR", "30", push=True, court=court)
        self.assertEqual((r.data["status"], r.data["court"]["id"], r.data["currency"]), ("confirmed", court, "EUR"))
        # 2 x round(50 x 0.923457) = 92.34; 20% of it = 18.468 -> 18.47 (DSC-3, GEN-16)
        self.assertEqual((r.data["price"], r.data["discount"], r.data["discount_amount"]), ("92.340", mine.id, "18.470"))
        self.assertEqual((r.data["coach_fee"], r.data["coach_fee_payer"], r.data["booked_by"]["id"]),
                         ("30.000", rana.id, rana.id))  # BOOK-23: the requester is the booker and owes the coach fee
        self.assertEqual([p["data"]["id"] for p in self.pushed(rana, "training_confirmed")], [str(asked.id)])
        self.assertEqual({p["user_id"] for p in accounts.outbox}, {rana.id})
        # BOOK-2: the slots are held now
        free = [s["starts_at"] for s in self.client.get(f"/api/courts/{court}/slots/?date=2027-01-11").data]
        self.assertNotIn(z(at(MON, 10)), free)
        self.code(self.confirm(coach, later, start, end, expect=409, court=court), "slot_taken")
        self.assertEqual(Session.objects.get(pk=later).status, "requested")

        # BOOK-1: only a requested session can be confirmed, declined or withdrawn
        self.code(self.confirm(coach, asked.id, start, end, expect=400), "invalid_status")
        self.code(self.call("post", f"sessions/{asked.id}/decline/", coach, expect=400), "invalid_status")
        self.code(self.call("post", f"sessions/{asked.id}/withdraw/", rana, expect=400), "invalid_status")

        # BOOK-21 without a court: price 0, no offer, any valid currency, the time only has to be in the future
        self.assertIn("starts_at", self.confirm(coach, later, NOW, end, "JPY", "5000", expect=400).data)
        self.assertIn("ends_at", self.confirm(coach, later, end, start, "JPY", "5000", expect=400).data)
        self.assertIn("coach_fee", self.confirm(coach, later, start, end, "JPY", "5000.5", expect=400).data)  # JPY: no decimals
        accounts.outbox.clear()
        r = self.confirm(coach, later, at(MON, 10), at(MON, 11), "JPY", "5000", push=True)
        self.assertEqual((r.data["status"], r.data["court"], r.data["currency"], r.data["price"]),
                         ("confirmed", None, "JPY", "0.000"))
        self.assertEqual((r.data["discount"], r.data["discount_amount"], r.data["coach_fee"]), (None, "0.000", "5000.000"))
        self.assertEqual(r.data["coach_fee_payer"], sam.id)
        self.assertEqual(len(self.pushed(sam, "training_confirmed")), 1)

        # AVL-20: confirmed sessions make the coach busy (10:00-12:00 Beirut; the two sessions overlap)
        self.assertEqual(self.free(coach, "users", coach.id, at(MON, 8), at(MON, 14)),
                         [(z(at(MON, 8)), z(at(MON, 10))), (z(at(MON, 12)), z(at(MON, 14)))])

        # BOOK-22: the coach declines; the requester hears; a repeat is a 200 that sends nothing (GEN-5)
        third = self.request(rana, coach, at(MON, 13), at(MON, 14)).data["id"]
        self.call("post", f"sessions/{third}/decline/", rana, expect=404)
        self.call("post", f"sessions/{third}/decline/", pat, expect=404)
        accounts.outbox.clear()
        r = self.call("post", f"sessions/{third}/decline/", coach, expect=200, push=True)
        self.assertEqual(r.data["status"], "cancelled")
        self.assertEqual([p["data"]["id"] for p in self.pushed(rana, "training_declined")], [str(third)])
        self.assertEqual({p["user_id"] for p in accounts.outbox}, {rana.id})
        accounts.outbox.clear()
        self.call("post", f"sessions/{third}/decline/", coach, expect=200, push=True)
        self.assertEqual(accounts.outbox, [])
        self.code(self.confirm(coach, third, start, end, expect=400), "invalid_status")

        # BOOK-22: the requester withdraws; the coach hears (an 8 hour request is fine)
        fourth = self.request(rana, coach, at(MON, 9), at(MON, 17)).data["id"]
        self.call("post", f"sessions/{fourth}/withdraw/", coach, expect=404)
        self.call("post", f"sessions/{fourth}/withdraw/", pat, expect=404)
        accounts.outbox.clear()
        r = self.call("post", f"sessions/{fourth}/withdraw/", rana, expect=200, push=True)
        self.assertEqual(r.data["status"], "cancelled")
        self.assertEqual([p["data"]["id"] for p in self.pushed(coach, "training_withdrawn")], [str(fourth)])
        self.assertEqual({p["user_id"] for p in accounts.outbox}, {coach.id})
        accounts.outbox.clear()
        self.call("post", f"sessions/{fourth}/withdraw/", rana, expect=200, push=True)
        self.assertEqual(accounts.outbox, [])

        # BOOK-1: a request cannot be answered once its proposed start has passed
        fifth = self.request(rana, coach, at(MON, 13), at(MON, 14)).data["id"]
        self.clock.return_value = at(MON, 14)
        self.code(self.call("post", f"sessions/{fifth}/decline/", coach, expect=400), "session_closed")
        self.code(self.call("post", f"sessions/{fifth}/withdraw/", rana, expect=400), "session_closed")
        self.assertEqual(Session.objects.get(pk=fifth).status, "requested")

    def test_team_training_journey(self):
        """BOOK-1, BOOK-2, BOOK-4, BOOK-30, BOOK-32, BOOK-33, BOOK-60, ACC-12, DSC-1, CHAT-30, NOTE-20, GEN-17:
        the team's coach books with a split fee or one payer, with or without a court."""
        coach, cora = self.user("coach", is_coach=True), self.user("cora", is_coach=True)
        hal, ian, joy, pat = (self.user(n) for n in ("hal", "ian", "joy", "pat"))
        team = self.make_team(coach, [hal, ian])
        GroupMember.objects.create(group=team, user=joy, status="invited")
        sam, zed = self.shadow("Sam", coach), self.shadow("Zed", cora)
        for shadow in (sam, zed):
            GroupMember.objects.create(group=team, user=shadow, status="active")
        play = Group.objects.create(type="play_group", name="Friends", created_by=coach)
        wide = {"starts_at": dt.datetime(2027, 1, 1, tzinfo=UTC), "ends_at": dt.datetime(2027, 12, 31, tzinfo=UTC)}
        mine = Discount.objects.create(club=self.club, user=coach, percent_off=10, message="Coach", **wide)
        Discount.objects.create(club=self.club, user=hal, percent_off=50, message="Hal", **wide)
        court = self.court1.id
        start, end = at(MON, 10), at(MON, 12)

        # who may, then the booking rules; nothing is written
        self.train(pat, start, end, expect=403, group=team.id)  # not a coach
        self.train(cora, start, end, expect=403, group=team.id)  # a coach, but not the team's
        self.code(self.train(coach, start, end, expect=400, group=play.id), "not_a_team")
        self.assertIn("group", self.train(coach, start, end, expect=400, group=99999).data)
        self.assertIn("player", self.train(coach, start, end, expect=400).data)  # neither
        self.assertIn("player", self.train(coach, start, end, expect=400, group=team.id, player=hal.id).data)  # both
        self.assertIn("coach_fee", self.train(coach, start, end, fee="-1", expect=400, group=team.id).data)
        self.code(self.train(coach, start, end, "GBP", expect=400, group=team.id, court=court), "currency_not_accepted")
        volleyball_only = self.court("Court V", sports=[self.volleyball]).id
        self.code(self.train(coach, start, end, expect=400, group=team.id, court=volleyball_only), "sport_not_offered")
        self.code(self.train(coach, at(MON, 8), at(MON, 10), expect=400, group=team.id, court=court), "not_bookable")  # BOOK-4
        # BOOK-32, ACC-12: the payer is an active member and not the coach; a shadow player only for their own coach
        for payer in (coach.id, joy.id, pat.id, zed.id, 99999):
            r = self.train(coach, start, end, expect=400, group=team.id, court=court, coach_fee_payer=payer)
            self.assertIn("coach_fee_payer", r.data)
        self.assertEqual(Session.objects.count(), 0)

        # BOOK-30, BOOK-33: split fee, court price with the coach's own offer (10%, not hal's 50%), card, invites
        r = self.train(coach, start, end, group=team.id, court=court, push=True)
        session = Session.objects.get(pk=r.data["id"])
        self.assertEqual((session.kind, session.status, session.booked_by, session.coach, session.group),
                         ("training", "confirmed", coach, coach, team))
        self.assertEqual((session.price, session.discount, session.discount_amount), (Decimal("100"), mine, Decimal("10")))
        self.assertEqual((session.coach_fee, session.coach_fee_payer), (Decimal("40"), None))  # split (PAY-12)
        self.assertEqual(self.names(session), {"Coach": "accepted", "Hal": "invited", "Ian": "invited",
                                               "Sam": "accepted", "Zed": "accepted"})
        for user in (hal, ian):
            self.assertEqual([p["data"]["id"] for p in self.pushed(user, "session_invite")], [str(session.id)])
        self.assertEqual({p["user_id"] for p in accounts.outbox}, {hal.id, ian.id})
        card = Message.objects.get(session=session)  # BOOK-60
        self.assertEqual((card.chat.group, card.sender), (team, None))
        self.code(self.train(coach, start, end, expect=409, group=team.id, court=court), "slot_taken")  # BOOK-2

        # BOOK-30 without a court, one payer: price 0, no offer, any currency (decimals as GEN-17), card posted
        r = self.train(coach, at(MON, 13), at(MON, 14), "GBP", "12.505", expect=400, group=team.id)
        self.assertIn("coach_fee", r.data)
        r = self.train(coach, at(MON, 13), at(MON, 14), "GBP", "12.5", group=team.id, coach_fee_payer=hal.id)
        self.assertEqual((r.data["court"], r.data["price"], r.data["discount"], r.data["currency"]),
                         (None, "0.000", None, "GBP"))
        self.assertEqual((r.data["coach_fee"], r.data["coach_fee_payer"]), ("12.500", hal.id))
        self.assertTrue(Message.objects.filter(session_id=r.data["id"]).exists())
        # a shadow player the coach manages may be the payer (ACC-12); an explicit null is the split
        r = self.train(coach, at(MON, 14), at(MON, 15), group=team.id, coach_fee_payer=sam.id)
        self.assertEqual(r.data["coach_fee_payer"], sam.id)
        r = self.train(coach, at(MON, 15), at(MON, 16), group=team.id, coach_fee_payer=None)
        self.assertEqual(r.data["coach_fee_payer"], None)
        self.assertIn("starts_at", self.train(coach, NOW, at(MON, 15), expect=400, group=team.id).data)  # not in the future

    def test_one_player_training_journey(self):
        """BOOK-31, BOOK-32, BOOK-33, BOOK-60, ACC-1, ACC-12, DSC-1, NOTE-20: for each kind of the coach's players."""
        coach, cora = self.user("coach", is_coach=True), self.user("cora", is_coach=True)
        ann, bob, cat, dan, eve, pat = (self.user(n) for n in ("ann", "bob", "cat", "dan", "eve", "pat"))
        Connection.objects.create(user=coach, other_user=ann, type="coaching", status="accepted")  # coaching link
        Connection.objects.create(user=coach, other_user=dan, type="coaching", status="pending")  # not yet
        team = self.make_team(coach, [bob])  # team member
        GroupMember.objects.create(group=team, user=cat, status="invited")  # not active
        shadow, other_shadow = self.shadow("Shad", coach), self.shadow("Other", cora)
        wide = {"starts_at": dt.datetime(2027, 1, 1, tzinfo=UTC), "ends_at": dt.datetime(2027, 12, 31, tzinfo=UTC)}
        Discount.objects.create(club=self.club, user=coach, percent_off=10, message="Coach", **wide)

        # BOOK-31: not a player of the coach (a pending link, an invited member, a stranger, another coach's shadow player)
        for stranger in (dan, cat, eve, other_shadow, coach):
            self.code(self.train(coach, at(MON, 9), at(MON, 10), expect=400, player=stranger.id), "not_your_player")
        self.code(self.train(coach, at(MON, 9), at(MON, 10), expect=400, player=99999), "not_your_player")
        self.train(pat, at(MON, 9), at(MON, 10), expect=403, player=ann.id)  # not a coach
        self.assertEqual(Session.objects.count(), 0)

        # a coaching link, with a court: the coach is the booker and gets the offer (BOOK-33); the player is invited
        r = self.train(coach, at(MON, 10), at(MON, 11), fee="25", player=ann.id, court=self.court1.id, push=True)
        session = Session.objects.get(pk=r.data["id"])
        self.assertEqual((session.kind, session.status, session.booked_by, session.coach, session.group),
                         ("training", "confirmed", coach, coach, None))
        self.assertEqual((session.price, session.discount_amount, session.coach_fee),
                         (Decimal("50"), Decimal("5"), Decimal("25")))
        self.assertEqual(session.coach_fee_payer, ann)  # BOOK-31: defaults to the player
        self.assertEqual(self.names(session), {"Coach": "accepted", "Ann": "invited"})
        self.assertEqual([p["data"]["id"] for p in self.pushed(ann, "session_invite")], [str(session.id)])
        self.assertEqual({p["user_id"] for p in accounts.outbox}, {ann.id})

        # a team member (an explicit null payer means the default); a shadow player is accepted and gets no push
        accounts.outbox.clear()
        r = self.train(coach, at(MON, 13), at(MON, 14), "LBP", "500000", player=bob.id, coach_fee_payer=None, push=True)
        self.assertEqual((r.data["coach_fee"], r.data["coach_fee_payer"]), ("500000.000", bob.id))
        self.assertEqual(self.names(Session.objects.get(pk=r.data["id"])), {"Coach": "accepted", "Bob": "invited"})
        r = self.train(coach, at(MON, 14), at(MON, 15), "EUR", "20", player=shadow.id, push=True)
        session = Session.objects.get(pk=r.data["id"])
        self.assertEqual(self.names(session), {"Coach": "accepted", "Shad": "accepted"})
        self.assertEqual((session.coach_fee_payer, session.price, session.court), (shadow, 0, None))
        self.assertEqual({p["user_id"] for p in accounts.outbox}, {bob.id})
        self.assertFalse(Message.objects.exists())  # no group, no card (BOOK-60)

        # BOOK-32: an explicit payer is the player; nobody else, not the coach
        for payer in (bob.id, coach.id):
            r = self.train(coach, at(MON, 15), at(MON, 16), expect=400, player=ann.id, coach_fee_payer=payer)
            self.assertIn("coach_fee_payer", r.data)
        r = self.train(coach, at(MON, 15), at(MON, 16), player=ann.id, coach_fee_payer=ann.id)
        self.assertEqual(r.data["coach_fee_payer"], ann.id)
        r = self.train(coach, at(MON, 16), at(MON, 17), player=shadow.id, coach_fee_payer=shadow.id)  # ACC-12: their coach
        self.assertEqual(r.data["coach_fee_payer"], shadow.id)

    def test_request_fee_choices(self):
        """BOOK-20, BOOK-21, BOOK-23, PAY-9, PAY-10, PAY-11, PAY-12, BOOK-15: the requester chooses how each fee is paid;
        the choice survives the coach's confirmation and decides who pays at billing."""
        rana, ali, coach = self.user("rana"), self.user("ali"), self.user("coach", is_coach=True)
        self.befriend(rana, ali)
        full = Session.objects.get(pk=self.request(rana, coach, at(MON, 10), at(MON, 11)).data["id"])
        self.assertEqual((full.court_fee_split, full.coach_fee_payer), (False, rana))
        r = self.request(rana, coach, at(MON, 12), at(MON, 13), court_fee_split=True, coach_fee_split=True)
        self.assertEqual((r.data["court_fee_split"], r.data["coach_fee_payer"]), (True, None))
        split = Session.objects.get(pk=r.data["id"])
        self.assertIn("court_fee_split", self.request(rana, coach, at(MON, 14), at(MON, 15), 400, court_fee_split="maybe").data)
        for session in (full, split):
            r = self.confirm(coach, session.id, session.starts_at, session.ends_at, fee="30.00", court=self.court1.id)
            self.assertEqual((r.data["court_fee_split"], r.data["coach_fee_payer"]),
                             (session.court_fee_split, session.coach_fee_payer_id))
            self.call("post", f"sessions/{session.id}/participants/", rana, {"invitees": [ali.id]}, 201)  # BOOK-23
            self.call("patch", f"sessions/{session.id}/participants/{ali.id}/", ali, {"status": "accepted"}, 200)
            self.clock.return_value = session.starts_at
            for user in (rana, ali):  # the coach of a request has no participant row
                self.call("post", f"sessions/{session.id}/participants/{user.id}/check-in/", coach, expect=200)
            self.clock.return_value = NOW
        self.clock.return_value = at(TUE, 18)
        call_command("tick", stdout=StringIO())
        owed = lambda s: [(p.payer.full_name, "club" if p.club_id else "coach", p.amount)  # noqa: E731
                          for p in s.payments.order_by("id").select_related("payer")]
        self.assertEqual(owed(full), [("Rana", "club", Decimal("50")), ("Rana", "coach", Decimal("30.00"))])
        # split: Rana and Ali attended; the remainder-free shares
        self.assertEqual(owed(split), [("Rana", "club", Decimal("25")), ("Ali", "club", Decimal("25")),
                                       ("Rana", "coach", Decimal("15.00")), ("Ali", "coach", Decimal("15.00"))])

    def test_hand_over_moves_upcoming_training(self):
        """TEAM-29, ACC-1, PAY-13, BOOK-65, RPT-6: on hand-over the team's upcoming team training passes to the new
        coach, who becomes its booker and takes the previous coach's first row; sessions that started, one-player
        training and other teams' sessions stay; the old coach keeps what they ran."""
        coach, cora = self.user("coach", is_coach=True), self.user("cora", is_coach=True)
        hal, ann = self.user("hal"), self.user("ann")
        team = self.make_team(coach, [hal])
        other = self.make_team(coach, [ann], name="Others")
        Connection.objects.create(user=coach, other_user=ann, type="coaching", status="accepted")
        started = Session.objects.get(pk=self.train(coach, at(MON, 10), at(MON, 11), group=team.id, coach_fee_payer=hal.id,
                                                    court=self.court1.id, court_fee_split=True).data["id"])
        upcoming = Session.objects.get(pk=self.train(coach, at(MON, 12), at(MON, 13), group=team.id, coach_fee_payer=hal.id,
                                                     court=self.court1.id, court_fee_split=True).data["id"])
        joined = Session.objects.get(pk=self.train(coach, at(MON, 14), at(MON, 15), group=team.id).data["id"])
        SessionParticipant.objects.create(session=joined, user=cora, status="accepted")  # Cora was already on it
        others = Session.objects.get(pk=self.train(coach, at(MON, 12), at(MON, 13), group=other.id).data["id"])
        one = Session.objects.get(pk=self.train(coach, at(MON, 16), at(MON, 17), player=ann.id).data["id"])
        first_row = upcoming.participants.get(user=coach).id
        self.clock.return_value = at(MON, 10, 30)  # `started` is under way
        self.call("post", f"groups/{team.id}/coach/", coach, {"coach": cora.id}, 200)

        for session in (started, upcoming, joined, others, one):
            session.refresh_from_db()
        self.assertEqual((started.coach, started.booked_by), (coach, coach))
        self.assertEqual((upcoming.coach, upcoming.booked_by), (cora, cora))
        # prices, fees and fee choices stay as booked; the booker's row is the same first row, now Cora's
        self.assertEqual((upcoming.price, upcoming.coach_fee, upcoming.coach_fee_payer, upcoming.court_fee_split),
                         (Decimal("50"), Decimal("40"), hal, True))
        self.assertEqual(upcoming.participants.order_by("id").first().id, first_row)
        self.assertEqual(self.names(upcoming), {"Cora": "accepted", "Hal": "invited"})
        self.assertEqual((joined.coach, self.names(joined)), (cora, {"Cora": "accepted", "Hal": "invited"}))
        self.assertEqual((others.coach, one.coach), (coach, coach))  # another team and one-player training stay
        # BOOK-65: the old coach no longer sees the moved session; the new one does; the started one stays the old coach's
        self.call("get", f"sessions/{upcoming.id}/", coach, expect=404)
        self.call("get", f"sessions/{upcoming.id}/", cora, expect=200)
        self.call("get", f"sessions/{started.id}/attendance/", coach, expect=200)
        self.call("get", f"sessions/{started.id}/attendance/", cora, expect=404)

    def test_user_availability_journey(self):
        """AVL-20, AVL-22, AVL-23, AVL-24, GEN-4, GEN-7, GEN-8, ACC-1, TEAM-40: a weekly block-out in the user's own
        timezone, sessions that count and sessions that do not, merging, the min_minutes filter, who may ask, bad ranges."""
        una, bob, coach = self.user("una", timezone="Asia/Beirut"), self.user("bob"), self.user("coach", is_coach=True)
        Connection.objects.create(user=coach, other_user=una, type="coaching", status="accepted")
        shadow = self.shadow("Shad", coach)
        # Monday 00:00-01:00 and 09:00-12:00 Beirut (Sunday 22:00-23:00Z and Monday 07:00-10:00Z), weekly from 4 January
        for a, b in ((0, 1), (9, 12)):
            UserBlockout.objects.create(user=una, starts_on=dt.date(2027, 1, 4), start_time=dt.time(a),
                                        end_time=dt.time(b), repeat="weekly")

        def row(start, end, user, answer, **fields):  # a session of bob's where `user` has a participant row
            s = self.session(self.court1, start, end, bob, **fields)
            SessionParticipant.objects.create(session=s, user=user, status=answer)

        row(at(MON, 12), at(MON, 13), una, "accepted")  # counts: touches the block-out, so one busy stretch 09-13
        row(at(MON, 13), at(MON, 14), una, "accepted", status="cancelled")  # none of these count
        row(at(MON, 14), at(MON, 15), una, "invited")
        row(at(MON, 14, 30), at(MON, 15, 30), una, "declined")
        row(at(MON, 15), at(MON, 16), una, "accepted", status="requested")  # AVL-20: a request does not make anyone busy
        self.session(self.court1, at(MON, 16), at(MON, 17), bob, coach=una)  # counts: una is the session coach
        row(at(MON, 14), at(MON, 15), shadow, "accepted")  # the shadow player is busy 14-15
        day = (at(MON, 0), at(TUE, 0))

        # AVL-20, AVL-23, GEN-8: free 01-09, 13-16, 17-24 Beirut; the block-out is placed in una's timezone
        self.assertEqual(self.free(una, "users", una.id, *day),
                         [(z(at(MON, 1)), z(at(MON, 9))), (z(at(MON, 13)), z(at(MON, 16))), (z(at(MON, 17)), z(at(TUE, 0)))])
        # min_minutes: "at least", so the 180 minutes of 13-16 stay at 180 and go at 181
        self.assertEqual(len(self.free(una, "users", una.id, *day, min_minutes=180)), 3)
        self.assertEqual(len(self.free(una, "users", una.id, *day, min_minutes=181)), 2)
        self.assertEqual(self.free(una, "users", una.id, *day, min_minutes=1440), [])
        # AVL-23: one interval across midnight, not cut at it
        self.assertEqual(self.free(una, "users", una.id, at(MON, 0), at(TUE, 12))[-1], (z(at(MON, 17)), z(at(TUE, 12))))
        # inside a busy stretch there is nothing; with no busy time the whole range is free
        self.assertEqual(self.free(una, "users", una.id, at(MON, 10), at(MON, 11)), [])
        self.assertEqual(self.free(una, "users", una.id, at(TUE, 8), at(TUE, 9)), [(z(at(TUE, 8)), z(at(TUE, 9)))])

        # AVL-22: the user, or a coach about their player (a link, or a shadow player of their own); others 404
        self.free(coach, "users", una.id, *day)
        self.assertEqual(self.free(coach, "users", shadow.id, *day),
                         [(z(at(MON, 0)), z(at(MON, 14))), (z(at(MON, 15)), z(at(TUE, 0)))])
        self.free(bob, "users", una.id, *day, expect=404)
        self.free(coach, "users", bob.id, *day, expect=404)
        self.free(una, "users", bob.id, *day, expect=404)
        self.free(una, "users", 99999, *day, expect=404)
        self.free(bob, "users", una.id, at(TUE, 0), at(MON, 0), expect=404)  # permission before input (GEN-4)

        # AVL-24, AVL-23: the range and its parts
        too_long = day[0] + dt.timedelta(days=14, seconds=1)
        for a, b in ((day[0], day[0]), (day[1], day[0]), (day[0], too_long)):
            self.code(self.free(una, "users", una.id, a, b, expect=400), "bad_range")
        self.free(una, "users", una.id, day[0], day[0] + dt.timedelta(days=14))  # exactly 14 days is fine
        for minutes in (4, 1441):
            self.assertIn("min_minutes", self.free(una, "users", una.id, *day, min_minutes=minutes, expect=400).data)
        self.client.force_authenticate(una)
        self.assertIn("from", self.client.get(f"/api/users/{una.id}/availability/", {"to": z(day[1])}).data)
        r = self.client.get(f"/api/users/{una.id}/availability/", {"from": "2027-01-11T00:00:00", "to": z(day[1])})
        self.assertEqual(r.status_code, 400)  # GEN-7

    def test_group_availability_journey(self):
        """AVL-20, AVL-21, AVL-22, AVL-23, AVL-24, AVL-25, GEN-4: a group is free when every active member is free;
        shadow players' sessions count; invited members, requests and other people's courts do not; who may ask."""
        coach, cora = self.user("coach", is_coach=True), self.user("cora", is_coach=True)
        hal, ian, joy, pat = self.user("hal", timezone="Asia/Beirut"), self.user("ian"), self.user("joy"), self.user("pat")
        team = self.make_team(coach, [hal, ian])
        sam = self.shadow("Sam", coach)
        GroupMember.objects.create(group=team, user=sam, status="active")
        GroupMember.objects.create(group=team, user=joy, status="invited")

        def at_z(hour):
            return dt.datetime(2027, 1, 11, hour, tzinfo=UTC)

        # busy: hal 09-10 Beirut = 07-08Z; ian 10-11Z; sam in another coach's session 14-15Z
        for user, a, b in ((hal, 9, 10), (ian, 10, 11)):
            UserBlockout.objects.create(user=user, starts_on=dt.date(2027, 1, 4), start_time=dt.time(a),
                                        end_time=dt.time(b), repeat="weekly")
        s = self.session(self.court2, at_z(14), at_z(15), cora)
        SessionParticipant.objects.create(session=s, user=sam, status="accepted")
        # not busy: an invited member all day, a request, a court booking of someone outside the group (AVL-25)
        UserBlockout.objects.create(user=joy, starts_on=dt.date(2027, 1, 1), start_time=dt.time(0), end_time=dt.time(0), repeat="daily")
        self.session(self.court1, at_z(12), at_z(13), hal, status="requested")
        self.session(self.court1, at_z(8), at_z(9), pat)
        window = (at_z(7), at_z(16))

        expected = [(z(at_z(8)), z(at_z(10))), (z(at_z(11)), z(at_z(14))), (z(at_z(15)), z(at_z(16)))]
        self.assertEqual(self.free(coach, "groups", team.id, *window), expected)
        self.assertEqual(self.free(ian, "groups", team.id, *window), expected)  # an active member may ask
        self.assertEqual(self.free(coach, "groups", team.id, *window, min_minutes=150), [(z(at_z(11)), z(at_z(14)))])

        # AVL-22: members and managers only; the invited, strangers and unknown groups 404
        self.free(joy, "groups", team.id, *window, expect=404)
        self.free(pat, "groups", team.id, *window, expect=404)
        self.free(pat, "groups", 99999, *window, expect=404)
        self.free(pat, "groups", team.id, window[1], window[0], expect=404)  # permission before input (GEN-4)
        self.code(self.free(coach, "groups", team.id, window[1], window[0], expect=400), "bad_range")  # AVL-24

        # AVL-21: a group with no active members is free at every instant; its manager may ask
        empty = Group.objects.create(type="play_group", name="Empty", created_by=cora)
        self.assertEqual(self.free(cora, "groups", empty.id, *window), [(z(window[0]), z(window[1]))])
        self.free(ian, "groups", empty.id, *window, expect=404)


class PaymentBase(BookingBase):
    """BookingBase plus the seeded default commission (SEED-2: 10% for clubs and for coaches)."""

    def setUp(self):
        super().setUp()
        for kind in ("club", "coach"):
            CommissionRate.objects.create(applies_to=kind, percent=Decimal("10"), effective_from=dt.date(2026, 1, 1))

    def check_in(self, user, session, target=None, expect=200):
        return self.call("post", f"sessions/{session.id}/participants/{(target or user).id}/check-in/", user, expect=expect)

    def owed(self, session):
        """[(payer, payee kind, amount, platform fee)] in creation order."""
        return [(p.payer.full_name, "club" if p.club_id else "coach", p.amount, p.platform_fee)
                for p in session.payments.order_by("id").select_related("payer")]

    def code(self, response, status, code):
        self.assertEqual((response.status_code, response.data["code"]), (status, code), response.data)

    def accept(self, user, session):
        self.call("patch", f"sessions/{session.id}/participants/{user.id}/", user, {"status": "accepted"}, 200)

    def tick(self):
        """One scheduler tick (NOTE-30) with pushes delivered as after commit; returns what it printed."""
        out = StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("tick", stdout=out)
        return out.getvalue()

    def train(self, coach, start, end, currency="USD", fee="40", expect=201, **extra):
        body = {"sport": self.basketball.id, "starts_at": z(start), "ends_at": z(end), "currency": currency,
                "coach_fee": fee, **extra}
        return Session.objects.get(pk=self.call("post", "sessions/training/", coach, body, expect).data["id"])


class CheckInTests(PaymentBase):
    def test_core_journey(self):
        """PAY-1, PAY-2, PAY-4, PAY-9, PAY-10, PAY-11, PAY-14, PAY-20, PAY-23, NOTE-33, COM-1, DSC-1, BOOK-16, BOOK-40,
        GEN-5, GEN-13, RPT-1, RPT-2, RPT-3, RPT-6: Rana books in EUR with a rental, the club approves it, Ben accepts and
        both check in; check-in creates nothing; the tick bills the court fee in full to Rana (113.90 EUR, fee 11.39) a day
        after the end, once; the owner marks it received."""
        rana, ben, sam = self.user("rana"), self.user("ben"), self.user("sam")
        self.staff(sam)
        self.befriend(rana, ben)
        self.past_bookings(rana, 4)
        offer = {"percent_off": "10", "starts_at": "2027-01-01T00:00:00Z", "ends_at": "2027-02-01T00:00:00Z", "message": "January promo"}
        self.call("post", f"clubs/{self.club.id}/offers/", self.owner, offer, 201)
        body = self.body(at(MON, 16), at(MON, 18), currency="EUR", rentals=[{"equipment": self.shooting.id, "quantity": 1}],
                         invitees=[ben.id])
        r = self.call("post", "sessions/", rana, body, 201)
        self.assertEqual((r.data["court_fee_split"], r.data["billed_at"]), (False, None))  # PAY-9: paid in full by default
        session = Session.objects.get(pk=r.data["id"])
        self.assertEqual((session.price, session.discount_amount), (Decimal("111.17"), Decimal("11.12")))
        self.call("patch", f"rentals/{session.rentals.get().id}/", sam, {"status": "approved"}, 200)  # BOOK-40
        self.accept(ben, session)  # BOOK-16

        # PAY-1: 30 minutes before the start is the first moment, a second earlier is too early
        self.clock.return_value = at(MON, 15, 30) - dt.timedelta(seconds=1)
        self.code(self.check_in(rana, session, expect=400), 400, "checkin_closed")
        self.clock.return_value = at(MON, 15, 30)
        self.check_in(ben, session)
        self.clock.return_value = at(MON, 15, 45)
        r = self.check_in(rana, session)
        self.assertEqual(r.data["checked_in_at"], z(at(MON, 15, 45)))
        # GEN-5: a repeat, and the club side checking the booker in again, change nothing
        self.clock.return_value = at(MON, 16, 5)
        self.assertEqual(self.check_in(rana, session).data["checked_in_at"], z(at(MON, 15, 45)))
        self.assertEqual(self.check_in(sam, session, rana).data["checked_in_at"], z(at(MON, 15, 45)))
        # PAY-4: checking in creates no payment; neither does a tick before ends_at + 24 h (PAY-10)
        self.assertEqual(session.payments.count(), 0)
        self.clock.return_value = at(MON, 18) + dt.timedelta(hours=24) - dt.timedelta(seconds=1)
        self.tick()
        session.refresh_from_db()
        self.assertEqual((session.payments.count(), session.billed_at), (0, None))

        # PAY-10, PAY-11, PAY-14: at ends_at + 24 h; the worked example, 111.17 - 11.12 + 13.85 = 113.90, fee 10% = 11.39
        billed = at(MON, 18) + dt.timedelta(hours=24)
        self.clock.return_value = billed
        self.assertIn("sessions billed: 1", self.tick())
        payment = session.payments.get()
        self.assertEqual((payment.payer, payment.club, payment.coach, payment.amount, payment.platform_fee, payment.currency),
                         (rana, self.club, None, Decimal("113.90"), Decimal("11.39"), "EUR"))
        self.assertEqual((payment.method, payment.paid_at, payment.settled_at, payment.waived_at), ("", None, None, None))
        session.refresh_from_db()
        self.assertEqual(session.billed_at, billed)
        # NOTE-33: a second tick bills nothing more
        self.clock.return_value = billed + dt.timedelta(minutes=1)
        self.assertIn("sessions billed: 0", self.tick())
        self.assertEqual(session.payments.count(), 1)
        self.assertEqual(self.call("get", f"sessions/{session.id}/", rana, expect=200).data["billed_at"], z(billed))

        # PAY-23, RPT-2: due, so it is in the payer's list, the payee side's lists and the due list, not in revenue
        rows = self.call("get", "payments/", rana, expect=200).data["results"]
        self.assertEqual([(r["amount"], r["platform_fee"], r["currency"], r["club"]["name"], r["payer"]["id"], r["paid_at"])
                          for r in rows], [("113.900", "11.390", "EUR", "Hoops", rana.id, None)])
        self.assertEqual(len(self.call("get", "payments/", sam, expect=200).data["results"]), 1)
        self.assertEqual(self.call("get", "payments/", ben, expect=200).data["results"], [])
        dues = self.call("get", f"clubs/{self.club.id}/dues/", sam, expect=200).data
        self.assertEqual(dues["totals"], [{"currency": "EUR", "total": "113.900"}])
        self.assertEqual([(d["session"], d["payer"]["full_name"], d["amount"]) for d in dues["payments"]],
                         [(session.id, "Rana", "113.900")])
        period = "from=2027-01-01&to=2027-01-31"
        self.assertEqual(self.call("get", f"clubs/{self.club.id}/revenue/?{period}", self.owner, expect=200).data, {"currencies": []})

        # PAY-20: the club owner marks it received; a repeat is a 200 that changes nothing (GEN-5)
        self.clock.return_value = at(TUE, 18, 10)
        r = self.call("post", f"payments/{payment.id}/mark-paid/", self.owner, expect=200)
        self.assertEqual((r.data["method"], r.data["paid_at"]), ("offline", z(at(TUE, 18, 10))))
        self.clock.return_value = at(TUE, 19)
        self.assertEqual(self.call("post", f"payments/{payment.id}/mark-paid/", sam, expect=200).data["paid_at"], z(at(TUE, 18, 10)))

        # RPT-3: now revenue (gross, fees, net per currency, owed to the platform); RPT-2: not due any more
        revenue = self.call("get", f"clubs/{self.club.id}/revenue/?{period}", self.owner, expect=200).data
        self.assertEqual(revenue, {"currencies": [{"currency": "EUR", "gross": "113.900", "fees": "11.390", "net": "102.510",
                                                   "owed_to_platform": "11.390"}]})
        self.assertEqual(self.call("get", f"clubs/{self.club.id}/dues/", sam, expect=200).data, {"payments": [], "totals": []})

        # RPT-1: it shows in the schedule (shown status completed, two accepted, rental approved); RPT-6: attendance
        r = self.call("get", f"clubs/{self.club.id}/schedule/?from=2027-01-11&to=2027-01-11", sam, expect=200).data
        row = r["sessions"][0]
        self.assertEqual((len(r["sessions"]), row["id"], row["status"], row["accepted_count"], row["booker"]["id"], row["court"]["name"]),
                         (1, session.id, "completed", 2, rana.id, "Court 1"))
        self.assertEqual([(x["quantity"], x["status"]) for x in row["rentals"]], [(1, "approved")])
        r = self.call("get", f"sessions/{session.id}/attendance/", sam, expect=200).data
        self.assertEqual((len(r["accepted"]), r["checked_in"], r["no_shows"]), (2, 2, []))

    def test_court_fee_split_journey(self):
        """PAY-9, PAY-10, PAY-11, PAY-13, PAY-14, PAY-15, PAY-16, BOOK-7, BOOK-51: the split worked example (Rana 37.98,
        Ali and Maya 37.96, Omar a no-show owes nothing); the booker pays a court fee in full even when absent; nobody
        attended: billed with no rows."""
        rana, ali, maya, omar = (self.user(n) for n in ("rana", "ali", "maya", "omar"))
        for friend in (ali, maya, omar):
            self.befriend(rana, friend)
        self.past_bookings(rana, 4)
        offer = {"percent_off": "10", "starts_at": "2027-01-01T00:00:00Z", "ends_at": "2027-02-01T00:00:00Z", "message": "Promo"}
        self.call("post", f"clubs/{self.club.id}/offers/", self.owner, offer, 201)
        body = self.body(at(MON, 16), at(MON, 18), currency="EUR", rentals=[{"equipment": self.shooting.id, "quantity": 1}],
                         invitees=[ali.id, maya.id, omar.id], court_fee_split=True)
        split = Session.objects.get(pk=self.call("post", "sessions/", rana, body, 201).data["id"])
        self.assertTrue(split.court_fee_split)
        self.call("patch", f"rentals/{split.rentals.get().id}/", self.owner, {"status": "approved"}, 200)
        for friend in (ali, maya, omar):
            self.accept(friend, split)
        full = Session.objects.get(pk=self.book(rana, at(MON, 9), at(MON, 10), invitees=[ali.id]).data["id"])
        self.accept(ali, full)
        empty = Session.objects.get(pk=self.book(rana, at(MON, 11), at(MON, 12), court_fee_split=True).data["id"])

        # PAY-2: the booker checks Ali and Maya in; Omar does not come. Ali alone attends the paid-in-full session
        self.clock.return_value = at(MON, 16)
        for user in (rana, ali, maya):
            self.check_in(rana, split, user)
        self.clock.return_value = at(MON, 9)
        self.check_in(ali, full)
        self.clock.return_value = at(TUE, 18)
        self.assertIn("sessions billed: 7", self.tick())  # these three and Rana's four past bookings (nobody checked in)
        # PAY-13: 113.90 / 3 = 37.96 rounded down, remainder 0.02 to the first row (the booker); fees 3.80 each
        self.assertEqual(self.owed(split), [("Rana", "club", Decimal("37.98"), Decimal("3.80")),
                                            ("Ali", "club", Decimal("37.96"), Decimal("3.80")),
                                            ("Maya", "club", Decimal("37.96"), Decimal("3.80"))])
        self.assertFalse(Payment.objects.filter(payer=omar).exists())  # PAY-16
        # PAY-11: paid in full, the booker owes it even though only Ali attended
        self.assertEqual(self.owed(full), [("Rana", "club", Decimal("45.00"), Decimal("4.50"))])  # the 10% offer applied
        # PAY-10, BOOK-51: nobody attended: billed, nothing owed
        empty.refresh_from_db()
        self.assertEqual((empty.billed_at, empty.payments.count()), (at(TUE, 18), 0))

    def test_team_training_split_journey(self):
        """PAY-11, PAY-12, PAY-13, PAY-14, PAY-15, PAY-16, PAY-10, PAY-23, GEN-15, COM-1, BOOK-30, BOOK-33, ACC-12: the
        team training worked example in LBP (Omar a no-show), the same with Omar, the USD variant, one payer who did not
        come, a free fee, a member who left the team and still came, a split court fee with only the coach there."""
        sami = self.user("sami", is_coach=True)
        kid, maya, omar = self.shadow("Kid A", sami), self.user("maya"), self.user("omar")
        team = self.make_team(sami, [kid, maya, omar], name="U12")
        court = self.court1.id
        sessions = {
            "lbp": self.train(sami, at(MON, 10), at(MON, 11), "LBP", "250000", group=team.id, court=court),
            "all": self.train(sami, at(MON, 11), at(MON, 12), "LBP", "250000", group=team.id),
            "usd": self.train(sami, at(MON, 12), at(MON, 13), "USD", "100.00", group=team.id),
            "one": self.train(sami, at(MON, 13), at(MON, 14), "LBP", "250000", group=team.id, coach_fee_payer=omar.id),
            "free": self.train(sami, at(MON, 14), at(MON, 15), "USD", "0", group=team.id),
            "left": self.train(sami, at(MON, 15), at(MON, 16), "USD", "100.00", group=team.id),
            "coach": self.train(sami, at(MON, 16), at(MON, 17), "USD", "0", group=team.id, court=court, court_fee_split=True),
        }
        for session in sessions.values():
            for user in (maya, omar):
                self.accept(user, session)
            self.assertEqual(session.participants.count(), 4)
        kid_row = sessions["lbp"].participants.get(user=kid)
        self.assertLess(kid_row.id, sessions["lbp"].participants.get(user=maya).id)  # PAY-13: ordered by row id
        came = {"lbp": (sami, kid, maya), "all": (sami, kid, maya, omar), "usd": (sami, kid, maya, omar),
                "one": (sami, kid), "free": (sami, kid, maya), "left": (kid, maya, omar), "coach": (sami,)}
        self.call("delete", f"groups/{team.id}/members/{omar.id}/", omar, expect=204)  # Omar leaves; attendance decides
        for name, people in came.items():
            self.clock.return_value = sessions[name].starts_at
            for user in people:
                self.check_in(sami, sessions[name], user)  # PAY-2: the session coach checks anyone in
        self.clock.return_value = at(TUE, 17)
        self.assertIn("sessions billed: 7", self.tick())

        # the worked example: the court fee in full by the booker (the coach, BOOK-33), the coach fee split between
        # the attendees but the coach; Omar is a no-show (PAY-16); a shadow player is a payer (ACC-12)
        self.assertEqual(self.owed(sessions["lbp"]), [
            ("Sami", "club", Decimal("4475000"), Decimal("447500")),
            ("Kid A", "coach", Decimal("125000"), Decimal("12500")),
            ("Maya", "coach", Decimal("125000"), Decimal("12500"))])
        self.assertEqual(Payment.objects.get(session=sessions["lbp"], payer=maya).currency, "LBP")
        # had Omar come too: 83 334 / 83 333 / 83 333, fees 8 333 (GEN-15: whole pounds)
        self.assertEqual(self.owed(sessions["all"]), [
            ("Kid A", "coach", Decimal("83334"), Decimal("8333")),
            ("Maya", "coach", Decimal("83333"), Decimal("8333")),
            ("Omar", "coach", Decimal("83333"), Decimal("8333"))])
        self.assertEqual(sum(p.amount for p in sessions["all"].payments.all()), Decimal("250000"))
        # the USD variant (no court, so only the coach fee): 33.34, 33.33, 33.33 with fees 3.33 each
        self.assertEqual(self.owed(sessions["usd"]), [
            ("Kid A", "coach", Decimal("33.34"), Decimal("3.33")),
            ("Maya", "coach", Decimal("33.33"), Decimal("3.33")),
            ("Omar", "coach", Decimal("33.33"), Decimal("3.33"))])
        # PAY-12: paid in full by Omar, who did not come: still owed (the coach may waive it, PAY-25)
        self.assertEqual(self.owed(sessions["one"]), [("Omar", "coach", Decimal("250000"), Decimal("25000"))])
        # PAY-15: a zero coach fee and no court create no row at all
        self.assertEqual(sessions["free"].payments.count(), 0)
        # PAY-12: Omar left the team and still came: he pays a share; the coach did not attend and pays nothing
        self.assertEqual(self.owed(sessions["left"]), [
            ("Kid A", "coach", Decimal("33.34"), Decimal("3.33")), ("Maya", "coach", Decimal("33.33"), Decimal("3.33")),
            ("Omar", "coach", Decimal("33.33"), Decimal("3.33"))])
        # PAY-11: a split court fee with only the session coach there: the booker (the coach) pays it in full
        self.assertEqual(self.owed(sessions["coach"]), [("Sami", "club", Decimal("50"), Decimal("5"))])
        # PAY-23: the coach sees the coach-fee rows, Maya only hers, the club owner only the court fees
        self.assertEqual(len(self.call("get", "payments/", maya, expect=200).data["results"]), 4)
        self.assertEqual([r["amount"] for r in self.call("get", "payments/", self.owner, expect=200).data["results"]],
                         ["50.000", "4475000.000"])
        # NOTE-33: nothing bills twice
        self.clock.return_value = at(TUE, 18)
        self.tick()
        self.assertEqual(Payment.objects.count(), 3 + 3 + 3 + 1 + 0 + 3 + 1)

    def test_check_in_who_journey(self):
        """PAY-2, PAY-3, PAY-5, GEN-3, GEN-5, ACC-2, ACC-6, BOOK-65: a participant checks in their own row; the booker,
        the session coach, the club side and a shadow player's managing coach check in any accepted row; the refusals
        (404, 403, not_accepted, invalid_status) in the order permission, then rules."""
        rana, ben, cy, dee = (self.user(n) for n in ("rana", "ben", "cy", "dee"))
        sam, rival, expired, coach, cora, hal = (self.user(n) for n in ("sam", "rival", "expired", "coach", "cora", "hal"))
        for user in (coach, cora):
            user.is_coach = True
            user.save()
        self.staff(sam)
        self.staff(expired, expires_on=dt.date(2026, 12, 31))
        Club.objects.create(owner=rival, name="Elsewhere", timezone="Asia/Beirut", currency="USD")
        for friend in (ben, cy, dee):
            self.befriend(rana, friend)
        session = Session.objects.get(pk=self.book(rana, at(MON, 10), at(MON, 11), invitees=[ben.id, cy.id, dee.id]).data["id"])
        self.accept(ben, session)
        self.accept(cy, session)
        self.call("patch", f"sessions/{session.id}/participants/{dee.id}/", dee, {"status": "declined"}, 200)
        self.clock.return_value = at(MON, 9, 45)

        # PAY-2: a participant only their own row
        self.check_in(ben, session, rana, 403)
        self.check_in(ben, session, cy, 403)
        self.assertEqual(session.participants.filter(checked_in_at__isnull=False).count(), 0)
        # GEN-3 before PAY-2: not visible is 404, also another club's owner, expired staff, an unknown row
        for stranger in (rival, expired, coach, hal):
            self.check_in(stranger, session, rana, 404)
        self.call("post", f"sessions/{session.id}/participants/{hal.id}/check-in/", rana, expect=404)  # no such row
        self.call("post", "sessions/99999/participants/1/check-in/", rana, expect=404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f"/api/sessions/{session.id}/participants/{rana.id}/check-in/").status_code, 401)
        # PAY-5 not_accepted: a declined row, even by the booker
        self.code(self.check_in(rana, session, dee, 400), 400, "not_accepted")
        # PAY-2: the booker checks Ben in; PAY-3: staff checks Cy in, the owner repeats it (GEN-5); Rana herself
        self.check_in(rana, session, ben)
        self.check_in(sam, session, cy)
        self.check_in(self.owner, session, cy)
        self.check_in(rana, session)
        self.assertEqual(session.participants.filter(checked_in_at__isnull=False).count(), 3)

        # PAY-5 invalid_status: a cancelled session, and a training request that is not confirmed
        other = Session.objects.get(pk=self.book(rana, at(MON, 12), at(MON, 13), court=self.court2).data["id"])
        self.call("post", f"sessions/{other.id}/cancel/", rana, expect=200)
        self.clock.return_value = at(MON, 11, 45)
        self.code(self.check_in(rana, other, expect=400), 400, "invalid_status")
        request = Session.objects.get(pk=self.call("post", "training-requests/", rana, {
            "coach": coach.id, "sport": self.basketball.id, "starts_at": z(at(MON, 13)), "ends_at": z(at(MON, 14))}, 201).data["id"])
        self.clock.return_value = at(MON, 12, 45)
        self.code(self.check_in(rana, request, expect=400), 400, "invalid_status")

        # PAY-2: on team training the session coach checks in anyone; a shadow player's managing coach their own only
        kid, zed = self.shadow("Kid", coach), self.shadow("Zed", cora)
        team = self.make_team(coach, [kid, zed, hal])
        training = self.train(coach, at(MON, 15), at(MON, 16), group=team.id)
        self.assertEqual(training.participants.get(user=zed).status, "accepted")
        self.clock.return_value = at(MON, 14, 45)
        self.check_in(hal, training, kid, 403)  # a participant is not the shadow player's coach
        self.code(self.check_in(hal, training, expect=400), 400, "not_accepted")  # hal has not answered yet
        self.code(self.check_in(coach, training, hal, 400), 400, "not_accepted")
        self.accept(hal, training)
        self.check_in(coach, training, hal)  # the session coach, any accepted row
        self.check_in(coach, training, kid)
        self.call("get", f"sessions/{training.id}/", cora, expect=200)  # BOOK-65: the managing coach of a shadow participant sees it
        self.check_in(cora, training, hal, 403)  # but only for their own shadow players
        self.check_in(cora, training, zed)
        self.assertEqual(training.participants.filter(checked_in_at__isnull=False).count(), 3)

    def test_check_in_window_journey(self):
        """PAY-1, PAY-4, PAY-5, PAY-6, PAY-7, PAY-10, GEN-5, RPT-6: a participant checks in from 30 minutes before the
        start to the end, both included; the booker, the session coach, the club side and a shadow player's coach until
        ends_at + 24 h; no-shows appear once check-in has closed."""
        rana, ben, cy, sam, coach = (self.user(n) for n in ("rana", "ben", "cy", "sam", "coach"))
        coach.is_coach = True
        coach.save()
        kid = self.shadow("Kid", coach)
        self.staff(sam)
        for friend in (ben, cy):
            self.befriend(rana, friend)
        made = {}
        for name, hour in (("a", 9), ("b", 10), ("c", 11), ("d", 12)):
            made[name] = Session.objects.get(pk=self.book(rana, at(MON, hour), at(MON, hour + 1), invitees=[ben.id, cy.id]).data["id"])
            for friend in (ben, cy):
                self.accept(friend, made[name])
        second = dt.timedelta(seconds=1)

        # PAY-1: a second before 30 minutes is too early; the last instant for a participant is ends_at
        a = made["a"]
        self.clock.return_value = a.starts_at - dt.timedelta(minutes=30) - second
        self.code(self.check_in(ben, a, expect=400), 400, "checkin_closed")
        self.code(self.check_in(rana, a, ben, 400), 400, "checkin_closed")  # too early for the booker as well
        self.clock.return_value = a.ends_at
        self.check_in(ben, a)  # PAY-1: ends_at included
        self.clock.return_value = a.ends_at + second
        self.code(self.check_in(cy, a, expect=400), 400, "checkin_closed")  # PAY-7: a participant not after ends_at
        self.assertEqual(self.check_in(ben, a).status_code, 200)  # GEN-5: checked in already, still 200 after the window

        # PAY-7: late check-in by the booker (also of their own row) and by the club side, until ends_at + 24 h included
        self.clock.return_value = a.ends_at + dt.timedelta(hours=3)
        self.check_in(sam, a, cy)
        self.check_in(rana, a)
        b, c = made["b"], made["c"]
        self.clock.return_value = b.ends_at + dt.timedelta(hours=24)
        self.check_in(self.owner, b, ben)
        self.clock.return_value = c.ends_at + dt.timedelta(hours=24) + second
        for who, target in ((sam, rana), (rana, ben), (rana, rana), (self.owner, cy)):
            self.code(self.check_in(who, c, target, 400), 400, "checkin_closed")
        # ... and by the session coach and a shadow player's managing coach
        training = self.session(self.court2, at(MON, 13), at(MON, 14), rana, coach=coach)
        SessionParticipant.objects.create(session=training, user=kid, status="accepted")
        SessionParticipant.objects.create(session=training, user=ben, status="accepted")
        self.clock.return_value = at(MON, 14) + dt.timedelta(hours=24)
        self.check_in(coach, training, ben)
        self.check_in(coach, training, kid)
        self.assertEqual(training.participants.filter(checked_in_at__isnull=False).count(), 2)

        # PAY-6, RPT-6: no-shows only once check-in has closed (ends_at + 24 h); before that nobody is one
        d = made["d"]
        self.clock.return_value = d.ends_at + dt.timedelta(hours=24)
        r = self.call("get", f"sessions/{d.id}/attendance/", self.owner, expect=200).data
        self.assertEqual((len(r["accepted"]), r["checked_in"], r["no_shows"]), (3, 0, []))
        self.clock.return_value = d.ends_at + dt.timedelta(hours=24) + second
        r = self.call("get", f"sessions/{d.id}/attendance/", self.owner, expect=200).data
        self.assertEqual(sorted(n["full_name"] for n in r["no_shows"]), ["Ben", "Cy", "Rana"])
        r = self.call("get", f"sessions/{a.id}/attendance/", sam, expect=200).data
        self.assertEqual((r["checked_in"], r["no_shows"]), (3, []))
        r = self.call("get", f"sessions/{b.id}/attendance/", sam, expect=200).data
        self.assertEqual([n["full_name"] for n in r["no_shows"]], ["Rana", "Cy"])
        # PAY-4: check-in itself never created a payment
        self.assertFalse(Payment.objects.exists())

    def test_one_off_discount_journey(self):
        """DSC-10, DSC-11, DSC-12, DSC-13, DSC-14, DSC-4, PAY-8, PAY-11, PAY-15, GEN-3, GEN-4, GEN-17: the owner replaces
        the offer with a one-off amount, 0 removes it, it is not re-applied, and it freezes at the first check-in."""
        rana, sam, bob, ben = self.user("rana"), self.user("sam"), self.user("bob"), self.user("ben")
        self.staff(sam)
        self.befriend(rana, ben)
        self.past_bookings(rana, 4)
        offer = {"percent_off": "10", "starts_at": "2027-01-01T00:00:00Z", "ends_at": "2027-02-01T00:00:00Z", "message": "Promo"}
        offer_id = self.call("post", f"clubs/{self.club.id}/offers/", self.owner, offer, 201).data["id"]
        r = self.book(rana, at(MON, 16), at(MON, 18), currency="EUR", invitees=[ben.id])
        session = Session.objects.get(pk=r.data["id"])
        self.accept(ben, session)
        self.assertEqual((session.discount_id, session.discount_amount), (offer_id, Decimal("11.12")))
        path = f"sessions/{session.id}/discount/"

        # DSC-10: the owner only; staff and the booker see the session and get 403; strangers 404 (GEN-3, GEN-4)
        self.call("put", path, sam, {"amount": "20"}, 403)
        self.call("put", path, rana, {"amount": "20"}, 403)
        self.call("put", path, sam, {"amount": "bogus"}, 403)  # permission before input
        Club.objects.create(owner=bob, name="Elsewhere", timezone="Asia/Beirut", currency="USD")
        self.call("put", path, bob, {"amount": "20"}, 404)
        self.call("put", "sessions/99999/discount/", self.owner, {"amount": "20"}, 404)
        # DSC-11, DSC-14: amount per field: missing, below 0, above the price, too many decimals (EUR has 2)
        for bad in ({}, {"amount": "-0.01"}, {"amount": "111.18"}, {"amount": "1.234"}, {"amount": "abc"}):
            self.assertIn("amount", self.call("put", path, self.owner, bad, 400).data, bad)
        session.refresh_from_db()
        self.assertEqual((session.discount_id, session.discount_amount), (offer_id, Decimal("11.12")))

        # DSC-13: replaces the offer ("Rana gets 20.00 off"); the response is the session
        r = self.call("put", path, self.owner, {"amount": "20.00"}, 200)
        self.assertEqual((r.data["discount"], r.data["discount_amount"], r.data["id"]), (None, "20.000", session.id))
        self.call("put", path, self.owner, {"amount": "20.00"}, 200)  # a repeat
        # DSC-13: 0 removes it, and the removed one-off does not bring the offer back
        r = self.call("put", path, self.owner, {"amount": "0"}, 200)
        self.assertEqual((r.data["discount"], r.data["discount_amount"]), (None, "0.000"))
        self.assertEqual(self.call("put", path, self.owner, {"amount": "111.17"}, 200).data["discount_amount"], "111.170")  # the price itself
        self.call("put", path, self.owner, {"amount": "20.00"}, 200)

        # DSC-12, PAY-8: once anyone has checked in (here Ben, not the booker), it is frozen; the amount is still checked first
        self.clock.return_value = at(MON, 15, 45)
        self.check_in(ben, session)
        self.code(self.call("put", path, self.owner, {"amount": "5"}), 400, "already_payable")
        self.assertIn("amount", self.call("put", path, self.owner, {"amount": "-1"}, 400).data)
        self.clock.return_value = at(TUE, 18)
        self.tick()
        self.assertEqual(session.payments.get().amount, Decimal("91.17"))  # PAY-11: 111.17 - 20.00, the booker in full
        # DSC-14: a cancelled session; DSC-10: a training request has no court, so it is not the owner's
        self.clock.return_value = NOW
        other = Session.objects.get(pk=self.book(rana, at(MON, 12), at(MON, 13), court=self.court2).data["id"])
        self.call("post", f"sessions/{other.id}/cancel/", rana, expect=200)
        self.code(self.call("put", f"sessions/{other.id}/discount/", self.owner, {"amount": "5"}), 400, "session_cancelled")
        coach = self.user("coach", is_coach=True)
        request = self.call("post", "training-requests/", rana, {
            "coach": coach.id, "sport": self.basketball.id, "starts_at": z(at(MON, 14)), "ends_at": z(at(MON, 15))}, 201)
        self.call("put", f"sessions/{request.data['id']}/discount/", self.owner, {"amount": "0"}, 404)  # not visible to the owner

        # PAY-15, DSC-11: a session discounted by its whole price owes no court fee; LBP takes whole pounds only
        free = Session.objects.get(pk=self.book(rana, at(MON, 9), at(MON, 10), currency="LBP").data["id"])
        self.assertEqual(free.price, Decimal("4475000"))
        self.assertIn("amount", self.call("put", f"sessions/{free.id}/discount/", self.owner, {"amount": "100.5"}, 400).data)
        self.call("put", f"sessions/{free.id}/discount/", self.owner, {"amount": "4475000"}, 200)
        self.clock.return_value = at(MON, 8, 45)
        self.check_in(rana, free)
        self.clock.return_value = at(TUE, 10)
        self.tick()
        free.refresh_from_db()
        self.assertEqual((free.payments.count(), free.billed_at), (0, at(TUE, 10)))


class ReportTests(PaymentBase):
    def test_schedule_journey(self):
        """RPT-1, ACC-6, GEN-3, GEN-18, AVL-8, BOOK-55: the club side reads the schedule of the period with closures;
        sessions that overlap the period count, cancelled ones and other clubs' do not; bad ranges are refused."""
        rana, pat, sam, bob, expired, coach = (self.user(n) for n in ("rana", "pat", "sam", "bob", "expired", "coach"))
        self.staff(sam)
        self.staff(expired, expires_on=dt.date(2026, 12, 31))
        coach.is_coach = True
        coach.save()
        team = self.make_team(coach, [pat])
        sunday = dt.date(2027, 1, 10)
        s1 = self.session(self.court1, at(sunday, 23), at(MON, 0, 30), rana)  # overlaps the start of Monday
        s2 = self.session(self.court1, at(MON, 10), at(MON, 11), rana)
        s3 = self.session(self.court2, at(MON, 10), at(MON, 11), pat, coach=coach, group=team)
        Session.objects.filter(pk=s3.pk).update(kind="training")
        self.session(self.court1, at(MON, 12), at(MON, 13), rana, status="cancelled")  # not listed
        self.session(self.court1, at(sunday, 22), at(MON, 0), rana)  # ends exactly when Monday starts: not listed
        self.session(self.court1, at(TUE, 0), at(TUE, 1), rana)  # starts exactly when Monday ends: not listed
        other = Club.objects.create(owner=bob, name="Elsewhere", timezone="Asia/Beirut", currency="USD")
        self.session(self.court("Far court", club=other), at(MON, 10), at(MON, 11), rana)
        SessionRental.objects.create(session=s2, equipment=self.shooting, quantity=1, price=15, status="requested")
        SessionParticipant.objects.create(session=s2, user=pat, status="invited")  # not accepted: not counted
        CourtBlockout.objects.create(court=self.court1, starts_on=MON, start_time=dt.time(12), end_time=dt.time(13, 30), reason="Floor repair")
        CourtBlockout.objects.create(court=self.court2, starts_on=dt.date(2027, 1, 4), start_time=dt.time(18), end_time=dt.time(0),
                                     repeat="weekly", reason="League night")
        path = f"clubs/{self.club.id}/schedule/"
        day = "?from=2027-01-11&to=2027-01-11"

        # RPT-1: the club side (staff too, ACC-6); ordered by start; closures in the period
        for reader in (sam, self.owner):
            r = self.call("get", path + day, reader, expect=200).data
            self.assertEqual([s["id"] for s in r["sessions"]], [s1.id, s2.id, s3.id])
        first, second, third = r["sessions"]
        self.assertEqual((first["status"], first["court"], first["sport"]["name"], first["kind"], first["accepted_count"]),
                         ("confirmed", {"id": self.court1.id, "name": "Court 1"}, "Basketball", "play", 1))
        self.assertEqual((second["accepted_count"], second["group"], second["coach"]), (1, None, None))
        self.assertEqual([(x["status"], x["quantity"]) for x in second["rentals"]], [("requested", 1)])
        self.assertEqual((third["kind"], third["group"], third["coach"]["full_name"], third["booker"]["full_name"]),
                         ("training", "Wolves", "Coach", "Pat"))
        self.assertEqual(r["closures"], [
            {"court": self.court1.id, "starts_at": z(at(MON, 12)), "ends_at": z(at(MON, 13, 30)), "reason": "Floor repair"},
            {"court": self.court2.id, "starts_at": z(at(MON, 18)), "ends_at": z(at(TUE, 0)), "reason": "League night"}])
        # one court only; a court of another club is "Not found." on the field (GEN-18)
        r = self.call("get", path + day + f"&court={self.court2.id}", sam, expect=200).data
        self.assertEqual(([s["id"] for s in r["sessions"]], [c["reason"] for c in r["closures"]]), ([s3.id], ["League night"]))
        far = Court.objects.get(club=other)
        self.assertIn("court", self.call("get", path + day + f"&court={far.id}", sam, expect=400).data)
        # a period is local dates: the whole week has the closure again next Monday, and a day with nothing is empty
        r = self.call("get", path + "?from=2027-01-11&to=2027-01-18", sam, expect=200).data
        self.assertEqual([c["starts_at"] for c in r["closures"]], [z(at(MON, 12)), z(at(MON, 18)), z(at(dt.date(2027, 1, 18), 18))])
        self.assertEqual(self.call("get", path + "?from=2027-03-02&to=2027-03-02", sam, expect=200).data, {"sessions": [], "closures": []})

        # ACC-6, GEN-3: players and other clubs' owners may not (403, the club is public), an expired staff member neither
        for reader in (rana, bob, expired):
            self.call("get", path + day, reader, expect=403)
        ghost = Club.objects.create(owner=bob, name="Ghost", timezone="Asia/Beirut", currency="USD")  # no active court: not public
        self.call("get", f"clubs/{ghost.id}/schedule/{day}", rana, expect=404)
        self.call("get", "clubs/99999/schedule/" + day, rana, expect=404)
        # the period: both dates required; at most 366 days; `to` not before `from`
        self.assertIn("from", self.call("get", path + "?to=2027-01-11", sam, expect=400).data)
        self.assertIn("to", self.call("get", path + "?from=2027-01-11&to=11-01-2027", sam, expect=400).data)
        self.call("get", path + "?from=2027-01-01&to=2028-01-01", sam, expect=200)  # 366 days
        for bad in ("from=2027-01-01&to=2028-01-02", "from=2027-01-11&to=2027-01-10"):
            self.code(self.call("get", f"{path}?{bad}", sam), 400, "bad_range")

    def test_customers_journey(self):
        """RPT-4, RPT-5, ACC-6, GEN-8: distinct bookers in the period (club timezone), the repeat rate 66.67 of the
        worked example, ties by name, null with no customers; staff may not read it."""
        rana, ali, maya, ben, sam, bob = (self.user(n) for n in ("rana", "ali", "maya", "ben", "sam", "bob"))
        self.staff(sam)
        for day in (4, 11, 18):
            self.session(self.court1, at(dt.date(2027, 1, day), 10), at(dt.date(2027, 1, day), 11), rana)
        self.session(self.court2, at(dt.date(2027, 1, 5), 10), at(dt.date(2027, 1, 5), 11), ali)
        self.session(self.court2, at(dt.date(2027, 1, 6), 10), at(dt.date(2027, 1, 6), 11), ali, status="cancelled")  # not counted
        self.session(self.court1, at(dt.date(2027, 1, 12), 10), at(dt.date(2027, 1, 12), 11), maya)
        self.session(self.court1, at(dt.date(2027, 1, 31), 23), at(dt.date(2027, 2, 1), 0), maya)  # 23:00 local, still January
        self.session(self.court1, at(dt.date(2027, 2, 1), 0, 30), at(dt.date(2027, 2, 1), 1, 30), rana)  # 22:30Z on the 31st: February
        other = Club.objects.create(owner=bob, name="Elsewhere", timezone="Asia/Beirut", currency="USD")
        self.session(self.court("Far court", club=other), at(dt.date(2027, 1, 7), 10), at(dt.date(2027, 1, 7), 11), ali)
        path = f"clubs/{self.club.id}/customers/"

        # RPT-4, RPT-5: Rana x3, Ali x1, Maya x2: three customers, two repeat, 2 / 3 x 100 = 66.67
        r = self.call("get", path + "?from=2027-01-01&to=2027-01-31", self.owner, expect=200).data
        self.assertEqual((r["customers"], r["repeat_rate"]), (3, "66.67"))
        self.assertEqual([(p["full_name"], p["sessions"]) for p in r["people"]], [("Rana", 3), ("Maya", 2), ("Ali", 1)])
        self.assertEqual(r["people"][0]["id"], rana.id)
        # ties on the count go by name; nobody repeats: 0.00
        self.session(self.court2, at(dt.date(2027, 2, 2), 10), at(dt.date(2027, 2, 2), 11), ben)
        self.session(self.court2, at(dt.date(2027, 2, 3), 10), at(dt.date(2027, 2, 3), 11), ali)
        r = self.call("get", path + "?from=2027-02-01&to=2027-02-28", self.owner, expect=200).data
        self.assertEqual(([p["full_name"] for p in r["people"]], r["repeat_rate"]), (["Ali", "Ben", "Rana"], "0.00"))
        # no customers: the rate is null, not 0
        r = self.call("get", path + "?from=2027-06-01&to=2027-06-30", self.owner, expect=200).data
        self.assertEqual(r, {"customers": 0, "repeat_rate": None, "people": []})
        # ACC-6: the owner only; the bad range
        self.call("get", path + "?from=2027-01-01&to=2027-01-31", sam, expect=403)
        self.call("get", path + "?from=2027-01-01&to=2027-01-31", rana, expect=403)
        self.code(self.call("get", path + "?from=2027-01-01&to=2028-01-02", self.owner), 400, "bad_range")

    def test_attendance_and_player_history_journey(self):
        """RPT-6, RPT-8, RPT-9, ACC-1, GEN-3, GEN-12, TEAM-29: attendance for the session coach and the club side only; a coach reads a
        player's sessions with the training load, newest first, paged, 404 for someone who is not their player."""
        coach, cora = self.user("coach", is_coach=True), self.user("cora", is_coach=True)
        hal, ann, pat = self.user("hal"), self.user("ann"), self.user("pat")
        kid = self.shadow("Kid", coach)
        team = self.make_team(coach, [hal, kid])
        Connection.objects.create(user=coach, other_user=ann, type="coaching", status="accepted")

        def train(day, hour, status="confirmed", by=coach, who=hal, row="accepted", **row_fields):
            session = Session.objects.create(
                sport=self.basketball, booked_by=by, coach=by, kind="training", status=status, starts_at=at(day, hour),
                ends_at=at(day, hour + 1), currency="USD", price=0)
            SessionParticipant.objects.create(session=session, user=by, status="accepted")
            SessionParticipant.objects.create(session=session, user=who, status=row, **row_fields)
            return session

        t1 = train(MON, 10, checked_in_at=at(MON, 9, 50), rpe=6, rpe_minutes=60)
        t2 = train(TUE, 10, rpe=7)  # RPE without minutes: no load
        t3 = train(dt.date(2027, 1, 13), 10, rpe=5, rpe_minutes=30, checked_in_at=at(dt.date(2027, 1, 13), 10))
        train(dt.date(2027, 1, 14), 10, status="cancelled")  # not played
        train(dt.date(2027, 1, 15), 10, row="invited")  # never took part
        train(dt.date(2027, 1, 16), 10, by=cora)  # another coach's session
        train(dt.date(2027, 1, 17), 10, who=kid)  # the shadow player's, not hal's
        self.clock.return_value = at(dt.date(2027, 1, 20), 12)

        # RPT-8: newest first, with the training load rpe x minutes (empty when not logged)
        r = self.call("get", f"players/{hal.id}/sessions/", coach, expect=200).data
        self.assertEqual((r["count"], [x["session"] for x in r["results"]]), (3, [t3.id, t2.id, t1.id]))
        self.assertEqual([(x["rpe"], x["rpe_minutes"], x["training_load"]) for x in r["results"]],
                         [(5, 30, 150), (7, None, None), (6, 60, 360)])
        self.assertEqual((r["results"][2]["checked_in_at"], r["results"][2]["starts_at"], r["results"][2]["kind"]),
                         (z(at(MON, 9, 50)), z(at(MON, 10)), "training"))
        self.call("get", f"players/{hal.id}/sessions/?page=2", coach, expect=404)  # one page only (GEN-12)
        self.assertEqual(self.call("get", f"players/{kid.id}/sessions/", coach, expect=200).data["count"], 1)  # a shadow player
        self.assertEqual(self.call("get", f"players/{ann.id}/sessions/", coach, expect=200).data["count"], 0)  # a coaching connection
        # ACC-1, GEN-3, RPT-9: not the coach's player and never in their sessions, nobody, and a user who is not a coach
        self.call("get", f"players/{pat.id}/sessions/", coach, expect=404)
        # RPT-8: Cora is not Hal's coach but coached one session he took part in: she reads that one only
        self.assertEqual(self.call("get", f"players/{hal.id}/sessions/", cora, expect=200).data["count"], 1)
        # RPT-8: after a hand-over the former team coach keeps the sessions they ran (TEAM-29)
        self.call("post", f"groups/{team.id}/coach/", coach, {"coach": cora.id}, 200)
        self.assertNotIn(hal.pk, coachs_players(coach).values_list("pk", flat=True))
        self.assertEqual(self.call("get", f"players/{hal.id}/sessions/", coach, expect=200).data["count"], 3)
        self.call("get", "players/99999/sessions/", coach, expect=404)
        self.call("get", f"players/{hal.id}/sessions/", hal, expect=403)

        # RPT-6: after the end, Hal checked in and Coach did not; the session coach and the club side may read it
        t1.court = self.court1
        t1.save()
        sam = self.user("sam")
        self.staff(sam)
        r = self.call("get", f"sessions/{t1.id}/attendance/", coach, expect=200).data
        self.assertEqual((r["session"], len(r["accepted"]), r["checked_in"], [n["full_name"] for n in r["no_shows"]]),
                         (t1.id, 2, 1, ["Coach"]))
        self.assertEqual(self.call("get", f"sessions/{t1.id}/attendance/", sam, expect=200).data["checked_in"], 1)
        self.call("get", f"sessions/{t1.id}/attendance/", hal, expect=403)  # a participant sees the session, not the report
        self.call("get", f"sessions/{t1.id}/attendance/", cora, expect=404)
        self.call("get", "sessions/99999/attendance/", coach, expect=404)


GIB = 1024 ** 3


@override_settings(STORAGE_ENDPOINT="")  # REC-3: always the in-memory fake, even where real storage is configured
class RecordingTests(BookingBase):
    """Training on Monday 10:00-11:00 (Beirut): coach Carl, booker Rana, players Ben and Cara, shadow player Kid,
    Dan declined. Ben checked in at 10:30."""

    def setUp(self):
        super().setUp()
        get_storage.cache_clear()
        self.addCleanup(get_storage.cache_clear)
        self.storage = get_storage()
        self.storage.keys.clear()
        self.storage.forms.clear()
        self.coach = self.user("carl", is_coach=True)
        self.rana, self.ben, self.cara, self.dan, self.sam = (self.user(n) for n in ("rana", "ben", "cara", "dan", "sam"))
        self.kid = self.shadow("Kid", self.coach)
        self.play = self.session(self.court1, at(MON, 10), at(MON, 11), self.rana, coach=self.coach)
        for user, status in ((self.ben, "accepted"), (self.cara, "accepted"), (self.dan, "declined"), (self.kid, "accepted")):
            SessionParticipant.objects.create(session=self.play, user=user, status=status)
        self.clock.return_value = at(MON, 10, 30)
        self.call("post", f"sessions/{self.play.id}/participants/{self.ben.id}/check-in/", self.ben, expect=200)

    def form(self, user, session=None, name="game.mp4", size=1000, expect=200):
        return self.call("post", f"sessions/{(session or self.play).id}/recordings/form/", user,
                         {"file_name": name, "size_bytes": size}, expect)

    def confirm(self, user, key, session=None, expect=None, **extra):
        return self.call("post", f"sessions/{(session or self.play).id}/recordings/", user, {"storage_key": key, **extra}, expect)

    def upload(self, user, session=None, name="game.mp4", **extra):
        """The whole journey: form, the phone's upload, confirm. Returns the Recording."""
        key = self.form(user, session, name).data["storage_key"]
        self.storage.put(key)
        return Recording.objects.get(pk=self.confirm(user, key, session, expect=201, **extra).data["id"])

    def log_rpe(self, user):
        SessionParticipant.objects.filter(session=self.play, user=user).update(rpe=6)

    def code(self, response, status, code):
        self.assertEqual((response.status_code, response.data["code"]), (status, code), response.data)

    def test_upload_journey(self):
        """REC-1, REC-2, REC-3, REC-11, REC-12, REC-13, GEN-5: Ben (checked in) gets a form for a 500 MB mov, the confirm
        fails until the phone uploaded, then creates the row; a repeat is 200; the coach uploads too; bad input."""
        r = self.form(self.ben, name="Match.MOV", size=500_000_000)
        key = r.data["storage_key"]
        self.assertEqual(set(r.data), {"url", "fields", "storage_key"})
        self.assertRegex(key, rf"^recordings/{self.play.id}/{UUID}\.mov$")  # lowercase extension
        self.assertEqual(r.data["fields"]["key"], key)
        self.assertEqual(self.storage.forms[key], 500_000_000)  # REC-11: the policy's content-length range
        self.assertEqual(Recording.objects.count(), 0)  # nothing written yet
        self.code(self.confirm(self.ben, key, expect=400), 400, "not_uploaded")
        self.storage.put(key)
        r = self.confirm(self.ben, key, expect=201, duration_seconds=600)
        row = Recording.objects.get()
        self.assertEqual((row.uploaded_by, row.storage_key, row.duration_seconds, row.session), (self.ben, key, 600, self.play))
        self.assertEqual(r.data["id"], row.id)
        self.assertNotIn("url", r.data)  # Ben may not watch yet (REC-20)
        self.assertEqual(self.confirm(self.ben, key, expect=200).data["id"], row.id)  # GEN-5
        self.assertEqual(self.confirm(self.coach, key, expect=200).data["id"], row.id)
        self.assertEqual(Recording.objects.count(), 1)

        coach_row = self.upload(self.coach, name="drill.mp4")  # the coach need not be a participant
        self.assertEqual((coach_row.uploaded_by, coach_row.duration_seconds), (self.coach, None))

        # bad name and size: one error per field, nothing issued (REC-11)
        for name in ("clip.avi", "clip", "mp4", "clip.mp4.exe"):
            self.assertIn("file_name", self.form(self.ben, name=name, expect=400).data)
        self.assertEqual(self.form(self.ben, name="CLIP.Mp4", size=2 * GIB).status_code, 200)  # the limit itself
        for size in (0, -5, 2 * GIB + 1, "big"):
            self.assertEqual(list(self.form(self.ben, size=size, expect=400).data), ["size_bytes"])
        self.assertEqual(sorted(self.call("post", f"sessions/{self.play.id}/recordings/form/", self.ben, {}, 400).data),
                         ["file_name", "size_bytes"])

        # bad_key: another session's key, a wrong shape, a wrong extension, someone else's prefix
        other = self.session(self.court2, at(MON, 10), at(MON, 11), self.rana, coach=self.coach)
        foreign = self.form(self.coach, other).data["storage_key"]
        self.storage.put(foreign)
        name = key.split("/")[2]
        for bad in (foreign, f"recordings/{self.play.id}/x.mp4", f"recordings/{self.play.id}/{name.upper()}",
                    f"recordings/{self.play.id}/{name[:-4]}.avi", f"avatars/{self.ben.id}/{name}", "recordings/"):
            self.code(self.confirm(self.ben, bad, expect=400), 400, "bad_key")
        self.assertEqual(self.confirm(self.ben, "", expect=400).data["storage_key"], ["This field may not be blank."])
        fresh = self.form(self.ben).data["storage_key"]
        self.storage.put(fresh)
        self.assertEqual(list(self.confirm(self.ben, fresh, expect=400, duration_seconds=0).data), ["duration_seconds"])
        self.assertEqual(Recording.objects.count(), 2)

    def test_upload_refusals(self):
        """REC-10, REC-13, GEN-3, GEN-4, GEN-5: who may upload and when. Not a checked-in participant 403, a stranger
        404, permission before input; the window is starts_at to ends_at + 30 days on a confirmed session."""
        self.assertEqual(self.form(self.cara, expect=403).data["code"], "forbidden")  # accepted, not checked in
        self.form(self.rana, expect=403)  # the booker is a participant who did not check in
        self.form(self.dan, expect=403)  # declined
        self.form(self.sam, expect=404)  # stranger
        self.form(self.sam, size=0, expect=404)  # GEN-4: permission before input
        self.form(self.cara, size=0, expect=403)
        stray = self.session(self.court2, at(MON, 12), at(MON, 13), self.rana, coach=self.sam)
        self.form(self.coach, stray, expect=404)  # another session's coach is not this session's
        self.call("post", "sessions/99999/recordings/form/", self.ben, {"file_name": "a.mp4", "size_bytes": 5}, 404)
        self.confirm(self.sam, "recordings/1/x.mp4", expect=404)
        self.confirm(self.cara, "recordings/1/x.mp4", expect=403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f"/api/sessions/{self.play.id}/recordings/form/").status_code, 401)

        key = self.form(self.ben).data["storage_key"]  # issued while the window is open
        self.storage.put(key)
        self.clock.return_value = self.play.starts_at - dt.timedelta(seconds=1)
        self.code(self.form(self.ben, expect=400), 400, "upload_closed")
        self.code(self.form(self.coach, expect=400), 400, "upload_closed")
        self.code(self.confirm(self.ben, key, expect=400), 400, "upload_closed")
        self.clock.return_value = self.play.starts_at
        self.form(self.ben, expect=200)
        last = self.play.ends_at + dt.timedelta(days=30)
        self.clock.return_value = last
        self.form(self.ben, expect=200)
        self.confirm(self.ben, key, expect=201)
        self.clock.return_value = last + dt.timedelta(seconds=1)
        self.code(self.form(self.ben, expect=400), 400, "upload_closed")
        later = f"recordings/{self.play.id}/{'0' * 8}-0000-0000-0000-{'0' * 12}.mp4"
        self.storage.put(later)
        self.code(self.confirm(self.ben, later, expect=400), 400, "upload_closed")
        self.confirm(self.ben, key, expect=200)  # a repeat still answers once the window has closed (GEN-5)
        self.assertEqual(Recording.objects.count(), 1)

        self.clock.return_value = at(MON, 10, 30)
        for state in ("cancelled", "requested"):  # REC-10: only a confirmed session
            Session.objects.filter(pk=self.play.pk).update(status=state)
            self.code(self.form(self.ben, expect=400), 400, "upload_closed")
            self.code(self.form(self.coach, expect=400), 400, "upload_closed")

    def test_watch_journey(self):
        """REC-2, REC-20, REC-21, GEN-3: the coach lists recordings with signed links; Ben, checked in without RPE, gets
        404 (also as the uploader) until he logs it; a participant who did not check in, a stranger, an unknown id: 404."""
        mine = self.upload(self.ben, duration_seconds=90)
        coach_row = self.upload(self.coach, name="drill.MP4")
        path = f"sessions/{self.play.id}/recordings/"
        r = self.call("get", path, self.coach, expect=200).data
        self.assertEqual(r["count"], 2)
        first, second = r["results"]
        self.assertEqual(first, {
            "id": mine.id, "session": self.play.id, "uploaded_by": {"id": self.ben.id, "full_name": "Ben", "is_coach": False},
            "duration_seconds": 90, "created_at": first["created_at"], "url": f"http://storage.test/pass/{mine.storage_key}?expires=3600"})
        self.assertEqual((second["id"], second["uploaded_by"]["id"], second["duration_seconds"]), (coach_row.id, self.coach.id, None))
        self.assertTrue(second["url"].endswith(".mp4?expires=3600"))  # REC-2: one hour

        self.call("get", path, self.ben, expect=404)  # checked in, uploaded, no RPE (REC-20)
        self.assertEqual(self.call("put", f"sessions/{self.play.id}/rpe/", self.ben, {"rpe": 7}, 200).data["rpe"], 7)
        r = self.call("get", path, self.ben, expect=200).data
        self.assertEqual([x["id"] for x in r["results"]], [mine.id, coach_row.id])

        SessionParticipant.objects.filter(session=self.play, user=self.cara).update(rpe=5)  # RPE but never checked in
        for user in (self.cara, self.rana, self.dan, self.sam, self.owner):  # the club owner is not a watcher either
            self.call("get", path, user, expect=404)
        self.call("get", "sessions/99999/recordings/", self.coach, expect=404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(f"/api/sessions/{self.play.id}/recordings/").status_code, 401)

    def test_tag_journey(self):
        """REC-25, REC-26, REC-27, REC-28, GEN-3, GEN-4: the coach tags a recording (whole team, named players, a shadow
        player included); bounds; players cannot tag; who sees which tag; creator or coach edits and deletes."""
        rec = self.upload(self.ben, duration_seconds=600)
        self.log_rpe(self.ben)
        tags = f"recordings/{rec.id}/tags/"
        team = self.call("post", tags, self.coach, {"start_second": 10, "label": "Opening"}, 201).data
        self.assertEqual((team["players"], team["end_second"], team["note"], team["created_by"], team["recording"]),
                         ([], None, "", self.coach.id, rec.id))
        named = self.call("post", tags, self.coach, {"start_second": 30, "end_second": 45, "label": "Fast break", "note": "Late pass",
                                                     "players": [self.ben.id, self.kid.id]}, 201).data
        self.assertEqual(sorted(named["players"]), sorted([self.ben.id, self.kid.id]))  # a shadow player is allowed
        self.call("post", tags, self.coach, {"start_second": 590, "end_second": 600, "label": "End", "players": [self.rana.id]}, 201)
        self.assertEqual(RecordingTag.objects.count(), 3)

        # input: players are non-declined participants, bounds, label (REC-25)
        bad = [({"players": [self.dan.id]}, "players"), ({"players": [self.sam.id]}, "players"), ({"players": [99999]}, "players"),
               ({"end_second": 5}, "end_second"), ({"end_second": 10}, "end_second"), ({"end_second": 601}, "end_second"),
               ({"start_second": 601}, "start_second"), ({"start_second": -1}, "start_second"),
               ({"label": ""}, "label"), ({"label": "x" * 256}, "label")]
        for extra, field in bad:
            self.assertIn(field, self.call("post", tags, self.coach, {"start_second": 10, "label": "Try", **extra}, 400).data, extra)
        self.assertEqual(self.call("post", tags, self.coach, {"start_second": 1, "label": "Try", "players": [self.sam.id]}, 400)
                         .data["players"], ["Not found."])  # GEN-18
        self.assertEqual(self.call("post", tags, self.coach, {"label": "No start"}, 400).data["start_second"], ["This field is required."])
        self.assertEqual(RecordingTag.objects.count(), 3)
        unknown = self.upload(self.coach, name="no-duration.mp4")  # duration unknown: no upper bound
        self.call("post", f"recordings/{unknown.id}/tags/", self.coach, {"start_second": 9000, "end_second": 9500, "label": "Late"}, 201)

        # REC-28: players cannot tag; REC-20 first: who cannot watch does not see the recording at all
        self.call("post", tags, self.ben, {"start_second": 1, "label": "Mine"}, 403)
        self.call("post", tags, self.ben, {"start_second": 1, "label": "Mine", "players": [self.ben.id]}, 403)
        self.call("post", tags, self.cara, {"start_second": 1, "label": "Mine"}, 404)  # did not check in
        self.call("post", tags, self.sam, {"start_second": 1, "label": "Mine"}, 404)
        self.call("post", "recordings/99999/tags/", self.coach, {"start_second": 1, "label": "x"}, 404)
        self.assertEqual(RecordingTag.objects.count(), 4)

        # REC-27: the coach sees all; Ben (named, may watch) sees his and the whole-team tag; Cara sees the team tag only
        def labels(user, expect=200):
            r = self.call("get", tags, user, expect=expect)
            return [t["label"] for t in r.data["results"]] if expect == 200 else None

        self.assertEqual(labels(self.coach), ["Opening", "Fast break", "End"])
        self.assertEqual(labels(self.ben), ["Opening", "Fast break"])
        SessionParticipant.objects.filter(session=self.play, user=self.cara).update(checked_in_at=at(MON, 10, 10))
        labels(self.cara, 404)  # checked in, no RPE: no tags either
        SessionParticipant.objects.filter(session=self.play, user=self.cara).update(rpe=4)
        self.assertEqual(labels(self.cara), ["Opening"])
        for user in (self.rana, self.dan, self.sam, self.owner):
            labels(user, 404)
        self.call("get", "recordings/99999/tags/", self.coach, expect=404)

        # REC-26: the coach changes any tag; a visible participant who did not create it gets 403, one who cannot see it 404
        self.call("patch", f"recording-tags/{team['id']}/", self.ben, {"label": "x"}, 403)
        self.call("patch", f"recording-tags/{named['id']}/", self.cara, {"label": "x"}, 404)
        self.call("patch", f"recording-tags/{named['id']}/", self.sam, {"label": "x"}, 404)
        self.call("delete", f"recording-tags/{team['id']}/", self.ben, expect=403)
        r = self.call("patch", f"recording-tags/{named['id']}/", self.coach, {"label": "Fast break!", "players": [self.cara.id]}, 200).data
        self.assertEqual((r["label"], r["players"], r["start_second"], r["end_second"]), ("Fast break!", [self.cara.id], 30, 45))
        self.assertEqual(labels(self.ben), ["Opening"])  # no longer named
        self.assertEqual(labels(self.cara), ["Opening", "Fast break!"])
        # a patch is checked against the stored values
        self.assertIn("end_second", self.call("patch", f"recording-tags/{named['id']}/", self.coach, {"start_second": 50}, 400).data)
        self.assertIn("end_second", self.call("patch", f"recording-tags/{named['id']}/", self.coach, {"end_second": 700}, 400).data)
        self.assertIn("players", self.call("patch", f"recording-tags/{named['id']}/", self.coach, {"players": [self.dan.id]}, 400).data)
        r = self.call("patch", f"recording-tags/{named['id']}/", self.coach, {"end_second": None, "players": []}, 200).data
        self.assertEqual((r["end_second"], r["players"]), (None, []))  # now a whole-team tag
        self.assertEqual(labels(self.ben), ["Opening", "Fast break!"])

        # the creator changes and deletes their own tag
        own = RecordingTag.objects.create(recording=rec, created_by=self.ben, start_second=5, label="Ben's")
        self.call("patch", f"recording-tags/{own.id}/", self.ben, {"note": "check this"}, 200)
        self.call("delete", f"recording-tags/{own.id}/", self.ben, expect=204)
        self.call("delete", f"recording-tags/{own.id}/", self.ben, expect=404)
        self.call("delete", f"recording-tags/{team['id']}/", self.coach, expect=204)
        self.assertEqual(labels(self.coach), ["Fast break!", "End"])

    def test_delete_recording(self):
        """REC-14, GEN-3: the uploader (even without RPE) or the coach deletes: object, row and tags go; a participant who
        may watch but did not upload gets 403; strangers 404; the object is gone from storage."""
        mine, theirs = self.upload(self.ben), self.upload(self.coach, name="drill.mp4")
        self.call("post", f"recordings/{theirs.id}/tags/", self.coach, {"start_second": 1, "label": "x"}, 201)
        self.call("delete", f"recordings/{theirs.id}/", self.ben, expect=404)  # Ben has no RPE: he cannot even see it
        self.log_rpe(self.ben)
        self.call("delete", f"recordings/{theirs.id}/", self.ben, expect=403)
        self.call("delete", f"recordings/{theirs.id}/", self.sam, expect=404)
        self.call("delete", f"recordings/{theirs.id}/", self.cara, expect=404)
        self.call("delete", "recordings/99999/", self.coach, expect=404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.delete(f"/api/recordings/{theirs.id}/").status_code, 401)
        self.assertEqual(Recording.objects.count(), 2)

        self.call("delete", f"recordings/{mine.id}/", self.ben, expect=204)  # the uploader
        self.assertEqual((Recording.objects.filter(pk=mine.pk).exists(), mine.storage_key in self.storage.keys), (False, False))
        self.call("delete", f"recordings/{theirs.id}/", self.coach, expect=204)  # the coach, tags included
        self.assertEqual((Recording.objects.count(), RecordingTag.objects.count(), self.storage.keys), (0, 0, set()))
        self.call("delete", f"recordings/{theirs.id}/", self.coach, expect=404)


class TickTests(BookingBase):
    def tick(self):
        with self.captureOnCommitCallbacks(execute=True):
            call_command("tick", stdout=StringIO())

    def attended(self, user, ended_ago, status="confirmed", **fields):
        """A session that ended `ended_ago` before NOW with `user` checked in (no RPE unless `fields` says so)."""
        end = NOW - ended_ago
        session = self.session(self.court1, end - dt.timedelta(hours=1), end, user, status=status)
        row = session.participants.get(user=user)  # the booker's row exists already
        SessionParticipant.objects.filter(pk=row.pk).update(checked_in_at=end, **fields)
        row.refresh_from_db()
        return session, row

    def test_rpe_reminder_journey(self):
        """NOTE-30, NOTE-31, NOTE-9, NOTE-14, NOTE-20: only checked-in participants without an RPE and without a reminder, of a
        confirmed session that ended within 7 days, get one `rpe_reminder` carrying the session id; never twice, running again
        changes nothing, a gap in the scheduler is caught up, and nothing older than 7 days is."""
        rana, ben, cy, dee, eve, fay, gus = (self.user(n) for n in ("rana", "ben", "cy", "dee", "eve", "fay", "gus"))
        hour, day = dt.timedelta(hours=1), dt.timedelta(days=1)
        due, row = self.attended(rana, hour)
        SessionParticipant.objects.create(session=due, user=ben, status="accepted")  # accepted, never checked in
        SessionParticipant.objects.create(session=due, user=cy, status="accepted", checked_in_at=NOW - hour, rpe=6)  # has an RPE
        SessionParticipant.objects.create(session=due, user=dee, status="accepted", checked_in_at=NOW - hour,
                                          rpe_reminded_at=NOW - day)  # already reminded
        self.attended(eve, hour, status="cancelled")  # not confirmed
        self.attended(fay, 7 * day + dt.timedelta(seconds=1))  # ended just over 7 days ago
        edge, edge_row = self.attended(gus, 7 * day)  # exactly 7 days: still in
        ahead = self.session(self.court1, NOW + hour, NOW + 2 * hour, rana)  # ends later
        ahead_row = ahead.participants.get(user=rana)
        SessionParticipant.objects.filter(pk=ahead_row.pk).update(checked_in_at=NOW)

        self.tick()
        reminders = lambda: [p for p in accounts.outbox if p["data"]["type"] == "rpe_reminder"]  # noqa: E731 (not payment_due)
        self.assertEqual([(p["user_id"], p["data"]) for p in reminders()], [
            (rana.id, {"type": "rpe_reminder", "id": str(due.id)}), (gus.id, {"type": "rpe_reminder", "id": str(edge.id)})])
        self.assertEqual(len(self.pushed(rana, "rpe_reminder")), 1)
        for r in (row, edge_row):
            r.refresh_from_db()
            self.assertEqual(r.rpe_reminded_at, NOW)  # NOTE-9
        self.assertEqual(SessionParticipant.objects.filter(rpe_reminded_at__isnull=False).count(), 3)  # those two and dee's

        accounts.outbox.clear()  # safe to run twice in a row
        self.tick()
        self.assertEqual(accounts.outbox, [])  # nothing billed twice either

        # the scheduler was down while the later session ended: it is caught up on the next tick, once
        self.clock.return_value = NOW + 3 * hour
        self.tick()
        self.tick()
        self.assertEqual([(p["user_id"], p["data"]["id"]) for p in reminders()], [(rana.id, str(ahead.id))])
        ahead_row.refresh_from_db()
        self.assertEqual(ahead_row.rpe_reminded_at, NOW + 3 * hour)


class SeedDemoTests(APITestCase):
    def test_every_screen_has_varied_data_and_a_changed_script_starts_over(self):
        """SEED-4: each thing the app shows exists and varies, court sessions sit on free offered slots, nobody is
        in two places at once; a second run changes nothing; a changed script wipes everything but real accounts."""
        from bookings.management.commands import seed_demo
        from bookings.services import offered_slots

        with mock.patch.dict("os.environ", {"DEMO_PASSWORD": PASSWORD}):
            call_command("seed_demo", stdout=StringIO())
        sessions = Session.objects.all()
        now = dt.datetime.now(UTC)
        for found in [
            User.objects.filter(is_coach=True, coach_rate__isnull=False), User.objects.filter(is_coach=True, coach_rate=None),
            Court.objects.filter(is_active=False), CourtRate.objects.all(), CourtBlockout.objects.exclude(repeat="none"),
            Equipment.objects.filter(rental_price=None), Equipment.objects.filter(rental_price__isnull=False),
            Equipment.objects.filter(court__isnull=False), Discount.objects.filter(min_bookings=None),
            Discount.objects.filter(user__isnull=False), Discount.objects.filter(amount_off__isnull=False),
            ClubMember.objects.filter(role="staff", status="active"), ClubMember.objects.filter(role="coach", status="active"),
            sessions.filter(status="requested"), sessions.filter(status="cancelled"), sessions.filter(discount_amount__gt=0),
            sessions.filter(starts_at__gt=now, status="confirmed", kind="play"), sessions.filter(starts_at__lt=now),
            sessions.filter(kind="training", court=None, status="confirmed"), sessions.filter(kind="training", group__isnull=False),
            SessionRental.objects.filter(status="requested"), SessionRental.objects.filter(status="declined"),
            SessionParticipant.objects.filter(status="invited"),
        ]:
            self.assertTrue(found.exists(), found.query)

        coaches = User.objects.filter(is_coach=True)
        bios = [b for b in coaches.values_list("coach_bio", flat=True) if b]
        self.assertEqual(len(bios), len(set(bios)))  # no two coaches share a bio
        self.assertGreater(len(set(coaches.values_list("coach_rate", "coach_currency"))), 10)
        self.assertGreater(len(set(CourtRate.objects.values_list("price", flat=True))), 60)
        self.assertGreater(len(set(CourtRate.objects.values_list("start_time", "end_time"))), 8)
        training = sessions.filter(kind="training", court=None).exclude(status="requested")
        self.assertGreater(len({s.starts_at.astimezone(zoneinfo.ZoneInfo(s.coach.timezone)).hour for s in training}), 8)
        sports_per_coach = Counter(c for c, _ in set(training.values_list("coach", "sport")))
        self.assertGreater(max(sports_per_coach.values()), 1)  # some coaches teach several sports

        for court in Court.objects.filter(sessions__isnull=False).distinct().select_related("club"):
            booked = list(court.sessions.exclude(status="cancelled").order_by("starts_at"))
            for a, b in zip(booked, booked[1:]):
                self.assertLessEqual(a.ends_at, b.starts_at)
            days = {s.starts_at.astimezone(zoneinfo.ZoneInfo(court.club.timezone)).date() for s in booked}
            slots = offered_slots(court, sorted(days))
            starts, ends = {s.starts_at for s in slots}, {s.ends_at for s in slots}
            for s in booked:
                self.assertIn(s.starts_at, starts)
                self.assertIn(s.ends_at, ends)
        times = {}
        for row in SessionParticipant.objects.exclude(session__status="cancelled").select_related("session"):
            times.setdefault(row.user_id, []).append((row.session.starts_at, row.session.ends_at))
        for spans in times.values():
            spans.sort()
            for (_, end), (start, _) in zip(spans, spans[1:]):
                self.assertLessEqual(end, start)

        login = self.client.post("/api/auth/login/", {"email": "player@pass-demo.example", "password": PASSWORD})
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {login.data['token']}")
        self.assertGreater(self.client.get("/api/me/sessions/").data["count"], 0)

        before = (User.objects.count(), Session.objects.count(), Equipment.objects.count())
        call_command("seed_demo", stdout=StringIO())
        self.assertEqual((User.objects.count(), Session.objects.count(), Equipment.objects.count()), before)
        self.assertFalse(User.objects.get(email="player@pass-demo.example").has_usable_password())  # no DEMO_PASSWORD

        real = User.objects.create_user("real@example.com", PASSWORD)
        Club.objects.create(owner=real, name="Mine", timezone="Asia/Beirut", currency="USD")
        with mock.patch.object(seed_demo, "VERSION", "changed"):
            call_command("seed_demo", stdout=StringIO())
        self.assertTrue(User.objects.filter(pk=real.pk).exists())
        self.assertFalse(Club.objects.filter(name="Mine").exists())
        self.assertFalse(User.objects.filter(email__startswith="seed-").exclude(email="seed-changed@pass-demo.example").exists())
        self.assertEqual(Club.objects.filter(owner__email="owner@pass-demo.example").count(), 2)

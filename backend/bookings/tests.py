import datetime as dt
from decimal import Decimal
from unittest import mock

from rest_framework.test import APITestCase

from accounts import services as accounts
from accounts.models import Connection, Device, User
from billing.models import Payment
from chat import services as chat_services
from chat.models import Chat, Message
from teams.models import Group, GroupMember
from venues.models import (
    Club, ClubCurrency, ClubMember, Court, CourtBlockout, CourtRate, Discount, Equipment, PriceOverride, Sport,
)

from .models import Session, SessionParticipant, SessionRental

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
        self.basketball = Sport.objects.create(name="Basketball")
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
        group = Group.objects.create(type="play_group", name="Not mine", owner=bob)
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
        team = Group.objects.create(type="team", name="Wolves", owner=coach, coach=coach)
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

        # frozen once the session has payments; a repeat of the current status is still 200
        Payment.objects.create(session=c_session, payer=cy, club=self.club, amount=Decimal("15"), currency="USD", platform_fee=0)
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

        # payments: refused; ended: refused; a requested session is not cancelled here (BOOK-1 gives that to the coach)
        paid = self.session(self.court1, at(MON, 14), at(MON, 15), ann)
        Payment.objects.create(session=paid, payer=ann, club=self.club, amount=Decimal("50"), currency="USD", platform_fee=0)
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

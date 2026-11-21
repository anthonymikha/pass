import datetime as dt
from decimal import Decimal

from accounts.models import Connection, User
from bookings import tests as base
from bookings.models import Session, SessionParticipant

from .models import CommissionRate, Payment

UTC = dt.timezone.utc
at, z, MON = base.at, base.z, base.MON


class PaymentTests(base.PaymentBase):
    def test_mark_paid_journey(self):
        """PAY-20, PAY-21, PAY-22, PAY-23, COM-10, ACC-6, GEN-3, GEN-5: who sees a payment (404 for everyone else), the
        payee side marks it paid and back to due, the payer may not, settled payments cannot go back to due."""
        rana, ben, sam, rival, sami, pat = (self.user(n) for n in ("rana", "ben", "sam", "rival", "sami", "pat"))
        sami.is_coach = True
        sami.save()
        self.staff(sam)
        base.Club.objects.create(owner=rival, name="Elsewhere", timezone="Asia/Beirut", currency="USD")
        Connection.objects.create(user=sami, other_user=ben, type="coaching", status="accepted")
        court = self.book(rana, at(MON, 10), at(MON, 11)).data["id"]
        training = self.train(sami, at(MON, 12), at(MON, 13), fee="40", player=ben.id)  # BOOK-31: the player pays the coach
        self.clock.return_value = at(MON, 9, 45)
        self.check_in(rana, Session.objects.get(pk=court))
        self.clock.return_value = at(MON, 11, 45)
        self.check_in(sami, training)
        self.clock.return_value = at(base.TUE, 13)
        self.tick()  # PAY-10
        club_row, coach_row = Payment.objects.get(club=self.club), Payment.objects.get(coach=sami)
        self.assertEqual((club_row.payer, club_row.amount, club_row.platform_fee), (rana, Decimal("50"), Decimal("5")))
        self.assertEqual((coach_row.payer, coach_row.amount, coach_row.platform_fee), (ben, Decimal("40"), Decimal("4")))

        # PAY-23: the payer sees theirs, the payee side the rows it is paid; the others get nothing, and a 404 by id
        def ids(user):
            return [p["id"] for p in self.call("get", "payments/", user, expect=200).data["results"]]
        self.assertEqual((ids(rana), ids(ben), ids(sam), ids(self.owner), ids(sami)),
                         ([club_row.id], [coach_row.id], [club_row.id], [club_row.id], [coach_row.id]))
        self.assertEqual((ids(rival), ids(pat)), ([], []))
        r = self.call("get", f"payments/{coach_row.id}/", ben, expect=200).data
        self.assertEqual((r["coach"]["id"], r["club"], r["payer"]["id"], r["amount"], r["method"]), (sami.id, None, ben.id, "40.000", ""))
        for outsider, row in ((rival, club_row), (pat, club_row), (rana, coach_row), (self.owner, coach_row), (sam, coach_row)):
            self.call("get", f"payments/{row.id}/", outsider, expect=404)
        self.call("get", "payments/99999/", rana, expect=404)

        # PAY-20, PAY-25: not the payer (403, they see the row), not another club's staff or a stranger (404)
        for who, row, status in ((rana, club_row, 403), (ben, coach_row, 403), (rival, club_row, 404), (pat, club_row, 404),
                                 (sam, coach_row, 404), (self.owner, coach_row, 404)):
            self.call("post", f"payments/{row.id}/mark-paid/", who, expect=status)
            self.call("post", f"payments/{row.id}/mark-due/", who, expect=status)
            self.call("post", f"payments/{row.id}/waive/", who, expect=status)
        self.call("post", "payments/99999/mark-paid/", sam, expect=404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f"/api/payments/{club_row.id}/mark-paid/").status_code, 401)
        club_row.refresh_from_db()
        self.assertEqual((club_row.method, club_row.paid_at), ("", None))

        # PAY-20: the club side (staff, owner) and the coach mark paid; a repeat changes nothing (GEN-5)
        self.clock.return_value = at(MON, 14)
        r = self.call("post", f"payments/{club_row.id}/mark-paid/", sam, expect=200)
        self.assertEqual((r.data["method"], r.data["paid_at"], r.data["waived_at"]), ("offline", z(at(MON, 14)), None))
        self.clock.return_value = at(MON, 15)
        self.assertEqual(self.call("post", f"payments/{club_row.id}/mark-paid/", self.owner, expect=200).data["paid_at"], z(at(MON, 14)))
        self.call("post", f"payments/{coach_row.id}/mark-paid/", sami, expect=200)
        # PAY-21: back to due (the coach's, and the club's by the owner); a repeat on a due row is 200
        r = self.call("post", f"payments/{coach_row.id}/mark-due/", sami, expect=200)
        self.assertEqual((r.data["method"], r.data["paid_at"]), ("", None))
        self.call("post", f"payments/{coach_row.id}/mark-due/", sami, expect=200)
        self.call("post", f"payments/{club_row.id}/mark-due/", self.owner, expect=200)
        self.call("post", f"payments/{club_row.id}/mark-paid/", sam, expect=200)
        club_row.refresh_from_db()
        self.assertEqual((club_row.method, club_row.paid_at), ("offline", at(MON, 15)))

        # COM-10, PAY-21: once the platform settled the cut, the row cannot go back to due; paid stays a 200
        Payment.objects.filter(pk=club_row.pk).update(settled_at=at(MON, 20))
        self.code(self.call("post", f"payments/{club_row.id}/mark-due/", sam), 400, "already_settled")
        self.call("post", f"payments/{club_row.id}/mark-paid/", sam, expect=200)
        club_row.refresh_from_db()
        self.assertEqual((club_row.method, club_row.paid_at, club_row.settled_at), ("offline", at(MON, 15), at(MON, 20)))
        # PAY-22: nothing here edits or deletes a payment
        self.assertEqual(self.call("patch", f"payments/{club_row.id}/", sam, {"amount": "1"}).status_code, 405)
        self.assertEqual(self.call("delete", f"payments/{club_row.id}/", sam).status_code, 405)

    def test_waive_journey(self):
        """PAY-25, PAY-20, PAY-21, PAY-12, RPT-2, RPT-3, RPT-7, COM-11, GEN-5: the coach waives the fee of a payer who
        did not come; a waived payment is not due, not revenue; it cannot be received until moved back to due; a
        received one cannot be waived."""
        sami, ben, rana = self.user("sami", is_coach=True), self.user("ben"), self.user("rana")
        Connection.objects.create(user=sami, other_user=ben, type="coaching", status="accepted")
        training = self.train(sami, at(MON, 12), at(MON, 13), fee="40", player=ben.id)
        court = Session.objects.get(pk=self.book(rana, at(MON, 10), at(MON, 11)).data["id"])
        self.clock.return_value = at(MON, 12)
        self.check_in(sami, training)  # Ben never comes: the fee paid in full is still owed (PAY-12)
        self.clock.return_value = at(MON, 10)
        self.check_in(rana, court)
        self.clock.return_value = at(base.TUE, 13)
        self.tick()
        row, club_row = Payment.objects.get(coach=sami), Payment.objects.get(club=self.club)
        self.assertEqual((row.payer, row.amount), (ben, Decimal("40")))

        # PAY-25: the coach waives it; a repeat is 200 and keeps the first time (GEN-5)
        self.clock.return_value = at(base.TUE, 14)
        r = self.call("post", f"payments/{row.id}/waive/", sami, expect=200)
        self.assertEqual((r.data["waived_at"], r.data["paid_at"]), (z(at(base.TUE, 14)), None))
        self.clock.return_value = at(base.TUE, 15)
        self.assertEqual(self.call("post", f"payments/{row.id}/waive/", sami, expect=200).data["waived_at"], z(at(base.TUE, 14)))
        # RPT-7, RPT-2: not in the coach's due list, not revenue
        r = self.call("get", "me/earnings/?from=2027-01-01&to=2027-01-31", sami, expect=200).data
        self.assertEqual((r["currencies"], r["due"]), ([], {"payments": [], "totals": []}))
        # PAY-20: a waived payment is not received until it is back to due (PAY-21 empties waived_at)
        self.code(self.call("post", f"payments/{row.id}/mark-paid/", sami), 400, "already_waived")
        r = self.call("post", f"payments/{row.id}/mark-due/", sami, expect=200)
        self.assertEqual((r.data["waived_at"], r.data["paid_at"]), (None, None))
        self.call("post", f"payments/{row.id}/mark-paid/", sami, expect=200)
        # PAY-25: a received payment cannot be waived; back to due first, then it can
        self.code(self.call("post", f"payments/{row.id}/waive/", sami), 400, "already_paid")
        self.call("post", f"payments/{row.id}/mark-due/", sami, expect=200)
        self.call("post", f"payments/{row.id}/waive/", sami, expect=200)
        # the club side waives its own payments too; the due list drops it, revenue never had it (RPT-2, RPT-3)
        self.call("post", f"payments/{club_row.id}/waive/", self.owner, expect=200)
        self.assertEqual(self.call("get", f"clubs/{self.club.id}/dues/", self.owner, expect=200).data, {"payments": [], "totals": []})
        r = self.call("get", f"clubs/{self.club.id}/revenue/?from=2027-01-01&to=2027-01-31", self.owner, expect=200).data
        self.assertEqual(r, {"currencies": []})
        # the payer sees the waived row (PAY-23)
        self.assertEqual(self.call("get", f"payments/{row.id}/", ben, expect=200).data["waived_at"], z(at(base.TUE, 15)))

    def test_admin_settles_payments_journey(self):
        """ACC-7, COM-10, PAY-22: a platform admin sets `settled_at` in the Django admin, only on a paid payment; no
        payment can be added or deleted there."""
        rana = self.user("rana")
        session = self.session(self.court1, at(MON, 10), at(MON, 11), rana)
        due = Payment.objects.create(session=session, payer=rana, club=self.club, amount=50, currency="USD", platform_fee=5)
        paid = Payment.objects.create(session=session, payer=rana, club=self.club, amount=50, currency="USD", platform_fee=5,
                                      method="offline", paid_at=at(MON, 12))
        admin = User.objects.create_superuser("admin@example.com", base.PASSWORD, full_name="Admin")
        self.client.force_authenticate(None)
        self.client.force_login(admin)
        form = {"settled_at_0": "2027-02-01", "settled_at_1": "10:00:00"}
        self.assertEqual(self.client.get(f"/admin/billing/payment/{due.id}/change/").status_code, 200)
        # COM-10: a payment that is still due cannot be settled
        r = self.client.post(f"/admin/billing/payment/{due.id}/change/", form)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "still due cannot be settled")
        due.refresh_from_db()
        self.assertIsNone(due.settled_at)
        # a paid one can; nothing else on it changes
        self.assertEqual(self.client.post(f"/admin/billing/payment/{paid.id}/change/", form).status_code, 302)
        paid.refresh_from_db()
        self.assertEqual((paid.settled_at, paid.amount, paid.paid_at), (dt.datetime(2027, 2, 1, 10, tzinfo=UTC), Decimal("50"), at(MON, 12)))
        # PAY-22: no add, no delete
        self.assertEqual(self.client.get("/admin/billing/payment/add/").status_code, 403)
        self.assertEqual(self.client.post(f"/admin/billing/payment/{paid.id}/delete/", {"post": "yes"}).status_code, 403)
        self.assertEqual(Payment.objects.count(), 2)


class CommissionTests(base.PaymentBase):
    def setUp(self):
        super().setUp()
        self.sami, self.cora = self.user("sami", is_coach=True), self.user("cora", is_coach=True)
        self.kid = self.user("kid")

    def coach_fee(self, coach, instant, club=False):
        """Bill at `instant` a session with a 100.00 USD payment to `coach` (or the court of Hoops), which ended a day
        earlier with the coach checked in: the platform fee on it is the percent (PAY-14: the billing date)."""
        session = Session.objects.create(
            sport=self.basketball, booked_by=coach, coach=coach, kind="training", status="confirmed", currency="USD",
            starts_at=instant - dt.timedelta(hours=25), ends_at=instant - dt.timedelta(hours=24),
            price=Decimal(100) if club else 0, coach_fee=0 if club else Decimal(100), coach_fee_payer=self.kid,
            court=self.court1 if club else None)
        SessionParticipant.objects.create(session=session, user=coach, status="accepted", checked_in_at=session.starts_at)
        self.clock.return_value = instant
        self.tick()
        return session.payments.get(**({"club": self.club} if club else {"coach": coach})).platform_fee

    def test_commission_lookup_journey(self):
        """COM-1, COM-2, COM-4, PAY-14: the commission example (default 10%, Sami 7% from 2027-03-01, another coach
        10%), no rows is 0%, own rows win over a newer default, the newest effective_from wins, a club override."""
        sami, cora = self.sami, self.cora
        day = lambda m, d, h=12: dt.datetime(2027, m, d, h, tzinfo=UTC)  # noqa: E731
        # the example: the date is the UTC date of billing (PAY-14)
        CommissionRate.objects.create(applies_to="coach", coach=sami, percent=Decimal("7"), effective_from=dt.date(2027, 3, 1))
        early = self.coach_fee(sami, day(2, 20))
        self.assertEqual(early, Decimal("10.00"))  # not yet in effect
        self.assertEqual(self.coach_fee(sami, dt.datetime(2027, 2, 28, 23, 59, 59, tzinfo=UTC)), Decimal("10.00"))
        self.assertEqual(self.coach_fee(sami, dt.datetime(2027, 3, 1, 0, 0, tzinfo=UTC)), Decimal("7.00"))
        self.assertEqual(self.coach_fee(sami, day(4, 1)), Decimal("7.00"))
        self.assertEqual(self.coach_fee(cora, day(4, 1)), Decimal("10.00"))  # another coach: the default
        # COM-2: the fee already stored is never recomputed
        self.assertEqual(Payment.objects.filter(coach=sami).order_by("id").first().platform_fee, Decimal("10.00"))
        # COM-1 step 2: a newer default does not beat the payee's own (older) row; step 3: newest own row wins
        CommissionRate.objects.create(applies_to="coach", percent=Decimal("12"), effective_from=dt.date(2027, 4, 1))
        self.assertEqual(self.coach_fee(sami, day(4, 10)), Decimal("7.00"))
        self.assertEqual(self.coach_fee(cora, day(4, 10)), Decimal("12.00"))  # the newest default
        CommissionRate.objects.create(applies_to="coach", coach=sami, percent=Decimal("5"), effective_from=dt.date(2027, 5, 1))
        self.assertEqual(self.coach_fee(sami, day(4, 20)), Decimal("7.00"))
        self.assertEqual(self.coach_fee(sami, day(5, 2)), Decimal("5.00"))
        # clubs have their own rows: a negotiated 8% for Hoops from 2027-06-01; coach rows do not apply to a club
        CommissionRate.objects.create(applies_to="club", club=self.club, percent=Decimal("8"), effective_from=dt.date(2027, 6, 1))
        self.assertEqual(self.coach_fee(sami, day(5, 20), club=True), Decimal("10.00"))
        self.assertEqual(self.coach_fee(sami, day(6, 2), club=True), Decimal("8.00"))
        # COM-1 step 4: no row at all is 0%
        CommissionRate.objects.all().delete()
        self.assertEqual(self.coach_fee(sami, day(7, 1)), Decimal("0.00"))
        self.assertEqual(Payment.objects.filter(coach=sami).order_by("id").last().amount, Decimal("100"))

    def test_commission_tiers_journey(self):
        """COM-1, COM-3: a tier (min_count above 0) is chosen by the count N: the coach's players, or the club's
        non-cancelled sessions started in the last 30 days; while all rows have min_count 0 nothing is counted."""
        sami, now = self.sami, dt.datetime(2027, 6, 1, 12, tzinfo=UTC)
        CommissionRate.objects.create(applies_to="coach", percent=Decimal("8"), min_count=2, effective_from=dt.date(2026, 1, 1))
        CommissionRate.objects.create(applies_to="club", percent=Decimal("5"), min_count=3, effective_from=dt.date(2026, 1, 1))
        # coach: no players is the base row; the count is of distinct players (a user twice still counts once)
        self.assertEqual(self.coach_fee(sami, now), Decimal("10.00"))
        Connection.objects.create(user=sami, other_user=self.kid, type="coaching", status="accepted")
        self.assertEqual(self.coach_fee(sami, now + dt.timedelta(hours=2)), Decimal("10.00"))  # N = 1
        self.make_team(sami, [self.kid, self.user("zed")])
        self.assertEqual(self.coach_fee(sami, now + dt.timedelta(hours=4)), Decimal("8.00"))  # kid and zed: N = 2
        # club: sessions on its courts started in the 30 days before now, not cancelled
        rana = self.user("rana")
        for days_ago, status in ((1, "confirmed"), (31, "confirmed"), (2, "cancelled")):
            start = now - dt.timedelta(days=days_ago)
            self.session(self.court1, start, start + dt.timedelta(hours=1), rana, status=status)
        # N = 2: the session 1 day ago and the billed session itself (it started 25 hours ago)
        self.assertEqual(self.coach_fee(sami, now + dt.timedelta(hours=6), club=True), Decimal("10.00"))
        start = now - dt.timedelta(days=3)
        self.session(self.court2, start, start + dt.timedelta(hours=1), rana)
        self.assertEqual(self.coach_fee(sami, now + dt.timedelta(hours=8), club=True), Decimal("5.00"))  # N = 4: each billed session counts too


class ReportTests(base.PaymentBase):
    def test_money_reports_journey(self):
        """RPT-2, RPT-3, RPT-7, COM-11, ACC-6, GEN-8, GEN-13: due list with totals per currency, revenue per currency
        by paid date in the club's timezone, owed to the platform over all dates, the coach's earnings in their own
        timezone, staff may not read revenue."""
        rana, sam, sami, bob = (self.user(n) for n in ("rana", "sam", "sami", "bob"))
        sami.is_coach = True
        sami.timezone = "Asia/Beirut"
        sami.save()
        self.staff(sam)
        s = self.session(self.court1, at(MON, 10), at(MON, 11), rana)

        def club(amount, fee, currency="USD", paid=None, settled=None, who=rana):
            return Payment.objects.create(
                session=s, payer=who, club=self.club, amount=Decimal(amount), currency=currency, platform_fee=Decimal(fee),
                method="offline" if paid else "", paid_at=paid, settled_at=settled)

        def coach(amount, fee, paid=None, currency="USD"):
            return Payment.objects.create(
                session=s, payer=rana, coach=sami, amount=Decimal(amount), currency=currency, platform_fee=Decimal(fee),
                method="offline" if paid else "", paid_at=paid)

        utc = lambda *a: dt.datetime(*a, tzinfo=UTC)  # noqa: E731
        club("100", "10", paid=utc(2027, 1, 11, 10))
        club("50", "5", paid=utc(2027, 1, 20, 10), settled=utc(2027, 1, 25))
        club("113.90", "11.39", "EUR", paid=utc(2027, 1, 12, 10))
        club("30", "3", paid=utc(2026, 12, 20))  # before the period, never settled
        club("10000", "1000", "LBP", paid=utc(2026, 12, 21))  # a currency with nothing in the period
        club("1", "0.10", paid=utc(2027, 1, 31, 21, 30))  # 23:30 in Beirut: January
        club("2", "0.20", paid=utc(2027, 1, 31, 22, 30))  # 00:30 in Beirut: February
        club("70", "7")
        club("20", "2", who=sam)
        club("20", "2", "EUR")
        Payment.objects.create(session=s, payer=rana, club=self.club, amount=5, currency="USD", platform_fee=Decimal("0.5"),
                               waived_at=utc(2027, 1, 12))  # waived: neither due nor revenue (PAY-25)
        Payment.objects.create(session=s, payer=rana, club=self.club, amount=1, currency="USD", platform_fee=0,
                               method="offline", paid_at=utc(2027, 1, 11, 11))  # a free-fee row: gross only
        other = base.Club.objects.create(owner=bob, name="Elsewhere", timezone="Asia/Beirut", currency="USD")
        Payment.objects.create(session=s, payer=rana, club=other, amount=999, currency="USD", platform_fee=99,
                               method="offline", paid_at=utc(2027, 1, 11, 11))  # another club's money never shows
        path = f"clubs/{self.club.id}/"

        # RPT-3: January in Beirut. USD gross 100 + 50 + 1 + 1, fees 10 + 5 + 0.10; owed = unsettled paid fees at any date
        r = self.call("get", path + "revenue/?from=2027-01-01&to=2027-01-31", self.owner, expect=200).data["currencies"]
        self.assertEqual(r, [
            {"currency": "EUR", "gross": "113.900", "fees": "11.390", "net": "102.510", "owed_to_platform": "11.390"},
            {"currency": "LBP", "gross": "0.000", "fees": "0.000", "net": "0.000", "owed_to_platform": "1000.000"},
            {"currency": "USD", "gross": "152.000", "fees": "15.100", "net": "136.900", "owed_to_platform": "13.300"}])
        r = self.call("get", path + "revenue/?from=2027-02-01&to=2027-02-28", self.owner, expect=200).data["currencies"]
        self.assertEqual([(x["currency"], x["gross"], x["fees"], x["net"], x["owed_to_platform"]) for x in r], [
            ("EUR", "0.000", "0.000", "0.000", "11.390"), ("LBP", "0.000", "0.000", "0.000", "1000.000"),
            ("USD", "2.000", "0.200", "1.800", "13.300")])
        # ACC-6: the owner only; the period is limited
        for reader in (sam, rana, bob):
            self.call("get", path + "revenue/?from=2027-01-01&to=2027-01-31", reader, expect=403)
        self.code(self.call("get", path + "revenue/?from=2027-01-01&to=2028-01-02", self.owner), 400, "bad_range")
        self.assertIn("from", self.call("get", path + "revenue/?to=2027-01-02", self.owner, expect=400).data)
        self.call("get", "clubs/99999/revenue/?from=2027-01-01&to=2027-01-31", self.owner, expect=404)

        # RPT-2: only unpaid rows of this club, totals per currency, staff may read it
        due = self.call("get", path + "dues/", sam, expect=200).data
        self.assertEqual([(d["payer"]["full_name"], d["amount"], d["currency"]) for d in due["payments"]],
                         [("Rana", "70.000", "USD"), ("Sam", "20.000", "USD"), ("Rana", "20.000", "EUR")])
        self.assertEqual(due["totals"], [{"currency": "EUR", "total": "20.000"}, {"currency": "USD", "total": "90.000"}])
        self.call("get", path + "dues/", rana, expect=403)
        self.call("get", path + "dues/", bob, expect=403)

        # RPT-7: the coach's own revenue in their timezone (Beirut), their due list; not the club's rows
        coach("40", "4", paid=utc(2027, 1, 11, 10))
        coach("60", "6", paid=utc(2027, 1, 31, 22, 30))  # February in Beirut
        coach("25", "2.50")
        coach("15", "1.50", currency="EUR")
        r = self.call("get", "me/earnings/?from=2027-01-01&to=2027-01-31", sami, expect=200).data
        self.assertEqual(r["currencies"], [{"currency": "USD", "gross": "40.000", "fees": "4.000", "net": "36.000", "owed_to_platform": "10.000"}])
        self.assertEqual(r["due"]["totals"], [{"currency": "EUR", "total": "15.000"}, {"currency": "USD", "total": "25.000"}])
        self.assertEqual([(d["amount"], d["payer"]["full_name"]) for d in r["due"]["payments"]], [("25.000", "Rana"), ("15.000", "Rana")])
        sami.timezone = "UTC"
        sami.save()
        r = self.call("get", "me/earnings/?from=2027-01-01&to=2027-01-31", sami, expect=200).data
        self.assertEqual(r["currencies"][0]["gross"], "100.000")  # now the 31st 22:30Z is January
        self.call("get", "me/earnings/?from=2027-01-01&to=2027-01-31", rana, expect=403)  # not a coach
        self.code(self.call("get", "me/earnings/?from=2027-01-02&to=2027-01-01", sami), 400, "bad_range")

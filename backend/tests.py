from datetime import date, datetime, time, timezone
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Connection, User, UserBlockout
from wellness.models import SleepLog
from billing.models import Payment
from bookings.models import Session, SessionParticipant
from venues.models import Club, ClubMember, Court, CourtBlockout, CourtRate, Equipment, PriceOverride, Sport

T0 = datetime(2026, 1, 5, 10, tzinfo=timezone.utc)
T1 = datetime(2026, 1, 5, 11, tzinfo=timezone.utc)


class SchemaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.coach = User.objects.create_user("coach@example.com", "pw-123-long", is_coach=True)
        cls.club = Club.objects.create(owner=cls.coach, name="Club", timezone="UTC", currency="KWD")
        cls.court = Court.objects.create(club=cls.club, name="Court 1", slot_minutes=60)
        cls.rate = CourtRate.objects.create(
            court=cls.court, weekday=0, start_time=time(17), end_time=time(0), price=Decimal("10")
        )
        cls.equipment = Equipment.objects.create(club=cls.club, name="Racket", quantity=4)
        cls.session = Session.objects.create(
            court=cls.court, sport=Sport.objects.create(name="Padel"), booked_by=cls.coach,
            kind="play", starts_at=T0, ends_at=T1, currency="KWD", price=Decimal("10"),
        )

    def assertRejected(self, model, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            model.objects.create(**fields)

    def test_users(self):
        self.assertEqual(self.coach.email, "coach@example.com")
        self.assertTrue(self.coach.check_password("pw-123-long"))
        shadow = User.objects.create_user(full_name="Kid", managed_by=self.coach)
        User.objects.create_user(full_name="Kid 2", managed_by=self.coach)  # second NULL email is fine
        self.assertIsNone(shadow.email)
        self.assertFalse(shadow.has_usable_password())

    def test_blockouts_repeat(self):
        monthly = CourtBlockout.objects.create(
            court=self.court, starts_on=date(2026, 1, 31), start_time=time(9), end_time=time(10),
            repeat="monthly", repeat_until=date(2026, 6, 30),
        )
        self.assertTrue(monthly.occurs_on(date(2026, 3, 31)))
        self.assertFalse(monthly.occurs_on(date(2026, 2, 28)))  # no 31st: skipped
        self.assertFalse(monthly.occurs_on(date(2026, 7, 31)))  # past repeat_until
        weekly = UserBlockout.objects.create(
            user=self.coach, starts_on=date(2026, 1, 6), start_time=time(9), end_time=time(10), repeat="weekly"
        )
        self.assertTrue(weekly.occurs_on(date(2026, 1, 13)))
        self.assertFalse(weekly.occurs_on(date(2026, 1, 14)))
        self.assertFalse(weekly.occurs_on(date(2025, 12, 30)))  # before the first occurrence
        once = UserBlockout(starts_on=date(2026, 1, 6), repeat="none")
        self.assertEqual([once.occurs_on(date(2026, 1, d)) for d in (6, 13)], [True, False])
        self.assertRejected(
            UserBlockout, user=self.coach, starts_on=date(2026, 1, 6), start_time=time(9), end_time=time(10),
            repeat="daily", repeat_until=date(2026, 1, 5),
        )

    def test_club_member_roles(self):
        ClubMember.objects.create(club=self.club, user=self.coach, role="coach")
        ClubMember.objects.create(club=self.club, user=self.coach, role="player", expires_on=date(2026, 12, 31))
        self.assertRejected(ClubMember, club=self.club, user=self.coach, role="player")

    def test_sleep_sync_is_idempotent(self):
        night = dict(user=self.coach, sleep_start=T0, sleep_end=T1)
        SleepLog.objects.create(source="apple_health", external_id="abc", **night)
        self.assertRejected(SleepLog, source="apple_health", external_id="abc", **night)
        SleepLog.objects.create(source="manual", **night)
        SleepLog.objects.create(source="manual", **night)  # manual rows have no external id

    def test_price_overrides_exactly_one(self):
        self.assertRejected(PriceOverride, court_rate=self.rate, equipment=self.equipment, currency="USD", price=1)
        self.assertRejected(PriceOverride, currency="USD", price=1)
        PriceOverride.objects.create(court_rate=self.rate, currency="USD", price=1)
        self.assertRejected(PriceOverride, court_rate=self.rate, currency="USD", price=2)  # conditional unique

    def test_payments_exactly_one_payee(self):
        # no method / paid_at: the payment is recorded as due
        base = dict(session=self.session, payer=self.coach, amount=10, currency="KWD", platform_fee=1)
        self.assertRejected(Payment, club=self.club, coach=self.coach, **base)
        self.assertRejected(Payment, **base)
        self.assertIsNone(Payment.objects.create(club=self.club, **base).paid_at)

    def test_connection_unique(self):
        other = User.objects.create_user("p@example.com", "pw-123-long")
        Connection.objects.create(user=self.coach, other_user=other, type="coaching")
        self.assertRejected(Connection, user=self.coach, other_user=other, type="coaching")

    def test_rpe_range(self):
        for bad in (0, 11):
            self.assertRejected(SessionParticipant, session=self.session, user=self.coach, rpe=bad)
        SessionParticipant.objects.create(session=self.session, user=self.coach, rpe=10)

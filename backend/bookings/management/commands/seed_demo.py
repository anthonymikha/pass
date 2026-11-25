"""SEED-4: demo data for every screen of the app (docs/backend/logic/seed-data.md).

Procedural, from a fixed random seed: clubs in six cities with courts, price windows, amenities, rentables, closures
and offers; their owners, staff and coaches (rates, bios, clubs); players; teams; and court bookings, training and
training requests from two weeks ago to a month ahead, with rentals waiting, approved or declined, and some cancelled.
Only what the app shows: no payments (the scheduler bills the past sessions itself), chat messages, wellness or video.

Runs once: when the demo accounts exist it only sets their password again. They are <name>@pass-demo.example, plus
owner@, staff@, coach@ and player@ with the richest data. Their password is DEMO_PASSWORD from the environment;
without it nobody can sign in as them.
"""
import datetime
import os
import random
import zoneinfo
from collections import Counter, defaultdict
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from bookings.models import Session, SessionParticipant, SessionRental
from bookings.services import _closed_ranges, best_offer, offered_slots
from chat.services import add_chat_member
from teams.models import Group, GroupMember
from teams.services import create_group
from venues.models import Club, ClubMember, Court, CourtBlockout, CourtRate, Discount, Equipment, Sport
from venues.services import club_today

DOMAIN = "pass-demo.example"
PAST_DAYS, FUTURE_DAYS = 14, 30
DAY = datetime.timedelta(days=1)
t = datetime.time

FIRST = ["Amira", "Karim", "Lina", "Omar", "Maya", "Hadi", "Nour", "Rami", "Sara", "Ziad", "Yara", "Fadi", "Dana",
         "Tarek", "Leila", "Sami", "Rana", "Jad", "Hala", "Nabil", "Lucia", "Mateo", "Sofia", "Diego", "Emma", "Oliver",
         "Chloe", "James", "Aisha", "Yusuf", "Mariam", "Khalid", "Salma", "Adam", "Ines", "Marco"]
LAST = ["Haddad", "Khoury", "Nassar", "Saleh", "Aoun", "Farah", "Mansour", "Hamdan", "Rahal", "Saad", "Garcia",
        "Martin", "Lopez", "Smith", "Taylor", "Brown", "Rossi", "Ali", "Hassan", "Ibrahim", "Youssef", "Karam"]

# (city, time zone, currency, an hour of court in that currency, districts: at least 3)
CITIES = [
    ("Beirut", "Asia/Beirut", "USD", 30, ["Hamra", "Achrafieh", "Verdun", "Mar Mikhael", "Badaro"]),
    ("Dubai", "Asia/Dubai", "AED", 150, ["Marina", "Al Quoz", "Jumeirah", "Business Bay"]),
    ("Riyadh", "Asia/Riyadh", "SAR", 150, ["Olaya", "Al Malqa", "Hittin"]),
    ("Cairo", "Africa/Cairo", "EGP", 800, ["Zamalek", "Maadi", "New Cairo"]),
    ("Madrid", "Europe/Madrid", "EUR", 28, ["Chamberi", "Salamanca", "Retiro"]),
    ("London", "Europe/London", "GBP", 32, ["Shoreditch", "Battersea", "Canary Wharf"]),
]
STREETS = ["Main Street", "Park Avenue", "Seaside Road", "Garden Street", "Station Road", "Olive Street"]

# (court name, sports, slot lengths, descriptions, club names); weights pick a club's main kind
KINDS = [
    ("Padel", ["Padel"], [60, 90], ["Panoramic glass walls, LED lights.", "Indoor and air-conditioned.",
                                    "Covered outdoor court."], ["Padel Club", "Padel Center"]),
    ("Tennis", ["Tennis"], [60], ["Red clay.", "Hard court with floodlights.", "Acrylic hard court, covered stands."],
     ["Tennis Club", "Racquet Club"]),
    ("Pitch", ["Football (5-a-side)"], [60, 90], ["Artificial grass, floodlit.", "Indoor pitch, rubber floor."],
     ["Football Arena", "Sports Park"]),
    ("Hall", ["Basketball", "Volleyball"], [60], ["Indoor hall with a sprung wooden floor."], ["Sports Hall", "Arena"]),
    ("Pickleball", ["Pickleball", "Badminton"], [30, 60], ["Indoor, lines for pickleball and badminton."],
     ["Pickleball Club", "Athletic Club"]),
    ("Squash", ["Squash"], [45], ["Glass back wall, air-conditioned."], ["Squash Club", "Racquet Club"]),
]
WEIGHTS = [5, 3, 2, 1, 1, 1]
RENTABLES = {  # sport: (name, quantity, price in USD); quantity 1 = one court's own
    "Padel": [("Padel racket", 12, 5), ("Padel balls, can of 3", 30, 4)],
    "Tennis": [("Tennis racket", 8, 6), ("Ball machine", 1, 15)],
    "Football (5-a-side)": [("Football", 8, 2), ("Bibs, set of 10", 4, 3)],
    "Basketball": [("Basketball", 10, 2)],
    "Volleyball": [("Volleyball", 6, 2)],
    "Pickleball": [("Pickleball paddle", 10, 3)],
    "Badminton": [("Badminton racket", 10, 3), ("Shuttlecocks, tube of 6", 20, 4)],
    "Squash": [("Squash racket", 6, 4), ("Squash balls", 12, 2)],
}
AMENITIES = ["Drinking water", "Changing rooms", "Showers", "Lockers", "Free parking", "Wi-Fi", "Towels", "Cafe"]
CLOSURES = ["Resurfacing", "Private event", "Club tournament", "Light repairs"]
WEEKLY = ["Academy hours", "Weekly cleaning", "Coaching clinic"]
BIOS = [
    "{sport} coach for {years} years. I work on footwork, positioning and match tactics.",
    "Former national {sport} player. Private and small-group sessions for every level.",
    "Certified {sport} coach. Beginners welcome: we start from the grip and build up.",
    "I coach juniors and adults in {sport}, with a focus on fitness and consistency.",
]
TEAMS = ["Juniors", "Squad", "Academy", "Ladies", "Seniors"]

ACCEPTED, INVITED = SessionParticipant.Status.ACCEPTED, SessionParticipant.Status.INVITED
CONFIRMED, CANCELLED = Session.Status.CONFIRMED, Session.Status.CANCELLED
PLAY, TRAINING = Session.Kind.PLAY, Session.Kind.TRAINING
ACTIVE = ClubMember.Status.ACTIVE


class Command(BaseCommand):
    help = "Demo clubs, courts, prices, equipment, people and sessions for every screen (SEED-4). Runs once."

    def handle(self, *args, **options):
        call_command("seed")  # the sports and default commissions it needs
        password = make_password(os.environ.get("DEMO_PASSWORD") or None)  # None: nobody can sign in
        demo = User.objects.filter(email__endswith="@" + DOMAIN)
        if demo.exists():
            demo.update(password=password)
            self.stdout.write("Demo data already there: only the demo password was set again.")
            return
        with transaction.atomic():
            made = Demo(random.Random(2026), password).build()
        self.stdout.write(f"Demo data created: {made}. Sign in as owner@, staff@, coach@ or player@{DOMAIN}.")


class Demo:
    def __init__(self, rng, password):
        self.rng, self.password, self.now = rng, password, timezone.now()
        self.sports = {s.name: s for s in Sport.objects.all()}
        self.names = rng.sample([(f, n) for f in FIRST for n in LAST], len(FIRST) * len(LAST))
        self.teams = {}  # coach pk: (team, players)
        self.busy = defaultdict(list)  # user pk: [(start, end)], so nobody is in two sessions at once
        self.sessions = []  # (unsaved session, {user: participant status}, [(equipment, quantity, price, status)])

    def build(self):
        rng = self.rng
        clubs = 0
        for i, city in enumerate(CITIES):
            first = i == 0  # the four sign-in accounts live in the first city
            kinds = rng.choices(KINDS, WEIGHTS, k=3 if first else rng.randint(2, 3))
            n = len(kinds)
            owners = [self.user("owner", city, first and k == 0) for k in range(n - first)]  # owner@ has two clubs
            staff = [self.user("staff", city, first and k == 0) for k in range(n - first)]  # so has staff@
            coach_clubs = [rng.sample(range(n), rng.randint(1, min(3, n))) for _ in range(rng.randint(3, 5))]
            for k in range(n):  # every club has a coach
                coach_clubs[k] = [k] + [c for c in coach_clubs[k] if c != k]
            coaches = [self.coach(city, first and j == 0, kinds[c[0]][1][0]) for j, c in enumerate(coach_clubs)]
            players = [self.user("player", city, first and k == 0) for k in range(rng.randint(30, 45))]
            User.objects.bulk_create(owners + staff + coaches + players)

            here = [self.club(city, kind, owners[k % len(owners)], district, first)
                    for k, (kind, district) in enumerate(zip(kinds, rng.sample(city[4], n)))]
            ClubMember.objects.bulk_create(
                [ClubMember(club=club, user=staff[k % len(staff)], role=ClubMember.Role.STAFF, status=ACTIVE)
                 for k, club in enumerate(here)]
                + [ClubMember(club=here[k], user=coach, role=ClubMember.Role.COACH, status=ACTIVE)
                   for coach, ks in zip(coaches, coach_clubs) for k in ks])
            for j, coach in enumerate(coaches):
                if j == 0 or rng.random() < 0.4:
                    self.team(coach, players, here[coach_clubs[j][0]])
                self.off_court(coach, players, city, j == 0)
            for k, club in enumerate(here):
                coaches_here = [c for c, ks in zip(coaches, coach_clubs) if k in ks]
                for court in club.demo_courts:
                    self.court_sessions(court, club, players, coaches_here)
            clubs += n

        sessions = [s for s, _, _ in self.sessions]
        Session.objects.bulk_create(sessions, batch_size=500)
        SessionParticipant.objects.bulk_create(
            [SessionParticipant(session=s, user=u, status=st) for s, people, _ in self.sessions
             for u, st in people.items()], batch_size=1000)
        SessionRental.objects.bulk_create(
            [SessionRental(session=s, equipment=e, quantity=q, price=p, status=st) for s, _, lines in self.sessions
             for e, q, p, st in lines], batch_size=1000)
        return (f"{clubs} clubs, {Court.objects.count()} courts, {User.objects.filter(is_coach=True).count()} coaches, "
                f"{len(sessions)} sessions")

    # ---- people ----

    def user(self, role, city, first, **fields):
        given, family = self.names.pop()
        email = f"{role}@{DOMAIN}" if first else f"{given}.{family}@{DOMAIN}".lower()
        return User(email=email, full_name=f"{given} {family}", password=self.password, timezone=city[1],
                    phone=f"+1 555 01{self.rng.randint(0, 99):02d}", **fields)

    def coach(self, city, first, sport):
        rng = self.rng
        rate = None if not first and rng.random() < 0.2 else Decimal(rng.choice([25, 30, 35, 40, 50, 60]))
        coach = self.user("coach", city, first, is_coach=True, coach_rate=rate, coach_currency="USD",
                          coach_bio=rng.choice(BIOS).format(sport=sport, years=rng.randint(3, 15)))
        coach.demo_sport = self.sports[sport]
        return coach

    def team(self, coach, players, club):
        """TEAM-20 and active members, so team training shows the team's name."""
        sport = coach.demo_sport
        team = create_group(coach, f"{club.demo_district} {sport.name} {self.rng.choice(TEAMS)}", Group.Type.TEAM, sport)
        members = self.rng.sample(players, self.rng.randint(4, 7))
        GroupMember.objects.bulk_create(GroupMember(group=team, user=p, status=GroupMember.Status.ACTIVE) for p in members)
        for p in members:
            add_chat_member(team, p)
        self.teams[coach.pk] = (team, members)

    # ---- clubs ----

    def club(self, city, kind, owner, district, rich):
        rng = self.rng
        name, zone, currency, hour, _ = city
        club = Club.objects.create(
            owner=owner, name=f"{district} {rng.choice(kind[4])}", timezone=zone, currency=currency,
            address=f"{rng.randint(1, 240)} {rng.choice(STREETS)}, {district}, {name}")
        club.demo_district, club.demo_hour = district, hour
        opens, closes = rng.choice([7, 8]), rng.choice([22, 23, 0])  # 0: until midnight

        numbers, courts = Counter(), []
        for j, (label, sports, slots, descriptions, _) in enumerate([kind] * rng.randint(2, 4)
                                                                  + rng.choices(KINDS, k=rng.randint(0, 2))):
            numbers[label] += 1
            court = Court.objects.create(club=club, name=f"{label} {numbers[label]}", description=rng.choice(descriptions),
                                         slot_minutes=rng.choice(slots), is_active=j == 0 or rng.random() > 0.1)
            court.demo_sports = [self.sports[s] for s in sports]
            court.sports.set(court.demo_sports)
            per_slot = Decimal(hour * court.slot_minutes) / 60

            def price(factor):
                return Decimal(round(per_slot * Decimal(factor)))

            rates = [(d, t(opens), t(17), price(1)) for d in range(5)]  # weekdays: off-peak, then peak
            rates += [(d, t(17), t(closes), price("1.4")) for d in range(5)]
            if j == 0 or rng.random() > 0.15:  # some courts are closed at weekends
                rates += [(d, t(opens + 1), t(closes), price("1.2")) for d in (5, 6)]
            CourtRate.objects.bulk_create(CourtRate(court=court, weekday=d, start_time=a, end_time=b, price=p)
                                          for d, a, b, p in rates)
            courts.append(court)
        active = [c for c in courts if c.is_active]
        club.demo_courts = active

        # amenities (free), one court's own amenity, rentables for the sports played here
        items = [(Equipment(club=club, name=a, quantity=rng.randint(1, 40)), None)
                 for a in rng.sample(AMENITIES, rng.randint(3, 5))]
        items.append((Equipment(club=club, court=rng.choice(active), name="Live scoreboard", quantity=1), None))
        for sport in sorted({s.name for c in active for s in c.demo_sports}):
            for item, quantity, usd in RENTABLES[sport]:
                court = rng.choice([c for c in active if sport in {s.name for s in c.demo_sports}]) if quantity == 1 else None
                items.append((Equipment(club=club, court=court, name=item, quantity=quantity,
                                        rental_price=Decimal(max(1, round(usd * hour / 30)))), sport))
        Equipment.objects.bulk_create(e for e, _ in items)
        club.demo_rentables = [(e, sport) for e, sport in items if sport]

        today = club_today(club)
        CourtBlockout.objects.bulk_create([  # closures: a weekly one and a one-off
            CourtBlockout(court=rng.choice(active), starts_on=today - PAST_DAYS * DAY, start_time=t(opens),
                          end_time=t(opens + 2), repeat=CourtBlockout.Repeat.WEEKLY, reason=rng.choice(WEEKLY)),
            CourtBlockout(court=rng.choice(active), starts_on=today + rng.randint(1, 20) * DAY, start_time=t(10),
                          end_time=t(13), reason=rng.choice(CLOSURES)),
        ])

        start, end, offers = self.now - PAST_DAYS * DAY, self.now + 45 * DAY, []  # DSC: offers shown in the quote
        if rich or rng.random() < 0.6:
            pct = rng.choice([10, 15, 20])
            offers.append(Discount(club=club, percent_off=pct, starts_at=start, ends_at=end,
                                   message=f"Opening season: {pct}% off every court."))
        if rich or rng.random() < 0.4:
            offers.append(Discount(club=club, min_bookings=3, percent_off=10, starts_at=start, ends_at=end,
                                   message="Regulars: 10% off once you have played here 3 times."))
        if rich or rng.random() < 0.4:
            court, off = rng.choice(active), Decimal(round(hour * 0.3))
            offers.append(Discount(club=club, court=court, amount_off=off, starts_at=start, ends_at=end,
                                   message=f"{court.name}: {off} {currency} off every booking."))
        Discount.objects.bulk_create(offers)
        return club

    # ---- sessions ----

    def court_sessions(self, court, club, players, coaches):
        """Runs of the court's offered slots (AVL-1), outside its closures and never overlapping; busier soon."""
        rng, today = self.rng, club_today(club)
        days = [today + n * DAY for n in range(-PAST_DAYS, FUTURE_DAYS + 1)]
        slots, closed = offered_slots(court, days), _closed_ranges(court, days)
        i = 0
        while i < len(slots):
            ahead = (slots[i].starts_at - self.now) / DAY
            density = 0.2 if ahead < 0 else 0.15 * max(0, 1 - ahead / 35)
            size = max(1, round(rng.choice([60, 60, 90, 120]) / court.slot_minutes))
            run = slots[i:i + size]
            start, end = run[0].starts_at, run[-1].ends_at
            if (rng.random() >= density or len(run) < size or any(a.ends_at != b.starts_at for a, b in zip(run, run[1:]))
                    or any(start < b and end > a for a, b in closed)):
                i += 1
                continue
            self.on_court(court, club, run, players, coaches)
            i += size

    def on_court(self, court, club, run, players, coaches):
        rng = self.rng
        start, end = run[0].starts_at, run[-1].ends_at
        past = start < self.now
        sport = rng.choice(court.demo_sports)
        price = sum((s.rate.price for s in run), Decimal(0))
        session = Session(court=court, sport=sport, kind=PLAY, starts_at=start, ends_at=end, currency=club.currency,
                          price=price, status=CANCELLED if rng.random() < 0.08 else CONFIRMED)
        free = self.free(players, start, end)
        coach = rng.choice(coaches) if coaches and rng.random() < 0.2 else None
        lines = []
        if not free or (coach and self.free([coach], start, end) == []):
            return
        if coach:
            session.kind, session.coach = TRAINING, coach
            session.coach_fee = self.fee(coach, start, end, club.demo_hour)
            team, members = self.teams.get(coach.pk, (None, []))
            if team and team.sport in court.demo_sports and rng.random() < 0.5:  # BOOK-30: the coach books for the team
                session.sport, session.booked_by, session.group = team.sport, coach, team
                people = {coach: ACCEPTED, **{p: self.answer(past) for p in self.free(members, start, end)}}
            else:  # BOOK-21: a player's request the coach confirmed on this court
                session.booked_by = session.coach_fee_payer = self.pick(free)
                people = {session.booked_by: ACCEPTED, coach: None}
        else:  # BOOK-8, with friends and maybe a rentable
            session.booked_by = self.pick(free)
            friends = [p for p in rng.sample(free, min(len(free), rng.randint(0, 3))) if p != session.booked_by]
            people = {session.booked_by: ACCEPTED, **{p: self.answer(past) for p in friends}}
            options = [e for e, s in club.demo_rentables if s == sport.name and e.court_id in (None, court.pk)]
            if options and rng.random() < 0.3:
                e = rng.choice(options)
                q = rng.randint(1, min(4, e.quantity))
                status = rng.choice(["approved"] * 4 + ["declined"] if past else ["requested", "requested", "approved", "declined"])
                lines.append((e, q, e.rental_price * q, status))
        session.discount, session.discount_amount = best_offer(court, session.booked_by, start, price, club.currency,
                                                               Decimal(1))
        self.add(session, people, lines)

    def off_court(self, coach, players, city, first):
        """Training at the coach's own venue in USD (BOOK-21 without a court), and requests waiting (BOOK-20)."""
        rng, zone = self.rng, zoneinfo.ZoneInfo(city[1])
        today = self.now.astimezone(zone).date()

        def when(days, hour, minutes):
            start = datetime.datetime.combine(today + days * DAY, t(hour), tzinfo=zone)
            return start, start + datetime.timedelta(minutes=minutes)

        for _ in range(rng.randint(3, 6)):
            start, end = when(rng.randint(-PAST_DAYS, FUTURE_DAYS), rng.choice([7, 8, 17, 18, 19]), rng.choice([60, 90]))
            booker = self.pick(self.free(players, start, end))
            if self.free([coach], start, end) == [] or booker is None:
                continue
            self.add(Session(
                kind=TRAINING, status=CONFIRMED, sport=coach.demo_sport, booked_by=booker, coach=coach,
                coach_fee_payer=booker, starts_at=start, ends_at=end, currency="USD", price=0,
                coach_fee=self.fee(coach, start, end, 30)), {booker: ACCEPTED, coach: None})
        for k in range(4 if first else rng.randint(2, 4)):  # the first one the coach declined
            start, end = when(rng.randint(1, 14), rng.choice([9, 10, 18, 19]), 60)
            booker = self.pick(self.free(players, start, end))
            if booker is None:
                continue
            self.add(Session(
                kind=TRAINING, status=CANCELLED if k == 0 else Session.Status.REQUESTED, sport=coach.demo_sport,
                booked_by=booker, coach=coach, coach_fee_payer=booker, starts_at=start, ends_at=end, currency="",
                price=0), {booker: ACCEPTED})

    def fee(self, coach, start, end, hour):
        """FE-4: the coach's USD rate (30 when unset) times the hours, in the currency of a court hour `hour`."""
        rate = coach.coach_rate or 30
        return Decimal(round(rate * Decimal(hour) / 30 * Decimal((end - start) / datetime.timedelta(hours=1))))

    def add(self, session, people, lines=()):
        """`people`: {user: participant status}; None = busy (the coach) but no participant row."""
        for user in people:
            self.busy[user.pk].append((session.starts_at, session.ends_at))
        self.sessions.append((session, {u: s for u, s in people.items() if s}, lines))

    def free(self, users, start, end):
        return [u for u in users if not any(start < b and end > a for a, b in self.busy[u.pk])]

    def pick(self, players):
        return self.rng.choice(players) if players else None

    def answer(self, past):
        return ACCEPTED if past else self.rng.choice([ACCEPTED, ACCEPTED, INVITED])

"""SEED-4: demo data for every screen of the app (docs/backend/logic/seed-data.md).

Every backend start runs it. When this file changed since the data was made, or there is none yet, it deletes everything
but the real accounts and the lookup data (sports, default commissions, exercises), then builds a new world from a
random seed taken from this file: clubs in six cities, each with its own prices, opening hours, courts, amenities,
rentables, closures and offers; owners and staff; coaches, each with their own sports, clubs, rate and currency, working
days and hours, and bio; players with favourite sports and how much they play; teams; and court bookings, training and
training requests from two weeks ago to a month ahead. Only what the app shows: no payments (the scheduler bills the
past sessions itself), chat messages, wellness or video.

Otherwise it only sets the demo accounts' password again. They are first.last@pass-demo.example, plus owner@, staff@,
coach@ and player@ with the richest data; the password is DEMO_PASSWORD (empty: nobody can sign in as them).
"""
import datetime
import hashlib
import os
import random
import zoneinfo
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Connection, User, UserBlockout
from billing.models import Payment
from bookings.models import Recording, Session, SessionParticipant, SessionRental
from bookings.services import _closed_ranges, best_offer, offered_slots
from chat.models import Chat, Message
from chat.services import add_chat_member
from teams.models import Group, GroupMember
from teams.services import create_group
from venues.models import Club, ClubMember, Court, CourtBlockout, CourtRate, Discount, Equipment, Sport
from venues.services import club_today
from wellness.models import ExerciseAssignment, SleepLog, SorenessLog, UserAchievement

DOMAIN = "pass-demo.example"
VERSION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]  # any change to this file makes a new world
PAST_DAYS, FUTURE_DAYS = 14, 30
DAY = datetime.timedelta(days=1)
t = datetime.time

FX = {"USD": 1, "AED": 3.67, "SAR": 3.75, "EGP": 48, "EUR": 0.92, "GBP": 0.79}  # units per US dollar, near enough
STEPS = {"USD": [1, 5], "AED": [5, 10], "SAR": [5, 10], "EGP": [25, 50], "EUR": [0.5, 1, 5], "GBP": [0.5, 1, 5]}
SMALL = {"USD": 0.5, "AED": 1, "SAR": 1, "EGP": 5, "EUR": 0.5, "GBP": 0.5}  # rentables and coach fees

NAMES = {
    "arabic": (
        ["Amira", "Karim", "Lina", "Omar", "Maya", "Hadi", "Nour", "Rami", "Sara", "Ziad", "Yara", "Fadi", "Dana",
         "Tarek", "Leila", "Sami", "Rana", "Jad", "Hala", "Nabil", "Aisha", "Yusuf", "Mariam", "Khalid", "Salma",
         "Hussein", "Reem", "Majed", "Dima", "Walid", "Farah", "Bilal", "Noor", "Imad", "Ghada", "Fares", "Lama",
         "Mazen", "Rawan", "Tamer", "Joud", "Ali"],
        ["Haddad", "Khoury", "Nassar", "Saleh", "Aoun", "Farah", "Mansour", "Hamdan", "Rahal", "Saad", "Hassan",
         "Ibrahim", "Youssef", "Karam", "Daher", "Chami", "Masri", "Otaibi", "Qahtani", "Shamsi", "Mahmoud", "Fakhoury",
         "Sabbagh", "Najjar", "Azar", "Barakat", "Zein", "Hijazi", "Tannous", "Kassem"]),
    "spanish": (
        ["Lucia", "Mateo", "Sofia", "Diego", "Paula", "Javier", "Carmen", "Pablo", "Elena", "Alvaro", "Marta", "Hugo",
         "Irene", "Sergio", "Laura", "Andres", "Nerea", "Ivan", "Clara", "Raul", "Alba", "Marcos", "Ines", "Daniel"],
        ["Garcia", "Martinez", "Lopez", "Sanchez", "Romero", "Navarro", "Torres", "Ruiz", "Moreno", "Jimenez",
         "Alonso", "Gil", "Serrano", "Molina", "Castro", "Ortega", "Delgado", "Vega", "Ramos", "Iglesias"]),
    "english": (
        ["Emma", "Oliver", "Chloe", "James", "Amelia", "Harry", "Grace", "Jack", "Isla", "George", "Freya", "Leo",
         "Poppy", "Charlie", "Evie", "Alfie", "Ruby", "Oscar", "Hannah", "Theo", "Megan", "Callum", "Zara", "Ethan"],
        ["Smith", "Taylor", "Brown", "Wilson", "Evans", "Thomas", "Roberts", "Walker", "Wright", "Hughes", "Green",
         "Hall", "Wood", "Clarke", "Turner", "Hill", "Cooper", "Ward", "Morris", "Bennett"]),
}

# (city, time zone, currency, an hour of padel there, weekend days, name pool, languages, districts)
CITIES = [
    ("Beirut", "Asia/Beirut", "USD", 30, (5, 6), "arabic", ["Arabic", "English", "French"],
     ["Hamra", "Achrafieh", "Verdun", "Mar Mikhael", "Badaro", "Gemmayzeh", "Jnah"]),
    ("Dubai", "Asia/Dubai", "AED", 160, (5, 6), "arabic", ["English", "Arabic", "Hindi", "Russian"],
     ["Marina", "Al Quoz", "Jumeirah", "Business Bay", "Al Barsha", "Mirdif"]),
    ("Riyadh", "Asia/Riyadh", "SAR", 150, (4, 5), "arabic", ["Arabic", "English"],
     ["Olaya", "Al Malqa", "Hittin", "Al Yasmin", "Diriyah"]),
    ("Cairo", "Africa/Cairo", "EGP", 700, (4, 5), "arabic", ["Arabic", "English"],
     ["Zamalek", "Maadi", "New Cairo", "Heliopolis", "Sheikh Zayed"]),
    ("Madrid", "Europe/Madrid", "EUR", 26, (5, 6), "spanish", ["Spanish", "English"],
     ["Chamberi", "Salamanca", "Retiro", "Chamartin", "Moncloa"]),
    ("London", "Europe/London", "GBP", 30, (5, 6), "english", ["English", "Spanish", "Portuguese"],
     ["Shoreditch", "Battersea", "Canary Wharf", "Hackney", "Wimbledon", "Islington"]),
]
STREETS = ["Main Street", "Park Avenue", "Seaside Road", "Garden Street", "Station Road", "Olive Street", "Cedar Lane",
           "Harbour Road", "Palm Avenue", "Mill Lane", "Market Street", "Hillside Drive"]

# kind: (sports, slot lengths, price of an hour against padel, club names, description parts: one from each list,
# the first always, the others mostly). The weights pick a club's main kind.
KINDS = {
    "Padel": (["Padel"], [60, 90], 1, ["Padel Club", "Padel Center", "Padel Lounge"],
              [["panoramic glass", "glass and mesh walls"], ["blue turf", "green turf", "textured turf"],
               ["indoor", "covered", "open-air", "on the roof"], ["LED lights", "spectator seats", "air-conditioned"]]),
    "Tennis": (["Tennis"], [60], 0.9, ["Tennis Club", "Racquet Club", "Lawn Tennis Club"],
               [["red clay", "hard court", "acrylic hard court", "artificial grass"], ["floodlit", "covered", "open-air"],
                ["stands for 50", "practice wall", "shaded benches"]]),
    "Pitch": (["Football (5-a-side)"], [60, 90], 2.2, ["Football Arena", "Sports Park", "Five-a-side Center"],
              [["third-generation turf", "rubber floor", "artificial grass"], ["floodlit", "indoor", "on the roof"],
               ["rebound boards", "new goal nets", "changing rooms next door"]]),
    "Hall": (["Basketball", "Volleyball"], [60], 1.8, ["Sports Hall", "Arena", "Athletic Center"],
             [["sprung wooden floor", "sports vinyl floor"], ["indoor", "air-conditioned"],
              ["electronic scoreboard", "bleachers", "two side baskets"]]),
    "Pickleball": (["Pickleball", "Badminton"], [30, 60], 0.7, ["Pickleball Club", "Athletic Club"],
                   [["lines for pickleball and badminton", "cushioned surface"], ["indoor", "covered"],
                    ["paddle rack", "benches along the side"]]),
    "Squash": (["Squash"], [40, 45], 0.6, ["Squash Club", "Racquet Club"],
               [["glass back wall", "all-glass show court", "classic plaster walls"], ["air-conditioned", "viewing gallery"]]),
}
WEIGHTS = [5, 3, 2, 1, 1, 1]
NAMED_COURTS = ["Center Court", "Garden Court", "Rooftop", "North Court", "South Court", "Sunset Court", "The Box",
                "Court Azure", "Court Olive", "Main Court", "Show Court", "Court Cedar"]
MINUTES = {"Padel": [60, 90, 90, 120], "Tennis": [60, 60, 90, 120], "Football (5-a-side)": [60, 60, 90],
           "Basketball": [60, 90, 120], "Volleyball": [60, 90, 120], "Pickleball": [30, 60, 60, 90],
           "Badminton": [30, 60, 60], "Squash": [40, 45, 45, 90]}
PARTY = {"Padel": (2, 4), "Tennis": (2, 4), "Squash": (2, 2), "Badminton": (2, 4), "Pickleball": (2, 4),
         "Football (5-a-side)": (6, 10), "Basketball": (4, 10), "Volleyball": (6, 12)}
FAMILIES = [["Padel", "Tennis", "Pickleball", "Squash", "Badminton"], ["Football (5-a-side)", "Basketball", "Volleyball"]]

RENTABLES = {  # sport: (name, price in USD, quantity range, one court's own)
    "Padel": [("Padel racket", 5, (6, 20), False), ("Premium padel racket", 10, (2, 6), False),
              ("Padel balls, can of 3", 4, (10, 40), False), ("Padel shoes", 5, (4, 12), False)],
    "Tennis": [("Tennis racket", 6, (4, 12), False), ("Tennis balls, can of 4", 5, (10, 30), False),
               ("Ball machine", 15, (1, 1), True), ("Ball hopper", 3, (2, 6), False)],
    "Football (5-a-side)": [("Football", 2, (4, 10), False), ("Bibs, set of 10", 3, (2, 6), False),
                            ("Goalkeeper gloves", 2, (2, 6), False), ("Shin guards", 1, (6, 20), False)],
    "Basketball": [("Basketball", 2, (4, 12), False), ("Bibs, set of 10", 3, (2, 6), False)],
    "Volleyball": [("Volleyball", 2, (3, 8), False), ("Knee pads", 2, (6, 16), False)],
    "Pickleball": [("Pickleball paddle", 3, (6, 16), False), ("Pickleballs, set of 6", 3, (5, 15), False)],
    "Badminton": [("Badminton racket", 3, (6, 16), False), ("Shuttlecocks, tube of 6", 4, (10, 30), False)],
    "Squash": [("Squash racket", 4, (4, 10), False), ("Squash balls", 2, (6, 20), False),
               ("Protective goggles", 1, (4, 10), False)],
}
AMENITIES = {"Drinking water": (1, 1), "Changing rooms": (2, 4), "Showers": (4, 16), "Lockers": (20, 80),
             "Free parking": (10, 120), "Valet parking": (1, 1), "Wi-Fi": (1, 1), "Towels": (20, 100), "Cafe": (1, 1),
             "Pro shop": (1, 1), "Kids' corner": (1, 1), "Prayer room": (1, 2), "Physio room": (1, 1), "Sauna": (1, 2),
             "Bike racks": (6, 30), "Shaded seating": (10, 60)}
COURT_AMENITIES = ["Live scoreboard", "Match camera", "Heating", "Spectator stand", "Ceiling fans"]

ONE_OFF = ["Resurfacing", "Private event", "Club tournament", "Light repairs", "Net replacement", "School booking",
           "Film shoot", "Public holiday"]
ALL_COURTS = {"Private event", "Club tournament", "Public holiday"}
REPEATING = {"weekly": ["Academy hours", "Weekly cleaning", "Coaching clinic", "Junior league", "Ladies' morning",
                        "Corporate league"],
             "monthly": ["Deep clean", "Floor inspection", "Members' tournament"], "daily": ["Midday break"]}
OFFERS = {
    "percent": ["Opening season: {p}% off every court.", "Summer evenings: {p}% off.", "Anniversary month: {p}% off.",
                "Off-peak deal: {p}% off.", "New courts, new prices: {p}% off.", "Friends of the club: {p}% off."],
    "regulars": ["Regulars: {p}% off once you have played here {n} times.", "Loyalty reward: {p}% off after {n} bookings.",
                 "Play here {n} times, then save {p}% on every game."],
    "court": ["{court}: {amount} {cur} off every booking.", "Try {court}: {amount} {cur} off.",
              "{amount} {cur} off on {court} this month."],
    "personal": ["Welcome back, {first}: {p}% off your games here.", "{first}, thanks for playing with us: {p}% off."],
    "upcoming": ["League week: {p}% off.", "Holiday special: {p}% off.", "Tournament warm-up week: {p}% off."],
}

FOCUS = ["I work on footwork, positioning and match tactics.", "Technique first, then a lot of match play.",
         "Expect fitness drills that leave you breathing hard.",
         "Nothing beats helping a beginner through their first long rally.", "I prepare juniors for regional tournaments.",
         "Video analysis is part of every block of sessions.", "Shot selection and the mental game are my thing.",
         "Small groups, lots of ball contact, no standing in line.", "I keep sessions fun; the progress follows.",
         "Warm-ups and injury prevention are built into every session.",
         "Every session ends with a game, so the drills stick."]
AUDIENCE = ["Kids from {age}, teens and adults.", "Mostly adults getting back into sport.",
            "Women's groups and private lessons.", "Competitive players aiming for league level.",
            "All levels, one to one or in groups of up to {n}.", "Corporate groups and team-building sessions."]
CREDENTIALS = ["Level {level} certified {sport} coach.", "Federation-certified, level {level}.",
               "First-aid and safeguarding certified.", "Sports science degree and a strength and conditioning certificate."]
ABROAD = ["the US", "the UK", "Spain", "France", "Canada", "Australia"]
TEAM_NAMES = ["U10", "U12", "U14", "U16", "U18", "Ladies", "Masters 40+", "Beginners", "Competition Squad", "Academy",
              "Juniors", "Development Group", "Elite", "Morning Crew", "After-work Group"]

ACCEPTED, INVITED, DECLINED = (SessionParticipant.Status.ACCEPTED, SessionParticipant.Status.INVITED,
                               SessionParticipant.Status.DECLINED)
CONFIRMED, CANCELLED, REQUESTED = Session.Status.CONFIRMED, Session.Status.CANCELLED, Session.Status.REQUESTED
PLAY, TRAINING = Session.Kind.PLAY, Session.Kind.TRAINING
ACTIVE = ClubMember.Status.ACTIVE


def label(sport):
    """A sport's name inside a sentence: padel, football."""
    return "football" if sport.startswith("Football") else sport.lower()


def wipe():
    """Everything but the real accounts (with their devices and sign-in tokens) and the lookup data, in the order the
    PROTECT foreign keys allow."""
    for model in (Message, Chat, Payment, Recording, SorenessLog, SleepLog, ExerciseAssignment, UserAchievement,
                  Session, Group, Club, Connection, UserBlockout):
        model.objects.all().delete()
    User.objects.filter(email__endswith="@" + DOMAIN).delete()


class Command(BaseCommand):
    help = "Demo data for every screen (SEED-4): rebuilt from scratch when this script changed, else left as it is."

    def handle(self, *args, **options):
        call_command("seed")  # the sports and default commissions it needs
        password = make_password(os.environ.get("DEMO_PASSWORD") or None)  # None: nobody can sign in
        marker = f"seed-{VERSION}@{DOMAIN}"
        demo = User.objects.filter(email__endswith="@" + DOMAIN)
        if demo.filter(email=marker).exists():
            demo.exclude(email=marker).update(password=password)
            self.stdout.write("Demo data is current: only the demo password was set again.")
            return
        with transaction.atomic():
            wipe()
            made = Demo(random.Random(VERSION), password).build()
            User.objects.create_user(email=marker, full_name="Demo data version", is_active=False)
        self.stdout.write(f"Everything but the real accounts deleted. Demo data created: {made}. "
                          f"Sign in as owner@, staff@, coach@ or player@{DOMAIN}.")


class Demo:
    def __init__(self, rng, password):
        self.rng, self.password, self.now = rng, password, timezone.now()
        self.sports = {s.name: s for s in Sport.objects.all()}
        self.names, self.bios = set(), set()
        self.teams = defaultdict(list)  # coach pk: [(team, players)]
        self.busy = defaultdict(list)  # user pk: [(start, end)], so nobody is in two sessions at once
        self.sessions = []  # (unsaved session, {user: participant status}, [(equipment, quantity, price, status)])

    def build(self):
        for i, city in enumerate(CITIES):
            self.city(city, first=i == 0)
        sessions = [s for s, _, _ in self.sessions]
        Session.objects.bulk_create(sessions, batch_size=500)
        SessionParticipant.objects.bulk_create(
            [SessionParticipant(session=s, user=u, status=st) for s, people, _ in self.sessions
             for u, st in people.items()], batch_size=1000)
        SessionRental.objects.bulk_create(
            [SessionRental(session=s, equipment=e, quantity=q, price=p, status=st) for s, _, lines in self.sessions
             for e, q, p, st in lines], batch_size=1000)
        return (f"{Club.objects.count()} clubs, {Court.objects.count()} courts, "
                f"{User.objects.filter(is_coach=True).count()} coaches, {len(sessions)} sessions")

    def city(self, city, first):
        """The first city holds the sign-in accounts: owner@ owns its first and third clubs, staff@ works at both,
        coach@ coaches at both, player@ plays a lot."""
        rng = self.rng
        n = 3 if first else rng.randint(2, 4)
        clubs, owner = [], None
        for k, district in enumerate(rng.sample(city[7], n)):
            if first and k == 2:
                owner = clubs[0].owner
            elif first or not owner or rng.random() > 0.25:  # elsewhere some owners have two clubs
                owner = self.person("owner", city, first and k == 0)
            clubs.append(self.club(city, rng.choices(list(KINDS), WEIGHTS)[0], owner, district))

        members, staff = [], []
        for k, club in enumerate(clubs):
            people = [self.person("staff", city, first and k == 0 and m == 0) for m in range(rng.randint(1, 2))]
            if first and k == 2:
                people.append(members[0].user)
            elif staff and rng.random() < 0.25:  # works at two clubs
                people.append(rng.choice(staff))
            staff += people
            members += [ClubMember(club=club, user=u, role=ClubMember.Role.STAFF, status=ACTIVE) for u in people]

        played = Counter(s.name for club in clubs for c in club.demo_courts for s in c.demo_sports)
        players = [self.player(city, played, first and k == 0) for k in range(rng.randint(30, 50))]

        coaches = []
        for j in range(rng.randint(4, 8)):
            if first and j == 0:
                coach = self.coach(city, [clubs[0].demo_courts[0].demo_sports[0].name], first=True)
                coach.demo_clubs = [clubs[0], clubs[2]]
            else:
                coach = self.coach(city, [rng.choices(list(played), list(played.values()))[0]])
                offering = [c for c in clubs if c.demo_sports & {s.name for s in coach.demo_sports}]
                coach.demo_clubs = rng.sample(offering, min(len(offering), rng.choices([0, 1, 2, 3], [1, 5, 3, 1])[0]))
            coaches.append(coach)
        for club in clubs:  # every club has a coach for one of its sports
            if not any(club in c.demo_clubs and club.demo_sports & {s.name for s in c.demo_sports} for c in coaches):
                coach = self.coach(city, [rng.choice(sorted(club.demo_sports))])
                coach.demo_clubs = [club]
                coaches.append(coach)
        members += [ClubMember(club=club, user=c, role=ClubMember.Role.COACH, status=ACTIVE)
                    for c in coaches for club in c.demo_clubs]
        ClubMember.objects.bulk_create(members)

        for club in clubs:
            self.offers(club, players, first)
        zone = zoneinfo.ZoneInfo(city[1])
        for j, coach in enumerate(coaches):
            self.coach_teams(coach, players, city, first and j == 0)
        for j, coach in enumerate(coaches):
            self.coach_week(coach, players, zone, first and j == 0)
        for club in clubs:
            teachers = [c for c in coaches if club in c.demo_clubs]
            for court in club.demo_courts:
                self.court_sessions(court, club, players, teachers)

    # ---- people ----

    def person(self, role, city, first=False, **fields):
        rng = self.rng
        pool = city[5] if rng.random() < 0.75 else rng.choice([p for p in NAMES if p != city[5]])
        while (name := (rng.choice(NAMES[pool][0]), rng.choice(NAMES[pool][1]))) in self.names:
            pass
        self.names.add(name)
        email = f"{role}@{DOMAIN}" if first else f"{name[0]}.{name[1]}@{DOMAIN}".lower()
        user = User(email=email, full_name=" ".join(name), password=self.password, timezone=city[1],
                    phone=f"+1 555 01{rng.randint(0, 99):02d}" if rng.random() < 0.85 else "", **fields)
        user.save()
        return user

    def player(self, city, played, first):
        player = self.person("player", city, first)
        player.demo_sports = set(self.rng.choices(list(played), list(played.values()), k=self.rng.randint(1, 3)))
        player.demo_activity = 2.5 if first else self.rng.choice([0.2, 0.5, 1, 1, 1.5, 2.5, 4])
        return player

    def coach(self, city, sports, first=False):
        """Own sports (the first, then related ones), rate and currency, working days and hours, session lengths."""
        rng = self.rng
        family = next(f for f in FAMILIES if sports[0] in f)
        sports += rng.sample([s for s in family if s != sports[0]], rng.choices([0, 1, 2], [5, 4, 1])[0])
        currency = city[2] if rng.random() < 0.55 else "USD"
        years = rng.randint(2, 25)
        rate = None if not first and rng.random() < 0.15 else self.nice(
            (18 + years * 2.2) * rng.uniform(0.7, 1.4) * FX[currency], rng.choice(STEPS[currency]))
        coach = self.person("coach", city, first, is_coach=True, coach_rate=rate, coach_currency=currency,
                            coach_bio=self.bio(city, sports, years))
        coach.demo_sports = [self.sports[s] for s in sports]
        coach.demo_days = {0, 1, 2, 3, 5} if first else set(rng.sample(range(7), rng.randint(3, 6)))
        start = 9 if first else rng.choice([6, 7, 8, 9, 10, 13, 14, 15, 16])
        coach.demo_hours = (start, 21 if first else min(23, start + rng.randint(4, 9)))
        coach.demo_lengths = rng.sample([45, 60, 75, 90, 120], rng.randint(1, 3))
        coach.demo_load = 0.5 if first else rng.uniform(0.2, 0.8)  # how busy
        return coach

    def bio(self, city, sports, years):
        """Sentences picked and filled per coach; never the same bio twice."""
        rng, place = self.rng, city[0]
        if rng.random() < 0.07:
            return ""
        main, since = label(sports[0]), self.now.year - years
        while True:
            lines = [rng.choice([
                f"Coaching {main} for {years} years.", f"{main.capitalize()} coach since {since}.",
                f"Former national-team {main} player, coaching full time since {since}.",
                f"Played college {main} in {rng.choice(ABROAD)} before coming back to {place}.",
                f"Grew up playing {main} in {place}; {years} years of coaching since.",
                f"Ex-pro {main} player, {years} years as a coach.",
            ])] + rng.sample(FOCUS, rng.randint(1, 2))
            if len(sports) > 1:
                lines.append(f"I also teach {' and '.join(label(s) for s in sports[1:])}.")
            if rng.random() < 0.6:
                lines.append(rng.choice(AUDIENCE).format(age=rng.choice([5, 6, 7, 8]), n=rng.choice([3, 4, 6, 8])))
            if rng.random() < 0.5:
                lines.append(rng.choice(CREDENTIALS).format(level=rng.randint(1, 3), sport=main))
            if rng.random() < 0.5:
                langs = rng.sample(city[6], rng.randint(1, min(3, len(city[6]))))
                lines.append(f"Sessions in {', '.join(langs[:-1]) + ' and ' if len(langs) > 1 else ''}{langs[-1]}.")
            bio = " ".join(lines)
            if bio not in self.bios:
                self.bios.add(bio)
                return bio

    def coach_teams(self, coach, players, city, first):
        """TEAM-20: 0 to 2 teams in the coach's sports, with active members who like that sport."""
        rng = self.rng
        for _ in range(max(first, rng.choices([0, 1, 2], [9, 8, 3])[0])):
            sport = rng.choice(coach.demo_sports)
            where = rng.choice(coach.demo_clubs).demo_district if coach.demo_clubs else rng.choice(city[7])
            team = create_group(coach, f"{where} {label(sport.name).title()} {rng.choice(TEAM_NAMES)}", Group.Type.TEAM,
                                sport)
            team_sport = sport.name in FAMILIES[1]
            members = self.choose(players, sport.name, rng.randint(6, 12) if team_sport else rng.randint(3, 8))
            GroupMember.objects.bulk_create(GroupMember(group=team, user=p, status=GroupMember.Status.ACTIVE)
                                            for p in members)
            for p in members:
                add_chat_member(team, p)
            self.teams[coach.pk].append((team, members))

    # ---- clubs ----

    def club(self, city, kind, owner, district):
        """A club with its own price level, opening hours, peak, deals, courts, equipment and closures."""
        rng = self.rng
        place, zone, currency, hour, weekend = city[:5]
        club = Club.objects.create(
            owner=owner, name=f"{district} {rng.choice(KINDS[kind][3])}", timezone=zone, currency=currency,
            address=f"{rng.randint(1, 240)} {rng.choice(STREETS)}, {district}, {place}")
        club.demo_district, club.demo_weekend = district, weekend
        club.demo_busy, club.demo_cancel = rng.uniform(0.5, 1.4), rng.uniform(0.02, 0.12)
        club.demo_tier = rng.uniform(0.75, 1.45)  # budget to premium
        club.demo_hour, club.demo_step = hour * club.demo_tier, rng.choice(STEPS[currency])
        opens, closes = rng.choice([6, 7, 7, 8, 9]), rng.choice([21, 22, 23, 23, 24])  # 24: until midnight
        club.demo_open, club.demo_close, club.demo_peak = opens, closes, rng.choice([16, 17, 17, 18])

        weekday = [(opens, 9, rng.uniform(0.7, 0.85))] if opens < 9 and rng.random() < 0.35 else []  # early bird
        weekday.append((weekday[-1][1] if weekday else opens, club.demo_peak, 1))
        late = closes >= 23 and rng.random() < 0.3  # cheaper late at night
        weekday.append((club.demo_peak, 22 if late else closes, rng.uniform(1.15, 1.6)))
        if late:
            weekday.append((22, closes, rng.uniform(0.8, 1)))
        we_open, we_close, we_price = opens + rng.choice([0, 1, 2]), rng.choice([20, 22, 23, 24]), rng.uniform(0.95, 1.4)
        weekend_rows = [(we_open, we_close, we_price)]
        if rng.random() < 0.3:  # weekend afternoons cheaper
            mid = rng.choice([14, 15, 16])
            weekend_rows = [(we_open, mid, we_price), (mid, we_close, we_price * rng.uniform(0.8, 0.95))]
        windows = {d: weekend_rows if d in weekend else weekday for d in range(7)}

        layout = [kind] * rng.randint(1, 5) + rng.choices(list(KINDS), k=rng.choices([0, 1, 2, 3], [5, 3, 2, 1])[0])
        style, named, numbers, courts = rng.choice(["kind", "number", "named"]), rng.sample(NAMED_COURTS, 12), Counter(), []
        for j, k in enumerate(layout):
            numbers[k] += 1
            name = named.pop() if style == "named" else f"Court {j + 1}" if style == "number" else f"{k} {numbers[k]}"
            courts.append(self.court(club, k, name, j, windows))
        club.demo_courts = [c for c in courts if c.is_active]
        club.demo_sports = {s.name for c in club.demo_courts for s in c.demo_sports}
        self.equipment(club, currency)
        self.closures(club)
        return club

    def court(self, club, kind, name, j, windows):
        rng = self.rng
        sports, slots, factor, _, parts = KINDS[kind]
        about = ", ".join([rng.choice(parts[0])] + [rng.choice(p) for p in parts[1:] if rng.random() < 0.7])
        court = Court.objects.create(club=club, name=name, slot_minutes=rng.choice(slots),
                                     description=about[0].upper() + about[1:] + "." if rng.random() < 0.9 else "",
                                     is_active=j == 0 or rng.random() > 0.08)
        court.demo_sports = [self.sports[s] for s in sports]
        court.sports.set(court.demo_sports)
        per_slot = club.demo_hour * factor * rng.choice([1, 1, 1, 0.9, 1.1, 1.25]) * court.slot_minutes / 60
        closed = set()
        if j and rng.random() < 0.15:  # a maintenance day
            closed.add(rng.randrange(7))
        if j and rng.random() < 0.1:  # weekdays only
            closed |= set(club.demo_weekend)
        CourtRate.objects.bulk_create(
            CourtRate(court=court, weekday=d, start_time=t(a), end_time=t(b % 24),
                      price=self.nice(per_slot * f, club.demo_step))
            for d, rows in windows.items() if d not in closed for a, b, f in rows)
        return court

    def equipment(self, club, currency):
        """Free amenities, a court's own amenities, and some of the rentables of each sport played here, at this
        club's prices."""
        rng, active = self.rng, club.demo_courts
        items = [Equipment(club=club, name=a, quantity=rng.randint(*AMENITIES[a]))
                 for a in rng.sample(list(AMENITIES), rng.randint(2, 7))]
        items += [Equipment(club=club, court=rng.choice(active), name=a, quantity=1)
                  for a in rng.sample(COURT_AMENITIES, rng.choices([0, 1, 2], [3, 4, 2])[0])]
        rentables = {}  # name: (equipment, sports)
        for sport in sorted(club.demo_sports):
            for name, usd, (lo, hi), own in rng.sample(RENTABLES[sport], rng.randint(1, len(RENTABLES[sport]))):
                if name not in rentables:
                    court = rng.choice([c for c in active if sport in {s.name for s in c.demo_sports}]) if own else None
                    price = self.nice(usd * FX[currency] * club.demo_tier * rng.uniform(0.8, 1.25), SMALL[currency])
                    rentables[name] = (Equipment(club=club, court=court, name=name, quantity=rng.randint(lo, hi),
                                                 rental_price=price), set())
                rentables[name][1].add(sport)
        Equipment.objects.bulk_create(items + [e for e, _ in rentables.values()])
        club.demo_rentables = list(rentables.values())

    def closures(self, club):
        """1 to 4: one-offs (some on every court, some all day), weekly ones (some ending), monthly, a daily break."""
        rng, today, rows = self.rng, club_today(club), []
        opens, closes = club.demo_open, club.demo_close
        for _ in range(rng.randint(1, 4)):
            kind = rng.choices(["once", "weekly", "monthly", "daily"], [5, 4, 1, 1])[0]
            start = rng.randint(opens, closes - 3)
            fields = {"start_time": t(start), "end_time": t(min(closes, start + rng.randint(2, 5)) % 24)}
            courts = [rng.choice(club.demo_courts)]
            if kind == "once":
                fields.update(starts_on=today + rng.randint(-10, 40) * DAY, reason=rng.choice(ONE_OFF))
                if fields["reason"] == "Public holiday" or rng.random() < 0.2:
                    fields.update(start_time=t(opens), end_time=t(closes % 24))  # all day
                if fields["reason"] in ALL_COURTS:
                    courts = club.demo_courts
            else:
                fields.update(starts_on=today - (PAST_DAYS + rng.randrange(28)) * DAY, repeat=kind,
                              reason=rng.choice(REPEATING[kind]))
                if kind == "daily":
                    fields.update(start_time=t(13), end_time=t(14))
                if kind == "weekly" and rng.random() < 0.4:
                    fields["repeat_until"] = today + rng.randint(10, 90) * DAY
            rows += [CourtBlockout(court=c, **fields) for c in courts]
        CourtBlockout.objects.bulk_create(rows)

    def offers(self, club, players, rich):
        """DSC: 0 to 5 offers of different kinds; every club in the first city has all of them."""
        rng, now = self.rng, self.now
        kinds = list(OFFERS) if rich else rng.sample(list(OFFERS), rng.choices([0, 1, 2, 3, 4], [2, 4, 3, 2, 1])[0])
        rows = []
        for kind in kinds:
            pct = rng.choice([5, 10, 12, 15, 20, 25, 30])
            offer = Discount(club=club, percent_off=pct, starts_at=now - rng.randint(1, 30) * DAY,
                             ends_at=now + rng.randint(20, 75) * DAY)
            fill = {"p": pct}
            if kind == "regulars":
                offer.min_bookings = fill["n"] = rng.choice([3, 5, 8, 10])
            elif kind == "court":
                offer.court, offer.percent_off = rng.choice(club.demo_courts), None
                offer.amount_off = self.nice(club.demo_hour * rng.uniform(0.15, 0.4), club.demo_step)
                fill.update(court=offer.court.name, amount=offer.amount_off, cur=club.currency)
            elif kind == "personal":
                offer.user = rng.choice(players)
                fill["first"] = offer.user.full_name.split()[0]
            elif kind == "upcoming":
                offer.starts_at = now + rng.randint(5, 20) * DAY
                offer.ends_at = offer.starts_at + rng.randint(7, 30) * DAY
            offer.message = rng.choice(OFFERS[kind]).format(**fill)
            rows.append(offer)
        Discount.objects.bulk_create(rows)

    # ---- sessions ----

    def court_sessions(self, court, club, players, teachers):
        """Runs of the court's offered slots (AVL-1) outside its closures, never overlapping; busier at peak, at
        weekends, at popular clubs and in the next days."""
        rng, today, zone = self.rng, club_today(club), zoneinfo.ZoneInfo(club.timezone)
        days = [today + n * DAY for n in range(-PAST_DAYS, FUTURE_DAYS + 1)]
        slots, closed = offered_slots(court, days), _closed_ranges(court, days)
        i = 0
        while i < len(slots):
            local = slots[i].starts_at.astimezone(zone)
            ahead = (slots[i].starts_at - self.now) / DAY
            density = (0.14 * club.demo_busy * (1.6 if local.hour >= club.demo_peak else 0.7 if local.hour < 10 else 1)
                       * (1.25 if local.weekday() in club.demo_weekend else 1) * (1 if ahead < 0 else max(0, 1 - ahead / 35)))
            sport = rng.choice(court.demo_sports)
            size = max(1, round(rng.choice(MINUTES[sport.name]) / court.slot_minutes))
            run = slots[i:i + size]
            start, end = run[0].starts_at, run[-1].ends_at
            if (rng.random() < density and len(run) == size and all(a.ends_at == b.starts_at for a, b in zip(run, run[1:]))
                    and not any(start < b and end > a for a, b in closed)
                    and self.on_court(court, club, run, sport, players, teachers, local)):
                i += size
            else:
                i += 1

    def on_court(self, court, club, run, sport, players, teachers, local):
        rng = self.rng
        start, end = run[0].starts_at, run[-1].ends_at
        minutes = int((end - start).total_seconds()) // 60
        session = Session(court=court, sport=sport, kind=PLAY, starts_at=start, ends_at=end, currency=club.currency,
                          price=sum((s.rate.price for s in run), Decimal(0)),
                          status=CANCELLED if rng.random() < club.demo_cancel else CONFIRMED)
        at = local.hour * 60 + local.minute
        free = [c for c in teachers if sport in c.demo_sports and local.weekday() in c.demo_days
                and c.demo_hours[0] * 60 <= at and at + minutes <= c.demo_hours[1] * 60 and self.free([c], start, end)]
        lines = []
        coach = rng.choice(free) if free else None
        if coach and rng.random() < 0.5 * coach.demo_load:  # training, in the coach's days and hours
            session.kind, session.coach = TRAINING, coach
            session.coach_fee = self.fee(coach, minutes, club.currency)
            teams = [x for x in self.teams[coach.pk] if x[0].sport == sport]
            if teams and rng.random() < 0.4:  # BOOK-30
                team, members = rng.choice(teams)
                session.booked_by, session.group = coach, team
                people = {coach: ACCEPTED, **{p: self.answer(start) for p in self.free(members, start, end)}}
            else:  # BOOK-21: a player's request, confirmed on this court
                booker = self.pick(players, sport.name, start, end)
                if booker is None:
                    return False
                session.booked_by = session.coach_fee_payer = booker
                people = {booker: ACCEPTED, coach: None}
        else:  # BOOK-8: the booker, friends for the sport's usual numbers, maybe rentables
            booker = self.pick(players, sport.name, start, end)
            if booker is None:
                return False
            session.booked_by = booker
            friends = self.choose(players, sport.name, rng.randint(*PARTY[sport.name]) - 1, start, end, [booker])
            people = {booker: ACCEPTED, **{p: self.answer(start) for p in friends}}
            options = [e for e, sports in club.demo_rentables if sport.name in sports and e.court_id in (None, court.pk)]
            for e in rng.sample(options, min(len(options), rng.choices([0, 1, 2], [7, 3, 1])[0])):
                q = rng.randint(1, min(e.quantity, len(people)))
                status = (rng.choices(["approved", "declined"], [5, 1]) if start < self.now
                          else rng.choices(["requested", "approved", "declined"], [3, 3, 1]))[0]
                lines.append((e, q, e.rental_price * q, status))
        session.discount, session.discount_amount = best_offer(court, session.booked_by, start, session.price,
                                                               club.currency, Decimal(1))
        self.add(session, people, lines)
        return True

    def coach_week(self, coach, players, zone, first):
        """Training at the coach's own venue on their days and hours, in their currency (BOOK-21 without a court, or
        BOOK-30 for a team), then requests waiting for them (BOOK-20), a few declined."""
        rng = self.rng
        today = self.now.astimezone(zone).date()
        lo, hi = coach.demo_hours
        for n in range(-PAST_DAYS, FUTURE_DAYS + 1):
            day = today + n * DAY
            chance = coach.demo_load * (0.6 if n < 0 else 0.5 * max(0.1, 1 - n / 35))
            minutes = rng.choice(coach.demo_lengths)
            if day.weekday() not in coach.demo_days or rng.random() > chance or (hi - lo) * 60 < minutes:
                continue
            start = datetime.datetime.combine(day, t(0), tzinfo=zone) + datetime.timedelta(
                minutes=rng.randrange(lo * 60, hi * 60 - minutes + 1, 15))
            end = start + datetime.timedelta(minutes=minutes)
            sport = rng.choice(coach.demo_sports)
            if not self.free([coach], start, end):
                continue
            session = Session(kind=TRAINING, status=CANCELLED if rng.random() < 0.06 else CONFIRMED, sport=sport,
                              coach=coach, starts_at=start, ends_at=end, currency=coach.coach_currency, price=0,
                              coach_fee=self.fee(coach, minutes, coach.coach_currency))
            teams = [x for x in self.teams[coach.pk] if x[0].sport == sport]
            if teams and rng.random() < 0.35:
                team, members = rng.choice(teams)
                session.booked_by, session.group = coach, team
                people = {coach: ACCEPTED, **{p: self.answer(start) for p in self.free(members, start, end)}}
            else:
                booker = self.pick(players, sport.name, start, end)
                if booker is None:
                    continue
                session.booked_by = session.coach_fee_payer = booker
                people = {booker: ACCEPTED, coach: None}
            self.add(session, people)

        for k in range(4 if first else rng.choices([0, 1, 2, 3, 4, 5], [2, 3, 3, 2, 1, 1])[0]):
            minutes = rng.choice([45, 60, 60, 90, 120])
            start = datetime.datetime.combine(today + rng.randint(1, 14) * DAY,
                                              t(rng.randint(7, 21), rng.choice([0, 0, 30])), tzinfo=zone)
            end = start + datetime.timedelta(minutes=minutes)
            sport = rng.choice(coach.demo_sports)
            booker = self.pick(players, sport.name, start, end)
            if booker is None:
                continue
            declined = k == 0 if first else rng.random() < 0.2
            self.add(Session(kind=TRAINING, status=CANCELLED if declined else REQUESTED, sport=sport, booked_by=booker,
                             coach=coach, coach_fee_payer=booker if rng.random() < 0.8 else None, starts_at=start,
                             ends_at=end, currency="", price=0), {booker: ACCEPTED})

    # ---- helpers ----

    def fee(self, coach, minutes, currency):
        """FE-4: the coach's rate times the hours, in `currency`; some coaches type a fee of their own."""
        rng = self.rng
        rate = float(coach.coach_rate or 0) or rng.uniform(25, 60) * FX[coach.coach_currency]
        amount = rate * minutes / 60 * FX[currency] / FX[coach.coach_currency]
        return self.nice(amount * (rng.uniform(0.8, 1.15) if rng.random() < 0.2 else 1), SMALL[currency])

    @staticmethod
    def nice(value, step):
        """`value` rounded to a multiple of `step` (5 AED, 0.50 EUR), at least one step."""
        step = Decimal(str(step))
        return max(step, step * round(Decimal(str(value)) / step))

    def add(self, session, people, lines=()):
        """`people`: {user: participant status}; None = busy (the coach) but no participant row."""
        for user in people:
            self.busy[user.pk].append((session.starts_at, session.ends_at))
        self.sessions.append((session, {u: s for u, s in people.items() if s}, lines))

    def free(self, users, start, end):
        return [u for u in users if not any(start < b and end > a for a, b in self.busy[u.pk])]

    def choose(self, players, sport, k, start=None, end=None, exclude=()):
        """Up to `k` players (free then, if a time is given), mostly ones who like `sport`, keen ones more often."""
        pool = [p for p in (self.free(players, start, end) if start else players) if p not in exclude]
        chosen = []
        while pool and len(chosen) < k:
            p = self.rng.choices(pool, [u.demo_activity * (3 if sport in u.demo_sports else 0.3) for u in pool])[0]
            chosen.append(p)
            pool.remove(p)
        return chosen

    def pick(self, players, sport, start, end):
        return next(iter(self.choose(players, sport, 1, start, end)), None)

    def answer(self, start):
        """An invitee's answer: past games were played, upcoming ones are partly still open."""
        if start < self.now:
            return self.rng.choices([ACCEPTED, DECLINED], [12, 1])[0]
        return self.rng.choices([ACCEPTED, INVITED, DECLINED], [6, 3, 1])[0]

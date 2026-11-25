# Seed data (SEED)

**Status: built** (command `seed`, tests in `backend/wellness/tests.py`). A `python manage.py seed` command fills the lookup data. It is safe to run again: it never duplicates rows and never overwrites rows an admin has edited.

**SEED-1.** **Sports:** padel, tennis, basketball, volleyball, football (5-a-side), pickleball, squash, badminton. Created by name if missing. Names stored as: `Padel`, `Tennis`, `Basketball`, `Volleyball`, `Football (5-a-side)`, `Pickleball`, `Squash`, `Badminton`.

**SEED-2.** **Default commission:** if no default row (club and coach both empty) exists for `applies_to = club`, create one: `percent = 10.00`, `min_count = 0`, `effective_from` = today (UTC). The same for `applies_to = coach`. Later changes are made in the admin (COM-4).

**SEED-3.** **Exercises: placeholders.** Created by name if missing, with the body areas below. Each `description` starts with "Placeholder, to be reviewed by the sports expert." `video_url` empty. If an exercise with that name exists, it is left as it is (body areas included). The sports expert's list will replace these through the admin.

| Name | Kind | Areas | Soreness range |
|---|---|---|---|
| Neck side stretch | stretch | neck | 1–6 |
| Chin tucks | mobility | neck | 1–5 |
| Cross-body shoulder stretch | stretch | shoulders | 1–7 |
| Wall slides | mobility | shoulders, upper_back | 1–5 |
| Thread the needle | mobility | upper_back | 1–6 |
| Cat-cow | mobility | upper_back, lower_back, core | 1–7 |
| Child's pose | stretch | lower_back, hips | 1–8 |
| Knee-to-chest stretch | stretch | lower_back, glutes | 1–7 |
| Doorway chest stretch | stretch | chest, shoulders | 1–6 |
| Overhead triceps stretch | stretch | arms | 1–6 |
| Wall biceps stretch | stretch | arms, elbows | 1–6 |
| Wrist flexor stretch | stretch | wrists_hands, elbows | 1–6 |
| Wrist circles | mobility | wrists_hands | 1–4 |
| Dead bug | mobility | core | 1–4 |
| Kneeling hip flexor stretch | stretch | hips, quads | 1–7 |
| 90/90 hip switches | mobility | hips, glutes | 1–5 |
| Figure-four stretch | stretch | glutes, hips | 1–7 |
| Standing quad stretch | stretch | quads, knees | 1–7 |
| Seated hamstring stretch | stretch | hamstrings | 1–7 |
| Leg swings | mobility | hamstrings, hips | 1–4 |
| Heel slides | mobility | knees | 1–5 |
| Wall calf stretch | stretch | calves | 1–7 |
| Ankle circles | mobility | ankles_feet | 1–4 |
| Plantar fascia stretch | stretch | ankles_feet, calves | 1–6 |

Every one of the 16 body areas has at least one exercise. No placeholder covers levels 9–10 (and only child's pose covers 8): severe soreness gets no exercise (WEL-30).

**SEED-4.** **Demo data** (added 2026-11-25; command `seed_demo` in `backend/bookings/management/commands/seed_demo.py`, test `SeedDemoTests` in `backend/bookings/tests.py`). Fills every screen of the app, and only what the screens show: no payments (the scheduler bills the past sessions itself, PAY-10), chat messages, wellness or recordings. It runs `seed` first. Every backend start runs it (`backend/Dockerfile`).

- **Runs once.** If any user with an `@pass-demo.example` email exists, it only sets the demo accounts' password again and stops. Otherwise it builds everything in one transaction.
- **Sign-in.** Every demo account's password is `DEMO_PASSWORD` from `.env`; empty, nobody can sign in as them. `owner@pass-demo.example` owns two clubs in Beirut, `staff@` works at both, `coach@` coaches there with a team and training requests waiting, `player@` has past and upcoming sessions. The others are `first.last@pass-demo.example`.
- **Procedural**, from a fixed random seed, so names and shapes repeat; times are relative to the day it runs.
- **Clubs:** 2 to 3 in each of Beirut (USD), Dubai (AED), Riyadh (SAR), Cairo (EGP), Madrid (EUR) and London (GBP), in the city's time zone, with an address. Each has a main kind of court (padel, tennis, 5-a-side pitch, basketball and volleyball hall, pickleball and badminton, squash) that names it, 2 to 4 of those courts and up to 2 others; a court after the first is sometimes not bookable.
- **Courts:** a description, the kind's sports and slot length (30 to 90 minutes). Prices per slot from the city's price of an hour: weekdays off-peak to 17:00, then peak (×1.4) to 22:00, 23:00 or midnight; weekends one window (×1.2), and some courts are closed at weekends.
- **Equipment:** 3 to 5 free amenities, one court's own amenity, and rentables for the sports played there (a quantity of 1 belongs to one court).
- **Closures:** one weekly (the first two opening hours on one weekday) and one one-off (10:00–13:00) per club.
- **Offers:** an "opening season" percentage, a regulars' 10% after 3 bookings, and an amount off one court; every club in the first city has all three, the others some.
- **People:** per city an owner per club, a staff member per club, 3 to 5 coaches (bio, a USD rate or none, 1 to 3 clubs there, every club at least one) and 30 to 45 players. About half the coaches have a team (TEAM-20) of 4 to 7 players.
- **Sessions,** from 14 days ago to 30 days ahead, busier in the next days: court bookings on runs of offered slots outside closures (BOOK-8: friends invited or accepted, sometimes a rentable that is waiting, approved or declined; the best offer applied, DSC-1), training on courts (a player's confirmed request, BOOK-21, or team training, BOOK-30), training at the coach's own venue in USD, and 1 to 3 training requests waiting for each coach plus one declined. About 8% are cancelled. Nobody is in two sessions at once.

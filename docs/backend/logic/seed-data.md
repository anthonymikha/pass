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

- **Rebuilt when the script changes.** The data carries the script's version (the first 12 hex digits of the file's SHA-256, kept as an inactive account `seed-<version>@pass-demo.example`). If that account exists, the run only sets the demo accounts' password again. Otherwise it **deletes everything except the real accounts** (with their devices and sign-in tokens) **and the lookup data** (sports, default commissions, exercises): every club, session, payment, recording, chat, team, friendship, blockout and wellness log, and every `@pass-demo.example` account. Then it builds a new world in the same transaction. A change to the script therefore wipes the data on the next deploy.
- **Sign-in.** Every demo account's password is `DEMO_PASSWORD` from `.env`; empty, nobody can sign in as them. `owner@pass-demo.example` owns two clubs in Beirut, `staff@` works at both, `coach@` coaches at both with a team and training requests waiting, `player@` plays a lot. The others are `first.last@pass-demo.example`, named from the city's pool (Arabic, Spanish or English names, a quarter from another pool).
- **Random**, seeded from the script's version, so each version builds the same world; times are relative to the day it runs. Nothing is shared between two clubs or two coaches except the lists the pieces are drawn from.
- **Clubs:** 2 to 4 in each of Beirut (USD), Dubai (AED), Riyadh (SAR), Cairo (EGP), Madrid (EUR) and London (GBP), in the city's time zone and with its weekend (Friday and Saturday in Riyadh and Cairo). Each club has its own price level (0.75 to 1.45 times the city's price), rounding step (5 or 10 AED, 0.50 EUR), opening hours, start of the peak (16:00 to 18:00) and how busy and how often cancelled it is. Some owners have two clubs, some staff work at two.
- **Prices:** weekdays off-peak, then peak (1.15 to 1.6 times), at some clubs an early-bird window before 09:00 or a cheaper late window after 22:00; weekends one price, at some clubs cheaper in the afternoon. A court's own factor (0.9 to 1.25) and its kind (a 5-a-side pitch costs more than padel, squash less) change its price. Some courts are closed one weekday, or at weekends.
- **Courts:** a main kind (padel, tennis, 5-a-side pitch, basketball and volleyball hall, pickleball and badminton, squash) that names the club, 1 to 5 of them and up to 3 others; named by kind ("Padel 2"), by number ("Court 4") or by name ("Center Court"); a description put together from the kind's surfaces, walls, roof and extras; slot lengths from 30 to 90 minutes; sometimes not bookable.
- **Equipment:** 2 to 7 free amenities with plausible quantities, up to 2 amenities of one court, and some of the rentables of each sport played there, at the club's prices (a ball machine belongs to one court).
- **Closures:** 1 to 4 per club: one-offs (a public holiday, tournament or private event on every court, some all day), weekly ones (some ending), monthly ones, a daily midday break.
- **Offers:** 0 to 5 per club of these kinds: a percentage off, a regulars' offer after 3 to 10 bookings, an amount off one court, a personal offer to one player, an upcoming week; every club in the first city has all five.
- **Coaches:** 4 to 8 per city, more if a club would have no coach for its sports. Each has a main sport and maybe 1 or 2 related ones (racquet or team sports), 0 to 3 clubs offering them, a rate in USD or the city's currency (or none), working days and hours, usual session lengths, how busy they are, and a bio made of sentences picked and filled for them (never the same twice; some have none). 0 to 2 teams each, in their sports, with players who like that sport.
- **Players:** 30 to 50 per city, each with favourite sports and how much they play.
- **Sessions,** from 14 days ago to 30 days ahead: court bookings on runs of offered slots outside closures, busier at peak, at weekends, at busy clubs and in the next days; as many players as the sport needs (2 for squash, up to 12 for volleyball), invited, accepted or declined; sometimes rentables waiting, approved or declined; the best offer applied (DSC-1). Training on a court only on the coach's days and hours (a player's confirmed request, BOOK-21, or team training, BOOK-30); training at the coach's own venue in the coach's currency, at quarter hours; 0 to 5 training requests per coach, some declined. Some cancelled. Nobody is in two sessions at once.

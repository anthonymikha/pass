# Seed data (SEED)

**Status: planned.** A `python manage.py seed` command fills the lookup data. It is safe to run again: it never duplicates rows and never overwrites rows an admin has edited.

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

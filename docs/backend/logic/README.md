# Business logic

**This folder is the specification.** Every business rule the backend implements is written here first, reviewed by the owner, and then built from these pages and nothing else. If code and these pages disagree, the code is wrong. If a rule is missing or unclear, the page is fixed first, and then the code.

Model pages ([models/](../models/)) say what each field means. Flow pages ([flows/](../flows/)) tell the user journeys in order. These pages hold the rules.

## Pages

| Page | Prefix | Covers |
|---|---|---|
| [conventions.md](conventions.md) | `GEN` | Errors, repeated requests, time zones, pagination, money rounding. Read this first |
| [access-and-roles.md](access-and-roles.md) | `ACC` | Who is who, who may see and do what, shadow players, finding users and coaches |
| [clubs-and-courts.md](clubs-and-courts.md) | `CLUB` | What owners configure: clubs, currencies, courts, rates, closures, equipment, overrides, discount offers, members, public search |
| [court-availability.md](court-availability.md) | `AVL` | Free slots for a court, free time for a user or a group |
| [pricing-and-currency.md](pricing-and-currency.md) | `PRC` | Accepted currencies, conversion, overrides, rounding, rental prices |
| [discounts.md](discounts.md) | `DSC` | Which offer applies, how much it takes off, one-off session discounts |
| [booking.md](booking.md) | `BOOK` | Booking a court, training requests, team training, invites, rentals, cancelling, session cards |
| [check-in-and-payments.md](check-in-and-payments.md) | `PAY` | Check-in, creating due payments, splitting coach fees, marking paid |
| [commission.md](commission.md) | `COM` | The platform's cut and settlement |
| [owner-reports.md](owner-reports.md) | `RPT` | Schedule, dues, revenue, customers, repeat rate, attendance, coach earnings |
| [teams-and-coaching.md](teams-and-coaching.md) | `TEAM` | Friends, blocking, coaching links, block-out times, play groups and teams, changing coach |
| [wellness.md](wellness.md) | `WEL` | RPE, soreness, sleep, exercise suggestions and assignments, achievements |
| [recordings.md](recordings.md) | `REC` | Storage, upload, playback, tags, avatars |
| [chat.md](chat.md) | `CHAT` | Direct, group and inquiry chats, polling, unread |
| [notifications.md](notifications.md) | `NOTE` | Devices, push sending, triggers, the scheduler |
| [seed-data.md](seed-data.md) | `SEED` | Sports, default commission, placeholder exercises |

## How to read a rule

- Each rule has a stable id such as `BOOK-3`. Ids are never reused or renumbered. A removed rule keeps its number with the text "Removed".
- Tests name the ids they prove in their docstring, e.g. `"""BOOK-3, BOOK-4: second player cannot take the same slot."""`.
- Code that implements a rule names its id in a short comment where the rule is enforced.
- **Status** on each page: `planned` (not built), `built` (endpoints and tests exist). A rule added during the build carries the note *decided during build* with the reason.

## Schema changes these pages require

Three changes to schema v5, all approved by the owner on 2026-11-16, all built (migrations `accounts/0002`, `chat/0002`, `bookings/0002`):

| Table | Change | Rule |
|---|---|---|
| `devices` | New table: `user`, `token` (unique), `platform` (`ios` / `android` / `web`), `created_at` | NOTE-1 |
| `chats` | New column `club_last_read_at` (nullable): the club side's shared read marker on inquiry chats | CHAT-11 |
| `session_participants` | New column `rpe_reminded_at` (nullable): when the RPE reminder was sent, so it is sent once | NOTE-9 |

`rpe_reminded_at` was added at review instead of a stateless reminder, which would miss sessions while the scheduler is down.

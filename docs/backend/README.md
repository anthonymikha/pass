# Backend architecture

Django 6.1 with Django REST Framework, Postgres in Docker, SQLite as a local fallback. Code lives in `backend/`.

## Apps and their order

| # | App | Owns | Model docs |
|---|---|---|---|
| 1 | `accounts` | Login, profiles and body metrics, shadow players, friends, 1:1 coaching links, personal availability, the shared block-out shape | [accounts](models/accounts.md) |
| 2 | `venues` | Everything an owner configures: clubs, courts, hours, closures, prices, equipment, offers, club memberships (coaches, staff, players) | [venues](models/venues.md) |
| 3 | `teams` | Play groups and teams, invites, join requests | [teams](models/teams.md) |
| 4 | `bookings` | Sessions, attendance, RPE, rentals, recordings and tags | [bookings](models/bookings.md) |
| 5 | `billing` | Payment records, commission, settlement | [billing](models/billing.md) |
| 6 | `wellness` | Soreness, sleep, exercises, achievements | [wellness](models/wellness.md) |
| 7 | `chat` | Direct, group and inquiry chats | [chat](models/chat.md) |

**Dependency rule:** a model may only have foreign keys to apps earlier in this list. `billing` can point at `bookings`; `bookings` can never point at `billing`.

```
accounts <- venues <- teams <- bookings <- billing
                                  ^------- wellness
                                  ^------- chat
```

## Where code goes

| Kind of code | Location | Rule |
|---|---|---|
| Data and constraints | `<app>/models.py` | No business logic in models |
| Business logic | `<app>/services.py` | Plain functions, e.g. `bookings.services.book_session()` |
| Input and output shapes | `<app>/serializers.py` | Validate everything from the client here |
| Endpoints | `<app>/views.py`, `<app>/urls.py` | Thin: parse, call a service, respond |
| Workflow tests | `<app>/tests.py` | Drive real endpoints with `APITestCase` |
| Schema constraint tests | `backend/tests.py` | |

Later apps may read earlier apps' data freely (for example `wellness` reads RPE from `bookings`). One later app writes an earlier app's rows: `wellness` stores RPE on `session_participants` (WEL-3), because the RPE and the post-session soreness rows are written in one transaction. *Decided during build (2026-11-16).*

### The allowed "downward" calls

An event in an earlier app sometimes has a consequence owned by a later app. These calls are allowed, made explicitly inside the same database transaction:

1. Booker checks in → `billing.services.record_payments(session)` (PAY-4)
2. Group session confirmed → `chat.services.post_session_card(session)` (BOOK-60)
3. Group created, membership changed, coach changed or group deleted (TEAM-20, TEAM-28 to TEAM-30) → `chat.services` functions that keep the group chat in step. *Decided during build (2026-11-16): the logic pages require it and `teams` comes before `chat`.*

A few reads the other way are allowed, through reverse relations only, never writes. *Decided during build (2026-11-16): the logic pages require them.*

| Earlier app | Reads | For |
|---|---|---|
| `bookings` | whether a session already has payments (`session.payments`) | DSC-12, BOOK-40, BOOK-50 |
| `venues` | a court's sessions (`court.sessions`) | CLUB-10 (court in use), CLUB-16 (closure conflicts) |
| `venues` | an item's rentals (`equipment.rentals`) | CLUB-19 (equipment in use) |

Push notifications (NOTE-1 to NOTE-14) live in `accounts` (the `devices` table and `accounts.services.notify()`), the first app, so every app can send a push without a downward call. *Decided during build (2026-11-16).*

No Django signals. If this list grows past a handful, switch to signals.

## Model conventions

- Every model has `id` and `created_at`.
- Every model sets `Meta.db_table` to a plain name (`sessions`, not `bookings_session`).
- Value sets are `TextChoices`, stored as text. No database enums.
- "Exactly one of A or B" is enforced by a check constraint (see `price_overrides`, `payments`).
- An empty foreign key often carries meaning (shared equipment, default commission, system message). Each case is listed in the model pages.

| Kind of value | Type |
|---|---|
| Money | `Decimal(12, 3)` |
| Currency | 3-letter ISO 4217 code, uppercase |
| Exchange rate | `Decimal(18, 6)` |
| Percent | `Decimal(5, 2)` |
| Weekday | 0 = Monday … 6 = Sunday |
| Timestamps | UTC in the database; convert with the club's or user's `timezone` |

## Deleting rows

| Behaviour | Applies to |
|---|---|
| **Blocked** (`PROTECT`) | Anything with financial or historical value: a user, club or court with sessions or payments cannot be deleted |
| **Deleted with parent** (`CASCADE`) | Pure children: memberships, participants, rates, currencies, overrides, tags, personal logs |
| **Emptied** (`SET_NULL`) | Optional references whose absence changes nothing |

Where an empty value has a meaning, the row is deleted with its parent rather than emptied, so it cannot silently change meaning.

## Things that are computed, never stored

Revenue, customer and repeat-customer rates, attendance, recovery level, group availability, suggested session times, and whether a video is unlocked. Each is a query over the tables above.

## Database independence

Postgres is the target, but the code uses no Postgres-only features. One consequence: double-booking is prevented in code (lock the court row, then check for overlap) rather than by a database exclusion constraint. See [booking-and-payment](flows/booking-and-payment.md).

## Running

See the root [README](../../README.md) for Docker and local commands.

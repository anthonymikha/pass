# Court availability and personal availability (AVL)

**Status: partly built.** Built: AVL-1 to AVL-12 (`backend/bookings/`, [API](../api/bookings.md)). Planned: AVL-20 to AVL-25. Which slots of a court can be booked, and when a user or a group is free.

## Court slots

**AVL-1.** A court's **offered slots** on a local date D (club timezone) come from its `court_rates` rows with `weekday = D.weekday()`. Each row is a window from `D + start_time` to `D + end_time`, where `end_time = 00:00` means `D + 1 day, 00:00` (GEN-11).

**AVL-2.** Each window is cut into slots of `court.slot_minutes`, starting at the window start: `[start, start + n)`, `[start + n, start + 2n)`, … A slot is offered only if it ends at or before the window end. A leftover shorter than one slot is not offered.

Example: window 09:00–17:00, `slot_minutes = 90`: slots 09:00, 10:30, 12:00, 13:30, 15:00 (ending 16:30). 16:30–17:00 is not offered.

**AVL-3.** Slots never cross midnight, because windows never do (GEN-11). A **booking** can cross midnight by taking a run of slots from two dates (BOOK-7).

**AVL-4.** Each slot belongs to the rate row whose window produced it; that row sets its price (PRC-4).

**AVL-5.** A slot is **free** when all of these hold:
1. It does not overlap an occurrence of any of the court's `court_blockouts` (AVL-8).
2. It does not overlap any session on that court whose `status` is not `cancelled`.
3. It starts after now.
4. Its local date is no later than today (club timezone) + 60 days.

Two time ranges overlap when `a.start < b.end and a.end > b.start`. Touching ranges (one ends exactly when the other starts) do not overlap.

**AVL-6.** Slots are built in the club's local wall-clock time and then converted to UTC (GEN-10). A slot whose local start or end does not exist (the skipped hour when clocks go forward), or whose real length in UTC is not exactly `slot_minutes`, is not offered. In the hour that repeats when clocks go back, the first occurrence is used (`fold = 0`) and slots whose UTC length comes out wrong are not offered.

**AVL-7.** An inactive court (`is_active = false`) has no offered slots.

## Closures

**AVL-8.** A court block-out B **occurs** on local date X when `B.occurs_on(X)` is true:
- `X` is not before `starts_on`, and not after `repeat_until` when that is set;
- `none`: `X = starts_on`; `daily`: every day; `weekly`: same weekday as `starts_on`; `monthly`: same day of the month as `starts_on`. A monthly block-out starting on the 29th, 30th or 31st does not occur in months without that day (no moving to the last day).

On a date where it occurs, it blocks `[X + start_time, X + end_time)` local, with `end_time = 00:00` meaning midnight at the end of X. A whole-day closure is `00:00`–`00:00`.

Example: monthly from 2027-01-31: occurs 31 Jan, 31 Mar, 31 May, 31 Jul, 31 Aug, 31 Oct, 31 Dec. Not in February, April, June, September or November.

## The free-slot endpoint

**AVL-10.** Who may: anyone, without signing in (it is part of public court detail). Input: court id, local `date`, optional `currency` (default: the club's base currency).

**AVL-11.** Returns the court's offered slots that are free on that date, in time order, each with `starts_at`, `ends_at` (UTC) and `price` in the requested currency (PRC-4). Not paginated. Discounts are not applied here; they depend on the booker (DSC-1) and are shown when the booking is quoted (BOOK-6).

**AVL-12.** Errors: unknown or inactive court `404`; currency not accepted `400 currency_not_accepted`; `date` before today or more than 60 days ahead `400 outside_horizon`.

## Personal and group availability

**AVL-20.** A user U is **busy** at an instant when any of these covers it:
1. an occurrence of one of U's `user_blockouts`, built as in AVL-8 but in **U's** timezone;
2. a `confirmed` session where U is an accepted participant, the booker, or the session coach. Training requests (`requested`) do not make anyone busy.

U is **free** at every other instant.

**AVL-21.** A group is free when every active member is free (shadow players included: they have no block-outs, but they have sessions). A group with no active members is free at every instant.

**AVL-22.** Who may ask:
- for a user: the user themselves, or a coach about one of the coach's players (ACC-1);
- for a group: an active member or a group manager.

Anyone else: `404`.

**AVL-23.** Input: `from`, `to` (instants, `to` after `from`, at most 14 days apart), optional `min_minutes` (default 30, 5–1440). Output: the free intervals inside `[from, to)` as `starts_at`/`ends_at` pairs, merged where they touch, keeping only those at least `min_minutes` long, in time order. Not paginated.

**AVL-24.** Errors: `to` not after `from`, or more than 14 days apart: `400 bad_range`.

**AVL-25.** Personal availability ignores courts. A group that wants to play then picks a court and books a free slot inside a common free interval (BOOK-10).

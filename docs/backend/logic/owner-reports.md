# Owner and coach reports (RPT)

**Status: planned.** Read-only views, computed on request, never stored. Periods are given as local dates `from` and `to` (both included) in the club's timezone; they cover `from 00:00` to `to + 1 day 00:00` local. At most 366 days; otherwise `400 bad_range`.

**RPT-1.** **Schedule.** Who may: the club side. For one court or all the club's courts, the sessions that overlap the period and are not cancelled, ordered by `starts_at`, each with: court, sport, kind, status as shown (BOOK-55), `starts_at`, `ends_at`, booker (`id`, `full_name`), session coach, group name, accepted participant count, rentals with status. Plus the court closures occurring in the period (AVL-8) as `starts_at`/`ends_at`/`reason`. Not paginated.

**RPT-2.** **Due list.** Who may: the club side. The club's payments with `paid_at` empty: session, payer (`id`, `full_name`), amount, currency, created_at; and totals per currency. No period filter.

**RPT-3.** **Revenue.** Who may: the club owner. Payments to the club with `paid_at` inside the period, grouped by currency: `gross = Σ amount`, `fees = Σ platform_fee`, `net = gross − fees`. Plus, per currency, `owed_to_platform` = Σ `platform_fee` over all the club's paid payments with `settled_at` empty (any date). Due payments are not revenue.

**RPT-4.** **Customers.** Who may: the club owner. The distinct bookers of the club's non-cancelled sessions whose `starts_at` is inside the period: `customers` (count) and the list (`id`, `full_name`, session count in the period), sorted by session count descending, then name.

**RPT-5.** **Repeat-customer rate** for the same period: customers with 2 or more such sessions ÷ customers × 100, rounded half-up to 2 decimals. No customers: `null`.

**RPT-6.** **Attendance.** Who may: the club side for sessions on its courts; the session coach for sessions they coached. Per session: accepted participants, how many checked in, the no-shows (accepted, not checked in, session ended). Before `ends_at`, nobody is a no-show yet.

**RPT-7.** **Coach earnings.** Who may: a coach, for themselves. Same as RPT-3 for payments where `coach` is the caller, plus their own due list as in RPT-2.

**RPT-8.** **Coach player history.** Who may: a coach. For one of the coach's players (ACC-1): the sessions they coached that the player took part in, with `checked_in_at`, `rpe`, `rpe_minutes`, and training load `rpe × rpe_minutes` (empty when RPE was not logged). Ordered by `starts_at`, newest first; paginated.

## Example

Hoops, January 2027 (`from = 2027-01-01`, `to = 2027-01-31`): sessions booked by Rana ×3, Ali ×1, Maya ×2. Customers 3; repeat customers 2 (Rana, Maya); rate 2 ÷ 3 × 100 = 66.666… → **66.67**.

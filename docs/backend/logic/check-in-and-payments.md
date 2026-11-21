# Check-in and payments (PAY)

**Status: built, except the changes from the owner's review of 2026-11-20, which are planned** (marked *review 2026-11-20*: PAY-20, PAY-21, PAY-23 to PAY-27). The changes from the review of 2026-11-17 (marked *review 2026-11-17*: PAY-2, PAY-4, PAY-6 to PAY-16, PAY-21, PAY-25) are built (2026-11-21). Check-in in `backend/bookings/`, payments in `backend/billing/`; API pages [bookings](../api/bookings.md), [billing](../api/billing.md). Attendance, how each fee is paid, and the payment rows that record money owed. There is no payment gateway: money changes hands at the court, and the payee ticks it off.

## Check-in

**PAY-1.** A participant row can be checked in when: the session is `confirmed`; the row's status is `accepted`; and now is between `starts_at − 30 minutes` and `ends_at` (both included), except for the late check-in of PAY-7.

**PAY-2.** Who may check in a row (*review 2026-11-17*: attendance decides who pays, PAY-11 and PAY-12, so the people running the session can mark it and a player cannot dodge a share by not tapping check-in):

| Row | Who |
|---|---|
| their own | the participant |
| any accepted participant's | the booker; the session coach; the club side of the court's club (PAY-3) |
| a shadow player's | also the shadow player's managing coach |

**PAY-3.** The club side may check people in only on sessions on their club's courts (ACC-6).

**PAY-4.** Steps, in one transaction:
1. Lock the session row (`select_for_update`).
2. If the row already has `checked_in_at`: change nothing and return it (GEN-5).
3. Set `checked_in_at` = now.

Checking in creates no payments; billing does, after the session (PAY-10). *Review 2026-11-17: before, the booker's check-in created the payments.*

**PAY-5.** Errors: session not visible `404`; caller not allowed for this row `403`; outside the window `400 checkin_closed`; row not `accepted` `400 not_accepted`; session not `confirmed` `400 invalid_status`.

**PAY-6.** A check-in is never undone, by anyone. An **attendee** is an accepted participant with `checked_in_at` set. A **no-show** is an accepted participant with no `checked_in_at` once check-in has closed (PAY-7); nothing is written, it is computed (RPT-6). A no-show owes nothing (PAY-16).

**PAY-7.** **Late check-in** (*review 2026-11-17*). After `ends_at`, the booker, the session coach, the club side (PAY-3) and a shadow player's managing coach may still check in any accepted row until `ends_at + 24 hours` (included), for someone who forgot. A participant checks themselves in only until `ends_at`. Anything later: `400 checkin_closed`.

**PAY-8.** **The first check-in freezes the session** (*review 2026-11-17*). Once any participant has checked in, the session can no longer be cancelled (BOOK-50), its rentals can no longer be decided (BOOK-40) and its one-off discount can no longer be set (DSC-12). Error: `400 already_payable`.

## How each fee is paid

**PAY-9.** *Review 2026-11-17.* Each fee of a session is either **paid in full** by one person or **split** among the attendees. The booker chooses when booking (BOOK-7, BOOK-20, BOOK-30, BOOK-31); the choice is not changed afterwards (like rentals, BOOK-42).
- Court fee: `court_fee_split` false = paid in full by the booker; true = split.
- Coach fee: `coach_fee_payer` set = paid in full by that person; empty = split.

## Billing (creating payments)

**PAY-10.** **Billing** (*review 2026-11-17*). Each scheduler tick (NOTE-33) bills every session that is `confirmed`, has `ends_at + 24 hours ≤ now` (check-in has closed, PAY-7) and has `billed_at` empty. Per session, in one transaction: lock the session row; if `billed_at` is now set, stop; set `billed_at` = now; if the session has at least one attendee, create the rows of PAY-11 and PAY-12, each with `currency` = the session currency, `platform_fee` from PAY-14, `method` empty, `paid_at` empty, `settled_at` empty. A session with no attendee is billed with no rows: nothing is owed (there are no no-show fees, BOOK-51). Payments therefore appear in the due list a day after the session ends. *Decided during build (2026-11-21), so the switch from the old rule bills nothing twice and nothing late:* the migration that adds `billed_at` sets it, for a session that already has payments (billed at the booker's check-in), to its first payment's `created_at`; and for a `confirmed` session with no payments whose `ends_at + 24 hours` had already passed (nothing was owed under the old rule) to the migration time, creating no rows. Sessions still inside the window are billed by the tick under this rule. After the transaction commits, each payer is notified of each row they owe (`payment_due`, NOTE-33, *review 2026-11-20*).

**PAY-11.** **Court fee** (only if the session has a court). Amount = `price − discount_amount + sum of approved rental prices`.
- Paid in full: one row, payer = booker, payee = the court's club.
- Split: the payers are the attendees except the session coach; shadow players included (the club collects from the parent). Shares by PAY-13. If there are no payers (only the session coach attended), the booker pays it in full; the club side may waive it (PAY-25).

**PAY-12.** **Coach fee** (only if `coach_fee > 0`). Payee = the session coach.
- Paid in full: one row, payer = `coach_fee_payer`, amount = `coach_fee`. Owed whenever the session has at least one attendee, whether or not the payer attended; when the payer did not attend, the coach may waive it (PAY-25).
- Split: the payers are the attendees except the session coach; shadow players included (the coach collects from the parent). Shares by PAY-13. If there are no payers, no coach-fee row is created. *Review 2026-11-17: attendance decides; group membership is no longer checked.*

**PAY-13.** **Splitting an amount** among `n` payers, with minor unit `u` (GEN-15). Order the payers by participant row `id`, ascending:
- `share = amount ÷ n`, rounded **down** to `u`;
- `remainder = amount − share × n`;
- the first payer pays `share + remainder`, every other payer pays `share`.

The booker's row is created first, so a booker who is a payer takes the remainder.

**PAY-14.** `platform_fee = round_money(amount × percent / 100, currency)`, where `percent` comes from the commission lookup (COM-1) for that row's payee on the billing date (UTC).

**PAY-15.** A row whose amount would be 0 is not created (a free court, a fully discounted session, a zero coach fee).

**PAY-16.** *Changed at review 2026-11-17:* a no-show owes no share. (Before: every accepted participant owed a share, attending or not.)

## Marking paid

**PAY-20.** **Mark received** (the payee's tick; "mark paid" before *review 2026-11-20*). Who may: for a club payment, the club side of that club; for a coach payment, that coach. The payer never (the payer has their own tick, PAY-26). Effect: `method = offline`, `paid_at` = now; `payer_marked_at` is left as it is. Allowed while the payment is due; waived: `400 already_waived` (move it back to due first, PAY-21). Already received: no change (GEN-5). Only this tick makes a payment **paid**: due lists, revenue and commission (RPT-2, RPT-3, COM-11) look at `paid_at` alone. The payee may receive a payment the payer never declared.

**PAY-21.** **Back to due** (undo a mistake). Same people. Allowed only while `settled_at` is empty. Effect: `method` and `paid_at` emptied; `payer_marked_at` is left as it is. A waived payment comes back to due the same way, `waived_at` emptied (PAY-25). Already due: no change. Settled: `400 already_settled`.

**PAY-22.** Payments are never deleted or edited otherwise. Disputes are not handled in the app.

**PAY-23.** A payer sees their own payment rows (what they owe and what they paid); a payee side sees rows where they are the payee. Others: `404`. Both sides see both ticks: `payer_marked_at` and `paid_at` (*review 2026-11-20*). When the payer declared and the payee has not received, the app shows both and does nothing else; disputes stay outside the app (PAY-22).

**PAY-24.** *Decided during build (2026-11-16):* check-in checks, in order: visibility (`404`), who may (`403`, PAY-2), then inside the lock an already checked-in row returns `200` unchanged (GEN-5) before `invalid_status`, `not_accepted` and `checkin_closed`. The payer marking their own payment is `403` (they can see it); anyone else `404`. Mark paid and back to due return `200` on a repeat.

**PAY-25.** **Waive** (*review 2026-11-17*). Who may: the same people as PAY-20 (the payee side). The payee gives up a due payment, typically one owed by someone who did not attend (PAY-11, PAY-12). Effect: `waived_at` = now. Allowed only while the payment is due, whether or not the payer declared it (*review 2026-11-20*); paid: `400 already_paid` (move it back to due first, PAY-21). Already waived: no change (GEN-5). A waived payment is not owed, is not revenue, and carries no platform fee owed (COM-11 counts paid payments only).

**PAY-26.** **Declare paid** (the payer's tick, *review 2026-11-20*). Who may: the payment's payer. Not for a shadow player's rows: they never sign in, and the payee simply receives (PAY-20). Allowed while `paid_at` and `waived_at` are empty; received: `400 already_paid`; waived: `400 already_waived`. Effect: `payer_marked_at` = now. Notifies the payee side (`payment_marked`, NOTE-20): for a club payment the club owner and the club's active staff, for a coach payment the coach. Already declared: no change and no second push (GEN-5). A declared payment is still **due**: it is a claim, not a receipt.

**PAY-27.** **Undo declare.** Who may: the payer. Allowed while `paid_at` is empty; received: `400 already_paid`. Effect: `payer_marked_at` emptied. Not declared: no change (GEN-5).

**PAY-28.** *Decided during build (2026-11-21), codes PAY-25 leaves open:* waiving answers like marking received (PAY-24): the payer gets `403` (they can see the row), anyone else `404`; a repeat returns `200` with the first `waived_at`. The ticks are `POST /api/payments/<id>/mark-paid/` (received), `mark-due/` (back to due) and `waive/`.

State of a payment row:

| From | To | Who | When |
|---|---|---|---|
| (new) | due | system | billing, a day after the session ends (PAY-10) |
| due | due, declared | payer | the payer says they paid (PAY-26); undone by the payer (PAY-27) |
| due (declared or not) | paid | payee side | money received (PAY-20) |
| paid | due | payee side | correcting a mistake, before settlement (PAY-21) |
| due (declared or not) | waived | payee side | the payee gives it up (PAY-25) |
| waived | due | payee side | correcting a mistake (PAY-21) |
| paid | settled | platform admin (Django admin) | the platform's cut is settled with the payee (COM-10) |

## Worked examples

**Court booking, paid in full.** The session from [discounts](discounts.md#worked-example): EUR, `price = 111.17`, `discount_amount = 11.12`, shooting machine approved at 13.85. Club commission 10%. Rana checks in; the next day the session is billed.

- Court fee: 111.17 − 11.12 + 13.85 = **113.90 EUR**, payer Rana, payee Hoops.
- Platform fee: 113.90 × 10 / 100 = 11.39 → **11.39 EUR**. Hoops keeps 102.51.

**Same booking, court fee split.** Rana (row 20) booked with `court_fee_split` and invited Ali (21), Maya (22) and Omar (23). All four accepted; Omar did not come. Attendees: Rana, Ali, Maya, so `n = 3`, `u = 0.01`.

- 113.90 ÷ 3 = 37.9666… → share **37.96**; remainder 113.90 − 113.88 = **0.02**.
- Rana **37.98**, Ali **37.96**, Maya **37.96**. Omar owes nothing.
- Platform fees: 3.798 → **3.80**; 3.796 → **3.80** (twice).

**Team training, coach fee split.** Coach Sami books the U12 team at Hoops in **LBP**, court price 4 475 000, no offer, court fee paid in full (`court_fee_split` false), `coach_fee = 250 000` split (`coach_fee_payer` empty). Accepted participants: Sami (row 40), Kid A (shadow, row 41), Maya (row 42), Omar (row 43). Coach commission 10%, club 10%. Sami checks in himself, Kid A and Maya; Omar does not come.

- Court fee: payer Sami, payee Hoops, **4 475 000**, platform fee 447 500.
- Coach fee payers (Sami excluded, Omar a no-show): rows 41 and 42, so `n = 2`, `u = 1`: Kid A **125 000**, Maya **125 000**; platform fee 12 500 each.

Had Omar come too: `n = 3`, 250 000 ÷ 3 = 83 333.33… → share **83 333**, remainder **1**: Kid A **83 334**, Maya **83 333**, Omar **83 333**; platform fees 8 333.4 → **8 333** and 8 333.3 → **8 333**.

Same three-way split in USD with `coach_fee = 100.00`: 100 ÷ 3 = 33.333… → 33.33, remainder 0.01: **33.34, 33.33, 33.33**.

## Edge cases

- **Two devices check the same row in at once:** one check-in (PAY-4 step 2). **Two ticks bill at once:** one set of rows (PAY-10, `billed_at` under the lock).
- **A member accepted, left the team, and still came:** pays a split share; attendance decides (PAY-12).
- **The booker is the coach and also a participant:** owes the court fee when it is paid in full, never a share of their own coach fee or of a split court fee.
- **Split court fee, only the coach attended:** the booker pays the court in full (PAY-11).
- **Nobody attended:** no payments; the club and the coach get nothing (BOOK-51).
- **Session currency LBP:** shares and fees are whole pounds (GEN-15).
- **Discount changed after someone checked in:** impossible (PAY-8).
- **Payer says paid, payee says not:** the row stays due with `payer_marked_at` set; both see it (PAY-23).
- **Payer deleted their account:** their rows stay due, payer shown as "Deleted user"; the payee may still receive or waive them (ACC-34).
- **Coach deleted their account:** payments due to them stay due; nobody can mark them any more (ACC-34). Paid ones can still be settled by a platform admin (COM-10).

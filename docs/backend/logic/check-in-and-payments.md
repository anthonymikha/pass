# Check-in and payments (PAY)

**Status: built** (check-in in `backend/bookings/`, payments in `backend/billing/`; API pages [bookings](../api/bookings.md), [billing](../api/billing.md)). Attendance, and the payment rows that record money owed. There is no payment gateway: money changes hands at the court, and the payee ticks it off.

## Check-in

**PAY-1.** A participant row can be checked in when: the session is `confirmed`; the row's status is `accepted`; and now is between `starts_at − 30 minutes` and `ends_at` (both included), except for the late check-in of PAY-7.

**PAY-2.** Who may check in a row:

| Row | Who |
|---|---|
| their own | the participant |
| a shadow player's | the session coach, or the shadow player's managing coach |
| the booker's | the booker, or the club side of the court's club (for a booker who does not use the app at the court) |

**PAY-3.** The club side may check in **only the booker's row**, and only on sessions on their club's courts. (This is the "check the booker in" right in ACC-6.)

**PAY-4.** Steps, in one transaction:
1. Lock the session row (`select_for_update`).
2. If the row already has `checked_in_at`: change nothing and return it (GEN-5).
3. Set `checked_in_at` = now.
4. If the row is the booker's: call `billing.services.record_payments(session)` (PAY-10).

**PAY-5.** Errors: session not visible `404`; caller not allowed for this row `403`; outside the window `400 checkin_closed`; row not `accepted` `400 not_accepted`; session not `confirmed` `400 invalid_status`.

**PAY-6.** No-shows: an accepted participant with no `checked_in_at` after `ends_at`. Nothing is written; it is computed (RPT-6). If the booker is not checked in by `ends_at + 24 hours` (PAY-7), no payment rows ever exist for the session.

**PAY-7.** **Late check-in** (settled at the owner's review on 2026-11-16). The club side may check in the **booker's row** (PAY-3) until `ends_at + 24 hours` (included), for a booker who forgot. Everything else in PAY-1 to PAY-5 holds, and the booker's check-in creates the payments as usual (PAY-4). Nobody else may check in after `ends_at`: `400 checkin_closed`.

## Creating payments

**PAY-10.** `record_payments(session)` runs inside the check-in transaction, with the session row locked. If the session already has any payment row, it does nothing. Otherwise it creates the rows of PAY-11 to PAY-13, each with `currency` = the session currency, `platform_fee` from PAY-14, `method` empty, `paid_at` empty, `settled_at` empty. Because the session row is locked and the check runs inside the lock, two simultaneous booker check-ins create the rows once.

**PAY-11.** **Court fee** (only if the session has a court): payer = booker, payee = the court's club, amount = `price − discount_amount + sum of approved rental prices`.

**PAY-12.** **Coach fee, split** (when `coach_fee > 0` and `coach_fee_payer` is empty): payee = the session coach. The payers are the session's accepted participants, excluding the session coach; when the session has a `group`, only those who are active members of that group at check-in time. Shadow players are included (the coach collects from the parent). Order the payers by participant row `id`, ascending. With `n` payers and minor unit `u` (GEN-15):
- `share = coach_fee ÷ n`, rounded **down** to `u`;
- `remainder = coach_fee − share × n`;
- the first payer pays `share + remainder`, every other payer pays `share`.

If there are no payers, no coach-fee row is created.

**PAY-13.** **Coach fee, single payer** (when `coach_fee > 0` and `coach_fee_payer` is set): one row, payer = `coach_fee_payer`, payee = the session coach, amount = `coach_fee`.

**PAY-14.** `platform_fee = round_money(amount × percent / 100, currency)`, where `percent` comes from the commission lookup (COM-1) for that row's payee on today's date (UTC) at check-in.

**PAY-15.** A row whose amount would be 0 is not created (a free court, a fully discounted session, a zero coach fee).

**PAY-16.** All shares are owed at check-in, including for members who did not attend (they accepted the session).

## Marking paid

**PAY-20.** **Mark paid.** Who may: for a club payment, the club side of that club; for a coach payment, that coach. The payer never. Effect: `method = offline`, `paid_at` = now. Already paid: no change (GEN-5).

**PAY-21.** **Back to due** (undo a mistake). Same people. Allowed only while `settled_at` is empty. Effect: `method` and `paid_at` emptied. Already due: no change. Settled: `400 already_settled`.

**PAY-22.** Payments are never deleted or edited otherwise. Disputes are not handled in the app.

**PAY-23.** A payer sees their own payment rows (what they owe and what they paid); a payee side sees rows where they are the payee. Others: `404`.

**PAY-24.** *Decided during build (2026-11-16):* check-in checks, in order: visibility (`404`), who may (`403`), then inside the lock an already checked-in row returns `200` unchanged (GEN-5) before `invalid_status`, `not_accepted` and `checkin_closed`. The payer marking their own payment is `403` (they can see it); anyone else `404`. Mark paid and back to due return `200` on a repeat.

State of a payment row:

| From | To | Who | When |
|---|---|---|---|
| (new) | due | system | booker's check-in (PAY-10) |
| due | paid | payee side | money handed over (PAY-20) |
| paid | due | payee side | correcting a mistake, before settlement (PAY-21) |
| paid | settled | platform admin (Django admin) | the platform's cut is settled with the payee (COM-10) |

## Worked examples

**Court booking.** The session from [discounts](discounts.md#worked-example): EUR, `price = 111.17`, `discount_amount = 11.12`, shooting machine approved at 13.85. Club commission 10%.

- Court fee: 111.17 − 11.12 + 13.85 = **113.90 EUR**, payer Rana, payee Hoops.
- Platform fee: 113.90 × 10 / 100 = 11.39 → **11.39 EUR**. Hoops keeps 102.51.

**Team training with a split fee.** Coach Sami books the U12 team at Hoops in **LBP**, court price 4 475 000, no offer, `coach_fee = 250 000`, `coach_fee_payer` empty. Accepted participants: Sami (row 40), Kid A (shadow, row 41), Maya (row 42), Omar (row 43). Coach commission 10%, club 10%.

- Sami checks in. Court fee: payer Sami, payee Hoops, **4 475 000**, platform fee 447 500.
- Coach fee payers (Sami excluded): rows 41, 42, 43, so `n = 3`, `u = 1`.
  `250 000 ÷ 3 = 83 333.33…` → share **83 333**; remainder 250 000 − 249 999 = **1**.
  Kid A **83 334**, Maya **83 333**, Omar **83 333**.
- Platform fees: 83 334 × 10% = 8 333.4 → **8 333**; 83 333 × 10% = 8 333.3 → **8 333** (twice).

Same split in USD with `coach_fee = 100.00`: 100 ÷ 3 = 33.333… → 33.33, remainder 0.01: **33.34, 33.33, 33.33**.

## Edge cases

- **Booker checks in twice, or two devices at once:** one set of rows (PAY-4 step 2, PAY-10 lock).
- **A member accepted, then left the team before check-in:** not a payer (PAY-12 checks membership at check-in).
- **The booker is the coach and also an accepted participant:** owes the court fee, never a share of their own fee.
- **Session currency LBP:** shares and fees are whole pounds (GEN-15).
- **Discount removed after check-in:** impossible; DSC-12 forbids changing the discount once payments exist.

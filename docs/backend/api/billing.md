# API: billing (payments, billing, the payer's and the payee's ticks, commission, money reports)

**Status: built and tested.** Code: [views](../../../backend/billing/views.py), [serializers](../../../backend/billing/serializers.py), [services](../../../backend/billing/services.py), [admin](../../../backend/billing/admin.py), [tests](../../../backend/billing/tests.py). Rules: [check-in-and-payments](../logic/check-in-and-payments.md) (PAY-9 to PAY-29), [commission](../logic/commission.md) (COM-1 to COM-11), [owner-reports](../logic/owner-reports.md) (RPT-2, RPT-3, RPT-7), [conventions](../logic/conventions.md). Same conventions as [accounts](accounts.md). Check-in itself, the one-off discount and the other reports are in [bookings](bookings.md).

There is no payment gateway: a payment row says money is owed, the payer may tick "I paid" (**declared paid**, a claim only), and the payee ticks **received**, which alone makes it paid. Rows are created only by **billing**: each scheduler tick (`manage.py tick`) calls `services.bill_ended_sessions()`, which bills every confirmed session a day after it ended, once check-in has closed (PAY-10, NOTE-33). There is no endpoint that creates, edits or deletes a payment (PAY-22).

## Who may call

Every call needs a token. A payment is visible to its payer and to its payee side: the coach, or for a club payment the club side (owner and current staff). Anyone else gets `404` (GEN-3, PAY-23). Someone who sees a row but may not tick it gets `403`: the payer on the payee's ticks, the payee side on the payer's (PAY-24, PAY-28, PAY-29).

## Endpoints

| Method | Path | Who | Body / notes | Success |
|---|---|---|---|---|
| GET | `/api/payments/` | any user | the payments the caller owes or is the payee side of, newest first, paged. `{id, session, payer: {id, full_name, is_coach}, club: {id, name} or null, coach: {...} or null, amount, currency, platform_fee, method, payer_marked_at, paid_at, waived_at, settled_at, created_at}` (PAY-23). Due = `paid_at` and `waived_at` empty | `200` page |
| GET | `/api/payments/<id>/` | payer, payee side | one payment; others `404` | `200` |
| POST | `/api/payments/<id>/declare-paid/` | the payer | no body. `payer_marked_at` = now; pushes `payment_marked` to the payee side (the coach, or the club owner and current staff). `400 already_paid` once received, `400 already_waived` (PAY-26) | `200`, also when already declared (no second push) |
| POST | `/api/payments/<id>/undo-declare/` | the payer | no body. Empties `payer_marked_at`. `400 already_paid` once received (PAY-27) | `200`, also when not declared |
| POST | `/api/payments/<id>/mark-paid/` | payee side | no body. **Received**: `method = offline`, `paid_at` = now; `payer_marked_at` stays. `400 already_waived` (PAY-20) | `200`, also when already received (nothing changes) |
| POST | `/api/payments/<id>/mark-due/` | payee side | no body. Back to due: empties `method`, `paid_at` and `waived_at`; `payer_marked_at` stays (PAY-21). `400 already_settled` once `settled_at` is set | `200`, also when already due |
| POST | `/api/payments/<id>/waive/` | payee side | no body. `waived_at` = now: not owed, not revenue, no platform fee. Allowed while due, declared or not; `400 already_paid` once received (PAY-25) | `200`, also when already waived |
| GET | `/api/clubs/<id>/dues/` | club side | RPT-2: `{payments: [{id, session, payer, amount, currency, created_at, payer_marked_at}], totals: [{currency, total}]}` for the club's payments still due (declared ones included), oldest first. No period, not paged. Players and other clubs' owners `403`; a club the caller cannot see `404` | `200` |
| GET | `/api/clubs/<id>/revenue/?from=&to=` | the club owner (staff `403`, ACC-6) | RPT-3: `{currencies: [{currency, gross, fees, net, owed_to_platform}]}` sorted by currency. Payments to the club with `paid_at` in the period (local dates in the club's timezone, both included, at most 366 days else `400 bad_range`); `owed_to_platform` is the sum of `platform_fee` over **all** the club's paid, unsettled payments (any date, COM-11), so a currency can appear with zero gross | `200` |
| GET | `/api/me/earnings/?from=&to=` | a coach (else `403`) | RPT-7: `{currencies: [...], due: {payments, totals}}`: RPT-3 for payments where the caller is the coach, with the period in **the coach's own timezone** (GEN-8), plus their own due list | `200` |

Money is a decimal string with three places (`"113.900"`, LBP `"4475000.000"`); totals are never mixed across currencies (GEN-13).

## What billing creates (PAY-9 to PAY-16)

Each tick, for every `confirmed` session with `ends_at + 24 h <= now` and `billed_at` empty, in one transaction with the session row locked: `billed_at` = now, then, if anyone attended (an accepted row with `checked_in_at`), the rows below. Nobody attended: billed with no rows. After the transaction commits each new row pushes `payment_due` to its payer ("You owe 37.98 EUR to Hoops").

- **Payers of a split** are the attendees except the session coach, ordered by participant row id (the booker's row is first). `share = amount / n` rounded down to the minor unit; the first payer also pays the remainder (PAY-13). LBP `250 000 / 3`: `83 334, 83 333, 83 333`; USD `100.00 / 3`: `33.34, 33.33, 33.33`. No-shows owe nothing (PAY-16).
- **Court fee** (session has a court), payee the court's club, `price - discount_amount + approved rentals`: paid in full by the booker (`court_fee_split` false), or split; a split with no payers (only the session coach came) falls back to the booker (PAY-11).
- **Coach fee** (`coach_fee > 0`), payee the session coach: paid in full by `coach_fee_payer`, attended or not; or split (`coach_fee_payer` empty); a split with no payers creates no row (PAY-12).
- Rows of amount 0 are not created (PAY-15).
- `platform_fee = round_money(amount * percent / 100)`, with the percent from the commission lookup for that row's payee on the UTC date of billing (PAY-14).

## Commission lookup (COM-1 to COM-3)

`services.commission_percent(applies_to, payee, day)`: candidate rows are of the payee type with `effective_from <= day` and `min_count <= N`; the payee's own rows win over the defaults whenever any of them is a candidate; newest `effective_from`, then highest `min_count`; no row at all is 0%. `N` is only counted when a candidate row has `min_count > 0` (until then it is 0, COM-3): for a coach, the number of their players (ACC-1); for a club, its non-cancelled sessions that started in the 30 days before now. Rates change only in the Django admin by adding rows (COM-4).

## Settlement (COM-10, ACC-7)

A platform admin sets `settled_at` in the Django admin (`/admin/billing/payment/`). The change form shows every field read-only except `settled_at`, and refuses a value while `paid_at` is empty. Payments cannot be added or deleted there.

## Concurrency (PAY-10, NOTE-33)

`bill_ended_sessions` bills each session in its own `transaction.atomic()` after `select_for_update()` on the session row, and re-reads `billed_at` under the lock, so two overlapping ticks bill a session once. Every tick on a payment locks its row too.

## Decided during build (2026-11-16)

- `already_settled` is checked before the "already due" no-op, so a settled row can never be made due. Marking a settled row paid again is a `200` no-op.
- A payment's payee side for a club is the club side at the time of the request (ACC-1, ACC-2): an expired staff membership loses access.
- Due lists (RPT-2, RPT-7) are not paged: payees tick rows off, so they stay short. Page them if clubs ever accumulate thousands of unpaid rows.

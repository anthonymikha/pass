# API: billing (payments, marking paid, commission, money reports)

**Status: built and tested.** Code: [views](../../../backend/billing/views.py), [serializers](../../../backend/billing/serializers.py), [services](../../../backend/billing/services.py), [admin](../../../backend/billing/admin.py), [tests](../../../backend/billing/tests.py). Rules: [check-in-and-payments](../logic/check-in-and-payments.md) (PAY-10 to PAY-23), [commission](../logic/commission.md) (COM-1 to COM-11), [owner-reports](../logic/owner-reports.md) (RPT-2, RPT-3, RPT-7), [conventions](../logic/conventions.md). Same conventions as [accounts](accounts.md). Check-in itself, the one-off discount and the other reports are in [bookings](bookings.md).

There is no payment gateway: a payment row says money is owed, and the payee ticks it off. Rows are created only by the booker's check-in (`services.record_payments`, called from `bookings.services.check_in` inside its transaction, PAY-4, PAY-10). There is no endpoint that creates, edits or deletes a payment (PAY-22).

## Who may call

Every call needs a token. A payment is visible to its payer and to its payee side: the coach, or for a club payment the club side (owner and current staff). Anyone else gets `404` (GEN-3, PAY-23). A payer who sees a row but may not tick it gets `403`.

## Endpoints

| Method | Path | Who | Body / notes | Success |
|---|---|---|---|---|
| GET | `/api/payments/` | any user | the payments the caller owes or is the payee side of, newest first, paged. `{id, session, payer: {id, full_name, is_coach}, club: {id, name} or null, coach: {...} or null, amount, currency, platform_fee, method, paid_at, settled_at, created_at}` (PAY-23) | `200` page |
| GET | `/api/payments/<id>/` | payer, payee side | one payment; others `404` | `200` |
| POST | `/api/payments/<id>/mark-paid/` | payee side | no body. `method = offline`, `paid_at` = now (PAY-20) | `200`, also when already paid (nothing changes) |
| POST | `/api/payments/<id>/mark-due/` | payee side | no body. Empties `method` and `paid_at` (PAY-21). `400 already_settled` once `settled_at` is set | `200`, also when already due |
| GET | `/api/clubs/<id>/dues/` | club side | RPT-2: `{payments: [{id, session, payer, amount, currency, created_at}], totals: [{currency, total}]}` for the club's unpaid payments, oldest first. No period, not paged. Players and other clubs' owners `403`; a club the caller cannot see `404` | `200` |
| GET | `/api/clubs/<id>/revenue/?from=&to=` | the club owner (staff `403`, ACC-6) | RPT-3: `{currencies: [{currency, gross, fees, net, owed_to_platform}]}` sorted by currency. Payments to the club with `paid_at` in the period (local dates in the club's timezone, both included, at most 366 days else `400 bad_range`); `owed_to_platform` is the sum of `platform_fee` over **all** the club's paid, unsettled payments (any date, COM-11), so a currency can appear with zero gross | `200` |
| GET | `/api/me/earnings/?from=&to=` | a coach (else `403`) | RPT-7: `{currencies: [...], due: {payments, totals}}`: RPT-3 for payments where the caller is the coach, with the period in **the coach's own timezone** (GEN-8), plus their own due list | `200` |

Money is a decimal string with three places (`"113.900"`, LBP `"4475000.000"`); totals are never mixed across currencies (GEN-13).

## What a check-in creates (PAY-10 to PAY-16)

In one transaction, with the session row locked, only if the session has no payment yet:

- **Court fee** (session has a court): payer the booker, payee the court's club, `price - discount_amount + approved rentals` (PAY-11).
- **Coach fee split** (`coach_fee > 0`, no `coach_fee_payer`): payee the session coach; payers are the accepted participants except the coach, and for a session with a group only those who are active members of it now. Ordered by participant row id; `share = coach_fee / n` rounded down to the minor unit, the first payer also pays the remainder (PAY-12). LBP `250 000 / 3`: `83 334, 83 333, 83 333`; USD `100.00 / 3`: `33.34, 33.33, 33.33`.
- **Coach fee, one payer** (`coach_fee_payer` set): one row for that payer (PAY-13).
- Rows of amount 0 are not created (PAY-15). Everyone who accepted owes their share whether they came or not (PAY-16).
- `platform_fee = round_money(amount * percent / 100)`, with the percent from the commission lookup for that row's payee on the UTC date of the check-in (PAY-14).

## Commission lookup (COM-1 to COM-3)

`services.commission_percent(applies_to, payee, day)`: candidate rows are of the payee type with `effective_from <= day` and `min_count <= N`; the payee's own rows win over the defaults whenever any of them is a candidate; newest `effective_from`, then highest `min_count`; no row at all is 0%. `N` is only counted when a candidate row has `min_count > 0` (until then it is 0, COM-3): for a coach, the number of their players (ACC-1); for a club, its non-cancelled sessions that started in the 30 days before now. Rates change only in the Django admin by adding rows (COM-4).

## Settlement (COM-10, ACC-7)

A platform admin sets `settled_at` in the Django admin (`/admin/billing/payment/`). The change form shows every field read-only except `settled_at`, and refuses a value while `paid_at` is empty. Payments cannot be added or deleted there.

## Concurrency (PAY-10)

`bookings.services.check_in` runs in `transaction.atomic()` and takes `select_for_update()` on the session row first. `record_payments` runs inside that lock and returns without writing when `session.payments` already has a row, so two simultaneous booker check-ins create one set of rows (the second waits for the lock, then finds the participant row already checked in).

## Decided during build (2026-11-16)

- `already_settled` is checked before the "already due" no-op, so a settled row can never be made due. Marking a settled row paid again is a `200` no-op.
- A payment's payee side for a club is the club side at the time of the request (ACC-1, ACC-2): an expired staff membership loses access.
- Due lists (RPT-2, RPT-7) are not paged: payees tick rows off, so they stay short. Page them if clubs ever accumulate thousands of unpaid rows.

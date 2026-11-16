# API: bookings (free slots, prices, court booking, invites, rentals, cancelling)

**Status: built and tested (play bookings).** Code: [views](../../../backend/bookings/views.py), [serializers](../../../backend/bookings/serializers.py), [services](../../../backend/bookings/services.py), [tests](../../../backend/bookings/tests.py); the session card is `post_session_card` in [chat/services.py](../../../backend/chat/services.py). Rules: [court-availability](../logic/court-availability.md) (AVL-1 to AVL-12), [pricing-and-currency](../logic/pricing-and-currency.md) (PRC-1 to PRC-12), [discounts](../logic/discounts.md) (DSC-1 to DSC-8), [booking](../logic/booking.md) (BOOK-1 to BOOK-17, BOOK-40 to BOOK-43, BOOK-50, BOOK-51, BOOK-55, BOOK-60, BOOK-65, BOOK-66), [chat](../logic/chat.md) (CHAT-30, CHAT-31). Same conventions as [accounts](accounts.md).

Not built yet: training requests and coach-booked training (BOOK-20 to BOOK-33), personal and group availability (AVL-20 to AVL-25), check-in and payments, one-off discounts (DSC-10 to DSC-14), reports.

## Who may call

- **Public (no token):** `GET /api/courts/<id>/slots/`. Everything else needs a token.
- **A session is visible** to its participants (any status), its booker, its session coach and the club side of its court's club (owner, current staff). Anyone else gets `404` (BOOK-65). A caller who sees a session but may not do an action gets `403`.
- **Rentals** are decided by the club side only. **Cancelling** is for the booker, the session coach and the club owner (not staff).

## Endpoints

| Method | Path | Who | Body / notes | Success |
|---|---|---|---|---|
| GET | `/api/courts/<id>/slots/?date=YYYY-MM-DD&currency=EUR` | public | `date` in the club's timezone, today to today + 60 days; `currency` defaults to the club's base. Free slots in time order, not paged: `[{starts_at, ends_at, price}]` (AVL-10 to AVL-12). `404` unknown or inactive court, `400 currency_not_accepted`, `400 outside_horizon` | `200` |
| POST | `/api/sessions/quote/` | any user | same body as booking. Writes and holds nothing. `{currency, price, offer: {id, message} or null, discount_amount, rentals: [{equipment, name, quantity, price}], court_amount}`; `court_amount = price - discount_amount + rentals` (BOOK-6). Also `409 slot_taken` if the times are already taken | `200` |
| POST | `/api/sessions/` | any user | book a court (BOOK-5 to BOOK-10): `court`, `sport`, `starts_at`, `ends_at`, `currency`, optional `rentals` `[{equipment, quantity}]`, `group`, `invitees` `[user ids]`. Returns the session | `201` |
| GET | `/api/sessions/<id>/` | visible | the session with `participants` and `rentals`; `status` shows `completed` for a confirmed session that has ended (BOOK-55, BOOK-65) | `200` |
| GET | `/api/me/sessions/` | any user | sessions where the caller is booker, session coach or an `invited`/`accepted` participant; `from`, `to` (instants; `starts_at >= from`, `starts_at < to`), `status` (the shown status, so `completed` works); ordered by `starts_at`; paged (BOOK-66) | `200` page |
| POST | `/api/sessions/<id>/cancel/` | booker, session coach, club owner | no body (BOOK-50, BOOK-51). `400 already_payable`, `400 session_closed`, `400 invalid_status` (not a confirmed session) | `200`, also on a repeat |
| POST | `/api/sessions/<id>/participants/` | the booker | invite after booking: `invitees` `[user ids]` (friends of the booker, or active members of the session's group). Anyone who already has a row is skipped (BOOK-15). `400 session_closed` | `201` if someone was invited, else `200`; returns the session |
| PATCH | `/api/sessions/<id>/participants/<user_id>/` | that user only | `status`: `accepted` or `declined`. `400 session_closed`, `400 booker_cannot_leave` (BOOK-16). Another user's row: `403` | `200`, also on a repeat |
| DELETE | `/api/sessions/<id>/participants/<user_id>/` | the booker | remove a participant before the start (BOOK-17). `400 booker_cannot_leave`, `400 already_checked_in`, `400 session_closed` | `204` |
| PATCH | `/api/rentals/<id>/` | club side of the court's club | `status`: `approved` or `declined`. `409 out_of_stock` on approval (BOOK-41); `400 already_payable` (payments exist), `400 session_cancelled` | `200`, also on a repeat |

## Errors on booking (BOOK-7)

Checked in this order, first failure wins; a refused request writes nothing:

1. `court`: `400` on the field (unknown or inactive); `sport`: `400` on the field if unknown.
2. `400 sport_not_offered`, then `400 currency_not_accepted`.
3. `400 not_bookable`: the run is not slots of the court from `starts_at` to `ends_at` (misaligned, a gap, a day without a rate, `ends_at` not after `starts_at`), starts in the past, is more than 60 days ahead, or runs into a closure.
4. `400` on `rentals`, then `group`, then `invitees` (field-shaped: `{"rentals": ["..."]}`).
5. Inside the court lock: `409 slot_taken` when a non-cancelled session overlaps (also the answer to the same user sending twice, GEN-6).

## Money and times

Money is a decimal string with 3 places (`"111.170"`); LBP amounts are whole numbers (`"4475000.000"`). Timestamps are ISO 8601 with an offset (`2027-01-11T14:00:00Z`); a request without an offset is `400`.

## Pushes

After the request commits: `session_invite` to each newly invited user (booking, group members, invites), `session_cancelled` to accepted and invited participants and the session coach except the caller. Data is `{id: <session id>, type}`.

## Concurrency

`services.book_court` runs in `transaction.atomic()` and takes `select_for_update()` on the court row (`venues.services.lock_court`) before it re-checks the run and the overlap, so two bookers of one court run one after the other. Rental approval locks the equipment row the same way.

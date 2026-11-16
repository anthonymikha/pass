# API: bookings (free slots, prices, court booking, training, availability, invites, rentals, cancelling)

**Status: built and tested (play bookings, training, availability).** Code: [views](../../../backend/bookings/views.py), [serializers](../../../backend/bookings/serializers.py), [services](../../../backend/bookings/services.py), [tests](../../../backend/bookings/tests.py); the session card is `post_session_card` in [chat/services.py](../../../backend/chat/services.py). Rules: [court-availability](../logic/court-availability.md) (AVL-1 to AVL-12, AVL-20 to AVL-25), [pricing-and-currency](../logic/pricing-and-currency.md) (PRC-1 to PRC-12), [discounts](../logic/discounts.md) (DSC-1 to DSC-8), [booking](../logic/booking.md) (BOOK-1 to BOOK-17, BOOK-20 to BOOK-33, BOOK-40 to BOOK-43, BOOK-50, BOOK-51, BOOK-55, BOOK-60, BOOK-65, BOOK-66), [chat](../logic/chat.md) (CHAT-30, CHAT-31). Same conventions as [accounts](accounts.md).

Not built yet: check-in and payments (a confirmed training session only stores `coach_fee` and `coach_fee_payer`), one-off discounts (DSC-10 to DSC-14), reports.

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
| POST | `/api/training-requests/` | any user | ask a coach (BOOK-20): `coach`, `sport`, `starts_at`, `ends_at` (in the future, at most 8 hours). Session `requested`, no court, `currency` empty, `price` 0, `coach_fee_payer` the requester. `400 not_a_coach`, `400 cannot_request` (yourself or a blocked pair); a shadow or unknown `coach` is `400` on the field | `201` |
| POST | `/api/sessions/<id>/confirm/` | the session coach | BOOK-21: `starts_at`, `ends_at`, `currency`, `coach_fee` (GEN-17), optional `court`. With a court the BOOK-7 checks and the court lock apply (`sport_not_offered`, `currency_not_accepted`, `not_bookable`, `409 slot_taken`) and the offer is the requester's; without one `price` is 0, any valid `currency`, the start must be in the future (`400` on `starts_at` / `ends_at`). Anyone else `404`; not `requested` `400 invalid_status` | `200` |
| POST | `/api/sessions/<id>/decline/` | the session coach | BOOK-22. `404` for anyone else; `400 invalid_status` if confirmed; `400 session_closed` once `starts_at` has passed | `200`, also on a repeat |
| POST | `/api/sessions/<id>/withdraw/` | the requester | BOOK-22, same errors as decline | `200`, also on a repeat |
| POST | `/api/sessions/training/` | coach | coach-booked training: as booking plus `coach_fee` (required), optional `court` (optional here), optional `coach_fee_payer` (user id), and **one of** `group` (a team the caller manages, BOOK-30) or `player` (one of the caller's players, BOOK-31). Not a coach `403`; not a manager `403`; `400 not_a_team`; `400 not_your_player`; `400` on `coach_fee_payer` (BOOK-32, ACC-12). No rentals or extra invitees | `201` |
| GET | `/api/users/<id>/availability/?from=&to=&min_minutes=` | the user, or a coach about one of their players | free intervals `[{starts_at, ends_at}]` (AVL-20, AVL-22, AVL-23); not paged; anyone else `404` | `200` |
| GET | `/api/groups/<id>/availability/?from=&to=&min_minutes=` | an active member or a group manager | intervals where every active member is free (AVL-21); anyone else `404` | `200` |

## Training and availability

- A training request is a session with `kind = training`, `status = requested`. It holds no court and makes nobody busy (AVL-20). Confirming sets `status = confirmed` and copies the court, price, offer, fee and the new times onto it; `booked_by` stays the requester, who owes the court fee and the coach fee when they check in (BOOK-23).
- Coach-booked training is `confirmed` at once: `booked_by` and `coach` are the caller. Team: the coach is `accepted`, active members `invited`, shadow members `accepted`, and the session card is posted. One player: the player is `invited` (`accepted` for a shadow player); `coach_fee_payer` defaults to the player. In a team an omitted or `null` `coach_fee_payer` means the fee is split (PAY-12). A `coach_fee_payer` that is a shadow player is accepted only from their managing coach.
- Availability: `from` and `to` are instants with an offset (at most 14 days apart, `to` after `from`, else `400 bad_range`); `min_minutes` is 5 to 1440, default 30. Intervals are in UTC, merged where they touch and in time order. Permission is checked before the input.

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

After the request commits: `session_invite` to each newly invited user (booking, group members, invites, coach-booked training), `training_request` to the coach, `training_confirmed` / `training_declined` to the requester, `training_withdrawn` to the coach, `session_cancelled` to accepted and invited participants and the session coach except the caller. Data is `{id: <session id>, type}`.

## Concurrency

`services.book_court` runs in `transaction.atomic()` and takes `select_for_update()` on the court row (`venues.services.lock_court`) before it re-checks the run and the overlap, so two bookers of one court run one after the other. Rental approval locks the equipment row the same way.

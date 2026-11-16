# API: bookings (free slots, prices, court booking, training, availability, invites, rentals, cancelling, check-in, one-off discount, reports, recordings and tags)

**Status: built and tested.** Code: [views](../../../backend/bookings/views.py), [serializers](../../../backend/bookings/serializers.py), [services](../../../backend/bookings/services.py), [tests](../../../backend/bookings/tests.py); the session card is `post_session_card` in [chat/services.py](../../../backend/chat/services.py). Rules: [court-availability](../logic/court-availability.md) (AVL-1 to AVL-12, AVL-20 to AVL-25), [pricing-and-currency](../logic/pricing-and-currency.md) (PRC-1 to PRC-12), [discounts](../logic/discounts.md) (DSC-1 to DSC-14), [booking](../logic/booking.md) (BOOK-1 to BOOK-17, BOOK-20 to BOOK-33, BOOK-40 to BOOK-43, BOOK-50, BOOK-51, BOOK-55, BOOK-60, BOOK-65, BOOK-66), [chat](../logic/chat.md) (CHAT-30, CHAT-31), [check-in-and-payments](../logic/check-in-and-payments.md) (PAY-1 to PAY-7), [owner-reports](../logic/owner-reports.md) (RPT-1, RPT-4 to RPT-6, RPT-8), [recordings](../logic/recordings.md) (REC-1 to REC-30). Same conventions as [accounts](accounts.md). Payments, commission and the money reports (RPT-2, RPT-3, RPT-7) are in [billing](billing.md).

## Who may call

- **Public (no token):** `GET /api/courts/<id>/slots/`. Everything else needs a token.
- **A session is visible** to its participants (any status), its booker, its session coach and the club side of its court's club (owner, current staff). Anyone else gets `404` (BOOK-65). A caller who sees a session but may not do an action gets `403`.
- **Rentals** are decided by the club side only. **Cancelling** is for the booker, the session coach and the club owner (not staff). **Check-in**: PAY-2 and PAY-3 (above). **One-off discount**: the club owner only. **Reports**: the club side, except customers (owner only); a coach for player history.

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
| POST | `/api/sessions/<id>/participants/<user_id>/check-in/` | the participant; for a shadow player the session coach or their managing coach; for the booker's row also the club side | no body (PAY-1 to PAY-7). Window `starts_at - 30 min` to `ends_at`, both included; the club side may check the **booker** in until `ends_at + 24 h`. The booker's check-in creates the payments in the same transaction ([billing](billing.md)). `404` session not visible or no such row, `403` not allowed for that row, `400 invalid_status`, `400 not_accepted`, `400 checkin_closed`. Returns the participant row | `200`, also on a repeat (GEN-5) |
| PUT | `/api/sessions/<id>/discount/` | the club owner of the session's court | one-off discount (DSC-10 to DSC-14): `amount` in the session currency, 0 to `price`, decimals as GEN-17 (`400` on `amount`). Replaces the offer (`discount` becomes empty); 0 removes the reduction; the offer is never re-applied. Staff, the booker and other visible users `403`; not visible `404`. `400 already_payable`, `400 session_cancelled`. Returns the session | `200` |
| GET | `/api/sessions/<id>/attendance/` | club side of the court's club, the session coach | RPT-6: `{session, accepted: [participant rows], checked_in, no_shows: [people]}`. A no-show is accepted, not checked in, and `now > ends_at`. Other visible users `403`, not visible `404` | `200` |
| GET | `/api/clubs/<id>/schedule/?from=&to=&court=` | club side | RPT-1: `{sessions, closures}`. `from`, `to` are local dates (club timezone, both included, at most 366 days, else `400 bad_range`). Sessions that overlap the period and are not cancelled, by `starts_at`: `id, court, sport, kind, status` (shown), `starts_at, ends_at, booker, coach, group` (name), `accepted_count, rentals`. Closures: `court, starts_at, ends_at, reason`. Optional `court` (a court of the club, else `400` on `court`). Not paged. A club the caller cannot see `404`, anyone else not club side `403` | `200` |
| GET | `/api/clubs/<id>/customers/?from=&to=` | the club owner (not staff, ACC-6) | RPT-4, RPT-5: `{customers, repeat_rate, people: [{id, full_name, sessions}]}` for non-cancelled sessions with `starts_at` in the period; `repeat_rate` is a decimal string (`"66.67"`) or `null` with no customers. People by session count (high first), then name. Not paged | `200` |
| GET | `/api/players/<user_id>/sessions/` | a coach, for one of their players (ACC-1) | RPT-8: the player's accepted rows in confirmed sessions the caller coached, newest first, paged: `session, kind, starts_at, ends_at, checked_in_at, rpe, rpe_minutes, training_load` (`rpe x rpe_minutes`, `null` when either is missing). Not a coach `403`; not their player `404` | `200` page |
| GET | `/api/users/<id>/availability/?from=&to=&min_minutes=` | the user, or a coach about one of their players | free intervals `[{starts_at, ends_at}]` (AVL-20, AVL-22, AVL-23); not paged; anyone else `404` | `200` |
| GET | `/api/groups/<id>/availability/?from=&to=&min_minutes=` | an active member or a group manager | intervals where every active member is free (AVL-21); anyone else `404` | `200` |
| POST | `/api/sessions/<id>/recordings/form/` | the session coach, or a participant who checked in | REC-10, REC-11: `file_name` (`.mp4` or `.mov`, any case), `size_bytes` (1 to 2 147 483 648). Returns `{url, fields, storage_key}`: a signed POST form valid 1 hour and limited to 1..`size_bytes` bytes; `storage_key` is `recordings/<session id>/<uuid>.<ext>` (lowercase). Writes nothing. Not visible `404`, visible but not allowed `403`, bad input `400` per field, `400 upload_closed` | `200` |
| POST | `/api/sessions/<id>/recordings/` | same | REC-12: `storage_key`, optional `duration_seconds` (>= 1). `400 bad_key`, `400 upload_closed`, `400 not_uploaded`. Returns the recording without a link (the uploader may not be allowed to watch yet) | `201`; `200` with the existing row on a repeat (GEN-5) |
| GET | `/api/sessions/<id>/recordings/` | the session coach, or a participant with `checked_in_at` and `rpe` both set | REC-20, REC-21: `[{id, session, uploaded_by: {id, full_name, is_coach}, duration_seconds, created_at, url}]` oldest first, paged; `url` is signed for 1 hour (REC-2). Anyone else (an uploader without RPE included) `404` | `200` page |
| DELETE | `/api/recordings/<id>/` | the uploader or the session coach | REC-14: deletes the object, the row and its tags. A participant who may watch but is neither `403`; who may not see it `404` | `204` |
| GET | `/api/recordings/<id>/tags/` | the session coach, or a participant who may watch | REC-27: the coach sees every tag; a participant sees whole-team tags and tags naming them. Ordered by `start_second`, paged. Anyone else `404` | `200` page |
| POST | `/api/recordings/<id>/tags/` | the session coach | REC-25: `start_second` (>= 0), optional `end_second` (> `start_second`), both at most `duration_seconds` when it is known; `label` (1 to 255), optional `note`, optional `players` (participants of the session that are not declined, shadow players included; empty or missing = whole team). Players cannot tag (REC-28): `403`; anyone who may not watch `404`. Returns `{id, recording, created_by, start_second, end_second, label, note, players, created_at}` | `201` |
| PATCH, DELETE | `/api/recording-tags/<id>/` | the tag's creator or the session coach | REC-26: PATCH any tag field, checked against the stored values (so `end_second: null` and `players: []` are valid). A tag the caller may not see `404`; visible but not theirs `403` | `200` / `204` |

## Recordings and tags

Video and avatars live in S3-compatible storage (MinIO in docker-compose, REC-1); Django never receives or serves the bytes. Settings: `STORAGE_ENDPOINT` (how the backend reaches storage for head and delete), `STORAGE_PUBLIC_ENDPOINT` (the address phones use; links and forms are signed for it), `STORAGE_BUCKET`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `STORAGE_REGION`. An empty `STORAGE_ENDPOINT` selects an in-memory fake (REC-3); tests use it and need no MinIO.

Upload with curl (local MinIO; send every returned field as `-F name=value`, the file last):

```sh
curl -s -X POST localhost:8000/api/sessions/<id>/recordings/form/ -H 'Authorization: Token <token>' \
  -H 'Content-Type: application/json' -d '{"file_name":"game.mp4","size_bytes":123456}'
# -> {"url": "http://localhost:9000/pass", "fields": {"key": ..., "policy": ..., "x-amz-...": ...}, "storage_key": ...}
curl -s -X POST http://localhost:9000/pass -F key=... -F x-amz-algorithm=... -F x-amz-credential=... \
  -F x-amz-date=... -F policy=... -F x-amz-signature=... -F file=@game.mp4      # 204 when stored
curl -s -X POST localhost:8000/api/sessions/<id>/recordings/ -H 'Authorization: Token <token>' \
  -H 'Content-Type: application/json' -d '{"storage_key":"<storage_key>","duration_seconds":600}'
```

Decided during build: only a `confirmed` session accepts uploads, from `starts_at` to `ends_at + 30 days` (stored status, so a finished session still counts); anything else is `400 upload_closed`. Confirm checks in the order permission, input, `bad_key`, repeat (`200` with the stored row, at any time), `upload_closed`, `not_uploaded`, and locks the session row so two confirms of one key make one recording. The policy's range is `1..size_bytes`. Signed links and forms last 1 hour.

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

## Check-in, discount and reports (decided during build, 2026-11-16)

- **Check-in** (`services.check_in`) takes `select_for_update()` on the session row, then re-reads the participant row; a row that already has `checked_in_at` is returned unchanged before any status, window or role rule (so a repeat is `200` even after the window closed). The booker's row then calls `billing.services.record_payments(session)` inside the same transaction; that function does nothing when the session already has a payment (PAY-10). Checks after the lock run in the order `invalid_status`, `not_accepted`, `checkin_closed`. The managing coach of a shadow player who is neither session coach, booker nor participant cannot see the session (BOOK-65), so gets `404`.
- **One-off discount**: permission, then the amount, then `already_payable` and `session_cancelled` (GEN-4), all inside a locked session row.
- **Reports**: a period is local dates in the club's timezone (`00:00` of `from` to `00:00` of `to + 1 day`); `to` before `from` or more than 366 days is `400 bad_range`. RPT-1, RPT-4, RPT-5, RPT-6 and RPT-8 live here (they read sessions only); RPT-2, RPT-3 and RPT-7 live in billing. RPT-6 is read per session. RPT-8 lists confirmed sessions only (cancelled and requested ones were not played).

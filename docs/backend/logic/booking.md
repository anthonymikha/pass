# Booking (BOOK)

**Status: built, except the changes from the owner's review of 2026-11-17, which are planned** (marked *review 2026-11-17*: BOOK-7, BOOK-8, BOOK-20, BOOK-21, BOOK-23, BOOK-30, BOOK-33, BOOK-34, BOOK-40, BOOK-50 to BOOK-52). `backend/bookings/`, [API](../api/bookings.md). Booking a court, training requests, coach-booked training, invites, rentals, cancelling, session cards.

## Sessions in general

**BOOK-1.** Session status changes:

| From | To | Who | When |
|---|---|---|---|
| (new) | `confirmed` | booker | a court booking (BOOK-8) or coach-booked training (BOOK-30, BOOK-31) |
| (new) | `requested` | player | a training request (BOOK-20) |
| `requested` | `confirmed` | the session coach | accepts the request (BOOK-21) |
| `requested` | `cancelled` | the session coach (declines) or the booker (withdraws) | before `starts_at` |
| `confirmed` | `cancelled` | see BOOK-50 | before the booker checks in and before `ends_at` |

No other change is allowed. `completed` is never written (BOOK-55).

**BOOK-2.** Every write that puts a session on a court (BOOK-8, BOOK-21, BOOK-30, BOOK-31) runs in **one database transaction** that first locks the court row (`select_for_update`). Inside the lock it re-checks that every slot is offered and free (AVL-5), then writes. Two people booking the same court therefore run one after the other; the second sees the first's session and fails.

**BOOK-3.** The free check counts every session on the court whose status is not `cancelled`, including `requested` ones that have a court (there are none in practice: BOOK-20 requests carry no court).

**BOOK-4.** The run of slots: `starts_at` must equal the start of an offered slot and `ends_at` the end of an offered slot, and every slot between must be offered and free, each starting exactly where the previous one ends. The run may cross rate windows and midnight (for example Monday 23:00–00:00 then Tuesday 00:00–01:00) as long as the slots are contiguous. Rule AVL-5 items 3 and 4 apply to every slot.

## Booking a court (play)

**BOOK-5.** Who may: any user. The booker becomes `booked_by`.

**BOOK-6.** **Quote** (optional, read-only): the same input as BOOK-7; returns `price`, the offer that would apply and its `discount_amount` (DSC-1 to DSC-4), each rental line's price, and the court amount `price − discount_amount + rentals`. Nothing is written or held; a later booking can still fail.

**BOOK-7.** Input: `court`, `sport`, `starts_at`, `ends_at`, `currency`, optional `rentals` (list of `equipment`, `quantity`), optional `group`, optional `invitees` (list of user ids), optional `court_fee_split` (default false: the booker pays the court fee in full; true: split among the attendees, PAY-9, *review 2026-11-17*). Checks, in this order:

| Check | Error |
|---|---|
| Court exists and is active | `400` on `court` |
| `sport` is one of the court's sports | `400 sport_not_offered` |
| Currency accepted (PRC-1) | `400 currency_not_accepted` |
| Run of slots valid (BOOK-4) and within 60 days (AVL-5) | `400 not_bookable` |
| Each rental: item of this club, `court` empty or this court, `rental_price` set, `1 ≤ quantity ≤ item.quantity`, no item twice | `400` on `rentals` |
| `group`: caller is an active member or a group manager of it | `400` on `group` |
| Each invitee: a friend of the caller, not shadow, not the caller, no duplicates | `400` on `invitees` |
| Inside the lock: every slot still free | `409 slot_taken` |

**BOOK-8.** Steps, inside the transaction of BOOK-2:
1. Lock the court; re-check every slot is free.
2. Compute `price` (PRC-5) and the offer (DSC-1 to DSC-5).
3. Create the `sessions` row: `kind = play`, `status = confirmed`, `booked_by` = caller, `coach` empty, `coach_fee = 0`, `group` if given, `currency`, `price`, `discount`, `discount_amount`, `court_fee_split`.
4. Create the booker's `session_participants` row with `status = accepted`.
5. Create one `session_rentals` row per rental with `status = requested` and `price` (PRC-6).
6. Create `invited` participant rows: each invitee, plus, when `group` is set, every active member of the group who is not the booker.
7. If `group` is set: post the session card (BOOK-60).
8. After commit: notify invitees (NOTE-20).

**BOOK-9.** Court bookings are confirmed at once when the slot is free. The club does not approve them.

## Group bookings

**BOOK-10.** A play group or team booking is a normal booking (BOOK-5 to BOOK-8) with `group` set. Every active member other than the booker is invited and accepts or declines on their own (BOOK-16). Shadow players in the group are added as `accepted` (they cannot answer).

**BOOK-11.** Members who join the group after the session was booked are not added to it.

## Invites

**BOOK-15.** Who may invite, after booking: the booker, adding friends of the booker (or active members of the session's group), while the session is `confirmed` and before `starts_at`. A user who already has a participant row in the session is skipped, not re-invited. Errors as in BOOK-7.

**BOOK-16.** The invitee changes their own row. All changes only before `starts_at`, while the session is not cancelled:

| From | To | Who |
|---|---|---|
| `invited` | `accepted` | the invitee |
| `invited` | `declined` | the invitee |
| `accepted` | `declined` | the participant (withdraws), except the booker |
| `declined` | `accepted` | the participant (changes their mind) |

Errors: session started or cancelled `400 session_closed`; booker tries to withdraw `400 booker_cannot_leave`.

**BOOK-17.** The booker may remove a participant (delete the row) who has not checked in, before `starts_at`. The booker's own row cannot be removed.

## Training requests (player asks a coach)

**BOOK-20.** Who may: any user, to a coach who is not themselves and not in a blocked pair with them. Input: `coach`, `sport`, `starts_at`, `ends_at` (the proposed time, in the future, `ends_at` after `starts_at`, at most 8 hours long), optional `court_fee_split` and `coach_fee_split` (each default false: the requester pays that fee in full; PAY-9, *review 2026-11-17*). Creates a session: `kind = training`, `status = requested`, `booked_by` = requester, `coach` = the coach, `court` empty, `currency` empty, `price = 0`, `coach_fee = 0`, `court_fee_split` as chosen, `coach_fee_payer` = the requester, or empty when `coach_fee_split` is true; and the requester's participant row as `accepted`. Notifies the coach (NOTE-20). A request does not block anyone's time: it is not in AVL-20 until confirmed.

**BOOK-21.** The coach **confirms**, giving: `starts_at`, `ends_at` (may differ from the proposal), `currency`, `coach_fee` (≥ 0, GEN-17), and optionally `court`.
- **With a court:** checks and lock as BOOK-7 and BOOK-2 (run of slots, sport offered by the court, currency accepted by the club); `price` from PRC-5; offer from DSC-1 with the **requester** as booker.
- **Without a court** (the coach's own venue): `price = 0`, no offer; `currency` is any valid code; the time only has to be in the future.
- Then `status = confirmed`; `court_fee_split` and `coach_fee_payer` stay as the requester chose. Notifies the requester.

Errors: not the session's coach `404`; not `requested` `400 invalid_status`; plus BOOK-7 errors.

**BOOK-22.** The coach **declines**: `status = cancelled`. The requester **withdraws** before it is confirmed: `status = cancelled`. Either notifies the other.

**BOOK-23.** The booker of a confirmed training session is the requester. The requester pays the court fee (if there is a court) and the coach fee in full unless they chose to split them among the attendees (PAY-9 to PAY-12, *review 2026-11-17*). The requester may invite friends after confirmation (BOOK-15), so a split can have several payers.

## Training booked by a coach

**BOOK-30.** **Team training.** Who may: the team coach (ACC-1). Input as BOOK-7 (court optional, as in BOOK-21, `court_fee_split` included) plus `coach_fee` and optional `coach_fee_payer`. Creates: `kind = training`, `status = confirmed`, `booked_by` = `coach` = caller, `group` = team. Participants: the coach as `accepted` (booker row), every active member except the coach as `invited`, except shadow players, who are added as `accepted`. Session card posted (BOOK-60).

**BOOK-31.** **One player.** Who may: a coach, for one of the coach's players (ACC-1). Same input with `player` instead of `group`. Participants: the coach `accepted`, the player `invited` (shadow player: `accepted`). `coach_fee_payer` defaults to the player.

**BOOK-32.** `coach_fee_payer`, when given, must be an active member of the team (BOOK-30) or the player (BOOK-31), and not the coach. Empty means the fee is split (PAY-12). Error: `400` on `coach_fee_payer`.

**BOOK-33.** In coach-booked training the coach is the booker, so the coach pays the court fee in full unless they chose to split it among the attending players (PAY-11). The session coach never owes a share of their own coach fee or of a split court fee (*review 2026-11-17*).

**BOOK-34.** *Decided during build (2026-11-16):* coach-booked training (BOOK-30, BOOK-31) takes the BOOK-7 court, sport, time and currency input but no `rentals` and no extra `invitees`: its participants are exactly those BOOK-30 and BOOK-31 list. Codes the training rules leave open: asking oneself or someone in a blocked pair is `400 cannot_request`; a target who is not a coach is `400 not_a_coach`; booking for a group that is not a team is `400 not_a_team`; a `player` who is not one of the coach's players is `400 not_your_player`; a non-coach booking training, or a coach who is not the team coach, is `403`. Decline by anyone but the session coach, or withdraw by anyone but the requester, is `404` (as BOOK-21); a request whose time has passed is `400 session_closed`; a repeat on a cancelled request is `200`. Without a court, a past start or an end not after the start is `400` on that field.

## Rentals

**BOOK-40.** Who may decide: the club side of the court's club. `requested` → `approved` or `declined`; `approved` → `declined` and `declined` → `approved` are also allowed. Only while the session is not cancelled and nobody has checked in (PAY-8, *review 2026-11-17*; after the first check-in rentals are frozen, and any still `requested` are never charged).

**BOOK-41.** **Stock check on approval.** In one transaction, lock the equipment row; sum `quantity` of `approved` rentals of the same item on non-cancelled sessions that overlap this session; if that sum + this rental's quantity > `equipment.quantity`, refuse with `409 out_of_stock`.

**BOOK-42.** Rentals are requested only with the booking (BOOK-7). Adding or changing rentals afterwards is not supported.

## Cancelling

**BOOK-50.** Who may cancel a `confirmed` session: its booker; its session coach; the club owner of its court. When: before `ends_at` and while nobody has checked in (PAY-8, *review 2026-11-17*). Effect: `status = cancelled`; rentals still `requested` become `declined`; the slots become free. Notifies every accepted and invited participant except the caller (NOTE-20).

**BOOK-51.** Errors: someone has checked in `400 already_payable`; ended `400 session_closed`; caller not allowed `403` (if they can see the session) or `404`. Cancelling an already cancelled session returns `200` and changes nothing (GEN-5). There are no cancellation fees or refunds.

**BOOK-52.** *Decided during build (2026-11-16), codes and choices the rules above leave open:* removing a participant who has checked in is `400 already_checked_in`, and removing the booker is `400 booker_cannot_leave` (BOOK-17); deciding a rental on a cancelled session is `400 session_cancelled`, and after the first check-in `400 already_payable` (BOOK-40); cancelling a session that is not `confirmed` through BOOK-50 is `400 invalid_status`. A run that is not offered, not contiguous, in the past, beyond 60 days or under a closure is `400 not_bookable`; only an overlapping non-cancelled session is `409 slot_taken` (BOOK-7). The quote (BOOK-6) also answers `409 slot_taken` when the times are taken. Invites after booking (BOOK-15) may name friends of the booker or active members of the session's group; shadow players are never invited. An answer, rental decision or cancel equal to the current state returns `200` even after the session started or ended (GEN-5). In "my sessions", `from` is inclusive and `to` exclusive on `starts_at`, and `status=completed` means a confirmed session that has ended.

## Completed

**BOOK-55.** `completed` is not stored. The API shows a session as `completed` when its stored status is `confirmed` and `ends_at` ≤ now. Every rule that says "confirmed" means the stored status.

## Session cards

**BOOK-60.** When a session with a `group` becomes `confirmed` (BOOK-8, BOOK-21, BOOK-30), in the same transaction call `chat.services.post_session_card(session)` (CHAT-30).

## Reading sessions

**BOOK-65.** A session is visible to: its participants, its booker, its session coach, the club side of its court's club, and the managing coach of a shadow player who is a participant (*decided during build, 2026-11-16*, so PAY-2 can be used). Anyone else: `404`.

**BOOK-66.** "My sessions": sessions where the caller is booker, session coach or a participant with status `invited` or `accepted`; filters `from`, `to`, `status`; ordered by `starts_at`; paginated.

## Edge cases

- **Same user, same request twice** (double tap): the second call fails with `409 slot_taken` because the first holds the slot (GEN-6).
- **Two users, same slot, same moment:** the court lock serialises them; the second gets `409 slot_taken`.
- **Closure added over an existing booking:** the booking stays; the owner sees it in the closure's conflict list (CLUB-16) and decides whether to cancel.
- **Booking that crosses midnight:** Monday 23:00–01:00 needs Monday's 23:00–00:00 slot and Tuesday's 00:00–01:00 slot to both be offered and free (BOOK-4). Each is priced from its own day's rate.
- **Club timezone and UTC:** the request carries instants; slot matching is done after converting the offered slots to UTC (AVL-6). A booking at 16:00 Beirut in January is `14:00Z`.

## Limits (settled at the owner's review on 2026-11-16)

**BOOK-12.** There is no limit on how many future bookings one user may hold.

**BOOK-43.** Stock is checked only when the club side approves a rental (BOOK-41), never when the player requests it. The club side sees the conflict at approval time.

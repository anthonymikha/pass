# Flow: book a court, play, pay

**Status: planned.** This is the core flow and the next large piece of work.

Models: [Court, CourtRate, ClubCurrency, PriceOverride, Equipment, Discount](../models/venues.md), [Session, SessionParticipant, SessionRental](../models/bookings.md), [Payment, CommissionRate](../models/billing.md), [Message](../models/chat.md).

```
CourtRate ─┐
Session ───┼─> free slots ─> price ─> Session + SessionParticipant (+ SessionRental)
Discount ──┘                                   │
                                     booker checks in
                                               │
                              CommissionRate ─> Payment(s)
```

## 1. Find free slots

For a court and a date:

1. Convert the date to the club's timezone and take that weekday's `CourtRate` rows.
2. Cut each window into slots of `court.slot_minutes`. An `end_time` of 00:00 is the end of the day.
3. Remove every slot that overlaps a `CourtBlockout` occurring on that date (`blockout.occurs_on(date)`).
4. Remove every slot that overlaps a `Session` on that court whose status is not `cancelled`.

Two time ranges overlap when `a.starts_at < b.ends_at and a.ends_at > b.starts_at`.

## 2. Price it

For the chosen slots and currency:

1. Each slot's price comes from the rate whose window contains it (see the lookup in [venues](../models/venues.md#priceoverride-price_overrides)): base price, or the override, or base × exchange rate.
2. `Session.price` is the sum.
3. Find the discount that applies (right club, right court or none, right user or none, enough bookings, valid now) and compute `discount_amount`. An `amount_off` is in base currency and is converted like a price.
4. Rentals are priced the same way, per item.

## 3. Book

In **one database transaction**:

1. Lock the court row (`Court.objects.select_for_update().get(pk=...)`). This makes two people booking the same court wait for each other.
2. Re-check that no non-cancelled session overlaps the requested time. If one does, reject.
3. Create the `Session` (`status=confirmed` for a plain court booking) with the price snapshot.
4. Create the booker's `SessionParticipant` with `status=accepted`.
5. Create a `SessionRental` (`requested`) per rental item.

The lock is what prevents double-booking; the overlap check alone is not enough when two requests arrive together.

## 4. Invite others

- Add a `SessionParticipant` (`invited`) per friend, or one per active member when booking for a group (set `Session.group`).
- Each invitee sets their row to `accepted` or `declined`.
- For a group session, a session card is posted in the group chat ([chat](chat.md)).

## 5. Check in

At the court, each participant sets `checked_in_at` on their own row. A coach does it for shadow players.

When the participant checking in is the **booker**, in the same transaction call `billing.services.record_payments(session)`.

## 6. Record payments

`record_payments` must do nothing if the session already has payments. Otherwise it creates:

1. **Court fee** (if the session has a court): payer = booker, payee = the club, amount = `price − discount_amount` + approved rentals.
2. **Coach fee** (if `coach_fee` > 0): to the coach, from `coach_fee_payer`, or split equally across accepted team members when that is empty.

Each payment gets `platform_fee = amount × rate / 100`, where the rate comes from the commission lookup in [billing](../models/billing.md#lookup) for that payee. `method` and `paid_at` stay empty: the row records money that is due.

When the money is handed over, the payee marks the row paid: `method=offline`, `paid_at=now`.

## 7. Afterwards

- Attendance: accepted participants with no `checked_in_at` once the session has ended are no-shows.
- Each participant is prompted to log RPE ([wellness](wellness.md)), which also unlocks the video ([recordings](recordings.md)).
- The owner sees the session in schedule, revenue and attendance ([owner-setup](owner-setup.md)).

## Cancelling

Set `Session.status = cancelled`. The slot becomes free. Cancellation fees and refunds are not designed.

## Open points

- Whether court bookings confirm instantly (assumed here) or need owner approval.
- How early check-in opens.
- Who may mark a payment paid (assumed: the payee) and whether a payer can dispute it.
- Whether discounts stack.
- Rental stock checking.

# Flow: owner sets up a club

**Status: planned.** Schema exists; endpoints and logic are not built.

Models: [User](../models/accounts.md), [Club, ClubCurrency, Court, CourtRate, Equipment, PriceOverride, Discount, ClubMember](../models/venues.md), [Session](../models/bookings.md), [Payment](../models/billing.md).

## 1. Create the club

1. A registered user creates a `Club` with themselves as `owner`, a `timezone` and a base `currency`.
2. For each extra currency they accept, add a `ClubCurrency` with their exchange rate.

```
User ──owner──> Club ──> ClubCurrency (LBP @ 89500)
```

## 2. Add courts

1. Create a `Court` per physical court with its `slot_minutes`.
2. Attach the sports it supports (`court.sports`). A multi-sport court lists several.

## 3. Set hours and prices

One `CourtRate` per court, weekday and price window. Example for a weekday: 09:00–17:00 at 50, 17:00–00:00 at 70.

- No row for a weekday = closed that day.
- Windows on the same court and weekday must not overlap.
- Optional: a `PriceOverride` per rate and currency to hand-set the price instead of converting.

## 4. Add equipment

`Equipment` rows for what comes with a court (free) and what can be rented (priced). Leave `court` empty for items shared across the club. Optional `PriceOverride` per item and currency.

## 5. Day-to-day

| Owner wants to | Reads or writes |
|---|---|
| See the schedule | `Session` rows for their courts in a date range, excluding `cancelled` |
| Close a court for a day | A `Session` with `status=blocked` over that time |
| Approve a rental | `SessionRental.status` → `approved` |
| See revenue | `Payment` where `club` is theirs, summed per `currency`; net = `amount − platform_fee` |
| See what they owe the platform | `Payment.platform_fee` where `settled_at` is empty |
| See customers | Distinct `Session.booked_by` on their courts |
| Repeat-customer rate | Share of those customers with two or more non-cancelled sessions |
| See attendance | `SessionParticipant.checked_in_at` per session |
| Send an offer to a player | A `Discount` with `user` set, plus a message in the inquiry chat |
| Reward frequent players | A `Discount` with `min_bookings` |
| Discount one time slot | A `Discount` with `court` and a narrow `starts_at`–`ends_at` |
| Take on a coach | `ClubMember` with `role=coach`, `pending` → `active` |

## Access rules

- Only `club.owner` may change the club and everything under it.
- Players can read active courts, rates, equipment and currently valid discounts that apply to them.

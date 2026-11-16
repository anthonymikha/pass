# Flow: owner sets up a club

**Status: planned.** Schema exists; endpoints and logic are not built. Rules: [clubs-and-courts](../logic/clubs-and-courts.md).

Models: [User](../models/accounts.md), [Club, ClubCurrency, Court, CourtRate, CourtBlockout, Equipment, PriceOverride, Discount, ClubMember](../models/venues.md), [Session](../models/bookings.md), [Payment](../models/billing.md).

## Setting up

| Step | What the owner does | Rules |
|---|---|---|
| 1. Create the club | Name, timezone, base currency | [CLUB-1 to CLUB-4](../logic/clubs-and-courts.md#club) |
| 2. Accept other currencies | One row per currency with the club's exchange rate | [CLUB-5 to CLUB-7](../logic/clubs-and-courts.md#accepted-currencies) |
| 3. Add courts | Slot length and sports | [CLUB-8 to CLUB-10](../logic/clubs-and-courts.md#courts) |
| 4. Set hours and prices | Rate windows per weekday; optional overrides per currency | [CLUB-11 to CLUB-13](../logic/clubs-and-courts.md#rates-open-hours-and-prices), [CLUB-20, CLUB-21](../logic/clubs-and-courts.md#price-overrides) |
| 5. Add equipment | Included and rentable items | [CLUB-18, CLUB-19](../logic/clubs-and-courts.md#equipment) |
| 6. Add people | Staff, registered players; approve coaches | [CLUB-25 to CLUB-29](../logic/clubs-and-courts.md#club-members) |

```
User ──owner──> Club ──> ClubCurrency (LBP @ 89500)
                  └────> Court ──> CourtRate, CourtBlockout, Equipment
```

## Day to day

| Owner wants to | Rules |
|---|---|
| See the schedule | [RPT-1](../logic/owner-reports.md) |
| Close a court once or repeatedly | [CLUB-15 to CLUB-17](../logic/clubs-and-courts.md#closures-court-block-outs) |
| See who still owes money; mark a payment received | [RPT-2](../logic/owner-reports.md), [PAY-20, PAY-21](../logic/check-in-and-payments.md#marking-paid) |
| Check in a booker who does not use the app | [PAY-3](../logic/check-in-and-payments.md) |
| Approve a rental | [BOOK-40, BOOK-41](../logic/booking.md#rentals) |
| Revenue, customers, repeat rate, attendance | [RPT-3 to RPT-6](../logic/owner-reports.md) |
| Run an offer (targeted, frequent-player, time slot) | [CLUB-22 to CLUB-24](../logic/clubs-and-courts.md#offers-the-discounts-table), [DSC-1 to DSC-6](../logic/discounts.md) |
| Discount one booked session | [DSC-10 to DSC-14](../logic/discounts.md#one-off-session-discount) |
| Answer inquiries | [CHAT-5 to CHAT-8](../logic/chat.md) |

Who may do what (owner versus staff): [ACC-5, ACC-6](../logic/access-and-roles.md#default-rules). What the public sees: [CLUB-30 to CLUB-32](../logic/clubs-and-courts.md#public-search-and-detail).

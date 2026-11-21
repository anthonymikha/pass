# Flow: book a court, play, pay

**Status: built** (`backend/bookings/`, `backend/billing/`; API pages [bookings](../api/bookings.md), [billing](../api/billing.md)). Step 9's RPE reminder arrives with the scheduler (NOTE-31). The rules are in the logic pages linked from each step; this page only tells the journey in order.

Models: [Court, CourtRate, ClubCurrency, PriceOverride, Equipment, Discount](../models/venues.md), [Session, SessionParticipant, SessionRental](../models/bookings.md), [Payment, CommissionRate](../models/billing.md), [Message](../models/chat.md).

```
CourtRate ─┐
Session ───┼─> free slots ─> price ─> Session + SessionParticipant (+ SessionRental)
Discount ──┘                                   │
                         participants check in; billed a day later
                                               │
                              CommissionRate ─> Payment(s)
```

| Step | What happens | Rules |
|---|---|---|
| 1. Find free slots | The player picks a court and a date and sees free slots with prices | [AVL-1 to AVL-12](../logic/court-availability.md) |
| 2. Price it | Prices in the chosen currency, then the best offer | [PRC-4 to PRC-6](../logic/pricing-and-currency.md), [DSC-1 to DSC-6](../logic/discounts.md) |
| 3. Book | One transaction with the court locked; confirmed at once | [BOOK-2 to BOOK-9](../logic/booking.md) |
| 4. Invite others | Friends or the whole group; each accepts or declines | [BOOK-10 to BOOK-17](../logic/booking.md#invites) |
| 5. Rentals | The club side approves or declines, with a stock check | [BOOK-40 to BOOK-42](../logic/booking.md#rentals) |
| 6. Check in | From 30 minutes before start; the booker, coach or club side can check others in; the first check-in freezes the session | [PAY-1 to PAY-8](../logic/check-in-and-payments.md) |
| 7. Billing | A day after the end: court fee and coach fee rows, paid in full or split among attendees, due, with the platform fee | [PAY-9 to PAY-16](../logic/check-in-and-payments.md#creating-payments), [COM-1](../logic/commission.md) |
| 8. Tick off | The payer may tick "I paid" (declared paid, a claim); the payee side ticks each row received, which alone makes it paid. Both see both ticks (*planned, review 2026-11-20*) | [PAY-20 to PAY-27](../logic/check-in-and-payments.md#marking-paid) |
| 9. Afterwards | RPE reminder, video unlock, owner reports | [NOTE-31](../logic/notifications.md), [WEL-1](../logic/wellness.md), [REC-20](../logic/recordings.md), [RPT-1 to RPT-6](../logic/owner-reports.md) |

Cancelling: [BOOK-50, BOOK-51](../logic/booking.md#cancelling). A one-off discount on one session: [DSC-10 to DSC-14](../logic/discounts.md#one-off-session-discount).

Worked examples with real numbers: [pricing](../logic/pricing-and-currency.md#worked-example), [discounts](../logic/discounts.md#worked-example), [payments](../logic/check-in-and-payments.md#worked-examples).

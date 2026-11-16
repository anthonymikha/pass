# Discounts (DSC)

**Status: planned.** Two ways a session's court price is reduced:

1. **Offers**: rows in `discounts` that the system applies automatically when a session is booked.
2. **One-off session discount**: the owner reduces the price of one specific session by hand.

A session carries at most one reduction. It is stored on the session: `discount_amount` (the amount taken off, in the session currency) and `discount` (the offer used, or **empty**).

> **Owner note 18 (2026-11-16):** "for a specific session we should attach the discount to the session id and it can be null." Read as: a discount meant for one session is attached to that session, and the link to an offer is nullable. Built with the existing columns: `sessions.discount_amount` holds the amount and `sessions.discount` stays empty. A `discounts.session` column was not added because `venues` may not point at `bookings` (dependency rule). **Confirmed by the owner at review, 2026-11-16.**

## Offers: which one applies

**DSC-1.** When session S is priced (BOOK-8, BOOK-21, BOOK-30), an offer D is **eligible** when all hold:
1. `D.club` is the club of S's court;
2. `D.court` is empty or is S's court;
3. `D.user` is empty or is S's booker;
4. `D.min_bookings` is empty, or the booker's **booking count** at the club (DSC-2) is ≥ `D.min_bookings`;
5. `D.starts_at ≤ S.starts_at < D.ends_at`: the offer window is about **when the session is played**, not when it is booked.

Sessions with no court (PRC-7) get no offer.

**DSC-2.** The **booking count** of user U at club K, at the moment of booking, is the number of sessions with `booked_by = U`, a court of K, `status` not `cancelled`, and `starts_at` before now. Future bookings do not count, so booking ten future slots does not unlock a frequent-player offer. The session being booked is never counted.

**DSC-3.** The **amount** of an eligible offer D for S, in S's currency C:
- `percent_off` set: `round_money(S.price × percent_off / 100, C)`;
- `amount_off` set: if C is base, `amount_off`; else `round_money(amount_off × exchange_rate of C, C)`. Price overrides do not apply to offers.
- In both cases the amount is capped at `S.price`, so a price never goes below 0.

**DSC-4.** Offers **never stack**. The offer with the largest amount (DSC-3) is applied; on a tie, the one with the lowest `id`. If no offer is eligible, or the best amount is 0, then `discount` is empty and `discount_amount` is 0.

**DSC-5.** The chosen offer and amount are copied to `sessions.discount` and `sessions.discount_amount`. Editing or deleting the offer later never changes the session. Deleting an offer empties `sessions.discount` and keeps `discount_amount`.

**DSC-6.** Discounts reduce the court price only: never rentals, never the coach fee.

## One-off session discount

**DSC-10.** Who may: the club owner of the session's court. Not staff (pricing is configuration, ACC-6).

**DSC-11.** Input: `amount` in the session's currency, ≥ 0, ≤ `S.price`, decimals as in GEN-17.

**DSC-12.** Preconditions: S has a court of the owner's club; `status` is `requested` or `confirmed`; S has no payments yet (the booker has not checked in).

**DSC-13.** Effect: `discount_amount = amount`, `discount` = empty. It **replaces** whatever offer was applied (no stacking, DSC-4). An amount of 0 removes the reduction. The offer is not re-applied later, even if the one-off discount is removed.

**DSC-14.** Errors: session not on the owner's club `404`; already has payments `400 already_payable`; cancelled `400 session_cancelled`; amount above price or below 0 `400` on `amount`.

## Worked example

Session from [pricing](pricing-and-currency.md#worked-example): booker Rana, Court 1, Monday 2027-01-11 16:00 local, EUR, `price = 111.17`. Rana has 4 past bookings at Hoops.

| Offer | Fields | Eligible? | Amount in EUR |
|---|---|---|---|
| #7 "January promo" | club-wide, 10%, 2027-01-01 to 2027-02-01 | yes | 111.17 × 10% = 11.117 → **11.12** |
| #8 "Loyalty" | `min_bookings = 5`, 15% | no, 4 < 5 | |
| #9 "Welcome back Rana" | `user = Rana`, `amount_off` 10.00 USD | yes | 10 × 0.923457 = 9.23457 → **9.23** |
| #10 "Court 2 happy hour" | `court = Court 2` | no, wrong court | |

Best is #7: `discount = 7`, `discount_amount = 11.12`. Court amount due later: 111.17 − 11.12 = 100.05 (+ rentals, PAY-11).

If the owner then gives Rana a one-off 20.00 EUR off this session: `discount` empty, `discount_amount = 20.00`; offer #7 no longer applies.

## Limits (settled at the owner's review on 2026-11-16)

**DSC-7.** An offer applies any number of times inside its window, to every booker it is eligible for (DSC-1). There is no usage cap per offer or per user.

**DSC-8.** Offers cannot be limited to club members. (Add a `members_only` flag if owners ask.)

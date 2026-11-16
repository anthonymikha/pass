# Pricing and currency (PRC)

**Status: planned.** How a court slot or a rental item gets a price in the currency the booker chose.

## Accepted currencies

**PRC-1.** A club accepts its base currency (`clubs.currency`) and every currency listed in its `club_currencies`. Any other currency: `400 currency_not_accepted`.

**PRC-2.** `club_currencies.exchange_rate` means *units of that currency per 1 unit of base*. It is set by the owner, must be greater than 0, and has at most 6 decimal places. There is no market rate and no FX table.

**PRC-3.** Prices typed by the owner are always in base: rate prices, rental prices, `amount_off` on offers. The only exception is a `price_overrides` row, which is a price typed directly in one non-base currency.

## Unit price lookup

**PRC-4.** The unit price of a court rate row R (or a rentable equipment item E) in currency C:

1. C is the base currency: the base price (`R.price` or `E.rental_price`), unchanged.
2. Otherwise, if a `price_overrides` row exists for (R or E, C): that row's `price`, unchanged.
3. Otherwise: `round_money(base price × exchange_rate of C, C)` (GEN-16).

**PRC-5.** A session's court **price** is the sum of the unit prices of its slots, each rounded on its own before summing (rule PRC-4 step 3 rounds per slot). The price is computed and stored when the session is booked or confirmed; later changes to rates, exchange rates or overrides never change it.

**PRC-6.** A rental line's **price** = unit price (PRC-4, for the equipment item) × quantity. Rental prices are per booking, not per slot. Stored on `session_rentals.price` when the booking is made.

**PRC-7.** A training session with no court has court price 0 and no rentals.

## Worked example

Club "Hoops", timezone `Asia/Beirut` (UTC+2 in January), base **USD**. Accepted: **EUR** at 0.923457, **LBP** at 89 500.

Court 1, `slot_minutes = 60`. Monday rates: 09:00–17:00 at 50.00, 17:00–00:00 at 70.00. Override: evening rate in EUR = 65.00.
Rentable: "Shooting machine", `rental_price` 15.00, no override.

Booking Monday 2027-01-11, 16:00–18:00 local (14:00–16:00 UTC), two slots:

| | USD | EUR | LBP |
|---|---|---|---|
| 16:00 slot (day rate 50.00) | 50.00 | 50.00 × 0.923457 = 46.17285 → **46.17** | 50 × 89 500 = **4 475 000** |
| 17:00 slot (evening rate 70.00) | 70.00 | override **65.00** | 70 × 89 500 = **6 265 000** |
| **Session price** | **120.00** | **111.17** | **10 740 000** |
| Shooting machine × 1 | 15.00 | 15 × 0.923457 = 13.851855 → **13.85** | **1 342 500** |

## Edge cases

**PRC-10.** An owner who changes an exchange rate or an override affects only bookings made afterwards.

**PRC-11.** Removing an accepted currency (CLUB-7) deletes its overrides; sessions already booked in it keep their snapshot and are paid in it.

**PRC-12.** A rate price of 0 is allowed (free court time); the slot then costs 0 in every currency unless an override for that currency says otherwise.

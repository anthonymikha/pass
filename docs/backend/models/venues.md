# venues models

Source: [backend/venues/models.py](../../../backend/venues/models.py). Tables: `sports`, `clubs`, `club_members`, `club_currencies`, `courts`, `court_sports`, `court_rates`, `court_blockouts`, `equipment`, `price_overrides`, `discounts`.

Everything a court or club owner configures.

## Sport (`sports`)

A lookup list (`name`, unique). Managed in the Django admin. Used by courts, groups and sessions.

## Club (`clubs`)

The business that owns courts. A person with a single court is a club with one court.

| Field | Meaning |
|---|---|
| `owner` | The user who controls the club |
| `name`, `address`, `latitude`, `longitude` | Listing and search |
| `timezone` | IANA name. All of the club's opening hours are in this timezone |
| `currency` | **Base currency.** Every rate, rental price and `amount_off` discount is entered in it |

A club with payments or an owner cannot be removed casually: deleting the owner is blocked.

## ClubMember (`club_members`)

Links a user to a club, with status `pending` or `active`. Unique per (club, user, role), so one person can be both a coach and a subscribed player at the same club.

| `role` | Meaning |
|---|---|
| `coach` | Affiliated coach. A coach can belong to many clubs, or none (freelancer) |
| `staff` | Can answer the club's inquiry chats |
| `player` | Registered at the club or holding a subscription |

`expires_on` is the end of a subscription; empty means no expiry. A membership counts when `status=active` and `expires_on` is empty or not yet passed ([ACC-2](../logic/access-and-roles.md)). Adding and approving members: [CLUB-25 to CLUB-29](../logic/clubs-and-courts.md#club-members).

- The owner is not a member row; ownership is `clubs.owner`.
- Booking a court does **not** need a membership. The `player` role records registration only; what a subscription costs or includes is not modelled.

## ClubCurrency (`club_currencies`)

Other currencies the club accepts, each with a club-set `exchange_rate` meaning *units of this currency per 1 unit of base*.

```python
club = Club.objects.create(owner=o, name="Hoops", timezone="Asia/Beirut", currency="USD")
ClubCurrency.objects.create(club=club, currency="LBP", exchange_rate=Decimal("89500"))
```

The base currency itself needs no row.

## Court (`courts`)

| Field | Meaning |
|---|---|
| `club` | Owner club |
| `name`, `description` | |
| `slot_minutes` | Length of one bookable slot. Bookings are made in whole slots |
| `is_active` | Hide from search and booking without deleting |
| `sports` | Many-to-many (`court_sports`). A court can host several sports; each session picks one |

```python
court = Court.objects.create(club=club, name="Court 1", slot_minutes=60)
court.sports.set([basketball, volleyball])
```

## CourtRate (`court_rates`)

**Opening hours and prices in one table.** A row means "this court is open on this weekday in this window, at this price per slot".

| Field | Meaning |
|---|---|
| `weekday` | 0 = Monday |
| `start_time`, `end_time` | Club timezone. **`end_time` 00:00 means end of day** |
| `price` | Per slot, base currency |

```python
# Mondays: 50 from 09:00 to 17:00, 70 from 17:00 to midnight
CourtRate.objects.create(court=court, weekday=0, start_time=time(9),  end_time=time(17), price=50)
CourtRate.objects.create(court=court, weekday=0, start_time=time(17), end_time=time(0),  price=70)
```

- Open hours are the union of a court's rows. No row for a weekday means closed that day.
- Windows for the same court and weekday must not overlap. This is checked in code, not by the database ([CLUB-12](../logic/clubs-and-courts.md#rates-open-hours-and-prices)). How windows become slots: [AVL-1 to AVL-6](../logic/court-availability.md).
- Rates repeat weekly only. Closures, including monthly ones, are `CourtBlockout` rows.

## CourtBlockout (`court_blockouts`)

Times a court cannot be booked: holidays, maintenance, private events. Same fields as [`UserBlockout`](accounts.md#blockout-shared-shape-and-userblockout-user_blockouts), with `court` instead of `user`; times are in the club's timezone.

```python
CourtBlockout.objects.create(court=court, starts_on=date(2027, 1, 1), start_time=time(0), end_time=time(0), reason="New Year")
CourtBlockout.objects.create(court=court, starts_on=date(2027, 1, 5), start_time=time(8), end_time=time(10), repeat="monthly", reason="Floor maintenance")
```

Bookable time = `court_rates` windows − `court_blockouts` − sessions that are not cancelled.

## Equipment (`equipment`)

Amenities, included gear and rentable gear.

| `court` | `rental_price` | Meaning |
|---|---|---|
| empty | any | Shared by all the club's courts |
| set | any | Tied to that one court |
| any | empty | Included for free (e.g. 3 basketballs) |
| any | set | Rentable on request, price per booking in base currency |

`quantity` is how many the club has.

```python
Equipment.objects.create(club=club, court=court, name="Basketballs", quantity=3)                 # free, this court
Equipment.objects.create(club=club, name="Shooting machine", quantity=1, rental_price=15)        # rentable, shared
```

What a player can see for a court: `Equipment.objects.filter(Q(court=court) | Q(court__isnull=True), club=court.club)`.

## PriceOverride (`price_overrides`)

A hand-set price in a non-base currency, for one court rate **or** one equipment item (exactly one must be set). One row per target and currency.

Price lookup, conversion and rounding: [PRC-1 to PRC-6](../logic/pricing-and-currency.md).

```python
PriceOverride.objects.create(court_rate=evening_rate, currency="LBP", price=Decimal("6000000"))
```

## Discount (`discounts`)

One table for every kind of offer. Empty fields widen the offer.

| Field | Meaning when set |
|---|---|
| `court` | Only this court (empty = whole club) |
| `user` | Only this player, a targeted retention offer (empty = everyone) |
| `min_bookings` | Only players with at least this many bookings at the club |
| `percent_off` / `amount_off` | The reduction; `amount_off` is in base currency |
| `starts_at`, `ends_at` | When the offer is valid |
| `message` | Text shown or sent to the player |

```python
# 20% off Court 1 this week for everyone
Discount.objects.create(club=club, court=court, percent_off=20, starts_at=a, ends_at=b)
# 10 off for players with 10+ bookings
Discount.objects.create(club=club, min_bookings=10, amount_off=10, starts_at=a, ends_at=b)
```

The discount used is copied onto the session (`discount`, `discount_amount`), so editing or deleting the offer later does not change past bookings. Which offer applies (never stacked, the window is about play time) and one-off discounts on a single session: [discounts](../logic/discounts.md).

## Used together with

- `bookings.Session.court` / `.discount`, `bookings.SessionRental.equipment`.
- `billing.Payment.club`, `billing.CommissionRate.club`.
- `chat.Chat.club` for inquiries.
- Full journey: [owner-setup](../flows/owner-setup.md).

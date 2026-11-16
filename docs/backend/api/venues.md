# API: venues

**Status: built and tested.** Code: [views](../../../backend/venues/views.py), [serializers](../../../backend/venues/serializers.py), [services](../../../backend/venues/services.py), [tests](../../../backend/venues/tests.py). Rules: [clubs-and-courts](../logic/clubs-and-courts.md). Same conventions as [accounts](accounts.md) (token header, error shapes, paging).

## Who may call

- **Public (no token):** `GET /api/clubs/` (search) and `GET /api/courts/<id>/` (court detail). Everything else needs a token.
- **Writes** are the club owner's only. A user who cannot see the club or court gets `404`; one who can see it but does not own it (staff, coach, player, anyone) gets `403`.
- **A club is visible** to its owner, to anyone with a membership row in it, and to everyone once it has an active court. An inactive court is visible to its owner only.
- **Configuration reads** (currencies, rates, closures, equipment, overrides, one row by id) are the owner's too: others get `403`. The public reads the same data through court detail.

## Endpoints

| Method | Path | Who | Body / notes | Success |
|---|---|---|---|---|
| GET | `/api/clubs/` | public | `sport` (id), `q`, `lat` + `lng` + `radius_km` (1-200, default 25) | `200` page of clubs |
| POST | `/api/clubs/` | any user | `name`, `timezone`, `currency`, optional `address`, `latitude`, `longitude` | `201` club |
| GET, PATCH | `/api/clubs/<id>/` | visible; PATCH owner | `currency` cannot change (`400 base_currency_fixed`) | `200` |
| GET, POST | `/api/clubs/<id>/currencies/` | owner | `currency`, `exchange_rate` | `201`; `400 currency_exists` |
| GET, PATCH, DELETE | `/api/currencies/<id>/` | owner | PATCH: `exchange_rate`. DELETE also deletes the overrides in that currency | `200` / `204` |
| GET, POST | `/api/clubs/<id>/courts/` | visible; POST owner | `name`, `description`, `slot_minutes`, `sports` (ids), `is_active`. Owner sees inactive courts too | `201` |
| GET | `/api/courts/<id>/` | public | court detail (below); inactive `404` | `200` |
| PATCH, DELETE | `/api/courts/<id>/` | owner | DELETE: `400 court_in_use` if it ever had a session | `200` / `204` |
| GET, POST | `/api/courts/<id>/rates/` | owner | `weekday` 0-6, `start_time`, `end_time`, `price` (base) | `201`; `400 rate_overlap` |
| GET, PATCH, DELETE | `/api/rates/<id>/` | owner | DELETE also deletes its overrides | `200` / `204` |
| GET, POST | `/api/courts/<id>/closures/` | owner | `starts_on`, `start_time`, `end_time`, `repeat`, `repeat_until`, `reason` | `201` with `conflicts` |
| GET, PATCH, DELETE | `/api/closures/<id>/` | owner | PATCH answers with `conflicts` | `200` / `204` |
| GET, POST | `/api/clubs/<id>/equipment/` | owner | `name`, `quantity` >= 1, `court` (optional), `rental_price` (optional, base) | `201` |
| GET, PATCH, DELETE | `/api/equipment/<id>/` | owner | DELETE: `400 equipment_in_use` if rented | `200` / `204` |
| GET, POST | `/api/clubs/<id>/overrides/` | owner | `court_rate` or `equipment` (exactly one), `currency`, `price` | `201`; `400 currency_not_accepted`, `400 override_exists` |
| GET, PATCH, DELETE | `/api/overrides/<id>/` | owner | PATCH: `price` only | `200` / `204` |
| GET, POST | `/api/clubs/<id>/offers/` | GET: any user who sees the club; POST owner | GET as owner: every offer. GET as anyone else: the offers shown to a player, `?court=<id>` adds that court's | `200` / `201` |
| PATCH, DELETE | `/api/offers/<id>/` | owner | | `200` / `204` |
| GET | `/api/clubs/<id>/members/` | owner, and anyone with a current membership | owner sees all rows; others only current ones; anyone else `404` | `200` |
| POST | `/api/clubs/<id>/members/` | owner | `email`, `role` (`staff` or `player`), `expires_on` (today or later) | `201`; `400 user_not_found`, `400 member_exists` |
| POST | `/api/clubs/<id>/coach-requests/` | a coach | none | `201` pending row; `400 member_exists` |
| PATCH | `/api/members/<id>/` | owner | `expires_on` (null clears it) | `200` |
| POST | `/api/members/<id>/approve/` | owner | pending coach becomes active; repeat is `200` | `200` |
| DELETE | `/api/members/<id>/` | owner, or the member (leave) | also how the owner rejects a pending coach | `204` |

Lists are paginated (50 a page). Money is a decimal string with 3 places (`"50.000"`). Rates, `rental_price` and `amount_off` are typed in the club's base currency and may not have more decimals than it uses (`400` on that field); an override's `price` follows its own currency.

## Search result

```json
{"id": 1, "name": "Hoops", "address": "Hamra", "latitude": "33.893800", "longitude": "35.501800",
 "timezone": "Asia/Beirut", "currency": "USD", "distance_km": 11.1, "courts": [{"id": 1, "name": "Court 1"}]}
```

`distance_km` is `null` when no location was sent. `courts` are the active ones: they give a visitor the ids for court detail.

## Court detail

```json
{"club": {"id": 1, "name": "Hoops", "address": "", "latitude": null, "longitude": null, "timezone": "Asia/Beirut",
          "currency": "USD", "currencies": [{"id": 1, "currency": "EUR", "exchange_rate": "0.923457"}]},
 "court": {"id": 1, "name": "Court 1", "description": "", "slot_minutes": 60, "is_active": true,
           "sports": [{"id": 1, "name": "Basketball"}]},
 "rates": [{"id": 1, "weekday": 0, "start_time": "09:00:00", "end_time": "17:00:00", "price": "50.000"}],
 "equipment": {"included": [{"id": 1, "name": "Basketballs", "quantity": 3, "court": 1, "rental_price": null}],
               "rentable": [{"id": 2, "name": "Shooting machine", "quantity": 1, "court": null, "rental_price": "15.000"}]}}
```

Prices are in base only. Price lookup in other currencies is not built yet.

## Closure conflicts

Creating or changing a closure never cancels anything. The response adds `conflicts`: the court's non-cancelled sessions that start after now and overlap an occurrence, as `{id, status, starts_at, ends_at}`. The app shows them so the owner can cancel by hand.

## Offers and pushes

Creating an offer with `user` set sends that user one `offer` push after the request commits (title "New offer from <club>", body the offer's `message`, data `{id, type: "offer"}`). Changing an offer sends nothing.

## Not built

Price lookup and free slots (PRC-4 onwards, AVL-10), applying offers to bookings (DSC), a list of the owner's own clubs (search shows only clubs with an active court), cancelling sessions from a closure's conflicts (BOOK-50).

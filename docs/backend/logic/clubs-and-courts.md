# Clubs and courts (CLUB)

**Status: built** (`backend/venues/`, API page [venues](../api/venues.md)). PRC-1 to PRC-3 are built here; the price lookup is built with booking. What an owner configures, and what the public can see. Every write on this page is by the **club owner** only (ACC-5) unless it says otherwise. Another user gets `404` for clubs they cannot see in that role, `403` on public clubs they can see but do not own.

## Club

**CLUB-1.** Who may create: any user, who becomes `owner`. Input: `name` (1–255), `timezone` (valid IANA name), `currency` (GEN-14), optional `address`, `latitude` (−90 to 90), `longitude` (−180 to 180).

**CLUB-2.** The owner may change `name`, `address`, `latitude`, `longitude`, `timezone`. A timezone change affects how rates and closures are read from then on (existing sessions keep their UTC times).

**CLUB-3.** The base `currency` cannot be changed after the club is created (every base price would change meaning). Error: `400 base_currency_fixed`.

**CLUB-4.** Clubs are not deleted through the API. Make courts inactive instead (CLUB-9).

## Accepted currencies

**CLUB-5.** Add: `currency` (GEN-14, not the base, not already listed: `400 currency_exists`), `exchange_rate` (> 0, ≤ 6 decimals).

**CLUB-6.** Change `exchange_rate`: affects later bookings only (PRC-10).

**CLUB-7.** Remove: deletes the row and the club's `price_overrides` in that currency. Sessions already in that currency keep it (PRC-11).

## Courts

**CLUB-8.** Create: `name` (1–255), optional `description`, `slot_minutes` (a multiple of 5 from 15 to 480), `sports` (at least one sport id), `is_active` (default true).

**CLUB-9.** Change any of those fields. Changing `slot_minutes` does not touch existing sessions; slots are built with the new length from then on. A rate window shorter than the new slot length then offers no slots.

**CLUB-10.** Delete: allowed only if the court has no sessions at all; otherwise `400 court_in_use` (use `is_active = false`). Deleting removes its rates, closures, court-tied equipment, overrides of those rates and items, and offers tied to the court.

## Rates (open hours and prices)

**CLUB-11.** A rate row: `weekday` 0–6, `start_time`, `end_time` (GEN-11: `end_time` after `start_time`, or `00:00`), `price` ≥ 0 in base with at most the base's minor units (GEN-17). Times must be on a 5-minute boundary. A window shorter than `slot_minutes` is allowed but offers nothing (AVL-2).

**CLUB-12.** Windows on the same court and weekday may not overlap (touching is fine). `00:00` as `end_time` counts as 24:00 for this check. Error: `400 rate_overlap`.

**CLUB-13.** Changing or deleting a rate affects later bookings only. Deleting a rate deletes its overrides.

## Closures (court block-outs)

**CLUB-15.** A closure: `starts_on`, `start_time`, `end_time` (GEN-11), `repeat` (`none`/`daily`/`weekly`/`monthly`), optional `repeat_until` (≥ `starts_on`), optional `reason`. Pattern and occurrence: AVL-8.

**CLUB-16.** Creating or changing a closure never cancels sessions. The response lists the **conflicts**: non-cancelled sessions on that court starting after now that overlap an occurrence (checked occurrence by occurrence with AVL-8). The owner decides whether to cancel them (BOOK-50).

**CLUB-17.** Change or delete a closure at any time.

## Equipment

**CLUB-18.** Create or change: `name`, `quantity` ≥ 1, optional `court` (must be a court of this club; empty = shared by all its courts), optional `rental_price` ≥ 0 in base (empty = included for free).

**CLUB-19.** Delete: allowed only if no rental row uses it; otherwise `400 equipment_in_use`. Setting `rental_price` to empty does not affect rentals already made.

## Price overrides

**CLUB-20.** Create: exactly one of `court_rate` (a rate of this club) or `equipment` (a rentable item of this club), `currency` (an accepted non-base currency of this club: else `400 currency_not_accepted`), `price` ≥ 0 with that currency's minor units. One per target and currency: `400 override_exists`.

**CLUB-21.** Change `price` or delete at any time; later bookings only.

## Offers (the `discounts` table)

**CLUB-22.** Create: exactly one of `percent_off` (> 0 and ≤ 100, 2 decimals) or `amount_off` (> 0, base minor units); `starts_at` < `ends_at`; optional `court` (of this club), optional `user` (an active, non-shadow user), optional `min_bookings` (≥ 1), optional `message` (≤ 1000 characters). Errors per field, `400`.

**CLUB-23.** Change or delete at any time. Sessions keep their snapshot (DSC-5).

**CLUB-24.** When an offer with `user` set is created, that user is notified (NOTE-20) with the offer's `message`.

## Club members

**CLUB-25.** The owner adds **staff** or **player** by the user's email (exact, case-insensitive): the row is created `active` straight away. `expires_on` optional (today or later). The user must exist, be active, not be the owner. Duplicate (club, user, role): `400 member_exists`. Unknown email: `400 user_not_found`.

**CLUB-26.** A **coach** asks to be affiliated: any user with `is_coach = true` creates a `coach` row for a club, status `pending`. Repeat: `400 member_exists`.

**CLUB-27.** The owner approves a pending coach (`pending` → `active`) or rejects it (row deleted).

**CLUB-28.** The owner may remove any member row. A member may remove their own row (leave).

**CLUB-29.** The owner may change `expires_on` on any member row (empty = no expiry). Expired rows: ACC-2.

| From | To | Who |
|---|---|---|
| (new) | `active` | owner adds staff or player |
| (new) | `pending` | coach asks |
| `pending` | `active` | owner approves |
| `pending` / `active` | (deleted) | owner removes, or the member leaves |

The club side, affiliated coaches and the member themselves may list the club's members; others `404`.

**CLUB-33.** **My clubs.** A signed-in user lists the clubs they own plus the clubs where they have an active, unexpired `staff` or `coach` membership (ACC-1, ACC-2), each with the caller's roles there (`owner`, `staff`, `coach`), sorted by name, paginated. *Decided during build (2026-11-16): a new club has no active court, so search (CLUB-30) cannot show it, and the club side needs a way to reach its clubs.*

## Public search and detail

**CLUB-30.** **Search** (no sign-in needed). Clubs that have at least one active court. Optional filters: `sport` (a club with an active court offering it), `q` (club name contains, case-insensitive), `lat` + `lng` + `radius_km` (1–200, default 25). With a location: keep clubs whose `latitude`/`longitude` are set and within the radius (great-circle distance, Earth radius 6371 km), sorted by distance, and include `distance_km` rounded to 1 decimal. Without a location: sorted by name. Paginated.
<!-- ponytail: distance computed in Python after a bounding-box filter; move to PostGIS only if the club list gets large -->

**CLUB-31.** **Court detail** (no sign-in needed): the club (`id`, `name`, `address`, location, `timezone`, base currency, accepted currencies with rates), the court (`name`, `description`, `slot_minutes`, sports), its rates per weekday, and its visible equipment: items with `court` = this court or empty, split into included (no `rental_price`) and rentable (with price in base). Inactive court: `404`.

**CLUB-32.** **Offers shown to a signed-in player** for a club: offers with `ends_at` after now, `user` empty or the player, `court` empty or a given court. Frequent-player offers are shown with their `min_bookings` whether or not the player qualifies yet.

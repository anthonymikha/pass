# Frontend MVP

**Status: approved 2026-11-24, built 2026-11-25** (widget tests and a local end-to-end run in the browser; not deployed). See *Decided during build* at the end. The first version of this spec (Flutter for web, Android and iOS, Material 3) was approved and built on 2026-11-24, then torn down at the owner's request. A second question round the same day changed the platform to a web app styled after pass_v1 (FE-1, FE-8 to FE-14 below). Everything else carries over.

The MVP is scheduling between players, coaches and courts: players find a court or a coach, see prices, amenities and rentables, and book; coaches answer training requests; the club side sets up courts, prices, amenities and rentables and sees its bookings. Words follow [GLOSSARY.md](../../GLOSSARY.md).

## Decisions

| # | Decision |
|---|---|
| FE-1 | **Progressive web app only.** One Flutter **web** project in `frontend/`. It is tuned for iPhone Safari and is added to the home screen to open full-screen. It also runs in any other browser, Android and desktop included. No App Store or Play Store builds. |
| FE-2 | Every screen exists at every width; only the layout changes. Phone (under 900 px): floating glass tab bar. Desktop (900 px and wider): left sidebar and wider forms, for coaches and the club side working at a desk. |
| FE-3 | Money is USD only. A new club is created with base currency USD (no currency field shown); a coach rate is always USD. The backend keeps its multi-currency support for later. |
| FE-4 | The **coach rate** is per hour ("25 USD / hour"). When a coach confirms a training request, the fee field is prefilled with rate × hours and can be changed. |
| FE-5 | No split fees in the MVP: the booker pays the court fee in full, the requester pays the coach fee in full (the backend defaults). |
| FE-6 | A player cannot see a coach's free times. The player proposes a time; the coach confirms (possibly at another time) or declines (BOOK-20 to BOOK-22). |
| FE-7 | **Amenities** are equipment without a rental price; **rentables** are equipment with one. Club-wide amenities (parking, showers) are club-wide items with quantity 1. No backend change. |
| FE-8 | **No push notifications in the MVP.** The app registers no device. A coach sees a badge with the number of training requests waiting, refreshed when the app opens and when a tab is shown again. |
| FE-9 | **Look: pass_v1's design language.** Its design tokens (`lib/theme/tokens.dart`) and shared widgets (`lib/widgets/`) are copied as they are: Cupertino widgets only, the Inter font bundled, tint `#EC3013`, light and dark, text logo "PASS". The app makes no requests to other hosts. |
| FE-10 | **One account, no role choice.** Tabs: **Book** (find a court or a coach), **Sessions** (my sessions; for a coach also training requests), **Club** (shown only to the club side), **Profile** ("I am a coach" switch, "Create a club", log out). |
| FE-11 | The **club side** (the owner's "managers") is the club owner and the club staff. The owner adds and removes staff by email on the club's Staff screen. |
| FE-12 | **Sports**: a public list `GET /api/sports/` (CLUB-36), and a data migration that adds Padel, Tennis, Basketball and Pickleball when they are missing. More are added in `/admin/`. |
| FE-13 | **Serving, as in pass_v1**: the backend image builds the Flutter web app in a first stage, and Django with WhiteNoise serves it at `/`, with `index.html` for every app URL. Same origin as the API, no new container, no CORS. No service worker cache, so a deploy is seen on the next load. The login token is kept in the browser's local storage. |
| FE-14 | **Deployment, as in pass_v1**: clone on the server, fill `.env`, run the Traefik override (`TRAEFIK_NETWORK=traefik-net`, `TRAEFIK_CERTRESOLVER=mytlschallenge`), and `scripts/autoupdate.sh` polls `origin` and rebuilds the stack when new commits arrive. |

## Screens

Times: court times are shown in the club's timezone (from court detail); everything else in the device's timezone. The API sends UTC.

### Everyone

| Screen | Does | API |
|---|---|---|
| Welcome, sign up, log in | email, password, full name | `POST /api/auth/register/`, `/login/` |
| Forgot password | sends the reset link (the reset itself is the backend's web page) | `POST /api/auth/password-reset/` |
| Profile | name, phone, timezone; "I am a coach" with bio and coach rate; create a club; log out; delete account | `GET`/`PATCH`/`DELETE /api/me/`, `POST /api/auth/logout/`, `POST /api/clubs/` |

### Player (Book and Sessions tabs)

| Screen | Does | API |
|---|---|---|
| Find a court | search clubs by name and sport | `GET /api/clubs/`, `GET /api/sports/` |
| Club | the club's active courts | `GET /api/clubs/<id>/`, `/courts/` |
| Court | description, sports, prices per weekday, amenities, rentables; pick a date and see free slots with prices | `GET /api/courts/<id>/`, `/slots/?date=` |
| Book | pick a run of free slots, sport, rentables with quantity; see the quote; book | `POST /api/sessions/quote/`, `POST /api/sessions/` |
| Find a coach | search by name; profile with bio, coach rate, clubs | `GET /api/coaches/`, `GET /api/users/<id>/` |
| Request training | sport, proposed start and end | `POST /api/training-requests/` |
| My sessions | upcoming and past; status (requested, confirmed, cancelled, completed); court, club, coach, price, coach fee, rentals with their status | `GET /api/me/sessions/`, `GET /api/sessions/<id>/` |
| Cancel / withdraw | cancel a confirmed booking; withdraw a training request | `POST /api/sessions/<id>/cancel/`, `/withdraw/` |

### Coach (Sessions tab)

| Screen | Does | API |
|---|---|---|
| Training requests | requests waiting for an answer; badge count (FE-8) | `GET /api/me/sessions/?status=requested` |
| Confirm | time (prefilled with the proposal), fee (prefilled, FE-4), optional court: pick club, court, then a free slot run | `POST /api/sessions/<id>/confirm/`, the court screens above |
| Decline | | `POST /api/sessions/<id>/decline/` |
| My schedule | confirmed training, as in "My sessions" | `GET /api/me/sessions/` |

### Club side (Club tab)

| Screen | Does | Who | API |
|---|---|---|---|
| My clubs | clubs the caller owns or works at (the tab shows only when there is one) | club side | `GET /api/me/clubs/` |
| Schedule | sessions per day, all courts or one; booker, coach, rentals | club side | `GET /api/clubs/<id>/schedule/` |
| Rentals | approve or decline a requested rentable | club side | `PATCH /api/rentals/<id>/` |
| Cancel a session | | club owner | `POST /api/sessions/<id>/cancel/` |
| Club details | name, address, timezone | club owner | `PATCH /api/clubs/<id>/` |
| Courts | add, edit, deactivate; sports, slot length | club owner | `/api/clubs/<id>/courts/`, `/api/courts/<id>/` |
| Prices | per court: weekday windows with a price per slot | club owner | `/api/courts/<id>/rates/`, `/api/rates/<id>/` |
| Amenities and rentables | name, quantity, one court or all, price (empty = amenity) | club owner | `/api/clubs/<id>/equipment/`, `/api/equipment/<id>/` |
| Staff (FE-11) | add by email, remove | club owner | `/api/clubs/<id>/members/`, `/api/members/<id>/` |

## Backend changes

- **Sports list** (FE-12). New public endpoint `GET /api/sports/`: every sport, `{id, name}`, by name, not paged. Rule CLUB-36 on [clubs-and-courts](../backend/logic/clubs-and-courts.md) (CLUB-34 and CLUB-35 are taken by the unbuilt `wip/local-2026-11-17-audit` branch). A data migration adds the four starting sports.
- **Serving the app** (FE-13). The backend image gets a Flutter build stage (build context becomes the repository root), and Django serves the build at `/` behind `/api/`, `/admin/`, `/static/` and `/account/`.
- **Coach rate unit** (docs only): ACC-21 and the accounts model page say the rate is per hour.

## Not in the MVP

The backend keeps them; the app has no screens for them: push notifications, check-in, payments and billing, chat, wellness, recordings, teams and play groups, friends and invites, offers and discounts, extra currencies and price overrides, closures, coach affiliation with clubs, shadow players, coach-booked training, personal and group availability, avatars, native store builds. Billing still runs on the server; its payments are simply not shown yet.

## Build

- Flutter 3.35.7 run through Docker (`scripts/flutter.sh`, the image `ghcr.io/cirruslabs/flutter:3.35.7` is cached on this machine), as in pass_v1. Packages: `http`, `go_router` (path URLs), `intl`. A hand-written API client in one file. No state-management package: widgets load their data.
- Built with `flutter build web --release --no-web-resources-cdn --pwa-strategy=none`; `web/manifest.json` and `index.html` carry the home-screen name, icons, `display: standalone` and the iOS status-bar and safe-area settings.
- Checks: `flutter analyze`; a widget test for booking and for confirming a training request; the backend test for CLUB-36; the web build driven in a browser against the local stack (book a court, request and confirm training, set up a club).

## Decided during build (2026-11-25)

What the decisions and screens above leave open, settled while building:

- **Packages:** `http`, `go_router`, `timezone` and `web`, not `intl`. Dart has no IANA time zone data, and court times are in the club's zone, so the `timezone` package (its bundled `latest_10y` database, no network) converts them and lists the zones for the time zone pickers. Dates are formatted by hand, as in pass_v1.
- **Token storage:** browser local storage, key `pass_token`. `lib/core/token_store_web.dart` is the one file that touches the browser (`package:web`, an exception to pass_v1's "no `package:web`" rule); tests and other platforms use an in-memory stand-in. The same file reads the device's IANA zone, the default time zone of a new club.
- **401:** any 401 while a token is stored forgets the token and shows Welcome. A stored token is checked once at start with `GET /api/me/`.
- **Money:** amounts are shown cut to the currency's minor units, `"50.000"` USD as `50.00 USD`; the digits are not recomputed. The coach fee prefill (FE-4) is computed exactly in thousandths and rounded half up to the minor units (GEN-16). It follows every change of time until the coach types a fee of their own.
- **Booking:** the quote is asked again on every change of time, sport or rentables; the Book button shows its total and is enabled only with a quote. `409 slot_taken` shows "Just taken" and opens the calendar again. A run of slots is one day's (a run across midnight is not offered in the app). Rentable quantities go from 0 to the item's quantity.
- **Training requests:** the player picks the sport (tags) and a proposed start and end (5-minute steps), device time. The coach confirms with "No court" (time pickers, currency USD) or "On a court": clubs offering the session's sport, then one of their active courts offering it, then a run of free slots; the currency is then the club's base.
- **My sessions:** Upcoming is every session starting from now, soonest first; Past is the 50 most recent, newest first. A coach's training requests have their own section at the top and are left out of the two lists. A request never confirmed shows no court and no costs.
- **Badge (FE-8):** refreshed at start, at sign-in, whenever a tab is tapped, when the app comes back to the foreground, and after the coach confirms or declines.
- **Club tab:** shown when `GET /api/me/clubs/` has a club with role `owner` or `staff`; an affiliated coach alone is not the club side. The schedule's day (arrows and a date capsule opening the calendar) goes from 7 days back to 60 days ahead; Setup is shown to the owner only.
- **Prices:** a new window can be added for several weekdays at once (one rate per weekday, CLUB-11); it starts as Monday to Friday, 08:00 to 22:00. Tapping a window edits or deletes it.
- **Equipment:** one form for both kinds: an empty rental price makes an amenity (FE-7); quantity starts at 1; "For" is all courts or one court.
- **Paths** are in the address bar for every screen, pushed ones included (go_router's `optionURLReflectsImperativeAPIs`), so a refresh keeps the screen: `/welcome`, `/signin`, `/signup`, `/forgot`; `/book`, `/book/clubs/<id>`, `/book/courts/<id>`, `/book/courts/<id>/times?day=`, `/book/courts/<id>/extras?day=&from=&to=`, `/book/courts/<id>/reserve?day=&from=&to=&sport=&rent=` (`from`/`to` once per booking, `rent` as `equipment:quantity`), `/book/booked/<id>[,<id>...]`, `/book/coaches/<id>`; `/sessions`, `/sessions/<id>`, `/sessions/<id>/confirm`; `/club`, `/club/<id>` (schedule), `/club/<id>/setup`, `/club/<id>/setup/courts/new`, `/club/<id>/setup/courts/<court>`, `/club/<id>/setup/equipment`, `/club/<id>/setup/staff`; `/profile`, `/profile/new-club`, `/profile/delete`.
- **Changes to pass_v1's copied widgets**, each a fix: the desktop sidebar is reachable by screen readers (the tab navigator is its own semantics container, a route's barrier hid it); a `ListRow` value is at most 180 px wide and wraps (long values overflowed at phone width); tab and sidebar items no longer repeat their label to screen readers; the nav bar's chat button became an optional `trailing` widget and the profile button opens Profile; the shell rebuilds with the app state (the Club tab and the badge).

## Redesign (2026-11-25, owner's review)

- **Layout from pass_v1, flow from Airbnb.** Book opens on pass_v1's "Book a session / What are we playing?" header; clubs, courts and coaches show as pass_v1's cards and rows (caps column header, chips). A club lists its courts and the coaches who work there; a coach's page is a host profile (avatar, rate and clubs tiles, about, clubs, request). A court is a listing (amenities, rentables, prices) with a glass bar pinned under it: "From <cheapest window> per slot · Pick a time". That opens a sheet with the calendar and the day's free slots; Reserve goes to Confirm (pass_v1's summary card, sport, included amenities, rentables, the quote, a glass "Book now" bar), then pass_v1's tint "Booked" hero.
- **Apple's components.** Dates are picked on an iOS inline calendar (month arrows, weekday letters, the chosen day a tinted disc, today in tint, closed days greyed: days of the week without a price window, and past days). Date and time rows are iOS compact pickers: grey capsules, the date opening the calendar in a sheet, the time opening the wheels (5-minute steps).
- **Sport tags as in Notes:** tap to select, tap again to clear, several at once, "All sports" clears. In search, several sports mean clubs offering all of them (`GET /api/clubs/?sport=1&sport=2`). A session has one sport, so its tags keep exactly one on.
- **Sessions** use pass_v1's schedule rows (a day column, the title and times, the status), requests to the coach tinted.
- Not done: photos of clubs and courts (the backend has none), booking several days at once (one run of slots per booking, as the API books), live glass blur (kept off for scrolling speed, see `Glass`).

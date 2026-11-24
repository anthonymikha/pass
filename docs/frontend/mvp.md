# Frontend MVP

**Status: approved 2026-11-24, being built.** Agreed in a question round on 2026-11-24 and approved the same day. It is built without further questions; anything found during the build is added here first, marked *decided during build*.

The MVP is scheduling between players, coaches and courts: players find a court or a coach, see prices, amenities and rentables, and book; coaches answer training requests; the club side sets up courts, prices, amenities and rentables and sees its bookings. Words follow [GLOSSARY.md](../../GLOSSARY.md).

## Decisions (2026-11-24)

| # | Decision |
|---|---|
| FE-1 | One Flutter project in `frontend/` for web, Android and iOS. All three launch together. |
| FE-2 | Every screen exists on every platform; only the layout changes with the width. The phone is tuned for players, plus a quick look for coaches (training requests) and the club side (today's schedule, rentals). The web is tuned for coaches and the club side (setup and schedule). |
| FE-3 | Money is USD only. A new club is created with base currency USD (no currency field shown); a coach rate is always USD. The backend keeps its multi-currency support for later. |
| FE-4 | The **coach rate** is per hour ("25 USD / hour"). When a coach confirms a training request, the fee field is prefilled with rate × hours and can be changed. |
| FE-5 | No split fees in the MVP: the booker pays the court fee in full, the requester pays the coach fee in full (the backend defaults). |
| FE-6 | A player cannot see a coach's free times. The player proposes a time; the coach confirms (possibly at another time) or declines (BOOK-20 to BOOK-22). |
| FE-7 | **Amenities** are equipment without a rental price; **rentables** are equipment with one. Club-wide amenities (parking, showers) are club-wide items with quantity 1. No backend change. |
| FE-8 | Pushes on phones for `training_request`, `training_confirmed`, `training_declined`, `training_withdrawn`, `session_cancelled`. The app works without them until the owner creates the Firebase project. |
| FE-9 | iOS is built and sent to TestFlight by a GitHub Actions macOS runner (this machine is Linux). The owner opens the Apple Developer and Google Play accounts and adds the signing secrets. |
| FE-10 | Look: Material 3, one green brand color, light and dark, text logo "PASS". |
| FE-11 | App name **PASS**. Bundle id placeholder `app.pass.mobile` until the owner gives the real one (it is fixed once the app is in the stores). |
| FE-12 | Club staff (Q3: they see bookings and decide rentals) are added and removed by the owner by email on the club's web page, so the staff role is reachable. |

## Screens

Times: court times are shown in the club's timezone (from court detail); everything else in the device's timezone. The API sends UTC.

### Everyone

| Screen | Does | API |
|---|---|---|
| Sign up, log in | email, password, full name | `POST /api/auth/register/`, `/login/` |
| Forgot password | sends the reset link (the reset itself is the backend's web page) | `POST /api/auth/password-reset/` |
| Profile | name, phone, timezone; "I am a coach" with bio and coach rate; log out; delete account | `GET`/`PATCH`/`DELETE /api/me/`, `POST /api/auth/logout/` |

### Player (phone first)

| Screen | Does | API |
|---|---|---|
| Find a court | search clubs by name and sport | `GET /api/clubs/`, `GET /api/sports/` (new, below) |
| Club | the club's active courts | `GET /api/clubs/<id>/`, `/courts/` |
| Court | description, sports, prices per weekday, amenities, rentables; pick a date and see free slots with prices | `GET /api/courts/<id>/`, `/slots/?date=` |
| Book | pick a run of free slots, sport, rentables with quantity; see the quote; book | `POST /api/sessions/quote/`, `POST /api/sessions/` |
| Find a coach | search by name; profile with bio, coach rate, clubs | `GET /api/coaches/`, `GET /api/users/<id>/` |
| Request training | sport, proposed start and end | `POST /api/training-requests/` |
| My sessions | upcoming and past; status (requested, confirmed, cancelled, completed); court, club, coach, price, coach fee, rentals with their status | `GET /api/me/sessions/`, `GET /api/sessions/<id>/` |
| Cancel / withdraw | cancel a confirmed booking; withdraw a training request | `POST /api/sessions/<id>/cancel/`, `/withdraw/` |

### Coach (web first, quick look on phone)

| Screen | Does | API |
|---|---|---|
| Training requests | requests waiting for an answer | `GET /api/me/sessions/?status=requested` |
| Confirm | time (prefilled with the proposal), fee (prefilled, FE-4), optional court: pick club, court, then a free slot run | `POST /api/sessions/<id>/confirm/`, the court screens above |
| Decline | | `POST /api/sessions/<id>/decline/` |
| My schedule | confirmed training, as in "My sessions" | `GET /api/me/sessions/` |

### Club side (web first, quick look on phone)

| Screen | Does | Who | API |
|---|---|---|---|
| My clubs | clubs the caller owns or works at; create a club (name, address, timezone) | any user | `GET /api/me/clubs/`, `POST /api/clubs/` |
| Schedule | sessions per day or week, all courts or one; booker, coach, rentals | club side | `GET /api/clubs/<id>/schedule/` |
| Rentals | approve or decline a requested rentable | club side | `PATCH /api/rentals/<id>/` |
| Cancel a session | | club owner | `POST /api/sessions/<id>/cancel/` |
| Club details | name, address, timezone | club owner | `PATCH /api/clubs/<id>/` |
| Courts | add, edit, deactivate; sports, slot length | club owner | `/api/clubs/<id>/courts/`, `/api/courts/<id>/` |
| Prices | per court: weekday windows with a price per slot | club owner | `/api/courts/<id>/rates/`, `/api/rates/<id>/` |
| Amenities and rentables | name, quantity, one court or all, price (empty = amenity) | club owner | `/api/clubs/<id>/equipment/`, `/api/equipment/<id>/` |
| Staff (FE-12) | add by email, remove | club owner | `/api/clubs/<id>/members/`, `/api/members/<id>/` |

## Backend changes

Only one gap blocks the MVP:

- **Sports list.** Nothing lists sports, but court creation, club search and training requests need sport ids. New public endpoint `GET /api/sports/`: every sport, `{id, name}`, by name, not paged. Rule CLUB-36 on [clubs-and-courts](../backend/logic/clubs-and-courts.md) (CLUB-34 and CLUB-35 are taken by the unbuilt `wip/local-2026-11-17-audit` branch).
- **Coach rate unit** (docs only): ACC-21 and the accounts model page say the rate is per hour.

## Not in the MVP

The backend keeps them; the app has no screens for them: check-in, payments and billing, chat, wellness, recordings, teams and play groups, friends and invites, offers and discounts, extra currencies and price overrides, closures, coach affiliation with clubs, shadow players, coach-booked training, personal and group availability, avatars. Billing still runs on the server; its payments are simply not shown yet.

## Build

- Flutter stable, installed under `~/flutter`. Packages: `http`, `go_router` (web URLs), `flutter_secure_storage` (the token), `intl`, `firebase_core`, `firebase_messaging`. A hand-written API client in one file instead of a generated one. No state-management package: widgets load their data.
- API address: same origin on the web; `--dart-define=API_URL=https://<host>` for phone builds.
- Firebase options come from `--dart-define`s; without them the app skips push setup.
- Serving: a `web` service in `docker-compose.yml` serves the web build at `/` and forwards `/api/`, `/admin/`, `/static/` and `/account/` to Django. The Traefik and Caddy overrides route the main host to it.
- CI: `.github/workflows/mobile.yml` builds the Android bundle and the iOS archive and uploads to the Play internal track and TestFlight, using secrets the owner adds.
- Checks: `flutter analyze`, a widget test for booking and for confirming a training request, the web build driven in a browser against the local stack, an Android build on this machine.

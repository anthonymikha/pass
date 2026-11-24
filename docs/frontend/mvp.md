# Frontend MVP

**Status: revised 2026-11-24, waiting for the owner's review, not built.** The first version of this spec (Flutter for web, Android and iOS, Material 3) was approved and built on 2026-11-24, then torn down at the owner's request. A second question round the same day changed the platform to a web app styled after pass_v1 (FE-1, FE-8 to FE-14 below). Everything else carries over.

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

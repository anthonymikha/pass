# Frontend

**Status: built 2026-11-25, not deployed.** The scheduling MVP of [mvp.md](mvp.md) (FE-1 to FE-14): a Flutter **web** app (installable on the iPhone home screen) in pass_v1's design language, served by the backend at `/`.

## Layout

```
frontend/
  pubspec.yaml           http, go_router, timezone, web (and flutter_lints, flutter_test)
  web/                   index.html, manifest.json, icons, flutter_bootstrap.js (no service worker, no CDN)
  assets/fonts/          Inter, bundled
  lib/
    main.dart app.dart   start-up: path URLs, sign in with the stored token, light or dark from the device
    core/
      api_client.dart    the only HTTP: `Authorization: Token <token>`, JSON, error messages, a 30 s GET cache
      token_store*.dart  the token in the browser's local storage (an in-memory stand-in in tests)
      app_state.dart     the signed-in user, the club-side clubs (Club tab), the coach badge
      router.dart        every path (listed in mvp.md, Decided during build)
      format.dart        times (club zone or device zone), dates, money
    theme/tokens.dart    pass_v1's design tokens, unchanged: the only colours, type, spacing and radii
    widgets/             pass_v1's shared widgets (PassScaffold, ApiLoader, showErrorAlert, ...)
    features/
      auth/              welcome, sign up, sign in, forgot password
      book/              find a club or a coach, club, court listing, calendar sheet, confirm (quote, book), booked, coach
      sessions/          my sessions, training requests, session detail, confirm a request
      club/              my clubs, schedule and rentals, setup (club, courts and prices, equipment, staff)
      profile/           profile, coach switch and rate, create a club, log out, delete account
      shared.dart        iOS calendar and date/time capsules, Notes-style sport tags, slot-run picker, summary card, booked hero, glass action bar
  test/                  widget tests of the three journeys against a fake network
```

Rules, as in pass_v1's `docs/FRONTEND.md`: Cupertino widgets only; colours and sizes from the tokens only; every screen loads through `ApiLoader` (loading, error with retry, empty text); errors in `showErrorAlert`; all HTTP through `ApiClient.instance`, with paths, never hosts. No state-management package: screens load their own data.

## Run Flutter

Only through Docker, with the pinned SDK: `scripts/flutter.sh` runs any Flutter command in `ghcr.io/cirruslabs/flutter:3.35.7` (it builds a local `pass-flutter-tools:3.35.7` image with the web artifacts the first time). Packages are cached in `.pub-cache/` at the repository root (gitignored).

```sh
scripts/flutter.sh pub get
scripts/flutter.sh analyze          # must be clean
scripts/flutter.sh test             # the widget journeys
scripts/flutter.sh build web --release --no-web-resources-cdn --pwa-strategy=none
```

The web app needs the API on the same origin. The simplest way to see it is the Docker stack: `docker compose up -d --build` builds the app inside the backend image and serves it at `http://localhost:<BACKEND_PORT>/` ([deployment](../deployment.md#the-web-app)). A local `runserver` also serves `frontend/build/web` once it is built.

## Tests

`test/journeys_test.dart` runs the real app (router and screens) with only the HTTP transport replaced by `package:http`'s `MockClient` (`test/helpers.dart`), and checks what is on screen and which requests went out with which bodies:

1. a player finds a club (and its coaches) and a court, sees prices and amenities, picks two slots on the calendar sheet, adds two rentables on Confirm, sees the quote and books exactly what was quoted, then the Booked hero;
2. a coach sees the badge and the request, the fee prefilled from the coach rate × hours, moves the training onto a court at another time (the fee follows) and confirms;
3. a club owner (desktop width) adds a court, a price window for six weekdays, an amenity and a rentable;
4. a Confirm link without a time asks for one instead of failing.

## What the app is responsible for

| Concern | Detail |
|---|---|
| Login state | The token from register or login, in local storage; sent as `Authorization: Token <token>`; a `401` forgets it and shows Welcome |
| Time zones | The API sends UTC. Court times (slots, prices, the club schedule) in the club's `timezone`; everything else in the device's |
| Money | USD only (FE-3); decimal strings shown cut to the currency's minor units, never added up in the app (the quote's total comes from the server) |

Not in the MVP (the backend keeps them): push notifications, check-in, payments, chat, wellness and sleep import, recordings and video, teams and play groups, friends, offers, other currencies, closures, coach affiliation, shadow players, coach-booked training, availability, avatars, native store builds.

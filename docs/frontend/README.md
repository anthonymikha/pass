# Frontend

**Status: MVP built** (2026-11-24). One Flutter project in `frontend/` for web, Android and iOS. What it does and why: [mvp.md](mvp.md) (FE-1 to FE-12), the approved spec.

## Layout

```
frontend/
  lib/
    main.dart            routes (go_router), theme, the shell: bottom bar on phones, side rail on wide screens (FE-2)
    api.dart             the one REST client: token, signed-in user, errors, money and time formatting
    push.dart            Firebase push on phones (FE-8), off without --dart-define settings
    widgets.dart         loader, slot picker (AVL-10, BOOK-4), timezone field, small helpers
    screens/
      auth.dart          log in, create account, forgot password
      player.dart        find a court, court detail and booking, find a coach, coach profile and training request
      sessions.dart      my sessions, one session and its actions, the coach's confirm form
      club.dart          my clubs, create a club, schedule, courts, prices, amenities and rentables, staff
      profile.dart       profile, coach details, log out, delete account
  test/flows_test.dart   booking a court; a coach confirming a request
  Dockerfile, Caddyfile  the web build served by Caddy, which forwards Django's paths (same origin)
```

No state-management package and no generated API client: each screen loads what it shows (`Loaded` in `widgets.dart`) and calls `Api.instance`.

## Run and check

Flutter is pinned to **3.35.7** (Dockerfile, CI). On this machine the SDK runs from the `ghcr.io/cirruslabs/flutter:3.35.7` image, so nothing is installed on the host:

```sh
docker run --rm -v "$PWD/frontend:/app" -w /app ghcr.io/cirruslabs/flutter:3.35.7 sh -c "flutter pub get && flutter analyze && flutter test"
```

The web app with the whole stack: `docker compose up --build`, then http://localhost:8080 (`WEB_PORT`). For a local stack on plain http set `HTTPS=0` and `PASS_HOST=localhost:8080` in `.env`.

A phone build needs the backend's address: `flutter build apk --dart-define=API_URL=https://PASS_HOST`. On the web the app calls its own origin.

## Settings passed at build time

| `--dart-define` | Meaning |
|---|---|
| `API_URL` | backend address for phone builds (`https://PASS_HOST`); empty on the web |
| `FIREBASE_API_KEY`, `FIREBASE_SENDER_ID`, `FIREBASE_PROJECT_ID`, `FIREBASE_ANDROID_APP_ID`, `FIREBASE_IOS_APP_ID` | from the Firebase console (project settings, one Android and one iOS app with id `app.pass.mobile`). Without them the app runs without pushes |

## Store builds (FE-9)

`.github/workflows/mobile.yml` runs on a tag `v*` or by hand: analyze and test, then an Android bundle to the Play **internal** track (as a draft) and an iOS build to **TestFlight**. It has not run yet: it needs the owner's accounts and these GitHub settings.

| Kind | Name | What |
|---|---|---|
| variable | `API_URL` | `https://PASS_HOST` |
| secret | `FIREBASE_*` | as in the table above |
| secret | `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD` | the upload key: `keytool -genkey -v -keystore upload.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload`, then `base64 -w0 upload.jks`. Keep the file and passwords safe: losing them blocks updates |
| secret | `PLAY_SERVICE_ACCOUNT_JSON` | a Google Cloud service account with release rights in the Play Console |
| secret | `APPLE_TEAM_ID`, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8` | App Store Connect API key (Admin role, so Xcode can create the signing certificate) and its `.p8` contents |

Before the first run: create the app `app.pass.mobile` in the Play Console (and upload the first bundle by hand, which Google requires) and in App Store Connect; upload the APNs key to Firebase (NOTE-10). The bundle id is a placeholder until the owner confirms it (FE-11); changing it later means a new store listing.

## What the app relies on from the backend

| Concern | Detail |
|---|---|
| Login state | the token from register or login is kept in secure storage and sent as `Authorization: Token <token>`; a `401` signs out |
| Time zones | the API sends UTC. Court slots and the club schedule are shown in the club's `timezone`; everything else in the device's |
| Money | decimal strings with a currency code; the MVP is USD only (FE-3) |
| Push | `POST /api/devices/` with the FCM token; a push's `data.id` opens that session |

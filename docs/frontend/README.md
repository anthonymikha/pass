# Frontend

**Status: not started.** `frontend/` holds only a placeholder. Nothing here describes existing code.

## Plan

- One Flutter project in `frontend/`, built for web, iOS and Android.
- It talks only to the backend's REST API under `/api/` ([API docs](../backend/api/)).
- The web build will be served by a `web` service in `docker-compose.yml`: a reverse proxy that serves the app at `/` and forwards `/api/`, `/admin/` and `/static/` to Django. Same origin, so no CORS configuration.
- Flutter has no virtual environment. The SDK is installed on the machine; packages are listed in `pubspec.yaml`.

## What the app is responsible for

| Concern | Detail |
|---|---|
| Login state | Store the token from register or login securely on the device; send it as `Authorization: Token <token>`; on `401`, return to login |
| Time zones | The API sends timestamps in UTC. Show court times in the club's `timezone` and personal times in the user's |
| Money | Amounts arrive as decimal strings with a 3-letter currency code. Never add different currencies together. Decimal places vary by currency |
| Sleep import | Read Apple Health / Google Health Connect on the phone and post the nights to the backend |
| Video | Upload and play through short-lived links from the backend, straight to storage |
| Chat | Poll for new messages; render messages that carry a session as a card with start and end time |
| Push notifications | Register the device's push token with the backend once that endpoint exists |

## Suggested layout for these docs once the app exists

```
docs/frontend/
  README.md        setup, run, build per platform
  architecture.md  state management, navigation, API client
  screens/         one page per area, mirroring docs/backend/flows/
```

Keep the same journey names as [backend/flows](../backend/flows/) so a feature can be followed from screen to table.

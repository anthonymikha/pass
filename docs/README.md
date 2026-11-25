# PASS documentation

PASS (Performance Analytics and Sports Solutions) helps players, coaches, and court/club owners book courts, run teams and coaching, track wellness, review session video and chat.

These docs describe how the system is built and how to use it. The roadmap and handoff notes are in [`PLAN.md`](../PLAN.md) in the repo root.

## Map

```
docs/
  backend/
    README.md            architecture: apps, rules, conventions
    models/              one page per Django app: every table, field and rule
      accounts.md        users, connections, block-out times
      venues.md          sports, clubs, courts, rates, equipment, discounts
      teams.md           play groups and teams
      bookings.md        sessions, participants, rentals, recordings, tags
      billing.md         payments, commission rates
      wellness.md        soreness, sleep, exercises, achievements
      chat.md            chats, members, messages
    logic/               THE SPECIFICATION: every business rule, with ids (BOOK-3, PAY-7)
    flows/               user journeys that combine several models
      owner-setup.md
      booking-and-payment.md
      coaching-and-teams.md
      wellness.md
      recordings.md
      chat.md
    api/                 REST endpoints, one page per app; the OpenAPI schema is served at /api/schema/
      accounts.md venues.md teams.md bookings.md billing.md wellness.md chat.md
    eraser/              diagram code for eraser.io: one file per app plus overview.eraser (generate.py rebuilds them)
  deployment.md          production: hosts, Traefik or Caddy, settings, backups
  frontend/
    README.md            the Flutter web app: layout, how to run, build and test it
    mvp.md               the frontend MVP spec (FE-1 to FE-14)
```

## Where to start

| You want to | Read |
|---|---|
| Understand how the backend is organised | [backend/README.md](backend/README.md) |
| Know what a table or field means | the matching page in [backend/models/](backend/models/) |
| Know exactly how something must behave | [backend/logic/](backend/logic/README.md): the rules code is built from |
| Build a feature that touches several tables | the matching page in [backend/flows/](backend/flows/) |
| Call the API | [backend/api/](backend/api/) |
| Work on the app | [frontend/README.md](frontend/README.md) |
| Run it on a server | [deployment.md](deployment.md) |

## Status markers

Each flow page says what is **built** (has endpoints and tests) and what is **planned** (schema exists, logic not written). As of 2026-11-21 every backend flow is built and tested (steps 2 to 10 of the roadmap and the reviews of 2026-11-17 and 2026-11-20, T14 to T19); only the deferred recovery level and suggested times are not. The frontend MVP (a Flutter web app served by the backend) is built as of 2026-11-25 ([frontend](frontend/README.md)); it is not deployed yet.

## Keeping these docs true

- The models in `backend/*/models.py` are the source of truth for fields and constraints. When a model changes, update its page in the same commit.
- Business rules are written in `backend/logic/` first and reviewed there; code implements only what those pages say.
- When an endpoint is added, add it to `backend/api/` and flip the status in the flow page. Mark the rules it implements as built on their logic page.

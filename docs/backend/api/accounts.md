# API: accounts

**Status: built and tested.** Includes friends, blocking, coaching links, block-outs and shadow players. Code: [views](../../../backend/accounts/views.py), [serializers](../../../backend/accounts/serializers.py), [tests](../../../backend/accounts/tests.py).

## Conventions for the whole API

- Base path `/api/`. JSON in, JSON out.
- Every call needs `Authorization: Token <token>`, except register and login.
- Validation errors return `400` with a body keyed by field name, or `non_field_errors`.
- Missing or dead token returns `401`.

## Endpoints

| Method | Path | Auth | Body | Success |
|---|---|---|---|---|
| POST | `/api/auth/register/` | none | `email`, `password`, `full_name` | `201` `{token, user}` |
| POST | `/api/auth/login/` | none | `email`, `password` | `200` `{token, user}` |
| POST | `/api/auth/logout/` | token | none | `204` (also deletes the caller's devices, NOTE-3) |
| GET | `/api/me/` | token | none | `200` user |
| PATCH | `/api/me/` | token | any editable field | `200` user |
| POST | `/api/me/avatar/form/` | token | `file_name` (`.jpg`, `.jpeg`, `.png`, `.webp`, case-insensitive), `size_bytes` (1 to 5 MiB) | `200` `{url, fields, storage_key}`: a signed POST form, valid 1 hour, limited to 1..`size_bytes` bytes (REC-30). `400` per field |
| POST | `/api/me/avatar/` | token | `storage_key` from the form | `200` the profile: sets `avatar` to a signed link and deletes the old object (REC-30). `400 bad_key` (not `avatars/<your id>/<uuid>.<ext>`), `400 not_uploaded`. Repeating the current key is `200` and changes nothing |
| POST | `/api/devices/` | token | `token`, `platform` (`ios`, `android`, `web`) | `201` device; `200` if the caller already has it or it moved to the caller (NOTE-2) |
| DELETE | `/api/devices/<token or id>/` | token | none | `204`; `404` if it is not the caller's own (NOTE-3, GEN-3) |
| GET | `/api/me/blockouts/` | token | none | `200` page of the caller's block-outs |
| POST | `/api/me/blockouts/` | token | block-out fields (below) | `201` block-out |
| GET, PATCH, DELETE | `/api/me/blockouts/<id>/` | token | PATCH: any block-out field | `200` / `200` / `204`; `404` if not the caller's (GEN-3) |
| GET | `/api/friends/` | token | none | `200` page of the caller's friends (TEAM-6) |
| POST | `/api/friends/` | token | `user` (id) | `201` a new request; `200` if friends already, already requested, or the other user had asked first (then it becomes accepted). Body: `{id, full_name, is_coach, status}` (TEAM-1) |
| GET | `/api/friends/incoming/`, `/api/friends/outgoing/` | token | none | `200` page of users with a pending request to / from the caller (TEAM-6) |
| POST | `/api/friends/<user_id>/accept/` | token | none | `200` accept the pending request that user sent the caller; `200` again if already friends; `404` otherwise (TEAM-2) |
| DELETE | `/api/friends/<user_id>/` | token | none | `204` decline, cancel or unfriend; `404` if there is nothing between the two (TEAM-3) |
| GET | `/api/blocks/` | token | none | `200` page of users the caller blocked; never who blocked the caller (TEAM-6) |
| POST | `/api/blocks/` | token | `user` (id) | `201`; `200` if already blocked. Removes friend and coaching links between the two (TEAM-4) |
| DELETE | `/api/blocks/<user_id>/` | token | none | `204` unblock; `404` unless the caller is the blocker (TEAM-5) |
| GET | `/api/coaching/` | token | none | `200` page of the caller's coaching links, as coach or player: `{id, coach, player, status, created_at}` |
| POST | `/api/coaching/` | token | `coach` (id) | `201` request; `200` if already pending or accepted (TEAM-10, TEAM-13) |
| POST | `/api/coaching/<id>/accept/` | the coach of the link | none | `200`; `200` again if already accepted (TEAM-11) |
| DELETE | `/api/coaching/<id>/` | either side | none | `204`: the coach declines a pending link; either side ends an accepted one (TEAM-11, TEAM-12) |
| GET, POST | `/api/shadow-players/` | token; POST: coach only | POST: shadow player fields | `200` page of the caller's shadow players; `201` created (ACC-10) |
| GET, PATCH | `/api/shadow-players/<id>/` | the managing coach | PATCH: any field | `200`; another coach's, or a normal user's, is `404` (ACC-11) |
| GET | `/api/schema/` | none | none | `200` OpenAPI schema (the Flutter client is generated from it) |

### Devices

A device is a phone registered for pushes: `{id, token, platform, created_at}`. The app registers its Firebase token after sign-in and whenever Firebase renews it. A token held by another user (a shared phone) moves to the caller. Pushes themselves are sent by `accounts.services.notify()` after the transaction commits; until `FCM_CREDENTIALS_FILE` is set, a fake sender only logs them (NOTE-11).

### The user object

```json
{
  "id": 1,
  "email": "pat@example.com",
  "full_name": "Pat",
  "phone": "",
  "timezone": "Asia/Beirut",
  "date_of_birth": "1998-04-12",
  "sex": "female",
  "height_cm": "172.0",
  "weight_kg": "64.50",
  "nationality": "LB",
  "dominant_hand": "right",
  "is_coach": true,
  "coach_bio": "",
  "coach_rate": "25.500",
  "coach_currency": "USD"
}
```

`avatar` is a signed GET link (valid 1 hour) or `""`; it is read-only here and set only through the avatar endpoints. `id` and `email` are read-only. Everything else can be sent to `PATCH /api/me/`.

### Rules

- **Email** is case-insensitive and stored lowercase. Registering an email that exists returns `400` on `email`.
- **Password** must pass Django's strength checks (length, not common, not all digits, not similar to the email or name). Failures return `400` on `password`.
- **`timezone`** must be a valid IANA name.
- **`date_of_birth`** cannot be in the future. **`sex`** is `male` or `female`; **`dominant_hand`** is `left`, `right` or `both`. **`nationality`** is two uppercase letters. **`height_cm`** 30–300, **`weight_kg`** 2–500. All optional (`null` or `""`).
- **`coach_currency`** must be three uppercase letters. **`coach_rate`** cannot be negative.
- **Login** fails with the same `400` for a wrong password, an unknown email and a deactivated account.
- **Shadow players** cannot log in: they have no email and no usable password.
- **Rate limit:** register and login share a limit of 10 requests per minute per IP, then `429`.
- **Tokens:** one per user, no expiry. Logging in again returns the same token. Logout deletes it, which signs the user out everywhere.

### Example

```sh
curl -s -X POST localhost:8000/api/auth/register/ -H 'Content-Type: application/json' \
  -d '{"email":"pat@example.com","password":"court-side-42","full_name":"Pat"}'

curl -s -X PATCH localhost:8000/api/me/ -H 'Authorization: Token <token>' \
  -H 'Content-Type: application/json' -d '{"is_coach":true,"timezone":"Asia/Beirut"}'
```

### Friends, blocking and coaching links

Lists show other users as `{id, full_name, is_coach}` (the full public profile, ACC-21, is in [teams](teams.md)). The `<user_id>` in friend and block paths is the other user's id, whoever sent the request.

- Targets must be active, non-shadow users; anyone else (a shadow player, an inactive or unknown id) is `400` on that field, "Not found." (GEN-18, ACC-12).
- Refusals (`400`, `{detail, code}`): `cannot_connect` for a blocked pair (either way), for yourself; `not_a_coach` when the coaching target is not a coach. The blocked user cannot tell who blocked them: their lists never show it, and unblocking is `404` for them.
- Any user, coaches included, may ask a coach; the caller is always the player (TEAM-10, TEAM-13). A player cannot decline or accept for the coach (`403`); a link the caller is not part of is `404`.
- Pushes: `friend_request` to the other user, `coaching_request` to the coach; `data.id` is the connection id.

### Block-outs

`{id, starts_on, start_time, end_time, repeat, repeat_until, reason}`. `repeat` is `none` (default), `daily`, `weekly` or `monthly`; times are the user's local clock times (GEN-8). `end_time` must be after `start_time`, or `00:00` for the end of the day (GEN-11); `repeat_until` cannot be before `starts_on`; `reason` up to 255 characters (CLUB-15). PATCH is checked against the stored row.

### Shadow players

`{id, full_name, date_of_birth, sex, dominant_hand, height_cm, weight_kg, nationality, is_active}`; only `full_name` is required, with the profile's validation for the rest. A new shadow player has no email and no usable password, `managed_by` is the calling coach, and its `timezone` is the coach's. Deactivate with `PATCH {"is_active": false}`. A non-coach creating one gets `403`.

## Not built yet

Email verification, password reset, changing email, viewing other users' public profiles.

### Avatar upload (REC-30)

```sh
curl -s -X POST localhost:8000/api/me/avatar/form/ -H 'Authorization: Token <token>' \
  -H 'Content-Type: application/json' -d '{"file_name":"me.png","size_bytes":48213}'
# post the file straight to storage: every returned field as -F name=value, the file last
curl -s -X POST <url> -F key=<fields.key> -F policy=... (and the other fields) -F file=@me.png
curl -s -X POST localhost:8000/api/me/avatar/ -H 'Authorization: Token <token>' \
  -H 'Content-Type: application/json' -d '{"storage_key":"<storage_key>"}'
```

Storage is described in [bookings](bookings.md#recordings-and-tags).

# API: accounts

**Status: built and tested.** Code: [views](../../../backend/accounts/views.py), [serializers](../../../backend/accounts/serializers.py), [tests](../../../backend/accounts/tests.py).

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
| POST | `/api/devices/` | token | `token`, `platform` (`ios`, `android`, `web`) | `201` device; `200` if the caller already has it or it moved to the caller (NOTE-2) |
| DELETE | `/api/devices/<token or id>/` | token | none | `204`; `404` if it is not the caller's own (NOTE-3, GEN-3) |
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

`id` and `email` are read-only. Everything else can be sent to `PATCH /api/me/`.

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

## Not built yet

Avatar upload, email verification, password reset, changing email, viewing other users' public profiles.

# Conventions (GEN)

**Status: built** (helpers in `backend/config/api.py` and `backend/config/money.py`; every endpoint follows them). Rules every endpoint follows. Other pages rely on them and do not repeat them.

## Errors

**GEN-1.** Responses for failures:

| Situation | Status | Body |
|---|---|---|
| A field is missing, the wrong type, or out of range | `400` | `{"<field>": ["<message>"]}` (DRF's normal shape) |
| A business rule refuses the action | `400` | `{"detail": "<message>", "code": "<code>"}` |
| The slot or stock is taken by someone else (a race the caller could not see) | `409` | `{"detail": "<message>", "code": "<code>"}` |
| No token, or a dead token | `401` | |
| The caller can see the object but may not do this to it | `403` | `{"detail": "<message>", "code": "forbidden"}` |
| The object does not exist, **or the caller may not see it** | `404` | |

**GEN-2.** `code` values are stable strings listed on each page (for example `slot_taken`). The app switches on `code`, never on `detail`.

**GEN-3.** Visibility before permission: if the caller may not even see an object (another user's chat, another club's payment), the answer is `404`, never `403`, so ids of other people's data cannot be probed.

**GEN-4.** Every action checks permission first, then input, then business rules, then writes. A refused action writes nothing.

## Repeated requests

**GEN-5.** Repeating an action whose effect already holds returns success and changes nothing. This covers: check-in, mark paid, cancel, accept an invite, accept a friend request, complete an exercise, mark a chat read, register a device. The response is the object in its current state, with the same status code as the first call (`200`, or `201` only on the call that created something; repeats return `200`).

**GEN-6.** Creating something that must be unique (a booking for a slot, a friend request) is not repeatable by retrying: the second call fails with the error that page names (for a slot, `409 slot_taken`). The app must not retry a create blindly after a timeout; it should reload and look.

## Time

**GEN-7.** The database stores every timestamp in UTC. The API sends and accepts ISO 8601 timestamps with an offset (`2027-01-11T14:00:00Z` or `2027-01-11T16:00:00+02:00`). A timestamp without an offset is refused (`400`).

**GEN-8.** Dates and clock times that belong to a club (rates, court closures, "today" for a club) are in the **club's** `timezone`. Dates and clock times that belong to a person (their block-outs, the day a soreness log is for, streaks) are in the **user's** `timezone`.

**GEN-9.** "Today" means today's date in the timezone named by GEN-8 for that rule. "Now" is the server's current UTC instant.

**GEN-10.** A local date and clock time is turned into an instant with Python `zoneinfo`, `fold=0`. A local time that does not exist (the hour skipped when clocks go forward) is detected by converting to UTC and back: if the clock time changes, the local time does not exist. Pages that turn local times into instants say what happens then (see AVL-6).

**GEN-11.** A clock-time window `start_time`–`end_time` where `end_time` is `00:00` ends at midnight at the end of that day. Any other window must have `end_time` after `start_time`. Windows never cross midnight; something that spans midnight is two windows.

## Lists

**GEN-12.** List endpoints are paginated by page number: `?page=2`, 50 items per page, with DRF's `count`, `next`, `previous`, `results` envelope. Endpoints that page differently (free slots, availability, chat messages) say so on their page.

## Money

**GEN-13.** Money is a decimal string in JSON (`"46.170"`, three decimal places as stored). Amounts in different currencies are never added together; any total is per currency.

**GEN-14.** A currency code is three uppercase letters. The code is not checked against the full ISO 4217 list.
<!-- ponytail: format check only; add the ISO list if bad codes ever appear -->

**GEN-15.** Each currency has a number of **minor units** (decimal places actually used):

| Minor units | Currencies |
|---|---|
| 0 | BIF, CLP, DJF, GNF, ISK, JPY, KMF, KRW, **LBP**, PYG, RWF, UGX, UYI, VND, VUV, XAF, XOF, XPF |
| 3 | BHD, IQD, JOD, KWD, LYD, OMR, TND |
| 2 | every other code |

LBP is listed as 0 on purpose: ISO 4217 says 2, but piastres are not used in practice (owner decision, 2026-11-16).

**GEN-16.** **Rounding:** `round_money(x, C)` rounds `x` to the minor units of currency `C`, half away from zero (Python `Decimal.quantize(..., ROUND_HALF_UP)`). Every amount the system **computes** (a converted price, a discount, a platform fee) is rounded with `round_money` at the moment it is computed, and stored rounded. Pages say exactly where.

**GEN-17.** Money the user **types** (a rate, an override, a coach fee, a manual discount) may not have more decimal places than the currency's minor units, and may not be negative. Too many decimals: `400` on that field, "Too many decimal places for <C>".

Examples: `round_money(46.17285, EUR) = 46.17`; `round_money(8333.4, LBP) = 8333`; `round_money(0.125, USD) = 0.13`; `round_money(1.2345, KWD) = 1.235`.

## Ids in requests

**GEN-18.** Requests refer to other objects by id (`"court": 3`). An id the caller may not see is answered as if it did not exist: `400` on that field, "Not found." (inside a body) or `404` (in the URL).

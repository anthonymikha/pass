# bookings models

Source: [backend/bookings/models.py](../../../backend/bookings/models.py). Tables: `sessions`, `session_participants`, `session_rentals`, `recordings`, `recording_tags`, `recording_tag_players`.

## Session (`sessions`)

The centre of the system: one booked block of time.

| Field | Meaning |
|---|---|
| `court` | Where. Empty for a training request not yet placed on a court |
| `sport` | Which sport, important on multi-sport courts |
| `booked_by` | The **booker**: the user who made it and whose check-in triggers payment |
| `coach` | Set for coached sessions |
| `group` | Set when booked for a play group or team |
| `kind` | `play` or `training` |
| `status` | See below |
| `starts_at`, `ends_at` | UTC; `ends_at` must be after `starts_at` |
| `currency` | Chosen by the booker from the club's accepted currencies |
| `price` | Court price for the whole session, in `currency`, **before** discount |
| `coach_fee` | Coach's fee in `currency`, 0 if none |
| `coach_fee_payer` | Empty = fee split equally between team members. Set = that user pays all of it |
| `discount`, `discount_amount` | The offer used and the amount taken off, copied at booking time |

`price`, `currency`, `coach_fee` and `discount_amount` are snapshots. Later changes to rates, exchange rates or offers never alter an existing session.

### Status

| Status | Meaning |
|---|---|
| `requested` | Waiting for someone: a coach to accept a training request |
| `confirmed` | Going ahead |
| `cancelled` | Called off; frees the slot |
| `completed` | Took place |

A slot is taken by any session on that court that overlaps it and is not `cancelled`, or by a [`CourtBlockout`](venues.md#courtblockout-court_blockouts). Who moves a session between statuses, and when: [BOOK-1](../logic/booking.md). `completed` is never stored; it is shown for confirmed sessions that have ended ([BOOK-55](../logic/booking.md#completed)).

### What one table covers

| Case | How it looks |
|---|---|
| Player books a court | `kind=play`, `court` set, `booked_by` = player |
| Play group game | same, plus `group` |
| Player requests a coach | `kind=training`, `coach` set, `status=requested`, `court` may be empty |
| Coach books for a team | `kind=training`, `booked_by` = `coach`, `group` set |

## SessionParticipant (`session_participants`)

One row per person in a session. Unique per (session, user).

| Field | Meaning |
|---|---|
| `status` | `invited` → `accepted` or `declined` |
| `checked_in_at` | Attendance. Empty after the session ended = no-show |
| `rpe` | Rate of perceived exertion, 1–10 |
| `rpe_minutes` | Minutes of effort, defaults to the session length |
| `rpe_logged_at` | When the form was submitted |
| `rpe_reminded_at` | When the RPE reminder was sent (**planned column**, [NOTE-9](../logic/notifications.md#the-scheduler)) |

- The booker gets a row with status `accepted` when the session is created.
- Coaches set `checked_in_at` on behalf of shadow players.
- Training load for one participation is `rpe × rpe_minutes`.
- **Video unlock:** `checked_in_at` and `rpe` both set ([REC-20](../logic/recordings.md#watch)).
- Check-in window and who may check in whom: [PAY-1 to PAY-5](../logic/check-in-and-payments.md).

```python
p = SessionParticipant.objects.get(session=s, user=me)
p.checked_in_at = timezone.now(); p.save()

no_shows = s.participants.filter(status="accepted", checked_in_at__isnull=True)   # after s.ends_at
can_watch = p.checked_in_at is not None and p.rpe is not None
```

## SessionRental (`session_rentals`)

Equipment requested with a session.

| Field | Meaning |
|---|---|
| `equipment` | Must be rentable (`rental_price` set) and available at that court |
| `quantity` | |
| `price` | Total for this line in the session's currency, copied at request time |
| `status` | `requested` → `approved` or `declined` by the owner |

Only approved rentals are charged. Stock is checked when the club side approves ([BOOK-40, BOOK-41](../logic/booking.md#rentals)).

## Recording (`recordings`)

A video attached to a session.

| Field | Meaning |
|---|---|
| `session` | |
| `uploaded_by` | A player who checked in, or the session's coach |
| `storage_key` | The file's key in object storage (not a URL) |
| `duration_seconds` | Optional |

A session with recordings cannot be deleted.

## RecordingTag (`recording_tags`)

A labelled moment or span in a recording.

| Field | Meaning |
|---|---|
| `created_by` | Usually the session's coach |
| `start_second`, `end_second` | Position in the video; `end_second` optional |
| `label`, `note` | |
| `players` | Many-to-many (`recording_tag_players`). **No players = whole-team tag** |

Who sees a tag: [REC-27](../logic/recordings.md#tags) (the session coach sees all; a player who may watch sees tags naming them and whole-team tags).

```python
tag = RecordingTag.objects.create(recording=r, created_by=coach, start_second=312, end_second=330, label="Fast break")
tag.players.set([player_a, player_b])
```

## Used together with

- `venues` for the court, prices, equipment and discount.
- `billing.Payment.session`: money for this session.
- `wellness.SorenessLog.session`: post-session soreness.
- `chat.Message.session`: the session card in a group chat.
- Journeys: [booking-and-payment](../flows/booking-and-payment.md), [recordings](../flows/recordings.md).

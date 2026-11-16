# Flow: session video and tags

**Status: planned.** Where the video files live is not finally decided; the working recommendation is S3-compatible object storage with signed links.

Models: [Session, SessionParticipant, Recording, RecordingTag](../models/bookings.md).

## Upload

Who may add a recording to a session:
- a participant who checked in (a "play-through"), or
- the session's coach.

Intended sequence with object storage:
1. The app asks the backend for an upload link for a session.
2. The backend checks the rule above and returns a short-lived signed link plus the `storage_key`.
3. The app uploads the file straight to storage.
4. The app confirms; the backend creates the `Recording` with that `storage_key`.

Video never passes through Django.

## Watch

A user may watch a session's recordings when either holds:
- they are the session's coach, or
- their `SessionParticipant` row has both `checked_in_at` and `rpe` set.

This is why check-in exists and why the RPE form matters: logging RPE is what unlocks the video. On success the backend returns a short-lived signed playback link.

```
SessionParticipant.checked_in_at ─┐
SessionParticipant.rpe ───────────┴─> may watch Recording ─> signed link
```

## Tag

The coach of the session marks moments:

1. Create a `RecordingTag` with `start_second`, optional `end_second`, a `label` and a `note`.
2. Attach the players involved (`tag.players`). Leave empty for a whole-team tag.

Coaches can tag any recording on sessions they coached, whoever uploaded it.

## Who sees which tags

| Viewer | Sees |
|---|---|
| The session's coach | every tag |
| A player who may watch | tags that name them, plus whole-team tags |
| Anyone else | nothing |

```python
from django.db.models import Q

RecordingTag.objects.filter(recording__session=session).filter(
    Q(players=me) | Q(players__isnull=True)
).distinct()
```

## Open points

- Storage choice and file size limits.
- Whether players can create their own private tags.

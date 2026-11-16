# Flow: session video and tags

**Status: built** (`backend/bookings/`, avatars in `backend/accounts/`, [API](../api/bookings.md)). Rules: [recordings](../logic/recordings.md). Storage: SeaweedFS (S3 API) in docker-compose, signed links, video never passes through Django.

Models: [Session, SessionParticipant, Recording, RecordingTag](../models/bookings.md).

| Step | What happens | Rules |
|---|---|---|
| 1. Ask for an upload form | A checked-in participant or the coach; mp4/mov up to 2 GiB | [REC-10, REC-11](../logic/recordings.md#upload-a-recording) |
| 2. Upload | The phone posts the file straight to storage | [REC-1, REC-2](../logic/recordings.md#storage) |
| 3. Confirm | The backend checks the file is there and creates the `Recording` | [REC-12, REC-13](../logic/recordings.md#upload-a-recording) |
| 4. Watch | The coach, or a participant who checked in **and** logged RPE | [REC-20, REC-21](../logic/recordings.md#watch) |
| 5. Tag | The coach marks moments, optionally naming players | [REC-25 to REC-28](../logic/recordings.md#tags) |

```
SessionParticipant.checked_in_at ─┐
SessionParticipant.rpe ───────────┴─> may watch Recording ─> signed link
```

Avatars use the same storage: [REC-30](../logic/recordings.md#avatars).

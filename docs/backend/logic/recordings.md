# Recordings and file storage (REC)

**Status: built** (`backend/config/storage.py`, recordings in `backend/bookings/`, avatars in `backend/accounts/`; [API](../api/bookings.md)). Session video, tags, and avatars.

## Storage

**REC-1.** Files live in S3-compatible object storage: a SeaweedFS container (S3 API) in docker-compose with data in `./data/storage`, one bucket. *Decided during build (2026-11-16): MinIO no longer publishes container images (Docker Hub and quay both refuse them), so the approved "MinIO container" is replaced by SeaweedFS, the upstream image by its author, which passed the signed POST (with size limit), signed GET, head and delete checks.* Django never receives or serves file bytes. Phones upload with a signed POST form and play back with a signed GET link. Moving to a cloud bucket later is a settings change (endpoint, bucket, keys).

**REC-2.** Signed links expire after 1 hour.

**REC-3.** Tests use a fake storage that records which keys were "uploaded"; no storage server is needed to run the test suite (tests force the fake even where real storage is configured).

## Upload a recording

**REC-10.** Who may: a participant of the session who checked in, or the session coach. When: the session is `confirmed`, from `starts_at` until 30 days after `ends_at`.

**REC-11.** **Ask for an upload form.** Input: `file_name` ending in `.mp4` or `.mov` (case-insensitive), `size_bytes` (1 to 2 GiB = 2 147 483 648). Returns a signed POST form (`url`, `fields`) limited to that content length range, and a `storage_key` = `recordings/<session id>/<random UUID>.<ext>`. Nothing is written to the database yet.

**REC-12.** **Confirm the upload.** Input: `storage_key`, optional `duration_seconds` (≥ 1). Checks: the key matches `recordings/<this session id>/<UUID>.(mp4|mov)`; the object exists in storage. Creates the `recordings` row with `uploaded_by` = caller. Confirming the same key again returns the existing row (`200`).

**REC-13.** Errors: not allowed `403`/`404`; outside the window `400 upload_closed`; bad name or size `400` per field; key not for this session `400 bad_key`; object missing `400 not_uploaded`.

**REC-14.** **Delete.** The uploader or the session coach. Deletes the object, the row and its tags.

**REC-15.** No transcoding and no thumbnails: the phone uploads a playable mp4 or mov (settled at the owner's review on 2026-11-16).

**REC-16.** *Decided during build (2026-11-16):* the upload window applies to the form and to the confirm; a repeat confirm of a stored key returns `200` at any time (GEN-5). Confirm checks, in order: permission, input, `bad_key`, repeat, `upload_closed`, `not_uploaded`. A caller who can see the session but may not upload (the booker who did not check in, a declined participant) gets `403`. The form's size limit is 1 byte to `size_bytes`. The upload form and the avatar confirm return `200` (they create no row). An uploader who may not watch yet gets no playback link in the confirm response but may still delete their own recording.

## Watch

**REC-20.** A user may watch a session's recordings when they are the session coach, or a participant whose row has both `checked_in_at` and `rpe` set. Anyone else, including an uploader who has not logged RPE: `404` for the list.

**REC-21.** The list shows each recording with `uploaded_by`, `duration_seconds`, `created_at` and a signed playback link (REC-2).

## Tags

**REC-25.** Who may create: the session coach, on any recording of a session they coached. Input: `start_second` ≥ 0, optional `end_second` > `start_second`, both ≤ `duration_seconds` when that is known; `label` (1–255); optional `note`; optional `players`: participants of the session (any status that is not `declined`), shadow players included. No players = a whole-team tag.

**REC-26.** The creator or the session coach may change or delete a tag.

**REC-27.** Who sees which tags:

| Viewer | Sees |
|---|---|
| The session coach | every tag |
| A participant who may watch (REC-20) | tags naming them, and whole-team tags |
| Anyone else | nothing |

> The bookings model page said "every participant who checked in" sees whole-team tags. This page follows the flow page instead: a player sees tags only once they may watch the video (checked in **and** logged RPE), because a tag without the video is useless.

**REC-28.** Players cannot create tags, private or shared.

## Avatars

**REC-30.** A user asks for an avatar upload form: `file_name` ending in `.jpg`, `.jpeg`, `.png` or `.webp`, `size_bytes` 1 to 5 MiB. Key `avatars/<user id>/<UUID>.<ext>`. Confirm: same checks as REC-12; sets `users.avatar` to the key; the old object is deleted. Wherever a user's avatar is shown (profile, public profile), it is a signed GET link, or empty.

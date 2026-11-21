# Push notifications and the scheduler (NOTE)

**Status: built, except the change from the owner's review of 2026-11-20 to NOTE-30 (the scheduler waits for a healthy backend), which is planned** (NOTE-3, the `payment_due` and `payment_marked` triggers of NOTE-20, and NOTE-33 are built, 2026-11-21). Built: devices and the sender in `backend/accounts/`, `tick` in `backend/bookings/management/commands/`, the `scheduler` service in `docker-compose.yml`). The Firebase sender is tested with the HTTP layer mocked; it has not sent a real push yet (no Firebase project).

## Devices

**NOTE-1.** New table `devices`: `user`, `token` (unique, up to 4096 characters), `platform` (`ios`, `android`, `web`), `created_at`.

**NOTE-2.** **Register.** A user sends `token` and `platform`. If the token exists for another user, it moves to the caller (a shared phone); if it exists for the caller, nothing changes (`200`); otherwise it is created (`201`).

**NOTE-3.** **Unregister.** A user deletes their own token. Logging out (ACC-31) deletes only the device token the app sends with it, so the user's other devices keep receiving pushes (*review 2026-11-20*; before, logout deleted every device). Deleting the account deletes every device (ACC-33).

## Sending

**NOTE-10.** Pushes go through Firebase Cloud Messaging (HTTP v1), which also relays to Apple's service for iPhones. The Apple key is uploaded to the Firebase console, not to this backend.

**NOTE-11.** The backend needs one secret: a Firebase service-account file, named by the setting `FCM_CREDENTIALS_FILE`. **Not provided yet.** When the setting is empty, a fake sender writes each push to the log instead of sending it. Tests always use a fake that records pushes in memory.

**NOTE-12.** A push is sent to every device of the recipient. If Firebase answers that a token is no longer registered, that device row is deleted. Any other failure is logged and ignored.

**NOTE-13.** Pushes are sent **after** the database transaction commits. A failed push never undoes or blocks the action that caused it.

**NOTE-14.** A push carries a `title`, a short `body`, and a `data` object with `type` (the trigger name in NOTE-20) and the id of the object to open.

**NOTE-15.** Every trigger is always on: no quiet hours and no per-user switches (settled at the owner's review on 2026-11-16).

## Triggers

**NOTE-20.**

| Trigger (`type`) | Recipient | Cause |
|---|---|---|
| `session_invite` | the invitee | BOOK-8 step 6, BOOK-15, BOOK-30, BOOK-31 |
| `training_request` | the coach | BOOK-20 |
| `training_confirmed` / `training_declined` | the requester | BOOK-21, BOOK-22 |
| `training_withdrawn` | the coach | BOOK-22 |
| `session_cancelled` | accepted and invited participants and the session coach, except the caller | BOOK-50 |
| `friend_request` | the other user | TEAM-1 step 5 |
| `coaching_request` | the coach | TEAM-10 |
| `group_invite` | the invitee | TEAM-22 |
| `join_request` | the group managers | TEAM-24 |
| `chat_message` | the other members; for an inquiry, the member or the club side (except the sender) | CHAT-10 |
| `offer` | the targeted user | CLUB-24 |
| `exercise_assigned` | each recipient | WEL-41 |
| `rpe_reminder` | the participant | NOTE-31 |
| `payment_due` | the payer of each new payment row | NOTE-33 (*review 2026-11-20*) |
| `payment_marked` | the payee side: the coach, or the club owner and active staff | PAY-26 (*review 2026-11-20*) |

Shadow players have no devices, so they never receive pushes. Nobody receives a push about their own action.

## The scheduler

**NOTE-30.** A `scheduler` service in docker-compose runs `python manage.py tick` every 60 seconds (same image as the backend). `tick` is safe to run twice in a row and safe to skip runs. The scheduler starts only once the backend reports healthy, so its first tick never runs before migrations (*review 2026-11-20*; removes the first-start traceback).

**NOTE-31.** **RPE reminder.** Each tick finds participant rows with `checked_in_at` set, `rpe` empty, `rpe_reminded_at` empty, whose session is `confirmed` and has `ends_at` between now − 7 days and now. For each, it sends `rpe_reminder` and sets `rpe_reminded_at` = now. Each row is reminded at most once, even if the scheduler was down for a while.

**NOTE-32.** *Decided during build (2026-11-16):* the service-account file is read once per process. Only Firebase's `UNREGISTERED` answer deletes a device (NOTE-12); a malformed-token answer is logged like any other failure. Each reminder row is claimed with a conditional update before the push is sent, so overlapping ticks never remind twice; a push that then fails is not retried (at most once). The reminder window includes both ends (`ends_at` exactly 7 days ago is still reminded). A push carries `data = {"type": <trigger>, "id": <object id>}`, all values as strings.

**NOTE-33.** **Billing** (*review 2026-11-17*, built 2026-11-21). Each tick bills the sessions whose check-in has closed (PAY-10). A session is billed once: `billed_at` is set under the session lock, so overlapping ticks and a scheduler that was down never bill twice or miss a session. After each session's billing commits, each new payment row sends `payment_due` to its payer, with the payment id, the amount, the currency and the payee's name (*review 2026-11-20*; before, billing sent no push). A push that fails is not retried.

**NOTE-9.** New column `session_participants.rpe_reminded_at` (nullable) supports NOTE-31. Approved by the owner at review, 2026-11-16.

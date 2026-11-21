# Access and roles (ACC)

**Status: built, except sign-out and password reset from the owner's review of 2026-11-20, which are planned** (ACC-30 to ACC-32; account deletion and deactivation, ACC-33 to ACC-35, built 2026-11-21). The changes from the review of 2026-11-17 (marked *review 2026-11-17*: ACC-1 group manager and coach's players, ACC-6, ACC-7, ACC-12) are built (2026-11-21). ACC-10 to ACC-13 in `backend/accounts/`, ACC-20 to ACC-23 in `backend/teams/` (avatar links arrive with REC-30). The names and default rules are applied by every endpoint. Who is who, and the default rules for seeing and changing things. Each other page adds its own "who may" line per action, using the names defined here.

## Names used on every page

**ACC-1.** Roles are worked out from data at the moment of the request; nothing is cached.

| Name | Means |
|---|---|
| **user** | Any signed-in account |
| **shadow player** | A `users` row with no email (`managed_by` is set when created; it is emptied only if the coach's account is deleted, and the row stays a shadow player). Cannot sign in, so never makes a request. *No-email test decided during build (2026-11-16)* |
| **coach** | A user with `is_coach = true` |
| **club owner** of club K | `K.owner` |
| **active membership** | A `club_members` row with `status = active` and `expires_on` empty or ≥ today (club timezone) |
| **club staff** of K | A user with an active `staff` membership of K |
| **club side** of K | The club owner of K plus the club staff of K |
| **affiliated coach** of K | A user with an active `coach` membership of K |
| **group manager** of group G | For a play group, `G.created_by`. For a team, `G.coach` only: the **team coach**. A team's creator has no rights once they are not its coach (*review 2026-11-17*) |
| **booker** of session S | `S.booked_by` |
| **session coach** of S | `S.coach` |
| **participant** of S | A user with a `session_participants` row in S, any status |
| **accepted participant** | A participant with `status = accepted` |
| **coach's players** of coach C | Users with an accepted `coaching` connection from C; active members of teams where C is the team coach; shadow players with `managed_by = C` |
| **friends** of U | Users with an accepted `friend` connection to U in either direction |
| **blocked pair** | Two users with a `blocked` connection in either direction |

**ACC-2.** A membership whose `expires_on` has passed is treated exactly like no membership: an expired staff member loses club-side access, an expired coach membership stops counting as affiliation, an expired player membership is not listed among the club's current players. The row is not deleted; the owner can extend `expires_on` to restore it.

## Default rules

**ACC-3.** Every endpoint needs a signed-in user except register, login, public club search and public court detail (CLUB-30, CLUB-31).

**ACC-4.** A user reads and changes their own data (profile, block-outs, wellness logs, devices). Nobody else changes it, except where a page says so (a coach for a shadow player, the club side checking a booker in).

**ACC-5.** Everything under a club (currencies, courts, rates, closures, equipment, overrides, discounts, memberships) is changed only by the club owner. The club side may additionally do the day-to-day actions listed in ACC-6. Coaches, players and the platform's admins (through the Django admin) have no API rights over a club's setup.

**ACC-6.** Club staff may: read the club's schedule (RPT-1), approve and decline rentals (BOOK-40), check participants in (PAY-2, PAY-3), mark the club's payments paid or due again (PAY-20, PAY-21), read the due list (RPT-2), and read and reply to the club's inquiry chats (CHAT-8). Staff may not read revenue, customers or repeat rate (RPT-3 to RPT-5), and may not change any configuration.

**ACC-7.** Platform admins work through the Django admin only: sports, the exercise catalogue, commission rates, `settled_at` on payments, and teams left without a coach (TEAM-34). No API endpoint changes these.

## Shadow players

**ACC-10.** Who may: a coach. Creates a user with `full_name` (required, 1–255 characters) and optionally `date_of_birth`, `sex`, `dominant_hand`, `height_cm`, `weight_kg`, `nationality` (same validation as the profile). The row gets no email, an unusable password, `managed_by` = the coach, `is_coach = false`, `timezone` = the coach's timezone.

**ACC-11.** The managing coach may read and edit those fields, and may deactivate the shadow player (`is_active = false`) and reactivate it (*decided during build, 2026-11-16*). Nobody else can see or edit a shadow player except where a page lists them (team member lists, session participant lists, tags).

**ACC-12.** A shadow player is never: a friend, a coaching-connection target, a chat member, a payer chosen in `coach_fee_payer` by anyone but their managing coach, or found by user search. They can be: an active team member (TEAM-27), a session participant (BOOK-10, BOOK-30, BOOK-31), a payer in a split court or coach fee (PAY-11, PAY-12; the club or the coach collects from the parent), and named in a recording tag.

**ACC-13.** A shadow player cannot be converted into a normal account in this version.

## Finding people

**ACC-20.** **User search** (signed-in only): `q` of at least 2 characters matches `full_name` case-insensitively (contains), or an exact `email` (case-insensitive). Shadow players, inactive users and users in a blocked pair with the caller are left out. Results show the **public profile** only.

**ACC-21.** The **public profile** is: `id`, `full_name`, `avatar` (signed link, REC-30), `is_coach`, and when `is_coach` is true also `coach_bio`, `coach_rate`, `coach_currency` and the clubs where the user is an affiliated coach (`id`, `name`). Email, phone and body data are never in a public profile.

**ACC-22.** **Coach search**: coaches only (`is_coach = true`, active, not shadow), optional `q` on name, optional `club` (affiliated coaches of that club). Sorted by `full_name`. Same public profile. Users in a blocked pair with the caller are left out, as in ACC-20 (*decided during build, 2026-11-16*: their profile is 404 by ACC-23). `club` must be a club the caller can see; otherwise the list is empty.

**ACC-23.** Any user may read any other non-shadow active user's public profile by id. A blocked pair gets `404`.

## Your account

*Review 2026-11-20, planned.* Register, login and the profile are described on the [accounts API page](../api/accounts.md); these rules add sign-out, password reset and account deletion.

**ACC-30.** **Tokens.** One token per user, with no expiry; logging in again returns the same token. Only a password reset (ACC-32) or deleting the account (ACC-33) deletes it, which signs the user out on every device.

**ACC-31.** **Logout.** `POST /api/auth/logout/` with an optional `device_token`. It deletes that device of the caller, if it exists (NOTE-3), and nothing else: the token is kept, so the user's other devices stay signed in. The app forgets the token on its side. Answers `204`, also when the device is unknown. *Before: logout deleted the token and every device, signing the user out everywhere.*

**ACC-32.** **Password reset.**
1. `POST /api/auth/password-reset/` with `email`. Always answers `200` with the same body, so it never tells whether an account exists. It counts against the same limit as register and login (10 requests a minute per IP).
2. If the email belongs to an active user who is not a shadow player, an email is sent with a link to `https://<PASS_HOST>/account/reset/<uid>/<token>/`, Django's built-in reset-confirm page and token generator. The link is valid for 1 hour and works once (Django's token stops working once the password changes).
3. The new password passes the same strength checks as at register. On success the user's token is deleted (ACC-30); devices are kept.

Email goes out through the SMTP server named in the settings (`EMAIL_HOST` and the rest, from `.env`; Brevo at launch). With `EMAIL_HOST` empty, emails are written to the log instead (development and tests).

**ACC-33.** **Delete account.** `DELETE /api/me/` with `password`. A wrong password: `400` on `password`. A user who owns any club: `400 owns_club` (club hand-over is not in this version). Otherwise, in one transaction:
1. **Upcoming sessions.** Every session that has not started, where nobody has checked in, and where the user is the booker or the session coach: a `requested` one is cancelled as in BOOK-22, a `confirmed` one as in BOOK-50 (rentals still `requested` become `declined`; participants are notified). In any other session that has not started, the user's own participant row becomes `declined`.
2. **Groups.** Play groups the user created are deleted with their chat (TEAM-30). Teams the user coaches lose their coach (TEAM-34). The user's member rows in every other group are deleted, which also removes them from the group chats (TEAM-28).
3. **Shadow players** the user manages get `managed_by` emptied. They stay on their teams, and nobody can edit them any more except a platform admin.
4. **Deleted:** the token, devices, connections (both directions), block-outs, sleep and soreness logs, exercise assignments made to the user, achievements, chat memberships and club memberships.
5. **Scrubbed on the user row:** `full_name` = "Deleted user"; `email` = `deleted-<id>@invalid` (it cannot be empty: no email means shadow player, ACC-1); `phone`, `date_of_birth`, `sex`, `height_cm`, `weight_kg`, `nationality`, `dominant_hand`, `coach_bio`, `coach_rate` and `coach_currency` emptied; `is_coach` = false; `timezone` = `UTC`; password made unusable; `is_active` = false. After commit the avatar file is deleted from storage and `avatar` emptied.

**Kept**, pointing at the "Deleted user" row, because they are money or other people's history: sessions, participant rows in past sessions (with RPE), payments in both directions, commission rows, recordings the user uploaded, recording tags, messages the user sent, and exercise assignments the user made to others. Answers `204`. Nothing can undo it; registering again with the same email creates a new account.

**ACC-34.** **After deletion.** The user shows as "Deleted user" wherever they appear, and is never found by search or by profile id (ACC-20, ACC-23: inactive). Payments they owe stay due; the payee may still receive or waive them (PAY-20, PAY-25). Payments owed to them as a coach stay due, and nobody can mark them any more; paid ones can still be settled by a platform admin (COM-10).

**ACC-36.** *Decided during build (2026-11-21), what ACC-33 leaves open:* the body is checked before the rule (GEN-4): a missing or wrong `password` is `400` on `password`, then `owns_club`. In step 1 a request the user made is withdrawn and one made to them is declined (BOOK-22, the other side is told); a confirmed session is cancelled as BOOK-50 with the user as the caller (everyone else listed is told); rows in sessions that are already cancelled are left alone. Teams the user created get `created_by` emptied (step 2). The avatar is emptied in the transaction and its file deleted after commit. Each later app forgets the user through one function called from `accounts.services.delete_account` ([backend README](../README.md)).

**ACC-35.** A platform admin setting `is_active = false` in the Django admin is **deactivation**, not deletion: nothing is scrubbed or removed, sign-in stops (login answers like a wrong password), and setting it back restores the account. Only ACC-33 deletes an account.

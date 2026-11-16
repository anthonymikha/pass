# Access and roles (ACC)

**Status: built.** ACC-10 to ACC-13 in `backend/accounts/`, ACC-20 to ACC-23 in `backend/teams/` (avatar links arrive with REC-30). The names and default rules are applied by every endpoint. Who is who, and the default rules for seeing and changing things. Each other page adds its own "who may" line per action, using the names defined here.

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
| **group manager** of group G | `G.owner`, and also `G.coach` when G is a team |
| **booker** of session S | `S.booked_by` |
| **session coach** of S | `S.coach` |
| **participant** of S | A user with a `session_participants` row in S, any status |
| **accepted participant** | A participant with `status = accepted` |
| **coach's players** of coach C | Users with an accepted `coaching` connection from C; active members of teams where C is a group manager; shadow players with `managed_by = C` |
| **friends** of U | Users with an accepted `friend` connection to U in either direction |
| **blocked pair** | Two users with a `blocked` connection in either direction |

**ACC-2.** A membership whose `expires_on` has passed is treated exactly like no membership: an expired staff member loses club-side access, an expired coach membership stops counting as affiliation, an expired player membership is not listed among the club's current players. The row is not deleted; the owner can extend `expires_on` to restore it.

## Default rules

**ACC-3.** Every endpoint needs a signed-in user except register, login, public club search and public court detail (CLUB-30, CLUB-31).

**ACC-4.** A user reads and changes their own data (profile, block-outs, wellness logs, devices). Nobody else changes it, except where a page says so (a coach for a shadow player, the club side checking a booker in).

**ACC-5.** Everything under a club (currencies, courts, rates, closures, equipment, overrides, discounts, memberships) is changed only by the club owner. The club side may additionally do the day-to-day actions listed in ACC-6. Coaches, players and the platform's admins (through the Django admin) have no API rights over a club's setup.

**ACC-6.** Club staff may: read the club's schedule (RPT-1), approve and decline rentals (BOOK-40), check the booker in (PAY-3), mark the club's payments paid or due again (PAY-20, PAY-21), read the due list (RPT-2), and read and reply to the club's inquiry chats (CHAT-8). Staff may not read revenue, customers or repeat rate (RPT-3 to RPT-5), and may not change any configuration.

**ACC-7.** Platform admins work through the Django admin only: sports, the exercise catalogue, commission rates, and `settled_at` on payments. No API endpoint changes these.

## Shadow players

**ACC-10.** Who may: a coach. Creates a user with `full_name` (required, 1–255 characters) and optionally `date_of_birth`, `sex`, `dominant_hand`, `height_cm`, `weight_kg`, `nationality` (same validation as the profile). The row gets no email, an unusable password, `managed_by` = the coach, `is_coach = false`, `timezone` = the coach's timezone.

**ACC-11.** The managing coach may read and edit those fields, and may deactivate the shadow player (`is_active = false`) and reactivate it (*decided during build, 2026-11-16*). Nobody else can see or edit a shadow player except where a page lists them (team member lists, session participant lists, tags).

**ACC-12.** A shadow player is never: a friend, a coaching-connection target, a chat member, a payer chosen in `coach_fee_payer` by anyone but their managing coach, or found by user search. They can be: an active team member (TEAM-27), a session participant (BOOK-10, BOOK-30, BOOK-31), a payer in a coach-fee split (PAY-12; the coach collects from the parent), and named in a recording tag.

**ACC-13.** A shadow player cannot be converted into a normal account in this version.

## Finding people

**ACC-20.** **User search** (signed-in only): `q` of at least 2 characters matches `full_name` case-insensitively (contains), or an exact `email` (case-insensitive). Shadow players, inactive users and users in a blocked pair with the caller are left out. Results show the **public profile** only.

**ACC-21.** The **public profile** is: `id`, `full_name`, `avatar` (signed link, REC-30), `is_coach`, and when `is_coach` is true also `coach_bio`, `coach_rate`, `coach_currency` and the clubs where the user is an affiliated coach (`id`, `name`). Email, phone and body data are never in a public profile.

**ACC-22.** **Coach search**: coaches only (`is_coach = true`, active, not shadow), optional `q` on name, optional `club` (affiliated coaches of that club). Sorted by `full_name`. Same public profile. Users in a blocked pair with the caller are left out, as in ACC-20 (*decided during build, 2026-11-16*: their profile is 404 by ACC-23). `club` must be a club the caller can see; otherwise the list is empty.

**ACC-23.** Any user may read any other non-shadow active user's public profile by id. A blocked pair gets `404`.

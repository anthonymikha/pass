# Friends, coaching links, play groups and teams (TEAM)

**Status: planned.**

## Friends

**TEAM-1.** **Request.** Who may: any user, to another active non-shadow user who is not themselves. Checks, in order:
1. The pair is blocked (either way): `400 cannot_connect`.
2. They are already friends: `200`, no change (GEN-5).
3. The caller already has a pending request to them: `200`, no change.
4. The other user has a pending request to the caller: that request becomes `accepted` (both want it); `200`.
5. Otherwise create `connections` (`user` = caller, `other_user` = them, `type = friend`, `status = pending`), `201`, and notify them (NOTE-20).

**TEAM-2.** **Accept.** Who may: the `other_user` of a pending friend row. `pending` → `accepted`.

**TEAM-3.** **Decline, cancel, unfriend.** The `other_user` declines a pending request, the `user` cancels it, or either side ends an accepted friendship: the row is deleted.

**TEAM-4.** **Block.** Who may: any user, against any other user. Deletes every friend row between the two (either way) and creates one row `user` = blocker, `other_user` = blocked, `type = friend`, `status = blocked`. Coaching rows between them are deleted too. Effects of a blocked pair: no friend requests (TEAM-1), no coaching request (TEAM-10), no invites (BOOK-7), no training requests (BOOK-20), no new direct chat and no sending in an existing one (CHAT-3), and they do not find each other in search (ACC-20).

**TEAM-5.** **Unblock.** Who may: the blocker only. Deletes the blocked row.

**TEAM-6.** **Lists.** The caller's friends; incoming pending requests; outgoing pending requests; users the caller blocked. Users who blocked the caller are never shown.

| From | To | Who |
|---|---|---|
| (new) | `pending` | requester |
| `pending` | `accepted` | the other user, or a matching reverse request (TEAM-1 step 4) |
| `pending` / `accepted` | (deleted) | either side |
| any | `blocked` (new row) | blocker |
| `blocked` | (deleted) | blocker |

## Coaching links (1:1)

**TEAM-10.** **Request.** Who may: a player (any user), to a coach who is not themselves and not in a blocked pair. Creates `connections` with `user` = the **coach**, `other_user` = the **player**, `type = coaching`, `status = pending`. Already pending or accepted: `200`, no change. Notifies the coach.

**TEAM-11.** **Accept or decline.** Who may: the coach (the row's `user`). Accept: `pending` → `accepted`. Decline: row deleted.

**TEAM-12.** **End.** Either side deletes an accepted row. Past sessions and assignments stay.

**TEAM-13.** A coach cannot start a coaching link; coaches reach players through teams (TEAM-22) and shadow players (ACC-10).

## Block-out times

**TEAM-15.** A user creates, changes and deletes their own `user_blockouts`. Fields and validation as for court closures (CLUB-15), times in the user's timezone. A block-out never cancels sessions. Used only for availability (AVL-20).

## Play groups and teams

**TEAM-20.** **Create.**
- Play group: any user. Team: a coach only (else `400 not_a_coach`).
- Input: `name` (1–255), optional `sport`.
- Writes, in one transaction: the `groups` row (`owner` = caller; for a team also `coach` = caller); a `group_members` row for the caller, `active`; the group's `chats` row (`type = group`); a `chat_members` row for the caller.

**TEAM-21.** **Seeing a group.** Any user may read a group's `name`, `type`, `sport`, `owner`, `coach` and active member count by id (so an invite link can show it). Only active members and group managers see the member list and statuses.

**TEAM-22.** **Invite.** Who may: a group manager. Invitee: active, non-shadow, not in a blocked pair with the inviter. For a play group the invitee must also be a friend of the inviter. If the invitee already has a row: `requested` becomes `active` (they had asked), `invited`/`active` stay as they are (`200`). Otherwise create `invited`, notify them.

**TEAM-23.** **Answer an invite.** The invitee: accept (`invited` → `active`) or decline (row deleted).

**TEAM-24.** **Ask to join.** Any active non-shadow user, not blocked by the owner or the coach. If an `invited` row exists it becomes `active`; an existing `requested` or `active` row stays (`200`). Otherwise create `requested`, notify the group managers.

**TEAM-25.** **Answer a request.** A group manager: accept (`requested` → `active`) or reject (row deleted).

**TEAM-26.** **Leave or remove.** A member deletes their own row (leave). A group manager deletes any member's row except the owner's. Sessions already booked keep their participant rows.

**TEAM-27.** **Add a shadow player.** A group manager of a **team** adds a shadow player they manage (`managed_by` = caller) directly as `active`. Shadow players cannot join play groups. Error: `400 not_your_player`.

**TEAM-28.** **Chat membership follows group membership.** Whenever a non-shadow user's row becomes `active`, add a `chat_members` row to the group's chat (if missing). Whenever an active row is deleted, delete their `chat_members` row. Shadow players never get one (ACC-12). Same transaction as the membership change.

**TEAM-29.** **Change a team's coach.** Who may: the team's `owner`. The new coach must be an active coach, not shadow. Sets `groups.coach`; the owner does not change. If the new coach has no active member row, one is created (`active`, plus chat membership, TEAM-28). The previous coach stays a member unless the owner removes them. Sessions already booked keep their `coach`. Error: `400 not_a_coach`.

**TEAM-30.** **Rename or delete.** The owner may change `name` and `sport`, or delete the group. Deleting removes its member rows; its sessions keep their data with `group` emptied; the chat stays, with `group` emptied and its members removed.

**TEAM-31.** The owner cannot leave their own group (`400 owner_cannot_leave`); they delete it instead. Ownership cannot be transferred in this version.

| From | To | Who |
|---|---|---|
| (new) | `invited` | group manager |
| (new) | `requested` | the user |
| (new) | `active` | creator (TEAM-20), manager adding a shadow player (TEAM-27), new coach (TEAM-29) |
| `invited` | `active` | the invitee, or the user asking to join |
| `requested` | `active` | group manager, or the manager inviting them |
| any | (deleted) | the member (leave or decline), a manager (remove or reject), except the owner's row |

## What a coach can see about their players

**TEAM-40.** A coach may read, for each of the coach's players (ACC-1): attendance and RPE history (RPT-8), soreness and sleep logs, exercise assignments (WEL-40), and availability (AVL-22). Nothing about users who are not the coach's players.

## Not decided

- Stopping reverse duplicate friend rows by storing the pair in a fixed order. Recommended default: no schema change; TEAM-1 step 4 turns a crossing request into an acceptance. A true race (both tap within milliseconds) can still leave two pending rows; either acceptance makes them friends and the list shows the friend once.
- Transferring group ownership. Recommended default: not built.

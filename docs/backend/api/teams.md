# API: teams (play groups, teams, finding people)

**Status: built and tested.** Code: [views](../../../backend/teams/views.py), [serializers](../../../backend/teams/serializers.py), [services](../../../backend/teams/services.py), [tests](../../../backend/teams/tests.py); group chat upkeep in [chat/services.py](../../../backend/chat/services.py). Rules: [teams-and-coaching](../logic/teams-and-coaching.md) (TEAM-20 to TEAM-31), [access-and-roles](../logic/access-and-roles.md) (ACC-1, ACC-20 to ACC-23), [chat](../logic/chat.md) (CHAT-4). Same conventions as [accounts](accounts.md).

## Who may call

Every call needs a token. Every group is visible by id to every user (TEAM-21), so an action the caller may not do is `403`, never `404`. The member list is the exception: it is hidden (`404`) from anyone who is not an active member or a group manager. A group manager is the owner, and for a team also its coach (ACC-1).

## Endpoints

| Method | Path | Who | Body / notes | Success |
|---|---|---|---|---|
| POST | `/api/groups/` | any user; a team needs a coach | `name` (1-255), `type` (`play_group`, `team`), optional `sport` (id). `400 not_a_coach` for a team by a non-coach (TEAM-20) | `201` group |
| GET | `/api/me/groups/` | any user | groups where the caller has a member row, each `{id, name, type, sport, owner, coach, member_count, my_status}`; optional `?status=invited\|requested\|active` (`400` otherwise); by name then id; paged (TEAM-32) | `200` page |
| GET | `/api/groups/<id>/` | any user | `{id, name, type, sport, owner, coach, member_count}`; `owner` and `coach` are `{id, full_name, is_coach}` (TEAM-21) | `200` |
| PATCH | `/api/groups/<id>/` | owner | `name`, `sport` (null clears) (TEAM-30) | `200` |
| DELETE | `/api/groups/<id>/` | owner | members go; the chat stays with no group and no members (TEAM-30) | `204` |
| GET | `/api/groups/<id>/members/` | active members, managers | page of `{id, user, status, created_at}`; others `404` (TEAM-21) | `200` |
| POST | `/api/groups/<id>/members/` | manager | invite: `user` (id). Play groups: friends only. `400 cannot_invite` (not a friend, or blocked pair). A `requested` row becomes `active` (TEAM-22) | `201` new, `200` otherwise |
| POST | `/api/groups/<id>/accept/` | the invitee | accept an invite; `404` if not invited (TEAM-23) | `200` (also on repeat) |
| POST | `/api/groups/<id>/join/` | any user | ask to join; managers get a push. `400 cannot_join` if blocked by the owner or the coach. An `invited` row becomes `active` (TEAM-24) | `201` new, `200` otherwise |
| POST | `/api/groups/<id>/members/<user_id>/accept/` | manager | accept a join request; `404` if the user has not asked (TEAM-25) | `200` (also on repeat) |
| DELETE | `/api/groups/<id>/members/<user_id>/` | the member themself, or a manager | leave, decline an invite, remove, reject a request. Others `403`. The owner's row: `400 owner_cannot_leave` (TEAM-26, TEAM-31) | `204` |
| POST | `/api/groups/<id>/shadow-players/` | manager of a team | `player` (shadow player id). `400 not_your_player` unless the caller manages them; `400 not_a_team` on a play group (TEAM-27) | `201` new, `200` if already in |
| POST | `/api/groups/<id>/coach/` | owner of a team | `coach` (user id). `400 not_a_coach`; `400 not_a_team` (TEAM-29) | `200` group |
| GET | `/api/users/?q=` | any user | `q` at least 2 characters (`400` otherwise). Name contains, or exact email. Public profiles (ACC-20) | `200` page |
| GET | `/api/users/<id>/` | any user | public profile; shadow, inactive or blocked-pair users `404` (ACC-23) | `200` |
| GET | `/api/coaches/` | any user | optional `q` (name), `club` (id of a club the caller can see; otherwise an empty list). Sorted by name (ACC-22) | `200` page |

Chat membership follows the rows (TEAM-28, CHAT-4): a row turning `active` adds the user to the group chat, deleting an active row removes them; shadow players never get one. Pushes (NOTE-20): `group_invite` to the invitee, `join_request` to the managers other than the asker; both carry `{"id": <group id>}`.

## Public profile (ACC-21)

```json
{"id": 7, "full_name": "Carl Coach", "avatar": "", "is_coach": true,
 "coach_bio": "Ex-pro", "coach_rate": "25.500", "coach_currency": "USD",
 "clubs": [{"id": 1, "name": "Beirut Hoops"}]}
```

`coach_bio`, `coach_rate`, `coach_currency` and `clubs` appear only when `is_coach` is true; `clubs` lists the clubs with an active, unexpired coach membership (ACC-2). `avatar` is always `""` until signed links exist (REC-30). Email, phone and body data are never included.

## Helpers for later tasks

`teams.services.coachs_players(coach)` (ACC-1: accepted coaching links from the coach, active members of teams the coach manages, shadow players managed by the coach; never the coach themself), `group_managers(group)` and `is_group_manager(user, group)`.

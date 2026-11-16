# Flow: friends, play groups, coaches and teams

**Status: planned.** Rules: [teams-and-coaching](../logic/teams-and-coaching.md), [booking](../logic/booking.md), [access-and-roles](../logic/access-and-roles.md).

Models: [User, Connection, UserBlockout](../models/accounts.md), [ClubMember](../models/venues.md), [Group, GroupMember](../models/teams.md), [Session, SessionParticipant](../models/bookings.md), [Payment](../models/billing.md), [Chat](../models/chat.md).

## Players: friends and play groups

| Step | Rules |
|---|---|
| 1. Add a friend, accept, block | [TEAM-1 to TEAM-6](../logic/teams-and-coaching.md#friends) |
| 2. Keep block-out times (work, school) | [TEAM-15](../logic/teams-and-coaching.md#block-out-times) |
| 3. Create a play group, invite friends | [TEAM-20 to TEAM-23](../logic/teams-and-coaching.md#play-groups-and-teams) |
| 4. Find a time everyone is free | [AVL-20 to AVL-25](../logic/court-availability.md#personal-and-group-availability) |
| 5. Book for the group | [BOOK-10, BOOK-11](../logic/booking.md#group-bookings) |

## Coaches

| Step | Rules |
|---|---|
| 1. Become a coach (`is_coach` on the profile) | [ACC-1](../logic/access-and-roles.md) |
| 2. Affiliate with clubs | [CLUB-26, CLUB-27](../logic/clubs-and-courts.md#club-members) |
| 3. Be found | [ACC-21, ACC-22](../logic/access-and-roles.md#finding-people) |
| 4. A player asks for training; the coach confirms with time, fee and court | [BOOK-20 to BOOK-23](../logic/booking.md#training-requests-player-asks-a-coach) |
| 5. Ongoing 1:1 coaching link | [TEAM-10 to TEAM-13](../logic/teams-and-coaching.md#coaching-links-11) |

## Teams

| Step | Rules |
|---|---|
| 1. The coach creates a team | [TEAM-20](../logic/teams-and-coaching.md#play-groups-and-teams) |
| 2. Fill it: invites, join requests, shadow players | [TEAM-22 to TEAM-27](../logic/teams-and-coaching.md#play-groups-and-teams), [ACC-10 to ACC-13](../logic/access-and-roles.md#shadow-players) |
| 3. Book training, choose who pays the coach fee | [BOOK-30 to BOOK-33](../logic/booking.md#training-booked-by-a-coach) |
| 4. Check in players and shadow players; payments are split | [PAY-2, PAY-12](../logic/check-in-and-payments.md) |
| 5. Change the team's coach | [TEAM-29](../logic/teams-and-coaching.md#play-groups-and-teams) |
| 6. Follow players | [TEAM-40](../logic/teams-and-coaching.md#what-a-coach-can-see-about-their-players), [RPT-8](../logic/owner-reports.md) |

```
coach ─coach─> Group(team) ─> GroupMember(active) ─┐
   │                                               ├─> Session(training, group) ─> SessionParticipant × n
   └─booked_by, coach──────────────────────────────┘            │
                                                    coach checks in ─> Payment × n (split) or × 1
```

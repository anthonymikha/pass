# Flow: messaging

**Status: planned.** Delivery is by polling first; WebSockets later.

Models: [Chat, ChatMember, Message](../models/chat.md), [Group](../models/teams.md), [Club, ClubMember](../models/venues.md), [Session](../models/bookings.md).

## Direct messages

1. Player or coach opens a conversation with another user.
2. Find an existing `Chat` with `type=direct` that has both users as `ChatMember`; create it with both members if none.
3. Send: create a `Message` with `sender`.

## Group chats

- Created together with the `Group` (`type=group`, `group` set).
- Members mirror the group's active members: add a `ChatMember` when someone becomes active, remove it when they leave.
- **Session cards:** when a session for the group is confirmed, a `Message` with `session` set and no sender is posted. The app shows the start and end time and opens the session page from it.

```
Session(group) confirmed ─> Message(chat=group.chat, session=…) ─> card in the chat
```

## Court inquiries

1. A player or coach opens an inquiry with a club: a `Chat` with `type=inquiry`, `club` set, and themselves as the `ChatMember`. One per user and club.
2. The club's owner and its active staff (`ClubMember`, `role=staff`) can read and reply. They are not stored as members; access is checked against the club at the time.
3. Owners also use this chat to tell a player about an offer (a `Discount` with `user` set).

## Reading and unread counts

- **Poll:** fetch messages in a chat with `id` greater than the last one the client has.
- **Mark read:** set the caller's `ChatMember.last_read_at` to now.
- **Unread:** messages newer than `last_read_at` not sent by the caller.

For the club side of an inquiry there is no member row, so unread state for owners and staff still needs a decision.

## Access rules

| Chat type | Who can read and write |
|---|---|
| direct | its two members |
| group | its members |
| inquiry | its member, plus the club's owner and active staff |

## Open points

- Unread tracking for club owners and staff on inquiries.
- Whether direct chats are limited to friends and coach–player pairs.

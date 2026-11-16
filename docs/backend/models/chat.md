# chat models

Source: [backend/chat/models.py](../../../backend/chat/models.py). Tables: `chats`, `chat_members`, `messages`.

## Chat (`chats`)

| `type` | Between | `group` | `club` |
|---|---|---|---|
| `direct` | Two users (players, coaches) | empty | empty |
| `group` | All members of a play group or team | set | empty |
| `inquiry` | One user and a club | empty | set |

`club_last_read_at` (empty by default): on an inquiry, the club side's read marker, shared by the owner and all staff ([CHAT-11](../logic/chat.md#messages)); unused on other types.

- A group has exactly one chat (`group` is one-to-one). Create it together with the group.
- A direct chat between two users should be reused, not duplicated: look for an existing `direct` chat having both as members before creating one.
- An inquiry is one chat per (user, club).

## ChatMember (`chat_members`)

Who is in a chat, and how far they have read. Unique per (chat, user).

| Field | Meaning |
|---|---|
| `last_read_at` | Messages newer than this are unread for that user |

The club side's read marker on an inquiry is `chats.club_last_read_at`, shared by the owner and staff ([CHAT-11](../logic/chat.md#messages)). Unread counts: [CHAT-13](../logic/chat.md#messages).

- Group chats: keep members in step with the group's active members, shadow players excluded ([TEAM-28](../logic/teams-and-coaching.md#play-groups-and-teams)).
- Inquiry chats: the inquiring user is the member. The club side is whoever owns or staffs the club at the time, so they are not stored as members.

```python
unread = Message.objects.filter(chat=chat, created_at__gt=member.last_read_at or chat.created_at).exclude(sender=me).count()
```

## Message (`messages`)

| Field | Meaning |
|---|---|
| `chat` | |
| `sender` | Empty = system-generated |
| `body` | Text; may be empty for a session card |
| `session` | Set = this message is a **session card**: it shows the session's start and end time and links to the session page |

When a session for a group is confirmed, a card is posted in that group's chat:

```python
Message.objects.create(chat=session.group.chat, session=session)   # sender empty: system card
```

The card stores no times of its own; clients read them from the session, so a rescheduled session shows correctly.

### Polling

Clients fetch new messages by asking for those after the last one they have (`id > last_seen_id`, ordered by `id`). Live delivery over WebSockets is a later change that does not affect these tables.

## Deleting

- A user who sent messages cannot be deleted (their messages would otherwise look like system messages). Deactivate instead.
- Deleting a chat deletes its members and messages.
- Deleting a group or club leaves the chat in place with the link emptied.

## Used together with

- `teams.Group` for group chats, `venues.Club` for inquiries, `bookings.Session` for cards.
- Journey: [chat](../flows/chat.md).

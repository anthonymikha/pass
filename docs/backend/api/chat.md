# API: chat

**Status: built and tested.** Code: [views](../../../backend/chat/views.py), [serializers](../../../backend/chat/serializers.py), [services](../../../backend/chat/services.py), [tests](../../../backend/chat/tests.py). Rules: [chat](../logic/chat.md) (CHAT-1 to CHAT-17), [access-and-roles](../logic/access-and-roles.md) (ACC-1, ACC-2, ACC-6, ACC-12), [notifications](../logic/notifications.md) (NOTE-20 `chat_message`). Same conventions as [accounts](accounts.md).

## Who may call

Every call needs a token. A chat is visible to its members, and for an inquiry chat also to the club side of its club (owner and staff with a current membership, ACC-1, ACC-2), checked at the time of the request. A chat the caller may not see is `404` (GEN-3), also for a staff member whose membership has expired. A group chat's members are the group's active, non-shadow members (CHAT-4); the group endpoints keep them in step.

## Endpoints

| Method | Path | Who | Body / notes | Success |
|---|---|---|---|---|
| POST | `/api/chats/direct/` | any user | `user` (id). Opens or finds the direct chat with that user (CHAT-2). `400 cannot_chat` unless CHAT-1 holds: not oneself, both active and not shadow, not a blocked pair, and friends or a coach with one of their players (either direction). Unknown id: `400` on `user` | `201` new, `200` existing, same chat from either side |
| POST | `/api/clubs/<id>/inquiries/` | any user (the club must be visible, else `404`) | No body: the caller's own inquiry with the club, found or created (CHAT-6). `400 cannot_chat` for the club's owner and staff | `201` new, `200` existing |
| POST | `/api/clubs/<id>/inquiries/` | the club side | `user` (id): the club side opens or finds that user's inquiry (CHAT-7). `400 cannot_chat` unless the user is active, not a shadow player, not on the club side, and has a non-cancelled session at the club (booker or participant), a current membership of it, or an offer targeted at them. `user` from anyone else: `400 cannot_chat` | `201` new, `200` existing |
| GET | `/api/chats/` | any user | Chats the caller is a member of, plus every inquiry chat of clubs on whose side they are now. Sorted by last message time, newest first (a chat with no message by its creation time); page-number paged (GEN-12) (CHAT-15) | `200` page |
| GET | `/api/chats/<id>/` | member, club side | One chat, same shape as a list row | `200` |
| GET | `/api/chats/<id>/messages/` | member, club side | Not paged (CHAT-14). `?after=<id>` (default 0): larger ids, oldest first. `?before=<id>`: smaller ids, newest first. `?limit=` 1 to 200, default 50. Not both `after` and `before`. Anything else invalid: `400` on that field | `200` plain list of messages |
| POST | `/api/chats/<id>/messages/` | member, club side | `body`: trimmed, 1 to 4000 characters, text only (CHAT-10, CHAT-17). In a direct chat CHAT-1 must hold now: `400 cannot_chat` (CHAT-3) | `201` message |
| POST | `/api/chats/<id>/read/` | member, club side | Sets the caller's marker to now: their member row, or, on the club side, `chats.club_last_read_at`, shared by the owner and all staff (CHAT-11, CHAT-12). A repeat only moves the time (GEN-5) | `200` chat |

There is no edit or delete endpoint (CHAT-16): `PUT`, `PATCH` and `DELETE` on a message are `404` or `405`.

## Chat

```json
{"id": 4, "type": "inquiry", "group": null, "club": 1, "title": "Beirut Hoops",
 "last_message": {"id": 12, "chat": 4, "sender": {"id": 7, "full_name": "Pat"}, "body": "Do you rent shoes?", "session": null, "created_at": "2026-11-16T12:00:00Z"},
 "unread_count": 1, "created_at": "2026-11-16T11:59:00Z"}
```

- `title` (CHAT-15): a direct chat shows the other person's name; a group chat the group's name; an inquiry shows the club's name to the inquiring user and the inquirer's name to the club side. `last_message` is `null` until there is one.
- `unread_count` (CHAT-13): messages after the viewer's marker (all if it is empty) not sent by the viewer. For the club side, only those sent by the inquirer or the system. A user who is both the inquirer and club side of the same chat reads it as the inquirer.

## Message

`{id, chat, sender, body, session, created_at}`. `sender` is `{id, full_name}`, or `null` for a session card. A session card (CHAT-30, CHAT-31) has an empty `body` and `session` set to the session id; clients read its times from the session.

## Pushes (NOTE-20)

`chat_message` after the commit of a send, `{"id": <chat id>}` as data, title the sender's name, body the first 140 characters. Recipients: the other members; for an inquiry, the club side (owner and current staff) when the member writes, the member when the club side writes. Never the sender.

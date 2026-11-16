# Flow: messaging

**Status: built** (`backend/chat/`, [API](../api/chat.md)). Rules: [chat](../logic/chat.md). Delivery by polling first; WebSockets later.

Models: [Chat, ChatMember, Message](../models/chat.md), [Group](../models/teams.md), [Club, ClubMember](../models/venues.md), [Session](../models/bookings.md).

| Kind | Who talks | Rules |
|---|---|---|
| Direct | Friends, or a coach and their player; never a blocked pair | [CHAT-1 to CHAT-3](../logic/chat.md#who-may-talk-to-whom) |
| Group | The active members of a play group or team | [CHAT-4](../logic/chat.md#who-may-talk-to-whom), [TEAM-28](../logic/teams-and-coaching.md#play-groups-and-teams) |
| Inquiry | One user and a club's owner and staff (a shared inbox) | [CHAT-5 to CHAT-8](../logic/chat.md#who-may-talk-to-whom) |

| Action | Rules |
|---|---|
| Send, poll (`after=<id>`), scroll back (`before=<id>`) | [CHAT-10, CHAT-14](../logic/chat.md#messages) |
| Mark read, unread counts, chat list | [CHAT-11 to CHAT-15](../logic/chat.md#messages) |
| Session card when a group session is confirmed | [CHAT-30, CHAT-31](../logic/chat.md#session-cards) |
| Push for new messages | [NOTE-20](../logic/notifications.md#triggers) |

```
Session(group) confirmed ─> Message(chat=group.chat, session=…) ─> card in the chat
```

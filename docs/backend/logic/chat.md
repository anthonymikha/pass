# Chat (CHAT)

**Status: built** (`backend/chat/`, API page [chat](../api/chat.md)). Delivery by polling. WebSockets later, with no change to these rules.

## Who may talk to whom

**CHAT-1.** **Direct chat** between users A and B is allowed when A ≠ B, both are active and not shadow, they are not a blocked pair, and at least one holds:
- A and B are friends;
- one is a coach and the other is one of that coach's players (ACC-1).

**CHAT-2.** **Open a direct chat.** Who may: A, about B, when CHAT-1 holds (else `400 cannot_chat`). If a `direct` chat with exactly A and B as members exists, it is returned (`200`); otherwise one is created with both as `chat_members` (`201`). To stop two simultaneous opens creating two chats, the lookup and create run in one transaction that first locks both users' rows, in id order.

**CHAT-3.** Sending in a direct chat requires CHAT-1 to hold **at the time of sending** (`400 cannot_chat`). Reading old messages stays allowed for its members after a friendship ends or a block starts.

**CHAT-4.** **Group chat**: one per group, created with the group (TEAM-20). Its members are the group's active non-shadow members (TEAM-28). Only members read and send.

**CHAT-5.** **Inquiry chat**: one per (user, club). Its one `chat_members` row is the inquiring user.

**CHAT-6.** **Open an inquiry.** A user, with a club: returns the existing inquiry chat for (caller, club) or creates it (`type = inquiry`, `club` set, the caller as member). The club owner and staff of that club cannot open an inquiry with their own club.

**CHAT-7.** **Club opens an inquiry with a user.** The club side may open (get or create) the inquiry chat of a user who has a non-cancelled session at the club, a membership of the club, or an offer targeted at them (CLUB-24). Anyone else: `400 cannot_chat`. The chat's member is still the user, not the club side.

**CHAT-8.** In an inquiry chat, the member and the **club side** of its club (checked at the time, ACC-1) may read and send. Club side people are not stored as members.

## Messages

**CHAT-10.** **Send.** `body`: trimmed, 1–4000 characters. Creates a `messages` row with `sender` = caller. After commit, push to the other side (NOTE-20).

**CHAT-11.** **Read markers.**
- A member's marker: `chat_members.last_read_at`.
- The club side's marker on an inquiry chat: `chats.club_last_read_at`, **shared** by the owner and all staff: when any of them reads, it is read for all of them (a shared inbox).

**CHAT-12.** **Mark read.** Sets the caller's marker (member or club side) to now. Repeat: no change beyond the time (GEN-5).

**CHAT-13.** **Unread count** for a viewer: messages in the chat with `created_at` after the viewer's marker (all messages if the marker is empty), not sent by the viewer. For the club side the messages counted are those not sent by any club-side person, i.e. sent by the inquiring user or by the system.

**CHAT-14.** **Polling.** `GET` messages with `after=<message id>` (default 0) returns messages with a larger id, oldest first, at most `limit` (default 50, max 200). For scrolling back, `before=<message id>` returns older messages, newest first, same limit. Not page-number paginated.

**CHAT-15.** **Chat list** for a user: every chat where they are a member, plus, if they are on a club side, every inquiry chat of that club. Each with: type, title (the other person's name, the group's name, or the club's name / the inquirer's name for the club side), last message, unread count (CHAT-13). Sorted by last message time, newest first; paginated.

**CHAT-16.** Messages cannot be edited or deleted in this version.

**CHAT-17.** Messages are text only; there are no attachments (settled at the owner's review on 2026-11-16).

**CHAT-18.** *Decided during build (2026-11-16):* CHAT-7's "non-cancelled session at the club" means the user is the booker or has a participant row in it; "membership" means a current one (ACC-1, ACC-2); "an offer targeted at them" means any offer of the club with `user` = them, expired or not. The club side may not open an inquiry with a shadow player, an inactive user, or someone on that club's own side (`400 cannot_chat`). A user who is both the inquirer and on the club side reads as the member. In an inquiry, a message from the member pushes the owner and current staff; a message from the club side pushes the member. Polling with both `after` and `before`, or a `limit` outside 1 to 200, is `400`.

## Session cards

**CHAT-30.** `post_session_card(session)`: called from bookings when a group session becomes `confirmed` (BOOK-60), in the same transaction. Creates a message in the group's chat with `sender` empty, `body` empty and `session` set. If a card for that session already exists in that chat, nothing is created. If the group has no chat (it was deleted), nothing is created.

**CHAT-31.** A card shows the session's current start and end time and links to the session; it stores no times of its own.

## Edge cases

- **Member leaves a group:** their `chat_members` row goes (TEAM-28); they can no longer read the group chat.
- **Staff membership expires:** they lose the club's inquiry chats at once (ACC-2).
- **A blocked pair with an existing direct chat:** both can still read history; neither can send (CHAT-3).

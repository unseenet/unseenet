```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0037                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0023

                          Matrix Gateways
```

# Abstract

This document is the network profile (UN-RFC 0023 section 9) for
**Matrix**, limited to public, unencrypted rooms. It says how a room
maps to `matrix.*`, how messages, replies, threads, edits and
redactions convert in both directions, how the room's moderators give
and withdraw their consent by inviting and removing the gateway, and
which Matrix features a gateway must never use because they would reveal
when an Unseenet author is active. It also covers portals: rooms a
gateway creates on its own homeserver for Unseenet groups. Everything not said here follows
UN-RFC 0023.

# 1. Overview

Matrix is a federated chat network. A **room** is replicated to every
homeserver one of its members is on; each server keeps the room's
history and enforces its rules. Rooms are named by an id
(`!opaque:server`) and usually by one or more aliases
(`#python:matrix.org`). Who may do what is set by **power levels** in the
room's state: moderators can invite, kick, ban and redact. Events are
signed by the homeserver that sent them, not by their author.

For a gateway, Matrix differs from Usenet (UN-RFC 0024) and Nostr
(UN-RFC 0026) in four ways:

- it is chat, so imported messages are chat lines (UN-RFC 0028), and a
  gatewayed group is a chat group;
- messages can be edited and redacted after the fact, and a redaction
  removes the content on every server that has the room;
- clients send presence, typing notifications and read receipts by
  default, all of which tell others when a person is active
  (section 8);
- a room's moderators can invite and remove accounts, which gives the
  consent UN-RFC 0023 section 6.1 asks for a direct form (section 6).

End-to-end encrypted rooms are out of scope: a gateway would have to
decrypt them, and the encryption would end at the gateway (UN-RFC 0023
section 4.1 item 6).

# 2. Manifest Fields

For Matrix, the `gateway` field of UN-RFC 0023 section 3.2 means:

| Field     | Value                                                                |
|-----------|----------------------------------------------------------------------|
| `network` | `matrix`                                                             |
| `source`  | The room as the gateway is configured with it: an alias (`#python:matrix.org`) or, for a room without one, its id (`!abc:example.org`) |
| `host`    | The gateway's Matrix user id, e.g. `@unseenet-gateway:example.org`   |
| `abuse`   | A contact reachable from Matrix: a user id, a room alias, or a URL   |

# 3. Names

A room with an alias `#<local>:<server>` is gatewayed as

    matrix.<server>.<local>

where each of `<server>` and `<local>` is lower-cased and every run of
characters not allowed in a group name component (UN-RFC 0004
section 1), dots and the port separator included, is replaced by one
`-`. So `#python:matrix.org` becomes `matrix.matrix-org.python`, and
`#Dk.Snak:example.org:8448` becomes `matrix.example-org-8448.dk-snak`.
The server comes first so that rooms with the same alias on different
servers never share a name.

A room known only by its id, or whose alias does not give a valid name,
is gatewayed under a name chosen by the gateway operator and endorsed by
the maintainer of `matrix` (UN-RFC 0023 section 3.3), or not at all.

An alias can later be moved to another room. A gateway MUST record which
room an alias named when it first imported from it, and MUST stop
importing from and exporting to that source if the alias comes to name
another room. The operator then decides whether the new room is
gatewayed, under a new name.

# 4. Import

## 4.1 What Is Imported

A gateway imports from a room only while all of the following hold,
checked before every pass:

1. the gateway's account is a member of the room, having joined on an
   invitation from the room (section 6);
2. the room's join rule (`m.room.join_rules`) is `public`;
3. the room has no `m.room.encryption` state.

It imports `m.room.message` events whose `msgtype` is `m.text`,
`m.notice` or `m.emote`, and edits of them (section 4.4). In addition
to UN-RFC 0023 section 4.1, a gateway MUST NOT import:

1. `m.room.encrypted` events, and events of any other type: state
   events, reactions (`m.reaction`), stickers (`m.sticker`), calls and
   polls;
2. messages with any other `msgtype`, including `m.image`, `m.file`,
   `m.audio`, `m.video` and `m.location`. Their media is never fetched
   and no link to it is made;
3. events sent by the gateway's own account, and events whose content,
   or whose `m.new_content`, has the key `org.unseenet.message_id`
   (section 5.2): they came from Unseenet;
4. redacted events (an empty `content`);
5. events sent while the gateway was not a member of the room. After
   being removed and invited again, a gateway imports only what is sent
   from the new invitation on.

## 4.2 Conversion

Every imported message is a chat line (UN-RFC 0028): `Message-Kind:
chat` and an empty `Subject`. The gatewayed group's manifest has
`"view": "chat"` and `"kinds": ["chat"]`.

| Unseenet header  | Value                                                            |
|------------------|------------------------------------------------------------------|
| `Subject`        | Empty                                                            |
| `Message-Kind`   | `chat`                                                           |
| `From`           | The sender's `displayname` in the room (`m.room.member`), otherwise the localpart of their user id |
| `References`     | Section 4.4                                                      |
| `Origin-Network` | `matrix`                                                         |
| `Origin-ID`      | The event id                                                     |
| `Origin-Date`    | `origin_server_ts` as an RFC 5322 date in UTC                    |
| `Origin-From`    | The sender's user id, e.g. `@alice:example.org`                  |
| `Matrix-Room`    | The room id                                                      |
| `Matrix-Msgtype` | `m.notice` or `m.emote`; left out for `m.text`                   |
| `Matrix-Edit`    | Section 4.4                                                      |

The body is the event's plain `body`; `formatted_body` is not used. An
`m.emote` body is prefixed with `* ` and the `From` name, as Matrix
clients show it. Where a message is a reply, the quoted fallback that
older clients put at the start of the body (lines starting with `>`
whose first line starts with `> <`, followed by a blank line) is
removed.

There is no `Origin-Proof`. Matrix events are signed by homeservers,
not by their authors, and clients do not see those signatures; a proof
would show only that some server sent the event.

## 4.3 Replies and Threads

| The event…                                             | Root                | Parent                      |
|--------------------------------------------------------|---------------------|-----------------------------|
| has `m.relates_to.rel_type` `m.thread`                 | its `event_id`      | `m.in_reply_to`, unless `is_falling_back` is true |
| has `m.relates_to.m.in_reply_to` and is not in a thread | (none)              | `m.in_reply_to`             |

In a thread, a reply marked `is_falling_back` points at the thread's
latest message only for clients without thread support, and is not a
parent. `References` holds the mapped Unseenet Message-IDs of the root
and then the parent, where they are known (UN-RFC 0023 section 4.4).

## 4.4 Edits

An edit (`m.relates_to.rel_type` `m.replace`) is imported as a new chat
line whose body is `m.new_content.body`, with `References` set to the
mapped Message-ID of the edited message and `Matrix-Edit` set to its
event id (UN-RFC 0023 section 4.5). An edit of a message that was not
imported is not imported either. The edited article itself is left as
it was: Unseenet articles are signed and do not change.

## 4.5 Redactions

A redaction (`m.room.redaction`) of an imported event is imported as a
cancel of the imported article. The room's homeserver accepted the
redaction, so it came from the event's sender or from someone with the
power to redact: the room's own authority, which is all UN-RFC 0023
section 4.5 asks for. The cancel's text says which of the two it was.

# 5. Export

## 5.1 The Gateway's Account

The gateway writes with one ordinary Matrix account, on a homeserver
whose operator allows bots, and only in rooms it has joined on
invitation (section 6). It never joins a room on its own, even a public
one.

An Application Service that makes one virtual user per Unseenet key
(`@unseenet_<fingerprint>:<server>`, with the `From` name as its display
name) would show authors apart in Matrix clients. It needs a homeserver
the gateway operator runs, and is left to a later revision of this
profile.

## 5.2 Conversion

An exported article becomes one `m.room.message` event with `msgtype`
`m.text`, sent with a transaction id derived from the article's
Message-ID, so a retry never sends it twice. Its content is:

| Key                       | Value                                                          |
|---------------------------|----------------------------------------------------------------|
| `body`                    | `<From> (<first 4 characters of the fingerprint>) on Unseenet:`, a line break, then the article's body |
| `org.unseenet.message_id` | The article's Message-ID                                       |
| `m.relates_to`            | Where the article answers an event imported from or exported to the room: `m.in_reply_to` that event; if that event is in a thread, also `rel_type` `m.thread` with the thread's root and `is_falling_back` false |

The author line comes first, as Matrix bridges commonly do, because the
message appears under the gateway's own name. Importing gateways skip
events carrying `org.unseenet.message_id` (section 4.1), so nothing comes
back. A Matrix client ignores the unknown key.

The homeserver has accepted the event (UN-RFC 0023 section 5.2 step 4)
when it answers with an `event_id`.

# 6. The Other Side

For Matrix the other side (UN-RFC 0023 section 6.1) is the room's
moderators: those whose power level lets them invite.

- **Consent is an invitation.** The gateway joins a room only when it
  has been invited to it and the room is in its configuration. Before
  accepting, it checks the room's invite state; if the room is not
  public or is encrypted, it declines the invitation with a reason
  saying why, so the moderators see that the room will not be carried.
- **Saying so in the room.** On joining, the gateway sends one
  `m.notice` saying which Unseenet group the room is gatewayed to, that
  copies arrive seconds to minutes late in both directions on purpose,
  that images and files are not carried, how to reach the operator, and
  that kicking the gateway stops it.
- **Withdrawal is a kick or a ban.** A gateway that is no longer a
  member stops importing and exporting at once. If it is invited again,
  section 4.1 item 5 applies.
- **Changes.** If a gatewayed room becomes private or encrypted, the
  gateway stops (section 4.1) and stays in the room until removed.

Reading a public room does not need an account, but this profile
requires membership all the same: it is the only form of consent a room
can give, and a gateway that reads without being invited is the kind
large homeservers ban.

# 7. Portals

A portal to Matrix (UN-RFC 0023 section 3.5) is a room the gateway
creates for an Unseenet group whose owner has opened one. Its `source`
in the manifest's `portals` entry is the room's alias, which MUST be on
the gateway's own homeserver, e.g. `#unseenet:unseenet.org`.

The gateway creates the room with its own account:

- public (join rule `public`), listed in the server's room directory, and
  never encrypted;
- named after the Unseenet group followed by `(Unseenet)`, with a topic
  saying that it is a portal to the named group (with its Group ID), that
  messages are copied both ways and arrive late on purpose, and that
  images and files are not carried. Both are kept up to date with the
  group's manifest;
- with the people the gateway operator names as the room's admins
  invited and given the same power as the gateway, so that the room can
  be moderated by people.

The owner's opening of the portal is the consent for both directions, so
the gateway joins and writes in its own room without an invitation and
posts no notice (section 6). Unseenet articles become messages as in
section 5.2; a new thread (an article that refers to nothing and whose
subject does not start with `Re:`) has its subject after the author line.
Messages written in the room are imported into the Unseenet group as in
section 4, as chat lines. A group that takes no chat lines (UN-RFC 0028
section 4.1) cannot have a Matrix portal.

If the room is later made private or encrypted by one of its admins, the
gateway stops exporting and importing (section 4.1) until it is public
and unencrypted again.

# 8. Timing Signals

Matrix clients send presence (`online`, `unavailable`, last active),
typing notifications, read receipts and read markers by default. Each
says when someone is active, which is what UN-RFC 0023 section 5.3
forbids a gateway to reveal about Unseenet authors. A gateway:

1. MUST NOT send typing notifications, read receipts (public or
   private) or read markers;
2. MUST NOT set presence, and MUST sync with `set_presence=offline` so
   syncing does not mark it online. The homeserver still sees the
   account's own activity when it sends; that activity follows the
   random delay of UN-RFC 0023 section 5.2, so it adds nothing. A gateway
   SHOULD use a homeserver with presence disabled where it can;
3. MUST NOT send reactions or any other event on behalf of Unseenet
   authors apart from the exported message itself.

`origin_server_ts` of an exported event is the time of sending, after
the random delay, not the article's `Date`.

# 9. Headers Defined Here

| Header           | In       | Defined in  |
|------------------|----------|-------------|
| `Matrix-Room`    | Unseenet | section 4.2 |
| `Matrix-Msgtype` | Unseenet | section 4.2 |
| `Matrix-Edit`    | Unseenet | section 4.4 |

# 10. Rationale

- **Why a bot account and not an Application Service from the start?**
  A bot needs no homeserver of the operator's own and gets a gateway
  running with a handful of API calls. An Application Service is better
  for readers and can come later without changing what is imported.
- **Why the server in the name?** Aliases are only unique on their
  server; `#python` on two servers is two rooms.
- **Why pin an alias to its room?** Whoever controls an alias can point
  it at a room of their choice; without pinning, they could make the
  gateway carry a different room under the same Unseenet group.
- **Why drop what was written while the gateway was out?** A kick
  withdraws consent; messages written in that time were written to a
  room without a gateway.
- **Why no proof?** Section 4.2: Matrix does not sign events per author,
  so there is nothing for a reader to check against.
- **Why chat lines?** Matrix messages have no subjects, and UN-RFC 0028
  says senders must not make one up.

# 11. Security Considerations

UN-RFC 0023 section 13 applies. In addition:

- The gateway sees the room through its own homeserver. A malicious
  homeserver in the room can forge events from its own users, as it can
  for every other member; the gateway is no worse off than any of them.
- The account's access token lets anyone holding it write in every room
  the gateway has joined. It is stored readable only by the gateway's
  user, SHOULD be on an encrypted disk with the gateway key, and SHOULD
  be revoked (logging the device out) if the gateway host is
  compromised.
- The gateway's Matrix account is a public presence. It MUST NOT be on
  the same host, address or homeserver account as anything that would
  link it to hidden nodes (UN-RFC 0023 section 6.3).
- A room can make the gateway post many articles. The gateway pays the
  postage; its own rate of passes and `max_pages` limit how much one
  pass imports.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.

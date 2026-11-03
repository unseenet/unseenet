```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0065                                             November 2026
Category: Standards Track
Status: Draft
Implemented: unseenet main (unreleased); partly - the building block (sections 3 to 6), not yet a server that uses it
Updates: 0047

                    Unseenet: Operator Channels
```

# Abstract

Every Unseenet server - a node, a council replica, a gateway, an
entrance, a spam-report issuer, a bot - sometimes needs a person: a
disk filling up, a change held for its operator, a hearing about to
close. This document gives each server an **operator channel**: a team
inbox (UN-RFC 0047) in which the server posts **notices** and reads
**commands** from its operators, and answers there. Operators use their
ordinary client, a phone through a web entrance included; no SSH, no
program of its own. Anything that changes something needs a
**confirmation code**, so a typo never acts. Who may give commands is
the list of readers, which only the operator's offline key can change.
Neither the channel nor a reply shows who runs the server.

A small format for **offers** (buttons) lets clients show a server's
commands as buttons; clients that do not know it show the text, which
always works by typing.

# 1. Motivation

Servers are run by people who are not always at them. Today an operator
looks at a node's log over SSH, a replica's held changes with
`unseenet-replica status`, and the Matrix gateway's invitations in an
inbox of its own (with a format of its own). A council member who must
second a proposal before a hearing closes should not need a terminal on
the replica's machine; a node at a relative's home should be able to
say that its disk is full.

Three things are wanted:

1. **Notices** from the server, readable on any device.
2. **Commands** to the server, from the same place, safe against typos
   and against people who are not its operators.
3. **No link to people.** Who runs a hidden server, a replica in
   particular, must not follow from the channel.

Team inboxes (UN-RFC 0047) already give a mailbox that several keys
read, owned by a key that can stay offline, whose readers are keys made
for it and nothing else. This document adds only what a server and its
operators' clients must agree on.

# 2. Terms

Server
: A program that runs unattended with a key of its own: a node, a
  replica, a gateway, an entrance, an issuer, a bot.

Operator
: A person who looks after a server.

Operator channel, operator box
: A team inbox (UN-RFC 0047) whose readers are the channel keys of one
  or more servers and the operators' team keys.

Channel key
: The team key the server reads and posts with in its channel. Made by
  the server, used for nothing else.

Notice
: A message from the server to its operators.

Command
: A message from an operator to the server that asks it to do or tell
  something.

# 3. The Channel

## 3.1 Setting Up

1. The server makes its channel key (section 2) and shows its public
   key, for example `unseenet-replica channel key`. The seed stays on
   the server, in its vault or state directory, mode 600.
2. The operator, with the key that is to own the channel (SHOULD be a
   key that stays offline, such as the operator key of UN-RFC 0011),
   creates a team inbox and lists as `readers` the channel key and a
   team key for each operator (UN-RFC 0047 section 6), and lists the
   channel keys also in `operator_servers` (section 3.2). It SHOULD set
   `team_name` to a name for the box, such as "My servers", and
   `retention_days` to 30 or less.
3. The operator gives the server the box's Group ID (`operator_group`
   in its configuration) and, in a box several servers read, a name
   for it (section 3.2). The server reads the manifest and starts only
   when its channel key is among the `readers`; until then it says so
   on its console and in its status.

Unlike UN-RFC 0047 section 6, the owner never knows the channel key's
seed: the server makes it and only its public key leaves the machine.

The manifest MAY have `"operator_channel": true`. Clients then show the
inbox as a server's channel (section 7) from the start; without it they
learn it from the first notice.

## 3.2 One Box for Several Servers

An operator with several servers SHOULD keep them in **one box**: one
place to read, one invitation per operator, one owner key. Each server
reads it with a channel key of its own.

- The manifest lists the servers' channel keys in `operator_servers`
  (each also in `readers`), so servers and clients tell servers from
  operators without waiting for a notice. Removing a reader removes it
  from `operator_servers` too.
- Each server has a **name** in the box (at most 32 characters,
  letters, digits, `-`), unique in it, and adds it as a `Server-Name`
  inner header to everything it posts.
- A command is **for a server** when it answers one of that server's
  messages (its last `References` entry is that server's), or when its
  first line starts with the server's name and a colon (section 5.1).
  A client offers the box's servers by name - from `operator_servers`
  and their notices - as whom a new message is for, as it offers
  contacts, so nobody has to remember the names.
- A command for no server in particular is answered by every server
  when it is `help`, `status` or `notices`, and by the server waiting
  for it when it is `yes <code>` (section 5.2); anything else is left
  alone.
- A server alone in its box takes every command, with or without its
  name.

A box shared by several servers **links** them and **exposes them
together**: whoever sees its manifest or traffic sees one inbox serving
all of them, and whoever seizes one server reads what the others were
told and learns who runs them all. That is nothing for servers already
known to be run by the same operator (UN-RFC 0011, a project's own
servers). A server that has to stay apart - a hidden replica of an
anonymous operator, a server with other operators - SHOULD have a box
of its own. Tools that set up a box MUST say what sharing it links.

## 3.3 Who May Give Commands

A server takes a command only when:

- it is in the server's channel;
- its inner headers have `Sender-Team` naming the channel and a
  `Sender-Key` that is in the channel's current `readers` (UN-RFC 0047
  section 8), checked against the manifest as the server reads it now;
- `Sender-Key` is not the server's own channel key, nor another
  server's (`operator_servers`, or a key it has seen post notices);
- its `Sender-Signature` verifies.

Anything else in the channel is ignored, with a line in the server's
log. The readers are the only list of who may steer a server, and only
the owner key changes it: removing a reader (UN-RFC 0047 section 9)
removes their say at once.

## 3.4 Several Operators

Each operator is a reader of the channel with a team key of their own
(UN-RFC 0047 section 6): up to 15 operators, the sixteenth reader
being the server. All of them see every notice and every answer
(section 5.4); a confirmation is accepted only from the operator who
gave the command (section 5.2). Different servers may have different
operators, and an operator removed from one channel keeps their place
in the others.

The owner is trusted by everyone in the channel (UN-RFC 0047 section
11). A team that runs a server together SHOULD let the owner key be
held by whoever the team trusts with that, not by the server.

Where servers have boxes of their own, adding or removing an operator
means one manifest per box. The owner's tools SHOULD do this for
several boxes in one go - one team key, one manifest and one invitation
per box, with the owner key at hand once - for example:

```
unseenet operator add <person> --channels all
unseenet operator remove <team key> --channels all
```

# 4. Notices

A notice is a message in the channel, sealed as UN-RFC 0047 section 4
says, from the channel key, with these inner headers besides those of
UN-RFC 0047 section 8:

| Header            | Value                                                      |
|-------------------|------------------------------------------------------------|
| `Operator-Notice` | A kind: one word, `[a-z0-9-]`, at most 32 characters, e.g. `disk-low`, `held`, `hearing-closing` |
| `Notice-Level`    | `info`, `warn` or `alarm`                                  |
| `Notice-Key`      | Optional. A short key for the matter, so a later notice can say it is over (`Notice-Over: yes`) |
| `Offer-<n>`       | Optional, `<n>` from 1 to 6: buttons (section 6)           |

The body is text for people, in the server's configured language, and
MUST say in words what can be done, with each command written out, so
that it is usable without the offers.

A server:

- SHOULD send a notice once per matter, not every round: a disk that
  stays full is one `warn` and, when it is over, one notice with
  `Notice-Over: yes`;
- SHOULD gather `info` notices into a digest at most once an hour, and
  MAY delay `warn` notices by a random time of up to ten minutes
  (section 9);
- sends `alarm` notices at once: a twin alarm (UN-RFC 0054), a disputed
  council, a node that refuses all posts.

# 5. Commands

## 5.1 Form

A command is a reply in the channel (UN-RFC 0009 section 2.5, UN-RFC
0047 section 8), of kind `chat` or `post` (UN-RFC 0028). Its first line
is the command: a verb, then arguments, separated by spaces, matched
without regard to case. A new message for one server in a box several
servers read starts with the server's name and a colon, e.g.
`replica2: second ABCD`; an answer to a server's message needs no name
(section 3.2).

Every server understands:

| Command   | Answer                                                        |
|-----------|---------------------------------------------------------------|
| `help`    | Its commands, each with a line saying what it does            |
| `status`  | What it would show in its status: up since, version, warnings |
| `notices` | The matters still open (section 4, `Notice-Key`)              |

The rest are the server's own (section 8).

## 5.2 Confirmation

A command that changes anything - a vote, a post on a council's behalf,
dropping a group, publishing - is not carried out when it comes. The
server answers with what it would do, in words, and a **confirmation
code**:

> Second proposal ABCD (the council keeps the gateway directory)?
> Answer *yes 4821* within 30 minutes.

with the inner headers `Confirm-Code: 4821` and `Confirm-For:` the
Message-ID of the command. The code:

- is 4 random digits, new for each command;
- is valid for 30 minutes, for one answer, and only from the reader
  who gave the command (the same `Sender-Key`);
- is answered by `yes <code>`; anything else from that reader, a wrong
  code included, cancels the command, and the server says so.

A typo therefore never acts: a wrong command gets "unknown command",
and a right command needs a second message with a code that only its
answer showed.

## 5.3 Once Only

Messages stay in the inbox until they expire, and a server restarts.
A server:

- MUST carry out each command at most once, keeping the Message-IDs it
  has handled, at least for the channel's `retention_days`;
- MUST NOT carry out a command dated more than an hour before it
  first saw it, nor a confirmation after its code expired; it answers
  that the command came too late, and the operator sends it again.

Carrying out each command once is what keeps an old message from
acting twice; the hour only keeps a server that was down for a day
from acting on what its operators have since forgotten. Articles take
up to a minute at each node before they are forwarded (UN-RFC 0005
section 5.5), and a command with its confirmation travels there and
back twice, so the limits leave room for a slow network and an
operator who is interrupted.

## 5.4 Answers

The server answers every command it takes, as a reply to it, with the
inner header `Command-Result`:

| Value     | Meaning                                                       |
|-----------|---------------------------------------------------------------|
| `asked`   | A confirmation code was sent (section 5.2)                     |
| `done`    | Carried out; the body says what happened                       |
| `refused` | Not carried out: unknown, not allowed here (section 5.5), too late, cancelled |
| `failed`  | Tried, and it did not work; the body says why                  |

Every reader sees every answer, so the channel is also a shared record
of what was done and by whom (which team key). This answers part of
UN-RFC 0047 section 12: two operators see that the other has acted.

The server also keeps a local log of every command: when, which
reader, what, the result.

## 5.5 What Chat May Not Do

A server keeps a list of commands it takes only from its own command
line, never from the channel: anything that cannot be undone or that
touches keys - for a replica `resign` and signing a genesis, for any
server showing or replacing a key. A command on that list gets
`refused` with "only on the server itself". The list is part of the
server's documentation and of its `help`.

The server's setting `operator_channel`:

- `off`: no channel;
- `notices` (the default): notices, and only `help`, `status` and
  `notices`;
- `commands`: all of section 5.

Letting chat act is a choice, so it is not made by default. The tool
that sets up a channel (section 3.1) SHOULD ask once whether the
operators may also give commands, and say that anything that changes
something still needs a confirmation code.

# 6. Offers

A message MAY carry up to six offers, in the inner headers `Offer-1` to
`Offer-6`, numbered as UN-RFC 0027 numbers `Attachment-<n>` so that
each is a header of its own. Each is a button, shown in the order of
its number:

```
Offer-<n>: <reply> | <label>
```

`<reply>` is the exact text the button sends; `<label>` (optional) is
what the button says, at most 40 characters; without it the reply is
the label. For example:

```
Offer-1: yes 4821 | Second it
Offer-2: no | Cancel
```

A client that shows offers:

- shows them as buttons under the message, and on a press sends
  `<reply>` as an ordinary reply in the same conversation, signed by the
  user like anything they type. A button sends nothing else, opens
  nothing, and runs nothing;
- shows them only on the newest message of a conversation, or greys
  out the older ones;
- MAY ask before sending, and SHOULD for a reply that starts with
  `yes`.

A client that does not show offers shows the text, which section 4
requires to name every command. Offers are not only for operator
channels: any message in a private chat (UN-RFC 0028) MAY carry them,
for example from the help bot or a game bot.

# 7. Clients

A client that reads team inboxes which are operator channels (section
3.1, or because they have notices):

- shows them **together**, as the user's servers - labelled with
  `team_name`, each message with its `Server-Name`, open matters and
  the newest `alarm` first - beside the user's own inbox and other
  team inboxes, never mixed in;
- lets the user write a new message to one server of a box by picking
  it from the box's servers, as a contact, and adds its name (section
  3.2); an answer goes to the server whose message it answers;
- shows notices by level - `alarm` marked so it is not missed, `info`
  quietly - and an open matter until a notice says it is over;
- shows answers with their `Command-Result`, and a confirmation's
  code and the time left;
- MUST NOT show a reader's team key as a person (UN-RFC 0047 section
  8); it MAY let the user give each team key a local nickname, so an
  operator team can tell its members apart.

Clients SHOULD offer to notify the user of `alarm` notices as they do
of private messages (UN-RFC 0032).

# 8. Servers (Informative)

What each kind of server is expected to say and take. The commands
are each server's own and documented with it; this list only keeps
them alike.

- **Replica** (UN-RFC 0054, 0061): notices for changes held for the
  operator, hearings opened and closing, objections to candidates,
  "you stop being active in 14 days", twin alarm, disputed council,
  failed rounds; commands `agree`, `hold`, `propose`, `second <id>`,
  `object <id> <reason>`, `talk: <text>`, `reply <id>: <text>`, all
  confirmed, and posted at once rather than at the next round. `resign`
  and `sign` only on the server (section 5.5). A post made on a
  command counts as a person writing, for the activity rule of UN-RFC
  0054.
- **Node:** Tor down, little disk, peer errors, refused posts, new
  messages in the contact inbox (UN-RFC 0011); commands `drop-group
  <id>` and `refuse-blob <id>`, confirmed. Settings stay in
  `node.toml`.
- **Gateway:** invitations and links waiting for approval
  (unseenet/unseenet-gateway#10), with `approve` and `decline`
  confirmed.
- **Issuer** (UN-RFC 0045): findings waiting in dry run; `publish` and
  `dry-run`, confirmed.
- **Entrance, bots, help bot:** errors, load, failing sources,
  questions the help bot could not answer.

# 9. Security and Privacy Considerations

- **Who runs the server.** The channel's manifest shows its owner key
  and its readers' team keys. Team keys are new and used for nothing
  else (UN-RFC 0047 section 11), and the server need not be named
  anywhere. A hidden server's operator SHOULD own the channel with a
  key that is not otherwise linked to that server; for a node whose
  operator is public (UN-RFC 0011) it may be the same key.
- **Timing.** A server's notices are posted when something happens to
  it. An observer who can tell when a hidden server is up, or when a
  disk filled, may link the server to its channel; and the channel's
  articles reach every node that carries it. Gathering `info` into
  digests and delaying `warn` (section 4) weaken the link; `alarm` is
  sent at once because it matters more. Operators who need more SHOULD
  keep `operator_channel = off`.
- **A stolen team key** lets its holder read the channel and give
  commands, but not those of section 5.5, and every command is
  answered where all readers see it. The owner removes the key
  (UN-RFC 0047 section 9).
- **A seized server** gives its channel key: whoever has it can read
  what was sent to the channel while it was a reader, and post notices;
  in a box several servers read, what was sent to every server in it
  (section 3.2).
  Short `retention_days` limit what is still there. The owner removes
  the channel key and makes the server a new one.
- **The owner is trusted**, as in UN-RFC 0047: it can add a key of its
  own and give commands.
- **No remote content.** Offers carry text only, and a press sends a
  reply the user could have typed (section 6).
- **Confirmation is not authentication.** The code guards against
  mistakes, not against a reader: any reader may give any command
  outside section 5.5.

# 10. Rationale

- **One box for an operator's servers, a box of its own where that
  matters.** Many boxes are hard to keep an eye on, and most servers
  of one operator are known to be theirs anyway. Where they must not
  be linked - a hidden server, other operators - a box of its own
  keeps one seized server from reading the others' notices (section
  3.2).
- **A team inbox, not a group.** The channel must be readable only by
  operators and must not show who they are. UN-RFC 0047 gives exactly
  that, with an owner that can stay offline.
- **The server makes its own key**, so no secret of the server's ever
  passes through the owner's client or an inbox.
- **Typed commands first, buttons second.** Every client and every
  phone can type; offers make it nicer where clients support them, and
  cost a client nothing where they do not.
- **Codes, not a second factor.** The danger in chat is a slip of the
  thumb, not an intruder; an intruder with a team key is handled by
  the owner removing it.
- **Some things never from chat.** Resigning from a council or
  replacing a key cannot be undone; doing them on the machine itself
  keeps them deliberate.

# 11. Changes to Other Documents

- UN-RFC 0047 section 3: an inbox manifest MAY have
  `"operator_channel": true` (section 3.1) and `operator_servers`, a
  list of its readers (section 3.2).
- UN-RFC 0047 section 12, shared state: answers in an operator channel
  are seen by every reader (section 5.4).
- UN-RFC 0028: a message in a private chat MAY carry `Offer-<n>` inner
  headers (section 6).

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.

```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0046                                              October 2026
Category: Standards Track
Status: Draft
Updates: none

                Unseenet: The Local Client API
```

# Abstract

A client keeps its vault, its keys, Tor and postage in one program. A
front end - a graphical window, a page in a browser on the same machine,
an Android app around the same core, a screen-reader client, a script -
should not have to implement any of that again, and should never hold a
key. This document defines a small HTTP and WebSocket API that such a
program offers to its own front end on the same computer: unlock, the
groups and their posts, writing, people, the groups you run, your names
and profile, and an event stream; and the same for a bot or gateway that
runs without a person. It also defines how the API keeps everything else
on the machine out.

# 1. Motivation

unseenet-gui was built this way from the start: its page never sees a
key, and everything security-relevant happens in Python (UN-RFC 0007,
0003, 0006). Other front ends need the same, and the reference
implementation now lives in the core (`unseenet.client.localapi`), behind
`Session` and `ClientRuntime`. Writing the API down lets anyone build a
front end against it, in any language, without reading the GUI's code.

The API is local by design. It is not a way to reach a client from
another computer; that is what nodes and web entrances (UN-RFC 0043) are
for.

# 2. Terms

Runtime
: The program that holds the unlocked vault and talks to the network:
  in the reference implementation, `Session` with `ClientRuntime`.

Front end
: The program a person uses, talking to the runtime through this API.

Job
: Something the runtime does on the front end's behalf that takes time,
  such as sending a post (postage, and for a new key ripening, UN-RFC 0025).

# 3. Security

A runtime offering this API:

- MUST listen on `127.0.0.1` (or `::1`) only, on a port chosen at random
  when it starts.
- MUST make a new random **token** of at least 32 octets each time it
  starts, and refuse every request without it (`401`). The token is
  given in the header `X-Unseenet-Token`, or, for the WebSocket, as a
  subprotocol `unseenet-token.<token>` next to `unseenet`, since a browser
  cannot set headers on a WebSocket. It MUST be compared in constant time.
- MUST refuse (`403`) a request whose `Host` is not its own address and
  port (`127.0.0.1:<port>` or `localhost:<port>`); this stops DNS
  rebinding, where a web page on the Internet makes a browser talk to a
  local port under another name.
- MUST refuse (`403`) a request with an `Origin` other than its own, and
  MUST NOT send any CORS header: no other page may read its answers.
- SHOULD serve any page it offers with a strict Content-Security-Policy
  (`default-src 'none'` with only `'self'` for scripts, styles and
  connections), so that a post can never load anything from outside.
- MUST NOT send a private key, a group key or the passphrase to the front
  end, in any answer or event. The passphrase goes in only, with unlock.

The token is what keeps other local users and programs out; the `Host`
and `Origin` checks are what keep web pages out. Both are needed.

## 3.1 Handing the Address to the Front End

Whatever starts the runtime gives the address and the token to its front
end out of band, in one of two ways (the reference implementation,
`unseenet serve`, does both for a vault and the first for a service):

- on standard output, as one line:
  `UNSEENET-API 1 http://127.0.0.1:<port>/ <token>`; or
- in a file only the user can read (mode `0600`; on Windows, in a folder
  only the user can read, as the vault is), next to the vault, named
  `<vault file>.api`, holding that same line, removed when the runtime
  stops.

A front end opened as a page by the runtime itself MAY get the token in
the URL fragment (`#t=<token>`), which browsers do not send to servers.

## 3.2 Service Mode

A program that runs unattended - a bot, a gateway, a helper behind a
node - uses the same API with its own runtime (`unseenet serve`). It has
no vault to unlock and no person to set up: it starts with a key file

```
unseenet serve --key-file <file> [--node <address>] [--state <file>]
```

and is unlocked from the start (`setup` false, `unlocked` true, section
4.1). Its state file keeps its ripening chain (UN-RFC 0025) and what it
has read, so a restart neither ripens again nor answers twice.
`POST /api/unlock` and `/api/setup` answer `400` in service mode.

Everything else is the same, and section 4.9 adds what only a program
needs. The security rules of section 3 apply unchanged: a service's front
end is the program on the same machine that drives it.

# 4. Requests and Answers

All bodies are JSON (`application/json; charset=utf-8`). A group ID in a
path is percent-encoded. Errors are `{"error": "<text for people>"}` with:

| Status | Meaning                                                     |
|--------|-------------------------------------------------------------|
| 400    | The request is wrong (a missing field, nothing to send)     |
| 401    | No or a wrong token                                         |
| 403    | Wrong `Host` or `Origin`                                    |
| 404    | No such group                                               |
| 409    | Locked: unlock first (or set up, section 4.2)               |
| 502    | The node or Tor could not be reached                        |

Messages and groups have the core's dict form, version 1
(`Message.to_dict()`, `GroupInfo.to_dict()`, field `v`). A front end MUST
check `v` and refuse a version it does not know rather than draw wrong.

## 4.1 State

`GET /api/state`, also while locked:

```
{"api": 1, "unlocked": false, "setup": false, "connected": false,
 "status": "Locked", "identity": null, "node": null, "inbox_ready": false,
 "ripening": null}
```

Unlocked: `identity` is `{"key": "ed25519:...", "display": "..."}`,
`node` the default node, and `ripening` `{"level": <0-4 or null>, "t":
<iterations>, "next_at": <iterations or null>, "published": <the level
nodes know, or null>, "available": <true if this runtime can ripen>,
"paused": <true while paused>}` (UN-RFC 0025). `setup` is true while the
identity or the node is still missing.

`POST /api/ripening` `{"paused": true | false}` pauses or resumes ripening
in the background (UN-RFC 0025 section 7), for example on a warm phone or
a laptop on battery, and answers the state's `ripening`. A pause lasts
until it is resumed or the runtime stops; the next start ripens again. It
stops only the background ripening: a post that needs a riper key still
ripens what it needs.

## 4.2 Unlocking and Setting Up

- `POST /api/unlock` `{"passphrase": "..."}`: answers the state. A wrong
  passphrase is `400`.
- `POST /api/setup` `{"display": "...", "node": "..."}`: the first start
  of a new vault. It makes the identity and adds the node, then the
  runtime starts (UN-RFC 0025: a new key ripens in the background).
- `POST /api/passphrase` `{"old": "...", "new": "..."}`: a new passphrase
  for this vault file, answering `{"ok": true}`. A wrong `old` or a `new`
  shorter than 4 characters is `400`; if the file cannot be written it is
  `500` and the old passphrase still works. Copies of the vault elsewhere
  keep the old one. Not for a service (section 3.2).

## 4.3 Groups

`GET /api/groups`:

```
{"groups": [<GroupInfo dict>, ...],
 "people": [{"id": "contact:<key>", "key": "...", "name": "...", "contact": true,
             "unread": 0}, ...],
 "inbox": {"id": "inbox@<fp>", "unread": 0},
 "hierarchies": [{"name": "dk", "tree": <folder>}, ...],
 "for_you": {"id": "for-you:", "replies": 0, "mentions": 0},
 "moderation": 0, "name_requests": 0}
```

`groups` are the groups the identity follows, in its order
(`Session.subscribed_groups()`), with their counts. `people` are its chats
(UN-RFC 0028 section 6.2); `inbox.id` is null until the inbox is set up,
`moderation` counts the posts waiting for you to approve (section 4.7) and
`name_requests` the people asking for a name under yours (section 4.8).
Every group here and elsewhere also has `shown`: its name as people should
see it, without the fingerprint only where the hierarchy lists the name
(UN-RFC 0018). A front end shows `shown`, not `label`.
`hierarchies` lays the groups out as every client of this project does: a
folder is `{"label", "path", "own", "groups": [<group ID>, ...],
"children": [<folder>, ...]}`, names under `alt.` without it and a shared
part of names as a folder.
Besides real group IDs, two pseudo IDs work
wherever a group ID does: `contact:<key>` (the chat with one person) and
`for-you:` (replies and mentions from all groups).

`GET /api/groups/<id>`:

```
{"group": <GroupInfo dict>,
 "rows": [{"message": <Message dict>, "depth": 0, "read": true, "for_me": null,
           "who": "...", "who_key": "...", "contact": false,
           "mine": false, "bot": false, "may_edit": false, "may_withdraw": false,
           "tree": [...], "groups": ["#name@fp", ...], "notice": null}, ...]}
```

`rows` are in the order to show them (`Session.threads()`): threads
newest first for a group read as threads, every line in order for one
read as a chat. `for_me` is `"reply"`, `"mention"` or null. `who` is how
the runtime names the author (a contact's name, a verified name, UN-RFC
0019), so that every front end names people alike. `tree` is the text
rendered for showing (UN-RFC 0031): Markdown or plain by the post's
`Content-Type`, as nodes `{"t": "p" | "text" | "strong" | ..., "c": [...],
"v": "..."}` in which HTML is always text. A front end MUST draw the tree,
or the plain text, and MUST NOT put a post's text into a page as HTML.
`bot` is true when the author's profile says it posts automatically
(UN-RFC 0030 section 6): show a mark. `groups` are the `#group` references in it; `notice` is set for a mention
notice (UN-RFC 0032): `{"group", "id", "label", "ref", "followed"}`. The group adds
`may_post`, and for a real group `rules`, `rules_type`, `rules_tree`, `portals`,
`portal_warning`, `write`, and for its owner or a moderator `roles` (section 4.7):
`{"moderators", "posters", "banned", "moderates", "maintainer"}` and, for a
closed group's owner, `members`; `maintainer` is true when you maintain a
hierarchy the group is in, so you may block people there (section 4.6).

`write` says whether you may write here, before you write:
`{"post": <permission>, "chat": <permission>}`, and in a real group each
row has `reply`, whether you may answer that post. A permission is
`{"allowed": true | false, "reason": "<for people>", "code": "ok" |
"own_inbox" | "kind" | "banned" | "blocked" | "not_member" | "channel" |
"channel_thread" | "comments_closed"}`, from the cached manifest: the kinds
a group takes (UN-RFC 0028), bans and blocks (UN-RFC 0004, 0018),
posters and members, and channel comments (UN-RFC 0030). A front end
SHOULD make what is not allowed unavailable up front and show `reason`;
the node still has the last word.

- `POST /api/groups/<id>/read` `{"ids": [<Message-ID>, ...]}`: at most 500.
- `POST /api/groups/<id>/view` `{"view": "threads" | "chat" | null}`:
  null goes back to the owner's choice (UN-RFC 0008 section 3.1).
- `POST /api/subscribe` `{"id": "<group ID>", "on": true}`.
- `GET /api/browse?pattern=<wildmat>`: `{"groups": [<GroupInfo dict>, ...]}`,
  what the node lists.
- `GET /api/known-nodes`: `{"nodes": [{"address", "name", "description",
  "operator"}, ...]}` (UN-RFC 0010), for choosing a node.
- `GET /api/group-ref?ref=<#name@fp or #name>`: `{"groups": [...]}`, what a
  `#group` reference in a post can mean, each with a `warning` for people
  where the name is not the hierarchy's (UN-RFC 0018).
- `GET /api/about`: what Unseenet is, in plain words, also while locked.
- `POST /api/refresh`: fetch every group now.

## 4.4 Writing

- `POST /api/groups/<id>/post`
  `{"kind": "post" | "chat", "subject": "...", "body": "...", "references": [...]}`
  answers `{"job": "<job ID>"}` at once. A post needs a subject; a chat
  line has none (UN-RFC 0028). A post gets your signature unless
  `"signature": false`; `"notify"` true or false overrides your setting for
  mention notices (UN-RFC 0032). To `contact:<key>` it is a private post.
- `POST /api/private`
  `{"key": "ed25519:...", "kind": "post" | "chat", "subject": "...", "body": "...", "reply_to": <Message-ID or null>}`
  answers `{"job": "<job ID>"}`.

Its progress comes as `job` events (section 5). The runtime asks about
portals (UN-RFC 0023 section 3.5) before it sends: a group with a portal
answers `400` with the warning until the post carries
`"publish_outside_tor": true`.

`GET /api/emoji`, also while locked, is what a front end needs for an
emoji picker and for completing `:ta` while typing (UN-RFC 0031 section
5.2): `{"table": {"<shortcode>": "<glyph>", ...}, "categories": [{"name",
"codes": [...]}, ...], "names": {"<shortcode>": "<search words>", ...}}`.
`categories` lists each emoji once, by its first shortcode; `names` has
its name, tags and other shortcodes, for searching. It does not change
while the runtime runs, so a front end loads it once. A picker puts the
`:shortcode:` in the text, not the glyph, so the text stays readable in
every client. The order to suggest in is that of the core's
`find_emoji()`: shortcodes that start with what was typed (shortest
first), then those containing it, then by a word of the name.

## 4.5 Your Own Posts

- `POST /api/groups/<id>/edit` `{"id": "<Message-ID>", "subject": "...", "body": "..."}`:
  a new version of your own post or chat line (UN-RFC 0042); answers
  `{"job": "<id>"}`.
- `POST /api/groups/<id>/withdraw` `{"id": "<Message-ID>"}`: your own
  post, or one in a group you own or moderate (UN-RFC 0004 section 7).
- `POST /api/groups/<id>/mentioned` `{"subject": "...", "body": "..."}`:
  who a post would tell (UN-RFC 0032), before it is sent:
  `{"may": true, "names": [...], "max": 10}`.

## 4.6 People and Safety

- `POST /api/contacts` `{"key": "...", "name": "..."}` adds or renames a
  contact, `{"key": "...", "remove": true}` removes one.
- `GET /api/ignore` lists the keys you ignore (`{"ignored": [{"key",
  "label"}, ...]}`); `POST /api/ignore`
  `{"key": "...", "label": "...", "on": true}` ignores one or stops.
- `GET /api/groups/<id>/report?id=<Message-ID>` lists who a post can be
  reported to (owner, moderators, the hierarchy's maintainer, the node's
  operator, and spam report issuers, UN-RFC 0045) as `{"targets": [{"i":
  0, "who": "..."}, ...]}`; `POST` it `{"id": "...", "targets": [<index>, ...], "note":
  "...", "anonymous": false}` answers `{"sent": <n>}`.
- `POST /api/groups/<id>/block` `{"key": "...", "reason": "..."}`: a
  hierarchy maintainer's block (UN-RFC 0018 section 5.4); answers
  `{"hierarchy": "<name>"}`.

## 4.7 Groups You Run

Each answers `{"ok": true}` unless said otherwise, and `400` when you may
not (you do not own or moderate the group).

- `POST /api/groups` `{"name": "...", "type": "open" | "moderated" |
  "channel" | "closed", "title": "...", "description": "...", "view":
  "threads" | "chat", "kinds": "both" | "post" | "chat", "fast": false}`
  creates a group you own; answers `{"id": "<group ID>"}`.
- `POST /api/groups/<id>/settings` with the manifest fields to change
  (`title`, `description`, `rules`, `rules_type`, `view`, `kinds` as for
  creating, `min_pow`, `low_latency`, `retention_days`, `comments`,
  `comment_days`): a new manifest (UN-RFC 0004, 0014, 0030). Any other field
  is `400`.
- `POST /api/groups/<id>/remove` `{"confirm": "remove", "reason": "..."}`:
  removes the group from the whole network (UN-RFC 0013). Final.
- `POST /api/groups/<id>/invite` `{"key": "..."}` and
  `POST /api/groups/<id>/members/remove` `{"key": "..."}` (closed groups;
  removing answers `{"epoch": <n>}`, UN-RFC 0004 section 6).
- `POST /api/groups/<id>/role` `{"role": "moderators" | "posters", "key": "...", "on": true}`.
- `POST /api/groups/<id>/ban` `{"key": "...", "on": true, "reason": "..."}`.
- `GET /api/moderation` lists posts waiting for you to approve (UN-RFC 0004
  section 5) as `{"waiting": [{"id", "group", "subject", "who", "key",
  "body", "tree", ...}, ...]}`; `POST` it `{"id": "...", "approve": true, "reason": "..."}`.

## 4.8 Who You Are

- `GET /api/profile?key=<key>` (yours without `key`): a public profile
  (UN-RFC 0022) or `null`, as `{"key", "profile", "about_tree", "label",
  "mine", "hidden", "link_kinds"}`. `hidden` is true when you hid this
  key's profile (UN-RFC 0022 section 9.2); then it is not even fetched.
  Before fetching someone's, the runtime reads the profiles of the authors
  it has together with it, so a node cannot tell whose you open (UN-RFC 0022
  section 13). Yours adds `published` (whether one is published yet) and
  `warning`, the text to show before the first is published (section 9.1),
  the same in every client.
- `POST /api/profile` with a profile object publishes yours, `null`
  removes it; `{"edit": {"about": "...", "links": [{"kind", "value",
  "label"}], "lang": ["da", ...], "markdown": true}}` builds the object from
  a form's fields and keeps the bot mark you have. It answers as `GET`,
  with `published`. A program's profile says `"bot": true` (UN-RFC 0030
  section 6).
- `POST /api/profile/hide` `{"key": "...", "hidden": true | false}`: hide
  or show someone's profile, for you alone; answers `{"key", "hidden"}`.
- `GET /api/names` lists your names, waiting claims and the names you give
  under yours (UN-RFC 0019); `POST /api/names` `{"action": "claim" |
  "renew" | "give" | "revoke" | "approve" | "refuse", ...}` answers
  `{"text": "<what happened, for people>"}`.
- `GET /api/settings` and `POST /api/settings` with any of:
  `signature` (a template), `markdown` (true or false, UN-RFC 0031),
  `notices` (`{"send": true, "receive": true}`, UN-RFC 0032),
  `private_min_ripe` (a level or null, UN-RFC 0025 section 3.5),
  `show_blocked` (true or false: show posts a hierarchy blocked,
  UN-RFC 0018), `hide_bots` (true or false: leave out posts by keys whose
  profile says `bot`, UN-RFC 0030 section 6). Both answer all settings, with `signature_preview` (the
  template filled in). An unknown setting is `400`.

## 4.9 Articles from a Program

For a service (section 3.2), such as a gateway, that builds what it posts:

- `POST /api/articles` `{"group": "...", "kind": "post" | "chat",
  "subject": "...", "body": "...", "from": "...", "references": [...],
  "content_type": "...", "headers": [["X-Gateway", "usenet"], ...]}`
  answers `{"job": "<id>"}`. The runtime builds, signs with its key,
  adds postage and `Key-Ripening`, and posts it (`Session.post_article`
  with `sign_with`). `headers` may only add headers this document's runtime
  may not set itself: names starting with `X-`, or those another UN-RFC
  gives a program (`Gateway-*`, UN-RFC 0023). Anything else is `400`.
- `POST /api/groups/<id>/manifest` with a whole manifest object posts a
  new version of a group the key owns (a gatewayed group, a bot's channel),
  for what section 4.7 does not cover. `type`, `owner`, `name` and `local`
  cannot change; the runtime sets `serial`.

# 5. Events

`GET /api/events` is a WebSocket (subprotocols `unseenet` and the token,
section 3). Each message is one JSON object with its name in `event`:

- every event of the core, as `to_dict()` gives it (`client.events`):
  `status`, `group-updated`, `groups-changed`, `node-state`, `tor-state`,
  `inbox-ready`, `refreshed`, `release-offer`, `ripening`, and
  `pow-progress`;
- `job`: `{"event": "job", "job": "<id>", "group": "<id>", "state": ...}`
  with `state` one of `ripening`, `pow`, `sent`, `reached`, `failed`, and
  `fraction` (0 to 1) with `ripening` and `pow`, `message_id` with `sent`
  and `reached`, `error` with `failed`;
- `ripening-paused`: `{"event": "ripening-paused", "paused": true | false}`
  after `POST /api/ripening`, so every window follows.

A front end that connects late asks `GET /api/state` and the groups
again; events are not replayed.

# 6. Extensions

A runtime MAY offer more, under `/x/<name>/` (for example unseenet-gui's
owner tools or a bootable machine's Wi-Fi and power settings, `/x/gui/`),
with the same security rules. Paths under `/api/` are this document's.
An extension's own events on `/api/events` are named `x-<name>-...`
(`x-gui-update` for unseenet-gui's update progress); a front end ignores
events it does not know.

## 6.1 Not in This API

Running a node or a web entrance, and having it join the network, is not
a client's work: a node asks the hierarchy to list it in its own way
(UN-RFC 0010 and 0021 for nodes, UN-RFC 0038 for gateways, UN-RFC 0043
for web entrances), and its
operator configures it in `node.toml`. A program that does that work for
an operator MAY use this API for the client part (posting the request
as the operator's key, section 4.9) and does the rest itself.

What only one front end on one kind of machine needs - Wi-Fi, power,
the keyboard layout, installing an update of a bootable image - stays
an extension (`/x/gui/` in unseenet-gui).

# 7. Rationale

**Why HTTP and a WebSocket.** Every language and every browser speaks
them, so a front end can be a page, a native app or a script. A local
socket file would keep out other users without a token, but a browser
cannot open one.

**Why this much.** A front end that can read and post but not report a
post, ignore a person, edit what it wrote or run its own group would
send people back to another client for half of what they do, and each
such front end would invent its own extension for it. So everything a
client of this project offers a person is here; only what depends on one
kind of machine is left to extensions.

**Why services use it too.** A bot or gateway posts the same way a person
does - postage, ripening, signatures - and the project wants one code
path for that (`Session`). Giving them the same API, without unlock and
with prebuilt articles, means a bot in any language gets ripening and
postage right without reimplementing UN-RFC 0025.

**Why jobs.** Postage takes seconds on an old laptop and a new key
ripens for minutes before its first post (UN-RFC 0025). A request that
waited would time out; a job answers at once and tells how far it is.

# 8. Security Considerations

- **Other users on the same machine** can connect to `127.0.0.1`. The
  token, which only the front end knows, keeps them out. The `.api` file
  is readable by its owner only.
- **Web pages** cannot read the API: no CORS, `Origin` and `Host` are
  checked, and the token is not in any URL a server sees.
- **The front end itself** is trusted to show what the person sees, not
  with keys: a compromised front end can post as the person while the
  vault is unlocked, but cannot take the keys away.
- **Posts are hostile text.** Anyone can post anything. Rendering in the
  runtime, to a tree in which HTML is only ever text, means no front end
  has to get Markdown or escaping right on its own; with the CSP, a post
  can neither run a script nor load anything from outside.
- **Logs.** A runtime MUST NOT log the token, the passphrase or bodies of
  private posts.

# 9. Changes to Other Documents

None. UN-RFC 0043's web entrance serves the client to a browser over the
network and is not this API.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.

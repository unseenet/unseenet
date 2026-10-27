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

Unlocked: `identity` is `{"key": "ed25519:...", "display": "...", "label",
"words_written", "words_reminder"}` (the last two: section 4.18),
`node` the default node, `node_label` how it is shown (section 4.17),
`nodes` your node addresses and `node_names` each one's `{"name",
"source", "label"}`, and `ripening` `{"level": <0-4 or null>, "t":
<iterations>, "next_at": <iterations or null>, "published": <the level
nodes know, or null>, "available": <true if this runtime can ripen>,
"paused": <true while paused>}` (UN-RFC 0025). `setup` is true while the
identity or the node is still missing.

`status` is a line for people. `status_idle` is true when it only says
that a node was reached ("Connected to ...", the default node or one a
group is read from): a front end that shows the node elsewhere MAY leave
such a line out, and show `status` again when `status_idle` is false (Tor
starting, offline, a post being sent). Whether a node is reached right
now is the `node-state` event's (section 5), per node.

`POST /api/ripening` `{"paused": true | false}` pauses or resumes ripening
in the background (UN-RFC 0025 section 7), for example on a warm phone or
a laptop on battery, and answers the state's `ripening`. A pause lasts
until it is resumed, also over a restart: the runtime keeps it with the
key's ripening in the vault, on this device only - it is not part of your
state in the network (UN-RFC 0044), so pausing on a phone does not pause
another device. It stops only the background ripening: a post that needs
a riper key still ripens what it needs.

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
 "contacts": [{"id": "contact:<key>", "key": "...", "name": "...", "closed": false}, ...],
 "inbox": {"id": "inbox@<fp>", "unread": 0},
 "hierarchies": [{"name": "dk", "tree": <folder>}, ...],
 "for_you": {"id": "for-you:", "replies": 0, "mentions": 0},
 "timeline": {"id": "timeline:", "feeds": 0},
 "my_feed": {"id": "feed@<fp>", "started": false, "unread": 0},
 "my_site": {"id": "site@<fp>", "started": false, "unread": 0},
 "moderation": 0, "name_requests": 0}
```

`groups` are the groups the identity follows, in its order
(`Session.subscribed_groups()`), with their counts. `people` are its chats
(UN-RFC 0028 section 6.2), without the ones you closed (section 4.6);
`contacts` are all your contacts, with whether their chat is closed;
`inbox.id` is null until the inbox is set up,
`moderation` counts the posts waiting for you to approve (section 4.7) and
`name_requests` the people asking for a name under yours (section 4.8).
Every group here and elsewhere also has `shown`: its name as people should
see it, without the fingerprint only where the hierarchy lists the name
(UN-RFC 0018). A front end shows `shown`, not `label`.
`hierarchies` lays the groups out as every client of this project does: a
folder is `{"label", "path", "own", "groups": [<group ID>, ...],
"children": [<folder>, ...]}`, names under `alt.` without it and a shared
part of names as a folder.
Besides real group IDs, three pseudo IDs work
wherever a group ID does: `contact:<key>` (the chat with one person),
`for-you:` (replies and mentions from all groups) and `timeline:` (the
entries of every feed you follow, section 4.14).
`timeline` is `{"id": "timeline:", "feeds": <how many feeds you follow>}`.
`my_feed` is your personal feed (UN-RFC 0034 section 5) and `my_site`
your personal site (UN-RFC 0035 section 7): a front end lists each at the
top as "My feed" and "My site" once `started`, and then `hierarchies`
leaves it out; before, it offers to start it (sections 4.14, 4.15).

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
(UN-RFC 0030 section 6): show a mark. `identicon` is the author's identicon
(section 4.11). `groups` are the `#group` references in it; `notice` is set for a mention
notice (UN-RFC 0032): `{"group", "id", "label", "ref", "followed"}`. The group adds
`may_post`, and for a real group `rules`, `rules_type`, `rules_tree`, `portals`,
`portal_warning`, `write`, `files` and `node_files` (section 4.10), and for its owner or a moderator `roles` (section 4.7):
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

**Reactions** (UN-RFC 0048). A group's head has `reactions`:
`{"offered": ["👍", ...], "any": false, "setting": "default"}`, the emoji
the group takes in the order to offer them (with `any`, the default set
first and any other emoji besides; `offered` is empty when the group takes
none) and the owner's choice as section 4.7 takes it. In a real
group and in the timeline, each row has `reactions`, `[{"emoji": "👍",
"count": 3, "mine": true}, ...]` in the order they were first given, one
per key, `react`, a permission whose further codes are `"private"`,
`"target"` and `"no_reactions"`, and `react_offered`, the set of the row's
own group as in the head (the timeline mixes groups). Reactions are never
rows themselves.

- `POST /api/groups/<id>/read` `{"ids": [<Message-ID>, ...]}`: at most 500.
- `POST /api/groups/<id>/view` `{"view": "threads" | "chat" | "feed" |
  "pages" | null}`: null goes back to the owner's choice (UN-RFC 0008
  section 3.1, UN-RFC 0034 section 3.1); `pages` only for a site (section
  4.15).
- `POST /api/subscribe` `{"id": "<group ID>", "on": true}`.
- `GET /api/browse?pattern=<wildmat>`: `{"groups": [<GroupInfo dict>, ...]}`,
  what the node lists.
- `GET /api/known-nodes`: `{"nodes": [{"address", "name", "description",
  "operator"}, ...]}` (UN-RFC 0010), for choosing a node. It answers as
  soon as the vault is unlocked, also while `setup` is true, since that is
  where a new user chooses one.
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

A post to a group, a chat line, and a private post or chat may carry
files: `"files": [{"name": "...", "data": "<base64>", "alt": "..."},
...]`, at most four (section 4.10). With files the body may be empty. In
closed groups and private posts the runtime encrypts them (UN-RFC 0027
section 3.3); to an inbox that takes no files the job fails, saying so.
An edit (section 4.5) keeps the files of the earlier version.

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
- `POST /api/groups/<id>/react` `{"id": "<Message-ID>", "emoji": "👍"}`:
  react to a post, comment or chat line (UN-RFC 0048), as a job (`{"job":
  "<id>"}`); the emoji you already gave takes it back, another one changes
  it. With `"who": true` it answers `{"who": ["<label>", ...]}`, who gave
  that emoji, instead.
- `POST /api/groups/<id>/mentioned` `{"subject": "...", "body": "..."}`:
  who a post would tell (UN-RFC 0032), before it is sent:
  `{"may": true, "names": [...], "max": 10}`.

## 4.6 People and Safety

- `POST /api/contacts` `{"key": "...", "name": "..."}` adds or renames a
  contact, `{"key": "...", "remove": true}` removes one.
- `POST /api/chats/close` `{"key": "...", "on": true}` takes a chat with a
  person off `people` in `GET /api/groups` (`"on": false` puts it back).
  It is kept in the state (UN-RFC 0044 section 4.2, `closed_chats`), and
  the chat comes back by itself with the next chat line from or to them;
  sending one opens it too.
- `GET /api/ignore` lists the keys you ignore (`{"ignored": [{"key",
  "label"}, ...]}`); `POST /api/ignore`
  `{"key": "...", "label": "...", "on": true}` ignores one or stops.
- `GET /api/groups/<id>/report?id=<Message-ID>` lists who a post can be
  reported to (owner, moderators, the hierarchy's maintainer, the node's
  operator, and spam report issuers, UN-RFC 0045) as `{"targets": [{"i":
  0, "who": "..."}, ...], "reasons": [{"id", "label"}, ...]}` - `spam`,
  `illegal`, `threats`, `other`, as every client offers them; `POST` it
  `{"id": "...", "targets": [<index>, ...], "reason": "...", "note": "...",
  "files": [...], "anonymous": false}` answers at once `{"job", "targets"}`:
  each receiver's sealed copy pays postage as an unripe key (UN-RFC 0025
  section 3.5), which can take minutes, so it is a job like a post
  (section 5), and `sent` says when every receiver has it. The note is
  Markdown (UN-RFC 0031) and `files` are as on a post (section 4.10) - a
  screenshot, a document - sent encrypted to each receiver (UN-RFC 0027
  section 3.3). The report arrives as Markdown with the parameter
  `report=post` in its Content-Type, its group, Message-ID, author key and
  reason as lines of their own.
- `POST /api/groups/<id>/block` `{"key": "...", "reason": "..."}`: a
  hierarchy maintainer's block (UN-RFC 0018 section 5.4); answers
  `{"hierarchy": "<name>"}`.

## 4.7 Groups You Run

Each answers `{"ok": true}` unless said otherwise, and `400` when you may
not (you do not own or moderate the group).

- `POST /api/groups` `{"name": "...", "type": "open" | "moderated" |
  "channel" | "closed", "title": "...", "description": "...", "view":
  "threads" | "chat" | "feed" | "pages", "kinds": "both" | "post" | "chat",
  "fast": false, "comments": "open" | "none", "files": "none" | "pictures" |
  "pictures+pdf"}` creates a group you own;
  answers `{"id": "<group ID>"}`. `files` is what files it takes (UN-RFC
  0027 section 5.1): none (the default), pictures, or pictures and PDFs,
  up to 4 MiB each. `pages` makes a site and needs `"type": "channel"`
  (UN-RFC 0035 section 3); `comments` is for channels (UN-RFC 0030), and a
  channel shown as `feed` takes comments unless it says `none`; `fast` is
  for chat groups only.
- `POST /api/groups/<id>/settings` with the manifest fields to change
  (`title`, `description`, `rules`, `rules_type`, `view`, `kinds` as for
  creating, `min_pow`, `low_latency`, `retention_days`, `comments`,
  `comment_days`, `files` as for creating, `reactions`: `"default"`,
  `"none"`, `"any"` or a list of up to 12 emoji, UN-RFC 0048 section 4,
  `index`: `"yes"` or `"no"` for a site, UN-RFC 0035 section 3):
  a new manifest (UN-RFC 0004, 0014, 0030). Any other field is `400`.
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
  "mine", "hidden", "link_kinds"}` (and `shared`, section 4.16). `hidden` is true when you hid this
  key's profile (UN-RFC 0022 section 9.2); then it is not even fetched.
  Before fetching someone's, the runtime reads the profiles of the authors
  it has together with it, so a node cannot tell whose you open (UN-RFC 0022
  section 13). Yours adds `published` (whether one is published yet) and
  `warning`, the text to show before the first is published (section 9.1),
  the same in every client, and `picture` (yours as published, section
  4.11, or null) with `picture_warning`, the text to show before the first.
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
  profile says `bot`, UN-RFC 0030 section 6), `pictures` (true or false:
  false shows identicons only, section 4.11), `state_local` (true or false:
  keep your state on this device only, or in the network, UN-RFC 0044
  section 7.4; turning it on removes what is in the network). Both answer
  all settings, with `signature_preview` (the template filled in). An
  unknown setting is `400`, and then nothing is changed.
- `GET /api/settings/clients/<client>` answers `{"client", "settings": {...}}`:
  the settings one kind of client keeps for itself (`gui`, `tui`, ...),
  kept with your state so they follow you from device to device (UN-RFC
  0044 section 4.2) - a theme, a font size. `POST` it `{"<key>": value, ...}`
  to change them, `null` removing one; it answers as `GET`. Client names
  and keys are lowercase letters, digits and `-` (at most 32); values are
  strings (at most 256 characters), numbers, true or false. A front end
  MAY keep a copy in the browser for its first paint, but these are what
  count.

- `GET /api/notifications`: what new has landed in *For you* since any client
  last asked - private chats and posts to you, replies and mentions; not your
  own, not reactions, not what was old on arrival (UN-RFC 0049 section 5.2).
  `{"settings", "count", "items": [{"id", "group", "why": "private" | "reply" |
  "mention", "chat", "who", "text"}]}`; `who` and `text` only when
  `settings.content` is true. Asking marks them as told. The first time ever it
  answers none and notes what is unread then. `settings` is the reader's choice,
  also in `GET /api/settings` as `notifications` and changed there with
  `{"notifications": {"on": true | false | null, "content": bool}}` (`on` null:
  ask the first time); it is kept with the state (UN-RFC 0044), so it is the
  same in every client. Front ends tell only while they run: there is no push.

- `POST /api/export` `{"path", "private": false, "passphrase"}`: write an
  export of your data as UN-RFC 0049 section 7 says - your own articles as
  signed, their files, the sites you write in, your profile and picture, your
  state and an `index.html`; never keys. `path` defaults to Downloads. With
  `private` the private posts and chats are in it too and the whole file is
  encrypted with `passphrase` (UN-RFC 0007), named `….zip.sealed`. Answers
  `{"path", "articles", "files", "sites", "private", "encrypted", "missing",
  "note"}`; `note` says it holds only what the nodes still carry and the client
  kept - show it.

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

## 4.10 Files on Posts

Files are blobs (UN-RFC 0027). A file from the network is hostile input,
so the runtime does all the work with it and the front end gets only
what the runtime has checked and, for a picture, saved again.

A Message dict lists the files a post carries in `attachments`:
`[{"blob": "blob1:...", "type": "image/jpeg", "size": <octets>, "name":
"...", "alt": "...", "dim": [<width>, <height>] or null}, ...]`, in the
order to show them. `name` and `alt` are text the author wrote (UN-RFC
0027 section 4.2): show them as text. A group's head (section 4.3) has
`files`, what the group takes - `{"max_size": <octets>, "types": [...]}`,
`types` empty for any type, or null when it takes none (UN-RFC 0027
section 5.1) - and `node_files`: true when the node the group is read
from carries files, false when it does not, null when the runtime is not
connected to it yet. A front end SHOULD say plainly when a group takes
files but its node carries none, rather than show posts whose pictures
never come.

`GET /api/groups/<id>/files/<blob-id>` answers a picture a post in that
group carries, made safe to show:

```
{"type": "image/jpeg", "width": 64, "height": 48, "frames": 1,
 "data": "data:image/jpeg;base64,..."}
```

The runtime fetches the blob from the group's node, checks it against
its blob ID and the size the post names, determines the type from the
content (it MUST be the declared one), and decodes and saves it again in
a separate process with as few rights as the platform allows, refusing
more than 50 megapixels or 1000 frames (UN-RFC 0027 section 9.2).
`data` is that new copy, never the octets from the network. Only
`image/jpeg`, `image/png`, `image/gif` and `image/webp` are shown; SVG
and PDF are never decoded. A picture by a key you ignore is answered
`403` unless the request adds `?asked=1` - the person chose to see it.

With `?save=1` it answers the file itself, checked against its blob ID
but not decoded, to save: `{"name": "...", "type": "...", "size":
<octets>, "data": "<base64>"}`. A front end MUST NOT open it in another
program without the person asking each time, and MUST warn first that
such a program runs outside Unseenet and may go to the internet without
Tor (UN-RFC 0027 section 9.2).

Errors carry `why` beside `error`:

| Status | `why`       | Meaning                                              |
|--------|-------------|------------------------------------------------------|
| 404    | (none)      | No post here that this runtime has read carries it   |
| 404    | `none`      | The group's node carries no files                    |
| 404    | `gone`      | The node does not have it (any more)                 |
| 503    | `later`     | The node is still fetching it from a peer: try again |
| 502    | `wrong`     | The node sent another file than the post names       |
| 403    | `ignored`   | By a key you ignore; `?asked=1` to see it anyway     |
| 415    | `not_shown` | Not a picture this API shows (save it instead)       |

A post with files (section 4.4) sends each file as `{"name", "data",
"alt"}` with `data` base64. The runtime prepares them as every client of
this project does: the type from the content, a picture saved again
without its metadata (GPS position, time, camera, owner), its size in
pixels in `dim`, and `alt` in the header. It checks them against the
group before any postage is computed and answers `400` with the reason
for people when the group takes no files, not of this type or size, or
more than four or 8 MiB together. A request may be at most 12 MiB.

## 4.11 Pictures of People

Every identity has an identicon and may have a picture (UN-RFC 0022
section 8). The runtime gives both ready to draw, and the page never
gets a picture the runtime has not checked.

An identicon is `{"hue": <degrees>, "cells": [[true, false, ...], ...],
"colour": "#rrggbb"}`: five rows of five cells, filled cells in the
colour (saturation 55 %, lightness 50 %; a front end MAY change the
lightness for its theme but MUST keep the hue). It is shown together
with the short form of the fingerprint, never instead of it (UN-RFC 0022
section 8.4). Each row of a group (section 4.3) has the author's.

`GET /api/pictures?keys=<key>,<key>,...` (at most 255) answers

```
{"pictures": {"<key>": {"identicon": {...},
                         "picture": {"type": "image/webp", "px": 96, "alt": "...",
                                     "data": "data:image/webp;base64,..."} or null}}}
```

The runtime reads the avatar groups of these keys together with those of
the other authors it has, so a node cannot tell whose pictures are
looked at (UN-RFC 0022 section 13), and keeps them for a day. It decodes
each picture and saves it again in a separate process (UN-RFC 0027
section 9.2) and treats it as absent unless it is the square, still
picture of `px` pixels it says it is (UN-RFC 0022 section 8.1). A key
whose profile you hid, a key you ignore, or every key while the setting
`pictures` is false, gets `null`: show its identicon. `alt` is text the
owner wrote: show it as text. A picture is shown next to the names and
the short form, never instead of them and never as part of a post.

`POST /api/profile/picture` sets your own:

- `{"data": "<base64>", "alt": "...", "preview": true}` makes the picture
  from a file the person chose - the middle square, at most 128 pixels
  and 8 KiB, saved again without metadata - and answers it as it would
  be published, `{"picture": {...}, "published": <whether one is
  published already>}`, without publishing anything. A front end MUST
  show it so before publishing (UN-RFC 0022 section 8.5), and before the
  first one it MUST show `picture_warning` from `GET /api/profile`.
- The same without `preview` publishes it and answers `{"picture": {...},
  "published": true}`.
- `{"remove": true}` removes yours; what others kept cannot be taken back.

## 4.12 Pinned Posts

The owner and moderators of a group may pin posts at the top of it, and
nodes keep a pinned post beyond the group's window (UN-RFC 0033). The
head of a group (section 4.3) has

```
"pins": [{"id": "<message-id>", "note": "...", "by": "<key>", "by_label": "...",
          "pinned": "<ISO 8601>", "subject": "..." or null, "who": "..." or null,
          "date": "<ISO 8601>" or null, "beyond_window": false}, ...],
"max_pins": 5, "may_pin": true
```

`pins` are the pins in force, newest pin first, as every client of this
project and every node works them out (UN-RFC 0033 section 4.2): only
pins by the owner and moderators of the current manifest count, at most
`max_pins`, and not of withdrawn posts. `subject`, `who` and `date` are
the pinned post's, null while the runtime does not have it. `note` is
text the pinner wrote: show it as text. `may_pin` says whether you may
pin here: you own or moderate the group and it takes pins. Each row also
has `pinned`. A front end shows the pins above the threads, or as a bar
above a chat, and keeps each pinned post in its place too (UN-RFC 0033
sections 7.2 and 7.3). When there are `max_pins` pins already, a new pin
makes the last of `pins` stop counting: a front end MUST say which
before pinning (UN-RFC 0033 section 7.1).

`POST /api/groups/<id>/pin` with `{"id": "<message-id>", "note": "..."}`
pins a post (a note is at most 256 characters), and with `{"id": ...,
"unpin": true}` unpins it; it answers `{"ok": true, "marker":
"<message-id of the marker>", "pins": [...]}`. Refused with 400 for
anyone but the owner and moderators, in a group whose `max_pins` is 0,
or to unpin a post that is not pinned. A pin with `beyond_window` true is
of a post older than the group keeps posts: unpinned, it is gone at
once, so a front end MUST say so before unpinning it (UN-RFC 0033
section 7.1).

## 4.13 Addresses

Every identity, group, post and page has one `unseenet:` address (UN-RFC
0031 section 3.4.1). The runtime writes them and reads them, so every front
end shares the same addresses and opens every form, the older ones too.

The head of a group (section 4.3) has `address`, the group's, and each of
its rows has `address`, the post's; a profile (section 4.8) has `address`,
the identity's. They carry the node this runtime reads the group from as
an `n=` hint when that node is an onion address. A front end offers them
to copy.

`GET /api/address?a=<address>` says what an address names:

```
{"kind": "identity" | "group" | "post" | "page", "address": "<the current form>",
 "web": "https://<entrance>/a/..." or null, "nodes": ["<n= hints>"],
 "fingerprint": "...", "key": "<key>" or null, "label": "...", "mine": false,
 "group_id": "...", "followed": true, "available": true,
 "group": {"id", "label", "title", "type", "view"},
 "message": {"id", "subject", "kind", "who", "date"} or null,
 "page": {"path", "title"} or null}
```

with the fields of its kind: `fingerprint`, `key` (a key this runtime knows
with that fingerprint, or null) and `mine` for an identity; for the others
`group_id`, `followed`, `available` (whether your nodes have the group) and
`group`, with `message` for a post and `page` for a page, null while the
runtime cannot find it. The runtime fetches the group's manifest, and for a
post or a page its posts, from your nodes; it never connects to the `n=`
hints by itself (UN-RFC 0031 section 3.4.1) - a front end asks before
adding one. An older form, such as `unseenet:join?g=...`, `web+unseenet:` or the
web form `https://<host>/a/...` on any host, is answered with its current
form in `address`; `web` is the web form on the first listed web entrance
(UN-RFC 0043 section 8.1), without `n=` hints, or null when none is
listed. A front end offers both to copy. Refused with 400 when it is not an address.

## 4.14 Feeds

A group whose `view` is `feed` (UN-RFC 0034) is read like any group
(section 4.3): its rows are its entries, every post or chat line that
answers nothing in the group, newest first by `Date`, each at depth 0 and
followed by its comments, two levels at most (`Session.feed_rows()`), and a front end shows them as
UN-RFC 0034 section 4 says. In a group shown as a feed each row also has `comment`, a
permission (section 4.3) to answer it with a chat line, which is how a
comment is written (UN-RFC 0034 section 4.2): `POST /api/groups/<id>/post`
with `"kind": "chat"` and the entry, or the comment answered, last in
`references`.

`GET /api/groups/timeline:` is the timeline (UN-RFC 0034 section 7): the
entries of every feed you follow, newest first by `Date` and in no other
order, each followed by its comments as its feed has them. Each row has
`group_label`, the feed it is from, `address`, `reply` and `comment` for
that feed; writing from the timeline writes to the entry's own feed. The
head has `feeds`, how many feeds you follow. The runtime asks for the
manifests of followed groups it does not know yet, so that a feed is
known to be one; what changes comes as `groups_changed`.

Following never sends anything to anyone (UN-RFC 0034 section 6):

- `GET /api/following`: `{"people": [{"fingerprint", "key", "name",
  "label", "feeds": [<feed>, ...]}, ...], "feeds": [<feed>, ...]}`, the
  people you follow with the feeds followed because of them, and every
  feed you follow. A feed is `{"id", "label", "title", "type",
  "personal"}`, `personal` for a personal group (UN-RFC 0029 section 2.1).
- `POST /api/following` `{"person": "<key, name, fingerprint or
  unseenet: address>", "on": true}` follows a person - their personal
  groups and the feeds their profile lists (UN-RFC 0034 section 6.1) - and
  answers `{"ok": true, "fingerprint", "key", "name", "feeds", "new"}`;
  with `"on": false` it stops, answering `{"ok": true, "unsubscribed":
  [...]}`, the feeds followed only because of them. `{"feed": "<group
  ID>", "on": true}` follows a feed on its own, or stops. `{"refresh":
  true}` reads the profiles of those you follow again and answers `{"ok":
  true, "new": [...]}`, the feeds followed since. Refused with 400 when a
  person cannot be found.

Your own feed (UN-RFC 0034 section 5) is started only when you ask:

- `GET /api/feed`: `{"id": "feed@<fp>", "started": false, "followed":
  false, "warning": "..."}`, with the warning a front end MUST show before
  it is started (UN-RFC 0029 section 2.1).
- `POST /api/feed` `{"comments": "open" | "none", "title": "..."}` starts
  it (or follows it again) and answers `{"ok": true, "id": "feed@<fp>"}`.

A profile of someone else (section 4.8) has `feed`, the Group ID of their
personal feed, which may not exist, and `following`, whether you follow
them. Unless you hid it, it also has `theirs`: `{"feed": <Group ID or
null>, "site": <Group ID or null>}`, their personal feed and site as far
as they exist, so a front end can offer to look at them - opening a group
does not follow it (#506): `GET /api/groups/<id>` of a group you do not
follow and have not read fetches it, and an event says when
its posts are here (`group-updated`, section 5).

## 4.15 Sites and Pages

A group whose `view` is `pages` is a site (UN-RFC 0035). Its rows (section
4.3) are every version of every page as they are carried; which versions
count is the runtime's, with the rules every node uses (UN-RFC 0035
section 5):

- `GET /api/groups/<id>/site`: `{"id", "label", "title", "home", "owner":
  {"key", "label"}, "may_write", "max_pages", "index", "address", "pages":
  [{"path", "title", "home", "id", "who", "who_key", "date", "previous"},
  ...]}`, the pages in force, the home page first (section 5.2);
  `previous` says whether a previous version is kept, `may_write` whether
  you are one of the site's writers, `address` the home page's. Refused
  with 400 for a group that is not a site.
- `GET /api/groups/<id>/page?path=<path>`: one page in force, the home page
  without `path`: `{"path", "title", "home", "address", "row": <row>,
  "previous": {"id", "who", "date"} or null}`. `row` is as in section 4.3;
  in its `tree` a link without a scheme, a path in the same site (UN-RFC
  0035 section 8), is the `unseenet:` address of that page, so a front end
  opens it as any address (section 4.13). 404 when the page is not in force
  or not read yet.
- `POST /api/groups/<id>/page` writes a page, as a job (section 4.4):
  `{"path", "title", "text", "markdown": true, "files": [...]}` (files as in
  section 4.10, pictures pointed at by blob ID), `{"path", "remove": true}`
  removes it, and `{"path", "restore": true}` publishes its previous version
  again (UN-RFC 0035 section 10.4). `{"path", "text", "markdown", "preview":
  true}` writes nothing and answers `{"tree"}`, the page as readers will see
  it, for a preview (UN-RFC 0035 section 9.2). The runtime reads the site first, so the
  new version names the current one (section 9.2). Refused with 400 for a
  path that is not valid (section 4.1) or when you do not write the site.

`GET /api/site` and `POST /api/site` `{"title"}` are your personal site, as
`/api/feed` is your feed (section 4.14, UN-RFC 0035 section 7).

- `POST /api/groups/{gid}/site` `{"folder", "prune": false, "dry_run": true}`:
  publish a folder of Markdown (and HTML) on this machine as the site's pages
  (#538). A dry run answers at once `{"changes": [{"path", "title", "action":
  "new" | "changed" | "unchanged" | "remove" | "kept", "source", "files"}],
  "notes", "problems", "sent": 0}`; otherwise it is a job, as a post is, that
  sends only what changed (new versions naming the old) and, with `prune`,
  removes pages no longer in the folder. Problems (too many pages, a page too
  large) send nothing.

## 4.16 Private Profiles

A profile can be shared with one person or a closed group, where only
they can read it and it is shown only there (UN-RFC 0022 section 6) - for
someone who wants no public profile, or another one for friends.

- `POST /api/profile/share` `{"to": "<key> | <closed group id>",
  "profile": {...} | {"edit": {...}}}` shares one: without `profile` your
  public profile (with your picture inline, UN-RFC 0022 section 8.3), or
  another, given as for `POST /api/profile`. A key's goes to their
  personal inbox; anything but a key or a closed group is refused, for a
  public profile is published, not shared. `{"to": ..., "withdraw": true}`
  takes back the one you shared there. It answers `{"ok": true, "id":
  "<Message-ID>"}` and publishes nothing.
- `GET /api/profile?key=<key>&context=<where>` adds `shared`: the profile
  that key shared where it is opened, as `{"key", "profile", "about_tree",
  "context", "context_label"}`, or null. `context` is a closed group's ID,
  or `me` - your private posts, your inbox or a chat with them (`contact:`,
  section 4.3), which are all one context. Anything else has no shared
  profile. A runtime MUST NOT answer one shared in another context, and a
  front end shows it in that context only, saying it was shared with you or
  with the group.

## 4.17 Your Nodes

A person has one or more nodes; each group is read from one of them, and
new groups and the inbox go to the default node, the first (UN-RFC 0001).
A front end shows a node by name, in this order:

1. the name on the signed known-node list (UN-RFC 0010), `source`
   `known`;
2. otherwise the node's own `name` from its node information (UN-RFC
   0011), `source` `self`. Anyone can give a node any name, also one on
   the known-node list, so a front end MUST show it as the node's own
   claim (the runtime's `label` adds "(unlisted)");
3. otherwise the start of its onion address, `source` `none`.

The runtime asks a node not on the list for its name once, while
connecting, and keeps it in the vault, cleaned: one line, no control or
format characters, at most 64 characters. The full address is always
given beside the name, for a tooltip or to copy.

- `GET /api/nodes`: `{"nodes": [{"address", "name", "source", "label",
  "description", "operator", "default", "groups"}], "known": [...]}` -
  your nodes, the default first, with how many groups you follow are read
  from each, and in `known` the listed nodes you do not use yet, in the
  same form. `description` and `operator` are the known-node list's (or
  empty). With `?info=1` each node is also asked for its node information:
  `reachable` (true or false) and `info` (its answer, `{}` if it offers
  none, null if unreachable). That waits for the slowest node, at most a
  minute: a front end shows the list first and asks with `info=1` after.
- `POST /api/nodes` `{"action": "add" | "remove" | "default", "address":
  "..."}` adds a node, stops using one, or makes one the default (adding
  it if needed), and answers `GET /api/nodes` without `info`. A new node's
  groups are read at once, and new posts on it pushed. `remove` also
  answers `moved`, the followed groups now read from the default node;
  nothing is deleted on the node itself, and the last node cannot be
  removed (400). An address is an onion address (56 characters and
  `.onion`, with an optional `:port`) or `host:port`; anything else is
  400.

## 4.18 Recovery Words

An identity's 24 recovery words (UN-RFC 0050 section 4) are its key. The
runtime never keeps them: not in the vault, the state, a log or a file,
and it never saves or prints them by itself (UN-RFC 0050 section 4.3).
What a front end does with `page` - save it as a file, print it - is the
person's deliberate choice, behind that section's warnings.

- `POST /api/recovery/words` `{"passphrase", "identity"}` (`identity`
  optional, the default one): the vault passphrase again, even though the
  vault is open (UN-RFC 0050 section 4.2); 400 when it is wrong. Answers
  `{"identity", "fingerprint", "words", "check", "note", "not_a_wallet",
  "title", "page"}`: `check` the three positions (1-24) to ask back,
  `note` that closed groups do not come back, `not_a_wallet` the sentence
  to show with them, `page` the plain text for *Save as file* or *Print*.
- `POST /api/recovery/written` `{"identity"}`: the words were written down
  and checked. `POST /api/recovery/reminded` `{"identity"}`: the front end
  reminded the person, or they skipped at creation. State's
  `words_reminder` is true when to remind again: not written down, and not
  reminded within a week.
- `POST /api/recovery/check` `{"words"}`: whether the words can be read,
  for feedback while they are typed; works while locked, keeps nothing.
  `{"ok": true, "words": [...]}` (the full words; four letters are enough
  when typing) or `{"ok": false, "kind": "count" | "word" | "checksum",
  "error", "position"}`.
- `POST /api/recovery/restore` `{"words", "display", "node", "name"}`:
  puts the identity in the vault - as the first setup of a new vault
  (instead of `/api/setup`, and then `node` is needed), or beside the
  identities already there - makes it the default, reads its state, name
  and profile from the network, and starts the runtime. Answers
  `{"identity", "new", "fingerprint", "key", "label", "profile", "state",
  "closed_groups", "note"}`: `state` is `read`, `none` (nothing in the
  network: the default groups) or `unreachable`; `closed_groups` as below.
- `GET /api/recovery/closed-groups`: `{"groups": [{"group", "label",
  "owner", "mine"}], "note"}` - closed groups you follow whose secret the
  vault lacks (UN-RFC 0050 section 4.5).
- `POST /api/recovery/ask` `{"group", "note"}`: asks the group's owner, by
  private post to their inbox, to invite you again; answers
  `{"message_id"}`.

## 4.19 Copying to Another Device

Copying identities from one device to another (UN-RFC 0050 section 3)
takes the user on both devices, so the copy lives in the runtime while
they compare the check words. One copy at a time, offered or received.
What happens to an offer comes as an event (section 5): `{"event":
"copy", "role": "old" | "new", "state", "check_words", "error",
"added"}`.

- `POST /api/copy/offer` `{"identities", "group_secrets"}`: offer a copy
  of the vault's identities (all, or the names given) and, unless
  `group_secrets` is false, the closed groups' secrets. Answers `{"role":
  "old", "state": "waiting", "code", "qr", "expires", "check_words",
  "error", "added"}`: `code` to show as text, `qr` the text of the QR code
  (`unseenet-copy:1:...`), `expires` a Unix time. 400 when this device's
  Tor cannot open an onion service, or no meeting point answers. When the
  new device has connected, a `copy` event with `state` `check` and the
  `check_words` follows.
- `POST /api/copy/confirm` `{"match"}`: the user's answer. True sends the
  copy and answers when the new device has it (`state` `done`, `added` the
  names it added); false sends nothing (`cancelled`).
- `POST /api/copy/receive` `{"code", "node"}`: on the new device, the
  typed code or the scanned QR text. Answers `{"role": "new", "state":
  "check", "check_words"}` once connected; 400 for a wrong code or one
  nobody is waiting with. Also the first setup of a new vault (instead of
  `/api/setup`; `node` is then needed).
- `POST /api/copy/finish`: waits until the old device's user has confirmed
  the words, adds the copy to the vault, reads the state from the network
  and starts the runtime. Answers `{"added", "state"}` (`state` as in
  section 4.18); 400 when the old device stopped.
- `POST /api/copy/cancel`: stop the copy offered or being received.
  `GET /api/copy`: the copy in progress, `{"role": null}` if none.

## 4.20 Your Own Rules

The user's own rules for their feed and groups (UN-RFC 0051) run in the
client core, so every front end shows the same order and the same
"Why?". Without rules nothing in this section changes any other answer.

- `GET /api/rules`: `{"text", "on", "rules", "problems"}` - the rules as
  the user wrote them, whether they are used, how many rules are used,
  and `problems`, `[{"line", "message"}]`, the lines that are not
  (UN-RFC 0051 section 6); and `suggestion`, the commented rule set every
  client offers when the user has none - shown in full, used only if the
  user saves it (UN-RFC 0051 section 3); and `help`, the language in
  short, for a client to show beside its editor.
- `POST /api/rules` `{"text", "on"}`, either or both: keep `text` as the
  rules ("" removes them; 400 when longer than 2048 bytes), and turn them
  on or off - off keeps the text (UN-RFC 0051 section 3). Answers as
  `GET`, and a `groups` event follows (section 5).
- `POST /api/rules/check` `{"text"}`: `{"rules", "problems"}` for a text,
  keeping nothing - for an editor that checks as the user types.
- `POST /api/groups/{gid}/seen` `{"until"}`: everything in the group
  dated up to `until` (ISO 8601, with a time zone) has been seen - shown
  on the screen, not opened (UN-RFC 0044 section 4.5). Answers
  `{"seen_to"}`; it never moves back.
- `POST /api/threads` `{"id", "mark"}`: watch (`"watched"`) or ignore
  (`"ignored"`) the thread whose first post is `id`, or neither (`""`).

With rules on, the rows of a threaded group (section 4.3) and the
entries of the timeline (section 4.14) carry `score`, `actions` (any of
`fold`, `dim`, `highlight`, `mark read`), `hidden` and `why` (UN-RFC
0051 section 10); a threaded group's first rows also `thread_mark`. The
rows come in the order the rules give: threads ordered, replies never
reordered, and threads whose every post is hidden left out. A client
SHOULD NOT show a row with `hidden` true, and SHOULD show `why` when the
user asks why a row is where it is.

## 4.21 Spam Reports

Spam reports (UN-RFC 0045) are followed and applied in the client core,
so every front end hides the same posts for the same reasons.

- Every post in every answer carries `reported`: null, or `{"issuer",
  "label", "reason", "automatic", "kind", "report"}` when an issuer the
  user follows reports the post (`kind` `"post"`) or its author's key
  (`"key"`). The post keeps its place. A front end SHOULD show it as
  hidden in that place, with who and why (and "automatic" when set),
  one action from being shown, and SHOULD NOT hide it silently (UN-RFC
  0045 section 7.3). The user's own posts and their contacts' never
  carry it.
- `GET /api/settings` (section 4.8) also says `report_issuer`: whether
  the user has started a `reports@` group, so a front end can offer
  publishing a report without asking for more.
- `GET /api/reports`: `{"issuers", "reasons", "mine"}` - `issuers`,
  `[{"key", "label", "yours", "hierarchies", "on"}]`, every issuer the
  user follows or that a hierarchy of their groups names; `reasons`, the
  reasons a report can give; `mine`, the user as an issuer (`{"group",
  "policy", "contact", "automatic"}`), or null before they start.
- `POST /api/reports/follow` `{"key", "label", "on"}`: follow an issuer
  in every group (also turning one a hierarchy names back on), or with
  `"on": false` stop following it, also one a hierarchy names. Answers
  as `GET`; a `groups` event follows.
- `POST /api/reports/refresh`: read the followed issuers' reports now;
  `{"issuers", "reports"}`.
- `POST /api/groups/{gid}/show` `{"id"}`: show a post hidden by a report
  anyway, on this device.
- `POST /api/reports/start` `{"policy", "contact", "automatic"}`: start
  or change the user's `reports@` group (UN-RFC 0045 section 3), and
  their inbox if they have none. With `"separate": {"name", "display"}`
  the issuer is a new identity beside the user's in the vault, and the
  user's stays the one in use. An issuer copied into a vault from another
  device (UN-RFC 0050) is found by itself. Answers as `GET`.
- `POST /api/reports/publish` `{"posts", "keys", "note"}`: publish a
  report; `posts` `[{"id", "group", "reason"}]`, `keys` `[{"key",
  "reason", "days"}]` (`days` 1-365, 365 when left out). Answers at once
  `{"job"}`: the issuer's postage, and the first time its ripening, can
  take minutes; the job's events (section 5) give the report's Message-ID.
- `GET /api/reports/mine`: `{"reports": [{"id", "date", "note", "posts",
  "keys"}]}`, newest first; `POST /api/reports/withdraw` `{"id"}`
  withdraws one.
- A report someone sent the user (section 4.6) has `report` in its row,
  `{"id", "group", "author_key", "reason"}`: the post it names, so a front
  end can open it and, for an issuer, publish it.
- `POST /api/groups/{gid}/settings` (section 4.7) also takes
  `report_issuers`, the whole list of keys the group's readers follow by
  default (UN-RFC 0045 section 7.5, [] for none), and for an inbox
  `team_name` (UN-RFC 0047); `GET /api/groups/{gid}` gives both, the
  issuers as `{"key", "label"}`.
- `GET /api/reports/received`: `{"received": [{"message", "subject",
  "date", "id", "group", "author_key"}]}`, the reports others sent the
  user (section 4.6), to publish without the reporter (UN-RFC 0045
  section 7.4).
- `POST /api/reports/hierarchy` `{"hierarchy", "keys"}`: as its
  maintainer, the whole list of issuers the hierarchy's readers follow
  by default, at most 16 (UN-RFC 0045 section 7.1).

## 4.22 Team Inboxes

Team inboxes (UN-RFC 0047) are read with team keys kept in the vault; the
owner key is needed only to change who reads.

- `GET /api/teams`: `{"teams": [{"group", "name", "reader"}]}`, the team
  inboxes the user reads; `reader` is false once the owner removed their
  key (a front end offers to forget it). Each is read like any group
  (section 4.3) and shown as a mailbox of its own, never mixed into the
  user's inbox.
- A private post that hands the user a team key has `team_invite`
  (`{"group"}`); `POST /api/teams/accept` `{"id"}` checks it against the
  inbox's owner and readers and keeps the key: `{"group"}`.
  `POST /api/teams/forget` `{"group"}` removes a team key.
- `POST /api/private` takes `as_team` (a team inbox): written with the
  team key, on the inbox's behalf, answers going to that inbox. A message
  written so has `team` in its row, `{"group", "name", "verified"}`, and
  `who` is the team's name: a front end MUST NOT show it as a person.
- As the owner: `GET /api/teams/readers?group=` `{"group", "readers",
  "team_name"}`; `POST /api/teams/readers` `{"group", "add": <key>,
  "team_name"}` makes a team key and sends it to that person's inbox,
  `{"group", "remove": <team key>}` removes one. Both answer as `GET`.

## 4.23 Content Labels

Content labels (UN-RFC 0053) describe and never sanction. Every row has
`labels`: `null`, or `{"warnings": [{"warning", "by", "choice"}],
"topics": [...], "action"}` - the post's warnings (the author's tags,
the group's, labellers'; `by` names who gave each), its topics from
labellers the user follows for topics, and what to do: `show`, `blur`
(behind *Show anyway*) or `hide`, from the user's choices. A front end
follows `action` and never hides or blurs silently: it says which warning
and by whom. The user's own posts and their contacts' are always `show`.
Rows also have the author's `tags` (UN-RFC 0052), groups their `tags`.

- `GET /api/labels`: `{"labellers": [{"key", "label", "yours", "topics",
  "hierarchies", "groups", "on"}], "warnings": [{"warning", "label",
  "choice"}], "mine"}` - the labellers that count and where each is named,
  what the user does with each warning, and their own `labels@` channel.
- `POST /api/labels/follow` `{"key", "label", "topics"}`: follow a
  labeller in every group, its topics too if `topics`; `"follow": false`
  stops following, also one a hierarchy or group names.
- `POST /api/labels/warning` `{"warning", "choice"}`: `show`, `blur` or
  `hide` for that warning.
- `POST /api/labels/refresh`: read the labellers' channels now.
- `POST /api/labels/profile` `{"profile"}`: the age guide (UN-RFC 0053
  6.1) - `under-13`, `13-17` or `adult` - applied as the user's choices per
  warning; the profile itself is not kept. `GET /api/labels` lists them as
  `profiles`: `[{"id", "label", "choices"}]`.
- `POST /api/labels/start` `{"policy", "contact", "automatic", "topics"}`:
  start or change the user's `labels@` channel.
- `POST /api/labels/publish` `{"posts": [{"id", "group", "labels"}],
  "note"}`: answers at once `{"job"}`; `"labels": []` takes the user's
  earlier labels of a post back.
- `GET /api/groups/tag:WORD`: every post with the tag in the groups and
  feeds the user follows - the author's tags, the group's, and topics of
  labellers followed for topics - newest first, as a feed (`view` feed,
  `label` `#word`); writing goes to each post's own group.
- `POST /api/groups/{gid}/post` takes `tags`, the author's own (at most 8),
  and `POST /api/groups/{gid}/settings` the group's `tags` and
  `labellers` (UN-RFC 0053 section 5).

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
- `status` carries `idle` (section 4.1) when the runtime says it, so a
  front end can follow without asking the state again.

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

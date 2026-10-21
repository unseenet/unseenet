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
groups and their posts, writing, and an event stream. It also defines how
the API keeps everything else on the machine out.

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
end out of band, in one of two ways:

- on standard output, as one line:
  `UNSEENET-API 1 http://127.0.0.1:<port>/ <token>`; or
- in a file only the user can read (mode `0600`), next to the vault,
  named `<vault file>.api`, holding that same line, removed when the
  runtime stops.

A front end opened as a page by the runtime itself MAY get the token in
the URL fragment (`#t=<token>`), which browsers do not send to servers.

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
<iterations>, "next_at": <iterations or null>}` (UN-RFC 0025). `setup`
is true while the identity or the node is still missing.

## 4.2 Unlocking and Setting Up

- `POST /api/unlock` `{"passphrase": "..."}`: answers the state. A wrong
  passphrase is `400`.
- `POST /api/setup` `{"display": "...", "node": "..."}`: the first start
  of a new vault. It makes the identity and adds the node, then the
  runtime starts (UN-RFC 0025: a new key ripens in the background).

## 4.3 Groups

`GET /api/groups`:

```
{"groups": [<GroupInfo dict>, ...],
 "people": [{"id": "contact:<key>", "key": "...", "name": "...", "unread": 0}, ...],
 "inbox": {"id": "inbox@<fp>", "unread": 0},
 "for_you": {"replies": 0, "mentions": 0}}
```

`groups` are the groups the identity follows, in its order
(`Session.subscribed_groups()`), with their counts. `people` are its chats
(UN-RFC 0028 section 6.2). Besides real group IDs, two pseudo IDs work
wherever a group ID does: `contact:<key>` (the chat with one person) and
`for-you:` (replies and mentions from all groups).

`GET /api/groups/<id>`:

```
{"group": <GroupInfo dict>,
 "rows": [{"message": <Message dict>, "depth": 0, "read": true, "for_me": null}, ...]}
```

`rows` are in the order to show them (`Session.threads()`): threads
newest first for a group read as threads, every line in order for one
read as a chat. `for_me` is `"reply"`, `"mention"` or null.

- `POST /api/groups/<id>/read` `{"ids": [<Message-ID>, ...]}`: at most 500.
- `POST /api/groups/<id>/view` `{"view": "threads" | "chat" | null}`:
  null goes back to the owner's choice (UN-RFC 0008 section 3.1).
- `POST /api/subscribe` `{"id": "<group ID>", "on": true}`.
- `GET /api/browse?pattern=<wildmat>`: `{"groups": [<GroupInfo dict>, ...]}`,
  what the node lists.
- `POST /api/refresh`: fetch every group now.

## 4.4 Writing

- `POST /api/groups/<id>/post`
  `{"kind": "post" | "chat", "subject": "...", "body": "...", "references": [...]}`
  answers `{"job": "<job ID>"}` at once. A post needs a subject; a chat
  line has none (UN-RFC 0028).
- `POST /api/private`
  `{"key": "ed25519:...", "kind": "post" | "chat", "subject": "...", "body": "...", "reply_to": <Message-ID or null>}`
  answers `{"job": "<job ID>"}`.

Its progress comes as `job` events (section 5). The runtime asks about
portals (UN-RFC 0023 section 3.5) before it sends: a group with a portal
answers `400` with the warning until the post carries
`"publish_outside_tor": true`.

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
  and `reached`, `error` with `failed`.

A front end that connects late asks `GET /api/state` and the groups
again; events are not replayed.

# 6. Extensions

A runtime MAY offer more, under `/x/<name>/` (for example unseenet-gui's
owner tools or a bootable machine's Wi-Fi and power settings, `/x/gui/`),
with the same security rules. Paths under `/api/` are this document's.

# 7. Rationale

**Why HTTP and a WebSocket.** Every language and every browser speaks
them, so a front end can be a page, a native app or a script. A local
socket file would keep out other users without a token, but a browser
cannot open one.

**Why so little.** What every front end needs is small; what a graphical
client on a bootable machine needs (Wi-Fi, power, updates) is not for
everyone. Extensions keep the core subset stable.

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
- **Logs.** A runtime MUST NOT log the token, the passphrase or bodies of
  private posts.

# 9. Changes to Other Documents

None. UN-RFC 0043's web entrance serves the client to a browser over the
network and is not this API.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.

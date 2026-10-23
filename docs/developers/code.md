# The code

A map of the Python package `unseenet` (`src/unseenet/`): where each part
lives, and where new code goes. Every file opens with a docstring saying what
belongs in it - when in doubt, read the top of the file. The protocol itself
is in the [UN-RFCs](../spec/index.md); the code follows them, and a file names
the sections it implements.

## The layers

```
core/          the protocol: articles, keys, groups, postage - shared by node and client
client/        the client core: Session, the runtime, the local client API, the TUI
node/          the node: an ONNTP server that stores groups and passes articles on
cli/           the command line: `unseenet` (a client) and `unseenet-node` (a node)
```

`core` knows nothing of clients or nodes. `client` and `node` both build on
`core`, never on each other. Every client - the terminal client, the
graphical client (`unseenet-gui`), the web client, the command line, bots and
gateways - goes through `Session`, so they behave alike.

## core: the protocol

| File | What |
|---|---|
| `article.py` | the article: parsing, the canonical form, Message-IDs (UN-RFC 0002) |
| `crypto.py`, `encoding.py` | identities, signatures, encryption, group keys (UN-RFC 0003) |
| `groups.py` | Group IDs, manifests, closed-group encryption, posting rules (UN-RFC 0004) |
| `pow.py` | proof-of-work postage (UN-RFC 0006) |
| `ripening.py` | key ripening (UN-RFC 0025) |
| `vault.py` | the encrypted client vault (UN-RFC 0007) |
| `tor.py` | starting Tor, its control port, onion connections |
| `markup.py` | Markdown and emoji as a small, safe tree (UN-RFC 0031) |
| `profiles.py` | profiles, pictures, identicons (UN-RFC 0022) |
| `blobs.py` | files as blobs (UN-RFC 0027) |
| `pins.py`, `pages.py` | pinned posts and pages, the kinds of kept articles (UN-RFC 0033, 0035) |
| `reconcile.py` | set reconciliation of key-bound state (UN-RFC 0040) |
| `store/` | the node's store in SQLite - see below |
| `portals.py`, `gateways.py` | portals and the gateway directory (UN-RFC 0023, 0038) |
| `addresses.py` | `unseenet:` addresses: reading (also older forms) and writing (UN-RFC 0031 3.4.1) |
| `poster.py` | posting with no one at the keyboard: bots, gateways, scripts |

### core/store: the node's store

| File | What |
|---|---|
| `__init__.py` | the SQLite schema, and `Store` joined from the parts |
| `base.py` | opening the store, the history of Message-IDs seen |
| `articles.py` | storing, finding, deleting and expiring articles |
| `groups.py` | manifests, carried groups, state, epochs, removal |
| `keybound.py` | key-bound groups: lifetime and reconciliation |
| `kept.py` | kept articles: pins and pages |
| `blobs.py` | blob references, deletion, refusal, quotas |
| `withdrawals.py` | cancels and edits |
| `peers.py` | peer queues, pull and reconcile state |
| `stats.py` | numbers for the operator's monitor |

A new table goes in the schema in `__init__.py`, its code in the file of its area.

## client: the client core

| File | What |
|---|---|
| `session/` | `Session`, the client core - see below and [the reference](session.md) |
| `runtime.py` | `ClientRuntime`: start-up, refresh and push, the same for every client |
| `events.py` | the events a session reports |
| `threads.py`, `grouptree.py`, `groupfilter.py` | laying out a group, the group tree, search - the same in every client |
| `naming.py` | names of groups and identities in the client (UN-RFC 0018, 0019) |
| `headless.py` | a session for a service with only a key |
| `media.py` | what a file is from its content, and pictures saved again without their metadata |
| `localapi/` | the local client API (UN-RFC 0046) - see below and [its page](localapi.md) |
| `tui.py`, `richtext.py` | the terminal client |

### client/session: Session

| File | What |
|---|---|
| `__init__.py` | the shared types (`Message`, `GroupInfo`, `SessionError`, ...), and `Session` joined from the parts |
| `base.py` | the vault, identities, settings, events |
| `ripening.py` | key ripening |
| `nodes.py` | nodes, the connection, push, Tor |
| `labels.py` | how people and groups are shown: names and labels |
| `groups.py` | manifests, creating and changing groups, moderation, roles, portals |
| `private.py` | the inbox, private posts and chats, key-bound groups and renewal |
| `profiles.py` | profiles and pictures |
| `people.py` | contacts, ignoring, for you and mentions, notices, bots, reporting |
| `reading.py` | following, fetching, threads and views, the offline cache, read marks |
| `posting.py` | posting, postage, editing and withdrawing |
| `attachments.py` | files on posts: preparing and checking them (UN-RFC 0027) |
| `kept.py` | pinned posts and the pages of sites, as the nodes keep them (UN-RFC 0033, 0035) |
| `personal.py` | an identity's personal feed and site (UN-RFC 0029 section 2.1) |
| `following.py` | following feeds and people, the timeline (UN-RFC 0034 sections 6, 7) |

A new function goes in the file whose docstring says it belongs there; a new
area gets a file of its own, added to `Session` in `__init__.py`. Every public
function has a docstring - a test checks it.

### client/localapi: the local client API

`server.py` puts the API on HTTP and a WebSocket; `api/` is what answers, one
file per section of [UN-RFC 0046](../spec/un-rfc-0046.md): `state.py` (4.1),
`setup.py` (4.2), `groups.py` (4.3), `writing.py` (4.4, 4.5), `people.py`
(4.6), `running.py` (4.7), `identity.py` (4.8), `articles.py` (4.9) and
`events.py` (5). A new request goes in its section's file, with a route in
`server.py`.

## node: the node

| File | What |
|---|---|
| `server/` | `Node` and `Session` (one connection) - see below |
| `peering.py` | streaming articles to peers (UN-RFC 0005 section 5.2) |
| `pulling.py` | catching up from peers (UN-RFC 0017, 0040) |
| `blobfetch.py` | blobs following their article (UN-RFC 0027 section 6.3) |
| `stats.py` | what the node tells its operator |

### node/server

| `Node` | | `Session` (one connection) | |
|---|---|---|---|
| `node.py` | the node, watchers, node info, serving | `connection.py` | the command loop, CAPABILITIES |
| `accepting.py` | the accept pipeline: the order of the checks | `auth_commands.py` | AUTHINFO, XUN-PEER |
| `postage.py` | postage, key ripening | `lists_commands.py` | LIST, XUN-WATCH, node info |
| `manifests.py` | manifests, new and removed groups | `reading_commands.py` | GROUP, ARTICLE, OVER, HDR |
| `controls.py` | key updates, cancels | `peering_commands.py` | IHAVE, TAKETHIS, NEWNEWS, XUN-RECONCILE, XUN-MANIFESTS |
| `kept.py` | pins and pages | `posting_commands.py` | POST |
| `blobs.py` | blobs | `blob_commands.py` | BLOBPOST, BLOB |
| `blocks.py` | maintainers' blocks | | |
| `edits.py` | edits | | |
| `forwarding.py` | queueing for peers | | |

The rules for one kind of article go in its file; `accepting.py` only decides
their order. A new NNTP command is a `cmd_<name>` method in the commands file
of its area.

## cli: the command line

`node.py` is `unseenet-node`; the `unseenet` client's commands are by area in
`basics.py`, `groups.py`, `messages.py`, `network.py`, `services.py` and
`kept.py` (pins, pages, personal groups), `following.py` (profile, follow,
timeline, addresses), and
`main.py` holds the parser and which function each command runs.

## Around them

`known_nodes.py` and `hierarchies.py` (the project's lists), `names.py` and
`registrar.py` (names, UN-RFC 0019), `nntp.py` (the ONNTP client),
`portable.py`, `launcher.py`, `update.py` and `boot.py` (the portable and
bootable builds), `monitor.py` (`unseenet-monitor`).

## Tools for checking the code

- `pytest`: the test suite. `tests/test_docstrings.py` checks that every
  public `Session` function has a docstring.
- `tools/dev/check_globals.py <root> <package>...`: every global name a
  function in a package looks up exists in its file - catches what a split
  or a move can break where no test reaches.

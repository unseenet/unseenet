# Changelog

All notable changes to the Unseenet software are listed here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [semantic versioning](docs/development.md#versioning).
Protocol changes are made through the [UN-RFC series](rfc/), not here.

## [Unreleased]

### Protocol
- Draft UN-RFC 0017 (catching up by pull, and group state).
- Draft UN-RFC 0015 (transferring group ownership) and 0016 (peer
  authentication with node keys).
- Draft UN-RFC 0009 (inbox groups and local groups), 0011 (node
  information and operator contact) and 0012 (retention, archive nodes
  and history).

### Fixed
- Tor's SOCKS refusals when reaching an onion service (common right after
  Tor starts) are retried and reported with a readable reason, instead of
  failing with a "proxy" error.
- Key updates of closed groups no longer expire with the group's
  retention; after they did, a new node rejected every post in the group.

### Added
- First start offers the known nodes (the project's test nodes) to choose
  from, and adds the others as backups; "Another node" for any address.
- Portable builds for Windows, macOS (Apple silicon and Intel) and Linux
  with Tor inside, and an all-in-one USB zip; built, unpacked and
  self-tested by GitHub Actions. Tor comes from the Tor Project's Expert
  Bundle and is only used if its signature checks out. See
  docs/portable.md.
- Portable mode: vault and Tor state in `data/` beside the programs.
- Tor bridges (obfs4, Snowflake, or your own) for networks that block Tor:
  "Tor bridges" in the TUI, `unseenet bridges` on the command line.
- `unseenet --self-test`: checks a build and connects to the Tor network.
- Tests run on Windows and macOS as well as Linux.
- Catching up by pull (UN-RFC 0017): nodes pull from each peer at start
  and every hour (`pull`, `pull_interval`), so new nodes get the history
  and nodes that were down get what they missed. Works from any node, so
  a personal node can carry groups from public nodes.
- `NEWNEWS` lists each group's state (manifest, live key updates) first,
  and owner removals.
- Peering with node keys (UN-RFC 0016): every node has a key (printed at
  start, `unseenet-node --show-key`, in node information); peers are
  configured with `key = "ed25519:..."` instead of a shared password, and
  authenticate by signing a challenge bound to both keys.
  `require_peer_auth` now defaults to true; passwords still work, are
  compared in constant time, and log a warning.
- Several nodes in one client (`o`): add, remove and choose the default
  node. The same key everywhere; each group is read from the node that
  carries it, and from another of your nodes if that one stops carrying
  it or is down. Join links can add the group's node.
- TUI: About screen (F1) with links to the source and the documentation.
- Inbox groups: private messages sealed to the recipient and signed with a
  one-time key, with a verified sender inside. Every identity gets a
  personal inbox (`inbox@<fingerprint>`).
- Local groups that are never replicated between nodes.
- `LIST UNSEENET.NODEINFO` and an `[operator]` section in `node.toml`.
- TUI: `m` private message, `o` node information and "write to operator",
  private replies, inbox at the top of the group list.
- CLI: `group-create --type inbox --local`.
- TUI: groups shown as a tree by hierarchy (`dk.*`, `comp.*`, ...), both in
  the main view and when browsing the node's groups.
- TUI: every action is in the command palette (Ctrl+P), plus "Private
  messages" and "Mark group as read".
- Signatures: up to four lines below `-- `, per identity, with `{name}`,
  `{key}` and `{fp}`; not quoted in replies; shown dimmed (`s` in the TUI).
- UN-RFC 0002: informative section on signature and quoting conventions.

- Removing groups (UN-RFC 0013, draft): the owner removes a group from the
  whole network with a signed `rmgroup`; nodes delete it and keep a
  tombstone so it cannot return. Operators drop a group from their own
  node with `unseenet-node --drop-group` (reversible with `--undrop-group`).
- TUI: "Unsubscribe from group" and "Remove group from the network" in the
  command palette.
- Contacts: give a key a name of your own (`a`), shown as "Name ✓"
  everywhere; a Contacts folder with one conversation per person, both
  directions, ordered as sent and received. Copies of sent private
  messages are kept encrypted next to the vault.

- Chat (UN-RFC 0008, draft): chat view for any group or conversation
  (`v`), with an input line; owners can mark a group as a chat and enable
  fast delivery (no random forwarding delay). Push: `XUN-WATCH` on nodes,
  and the TUI keeps a second connection so new posts appear at once.
- Postage now follows the group and node minimums instead of a fixed
  20 bits, so cheap chat groups are actually faster to post in.
- Group rules (UN-RFC 0014, draft): a charter in the signed manifest,
  shown on first visit and after changes (`?`); owners edit title,
  description, rules, view and delivery from the TUI.

### Fixed
- TUI: an error in a background task (refreshing, fetching, saving) could
  close the whole program. Such errors are now shown as a message and
  written to `unseenet-tui-errors.log` next to the vault.
- TUI: the group list jumped back to the top on every refresh. The cursor
  and scroll position now stay where you left them.
- TUI: selecting a group that had just been removed could fail.
- TUI: creating a group with an invalid name closed the dialog and lost what
  was typed. Names are now checked as you type, with the reason shown, and
  the dialog stays open until the name is valid.

## [0.1.0] - 2026-10-15

First public release. Pre-alpha: expect breaking changes.

### Protocol
- Draft UN-RFC 0000-0007: process, architecture, article format,
  identities and cryptography, groups and closed groups, ONNTP transport
  and peering, proof-of-work postage, data at rest. Protocol version `1`.

### Node
- ONNTP server over a Tor onion service, with its own private Tor process.
- Validation of signatures, content-derived Message-IDs, postage and group
  rules; cancels; retention.
- Push replication to peers (MODE STREAM / CHECK / TAKETHIS) with optional
  peer authentication and random forwarding delay.
- Group carrying policies: `accept`, `trusted`, `manual`.
- `deploy/install-node.sh` and a systemd unit.

### Client
- `unseenet-tui`: groups, threaded posts, compose and reply, browse and
  subscribe, create groups of all four types, invitations to closed groups.
- Encrypted vault (Argon2id + XSalsa20-Poly1305) and an encrypted offline
  cache, so saved posts can be read without a connection.
- `unseenet`: command line client.

[Unreleased]: https://github.com/andlo/unseenet/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/andlo/unseenet/releases/tag/v0.1.0

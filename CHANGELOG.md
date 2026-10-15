# Changelog

All notable changes to the Unseenet software are listed here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [semantic versioning](docs/development.md#versioning).
Protocol changes are made through the [UN-RFC series](rfc/), not here.

## [Unreleased]

### Protocol
- Draft UN-RFC 0009 (inbox groups and local groups), 0011 (node
  information and operator contact) and 0012 (retention, archive nodes
  and history).

### Added
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

### Fixed
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

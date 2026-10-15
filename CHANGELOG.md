# Changelog

All notable changes to the Unseenet software are listed here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [semantic versioning](docs/development.md#versioning).
Protocol changes are made through the [UN-RFC series](rfc/), not here.

## [Unreleased]

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

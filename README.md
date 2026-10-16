<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="Unseenet" width="440">
  </picture>
</p>

**📖 Documentation: [unseenet.org](https://unseenet.org/)**

**Usenet, unseen.** A decentralized, encrypted discussion network in the
spirit of old Usenet and BBSes — groups and chats you can reach by
running one program from a USB stick, carried between independently run
nodes over Tor onion services.

> Status: **pre-alpha.** Nothing is stable yet, and it has not had a
> security review. Do not rely on it to protect anyone yet.

## The idea

In the old days, you connected to *your* news server. Your server
exchanged articles with other servers, and before long your post had
travelled around the world. Nobody owned Usenet. Anyone could run a
server. You could read it with any newsreader.

Unseenet brings that model back, with what we have learned since:

- **Easy access.** One program, no installation, no account, no public
  IP, no port forwarding. Put it on a USB stick and go.
- **Decentralized.** Anyone can run a node — on a Raspberry Pi, a
  homelab container, a VPS. Nodes replicate groups to each other the
  way Usenet servers did. No central server, no company.
- **Encrypted where it matters.** Closed groups are end-to-end
  encrypted; the nodes that carry them see only ciphertext. A stolen
  stick or a seized server reveals as little as possible.
- **Hidden.** Every node is a Tor onion service. Nobody needs to know
  where a node is, or who is reading.
- **Open protocol.** Specified in numbered RFC-style documents, so
  others can write their own nodes and clients — exactly like in the
  old days.

```
  you (USB stick)                 the network
  +-----------+     Tor     +--------+  Tor  +--------+
  | unseenet  | <---------> | node A | <---> | node B | <--->  ...
  |  client   |   ONNTP     +--------+       +--------+
  +-----------+                 ^                 ^
   encrypted vault              +---- node C -----+
```

Posts are signed, groups are owned by a key, spam costs a little
proof-of-work, and the wire protocol is a strict profile of NNTP. How it
all fits together: [Concepts](https://unseenet.org/concepts/).

## The specification

The protocol is defined in the **UN-RFC** series. The documents are the
authority; this code is just one implementation. Read them in
[`rfc/`](rfc/) or on [unseenet.org](https://unseenet.org/spec/). Want to
change the protocol or build something compatible? Start with
[UN-RFC 0000](rfc/un-rfc-0000.md).

## Getting started

| | |
|---|---|
| **Portable (Linux, macOS, Windows)** | Download a zip from the [releases](https://github.com/unseenet/unseenet/releases), unzip, start. Tor is included. [Guide](https://unseenet.org/portable/) |
| **Bootable (USB, SSD etc.)** | Unseenet in a text console, from memory. [Guide](https://unseenet.org/bootable/) |
| **Python** | `pipx install "unseenet[tui]"`, then `unseenet-tui` (needs Python 3.11+ and `tor`). [Using the client](https://unseenet.org/client/) |
| **Other newsreaders** | Read with tin, Thunderbird and friends. [Guide](https://unseenet.org/other-clients/) |
| **A node** | `curl -fsSL https://raw.githubusercontent.com/unseenet/unseenet/main/deploy/install-node.sh \| sudo bash` on Debian or Ubuntu, or [Docker](https://unseenet.org/node/docker/). [Guide](https://unseenet.org/node/install/) |

The project's own groups, `unseenet`, `unseenet.test` and
`unseenet.announce` (all `@ph5fc5hop5232qsz`), are on the test node
`f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion`. The
client subscribes you to them on first start. Test nodes may be reset at
any time while Unseenet is pre-alpha.

## Contributing

Ideas, criticism and code are welcome. Protocol changes go through the
UN-RFC process; code changes through ordinary pull requests. See
[Development](https://unseenet.org/development/) for architecture and
design decisions, the [milestones](https://github.com/unseenet/unseenet/milestones)
for what comes in the next releases, and the
[issues](https://github.com/unseenet/unseenet/issues) for everything else.

## License

- Code: [Apache License 2.0](LICENSE)
- Protocol specification (`rfc/`) and logo (`assets/`):
  [CC BY 4.0](rfc/LICENSE.md) — copy, quote and implement freely, with credit

Anyone may implement the protocol; no license is needed for that.

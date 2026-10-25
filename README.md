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

<p align="center">
  <img src="docs/img/demo.gif" alt="The Unseenet terminal client: unlocking the vault, reading a thread, replying, chatting and browsing groups" width="820">
</p>

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
all fits together: [How it works](https://unseenet.org/guide/).

## This repository

The heart of Unseenet: the protocol and the code every other part builds on.

| | Where | What |
|---|---|---|
| **The specification** | [`rfc/`](rfc/) | The **UN-RFC** series. The documents are the authority; this code is one implementation. Read them on [unseenet.org/spec](https://unseenet.org/spec/); to change the protocol or build something compatible, start with [UN-RFC 0000](rfc/un-rfc-0000.md). |
| **The core** | [`src/unseenet/core/`](src/unseenet/core/), [`client/session/`](src/unseenet/client/session/) | The library: articles, signing and keys, the vault, proof-of-work and key ripening, groups, profiles, pages, files; `Session`, which every client (CLI, TUI, the graphical client, bots, gateways) is built on; the local client API (`client/localapi/`). On PyPI as [`unseenet`](https://pypi.org/project/unseenet/). |
| **The node** | [`src/unseenet/node/`](src/unseenet/node/), [`deploy/`](deploy/), [`docker/`](docker/) | `unseenet-node`, the server that stores groups and peers with other nodes over Tor; the installer, systemd units and Docker image; `unseenet-monitor`, the node operator's terminal view; `unseenet-registrar` for names. |
| **The command-line client** | [`src/unseenet/cli/`](src/unseenet/cli/) | `unseenet`: everything the core can do, from a shell or a script - the client to show and test the core. |
| **The terminal client** | [`src/unseenet/client/tui.py`](src/unseenet/client/tui.py) | `unseenet-tui`, for now. It moves to [unseenet-tui](https://github.com/unseenet/unseenet-tui) (#548). |
| **Builds** | [`tools/build_portable.py`](tools/build_portable.py), [`tools/image/`](tools/image/) | The portable zips and the bootable image, for now. They move to unseenet-portable and unseenet-bootable (#549, #550); see [builds](#builds). |
| **The project** | [`tools/project/`](tools/project/), [`src/unseenet/*.json`](src/unseenet/) | The owner's scripts (no secrets), the known-node, entrance and hierarchy lists, the network health checks. |
| **Docs** | [`docs/`](docs/) | The pages about what this repository holds - the node, the local API, the developers' reference, and for now the clients and builds - gathered into unseenet.org by [unseenet-docs](https://github.com/unseenet/unseenet-docs) (#547). `tools/docs_check.sh` previews and checks them. |

### Getting started

| | |
|---|---|
| **Portable (Linux, macOS, Windows) · Terminal** | Download a zip from the [releases](https://github.com/unseenet/unseenet/releases), unzip, start. Tor is included. [Guide](https://unseenet.org/portable/) |
| **Bootable (USB, SSD etc.) · Terminal** | Unseenet in a text console, from memory. [Guide](https://unseenet.org/bootable/) |
| **Graphical client** | Unseenet in a window, Portable or Bootable: [unseenet-gui](https://github.com/unseenet/unseenet-gui). [Guide](https://unseenet.org/graphical/) |
| **Python** | `pipx install "unseenet[tui]"`, then `unseenet-tui` (needs Python 3.11+ and `tor`). [Using the client](https://unseenet.org/client/) |
| **Other newsreaders** | Read with tin, Thunderbird and friends. [Guide](https://unseenet.org/other-clients/) |
| **A node** | `curl -fsSL https://raw.githubusercontent.com/unseenet/unseenet/main/deploy/install-node.sh \| sudo bash` on Debian or Ubuntu, or [Docker](https://unseenet.org/node/docker/). [Guide](https://unseenet.org/node/install/) |

The project's own groups, `unseenet`, `unseenet.test` and
`unseenet.announce` (all `@ph5fc5hop5232qsz`), are on the test node
`f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion`. The
client subscribes you to them on first start. Test nodes may be reset at
any time while Unseenet is pre-alpha.

### Builds

Merging to `main` runs the tests, nothing more. The portable zips and the
bootable image are built **each night** when the software changed (the
[development build](https://github.com/unseenet/unseenet/releases/tag/dev)),
**by hand** from the Actions tab, and for **releases** (version tags). See
[Development](https://unseenet.org/development/#test-releases-and-development-builds).

## Part of Unseenet

Unseenet is made in several repositories, each released on its own:

| Repository | What it is |
|---|---|
| [unseenet](https://github.com/unseenet/unseenet) | The protocol (UN-RFCs), the core library, the node and the command-line client |
| [unseenet-tui](https://github.com/unseenet/unseenet-tui) | The terminal client (moving here from unseenet, unseenet#548) |
| [unseenet-gui](https://github.com/unseenet/unseenet-gui) | The graphical client - in a window, booted, or in a browser |
| [unseenet-portable](https://github.com/unseenet/unseenet-portable) | Builds the portable clients, Terminal and Graphical, with Tor inside (unseenet#549) |
| [unseenet-bootable](https://github.com/unseenet/unseenet-bootable) | Builds the bootable images, Terminal and Graphical, and later a node image (unseenet#550) |
| [unseenet-docs](https://github.com/unseenet/unseenet-docs) | The site [unseenet.org](https://unseenet.org), gathering the docs of every repository (unseenet#547) |
| [unseenet-entrance](https://github.com/unseenet/unseenet-entrance) | Web entrances: the graphical client in an ordinary browser |
| [unseenet-gateway](https://github.com/unseenet/unseenet-gateway) | Gateways to other networks: Usenet, Nostr, Matrix |
| [unseenet-bots](https://github.com/unseenet/unseenet-bots) | Bots that keep channels filled with current content |
| [unseenet-helpbot](https://github.com/unseenet/unseenet-helpbot) | The bot that answers questions in `unseenet.help` |
| [unseenet-stats](https://github.com/unseenet/unseenet-stats) | Statistics for the network |
| [unseenet-mcp](https://github.com/unseenet/unseenet-mcp) | An MCP server, so a language model can read and post as you (planning) |
| [unseenet-demo](https://github.com/unseenet/unseenet-demo) | Demo people, feeds and sites, made with the command-line client |

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

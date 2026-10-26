<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/unseenet/unseenet/main/assets/logo-dark.svg">
    <img src="https://raw.githubusercontent.com/unseenet/unseenet/main/assets/logo-light.svg" alt="Unseenet" width="360">
  </picture>
</p>

<h1 align="center">unseenet</h1>

<p align="center"><b>Usenet, unseen.</b><br>
A decentralized, encrypted discussion network over Tor onion services: the protocol, the core every client is built on, the node, and the command-line client.</p>

<p align="center">
  <a href="https://pypi.org/project/unseenet/"><img src="https://img.shields.io/pypi/v/unseenet?label=PyPI" alt="PyPI"></a>
  <a href="https://github.com/unseenet/unseenet/actions/workflows/tests.yml"><img src="https://github.com/unseenet/unseenet/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0"></a>
</p>

<p align="center">
  <img src="assets/overview.svg" alt="Clients reach nodes over Tor; nodes are onion services peering with each other; a web entrance lets a browser in, a gateway links other networks" width="880">
</p>

> **Pre-alpha.** Nothing is stable yet, and Unseenet has not had a security
> review. Do not rely on it to protect anyone yet.

**📖 Documentation: [unseenet.org](https://unseenet.org/)**

## What it is

In the old days, you connected to *your* news server. Your server
exchanged articles with other servers, and before long your post had
travelled around the world. Nobody owned Usenet. Anyone could run a
server. You could read it with any newsreader.

Unseenet brings that model back, with what we have learned since:

- **Decentralized.** Anyone can run a node - on a Raspberry Pi, a homelab
  container, a free cloud VM. Nodes replicate groups to each other the way
  Usenet servers did. No central server, no company, nobody to remove a
  group or sort what you see.
- **Hidden.** Every node is a Tor onion service: it has no address outside
  Tor, needs no public IP or port forwarding, and nobody needs to know where
  it is or who is reading.
- **Signed and encrypted.** Every post is signed by its author's key, so
  nobody else can forge or change it. Closed groups and private posts are
  end-to-end encrypted; the nodes that carry them see only ciphertext.
- **Hard to spam.** Posting costs a little proof-of-work, and new keys must
  ripen before they post cheaply - no central moderation needed.
- **Everything people know from today's networks**, on one technique:
  threaded discussions, chats, private posts, feeds you follow, sites and
  pages, pictures and reactions - all articles in groups, carried the same
  way.
- **An open protocol.** A strict profile of NNTP, specified in numbered
  RFC-style documents, so others can write their own nodes and clients -
  exactly like in the old days.

How it all fits together, in plain prose: [How it works](https://unseenet.org/guide/),
and what is hidden from whom: [the threat model](https://unseenet.org/guide/threats/).

## The protocol

The protocol is defined in the **UN-RFC** series, in [`rfc/`](rfc/) and on
[unseenet.org/spec](https://unseenet.org/spec/). The documents are the
authority; this code is one implementation. To change the protocol or build
something compatible, start with [UN-RFC 0000](rfc/un-rfc-0000.md) and
[0001](rfc/un-rfc-0001.md). All are drafts while Unseenet is pre-alpha.

| Area | UN-RFCs |
|---|---|
| **The basis** - how the network is built, what a post is, keys, the wire, postage, the vault | [0000 Process](rfc/un-rfc-0000.md) · [0001 Architecture](rfc/un-rfc-0001.md) · [0002 Article format](rfc/un-rfc-0002.md) · [0003 Identities and crypto](rfc/un-rfc-0003.md) · [0005 ONNTP transport](rfc/un-rfc-0005.md) · [0006 Proof-of-work postage](rfc/un-rfc-0006.md) · [0007 Data at rest](rfc/un-rfc-0007.md) |
| **Groups** - owned by a key, their rules, hierarchies, inboxes | [0004 Groups](rfc/un-rfc-0004.md) · [0013 Removing groups](rfc/un-rfc-0013.md) · [0014 Group rules](rfc/un-rfc-0014.md) · [0015 Ownership transfer](rfc/un-rfc-0015.md) · [0018 Hierarchies](rfc/un-rfc-0018.md) · [0029 Key-bound groups](rfc/un-rfc-0029.md) · [0040 Key-bound groups at scale](rfc/un-rfc-0040.md) · [0041 Many manifests at once](rfc/un-rfc-0041.md) · [0047 Team inboxes](rfc/un-rfc-0047.md) |
| **What people write** - posts and chats, files, Markdown, feeds, sites, reactions | [0008 Chat and low latency](rfc/un-rfc-0008.md) · [0027 Attachments](rfc/un-rfc-0027.md) · [0028 Chats and posts](rfc/un-rfc-0028.md) · [0030 Comments in channels](rfc/un-rfc-0030.md) · [0031 Markdown and emoji](rfc/un-rfc-0031.md) · [0032 Mention notices](rfc/un-rfc-0032.md) · [0033 Pinned posts](rfc/un-rfc-0033.md) · [0034 Feeds and following](rfc/un-rfc-0034.md) · [0035 Pages and sites](rfc/un-rfc-0035.md) · [0042 Editing posts](rfc/un-rfc-0042.md) · [0048 Reactions](rfc/un-rfc-0048.md) |
| **People and keys** - names, profiles, key ripening, standing, your state | [0009 Inbox and local groups](rfc/un-rfc-0009.md) · [0019 Names for identities](rfc/un-rfc-0019.md) · [0022 Profiles](rfc/un-rfc-0022.md) · [0025 Key ripening](rfc/un-rfc-0025.md) · [0036 Attestations](rfc/un-rfc-0036.md) · [0044 Your state in the network](rfc/un-rfc-0044.md) · [0045 Spam reports](rfc/un-rfc-0045.md) |
| **Nodes** - finding them, peering, keeping, the project's lists | [0010 Known nodes](rfc/un-rfc-0010.md) · [0011 Node information](rfc/un-rfc-0011.md) · [0012 Retention and archives](rfc/un-rfc-0012.md) · [0016 Peer keys](rfc/un-rfc-0016.md) · [0017 Catch-up by pull](rfc/un-rfc-0017.md) · [0020 Lists from inside the network](rfc/un-rfc-0020.md) · [0021 Listed nodes must be connected](rfc/un-rfc-0021.md) |
| **The way out** - gateways to other networks, web entrances | [0023 Gateways](rfc/un-rfc-0023.md) · [0024 Usenet gateways](rfc/un-rfc-0024.md) · [0026 Nostr gateways](rfc/un-rfc-0026.md) · [0037 Matrix gateways](rfc/un-rfc-0037.md) · [0038 Gateway cooperation](rfc/un-rfc-0038.md) · [0043 Web entrances](rfc/un-rfc-0043.md) |
| **Clients** - the API every front end is built on | [0046 The local client API](rfc/un-rfc-0046.md) |

## This repository

The heart of Unseenet: the protocol and the code every other part builds on.

| | Where | What |
|---|---|---|
| **The specification** | [`rfc/`](rfc/) | The UN-RFCs above. |
| **The core** | [`src/unseenet/core/`](src/unseenet/core/), [`client/`](src/unseenet/client/) | The library: articles, signing and keys, the vault, postage and key ripening, groups, profiles, pages, files; `Session`, which every client, bot and gateway is built on; the local client API (`client/localapi/`). On PyPI as [`unseenet`](https://pypi.org/project/unseenet/). |
| **The node** | [`src/unseenet/node/`](src/unseenet/node/), [`deploy/`](deploy/), [`docker/`](docker/) | `unseenet-node`, which stores groups and peers with other nodes over Tor; its installer, systemd units and Docker image; `unseenet-monitor`, the operator's view; `unseenet-registrar` for names. |
| **The command-line client** | [`src/unseenet/cli/`](src/unseenet/cli/) | `unseenet`: everything the core can do, from a shell or a script. |
| **The project** | [`tools/project/`](tools/project/), [`src/unseenet/*.json`](src/unseenet/) | The owner's scripts (no secrets), the known-node, entrance and hierarchy lists, the network health checks. |
| **Docs** | [`docs/`](docs/) | The pages about the node, the CLI, the local API and the developers' reference, gathered into unseenet.org by [unseenet-docs](https://github.com/unseenet/unseenet-docs). |

The build tools are in their own repositories:
[unseenet-portable](https://github.com/unseenet/unseenet-portable) for the
portable builds, [unseenet-bootable](https://github.com/unseenet/unseenet-bootable)
for the bootable images.

## Get it

| | |
|---|---|
| **Use Unseenet** | The [terminal client](https://github.com/unseenet/unseenet-tui) or the [graphical client](https://github.com/unseenet/unseenet-gui), [portable](https://github.com/unseenet/unseenet-portable) with Tor inside, [bootable](https://github.com/unseenet/unseenet-bootable) from a stick, or in a browser through a [web entrance](https://github.com/unseenet/unseenet-entrance). Start here: [Getting started](https://unseenet.org/). |
| **Run a node** | `curl -fsSL https://raw.githubusercontent.com/unseenet/unseenet/main/deploy/install-node.sh \| sudo bash` on Debian or Ubuntu, or [Docker](https://unseenet.org/node/docker/). [Guide](https://unseenet.org/node/install/) |
| **The core and the CLI** | `pipx install unseenet` (Python 3.11+ and `tor`), then `unseenet --help`. Build on it: [Write a client](https://unseenet.org/developers/). |
| **Other newsreaders** | Read the open groups with tin, Thunderbird and friends: [Other newsreaders](https://unseenet.org/other-clients/). |

The project's own groups, `unseenet`, `unseenet.help` and
`unseenet.announce` (all `@ph5fc5hop5232qsz`), are on the project's nodes; the
clients subscribe you on first start.

## How it works

A client keeps its keys in an encrypted vault and talks to a node over Tor
(ONNTP, UN-RFC 0005). It signs every article and pays its postage; the node
checks both, stores the article and passes it to the nodes it peers with,
without knowing who wrote it or where it came in. Groups are owned by a key
whose signed manifest says who may post and how the group is shown; closed
groups and inboxes carry only ciphertext. Everything else - chats, feeds,
sites, reactions, profiles - is articles in groups too.

Read it chapter by chapter: [How it works](https://unseenet.org/guide/).

## Develop

```bash
pip install -e ".[dev]"
pytest -q                   # nodes on localhost, no Tor
tools/docs_check.sh serve   # this repository's docs pages
```

Protocol changes go through the UN-RFC process (an issue first, then a
draft); code changes through ordinary pull requests. See
[Development](https://unseenet.org/development/) for the architecture and the
design decisions, the [milestones](https://github.com/unseenet/unseenet/milestones)
for what comes next, and the [issues](https://github.com/unseenet/unseenet/issues)
for everything else.

## Versions and releases

Semantic versioning, pre-1.0: a minor version (0.5 → 0.6) may change the
protocol, and nodes are updated first. Tags `vX.Y.Z` on `main`; the release
workflow checks the tag against `__version__` and [CHANGELOG.md](CHANGELOG.md),
publishes to [PyPI](https://pypi.org/project/unseenet/) and announces the
release in `unseenet.announce`. The newest minor version gets security and bug
fixes until the next ([SECURITY.md](SECURITY.md)). Clients and services
number their own releases and say which core they need.

## Part of Unseenet

| Repository | What it is |
|---|---|
| [unseenet](https://github.com/unseenet/unseenet) | The protocol (UN-RFCs), the core library, the node and the command-line client |
| [unseenet-tui](https://github.com/unseenet/unseenet-tui) | The terminal client |
| [unseenet-gui](https://github.com/unseenet/unseenet-gui) | The graphical client - in a window, booted, or in a browser |
| [unseenet-portable](https://github.com/unseenet/unseenet-portable) | Builds the portable clients, Terminal and Graphical, with Tor inside |
| [unseenet-bootable](https://github.com/unseenet/unseenet-bootable) | Builds the bootable images, Terminal and Graphical |
| [unseenet-docs](https://github.com/unseenet/unseenet-docs) | The site [unseenet.org](https://unseenet.org) |
| [unseenet-entrance](https://github.com/unseenet/unseenet-entrance) | Web entrances: the graphical client in an ordinary browser |
| [unseenet-gateway](https://github.com/unseenet/unseenet-gateway) | Gateways to other networks: Usenet, Nostr, Matrix |
| [unseenet-bots](https://github.com/unseenet/unseenet-bots) | Bots that keep channels filled with current content |
| [unseenet-helpbot](https://github.com/unseenet/unseenet-helpbot) | The bot that answers questions in `unseenet.help` |
| [unseenet-stats](https://github.com/unseenet/unseenet-stats) | Statistics for the network |
| [unseenet-mcp](https://github.com/unseenet/unseenet-mcp) | An MCP server, so a language model can read and post as you (planning) |
| [unseenet-demo](https://github.com/unseenet/unseenet-demo) | Demo people, feeds and sites, made with the command-line client |

## License

- Code: [Apache License 2.0](LICENSE)
- Protocol specification (`rfc/`) and logo (`assets/`):
  [CC BY 4.0](rfc/LICENSE.md) - copy, quote and implement freely, with credit

Anyone may implement the protocol; no license is needed for that.

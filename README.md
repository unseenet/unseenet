<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="Unseenet" width="440">
  </picture>
</p>

**📖 Documentation: [andlo.github.io/unseenet](https://andlo.github.io/unseenet/)**

**Usenet, unseen.** A decentralized, encrypted discussion network in the
spirit of old Usenet and BBSes — groups and chats you can reach by
running one program from a USB stick, carried between independently run
nodes over Tor onion services.

> Status: **pre-alpha / design phase.** The protocol is being written
> down in the [UN-RFC series](rfc/). The Python code here is a first
> working skeleton of it. Nothing is stable yet, and it has not had a
> security review. Do not rely on it to protect anyone yet.

---

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
  way Usenet servers did. There is no central server and no company.
- **Encrypted where it matters.** Closed groups are end-to-end
  encrypted. The nodes that carry them see only ciphertext.
- **Hard to seize.** The client keeps everything in one encrypted
  vault. Nodes never hold group keys. A stolen stick or a seized server
  reveals as little as possible.
- **Hidden.** Every node is a Tor onion service. Nobody needs to know
  where a node is, or who is reading.
- **Open protocol.** Specified in numbered RFC-style documents, so
  others can write their own nodes and clients — exactly like in the
  old days.

## How it works

```
  you (USB stick)                 the network
  +-----------+     Tor     +--------+  Tor  +--------+
  | unseenet  | <---------> | node A | <---> | node B | <--->  ...
  |  client   |   ONNTP     +--------+       +--------+
  +-----------+                 ^                 ^
   encrypted vault              +---- node C -----+
```

- **Articles** are signed with the author's key. Their Message-ID is a
  hash of their content, so they cannot be forged or altered in transit.
- **Groups** are owned. A group's name includes a fingerprint of its
  owner's key (`dk.snak@ab3k5x7qwe2rtz4m`), so nobody can hijack it, and
  its settings live in a signed *manifest*.
- **Group types** are chosen by the owner:

  | Type        | Read         | Post                              | Encrypted |
  |-------------|--------------|-----------------------------------|-----------|
  | `open`      | anyone       | anyone                            | no        |
  | `moderated` | anyone       | moderators, or with approval      | no        |
  | `channel`   | anyone       | owner and chosen posters          | no        |
  | `closed`    | members only | members only                      | yes       |

- **Spam** is priced, not policed: every post carries a small
  proof-of-work ("postage"), a fraction of a second for a person, costly
  in bulk.
- **Three authorities, no rulers.** Group owners decide who may post in
  their group. Node operators decide which groups and peers they carry.
  Readers decide what they see.
- **Text only.** No binaries. Articles are at most 64 KiB. That keeps
  nodes small and their operators out of trouble.
- **Standard tools.** The wire protocol, ONNTP, is a strict profile of
  NNTP. Classic newsreaders can talk to a node.

## The specification

The protocol is defined in the **UN-RFC** series. The documents are the
authority; this code is just one implementation.

| No. | Title |
|-----|-------|
| [0000](rfc/un-rfc-0000.md) | The Unseenet Request for Comments Process |
| [0001](rfc/un-rfc-0001.md) | Architecture and Terminology |
| [0002](rfc/un-rfc-0002.md) | Article Format |
| [0003](rfc/un-rfc-0003.md) | Identities, Keys and Cryptographic Primitives |
| [0004](rfc/un-rfc-0004.md) | Groups, Manifests and Access Control |
| [0005](rfc/un-rfc-0005.md) | ONNTP: Transport and Peering over Onion Services |
| [0006](rfc/un-rfc-0006.md) | Proof-of-Work Postage |
| [0007](rfc/un-rfc-0007.md) | Protecting Data at Rest |

Want to change the protocol or build something compatible? Read
[UN-RFC 0000](rfc/un-rfc-0000.md) for how.

## Trying it

Requires Python 3.11+ and the `tor` binary (`dnf install tor` / `apt install tor`).

### The client

```bash
git clone https://github.com/andlo/unseenet
cd unseenet
pip install -e ".[tui]"
unseenet-tui
```

On first start you choose a passphrase for your vault, a display name, and
the node to connect to (its `.onion` address). Then:

| Key | |
|-----|---|
| `g` | browse the node's groups and subscribe |
| `n` / `r` | new post / reply (Ctrl+S sends) |
| `c` | create a group (open, moderated, channel or closed) |
| `k` | show your key, so a group owner can invite you |
| `i` | invite someone to a closed group you own |
| `j` | join a group by ID or `unseenet:join` link |
| `F5` | refresh (also happens every 30 seconds) |

Everything is kept in `unseenet.vault`, encrypted, next to where you run it.
There is also a plain command line client, `unseenet --help`.

### A node

On Debian or Ubuntu (a Proxmox LXC or a Raspberry Pi is plenty):

```bash
curl -fsSL https://raw.githubusercontent.com/andlo/unseenet/main/deploy/install-node.sh | sudo bash
```

It installs Tor and the node as a systemd service and prints the node's
`.onion` address. The full guide - configuration, peering, backup,
security and troubleshooting - is in the
[documentation](https://andlo.github.io/unseenet/node/install/). To peer with a friend's node, add a `[[peer]]` section
to `/home/unseenet/node.toml` on both nodes (same `password`, each using
the other's `name` and address) and restart with
`systemctl restart unseenet-node`.

For development, a node can run without Tor:
`unseenet-node --no-tor --data /tmp/node --listen 127.0.0.1:1119`.

## Talk about Unseenet - on Unseenet

Two open groups are carried by the project's test nodes:

| Group | For |
|-------|-----|
| `unseenet@ph5fc5hop5232qsz` | The project: protocol, software, ideas, questions |
| `unseenet.test@ph5fc5hop5232qsz` | Test posts - say hello, try replies |

Both are owned by the project key
`ed25519:det5dxevwbk36eds2indrzlazyri3fq3bgdzw6kx4ems3o267sya`.
Connect to the test node
`f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion`,
press `j` in the TUI and paste a group ID (or `g` to browse).
The test nodes may be reset at any time while Unseenet is pre-alpha.

## Roadmap

- [x] Protocol drafts UN-RFC 0000–0007
- [x] Article signing, content-derived Message-IDs, postage
- [x] Manifests, four group types, moderation approvals, cancels
- [x] Closed groups: epochs, member keys, sealed envelopes, E2E encryption
- [x] Node: ONNTP server, validation, streaming feeds to peers
- [x] Tor: own process, onion service via control port, SOCKS
- [x] Client: encrypted vault, command line
- [x] First real test: two nodes peering over Tor
- [x] TUI client (first version): groups, threads, posting, closed groups, invites
- [x] Node install script and systemd service
- [ ] Pull catch-up between nodes (NEWNEWS)
- [ ] Chat view in the TUI
- [ ] Portable builds with bundled Tor for USB (Linux, Windows, macOS)
- [ ] Low-latency chat delivery (UN-RFC 0008)
- [ ] Moderation submission queue (UN-RFC 0009)
- [ ] Node discovery (UN-RFC 0010)
- [ ] Independent security review
- [ ] A second, independent implementation

## Contributing

Ideas, criticism and code are welcome. Protocol changes go through the
UN-RFC process; code changes through ordinary pull requests. See
[docs/development.md](docs/development.md) for architecture and design
decisions.

## På dansk

Unseenet er et decentralt og krypteret diskussionsnet i stil med det
gamle Usenet og BBS'erne. Du kører én klient, gerne fra en USB-pind,
kobler dig på en node over Tor, og noderne udveksler grupper med
hinanden. Åbne grupper er som det gamle Usenet; lukkede grupper er
end-to-end-krypterede, så noderne kun ser støj. Protokollen beskrives i
RFC-lignende dokumenter, så alle kan lave kompatible noder og klienter.

## License

- Code: [Apache License 2.0](LICENSE)
- Protocol specification (`rfc/`) and logo (`assets/`):
  [CC BY 4.0](rfc/LICENSE.md) — copy, quote and implement freely, with credit

Anyone may implement the protocol; no license is needed for that.

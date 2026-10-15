<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="Unseenet" width="440">
  </picture>
</p>

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

Requires Python 3.11+ and, for real use, the `tor` binary.

```bash
git clone https://github.com/andlo/unseenet
cd unseenet
pip install -e .

# Run a node (starts its own Tor and prints its .onion address)
unseenet-node --data node-data

# ... or locally without Tor, for development
unseenet-node --no-tor --data node-data --listen 127.0.0.1:1119
```

Using the client (everything is stored in `unseenet.vault`, encrypted
with your passphrase):

```bash
unseenet id-new me --display "Andreas"
unseenet node-add xyz...abc.onion          # or 127.0.0.1:1119 locally
unseenet groups
unseenet group-create dk.snak --title "Dansk snak"
unseenet post dk.snak@<fingerprint> -s "Hello" --body "First post!"
unseenet read dk.snak@<fingerprint>

# A closed group, and an invitation
unseenet group-create family --type closed
unseenet invite family@<fingerprint> ed25519:<their key>
```

## Roadmap

- [x] Protocol drafts UN-RFC 0000–0007
- [x] Article signing, content-derived Message-IDs, postage
- [x] Manifests, four group types, moderation approvals, cancels
- [x] Closed groups: epochs, member keys, sealed envelopes, E2E encryption
- [x] Node: ONNTP server, validation, streaming feeds to peers
- [x] Tor: own process, onion service via control port, SOCKS
- [x] Client: encrypted vault, command line
- [ ] Pull catch-up between nodes (NEWNEWS) and persistent read state
- [ ] TUI client (Textual) with threads and chats
- [ ] Portable builds with bundled Tor for USB (Linux, Windows, macOS)
- [ ] Low-latency chat delivery (UN-RFC 0008)
- [ ] Moderation submission queue (UN-RFC 0009)
- [ ] Node discovery (UN-RFC 0010)
- [ ] Independent security review
- [ ] A second, independent implementation

## Contributing

Ideas, criticism and code are welcome. Protocol changes go through the
UN-RFC process; code changes through ordinary pull requests. See
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for architecture and design
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

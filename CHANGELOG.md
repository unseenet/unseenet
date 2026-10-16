# Changelog

All notable changes to the Unseenet software are listed here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [semantic versioning](docs/development.md#versioning).
Protocol changes are made through the [UN-RFC series](rfc/), not here.

## [Unreleased]

### Added
- Screenshots of the client in docs/client.md, made by
  `tools/docs_screenshots.py` from a local node with made-up content. (#57)
- Names in the client (UN-RFC 0018 section 8, UN-RFC 0019 sections 5.2, 6.1
  and 8). It reads the root list, the hierarchy lists (including the new
  `unseenet.checkgroups`) and the registrar's group in the background.
  Groups are shown without their fingerprint where the name cannot be
  mistaken, with a warning in the group browser where it can. People are
  shown as your petname, else `@domain` or `@name`, else `Name~abcd`.
  `@` claims and renews names and shows the ones you hold; your posts in
  public groups carry your certificate once a week per group.
- `src/unseenet/checkgroups.json`: the project's list of `unseenet.*`
  groups, posted to `unseenet.checkgroups` by `tools/announce.py
  checkgroups` and the announce workflow.
- `tools/project/create_groups.py` also brings an existing group's title,
  description, rules and `min_pow` up to date with a new manifest, keeping its
  posters and other fields, so `unseenet`, `unseenet.test` and the other
  groups made before the script get their rules (UN-RFC 0014). (#46)
- Data groups (UN-RFC 0008 section 3.1.1): a group whose manifest says
  `"view": "data"` carries lists and certificates for programs, not posts
  for people. The client marks it `¤` and leaves it out when you browse for
  groups to join; the project's node list, root list, names and checkgroups
  are known as data groups from the start. `tools/project/create_groups.py`
  gives the project's data groups that view.
- The command-line client can remove groups you own from the network:
  `unseenet group-remove GROUP_ID ...` (UN-RFC 0013). It finds the owning
  identity in the vault, refuses groups you do not own and your personal
  inbox, and asks you to type `remove` unless you add `--yes`.
  `unseenet groups --mine` lists only the groups your identities own. (#42)
- `unseenet-registrar`: a registrar for names of identities such as
  `@lorensen` (UN-RFC 0019). It runs as several replicas on separate
  machines that make the same decisions without talking to each other, so
  names keep working when one machine is gone. `unseenet.names` shares the
  formats with the client. See "Running a registrar replica" in the docs.
  (#27, #38)
- `tools/project/`: the scripts the maintainer runs with the project key, to
  change its vault's passphrase, create the project's groups and set up the
  registrar. They ask for the passphrase in the terminal only.
- The project's root list of hierarchies (UN-RFC 0018) is kept in
  `src/unseenet/hierarchies.json`, checked by the tests, and posted to
  `unseenet.hierarchies` when it changes and every month, together with
  the node list. The client does not use it yet. (#25)
- Development builds: every change to the code is built and self-tested,
  and the zips replace the pre-release
  [Development build](https://github.com/unseenet/unseenet/releases/tag/dev),
  with versions like `0.2.1.dev3`. Test releases (`0.2.1a1`) go to PyPI and
  GitHub as pre-releases. (#12)
- Icons for each group in both group lists: `≡` posts, `»` chat, `√`
  moderated, `►` channel, `∩` closed, `@` inbox, `⌂` local. They and the
  client's other symbols are from the basic character set every terminal
  font has, so they show in the classic Windows console too. (#14)
- Read a post on the whole screen: Enter (or a second click). There, r
  replies, m writes privately, n and p go to the next and previous post,
  Space pages down and reads on, Esc goes back. (#16)
- In the group list, Space subscribes and unsubscribes; with the mouse,
  only a click on `[ ]` does, so a click on the line just shows the
  group. (#17)
- The footer shows only the shortcuts that work where you are (Invite only
  in closed groups you own, New post only where you may post, ...). In chat
  view, Esc leaves the input line so the letters are shortcuts again, and
  Enter goes back to writing. (#18)
- `unseenet-monitor`: a program of its own that shows how a node is doing -
  traffic in the last hour, peers, storage, Tor, warnings and the last log
  lines. It reads the node's new local stats interface (`monitor.sock` in
  the data directory, never over Tor; counters only, nothing about who
  reads what), which other tools can use too. `install-node.sh` sets it up
  as `unseenet-monitor`. See docs/node/monitor.md. (#20)
- A bootable image, `unseenet-<version>-x86_64.img.xz`: Alpine Linux from
  memory with a boot menu (client, node, monitor, Wi-Fi, keyboard, clock),
  for BIOS and UEFI; the same FAT partition is a portable stick on a running
  computer, sharing `data/`. Built and booted in QEMU by CI, where its
  self-test must pass with Tor connecting. See docs/bootable.md. (#19)
- On the Linux console the client, the monitor and the boot menu draw
  borders the console's font has.
- A Docker image for the node, `ghcr.io/unseenet/node` (amd64, arm64): the
  node, the monitor and Tor; runs as a normal user, works with a read-only
  root file system; the passphrase as a Docker secret; `node.toml` written
  from the environment on the first start. `:dev` follows main, releases
  get `:<version>` and `:latest`; signed with cosign. See
  docs/node/docker.md and deploy/docker-compose.yml. (#22)
- Issue forms for the bootable stick and the Docker image.

### Fixed
- The tests pass on macOS and Windows again: the stats test makes its Unix
  socket under a short path, and the monitor test waits for a refused
  connection, which is slow on Windows. The node now says clearly when the
  monitor socket's path is too long for the system (104 bytes on macOS)
  instead of failing with `AF_UNIX path too long`. (#33)
- The client checks a group's manifest itself before it keeps it: it must
  be signed by the owner in the group ID, be for that group, keep the type,
  owner and locality, and be newer. A hostile node could otherwise have
  served a manifest signed by its own key, for example adding itself to the
  posters of `unseenet.nodes` or `unseenet.names` (UN-RFC 0004 section 4).
  (#41)
- The node's onion key file could be read by other users on the machine
  (it is sealed with the passphrase, but should be the node's alone).
- After picking another group or a refresh while an answer was still
  arriving over Tor, the connection to the node got out of step, and every
  later command failed ("invalid literal for int()") until a restart. An
  interrupted connection is now closed and a new one opened. (#9)
- Closing the group list with OK crashed the client ("ScreenStackError"):
  one press closed the dialog twice. (#10)
- The group list marks inboxes you do not own, such as a node operator's
  contact inbox, and Enter explains how to write to them instead of
  subscribing to messages only their owner can read. (#11)
- Private messages you sent are shown in Private messages ("You → name"),
  not only in conversations with contacts; before, a message to a key you
  pasted or to a node operator could not be seen again. (#15)

## [0.2.0] - 2026-10-16

First release with portable builds: unzip, start, done - on Windows, macOS
and Linux, from a USB stick if you like. Pre-alpha: expect breaking changes.

### Protocol
- Draft UN-RFC 0010 (lists of known nodes).
- Draft UN-RFC 0017 (catching up by pull, and group state).
- Draft UN-RFC 0015 (transferring group ownership) and 0016 (peer
  authentication with node keys).
- Draft UN-RFC 0009 (inbox groups and local groups), 0011 (node
  information and operator contact) and 0012 (retention, archive nodes
  and history).

### Fixed
- The client started one Tor per connection when several connected at once
  (each node and the live-update connections). The extra ones died on the
  shared data directory, but first overwrote its control-port file, so the
  client could end up using a Tor that was gone ("WinError 64" on Windows).
  The session now starts exactly one Tor, and replaces it if it has died.
  (#3)
- Browsing groups no longer lists other people's inboxes, which only their
  owner can read. (#5)
- Tor's SOCKS refusals when reaching an onion service (common right after
  Tor starts) are retried and reported with a readable reason, instead of
  failing with a "proxy" error.
- Key updates of closed groups no longer expire with the group's
  retention; after they did, a new node rejected every post in the group.

### Added
- A new client is subscribed to the project's groups (`unseenet`,
  `unseenet.announce`, `unseenet.test`) once, and a new identity gets a
  default signature with the display name and key. (#4)
- Browsing groups describes the highlighted group below the list: title,
  type, number of posts, owner, nodes and the first line of its rules,
  read from the group's signed manifest without subscribing. (#6)
- Your nodes, adding a node and the first start describe the highlighted
  node: description, operator, address and policy. (#6)
- Issue forms for the client, the node, the protocol, ideas and the
  documentation, with type and area labels, and `SECURITY.md` with private
  vulnerability reporting.
- Node requests must prove that the requester runs the node: the operator
  signs a challenge with `unseenet-node --sign`. Listed nodes are checked
  daily over Tor; unreachable for 3 days gets a note, 10 days removes them.
- "Add my node" issue form: a check reaches the node over Tor and compares
  its node key; the `accepted` label adds it to the list, posts the list to
  `unseenet.nodes`, and closes the issue.
- Known nodes (UN-RFC 0010, draft): one list in `src/unseenet/nodes.json`;
  the client ships with it and reads the newest signed list from the
  channel `unseenet.nodes` over Tor. "Add a node" offers the known nodes.
- Project channels `unseenet.announce` (releases, news) and
  `unseenet.nodes`, posted to by GitHub Actions over Tor
  (`tools/announce.py`, `announce.yml`) with a poster key the project key
  can revoke.
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

### Changed
- Dialogs with lists fill the window, buttons stay visible at the bottom
  of every dialog in small terminals, and long hints wrap. The group list
  closes with OK. An invalid group name is shown under the name field
  instead of in a message that covered the buttons. (#6)
- The project moved to the `unseenet` organization:
  https://github.com/unseenet/unseenet, and the documentation to
  https://unseenet.org (the old addresses redirect). (#7)

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

[Unreleased]: https://github.com/unseenet/unseenet/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/unseenet/unseenet/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/unseenet/unseenet/releases/tag/v0.1.0

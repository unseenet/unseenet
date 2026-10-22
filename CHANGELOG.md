# Changelog

All notable changes to the Unseenet software are listed here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [semantic versioning](docs/development.md#versioning).
Protocol changes are made through the [UN-RFC series](rfc/), not here.

## [Unreleased]

## [0.4.1] - 2026-10-22

A fix for clients and services; nodes can stay on 0.4.0.

### Fixed

- A client or service that started while its node could not be reached
  (Tor not up yet, the node restarting) never ripened its key in the
  background until it was restarted, so its first post waited minutes for
  it. It now asks the node again with the reconnect backoff, and a node
  that says `"-"` again every hour (#314).
- `tools/project/ripen_keys.py` also ripens the GitHub poster and the
  registrar's inbox key, which the owner vault keeps beside its identities
  (#313).

### Changed

- The gateway repository is now
  [unseenet/unseenet-gateway](https://github.com/unseenet/unseenet-gateway)
  (the old address redirects).

## [0.4.0] - 2026-10-22

**Key ripening (UN-RFC 0025): every node and client must be updated.** A
new key now does a few minutes of work, once, before nodes take its posts;
that is what keeps throwaway keys from spamming. Nodes from 0.4.0 refuse
articles without `Key-Ripening` from keys that have not ripened. 0.4
clients only send the header to nodes that ask for it (`UNSEENET-MINRIPE`),
so they work with 0.3 nodes during the change-over; once a node runs 0.4,
clients from before 0.4.0 can no longer post there. Pre-alpha: there is no
compatibility code beyond that.

- **People:** the first post of a new identity waits while its key ripens
  (7-11 minutes on a laptop, longer on old ones); both clients show how far
  it is. It happens once per identity, and goes on in the background to
  level 4, which lowers the postage a key pays.
- **Node operators:** nodes need `chiavdf` (in the container and the
  bootable images; `pip install chiavdf` elsewhere). `min_ripe` in
  `node.toml` says what a node asks for: `0` (the default) or higher, or
  `"-"` for none. With `"-"` keys that have not ripened still pay the
  unripe surcharge (+6 bits, UN-RFC 0025 section 5): a group at the default
  20 bits costs 26 bits a post for them.
- **Bots, gateways and other services:** ripen each key once at setup -
  `unseenet ripen --key-file KEY --to 0 --node NODE --publish`, or
  `unseenet-gateway ripen --group-key` - and keep its chain file
  (`<key file>.state.json`, public). A key ripened and published once is
  taken over anywhere else instead of ripening again.
- **The browser client** (through a web entrance) can read but not post on
  0.4 nodes until it can ripen in the browser (unseenet-gui#31).

### Added

- Key ripening (UN-RFC 0025): Wesolowski VDF chains in `ripe@` groups, the
  `Key-Ripening` header, levels 0-4 with postage surcharges from +6 bits to
  -2, and private posts' senders checked against their chain
  (`private_min_ripe`). `unseenet ripen` ripens a key from its key file or
  from the public key alone, on any machine (#121, #278, #285, #292).
- A session takes over its key's chain from the key's own `ripe@` group
  when that is further than its own: the same key on another machine, a
  vault copy, a reinstalled service or CI never ripens again (#308).
- Every portable build proves in its self-test that it can ripen (a short
  proof made and checked); the Intel Mac builds get `chiavdf` built from
  source, and the Windows builds the DLLs it loads at run time (#306).
- The client core every client shares (#139): threads, views and chat
  lines (`Session.threads`, `view_of`, `send_chat`), groups as every client
  lists them (`subscribed_groups`, `group_info`), a stable dict form of
  messages and groups (`to_dict`), typed events (`Session.on`), and
  `ClientRuntime` for startup, refresh, push, maintenance and ripening.
- The local client API (UN-RFC 0046, `unseenet.client.localapi`,
  `unseenet serve`): HTTP and a WebSocket on 127.0.0.1 with a per-start
  token, for a front end in any language or a bot (service mode with
  `--key-file`). Posts come as a safe render tree, so no front end turns
  post text into HTML. unseenet-gui now runs on it (#300-#305).
- Bots are marked next to their posts, and "Hide bots" leaves them out;
  clients read the authors' profiles in one batch (#163, #307).
- Changing the vault's passphrase (Ctrl+P in the terminal client;
  `Vault.change_passphrase`); copies of the vault elsewhere keep the old
  one (#281, #282).
- `tools/project/ripen_keys.py`: ripen and publish the keys in the owner
  vault.
- Nodes limit how many clients they serve at once (`max_clients` under
  `[limits]`; `"auto"`, the default, follows the open-file limit). A full
  node answers a new client with `400` and the client tries another; peers
  always get in. The monitor shows the limit, and the service file and the
  container raise the open-file limit to 65536 (#296, #310).

### Changed

- Everything that posts goes through `Session` - the clients, the bots'
  `Poster`, the project tools, the gateway, the help bot and the web
  entrance's release tool - so ripening, the header and postage are one
  piece of code (#287, #292).
- `Session.post` takes `extra` headers and `from_name`, for programs.
- Clients reconnect after a random wait that doubles up to five minutes
  (UN-RFC 0043 section 4.4), so a node that comes back is not hit by every
  client at once, and new users start on a random known node instead of
  the first in the list (#297, #311).

**All nodes must be updated** (step 4 of #217). Nodes now leave
key-bound groups out of their listings, so a node from before 0.4.0 can no
longer catch up on inboxes and profiles from an updated one, and is judged
incomplete by the daily check.

### Fixed

- A connection closed for being idle no longer logs "Unhandled exception
  in client_connected_cb" with a traceback.

### Added

- Clients say when a newer release is ready (the terminal client in a
  notice, the graphical client in the status bar, with an Update button on
  a stick or portable folder). They learn it from `unseenet.releases`,
  where each release's signed `SHA256SUMS.txt` is posted - by CI for
  development builds, by `sign_release.py` for releases (#264).
- `unseenet update` finds the newest signed checksums on GitHub *and* in
  the network, and takes the zip from GitHub or any mirror that has it -
  web entrances can mirror the releases - over Tor. Only a zip that
  matches the signed checksum is used (#264).
- The project channel `unseenet.releases`, where new versions of the web
  client are posted with the SHA-256 of every file, for the web app and
  for entrances to update from (UN-RFC 0043 sections 7.2 and 7.3).
  `tools/project/share_poster.py` gives unseenet-entrance's CI the
  GitHub poster key, so it can post them.

### Changed

- A new identity's inbox lives 60 days until the identity is used, not two
  years (#270, UN-RFC 0029 section 4.1): it is in use from the third day it
  is opened, or at the first post, chat, contact, group or profile, and then
  renewed for the full lifetime. Someone who opened the client once to look
  around is gone from the nodes after about 90 days. Every client now renews
  key-bound groups when it opens (`Session.ensure_inbox`); the graphical
  client did not before.

- Key-bound groups (`inbox@`, `profile@`, `avatar@`, `names@`) are no
  longer listed: not in `LIST ACTIVE` or `LIST NEWSGROUPS`, and not in
  part 1 of `NEWNEWS` (UN-RFC 0040 sections 3 and 5). They are still
  reached by Group ID, and part 2 of `NEWNEWS` still has what arrived in
  them; nodes keep them in step with `XUN-RECONCILE`. Listings stay the
  size of the ordinary groups, not of the number of people.
- Manifests of key-bound groups have a size limit: 16 KiB for `inbox@`,
  10 KiB for `profile@`, 12 KiB for `avatar@`, 64 KiB for `names@`
  (UN-RFC 0040 section 9; refused with `441 size`). That is about 100
  bans in an inbox; every manifest in the network today is far below.
- The daily node check also compares each node's key-bound groups with
  the listed node that has the most (UN-RFC 0040 section 7): a node must
  advertise `UNSEENET-RECONCILE`, and may lack at most 0.1% of them, or
  100 - counting only what it lacked the day before too.
- The terminal client no longer says your inbox is "(not on your nodes)"
  because it is not listed.
- Node health no longer counts key-bound groups (`inbox@`, `profile@`,
  `avatar@`, `names@`) when it decides whether a listed node is complete,
  first step of #217 (UN-RFC 0040 section 7). Nodes that still list them
  and nodes that don't are judged alike, so the later change that takes
  them out of `LIST` does not make updated nodes look incomplete.

### Added

- Edit your own posts and chat lines (UN-RFC 0042, #37). An edit is a
  new article with `Supersedes` naming every earlier version (at most
  32). Nodes check that it is the same author's, in the same group, of
  the same kind and place in its thread, withdraw the earlier versions as
  a cancel would, and refuse versions that arrive after their edit. A
  channel thread's comments still close from its first version's date.
  Private posts cannot be edited yet (#248). The client checks every edit
  itself, shows the newest version in the first one's place marked
  "(edited 21:58)" with replies to any version under it, keeps an edited
  post read if you had read it, and withdrawing an edited post drops its
  earlier versions too. In the terminal client `e` edits the selected
  post, or in a chat your last line, and warns that people may have read
  the earlier version; mention notices go only to newly mentioned
  people. Core: `Session.edit`, `Session.may_edit`, `resolve_edits`.

- Clients know before you write whether you may, and say why (#181):
  `Session.write_permission(group_id, reply_to=None, kind="post")`
  returns a `Permission(allowed, reason, code)` from the cached manifest -
  the kinds a group takes, the ban list, maintainers' blocks, type and
  posters, closed-group membership, and comments in channels with their
  `comment_days`. `may_post`/`may_reply` are thin wrappers around it. In
  the terminal client the chat line is unavailable, with the reason as
  its placeholder, where a chat line would be refused; New post and
  Reply hide where they would be refused and give the reason when used
  anyway; a channel post whose comments have closed says "Comments
  closed". The node still has the last word.
- Search and filter the group list (#13). In the group browser (`g`)
  just typing, or `/`, searches; in your own list `/` does. Words match
  a group's name, title and description; `type:chat`, `type:open`,
  `type:moderated`, `type:channel`, `type:closed`, `type:local`,
  `owner:me`, `subscribed`/`-subscribed` and wildmats like `dk.*`
  narrow it. Esc clears the search first. The search runs in the client,
  so the node learns nothing about what you look for; for `type:` the
  client reads the manifests of the listed groups it lacks in a few
  `XUN-MANIFESTS` requests (UN-RFC 0041), checked like any manifest, and
  never reads whole groups for it on older nodes. Core:
  `unseenet.client.groupfilter`, `Session.filter_groups`,
  `Session.group_manifests`, for the web client too.
- `XUN-MANIFESTS` (UN-RFC 0041, #218): nodes return the current
  manifests of up to 256 groups in one answer and advertise
  `UNSEENET-MANIFESTS 256`; an answer carries at most 1 MiB of articles,
  the rest is answered `431` and asked for again. Unauthenticated
  readers get 60 requests a minute. The client reads profiles and
  pictures this way where the node has it, and with `GROUP`/`HDR`/
  `ARTICLE` where it does not. Opening a profile in the TUI now reads the
  profiles of all authors shown in one go (UN-RFC 0022 section 9.2), so
  a busy group's 500 authors take two requests instead of some 1500
  round trips, and the node cannot tell whose profile was opened.
  Cached Message-IDs are not sent (section 3.3). Pulling fetches a
  missing key-bound manifest from a peer with it (0041 section 4.3).
  Core: `Client.manifests`, `Client.manifests_all`,
  `Session.fetch_manifests`, `Session.prefetch_profiles`.
- Nodes answer `XUN-RECONCILE` and advertise `UNSEENET-RECONCILE 1`
  (UN-RFC 0040 section 4, second step of #217): two nodes compare the
  key-bound manifests they hold by range fingerprints, at a cost that
  follows the differences, not the number of groups (100 000 against
  100 000 with 100 missing: three rounds). The store keeps the key-bound
  state as an index with running sums per key prefix, kept up to date as
  manifests arrive, are renewed, expire or are removed, and built once
  from existing data on first start. Readers may use it too, one
  exchange (64 rounds) per connection. Nothing uses it yet: pulling
  reconciles in the next step. Core: `unseenet.core.reconcile`
  (`answer`, `reconcile`), `Store.kb_count_sum`, `Store.kb_items`,
  `Client.reconcile`.
- Pulling reconciles key-bound state before `NEWNEWS` (UN-RFC 0040
  section 6, third step of #217): on the first pull from a peer, after a
  pause of more than 7 days, once a day at a random time, and soon after
  a peer offered an article whose key-bound group's manifest we lack. What
  we lack is fetched first; what the peer lacks is queued for its feeder.
  A new node catching up with 100 000 items needs 9 rounds and never asks
  for more than about 16 000 listed items at once.
  - An article in a key-bound group whose manifest the node does not hold
    is no longer refused at once: when pulled, the node fetches the
    group's manifests from the same peer and takes the article; when
    pushed, it answers "try again later" (431/436) for up to six hours and
    reconciles with that peer at its next pull.
  - Core: `Node.offer`, `Store.reconcile_due`, `Store.set_reconciled`;
    `core.reconcile.reconcile` starts with a fingerprint, lists only where
    the peer has few items, and returns what it found with
    `complete=False` instead of failing at `max_rounds`.
- Profiles and group rules can be Markdown (#211, UN-RFC 0022 section
  4.1 and 0014 section 2.1, amended): the new optional `about_type` and
  `rules_type` fields take a post's Content-Type, and the text gets the
  post subset of UN-RFC 0031 without images (manifests cannot hold blobs).
  Readers that don't know the fields show the text as typed, so it is
  compatible both ways. The terminal client renders both with the post
  renderer, the profile in a scroll of its own, and its profile, create
  and edit dialogs have a *Markdown* box (on for new text when you write
  posts in Markdown). Core: `markup.manifest_text`, `markup.text_type_for`,
  `make_profile(markdown=)`, `Profile.about_type`, `Manifest.rules_type`.
- The client can use a Tor that is already running instead of starting
  its own, so it works in Tails (#140). On Tails it uses Tails' Tor by
  itself; elsewhere choose with Ctrl+P → *Tor: which Tor*,
  `unseenet cli tor 127.0.0.1:9050`, or `UNSEENET_TOR_SOCKS`. Each node
  gets its own circuit (a SOCKS username per node), and if that Tor does
  not answer the client says so rather than starting its own. Core:
  `existing_tor`, `Socks` and `check_socks` in `unseenet.core.tor`, used by
  every client through `Session`.
- The vault is locked while a program has it open (#141): a second
  program - say the graphical client next to the terminal client - is
  told "This vault is already open in another Unseenet program" instead
  of quietly overwriting the first one's changes (and keys of closed
  groups). The lock is the OS's, so a crash leaves nothing locked; on file
  systems without locks (FAT on macOS) a `pid host` lock file stands in.
  In the core (`Vault.open`, new `Vault.close`), so it covers every client.
- The group list is a tree: under `alt.*` the groups are shown without
  `alt.` (`.news.wikipedia`), and a part of a name that two or more groups
  share is a folder that folds (`.history` with `.egypt` and `.denmark`).
  A part only one group has stays in its name, and a folder holding only
  one folder is joined with it (`.usenet.comp`). The full name is still
  shown when a group is open, in search and as the web client's tooltip.
  Folders start folded unless the open group is in them; hierarchies start
  open. Core: `unseenet.client.grouptree`, used by the terminal and the
  web client.

- Docs: pages on the web client (portable and bootable), gateways to other
  networks, getting help (`unseenet.help` and the help bot), and the
  project's bots; People.

- A help group, `unseenet.help`, which new clients (terminal and web)
  follow from the start, so newcomers know where to ask. The help bot
  (unseenet/unseenet-helpbot) answers there from the docs. Vaults that
  already exist are not changed. (#189)

- Profiles (UN-RFC 0022): an identity can publish a public profile -
  about, languages, links, a bot mark - in its key-bound group
  `profile@<fp>`, and a small picture in `avatar@<fp>`. Every key has an
  identicon. (#155)
  - Terminal client: Ctrl+P *Your profile* (with the warnings of section
    9.1) and *Profile of this author* (identicon, about, languages,
    links as stated; hide a profile).
  - Core: `core.profiles` (profile and picture objects, identicons);
    `Session.publish_profile`, `profile_of` (cached a day),
    `publish_picture`, `picture_of`. Choosing and re-encoding a picture
    comes with attachments (0.5.0).
  - Nodes: `profiles` (default `accept`, also when `new_groups` is
    closed) and `avatars` (default `refuse`) in `node.toml` and the node
    information; invalid or misplaced profiles and pictures are refused.
- Key-bound groups expire unless renewed (UN-RFC 0029): personal
  inboxes, sub-name revocation lists (`names@`) and, later, profiles and
  pictures. Their manifests carry `expires`, at most two years ahead.
  (#160)
  - Clients renew them without asking, all of an identity's groups
    together, at a random moment within 30 days once they are about
    six months old (at once if expiry is near).
  - Nodes stop listing, offering and accepting posts in an expired
    group (`441 group`) and remove it 30 days later. A renewal brings
    it back, also on nodes that take no new groups.
  - Sending to an inbox that has expired says only that the receiver
    has no inbox you can reach.
  - **Nodes and clients must be updated together:** updated nodes
    refuse new key-bound manifests without `expires`. Inboxes created
    before this keep working, and the owner's updated client renews
    them the first time it runs.
- Markdown and emoji (UN-RFC 0031, draft): posts and private posts are
  Markdown by default (`Content-Type: text/markdown; ...; variant=unseenet`),
  a small safe subset; chat lines a lighter one. No raw HTML, nothing loaded
  from outside, images only from attachments, links show their address.
  Emoji as Unicode or as gemoji shortcodes (`:tada:`). The terminal client
  renders it; Ctrl+P *Write plain text* turns it off. Core: `core.markup`,
  shared by every client. New dependency: `markdown-it-py`. (#153)
- Chats and posts (UN-RFC 0028, draft): every message says whether it
  is a chat line or a post (with a subject), in groups and in
  private messages. Messages from older clients count as posts. (#152)
  - Private messages: the terminal client shows private posts under *Private posts*
    (previously *Private messages*) and chats under *Chats* (previously
    *Contacts*), one conversation per person, contact or not; `m`
    writes a post, `c` opens your contacts (chat, write a post, rename,
    remove), and the command palette has *Chat with someone*.
    The kind is sealed inside the message.
  - Groups: a chat line no longer gets its first line as a made-up
    subject. Shown as threads, chat lines are marked » and kept
    together; shown as a chat, posts stand out with their subject.
  - A group owner chooses what a group takes: posts and chat lines,
    posts only, or chat lines only (manifest field `kinds`). Nodes
    refuse the other kind in open, moderated and channel groups.
    **Nodes must be updated** before groups use `kinds`.
- Comments in channels (UN-RFC 0030, draft): a channel's owner can let
  anyone comment on posts while only the owner and posters start
  threads, optionally for a number of days after each post (manifest
  fields `comments` and `comment_days`; *Edit group* in the terminal
  client, `--comments` and `--comment-days` for `group-create`). A
  node holds a comment that arrives before its thread for up to an hour
  and answers the sender "try again later" (`431` after `TAKETHIS`,
  `436` after `IHAVE`, `441 later` after `POST`). (#162)
  **Nodes must be updated** before channels open for comments.
- A headless posting API for bots, gateways and scripts,
  `unseenet.core.poster`: a key from a file, a vault or the environment
  without prompting; its own Tor or a running one; postage, kinds and
  "try later" handled; reading back to avoid double posts. See
  *Writing a bot* in the docs. `tools/announce.py` now uses it. (#166)
- `#group` references: write `#dk.snak.marsvin` to point to a group, and
  press `#` on a post to go there - a group you follow opens, one you do
  not is shown and you are asked before subscribing. The core has
  `group_refs()` and `Session.find_group_ref()` for other clients.
  References are underlined and can be clicked. (#172)
- Mention notices (UN-RFC 0032): naming someone by a certified name in a
  post also tells them in their inbox, so they see it in a group they do
  not follow - at most 5 per post, a few minutes later, never for closed
  groups or private posts. The compose window shows who is told and can
  say no; the command palette turns sending or showing them off.
  Received notices are checked against the post and show in *For you*.
  Core: `Session.mentioned()`, `send_mention_notices()`,
  `check_notices()`, `notices()`. (#171)
- Mention notices for a post in a moderated group are built when it is
  submitted and go to the moderators with it; the approving moderator's
  client posts them, so the author need not be online (UN-RFC 0032,
  section 4.3). (#171)

### Changed

- Replies and mentions are counted apart: a group shows e.g.
  `dk.snak (5) ◄1 ♦2`, *For you* the same for all groups, and the
  notification says whether it is a reply or a post naming you. The core
  has `Session.for_you_counts()` for other clients. (#170)


### Fixed

- The client checked the owner of a profile or picture manifest read
  from a node, but not its signature, so a hostile node could have shown
  a changed profile under the right key. Every manifest read with
  `fetch_manifest` is now checked as a whole (UN-RFC 0041 section 3.1),
  and a node serving an older serial no longer replaces a newer cached
  profile.

## [0.3.1] - 2026-10-18

Updates from an alpha to a release, and a stable release that sticks can
find. The first release from the `release/0.3` branch: fixes only.

### Fixed
- A stable release is now GitHub's "latest" release. Before 1.0 every
  release was marked as a pre-release, so `releases/latest` did not exist
  and Portable and Bootable on the stable channel found no signed version
  to update to. (v0.3.0 was corrected by hand on GitHub.)
- Portable and Bootable update from an alpha or its development build
  (0.3.0a2.dev10, say) to the release (0.3.0). They took all three to be
  the same version and said they were up to date. A stick that already
  runs such a version can update with `python3 -m unseenet.update --media
  /media/usb --channel stable --force` from the Shell in the menu.

## [0.3.0] - 2026-10-18

Names, moderation and updates. People and groups get names you can
remember and trust - registered names, domain names and names under a
name like `sonia@lorensen` - from a registrar that keeps working when one
machine is gone. Group owners, moderators and hierarchy maintainers get
tools against abuse: moderation queues, bans, hierarchy blocks, reports,
withdrawing posts. Portable and Bootable update themselves. The project
now runs four nodes, two of them stable. Also: newsreader support
(`OVER`), Bootable (USB, SSD etc.), a Docker image and a node monitor.
Pre-alpha: expect breaking changes.

**Support:** 0.3.x gets security and bug fixes until 0.4.0 is released;
after that, upgrade. There is no compatibility guarantee before 1.0
(see [SECURITY.md](SECURITY.md#supported-versions)).

### Protocol
- Draft UN-RFC 0018 (hierarchies and authority over group names), with
  hierarchy blocks (section 5.4), and UN-RFC 0019 (names for identities),
  with registrar replicas, reserved names and names under a name.
- Draft UN-RFC 0020 (keeping the project's lists from inside the
  network) and UN-RFC 0021 (listed nodes must be connected).
- UN-RFC 0004: banned keys (section 5.1), closing an epoch when a member
  is removed (sections 6.2, 6.5), and what clients do with cancels
  (section 7): check a cancel before acting on it, drop the target from
  the cache, remember cancels for posts not yet seen, and say that
  withdrawing is best effort. Control articles cannot be cancelled. (#35)
- UN-RFC 0009 section 3: submissions reach every moderator.
- UN-RFC 0008 section 3.1.1: data groups, for lists and certificates that
  programs read.
- UN-RFC 0011: `honours_blocks` and excluded groups in node information.
- UN-RFC 0022 (profiles for identities).
- Draft UN-RFC 0023 (gateways to other networks) and UN-RFC 0024 (Usenet
  gateways). The root list reserves hierarchies for gateways: `usenet`,
  `fido`, `matrix`, `irc`, `xmpp`, `fedi`, `nostr`, `bsky`, `discord`,
  `telegram`, `slack`, `reddit`. The gateway software is a separate
  project, https://github.com/unseenet/gateway.

### Added
- Replies and mentions: posts answering yours are marked ◄, posts naming
  one of your certified names ♦, and **For you** at the top of the group
  list gathers the unread ones from all groups; groups show their count
  and the client tells you when new ones arrive. Worked out locally;
  nothing is sent. (#109)
- **Update** in the menu of Bootable (USB, SSD etc.): fetch the newest release over
  Tor (or a development build, or an update zip on the stick) and replace
  the system files, keeping `data/`. Releases get an
  `unseenet-<version>-x86_64-update.zip` and a signed `SHA256SUMS.txt.sig`:
  releases signed with the project key (`tools/project/sign_release.py`),
  development builds with a separate release key in CI. Also
  `python -m unseenet.update`. (#68)
- **Update Unseenet** in the client's command palette and `unseenet update`
  for Portable (Linux, macOS, Windows), also on a USB stick: the USB
  zip or the platform's zip, checked the same way, `data/` kept. Running
  programs on Windows are moved aside and removed at the next start. (#68)
- Listed nodes must be connected (UN-RFC 0021): the daily health check
  posts a small canary to each listed node in `unseenet.canary` and reads
  the next day where they arrived. A node whose canary does not reach more
  than half of the others, that misses theirs, or that does not carry what
  most of them carry, gets a note after 3 days and is taken off the list
  after 10. The "Add my node" check sends a canary each way first. (#87)
- `excludes` in `[node]`: groups the node does not carry by choice. They
  are refused, and published in the node information with every dropped
  group; clients show them under **About this node**. (#87)
- Per-peer `accept` in `[[peer]]`: which groups the node takes from that
  peer, pushed or pulled. `groups` only ever limited what is sent, so a
  peering "for dk.* only" can now be held on both sides. (#86)
- Names under a name (UN-RFC 0019 sections 4.4, 5.4, 6.4, 6.6): the holder
  of `@lorensen` gives `andreas@lorensen` and `sonia@lorensen` with
  certificates signed by its own key, for 1 to 5 years, renewed
  automatically and revocable in a public list; they count only while the
  parent is held. Domains can name people in DNS (`andlo@lorensen.dk`
  through `andlo._unseenet.lorensen.dk`), checked by the registrar. An
  identity with several names chooses which one its posts show. In the
  client: *Give a name under yours*, *Ask for a name under someone's
  name*, *Name requests*, *Names you gave*, *Name your posts show*. (#92)
- Report a post: **Report post** in the client sends it, with a note and
  optionally anonymously, to the group's owner, its moderators, the
  hierarchy's maintainer and the node's operator - whoever you tick.
  **Open reported post** takes a recipient to it. (#74)
- Hierarchy blocks (UN-RFC 0018 section 5.4): a hierarchy's maintainer can
  block an identity across its hierarchy with a public reason, and a
  maintainer of a delegated part (such as `dk.snak.*`) within that part.
  Clients hide blocked posts and say so, and readers can show them
  anyway; nodes with the new `honour_blocks` setting refuse them and say
  so in their node information (UN-RFC 0011). **Block in hierarchy** for
  maintainers in the client; the client now also reads the lists of
  delegated sub-hierarchies. (#75)
- Moderated groups work for everyone: a non-moderator's post goes, sealed,
  to the owner and every moderator (UN-RFC 0009 section 3, now covering
  several moderators), and **Moderation queue** in the client approves it
  unchanged or rejects it. The first moderator to act decides. (#71)
- Owners run their groups from the client: **Make moderator**, **Make
  poster** (channels), **Moderators and posters** (remove), and **Members
  of closed group**, which removes a member by giving everyone else a new
  key (a new epoch, UN-RFC 0004 section 6). *About group* shows moderators
  and posters. (#70)
- Ban a key from a group (UN-RFC 0004 section 5.1): the owner lists keys in
  the manifest's new `banned` field, with a public reason. Nodes refuse
  their posts, clients hide the old ones, and *About group* shows the bans.
  **Ban from group** and **Banned from group** in the client's command
  palette. (#73)
- Ignore a person: **Ignore this person** in the client's command palette
  hides everything they write, in every group and in private messages.
  The list stays in your vault and is never sent; **People you ignore**
  shows someone again. (#72)
- Withdraw a post (UN-RFC 0004 section 7): **Withdraw post** in the
  command palette or Shift+D in the client, and `unseenet withdraw` on
  the command line, for your own posts and any post in a group you own or
  moderate. The client asks first and says that withdrawing is best effort.
  It also honours cancels from others: it checks each one itself, drops the
  post from its cache, and remembers cancels for posts it has not seen yet.
  `unseenet read` shows each post's Message-ID. (#36)
- The node supports `OVER`/`XOVER`, `HDR`/`XHDR`, `LIST OVERVIEW.FMT` and
  `LIST HEADERS` (RFC 3977 sections 8.3-8.5), so newsreaders such as tin,
  slrn and Thunderbird list a group in one request instead of fetching
  every article's headers over Tor. Group settings, encrypted posts and
  private messages get a fixed subject in the overview. (#21)
- *Transfer* and *Release* under `@` in the client: hand a name to another
  key, or give it up (UN-RFC 0019 section 6.5). (#60)
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
  view, Esc leaves the input line so the posts are shortcuts again, and
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
- A node no longer refuses an article for ever because it once refused it
  when pulling it from a peer. Refusals are kept per peer, only so the
  article is not fetched from that peer again; a client can still post it,
  and it is accepted once the node's policy or the group's manifest allows
  it. Before, a local group (such as an operator inbox) refused from a peer
  could never be created on the node afterwards. (#132)
- The daily health check could not read any canary back: it checked the
  signature of articles as served to a reader, with Xref and the like
  added. It now strips them first. Without this, the first day canaries
  were read would have reported every listed node as disconnected. (#95)
- The node no longer crashes the monitor's stats request with
  `readuntil() called while another coroutine is already waiting`: commands
  on the Tor control connection now run one at a time, and a timed-out
  status request still reads its whole reply, so the next command does not
  get it. Seen when the monitor asked while Tor was still starting. (#127)
- A member removed from a closed group could go on posting with the
  previous epoch's key, which nodes accept to tolerate replication delay.
  A key update made because a member was removed now carries
  `closes_previous` (UN-RFC 0004 sections 6.2 and 6.5): nodes refuse
  earlier epochs from then on, and clients hide such posts that a lagging
  node let through. (#84)
- In *Your names* (`@`) the claim field no longer sits against the line
  with your key. (#61)
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

[Unreleased]: https://github.com/unseenet/unseenet/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/unseenet/unseenet/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/unseenet/unseenet/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/unseenet/unseenet/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/unseenet/unseenet/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/unseenet/unseenet/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/unseenet/unseenet/releases/tag/v0.1.0

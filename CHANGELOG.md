# Changelog

All notable changes to the Unseenet software are listed here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [semantic versioning](docs/development.md#versioning).
Protocol changes are made through the [UN-RFC series](rfc/), not here.

## [Unreleased]

### Added

- **A share written like any post** (UN-RFC 0060, unseenet-gui): `POST /api/groups/{gid}/post`
  and `POST /api/private` take `share` (`{"group", "id"}` of the post being shared), so a
  share with a comment - into your feed, into a group, or to one person - has everything a
  post has: a subject of its own or none (the core makes one), files, a link card, tags,
  languages and comment days. The same checks as `.../share`; `share_notice: false` sends
  the author no notice.

## [0.6.7] - 2026-10-31

### Fixed

- **Link cards lost their picture** where the picture's server chooses the format (#813):
  the client asked for AVIF, which it cannot show, so DR's pictures - sent as AVIF when
  asked - were dropped. Pictures and icons are now asked for only as WebP, PNG, JPEG or
  GIF, the formats the decoder shows; a test keeps the two lists in step.

## [0.6.6] - 2026-10-30

Sharing - "Facebook mode" is complete with it (UN-RFC 0060). **Update the nodes first**: a
node before 0.6.6 refuses shares as posts without a subject, and only 0.6.6 nodes answer
`XUN-FETCH`. A client before 0.6.6 shows a share as a post with an `unseenet:` address.

### Added

- **Sharing** (#805, #808, UN-RFC 0060): share a post into your feed, plainly or with words
  of your own, into up to three other groups, or send it to one person. A share is a
  reference, never a copy: an edit or a withdrawal by the author reaches every share, and
  nothing is counted - no "shared 12 times". In the timeline each original shows once,
  "shared by" those you follow; plain shares can be hidden per feed or everywhere
  (`hide_shares`). The author gets a share notice in For you (`share_notices`, on).
  Session: `share`, `unshare`, `send_share`, `share_permission`, `share_destinations`,
  `fetch_share_target`; local API: `GET/POST /api/groups/{gid}/share`, `.../unshare`,
  `GET /api/share-target` (`503 later` while a node fetches); CLI: `unseenet share`
  (`--comment`, `--into`, `--to`) and `unseenet unshare`.
- **Nodes: shares and `XUN-FETCH`** (UN-RFC 0060 sections 4, 6, 7): nodes take
  `Message-Kind: share` and the `Share-Of`/`Share-Group`/`Sharing` headers, refuse shares
  of encrypted articles they hold, of articles that ask not to be shared, into groups with
  `share_into: false` (chat groups by default), plain shares into discussion groups, and a
  fourth group for one key's shares of one article. `XUN-FETCH <message-id> <group-id>`
  answers with a shared article - or its newest version - and fetches one from peers into a
  cache of its own (a day at most, never carried, listed or forwarded); `fetch = false` in
  `[node]` turns that off for groups the node does not carry. **Update the nodes first**:
  a node before 0.6.6 refuses shares as posts without a subject.

### Changed

- **A post's own pictures before its link card** (UN-RFC 0059 section 8): a post with
  pictures or files of its own shows them first and its card small, as in a chat - a NASA
  picture of the day is the picture, with a line saying where the link goes.

## [0.6.5] - 2026-10-30

A patch release with new features, by choice: link cards and the rest below. Nothing
breaks for 0.6 nodes and clients - a client before 0.6.5 shows a post with a card as
before, with its link. Nodes need no update for it.

### Added

- **Link cards from programs** (UN-RFC 0059): `Poster.make_card(url)` makes a card over the
  Poster's Tor as a client does, and `Poster.post(..., card=...)` sends it with the post -
  its picture as one more file where the group takes files, else without it. Bots can drop
  the picture when its licence is not known. `client.session.fetch_card(url, socks,
  picture=)` makes one at a given Tor without a Session, for a gateway.
- **Link cards** (#792, UN-RFC 0059): a post with a link can carry a preview of the
  page - its icon, domain, title, description and picture - made once by the poster's
  client over Tor and carried in the signed post as a `Link-Card` header, the picture as an
  ordinary attachment; readers never fetch. `core.cards` (the header, a reader's checks,
  reading a page's head in the order og: -> twitter: -> `<title>`, the domain with
  look-alikes marked, hosts never fetched), `client.webfetch` (HTTP over Tor only, with
  limits), `media.card_icon` / `card_picture`, and `Session.make_card`,
  `post(card=...)`, `send_private`/`send_chat(card=...)`, `edit` keeping the card,
  `Message.card`. Settings: `link_cards`, off by default in the bootable client. Local API:
  `POST /api/card`, `card` on posts, private posts, edits and messages (UN-RFC 0046 4.25).
  CLI: `unseenet card URL`, `post --card [URL]`, `--card-title`, `--card-desc`,
  `--card-no-picture`, `--no-card`, and the card's domain and title in `read`.
- **The user guide inside Unseenet** (unseenet-docs#7): the project's site
  `unseenet.help.guide`, in `create_groups.py` and the `unseenet` hierarchy list, and a
  weekly workflow (`publish-guide.yml`) that publishes unseenet.org's guide there with
  the site import, posting with the announce key. `unseenet.help`'s charter points to it.
- **A stick finds a mirror by every version it has** (unseenet-entrance#44): a mirror keeps
  the portable builds and the bootable images each at its own newest version (a portable
  post-release can be ahead of the images) and names them all in `mirror_all`;
  `update.mirrors_with` uses it, and an older entrance's `mirror` as before.

- **Long entries and comments in a feed, cut by one shared rule** (#781): `markup.preview`
  decides what a feed's preview shows - the author's read-more line within twice the
  normal cut (UN-RFC 0031 3.2.1), nothing cut for a line or two, a cut at a sentence or a
  word and never inside a link, a code block or a table, and in a comment its own words
  before what it quotes. The numbers stay the clients' (an entry's and a comment's normal
  cut). The local API gives each feed row its `preview` with
  `GET /api/groups/{gid}?preview=ENTRY,COMMENT,WIDTH` (UN-RFC 0046 4.3 as amended), and
  `unseenet timeline --json` each entry's. UN-RFC 0034 section 4.2 amended (draft): comments
  in a feed are cut like posts, with a shorter cut; only the feed and the timeline cut.

- **The other repositories' releases in `unseenet.announce`** (#772): every hour,
  `announce-repos.yml` posts each new stable release of the graphical and terminal
  clients, the portable and bootable builds, the web entrance, the gateway, the bots and
  the watchman, with the same frame as the core's release posts and issue links to the
  right repository. Same announce key; nothing needed in the other repositories.

### Changed

- **Every group's state about once a day, not on every pull** (UN-RFC 0017 3-4 as amended,
  #748): a node lists the state in `NEWNEWS` only for a time at least 24 hours back, and
  a node pulls that far back at start and then about daily. On the project's nodes that
  is some 5,600 Message-IDs (~250 KB) per peer once a day instead of every hour.

### Changed

- **Development builds count on from a fix release** (`tools/dev_version.py`): with v0.6.1
  tagged on `release/0.6`, main's builds were 0.6.1.devN - below 0.6.1 by PEP 440 - so
  clients that need 0.6.1 could not be built nightly with core main. They now count
  on from the newest release of the series.

### Fixed

- **Publishing a site from a vault that has not read it** (unseenet-docs#7): `site-publish`
  checked who may write before it had fetched the site's manifest, so a poster whose
  vault had never seen the site - a CI key in a throwaway vault - was told "this group
  is not a site". The manifest is now fetched first.

## [0.6.4] - 2026-10-29

A fix for 0.6.3. **Update clients**; nodes gain nothing.

### Fixed

- **A copied or restored key has its feed and site** (#771): a copy carries identities and
  closed groups' secrets (UN-RFC 0050 3.6), not the vault's entries for the key's own
  feed and site, so the new device said *Start your feed* and *Start your site* although
  both existed. Right after a key arrives - copied in the app, the browser or with
  `unseenet copy-from`, or restored from its words - the client reads the key's feed and
  site manifests from the network (one request, UN-RFC 0041), takes them as started and
  follows them again, as it does for ripening (#758); starting a second one is never
  offered. `Session.adopt_published_personal_groups`.

## [0.6.3] - 2026-10-29

A fix for 0.6.2. **Update clients**; nodes gain nothing.

### Fixed

- **A Tor another running program uses is never stopped** (#768): 0.6.2's fix for a Tor
  left behind stopped any Tor in the folder's `unseenet-tor` - also one that another
  running Unseenet program with a vault in the same folder used, which cut a copy in
  progress off its onion service. Now only a Tor whose program is gone is stopped;
  otherwise the start says that another program uses this folder's Tor.
- **A used copy code says so** (#757, #765): the lookup takes the meeting off the node,
  so when the copy then failed, trying the same code again said *No device is waiting
  with this code. Check the code* - about a code that was right. A failed copy now ends
  with *This code has been used ... Start again on the other device for a new code*.

## [0.6.2] - 2026-10-29

From the first live copy of an identity to a browser. **Update clients first**; nodes
gain nothing.

### Fixed

- **Copying waits for the other device** (UN-RFC 0050, #754): the new device gave the
  old device's one-time onion service a few seconds, though a fresh descriptor can take a
  minute - and the lookup had used the code up, so a second try said *No device is
  waiting*. It now keeps trying for 90 seconds (unseenet-entrance 0.3.1 does the same
  for a browser).
- **A key that arrives shows its level at once** (#758): copied from another device or
  restored from its words, a key said *New key getting ready* until a node asked for
  ripening. It now takes over its published chain right away, and is never ripened
  again from the start.
- **A copied key brings its ripening** (UN-RFC 0050 3.6 as amended, #759): the old device
  sends the key's ripening chain with it, and the new one keeps it once checked - so
  the level shows with no node, and ripening done but not yet published is not lost.
  Older clients ignore it; a chain that does not check out is dropped.
- **A Tor left behind no longer blocks the client** (#755): when a client ended without
  stopping its Tor, that Tor kept the data directory, and the next start waited for it
  with *Starting Tor ...* and every node "does not answer". Tor now quits by itself when
  its program is gone (`__OwningControllerProcess`), and at start a Tor an earlier run
  left in the directory is told to halt through its control port.

## [0.6.1] - 2026-10-29

### Fixed

- **Nodes pull again** (#748): NEWNEWS lists every group's state first, whatever the
  time asked for (UN-RFC 0017), so its answer grows with the network - past 250 KB on the
  project's nodes on 29 Oct - and the pulling node read at most 70 KB of it: every pull
  stopped with `block too large`, and a node that was down did not catch up (pushed
  articles still arrived). It is now read with the same limit as reconciliation (16 MiB).
  Making the listing itself smaller is #748.

## [0.6.0] - 2026-10-29

**Facebook mode: feeds you follow, comments, likes - with nobody deciding what you see.
Update the nodes first, then the clients.** 0.6 nodes check what 0.6 clients write -
tags, spam reports and labels, comment deadlines and closes, team inboxes - and 0.6
clients expect them. Pre-alpha: there is no compatibility code for older nodes, so a
0.6 client on a 0.5 node misses these.

- **People:** comments on feeds with an entry's own time and *Close comments*, tags and
  content warnings, your own rules for your feed (UN-RFC 0051) and *Show all*, spam
  reports and labels you choose to follow (and nothing ever removed from the network),
  copying your identity to another device with a code or a QR code, recovery words, a
  PIN on a device, and a client that carries on by itself when your nodes are gone - in
  unseenet-gui 0.3 and unseenet-tui 0.2.
- **Node operators:** nothing to turn on; update to 0.6 before your users' clients. A
  node now rejects replies past a thread's deadline or in a closed thread, and checks
  tags, report and label channels and team inboxes (UN-RFC 0030, 0045, 0047, 0052, 0053).
- **Bots, gateways and other services:** require `unseenet>=0.6,<0.7`; ripen to level 4
  if you post a lot (`UNSEENET_RIPEN_TO`, `client.runtime.service_ripen_to()`), post
  through the posting queue, and keep how far you read with `keep=False` across
  restarts. Container images for the services are published for releases
  (`ghcr.io/unseenet/gateway`, `bots`, `entrance`, `watchman`).

### Changes in this release

- **Release notes in `unseenet.announce` are Markdown** (#611): `tools/announce.py release`
  posts `text/markdown` (UN-RFC 0031) with a title, the changelog section - issue
  references such as `(#518)` or `unseenet-gui#237` as links, its `###` headings one
  level up under the title - and a *Get it* section with the downloads, `pipx` and the
  full changelog; a test release says so at the top. A section too long for one post
  becomes its lead and a link. `message` posts Markdown too; the lists and
  `client-release` stay plain text, since programs read them.

- **Level 4 by choice** (#740, UN-RFC 0025 section 7): a key can be ripened to level 4
  on a device that is chosen for it - about two weeks of one core on a fast desktop
  while the program runs, after which each post costs about a quarter of the work.
  The default stays 3. `Session.set_ripening_target(3|4)` keeps the choice with the
  key's chain in the vault, on this device only, like the pause; the client runtime
  follows it at once (raised: ripening starts again; lowered: it stops after the
  segment it is on). The time left is estimated from this device's own speed, measured
  while it proves (`ripening_seconds_left`). Local API: `POST /api/ripening {"to": 3|4}`
  and `target`, `chosen`, `seconds_left` and `speed` in the state's `ripening`, and the
  event `ripening-target` (UN-RFC 0046 section 4.1). CLI: `unseenet ripening [--to 3|4]`.
  Services: `client.runtime.service_ripen_to()` - `UNSEENET_RIPEN_TO` (0-4) if set,
  else 3 - one way for every service to choose. UN-RFC 0025's level table now gives
  the times with the low-memory prover (measured: about 107,000 iterations a second on
  a Ryzen 9 5950X core, against 165,000 with `chiavdf.prove`).
- **Mark a whole group read** (#625): `Session.mark_group_read(gid)` - a newsreader's
  "catch up", saved once - `POST /api/groups/<id>/read {"all": true}` (answers how many
  were unread) and `unseenet read --all GROUP`.
- **A Markdown preview from the core** (#632): `Session.preview(text, kind)` and
  `POST /api/markup {"text", "kind", "markdown"}` give the same safe tree messages carry
  (UN-RFC 0031), so a Write / Preview toggle in any client shows exactly what readers
  will see (UN-RFC 0046 section 4.4).
- **How far a program read survives a restart** (#735, #669 follow-up): groups read with
  `fetch_group(..., keep=False)` keep how far they got in the vault or the service's
  state file, per node, so a restart goes on from there instead of reading them from
  the start; `Session.read_marks()` / `set_read_marks()` for programs that keep it
  themselves. unseenet-watchman can drop its own copy.

- **When your nodes are gone, the client carries on** (#603, #604, #605):
  - When none of your nodes has answered for two minutes, the client takes a random node
    from the newest signed known-node list that answers (UN-RFC 0010 section 5), makes it
    your default and reads there the groups it carries; your inbox goes along. You are
    told ("unseenet-node1 does not answer - you now use unseenet-node3"); the old nodes
    stay in your list and are read again when they come back. Only listed nodes are
    used, never one learned from an article or a page.
  - A group is only ever moved to a node that carries it. A group only one node carries
    (a local node, an unlisted one) stays with it and shows as not reachable until it
    comes back. Removing a node no longer moves its groups blindly to the default: the
    local API's `remove` answers which groups moved and which no node of yours carries
    (`unavailable`), and `Session.rehome_groups` does the same for other programs.
  - Posting goes through another of your nodes when the group's node cannot be reached,
    and the postage and ripening are asked of the node the post goes to. A post sent
    again after a broken line that the node already has (`duplicate`) is a success, not
    an error and never a second post.
  - When the default node has failed for two minutes and another of your nodes answers,
    that one becomes the default: new groups and your inbox go there. Creating a group
    and setting up your inbox no longer fail while the default is down; they use the
    next node that answers. A new event, `default-node-changed`, tells front ends.
- **An entry's own time for comments, and closing comments on one entry** (#732, the
  UN-RFC 0030 amendment):
  - Whoever starts a thread can give it a shorter time for comments than the group's,
    from none (`0`) up to the group's `comment_days` (`Comment-Days`, an outer header in
    closed groups). The thread's deadline is the shorter of the two; an edit of the
    root can shorten it, never lengthen it.
  - The entry's author, the owner and moderators can close comments on one entry, with
    a short note for readers, and open them again (`comments-close`/`comments-open`).
    The author can close and open their own, but not open what the owner or a moderator
    closed. Reactions are not touched by either.
  - `comment_days` can now be set in open, moderated and closed groups too, not only
    channels - there it limits replies in a thread - and never in inboxes or local
    groups. Reactions close with the group's `comment_days` in every group that sets it.
  - Nodes reject a root whose own time is longer than the group's, an edit that would
    lengthen it, and replies past the deadline or in a closed thread (when they hold
    the root); a close that arrives before its entry is "try later", as a comment is.
  - Session: `post(comment_days=)`, `edit(comment_days=)`, `comments_state`,
    `close_comments`, and `write_permission` answering `comments_closed` with the
    reason and the note. Local API: `comment_days` on post, edit and creating a group,
    `comments` and `may_close_comments` on a thread's row, and
    `POST /api/groups/<id>/comments` (UN-RFC 0046 section 4.24). CLI: `post
    --comment-days`, `comments-close`, `comments-open`, and `group create
    --comment-days` for every type.

- **UN-RFC status means what UN-RFC 0000 says** (#738): five documents (0047, 0052-0055)
  said `Status: Accepted`, which is not a status. The maintainer's acceptance agrees to a
  *change* - a new UN-RFC, an amendment, a correction - never to a status; every protocol
  document of the first series stays Draft until 1.0 (UN-RFC 0000 3.3.1). Each Standards
  Track document now says what is built in an `Implemented:` line (3.4), and at 1.0 the
  implemented ones become Proposed and are changed only by new UN-RFCs (3.3.2).
  `tools/check_rfc_headers.py` checks every header on pull requests that touch `rfc/`
  (in the docs check) and in the tests, and a release fails while an `Implemented:` line
  still says `unseenet main (unreleased)` (`--release X.Y.Z` names the version).
- **Key ripening in constant memory** (#444): segments are proved with chiavdf's new
  `prove_low_memory` (chiavdf 1.2.1, now the minimum), which gives the same proof as
  before in about 20 MiB whatever the segment's length, at about twice the time. Every
  machine can now ripen a key to level 4; memory no longer limits the level. Nothing
  changes for nodes or other clients: the proofs are byte for byte the same. Clients
  still ripen to level 3 by default (level 4 takes weeks of one core).
- **One ripening lock for the whole machine** (#677): the lock for large segments is
  one file for every user and service (`/run/lock` or `/dev/shm`, which systemd's
  `PrivateTmp` leaves shared; `UNSEENET_RIPENING_LOCK` to choose), not one per user in
  `/tmp`, and free memory is read again once the lock is held. Two services on the
  project's help-bot VM each ripened at once and ran it out of memory. Where chiavdf has
  the low-memory prover the lock is rarely needed at all. A segment's start is logged.

- **Accepted** by the maintainer, 28 Oct: the UN-RFC 0030 amendment (#730): an entry's
  or thread's own comment deadline (`Comment-Days`, never longer than the group's),
  closing and opening comments on one entry (`Control: comments-close` /
  `comments-open`), and `comment_days` in open, moderated and closed groups too. Reactions
  are not closed by either (UN-RFC 0048 4.4). Node and client support follow.

- **A group's rules are now its charter** (#726, UN-RFC 0014): "rules" means only your own
  rules (UN-RFC 0051), which your client applies; what a group's owner writes about the
  group is its *charter*, which no machine enforces. Breaking for clients of the local API
  and the CLI: the manifest fields are `charter`/`charter_type`, the API fields `charter`,
  `charter_type`, `charter_tree` (and `charter` when creating a group), the CLI option
  `--charter FILE`, and `Session.create_group(charter=…)`, `charter_unseen()`,
  `mark_charter_seen()`. Manifests signed with the old names are still read; republishing
  one writes the new names, and `tools/project/create_groups.py` moves the project's
  groups over the next time it runs. Nodes are not affected.

- **Key ripening keeps within a service's own memory limit** (gateway#47): the memory
  budget for ripening (#440) now reads this process's own cgroup and every one above it,
  so a systemd `MemoryMax` inside a container counts, not only the container's limit. A
  gateway or bot under `MemoryMax` no longer chooses segments too large for it and is
  killed over and over.

- **Refusal lists for every picture** (#715, #717, UN-RFC 0027 section 7.3): the node now
  refuses a profile picture (and, since #714, a group's emoji) whose ID a refusal list or
  `--refuse-blob` names, and tells the person in plain words. Lists are set in a new
  `[refusals]` table in `node.toml` (`keys`, `groups`) and work also on a node that
  carries no files; `[blobs] refusal_keys` keeps working.

- **A group's own emoji** (#156, UN-RFC 0056): up to 16 small pictures with a name, in the
  data group `<name>.emoji@<fp>` (`core.group_emoji`). The owner publishes them
  (`Session.set_group_emoji`, `make_group_emoji`; `GET`/`POST /api/groups/<id>/emoji`), and
  readers read them with the group. Nodes carry them only when `emoji = "accept"` in
  `node.toml`, which is off by default; the installer and the Docker image follow the
  answer for profile pictures, or `UNSEENET_EMOJI`. New groups can no longer be named
  `….emoji`.
- **A PIN on a device** (UN-RFC 0050 section 5): the vault key can be wrapped by a passkey's
  secret, which the device's secure hardware gives only after its PIN
  (`Vault.add_device_unlock`, `open_with_device`; `/api/device-unlock`). The passphrase
  still opens the vault everywhere, and a new passphrase removes the devices.
- **Help for Edit group** (`GET /api/help/group-settings`): per setting, what it does, whom
  it affects and what changing it later does, the same in every client.
- **Someone you follow is named at once** (#709): following a person reads their feed until
  their name is known.

- **What you follow because of a person, by person** (#706): `Session.followed_people_groups()`
  and `people_followed` in the local API's `/api/groups` group other people's feeds and
  sites by the person they belong to, sorted by name; the group tree no longer has
  hierarchies called `feed` and `site`.

- **One slow node no longer holds up the others** (#704): the client runtime gives each node
  12 s to list its groups; what the others have is shown at once, the slow one is said to be
  "not answering yet" (`Session.slow`, `Refreshed.slow`), its answer is awaited in the
  background, and when it comes everything is listed and fetched again. Meanwhile nothing
  else waits on it: a call to a node that has not answered yet fails at once.

- **How long ago, in the same words everywhere**: `unseenet.client.timefmt.ago()` - *now*,
  *5 min*, *2 h*, *Yesterday 14:20*, *3 days*, then the date - for every client's feeds
  (unseenet-tui#34, as the GUI says it).

- **What comes into the timeline is your choice per group** (#697, UN-RFC 0034 6.2): feeds by
  default, a group of threads when you put it in (each new thread once), chats never; kept
  in your state (UN-RFC 0044 `timeline`); `unseenet timeline groups | add | remove | default`,
  and `POST /api/groups/<id>/timeline` in the local API.

- **`unseenet post` tells the language from the text** when `--lang` is not given (#686),
  as the clients do - the demo's people and other scripts get it right by themselves.

- **A group with several languages suggests its main one** (the first), not all of them
  on every post (UN-RFC 0052 5a).

- **The project's groups say their language** (UN-RFC 0052 5a): `create_groups.py` gives
  the project's discussion groups and the bot channels `languages: ["en"]`; data channels
  none.

- **One list of languages** (asked for by the maintainer, 27 Oct): `core.languages` - code,
  its own name (*Dansk*, *Svenska*) and its English name, the nine a text can be told in
  first; `name`, `search` ("da", "dansk" and "danish" find Danish), `GET /api/languages`.
  No flags: a flag is a country, not a language.

- **Your choice for chat lines and comments wins** (UN-RFC 0052 5a): `choose_chat_language`
  and `POST /api/groups/{gid}/language/choose` - what you chose to write lines in here is
  used for them before the text, the conversation or the group; `[]` takes it back. With
  the group's languages before your last choice (#686), a remembered choice alone would
  never have reached them.

- **Language recognition in core** (#686, from unseenet-watchman): `core.language` -
  the small words that tell nine languages apart (Danish, Norwegian and Swedish too),
  `words`, `language`, `detect`, `guess`; Lingua afterwards when installed
  (`pip install "unseenet[language]"`), only when ≥ 80 % sure. A few KB without it, so
  the browser build has it too. **The suggestion's order changes** (UN-RFC 0052 5a): the
  text when it tells for sure, then the group's languages, then your last choice there,
  then a one-language profile; a comment the post it answers; a chat line the
  conversation's unless a longer line is sure of another. `suggest_languages(group,
  text=, reply_to=, kind=)`, `POST /api/groups/{gid}/language`; `send_chat` uses it.
  The header is the author's suggestion, never evidence: moderation and labels decide
  from the text.

- **Origin-Proof** (#609, UN-RFC 0049 section 7.3, its encoding written down): a post
  brought to a new key from an Unseenet export may carry the old article's header block
  (base64, at most 8 KiB) - with this body it is the old article, so a reader checks the
  old key's signature, the Message-ID, `Origin-Date` and `Origin-ID`, and only then shows
  it as proven (`Message.origin_proven`, `origin.proven` in the local API). A proof that
  does not hold is none. `origin_headers(..., proof=)`, `check_proof`,
  `Session.post(origin={..., "proof": raw})`. Off by default: it links the two keys.

- **A chat line in a group gets the suggested language** (UN-RFC 0052 5a):
  `send_chat(..., languages=)`, left out the group's suggestion - a chat line is not
  asked about, so every client and program does the same.

- **The language of a post** (#671, UN-RFC 0052 section 5a; decided 27 Oct): the author's
  `Content-Language` (1-4 codes such as `da`, `en`), checked for form by nodes, inside
  the encryption in closed groups. People write in several languages by group, so the
  client suggests and the author decides: what you chose last in that group (kept in
  your settings, never published), else the group's `languages` (a new manifest field),
  else your profile when it names one language - else no header, better none than wrong.
  `Session.post(..., languages=)`, `suggest_languages`, `remember_languages`;
  `Message.languages`, `GroupInfo.languages`; rules `lang da en` (UN-RFC 0051), falling
  back to `lang-xx` labels from labellers followed for topics; local API `languages`
  and `suggested_languages`; `unseenet post --lang`, `group-edit --languages`.

- **For you with your rules, seen, and Show all** (#629, UN-RFC 0051 5.5): only
  `[foryou]` rules act on For you - rules for the feed or groups never do; `quiet`
  (only there) lists an entry without counting it or telling you, `hide` leaves it out,
  `for you is reply` / `mention`; `scored_for_you`, `for_you_quiet`; the counts leave out
  what is read, seen (in For you - `for-you:`'s seen mark - or in its group), quiet or
  hidden, and notifications skip quiet and hidden ones. **Show all**: `rules=False` on
  For you, the timeline and threaded groups, `GET /api/groups/{gid}?all=1` (`show_all`
  in the head) - a look, never saved. `unseenet foryou [--all] [--why] [--unread]`.
  Fix: the rules read a group's tags from its manifest, not its info, which counted For you.
- **For programs that follow every group** (#669, asked for by unseenet-watchman):
  `Session.skip_to_now(group)` begins at the newest article without fetching what is
  there (its manifest read, so its settings are known); `fetch_group(group, skip=...)`
  reads the overview first (`OVER`, `nntp.Client.over`) and fetches only the articles
  the function does not skip - manifests and control articles always; and
  `fetch_group(group, keep=False)` keeps nothing but how far it has read and returns
  just the new messages.
- **Start the reports or labels channel of a named identity** (#661):
  `start_reports(..., issuer=)`, `start_labels(..., labeller=)` and
  `publish_labels(..., labeller=)`, as `publish_report` already did - one issuer per
  kind in one vault, the identity in use unchanged.
- **Looking labels and reports up, and their expiry** (#670, spec only; accepted by the
  maintainer 27 Oct): UN-RFC 0053 sections 7.1-7.2 and UN-RFC 0045 section 6.1 -
  `XUN-MARKS`: a reader asks its node which signed label and report articles name the
  posts and keys of a page, and fetches only those (the node can withhold, never
  invent); `UNSEENET-MARKS <max>`; fallback to whole channels. Entries expire with their
  posts, and a node may drop an article whose posts are all gone. Labellers and issuers
  should keep an article within one top-level hierarchy. Implemented in 0.7.0.

- **The age guide** (UN-RFC 0053 section 6.1): `core.labels.AGE_PROFILES` - under 13,
  13 to 17, an adult - suggest what to do with each warning; `Session.apply_age_profile`
  takes one as your own choices and keeps nothing of the age group;
  `POST /api/labels/profile`, and `profiles` in `GET /api/labels`.
- **Ready for the project's labeller** (decided 27 Oct: the default for warnings in
  `unseenet.*`): `create_groups.py` names `PROJECT_LABELLER` in the bot channels once it
  is set; the list of `unseenet.*` takes `labellers` as it takes `report_issuers`.

- **Everything with a tag** (UN-RFC 0052 section 7): `Session.tagged(tag)` - the posts
  with a tag in the groups and feeds you follow (the author's tags, the group's, topics
  of labellers you follow for topics), newest first - and the pseudo-group
  `tag:WORD` in the local API, shown as a feed (UN-RFC 0046 4.23).

- **`!` for groups, `#` for tags** (decided 27 Oct): a group is referred to as
  `!dk.snak.marsvin` or `!dk.snak@abcd` (UN-RFC 0031 3.4.2, as Lemmy's
  `!community`), and `#word` in the subject or text of what you write is a tag - your
  client puts it in the `Tags` header with the chips and leaves the text as you wrote
  it (UN-RFC 0052 section 3); nobody else reads tags from text. `core.groups.GROUP_REF_RE`
  uses `!`, `core.tags.in_text`/`TAG_REF_RE` find tags; mention notices say
  `!group@fp`. Pre-alpha, so a clean break: old `#group` text is a tag now.

- **Accepted** by the maintainer, 27 Oct: UN-RFC 0052 (Tags) and UN-RFC 0053
  (Content Labels, labels on posts only - never on keys, which can be persons), the
  UN-RFC 0045 amendment (`harassment`; reasons sanction, labels describe) and the
  UN-RFC 0051 amendment (`tagged`, `labelled`, and `blur` as its own action).

- **Rules with tags and labels** (#658, UN-RFC 0051 amended): `tagged WORD...` (any
  of the post's tags, the author's or its group's), `tagged all WORD...`, `labelled
  WORD...` and `labelled all WORD...` (labels from labellers that count for you, never
  the author's own tags), and the action `blur` - text and pictures behind *Show
  anyway*, in the feed and in groups (a rule's `actions` has it).

- **Content labels** (#656, UN-RFC 0053, new): labellers - people or programs -
  label posts others wrote, in a `labels@` channel; a label only describes, never
  sanctions, and nodes never act on it. **Warnings** (the set shared with tags) are
  shown, blurred (default) or hidden as the reader chose, never silently, never on
  your own or your contacts' posts; hierarchies (`labellers` in their list) and
  group owners (`labellers` in the manifest) may name labellers for warnings by
  default. **Topics** count only for a labeller the reader follows for topics
  themselves. Labels name posts only, never keys. `core.labels`, the session's
  `ContentLabelsMixin` (`labellers`, `follow_labeller(topics=)`, `refresh_labels`,
  `post_labels`, `warning_choices`, `start_labels`, `publish_labels`),
  `Message.labels` on every row with an `action`; `/api/labels…` (UN-RFC 0046
  4.23); `unseenet labels …`. A client's age guide stores only the choices, never
  the age (section 6.1, for the clients).

- **Tags** (#657, UN-RFC 0052, new): an author tags their own post with up to 8
  words - topics, and content warnings from a fixed set shared with labels
  (`profanity`, `sexual`, `nudity`, `violence`, `gore`, `spoiler`) - in a signed
  `Tags` header, never read from the text (`#` stays a group reference); in a closed
  group inside the encryption. A group's owner may give it `tags` in its manifest.
  Nodes check the form only (`441 syntax`) and never act on tags. `core.tags`;
  `Session.post(..., tags=)`, `Message.tags`, `GroupInfo.tags`; `tags` in the local
  API's post and group settings; `unseenet post --tag`, `group-edit --tags`.

- **One list of report reasons** (#659): `core.reports.REASONS` is the one list -
  clients, issuers and bots all use it - with `REASON_LABELS` to show them and
  `READER_REASONS` for what a reader's report action offers (all but `flood`). New:
  `harassment` (threats and harassment) in UN-RFC 0045 section 4; readers can report
  `phishing` and `malware`. A report now says its reason as the word itself; reports
  from older clients (`threats`, or the label they wrote) still say what they meant.
  `/api/reports` gives `reason_labels`.

- **Publishing a spam report is a job** (found 27 Oct: *Publish* seemed to do
  nothing): the issuer's postage, and the first time its ripening, can take minutes,
  and `POST /api/reports/publish` waited. Now it checks the report, answers `{"job"}`
  at once, and the job's events give the Message-ID.

- **An issuer for everyone, not only the project** (27 Oct): become an issuer as a
  separate identity beside yours (`POST /api/reports/start` with `separate`), for an
  organisation or a hierarchy, while yours stays the one in use; share it with a
  colleague by copying that identity to their device (UN-RFC 0050), where it is found
  to be an issuer by itself (`discover_issuers`, also after a copy and on refresh).
  Copying an identity into a vault that never chose a default no longer makes the
  copied one the one in use.

- **An issuer beside your own identity** (27 Oct): a vault may hold an issuer as a
  second identity - the project's in its maintainer's everyday vault - and reports
  are then published, listed and withdrawn as that issuer (`issuer_names`,
  `issuer_for`, `publish_report(..., issuer=)`), while your own identity stays the
  one in use. `/api/settings` `report_issuer` and `/api/reports` `mine` (with the
  issuer's `identity` and `label`) count it. `tools/project/issuer_to_vault.py`
  copies the project's issuer, its reports group and its ripening chain into the
  everyday vault. So a report in the contact inbox is handled where it is read.

- **Reporting a post is a job** (found 27 Oct): each receiver's sealed copy pays
  postage as an unripe key, a minute or more each, and `POST /api/groups/{gid}/report`
  waited for all of them - the report window said *Sending …* and seemed to hang.
  Now it answers at once with `{"job", "targets"}`, and the job's events say when
  every receiver has it (UN-RFC 0046 4.6).

- **Nodes take sealed posts in any inbox** (found 27 Oct): a sealed private post is
  signed by a one-time key, which cannot ripen, and nodes allowed that only in groups
  *named* `inbox@` - so posts to an operator's `operator@`, a team's `contact@` or any
  other inbox were refused ("no Key-Ripening header"). Now by the manifest's type.
  Nodes need this before team inboxes work (rollout rule: update the nodes first).

- **Edit a group's report issuers and a team inbox's name** (27 Oct): `group-edit
  --add-report-issuer/--remove-report-issuer KEY` and `--team-name`; the local API's
  group settings take `report_issuers` and `team_name`, and a group gives both
  (UN-RFC 0046). A team inbox's name may now be set before its first reader (UN-RFC
  0047 asked for 1-16 readers only when `readers` is there; the check asked always).

- **Reports land where they are read** (UN-RFC 0045 section 7.4): a report to an
  issuer goes to the inbox its `contact` names - a team inbox, say - with that
  inbox's own owner, else to its personal inbox as before; targets that share an
  inbox are one. *Reports sent to you* (`reports_sent_to_you`, `/api/reports/received`,
  `unseenet reports received`) include the team inboxes you read. So the project's
  issuer, whose contact is `contact@ph5fc5hop5232qsz`, has its reports read in
  everyday clients. Found by the maintainer: reports to the issuer were only in its
  own inbox.

- **A hierarchy's contact** (#647, UN-RFC 0018 section 4.1): an entry of the root
  list (and of a list's `sub`) may name `contact`, an inbox where its maintainer is
  reached - a team inbox, so the maintainer key stays offline. Reports to a
  maintainer go there; `unseenet.*` names `contact@ph5fc5hop5232qsz`. Found by the
  maintainer: reporting to "Maintainer of unseenet.*" failed, as the project key
  has no personal inbox. Report targets with no inbox one can reach are now left
  out instead of making the report fail.

- **The project's spam report issuer** (`ed25519:mhgvcdevmx5g2r6t…`, made with
  `report_issuer.py`): named in the list of `unseenet.*` (`report_issuers` in
  checkgroups.json, UN-RFC 0045 section 7.1) and in the bot channels in `alt.*`
  (create_groups.py, section 7.5), so their readers follow it by default and can
  turn it off; `reports@unseenet` in give_names.py. Not named for `dk.*`.

- **A group's owner names report issuers for its group** (#644, UN-RFC 0045 section
  7.5): `report_issuers` in a group's manifest, up to 16; clients follow them by
  default for that group only, next to its hierarchy's, and the reader can turn
  them off. For `alt.*`, which nobody governs, it is the only default there is -
  the project's bots name the project's issuer for their channels. Nodes do not
  act on it. `report_issuers()` says where each issuer is named (`groups`).

- **A node that does not answer over Tor** is a node away, not a crash: Tor's SOCKS
  timeout is tried once more and then a `ConnectionError`, as a refusal already
  was, and reading manifests asks your other nodes when the group's node cannot be
  reached. `team_contact.py` reads and creates on the first project node that
  answers, and says which did not. Found running it, 27 Oct.

- **The project's contact inbox and spam report issuer** (tools/project/):
  `team_contact.py` makes `contact@ph5fc5hop5232qsz` a replicated team inbox owned
  by the project key, read and answered as "Unseenet (operator)" with team keys in
  everyday clients, and prints what each node's `[operator] contact` must say;
  `report_issuer.py` makes the project's spam report issuer - a key of its own in
  `~/.unseenet/issuer.vault`, never the project key - and starts its reports group.
  Both have --dry-run.

- **Inboxes take PDFs too** (#637): send a document to someone and talk about it.
  Every inbox - personal, team, operator, issuer - takes pictures and PDFs,
  encrypted, up to 4 MiB each; one that took pictures only takes PDFs from the next
  time the client makes its manifest say what it takes. Clients never show a PDF
  inside the app (#638 asks whether a safe view can be made); they offer to save it.
- **UN-RFC 0047 (team inboxes) accepted** by the maintainer, 27 Oct, with
  UN-RFC 0046 section 4.22.

- **Team inboxes** (#341, UN-RFC 0047): an inbox may list up to 16 readers - team
  keys, each made for that inbox only - and messages to it are team boxes: a
  content key sealed to each reader in 16 slots without key IDs, so an article
  shows neither how many read it nor who. Nodes take team boxes in team inboxes
  only (an outdated client fails at once). The owner adds a reader by sending a
  new team key to their inbox (`add_team_reader`; the owner keeps none) and
  removes one with a new manifest; the reader accepts after checking owner and
  readers (`accept_team_invitation`) and keeps the key in the vault. Readers
  answer on the inbox's behalf (`send_private(..., as_team=)`): the receiver sees
  the team's name, verified against the readers, never a person. So the project
  key can stay offline while its contact inbox is read and answered. Local API
  `/api/teams...` and `as_team` (UN-RFC 0046 section 4.22), CLI `unseenet team
  ...`, docs/node/operations.md.

- **A local group on all your nodes** (#134): an operator with several nodes has a
  contact inbox on each, with the same Group ID. The client now reads a local group
  on every node in your vault that carries it - articles from the others numbered
  from an offset of their own, each post once (by Message-ID), with
  `Message.node` saying where it came - so one vault reads them all. Read marks are
  by Message-ID and hold; a node without the group is asked again after an hour;
  the offline cache keeps them all. `GroupInfo.read_from` (and `read_from` in the
  local API) lists the nodes, for "Operator inbox (4 nodes)". No node learns about
  your others. docs/node/operations.md says how to set it up.

- **Reports with a reason, Markdown and files** (unseenet-gui#70): reporting a post
  takes a reason (spam, illegal, threats or harassment, something else), a note in
  Markdown and files - a screenshot, a document for the police - sent encrypted to
  each receiver as on a private post. The report is Markdown with `report=post`;
  plain reports from before are still found. An issuer publishing a report it got
  keeps the reporter's reason where UN-RFC 0045 has it. UN-RFC 0046 section 4.6 says so.

- **UN-RFC 0046 section 4.21, spam reports**: the local API's requests for UN-RFC
  0045 and `reported` on every post, written into the spec (accepted 27 Oct).

- **Spam reports** (#122, UN-RFC 0045): any key can be an *issuer* and publish
  signed reports - posts and keys, each with a reason - in its own channel
  `reports@<fp>`; nobody has to follow anybody. `core/reports.py` builds and reads
  reports and keeps a `Book` of what followed issuers say. **Nodes** follow only
  the issuers in `[[follow_reports]]` (`posts`: hide or delete; `keys`: refuse,
  surcharge +6 bits, or ignore), apply them to posts held and posts that come
  later, serve a hidden post again when its report is withdrawn, and list the
  issuers in their node information. **Clients** follow the issuers a group's
  hierarchy names for that hierarchy (`report_issuers` in its list, at most 16,
  lower lists add) and those the reader chooses, for every group; the reader can
  turn any of them off. A hidden post keeps its place with `Message.reported`
  (who, why, which report) so clients show "Hidden by ...: spam" with *Show
  anyway*; your own posts and your contacts' are never hidden. The report action
  offers the issuers you follow; an issuer publishes what it got without the
  reporter. Followed issuers travel in your state (UN-RFC 0044). Everything is in
  the local API (`/api/reports...`, `/api/groups/{gid}/show`, `reported` in every
  message) and the CLI (`unseenet reports ...`, also `hierarchy` for maintainers).
  Clients' screens follow in unseenet-gui#70 and unseenet-tui#11.

- **A file the group's node lacks comes from your other nodes**: `fetch_blob` asks
  the node a group is read from first, then your other nodes, before saying a
  picture cannot be had - found when node1 and node2 carried files for `dk.test.*`
  only, so pictures in other groups were on node3 and node4 but not where they
  were read from. The file is checked against its ID wherever it comes from.

- **`node_info()` says what a node carries**: `carries`, how many groups it lists
  (one LIST ACTIVE on the same connection), so a client can show it beside how
  many of yours you read there (unseenet-gui#153).

- **The rules' help, readable** (#615): one thing a line, the rule on the left and
  what it means on the right - every condition, every count - at most 64
  characters wide, so it fits beside an editor without scrolling sideways. Tests:
  every word the language knows is in it, and every example in it is a rule.

- **Your own rules for your feed and groups** (#615, UN-RFC 0051, draft):
  scorefiles as Usenet readers had them, in a small language you can read -
  `+10 if author in following`, `show if score >= 0`, `sort by score, then date`,
  `#` comments, any case. They run only in your client, travel only in your
  encrypted state, and without them nothing changes. `client/scoring.py` parses
  and uses them (with "Why?" and line-numbered problems); the Session keeps them,
  what you have seen and the threads you watch or ignore (UN-RFC 0044 4.5), and
  gives the timeline and a group's threads as your rules have them - replies never
  reordered. The state now keeps fields a client does not know.
  The local API has them (`/api/rules`, `/api/rules/check`, `/api/threads`,
  `/api/groups/{gid}/seen`; rows with `score`, `actions`, `hidden`, `why` only
  when you have rules, UN-RFC 0046 4.20), and so does the CLI: `unseenet rules
  show|set|check|on|off|clear`, `unseenet thread watch|ignore|clear`,
  `unseenet timeline --why`.

- **`unseenet.help.news`** (unseenet-helpbot#21): the help bot's plain-language
  news about releases, a feed open for comments for 30 days; in the project's
  groups and the hierarchy list, and a **starter group** (version 4): new clients
  follow it, and existing ones at their next start.

- **Reactions through a gateway count per outside person** (UN-RFC 0048 section
  9, unseenet-gateway#32): in a gatewayed group, a reaction its gateway (a
  moderator) brought in with `Origin-Network` and `Origin-From` counts for that
  outside author, so ten Matrix users' 👍 show 10, and one person changing counts
  once; `Origin-From` from any other key is not believed. "Who" names them
  "@a:hs (via matrix)".

- **Encrypted files are padded** (#486, UN-RFC 0027 3.3 and 4.4, #598): before
  encryption a file in a closed group, private post or chat is padded with zeros
  to the next 64 KiB (never beyond the group's `max_size`), so nodes see only its
  size class, not a length that could tell a known picture; readers cut it back
  to the size in the inner header and accept a blob between the file plus 40 and
  its 64 KiB-rounded size plus 40, whatever the group's limit is now.

- **Reactions to private chats and posts** (#513, UN-RFC 0048 section 4.3): a
  reaction to a private message someone sent you is itself one, sealed to their
  inbox, with any emoji; changing it is sending another (naming the one it
  changes inside, #599), taking it back is sending an empty one; the latest per
  verified sender counts, anonymous ones never. Yours are kept with your sent
  messages, never shown as messages. In the local API on contact and inbox rows
  (`react`, `reactions`). Also: the `References` of a sealed reaction are inside
  the sealed article, as the RFC says.
- **Export your data** (#577, UN-RFC 0049 section 7): `Session.export`,
  `POST /api/export` and `unseenet export [FILE] [--private]` write a zip with
  your own articles exactly as signed (anyone can check them against your key),
  their files, the sites you write in, your profile and picture, your state and a
  plain `index.html` - never keys. `--private` adds private posts and chats and
  encrypts the whole file with a passphrase (`….zip.sealed`). It says it holds
  only what the nodes still carry and the client kept.

- **Publish a folder as a site** (#538): `client.siteimport.plan(folder)` turns a
  folder of Markdown - and HTML pages, their content without their design - into
  a site's pages: paths made safe (`Guide/First Steps.md` -> `guide/first-steps`),
  titles from front matter or the first heading, raw HTML turned into Markdown,
  links between the files made site links, pictures cleaned of metadata and made
  smaller when too large, limits checked, `.siteignore`; every change in a report
  with file and line. `Session.publish_site` sends only what changed (a new
  version naming the old), `prune` removes pages no longer there, `dry_run` sends
  nothing. CLI: `unseenet site-publish FOLDER SITE [--dry-run] [--prune] [--yes]`.

- **What is new to tell about** (unseenet-gui#126, unseenet-tui#4):
  `Session.notifications()` and `GET /api/notifications` give what has landed in
  For you since a client last asked - private chats and posts, replies and
  mentions; not your own, not reactions, not what was old on arrival - so every
  client notifies alike. The choice (`on`: yes, no, or ask once; `content`:
  sender and excerpt, off by default) is a setting kept with your state, the
  same in every client. No push: only a running client asks.

- **The bootable image's tools have moved to
  [unseenet-bootable](https://github.com/unseenet/unseenet-bootable)**
  (unseenet-bootable#5), with their history: `tools/image/`.

- **The portable builds' tools have moved to
  [unseenet-portable](https://github.com/unseenet/unseenet-portable)**
  (unseenet-portable#6), with their history: `tools/build_portable.py`,
  `tools/portable/`, `tools/tor-version.txt`, Tor Browser's key in
  `tools/keys/`, and the weekly *tor-update* check. `tools/sign_sums.py`,
  `tools/announce.py` and `tools/dev_version.py` stay here; the bootable
  image's `tools/image/` until unseenet-bootable#5.

- **A posting queue** (#569, `Session.posting_queue`): many posts - an importer's,
  a bot's, a gateway's - posted in the order given, each through `Session.post`
  when its turn comes (so its `Date` is the time of posting, UN-RFC 0049), as
  fast as postage and ripening allow, waiting for the next day at a file quota
  and trying again after network failures, with refused posts set aside with
  the reason; kept in a JSON file (0600) or by the caller, with an estimate of
  how long the rest takes.

- **No posting into the past; imported posts keep their original date** (#568,
  #566, UN-RFC 0049). Nodes refuse a `POST` whose `Date` is more than an hour
  old (`441 date`), except an article a moderator validly approves; articles
  from peers are checked against the window as before. A client refused that
  way - an article that waited in a queue, offline or through a long ripening -
  gives it the time of posting and posts it again. Anyone may put the origin
  headers (`Origin-Network`, `Origin-Date`, `Origin-ID`, `Origin-From`) on their
  own posts (`Session.post(origin=...)`, `origin` in the local API's post,
  `unseenet post --origin-network/--origin-date`); messages carry their origin
  and whether they are *old on arrival* (first published more than a day
  before they came in), which are not new and never in For you. Feeds, the
  timeline and threads with imports are ordered by the origin date. **Update
  the nodes first.**

- **The bootable image tells its clients so** (`UNSEENET_BOOTABLE=1`), so they
  leave out what must not happen there, such as saving recovery words.

- **Copy an identity to another device** (#572, UN-RFC 0050 section 3): the
  old device shows a short code (`7-guitar-tunnel`) and a QR code, the new
  device types or scans it, both show the same two check words, and only
  when the user confirms them on the old device are the identities - and,
  unless left out, the closed groups' secrets - sent, straight from device
  to device over a one-time onion service with SPAKE2. Nodes offer the
  meeting point for typed codes (`XUNMEET`, in memory only, never logged).
  In the core (`core/copying.py`, `Session.start_copy` / `receive_copy`),
  the local API (UN-RFC 0046 section 4.19, `/api/copy/...` and `copy`
  events) and the command line (`unseenet copy-to`, `unseenet copy-from`).
  New dependency: `spake2` (pure Python, MIT). UN-RFC 0050 gained section
  3.9, the connection (#583). Update the nodes first: a 0.6 client opens its
  meeting at a node that offers `XUNMEET`.

- **Recovery words** (#573, UN-RFC 0050 section 4): every identity can be
  shown as 24 Unseenet recovery words - its seed, BIP39's English word list
  and checksum - and brought back from them on any device, with the state
  (UN-RFC 0044) read from the network. Closed groups do not come back; the
  client lists them and can ask their owners to invite you again. In the
  core (`core/recovery.py`, `Session.recovery_words`, `restore_identity`,
  `restore_from_network`, `closed_groups_to_rejoin`, `ask_to_be_invited`),
  the local API (UN-RFC 0046 section 4.18, `/api/recovery/...`, and
  `words_written`/`words_reminder` in the state) and the command line
  (`unseenet id-words`, `unseenet id-restore`). The screens come in
  unseenet-gui#142 and unseenet-tui#15.

- **A node that changes what it carries fetches what it refused before** (#543).
  When `new_groups`, `trusted_owners`, `excludes`, `profiles`, `avatars`,
  `sites`, `[blobs]` or a peer's `accept` differ from the last run, the node
  forgets the posts it refused for the old setting, reconciles and pulls from
  its peers again, and fetches the files of stored posts it now carries. No
  more `DELETE FROM refused` by hand.

- **`unseenet passphrase`** (#579): the command line can give the vault a new
  passphrase, as *Change passphrase* in the clients does. The new one is asked
  for twice, or taken from `UNSEENET_NEW_PASSPHRASE` for scripts; copies of the
  vault elsewhere keep the old passphrase.

- **The node's container image** is published for releases only (`:<version>`,
  `:latest`), no longer as `:dev` after every merge; `:dev` comes from a run
  by hand.

- **The portable and bootable builds are made in unseenet-portable and
  unseenet-bootable** (#549, #550), nightly, by hand and for releases; this
  repository no longer builds them. Development builds are
  [there](https://github.com/unseenet/unseenet-portable/releases/tag/dev).

- **The terminal client has moved to [unseenet-tui](https://github.com/unseenet/unseenet-tui)**
  (#548), with its history: `pipx install unseenet-tui` (0.1.0 is the client
  of unseenet 0.5). The `unseenet-tui` command is gone from this package, and
  the `tui` extra now installs unseenet-tui; the portable and bootable builds
  include the terminal client as before.

- **Development builds from unseenet-portable and unseenet-bootable** are
  trusted on the development channel: their release key is pinned next to
  this repository's (#549, #550).

- **Development builds** are made each night when `main` changed, by hand,
  and on release tags - no longer after every merge (#544). Sticks on the
  development channel get at most one update a day.
- **Updating sticks** looks for releases in unseenet-portable and
  unseenet-bootable first, then here, so sticks keep updating when the builds
  move to their own repos (#546). Bundles rebuilt with newer clients
  (`0.6.0.post1`) are offered over `0.6.0`.

## [0.5.0] - 2026-10-25

**Feeds, sites, pictures and files. Update the nodes first, then the
clients.** 0.5 nodes carry what 0.5 clients write - files (blobs), profile
pictures, pinned posts, sites and reactions - and 0.5 clients expect them.
Pre-alpha: there is no compatibility code for older nodes, so a 0.5 client
on a 0.4 node misses these.

- **People:** a *Timeline* of the feeds you follow, **My feed** and **My
  site**, pages, pictures and files in posts, chats and private posts,
  profile pictures, pins, reactions, tables in Markdown, private profiles,
  and `unseenet:` addresses you can copy and open - in the terminal client
  and, with unseenet-gui 0.2, in the graphical one. Your groups, people and
  sent private posts follow you to other devices. New vaults also start in
  `unseenet.chat` and the demo site and feed.
- **Node operators:** files, profile pictures and sites are your choice and
  off until you turn them on in `node.toml`: `[blobs] enabled = true`,
  `avatars = "accept"`, `sites = "accept"` (the installer and the Docker
  image ask). See [configuration](https://unseenet.org/node/configuration/).
- **Bots, gateways and other services:** `Poster.post(..., files=)` and
  `post_article(blobs=)` post with files; require `unseenet>=0.5,<0.6`.

### Added

- **Nodes by name** (#518): a node is shown by its name on the signed
  known-node list; else by its own name from its node information, marked
  *(unlisted)* because anyone can choose any name; else by the start of its
  onion address (`Session.node_name`, `node_label`, `node_entries`). A node
  not on the list is asked its name once while connecting, and the name is
  kept in the vault, cleaned. The TUI's subtitle, *Your nodes*, the group
  list and notices use it, and the status line says *Connected to
  unseenet-node1*. Local client API (UN-RFC 0046 section 4.17): `GET
  /api/nodes` (with `?info=1` to ask each node), `POST /api/nodes` to add,
  remove or make a node the default - the runtime starts and stops watching
  at once - and `node_label`, `node_names` and `status_idle` in `/api/state`
  (`idle` on `status` events, also for a connection to any of your nodes),
  so a graphical client can change node and need not repeat the node in its
  status bar.
- Close a chat (UN-RFC 0044 section 4.2, `closed_chats`, amended): it leaves the
  list of chats on all your devices, the messages stay, and it comes back by
  itself with the next chat line from or to the person (sending opens it
  too). `Session.close_chat`/`open_chat`/`chat_closed`; the local client API's
  `POST /api/chats/close`, and `contacts` in `GET /api/groups` with every
  contact, also those whose chat is closed (UN-RFC 0046 4.3, 4.6). The TUI has
  *Close chat* in its commands, and *Add contact* / *Remove contact* on a
  person's profile.
- Withdrawing chat lines in the TUI: in a chat, where no line is selected, `D`
  withdraws your last line (as `e` edits it), after asking; the question says
  whether it is a post, a comment or a chat line. The command is *Withdraw
  (delete) post*, so the palette finds it by *delete* too.
- Create a group as a feed or a site (UN-RFC 0034 3.2, UN-RFC 0035 3): the TUI's
  Create group offers *Site* besides *Feed* (choosing it makes the group a
  channel, as a site must be, and says who writes it), and Edit group offers
  *Site* for any channel. The local client API's `POST /api/groups` takes
  `view` `feed` and `pages` and `comments`; a channel shown as a feed takes
  comments unless it says `none` (UN-RFC 0046 section 4.7).
- **Reactions** (#510, UN-RFC 0048): one emoji under a post, comment, answer or
  chat line, one per key, changed with `Supersedes` and taken back with a
  cancel. The group owner chooses the set in the manifest (`reactions`: a list
  of up to 12, `[]` for none, or `"any"`); without it, feeds and chats take
  👍 👎 ❤️ 😂 😮 😢 and discussions none. Nodes refuse reactions outside the
  set, a second one from the same key, and reactions to reactions; they hold
  a reaction until its article arrives and drop it when the article goes.
  Clients keep reactions out of threads, chats, feeds and the timeline and
  show them as counts only (`Session.reactions_on`, `react`, `react_permission`,
  `reaction_set`, `who_reacted`), also in closed groups. TUI: ++l++, counts in
  the list, the chat and the reader, and *Reactions* in the group's settings.
  Local client API: `reactions` in a group's head, `reactions` and `react` on
  every row, `POST /api/groups/<id>/react` and `reactions` in the settings
  (UN-RFC 0046 sections 4.3, 4.5, 4.7). CLI: `unseenet react` and
  `--reactions` for `group-create` and `group-edit`. Nodes must be updated
  first. Reactions to private posts come later.

- Tables in Markdown (UN-RFC 0031 section 3.6, amended): GitHub-style tables in
  posts, chat lines, pages, profiles and group rules, with each column's
  alignment; `core.markup` gives a `table` node (`align`, `head`, `rows`, cells
  of inline content, at most 16 columns and 500 rows). The TUI draws them with
  lines (ASCII on the Linux console), cutting long cells with an ellipsis.
- From a person to their feed and site without following them (#506): a
  profile shows *Their feed* and *Their site* when they have them (looked up
  with the profile, in one request) and opens them to read; following stays a
  choice. The TUI opens the selected post's author's profile with `u`, also
  in the reading screen. The local client API's profile has `theirs` (UN-RFC
  0046 section 4.14), and `GET /api/groups/<id>` of a group you do not follow
  fetches it and says when it is here; `Session.personal_groups_of`.
- **My site** as **My feed** (#495): the TUI lists it at the top of the group
  list, or a dimmed *Start my site*, and your own profile has *Start my site* /
  *My site*; `GET /api/groups` gives `my_site` too (UN-RFC 0046 section 4.3).
- `files` (`none`, `pictures`, `pictures+pdf`) when creating a group and in its
  settings in the local client API (#496, UN-RFC 0046 section 4.7), for
  unseenet-gui's *Files* choice.
- **"Add my entrance"** (unseenet-entrance#3, UN-RFC 0043 8.1), as for nodes:
  an issue form; a check that reaches the entrance over HTTPS and its onion,
  compares every file of the web client it serves with the signed version
  (read from its own `/.well-known/unseenet-releases.json` and checked against
  the project key), tunnels to a known node, and looks for the request's
  challenge in `ENTRANCE_CLAIM`; on `accepted`, the entrance goes into
  `entrances.json` and the new list is posted. A **daily check** takes an
  entrance off at once if it serves changed files, after 10 days if it
  fails (a note after 3), and only notes an old version; the project's own
  entrances get an issue instead. Docs: *Being listed*.
- Encrypted files (#497, UN-RFC 0027 sections 3.3, 4.3, 4.4, 5.3): pictures and
  files in closed groups and in private posts and chats, each file encrypted
  with a fresh key that travels inside the encrypted article; members check the
  inner headers against `Blobs` and the group's types before showing them.
  Submissions to moderated groups carry their files to the moderators
  encrypted, and the approving moderator checks and uploads the plain ones.
  New inboxes take pictures (up to 4 MiB each), older ones are given them, and
  *Pictures in private posts* in the TUI's commands turns it off
  (`Session.set_inbox_files`). The TUI attaches files when writing a private
  post, and with Ctrl+F in a chat with a person; the local client API takes
  `files` on `POST /api/private` (UN-RFC 0046 section 4.4). Encrypted blobs
  are carried only by nodes whose operator turned on `encrypted`. (Reviewed
  in #502, but landed on main inside the squash merge of #503, commit
  f39bfbb, whose title names only "Add my entrance".)
- Pictures where they were forgotten (#496): a new personal feed or site
  takes pictures by default (up to 4 MiB each; `feed-start`/`site-start
  --no-files` for none), and the TUI offers it once for one made before.
  Creating and editing an open group or a channel in the TUI has a *Files*
  choice: none, pictures, or pictures and PDFs (`core.blobs.FILE_CHOICES`).
  Chat lines carry files (UN-RFC 0028 section 6.1): `send_chat(files=...)`,
  and in the TUI Ctrl+F in a chat attaches files to the next line; a chat line
  names its files.
- Your own feed where people look for it (#495): the TUI lists **My feed** at
  the top of the group list, under For you and Timeline (and not again further
  down), or a dimmed **Start my feed** until you have one. Profiles get buttons:
  your own *Start my feed* / *My feed*, someone else's *Follow* / *Following*
  and *Their feed*. `Session.has_personal_group` and `Session.is_following` for
  every client.
  The local client API's `GET /api/groups` gives `my_feed` and leaves a
  started one out of `hierarchies` (UN-RFC 0046 section 4.3), for unseenet-gui.
- The demo (#385, #388): the project's list of its groups endorses the demo's
  groups `unseenet.demo.*`, owned by the demo key (unseenet-demo); new and
  existing clients start following the demo's site and its shared feed
  (starter groups, version 3).
- The TUI writes pages (#212, UN-RFC 0035 section 9.2), as unseenet-gui does: in a
  site, `n` writes a new page and `e` a new version of the selected one, with
  its path, title, Markdown and pictures, and a preview (Ctrl+O) as readers
  will see it; it warns before writing over a path or past `max_pages`. The
  commands add Start my site, Previous version of this page and Remove this
  page. Only the site's writers get them.
- Addresses on the web (#454, UN-RFC 0031 section 3.4.1): every client reads
  `web+unseenet:` and the web form `https://<any host>/a/<...>` as the
  `unseenet:` address it stands for, and opens it in the network over Tor -
  the host is only a hint. `core.addresses.web_address` writes the web form on
  a listed web entrance, without `n=` hints. The TUI shows both forms when you
  copy an address and opens the web form with `j`; the local client API gives
  `web` in `/api/address` (UN-RFC 0046 section 4.13).
- A site's `index` field (UN-RFC 0035 section 3): `yes` or `no` (the default),
  whether search engines may index it when an entrance shows it on the web;
  `unseenet group-create`/`group-edit --index`.
- A client's own settings in the local client API (unseenet-gui#84, UN-RFC
  0046 section 4.8): `GET/POST /api/settings/clients/<client>`, kept with your
  state so a front end's theme follows you; and `state_local` in
  `/api/settings`, to keep your state on this device only (UN-RFC 0044 7.4).
- Private profiles in the local client API (#442, UN-RFC 0046 section 4.16,
  UN-RFC 0022 section 6): `POST /api/profile/share` shares a profile with one
  person or a closed group, or takes it back; `GET /api/profile` with
  `context` gives the profile shared there, never one from another context.
- Sites and pages in the local client API (#442, UN-RFC 0046 section 4.15,
  UN-RFC 0035): a site's pages in force with the home page first; one page
  with its links within the site resolved to `unseenet:` addresses; writing,
  removing and restoring the previous version of a page, as a job;
  `GET/POST /api/site` for your personal site; `pages` as a view of a site.
  `core.pages.resolve_link` and `core.markup.page_body` give every client the
  same links within a site. A job that the core refuses now ends as failed.
- Files on posts from bots and gateways (#474, UN-RFC 0027): `Poster.post(...,
  files=[...])` takes paths, `(name, octets)` or `(name, octets, alt)`, prepares
  them as the clients do (type from the content, pictures cleaned of metadata),
  checks them against the group's manifest before any postage is computed, and
  sends them as blobs with the post through `Session`. `Session.post_article`
  takes `blobs` and `extra_bits` for this. Documented in `docs/bots.md`.
- Feeds in the local client API (#442, UN-RFC 0046 section 4.14, UN-RFC
  0034): a group can be shown as a feed, with `comment` on each row (may you
  answer it with a chat line); the timeline as the pseudo-group `timeline:`,
  every followed feed's entries newest first with their comments under them;
  `GET/POST /api/following` to follow and stop following people and feeds;
  `GET/POST /api/feed` to start your own feed after the warning; and a
  profile says whose feed it is and whether you follow them. A group shown
  as a feed is laid out by `Session.feed_rows()` in every client: each note its
  own entry, entries newest first by date, comments under them.
- Addresses in the local client API (#442, UN-RFC 0046 section 4.13, UN-RFC
  0031 section 3.4.1): a group's head, each of its posts and every profile
  carry their `unseenet:` address, and `GET /api/address` says what any
  address names - an identity, a group, a post or a page, the older
  `unseenet:join?g=` form too - and whether your nodes have it.
- `unseenet:` addresses in the terminal client and the command line (#357,
  UN-RFC 0031 section 3.4.1): invitations are written as
  `unseenet:<group-id>?n=<onion>`; Join (j) takes every form - a group ID, a
  group's, a post's (selected in its group) or a person's address (their
  profile, if the client has met the key), and the older `unseenet:join?g=`;
  Address of this post and Address of this group in the command palette show
  the address and copy it where the terminal allows.
- Pinned posts in the terminal client (#442, UN-RFC 0033 section 7): a Pinned
  section above the threads, newest pin first with its note, folded away with
  Enter on its head; pinned posts and chat lines marked `[P]`; a pinned line
  above a chat with "Next pin"; and in the command palette "Pin or unpin
  post", "Pinned posts" and "Show or hide the pins". Pinning warns when the
  group is full, and unpinning a post older than the window that it then
  disappears from the nodes.
- Pinned posts in the local client API (#442, UN-RFC 0046 section 4.12,
  UN-RFC 0033): a group's head lists the pins in force with each pinned
  post's subject and author, `max_pins` and `may_pin`, every row says
  whether it is `pinned`, and `POST /api/groups/{id}/pin` pins or unpins a
  post with an optional note. A pin of a post beyond the group's window is
  marked `beyond_window`, for a front end to warn before unpinning it.
- Pictures of people in the local client API (#442, UN-RFC 0046 section
  4.11): every post's row has its author's identicon, `GET /api/pictures`
  answers the pictures and identicons of many keys - read together with
  the other authors' and decoded in a separate process, null for hidden or
  ignored keys or with the new setting `pictures` off - and `POST
  /api/profile/picture` shows your picture as it would be published,
  publishes it or removes it; your profile says which is published and the
  warning before the first. `Session.pictures()`, `make_picture()`,
  `my_picture()` and `show_pictures()`.
- Files in the local client API (#442, UN-RFC 0046 section 4.10): posts list
  their files in `attachments`, a group's head says what files it takes
  (`files`) and whether its node carries them (`node_files`), `GET
  /api/groups/<id>/files/<blob>` answers a picture checked, decoded and
  saved again by the runtime (or with `?save=1` the file itself, to save),
  and a post can carry up to four files with their alternative text.
- Files on posts can be read, not only sent (#442, UN-RFC 0027 sections 6.4
  and 9.2): `BLOB` for readers (`Client.blob`), `Session.fetch_blob()`, which
  checks a file against its blob ID and size before anything else, and
  `Session.picture()`, which decodes a picture in a separate process with
  limits on memory, CPU time and open files and no files written, refuses
  more than 50 megapixels or 1000 frames, and saves it again in the same
  format (`client.decode`). SVG and PDF are never decoded; pictures by people
  you ignore are not decoded unless you ask. A post now knows its files
  (`Message.attachments`: name, type, size, alternative text, size in
  pixels), and `Session.node_files()` says whether a group's node carries
  files. Posted files carry their alternative text and size in pixels
  (`Prepared.alt`, `dim`). The TUI lists a post's files with their
  alternative text, and `f` saves them in your Downloads folder, unopened.
- The CLI is one more client on `Session`, like the TUI and the GUI
  (#387, part 1): `group-create` with views, posters, moderators, files,
  pins and site settings; `group-edit` for roles, bans and settings in one
  new manifest; `group-show`; `withdraw` for several posts, or `--all` in a
  group you own or moderate; `--json` for scripts; `-i` acts as an identity
  for the run without changing the vault's default. `Session` gains
  `withdraw()`, `withdraw_all()` and the manifest fields of 0.5.0 in
  `create_group()`/`update_group()`.
- Writing from the command line goes through `Session` (#387, part 2):
  `unseenet post` with `--reply-to` (replies, and comments in channels),
  `--kind chat`, `--edit`, `--format`, and `--attach` for real: up to four
  files, checked against the group, sent as blobs with the post. Pictures
  are saved again without their metadata first - GPS, time, camera, owner,
  comments, colour profile - turned the way they were shown, animations
  kept (`client.media`, the same for every client). `Session.post(files=)`
  and `prepare_files()`; Pillow is a new dependency. A node that carries no
  files, or a group that takes none, is said plainly.
- Pins, sites and personal groups from the command line (#387, part 3):
  `pin`, `pins`, `page-put`, `page-remove`, `pages`, `feed-start` and
  `site-start`. In the core, new parts of `Session`: `kept.py` (`pins()`,
  `pin()`, `site()`, `put_page()`, `remove_page()`, worked out with the
  rules the nodes use, from markers and page articles now kept as they are
  read) and `personal.py` (`start_personal_group()` and the warning UN-RFC
  0029 asks for). The core of #193 and #212 for every client.
- A personal feed or site is named after its owner - "Andreas~42e5's feed",
  not "feed" - and a followed person keeps the name seen in their posts
  across commands and restarts, not "?~42e5" (#423).
- CI: the tests run on main and on pull requests - no longer a second time for
  every pushed branch - and not for changes to the docs or RFCs only (#392).
  The portables, the bootable image, Docker and the docs already built only
  when their own inputs changed.
- Starter groups come in versions (#388): a vault takes each version's
  groups once, so groups added later reach those who started earlier - and a
  group they left is never added again. Version 2 adds `unseenet.chat`; the
  demo's groups follow when the demo moves to `unseenet.demo`.
- A new group's posts no longer wait an hour at a peer that has not got its
  manifest yet (#384): a manifest goes to peers without the random delay,
  and a post that still arrives first is answered "try later" (431) for up
  to 15 minutes instead of being refused.
- TUI: "Key ripening" in the palette pauses and resumes ripening, and says
  what it is; the subtitle shows "(ripening paused)", or that the key is as
  ripe as the machine allows (#358, #440). Your own chat line shows at once,
  dimmed, "sending ...", then the real one - or red, "not sent" (#325).
  "Your state" keeps it in the network or on this device only (UN-RFC 0044).
- TUI: feeds (#207). A **Timeline** under "For you" - the entries of the feeds
  you follow, newest first, nothing reordered; a group shown as a **feed** -
  entries newest first, comments under each, two levels, marked ↳; `v` goes
  threads → feed → chat. In the palette: **Follow** (the selected post's
  author, or anyone by key or name), **Following** (and stop), **Start my
  feed** (after saying it is public). The rows come from the core
  (`Session.feed_rows`, the pseudo group `TIMELINE`), so the GUI can show the
  same.
- TUI: files and pictures (#149, #155). Where a group takes files, the compose
  dialog has a Files field (paths, comma between); pictures are cleaned of
  their metadata before they are sent. Edit profile takes a picture file,
  published as your profile picture - the middle square, at most 128 px, no
  metadata. Reading and saving files (f) was there already.
- Registered names (`@lorensen`) are renewed by themselves in their last 30
  days, as key-bound groups and names given under yours already were (#424):
  a `renew` claim in the background, once per name per run and not while one
  is on its way - so nobody loses a name, and every name under it, by
  forgetting. Domain names need nothing.
- TUI: a site is shown as its pages (#212) - one row a page, the home page first
  (⌂), each with its path; choosing one shows it, Markdown and all; `v`
  switches a site between pages and threads. Writing pages stays with the
  command line (`unseenet page-put`) for now.
- Root list: `torproject` and `tor` are reserved for the Tor Project (#335), so
  nobody - the project included - can look as if it speaks for it; theirs to
  claim when they want it.
- Nodes tell the operator when the contact inbox has new messages (#135): it
  counts them without reading them - in `unseenet-monitor` (c: seen), as a
  warning in `unseenet-node status`, and through an optional `[operator]
  notify` command run on new ones (counts only, no shell), to pass on to ntfy,
  Home Assistant or e-mail. Not in the daily health check: it sees only what is
  public, and the number of reports a node gets is not.
- **Private profiles** (UN-RFC 0022 section 6, #182): share a profile with one
  person or a closed group only - for those who want no public profile, or
  another one for friends. It is read only by them, shown only there, marked
  "shared with you" or "with this group", never elsewhere; an empty one takes
  it back. `Session.share_profile`, `withdraw_shared_profile`,
  `private_profile(key, context)`; in the TUI, "Share my profile" and "Take
  back my shared profile" in the palette.
- TUI: "Copy address" gives the `unseenet:` address of the post, page, group or
  person you are on (and puts it on the clipboard where the terminal lets it);
  "Open address" goes to one - a group (following it if you say so), a post or a
  page with the cursor on it, or a person to follow (#357).
- **Your sent private posts follow you too** (UN-RFC 0009 2.3, 0044 6, #257
  step 4): a private post can carry two envelopes (`sealedbox2`) - one for the
  recipient, one for you - so any device of yours reads it again from the
  recipient's inbox (the sent list goes with your state). Nobody can tell
  whether you kept a copy: both forms are the same size. Used only where both
  ends can - the recipient's inbox says `sealedbox2` (clients set it once all
  their nodes take it) and your node lists `UNSEENET-SEALEDBOX2`; otherwise
  the old form, with the copy in your vault as before. Nodes take both forms.
  Inbox bodies are wrapped in fixed 76-character lines (textwrap broke at the
  `-` of base64url, so the size varied).
- Each kind of client has its own settings, kept with your state:
  `Session.client_setting(client, key)` / `set_client_setting`. The TUI keeps
  the theme you choose in the command palette there, so it is there next time
  and on every device (the GUI follows, gui#84).
- **Your state follows you** (UN-RFC 0044, #257 step 3): the groups and people
  you follow, contacts, ignored keys, hidden profiles, settings and read marks
  are kept, encrypted with a key from your seed, in `state@<fp>` - padded to
  4, 8 or 16 KiB - and merged with what the network has whenever a client
  starts and refreshes; written at most once an hour, and not for read marks
  alone. A new stick or phone with the same key looks like the old one after
  one fetch; its own defaults never overwrite what was set elsewhere. Per
  identity it can be kept local (`Session.set_state_kept_local`), which
  removes the group. `core/state.py`, `client/session/state.py`,
  `ClientRuntime.sync_state`.
- Nodes carry `state@<fp>`, an identity's encrypted state (UN-RFC 0044, #257
  step 2): a key-bound group of the new type `state` that has only its
  owner's manifest - at most 24 KiB, at most once an hour (`441 too soon`),
  no articles - accepted whatever the node's policy for new groups.
- Key ripening keeps within the machine's memory (#440): proving a segment
  takes about 0.7 octets an iteration, so clients ripen to **level 3** by
  default (where the surcharge ends; level 4 needs several GB), choose
  shorter segments to fit the memory free - a container's limit too - and
  stop at the level the machine can reach, saying so; one large ripening at
  a time per machine (a lock). `client/machine.py`, `ripening.memory_for`,
  `fitting_segment_length`, `reachable_level`; `UNSEENET_RIPENING_MEMORY`
  (MiB) sets the budget. UN-RFC 0025 sections 3.2 and 7 say a client may.
- `unseenet read` goes through `Session` too, and `--json` gives each post's
  author, date, references, kind, page and blob IDs (`Message.blobs`, new);
  `withdraw --all --keep-author KEY` leaves the posts by some keys
  (`Session.withdraw_all(keep_authors=)`). For unseenet-demo's weekly run (#385).
- A personal feed or site can carry pictures: `feed-start --attachments
  MAX_SIZE [--types image/*]`, also for one started without
  (`Session.start_personal_group(attachments=)`). Found by the demo (#385).
- Images in Markdown point at real blobs (UN-RFC 0031 section 3.5, #427):
  `![alt](blob1:...)`, the blob ID of UN-RFC 0027, which must be one the
  article carries (`markup.only_carried_images`); the old `blob:<hex>`, which
  no blob ever had, is gone. Pages can carry their pictures:
  `Session.put_page(files=)`, and `unseenet page-put` turns
  `![alt](file:photo.jpg)` into a cleaned, attached, pointed-at picture.
- `unseenet id-import NAME` adds an identity from its seed, read from stdin
  so it never shows in the process list (for unseenet-demo, #385); `id-new`
  and `whoami` answer in JSON too.
- Profiles, following and addresses from the command line (#387, part 4):
  `profile` (with `feeds`, UN-RFC 0022 4.5, and a picture cut square, made
  small and cleaned of metadata), `follow`/`unfollow` a feed or a person
  (by key, fingerprint, address or name; their personal groups and the
  listed feeds that are really theirs, kept up to date), `following`,
  `timeline` (newest first, as written), `address` and `open`. In the core:
  `Session` part `following.py`, `publish_picture_file()`,
  `core.addresses` (every `unseenet:` form, older ones read), `feeds` in
  `core.profiles`, `client.media.avatar()`. The core of #207, #155 and #357.
- Background ripening can be paused and resumed: `ClientRuntime.pause_ripening()`
  and `resume_ripening()`, and in the local client API `POST /api/ripening`,
  `"paused"` in the state's `ripening` and a `ripening-paused` event
  (UN-RFC 0046, #337). A pause lasts for the run; a post that needs a riper
  key still ripens what it needs.
- The local client API has what unseenet-gui served on its own (#320): a
  group's `write` and each row's `reply` (may you write, and if not, why),
  `POST /api/passphrase`, and for profiles the label, whether you hid it,
  `POST /api/profile/hide`, publishing from a form's fields, and for yours
  whether one is published and the warning before the first. Opening
  someone's profile reads the authors' profiles together, so a node cannot
  tell whose you open. The warning is `profiles.PROFILE_WARNING`, used by the
  TUI too (UN-RFC 0046).
- Groups can be shown as a feed (`view: feed`, UN-RFC 0034) or, for
  channels, as pages (`view: pages`, UN-RFC 0035). `feed@<fp>` and
  `site@<fp>` are key-bound personal groups (UN-RFC 0029 section 2.1):
  nodes accept them only as channels with that view, and do not list
  them (#359). **Nodes must be updated** before clients create them.
- Emoji for pickers, the same in every client (#362): `emoji.json` also
  has gemoji's categories and names, `markup.emoji_categories()`,
  `emoji_names()` and `find_emoji()` rank suggestions, and the local client
  API serves them as `GET /api/emoji` (UN-RFC 0046 section 4.4).
  `tools/emoji_data.py` makes the file from gemoji's database.
- Nodes keep pinned posts (UN-RFC 0033) beyond the group's window, the
  first kind of kept articles (UN-RFC 0017 section 2.1): `Control: pin`
  and `unpin` by the owner or a moderator, the manifest field `max_pins`
  (0-25, default 5), and a pin that arrives before its post. Kept articles
  are not expired, are listed with the group's state, and are accepted
  when older than the window, so a new node gets them by pulling. A pin
  or unpin names the one it replaces (`Supersedes`), so a quick undo is
  not decided by the rounded `Date`, and a pin follows an edit of its
  post (#361).
- Blobs, part 1 (UN-RFC 0027, #370): blob IDs, the `Blobs` and
  `Attachment-<n>` headers, the manifest field `attachments`, the postage
  extra for files, and the rules every node checks. A node carries blobs
  only when its operator turns them on in `node.toml` (`[blobs]
  enabled = true`); it then offers `UNSEENET-BLOB`, stages uploads with
  `BLOBPOST` per connection, keeps them when the article is posted, and
  serves them with `BLOB`. Blobs are files in `blobs/` next to the
  database.
- Blobs follow their article (UN-RFC 0027 section 6.3, #374): a blob node
  that gets an article with blobs from a peer fetches them from that peer,
  then from others carrying the group, before passing the article on, and
  after 10 minutes passes it on without them. `BLOB` answers `436 try
  later` meanwhile.
- Keeping and removing blobs (UN-RFC 0027 sections 7, 8.1, #377): a blob
  goes when no stored article references it (expiry, cancels, edits), and
  after `[blobs] retention_days` unless a kept article such as a pinned
  post references it. Operators refuse a blob with `unseenet-node
  --refuse-blob ID`, and may follow refusal lists from `refusal_keys`
  (none by default). Daily quotas per key and group (`daily_per_key`,
  `daily_per_group`): `441 quota` for the node's own clients; from peers
  the article goes on without its files. A pin is refused when its post's
  blobs would take the group's kept blobs above 8 MiB (UN-RFC 0017 2.2).
- Operators see and choose blobs (#380): node info has `policy.blobs`, the
  monitor shows the files a node keeps, and `install-node.sh` asks whether
  to carry pictures and small files and profile pictures (recommended:
  yes; `UNSEENET_BLOBS`/`UNSEENET_AVATARS` answer beforehand, and
  without a terminal both stay off). The Docker image takes the same
  variables, off by default. `unseenet post --attach FILE` posts with a
  file, as a tool for testing nodes.
- Nodes carry sites (UN-RFC 0035, #382): channels with `view: pages`,
  page articles with a `Page` path, new versions with `Supersedes` by any
  of the site's writers, `max_pages` and `home`. A node keeps each page's
  current and previous version beyond the window, so a page falls back
  when its writer is removed, and a new node gets the whole site by
  pulling. Off unless `sites = "accept"`; the installer and Docker ask.

### Fixed

- Editing a feed or a site in the TUI no longer turns it into a discussion:
  the settings know the `feed` view, and `pages` for a site.
- Editing a post with files (UN-RFC 0042) dropped them: the new version now
  carries the files of the earlier one unless new ones are given (#496).
- The TUI's Join (`j`) opens a page address at its page, instead of saying the
  client does not show pages (they are shown since #473).
- Stopping and starting ripening quickly could let the old run remove the
  new run's file, so the new segment stopped at once (#337).

### Changed

- The TUI's footer shows the keys of the view you are in (#490), the same as the
  graphical client: Space goes to the next unread post or entry, f reads, v is
  "View" (threads, feed, chat; or pages), and on a site New post and Reply are
  hidden.
- A paused key ripening stays paused over a restart until you resume it (#337):
  kept with the key in the vault, on that device only. The TUI says so, and the
  local client API (UN-RFC 0046 section 4.1) keeps it the same way.
- The project's bot channels are feeds by default and take pictures (#475):
  `tools/project/create_groups.py` sets `view: feed` for the six of them and
  `attachments` (`image/*`, 512 KiB) for all but The Conversation.
- `Session` is split into files by area (`client/session/`: base, ripening,
  nodes, labels, groups, private, profiles, people, reading, posting), each
  with a docstring saying what belongs there, joined into
  the one class clients use as before (#390). Code moved only.
- The node server is split into files by area (`node/server/`): the
  accept pipeline and the rules of each kind of article (postage,
  manifests, controls, kept articles, blobs, blocks, edits, forwarding) for
  `Node`, and the commands by area for `Session`, each with a docstring
  saying what belongs there (#394). Code moved only.
- The command line is split into files by area (`cli/`: node, basics,
  groups, messages, network, services, main), each with a docstring saying
  what belongs there (#396). Code moved only.
- The node's store is split into files by area (`core/store/`: base,
  articles, groups, key-bound, kept, blobs, withdrawals, peers, stats),
  each with a docstring saying what belongs there (#398). Code moved only.
- The local client API is split into files by section of UN-RFC 0046
  (`client/localapi/api/`), so a section and its code find each other
  (#400). Code moved only. `tools/dev/check_globals.py` checks that every
  global name a function in a package uses exists in its file.
- Every public `Session` function has a docstring - what it does, what it
  returns, when a client uses it - and a test keeps it so (#402). So does
  every public function of the local client API (each naming its route and
  its section of UN-RFC 0046, #404), the node, its NNTP commands (syntax,
  answers, RFC), the store and the command line (#407).
- The site has a Developers section (#405): how to write a client on
  `Session` or the local client API, a map of the code and where new code
  goes, and a Session and local API reference generated from the
  docstrings (mkdocstrings), and a Node reference: the accept pipeline, the
  commands and the store.

## [0.4.4] - 2026-10-23

A fix for front ends of the local client API, from the new `release/0.4`
branch. Nodes can stay on 0.4.0.

### Fixed

- `GET /api/known-nodes` answers during setup too, so a new user of a front
  end like the graphical client can choose a node from the list instead of
  only typing an address (UN-RFC 0046 section 4.3, #372).

## [0.4.3] - 2026-10-23

0.4.2 with portable builds: chiavdf 1.2.0 came out during that release and
broke the Windows build. Nodes can stay on 0.4.0.

### Fixed

- The portable build for Windows could not ripen keys with chiavdf 1.2.0,
  which keeps its DLLs in `chiavdf.libs`. The build now takes them from
  there as well (#332). 0.4.2 has no portable files because of this.

## [0.4.2] - 2026-10-23

For clients, and what the browser client needs to ripen its keys; nodes can
stay on 0.4.0. A new key now reads at once while it ripens, and its first
post no longer fails when the background ripening ran at the same time.

### Added

- `Session._prove_segment()`: one place where a platform without threads
  can prove key-ripening segments its own way. The browser client proves
  them in a Web Worker of its own (unseenet-entrance#27). The portable client,
  GUI and TUI work as before (#323).

### Fixed

- A brand-new key that posted while the client ripened it in the background
  could fail with "ripening stopped before the key could post", and the
  background ripening stopped until the next start. Both had proved the same
  segment, and the second to finish read the chain having grown as a stop.
  It now counts as progress, and both go on (#326).
- A brand-new key on a node that asks for ripening saw its groups without
  posts for minutes: the client set up its inbox, which waits for the key to
  ripen, before it fetched any group. The groups are now fetched meanwhile
  (#328).

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

[Unreleased]: https://github.com/unseenet/unseenet/compare/v0.6.6...HEAD
[0.6.6]: https://github.com/unseenet/unseenet/compare/v0.6.5...v0.6.6
[0.6.5]: https://github.com/unseenet/unseenet/compare/v0.6.4...v0.6.5
[0.6.4]: https://github.com/unseenet/unseenet/compare/v0.6.3...v0.6.4
[0.6.3]: https://github.com/unseenet/unseenet/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/unseenet/unseenet/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/unseenet/unseenet/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/unseenet/unseenet/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/unseenet/unseenet/compare/v0.4.4...v0.5.0
[0.4.4]: https://github.com/unseenet/unseenet/compare/v0.4.3...v0.4.4
[0.4.3]: https://github.com/unseenet/unseenet/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/unseenet/unseenet/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/unseenet/unseenet/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/unseenet/unseenet/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/unseenet/unseenet/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/unseenet/unseenet/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/unseenet/unseenet/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/unseenet/unseenet/releases/tag/v0.1.0

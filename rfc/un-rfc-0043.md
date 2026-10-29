```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0043                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.4.0, unseenet-entrance 0.1.0, unseenet-entrance 0.3.0
Updates: 0000, 0007

             Unseenet: Web Entrances and Clients on the Open Web
```

# Abstract

Many people will never install a program or boot from a stick before
they have seen what a network is like. This document lets them reach
Unseenet from an ordinary browser on the open web. A **web client** is
a page that does all the work with keys in the browser: it opens the
vault, signs, encrypts, decrypts and pays proof-of-work. A **web
entrance** is a server that passes the browser's ONNTP session to a node
over Tor and does nothing else. It never sees a passphrase, a private
key or the plaintext of a closed group.

This access is less hidden than the real clients, and the document says
so plainly: the entrance sees the visitor's IP address, and the visitor
must trust the code the page is served with. What does not change is
what makes Unseenet worth using: groups and nodes cannot be removed by
anyone, and no one can delete or change someone else's signed post.

# 1. Motivation

The portable and bootable clients (UN-RFC 0001) hide who talks to whom.
They also ask a lot of a newcomer: download, unzip or flash, start. A
person who just wants to look will go back to Discord instead.

Old Usenet had web entrances, and many people only ever knew it through
one. That was also a lesson: when the convenient way becomes the only
way most people know, its operator holds the network in practice. This
document therefore keeps the web entrance as thin as possible, makes it
replaceable, and keeps the real clients the documented path for anyone
who needs to be hidden.

# 2. Terms

- **Open-web access**: using Unseenet from a browser without Tor.
- **Web client**: the code a browser runs to use Unseenet: the same
  user interface as the graphical client (`unseenet-gui`), with a
  transport that talks to a web entrance instead of a local Tor.
- **Web entrance**: a server that accepts WebSocket connections from web
  clients and carries each one, byte for byte, to an onion service node
  over Tor. Not to be confused with a **gateway** (UN-RFC 0023), which
  carries posts between Unseenet and another network; a web entrance
  only lets a browser into Unseenet itself.
- **Hidden-only identity**: an identity in a vault marked so that web
  clients refuse to use it (section 6.3).

# 3. What Changes and What Does Not

| | Real client (portable, bootable) | Web client, open web | Web client in Tor Browser |
|---|---|---|---|
| Groups and nodes can be removed by someone | No | No | No |
| Others can delete or change your signed posts | No | No | No |
| Nodes learn your IP address | No | No | No |
| The entrance learns your IP address | (no entrance) | **Yes** | No |
| You must trust code served to you | Once, on download, signed | **Every load** (section 7) | **Every load** (section 7) |
| Keys stay on your stick or in memory | Yes | In the browser (section 6) | In the browser (section 6) |
| The access point can be blocked | Hard (Tor, bridges) | **Each entrance easily**, many entrances less so (section 8) | Hard |

Everything below the network layer is unchanged: a post from a web
client is an ordinary signed article, and nodes cannot tell it from any
other.

# 4. The Web Entrance Protocol

## 4.1 One Tunnel per Connection

A web client opens a WebSocket over TLS to the entrance:

```
wss://entrance.example/onntp?node=<56-character v3 onion address>
```

The entrance opens a connection over Tor to that onion address on the
ONNTP port (UN-RFC 0005) and copies bytes in both directions until
either side closes. Each WebSocket binary message carries an arbitrary
run of bytes; the ONNTP line protocol is unchanged and runs inside. The
web client speaks to the node exactly as a portable client would,
including node authentication where the node uses it.

A web entrance:

- MUST connect only to v3 onion addresses, and only on the ONNTP port -
  or, for copying an identity, as section 4.5 says. It MUST NOT reach
  any address on the open web, so that it cannot be used as an open
  proxy.
- SHOULD connect only to nodes on a list of known nodes (UN-RFC 0010)
  or nodes its operator has added, and MAY refuse others.
- MUST NOT read, parse, change or add to the ONNTP stream. It MUST NOT
  add headers to articles; there is no field that marks an article as
  coming from the web.
- MUST keep the Tor circuits of different web-client sessions apart, so
  that a node cannot link two sessions through the entrance's circuits
  (section 4.1.1).
- MUST NOT cache articles, groups or answers. An entrance that caches is
  a node, and should be run as one.

### 4.1.1 One Circuit per Session

A web-client session holds several connections: one to each node it
uses and one watch connection to each (UN-RFC 0008). Unseenet's own
clients reach a node over one circuit for all of them. A web entrance
does the same per session, and keeps sessions apart:

- A web client SHOULD add a session tag to the URL,
  `&session=<tag>`, where the tag is at least 128 random bits in
  base64url. It makes a new tag every time a session starts (a vault
  is opened, or the page is loaded) and MUST NOT store it.
- The entrance MUST derive the SOCKS credentials of a tunnel from an
  HMAC, under the key of section 4.2, of the visitor's address and the
  tag. Tunnels from the same visitor with the same tag then share a
  circuit; tunnels of another session, or of another visitor who sends
  the same tag, never do.
- A tunnel without a tag, or with one that is not well formed, MUST get
  a circuit of its own (random credentials).

Two connections of one session reach the same node in any case, and the
node already sees them come from one client. Giving each its own
circuit would hide nothing from the node and doubles the circuits the
entrance and the node must build, which is what costs them most
(section 5.1).

## 4.2 Limits

An entrance MAY limit connections per visitor and in total. It MUST do
this without storing addresses: counters are kept in memory only, keyed
by an HMAC of the address under a key made at start and never written
down, and dropped after at most one hour.

Many visitors share one address: a household, a school, a workplace, a
mobile network behind carrier-grade NAT. A limit per address SHOULD
therefore be counted in sessions (distinct tags, section 4.1.1) rather
than tunnels, and SHOULD allow many sessions per address; it is there
to stop one visitor from taking the whole entrance, not to allow one
person per address. The total limit SHOULD follow from the memory the
entrance has (section 5.1). An entrance refuses with HTTP 429 before
the WebSocket is opened, so that the client can tell a full entrance
from a broken one and try another (section 8.3).

## 4.3 Entrance Information

An entrance SHOULD answer `GET /.well-known/unseenet-entrance` with a JSON
object:

```json
{
  "operator": "@lorensen",
  "contact": "inbox:<identity fingerprint>",
  "onion": "<the entrance's own onion address, if it has one>",
  "nodes": "known",
  "statement": "memory only, no logs, no third-party proxy"
}
```

`nodes` is `"known"` (only listed nodes) or `"any"`. An entrance that
relays the copy of an identity (section 4.5) adds `"copy": true`;
without it, or with `false`, a web client does not offer to receive a
copy. The web client shows this information on its About page. It is a
promise, not proof (section 5).

## 4.4 Reconnecting

When an entrance restarts or loses its Tor connection, every web client
on it loses its tunnels at the same moment. If they all reconnect at
once, the entrance and the nodes must build every circuit in the same
few seconds, which is the most expensive thing they do (section 5.1).

A web client therefore MUST NOT reconnect at once after a tunnel
closes that it did not close itself. It SHOULD wait a random time,
first between 1 and 30 seconds, then twice as long after each attempt
that fails, at most 5 minutes, and start again from the shortest wait
once a tunnel has stayed open for a minute. An HTTP 429 from the
entrance (section 4.2) counts as a failed attempt; after a few, the
client moves to another entrance (section 8.3).

## 4.5 Copying an Identity

A web client can receive a copy of an identity from another device
(UN-RFC 0050 section 3.8). The other device listens on a one-time onion
address, which is on no list of nodes, on virtual port 9119 (UN-RFC
0050 section 3.9). An entrance MAY relay that one connection:

```
wss://entrance.example/copy?onion=<56-character v3 onion address>&session=<tag>
```

An entrance that does:

- MUST connect only to a v3 onion address, and only on port 9119, for
  this endpoint, whatever its node setting (section 4.1).
- MUST allow at most one copy connection per session at a time, and
  count it in the session's limits (section 4.2).
- MUST close the connection after at most 10 minutes, the code's
  lifetime (UN-RFC 0050 section 3.2), and after at most 2 MiB in each
  direction: a copy is a few messages of at most 64 KiB and one of at
  most 1 MiB (UN-RFC 0050 section 3.9).
- MUST NOT read, keep or log what passes, as for every tunnel. It sees
  only SPAKE2 messages and ciphertext: the code never reaches it, and it
  cannot open the copy or take the identity.
- SHOULD let its operator turn it off, and says whether it is on in its
  information (section 4.3).

The entrance learns that a visitor received a copy, and the one-time
address, which is never used again. The other device's onion service
hides where that device is from the entrance as from anyone.

# 5. Operating a Web Entrance

A web entrance sees every visitor's IP address and when they are
online. Nothing in this protocol can stop an operator from recording
that. The obligations below are what an operator promises, and the
reason the entrance is kept so thin is that there is little else to
promise.

An operator of a web entrance:

- MUST run the entrance so that nothing about visitors is written to
  disk: no access logs, no connection logs, no error logs naming
  addresses, no core dumps. The RECOMMENDED setup is a host or
  container whose writable storage is in memory only (tmpfs) and whose
  logging is turned off at every layer: reverse proxy, entrance, Tor,
  system journal.
- MUST NOT put the entrance behind a service that ends TLS on someone
  else's machine (a CDN or a proxying DNS service). That party would
  see every address and the whole ONNTP stream. DNS for the entrance's
  name MUST point straight at the entrance.
- MUST NOT add analytics, trackers or content from third parties to
  the page.
- SHOULD also offer the entrance and the page as an onion service, for
  visitors who use Tor Browser.
- SHOULD publish the entrance's configuration, so others can see what it
  runs.

A web client MUST treat the entrance as able to see the visitor's
address whatever the entrance says about itself.

## 5.1 Capacity

The numbers in this section are informative; the requirements in it
are not. They were measured in October 2026 with the reference
entrance (Python, aiohttp) on one core and 512 MB, against a test node
on one core and 512 MB; the scripts and the full results are in the
entrance's repository (`tools/loadtest`). A session is two tunnels per
node (section 4.1.1 makes that one circuit).

| | Per open tunnel |
|---|---|
| Entrance, TLS with Python's default read buffer (256 KiB per connection) | about 333 KB |
| Entrance, TLS with a 16 KiB read buffer | about 99 KB |
| Entrance without TLS (a server in front adds its own share) | about 36 KB |
| Node (the Unseenet process) | about 10 KB |
| Tor at the entrance / at the node | about 60 KB / 5 KB |

- **Memory decides how many visitors fit.** With the default buffer the
  entrance ran out of memory at about 1650 tunnels; with 16 KiB it held
  3000 tunnels in 285 MB. An entrance SHOULD keep its per-connection TLS
  buffers small, or end TLS in a server on the same machine (which
  section 5 allows: only someone else's machine is ruled out).
- **Opening circuits costs CPU, holding them does not.** At four new
  tunnels a second, Tor used about 10 % of a core at the entrance and
  5 % at the node; with 200 tunnels open and idle, nearly nothing. A
  new tunnel takes about 2.5 s to open (95 % within about 7 s). Section 4.4
  exists because of this.
- **Moving bytes is cheap.** 3000 open tunnels with requests flowing
  used 2–3 % of a core.
- **Limits around the program.** Each tunnel holds two open files
  (WebSocket and SOCKS). An entrance SHOULD raise its open-file limit
  well above twice the tunnels it allows, and SHOULD set its total
  limit from its memory, not from a fixed number.
- **The first visit** downloads the whole web client (about 15 MB, half
  that compressed). An entrance SHOULD serve it compressed. Later
  visits use the copy kept on the device (section 7.3).

A node carries the tunnels of every entrance that sends visitors to it,
and its Tor builds a circuit for each, so nodes need limits of their
own. A web client SHOULD pick its first node at random from the known
nodes rather than always the first one listed, so that visitors are
spread over the network instead of all arriving at one node.

# 6. The Web Client

## 6.1 Showing Where You Are

A web client on the open web MUST show, at all times and on every
screen, that it is on the open web: a bar that cannot be hidden, in a
colour that differs from the graphical client's, with a short text such
as "Open web - the entrance can see your IP address". The bar links to a
page that explains, without technical words, what this means and how to
get the real client.

When the page was loaded over an onion service, the bar says so instead
("Tor Browser - the entrance cannot see your address, but you trust the
code it serves").

The About page (the "About Unseenet" every client has) MUST include the
table in section 3.

## 6.2 Keys and the Vault

All work with secrets happens in the browser:

- The vault format is the one in UN-RFC 0007 section 2.1. The web
  client opens a vault file the user picks (for example from a stick)
  and, when saving, writes the file back or offers it for download.
  The payload is kept in memory as in UN-RFC 0007 section 2.2.
- A web client MUST NOT send a passphrase, a private key, a group key
  or decrypted content to the entrance or anywhere else.
- A web client MUST NOT store a vault in the browser (IndexedDB, local
  storage, the cache) unless the user turns this on, with a warning
  that anyone using the browser later can try passphrases against it.
- Where the browser supports it, a web client SHOULD import signing
  and agreement keys as non-extractable WebCrypto keys and drop the raw
  bytes, so code running later in the page cannot read them back.
- Proof-of-work (UN-RFC 0006) is paid in the browser at the same
  difficulty as any client. A web client SHOULD tell the user while it
  works, since phones are slow.
- Key derivation uses the vault's own Argon2id parameters. If the
  browser cannot give the memory they need, the web client MUST refuse
  to open the vault rather than weaken it.

## 6.3 Hidden-only Identities

An identity entry in the vault MAY carry the flag `hidden_only`. A web
client MUST NOT sign, decrypt or claim with a hidden-only identity, and
says why. The portable and bootable clients SHOULD offer to set the
flag when an identity is made, and SHOULD set it by default in the
bootable client.

This lets someone keep one vault on their stick and still use it on
the open web for a public, low-stakes identity, without risking the one
that needs to stay hidden. Users SHOULD be told plainly that the safest
choice is a separate vault for the open web.

## 6.4 Nothing from Elsewhere

The page MUST load nothing from outside its own origin: no fonts,
scripts, images or styles from third parties. It MUST set a Content
Security Policy that forbids it, and MUST NOT load images or other
content that posts link to (UN-RFC 0027 attachments come through the
entrance like everything else). Links in posts follow the graphical
client's rules.

## 6.5 New Users

A web client MUST be able to make a new vault and a new identity on the
spot, so a newcomer can read and post within minutes. It makes the keys
in the browser, as any client does (UN-RFC 0003), pays the cost of a new
key (UN-RFC 0025) in the browser, and then offers the vault file for
download with a plain explanation: this file and its passphrase are the
identity, and nobody can restore them if both are lost.

A web client SHOULD suggest a separate identity for anything the user
may later want to keep hidden, and MAY offer to move the vault to a
stick with the portable client.

# 7. Trusting the Code

## 7.1 The Problem

A real client is downloaded once, its signature checked, and then it
runs the same code every time. A web page is fetched again on every
visit. Whoever controls the server or the domain - its operator, an
attacker who takes over the account, someone with a court order - can
serve a different page to one chosen visitor that sends their
passphrase away. Encryption in the browser does not help against this:
the code that does the encryption is the code that is changed.

A signature check done by the page itself proves nothing, since a
changed page can skip it. A check only helps when the code doing it
does not come from the same server on every visit. Sections 7.3 to 7.5
give three such places, from weakest to strongest.

## 7.2 Signed Releases

The web client is built once, reproducibly, by the project, and every
entrance serves that build instead of one of its own: the same sources
give the same files, byte for byte. A build is published in two ways:

- as a release of the entrance software: a zip of the files, and the
  same list as below;
- in the project's channel `unseenet.releases`, as one post per version
  whose body names the version and gives the SHA-256 of every file:

```
Unseenet web client 20261021.1145

Built from unseenet 1a2b3c4, unseenet-gui 5d6e7f8, unseenet-entrance 9a0b1c2.

<sha256>  index.html
<sha256>  pyodide/pyodide.asm.wasm
...
<sha256>  unseenet-web-20261021.1145.zip
```

A version is a number of dot-separated parts, compared part by part
(the build's date and time). The post is signed by a poster the project
key lists in the group's manifest, or by the project key itself, so it
can be read from inside the network, through Tor or through any
entrance, and checked by a key no entrance has. An entrance can
withhold a post but cannot forge one.

Entrances fetch the group's manifest and newest posts, about once an
hour, and serve them unchanged, as for the list of entrances (section
8.2), at `/.well-known/unseenet-releases.json`. They say which version
they serve in `/.well-known/unseenet-entrance` (`"web"`), and serve
their files to any origin (CORS), so that an app installed from one
entrance can update from another.

## 7.3 A Pinned Loader

The page SHOULD keep itself on the device (a service worker and the
browser's cache) with the project's public key built in. It then runs
only what it keeps, and keeps only files whose SHA-256 a valid post in
`unseenet.releases` gives, for a version no older than the one it runs:

- When it finds a newer valid post, it says so and offers to update.
  It does not update silently: whoever holds a key that may post can
  otherwise reach every app at once.
- Updating downloads the files from any entrance that serves that
  version, its own or one from the list in section 8.1, checks every
  file, and switches only when all of them match. Files that did not
  change are taken from the version it has.
- It never goes back to an older version, whatever an entrance says.

An entrance MAY update the web client it serves by itself, in the same
way and with the same checks (from the release, or file by file from
other entrances). It MUST NOT update its own server software without
its operator having turned that on.

This protects every visit after the first against a server that changes
the application. It does not protect the first visit, and browsers
fetch the service worker's own script again from its address from time
to time, so whoever controls that address can replace the loader. The
loader therefore compares the service worker the entrance serves with
the signed one and MUST warn when they differ. It is a tripwire, not a
guarantee.

A build that is not signed (an entrance that builds its own, for
testing) is kept and run as it is, and the page says that it is not a
signed release.

### 7.3.1 Asking More Than One Source

Every post is signed, so sources cannot disagree about what a version
is, only about which is the newest. The loader SHOULD ask for the
signed posts from its own entrance and from at least one other from the
list in section 8.1, and take the newest valid version any of them has.
Holding an update back then needs every entrance asked to do it.

## 7.4 A Verifier Outside the Page

The project SHOULD publish a browser extension, itself signed and
installed from the browser's store, that checks every file the page
loads against the signed checksums and shows plainly whether the page
is a signed release. Because the extension does not come from the
entrance, a changed page cannot switch it off. This is the only
protection that holds against a server that serves a changed page to
one person on their first visit.

## 7.5 Running It Yourself

The signed web client release includes the client as a single file,
`unseenet-web.html` (section 8.7), that is checked once and opened from
disk. A person who does this has the same trust in the code as with
the portable client, and only the entrance's view of their address
remains.

## 7.6 Watching from Outside

Real clients and the project's monitoring SHOULD regularly fetch the
page from each known web entrance, over Tor and over the open web, and
compare it with the signed checksums, reporting any difference in
`unseenet.announce` or the statistics site. This catches an entrance that
changes the page for everyone. It cannot catch one that changes it for
a single visitor, which is why section 7.4 exists.

# 8. Finding and Switching Web Entrances

## 8.1 The List of Known Web Entrances

Known web entrances are listed like known nodes (UN-RFC 0010), in a
project group of their own, `unseenet.entrances`. Each entry is the
entrance's information from section 4.3 plus its open-web and onion
addresses, signed by a key the project key lists as a poster. Anyone
may ask to be listed (a GitHub issue, as for nodes). The project lists
an entrance only when its operator promises section 5 and outside
watching (section 7.6) has found it serving the signed release.

The list says who is known, not who is safe. No one can see whether an
entrance keeps logs.

Each post is one complete list, as for node lists (UN-RFC 0010
section 3); the newest valid post counts. The list is a JSON object
`{"v": 1, "updated": "...", "entrances": [...]}`, at most 200 entries:

| Field         | Req.        | Meaning                                          |
|---------------|-------------|--------------------------------------------------|
| `url`         | one of both | The entrance on the open web: `https://host/`    |
| `onion`       | one of both | Its onion address, `<56 base32>.onion`           |
| `name`        | no          | A short label, at most 64 characters             |
| `operator`    | no          | The operator's identity key or name (UN-RFC 0019)|
| `contact`     | no          | How to reach the operator, at most 120 characters|
| `description` | no          | At most 200 characters, shown to users           |

Clients ignore entries with neither a valid `url` nor a valid `onion`,
and unknown fields.

## 8.2 Bootstrap

A web client needs a first entrance before it can read the list from the
network. It finds one by, in order:

1. the list built into the loader at release time;
2. the bootstrap file `https://<any listed entrance>/.well-known/unseenet-entrances.json`,
   a copy of `unseenet.entrances` with each entry's signature, which
   every listed entrance SHOULD serve;
3. the same file from the project's own bootstrap at `unseenet.net`.

The web client MUST check every entry's signature against the project
key whatever served it, so that a bootstrap source can withhold
entrances but not add one. Once connected, it reads
`unseenet.entrances` from the network and keeps the list in memory
(or in the vault, when one is open).

## 8.3 Staying on One, Moving When Needed

A web client SHOULD keep using one entrance for a whole session and
pick it at random from the list when the session starts. It moves to
another listed entrance:

- when the entrance cannot be reached or stops answering;
- when the user asks;
- when a post it sent has not come back through a second entrance
  within a reasonable time (section 8.4).

It MUST NOT change entrance on a timer or after every post. Every
entrance a visitor uses learns their address and, once they post, their
key. Moving often spreads that knowledge to more operators without
hiding anything from any of them: the chance that one of them records
it only grows.

## 8.4 Checking for Dropped Posts

An entrance cannot change a signed post, but it can drop one. After
posting, a web client SHOULD check that the article reached the
network by asking for its Message-ID through another listed entrance,
connecting to a different node. If the article is missing, it says so
and offers to send it again through the other entrance. This second
entrance sees the visitor's address too, so the check SHOULD be one the
user can turn off.

## 8.5 The Project's Own Web Entrance (Informative)

The project intends to run a web entrance, the web client and the
bootstrap file at `unseenet.net`, kept apart from `unseenet.org`, so
that the documentation and the real clients live on one name and the
less hidden access on another. It would follow section 5 in full: DNS
straight to the entrance with no proxying, memory-only storage, no logs,
an onion address beside it. Its configuration would be public.

## 8.6 Making It Easy to Run One (Informative)

More entrances run by more people make the list harder to block or
pressure. The project intends to publish a package that sets up a web
entrance on a small free virtual machine (for example an Oracle Cloud
Always Free instance) in one command: Tor, the entrance, a TLS server
with a free certificate, memory-only storage, logging off, an onion
address, and the request to be listed.

## 8.7 A List in a File

A government or a provider can block `unseenet.net` and every listed
entrance it knows of. A file on the user's own computer cannot be
blocked, and can be passed on by mail, chat or stick. The project
therefore publishes, with every release of the web client, two files
meant to be saved and shared:

- **`unseenet-entrances.html`**, the jump page: one self-contained page
  with the signed list of web entrances built in, both open-web and
  onion addresses. It shows the list, checks which entrances answer, and
  has a button that opens a random one that does. Opening an entrance
  this way loads the code that entrance serves, so section 7 applies.
- **`unseenet-web.html`**, the client in a file: the whole web client
  and the list in one page, opened from disk. It needs no entrance to
  serve it anything, only one to carry ONNTP, so neither blocked
  domains nor changed pages (section 7.1) matter while the file itself
  is genuine. It is the better choice whenever someone can keep a file.

Both files:

- MUST contain the project's public key and show its fingerprint, so a
  user can compare it with one they got elsewhere (the documentation,
  a friend, a printed note). Each list entry is checked against that
  key.
- SHOULD, when opened, fetch the newest signed list from the entrances
  they reach (the bootstrap file of section 8.2), keep only entries
  whose signature is good, and offer to save an updated copy of
  themselves. A list in a file is otherwise only as fresh as the day it
  was saved.
- MUST work when opened from disk (`file://`). Web entrances therefore
  MUST accept WebSocket connections whose `Origin` is `null`, and MUST
  serve the bootstrap file with `Access-Control-Allow-Origin: *`.

A copy from a stranger may have been changed, list, key and all. The
safest copy is the one in the signed release zip, checked as in
section 7.2. The files SHOULD say this on their first screen.

# 9. Security and Privacy Considerations

- **The entrance links address and identity.** It sees when an address
  is online and, since posts are signed, which key posts from it. Treat
  every open-web post as tied to the poster's address for anyone who
  can see the entrance: its operator, its hosting provider, or someone
  who compels either.
- **Served code** (section 7). The real risk for anyone a powerful
  adversary is interested in.
- **The browser** holds decrypted content in memory, and extensions
  with access to all pages can read it. Users SHOULD use a browser
  profile without extensions, or a private window.
- **Blocking.** One domain is easy to block; the onion address, the
  other listed entrances, the bootstrap of section 8.2 and the files of
  section 8.7 remain. Blocking every listed entrance is possible for a
  determined state; entrances it does not know of, and Tor, are not.
- **Network.** Nodes see the entrance's Tor circuits, nothing more. A
  entrance with very many users becomes something an observer can watch
  to learn who uses Unseenet at all, not what they do in it.
- **No mark on articles.** Marking open-web posts would tell everyone
  which posts are easier to trace, and help no one.

# 10. Rationale

- **Why a dumb tunnel?** An entrance that understood ONNTP would be
  tempted to cache, index and filter, and then it would be a central
  service. A tunnel can be replaced by any other tunnel.
- **Why not run Tor in the browser?** Browsers cannot open raw
  connections to Tor relays; projects that tried need a bridge on the
  open web anyway, which then sees the address too.
- **Why "memory only, no logs" as a duty, when it cannot be checked?**
  Because it is still the difference between an honest operator who is
  served a demand and has nothing to hand over, and one who does. The
  document is honest that it is a promise (section 5).
- **Why not change entrance every few minutes?** It feels safer, but a
  entrance learns the same thing in one minute as in an hour: who you
  are and that you use Unseenet. Every extra entrance is one more
  operator who could record it. Where several entrances do help is in
  agreeing on the code (section 7.3.1), in getting around one that is
  down or blocked (section 8.3), and in noticing one that drops posts
  (section 8.4).
- **Why hidden-only identities?** People will open their real vault on
  the open web out of habit. The flag makes the safe choice the
  default where it matters most.

# 11. Open Questions

1. Should the browser extension of section 7.4 be required before a
   web client offers to open a vault that holds anything but public,
   low-stakes identities?
2. Should the check for dropped posts (section 8.4) be on by default?

# 12. Changes to Other Documents

- **UN-RFC 0007** section 2.1: identity entries may carry `hidden_only`
  (section 6.3).
- **UN-RFC 0010**: web entrances are listed like known nodes, in their
  own group `unseenet.entrances` (section 8.1).
- **UN-RFC 0050** section 3.8: the entrance's relay for a copy is
  section 4.5 of this document.
- **UN-RFC 0000** section 6: 0043 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.

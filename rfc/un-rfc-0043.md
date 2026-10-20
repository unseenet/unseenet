```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0043                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0000, 0007

             Unseenet: Web Gateways and Clients on the Open Web
```

# Abstract

Many people will never install a program or boot from a stick before
they have seen what a network is like. This document lets them reach
Unseenet from an ordinary browser on the open web. A **web client** is
a page that does all the work with keys in the browser: it opens the
vault, signs, encrypts, decrypts and pays proof-of-work. A **web
gateway** is a server that passes the browser's ONNTP session to a node
over Tor and does nothing else. It never sees a passphrase, a private
key or the plaintext of a closed group.

This access is less hidden than the real clients, and the document says
so plainly: the gateway sees the visitor's IP address, and the visitor
must trust the code the page is served with. What does not change is
what makes Unseenet worth using: groups and nodes cannot be removed by
anyone, and no one can delete or change someone else's signed post.

# 1. Motivation

The portable and bootable clients (UN-RFC 0001) hide who talks to whom.
They also ask a lot of a newcomer: download, unzip or flash, start. A
person who just wants to look will go back to Discord instead.

Old Usenet had web gateways, and many people only ever knew it through
one. That was also a lesson: when the convenient way becomes the only
way most people know, its operator holds the network in practice. This
document therefore keeps the web gateway as thin as possible, makes it
replaceable, and keeps the real clients the documented path for anyone
who needs to be hidden.

# 2. Terms

- **Open-web access**: using Unseenet from a browser without Tor.
- **Web client**: the code a browser runs to use Unseenet: the same
  user interface as the graphical client (`unseenet-gui`), with a
  transport that talks to a web gateway instead of a local Tor.
- **Web gateway**: a server that accepts WebSocket connections from web
  clients and carries each one, byte for byte, to an onion service node
  over Tor.
- **Hidden-only identity**: an identity in a vault marked so that web
  clients refuse to use it (section 6.3).

# 3. What Changes and What Does Not

| | Real client (portable, bootable) | Web client, open web | Web client in Tor Browser |
|---|---|---|---|
| Groups and nodes can be removed by someone | No | No | No |
| Others can delete or change your signed posts | No | No | No |
| Nodes learn your IP address | No | No | No |
| The gateway learns your IP address | (no gateway) | **Yes** | No |
| You must trust code served to you | Once, on download, signed | **Every load** (section 7) | **Every load** (section 7) |
| Keys stay on your stick or in memory | Yes | In the browser (section 6) | In the browser (section 6) |
| The access point can be blocked | Hard (Tor, bridges) | **Easy** (one domain) | Hard |

Everything below the network layer is unchanged: a post from a web
client is an ordinary signed article, and nodes cannot tell it from any
other.

# 4. The Web Gateway Protocol

## 4.1 One Tunnel per Connection

A web client opens a WebSocket over TLS to the gateway:

```
wss://gateway.example/onntp?node=<56-character v3 onion address>
```

The gateway opens a connection over Tor to that onion address on the
ONNTP port (UN-RFC 0005) and copies bytes in both directions until
either side closes. Each WebSocket binary message carries an arbitrary
run of bytes; the ONNTP line protocol is unchanged and runs inside. The
web client speaks to the node exactly as a portable client would,
including node authentication where the node uses it.

A web gateway:

- MUST connect only to v3 onion addresses, and only on the ONNTP port.
  It MUST NOT reach any address on the open web, so that it cannot be
  used as an open proxy.
- SHOULD connect only to nodes on a list of known nodes (UN-RFC 0010)
  or nodes its operator has added, and MAY refuse others.
- MUST NOT read, parse, change or add to the ONNTP stream. It MUST NOT
  add headers to articles; there is no field that marks an article as
  coming from the web.
- MUST give each WebSocket connection its own Tor circuit (for example
  with SOCKS isolation and random credentials per connection), so that
  a node cannot link two sessions through the gateway's circuits.
- MUST NOT cache articles, groups or answers. A gateway that caches is
  a node, and should be run as one.

## 4.2 Limits

A gateway MAY limit connections per visitor and in total. It MUST do
this without storing addresses: counters are kept in memory only, keyed
by an HMAC of the address under a key made at start and never written
down, and dropped after at most one hour.

## 4.3 Gateway Information

A gateway SHOULD answer `GET /.well-known/unseenet-gateway` with a JSON
object:

```json
{
  "operator": "@lorensen",
  "contact": "inbox:<identity fingerprint>",
  "onion": "<the gateway's own onion address, if it has one>",
  "nodes": "known",
  "statement": "memory only, no logs, no third-party proxy"
}
```

`nodes` is `"known"` (only listed nodes) or `"any"`. The web client
shows this information on its About page. It is a promise, not proof
(section 5).

# 5. Operating a Web Gateway

A web gateway sees every visitor's IP address and when they are
online. Nothing in this protocol can stop an operator from recording
that. The obligations below are what an operator promises, and the
reason the gateway is kept so thin is that there is little else to
promise.

An operator of a web gateway:

- MUST run the gateway so that nothing about visitors is written to
  disk: no access logs, no connection logs, no error logs naming
  addresses, no core dumps. The RECOMMENDED setup is a host or
  container whose writable storage is in memory only (tmpfs) and whose
  logging is turned off at every layer: reverse proxy, gateway, Tor,
  system journal.
- MUST NOT put the gateway behind a service that ends TLS on someone
  else's machine (a CDN or a proxying DNS service). That party would
  see every address and the whole ONNTP stream. DNS for the gateway's
  name MUST point straight at the gateway.
- MUST NOT add analytics, trackers or content from third parties to
  the page.
- SHOULD also offer the gateway and the page as an onion service, for
  visitors who use Tor Browser.
- SHOULD publish the gateway's configuration, so others can see what it
  runs.

A web client MUST treat the gateway as able to see the visitor's
address whatever the gateway says about itself.

# 6. The Web Client

## 6.1 Showing Where You Are

A web client on the open web MUST show, at all times and on every
screen, that it is on the open web: a bar that cannot be hidden, in a
colour that differs from the graphical client's, with a short text such
as "Open web - the gateway can see your IP address". The bar links to a
page that explains, without technical words, what this means and how to
get the real client.

When the page was loaded over an onion service, the bar says so instead
("Tor Browser - the gateway cannot see your address, but you trust the
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
  or decrypted content to the gateway or anywhere else.
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
gateway like everything else). Links in posts follow the graphical
client's rules.

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

Every release of the web client is built reproducibly and published
like the other releases: a `SHA256SUMS.txt` over every file the page
consists of, signed (`SHA256SUMS.txt.sig`) with the project key for
stable releases and the release key for development builds, exactly as
for stick updates. The project announces each stable release in
`unseenet.announce` with the same checksums, so they can be read from
inside the network, through Tor, signed by a key the gateway does not
have. A gateway can withhold that announcement but cannot forge it.

## 7.3 A Pinned Loader

The page SHOULD consist of a small loader, installed on the first
visit as a service worker, with the project's public keys built in.
After that the loader fetches the application files, checks them
against signed checksums (from the release or from `unseenet.announce`
through the gateway), and runs them only if they match a version no
older than the last one it ran. It refuses, with a clear warning, if
the signature is wrong or the version goes back.

This protects every visit after the first against a server that changes
the application. It does not protect the first visit, and browsers
fetch the service worker's own script again from time to time, so a
server can replace the loader. The loader MUST therefore warn when its
own script has changed. It is a tripwire, not a guarantee.

## 7.4 A Verifier Outside the Page

The project SHOULD publish a browser extension, itself signed and
installed from the browser's store, that checks every file the page
loads against the signed checksums and shows plainly whether the page
is a signed release. Because the extension does not come from the
gateway, a changed page cannot switch it off. This is the only
protection that holds against a server that serves a changed page to
one person on their first visit.

## 7.5 Running It Yourself

The signed web client release is a zip that can be checked and opened
locally, pointed at any web gateway. A person who does this has the
same trust in the code as with the portable client, and only the
gateway's view of their address remains. Someone who can do this can
usually run the portable client, which is better.

## 7.6 Watching from Outside

Real clients and the project's monitoring SHOULD regularly fetch the
page from each known web gateway, over Tor and over the open web, and
compare it with the signed checksums, reporting any difference in
`unseenet.announce` or the statistics site. This catches a gateway that
changes the page for everyone. It cannot catch one that changes it for
a single visitor, which is why section 7.4 exists.

# 8. The Project's Own Web Gateway (Informative)

The project intends to run a web gateway and web client at
`unseenet.net`, kept apart from `unseenet.org`, so that the
documentation and the real clients live on one name and the less hidden
access on another. It would follow section 5 in full: DNS straight to
the gateway with no proxying, memory-only storage, no logs, an onion
address beside it. Its configuration would be public.

Anyone may run a web gateway. A web client SHOULD let the user pick
another one, and the project SHOULD list known web gateways like known
nodes, so that blocking or pressuring one name does not cut people off.

# 9. Security and Privacy Considerations

- **The gateway links address and identity.** It sees when an address
  is online and, since posts are signed, which key posts from it. Treat
  every open-web post as tied to the poster's address for anyone who
  can see the gateway: its operator, its hosting provider, or someone
  who compels either.
- **Served code** (section 7). The real risk for anyone a powerful
  adversary is interested in.
- **The browser** holds decrypted content in memory, and extensions
  with access to all pages can read it. Users SHOULD use a browser
  profile without extensions, or a private window.
- **Blocking.** One domain is easy to block; the onion address and
  other gateways remain.
- **Network.** Nodes see the gateway's Tor circuits, nothing more. A
  gateway with very many users becomes something an observer can watch
  to learn who uses Unseenet at all, not what they do in it.
- **No mark on articles.** Marking open-web posts would tell everyone
  which posts are easier to trace, and help no one.

# 10. Rationale

- **Why a dumb tunnel?** A gateway that understood ONNTP would be
  tempted to cache, index and filter, and then it would be a central
  service. A tunnel can be replaced by any other tunnel.
- **Why not run Tor in the browser?** Browsers cannot open raw
  connections to Tor relays; projects that tried need a bridge on the
  open web anyway, which then sees the address too.
- **Why "memory only, no logs" as a duty, when it cannot be checked?**
  Because it is still the difference between an honest operator who is
  served a demand and has nothing to hand over, and one who does. The
  document is honest that it is a promise (section 5).
- **Why hidden-only identities?** People will open their real vault on
  the open web out of habit. The flag makes the safe choice the
  default where it matters most.

# 11. Open Questions

1. Should web gateways be listed in their own group
   (`unseenet.webgateways`) or as a field on known-node entries?
2. Should the browser extension of section 7.4 be required before a
   web client offers to open a vault that holds anything but public,
   low-stakes identities?
3. Should a web client be able to make a new identity and vault on the
   spot, so a newcomer can try posting in minutes?

# 12. Changes to Other Documents

- **UN-RFC 0007** section 2.1: identity entries may carry `hidden_only`
  (section 6.3).
- **UN-RFC 0000** section 6: 0043 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.

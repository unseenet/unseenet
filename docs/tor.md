# Tor and Tails

Unseenet runs entirely on the [Tor network](https://www.torproject.org/).
This page explains what Tor does for you, what it does not do, and how to
use Unseenet from [Tails](https://tails.net/).

## What Tor is

Tor is a network of a few thousand volunteer-run relays. A program that
uses Tor does not connect to its destination directly. It sends its
traffic through three relays in a row - a *circuit* - and wraps it in
three layers of encryption, one for each relay:

```
 you --> guard --> middle --> exit --> website
```

- The **guard** knows who you are, but not where you are going.
- The **exit** knows where the traffic goes, but not who sent it.
- The **middle** knows neither.

No single relay knows both ends. Tor changes circuits regularly, and
anyone watching your network only sees that you use Tor.

## Onion services

A website on the normal internet has a public address, and the exit
relay can see the traffic to it. An **onion service** is different: it
lives inside the Tor network and has an address that ends in `.onion`.

```
 you --> 3 relays --> rendezvous <-- 3 relays <-- onion service
```

Both sides build their own circuit to a meeting point, the *rendezvous*.
The traffic never leaves the Tor network, there is no exit, and neither
side learns the other's IP address.

The address itself is the service's public key. When you connect to
`f6vn...n64qd.onion`, Tor checks that whoever answers holds the matching
private key. Nobody can pretend to be that node, and the connection is
encrypted end to end. That is why Unseenet does not need TLS or
certificates ([UN-RFC 0005](spec/un-rfc-0005.md)).

## How Unseenet uses Tor

- **Every node is an onion service**, on virtual port 119. It has no
  public IP address and needs no open port in a router or firewall. It
  can run at home, behind NAT, on a Raspberry Pi.
- **The client starts its own private Tor.** It ignores the system's Tor
  and `/etc/tor/torrc`, so it works the same everywhere. Other programs
  cannot use this Tor.
- **Nodes talk to each other** over Tor too. A node only knows its peers'
  onion addresses, never where they are.
- **Nodes wait a random time** (up to a minute) before passing a post on,
  so it is harder to tell which node a post entered the network through
  ([UN-RFC 0005](spec/un-rfc-0005.md), section 5.5).

## What Tor does not hide

Tor hides *where* you are. It does not hide *what* you do:

- **The node you use sees which groups you read.** Use several nodes, or
  subscribe to whole hierarchies, if that matters to you.
- **What you write** can identify you: your writing style, the topics you
  know about, the times of day you post. Unseenet signs posts with a key,
  not with your name - but a key you use for years becomes a name too.
  Use separate identities for separate parts of your life.
- **Your own computer** can record what you do (see
  [What stays on the computer](portable.md#what-stays-on-the-computer)).
  Tails solves much of that - see below.
- **Your network** sees that you use Tor. Where that is a problem, or
  where Tor is blocked, use a bridge (see
  [If Tor cannot connect](portable.md#if-tor-cannot-connect)).

## Tor for other programs

The client's own Tor is private. If you want to reach Unseenet from other
programs - for example a [classic newsreader](other-clients.md) - they
need a Tor of their own:

| Tor | SOCKS port | Notes |
|---|---|---|
| The system's Tor service | `127.0.0.1:9050` | `sudo apt install tor` or `sudo dnf install tor`, then `sudo systemctl enable --now tor` |
| Tor Browser | `127.0.0.1:9150` | Only while Tor Browser is running |
| Tails | `127.0.0.1:9050` | Always running |

Programs must let Tor resolve `.onion` names (SOCKS5 with remote name
resolution). `torsocks` does that for programs that know nothing about
proxies: `torsocks tin ...`.

## Tails

[Tails](https://tails.net/) is a complete operating system that starts
from a USB stick. Everything it does goes through Tor, and it forgets
everything when you shut it down, unless you save it in its encrypted
*Persistent Storage*. It leaves no traces on the computer it runs on.

That makes Tails a good match for Unseenet - but there is no Unseenet
client for Tails yet.

!!! warning "The Unseenet client does not run in Tails yet"
    The client starts its own Tor. Tails' firewall only lets Tails' own
    Tor connect to the internet, so the client's Tor is blocked. The
    client needs an option to use an existing Tor instead; until it has
    one, use Tails to **read** with a classic newsreader.

### Reading with tin in Tails

1. Start Tails and connect to Tor.
2. Install `tin` (and `torsocks`, if it is missing) as
   [additional software](https://tails.net/doc/persistent_storage/additional_software/).
   If you have Persistent Storage, Tails offers to install it again at
   every start.
3. Open a terminal and start tin through Tails' Tor:
   ```bash
   torsocks tin -r -x -g f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion -p 119
   ```
4. To keep your subscriptions and settings (`~/.newsrc`, `~/.tin/`), turn
   on the [*Dotfiles* feature](https://tails.net/doc/persistent_storage/configure/)
   of Persistent Storage and copy them to
   `/live/persistence/TailsData_unlocked/dotfiles/`. Tails links them
   into your home folder at every start.

See [Other newsreaders](other-clients.md#tin-classic-text) for using tin
and showing æ, ø and å correctly.

### Thunderbird in Tails

Tails no longer includes Thunderbird by default (since Tails 7.8), but
you can install it as additional software. It already goes through Tor.
Set up a news account as described in
[Other newsreaders](other-clients.md#thunderbird-graphical), skipping the
proxy step.

!!! note "Not yet verified"
    Tails configures Thunderbird to allow only secure protocols, and
    Unseenet nodes use plain NNTP inside Tor. Thunderbird in Tails may
    refuse the connection. The node's missing `XOVER`
    ([issue #21](https://github.com/unseenet/unseenet/issues/21)) also
    applies here.

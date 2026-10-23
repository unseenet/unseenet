# The clients

A client is where a person meets Unseenet: the program that holds your
keys, talks to nodes over Tor and shows you the groups. There are
several - a terminal client, a graphical client, a browser version, a
command line - but they are less different than they look. This chapter
is about the one core they share, the ways you can run them, and what
that means for your privacy.

## One core, many front ends

Everything hard about being a client lives in one place: the **client
core**, in the Python package `unseenet`, and in particular its
`Session`. A session holds one vault and does, for every client alike:

- the keys and the encrypted vault;
- starting Tor and talking to nodes through it;
- postage and key ripening;
- checking every signature and every manifest itself, so no node has to
  be trusted;
- encrypting and decrypting closed groups and private posts;
- edits, withdrawals, names, profiles, files, and the offline cache.

The clients people see are front ends on top of that:

| Client | What it is |
|--------|------------|
| **The terminal client** | a full-screen text program (built with Textual), the project's reference client |
| **The graphical client** | a window drawn with web technology, in its own repository, `unseenet-gui` |
| **The browser version** | the same graphical client, core and all, running inside a web browser |
| **The command line** | `unseenet`, for scripts and for doing everything a group owner needs |
| **Bots, gateways, the MCP server** | programs with a key but no person at the keyboard |

Because they all go through the same core, they behave alike. A post
written from the command line pays the same postage and carries the same
headers as one from the terminal client; a rule the core enforces - "you
may not write here, and here is why" - is the same everywhere. A client
does not have to get the cryptography right on its own, because it
never does it on its own.

### The local client API

A front end does not even have to be written in Python. The core can
offer a small **local client API** - HTTP and a WebSocket on `127.0.0.1`
- to a front end on the same computer: unlock the vault, list groups and
posts, write, look up people, follow events as they happen. That is how
the graphical client works:

```
 window ──HTTP/WebSocket──▶ local client API ──▶ Session ──Tor──▶ nodes
 (127.0.0.1 only)                                vault, keys, postage
```

The front end only draws. **Keys, signing, encryption and postage never
leave the core**, and the passphrase is sent to it once, to unlock. The
API listens only on the machine itself, every start makes a random token
that every request must carry, and what people wrote reaches the window
as a safe tree of text and formatting, never as HTML - so a post cannot
run code in the client.

## Ways to run it

The same client comes in several packages, for different needs.

**Portable** (Linux, macOS, Windows). A folder with the client and Tor in
it. Unzip it onto a USB stick and start it on any computer; the vault
lives on the stick. It writes nothing outside its own folder - no
installation, no registry entries, no temporary files. The computer's own
system may still note that a program ran, and a keylogger on it sees
what you type, so use a computer you trust.

**Bootable** (USB, SSD and so on). A stick you start the computer from.
It runs Unseenet from memory, touches nothing on the computer's disks
and leaves nothing behind when you switch off. The same stick also works
as a portable one on a running computer, with the same vault. This is the
choice for someone who really needs to hide: a compromised Windows or
macOS installation never gets to see your passphrase, because it never
runs.

**In your browser.** A **web entrance** serves the graphical client to an
ordinary browser, on a computer, phone or tablet, with nothing to install.
The whole client runs inside the browser: your keys stay there, the page
signs and pays postage itself, and the entrance only carries the
connection to a node over Tor - it can neither read nor change what goes
through. The price is honest: the entrance sees your IP address (unless
you use Tor Browser), your network sees you visit it, and you trust code
served from the web. A bar at the top always says you are on the open
web. It is for people who want the freedom - groups nobody can remove,
posts nobody can change - more than full anonymity. Chapter 7 has more.

**With pip.** `pip install unseenet` gives the terminal client and the
command line on a computer that already has Python and Tor.

### Using a Tor that is already running

Normally a client starts its own Tor. On Tails, or on a computer with a
system Tor or Whonix, it can use the Tor that is already there instead,
and start none. On Tails it does that by itself.

## Other newsreaders

A node speaks ordinary NNTP over Tor, so a classic newsreader such as
tin or Thunderbird can connect and **read** open groups, just as it reads
Usenet. It cannot write - a post needs a signature and postage that a
newsreader cannot make - and it cannot read closed groups or check who
really wrote a post. For following public groups from an old favourite,
it works; for anything else, use an Unseenet client.

## What a client keeps to itself

A few principles hold for every Unseenet client, because a client is
where a person can most easily give themselves away:

- **Nothing from the open web without asking.** A link in a post or a
  profile is not opened, and no picture or preview is fetched from it,
  unless you choose to - following a link would leave Tor. The bootable
  client does not open links at all.
- **No metadata in files.** Pictures are saved again before they are
  sent, without GPS position, time, camera or owner.
- **Files are not handed to other programs** without you asking.
- **Write controls only where you may write**, so you are told before you
  spend time writing, not after.
- **Clear about chat and posts**: the client always shows which one you
  are writing.

## Write your own

Unseenet is meant to have more clients than the project's own. There are
three ways in: a Python program on `Session`; a program in any language
on the local client API; or a newsreader, for reading only. Every rule a
client must follow is in the UN-RFCs, so a client written from scratch,
in another language, works with everyone else's. The
[developers' pages](../developers/index.md) show how, and chapter 9 says
which UN-RFCs to read first.

**Details:**
[UN-RFC 0005](../spec/un-rfc-0005.md) (ONNTP),
[0007](../spec/un-rfc-0007.md) (the vault, host hygiene),
[0027](../spec/un-rfc-0027.md) (files and metadata),
[0031](../spec/un-rfc-0031.md) (safe Markdown),
[0043](../spec/un-rfc-0043.md) (web entrances),
[0046](../spec/un-rfc-0046.md) (the local client API).
For using them: [Portable](../portable.md), [Bootable](../bootable.md),
[The graphical client](../graphical.md), [In your browser](../web.md),
[Tor and Tails](../tor.md) and [Other newsreaders](../other-clients.md).

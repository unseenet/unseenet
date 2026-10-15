# Using the client

The TUI client is a terminal program. It starts its own private Tor,
connects to a node and keeps everything you have - identity, group keys,
subscriptions, what you have read - in one encrypted file, the **vault**.

## Install

You need Python 3.11 or newer, `git` and the `tor` program.

=== "Fedora"

    ```bash
    sudo dnf install tor git python3
    ```

=== "Debian / Ubuntu"

    ```bash
    sudo apt install tor git python3-venv
    ```

=== "macOS"

    ```bash
    brew install tor git python
    ```

Then install Unseenet from PyPI with [pipx](https://pipx.pypa.io/), which
keeps it in its own environment:

```bash
pipx install "unseenet[tui]"
unseenet-tui
```

Or, to follow development, from the repository:

```bash
git clone https://github.com/andlo/unseenet
cd unseenet
python3 -m venv .venv
.venv/bin/pip install -e ".[tui]"
.venv/bin/unseenet-tui
```

You do **not** need to start or configure the system's Tor service.
Unseenet runs its own Tor process with its own settings and ignores
`/etc/tor/torrc`.

## First start

1. **Choose a passphrase.** It encrypts your vault (`unseenet.vault` in the
   current directory). There is no way to recover it if you forget it.
2. **Choose a display name.** This is just a label. Your real identity is a
   key pair that is created for you.
3. **Enter a node address**, e.g. the test node
   `f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion`.

The first connection takes 10-30 seconds while Tor builds its circuits.
After that the connection is reused.

!!! tip "Several vaults"
    Use `--vault` to keep separate vaults, e.g. one per identity or per
    node: `unseenet-tui --vault ~/work.vault`.

## Keys

| Key | What it does |
|-----|--------------|
| ++g++ | Browse the groups on the node; ++enter++ subscribes or unsubscribes |
| ++n++ | New post in the current group |
| ++r++ | Reply to the selected post |
| ++ctrl+s++ | Send (in the compose window) |
| ++c++ | Create a group |
| ++m++ | Send a private message (pre-filled with the selected post's author) |
| ++o++ | About this node - and write to its operator |
| ++k++ | Show your key (share it to get private messages or invitations) |
| ++i++ | Invite someone to a closed group you own |
| ++j++ | Join a group by ID or `unseenet:join` link |
| ++f5++ | Refresh (also happens every 30 seconds) |
| ++q++ | Quit |

Unread posts are marked with ●. Posts in closed groups are marked with ◈,
private messages with ✉.

## Private messages

Every identity has a personal **inbox**. The client creates it on the
node the first time you connect, and it is shown at the top of the group
list as *✉ Private messages*.

- To write to someone, press ++m++ and paste their key (they find it with
  ++k++). If you have a post by them selected, their key is filled in.
- Only the recipient can read the message. The node cannot, and it does
  not even learn who sent it: the message is sealed to the recipient's key
  and signed with a key that is used only once.
- Inside the sealed message you prove who you are, so the recipient sees
  your name marked **verified**.
- Press ++r++ on a private message to reply privately.

The recipient's inbox has to be on the node you use, or on a node it is
replicated to.

## Contacting a node's operator

Press ++o++ to see who runs the node and its policy: which groups it
accepts, how long it keeps posts, the minimum postage and what it logs.
If the operator has set up a contact inbox, **Write to operator** sends
them a private message. Use it to report abuse, ask for a group to be
carried, or just say thanks.

## Joining a closed group

Closed groups are end-to-end encrypted, so you need to be invited:

1. Press ++k++ and send your key to the group's owner (any way you like).
2. The owner presses ++i++ in the group and pastes your key.
3. The owner sends you the `unseenet:join?...` link it shows.
4. You press ++j++ and paste the link.

A minute or so later, when the invitation has reached your node, the
posts become readable.

## Sending takes a moment

Every post carries a small proof-of-work, about a second of CPU time. It
makes mass spam expensive. The client computes it in the background.

## Your vault

- Everything you store is in the vault file, encrypted with your
  passphrase (Argon2id + XSalsa20-Poly1305). It is only decrypted in memory.
- Back it up. If you lose it, you lose your identity and your keys to
  closed groups.
- The vault and its cache are normal files, so they can live on a USB stick
  together with the program.

## Reading offline

Posts you have fetched are kept in an encrypted cache next to the vault
(`unseenet.vault.cache`), encrypted with the same key. When you start the
client it shows them at once, and then fetches what is new. Without a
connection to the node you can still read everything you fetched before.

The cache belongs to one node: article numbers differ between nodes, so
if you switch node the cache starts over.

## The command line client

There is also a plain command line client for scripting and testing:

```bash
unseenet --help
```

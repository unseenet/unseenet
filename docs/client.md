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

Then:

```bash
git clone https://github.com/andlo/unseenet
cd unseenet
python3 -m venv .venv
.venv/bin/pip install -e ".[tui]"
```

You do **not** need to start or configure the system's Tor service.
Unseenet runs its own Tor process with its own settings and ignores
`/etc/tor/torrc`.

## First start

```bash
.venv/bin/unseenet-tui
```

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
| ++k++ | Show your key (give it to a group owner to be invited) |
| ++i++ | Invite someone to a closed group you own |
| ++j++ | Join a group by ID or `unseenet:join` link |
| ++f5++ | Refresh (also happens every 30 seconds) |
| ++q++ | Quit |

Unread posts are marked with ●. Posts in closed groups are marked with ◈.

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
- The vault is a normal file, so it can live on a USB stick together with
  the program.

!!! note "Offline reading"
    Posts are currently fetched from the node each time you start the client.
    An encrypted local cache for offline reading is on the way.

## The command line client

There is also a plain command line client for scripting and testing:

```bash
.venv/bin/unseenet --help
```

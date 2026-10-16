# Other newsreaders

An Unseenet node speaks ONNTP, which is ordinary NNTP (RFC 3977) over a
Tor onion service ([UN-RFC 0005](spec/un-rfc-0005.md)). That means a
classic newsreader can connect to a node and **read** groups, just as it
would read Usenet.

This page shows two examples: **tin**, a classic text newsreader, and
**Thunderbird**, Mozilla's mail and news client.

## What works and what does not

| | Unseenet client | Other newsreaders |
|---|---|---|
| Read open, moderated and channel groups | yes | yes |
| Read closed groups and private messages | yes | no - the posts are encrypted |
| Post and reply | yes | no - the node answers `441` |
| Check that a post really is from its author | yes | no - you trust the node |
| Keys, vault, contacts, chat | yes | no |

Posting needs a signature and proof-of-work postage
([UN-RFC 0003](spec/un-rfc-0003.md), [0006](spec/un-rfc-0006.md)), which
a normal newsreader cannot produce. Use another newsreader to **follow**
groups; use the Unseenet client to write.

Some things look a little different from Usenet:

- **Group names end in the owner's fingerprint**, for example
  `dk.test@fm7i6vut5wjx7vup`. Two groups can have the same name with
  different owners - check the fingerprint before you trust a group.
- **The author** is shown as the display name the poster chose, not as
  an e-mail address. Anyone can choose any name; only the Unseenet client
  can tell you which key signed a post.
- **Headers are UTF-8** without MIME encoding. Tell your reader so, or
  æ, ø and å come out as `Ã¦`, `Ã¸` and `Ã¥` (see the examples below).
- The node does not yet support `OVER`/`XOVER`, so readers fetch the
  headers of each article one by one. Large groups load slowly
  ([issue #21](https://github.com/unseenet/unseenet/issues/21)).

## Connecting through Tor

Nodes are only reachable as onion services, on port **119**. Your
newsreader needs a Tor SOCKS port, and it must let Tor resolve the
`.onion` name - never your own DNS.

The Unseenet client starts its own private Tor, which other programs
cannot use. Use one of these instead:

- **The system's Tor service** - SOCKS port `127.0.0.1:9050`.
  ```bash
  sudo apt install tor torsocks      # Debian, Ubuntu
  sudo dnf install tor torsocks      # Fedora
  sudo systemctl enable --now tor
  ```
- **Tor Browser**, while it is running - SOCKS port `127.0.0.1:9150`.

You also need a node's address. The project's nodes are:

```
f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion
ze4aqpjfyteij4tqaaztyujoj7wsjgbv4cliexljckdfp5eomkshfead.onion
```

!!! tip "Running your own node?"
    On the node's own machine you can skip Tor: the node listens on
    `127.0.0.1:1119`. Use host `127.0.0.1`, port `1119` in the examples
    below.

## tin (classic, text)

[tin](http://www.tin.org/) is a full-screen threaded newsreader for the
terminal. It is packaged by most Linux distributions and in Homebrew.

```bash
sudo apt install tin torsocks        # Debian, Ubuntu
sudo dnf install tin torsocks        # Fedora
```

Start it through `torsocks`, in remote and no-posting mode:

```bash
torsocks tin -r -x -g f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion -p 119
```

| Option | Meaning |
|---|---|
| `-r` | read news from an NNTP server |
| `-x` | no-posting mode - posting would be rejected anyway |
| `-g` | the server: the node's onion address |
| `-p 119` | the port |

The first time, tin shows no groups. Press ++y++ to list all groups on
the node, move to a group and press ++s++ to subscribe, then ++enter++ to
read it. ++q++ goes back, ++h++ shows help.

To show æ, ø and å correctly, add this to the end of `~/.tin/attributes`
(tin creates the file on its first start):

```
scope=*
undeclared_charset=UTF-8
```

!!! note
    `torsocks` makes tin's connection go through Tor and resolves the
    `.onion` name inside Tor. For Tor Browser's port, use
    `TORSOCKS_TOR_PORT=9150 torsocks tin ...`.

## Thunderbird (graphical)

[Thunderbird](https://www.thunderbird.net/) from Mozilla is a mail
client with a built-in newsreader, for Linux, Windows and macOS.

Thunderbird's proxy setting applies to **everything** it does, including
your mail. Use a separate profile for Unseenet:

```bash
thunderbird -P        # Profile Manager: create a profile "unseenet"
```

In the new profile:

1. **Proxy.** *Settings → General → Network & Disk Space → Settings...*
    - *Manual proxy configuration*
    - *SOCKS Host*: `127.0.0.1`, *Port*: `9050` (or `9150` for Tor Browser)
    - *SOCKS v5*
    - Tick **Proxy DNS when using SOCKS v5**. Without it, Thunderbird
      tries to look up the `.onion` name itself and fails.
2. **Account.** *☰ → New Account → Newsgroups*.
    - *Your name* and *e-mail*: anything; they are not used.
    - *Newsgroup Server*: the node's onion address.
3. **Server settings.** Open *Account Settings* for the new account →
   *Server Settings*:
    - *Port*: `119`
    - *Connection security*: **None** (Tor already encrypts the
      connection and authenticates the node by its address).
4. **Charset.** In *Account Settings → Server Settings*, set the default
   text encoding to *Unicode (UTF-8)*, if your version offers it.
5. **Subscribe.** Right-click the account → *Subscribe...*, tick the
   groups you want, and click *OK*.

!!! warning "Not yet verified"
    Thunderbird lists a group's posts with `XOVER`, which the node does
    not support yet. Until it does, Thunderbird may show an empty group
    or load very slowly. This is tracked in
    [issue #21](https://github.com/unseenet/unseenet/issues/21).

## Other readers

Any newsreader that can use a SOCKS5 proxy with remote name resolution,
or that runs under `torsocks`, should work the same way - for example
slrn, Pan, Gnus in Emacs or Claws Mail. Point it at the node's onion
address on port 119, turn off TLS, and do not post from it.

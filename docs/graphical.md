# The graphical client

The graphical client is Unseenet in a window on your own computer: the same
groups, keys and vault as the terminal client, drawn with a mouse-friendly interface in the look of
this site. It lives in its own repository,
[unseenet/unseenet-gui](https://github.com/unseenet/unseenet-gui).

!!! warning "Pre-alpha prototype"
    Neither the graphical client nor the Unseenet core has had a security review.
    Play with it and pick it apart; do not rely on it to protect anyone yet.

A discussion is not a chat, and the graphical client keeps them apart just like
the terminal client. Discussion groups work like a newsreader: the posts as
a tree, one post at a time below it, ++up++ ++down++ through the thread,
++space++ to the next unread, and ++r++ to answer in a compose window with
the post quoted and your signature below. Chat groups are chats. The
group's owner decides which a group is, and ++v++ shows it the other way.

## Two ways to run it

Both are built from every change and self-tested; the newest are the
[development pre-release](https://github.com/unseenet/unseenet-gui/releases/tag/dev).

**Portable (Linux, macOS, Windows) · Graphical.** Unzip and start, from a USB stick or a
folder. Tor is included, and everything stays in `data/` beside the
programs.

- Windows: `Unseenet Graphical.exe` opens an app window (no console).
- macOS: `Start Unseenet Graphical.command` opens an app window.
- Linux: `sh start-graphical-linux.sh` opens Chromium, Chrome, Edge or Brave
  without tabs if you have one, else your browser.

**Bootable (USB, SSD etc.) · Graphical.** Write `unseenet-gui-…-x86_64.img.xz` to a USB
stick (for example with Raspberry Pi Imager or balenaEtcher), boot from it,
and the client starts full screen and runs from memory, as with the
terminal client's [bootable image](bootable.md). The first screen sets up
Wi-Fi and the keyboard. It needs 4 GB of memory. In the boot menu, *safe
graphics* helps if the screen stays black, and *text only* starts the
terminal client instead.

The graphical client uses the same `Unseenet/` folder and `data/` as the terminal
client's [portable build](portable.md), so the two can share a stick and a
vault. Do not run both on the same vault at the same time.

## How it works

The graphical client draws its window with web technology, but it is not a
website. It runs on your own computer, nothing
is hosted anywhere, and on Linux the window it opens in your browser only
talks to the program on your own machine.

```
 window ──HTTP/WebSocket──▶ unseenet-gui ──▶ unseenet core ──Tor──▶ nodes
 (127.0.0.1 only)           (local server)   vault, keys, postage
```

`unseenet-gui` is a small local server around the core's `Session`, the
same one the terminal client uses. It opens the same encrypted vault,
starts the same Tor and talks to the same nodes. The window only draws what
you see: **keys, signing, encryption and postage never leave the core**, and
the passphrase is sent once, to unlock.

The local server guards itself against other programs and web pages on the
same computer: it listens on 127.0.0.1 only, every start makes a random
token that every request must carry, and a strict Content-Security-Policy
keeps the page from loading anything from outside. What people wrote is
shown as text, never as HTML, and links in posts are not clickable, because
following one would leave Tor. The
[README](https://github.com/unseenet/unseenet-gui#security) has the details.

## What it can do, and not yet

It can unlock or create a vault, follow and leave groups, read threads and
chats (closed groups decrypted), post, reply and chat, show *For you*,
private messages and contacts, create groups and invite to closed ones, and
switch between a light and a dark theme. The bootable image also sets up the
network, Wi-Fi and keyboard, and restarts or shuts down.

Not yet - use the [terminal client](client.md) for these: names (`@you`),
moderation and member removal, reporting, ignoring people, Tor bridges,
several identities and updating the stick.

## From source

You need Python 3.11 or newer:

```sh
pip install "unseenet-gui @ git+https://github.com/unseenet/unseenet-gui"
unseenet-gui            # opens your browser
unseenet-gui --window   # in its own window (pip install "unseenet-gui[window] @ ...")
```

`--window` uses the system's web view in private mode, so nothing ends up in
your browser's history.

# Updating

A portable folder, a USB stick and a bootable stick all update themselves to
the newest release, over Tor, and **keep `data/`**: your vault, the offline
cache, a node's data and your settings. Nothing needs to be copied off first.

## Bootable (USB, SSD etc.)

Boot the stick and choose **Update** in the menu, then one of:

- **Newest release** - what most people want;
- **Newest development build** - the newest code on `main`, which may have
  bugs a release would not;
- **From unseenet-...-update.zip on the stick** - for a computer without a
  network (see [Without a network](#without-a-network)).

It connects (cable or Wi-Fi first), starts Tor, shows the version it found
and asks before it changes anything. When it is done the computer restarts
into the new version.

You can also update a bootable stick from a computer that is running: start
Unseenet from the stick as a [portable](portable.md#start-it) and update as
below. A bootable stick always gets the bootable update, which includes the
portable programs too.

## Portable (Linux, macOS, Windows)

In the client, open the command palette (**Ctrl+P**) and choose **Update
Unseenet**. The client saves your work, the update runs in the terminal, and
the client closes when it is done; start it again to use the new version.

The same from a terminal, in the Unseenet folder:

```bash
./linux-x86_64/unseenet update            # Linux
./macos-aarch64/unseenet update           # macOS (Apple silicon; macos-x86_64 on Intel)
windows-x86_64\unseenet.exe update        # Windows
```

| Option | Does |
|--------|------|
| `--check` | Only says whether there is something newer |
| `--channel dev` | The newest development build instead of the newest release |
| `--zip FILE` | Updates from a zip you downloaded yourself |
| `--yes` | Does not ask |

A folder with every platform (the USB zip) gets the USB zip again; a folder
with one platform gets that platform's zip, so it stays small. On Windows a
program that is running cannot be replaced, so it is moved aside and deleted
the next time Unseenet starts.

## Without a network

Download, from the same release on
[GitHub](https://github.com/unseenet/unseenet/releases):

- the zip for your installation - `unseenet-<version>-x86_64-update.zip` for
  a bootable stick, `unseenet-<version>-usb.zip` for a USB folder, or the
  platform's zip;
- `SHA256SUMS.txt` and `SHA256SUMS.txt.sig`.

Put the three files in one folder (for a bootable stick: in the stick's
root) and choose the zip in the boot menu, or run `unseenet update --zip
<the zip>`. Where Tor is blocked, this is also the way to update: the
updater uses Tor without bridges.

## Why it can be trusted

Every release has a `SHA256SUMS.txt` with the checksum of every file, and a
signature over it, `SHA256SUMS.txt.sig`. The updater only goes on when

1. the signature is from a key built into Unseenet, and
2. the zip it downloaded matches its checksum.

**Releases** are signed by the maintainer with the project key, which never
leaves the maintainer's computer. **Development builds** are signed in
GitHub Actions with a separate release key, which the updater accepts only
when you ask for a development build. So even someone who took over the
GitHub project could not send an update to sticks that follow releases. See
[the project's keys](project/keys.md).

It also refuses an older version than the one you have (unless you give
`--force`), and a zip meant for another kind of installation.

## What happens, and what can go wrong

The files are replaced one by one: each new file is written next to the old
one and then renamed over it, so a file is never half-written. The bootable
system's kernel comes last. `data/` is never touched, nor are files of your
own that you put on the stick, nor the boot loader (`ldlinux.sys`).

Do not pull out the stick or turn off the computer while it works. If it
happens anyway, `data/` is still as it was, and choosing Update again
finishes the job. If a bootable stick no longer starts, start it on a
running computer as a portable, copy `data/` off, and write a new image.

!!! note "Versions before 0.3.0"
    Updating came with 0.3.0. A stick or folder with an older version has to
    be written or unpacked once more with 0.3.0 (copy `data/` off first, and
    back afterwards); from then on it updates itself.

!!! note "Coming"
    Going back to the previous version, and growing a bootable stick's
    partition to the whole stick so there is room for it (#68).

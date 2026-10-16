# Portable: USB stick, Windows, macOS

The portable builds are the easiest way to use Unseenet: one folder with the
client **and Tor** inside, nothing to install. Unzip it, start it, done. Put
the folder on a USB stick and you carry your Unseenet with you - your keys,
groups and contacts are in the encrypted vault inside it.

## Download

Get the zips from the [releases page](https://github.com/unseenet/unseenet/releases):

| File | For |
|------|-----|
| `unseenet-<version>-windows-x86_64.zip` | Windows 10 and 11, 64-bit |
| `unseenet-<version>-macos-aarch64.zip` | Macs with Apple silicon (M1 and later) |
| `unseenet-<version>-macos-x86_64.zip` | Macs with Intel processors |
| `unseenet-<version>-linux-x86_64.zip` | Linux, 64-bit (glibc 2.35 or newer) |
| `unseenet-<version>-usb.zip` | **All of the above** in one folder - for a stick that works on any computer |

Check the download against `SHA256SUMS.txt` from the same release:

=== "Windows"

    ```powershell
    certutil -hashfile unseenet-0.2.0-usb.zip SHA256
    ```

=== "macOS"

    ```bash
    shasum -a 256 unseenet-0.2.0-usb.zip
    ```

=== "Linux"

    ```bash
    sha256sum unseenet-0.2.0-usb.zip
    ```

## Put it on a stick

Unzip, and copy the `Unseenet` folder to the stick. Any stick formatted
for Windows (FAT32 or exFAT) works on all three systems. You need about
120 MB per system, 500 MB for the all-in-one folder.

```text
Unseenet/
  Start Unseenet.bat          Windows: double-click
  Start Unseenet.command      macOS: double-click
  start-linux.sh              Linux: sh start-linux.sh
  README.txt
  data/                       your vault, created at the first start
  windows-x86_64/  macos-aarch64/  macos-x86_64/  linux-x86_64/
  LICENSES/
```

## Start it

=== "Windows"

    Double-click **Start Unseenet.bat**. It opens in Windows Terminal if you
    have it (Windows 11 does), otherwise in the classic console.

    The first time, Windows may show *"Windows protected your PC"*. The
    program is not signed (a code-signing certificate costs money every
    year). Click **More info**, then **Run anyway**.

=== "macOS"

    Double-click **Start Unseenet.command**. A Terminal window opens with
    the client.

    The first time, macOS may say the developer cannot be verified.
    Right-click (or Ctrl-click) the file, choose **Open**, and confirm.
    The launcher then lets macOS run the programs in its folder.

=== "Linux"

    From a terminal:

    ```bash
    sh /run/media/$USER/STICK/Unseenet/start-linux.sh
    ```

    USB sticks formatted with FAT are usually mounted without execute
    permission; the script starts the program anyway, through the system's
    program loader.

The first start asks for a passphrase for your new vault, a display name and
a node. Starting Tor takes up to a minute; after that, it is quicker,
because Tor keeps what it learned about the network in `data/`.

## Your data

Everything is in `data/`, encrypted with your passphrase (Argon2id and
XSalsa20-Poly1305, [UN-RFC 0007](spec/un-rfc-0007.md)):

- `unseenet.vault` - your keys, groups, contacts, settings
- `unseenet.vault.cache`, `.sent` - saved posts and your sent private
  messages
- `unseenet-tor/` - Tor's state (no secrets of yours)

**Back up `data/`.** It is small. If you lose the stick and have no copy,
your identity is gone - nobody, not even a node operator, can restore it.
If you forget the passphrase, the vault cannot be opened.

The same `data/` works with every program in the folder: start on Windows
at work, continue on Linux at home.

## What stays on the computer

Unseenet writes only inside its folder: no installation, no registry, no
files in your home directory or the system's temp directory. (That is why it
is built as a folder and not as one `.exe`: one-file programs unpack
themselves into the temp directory at every start.)

But the computer's own system can still record things, and Unseenet cannot
stop that:

- **Windows** keeps *Prefetch* entries and *recent files* lists that show a
  program ran, and antivirus software may scan and log it.
- **macOS** records opened applications and downloaded files' origin.
- **Linux** may keep your shell history and system logs.
- **The network** sees that the computer connects to Tor - not what you do
  there.
- **Anything** with a keylogger or screen recorder sees what you type and
  read.

Use a computer you trust. On a computer you do not trust, assume that
everything you type may be recorded.

## If Tor cannot connect

Some networks block Tor: workplaces, schools, hotels, some countries. Press
++ctrl+p++ in the client and choose **Tor bridges**:

| Choice | What it does |
|--------|--------------|
| Off | Connect to Tor directly. Best where Tor is not blocked. |
| Built-in obfs4 | Tor traffic disguised as random data. Works in most places. |
| Built-in Snowflake | Goes through volunteers' web browsers; very hard to block, slower. |
| My own bridges | Lines you got from [bridges.torproject.org](https://bridges.torproject.org/) or by email to bridges@torproject.org. |

The built-in bridges come with each release, from the Tor Project. From the
command line: `unseenet cli bridges obfs4`.

## Checking a copy

```bash
Start Unseenet.bat --self-test          # Windows
sh start-linux.sh --self-test           # Linux
./macos-aarch64/unseenet --self-test    # macOS, from the Unseenet folder
```

prints which program, vault and Tor it uses, checks that every part loads,
starts Tor and connects to the Tor network. Add `--offline` to skip the
network, or `--node xyz.onion` to also talk to a node over Tor - the whole
path a post takes.

## Other modes

The program in each folder is also the command-line client and a node:

```bash
unseenet                    # the terminal client (default)
unseenet cli --help         # the command-line client
unseenet node --help        # run a node (see "Running a node")
unseenet --version
```

## How the builds are made

Every release is built by GitHub Actions from the tagged source, in the
open: [`.github/workflows/portable.yml`](https://github.com/unseenet/unseenet/blob/main/.github/workflows/portable.yml)
and [`tools/build_portable.py`](https://github.com/unseenet/unseenet/blob/main/tools/build_portable.py).

- **Tor** is the Tor Project's
  [Expert Bundle](https://www.torproject.org/download/tor/) - Tor, its
  libraries and the pluggable transports, without a browser. The build
  downloads it from `dist.torproject.org` and **refuses to continue** unless
  `gpg` finds a valid signature by the Tor Browser Developers key
  (`EF6E 286D DA85 EA2A 4BA7 DE68 4E2C 6E87 9329 8290`), which is kept in
  the repository. The version is pinned in `tools/tor-version.txt`; a weekly
  job opens an issue when Tor releases a newer one.
- **The client** is packed with [PyInstaller](https://pyinstaller.org/) on
  each system. Each build is unpacked and self-tested (offline, and over the
  Tor network) before it is published.
- **Releases** are drafted by the workflow and published by hand, with
  `SHA256SUMS.txt`.

To build one yourself (you need Python 3.11+, `gpg`, and the system you are
building for):

```bash
pip install ".[tui]" pyinstaller pillow
python tools/build_portable.py          # -> dist-portable/unseenet-<version>-<platform>.zip
```

## Known limits

- The programs are not code-signed, hence the warnings on first start.
- No 32-bit builds, and no Linux on ARM yet (the Tor Project offers no
  stable Expert Bundle for it).
- Linux builds need glibc 2.35 or newer (Ubuntu 22.04, Debian 12, Fedora 36
  and later).

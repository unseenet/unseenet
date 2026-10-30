"""Update an Unseenet stick in place, keeping data/ (issue #68).

    python -m unseenet.update [--media PATH] [--channel stable|dev] [--zip FILE]
                              [--check] [--yes] [--no-tor]

The stick is one FAT partition of ordinary files (unseenet-bootable's tools/image). An update
replaces the system files with those of a newer release's update zip,
``unseenet-<version>-x86_64-update.zip``, and never touches ``data/``.

Where from: the newest signed checksums are looked for on GitHub *and* in the
project channel ``unseenet.releases``, and the zip is taken from GitHub or any
mirror that has that version - web entrances can be mirrors, found in the signed
list of entrances and reached over Tor (#264). Only files that match the signed
checksums are used, so where they came from does not matter.

Trust: a release's ``SHA256SUMS.txt`` is signed (``SHA256SUMS.txt.sig``) and the
zip must match its checksum. The *stable* channel accepts only the project key,
used by the maintainer from the owner vault (tools/project/sign_release.py);
*dev* also accepts the release key that CI signs development builds with. Both
public keys are pinned below. See docs/bootable.md, "Updating".

How files are replaced: one at a time, each written next to the old one and
renamed over it, so a file is never half-written. The stick usually has too
little free room for a second copy of the system, so there is no previous
version to go back to yet (issue #68, steps 3 and 4). ``ldlinux.sys`` is never
touched, and the syslinux ``.c32`` files only when the syslinux version is the
same as the one on the stick (they must match ``ldlinux.sys``).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import http.client
import json
import os
import random
import re
import shutil
import socket
import ssl
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import urlsplit

from . import __version__
from .core import crypto
from .known_nodes import ENTRANCES_GROUP, PROJECT_KEY, RELEASES_GROUP

PURPOSE_RELEASE = crypto.PURPOSE_RELEASE
# CI signs development builds with a release key (GitHub secret UNSEENET_RELEASE_KEY):
# unseenet's own, and the one the build repositories share (#549, #550), made with
# tools/project/new_release_key.py. Both are trusted while unseenet still builds.
DEV_RELEASE_KEY = "ed25519:clbv6765nyz74fxm5qb4ktmdtuyotgxe3h3yozjlgneh7jserf2a"
BUILD_REPOS_RELEASE_KEY = "ed25519:hmkki7rxa52zur5syjlrc4hqz6h63fyi7ac6hbxegrbpotxgbvla"   # portable, bootable
DEV_RELEASE_KEYS: tuple[str, ...] = (DEV_RELEASE_KEY, BUILD_REPOS_RELEASE_KEY)
TRUSTED = {"stable": (PROJECT_KEY,), "dev": (PROJECT_KEY, *DEV_RELEASE_KEYS)}

REPO = "https://github.com/unseenet/unseenet"
# Where releases are looked for, in order (#546): the build repos the portable zips
# and the bootable images come from, then this repo, where they were until 0.6.
# Where a file comes from does not matter for trust: it must match the signed sums.
RELEASE_REPOS = ("https://github.com/unseenet/unseenet-portable",
                 "https://github.com/unseenet/unseenet-bootable",
                 REPO)
SUMS = "SHA256SUMS.txt"
SIG = SUMS + ".sig"
# What a release offers: one zip per kind of installation (see stick_kind)
ASSET = re.compile(r"^unseenet-(?P<version>[0-9][0-9A-Za-z.+]*?)-(?P<what>x86_64-update|usb|"
                   r"linux-x86_64|windows-x86_64|macos-aarch64|macos-x86_64)\.zip$")
PLATFORMS = ("linux-x86_64", "windows-x86_64", "macos-aarch64", "macos-x86_64")
TOP = "Unseenet"                     # the portable zips' top folder
OLD_SUFFIX = ".unseenet-old"         # Windows: a program in use, moved aside
VERSION_FILE = "UNSEENET-VERSION"
FILES_LIST = "UNSEENET-FILES"        # what this version put on the stick (removed by the next)
MARKER = "UPDATING"                  # on the stick while files are being replaced
SYSLINUX = "boot/syslinux"
SYSLINUX_VERSION = SYSLINUX + "/SYSLINUX-VERSION"
NEVER = {"data", "ldlinux.sys", MARKER}   # never in an update, never removed
KERNEL = ("boot/vmlinuz-lts", "boot/initramfs-lts", "boot/modloop-lts")   # replaced last


class UpdateError(Exception):
    pass


# ----------------------------------------------------------------------
# Versions
# ----------------------------------------------------------------------
def version_key(v: str) -> tuple:
    """Order versions as PEP 440 does, for the parts Unseenet uses:
    0.3.0.dev1 < 0.3.0a1.dev2 < 0.3.0a1 < 0.3.0b1 < 0.3.0rc1 < 0.3.0
    < 0.3.0.post1.dev1 < 0.3.0.post1 < 0.3.1.dev1. A post-release (``.postN``) is a
    rebuild of a bundle with the same core and newer clients (#546).
    """
    m = re.match(r"^v?(\d+(?:\.\d+)*)(?:(a|b|rc)(\d+))?(?:\.post(\d+))?(?:\.dev(\d+))?",
                 v.strip())
    if not m:
        return ((-1,), (-2, 0), -1, (0, 0))
    release = tuple(int(x) for x in m.group(1).split("."))
    release += (0,) * (4 - len(release))
    phase, num, post, dev = m.group(2), m.group(3), m.group(4), m.group(5)
    if phase:
        pre = ({"a": 0, "b": 1, "rc": 2}[phase], int(num))
    elif dev and not post:
        pre = (-1, 0)              # X.devN comes before every pre-release of X
    else:
        pre = (3, 0)               # the release itself comes after all of them
    postkey = int(post) if post else 0
    devkey = (0, int(dev)) if dev else (1, 0)   # a dev build comes before what it builds up to
    return (release, pre, postkey, devkey)


def stick_version(media: Path) -> str:
    try:
        return (media / VERSION_FILE).read_text().strip() or __version__
    except OSError:
        return __version__


# ----------------------------------------------------------------------
# Signed checksums
# ----------------------------------------------------------------------
def signature_text(sums: bytes, identity: crypto.Identity) -> str:
    """The contents of SHA256SUMS.txt.sig: which key, and its signature over the sums."""
    return (f"Unseenet release signature\nkey: {identity.key_text}\n"
            f"signature: {identity.sign_text(PURPOSE_RELEASE, sums)}\n")


def check_signature(sums: bytes, sig: str, channel: str) -> str:
    """The key that signed ``sums`` if it is trusted for ``channel``; UpdateError otherwise."""
    fields = dict(line.split(": ", 1) for line in sig.splitlines() if ": " in line)
    key, signature = fields.get("key", "").strip(), fields.get("signature", "").strip()
    if key not in TRUSTED.get(channel, ()):
        raise UpdateError(f"{SIG} is signed by a key not trusted for {channel}: {key or '-'}")
    try:
        good = crypto.verify(crypto.key_from_text(key), PURPOSE_RELEASE, sums,
                             crypto.sig_from_text(signature))
    except crypto.CryptoError as exc:
        raise UpdateError(f"{SIG}: {exc}") from exc
    if not good:
        raise UpdateError(f"the signature on {SUMS} is wrong: it was changed after signing")
    return key


def parse_sums(sums: bytes) -> dict[str, str]:
    """``sha256sum`` output: file name -> hex digest."""
    out = {}
    for line in sums.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            out[parts[1].lstrip("*").removeprefix("./")] = parts[0]
    return out


def asset_in(sums: dict[str, str], what: str) -> tuple[str, str]:
    """(file name, version) of the zip for ``what`` that a release's checksums list."""
    for name in sums:
        m = ASSET.match(name)
        if m and m.group("what") == what:
            return name, m.group("version")
    raise UpdateError(f"this release has no {what} zip (it is older than updating)")


def update_zip_in(sums: dict[str, str]) -> tuple[str, str]:
    """The bootable image's update zip (every release that can be updated to has one)."""
    return asset_in(sums, "x86_64-update")


def stick_kind(root: Path) -> str:
    """Which of a release's zips updates ``root``: a bootable stick takes the update
    zip (it has the portable builds too), a USB folder with every platform the usb
    zip, and a folder with one platform that platform's zip."""
    if (root / "unseenet.apkovl.tar.gz").exists():
        return "x86_64-update"
    present = [p for p in PLATFORMS if (root / p).is_dir()]
    return present[0] if len(present) == 1 else "usb"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------
# Downloading (over Tor when a SOCKS port is given)
# ----------------------------------------------------------------------
def _tls() -> ssl.SSLContext:
    """The system's certificates, or certifi's where it has none (a frozen build of
    Python often looks in the build machine's folders)."""
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) == 0:
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
    return ctx


class _Conn(http.client.HTTPSConnection):
    def __init__(self, host: str, socks_port: int | None):
        super().__init__(host, timeout=90, context=_tls())
        self.socks_port = socks_port

    def connect(self) -> None:
        if self.socks_port:
            from python_socks.sync import Proxy
            proxy = Proxy.from_url(f"socks5://127.0.0.1:{self.socks_port}", rdns=True)
            raw = proxy.connect(self.host, self.port or 443, timeout=90)
            raw.settimeout(90)
        else:
            raw = socket.create_connection((self.host, self.port or 443), 90)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class _OnionConn(http.client.HTTPConnection):
    """Plain HTTP to an onion address: Tor already encrypts and authenticates it."""
    def __init__(self, host: str, socks_port: int):
        super().__init__(host, timeout=120)
        self.socks_port = socks_port

    def connect(self) -> None:
        from python_socks.sync import Proxy
        proxy = Proxy.from_url(f"socks5://127.0.0.1:{self.socks_port}", rdns=True)
        self.sock = proxy.connect(self.host, self.port or 80, timeout=120)
        self.sock.settimeout(120)


def release_url(channel: str, name: str, version: str | None = None, repo: str = REPO) -> str:
    if channel == "dev":
        return f"{repo}/releases/download/dev/{name}"
    if version:
        return f"{repo}/releases/download/v{version}/{name}"
    return f"{repo}/releases/latest/download/{name}"


def release_urls(channel: str, name: str, version: str | None = None) -> list[str]:
    """``name`` in each of RELEASE_REPOS, in the order they are tried."""
    return [release_url(channel, name, version, repo) for repo in RELEASE_REPOS]


def from_github(channel: str, what: str, socks_port: int | None) -> tuple[list[Release], list[str]]:
    """The signed releases for ``what`` in every release repo, and what went wrong where.

    Each build repo signs the sums of its own files, so a repo without ``what`` is no
    error as long as another one has it."""
    found: list[Release] = []
    problems: list[str] = []
    for repo in RELEASE_REPOS:
        try:
            sums = fetch(release_url(channel, SUMS, repo=repo), socks_port)
            sig = fetch(release_url(channel, SIG, repo=repo), socks_port).decode("utf-8", "replace")
            found.append(check_release(sums, sig, channel, what))
        except UpdateError as exc:
            problems.append(f"{urlsplit(repo).path.strip('/')}: {exc}")
    return found, ([] if found else problems)


def fetch(url: str, socks_port: int | None, dest: Path | None = None,
          progress: Callable[[int, int], None] | None = None) -> bytes:
    """GET ``url`` over HTTPS, following GitHub's redirects; into ``dest`` if given."""
    for _ in range(6):
        u = urlsplit(url)
        onion = u.scheme == "http" and (u.hostname or "").endswith(".onion") and socks_port
        if not onion and (u.scheme != "https" or not u.hostname):
            raise UpdateError(f"refusing a non-HTTPS address: {url}")
        conn = _OnionConn(u.hostname, socks_port) if onion else _Conn(u.hostname, socks_port)
        try:
            conn.request("GET", (u.path or "/") + (f"?{u.query}" if u.query else ""),
                         headers={"User-Agent": f"unseenet-update/{__version__}"})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308) and r.getheader("Location"):
                url = r.getheader("Location") or ""
                continue
            if r.status == 404:
                raise UpdateError(f"not found: {url} (the release may be older than updating, "
                                  "or not signed yet)")
            if r.status != 200:
                raise UpdateError(f"{url}: HTTP {r.status} {r.reason}")
            if dest is None:
                return r.read()
            total, done = int(r.getheader("Content-Length") or 0), 0
            with open(dest, "wb") as f:
                while chunk := r.read(1 << 18):
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            return b""
        except (OSError, http.client.HTTPException) as exc:
            raise UpdateError(f"cannot download {url}: {exc}") from exc
        finally:
            conn.close()
    raise UpdateError(f"too many redirects: {url}")


# ----------------------------------------------------------------------
# Replacing the files on the stick
# ----------------------------------------------------------------------
def _member(name: str) -> str:
    """A zip member as a safe relative path; UpdateError for anything else."""
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or "\\" in name or not p.parts or ":" in p.parts[0]:
        raise UpdateError(f"unsafe file name in the update zip: {name!r}")
    if p.parts[0].lower() in NEVER or p.name.lower() in NEVER:
        raise UpdateError(f"the update zip may not contain {name!r}")
    return p.as_posix()


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _is_link(info: zipfile.ZipInfo) -> bool:
    return info.create_system == 3 and (info.external_attr >> 16) & 0o170000 == 0o120000


@dataclass
class Plan:
    version: str
    replace: list[str]          # paths on the stick, in the order they are written (kernel last)
    remove: list[str]           # what the old version put there and the new one does not
    keep_syslinux: bool         # the stick's .c32 files stay (they match its ldlinux.sys)
    room: int                   # free bytes needed on the stick
    prefix: str = ""            # the zip's top folder ("Unseenet/" in the portable zips)


def make_plan(media: Path, zf: zipfile.ZipFile) -> Plan:
    raw = [n for n in zf.namelist() if not n.endswith("/")]
    prefix = TOP + "/" if raw and all(n.startswith(TOP + "/") for n in raw) else ""
    names = [_member(n[len(prefix):]) for n in raw]
    if VERSION_FILE not in names:
        raise UpdateError(f"not an Unseenet update zip: it has no {VERSION_FILE}")
    version = zf.read(prefix + VERSION_FILE).decode("utf-8", "replace").strip()
    new_sl = zf.read(prefix + SYSLINUX_VERSION).decode().strip() \
        if SYSLINUX_VERSION in names else ""
    old_sl = _read(media / SYSLINUX_VERSION)
    keep = not (old_sl and new_sl and old_sl == new_sl)
    if keep:     # unknown or different: the .c32 files must stay those ldlinux.sys knows
        names = [n for n in names if not (n.startswith(SYSLINUX + "/")
                                          and (n.endswith(".c32") or n == SYSLINUX_VERSION))]
    # the version file last but the kernel: a stick that says "new" has all of it
    order = (VERSION_FILE, FILES_LIST, *KERNEL)
    names.sort(key=lambda n: (order.index(n) + 1 if n in order else 0, n))
    lower = {n.lower() for n in names}
    remove = []
    for line in _read(media / FILES_LIST).splitlines():
        try:
            old = _member(line.strip())
        except UpdateError:
            continue
        if old.lower() not in lower and (media / old).is_file() \
                and not (keep and old.startswith(SYSLINUX + "/")):
            remove.append(old)
    # One file at a time: each old file is freed when the new one replaces it,
    # except the modloop (mounted until the reboot) and, on Windows, programs
    # that are running - but those are few, so the largest file plus some room.
    largest = max((zf.getinfo(prefix + n).file_size for n in names), default=0)
    return Plan(version, names, remove, keep, largest + (64 << 20), prefix)


def _sync() -> None:
    if hasattr(os, "sync"):
        os.sync()


def _replace(tmp: Path, dest: Path) -> None:
    """Rename ``tmp`` over ``dest``; on Windows a running program is moved aside first."""
    try:
        os.replace(tmp, dest)
    except PermissionError:
        aside = dest.with_name(dest.name + OLD_SUFFIX)
        n = 0
        while aside.exists():
            try:
                aside.unlink()
            except OSError:
                n += 1
                aside = dest.with_name(f"{dest.name}.{n}{OLD_SUFFIX}")
        os.replace(dest, aside)          # Windows lets a file in use be renamed
        os.replace(tmp, dest)


def clean_old(root: Path) -> None:
    """Delete files an earlier update moved aside because they were in use."""
    for top in root.iterdir() if root.is_dir() else ():
        if top.name.lower() == "data":
            continue
        for p in ([top] if top.is_file() else top.rglob("*" + OLD_SUFFIX)):
            if p.name.endswith(OLD_SUFFIX):
                try:
                    p.unlink()
                except OSError:
                    pass


def _write_file(zf: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path) -> None:
    """Write one file next to ``dest`` and rename it over it."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".new")
    with zf.open(info) as src, open(tmp, "wb") as out:
        shutil.copyfileobj(src, out, 1 << 20)
        out.flush()
        os.fsync(out.fileno())
    mode = (info.external_attr >> 16) & 0o777
    if mode and os.name != "nt":
        try:
            os.chmod(tmp, mode)
        except OSError:                  # FAT: no modes to keep
            pass
    _replace(tmp, dest)


def _resolve(member: str, target: str) -> str:
    parts: list[str] = []
    for part in (PurePosixPath(member).parent / target).as_posix().split("/"):
        if part == "..":
            parts = parts[:-1]
        elif part not in ("", "."):
            parts.append(part)
    return "/".join(parts)


def _write_link(zf: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path) -> None:
    """A symbolic link (the macOS builds have some): made as a link where the file
    system has them, else (FAT) a copy of what it points to, as the image does."""
    target = zf.read(info).decode()
    # Windows: links need privileges and a POSIX-style relative target makes a link
    # Windows cannot open, so there the copy is used, as on FAT
    if os.name != "nt" and not (dest.is_dir() and not dest.is_symlink()):
        tmp = dest.with_name(dest.name + ".new")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if tmp.is_symlink() or tmp.exists():
                tmp.unlink()
            os.symlink(target, tmp)
            _replace(tmp, dest)
            return
        except (OSError, NotImplementedError):
            pass
    resolved = _resolve(info.filename, target)
    members = {i.filename: i for i in zf.infolist() if not i.filename.endswith("/")}
    if resolved in members:
        src = members[resolved]
        (_write_link if _is_link(src) else _write_file)(zf, src, dest)
        return
    for name, sub in members.items():    # a link to a folder: copy the folder
        if name.startswith(resolved + "/"):
            out = dest / name[len(resolved) + 1:]
            (_write_link if _is_link(sub) else _write_file)(zf, sub, out)


def apply(media: Path, zip_path: Path, say: Callable[[str], None] = print) -> Plan:
    """Replace the stick's system files with those in ``zip_path``. data/ is not touched."""
    clean_old(media)
    with zipfile.ZipFile(zip_path) as zf:
        plan = make_plan(media, zf)
        free = shutil.disk_usage(media).free
        if free < plan.room:
            raise UpdateError(f"the stick needs {plan.room >> 20} MB free for the update and "
                              f"has {free >> 20} MB; delete something outside data/, or "
                              "start again with a fresh copy (keep a copy of data/ first)")
        (media / MARKER).write_text(plan.version + "\n")
        _sync()
        for i, name in enumerate(plan.replace, 1):
            info = zf.getinfo(plan.prefix + name)
            (_write_link if _is_link(info) else _write_file)(zf, info, media / name)
            if i % 100 == 0 or name in KERNEL:
                say(f"  {i}/{len(plan.replace)} files")
        for name in plan.remove:
            try:
                (media / name).unlink(missing_ok=True)
            except OSError:              # in use (Windows): gone at the next update
                pass
    _sync()
    (media / MARKER).unlink(missing_ok=True)
    _sync()
    return plan


def unfinished(media: Path) -> str | None:
    """The version an interrupted update was writing, if any."""
    return _read(media / MARKER) or None


# ----------------------------------------------------------------------
# Finding a release, and the command line
# ----------------------------------------------------------------------
@dataclass
class Release:
    channel: str
    version: str
    zip_name: str
    sha256: str
    signed_by: str


def check_release(sums: bytes, sig: str, channel: str, what: str = "x86_64-update") -> Release:
    """What a release's signed checksums offer; UpdateError unless the signature is good."""
    signer = check_signature(sums, sig, channel)
    table = parse_sums(sums)
    name, version = asset_in(table, what)
    return Release(channel, version, name, table[name], signer)


# ----------------------------------------------------------------------
# Through the network (#264): the checksums in unseenet.releases, and mirrors
# ----------------------------------------------------------------------
_POST_HEAD = re.compile(r"^Unseenet (?P<version>[0-9][0-9A-Za-z.+]*), (?P<channel>stable|dev)$")
MIRROR_PATH = "mirror/{channel}/{name}"         # on an entrance that mirrors releases


def release_post(sums: bytes, sig: str, channel: str) -> tuple[str, str]:
    """(subject, body) of the post in unseenet.releases that carries a release's
    checksums and their signature, unchanged. Only one that checks out is made.

    The sums are a portable build's (unseenet-portable) or a bootable image's
    (unseenet-bootable, with the update zip): either names the version (#550)."""
    for what in ("linux-x86_64", "x86_64-update"):
        try:
            rel = check_release(sums, sig, channel, what)
            break
        except UpdateError as exc:
            problem = exc
    else:
        raise problem
    return (f"Unseenet {rel.version}",
            f"Unseenet {rel.version}, {channel}\n\n{SUMS}:\n{sums.decode()}\n{SIG}:\n{sig}")


def parse_release_post(body: str) -> tuple[str, bytes, str] | None:
    """(channel, sums, sig) from such a post; None for anything else. Nothing in it is
    trusted until check_release() has checked the signature."""
    lines = body.replace("\r\n", "\n").split("\n")
    m = _POST_HEAD.match(lines[0]) if lines else None
    if not m or f"{SUMS}:" not in lines or f"{SIG}:" not in lines:
        return None
    i, j = lines.index(f"{SUMS}:"), lines.index(f"{SIG}:")
    if j < i:
        return None
    sums = "\n".join(lines[i + 1:j]).strip("\n") + "\n"
    sig = "\n".join(lines[j + 1:]).strip("\n") + "\n"
    return m.group("channel"), sums.encode(), sig


async def _newest_bodies(c, group: str, n: int) -> list[str]:
    from .core.article import Article
    try:
        _, low, high = await c.group(group)
    except Exception:                     # noqa: BLE001  the node does not carry it
        return []
    out = []
    for num in range(high, max(low, high - n + 1) - 1, -1):
        raw = await c.article(str(num))
        if raw:
            try:
                out.append(Article.from_bytes(raw).body)
            except ValueError:
                pass
    return out


async def from_network(socks_port: int) -> tuple[list[str], list[str]]:
    """The newest posts in unseenet.releases, and the onion addresses in the newest
    lists of entrances, from the first known node that answers."""
    from .known_nodes import builtin_list, parse_entrance_list
    from .nntp import Client
    nodes = [n.address for n in builtin_list()[1]]
    for address in random.sample(nodes, len(nodes)):
        try:
            c = await asyncio.wait_for(Client.connect(address, socks_port), 120)
        except Exception:                 # noqa: BLE001  the next node
            continue
        try:
            releases = await _newest_bodies(c, RELEASES_GROUP, 30)
            onions = []
            for body in await _newest_bodies(c, ENTRANCES_GROUP, 3):
                try:
                    onions += [e["onion"] for e in parse_entrance_list(body)[1] if e["onion"]]
                except ValueError:
                    continue
            return releases, list(dict.fromkeys(onions))
        except Exception:                 # noqa: BLE001  the next node
            continue
        finally:
            try:
                await c.quit()
            except Exception:             # noqa: BLE001
                pass
    return [], []


def mirrors_with(onions: list[str], channel: str, version: str, socks_port: int) -> list[str]:
    """Base addresses of the entrances that mirror this version (they say so in
    /.well-known/unseenet-entrance), in random order."""
    out = []
    for onion in random.sample(onions, len(onions)):
        try:
            info = json.loads(fetch(f"http://{onion}/.well-known/unseenet-entrance", socks_port))
            # every version it has ("mirror_all": a bootable image can be at another version
            # than the portable builds, unseenet-entrance#44), else the one "mirror" names
            every = (info.get("mirror_all") or {}).get(channel)
            if version in (every if isinstance(every, list) else [(info.get("mirror") or {}).get(channel)]):
                out.append(f"http://{onion}/")
        except (UpdateError, ValueError, AttributeError):
            continue
    return out


def find_stick() -> Path | None:
    from .portable import portable_root
    root = portable_root()
    if root is not None:
        return root
    try:
        from .boot import find_media
    except ImportError:
        return None
    return find_media()


def _remount_rw(media: Path) -> None:
    if not os.access(media, os.W_OK) and sys.platform.startswith("linux"):
        import subprocess
        subprocess.run(["mount", "-o", "remount,rw", str(media)], capture_output=True)


def _progress(done: int, total: int) -> None:
    if total:
        print(f"\r  {done >> 20} of {total >> 20} MB ({done * 100 // total}%)", end="", flush=True)


def _ask(question: str, yes: bool) -> bool:
    if yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes", "j", "ja")
    except EOFError:
        return False


GRAPHICAL = "README-graphical.txt"      # a folder or stick of unseenet-gui's builds


def run(args: argparse.Namespace, socks_port: int | None) -> int:
    media: Path = args.media
    if (media / GRAPHICAL).exists():
        # its builds have the graphical client too: this release's zips would remove it
        raise UpdateError("this is a stick or folder of the graphical client (unseenet-gui); "
                          "it cannot be updated with unseenet's own releases yet - "
                          "download the new one from github.com/unseenet/unseenet-gui")
    current = stick_version(media)
    what = stick_kind(media)
    print(f"This stick: Unseenet {current}  ({media})")
    if (left := unfinished(media)):
        print(f"An update to {left} did not finish; it is done again now.")
    if args.zip:                       # offline: the zip, with the release's sums and signature
        m = ASSET.match(args.zip.name)
        if not m or m.group("what") != what:
            raise UpdateError(f"{args.zip.name} is not the zip for this stick: it needs "
                              f"unseenet-<version>-{what}.zip")
        folder = args.zip.parent
        try:
            sums, sig = (folder / SUMS).read_bytes(), (folder / SIG).read_text()
        except OSError:
            raise UpdateError(f"put {SUMS} and {SIG} from the same release next to the zip")
        try:
            rel = check_release(sums, sig, "stable", what)
        except UpdateError:              # a file you chose: a development build will do too
            rel = check_release(sums, sig, "dev", what)
        if rel.zip_name != args.zip.name:
            raise UpdateError(f"{SUMS} is for {rel.zip_name}, not {args.zip.name}")
    else:
        print(f"Looking for the newest {args.channel} release (GitHub and the network) ...")
        found: list[Release] = []
        problems: list[str] = []
        on_github, missed = from_github(args.channel, what, socks_port)
        found += on_github
        problems += [f"GitHub {m}" for m in missed]
        onions: list[str] = []
        if socks_port:
            bodies, onions = asyncio.run(from_network(socks_port))
            for body in bodies:
                post = parse_release_post(body)
                if post and post[0] == args.channel:
                    try:
                        found.append(check_release(post[1], post[2], args.channel, what))
                    except UpdateError:
                        continue                 # not signed by a key this channel trusts
            if not bodies:
                problems.append("the network: no node answered, or no release is posted yet")
        if not found:
            raise UpdateError("no signed release found - " + "; ".join(problems or ["nowhere"]))
        for problem in problems:
            print(f"  ({problem})")
        rel = max(found, key=lambda r: version_key(r.version))
    who = "the project key" if rel.signed_by == PROJECT_KEY else "the release key (development)"
    print(f"Newest: Unseenet {rel.version}, signed by {who}")
    if version_key(rel.version) <= version_key(current) and not args.force and not left:
        print("It is up to date.")
        return 3
    if args.check:
        print("An update is available.")
        return 0
    if not _ask(f"Update the stick to {rel.version}? data/ is kept.", args.yes):
        return 1
    with tempfile.TemporaryDirectory(prefix="unseenet-update-") as tmp:
        zip_path = args.zip or Path(tmp) / rel.zip_name
        if not args.zip:
            sources = release_urls(args.channel, rel.zip_name, rel.version)
            if socks_port and onions:
                sources += [base + MIRROR_PATH.format(channel=args.channel, name=rel.zip_name)
                            for base in mirrors_with(onions, args.channel, rel.version, socks_port)]
            for url in sources:
                print(f"Downloading {rel.zip_name} from {urlsplit(url).hostname} ...")
                try:
                    fetch(url, socks_port, zip_path, _progress)
                    print()
                except UpdateError as exc:
                    print(f"\n  {exc}")
                    continue
                if sha256_file(zip_path) == rel.sha256:
                    break
                print("  it does not match the signed checksum: trying the next source")
            else:
                raise UpdateError(f"{rel.zip_name} could not be fetched from any source; "
                                  "nothing was changed")
        if sha256_file(zip_path) != rel.sha256:
            raise UpdateError(f"{zip_path.name} does not match its checksum; nothing was changed")
        _remount_rw(media)
        print("Replacing the system files (do not pull out the stick) ...")
        apply(media, zip_path)
    print(f"Done: the stick has Unseenet {rel.version}. Your data/ is as it was.")
    if args.reboot and _ask("Restart now to use it?", args.yes):
        import subprocess
        subprocess.run(["reboot"])
    elif args.reboot:
        print("Restart before you use the stick again.")
    return 0


async def _over_tor(args: argparse.Namespace) -> int:
    from .core.tor import TorError, TorProcess
    with tempfile.TemporaryDirectory(prefix="unseenet-update-tor-") as tmp:
        try:
            tor = TorProcess(Path(tmp), TorProcess.find_binary())
            print("Starting Tor ...")
            await tor.start()
        except TorError as exc:
            raise UpdateError(f"Tor: {exc}") from exc
        try:
            return await asyncio.to_thread(run, args, tor.socks_port)
        finally:
            await tor.stop()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="unseenet-update", description=__doc__.splitlines()[0])
    p.add_argument("--media", type=Path, help="the stick (default: the one this runs from)")
    p.add_argument("--channel", choices=("stable", "dev"), default="stable",
                   help="stable releases (default), or development builds")
    p.add_argument("--zip", type=Path, help="update from this file instead of downloading; "
                   f"{SUMS} and {SIG} must be next to it")
    p.add_argument("--check", action="store_true", help="only say whether there is an update")
    p.add_argument("--force", action="store_true", help="also to the same or an older version")
    p.add_argument("--yes", action="store_true", help="do not ask")
    p.add_argument("--reboot", action="store_true", help="offer to restart afterwards (booted)")
    p.add_argument("--pause", action="store_true", help="wait for Enter at the end (menu)")
    p.add_argument("--no-tor", action="store_true", help="download directly, not over Tor")
    args = p.parse_args(argv)
    args.media = args.media or find_stick()
    if args.media is None or not any((args.media / f).exists() for f in (
            VERSION_FILE, "unseenet.apkovl.tar.gz", "UNSEENET-PORTABLE")):
        sys.exit("No Unseenet stick or portable folder found; give it with --media.")
    try:
        code = run(args, None) if (args.zip or args.no_tor) else asyncio.run(_over_tor(args))
    except UpdateError as exc:
        print(f"Update failed: {exc}", file=sys.stderr)
        code = 2
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        code = 130
    if args.pause:
        try:
            input("\nPress Enter to go back to the menu.")
        except EOFError:
            pass
    sys.exit(code)


if __name__ == "__main__":
    main()

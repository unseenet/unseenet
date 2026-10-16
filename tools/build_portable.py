#!/usr/bin/env python3
"""Build a portable Unseenet: one folder per platform, with Tor inside.

    python tools/build_portable.py                       # this computer's platform
    python tools/build_portable.py --platform windows-x86_64 --tor-archive tor.tar.gz
    python tools/build_portable.py --fetch-tor windows-x86_64 --out dl/
    python tools/build_portable.py --combine dist/*.zip --out dist/
    python tools/build_portable.py --check-tor           # is there a newer Tor?

A build is ``unseenet-<version>-<platform>.zip`` containing::

    Unseenet/
      UNSEENET-PORTABLE, README.txt, LICENSES/, the launcher for that platform
      <platform>/unseenet[.exe], <platform>/_internal/   (PyInstaller, one folder)
      <platform>/tor/                                    (Tor Expert Bundle)

``--combine`` merges several into ``unseenet-<version>-usb.zip`` with every
platform and every launcher, for a stick that works on any computer.

Tor comes from the Tor Project's *Expert Bundle*. It is downloaded from
dist.torproject.org and its OpenPGP signature is checked against the Tor
Browser Developers key in ``tools/keys`` (fingerprint pinned below) with
``gpg``. Without gpg the download is refused. CI fetches and verifies the
bundles on Linux and hands them, with their SHA-256, to the per-OS builds.

PyInstaller builds one *folder*, not one file: a one-file program unpacks
itself into the computer's temp directory at every start, which is exactly
what a USB client must not do.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
DIST_URL = "https://dist.torproject.org/torbrowser/"
TOR_KEY = TOOLS / "keys" / "torbrowser-signing-key.asc"
TOR_KEY_FINGERPRINT = "EF6E286DDA85EA2A4BA7DE684E2C6E8793298290"   # Tor Browser Developers
PLATFORMS = ("linux-x86_64", "windows-x86_64", "macos-aarch64", "macos-x86_64")
TOP = "Unseenet"
MARKER = "UNSEENET-PORTABLE"


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def version() -> str:
    text = (ROOT / "src" / "unseenet" / "__init__.py").read_text()
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def this_platform() -> str:
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}[machine]
    system = {"linux": "linux", "win32": "windows", "darwin": "macos"}[sys.platform]
    return f"{system}-{arch}"


# ---------------------------------------------------------------------------
# Tor
# ---------------------------------------------------------------------------
def pinned_tor_version() -> str:
    return (TOOLS / "tor-version.txt").read_text().strip()


def latest_tor_version() -> str:
    """The newest stable (non-alpha) Tor Browser release that has expert bundles."""
    with urllib.request.urlopen(DIST_URL, timeout=60) as r:
        listing = r.read().decode()
    versions = set(re.findall(r'href="(\d+(?:\.\d+)+)/"', listing))
    return max(versions, key=lambda v: tuple(int(x) for x in v.split(".")))


def download(url: str, dest: Path) -> Path:
    log(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return dest


def verify_signature(archive: Path, signature: Path) -> None:
    """Refuse unless ``signature`` is a good signature by the pinned Tor key."""
    gpg = shutil.which("gpg")
    if not gpg:
        sys.exit("gpg is needed to verify Tor's signature; install GnuPG "
                 "(or use --tor-archive with a bundle verified elsewhere)")
    with tempfile.TemporaryDirectory() as home:
        base = [gpg, "--homedir", home, "--batch", "--no-tty"]
        subprocess.run(base + ["--import", str(TOR_KEY)], check=True, capture_output=True)
        out = subprocess.run(base + ["--status-fd", "1", "--verify", str(signature), str(archive)],
                             capture_output=True, text=True)
    # [GNUPG:] VALIDSIG <signing subkey fpr> <date> ... <primary key fpr>
    valid = [ln.split() for ln in out.stdout.splitlines() if ln.startswith("[GNUPG:] VALIDSIG ")]
    if out.returncode != 0 or not valid or valid[0][-1].upper() != TOR_KEY_FINGERPRINT:
        sys.exit(f"BAD SIGNATURE on {archive.name} - refusing to build with it.\n{out.stderr}")
    log(f"good signature on {archive.name} by {TOR_KEY_FINGERPRINT}")


def fetch_tor(plat: str, tor_version: str, out: Path) -> Path:
    """Download and verify the expert bundle; writes <archive> and <archive>.sha256."""
    out.mkdir(parents=True, exist_ok=True)
    name = f"tor-expert-bundle-{plat}-{tor_version}.tar.gz"
    archive = download(f"{DIST_URL}{tor_version}/{name}", out / name)
    signature = download(f"{DIST_URL}{tor_version}/{name}.asc", out / f"{name}.asc")
    verify_signature(archive, signature)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / f"{name}.sha256").write_text(f"{digest}  {name}\n")
    return archive


def check_archive_digest(archive: Path) -> None:
    sidecar = archive.with_name(archive.name + ".sha256")
    if not sidecar.exists():
        sys.exit(f"{sidecar.name} missing: fetch Tor with --fetch-tor, which verifies it")
    expected = sidecar.read_text().split()[0]
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected:
        sys.exit(f"{archive.name}: SHA-256 does not match the verified download")


def unpack_tor(archive: Path, dest: Path, licenses: Path) -> None:
    """tor/ of the bundle -> dest/, plus the GeoIP files; its licences -> licenses/."""
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(archive) as tar:
        kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(tmp, **kwargs)
        src = Path(tmp)
        shutil.copytree(src / "tor", dest, symlinks=True, dirs_exist_ok=True)
        for geo in ("geoip", "geoip6"):
            if (src / "data" / geo).exists():
                shutil.copy2(src / "data" / geo, dest / geo)
        docs = src / "docs"
        for doc in docs.glob("*.txt") if docs.exists() else []:
            shutil.copy2(doc, licenses / f"tor-bundle-{doc.name}")
        for prog in [dest / "tor", dest / "pluggable_transports" / "lyrebird",
                     dest / "pluggable_transports" / "conjure-client"]:
            if prog.exists():
                prog.chmod(0o755)


# ---------------------------------------------------------------------------
# The program
# ---------------------------------------------------------------------------
def pyinstaller(plat: str, work: Path) -> Path:
    """One-folder build of unseenet.launcher. Returns the folder."""
    entry = work / "unseenet_entry.py"
    entry.write_text("from unseenet.launcher import main\nmain()\n")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
           "--console", "--name", "unseenet",
           "--distpath", str(work / "dist"), "--workpath", str(work / "build"),
           "--specpath", str(work),
           # Textual and Rich import parts of themselves lazily, by name
           "--collect-all", "textual", "--collect-submodules", "rich",
           "--collect-submodules", "unseenet",
           # PyNaCl's libsodium comes through cffi, which PyInstaller does not see
           "--collect-all", "nacl", "--hidden-import", "_cffi_backend",
           # Pillow is only here to convert the icon; none of these are used at run time
           "--exclude-module", "PIL", "--exclude-module", "tkinter",
           "--exclude-module", "unittest", "--exclude-module", "pydoc_data"]
    if not plat.startswith("windows"):
        cmd.append("--strip")                       # debug symbols: a lot of megabytes
    icon = ROOT / "assets" / "icon-512.png"        # PyInstaller converts it (needs Pillow)
    if icon.exists() and not plat.startswith("linux"):
        try:
            import PIL  # noqa: F401
            cmd += ["--icon", str(icon)]
        except ImportError:
            log("Pillow not installed: building without an icon")
    cmd.append(str(entry))
    try:
        import textual  # noqa: F401
    except ImportError:
        sys.exit('the terminal client needs Textual: pip install ".[tui]" pyinstaller')
    log("running PyInstaller")
    subprocess.run(cmd, check=True, cwd=work)
    return work / "dist" / "unseenet"


LAUNCHER_FILES = {
    "linux": ["start-linux.sh"],
    "windows": ["Start Unseenet.bat"],
    "macos": ["Start Unseenet.command"],
}


def common_files(top: Path) -> None:
    (top / MARKER).write_text(
        "This folder is a portable Unseenet. Its programs keep everything in data/\n"
        "beside them. Delete this file to make them use the current directory.\n")
    shutil.copy2(TOOLS / "portable" / "README.txt", top / "README.txt")
    licenses = top / "LICENSES"
    licenses.mkdir(exist_ok=True)
    for name in ("LICENSE", "NOTICE"):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, licenses / f"unseenet-{name}.txt")


def add_launchers(top: Path, system: str) -> None:
    for name in LAUNCHER_FILES[system]:
        target = top / name
        data = (TOOLS / "portable" / name).read_bytes().replace(b"\r\n", b"\n")
        if system == "windows":
            data = data.replace(b"\n", b"\r\n")      # cmd.exe wants CRLF
        target.write_bytes(data)
        target.chmod(0o644 if system == "windows" else 0o755)


def build(plat: str, tor_archive: Path, out: Path, keep: bool = False) -> Path:
    system = plat.split("-")[0]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        stage = work / "stage" / TOP
        prog_dir = stage / plat
        stage.mkdir(parents=True)
        common_files(stage)
        add_launchers(stage, system)
        folder = pyinstaller(plat, work)
        shutil.copytree(folder, prog_dir, symlinks=True)
        check_archive_digest(tor_archive)
        unpack_tor(tor_archive, prog_dir / "tor", stage / "LICENSES")
        (prog_dir / "tor" / "VERSION").write_text(tor_archive.name + "\n")
        out.mkdir(parents=True, exist_ok=True)
        zip_path = out / f"unseenet-{version()}-{plat}.zip"
        write_zip(stage, zip_path)
        if keep:
            shutil.copytree(stage, out / f"{TOP}-{plat}", symlinks=True, dirs_exist_ok=True)
    log(f"built {zip_path} ({zip_path.stat().st_size // (1024 * 1024)} MB)")
    return zip_path


# ---------------------------------------------------------------------------
# Zips that keep execute bits, and the all-in-one USB zip
# ---------------------------------------------------------------------------
def write_zip(stage: Path, zip_path: Path) -> None:
    """Zip ``stage`` (the Unseenet/ folder) keeping Unix modes and symlinks."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(stage.rglob("*")):
            arc = (Path(TOP) / path.relative_to(stage)).as_posix()
            st = path.lstat()
            if path.is_symlink():
                info = zipfile.ZipInfo(arc, (2026, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o120777 << 16
                z.writestr(info, os.readlink(path))
            elif path.is_dir():
                info = zipfile.ZipInfo(arc + "/", (2026, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (0o40755 << 16) | 0x10
                z.writestr(info, b"")
            else:
                info = zipfile.ZipInfo(arc, (2026, 1, 1, 0, 0, 0))   # same input, same zip
                info.create_system = 3
                mode = 0o755 if (st.st_mode & 0o111) else 0o644
                info.external_attr = (0o100000 | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, path.read_bytes())


def extract_zip(zip_path: Path, dest: Path) -> None:
    """Extract keeping modes and symlinks (zipfile alone drops both)."""
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            target = dest / info.filename
            mode = (info.external_attr >> 16) & 0o177777
            if info.filename.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            data = z.read(info)
            if mode & 0o170000 == 0o120000:
                if target.is_symlink() or target.exists():
                    target.unlink()
                target.symlink_to(data.decode())
                continue
            target.write_bytes(data)
            if mode:
                target.chmod(mode & 0o777)


def combine(zips: list[Path], out: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        stage_parent = Path(tmp)
        for z in zips:
            log(f"adding {z.name}")
            extract_zip(z, stage_parent)
        stage = stage_parent / TOP
        for system in LAUNCHER_FILES:
            add_launchers(stage, system)
        zip_path = out / f"unseenet-{version()}-usb.zip"
        out.mkdir(parents=True, exist_ok=True)
        write_zip(stage, zip_path)
    log(f"built {zip_path} ({zip_path.stat().st_size // (1024 * 1024)} MB)")
    return zip_path


def checksums(paths: list[Path], out: Path) -> Path:
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in sorted(paths)]
    out.mkdir(parents=True, exist_ok=True)
    target = out / "SHA256SUMS.txt"
    target.write_text("\n".join(lines) + "\n")
    return target


# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--platform", default=None, choices=PLATFORMS, help="default: this computer")
    p.add_argument("--tor-version", default=None,
                   help="Tor Browser release (default: tools/tor-version.txt; 'latest')")
    p.add_argument("--tor-archive", type=Path, help="an expert bundle fetched with --fetch-tor")
    p.add_argument("--fetch-tor", nargs="+", metavar="PLATFORM", help="download and verify bundles, then stop")
    p.add_argument("--combine", nargs="+", type=Path, metavar="ZIP", help="merge platform zips into the USB zip")
    p.add_argument("--checksums", nargs="+", type=Path, metavar="FILE", help="write SHA256SUMS.txt for files")
    p.add_argument("--check-tor", action="store_true", help="exit 1 if a newer stable Tor exists")
    p.add_argument("--keep", action="store_true", help="also keep the unzipped folder in --out")
    p.add_argument("--out", type=Path, default=ROOT / "dist-portable")
    args = p.parse_args()

    if args.check_tor:
        latest, pinned = latest_tor_version(), pinned_tor_version()
        print(f"pinned {pinned}, latest {latest}")
        sys.exit(0 if latest == pinned else 1)
    tor_version = args.tor_version or pinned_tor_version()
    if tor_version == "latest":
        tor_version = latest_tor_version()
    if args.fetch_tor:
        for plat in args.fetch_tor:
            fetch_tor(plat, tor_version, args.out)
        return
    if args.combine:
        combine(args.combine, args.out)
        return
    if args.checksums:
        print(checksums(args.checksums, args.out).read_text(), end="")
        return

    plat = args.platform or this_platform()
    archive = args.tor_archive
    if archive is None:
        archive = fetch_tor(plat, tor_version, args.out / "tor-download")
    build(plat, archive, args.out, keep=args.keep)


if __name__ == "__main__":
    main()

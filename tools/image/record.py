#!/usr/bin/env python3
"""A video of the bootable image for the documentation (docs/img/boot.webm).

Boots the image in QEMU, takes a picture of the screen several times a
second, types into it like a person would, and puts the pictures together
with ffmpeg. Waiting (the firmware, the kernel, the client starting) is sped up so
the video stays short; what the person does plays at normal speed.

    python tools/image/record.py IMAGE                      # docs/img/boot.webm and boot-poster.png
    python tools/image/record.py IMAGE --gif docs/img/boot.gif
    python tools/image/record.py IMAGE --frames-only DIR    # just the pictures, to find timings

Needs qemu-system-x86_64, socat and ffmpeg. The image is copied first, so
the original is not changed. KVM makes it much faster, but is not needed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# QEMU sendkey names for the characters we type
KEYS = {" ": "spc", "-": "minus", ".": "dot", ",": "comma", "'": "apostrophe", "!": "shift-1",
        "?": "shift-slash", "@": "shift-2", "\n": "ret", ":": "shift-semicolon"}


def key_names(text: str) -> list[str]:
    names = []
    for ch in text:
        if ch in KEYS:
            names.append(KEYS[ch])
        elif ch.isupper():
            names.append(f"shift-{ch.lower()}")
        else:
            names.append(ch)
    return names


def ppm_size(data: bytes) -> tuple[int, int]:
    parts = data[:40].split()
    return (int(parts[1]), int(parts[2])) if len(parts) > 2 else (0, 0)


class Machine:
    def __init__(self, image: Path, tmp: Path):
        self.tmp, self.mon_path = tmp, tmp / "mon"
        disk = tmp / "disk.img"
        subprocess.run(["cp", "--sparse=always", str(image), str(disk)], check=True)
        kvm = ["-enable-kvm", "-cpu", "host"] if os.access("/dev/kvm", os.W_OK) else []
        self.proc = subprocess.Popen(
            ["qemu-system-x86_64", *kvm, "-m", "2048", "-smp", "2",
             "-drive", f"file={disk},format=raw,if=none,id=stick", "-device", "qemu-xhci",
             "-device", "usb-storage,drive=stick,removable=on",
             "-netdev", "user,id=net", "-device", "virtio-net-pci,netdev=net",
             "-display", "none", "-vga", "std",
             "-monitor", f"unix:{self.mon_path},server,nowait"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if self.mon_path.exists():
                break
            time.sleep(0.1)
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect(str(self.mon_path))
        self.sock.settimeout(5)
        self._drain()

    def _drain(self) -> None:
        time.sleep(0.05)
        self.sock.setblocking(False)
        try:
            while self.sock.recv(65536):
                pass
        except BlockingIOError:
            pass
        self.sock.setblocking(True)
        self.sock.settimeout(5)

    def cmd(self, line: str) -> None:
        self.sock.sendall(line.encode() + b"\n")
        self._drain()

    def screendump(self, path: Path) -> bool:
        self.cmd(f"screendump {path}")
        for _ in range(40):
            if path.exists() and path.stat().st_size > 0:
                return True
            time.sleep(0.025)
        return False

    def stop(self) -> None:
        try:
            self.cmd("quit")
        except OSError:
            pass
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class Film:
    """Pictures of the screen with how long each is shown in the video."""

    def __init__(self, machine: Machine, frames: Path, every: float = 0.25):
        self.m, self.dir, self.every = machine, frames, every
        self.shots: list[tuple[Path, float]] = []   # (picture, seconds in the video)
        self.speed = 1.0
        self.poster: Path | None = None     # a picture to show before the video plays

    def shoot(self, seconds: float) -> None:
        """Keep filming for `seconds` of real time, at the current speed."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._one()

    def _one(self) -> bytes:
        """One picture; it stays on screen for the real time it took, divided by the speed."""
        t0 = time.monotonic()
        path = self.dir / f"{len(self.shots):05d}.ppm"
        ok = self.m.screendump(path)
        time.sleep(max(0.0, self.every * self.speed - (time.monotonic() - t0)))
        d = (time.monotonic() - t0) / self.speed
        if ok:
            self.shots.append((path, d))
            return path.read_bytes()
        if self.shots:
            self.hold(d)
        return b""

    def until_still(self, still: float = 3.0, timeout: float = 400.0,
                    size: tuple[int, int] | None = None) -> None:
        """Film until the screen has not changed for `still` seconds (and has `size`)."""
        end, last, since = time.monotonic() + timeout, b"", time.monotonic()
        while time.monotonic() < end:
            pic = self._one()
            if pic != last:
                last, since = pic, time.monotonic()
            elif time.monotonic() - since >= still and (size is None or ppm_size(pic) == size):
                return
        print("warning: the screen did not settle", file=sys.stderr)

    def until(self, cond, timeout: float = 400.0) -> None:
        """Film until a picture of the screen makes `cond` true."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond(self._one()):
                return
        print("warning: gave up waiting", file=sys.stderr)

    def type(self, text: str, pause: float = 0.08) -> None:
        for name in key_names(text):
            self.m.cmd(f"sendkey {name}")
            self.shoot(pause)

    def key(self, name: str) -> None:
        self.m.cmd(f"sendkey {name}")

    def hold(self, seconds: float) -> None:
        """Show the last picture a little longer."""
        if self.shots:
            path, d = self.shots[-1]
            self.shots[-1] = (path, d + seconds)

    def write(self, out: Path, gif: Path | None, width: int = 1024) -> None:
        listing = self.dir / "frames.txt"
        with listing.open("w") as f:
            for path, d in self.shots:
                f.write(f"file '{path}'\nduration {max(d, 0.02):.3f}\n")
            f.write(f"file '{self.shots[-1][0]}'\n")
        height = width * 5 // 8
        scale = (f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                 f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black")
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(listing), "-vf", f"{scale},fps=10", "-c:v", "libvpx-vp9",
                        "-b:v", "0", "-crf", "36", "-row-mt", "1", "-an", str(out)], check=True)
        if self.poster:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(self.poster),
                            "-vf", scale, str(out.with_name(out.stem + "-poster.png"))], check=True)
        if gif:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                            "-i", str(listing), "-vf",
                            f"{scale},fps=8,split[a][b];[a]palettegen=max_colors=64[p];"
                            "[b][p]paletteuse=dither=none", str(gif)], check=True)


def menu_shown(picture: bytes) -> bool:
    """The Unseenet menu: its highlighted line is a wide bar in console cyan."""
    return picture.count(b"\x00\xaa\xaa") > 9000


def scene(film: Film, passphrase: str) -> None:
    """What the video shows. It waits for the screen to settle, so it works with and without KVM."""
    film.speed = 15.0
    film.until(menu_shown)            # firmware, boot loader, kernel: sped up
    film.speed = 1.0
    film.shoot(3)                     # the Unseenet menu
    film.poster = film.shots[-1][0]
    film.key("ret")                   # Client
    film.speed = 4.0
    film.until_still(still=3.0, timeout=120)        # the client starts
    film.speed = 1.0
    film.shoot(1.5)
    film.type(passphrase)             # a new vault: the passphrase, twice
    film.key("tab")
    film.shoot(0.4)
    film.type(passphrase)
    film.shoot(0.6)
    film.key("ret")
    film.speed = 4.0
    film.until_still(still=4.0, timeout=180)        # the vault is made: the welcome dialog
    film.speed = 1.0
    film.shoot(1.5)
    film.type("Andreas")              # the name others see; the node is picked already
    film.shoot(2)
    film.hold(3)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("image")
    p.add_argument("--out", default=str(ROOT / "docs" / "img" / "boot.webm"))
    p.add_argument("--gif")
    p.add_argument("--frames-only", metavar="DIR", help="save every picture here, with its time")
    p.add_argument("--seconds", type=float, default=180, help="how long --frames-only films")
    args = p.parse_args()
    for tool in ("qemu-system-x86_64", "ffmpeg"):
        if not shutil.which(tool):
            sys.exit(f"{tool} is needed")

    with tempfile.TemporaryDirectory(prefix="unseenet-rec-") as tmp:
        tmp = Path(tmp)
        frames = Path(args.frames_only) if args.frames_only else tmp / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        machine = Machine(Path(args.image), tmp)
        film = Film(machine, frames, every=1.0 if args.frames_only else 0.25)
        start = time.monotonic()
        try:
            if args.frames_only:
                film.shoot(args.seconds)
            else:
                scene(film, "correct horse battery")
        finally:
            machine.stop()
        if args.frames_only:
            print(f"{len(film.shots)} pictures in {frames}, {time.monotonic() - start:.0f} s")
            return
        film.write(Path(args.out), Path(args.gif) if args.gif else None)
        print(args.out)


if __name__ == "__main__":
    main()

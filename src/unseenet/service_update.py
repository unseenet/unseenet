"""Servers that update themselves (UN-RFC 0062 section 6.1, #827).

    unseenet-service-update run    --service unseenet-node [--check tcp:127.0.0.1:1119]
    unseenet-service-update status --service unseenet-node
    unseenet-service-update off    --service unseenet-node      (and ``on``)

What the update timer of a node, a replica or a registrar runs, as root. It runs from
the service's own virtual environment and updates that one:

1. **Only signed.** It reads the newest stable release's ``SHA256SUMS.txt`` and its
   signature (the project key, as sticks do) and takes the release's
   ``unseenet-<version>-server-requirements.txt``: every package with its hash. pip
   installs with ``--require-hashes``, so nothing else gets in.
2. **Never older**, and never a version that broke here before.
3. **Not all at once.** It waits a random time of up to 48 hours after it first saw
   the release.
4. **Back if broken.** The environment is copied first. After the restart the service
   must stay up for a minute within 10 minutes (and answer, with ``--check``);
   otherwise the copy is put back, the service restarted, and that version skipped.

Turned ``off``, it still looks once a day, and says so in the log when a newer
release has existed for 30 days.

State: ``/var/lib/unseenet-update/<service>/state.json``; the copy is ``<venv>.prev``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__
from . import update as up

STATE_ROOT = Path("/var/lib/unseenet-update")
SPREAD = 48 * 3600            # section 6.1 item 4
HEALTHY_WITHIN = 600          # item 5: 10 minutes
STAY_UP = 60                  # up this long, without restarting, counts as up
NAG_AFTER = 30 * 86400        # when turned off
REQUIREMENTS = "unseenet-{version}-server-requirements.txt"


class Problem(Exception):
    pass


@dataclass
class Release:
    version: str
    requirements: bytes        # checked against the signed sums


def newest_release(fetch: Callable[[str], bytes] = lambda u: up.fetch(u, None)) -> Release:
    """The newest stable release that servers can take: signed by the project key, and
    with a server requirements file matching its checksums."""
    sums = fetch(up.release_url("stable", up.SUMS))
    sig = fetch(up.release_url("stable", up.SIG)).decode("utf-8", "replace")
    try:
        up.check_signature(sums, sig, "stable")
    except up.UpdateError as exc:
        raise Problem(str(exc)) from exc
    listed = up.parse_sums(sums)
    names = [n for n in listed if n.startswith("unseenet-") and n.endswith("-server-requirements.txt")]
    if len(names) != 1:
        raise Problem("the newest release has no server requirements (it is older than "
                      "self-updating servers)")
    name = names[0]
    version = name[len("unseenet-"):-len("-server-requirements.txt")]
    req = fetch(up.release_url("stable", name, version))
    if hashlib.sha256(req).hexdigest() != listed[name]:
        raise Problem(f"{name} does not match the signed checksums")
    if f"unseenet=={version} " not in req.decode("utf-8", "replace"):
        raise Problem(f"{name} does not name unseenet {version}")
    return Release(version, req)


# --- state ------------------------------------------------------------------------------

@dataclass
class State:
    path: Path
    data: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> State:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = {}
        data.setdefault("seen", {})          # version -> [first seen, chosen delay]
        data.setdefault("skip", [])          # versions that broke here
        data.setdefault("off", False)
        return cls(path, data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True))
        os.replace(tmp, self.path)

    def due_at(self, version: str, now: float) -> float:
        """When ``version`` may be installed: first seen plus a random delay (item 4)."""
        if version not in self.data["seen"]:
            self.data["seen"][version] = [now, random.uniform(0, SPREAD)]
        seen, delay = self.data["seen"][version]
        return seen + delay

    def note(self, **kw) -> None:
        self.data.update(kw)


# --- what an update does to the machine (replaced in tests) ------------------------------

class Machine:
    """The service, its virtual environment and systemd."""

    def __init__(self, service: str, venv: Path, check: str | None = None):
        self.service, self.venv, self.check = service, venv, check

    @property
    def prev(self) -> Path:
        return self.venv.with_name(self.venv.name + ".prev")

    def installed(self) -> str:
        r = subprocess.run([str(self.venv / "bin" / "python"), "-c",
                            "import unseenet; print(unseenet.__version__)"],
                           capture_output=True, text=True)
        return r.stdout.strip() or __version__

    def copy(self) -> None:
        if self.prev.exists():
            shutil.rmtree(self.prev)
        subprocess.run(["cp", "-a", str(self.venv), str(self.prev)], check=True)

    def install(self, requirements: bytes, workdir: Path) -> None:
        """pip, as the owner of the environment, with every hash required."""
        workdir.mkdir(parents=True, exist_ok=True)
        req = workdir / "requirements.txt"
        req.write_bytes(requirements)
        owner = self.venv.stat().st_uid
        os.chown(workdir, owner, -1)
        os.chown(req, owner, -1)
        r = subprocess.run([str(self.venv / "bin" / "pip"), "install", "--quiet",
                            "--disable-pip-version-check", "--require-hashes",
                            "-r", str(req)],
                           capture_output=True, text=True, user=owner if owner else None)
        if r.returncode != 0:
            raise Problem(f"pip failed: {r.stderr.strip()[-800:]}")

    def restore(self) -> None:
        bad = self.venv.with_name(self.venv.name + ".bad")
        if bad.exists():
            shutil.rmtree(bad)
        os.rename(self.venv, bad)
        os.rename(self.prev, self.venv)
        shutil.rmtree(bad, ignore_errors=True)

    def restart(self) -> None:
        subprocess.run(["systemctl", "restart", self.service], capture_output=True)

    def _show(self) -> tuple[str, int]:
        r = subprocess.run(["systemctl", "show", "-p", "ActiveState", "-p", "NRestarts",
                            self.service], capture_output=True, text=True)
        f = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
        return f.get("ActiveState", ""), int(f.get("NRestarts", "0") or 0)

    def answers(self) -> bool:
        """``--check tcp:host:port``: it greets as an NNTP server does (``200``/``201``)."""
        if not self.check:
            return True
        host, _, port = self.check.removeprefix("tcp:").rpartition(":")
        try:
            with socket.create_connection((host, int(port)), timeout=10) as s:
                return s.recv(64).startswith((b"200", b"201"))
        except (OSError, ValueError):
            return False

    def healthy(self, within: float = HEALTHY_WITHIN, stay: float = STAY_UP,
                sleep: Callable[[float], None] = time.sleep) -> bool:
        """Up for ``stay`` seconds without a restart, and answering, within ``within``."""
        start = time.monotonic()
        up_since, restarts = None, None
        while time.monotonic() - start < within:
            state, n = self._show()
            if state == "active" and (restarts is None or n == restarts):
                up_since = up_since or time.monotonic()
                if time.monotonic() - up_since >= stay and self.answers():
                    return True
            else:
                up_since = None
            restarts = n
            sleep(5)
        return False


# --- one run ----------------------------------------------------------------------------

def run(machine: Machine, state: State, find: Callable[[], Release] = newest_release,
        now: Callable[[], float] = time.time, say: Callable[[str], None] = print,
        at_once: bool = False) -> str:
    """One look, and an update when one is due. Returns what happened, in a word:
    ``current``, ``waiting``, ``off``, ``skipped``, ``updated`` or ``rolled-back``."""
    have = machine.installed()
    rel = find()
    t = now()
    state.note(checked=t, installed=have, newest=rel.version)
    if up.version_key(rel.version) <= up.version_key(have):
        state.save()
        say(f"up to date ({have})")
        return "current"
    if rel.version in state.data["skip"]:
        state.save()
        say(f"{rel.version} broke this service before; staying on {have}")
        return "skipped"
    due = state.due_at(rel.version, t)
    if state.data["off"]:
        seen = state.data["seen"][rel.version][0]
        if t - seen >= NAG_AFTER:
            say(f"WARNING: self-updating is off, and {rel.version} has been out for "
                f"{int((t - seen) // 86400)} days; this runs {have}")
        else:
            say(f"self-updating is off; {rel.version} is out (this runs {have})")
        state.save()
        return "off"
    if t < due and not at_once:
        state.save()
        say(f"{rel.version} is out; updating after {time.strftime('%Y-%m-%d %H:%M', time.gmtime(due))} UTC")
        return "waiting"
    say(f"updating {have} -> {rel.version}")
    machine.copy()
    try:
        machine.install(rel.requirements, state.path.parent / "work")
        machine.restart()
        ok = machine.healthy()
    except Problem as exc:
        say(str(exc))
        ok = False
    if ok:
        state.note(updated=t, previous=have, problem=None)
        state.save()
        say(f"updated to {rel.version}")
        return "updated"
    machine.restore()
    machine.restart()
    state.data["skip"].append(rel.version)
    state.note(problem=f"{rel.version} did not come up; went back to {have} and will not "
                       "try that version again")
    state.save()
    say(f"ERROR: {state.data['problem']}")
    return "rolled-back"


def explain(state: State) -> list[str]:
    d = state.data
    out = [f"Self-updating: {'off' if d['off'] else 'on'}"]
    if d.get("installed"):
        out.append(f"Runs {d['installed']}; newest stable release {d.get('newest', '?')}")
    if d.get("checked"):
        out.append("Last looked: " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(d["checked"])))
    if d.get("updated"):
        out.append("Last updated: " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(d["updated"]))
                   + f" (from {d.get('previous')})")
    if d.get("skip"):
        out.append("Skipped (broke here): " + ", ".join(d["skip"]))
    if d.get("problem"):
        out.append("Problem: " + d["problem"])
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="unseenet-service-update", description=__doc__.split("\n\n")[0])
    p.add_argument("action", choices=("run", "status", "on", "off"))
    p.add_argument("--service", required=True, help="the systemd service, e.g. unseenet-node")
    p.add_argument("--venv", default=sys.prefix, help="its virtual environment (default: this one)")
    p.add_argument("--check", help="tcp:host:port where the service answers (a node: tcp:127.0.0.1:1119)")
    p.add_argument("--now", action="store_true", help="do not wait the random delay")
    p.add_argument("--state", default=None, help=f"state folder (default {STATE_ROOT}/<service>)")
    a = p.parse_args(argv)
    state = State.load(Path(a.state or STATE_ROOT / a.service) / "state.json")
    if a.action in ("on", "off"):
        state.note(off=a.action == "off")
        state.save()
        print(f"Self-updating of {a.service} is {a.action}.")
        return 0
    if a.action == "status":
        print("\n".join(explain(state)))
        return 0
    if os.geteuid() != 0:
        print("Updating a service needs root (it restarts the service).")
        return 1
    try:
        what = run(Machine(a.service, Path(a.venv), a.check), state, at_once=a.now)
    except (Problem, up.UpdateError, OSError) as exc:
        print(f"could not look for updates: {exc}")
        return 1
    return 1 if what == "rolled-back" else 0


if __name__ == "__main__":
    sys.exit(main())

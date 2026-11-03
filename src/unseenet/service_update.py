"""Servers that update themselves (UN-RFC 0062 section 6.1, #827).

    unseenet-service-update run    --service unseenet-node [--check tcp:127.0.0.1:1119]
    unseenet-service-update status --service unseenet-node
    unseenet-service-update off    --service unseenet-node      (and ``on``)
    unseenet-service-update run    --service unseenet-gateway --package unseenet-gateway

What the update timer of a node, a replica, a registrar - or any other Unseenet
service: a gateway, an entrance, a watchman, a bot - runs, as root. It runs from the
service's own virtual environment and updates that one:

1. **Only signed.** It reads the newest stable release's ``SHA256SUMS.txt`` and its
   signature (the project key, as sticks do) and takes the release's
   ``<package>-<version>-server-requirements.txt``: every package with its hash. pip
   installs with ``--require-hashes``, so nothing else gets in. ``--package`` names the
   service's package (default ``unseenet``); its releases are in the repository of the
   same name under github.com/unseenet (``--repo`` for another).
2. **Never older**, and never a version that broke here before.
3. **Not all at once.** It waits a random time of up to 48 hours after it first saw
   the release.
4. **Back if broken.** The environment is copied first. After the restart the service
   must stay up for a minute within 10 minutes (and answer, with ``--check``);
   otherwise the copy is put back, the service restarted, and that version skipped.

5. **Over Tor** (#900): the checksums, the requirements and every package pip fetches
   go through Tor - a Tor already running on 127.0.0.1:9050 (``--socks`` for another
   port), else one it starts for the run - so nobody watching GitHub or PyPI can tell
   from the downloads after a release which machines run a server, or where. pip gets
   a local proxy (``torconnect.py``). ``--direct`` (or ``UNSEENET_UPDATE_DIRECT=1``,
   e.g. in ``/etc/unseenet-update/<service>.env``) downloads without Tor; without it,
   no Tor means no update, never a quiet fallback.

6. **From the network first** (#901): the owner posts each server release in
   ``unseenet.releases`` (``tools/project/sign_release.py``): the signed checksums,
   their signature and the requirements. The updater reads them through a node - the
   one on this machine (127.0.0.1:1119) if there is one, else the known nodes over Tor
   (``--node`` for another) - and asks GitHub only when the network has no release
   of its package. The signature and the hashes are checked the same either way.

7. **Sources set in the network** (#902): the newest list of release sources the
   project key signed (``release_sources.py``), kept in the state so it outlives a
   network that does not answer, gives the package indexes pip uses and where a wheel
   that is not on PyPI is fetched from. Without one, PyPI and GitHub.

Turned ``off``, it still looks once a day, and says so in the log when a newer
release has existed for 30 days.

State: ``/var/lib/unseenet-update/<service>/state.json``; the copy is ``<venv>.prev``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import random
import re
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
BUSY_FOR = 6 * 3600           # a --busy file older than this is left over, not busy
SUFFIX = "-server-requirements.txt"
CORE = "unseenet"
VERSION = re.compile(r"\d+(\.\d+)*([abc]|rc)?\d*")
PACKAGE = re.compile(r"unseenet(-[a-z0-9]+)*")


class Problem(Exception):
    pass


@dataclass
class Release:
    version: str
    requirements: bytes        # checked against the signed sums


def repo_url(repo: str) -> str:
    """``unseenet/unseenet-gateway`` (or just ``unseenet-gateway``) -> its GitHub URL."""
    owner, _, name = repo.rpartition("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or not re.fullmatch(r"[A-Za-z0-9_.-]*", owner):
        raise Problem(f"not a repository: {repo}")
    return f"https://github.com/{owner or 'unseenet'}/{name}"


def requirements_version(name: str, package: str) -> str | None:
    """``unseenet-gateway-0.6.0-server-requirements.txt`` -> ``0.6.0`` for that package."""
    if not (name.startswith(package + "-") and name.endswith(SUFFIX)):
        return None
    version = name[len(package) + 1:-len(SUFFIX)]
    return version if VERSION.fullmatch(version) else None


# --- the releases in the network (#901) -------------------------------------------------

POST_HEAD = re.compile(r"^Unseenet server (?P<package>unseenet(?:-[a-z0-9]+)*) "
                       r"(?P<version>[0-9][0-9A-Za-z.+]*), (?P<channel>stable|dev)$")
PACKED = " (gzip, base64):"
SCAN = 400                    # the newest articles of unseenet.releases looked through
LOCAL_NODE = "127.0.0.1:1119"


def server_post(package: str, version: str, sums: bytes, sig: str, req_name: str,
                req: bytes, channel: str = "stable") -> tuple[str, str]:
    """(subject, body) of the post in unseenet.releases that carries a server release:
    the signed checksums, their signature and the requirements (packed: with every hash
    the file is tens of kilobytes). Nothing in it is trusted until the signature is
    checked; the requirements must match the signed sums."""
    import base64
    import gzip
    packed = base64.encodebytes(gzip.compress(req, 9, mtime=0)).decode()
    body = (f"Unseenet server {package} {version}, {channel}\n\n{up.SUMS}:\n{sums.decode()}"
            f"\n{up.SIG}:\n{sig.rstrip()}\n\n{req_name}{PACKED}\n{packed}")
    return f"Unseenet server {package} {version}", body


def parse_server_post(body: str) -> dict | None:
    """The parts of such a post, or None for anything else."""
    import base64
    import binascii
    import gzip
    lines = body.replace("\r\n", "\n").split("\n")
    m = POST_HEAD.match(lines[0]) if lines else None
    if not m or f"{up.SUMS}:" not in lines or f"{up.SIG}:" not in lines:
        return None
    i, j = lines.index(f"{up.SUMS}:"), lines.index(f"{up.SIG}:")
    k = next((n for n, line in enumerate(lines) if line.endswith(PACKED)), None)
    if k is None or not i < j < k:
        return None
    try:
        req = gzip.decompress(base64.b64decode("".join(lines[k + 1:]), validate=False))
    except (binascii.Error, OSError, EOFError):
        return None
    return {**m.groupdict(), "sums": ("\n".join(lines[i + 1:j]).strip("\n") + "\n").encode(),
            "sig": "\n".join(lines[j + 1:k]).strip("\n") + "\n",
            "name": lines[k][:-len(PACKED)], "requirements": req}


def from_posts(bodies: list[str], package: str, base: str, keys=None) -> Release | None:
    """The newest valid stable release of ``package`` among the posts, signed by enough
    of the publisher's keys (``keys``, UN-RFC 0062; by default the pinned list)."""
    best: Release | None = None
    for body in bodies:
        if not isinstance(body, str):
            continue
        post = parse_server_post(body)
        if not post or post["package"] != package or post["channel"] != "stable":
            continue
        try:
            up.check_signature(post["sums"], post["sig"], "stable", keys)
        except up.UpdateError:
            continue                     # not signed by enough of the keys: ignored
        listed = up.parse_sums(post["sums"])
        name, req = post["name"], post["requirements"]
        version = requirements_version(name, package)
        if (not version or listed.get(name) != hashlib.sha256(req).hexdigest()
                or not names_itself(req.decode("utf-8", "replace"), package, version, base)):
            continue
        if best is None or up.version_key(version) > up.version_key(best.version):
            best = Release(version, req)
    return best


async def _posts_from(address: str, socks: int | None, package: str) -> list[str]:
    """The server posts for ``package`` and the lists of release sources (#902) in
    unseenet.releases, newest first, through one node."""
    from . import release_sources as rs
    from .known_nodes import RELEASES_GROUP
    from .nntp import Client
    c = await asyncio.wait_for(Client.connect(address, socks), 120)
    try:
        found = await rs.read_group(c, RELEASES_GROUP,
                                    (f"Unseenet server {package} ", rs.HEAD), scan=SCAN)
        from . import release_keys as rk     # and the key list's chain (UN-RFC 0062 3)
        return ([body for bodies in found.values() for body in bodies]
                + await rk.read_votes(c, RELEASES_GROUP, scan=SCAN))
    finally:
        with contextlib.suppress(Exception):
            await c.quit()


def posts_in_network(package: str, socks: int | None, node: str | None = None) -> list[str]:
    """The posts for ``package`` in unseenet.releases, through ``node``, else the node on
    this machine, else the known nodes (over Tor only: without Tor, none)."""
    if node:
        nodes = [node]
    elif _listening(int(LOCAL_NODE.rsplit(":", 1)[1])):
        nodes = [LOCAL_NODE]
    elif socks is not None:
        from .known_nodes import builtin_list
        nodes = [n.address for n in builtin_list()[1]]
        nodes = random.sample(nodes, min(len(nodes), 5))
    else:
        return []
    for address in nodes:
        try:
            return asyncio.run(_posts_from(address, socks, package))
        except Exception:  # noqa: BLE001 - the next node; GitHub after the last
            continue
    return []


def newest_release(fetch: Callable[[str], bytes] = lambda u: up.fetch(u, None),
                   package: str = CORE, repo: str | None = None,
                   network: Callable[[], list[str]] | None = None,
                   say: Callable[[str], None] = lambda _: None,
                   keys: dict | None = None) -> Release:
    """The newest stable release of ``package`` that servers can take: signed by the
    project key, and with a server requirements file matching its checksums. From the
    posts in the network when ``network`` gives any (#901), else from GitHub."""
    from . import release_keys as rk
    base = repo_url(repo or package)
    kl, fork = rk.newest(rk.votes_of(network() if network is not None else []),
                         (keys or {}).get("body"))
    if fork:
        raise Problem("the publisher's key list has forked (two lists with one number): no "
                      "update until the operator acts (UN-RFC 0062 section 3)")
    if keys is not None and kl.seq:
        keys["body"] = kl.body                    # kept: counted from it next time
    if network is not None:
        found = from_posts(network(), package, base, kl)
        if found is not None:
            say(f"found {package} {found.version} in the network")
            return found
        say(f"no release of {package} in the network; asking GitHub")
    sums = fetch(up.release_url("stable", up.SUMS, repo=base))
    sig = fetch(up.release_url("stable", up.SIG, repo=base)).decode("utf-8", "replace")
    try:
        up.check_signature(sums, sig, "stable", kl)
    except up.UpdateError as exc:
        raise Problem(str(exc)) from exc
    listed = up.parse_sums(sums)
    found = {n: v for n in listed if (v := requirements_version(n, package))}
    if len(found) != 1:
        raise Problem(f"the newest release of {package} has no server requirements (it is "
                      "older than self-updating servers)")
    (name, version), = found.items()
    req = fetch(up.release_url("stable", name, version, repo=base))
    if hashlib.sha256(req).hexdigest() != listed[name]:
        raise Problem(f"{name} does not match the signed checksums")
    if not names_itself(req.decode("utf-8", "replace"), package, version, base):
        raise Problem(f"{name} does not name {package} {version}")
    return Release(version, req)


def names_itself(requirements: str, package: str, version: str, base: str) -> bool:
    """The requirements install ``package`` at ``version``: from PyPI
    (``unseenet-gateway==0.6.0 --hash=...``), or, for a service not on PyPI, as the
    wheel of that very release (``unseenet-helpbot @ <base>/releases/download/v0.6.0/
    unseenet_helpbot-0.6.0-py3-none-any.whl --hash=...``)."""
    if f"{package}=={version} " in requirements:
        return True
    wheel = f"{base}/releases/download/v{version}/{package.replace('-', '_')}-{version}-"
    return any(line.startswith(f"{package} @ {wheel}") and ".whl " in line
               for line in requirements.splitlines())


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

    def __init__(self, service: str, venv: Path, check: str | None = None,
                 package: str = CORE, oneshot: bool = False, busy: Path | None = None,
                 socks_port: int | None = None, sources=None):
        self.service, self.venv, self.check, self.package = service, venv, check, package
        self.oneshot = oneshot     # a service its timer starts now and then (the bots)
        self.busy_file = busy      # there while it must not be restarted (a key ripening)
        self.socks_port = socks_port   # pip over Tor through a local proxy (None: direct)
        from .release_sources import BUILT_IN
        self.sources = sources or BUILT_IN   # indexes and file places (#902)

    def busy(self, now: float | None = None) -> bool:
        """The service says it must not be restarted now, in a file it keeps fresh."""
        if self.busy_file is None:
            return False
        try:
            age = (time.time() if now is None else now) - self.busy_file.stat().st_mtime
        except OSError:
            return False
        return age < BUSY_FOR

    @property
    def prev(self) -> Path:
        return self.venv.with_name(self.venv.name + ".prev")

    def installed(self) -> str:
        r = subprocess.run([str(self.venv / "bin" / "python"), "-c",
                            "import importlib.metadata as m, sys; print(m.version(sys.argv[1]))",
                            self.package], capture_output=True, text=True)
        version = r.stdout.strip()
        if not version and self.package == CORE:
            return __version__
        if not version:
            raise Problem(f"{self.package} is not installed in {self.venv}")
        return version

    def copy(self) -> None:
        if self.prev.exists():
            shutil.rmtree(self.prev)
        subprocess.run(["cp", "-a", str(self.venv), str(self.prev)], check=True)

    def install(self, requirements: bytes, workdir: Path) -> None:
        """pip, as the owner of the environment, with every hash required."""
        workdir.mkdir(parents=True, exist_ok=True)
        req = workdir / "requirements.txt"
        req.write_bytes(self.localize(requirements, workdir))
        owner = self.venv.stat().st_uid
        os.chown(workdir, owner, -1)
        os.chown(req, owner, -1)
        cmd = [str(self.venv / "bin" / "pip"), "install", "--quiet",
               "--disable-pip-version-check", "--require-hashes", "-r", str(req),
               *index_args(self.sources.index)]
        if self.socks_port is None:
            r = subprocess.run(cmd, capture_output=True, text=True, user=owner if owner else None)
        else:
            from .torconnect import TorConnectThread
            with TorConnectThread(self.socks_port) as port:
                r = subprocess.run([*cmd, "--proxy", f"http://127.0.0.1:{port}", "--timeout", "120",
                                    "--retries", "8"],
                                   capture_output=True, text=True, user=owner if owner else None,
                                   env={**os.environ, "NO_PROXY": "", "no_proxy": ""})
        if r.returncode != 0:
            raise Problem(f"pip failed: {r.stderr.strip()[-800:]}")

    def localize(self, requirements: bytes, workdir: Path) -> bytes:
        """A package named by its wheel on GitHub (one not on PyPI, the help bot) is
        fetched from the release sources in their order, checked against its hash, and
        given to pip as a local file; if none has it, the line stays as it was."""
        from . import release_sources as rs
        lines = requirements.decode("utf-8", "replace").splitlines(keepends=True)
        for n, line in enumerate(lines):
            m = re.match(r"^(?P<pkg>[A-Za-z0-9_.-]+) @ (?P<url>\S+)(?P<rest>.*?--hash=sha256:"
                         r"(?P<hash>[0-9a-f]{64}).*)$", line.rstrip("\n"))
            where = rs.GITHUB_FILE.match(m.group("url")) if m else None
            if not where:
                continue
            dest = workdir / where.group("name")
            for url in self.sources.file_urls(**where.groupdict()):
                try:
                    up.fetch(url, self.socks_port, dest)
                except up.UpdateError:
                    continue
                if hashlib.sha256(dest.read_bytes()).hexdigest() == m.group("hash"):
                    lines[n] = f"{m.group('pkg')} @ {dest.resolve().as_uri()}{m.group('rest')}\n"
                    break
        return "".join(lines).encode()

    def restore(self) -> None:
        bad = self.venv.with_name(self.venv.name + ".bad")
        if bad.exists():
            shutil.rmtree(bad)
        os.rename(self.venv, bad)
        os.rename(self.prev, self.venv)
        shutil.rmtree(bad, ignore_errors=True)

    def restart(self) -> None:
        if self.oneshot:           # its timer starts the new version next time
            return
        subprocess.run(["systemctl", "restart", self.service], capture_output=True)

    def imports(self) -> bool:
        """The installed package loads in its environment."""
        module = self.package.replace("-", "_")
        r = subprocess.run([str(self.venv / "bin" / "python"), "-c", f"import {module}"],
                           capture_output=True, text=True)
        return r.returncode == 0

    def _show(self) -> tuple[str, int]:
        r = subprocess.run(["systemctl", "show", "-p", "ActiveState", "-p", "NRestarts",
                            self.service], capture_output=True, text=True)
        f = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
        return f.get("ActiveState", ""), int(f.get("NRestarts", "0") or 0)

    def answers(self) -> bool:
        """``--check tcp:host:port``: it greets as an NNTP server does (``200``/``201``);
        ``--check http://host:port/path``: it answers that with 2xx or 3xx."""
        if not self.check:
            return True
        if self.check.startswith(("http://", "https://")):
            import ssl
            import urllib.error
            import urllib.request
            ctx = ssl.create_default_context()
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE   # its own, local
            try:
                with urllib.request.urlopen(self.check, timeout=10, context=ctx) as r:
                    return 200 <= r.status < 400
            except urllib.error.HTTPError as exc:
                return 300 <= exc.code < 400
            except (OSError, ValueError):
                return False
        host, _, port = self.check.removeprefix("tcp:").rpartition(":")
        try:
            with socket.create_connection((host, int(port)), timeout=10) as s:
                return s.recv(64).startswith((b"200", b"201"))
        except (OSError, ValueError):
            return False

    def healthy(self, within: float = HEALTHY_WITHIN, stay: float = STAY_UP,
                sleep: Callable[[float], None] = time.sleep) -> bool:
        """Up for ``stay`` seconds without a restart, and answering, within ``within``.
        A oneshot service is not running between its runs: there it must load."""
        if self.oneshot:
            return self.imports()
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
    if getattr(machine, "busy", lambda: False)():
        state.save()
        say(f"{rel.version} is due, but {have} is busy (it must not be restarted now); later")
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


def index_args(index: tuple[str, ...]) -> list[str]:
    """pip's index options for the release sources' indexes (#902): the first is the
    index, the others extra ones; an onion address over plain HTTP is a trusted host
    (Tor encrypts and authenticates it, and every file must match its hash anyway)."""
    from urllib.parse import urlsplit
    out: list[str] = []
    for i, url in enumerate(index):
        out += ["--index-url" if i == 0 else "--extra-index-url", url]
        host = urlsplit(url).hostname or ""
        if url.startswith("http://") and host.endswith(".onion"):
            out += ["--trusted-host", host]
    return out


DIRECT_ENV = "UNSEENET_UPDATE_DIRECT"
SYSTEM_TOR = 9050


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            return True
    except OSError:
        return False


def _with_tor(socks: int | None, direct: bool, work: Callable[[int | None], str]) -> str:
    """Run ``work`` with a SOCKS port: none when direct, the given or the system's Tor,
    else a Tor started for this run. Problem when there is no Tor."""
    if direct:
        return work(None)
    if socks is not None:
        if not _listening(socks):
            raise Problem(f"no Tor on 127.0.0.1:{socks} (--direct updates without Tor)")
        return work(socks)
    if _listening(SYSTEM_TOR):
        return work(SYSTEM_TOR)
    import asyncio
    import tempfile

    from .core.tor import TorError, TorProcess

    async def own() -> str:
        with tempfile.TemporaryDirectory(prefix="unseenet-service-update-tor-") as tmp:
            try:
                tor = TorProcess(Path(tmp), TorProcess.find_binary())
                await tor.start()
            except TorError as exc:
                raise Problem(f"could not start Tor: {exc} (--direct updates without Tor)") from exc
            try:
                return await asyncio.to_thread(work, tor.socks_port)
            finally:
                await tor.stop()
    return asyncio.run(own())


def direct_by_env() -> bool:
    return os.environ.get(DIRECT_ENV, "").strip().lower() in ("1", "yes", "true", "on")


def update_service(service: str, venv: Path, state: State, *, check: str | None = None,
                   package: str = CORE, repo: str | None = None, oneshot: bool = False,
                   busy: Path | None = None, socks: int | None = None, direct: bool = False,
                   node: str | None = None,
                   at_once: bool = False, say: Callable[[str], None] = print) -> str:
    """One run, over Tor unless ``direct`` (or the environment) says otherwise: what the
    update timers of nodes, replicas, registrars and the other services run."""
    def work(socks_port: int | None) -> str:
        from . import release_sources as rs
        machine = Machine(service, venv, check, package, oneshot, busy, socks_port)
        seen: list[list[str]] = []

        def network() -> list[str]:
            if not seen:
                seen.append(posts_in_network(package, socks_port, node))
            return seen[0]

        def find() -> Release:
            try:
                return newest_release(lambda u: up.fetch(u, socks_port), package=package,
                                      repo=repo, network=network, say=say,
                                      keys=state.data.setdefault("release_keys", {}))
            finally:     # the newest list of sources, kept for when the network is gone (#902)
                from . import release_keys as rk
                got = seen[0] if seen else []
                keys, _ = rk.newest(rk.votes_of(got),
                                    (state.data.get("release_keys") or {}).get("body"))
                machine.sources = rs.newest([b for b in got if isinstance(b, str)],
                                            state.data.get("sources"), keys)
                if machine.sources.updated:
                    state.data["sources"] = machine.sources.to_dict()
        return run(machine, state, find=find, say=say, at_once=at_once)
    return _with_tor(socks, direct or direct_by_env(), work)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="unseenet-service-update", description=__doc__.split("\n\n")[0])
    p.add_argument("action", choices=("run", "status", "on", "off"))
    p.add_argument("--service", required=True, help="the systemd service, e.g. unseenet-node")
    p.add_argument("--package", default=CORE,
                   help="the service's package, e.g. unseenet-gateway (default: unseenet)")
    p.add_argument("--repo", help="where its releases are (default: unseenet/<package>)")
    p.add_argument("--venv", default=sys.prefix, help="its virtual environment (default: this one)")
    p.add_argument("--check", help="where the service answers: tcp:host:port (NNTP; a node: "
                   "tcp:127.0.0.1:1119) or http://host:port/path")
    p.add_argument("--oneshot", action="store_true",
                   help="a service its own timer starts (the bots): not restarted; the new "
                        "version must load")
    p.add_argument("--busy", type=Path,
                   help="a file the service keeps fresh while it must not be restarted "
                        "(a key ripening): the update waits")
    p.add_argument("--direct", action="store_true",
                   help=f"download without Tor (also {DIRECT_ENV}=1); by default everything "
                        "goes over Tor")
    p.add_argument("--socks", type=int, help=f"Tor's SOCKS port on 127.0.0.1 (default: {SYSTEM_TOR} "
                   "if a Tor listens there, else one is started for the run)")
    p.add_argument("--node", help="read the releases in the network through this node "
                   f"(default: {LOCAL_NODE} if a node runs here, else the known nodes over Tor)")
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
    if not PACKAGE.fullmatch(a.package):
        print(f"not an Unseenet package: {a.package}")
        return 1
    if os.geteuid() != 0:
        print("Updating a service needs root (it restarts the service).")
        return 1
    try:
        what = update_service(a.service, Path(a.venv), state, check=a.check, package=a.package,
                              repo=a.repo, oneshot=a.oneshot, busy=a.busy, socks=a.socks,
                              direct=a.direct, node=a.node, at_once=a.now)
    except (Problem, up.UpdateError, OSError) as exc:
        print(f"could not look for updates: {exc}")
        return 1
    return 1 if what == "rolled-back" else 0


if __name__ == "__main__":
    sys.exit(main())

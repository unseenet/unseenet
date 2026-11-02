#!/usr/bin/env python3
"""Sign a stable release with the project key, so sticks will update to it.

    python tools/project/sign_release.py v0.6.1
    python tools/project/sign_release.py --repo unseenet-gateway v0.6.0
    python tools/project/sign_release.py --post v0.7.1      (a release signed before: post it)

Since 0.6 a release is built in two repositories, each with its own SHA256SUMS.txt
(#546): unseenet-portable (the zips for folders and USB sticks) and
unseenet-bootable (the image and its update zip; it can come days later, when
Alpine has the newest Tor). This signs each that has the release and no
signature yet - run it again when the other one is out. For each it downloads
SHA256SUMS.txt, checks that it names this version, asks for the owner vault's
passphrase (once), signs, uploads SHA256SUMS.txt.sig and posts both in
unseenet.releases. The project key never leaves this computer.

It also signs the core release, whose server requirements self-updating servers
take (unseenet.service_update, #827).

``--repo NAME`` signs one service's release instead (a gateway, an entrance, a
watchman, the bots, the help bot - each released with its own version): its
``<package>-<version>-server-requirements.txt``, which that service's servers take.

Server releases (the core's and each service's) are posted in unseenet.releases too
(#901): the checksums, the signature and the requirements, which servers read through
the network before they ask GitHub.

Sticks on the stable channel accept only this signature (unseenet.update).
Run it again after files were added to the release: the sums change, and
the old signature no longer fits.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

import _owner  # noqa: F401  (puts src/ on the path)
from _owner import open_owner_session, post_everywhere

from unseenet import update
from unseenet.core.article import new_article
from unseenet.known_nodes import RELEASES_GROUP

SERVER = "server-requirements"   # the core release's server requirements (#827)
REPOS = {"unseenet/unseenet-portable": "linux-x86_64",       # the zip that names the version
         "unseenet/unseenet-bootable": "x86_64-update",
         # the core: the servers' requirements, which self-updating servers take (#827)
         "unseenet/unseenet": SERVER}


def server_requirements(sums: dict[str, str], package: str = "unseenet") -> tuple[str, str]:
    """(file name, version) of a release's server requirements."""
    from unseenet.service_update import requirements_version
    for name in sums:
        if version := requirements_version(name, package):
            return name, version
    sys.exit(f"{update.SUMS} names no server requirements of {package}")


def gh(repo: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["gh", *args, "-R", repo], capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"gh {args[0]} {args[1]} -R {repo} failed: {r.stderr.strip()}")
    return r


def assets(repo: str, tag: str) -> list[str] | None:
    """The release's file names, or None when there is no such release (yet)."""
    r = gh(repo, "release", "view", tag, "--json", "assets", "--jq", ".assets[].name",
           check=False)
    return r.stdout.split() if r.returncode == 0 else None


def main() -> None:
    args = sys.argv[1:]
    post_signed = "--post" in args          # post a release that is signed already (#901)
    args = [a for a in args if a != "--post"]
    repos = REPOS
    package = "unseenet"
    if len(args) == 3 and args[0] == "--repo":
        package = args[1].rpartition("/")[2]
        if not package.startswith("unseenet-"):
            sys.exit(f"not an Unseenet service: {args[1]}")
        repos = {f"unseenet/{package}": SERVER}
        args = args[2:]
    if len(args) != 1 or not args[0].startswith("v"):
        sys.exit("\n".join(x.strip() for x in __doc__.strip().splitlines()[2:4]))
    tag = args[0]
    todo = []
    for repo, what in repos.items():
        names = assets(repo, tag)
        if names is None:
            print(f"{repo}: no {tag} release yet - run this again when it is out.")
        elif update.SUMS not in names:
            print(f"{repo}: {tag} has no {update.SUMS} yet - its build is still running?")
        elif update.SIG in names and not post_signed:
            print(f"{repo}: {tag} is signed already (--post posts it in unseenet.releases).")
        else:
            todo.append((repo, what, update.SIG in names))
    if not todo:
        return
    s = identity = None
    with tempfile.TemporaryDirectory(prefix="unseenet-sign-") as tmp:
        for repo, what, signed in todo:
            d = Path(tmp) / repo.split("/")[1]
            d.mkdir()
            gh(repo, "release", "download", tag, "-p", update.SUMS, "-D", str(d))
            sums = (d / update.SUMS).read_bytes()
            name, version = (server_requirements(update.parse_sums(sums), package)
                             if what == SERVER
                             else update.asset_in(update.parse_sums(sums), what))
            if version != tag[1:]:
                sys.exit(f"{repo}: {update.SUMS} lists {name}, not version {tag[1:]}")
            print(f"{repo} {tag}: {len(update.parse_sums(sums))} files, {name}")
            if s is None:
                s = open_owner_session()
                identity = s.identity()
            if signed:                             # --post: the signature it has
                gh(repo, "release", "download", tag, "-p", update.SIG, "-D", str(d))
                sig = (d / update.SIG).read_text()
            else:
                sig = update.signature_text(sums, identity)
            if what == SERVER:
                update.check_signature(sums, sig, "stable")     # as servers will check it
            else:
                update.check_release(sums, sig, "stable", what)  # as sticks will check it
            if not signed:
                (d / update.SIG).write_text(sig)
                gh(repo, "release", "upload", tag, str(d / update.SIG), "--clobber")
                print(f"Signed: {update.SIG} is on {repo} {tag}.")
            if what == SERVER:                     # servers read it in the network (#901)
                from unseenet import service_update as su
                gh(repo, "release", "download", tag, "-p", name, "-D", str(d))
                req = (d / name).read_bytes()
                subject, body = su.server_post(package, version, sums, sig, name, req)
                art = new_article(RELEASES_GROUP, subject, body, from_name="Unseenet project")
                art = art.finalize(identity, _owner.POW_BITS)
                if asyncio.run(post_everywhere([art], session=s)) == 0:
                    print("No node took the server release in unseenet.releases: run this again "
                          "later (servers fall back to GitHub meanwhile).")
                else:
                    print(f"Posted {package} {version} in unseenet.releases: servers take it from there.")
                continue
            # and tell the clients through the network (#264): the checksums and the
            # signature, posted by the project key itself in unseenet.releases
            subject, body = update.release_post(sums, sig, "stable")
            art = new_article(RELEASES_GROUP, subject, body, from_name="Unseenet project")
            art = art.finalize(identity, _owner.POW_BITS)
            if asyncio.run(post_everywhere([art], session=s)) == 0:
                print("No node took the post in unseenet.releases: run this again later.")
            else:
                print("Posted in unseenet.releases: clients will offer the update.")

if __name__ == "__main__":
    main()

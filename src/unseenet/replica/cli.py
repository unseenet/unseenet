"""``unseenet-replica``: set up, run and look after a replica of a council registrar.

Made for people who can follow a guide but would rather not read the RFCs: one command
sets everything up, one tells in plain words how the replica is doing.

    sudo unseenet-replica setup --group unseenet.names@...   key, vault, service, updates
    unseenet-replica status                                   how it is doing, in words
    sudo unseenet-replica agree removal:ed25519:...           agree to a held change
    sudo unseenet-replica hold admission,removal              what to agree to first
    sudo unseenet-replica resign                              step down (UN-RFC 0054, 20)
    sudo unseenet-replica propose --set min_level=3 --reason ...   a proposal (UN-RFC 0061)
    sudo unseenet-replica second ID                           post the same proposal too
    sudo unseenet-replica talk "subject" "text"               say something as the member
    sudo unseenet-replica object ID "reason"                  object to a proposal
    unseenet-replica run --dir DIR                            what the service runs
    sudo unseenet-replica update                              what the update timer runs

Everything lives in one folder (``--dir``, by default ``/var/lib/unseenet-replica``):
the vault with the replica's key, ``config.json`` (the operator's choices) and
``status.json`` (written after every round; no secrets) and ``outbox/``, where the
operator's posts wait for the service to post them with the member key. The vault's
passphrase is
made at random and kept in ``/etc/unseenet-replica/passphrase``, readable by root
only; systemd hands it to the service. ``agree``, ``hold`` and ``resign`` only write
``config.json``: the running service reads it at its next round, so the vault never
has to be opened twice.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from .. import names as nm

DEFAULT_DIR = Path("/var/lib/unseenet-replica")
ETC = Path("/etc/unseenet-replica")
USER = "unseenet-replica"
UNITS = Path("/etc/systemd/system")
SERVICE = "unseenet-replica"
CHANNELS = {"stable": "unseenet", "main": "git+https://github.com/unseenet/unseenet@main"}
STALE_MINUTES = 30


# --- the folder ------------------------------------------------------------------------

def config_path(d: Path) -> Path:
    return d / "config.json"


def read_config(d: Path) -> dict:
    try:
        return json.loads(config_path(d).read_text())
    except (OSError, ValueError):
        return {}


def write_config(d: Path, cfg: dict) -> None:
    p = config_path(d)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=1, sort_keys=True) + "\n")
    os.chmod(tmp, 0o644)
    tmp.replace(p)


def read_status(d: Path) -> dict:
    try:
        return json.loads((d / "status.json").read_text())
    except (OSError, ValueError):
        return {}


# --- status in plain words -------------------------------------------------------------------

def _ago(text: str | None, now: datetime) -> str:
    if not text:
        return "never"
    minutes = int((now - nm.parse_rfc3339(text)).total_seconds() // 60)
    if minutes < 2:
        return "just now"
    if minutes < 120:
        return f"{minutes} minutes ago"
    return f"{minutes // 60} hours ago"


def _date(text: str | None) -> str:
    if not text:
        return "?"
    d = nm.parse_rfc3339(text)
    return f"{d.day} {d:%B %Y}"                    # %-d is not on Windows


def explain(st: dict, cfg: dict, now: datetime | None = None) -> list[str]:
    """The status of a replica as a few sentences for its operator."""
    now = now or datetime.now(timezone.utc)
    if not st:
        return ["The replica has not finished a round yet. If it was just set up, give it",
                "a few minutes (it starts Tor first). Otherwise look at its log:",
                f"  journalctl -u {SERVICE} -n 50"]
    out = []
    role = st.get("role", "?")
    group = st.get("group", cfg.get("group", "?"))
    out.append(f"This replica works for the council registrar {group}.")
    out.append(f"Its key: {st.get('key', '?')}")
    twin = st.get("twin")
    if twin:
        out.append("STOPPED: something else posts with this replica's key - most likely a copy")
        out.append("of this replica running on another machine. Two replicas with one key can")
        out.append("split the council, so this one signs nothing until you act.")
        out.append(f"  The article it did not send: {twin['subject']!r} on {_date(twin['date'])}")
        out.append("  Stop the other copy, or set this replica up again with a new key")
        out.append("  (sudo unseenet-replica setup ... in an empty folder). When the other is gone:")
        out.append(f"  sudo unseenet-replica twin-gone {twin['message_id']}")
    if role == "waiting":
        out.append("The council does not exist yet: its first manifest is not signed by every")
        out.append("founding member. The replica checks again every few minutes.")
    elif role == "shadow":
        out.append("It runs as a SHADOW: it decides every name claim like the council, issues")
        out.append("nothing, and posts what it decided once a day. After 60 days of agreeing,")
        out.append("the members' replicas let it in by themselves.")
        out.append(f"Reports in the last 60 settled days: {st.get('reports_60', 0)} "
                   f"(55 are needed).")
    elif role == "member on probation":
        out.append("It is a MEMBER ON PROBATION: it signs certificates, but does not yet count")
        out.append(f"when the council changes. It becomes a full member on {_date(st.get('full_from'))}.")
    elif role == "full member":
        out.append("It is a FULL MEMBER: it signs certificates and, with the others, every")
        out.append("change of the council.")
    level, want = st.get("level"), st.get("min_level")
    if want is not None and (level is None or level < want):
        out.append(f"Its key is ripening: level {level if level is not None else 'none yet'} "
                   f"of the {want} the council asks for. This takes weeks and runs by itself.")
    if st.get("founding", {}).get("lasts"):
        out.append(f"The council is in its founding period until {_date(st['founding']['until'])}.")
    out.append(f"The council has {st.get('members', '?')} members, {st.get('full', '?')} of them full.")
    nc = st.get("next_change")
    if nc:
        out.append(f"Next change the replicas compute: {nc['kind']} of {nc.get('key') or '-'} "
                   f"({nc['why']}).")
    for label, h in (st.get("held") or {}).items():
        out.append(f"HELD, waiting for you: {h['kind']} of {h.get('key')} - {h['why']}.")
        out.append(f"  To let it go ahead:  sudo unseenet-replica agree {label}")
    for o in st.get("objections") or []:
        if o.get("by_full_member"):
            out.append(f"A full member objects to {o['about']}: {o['why'][:200]}")
    for h in st.get("hearings") or []:
        if h["state"] in ("open", "extended"):
            out.append(f"Hearing {h['id']} ({h['kind']}{', urgent' if h.get('urgent') else ''}): "
                       f"{h['objections']} objection(s), {h['active']} active members; "
                       f"closes {_date(h['closes'])}. Reason: {h['reason'][:120]}")
    for pid, p in (st.get("proposals_pending") or {}).items():
        mine = st.get("key") in p.get("by", [])
        out.append(f"Proposal {pid} waits for more members to post it ({len(p.get('by', []))} "
                   f"so far{', you did' if mine else ''}). To join:  "
                   f"sudo unseenet-replica second {pid}")
    if cfg.get("hold"):
        out.append(f"You hold: {', '.join(cfg['hold'])} (they wait for you to agree).")
    if cfg.get("resign"):
        out.append("You asked to step down; the replica posts it at its next round.")
    if st.get("error"):
        out.append(f"The last round failed: {st['error']}")
    out.append(f"Last round: {_ago(st.get('time'), now)}. Software: {st.get('software', '?')}.")
    if st.get("time") and (now - nm.parse_rfc3339(st["time"])).total_seconds() > STALE_MINUTES * 60:
        out.append(f"That is long ago - is it running?  systemctl status {SERVICE}")
    return out


# --- setting up ------------------------------------------------------------------------------------

SERVICE_UNIT = """[Unit]
Description=Unseenet replica of a council registrar (UN-RFC 0054)
After=network-online.target
Wants=network-online.target

[Service]
User={user}
WorkingDirectory={dir}
# the vault's passphrase, readable only by root: systemd hands it to the service
LoadCredential=passphrase:{etc}/passphrase
ExecStart={bin} run --dir {dir} --passphrase-file ${{CREDENTIALS_DIRECTORY}}/passphrase
Restart=always
RestartSec=60
Nice=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={dir}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
"""

UPDATE_UNIT = """[Unit]
Description=Update the Unseenet replica

[Service]
Type=oneshot
ExecStart={bin} update --dir {dir}
"""

UPDATE_TIMER = """[Unit]
Description=Update the Unseenet replica once a day

[Timer]
OnCalendar=daily
RandomizedDelaySec=12h
Persistent=true

[Install]
WantedBy=timers.target
"""


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def setup(args) -> int:
    """Make the key and vault, write the config, and install and start the service and
    the daily update. Root, so that the vault's passphrase can be kept from the service
    user and systemd can be told; ``--no-systemd`` for a try-out as an ordinary user."""
    from ..client.session import Session
    from ..core.vault import Vault
    d = Path(args.dir)
    systemd = not args.no_systemd
    if systemd and os.geteuid() != 0:
        print("Setting up the service needs root: run it with sudo (or add --no-systemd).")
        return 1
    if (d / "replica.vault").exists():
        print(f"There is a replica in {d} already. Its status: unseenet-replica status --dir {d}")
        return 1
    if systemd and not shutil.which("systemctl"):
        print("This machine has no systemd. Use --no-systemd and start "
              "'unseenet-replica run' another way.")
        return 1
    if not shutil.which("tor"):
        print("Tor is not installed. On Debian, Ubuntu or Raspberry Pi OS: sudo apt install tor")
        return 1
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    passphrase = secrets.token_urlsafe(32)
    if systemd:
        ETC.mkdir(parents=True, exist_ok=True)
        os.chmod(ETC, 0o700)
        pw_file = ETC / "passphrase"
    else:
        pw_file = d / "passphrase"
    pw_file.write_text(passphrase + "\n")
    os.chmod(pw_file, 0o600)

    print("Making the replica's key and its vault (this takes a moment)...")
    s = Session(Vault.open(d / "replica.vault", passphrase), status=lambda *_: None)
    if args.seed_file:
        from ..core import crypto
        seed = bytes.fromhex(Path(args.seed_file).read_text().strip())
        ident = crypto.Identity.from_seed(seed)
        s.data["identities"]["replica"] = {"seed": ident.seed.hex(), "display": "Unseenet registrar"}
        s.data["default_identity"] = "replica"
    else:
        s.new_identity("replica", "Unseenet registrar")
    key = s.identity().key_text
    s.save()
    s.vault.close()                       # free the vault's lock for the service

    cfg = {"group": args.group, "hold": sorted(_kinds(args.hold)) if args.hold else [],
           "agreed": [], "nodes": args.node or [], "channel": args.channel,
           "interval": args.interval}
    write_config(d, cfg)

    if systemd:
        if _run(["id", USER], check=False).returncode != 0:
            _run(["useradd", "--system", "--home-dir", str(d), "--shell", "/usr/sbin/nologin", USER])
        _run(["chown", "-R", f"{USER}:{USER}", str(d)])
        binary = shutil.which("unseenet-replica") or str(Path(sys.executable).with_name("unseenet-replica"))
        (UNITS / f"{SERVICE}.service").write_text(
            SERVICE_UNIT.format(user=USER, dir=d, etc=ETC, bin=binary))
        (UNITS / f"{SERVICE}-update.service").write_text(UPDATE_UNIT.format(bin=binary, dir=d))
        (UNITS / f"{SERVICE}-update.timer").write_text(UPDATE_TIMER)
        _run(["systemctl", "daemon-reload"])
        _run(["systemctl", "enable", "--now", f"{SERVICE}.service"])
        if args.channel != "off":
            _run(["systemctl", "enable", "--now", f"{SERVICE}-update.timer"])

    print()
    print("Done. Your replica's key is:")
    print(f"  {key}")
    print()
    print("What happens now, by itself:")
    print("  1. The replica starts Tor and begins as a SHADOW: it decides every name")
    print("     claim the way the council does, and once a day posts what it decided.")
    print("  2. Its key ripens in the background (weeks on a small machine) - the council")
    print("     asks for a ripened key so that new members cannot be made in bulk.")
    print("  3. When it has agreed with the council for 60 days and the key is ripe, the")
    print("     members' replicas admit it. 180 days later it is a full member.")
    if args.channel != "off":
        print(f"  4. Once a day it updates itself ({args.channel} channel) and restarts if needed.")
    print()
    print("See how it is doing at any time:  unseenet-replica status")
    if not systemd:
        print(f"Start it:  unseenet-replica run --dir {d} --passphrase-file {pw_file}")
    print("Nobody learns who runs this replica: it reaches the network over Tor, like any")
    print("client. Keep the folder and the passphrase file safe; they are the replica.")
    return 0


def _kinds(text: str) -> set[str]:
    from .run import HOLDABLE
    kinds = {k.strip() for k in text.split(",") if k.strip()}
    if "all" in kinds:
        return set(HOLDABLE)
    bad = kinds - set(HOLDABLE)
    if bad:
        raise SystemExit(f"Can hold only: {', '.join(HOLDABLE)} (or all), not {', '.join(sorted(bad))}")
    return kinds


# --- running -----------------------------------------------------------------------------------------

def run_service(args) -> int:
    import asyncio

    from ..client.session import Session
    from ..core.vault import Vault, VaultError
    from . import run as rr
    d = Path(args.dir)
    cfg = read_config(d)
    pw = (os.environ.get("UNSEENET_REPLICA_PASSPHRASE")
          or (Path(args.passphrase_file).read_text().strip() if args.passphrase_file else None))
    if not pw:
        import getpass
        pw = getpass.getpass("Vault passphrase: ")
    try:
        session = Session(Vault.open(d / "replica.vault", pw), status=lambda m: rr.log.info("%s", m))
    except VaultError as exc:
        print(exc)
        return 1
    session.service = True
    for node in cfg.get("nodes") or [n.address for n in session.known_nodes()]:
        session.add_node(node)
    group = args.group or cfg.get("group") or nm.NAMES_GROUP
    rr.log.info("replica %s for %s", session.identity().key_text, group)
    try:
        asyncio.run(rr.run(session, group=group, interval=args.interval or cfg.get("interval", 300),
                           once=args.once, state_dir=d, config=lambda: read_config(d)))
    except KeyboardInterrupt:
        pass
    finally:
        session.save()
    return 0


# --- the operator's choices ---------------------------------------------------------------------------

def agree(args) -> int:
    d = Path(args.dir)
    cfg = read_config(d)
    held = read_status(d).get("held") or {}
    if args.label not in held and not args.force:
        print("No such change is held now. Held changes are listed by: unseenet-replica status")
        return 1
    cfg["agreed"] = sorted(set(cfg.get("agreed", [])) | {args.label})
    write_config(d, cfg)
    print("Agreed. The replica posts it at its next round (within a few minutes).")
    return 0


def twin_gone(args) -> int:
    """The operator stopped the other user of the key: the replica may sign again."""
    d = Path(args.dir)
    twin = read_status(d).get("twin")
    if not twin or (args.message_id and args.message_id != twin["message_id"]):
        print("The replica is not stopped for another user of its key.")
        return 1
    cfg = read_config(d)
    cfg["twin_gone"] = (cfg.get("twin_gone", []) + [twin["message_id"]])[-20:]
    write_config(d, cfg)
    print("Noted. The replica signs again from its next round. If it stops again, the")
    print("other copy is still running.")
    return 0


def hold(args) -> int:
    d = Path(args.dir)
    cfg = read_config(d)
    cfg["hold"] = [] if args.kinds in ("none", "") else sorted(_kinds(args.kinds))
    write_config(d, cfg)
    print("The replica now holds: " + (", ".join(cfg["hold"]) or "nothing") +
          ". Held changes wait until you agree (unseenet-replica status lists them).")
    return 0


def resign(args) -> int:
    d = Path(args.dir)
    st = read_status(d)
    if st.get("role") not in ("full member", "member on probation"):
        print("This replica is not a member of the council, so there is nothing to step down from.")
        return 1
    if not args.yes:
        print("Stepping down posts a signed 'resign' in the council's group. The other members'")
        print("replicas then remove this key from the council. It cannot be undone: to come")
        print("back, a new key starts again as a shadow.")
        if not sys.stdin.isatty() or input("Step down? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Not done.")
            return 1
    cfg = read_config(d)
    cfg["resign"] = True
    write_config(d, cfg)
    print("The replica posts it at its next round. You can then stop the service:")
    print(f"  sudo systemctl disable --now {SERVICE} {SERVICE}-update.timer")
    return 0


# --- speaking with the member key (UN-RFC 0061) -------------------------------------------------

def _queue(d: Path, item: dict) -> Path:
    """Put a post in the outbox; the service posts it at its next round."""
    box = d / "outbox"
    box.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = box / f"{stamp}.json"
    path.write_text(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    if getattr(os, "geteuid", lambda: -1)() == 0 and _has_user():
        for p in (box, path):                   # the service deletes what it posted
            shutil.chown(p, USER, USER)
    return path


def _has_user() -> bool:
    try:
        import pwd
        pwd.getpwnam(USER)
        return True
    except (ImportError, KeyError):
        return False


def _groups(d: Path) -> tuple[dict, dict]:
    st = read_status(d)
    if not st.get("groups", {}).get("proposals"):
        raise SystemExit("This council has no proposals group, or the replica has not "
                         "finished a round yet (unseenet-replica status).")
    return st, st["groups"]


def _parse_value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def propose(args) -> int:
    from ..core import proposals as pr
    d = Path(args.dir)
    st, groups = _groups(d)
    if args.change_file:
        change = json.loads(Path(args.change_file).read_text())
    else:
        fields, council = {}, {}
        for item in args.set or []:
            k, _, v = item.partition("=")
            (council if k in (*pr.COUNCIL_PARAMS, "until") else fields)[k] = _parse_value(v)
        if args.extend_founding:
            council["until"] = args.extend_founding + "T00:00:00Z"
        m = {}
        if fields:
            m["fields"] = fields
        if council:
            m["council"] = council
        change = {"manifest": m}
    try:
        pid, body = pr.make_proposal(st["group"], st["seq"], change, args.reason,
                                     days=args.days, urgent=args.urgent)
    except pr.ProposalProblem as exc:
        raise SystemExit(f"Not a proposal: {exc}")
    print(f"Proposal {pid}:")
    print(f"  change  {json.dumps(change, sort_keys=True)}")
    print(f"  reason  {args.reason}")
    print("It counts when a majority of the active members have posted exactly this, within")
    print("7 days; then it stands in public for its hearing, and anybody with a ripened key")
    print(f"may object. The others join with:  sudo unseenet-replica second {pid}")
    _queue(d, {"group": groups["proposals"], "subject": f"{pr.PROPOSAL} {pid}", "body": body,
               "content_type": "application/json"})
    print("Queued: the replica posts it at its next round.")
    return 0


def second(args) -> int:
    from ..core import proposals as pr
    d = Path(args.dir)
    st, groups = _groups(d)
    p = (st.get("proposals_pending") or {}).get(args.id)
    if p is None:
        raise SystemExit("No such proposal is waiting. See: unseenet-replica status")
    shown = pr.parse_proposal(p["body"])
    print(f"Proposal {args.id}: {json.dumps(shown.change, sort_keys=True)}")
    print(f"Reason: {shown.reason}")
    if not args.yes and (not sys.stdin.isatty() or
                         input("Post it as this member? [y/N] ").strip().lower() not in ("y", "yes")):
        print("Not done.")
        return 1
    _queue(d, {"group": groups["proposals"], "subject": f"{pr.PROPOSAL} {args.id}",
               "body": p["body"], "content_type": "application/json"})
    print("Queued: the replica posts it at its next round.")
    return 0


def talk(args) -> int:
    d = Path(args.dir)
    _, groups = _groups(d)
    if not groups.get("talk"):
        raise SystemExit("This council has no talk group.")
    _queue(d, {"group": groups["talk"], "subject": args.subject, "body": args.text + "\n"})
    print("Queued: the replica posts it at its next round. It also keeps this member active "
          "(UN-RFC 0061 section 2).")
    return 0


def object_(args) -> int:
    from ..core import proposals as pr
    d = Path(args.dir)
    _, groups = _groups(d)
    body = pr.objection_body(args.id, args.reason or "", withdrawn=args.withdraw)
    _queue(d, {"group": groups["proposals"], "subject": f"{pr.OBJECTION} {args.id}",
               "body": body, "content_type": "application/json"})
    print("Queued. Objections are public: anybody can see which key objected, and why.")
    return 0


def update(args) -> int:
    """Upgrade the package from the configured channel and restart the service if the
    version changed. Run by the daily timer."""
    cfg = read_config(Path(args.dir))
    channel = cfg.get("channel", "stable")
    if channel == "off":
        return 0
    pip = Path(sys.executable).with_name("pip")
    before = __version__
    r = _run([str(pip), "install", "--quiet", "--upgrade", CHANNELS.get(channel, CHANNELS["stable"])],
             check=False)
    if r.returncode != 0:
        print(f"update failed: {r.stderr.strip()[-500:]}")
        return 1
    after = _run([sys.executable, "-c", "import unseenet; print(unseenet.__version__)"],
                 check=False).stdout.strip()
    if after and after != before:
        print(f"updated {before} -> {after}; restarting")
        _run(["systemctl", "restart", SERVICE], check=False)
    else:
        print(f"up to date ({before})")
    return 0


def status(args) -> int:
    d = Path(args.dir)
    st, cfg = read_status(d), read_config(d)
    if args.json:
        print(json.dumps({"status": st, "config": cfg}, indent=1, sort_keys=True))
    else:
        if not cfg and not st:
            print(f"There is no replica in {d}. Set one up with: sudo unseenet-replica setup")
            return 1
        print("\n".join(explain(st, cfg)))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="unseenet-replica", description=(
        "A replica of a council registrar (UN-RFC 0054): it starts as a shadow, and "
        "the council's own replicas let it in once it has decided like them for 60 days."))
    p.add_argument("--dir", default=os.environ.get("UNSEENET_REPLICA_DIR", str(DEFAULT_DIR)),
                   help=f"the replica's folder (default {DEFAULT_DIR})")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="make the key and vault, and install the service")
    s.add_argument("--group", default=nm.NAMES_GROUP, help="the council registrar's group")
    s.add_argument("--node", action="append", default=[],
                   help="a node to use (repeat; default: the known nodes)")
    s.add_argument("--hold", default="", help="changes to agree to first: admission, "
                                              "promotion, removal, proposal, or all")
    s.add_argument("--channel", choices=("stable", "main", "off"), default="stable",
                   help="where updates come from (default: stable releases)")
    s.add_argument("--interval", type=int, default=300, help="seconds between rounds")
    s.add_argument("--seed-file", help="use this key (a file with its 64 hex seed) instead of a new one")
    s.add_argument("--no-systemd", action="store_true", help="no service: start it yourself")
    s = sub.add_parser("run", help="run the replica (what the service does)")
    s.add_argument("--group", default=None)
    s.add_argument("--passphrase-file")
    s.add_argument("--interval", type=int, default=None)
    s.add_argument("--once", action="store_true")
    s = sub.add_parser("status", help="how the replica is doing, in plain words")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("agree", help="let a held change go ahead")
    s.add_argument("label", help="as status shows it, e.g. removal:ed25519:...")
    s.add_argument("--force", action="store_true", help="also if it is not held now")
    s = sub.add_parser("twin-gone", help="the other user of this replica's key is stopped")
    s.add_argument("message_id", nargs="?", default=None)
    s = sub.add_parser("hold", help="which changes wait for you: admission,promotion,removal,"
                                    "proposal, all or none")
    s.add_argument("kinds")
    s = sub.add_parser("resign", help="step down from the council (UN-RFC 0054 section 20)")
    s.add_argument("--yes", action="store_true")
    sub.add_parser("update", help="update the software (what the daily timer runs)")
    s = sub.add_parser("propose", help="as a member: propose a change (UN-RFC 0061)")
    s.add_argument("--set", action="append", metavar="FIELD=VALUE",
                   help="a manifest field (title, posters, ...) or min_level, max_probation, "
                        "sponsors; repeat")
    s.add_argument("--extend-founding", metavar="YYYY-MM-DD",
                   help="extend the founding period to this day (once it is over)")
    s.add_argument("--change-file", help="the change as JSON, for list, endorse, retire or rfc")
    s.add_argument("--reason", required=True, help="why - everybody sees it")
    s.add_argument("--days", type=int, default=None, help="the hearing, 14 to 60 days")
    s.add_argument("--urgent", action="store_true", help="a 3-day hearing; needs two thirds")
    s = sub.add_parser("second", help="as a member: post a waiting proposal too")
    s.add_argument("id")
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("talk", help="as a member: post in the council's talk group")
    s.add_argument("subject")
    s.add_argument("text")
    s = sub.add_parser("object", help="as a member: object to a proposal")
    s.add_argument("id")
    s.add_argument("reason", nargs="?", default="")
    s.add_argument("--withdraw", action="store_true", help="take an objection back")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return {"setup": setup, "run": run_service, "status": status, "agree": agree,
            "hold": hold, "resign": resign, "update": update, "propose": propose,
            "second": second, "talk": talk, "object": object_,
            "twin-gone": twin_gone}[args.cmd](args)


def entry() -> None:
    sys.exit(main())

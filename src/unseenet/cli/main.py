"""`unseenet`: the command line - its parser, and which function each command runs.

A new command: its function in the file of its area (``c_<name>``), its parser in
``client_main``, and an entry in ``COMMANDS``.

Part of ``unseenet.cli`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names, as when this was one file
from .. import cli as _c   # names tests patch on the module, read at call time
from .node import *  # noqa: F403
from .basics import *  # noqa: F403
from .groups import *  # noqa: F403
from .messages import *  # noqa: F403
from .network import *  # noqa: F403
from .services import *  # noqa: F403


COMMANDS = {
    "id-new": c_id_new, "whoami": c_whoami, "node-add": c_node_add, "groups": c_groups,
    "group-create": c_group_create, "group-remove": c_group_remove, "invite": c_invite,
    "withdraw": c_withdraw, "group-edit": c_group_edit, "group-show": c_group_show,
    "post": c_post, "read": c_read,
    "bridges": c_bridges, "tor": c_tor, "gateways": c_gateways,
}


def client_main(argv=None) -> None:
    """The ``unseenet`` command line: parse the arguments and run the command (an
    entry point in ``pyproject.toml``)."""
    p = argparse.ArgumentParser(prog="unseenet", description="Unseenet client.")
    from ..portable import default_vault_path
    p.add_argument("--vault", default=str(default_vault_path()), help="encrypted vault file")
    p.add_argument("--identity", "-i", help="identity to use (default: first)")
    p.add_argument("--version", action="version", version=f"unseenet {__version__}")
    p.add_argument("--json", action="store_true", help="answer in JSON, for scripts")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("id-new", help="create a new identity")
    s.add_argument("name")
    s.add_argument("--display", help="display name shown in From")
    sub.add_parser("whoami", help="list identities")
    s = sub.add_parser("node-add", help="add a node address (xyz.onion or host:port)")
    s.add_argument("address")
    s = sub.add_parser("groups", help="list groups on the node")
    s.add_argument("pattern", nargs="?", default="*")
    s.add_argument("--mine", action="store_true", help="only groups owned by an identity in this vault")
    s = sub.add_parser("group-create", help="create a group you own")
    s.add_argument("name")
    s.add_argument("--type", choices=["open", "moderated", "channel", "closed", "inbox"], default="open")
    s.add_argument("--local", action="store_true", help="never replicated to other nodes (UN-RFC 0009)")
    s.add_argument("--moderator", action="append", metavar="KEY", help="a moderator's key (repeat)")
    s.add_argument("--poster", action="append", metavar="KEY", help="channels: a poster's key (repeat)")
    _group_options(s, create=True)
    s = sub.add_parser("group-edit", help="change a group you own: roles, bans and settings")
    s.add_argument("group", help="full group ID, name@fingerprint")
    s.add_argument("--add-poster", action="append", metavar="KEY")
    s.add_argument("--remove-poster", action="append", metavar="KEY")
    s.add_argument("--add-moderator", action="append", metavar="KEY")
    s.add_argument("--remove-moderator", action="append", metavar="KEY")
    s.add_argument("--ban", action="append", metavar="KEY", help="ban a key from posting (UN-RFC 0004 5.1)")
    s.add_argument("--unban", action="append", metavar="KEY")
    s.add_argument("--reason", help="with --ban: shown to the banned and to readers")
    _group_options(s, create=False)
    s = sub.add_parser("group-show", help="show a group's current manifest")
    s.add_argument("group", help="full group ID, name@fingerprint")
    s = sub.add_parser("group-remove", help="remove groups you own from the whole network (final)")
    s.add_argument("group", nargs="+", help="full group ID, name@fingerprint")
    s.add_argument("--reason", help="short reason, shown to nodes and readers")
    s.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")
    s = sub.add_parser("withdraw", help="withdraw posts: your own, or any in a group you own or moderate")
    s.add_argument("group", help="full group ID, name@fingerprint")
    s.add_argument("message_id", nargs="*", help="Message-IDs")
    s.add_argument("--all", action="store_true", help="every post in a group you own or moderate")
    s.add_argument("--keep", action="append", metavar="MSGID", help="with --all: leave this one")
    s.add_argument("--reason", help="shown to readers (not in closed groups)")
    s.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")
    s = sub.add_parser("invite", help="give a key access to a closed group you own")
    s.add_argument("group")
    s.add_argument("key", help="the member's ed25519:... key")
    s = sub.add_parser("post", help="post to a group (body from --body or stdin)")
    s.add_argument("group")
    s.add_argument("--subject", "-s", help="the subject (a reply: Re: and the parent's by default)")
    s.add_argument("--body", help="the text; without it, read from stdin")
    s.add_argument("--kind", choices=["post", "chat"], default="post",
                   help="a post with a subject, or a chat line (UN-RFC 0028)")
    s.add_argument("--reply-to", metavar="MSGID", help="reply to (or comment on) this post")
    s.add_argument("--edit", metavar="MSGID",
                   help="a new version of your own post (UN-RFC 0042); the body replaces it")
    s.add_argument("--format", choices=["markdown", "plain"],
                   help="the text's format (default: your setting, Markdown unless changed)")
    s.add_argument("--attach", action="append", metavar="FILE",
                   help="a file to post with it, up to 4 (UN-RFC 0027); pictures are saved "
                        "again without their metadata (GPS, time, camera)")
    s.add_argument("--publish-outside-tor", action="store_true",
                   help="post even though the group has portals to other networks")
    s = sub.add_parser("read", help="read a group")
    s.add_argument("group")
    s = sub.add_parser("gateways", help="list gateways to other networks (to invite one)")
    s.add_argument("--network", help="only this network, e.g. matrix")
    s.add_argument("--directory", help="another directory group")
    s = sub.add_parser("bridges", help="show or set Tor bridges, for networks that block Tor")
    s.add_argument("mode", nargs="?", choices=["off", "obfs4", "snowflake", "custom"])
    s.add_argument("--line", action="append", help="a bridge line (custom; repeat for more)")
    s = sub.add_parser("tor", help="show or set which Tor to use: our own or one already running")
    s.add_argument("use", nargs="?", metavar="auto|own|HOST:PORT",
                   help="auto: Tails' Tor on Tails, else our own; own: always our own; "
                        "HOST:PORT: the SOCKS port of a running Tor, e.g. 127.0.0.1:9050")

    s = sub.add_parser("ripen", help="ripen a key so it can post, e.g. a gateway's or a bot's "
                                     "(UN-RFC 0025)")
    s.add_argument("--to", type=int, default=0, choices=range(5),
                   help="the level to reach (default 0: enough to post; 3: no surcharge)")
    s.add_argument("--key-file", help="a file with the key's seed in hex, instead of the vault")
    s.add_argument("--public-key", help="ripen from the public key alone (ed25519:...), on any "
                                       "machine; publish later with --key-file")
    s.add_argument("--state", help="where the chain is kept for --key-file (default: next to it)")
    s.add_argument("--node", action="append", help="a node to publish to (with --publish)")
    s.add_argument("--publish", action="store_true", help="post the ripe@ manifest when done")

    s = sub.add_parser("serve", help="offer the local client API (UN-RFC 0046) to a front end "
                                     "or a program on this computer")
    s.add_argument("--key-file", help="run as a service with this key (a bot, a gateway): "
                                      "no vault, no unlock")
    s.add_argument("--state", help="where a service keeps its state (default: next to the key)")
    s.add_argument("--node", action="append", help="a node to use (a service needs one)")
    s.add_argument("--port", type=int, default=0, help="the port on 127.0.0.1 (default: random)")
    s.add_argument("--api-file", help="also write the address and token to this file (mode "
                                      "0600); default for a vault: <vault>.api")

    args = p.parse_args(argv)
    if args.cmd == "ripen":
        asyncio.run(ripen_command(args))
        return
    if args.cmd == "serve":
        asyncio.run(serve_command(args))
        return
    asyncio.run(_c.client_command(args))


__all__ = ['COMMANDS', 'client_main']

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
from .kept import *  # noqa: F403
from .following import *  # noqa: F403
from .names import *  # noqa: F403
from .reports import *  # noqa: F403
from .teams import *  # noqa: F403


COMMANDS = {
    "id-new": c_id_new, "id-import": c_id_import, "whoami": c_whoami, "passphrase": c_passphrase,
    "id-words": c_id_words, "id-restore": c_id_restore, "copy-to": c_copy_to, "copy-from": c_copy_from, "node-add": c_node_add, "groups": c_groups,
    "group-create": c_group_create, "group-remove": c_group_remove, "invite": c_invite,
    "withdraw": c_withdraw, "group-edit": c_group_edit, "group-show": c_group_show,
    "post": c_post, "read": c_read,
    "bridges": c_bridges, "tor": c_tor, "gateways": c_gateways,
    "pin": c_pin, "pins": c_pins, "react": c_react, "page-put": c_page_put, "export": c_export, "site-publish": c_site_publish, "page-remove": c_page_remove,
    "pages": c_pages, "feed-start": c_feed_start, "site-start": c_site_start,
    "profile": c_profile, "follow": c_follow, "unfollow": c_unfollow, "following": c_following,
    "timeline": c_timeline, "rules": c_rules, "thread": c_thread, "address": c_address, "open": c_open,
    "names": c_names, "name-claim": c_name_claim, "name-give": c_name_give,
    "name-revoke": c_name_revoke, "name-primary": c_name_primary, "name-requests": c_name_requests,
    "reports": c_reports, "team": c_team,
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
    s = sub.add_parser("id-import", help="add an identity from its seed (64 hex characters on stdin)")
    s.add_argument("name")
    s.add_argument("--display", help="display name shown in From")
    sub.add_parser("whoami", help="list identities")
    s = sub.add_parser("id-words", help="show an identity's 24 recovery words, to write down",
                       description="Show an identity's 24 Unseenet recovery words (UN-RFC 0050). "
                                   "Whoever has them IS the identity. They are printed only, "
                                   "never saved. Closed groups do not come back with them.")
    s.add_argument("name", nargs="?", help="the identity (default: the default one)")
    s.add_argument("--written", action="store_true", help="note that they are written down")
    s.add_argument("--yes", action="store_true",
                   help="do not ask for the passphrase again (scripts and tests)")
    s = sub.add_parser("id-restore", help="bring an identity back from its recovery words (stdin)",
                       description="Read 24 recovery words from stdin, put the identity in the "
                                   "vault, and read its state from the network (UN-RFC 0050).")
    s.add_argument("name", nargs="?", help="its name in this vault (default: restored-<fp>)")
    s.add_argument("--display", help="display name shown in From")
    s.add_argument("--offline", action="store_true", help="only put it in the vault")
    s = sub.add_parser("copy-to", help="copy identities to another device (code or QR, over Tor)",
                       description="Offer this vault's identities to another device (UN-RFC "
                                   "0050). Nothing is sent until you confirm the check words.")
    s.add_argument("--names", help="only these identities, comma-separated (default: all)")
    s.add_argument("--no-group-secrets", action="store_true",
                   help="leave out the closed groups' secrets")
    s.add_argument("--yes", action="store_true", help="do not ask whether the check words match")
    s = sub.add_parser("copy-from", help="get identities from another device with its code",
                       description="Get identities from another device (UN-RFC 0050) with the "
                                   "code it shows, or the text of its QR code.")
    s.add_argument("code")
    sub.add_parser("passphrase", help="give the vault a new passphrase",
                   description="Give the vault a new passphrase. The current one is the one it was "
                               "opened with; the new one is asked for twice, or taken from "
                               "UNSEENET_NEW_PASSPHRASE for scripts. Copies of the vault elsewhere "
                               "keep the old passphrase.")
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
    s.add_argument("--keep-author", action="append", metavar="KEY",
                   help="with --all: leave the posts by this key (repeat)")
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
    s.add_argument("--origin-network", metavar="NAME",
                   help="your own post imported from another network, e.g. facebook (UN-RFC 0049)")
    s.add_argument("--origin-date", metavar="RFC3339",
                   help="when it was first published there, e.g. 2026-08-03T14:20:00Z")
    s.add_argument("--origin-id", metavar="ID", help="its ID there (links this key to that account)")
    s.add_argument("--origin-from", metavar="NAME", help="its author there")
    s = sub.add_parser("pin", help="owner or moderator: pin a post at the top of a group")
    s.add_argument("group")
    s.add_argument("message_id", help="the post's Message-ID")
    s.add_argument("--note", help="a short note shown with the pin")
    s.add_argument("--unpin", action="store_true", help="unpin it instead")
    s = sub.add_parser("react", help="react to a post, comment or chat line with an emoji "
                                     "(again: take it back)")
    s.add_argument("group")
    s.add_argument("message_id", help="the post's Message-ID")
    s.add_argument("emoji", help="one emoji the group takes, e.g. 👍")
    s.add_argument("--who", action="store_true", help="list who gave this emoji instead")
    s = sub.add_parser("pins", help="the posts pinned in a group")
    s.add_argument("group")
    s = sub.add_parser("page-put", help="write a page of a site (UN-RFC 0035)")
    s.add_argument("group", help="the site's Group ID")
    s.add_argument("path", help="e.g. index, about, guides/start")
    s.add_argument("file", help="the page as Markdown (.txt: plain text), - for stdin")
    s.add_argument("--title", help="the page's title (default: its path)")
    s.add_argument("--attach", action="append", metavar="FILE",
                   help="a file to send with the page; images in it: ![alt](file:photo.jpg)")
    s = sub.add_parser("export", help="your data as a file (never your keys)")
    s.add_argument("file", nargs="?", help="where to write it (default: unseenet-export-<fp>.zip)")
    s.add_argument("--private", action="store_true",
                   help="also private posts and chats; the file is then encrypted with a passphrase")
    s = sub.add_parser("site-publish", help="publish a folder of Markdown (and HTML) as a site's pages")
    s.add_argument("folder", help="the folder: .md (and .html) files are pages, index.md the front page")
    s.add_argument("group", help="the site's Group ID")
    s.add_argument("--dry-run", action="store_true", help="show what would be sent, send nothing")
    s.add_argument("--prune", action="store_true", help="also remove pages no longer in the folder")
    s.add_argument("--yes", action="store_true", help="do not ask before sending")
    s = sub.add_parser("page-remove", help="remove a page from a site")
    s.add_argument("group")
    s.add_argument("path")
    s = sub.add_parser("pages", help="the pages of a site")
    s.add_argument("group")
    for kind in ("feed", "site"):
        s = sub.add_parser(f"{kind}-start", help=f"start your personal {kind} (public, tied to your key)")
        s.add_argument("--title")
        if kind == "feed":
            s.add_argument("--comments", choices=["open", "none"], default="open",
                           help="whether readers may comment (default open)")
        s.add_argument("--attachments", type=int, metavar="MAX_SIZE",
                       help="let it carry files up to this many octets (default: pictures "
                            "up to 4 MiB)")
        s.add_argument("--no-files", action="store_true",
                       help="carry no files at all (new ones take pictures by default)")
        s.add_argument("--types", help="with --attachments: e.g. image/*")
        s.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")
    s = sub.add_parser("profile", help="show or publish your profile (public), or --of someone's")
    s.add_argument("--of", metavar="WHO", help="show this person's profile (key, fingerprint or name)")
    s.add_argument("--about", help="a few words about you")
    s.add_argument("--markdown", action="store_true", help="--about is Markdown")
    s.add_argument("--link", action="append", metavar="KIND=VALUE",
                   help="e.g. web=https://..., mastodon=@me@host, email=me@... (repeat; replaces all)")
    s.add_argument("--lang", action="append", metavar="TAG", help="a language you write, e.g. da")
    s.add_argument("--feed", action="append", metavar="GROUP_ID",
                   help="a feed of yours your followers should also follow (UN-RFC 0022 4.5)")
    s.add_argument("--picture", metavar="FILE", help="your picture: cut square, made small, no metadata")
    s.add_argument("--alt", help="with --picture: what it shows, for screen readers")
    s.add_argument("--remove-picture", action="store_true")
    s.add_argument("--empty", action="store_true", help="publish an empty profile")
    s.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")
    s = sub.add_parser("follow", help="follow a feed, or a person (nobody is told)")
    s.add_argument("target", help="a Group ID or address, or a key, fingerprint or name")
    s = sub.add_parser("unfollow", help="stop following a feed or a person")
    s.add_argument("target")
    s = sub.add_parser("following", help="the people and feeds you follow")
    s.add_argument("--refresh", action="store_true", help="read their profiles again first")
    s = sub.add_parser("timeline", help="the entries of the feeds you follow - newest first, "
                       "or as your own rules have them")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--why", action="store_true", help="with your rules: why each entry is where it is")
    s = sub.add_parser("rules", help="your own rules for your feed and groups (UN-RFC 0051)")
    s.add_argument("what", nargs="?", default="show", choices=["show", "help", "set", "check", "on", "off", "clear"])
    s.add_argument("file", nargs="?", help="set, check: a file of rules (- or none: stdin)")
    s = sub.add_parser("thread", help="watch a thread, ignore it, or neither")
    s.add_argument("what", choices=["watch", "ignore", "clear"])
    s.add_argument("msgid", help="the Message-ID of the thread's first post")
    s = sub.add_parser("address", help="the unseenet: address of a group, post, page - or you")
    s.add_argument("group", nargs="?")
    s.add_argument("--message", metavar="MSGID")
    s.add_argument("--page", metavar="PATH")
    s.add_argument("--node", metavar="ONION", help="add a node that carries it, as a hint")
    s = sub.add_parser("open", help="say what an unseenet: address names")
    s.add_argument("address")
    s.add_argument("--follow", action="store_true", help="and follow it")
    names_parsers(sub)
    reports_parsers(sub)
    teams_parsers(sub)
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

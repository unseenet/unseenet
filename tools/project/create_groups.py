#!/usr/bin/env python3
"""The project's groups, created and owned by the project key.

    python tools/project/create_groups.py [--dry-run]

This is the list of every group the project owns, with its type, its posters,
its view and its charter, so that anyone can see how the project is set up and
do the same for their own. Missing groups are created. A group that exists
(the owner vault knows it) gets a new manifest, with the next serial, if its
view, title, description, charter, min_pow, kinds or portals differ from this list (or its
charter still has the earlier field name `rules`, UN-RFC 0014 section 2.2); everything
else in its manifest, such as its posters or `claims`, is kept. Groups that
match are left alone, so running the script again changes nothing.

The groups that carry lists and certificates for programs are `data` groups
(UN-RFC 0008 section 3.1.1), which clients hide when people browse.

Everything is posted over Tor to the project's nodes. --dry-run shows what
would change, signs everything, and posts and stores nothing.

Posters are keys the project key lets post in a channel, so that automation
never needs the project key itself:

- github_poster: the GitHub Actions key (repository secret
  UNSEENET_ANNOUNCE_SEED), which posts releases, the node list, the root list
  and the project's hierarchy list (tools/announce.py), and the daily canaries
  (tools/node_health.py); unseenet-entrance's CI has it too, for new versions
  of the web client in unseenet.releases (share_poster.py);
- registrar keys: see setup_registrar.py;
- bot keys, written here as public keys: the bots of unseenet/unseenet-bots,
  which run on unseenet-node3 as the user `bots` with their keys in
  /home/bots/.config/unseenet-bots/ (see the backup notes).

The bots' channels are open for comments (UN-RFC 0030): readers may reply to
a post, only the bot starts threads.
"""

from __future__ import annotations

import asyncio
import json
import sys

import _owner
from _owner import FP, fetch_manifests, open_owner_session, post_everywhere

from unseenet.core.groups import make_manifest, manifest_article, with_charter

TALK = """The place to talk about Unseenet itself: the protocol (the UN-RFCs), the
node and client software, ideas, bugs and questions. Danish is fine too.
To try posting, use unseenet.test."""

ANNOUNCE = """Announcements from the Unseenet project: releases, security notices,
changes to the network. Only the project posts here - it is a channel.
Discussion belongs in unseenet@""" + FP + "."

NODES = """The list of known Unseenet nodes, for clients to read. Each post is one
complete list as JSON (UN-RFC 0010); the newest one counts. Only the project
posts here. To have a node listed, use the "Add my node" form on GitHub."""

ENTRANCES = """The list of known web entrances (UN-RFC 0043 section 8.1), for web
clients and the jump page to read. Each post is one complete list as JSON;
the newest one counts. Only the project posts here. To have an entrance
listed, open an issue in unseenet/unseenet-entrance."""

RELEASES = """New versions of programs that update themselves through the network, for
them to read: first the web client (UN-RFC 0043 sections 7.2 and 7.3). Each
post names one version and the SHA-256 of every one of its files; programs
check what they download against it, wherever it came from. Only the project
posts here. The newest version counts; nothing ever goes back to an older one."""

HIERARCHIES = """The project's root list of hierarchies (UN-RFC 0018), for clients and
nodes to read. Each post is one complete list as JSON; the newest one counts.
It is kept in the project's repository and changed by pull request. To ask
for a hierarchy, use the "Request a hierarchy" form on GitHub, or write to
the project's inbox. Requests are discussed in unseenet.admin@""" + FP + "."

CHECKGROUPS = """The project's hierarchy list for unseenet.* (UN-RFC 0018 section 5): which
group each name in the unseenet hierarchy means. Each post is one complete
list as JSON; the newest one counts. Only the project posts here."""

NAMES = """The project's registrar for names of identities (UN-RFC 0019): the name
certificates its replicas have issued, and their revocation lists. Only the
registrar posts here. To claim a name, use your client; it writes to the
claim inbox named in this group's manifest. Names are first come, first
served; top-level domains and reserved names are not given out. Complaints
about impersonation go to unseenet.admin@""" + FP + "."

ADMIN = """Requests for hierarchies and the project's decisions on them (UN-RFC 0018
section 7), and complaints about names used to impersonate someone (UN-RFC
0019 section 6.7). Decisions are made in public, here or on GitHub. General
talk about Unseenet belongs in unseenet@""" + FP + "."

CANARY = """Connection checks for the known nodes (UN-RFC 0021). Every day the project's
checker posts one small canary to each listed node and looks the next day
where it arrived. Only the checker posts here; there is nothing to read."""

CHAT = """Chat about Unseenet: quick questions, hello, what you are trying. This group
is also the Matrix room #unseenet:unseenet.org - a portal run by the project's
gateway. Everything written here is published there too, outside Tor, under
your name and the start of your key; messages from Matrix appear here, signed
by the gateway. Copies arrive seconds to minutes late, on purpose. Longer
discussion belongs in unseenet@""" + FP + "."

GATEWAYS = """The gateway directory (UN-RFC 0038 section 6): gateways to other networks
announce themselves here, for clients to read (`unseenet gateways`). Each post
is one gateway's announcement as JSON, signed by its key; the newest per key
counts and ones older than 30 days are not shown. Anybody running a gateway
may announce; this is a list, not an endorsement. A gatewayed group stays
active while one of its gateways announces it."""

TEST = "Use this group to test posting, replies and your setup. Anything goes."

HELP = """Ask here when something about Unseenet does not work or is unclear: the
client, the vault, nodes, names, groups. Any question is welcome; say what
you did and what happened. People answer when they can. The help bot
(unseenet/unseenet-helpbot) answers from the documentation if nobody has
after a while, or right away if you write @helpbot - it can be wrong, and it
says where its answer comes from. The user guide is the site unseenet.help.guide@""" + FP + """
(and unseenet.org/use/). Ideas and talk about the project belong in
unseenet@""" + FP + "."

NEWS = """What's new in Unseenet, told in plain words by the help bot (unseenet-helpbot#13)
when the project releases something: what changed for you, what node operators must do,
and where to get it. Its posts are written by a program from the release notes and can
be wrong; the official word is in unseenet.announce. Comment to ask about a release -
stay on it; the bot answers, and so may people. New threads are the bot's."""

GUIDE = """The user guide, as a site: how to do things in Unseenet - first start, your key,
groups, writing, following, private posts, names, nodes, backup - for the graphical and
the terminal client. The pages are published by a program from the documentation
(unseenet-docs, the same as unseenet.org/use/); nobody edits them here. Something wrong
or missing? Ask in unseenet.help@""" + FP + """, or open an issue in unseenet-docs.
Comments are off; questions belong in unseenet.help."""

BOT_CHARTER = """Posts here are made by a bot from {source}, credited in each post.
Comment on a post to talk about it; new threads are the bot's. Be kind, stay
on the topic of the post, and no advertising."""

# name, type, view, title, description, charter, poster (a key in the vault, or a
# public key "ed25519:..." for keys kept elsewhere), min_pow.
# The poster is only used when a group is created; later changes to posters
# are made by the scripts that own them (setup_registrar.py).
GROUPS = (
    ("unseenet", "open", "threads", "Unseenet - the project: protocol, software, ideas",
     "Talk about Unseenet itself.", TALK, None, 20),
    ("unseenet.chat", "open", "chat", "Unseenet chat - also on Matrix",
     "Chat about Unseenet, open on Matrix as #unseenet:unseenet.org (a portal: what you "
     "write here is published there too, outside Tor).", CHAT, None, 18),
    ("unseenet.test", "open", "threads", "Unseenet test posts - say hello",
     "For trying things out.", TEST, None, 20),
    ("unseenet.help", "open", "threads", "Unseenet help - ask anything",
     "Questions about using Unseenet; people and the help bot answer.", HELP, None, 20),
    ("unseenet.help.news", "channel", "feed", "What's new in Unseenet - in plain words",
     "The help bot tells about new releases in ordinary language. Comment to ask; "
     "the official release notes are in unseenet.announce.",
     NEWS, "ed25519:6gf6zqd6hzligjk57kdbna3z7uwlnipfgg47v765kitkn2avdxfa", 20),
    ("unseenet.help.guide", "channel", "pages", "The Unseenet user guide",
     "How do I ...: the user guide for both clients, published from unseenet.org.",
     GUIDE, "github_poster", 20),
    ("unseenet.announce", "channel", "threads", "Unseenet announcements: releases and news",
     "Releases, security notices and network news from the Unseenet project.", ANNOUNCE,
     "github_poster", 20),
    ("unseenet.nodes", "channel", "data", "Known Unseenet nodes (for clients)",
     "The signed list of known nodes that clients read (UN-RFC 0010).", NODES, "github_poster", 20),
    ("unseenet.entrances", "channel", "data", "Known web entrances (for web clients)",
     "The signed list of web entrances that web clients read (UN-RFC 0043).", ENTRANCES,
     "github_poster", 20),
    ("unseenet.releases", "channel", "data", "New versions, for programs that update themselves",
     "Signed versions of the web client that apps and entrances update to (UN-RFC 0043 7.3).",
     RELEASES, "github_poster", 20),
    ("unseenet.hierarchies", "channel", "data", "Hierarchies: the project's root list",
     "The signed list of hierarchies and their maintainers (UN-RFC 0018).", HIERARCHIES,
     "github_poster", 20),
    ("unseenet.checkgroups", "channel", "data", "The groups of the unseenet hierarchy",
     "The project's hierarchy list for unseenet.* (UN-RFC 0018).", CHECKGROUPS,
     "github_poster", 20),
    ("unseenet.names", "channel", "data", "Names: the project's registrar",
     "Name certificates and revocations for identities (UN-RFC 0019).", NAMES,
     "registrar_poster", 20),
    ("unseenet.canary", "channel", "data", "Connection checks for known nodes",
     "Daily canary posts that show listed nodes are connected (UN-RFC 0021).", CANARY,
     "github_poster", 20),
    ("unseenet.gateways", "open", "data", "The gateway directory",
     "Gateways to other networks announce themselves here (UN-RFC 0038).", GATEWAYS, None, 18),
    ("unseenet.admin", "open", "threads", "Hierarchy requests and name disputes",
     "Requests for hierarchies, decisions, and complaints about names.", ADMIN, None, 22),
    ("alt.news.wikipedia", "channel", "feed", "News from Wikipedia's In the news",
     "One post per story in Wikipedia's \"In the news\", by a bot. Comment on any story.",
     BOT_CHARTER.format(source="Wikipedia (CC BY-SA 4.0)"),
     "ed25519:2xx732vxtge5ficz7ihbi75uctegsmyzc5bmllwett62etjtfuza", 20),
    ("alt.history.onthisday", "channel", "feed", "On this day in history",
     "Each day's anniversaries from Wikipedia's \"On this day\", by a bot.",
     BOT_CHARTER.format(source="Wikipedia (CC BY-SA 4.0)"),
     "ed25519:ame5agdrby6zyjqusfnpyicxg4nygfai3lqwewz2ctkkjuid3hxa", 20),
    ("alt.news.globalvoices", "channel", "feed", "Global Voices: citizen media from around the world",
     "Whole stories from Global Voices, by a bot. Comment on any story.",
     BOT_CHARTER.format(source="Global Voices (CC BY 3.0)"),
     "ed25519:ojyu2pv2v3aye2tw4xbel3ha5loujwxqjao5wnoe55dw7zc4fw7q", 20),
    ("alt.news.theconversation", "channel", "feed", "The Conversation: news analysis by researchers",
     "The opening of articles from The Conversation, with a link to the rest, by a bot.",
     BOT_CHARTER.format(source="The Conversation (CC BY-ND 4.0)"),
     "ed25519:7ky3decxcamoqttl2fqysiie24ptdxt4mld5yrxdb2ftbheukydq", 20),
    ("alt.privacy.eff", "channel", "feed", "EFF Deeplinks: digital rights, privacy, free speech",
     "Posts from the Electronic Frontier Foundation's Deeplinks blog, by a bot.",
     BOT_CHARTER.format(source="EFF Deeplinks (CC BY 4.0)"),
     "ed25519:uangztkgxp6ql2nxj6fy34d2bjspykt5taxfi7i4urrcm2o4kvca", 20),
    ("alt.space.nasa", "channel", "feed", "NASA Image of the Day",
     "NASA's Image of the Day: the caption and a link to the picture, by a bot.",
     BOT_CHARTER.format(source="NASA (not copyrighted)"),
     "ed25519:ftseuejwlor33343q7d6on3zq4yow2dn5ro7zbltfbufilacu3eq", 20),
)

# Channels open for comments (UN-RFC 0030): name -> (comments, comment_days).
COMMENTS = {
    "unseenet.help.news": ("open", 30),       # releases are slower than daily news
    "alt.news.wikipedia": ("open", 14),
    "alt.history.onthisday": ("open", 7),
    "alt.news.globalvoices": ("open", 14),
    "alt.news.theconversation": ("open", 14),
    "alt.privacy.eff": ("open", 14),
    "alt.space.nasa": ("open", 7),
}


# Files the bot channels take (UN-RFC 0027 section 5.1): pictures, kept small - a node
# keeps at most 8 MiB of files per group (UN-RFC 0017 2.2), so a picture a day must be
# a few hundred KiB for its channel to keep them for weeks. The Conversation's are
# agency pictures the bot does not post (unseenet-bots#7), so it takes none.
BOT_PICTURES = {"max_size": 512 * 1024, "types": ["image/*"]}
ATTACHMENTS = {name: BOT_PICTURES for name in (
    "alt.news.wikipedia", "alt.history.onthisday", "alt.news.globalvoices",
    "alt.privacy.eff", "alt.space.nasa")}
# the user guide's screenshots (unseenet-docs#7): about a dozen, each under 64 KiB
ATTACHMENTS["unseenet.help.guide"] = BOT_PICTURES


# The project's spam report issuer (tools/project/report_issuer.py), named in the bot
# channels for their readers (UN-RFC 0045 section 7.5): alt.* has no maintainer to name
# one, and spam there can come only in comments. Readers can turn it off.
PROJECT_ISSUER = "ed25519:mhgvcdevmx5g2r6tqm5nrsm62k4hp3ahpgpx7re5lqvmw326btmq"
REPORT_ISSUERS = {name: [PROJECT_ISSUER] for name in (
    "alt.news.wikipedia", "alt.history.onthisday", "alt.news.globalvoices",
    "alt.news.theconversation", "alt.privacy.eff", "alt.space.nasa")}

# The languages written in a group (UN-RFC 0052 section 5a): the project talks English,
# and the bot channels' sources are English. Data channels hold no text for people, so
# they say none. Clients suggest the group's language to those who write there.
LANGUAGES = {name: ["en"] for name in (
    "unseenet", "unseenet.chat", "unseenet.test", "unseenet.help", "unseenet.help.news",
    "unseenet.help.guide",
    "unseenet.announce", "unseenet.admin",
    "alt.news.wikipedia", "alt.history.onthisday", "alt.news.globalvoices",
    "alt.news.theconversation", "alt.privacy.eff", "alt.space.nasa")}


# The project's labeller (UN-RFC 0053), named in the bot channels for their readers'
# warnings, as the issuer above: set its key here once the label bot has one
# (unseenet-bots#21). Until then, None names nobody. Readers can turn it off.
PROJECT_LABELLER: str | None = None
LABELLERS = {name: [PROJECT_LABELLER] for name in REPORT_ISSUERS} if PROJECT_LABELLER else {}


# Portals (UN-RFC 0023 section 3.5): name -> the group's counterparts on other networks,
# each run by the gateway key listed. The project's official gateway runs on the
# unseenet-helpbot VM (see UN-RFC 0037 for Matrix).
OFFICIAL_GATEWAY = "ed25519:dxgwb5ltpnmmh33rab6rpsfzmmdqrzwkrnzjtj4oos7m2ffl4aiq"
PORTALS = {
    "unseenet.chat": [{"network": "matrix", "source": "#unseenet:unseenet.org",
                       "gateway": [OFFICIAL_GATEWAY]}],
}

# What a group takes (UN-RFC 0028 section 4.1), where it is not both.
KINDS = {"unseenet.chat": ["chat"]}


# What this list decides for groups that already exist, and each field's default.
SETTINGS = {"view": "threads", "title": "", "description": "", "charter": "", "min_pow": 0,
            "comments": "none", "comment_days": None, "portals": [], "kinds": None,
            "attachments": None, "report_issuers": None, "labellers": None, "languages": None}


def _short(value) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= 60 else text[:57] + "..."


def updated_manifest(current: dict, gtype: str, wanted: dict) -> tuple[dict | None, list[str]]:
    """The next manifest for an existing group, or None if it already matches."""
    if current.get("type") != gtype:
        sys.exit(f"{current.get('name')} is a {current.get('type')} group, not {gtype}; "
                 "a group's type cannot change (UN-RFC 0004 section 2)")
    legacy = any(k in current for k in ("rules", "rules_type"))     # UN-RFC 0014 2.2
    current = with_charter(current)
    changes = [k for k, default in SETTINGS.items() if current.get(k, default) != wanted[k]]
    if not changes and not legacy:
        return None, []
    data = dict(current)
    data.update({k: wanted[k] for k in changes})
    for k, default in (("comments", "none"), ("comment_days", None), ("portals", []),
                       ("kinds", None), ("attachments", None), ("report_issuers", None),
                       ("labellers", None), ("languages", None)):
        if data.get(k, default) == default:
            data.pop(k, None)                   # defaults are left out of manifests
    data["serial"] = int(current["serial"]) + 1
    notes = [f"    {k}: {_short(current.get(k, '-'))!r} -> {_short(wanted[k])!r}" for k in changes]
    if legacy:
        notes.append("    rules -> charter (the field's current name)")
    return data, notes


async def main() -> None:
    dry = "--dry-run" in sys.argv[1:]
    s = open_owner_session()
    owner = s.identity()
    todo = []                                   # (article, type, new group?)
    owned = [f"{g[0]}@{owner.fingerprint}" for g in GROUPS
             if s.data["groups"].get(f"{g[0]}@{owner.fingerprint}", {}).get("owner")]
    network = await fetch_manifests(owned) if owned else {}
    for name, gtype, view, title, desc, charter, poster, min_pow in GROUPS:
        gid = f"{name}@{owner.fingerprint}"
        entry = s.data["groups"].get(gid, {})
        if entry.get("owner"):
            # the newest of what the nodes have and what the vault remembers
            known = [m for m in (network.get(gid), entry.get("manifest")) if m]
            if not known:
                sys.exit(f"{gid}: no node has its manifest and the vault has none; "
                         "is a node reachable?")
            current = max(known, key=lambda m: int(m.get("serial", 0)))
            comments, comment_days = COMMENTS.get(name, ("none", None))
            wanted = {"view": view, "title": title, "description": desc, "charter": charter,
                      "min_pow": min_pow, "comments": comments, "comment_days": comment_days,
                      "portals": PORTALS.get(name, []), "kinds": KINDS.get(name),
                      "attachments": ATTACHMENTS.get(name),
                      "report_issuers": REPORT_ISSUERS.get(name),
                      "labellers": LABELLERS.get(name),
                      "languages": LANGUAGES.get(name)}
            data, notes = updated_manifest(current, gtype, wanted)
            if data is None:
                print(f"{gid}: up to date (serial {current['serial']})")
                entry["manifest"] = current
                continue
            todo.append((manifest_article(owner, gid, data, pow_bits=_owner.POW_BITS), gtype, False))
            print(f"{gid}: will update to serial {data['serial']}")
            print("\n".join(notes))
            continue
        if poster and not poster.startswith("ed25519:") and poster not in s.data:
            sys.exit(f"{gid} needs the {poster} key, which is not in the vault")
        posters = ([poster] if poster.startswith("ed25519:") else [s.data[poster]["key"]]) \
            if poster else []
        comments, comment_days = COMMENTS.get(name, (None, None))
        art = make_manifest(owner, name, gtype, title=title, description=desc, charter=charter,
                            posters=posters, min_pow=min_pow, retention_days=90,
                            view=None if view == "threads" else view,
                            comments=comments, comment_days=comment_days,
                            kinds=KINDS.get(name), pow_bits=_owner.POW_BITS,
                            extra={k: v for k, v in (("attachments", ATTACHMENTS.get(name)),
                                                     ("report_issuers", REPORT_ISSUERS.get(name)),
                                                     ("labellers", LABELLERS.get(name)),
                                                     ("languages", LANGUAGES.get(name))) if v} or None)
        if PORTALS.get(name):                   # make_manifest has no portals: add and re-sign
            data = json.loads(art.body)
            data["portals"] = PORTALS[name]
            art = manifest_article(owner, gid, data, pow_bits=_owner.POW_BITS)
        todo.append((art, gtype, True))
        print(f"{gid}: will create ({gtype}, view {view}, posters {posters or 'none'})")
    if not dry:
        s.save()                                # remembers the manifests read from the nodes
    if not todo or dry:
        print("Nothing to do." if not todo else "--dry-run: nothing posted or stored.")
        return
    if await post_everywhere([a for a, _, _ in todo], session=s) == 0:
        sys.exit("No node took the manifests; nothing stored. Try again later.")
    for art, gtype, new in todo:
        entry = s.group_entry(art.group)
        entry.update({"type": gtype, "owner": True, "owner_key": owner.key_text,
                      "manifest": json.loads(art.body)})
        if new:
            s.subscribe(art.group)
    s.save()
    await s.close()
    print("Done: " + ", ".join(a.group for a, _, _ in todo))


if __name__ == "__main__":
    asyncio.run(main())

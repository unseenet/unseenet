#!/usr/bin/env python3
"""The project's groups, created and owned by the project key.

    python tools/project/create_groups.py [--dry-run]

This is the list of every group the project owns, with its type, its posters,
its view and its rules, so that anyone can see how the project is set up and
do the same for their own. Missing groups are created. A group that exists
(the owner vault knows it) gets a new manifest, with the next serial, if its
view, title, description, rules or min_pow differ from this list; everything
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
  (tools/node_health.py);
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

from unseenet.core.groups import make_manifest, manifest_article

TALK = """The place to talk about Unseenet itself: the protocol (the UN-RFCs), the
node and client software, ideas, bugs and questions. Danish is fine too.
To try posting, use unseenet.test."""

ANNOUNCE = """Announcements from the Unseenet project: releases, security notices,
changes to the network. Only the project posts here - it is a channel.
Discussion belongs in unseenet@""" + FP + "."

NODES = """The list of known Unseenet nodes, for clients to read. Each post is one
complete list as JSON (UN-RFC 0010); the newest one counts. Only the project
posts here. To have a node listed, use the "Add my node" form on GitHub."""

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

TEST = "Use this group to test posting, replies and your setup. Anything goes."

BOT_RULES = """Posts here are made by a bot from {source}, credited in each post.
Comment on a post to talk about it; new threads are the bot's. Be kind, stay
on the topic of the post, and no advertising."""

# name, type, view, title, description, rules, poster (a key in the vault, or a
# public key "ed25519:..." for keys kept elsewhere), min_pow.
# The poster is only used when a group is created; later changes to posters
# are made by the scripts that own them (setup_registrar.py).
GROUPS = (
    ("unseenet", "open", "threads", "Unseenet - the project: protocol, software, ideas",
     "Talk about Unseenet itself.", TALK, None, 20),
    ("unseenet.test", "open", "threads", "Unseenet test posts - say hello",
     "For trying things out.", TEST, None, 20),
    ("unseenet.announce", "channel", "threads", "Unseenet announcements: releases and news",
     "Releases, security notices and network news from the Unseenet project.", ANNOUNCE,
     "github_poster", 20),
    ("unseenet.nodes", "channel", "data", "Known Unseenet nodes (for clients)",
     "The signed list of known nodes that clients read (UN-RFC 0010).", NODES, "github_poster", 20),
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
    ("unseenet.admin", "open", "threads", "Hierarchy requests and name disputes",
     "Requests for hierarchies, decisions, and complaints about names.", ADMIN, None, 22),
    ("alt.news.wikipedia", "channel", "threads", "News from Wikipedia's In the news",
     "One post per story in Wikipedia's \"In the news\", by a bot. Comment on any story.",
     BOT_RULES.format(source="Wikipedia (CC BY-SA 4.0)"),
     "ed25519:2xx732vxtge5ficz7ihbi75uctegsmyzc5bmllwett62etjtfuza", 20),
    ("alt.history.onthisday", "channel", "threads", "On this day in history",
     "Each day's anniversaries from Wikipedia's \"On this day\", by a bot.",
     BOT_RULES.format(source="Wikipedia (CC BY-SA 4.0)"),
     "ed25519:ame5agdrby6zyjqusfnpyicxg4nygfai3lqwewz2ctkkjuid3hxa", 20),
    ("alt.news.globalvoices", "channel", "threads", "Global Voices: citizen media from around the world",
     "Whole stories from Global Voices, by a bot. Comment on any story.",
     BOT_RULES.format(source="Global Voices (CC BY 3.0)"),
     "ed25519:ojyu2pv2v3aye2tw4xbel3ha5loujwxqjao5wnoe55dw7zc4fw7q", 20),
    ("alt.news.theconversation", "channel", "threads", "The Conversation: news analysis by researchers",
     "The opening of articles from The Conversation, with a link to the rest, by a bot.",
     BOT_RULES.format(source="The Conversation (CC BY-ND 4.0)"),
     "ed25519:7ky3decxcamoqttl2fqysiie24ptdxt4mld5yrxdb2ftbheukydq", 20),
    ("alt.privacy.eff", "channel", "threads", "EFF Deeplinks: digital rights, privacy, free speech",
     "Posts from the Electronic Frontier Foundation's Deeplinks blog, by a bot.",
     BOT_RULES.format(source="EFF Deeplinks (CC BY 4.0)"),
     "ed25519:uangztkgxp6ql2nxj6fy34d2bjspykt5taxfi7i4urrcm2o4kvca", 20),
    ("alt.space.nasa", "channel", "threads", "NASA Image of the Day",
     "NASA's Image of the Day: the caption and a link to the picture, by a bot.",
     BOT_RULES.format(source="NASA (not copyrighted)"),
     "ed25519:ftseuejwlor33343q7d6on3zq4yow2dn5ro7zbltfbufilacu3eq", 20),
)

# Channels open for comments (UN-RFC 0030): name -> (comments, comment_days).
COMMENTS = {
    "alt.news.wikipedia": ("open", 14),
    "alt.history.onthisday": ("open", 7),
    "alt.news.globalvoices": ("open", 14),
    "alt.news.theconversation": ("open", 14),
    "alt.privacy.eff": ("open", 14),
    "alt.space.nasa": ("open", 7),
}


# What this list decides for groups that already exist, and each field's default.
SETTINGS = {"view": "threads", "title": "", "description": "", "rules": "", "min_pow": 0,
            "comments": "none", "comment_days": None}


def _short(value) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= 60 else text[:57] + "..."


def updated_manifest(current: dict, gtype: str, wanted: dict) -> tuple[dict | None, list[str]]:
    """The next manifest for an existing group, or None if it already matches."""
    if current.get("type") != gtype:
        sys.exit(f"{current.get('name')} is a {current.get('type')} group, not {gtype}; "
                 "a group's type cannot change (UN-RFC 0004 section 2)")
    changes = [k for k, default in SETTINGS.items() if current.get(k, default) != wanted[k]]
    if not changes:
        return None, []
    data = dict(current)
    data.update({k: wanted[k] for k in changes})
    for k, default in (("comments", "none"), ("comment_days", None)):
        if data.get(k, default) == default:
            data.pop(k, None)                   # defaults are left out of manifests
    data["serial"] = int(current["serial"]) + 1
    notes = [f"    {k}: {_short(current.get(k, '-'))!r} -> {_short(wanted[k])!r}" for k in changes]
    return data, notes


async def main() -> None:
    dry = "--dry-run" in sys.argv[1:]
    s = open_owner_session()
    owner = s.identity()
    todo = []                                   # (article, type, new group?)
    owned = [f"{g[0]}@{owner.fingerprint}" for g in GROUPS
             if s.data["groups"].get(f"{g[0]}@{owner.fingerprint}", {}).get("owner")]
    network = await fetch_manifests(owned) if owned else {}
    for name, gtype, view, title, desc, rules, poster, min_pow in GROUPS:
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
            wanted = {"view": view, "title": title, "description": desc, "rules": rules,
                      "min_pow": min_pow, "comments": comments, "comment_days": comment_days}
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
        art = make_manifest(owner, name, gtype, title=title, description=desc, rules=rules,
                            posters=posters, min_pow=min_pow, retention_days=90,
                            view=None if view == "threads" else view,
                            comments=comments, comment_days=comment_days,
                            pow_bits=_owner.POW_BITS)
        todo.append((art, gtype, True))
        print(f"{gid}: will create ({gtype}, view {view}, posters {posters or 'none'})")
    if not dry:
        s.save()                                # remembers the manifests read from the nodes
    if not todo or dry:
        print("Nothing to do." if not todo else "--dry-run: nothing posted or stored.")
        return
    if await post_everywhere([a.to_bytes() for a, _, _ in todo]) == 0:
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

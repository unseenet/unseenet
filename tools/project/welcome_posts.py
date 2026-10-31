#!/usr/bin/env python3
"""The project's welcome posts: one pinned post at the top of each project group.

    python3 tools/project/welcome_posts.py [--dry-run] [--group NAME ...]

Each group in WELCOME below gets one welcome post by the project key, pinned with
the group's note (UN-RFC 0033), so a newcomer sees first where they are and where
to go. The texts live here so anyone can see them and change them by pull request.

For each group the script reads the group, then:

- if the post pinned with that note already has this text, nothing is done, so
  running it again changes nothing;
- otherwise it posts the new text, pins it, and only then withdraws the earlier
  welcome (the one pinned with the note, and the old unpinned ones named in
  `old`), so the group is never without one.

The groups are owned by the project key, so only it can pin and withdraw there;
the script asks for the owner vault's passphrase. --dry-run reads the groups and
shows what would be posted, pinned and withdrawn, and sends nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from _owner import FP, builtin_list, open_owner_session

from unseenet.client.session import SessionError

LINKS = """\
- First start: https://unseenet.org/use/first-start/
- The user guide: https://unseenet.org/use/
- How it all works: https://unseenet.org/guide/ - and what is hidden from whom:
  https://unseenet.org/guide/threats/"""

PRE_ALPHA = """\
Unseenet is pre-alpha and has not had a security review yet: play with it and
pick it apart, but don't rely on it to protect anyone yet."""

TALK = f"""\
**Welcome!** This is the Unseenet project's own group: talk about the protocol
(the UN-RFCs), the node and the clients, ideas, bugs and plans.
Dansk er også velkommen her.

Unseenet is a discussion network in the spirit of old Usenet and the BBSes,
carried entirely over Tor onion services: chat, threaded discussion, feeds,
sites and private posts, on nodes anyone can run. No accounts - you are your key.

### Where to go

- !unseenet.help@{FP} - stuck or unsure? Ask here; people and the help bot answer.
- !unseenet.chat@{FP} - quick chat, also
  [the project's Matrix room](https://matrix.to/#/#unseenet:unseenet.org) (outside Tor).
- !test.unseenet@{FP} - try posting, replies and pictures. Anything goes.
- !unseenet.help.guide@{FP} - the user guide, as a site in the network.
- !unseenet.help.news@{FP} - what's new, in plain words.
- !unseenet.announce@{FP} - the official release notes.
- !demo.unseenet - a small demo village with feeds, a site and photos.

### Read more

{LINKS}
- Run a node: https://unseenet.org/node/install/ - or a web entrance:
  https://unseenet.org/entrance/
- The spec: https://unseenet.org/spec/ - the code: https://github.com/unseenet

{PRE_ALPHA}"""

HELP = f"""\
**Ask anything here** - about the graphical or the terminal client, your key and
vault, nodes, names or groups. No question is too small.

### How to get a good answer

- Say which client you use (graphical, terminal or in the browser) and its version
  (it is in *About Unseenet*).
- Say what you did, what you expected, and what happened instead - the exact
  error text helps.
- Never post your passphrase, recovery words or vault file.

People answer when they can. The help bot answers from the documentation if
nobody has after a while, or right away if you write @helpbot. It can be wrong,
and it says where its answer comes from.

### Maybe it is already answered

{LINKS}
- The user guide in the network: !unseenet.help.guide@{FP}
- Help on the web: https://unseenet.org/help/

Ideas and talk about the project belong in !unseenet@{FP}; quick chat in
!unseenet.chat@{FP}."""

TEST = f"""\
**Try things out here** - nothing in this group needs to make sense, and
nobody minds.

Some things to try:

- write a post, then reply to it with a quote;
- edit or withdraw one of your own posts;
- add a picture, or a bit of Markdown: **bold**, *italic*, `code`, a list, a table;
- react to a post with an emoji;
- point to another group with a reference, like !unseenet.help@{FP}.

When something does not work as you expected, ask in !unseenet.help@{FP}."""

ANNOUNCE = f"""\
**About this channel.** Here the project posts the official release notes of all
its programs - the core and node, the graphical and terminal clients, the
portable and bootable builds, the web entrance, gateways, bots and the watchman -
with their checksums, and security notices and news about the network.

Only the project posts here. To read the same news in plain words, and to ask
about it, follow !unseenet.help.news@{FP}. Talk about releases in
!unseenet@{FP}.

The lists programs read live next door: known nodes in unseenet.nodes, web
entrances in unseenet.entrances, hierarchies in unseenet.hierarchies.
Everything is also on https://unseenet.org and https://github.com/unseenet."""

CHAT = f"""\
👋 Welcome to the Unseenet chat! Say hello, ask quick questions, tell what you
are trying. This group is also
[the project's Matrix room](https://matrix.to/#/#unseenet:unseenet.org): what you write here is published there too, outside Tor. Longer questions go to
!unseenet.help@{FP}, longer talk to !unseenet@{FP}."""

# name -> what is pinned there. kind: "post" (with a subject) or "chat" (a chat line,
# for groups that take only those). old: earlier welcomes that were never pinned,
# withdrawn once the new one is pinned.
WELCOME = {
    "unseenet": {"kind": "post", "subject": "Welcome to Unseenet - start here",
                 "body": TALK, "note": "Start here",
                 "old": ["<udvnfvinwimo4hucucvojtxe7sekox5w@unseenet>"]},
    "unseenet.help": {"kind": "post", "subject": "How to ask - and where answers may already be",
                      "body": HELP, "note": "Read this first", "old": []},
    "test.unseenet": {"kind": "post", "subject": "Welcome to the test group",
                      "body": TEST, "note": "Start here",
                      "old": ["<c7jf4sm3unidzn3ra5ddd6iwcuw5ogra@unseenet>"]},
    "unseenet.announce": {"kind": "post", "subject": "About this channel",
                          "body": ANNOUNCE, "note": "About this channel",
                          "old": ["<hpui45656vfuf3mq4cpboeox6a56jk5t@unseenet>"]},
    "unseenet.chat": {"kind": "chat", "subject": "", "body": CHAT, "note": "Welcome", "old": []},
}

REASON = "Replaced by a newer welcome post."


def _same(msg, w: dict) -> bool:
    return (msg.body.strip() == w["body"].strip()
            and (w["kind"] == "chat" or msg.subject.strip() == w["subject"].strip()))


async def _one(s, name: str, w: dict, dry: bool) -> str:
    """Bring one group's welcome up to date; returns what was done, in a few words."""
    gid = f"{name}@{FP}"
    m = await s.fetch_manifest(gid)
    if m is None:
        return "no such group on the nodes; skipped (run create_groups.py first)"
    s.group_entry(gid).update({"manifest": dict(m.raw), "owner": True, "type": m.raw.get("type")})
    await s.fetch_group(gid)
    me = s.identity().key_text
    ours = [p for p in s.pins(gid) if p["by"] == me and p["note"] == w["note"]]
    current = [s.find_message(gid, p["id"]) for p in ours]
    if any(msg is not None and _same(msg, w) for msg in current):
        return "up to date"
    withdrawn = set(s.group_entry(gid).get("cancels", {}))
    old = [p["id"] for p in ours] + [mid for mid in w["old"]
                                     if s.find_message(gid, mid) is not None and mid not in withdrawn]
    if dry:
        print(f"\n--- {gid}: would post and pin ({w['note']!r})")
        if w["subject"]:
            print(f"Subject: {w['subject']}")
        print(w["body"])
        return f"would replace {len(old)} earlier welcome(s): {', '.join(old) or '-'}"
    if s.portal_warning(gid):
        s.accept_portals(gid)              # the project's own portal (unseenet.chat on Matrix)
    mid = await s.post(gid, w["subject"], w["body"], kind=w["kind"], languages=["en"])
    await s.pin(gid, mid, w["note"])
    for gone in old:
        try:
            await s.withdraw(gid, gone, REASON)
        except SessionError as exc:
            print(f"  {gid}: could not withdraw {gone}: {exc}", flush=True)
    return f"posted and pinned {mid}; withdrew {len(old)} earlier"


async def run(dry: bool, only: list[str] | None, nodes: list[str] | None = None) -> None:
    unknown = set(only or ()) - set(WELCOME)
    if unknown:
        sys.exit(f"No welcome text for: {', '.join(sorted(unknown))}")
    s = open_owner_session()
    for address in nodes or [n.address for n in builtin_list()[1]]:
        if address not in s.nodes:
            s.add_node(address)
    try:
        print("Reading the project's groups over Tor ...", flush=True)
        for name, w in WELCOME.items():
            if only and name not in only:
                continue
            try:
                print(f"{name}: {await _one(s, name, w, dry)}", flush=True)
            except (OSError, ConnectionError, SessionError) as exc:
                print(f"{name}: not done ({exc})", flush=True)
        if dry:
            print("\n--dry-run: nothing posted, pinned or withdrawn.")
    finally:
        if not dry:
            s.save()
        await s.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="show what would be done, send nothing")
    ap.add_argument("--group", action="append", metavar="NAME",
                    help="only this group, e.g. unseenet.help (repeat); default: all")
    args = ap.parse_args()
    asyncio.run(run(args.dry_run, args.group))


if __name__ == "__main__":
    main()

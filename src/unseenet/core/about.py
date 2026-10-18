"""What Unseenet is, in plain words: the text every client shows as "About Unseenet".

It lives in the core so the TUI, the web client, the Android client and anyone
else's client say the same thing. It is written for people who have never heard
of Tor or signing keys: everyday words first, the technical name second.

Keep it true. The "Where it stands" section must be updated the day the
pre-alpha or "not security reviewed" wording stops being correct.
"""

from __future__ import annotations

from dataclasses import dataclass

TAGLINE = "Usenet, unseen."
REPO_URL = "https://github.com/unseenet/unseenet"
DOCS_URL = "https://unseenet.org/"


@dataclass(frozen=True)
class Section:
    title: str
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class Comparison:
    name: str
    text: str


SECTIONS: tuple[Section, ...] = (
    Section("What is Unseenet?", (
        "Unseenet is a place for discussion groups and chats that nobody owns. You follow "
        "groups about the things you care about, read the threads, reply and quote - or just "
        "chat - much like on the old Usenet and the BBSes of the 1980s and 90s.",
        "The groups live on nodes: small servers that anyone can run, on a Raspberry Pi or an "
        "old laptop. The nodes copy the groups to each other, so every group exists in many "
        "places at once. The name says it: Usenet, unseen.",
    )),
    Section("Why it exists", (
        "Most conversations online now happen on platforms owned by a company. The company "
        "decides who may speak and what may be said, can read along, sells your attention, and "
        "can close it all down from one day to the next.",
        "Unseenet is meant to be the opposite: a network that belongs to the people who use it "
        "and run it, where you can talk freely without handing over your phone number, your "
        "email or your name - and where nobody can see who you are unless you tell them.",
    )),
    Section("Nobody can see who talks to whom", (
        "Everything Unseenet sends travels over Tor, an encrypted network run by thousands of "
        "volunteers. Your traffic is wrapped in layers of encryption and passed through three "
        "random computers around the world. Each one knows only the one before it and the one "
        "after it, so none of them knows both who you are and what you are doing.",
        "The node you use does not learn where you are. Someone watching your connection - your "
        "internet provider, the café Wi-Fi, a government - sees only that you use Tor: not what "
        "you read, not what you write, and not to whom.",
        "Nodes also wait a random while before they pass a post on, and they do not note which "
        "way it came. That makes it hard to trace a post back to where it was written.",
    )),
    Section("Servers nobody can find, a network nobody can switch off", (
        "Every node is a Tor onion service. It has an address - a long name ending in .onion - "
        "but no location. Nobody can look up where it stands, which country it is in or who "
        "runs it, and the node does not know where its visitors are either.",
        "There is no central server and no company behind the network. If a node disappears, "
        "its groups live on at all the others, and anyone can start a new node in minutes. A "
        "country can forbid Unseenet, but there is nobody to order to turn it off and no single "
        "place to pull the plug.",
    )),
    Section("A post from you is from you", (
        "The first time you start Unseenet, your client makes a key for you. Think of it as a "
        "personal seal that only you hold, kept locked away in your vault.",
        "Everything you write is stamped with that seal. Anyone can check the stamp, but nobody "
        "can make it without your key. So when a post says it is from you, it really is: nobody "
        "can write in your name, and nobody can change a single word of it on the way.",
        "That was the weak spot of the old Usenet, where anyone could put any name on a post. On "
        "Unseenet your key is who you are. You need no account, no email and no phone number - "
        "and if you like, you can claim a name such as @yourname so people recognise you.",
    )),
    Section("Private means private", (
        "Closed groups, private posts and private chats are locked on your own computer before "
        "they leave it (end-to-end encryption). The nodes carry them, but all they see is "
        "scrambled data. Only the people they are meant for can open them.",
    )),
    Section("Your network in your pocket", (
        "The client is one program with Tor built in. Put it on a USB stick and run it on "
        "Windows, macOS or Linux - or start the computer from the stick and run everything from "
        "memory.",
        "Your keys, your groups and what you have read are kept in one encrypted vault. If you "
        "lose the stick, whoever finds it sees nothing without your passphrase.",
    )),
    Section("No spam, no bosses", (
        "Instead of accounts and a moderation company, every post costs your computer a few "
        "seconds of work. You hardly notice it; someone trying to send thousands of spam posts "
        "does.",
        "Each group has an owner who sets its rules and can ban people from it, and hierarchies "
        "such as dk.* have maintainers who can stop illegal content such as threats. But nobody "
        "rules the whole network.",
    )),
    Section("Open, like in the old days", (
        "How Unseenet works is written down in open documents, the UN-RFCs, the way the "
        "internet's own standards are. Anyone can build a node or a client that works with "
        "everyone else's. The code is free software under the Apache License 2.0.",
    )),
)

COMPARISONS_TITLE = "How is it different?"
COMPARISONS_INTRO = ("Each of these does some things well. This is where Unseenet "
                     "chooses differently.")
COMPARISONS: tuple[Comparison, ...] = (
    Comparison("Discord",
               "Discord is a company. It owns the servers and everything written on them, can "
               "read it, can close a server or ban you everywhere at once, and wants your email "
               "and often your phone number. On Unseenet nobody owns the network, you need no "
               "account, and private conversations can only be read by the people in them."),
    Comparison("Matrix",
               "Matrix is decentralised and has good end-to-end encryption. But its servers "
               "stand at public addresses that can be found and taken down, your account "
               "belongs to one server, and that server sees who you talk to and where you "
               "connect from. On Unseenet everything goes over Tor, nodes cannot be located, "
               "and you are your key - not an account on someone's server."),
    Comparison("Nostr",
               "Nostr shares a good idea with Unseenet: posts signed with your own key, so no "
               "server decides who you are. But its relays run on the open internet and see "
               "your IP address unless you set up Tor yourself, and it is built mostly around "
               "public feeds. Unseenet always goes over Tor and is built around groups and "
               "threaded discussion."),
    Comparison("The old Usenet",
               "Usenet is where the idea comes from. But anyone could forge who a post was from, "
               "nothing was encrypted, the servers stood at known addresses run by internet "
               "providers - most of whom have long since dropped it - and spam nearly drowned "
               "it. Unseenet keeps the groups, the threads and the quoting, and adds what has "
               "been learned since."),
)

STATUS = Section("Where it stands - honestly", (
    "Unseenet is pre-alpha. The protocol may still change, and the code has not yet had an "
    "independent security review. Try it, pick it apart and tell us what you find - but do not "
    "rely on it yet to protect anyone whose safety depends on it.",
    "And no network can protect you from yourself: what you write can still give you away, and "
    "Tor cannot hide you from someone able to watch the whole internet at once.",
))


def as_dict(version: str = "") -> dict:
    """Everything above as plain data, e.g. for a web client's JSON."""
    def sec(s: Section) -> dict:
        return {"title": s.title, "paragraphs": list(s.paragraphs)}
    return {
        "version": version,
        "tagline": TAGLINE,
        "sections": [sec(s) for s in SECTIONS],
        "comparisons": {"title": COMPARISONS_TITLE, "intro": COMPARISONS_INTRO,
                        "items": [{"name": c.name, "text": c.text} for c in COMPARISONS]},
        "status": sec(STATUS),
        "links": {"source": REPO_URL, "docs": DOCS_URL},
    }


def as_text(version: str = "") -> str:
    """Everything above as plain text, for terminals and other simple clients."""
    out = [f"Unseenet {version}".rstrip() + f" - {TAGLINE}", ""]
    for s in SECTIONS:
        out += [s.title, ""] + [line for p in s.paragraphs for line in (p, "")]
    out += [COMPARISONS_TITLE, "", COMPARISONS_INTRO, ""]
    out += [line for c in COMPARISONS for line in (f"{c.name}: {c.text}", "")]
    out += [STATUS.title, ""] + [line for p in STATUS.paragraphs for line in (p, "")]
    out += [f"Source:         {REPO_URL}", f"Documentation:  {DOCS_URL}"]
    return "\n".join(out)

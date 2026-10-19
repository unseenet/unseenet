"""Portals as clients see them (UN-RFC 0023 section 3.5).

A portal publishes an Unseenet group's posts on another network, outside Tor.
Clients MUST show that a group has portals, and MUST tell the user before
their first post there. This module only reads the manifest's `portals`
field and words the warning; every client uses the same text.
"""

from __future__ import annotations

NETWORK_NAMES = {
    "usenet": "Usenet", "fido": "FidoNet", "matrix": "Matrix", "irc": "IRC", "xmpp": "XMPP",
    "fedi": "the fediverse", "nostr": "Nostr", "bsky": "Bluesky", "discord": "Discord",
    "telegram": "Telegram", "slack": "Slack", "reddit": "Reddit",
}


def portals(manifest: dict) -> list[tuple[str, str]]:
    """(network, source) for each well-formed entry of a manifest's `portals` field."""
    out = []
    for p in manifest.get("portals") or []:
        if isinstance(p, dict) and isinstance(p.get("network"), str) \
                and isinstance(p.get("source"), str) and p["network"] and p["source"]:
            out.append((p["network"], p["source"]))
    return out


def network_name(network: str) -> str:
    return NETWORK_NAMES.get(network, network)


def describe(found: list[tuple[str, str]]) -> str:
    """One line per portal, e.g. 'Matrix: #unseenet:unseenet.org'."""
    return "\n".join(f"{network_name(n)}: {s}" for n, s in found)


def fingerprint(found: list[tuple[str, str]]) -> str:
    """Stable text for a set of portals, to remember which set the user accepted."""
    return "\n".join(sorted(f"{n} {s}" for n, s in found))


def warning(group: str, found: list[tuple[str, str]]) -> str:
    names = sorted({network_name(n) for n, _ in found})
    where = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return (f"{group} has a portal to {where}. What you post here is also published there, "
            "outside Tor, by a gateway: anyone on that network can read it, and it may be "
            "kept and indexed there for years. Your name and the start of your key go with "
            "it; where you are does not.\n\n" + describe(found))

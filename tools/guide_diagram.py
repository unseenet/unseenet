"""The overview drawing in "How it works" (docs/guide/), drawn at build time.

One picture of the whole network - clients, the browser and a web entrance,
Tor, nodes peering, a gateway to other networks - and the same picture in
each chapter with that chapter's parts picked out and the rest faded, so a
reader always sees where the part fits.

A page asks for it with ``<!-- unseenet:diagram NAME -->`` (see
tools/docs_hooks.py); NAME is a key of ``FOCUS``. The SVG is put inline in
the page and styled by docs/stylesheets/guide.css with the theme's own
colours, so it follows light and dark mode.
"""

from __future__ import annotations

from html import escape

W, H = 880, 400

# id: (x, y, width, height, title, subtitle)
BOXES: dict[str, tuple[int, int, int, int, str, str]] = {
    "client":   (20, 50, 170, 56, "Client", "portable · bootable"),
    "browser":  (20, 262, 170, 56, "Browser", "phone · tablet · PC"),
    "entrance": (236, 262, 124, 56, "Web entrance", "on the open web"),
    "n1":       (400, 50, 120, 52, "Node", "onion service"),
    "n2":       (490, 156, 120, 52, "Node", "onion service"),
    "n3":       (400, 262, 120, 52, "Node", "onion service"),
    "gateway":  (580, 290, 116, 52, "Gateway", "between networks"),
    "others":   (724, 290, 140, 52, "Other networks", "Usenet · Matrix · Nostr"),
}

# id: (from, to, label) - lines between the boxes' edges, drawn under the boxes
LINES: dict[str, tuple[tuple[int, int], tuple[int, int], str]] = {
    "client-n1":   ((190, 78), (400, 76), "over Tor"),
    "browser-ent": ((190, 290), (236, 290), ""),
    "ent-n3":      ((360, 290), (400, 288), ""),
    "n1-n2":       ((520, 92), (540, 156), ""),
    "n2-n3":       ((540, 208), (520, 272), ""),
    "n1-n3":       ((460, 102), (460, 262), "peering"),
    "n2-gw":       ((590, 208), (620, 290), ""),
    "gw-others":   ((696, 316), (724, 316), ""),
}

# Where a line's label goes: x, y, text-anchor.
LABELS: dict[str, tuple[int, int, str]] = {
    "client-n1": (245, 70, "middle"),
    "n1-n3":     (452, 186, "end"),
}

# Which parts each chapter picks out. "tor" is the Tor area.
ALL = set(BOXES) | set(LINES) | {"tor"}
FOCUS: dict[str, set[str]] = {
    "overview": ALL,
    "journey":  {"client", "n1", "n2", "n3", "tor", "client-n1", "n1-n2", "n2-n3", "n1-n3"},
    "identity": {"client", "browser"},
    "groups":   {"n1", "n2", "n3", "n1-n2", "n2-n3", "n1-n3"},
    "node":     {"n1", "n2", "n3", "tor", "n1-n2", "n2-n3", "n1-n3", "client-n1", "ent-n3", "n2-gw"},
    "clients":  {"client", "browser", "entrance", "client-n1", "browser-ent", "ent-n3"},
    "world":    {"browser", "entrance", "gateway", "others", "browser-ent", "ent-n3", "n2-gw", "gw-others"},
}

CAPTIONS: dict[str, str] = {
    "overview": ("The whole network: clients reach nodes over Tor; a web entrance lets a "
                 "browser in, a gateway links other networks."),
    "journey":  "A post goes from a client over Tor to its node, and from node to node.",
    "identity": "Your keys live in your client's vault, never on a node.",
    "groups":   "Groups live on the nodes, copied between them.",
    "node":     "Nodes are onion services inside Tor, peering with each other.",
    "clients":  "Clients reach a node over Tor; a browser goes through a web entrance.",
    "world":    "Entrances and gateways are the doors between Tor and the rest of the internet.",
}


def _cls(part: str, focus: set[str]) -> str:
    return "" if part in focus else " ug-dim"


def svg(name: str) -> str:
    """The drawing with the parts of FOCUS[name] picked out, as inline HTML."""
    focus = FOCUS[name]
    out = [(f'<figure class="ug-figure"><svg class="ug" viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="{escape(CAPTIONS[name])}" xmlns="http://www.w3.org/2000/svg">')]
    out.append(f'<g class="ug-torarea{_cls("tor", focus)}">'
               '<rect x="300" y="16" width="330" height="368" rx="26"/>'
               '<text x="318" y="40">Tor</text>'
               '<text class="ug-note" x="318" y="372">nodes have no address outside Tor</text></g>')
    for part, ((x1, y1), (x2, y2), label) in LINES.items():
        out.append(f'<g class="ug-link{_cls(part, focus)}">'
                   f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
        if label:
            lx, ly, anchor = LABELS[part]
            out.append(f'<text class="ug-note" x="{lx}" y="{ly}" text-anchor="{anchor}">'
                       f'{escape(label)}</text>')
        out.append("</g>")
    for part, (x, y, w, h, title, sub) in BOXES.items():
        out.append(f'<g class="ug-box{_cls(part, focus)}">'
                   f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>'
                   f'<text class="ug-title" x="{x + w / 2:.0f}" y="{y + 23}">{escape(title)}</text>'
                   f'<text class="ug-sub" x="{x + w / 2:.0f}" y="{y + 41}">{escape(sub)}</text></g>')
    out.append(f'</svg><figcaption>{escape(CAPTIONS[name])}</figcaption></figure>')
    return "".join(out)


if __name__ == "__main__":      # python tools/guide_diagram.py NAME > x.svg, to look at one
    import sys
    print(svg(sys.argv[1] if len(sys.argv) > 1 else "overview"))

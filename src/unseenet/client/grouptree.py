"""The group list as a tree, shared by the terminal and the web client.

Under a hierarchy (``alt.*``) the groups are shown without its name: ``alt.history.egypt``
is ``.history.egypt``. A part of the name that two or more groups share becomes a folder
that can be folded (``.history`` with ``.egypt`` and ``.denmark`` in it); a part only one
group has stays in its name, so there are no folders with a single group in them, and a
folder with only one folder in it is joined with it (``.usenet.comp``).

The tree only decides how names are shown. Groups are still known by their full ID,
and the full name is shown wherever a group is opened, searched for or posted to.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Iterable, TypeVar

T = TypeVar("T")


@dataclass
class Node(Generic[T]):
    """A point in the tree.

    ``label`` is the name relative to the parent, without the leading dot
    (``history``, ``usenet.comp``, ``lang.python``); ``path`` is the full name up to
    here (``alt.history``). ``items`` are the groups called exactly ``path`` - usually
    one, more if groups with the same name have different owners. A node with
    ``children`` is a folder; its own ``items`` are shown first inside it.
    """
    label: str
    path: str
    items: list[T] = field(default_factory=list)
    children: list["Node[T]"] = field(default_factory=list)

    @property
    def is_folder(self) -> bool:
        return bool(self.children)

    @property
    def own_label(self) -> str:
        """How a folder's own group is shown inside it: the last part, no dot."""
        return self.path.rsplit(".", 1)[-1]

    def all_items(self) -> list[T]:
        out = list(self.items)
        for c in self.children:
            out.extend(c.all_items())
        return out

    def folders(self) -> list["Node[T]"]:
        """This node's folders and those under them, depth first."""
        out = []
        for c in self.children:
            if c.is_folder:
                out.append(c)
                out.extend(c.folders())
        return out


@dataclass
class _Raw(Generic[T]):
    items: list[T] = field(default_factory=list)
    kids: dict[str, "_Raw[T]"] = field(default_factory=dict)

    def count(self) -> int:
        return len(self.items) + sum(k.count() for k in self.kids.values())


def _shape(raw: _Raw[T], label: str, path: str) -> Node[T]:
    # one group under here: a leaf with the rest of its name
    if raw.count() == 1:
        while not raw.items:
            seg, raw = next(iter(raw.kids.items()))
            label, path = f"{label}.{seg}", f"{path}.{seg}"
        return Node(label, path, list(raw.items))
    # nothing of its own and a single way on: join with it
    if not raw.items and len(raw.kids) == 1:
        seg, kid = next(iter(raw.kids.items()))
        return _shape(kid, f"{label}.{seg}", f"{path}.{seg}")
    return Node(label, path, list(raw.items),
                [_shape(k, seg, f"{path}.{seg}") for seg, k in sorted(raw.kids.items())])


def group_tree(top: str, entries: Iterable[tuple[str, T]]) -> Node[T]:
    """The tree of one hierarchy. ``entries`` are (group name without fingerprint, item);
    names outside ``top`` are ignored. The root is the hierarchy itself; a group called
    exactly ``top`` (``unseenet``) is in the root's ``items``. The root is never joined
    or turned into a leaf, so the caller decides how a one-group hierarchy is shown."""
    root: _Raw[T] = _Raw()
    for name, item in entries:
        if name == top:
            root.items.append(item)
        elif name.startswith(top + "."):
            raw = root
            for seg in name[len(top) + 1:].split("."):
                raw = raw.kids.setdefault(seg, _Raw())
            raw.items.append(item)
    return Node(top, top, list(root.items),
                [_shape(k, seg, f"{top}.{seg}") for seg, k in sorted(root.kids.items())])


def fingerprint_suffix(label: str) -> str:
    """``@abcd`` from a shown group label ``name@abcd``, or '' when the name is short."""
    at = label.find("@")
    return label[at:] if at >= 0 else ""

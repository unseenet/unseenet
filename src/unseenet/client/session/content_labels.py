"""Session: content labels (UN-RFC 0053) - which labellers count, what they say about a
post, what the reader chose to do with each warning, and being a labeller.

(Not the labels people and groups are shown by - that is labels.py, UN-RFC 0019.)

**A label only describes.** Nothing is hidden for a reader who did not choose that.
Warnings - the author's own (tags, UN-RFC 0052), the group's, and labellers' - are
shown, blurred or hidden per the reader's choice (blurred by default), never silently;
topics only feed the reader's rules. Your own posts and your contacts' are never blurred.

Belongs here: following labellers (warnings by default from a hierarchy or a group's
owner, topics only by the reader's own choice, section 5), reading their ``labels@``
channels, ``post_labels`` for a post, the reader's warning choices, and publishing
labels as a labeller. Not here: the form of label articles (core/labels.py).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the shared names: SessionError, Message, ...
from .. import session as _s   # names tests patch on the module, read at call time
from ... import hierarchies as hz
from ...core import labels as lb
from ...core import tags as tg
from ...core.groups import make_manifest

CHOICES = ("show", "blur", "hide")          # what the reader does with a warning (section 6)
DEFAULT_CHOICE = "blur"


class ContentLabelsMixin:
    # --- the reader's settings (UN-RFC 0044) ---
    def _label_settings(self) -> dict:
        """``{"follow": {key: {"label", "topics"}}, "off": [key], "warnings": {w: choice}}``."""
        s = self.data.setdefault("labellers", {})
        s.setdefault("follow", {})
        s.setdefault("off", [])
        s.setdefault("warnings", {})
        return s

    def warning_choices(self) -> dict[str, str]:
        """What you do with each warning: show, blur or hide (blur unless you chose)."""
        mine = self._label_settings()["warnings"]
        return {w: mine[w] if mine.get(w) in CHOICES else DEFAULT_CHOICE for w in tg.WARNINGS}

    def set_warning_choice(self, warning: str, choice: str) -> None:
        """Choose what to do with a warning: ``show``, ``blur`` or ``hide`` (section 6);
        kept with your settings (UN-RFC 0044)."""
        if warning not in tg.WARNINGS or choice not in CHOICES:
            raise SessionError(f"a warning is one of {', '.join(tg.WARNINGS)}; show, blur or hide")
        self._label_settings()["warnings"][warning] = choice
        self.save()

    def apply_age_profile(self, profile: str) -> dict[str, str]:
        """The age guide (section 6.1): take a profile's suggested choices per warning as
        your own. The profile itself is never stored - only the choices, which you can
        change afterwards like any other. Returns the choices now."""
        if profile not in lb.AGE_PROFILES:
            raise SessionError("a profile is one of " + ", ".join(lb.AGE_PROFILES))
        mine = self._label_settings()["warnings"]
        mine.update(lb.AGE_PROFILES[profile])
        self.save()
        return self.warning_choices()

    # --- which labellers count (section 5) ---
    def named_labellers(self, group_id: str) -> dict[str, str]:
        """{labeller key: where named} for warnings by default: the group's hierarchy
        (its name) and its owner (``"group"``)."""
        if group_id.startswith("inbox@") or "@" not in group_id:
            return {}
        try:
            out = dict(hz.labellers_for(group_id.rpartition("@")[0], naming.root_list(self),
                                        naming.hierarchy_lists(self)))
        except Exception:  # noqa: BLE001  lists that cannot be read name nobody
            out = {}
        for k in lb.named(self.manifest_data(group_id)):
            out.setdefault(k, "group")
        return out

    def labellers_for(self, group_id: str) -> tuple[set[str], set[str]]:
        """(labellers whose warnings count, labellers whose topics count) in a group."""
        s = self._label_settings()
        warn = {k for k in self.named_labellers(group_id) if k not in s["off"]} | set(s["follow"])
        topics = {k for k, v in s["follow"].items() if v.get("topics")}
        return warn, topics

    def labellers(self) -> list[dict]:
        """Every labeller you follow or that a hierarchy or a group of yours names, each
        ``{"key", "label", "yours", "topics", "hierarchies", "groups", "on"}``."""
        s = self._label_settings()
        hier: dict[str, set[str]] = {}
        groups: dict[str, set[str]] = {}
        for gid in self.data.get("subscribed", []):
            for k, where in self.named_labellers(gid).items():
                if where == "group":
                    groups.setdefault(k, set()).add(gid)
                else:
                    hier.setdefault(k, set()).add(where)
        out = []
        for k in sorted(set(hier) | set(groups) | set(s["follow"])):
            f = s["follow"].get(k)
            out.append({"key": k, "label": self.labeller_label(k),
                        "yours": f is not None, "topics": bool(f and f.get("topics")),
                        "hierarchies": sorted(hier.get(k, ())), "groups": sorted(groups.get(k, ())),
                        "on": f is not None or k not in s["off"]})
        return out

    def labeller_label(self, key: str) -> str:
        """What you call a labeller: the name you gave it when following, else its label."""
        f = self._label_settings()["follow"].get(key) or {}
        return f.get("label") or self.identity_label(key)

    def follow_labeller(self, key: str, label: str = "", topics: bool = False) -> None:
        """Follow a labeller in every group - its warnings, and its topics if you say so
        (section 5: topics only by your own choice)."""
        key = key.strip()
        try:
            crypto.key_from_text(key)
        except crypto.CryptoError as exc:
            raise SessionError(f"not a key: {key}") from exc
        s = self._label_settings()
        before = s["follow"].get(key) or {}
        s["follow"][key] = {"label": label.strip() or before.get("label", ""), "topics": bool(topics)}
        if key in s["off"]:
            s["off"].remove(key)
        self._label_book = None
        self.save()

    def unfollow_labeller(self, key: str) -> None:
        """Stop following a labeller, also one a hierarchy or a group names for you."""
        s = self._label_settings()
        s["follow"].pop(key, None)
        if key not in s["off"] and any(key in self.named_labellers(g) for g in self.data.get("subscribed", [])):
            s["off"].append(key)
        self._label_book = None
        self.save()

    # --- what they say ---
    def _labellers_to_read(self) -> set[str]:
        out = set(self._label_settings()["follow"])
        for gid in self.data.get("subscribed", []):
            out |= self.labellers_for(gid)[0]
        return out

    async def refresh_labels(self) -> int:
        """Read the ``labels@`` channels of the labellers that count for your groups.
        Returns how many could be read."""
        read = 0
        for key in sorted(self._labellers_to_read()):
            try:
                gid = lb.labels_group(crypto.key_from_text(key))
                m = await self.fetch_manifest(gid)
                if m is None or m.expired():
                    continue
                self.group_entry(gid)["manifest"] = dict(m.raw)
                await self.fetch_group(gid)
                read += 1
            except (SessionError, OSError, ConnectionError, NNTPError, crypto.CryptoError) as exc:
                log.debug("labels of %s not read: %s", key, exc)
        self._label_book = None
        return read

    def label_book(self) -> lb.Book:
        """What the labellers that count for your groups say, from their channels read
        (``refresh_labels``); kept until something changes."""
        cached = getattr(self, "_label_book", None)
        if cached is not None:
            return cached
        book = lb.Book()
        for key in self._labellers_to_read():
            try:
                gid = lb.labels_group(crypto.key_from_text(key))
            except crypto.CryptoError:
                continue
            for msg in self.cache.get(gid, {}).values():
                if not msg.readable:
                    continue
                try:
                    book.add(lb.read_labels(msg.message_id, msg.group, msg.author_key, msg.date, msg.body))
                except lb.LabelError:
                    continue
        self._label_book = book
        return book

    def post_labels(self, msg: "Message", lfor: tuple[set[str], set[str]] | None = None) -> dict | None:
        """A post's warnings and topics, and what to do with it: ``{"warnings":
        [{"warning", "by" (["author"], ["group"], labellers' names), "choice"}],
        "topics": [...], "action": "show"|"blur"|"hide"}``; None when there is
        nothing. Your own posts and your contacts' are always "show"."""
        warn_l, topic_l = lfor or self.labellers_for(msg.group)
        by: dict[str, list[str]] = {}
        for w in tg.warnings(msg.tags):
            by.setdefault(w, []).append("author")
        group_tags = self.manifest_data(msg.group).get("tags")
        for w in tg.warnings(group_tags if isinstance(group_tags, list) else ()):
            by.setdefault(w, []).append("group")
        topics: list[str] = []
        if warn_l or topic_l:
            for k, labels in self.label_book().labels(msg.message_id, warn_l | topic_l).items():
                name = self.labeller_label(k)
                for x in labels:
                    if lb.is_warning(x):
                        if k in warn_l and name not in by.get(x, []):
                            by.setdefault(x, []).append(name)
                    elif k in topic_l and x not in topics:
                        topics.append(x)
        if not by and not topics:
            return None
        choices = self.warning_choices()
        warnings = [{"warning": w, "by": by[w], "choice": choices[w]} for w in tg.WARNINGS if w in by]
        safe = msg.author_key in self._my_keys() or msg.author_key in self.data.get("contacts", {})
        order = {"show": 0, "blur": 1, "hide": 2}
        action = "show" if safe or not warnings else max((w["choice"] for w in warnings), key=order.get)
        return {"warnings": warnings, "topics": topics, "action": action}

    def mark_labelled(self, msgs: list["Message"]) -> list["Message"]:
        """Set ``Message.labels`` (``post_labels``) on posts, for clients to blur or hide."""
        per_group: dict[str, tuple[set[str], set[str]]] = {}
        for m in msgs:
            if m.private or not m.readable:
                m.labels = None
                continue
            if m.group not in per_group:
                per_group[m.group] = self.labellers_for(m.group)
            m.labels = self.post_labels(m, per_group[m.group])
        return msgs

    # --- being a labeller (sections 3, 4) ---
    def my_labels_group(self, name: str | None = None) -> str:
        """``labels@<fingerprint>`` of an identity (the one in use), started or not."""
        return lb.labels_group(self.identity(name).public_key)

    def is_labeller(self, name: str | None = None) -> bool:
        """Whether an identity (the one in use) has started its labels channel here."""
        return bool(self.data["groups"].get(self.my_labels_group(name), {}).get("owner"))

    async def start_labels(self, policy: str = "", contact: str = "", automatic: bool = False,
                           topics: bool = False) -> str:
        """Start, or change, this identity's ``labels@`` channel (section 3)."""
        extra = {k: v for k, v in (("policy", policy.strip() or None), ("contact", contact.strip() or None),
                                   ("automatic", True if automatic else None),
                                   ("topics", True if topics else None)) if v is not None}
        gid = self.my_labels_group()
        try:
            current = await self.fetch_manifest(gid)
        except (SessionError, OSError, ConnectionError, NNTPError):
            current = None
        serial = max(int(self.manifest_data(gid).get("serial", 0)),
                     current.serial if current else 0) + 1
        try:
            art = make_manifest(self.identity(), lb.GROUP_NAME, "channel", serial=serial,
                                title="Content labels", min_pow=_s.DEFAULT_POW,
                                extra=extra or None, pow_bits=await self.required_pow(gid),
                                lifetime=self.key_bound_lifetime())
        except ValueError as exc:
            raise SessionError(str(exc)) from exc
        await self._post_article(art)
        entry = self.group_entry(gid)
        entry["manifest"] = json.loads(art.body)
        entry.update({"type": "channel", "owner": True})
        self.save()
        return gid

    async def publish_labels(self, posts, note: str = "") -> str:
        """Publish labels: ``posts`` as (Message-ID, Group ID, [labels]); ``[]`` takes a
        labeller's earlier labels of that post back (section 4). Returns its Message-ID."""
        if not self.is_labeller():
            raise SessionError("start your labels channel first (start_labels)")
        try:
            body = lb.label_body(posts, note)
        except lb.LabelError as exc:
            raise SessionError(str(exc)) from exc
        me = self.identity()
        art = await self._post_with_postage(self.my_labels_group(), lambda bits: lb.label_article(
            me, body, from_name=self.display_name() or "Labeller", pow_bits=bits))
        self._label_book = None
        return art.message_id

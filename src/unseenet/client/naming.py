"""Names in the client: groups (UN-RFC 0018) and identities (UN-RFC 0019).

The client reads three kinds of data groups in the background, the way it
reads the node list (UN-RFC 0010): the project's root list of hierarchies,
the hierarchy lists of the maintainers, and the registrar's group of name
certificates. What it learns is kept in the vault, so names show offline
too; until it has read anything, the lists that ship with the client count.

Everything here is a function of a Session, so the TUI and the command line
use the same rules.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .. import hierarchies as hz
from .. import known_nodes as kn
from .. import names as nm
from ..core import crypto
from ..core.groups import short_group_id, split_group_id

if TYPE_CHECKING:
    from .session import Message, Session

RESEND = timedelta(days=7)            # UN-RFC 0019 section 5.2: once a week per group
MAX_SEEN_PER_KEY = 8


def _store(s: "Session") -> dict:
    st = s.data.setdefault("naming", {})
    for key, empty in (("lists", {}), ("names", {}), ("seen", {}), ("sent", {}), ("pending", []),
                       ("issued", []), ("my_revoked", []), ("issuer_revoked", {}),
                       ("requests_done", [])):
        st.setdefault(key, empty)
    return st


# --- reading the data groups -----------------------------------------------------------

async def _read(s: "Session", group_id: str, owner: str) -> list[tuple["Message", str]]:
    """The posts in a data group by its owner or posters, if ``owner`` owns it.

    Reads it without subscribing and without keeping it around; returns
    (message, author) pairs, or nothing if the owner is not the one expected.
    """
    from .session import SessionError
    subscribed = group_id in s.data["subscribed"]
    try:
        messages = await s.fetch_group(group_id)
    except SessionError:
        return []                                  # not on the node (yet)
    finally:
        if not subscribed:
            s.cache.pop(group_id, None)
            s._raw.pop(group_id, None)
            s._high.pop(group_id, None)
    manifest = s.manifest_data(group_id)
    if manifest.get("owner") != owner:
        return []
    allowed = {owner, *manifest.get("posters", [])}
    return [(m, m.author_key) for m in messages if m.readable and m.author_key in allowed]


def _newest(posts, parse):
    best = None
    for m, _ in posts:
        try:
            value = parse(m.body)
        except (ValueError, KeyError, TypeError):
            continue
        if best is None or (m.date and (best[0] is None or m.date > best[0])):
            best = (m.date, m.body, value)
    return best


async def read_root_list(s: "Session") -> dict[str, hz.Hierarchy] | None:
    """The newest root list the project has posted (UN-RFC 0018), or None if
    none could be read. Does not touch the vault; the registrar uses it."""
    best = _newest(await _read(s, hz.HIERARCHIES_GROUP, kn.PROJECT_KEY),
                   lambda body: hz.parse_root_list(body))
    return best[2][1] if best else None


async def refresh(s: "Session") -> bool:
    """Read the root list, the hierarchy lists the client needs, and the names.

    True if anything changed. A list that cannot be read keeps its last value.
    """
    st = _store(s)
    before = repr(st)
    posts = await _read(s, hz.HIERARCHIES_GROUP, kn.PROJECT_KEY)
    best = _newest(posts, lambda body: hz.parse_root_list(body))
    if best:
        st["root"] = best[1]
    root = root_list(s)
    for top in sorted({gid.split(".")[0].split("@")[0] for gid in _known(s)}):
        h = hz.policy_of(top, root)
        if h.policy != "governed":
            continue
        try:
            posts = await _read(s, h.list, h.maintainer)
        except Exception:  # noqa: BLE001  one list that cannot be read does not stop the rest
            continue
        best = _newest(posts, lambda body, n=h.name: hz.parse_hierarchy_list(body, n))
        if best:
            st["lists"][h.name] = best[1]
    # delegated sub-hierarchies above the groups we know: their endorsements and
    # blocks count too (sections 5.3, 5.4); at most the depth section 5.3 allows
    for _ in range(hz.MAX_DEPTH):
        lists = hierarchy_lists(s)
        wanted = {sub.name: sub for gid in _known(s)
                  for sub in hz.sub_lists_needed(gid.rpartition("@")[0] or gid, root, lists)}
        wanted = {n: h for n, h in wanted.items() if n not in st.setdefault("tried", [])}
        if not wanted:
            break
        for name, sub in sorted(wanted.items()):
            st["tried"].append(name)
            try:
                posts = await _read(s, sub.list, sub.maintainer)
            except Exception:  # noqa: BLE001
                continue
            best = _newest(posts, lambda body, n=name: hz.parse_hierarchy_list(body, n))
            if best:
                st["lists"][name] = best[1]
    st.pop("tried", None)
    await _read_names(s, st)
    take_certificates(s)
    issuers = sorted({c.issuer for c in _all_certs(s) if c.kind == "sub"})[:20]
    for issuer in issuers:                     # their revocation lists (section 6.6)
        try:
            posts = await _read(s, nm.revocation_group(issuer), issuer)
        except Exception:  # noqa: BLE001
            continue
        best = _newest(posts, nm.parse_revocations)
        if best:
            st["issuer_revoked"][issuer] = sorted([n, v] for n, v in best[2])
    try:
        await renew_given(s)
    except Exception:  # noqa: BLE001  renewal is retried at the next refresh
        pass
    try:
        await renew_held(s)                     # your own registered names (#424)
    except Exception:  # noqa: BLE001  likewise
        pass
    st["kept"] = nm.rfc3339(datetime.now(timezone.utc))
    changed = repr(st) != before
    if changed:
        s.save()
    return changed


KEEP_EVERY = timedelta(days=1)
KEEP_TIMEOUT = 120                              # seconds; a post is never held up longer


async def keep_my_names(s: "Session") -> None:
    """Your own names, for a program that never runs ``refresh`` - a bot, a gateway,
    the help bot (``Session.service``, set by ``Session.from_key``; a service with a
    vault sets it itself). At most once a day, from ``post``: make sure your inbox exists (a
    name under a name, like ``help@unseenet``, is sent there, section 5.4), take the
    certificates that came, read the registrar's group so they count, and renew your
    registered names. So a service shows its name with no code of its own.
    Clients that run ``refresh`` have done all this already and skip it. Never
    raises: what fails is tried again the next day."""
    import asyncio
    if not getattr(s, "service", False):
        return
    st = _store(s)
    last = st.get("kept")
    now = datetime.now(timezone.utc)
    if last and now - nm.parse_rfc3339(last) < KEEP_EVERY:
        return
    st["kept"] = nm.rfc3339(now)

    async def keep() -> None:
        await s.ensure_inbox()
        await s.fetch_group(s.my_inbox)
        take_certificates(s)
        await _read_names(s, st)
        await renew_held(s)

    try:
        await asyncio.wait_for(keep(), KEEP_TIMEOUT)
    except Exception:  # noqa: BLE001  names are a nicety; the post goes out regardless
        pass
    s.save()


async def _read_names(s: "Session", st: dict) -> None:
    posts = await _read(s, nm.NAMES_GROUP, kn.PROJECT_KEY)
    manifest = s.manifest_data(nm.NAMES_GROUP)
    if not manifest:
        return
    registrars = sorted({kn.PROJECT_KEY, *manifest.get("posters", [])})
    certs: dict[str, str] = {}
    newest: dict[str, tuple] = {}
    for m, author in posts:
        if m.subject.startswith("name "):
            try:
                cert = nm.parse_certificate(m.body)
            except nm.NameProblem:
                continue
            if cert.registrar in registrars:
                certs[cert.to_json()] = cert.to_json()
        elif m.subject == nm.REVOKED_SUBJECT:
            try:
                revoked = nm.parse_revocations(m.body)
            except (nm.NameProblem, ValueError):
                continue
            if author not in newest or (m.date and newest[author][0] and m.date > newest[author][0]):
                newest[author] = (m.date, revoked)
    revoked = set().union(*(r for _, r in newest.values())) if newest else set()
    st["names"] = {"registrars": registrars, "claims": manifest.get("claims"),
                   "certs": sorted(certs), "revoked": sorted([n, v] for n, v in revoked)}


def _known(s: "Session") -> set[str]:
    """Every Group ID this client knows of."""
    return set(s.data["groups"]) | set(s.data["subscribed"])


# --- groups (UN-RFC 0018 section 8.1) ------------------------------------------------------

def root_list(s: "Session") -> dict[str, hz.Hierarchy]:
    text = _store(s).get("root")
    if text:
        try:
            return hz.parse_root_list(text)[1]
        except ValueError:
            pass
    return hz.builtin_root_list()[1]


def governing(s: "Session", group_id: str) -> list[hz.Hierarchy]:
    """The governed hierarchies from the top down to the one deciding the group."""
    name = group_id.rpartition("@")[0] or group_id
    root, lists = root_list(s), hierarchy_lists(s)
    out = []
    h = hz.policy_of(name.split(".")[0], root)
    for _ in range(hz.MAX_DEPTH + 1):
        if h.policy != "governed":
            break
        out.append(h)
        lst = lists.get(h.name)
        deeper = [x for x in (lst.sub.values() if lst else []) if hz._within(name, x.name)]
        if not deeper:
            break
        h = max(deeper, key=lambda x: len(x.name))
    return out


async def block(s: "Session", group_id: str, key_text: str, reason: str,
                hierarchy: str | None = None) -> str:
    """As a maintainer: add a block to your hierarchy list and post it (section 5.4).
    Returns the hierarchy blocked in."""
    import json
    from datetime import datetime, timezone
    from .session import SessionError
    crypto.key_from_text(key_text)
    if not 1 <= len(reason.strip()) <= hz.MAX_BLOCK_REASON:
        raise SessionError(f"a block needs a reason of 1 to {hz.MAX_BLOCK_REASON} characters")
    me = s.identity().key_text
    mine = [h for h in governing(s, group_id) if h.maintainer == me]
    if hierarchy:
        mine = [h for h in mine if h.name == hierarchy]
    if not mine:
        raise SessionError("you are not the maintainer of a hierarchy above this group")
    h = mine[0]                                   # the widest one you maintain
    text = _store(s)["lists"].get(h.name)
    data = json.loads(text) if text else {"v": 1, "hierarchy": h.name, "groups": []}
    data["blocked"] = [b for b in data.get("blocked", []) if b.get("key") != key_text] + [
        {"key": key_text, "reason": reason.strip(),
         "since": datetime.now(timezone.utc).isoformat(timespec="seconds")}]
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    body = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    hz.parse_hierarchy_list(body, h.name)          # never post a list with mistakes
    await s.fetch_group(h.list)
    await s.post(h.list, f"Groups of {h.name}, {data['updated']} (block)", body,
                 content_type="application/json")
    _store(s)["lists"][h.name] = body
    s.save()
    return h.name


def blocks(s: "Session", group_id: str) -> dict[str, tuple[str, str]]:
    """{key: (hierarchy, reason)} blocked by maintainers for this group (section 5.4)."""
    name = group_id.rpartition("@")[0] or group_id
    return hz.blocks_for(name, root_list(s), hierarchy_lists(s))


def hierarchy_lists(s: "Session") -> dict[str, hz.HierarchyList]:
    lists = {"unseenet": hz.builtin_checkgroups()}
    for name, text in _store(s)["lists"].items():
        try:
            lists[name] = hz.parse_hierarchy_list(text, name)
        except ValueError:
            continue
    return lists


def group_status(s: "Session", group_id: str, also_known: set[str] = frozenset()) -> hz.GroupName:
    return hz.name_status(group_id, root_list(s), hierarchy_lists(s), _known(s) | set(also_known))


def group_label(s: "Session", group_id: str, also_known: set[str] = frozenset()) -> str:
    """``unseenet.announce`` where the name is unambiguous, else ``name@abcd``."""
    try:
        status = group_status(s, group_id, also_known)
    except ValueError:
        return group_id
    if status.short:
        return split_group_id(group_id)[0]
    return short_group_id(group_id)


def group_warning(s: "Session", group_id: str, also_known: set[str] = frozenset()) -> str | None:
    """What to tell someone about to follow this group, if anything."""
    try:
        status = group_status(s, group_id, also_known)
    except ValueError:
        return None
    name = split_group_id(group_id)[0]
    if status.status == "endorsed":
        return f"Endorsed by the maintainer of {status.hierarchy}.*."
    if status.status == "unendorsed":
        return (f"The maintainer of {status.hierarchy}.* does not vouch for this {name} "
                "(or their list has not been read yet). It could be anyone's.")
    if status.status == "reserved":
        return f"{status.hierarchy}.* is reserved: nobody vouches for groups in it."
    if status.status == "free" and not status.short:
        return f"There is more than one group called {name}; check its fingerprint."
    return None


# --- identities (UN-RFC 0019 section 8) ------------------------------------------------------

def _registrars(s: "Session") -> set[str]:
    return set(_store(s)["names"].get("registrars", []))


def _revoked(s: "Session") -> set[tuple[str, int]]:
    return {(n, v) for n, v in _store(s)["names"].get("revoked", [])}


def _all_certs(s: "Session") -> list[nm.Certificate]:
    st = _store(s)
    texts = set(st["names"].get("certs", []))
    for seen in st["seen"].values():
        texts.update(seen)
    out = []
    for text in texts:
        try:
            out.append(nm.parse_certificate(text))
        except nm.NameProblem:
            continue
    return out


def _registrar_names(s: "Session", certs: list[nm.Certificate], key_text: str,
                     now: datetime) -> list[nm.Certificate]:
    registrars, revoked = _registrars(s), _revoked(s)
    accepted = [c for c in certs if c.kind != "sub" and c.registrar in registrars
                and c.valid_at(now) and (c.name, c.serial) not in revoked]
    out = []
    for name in sorted({c.name for c in accepted if c.key == key_text}):
        cur, disputed = nm.current([c for c in accepted if c.name == name])
        if cur is not None and not disputed and cur.key == key_text:
            out.append(cur)
    return out


def _holder(s: "Session", certs: list[nm.Certificate], name: str, now: datetime) -> str | None:
    """Who holds a registered or domain name now, per the registrar's certificates."""
    registrars, revoked = _registrars(s), _revoked(s)
    accepted = [c for c in certs if c.kind != "sub" and c.name == name
                and c.registrar in registrars and c.valid_at(now)
                and (c.name, c.serial) not in revoked]
    cur, disputed = nm.current(accepted)
    return cur.key if cur is not None and not disputed else None


def _sub_names(s: "Session", certs: list[nm.Certificate], key_text: str,
               now: datetime) -> list[nm.Certificate]:
    """Accepted names under a name (section 5.4): signed by whoever holds the parent
    now, valid now, not revoked by that issuer, and not overruled by DNS (6.4)."""
    out = []
    issuer_revoked = _store(s)["issuer_revoked"]
    for name in sorted({c.name for c in certs if c.kind == "sub" and c.key == key_text}):
        local, parent = nm.split_sub(name)
        holder = _holder(s, certs, parent, now)
        if holder is None:
            continue
        valid = [c for c in certs if c.kind == "sub" and c.name == name and c.issuer == holder
                 and c.valid_at(now)
                 and [c.name, c.serial] not in issuer_revoked.get(holder, [])]
        if not valid:
            continue
        best = max(valid, key=lambda c: c.serial)          # the issuer's newest decision
        dns = _holder(s, certs, name, now) if "." in parent else None
        if best.key == key_text and dns in (None, key_text):
            out.append(best)
    return out


def _rank(c: nm.Certificate) -> tuple:
    """Section 8.1: domain names (also person@domain from DNS), names under a
    name, registered names."""
    return ({"domain": 0, "sub": 1}.get(c.kind, 2), c.name)


def names_of(s: "Session", key_text: str, now: datetime | None = None) -> list[nm.Certificate]:
    """The names that belong to a key now: accepted certificates that count (5.3, 5.4)."""
    now = now or datetime.now(timezone.utc)
    certs = _all_certs(s)
    out = _registrar_names(s, certs, key_text, now) + _sub_names(s, certs, key_text, now)
    return sorted(out, key=_rank)


def name_text(name: str) -> str:
    """``@lorensen``, ``@lorensen.dk``, but ``sonia@lorensen`` and ``andlo@lorensen.dk``."""
    return name if "@" in name else "@" + name


def preferred(s: "Session", key_text: str, names: list[nm.Certificate]) -> nm.Certificate:
    """The name an identity shows: your own choice for yourself; for others the one
    they sent most recently (they choose), else the first by section 8.1."""
    if not names:
        raise ValueError("no names")
    by_name = {c.name: c for c in names}
    if key_text == s.identity().key_text:
        chosen = _store(s).get("primary")
        if chosen in by_name:
            return by_name[chosen]
        return names[0]
    for text in reversed(_store(s)["seen"].get(key_text, [])):
        try:
            name = nm.parse_certificate(text).name
        except nm.NameProblem:
            continue
        if name in by_name:
            return by_name[name]
    return names[0]


def identity_label(s: "Session", key_text: str, from_name: str = "") -> str:
    """Petname, else ``@domain``, else ``@name``, else ``Name~abcd`` (section 8.1)."""
    petname = s.contact_name(key_text)
    if petname:
        return f"{petname} √"
    names = names_of(s, key_text)
    if names:
        return name_text(preferred(s, key_text, names).name)
    try:
        fp = crypto.fingerprint(crypto.key_from_text(key_text))[:4]
    except crypto.CryptoError:
        fp = "????"
    shown = (from_name or "").lstrip("@").strip() or "?"   # never looks like a certified name
    return f"{shown}~{fp}"


def note_certificate(s: "Session", author_key: str, header_value: str | None) -> None:
    """Remember a certificate an author sent with an article (section 5.2).

    Whether it counts is decided when it is shown, against the registrar's
    keys and revocations as they are then.
    """
    if not header_value:
        return
    try:
        cert = nm.certificate_from_header(header_value)
    except nm.NameProblem:
        return
    if cert.key != author_key:
        return
    seen = _store(s)["seen"].setdefault(author_key, [])
    text = cert.to_json()
    if text in seen:                  # the most recent one last: it is the name they show now
        seen.remove(text)
    seen.append(text)
    del seen[:-MAX_SEEN_PER_KEY]


# --- your own names ---------------------------------------------------------------------------

PENDING_FOR = timedelta(days=3)


def pending(s: "Session") -> list[list[str]]:
    """Claims sent in the last few days: (name, action, when sent)."""
    now = datetime.now(timezone.utc)
    return [p for p in _store(s)["pending"] if now - nm.parse_rfc3339(p[2]) < PENDING_FOR]


def my_names(s: "Session") -> list[nm.Certificate]:
    return names_of(s, s.identity().key_text)


def header_for(s: "Session", group_id: str, now: datetime | None = None) -> tuple[str, str] | None:
    """The Name-Certificate header to send with a post here, or None (section 5.2).

    Only in groups everyone can read (never in closed groups or inboxes, where
    a name would link you), and once a week per group.
    """
    entry = s.data["groups"].get(group_id, {})
    if entry.get("type") in ("closed", "inbox"):
        return None
    names = my_names(s)
    if not names:
        return None
    now = now or datetime.now(timezone.utc)
    last = _store(s)["sent"].get(group_id)
    if last and now - nm.parse_rfc3339(last) < RESEND:
        return None
    return nm.HEADER, preferred(s, s.identity().key_text, names).header_value()


def set_primary(s: "Session", name: str) -> None:
    """Choose which of your names your posts show (they carry its certificate)."""
    if name not in {c.name for c in my_names(s)}:
        from .session import SessionError
        raise SessionError(f"{name} is not one of your names")
    _store(s)["primary"] = name
    _store(s)["sent"] = {}                   # send the new one with the next post everywhere
    s.save()


# --- names under your name (section 5.4) -----------------------------------------------

REQUEST_TYPE = "application/x-unseenet-name-request"
CERT_TYPE = "application/x-unseenet-name-certificate"
RENEW_BEFORE = timedelta(days=30)


def parents_i_hold(s: "Session") -> list[str]:
    """Your registered and domain names: you can give names under these."""
    return [c.name for c in my_names(s) if c.kind != "sub" and "@" not in c.name]


def holder_of(s: "Session", name: str) -> str | None:
    return _holder(s, _all_certs(s), name, datetime.now(timezone.utc))


def key_for_name(s: "Session", name: str) -> str | None:
    """The key a name belongs to now, as this client knows (section 8.3): a registered
    or domain name, a name given in DNS, or a name under a name. None if unknown."""
    now = datetime.now(timezone.utc)
    certs = _all_certs(s)
    key = _holder(s, certs, name, now)
    if key or "@" not in name:
        return key
    for c in certs:                       # a name under a name: _sub_names decides
        if c.kind == "sub" and c.name == name and any(
                x.name == name for x in _sub_names(s, certs, c.key, now)):
            return c.key
    return None


async def request_subname(s: "Session", name: str) -> str:
    """Ask the holder of the parent for ``local@parent`` (section 5.4)."""
    from .session import SessionError
    from ..core.groups import personal_inbox_id
    body = nm.make_subname_request(name, s.identity().key_text)
    parent = nm.split_sub(name)[1]
    holder = holder_of(s, parent)
    if holder is None:
        raise SessionError(f"nobody holds @{parent} as far as this client knows")
    await s.ensure_inbox()
    msgid = await s.send_private(personal_inbox_id(crypto.key_from_text(holder)),
                                 f"May I be {name}?", body,
                                 owner_key=crypto.key_from_text(holder), content_type=REQUEST_TYPE)
    st = _store(s)
    st["pending"] = [p for p in st["pending"] if p[0] != name][-20:] + [
        [name, "ask", nm.rfc3339(datetime.now(timezone.utc))]]
    s.save()
    return msgid


def name_requests(s: "Session") -> list[tuple["Message", dict]]:
    """Requests in your inbox for names under the names you hold."""
    done = set(_store(s)["requests_done"])
    mine = set(parents_i_hold(s))
    out = []
    for m in s.private_messages():
        if not m.content_type.startswith(REQUEST_TYPE) or m.message_id in done:
            continue
        try:
            data = nm.parse_subname_request(m.body)
        except nm.NameProblem:
            continue
        if nm.split_sub(data["name"])[1] in mine:
            out.append((m, data))
    return out


async def has_inbox(s: "Session", key_text: str) -> bool:
    """True if the key's personal inbox is on the node: a name given to a key without
    one cannot be delivered yet (a service makes its inbox when it first posts)."""
    from ..core.groups import personal_inbox_id
    from ..nntp import NNTPError
    gid = personal_inbox_id(crypto.key_from_text(key_text))

    async def exists(c) -> bool:
        try:
            await c.group(gid)
            return True
        except NNTPError:
            return False
    return await s._call(exists, s.node_for(gid))


async def give_subname(s: "Session", name: str, key_text: str,
                       lifetime: timedelta = nm.SUB_LIFETIME_DEFAULT) -> nm.Certificate:
    """As the holder of the parent: issue ``name`` to a key and send it to them."""
    from .session import SessionError
    from ..core.groups import personal_inbox_id
    parent = nm.split_sub(name)[1]
    if parent not in parents_i_hold(s):
        raise SessionError(f"you do not hold @{parent}")
    st = _store(s)
    serial = 1 + max((nm.parse_certificate(t).serial for t in st["issued"]
                      if nm.parse_certificate(t).name == name), default=0)
    cert = nm.make_subname(s.identity(), name, key_text, serial, lifetime)
    if key_text == s.identity().key_text:
        note_certificate(s, key_text, cert.header_value())
    else:
        try:
            await s.send_private(personal_inbox_id(crypto.key_from_text(key_text)),
                                 f"You are {name}", cert.to_json() + "\n",
                                 owner_key=crypto.key_from_text(key_text),
                                 content_type=CERT_TYPE, remember=False)
        except SessionError:
            pass                    # they get it with the next renewal; the certificate stands
    st["issued"].append(cert.to_json())         # after sending: then it is on its way
    s.save()
    return cert


async def answer_request(s: "Session", msg: "Message", data: dict, approve: bool,
                         lifetime: timedelta = nm.SUB_LIFETIME_DEFAULT) -> None:
    if approve:
        await give_subname(s, data["name"], data["key"], lifetime)
    _store(s)["requests_done"].append(msg.message_id)
    del _store(s)["requests_done"][:-500]
    s.save()


def names_given(s: "Session") -> list[nm.Certificate]:
    """The newest certificate for each name you gave, not revoked."""
    st = _store(s)
    newest: dict[str, nm.Certificate] = {}
    for text in st["issued"]:
        try:
            c = nm.parse_certificate(text)
        except nm.NameProblem:
            continue
        if c.name not in newest or c.serial > newest[c.name].serial:
            newest[c.name] = c
    return [c for n, c in sorted(newest.items()) if [c.name, c.serial] not in st["my_revoked"]]


async def revoke_subname(s: "Session", name: str) -> None:
    """Take back a name you gave: publish it in your revocation list (section 6.6)."""
    import json
    st = _store(s)
    for c in names_given(s):
        if c.name == name:
            st["my_revoked"].append([c.name, c.serial])
    gid = nm.revocation_group(s.identity().key_text)
    if gid not in s.data["groups"]:
        try:
            created = await s.create_group("names", "channel", view="data",
                                           title="Revoked names")
        except Exception:  # noqa: BLE001  it may exist on the node already
            created = gid
        if created != gid:
            from .session import SessionError
            raise SessionError("could not make your revocation group")
    revoked = {(n, v) for n, v in st["my_revoked"]}
    await s.post(gid, nm.REVOKED_SUBJECT, nm.make_revocations(revoked), content_type="text/plain; charset=utf-8")
    s.save()


def take_certificates(s: "Session") -> bool:
    """Keep the name certificates others sent you (section 5.4). True if any is new."""
    me = s.identity().key_text
    seen = _store(s)["seen"].setdefault(me, [])
    new = False
    for m in s.private_messages():
        if not m.content_type.startswith(CERT_TYPE):
            continue
        try:
            cert = nm.parse_certificate(m.body.strip())
        except nm.NameProblem:
            continue
        if cert.key == me and cert.to_json() not in seen:
            seen.append(cert.to_json())
            new = True
    del seen[:-MAX_SEEN_PER_KEY * 4]
    return new


async def renew_given(s: "Session") -> int:
    """Give a fresh certificate for names you gave that run out within 30 days,
    while the parent is still yours. Returns how many."""
    now = datetime.now(timezone.utc)
    mine = set(parents_i_hold(s))
    n = 0
    for c in names_given(s):
        if c.expires - now < RENEW_BEFORE and nm.split_sub(c.name)[1] in mine:
            await give_subname(s, c.name, c.key, c.expires - c.issued)
            n += 1
    return n


async def renew_held(s: "Session") -> list[str]:
    """Renew your registered names that run out within 30 days (``RENEW_BEFORE``), by
    themselves, as key-bound groups are (#424) - so nobody loses ``@lorensen``, and every
    name under it, by forgetting. A ``renew`` claim to the registrar (UN-RFC 0019 section
    6.3) at most once per name per run, and none while one sent is still on its way.
    Domain names need nothing: the registrar renews them while their DNS record is
    there. Returns the names a claim was sent for."""
    now = datetime.now(timezone.utc)
    tried = s.__dict__.setdefault("_renew_tried", set())
    waiting = {p[0] for p in pending(s) if p[1] == "renew"}
    sent = []
    for c in my_names(s):
        if (c.kind != "registered" or c.expires - now >= RENEW_BEFORE or c.name in tried
                or c.name in waiting):
            continue
        tried.add(c.name)
        await claim(s, c.name, "renew")
        sent.append(c.name)
    return sent


def sent_header(s: "Session", group_id: str, now: datetime | None = None) -> None:
    _store(s)["sent"][group_id] = nm.rfc3339(now or datetime.now(timezone.utc))


async def claim(s: "Session", name: str, action: str = "claim", to: str | None = None) -> str:
    """Send a claim (or renew, transfer, release) to the registrar (section 6.1).

    The answer comes to your inbox; the certificate also appears in the
    registrar's group, which ``refresh`` reads.
    """
    body = nm.make_claim(action, name, to)
    st = _store(s)
    if not st["names"].get("claims"):
        await _read_names(s, st)
    claims = st["names"].get("claims")
    if not claims:
        from .session import SessionError
        raise SessionError("the registrar is not set up yet: its group names no claim inbox")
    await s.ensure_inbox()                         # the answer comes there
    msgid = await s.send_private(claims, f"{action} {name}", body, content_type="application/json")
    st["pending"] = [p for p in st["pending"] if p[0] != name][-20:] + [
        [name, action, nm.rfc3339(datetime.now(timezone.utc))]]
    s.save()
    return msgid

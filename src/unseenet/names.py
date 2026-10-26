"""Names for identities (UN-RFC 0019): syntax, certificates, claims, revocations.

Shared by the registrar, the client and the project's tools, so that all of
them read and write exactly the same formats.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .core import crypto
from .core.encoding import b64, b64decode
from .core.groups import canonical_json, parse_canonical_json

NAMES_GROUP = "unseenet.names@ph5fc5hop5232qsz"      # the project's registrar (section 7.2)
PURPOSE_NAME_CERT = "UNSEENET-NAME-CERT-1"            # section 10
PURPOSE_SUBNAME_CERT = "UNSEENET-SUBNAME-CERT-1"      # section 5.4
SUB_LIFETIME_MAX = timedelta(days=5 * 365 + 1)        # section 5.4
SUB_LIFETIME_DEFAULT = timedelta(days=365)
HEADER = "Name-Certificate"                           # section 5.2
KINDS = ("registered", "domain")
LIFETIME = {"registered": timedelta(days=365), "domain": timedelta(days=35)}   # section 5.1
GRACE = timedelta(days=30)                            # section 6.3
ACTIONS = ("claim", "renew", "transfer", "release")   # section 6.1
CLAIM_POW = 24                                        # section 6.2
MAX_NAMES_PER_KEY = 3                                 # section 6.2
DNS_PREFIX = "_unseenet"                              # section 6.4

# Section 9, and the names UN-RFC 0018 section 9 reserves. They are the project's.
# Other hierarchies in the root list are not copied here: the registrar reads the
# root list and gives their names to their maintainers (section 4.1 item 3).
RESERVED = frozenset({
    "admin", "abuse", "help", "info", "node", "nodes", "operator", "postmaster", "registrar",
    "root", "security", "support", "system", "unseenet", "usenet",
    "control", "junk", "local", "inbox", "all", "example", "invalid",
})

_REGISTERED = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_LOCAL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")       # section 4.4


class NameProblem(ValueError):
    """A name, certificate or claim that is not valid (the reason is the message)."""


# --- syntax (section 4) -------------------------------------------------------

def kind_of(name: str) -> str:
    """Section 4.3: 'domain' if the name has a dot (also ``local@domain``, given
    through DNS), 'sub' for ``local@registered``, else 'registered'."""
    if "@" in name:
        return "domain" if "." in name.split("@", 1)[1] else "sub"
    return "domain" if "." in name else "registered"


def split_sub(name: str) -> tuple[str, str]:
    """``sonia@lorensen`` -> ("sonia", "lorensen")."""
    local, _, parent = name.partition("@")
    return local, parent


def check_local(local: str) -> None:
    if not _LOCAL.match(local) or "--" in local:
        raise NameProblem("the part before @ is 1 to 32 of a-z, 0-9 and -, "
                          "does not start or end with - and has no --")


def check_registered(name: str) -> None:
    if not _REGISTERED.match(name) or "--" in name:
        raise NameProblem("a name is 3 to 32 of a-z, 0-9 and -, starts with a letter, "
                          "does not end with - and has no --")


def check_domain(name: str) -> None:
    labels = name.split(".")
    if (len(name) > 253 or len(labels) < 2 or name.endswith(".")
            or not all(_LABEL.match(label) for label in labels)):
        raise NameProblem("not a lowercase domain name like example.org")


def check_name(name: str) -> str:
    """Raise NameProblem unless the name is valid for its kind; return the kind."""
    kind = kind_of(name)
    if "@" in name:
        local, parent = split_sub(name)
        check_local(local)
        (check_domain if "." in parent else check_registered)(parent)
        return kind
    (check_domain if kind == "domain" else check_registered)(name)
    return kind


def dns_record_name(domain: str) -> str:
    """``_unseenet.lorensen.dk``; for a person under a domain (section 6.4),
    ``andlo._unseenet.lorensen.dk``."""
    if "@" in domain:
        local, parent = split_sub(domain)
        return f"{local}.{DNS_PREFIX}.{parent}"
    return f"{DNS_PREFIX}.{domain}"


def tld_record_name(tld: str) -> str:
    """``_unseenet.nic.microsoft``: where a registry proves a registered name equal
    to its top-level domain (section 4.5)."""
    return dns_record_name(f"nic.{tld}")


def dns_record_value(key_text: str) -> str:
    return f"unseenet-key={key_text}"


# --- time ----------------------------------------------------------------------

def rfc3339(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_rfc3339(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# --- certificates (section 5) ---------------------------------------------------

@dataclass(frozen=True)
class Certificate:
    name: str
    kind: str
    key: str
    issued: datetime
    expires: datetime
    serial: int
    registrar: str
    claim: str | None = None            # Message-ID of the claim (section 6.8)
    claimed: datetime | None = None     # the claim's Date
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def decision(self) -> tuple:
        """What replicas agree on; certificates from different keys with the same
        decision are one decision, not a conflict (section 5.3)."""
        return (self.name, self.key, self.serial)

    def to_json(self) -> str:
        return canonical_json(self.raw)

    def header_value(self) -> str:
        return b64(self.to_json().encode())

    def valid_at(self, when: datetime) -> bool:
        return self.issued <= when < self.expires

    @property
    def parent(self) -> str:
        """For a sub-name certificate: the name it is under."""
        return self.raw.get("parent", "")

    @property
    def issuer(self) -> str:
        """Who signed it: the registrar, or for a sub-name the parent's holder."""
        return self.registrar


def make_certificate(registrar: crypto.Identity, name: str, key_text: str, serial: int,
                     now: datetime | None = None, *, claim: str | None = None,
                     claimed: datetime | None = None) -> Certificate:
    """A signed certificate. For a claim (section 6.8), pass its Message-ID and Date:
    ``issued`` is then the claim's Date, so every replica makes the same one."""
    kind = check_name(name)
    crypto.key_from_text(key_text)
    if claim is not None and claimed is None:
        raise NameProblem("a certificate for a claim needs the claim's Date")
    issued = (claimed or now or datetime.now(timezone.utc)).replace(microsecond=0)
    data = {"v": 1, "name": name, "kind": kind, "key": key_text, "issued": rfc3339(issued),
            "expires": rfc3339(issued + LIFETIME[kind]), "serial": serial,
            "registrar": registrar.key_text}
    if claim is not None:
        data["claim"], data["claimed"] = claim, rfc3339(claimed)
    data["sig"] = registrar.sign_text(PURPOSE_NAME_CERT, canonical_json(data).encode())
    return parse_certificate(canonical_json(data))


def parse_certificate(text: str) -> Certificate:
    """Parse and check the signature (section 5.3 steps 1 and 6, and the signature in 3).

    Whether the registrar is trusted, the dates, the author and revocation are
    the caller's to check (``accept``).
    """
    try:
        data = parse_canonical_json(text if text.endswith("\n") else text + "\n")
    except ValueError as exc:
        raise NameProblem("certificate is not canonical JSON") from exc
    if data.get("kind") == "sub":
        return _parse_sub(data)
    try:
        if data.get("v") != 1 or data["kind"] not in KINDS:
            raise NameProblem("not a version 1 certificate")
        if check_name(data["name"]) != data["kind"]:
            raise NameProblem("the name does not match its kind")
        unsigned = {k: v for k, v in data.items() if k != "sig"}
        registrar = crypto.key_from_text(data["registrar"])
        crypto.key_from_text(data["key"])
        if not crypto.verify(registrar, PURPOSE_NAME_CERT, canonical_json(unsigned).encode(),
                             crypto.sig_from_text(data["sig"])):
            raise NameProblem("the registrar's signature does not verify")
        claim, claimed = data.get("claim"), data.get("claimed")
        if (claim is None) != (claimed is None) or (claim is not None and not isinstance(claim, str)):
            raise NameProblem("claim and claimed go together")
        cert = Certificate(data["name"], data["kind"], data["key"], parse_rfc3339(data["issued"]),
                           parse_rfc3339(data["expires"]), int(data["serial"]), data["registrar"],
                           claim, parse_rfc3339(claimed) if claimed else None, data)
    except (KeyError, TypeError, ValueError, crypto.CryptoError) as exc:
        if isinstance(exc, NameProblem):
            raise
        raise NameProblem(f"bad certificate: {exc}") from exc
    if cert.expires - cert.issued > LIFETIME[cert.kind] or cert.serial < 1:
        raise NameProblem("certificate lifetime or serial out of range")
    return cert


# --- names under a name (section 5.4) ------------------------------------------------

def make_subname(issuer: crypto.Identity, name: str, key_text: str, serial: int,
                 lifetime: timedelta = SUB_LIFETIME_DEFAULT,
                 now: datetime | None = None) -> Certificate:
    """A sub-name certificate, ``sonia@lorensen``, signed by the holder of ``lorensen``."""
    if "@" not in name:
        raise NameProblem("a name under a name looks like sonia@lorensen")
    check_name(name)
    crypto.key_from_text(key_text)
    if not timedelta(days=1) <= lifetime <= SUB_LIFETIME_MAX:
        raise NameProblem("a name under a name lasts from a day to five years")
    issued = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    data = {"v": 1, "name": name, "kind": "sub", "parent": split_sub(name)[1], "key": key_text,
            "issued": rfc3339(issued), "expires": rfc3339(issued + lifetime), "serial": serial,
            "registrar": issuer.key_text}
    data["sig"] = issuer.sign_text(PURPOSE_SUBNAME_CERT, canonical_json(data).encode())
    return parse_certificate(canonical_json(data))


def _parse_sub(data: dict) -> Certificate:
    try:
        if data.get("v") != 1 or "@" not in data["name"]:
            raise NameProblem("not a version 1 sub-name certificate")
        check_name(data["name"])
        if split_sub(data["name"])[1] != data["parent"]:
            raise NameProblem("the name is not under its parent")
        unsigned = {k: v for k, v in data.items() if k != "sig"}
        issuer = crypto.key_from_text(data["registrar"])
        crypto.key_from_text(data["key"])
        if not crypto.verify(issuer, PURPOSE_SUBNAME_CERT, canonical_json(unsigned).encode(),
                             crypto.sig_from_text(data["sig"])):
            raise NameProblem("the issuer's signature does not verify")
        cert = Certificate(data["name"], "sub", data["key"], parse_rfc3339(data["issued"]),
                           parse_rfc3339(data["expires"]), int(data["serial"]), data["registrar"],
                           None, None, data)
    except (KeyError, TypeError, ValueError, crypto.CryptoError) as exc:
        if isinstance(exc, NameProblem):
            raise
        raise NameProblem(f"bad sub-name certificate: {exc}") from exc
    if cert.expires - cert.issued > SUB_LIFETIME_MAX or cert.serial < 1:
        raise NameProblem("sub-name lifetime or serial out of range")
    return cert


def revocation_group(issuer_key: str) -> str:
    """Where an issuer of sub-names publishes its revocation list (section 6.6)."""
    return f"names@{crypto.fingerprint(crypto.key_from_text(issuer_key))}"


def make_subname_request(name: str, key_text: str) -> str:
    check_name(name)
    if "@" not in name:
        raise NameProblem("ask for a name under a name, like sonia@lorensen")
    crypto.key_from_text(key_text)
    return canonical_json({"v": 1, "name": name, "key": key_text}) + "\n"


def parse_subname_request(body: str) -> dict:
    try:
        data = parse_canonical_json(body if body.endswith("\n") else body + "\n")
    except ValueError as exc:
        raise NameProblem("the request is not canonical JSON") from exc
    if data.get("v") != 1 or not isinstance(data.get("name"), str) or "@" not in data["name"]:
        raise NameProblem("not a version 1 name request")
    check_name(data["name"])
    try:
        crypto.key_from_text(data.get("key", ""))
    except crypto.CryptoError as exc:
        raise NameProblem("the request names no valid key") from exc
    return data


def certificate_from_header(value: str) -> Certificate:
    try:
        text = b64decode(value.strip()).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise NameProblem("Name-Certificate is not base64 of JSON") from exc
    return parse_certificate(text)


def accept(cert: Certificate, *, author_key: str, registrars: set[str],
           revoked: set[tuple[str, int]] = frozenset(), now: datetime | None = None) -> bool:
    """Section 5.3: may this certificate name the author of an article?"""
    now = now or datetime.now(timezone.utc)
    return (cert.key == author_key and cert.registrar in registrars and cert.valid_at(now)
            and (cert.name, cert.serial) not in revoked)


def current(certs: list[Certificate]) -> tuple[Certificate | None, bool]:
    """Of the accepted certificates for one name: (the one that counts, disputed?).

    Section 5.3: the highest serial counts. Among different keys with that
    serial, the earlier claim (``claimed``, then ``claim``) wins. Certificates
    from several registrar keys for one decision agree and do not conflict.
    Only if the claims cannot decide is the name disputed.
    """
    if not certs:
        return None, False
    top = max(c.serial for c in certs)
    best = [c for c in certs if c.serial == top]
    keys = {c.key for c in best}
    if len(keys) == 1:
        return best[0], False
    if any(c.claim is None for c in best):
        return None, True
    first = min(best, key=lambda c: (c.claimed, c.claim))
    rivals = [c for c in best if c.key != first.key]
    if any((c.claimed, c.claim) == (first.claimed, first.claim) for c in rivals):
        return None, True                    # one claim, two keys: a registrar lied
    return first, False


def keys_for(certs: list[Certificate], decision: tuple) -> set[str]:
    """The registrar keys that signed one decision (for "at least two keys", 5.3)."""
    return {c.registrar for c in certs if c.decision == decision}


# --- claims (section 6.1) ---------------------------------------------------------

def make_claim(action: str, name: str, to: str | None = None) -> str:
    if action not in ACTIONS:
        raise NameProblem(f"unknown action {action!r}")
    check_name(name)
    data = {"v": 1, "action": action, "name": name}
    if action == "transfer":
        if not to:
            raise NameProblem("a transfer names the new key")
        crypto.key_from_text(to)
        data["to"] = to
    return canonical_json(data) + "\n"


def parse_claim(body: str) -> dict:
    try:
        data = parse_canonical_json(body if body.endswith("\n") else body + "\n")
    except ValueError as exc:
        raise NameProblem("the claim is not canonical JSON") from exc
    if data.get("v") != 1 or data.get("action") not in ACTIONS or not isinstance(data.get("name"), str):
        raise NameProblem("not a version 1 claim")
    check_name(data["name"])
    if data["action"] == "transfer":
        try:
            crypto.key_from_text(data.get("to", ""))
        except crypto.CryptoError as exc:
            raise NameProblem("a transfer needs a valid new key") from exc
    return data


# --- the revocation list (section 6.6) -----------------------------------------------

def make_revocations(revoked: set[tuple[str, int]]) -> str:
    items = [{"name": n, "serial": s} for n, s in sorted(revoked)]
    return canonical_json({"v": 1, "revoked": items}) + "\n"


def parse_revocations(body: str) -> set[tuple[str, int]]:
    data = parse_canonical_json(body if body.endswith("\n") else body + "\n")
    if data.get("v") != 1 or not isinstance(data.get("revoked"), list):
        raise NameProblem("not a version 1 revocation list")
    return {(str(i["name"]), int(i["serial"])) for i in data["revoked"]
            if isinstance(i, dict) and "name" in i and "serial" in i}


# --- articles in the registrar's group (section 7.1) -----------------------------------

def certificate_subject(name: str) -> str:
    return f"name {name}"


REVOKED_SUBJECT = "revoked"

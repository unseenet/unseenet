"""Groups: manifests, new groups, removing and dropping groups (UN-RFC 0004, 0013, 0021).

Belongs here: taking a new manifest (``_accept_manifest``: type, owner and locality
never change, key-bound expiry, sites only when the operator carries them), which new
groups the node takes (``new_groups``), profile and avatar groups (UN-RFC 0022 section
10), an owner removing a group (``rmgroup``) and the operator dropping one, and the
groups the node leaves out (``excludes``).

Part of ``Node`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class Manifests:
    def _accept_rmgroup(self, art: Article, manifest: Manifest | None, raw: bytes,
                        source: str | None, from_peer: bool) -> Article:
        """UN-RFC 0013: the owner removes the group from the network."""
        author = art.author_key
        if manifest is not None:
            if author != manifest.owner:
                raise ArticleError("permission", "only the group's owner can remove it")
            if manifest.local and from_peer:
                raise ArticleError("group", "local group: never accepted from peers")
        elif crypto.fingerprint(author) != split_group_id(art.group)[1]:
            raise ArticleError("permission", "only the group's owner can remove it")
        if art.proven_pow() < self.config.min_pow:          # exempt from the group's own minimum
            raise ArticleError("postage", f"need {self.config.min_pow} bits")
        local = manifest is not None and manifest.local
        self.store.remember(art.message_id)
        self.store.add_tombstone(art.group, "owner", art.message_id, raw)
        deleted = self.store.remove_group(art.group)
        if not local:
            self._enqueue(art, source, force=True)
        log.info("group %s removed by its owner (%d articles deleted)", art.group, deleted)
        return art

    def drop_group(self, group_id: str) -> int:
        """UN-RFC 0013 section 3: the operator stops carrying a group on this node."""
        self.store.add_tombstone(group_id, "operator")
        return self.store.remove_group(group_id)

    def _accept_manifest(self, art: Article, current: Manifest | None, raw: bytes,
                         from_peer: bool = False) -> None:
        m = Manifest.from_article(art)
        if m.local and from_peer:
            raise ArticleError("group", "local group: never accepted from peers")
        if current is not None:
            if m.type != current.type or m.owner != current.owner or m.local != current.local:
                raise ArticleError("permission", "manifest may not change type, owner or locality")
        elif (not self.store.known_group(art.group) and not self._is_profile_group(art.group)
              and self._group_name(art.group) != "state" and not self._allow_new_group(m)):
            # profile and avatar groups are accepted whatever new_groups says (UN-RFC 0022, 10)
            # an expired key-bound group is not new: its renewal is accepted (UN-RFC 0029)
            raise ArticleError("group", "node does not accept this new group")
        if m.expired():
            raise ArticleError("group", "key-bound group has expired")
        if m.type == "state" and current is not None:            # UN-RFC 0044 section 7.1
            old = self.store.get(current.message_id)
            if old is not None and (parse_date(art["Date"]) - parse_date(Article.from_bytes(old)["Date"])
                                    < timedelta(hours=1)):
                raise ArticleError("rate", "too soon: a state at most once an hour (UN-RFC 0044 7.1)")
        if m.view == "pages" and self.config.sites != "accept":     # UN-RFC 0035 section 6.2
            raise ArticleError("group", "this node carries no sites")
        self._check_profile_content(m)
        self._check_ripe_manifest(m, current)
        self.store.add(art, raw)
        if m.supersedes(current):
            self.store.set_manifest(m)

    @staticmethod
    def _group_name(group_id: str) -> str:
        try:
            return split_group_id(group_id)[0]
        except ValueError:
            return ""

    def _is_profile_group(self, group_id: str) -> bool:
        """Groups every key may have, accepted whatever new_groups says: profiles,
        pictures (UN-RFC 0022 section 10) and ripening (UN-RFC 0025 section 3.3)."""
        return self._group_name(group_id) in (profiles.PROFILE_NAME, profiles.AVATAR_NAME,
                                              rp.GROUP_NAME)

    def _check_profile_group(self, group_id: str) -> None:
        """UN-RFC 0022 section 10: the operator decides whether profiles and pictures
        are carried; pictures only when turned on."""
        name = self._group_name(group_id)
        if name == profiles.PROFILE_NAME and self.config.profiles != "accept":
            raise ArticleError("group", "this node does not carry profiles")
        if name == profiles.AVATAR_NAME and self.config.avatars != "accept":
            raise ArticleError("group", "this node does not carry pictures")

    def _check_profile_content(self, m: Manifest) -> None:
        """A profile or picture manifest must hold a valid one (sections 4, 8.1)."""
        own = {profiles.PROFILE_NAME: "profile", profiles.AVATAR_NAME: "avatar"}.get(m.name)
        try:
            for field_ in ("profile", "avatar"):
                if field_ in m.raw and field_ != own:
                    raise profiles.ProfileError(f"{field_} belongs in a {field_}@ group")
            if own == "profile" and "profile" in m.raw:
                profiles.check_profile(m.raw["profile"])
            if own == "avatar" and "avatar" in m.raw:
                profiles.check_picture(m.raw["avatar"])
        except profiles.ProfileError as exc:
            raise ArticleError("syntax", str(exc)) from exc

    def _allow_new_group(self, m: Manifest) -> bool:
        if self.config.new_groups == "accept":
            return True
        if self.config.new_groups == "trusted":
            return crypto.key_to_text(m.owner) in self.config.trusted_owners
        return False  # "manual": operator adds groups out of band

    def excludes(self) -> str:
        """UN-RFC 0021 section 3: `excludes` from node.toml, plus every dropped group."""
        parts = [p for p in self.config.excludes.split(",") if p]
        parts += [g for g in self.store.dropped_groups() if g not in parts]
        return ",".join(parts)

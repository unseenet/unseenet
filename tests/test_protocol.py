"""Protocol tests: articles, postage, groups, closed-group crypto, vault."""

import pytest

from unseenet.core import crypto
from unseenet.core.article import Article, ArticleError, new_article, validate_structure
from unseenet.core.groups import (Manifest, approve, check_permitted, decrypt_article,
                                  encrypted_article, make_group_id, make_key_update,
                                  make_manifest, open_envelope, parse_key_update)
from unseenet.core.pow import leading_zero_bits
from unseenet.core.vault import VaultError, seal, unseal

BITS = 8


def post(group, author, subject="Hej", body="Det virker!\n"):
    return new_article(group, subject, body, from_name="Andreas").finalize(author, BITS)


def test_sign_roundtrip_and_message_id():
    me = crypto.Identity.generate()
    art = post("dk.snak@" + me.fingerprint, me)
    raw = art.to_bytes()
    again = Article.from_bytes(raw)
    validate_structure(again, raw_size=len(raw))
    assert again.message_id == art.message_id
    assert again.proven_pow() >= BITS


def test_tampering_is_detected():
    me = crypto.Identity.generate()
    art = post("dk.snak@" + me.fingerprint, me)
    raw = art.to_bytes().replace(b"Det virker!", b"Det virker?")
    with pytest.raises(ArticleError) as exc:
        validate_structure(Article.from_bytes(raw), raw_size=len(raw))
    assert exc.value.reason == "signature"


def test_forbidden_and_duplicate_headers():
    me = crypto.Identity.generate()
    raw = post("a@" + me.fingerprint, me).to_bytes()
    with pytest.raises(ArticleError):
        a = Article.from_bytes(b"Path: x\r\n" + raw)
        validate_structure(a, raw_size=len(raw))
    with pytest.raises(ArticleError):
        Article.from_bytes(b"Subject: x\r\n" + raw)


def test_canonical_form_ignores_header_order():
    me = crypto.Identity.generate()
    art = post("a@" + me.fingerprint, me)
    shuffled = Article(list(reversed(art.headers)), art.body)
    assert shuffled.canonical() == art.canonical()
    assert shuffled.compute_message_id() == art.message_id


def test_pow_bits():
    assert leading_zero_bits(b"\x00\x0f") == 12
    assert leading_zero_bits(b"\x80") == 0


def test_manifest_and_owner_check():
    owner = crypto.Identity.generate()
    art = make_manifest(owner, "dk.snak", "open", title="Snak", pow_bits=BITS)
    m = Manifest.from_article(art)
    assert m.group_id == make_group_id("dk.snak", owner.public_key)
    # Someone else cannot publish a manifest for the owner's group ID
    thief = crypto.Identity.generate()
    forged = new_article(m.group_id, None, art.body,
                         extra=[("Control", "manifest"), ("Content-Type", "application/json")])
    forged.finalize(thief, BITS)
    with pytest.raises(ArticleError):
        Manifest.from_article(forged)


def test_channel_and_moderated_rules():
    owner, mod, user = (crypto.Identity.generate() for _ in range(3))
    chan = Manifest.from_article(make_manifest(owner, "news", "channel", pow_bits=BITS))
    with pytest.raises(ArticleError):
        check_permitted(post(chan.group_id, user), chan, {})
    check_permitted(post(chan.group_id, owner), chan, {})

    modg = Manifest.from_article(make_manifest(owner, "mod", "moderated",
                                               moderators=[mod.key_text], pow_bits=BITS))
    art = post(modg.group_id, user)
    with pytest.raises(ArticleError):
        check_permitted(art, modg, {})
    msgid = art.message_id
    approve(art, mod)
    assert art.compute_message_id() == msgid  # approval does not change the ID
    check_permitted(art, modg, {})


def test_closed_group_end_to_end():
    owner, member, outsider = (crypto.Identity.generate() for _ in range(3))
    gid = make_group_id("hemmelig", owner.public_key)
    keys = crypto.GroupKeys.generate()
    upd = make_key_update(owner, gid, 1, keys, [member.public_key], pow_bits=BITS)
    epoch, member_key, _ = parse_key_update(upd)
    assert member_key == keys.member.public_key

    got = open_envelope(upd, member)
    assert got and got[1].secret == keys.secret
    assert open_envelope(upd, outsider) is None

    manifest = Manifest.from_article(make_manifest(owner, "hemmelig", "closed", pow_bits=BITS))
    art = encrypted_article(gid, 1, got[1], member, from_name="Sonia", subject="Tegning",
                            body="Hemmelig hilsen\n", pow_bits=BITS)
    assert "From" not in art and b"Hemmelig" not in art.to_bytes()
    check_permitted(art, manifest, {1: member_key})
    inner = decrypt_article(art, keys)
    assert inner["Subject"] == "Tegning" and inner.body == "Hemmelig hilsen\n"

    # An outsider with a guessed key cannot post
    fake = encrypted_article(gid, 1, crypto.GroupKeys.generate(), outsider,
                             from_name="x", subject="spam", body="spam", pow_bits=BITS)
    with pytest.raises(ArticleError):
        check_permitted(fake, manifest, {1: member_key})


def test_vault_roundtrip():
    blob = seal(b"secret", "pw", ops=1, mem=8192 * 1024)
    assert unseal(blob, "pw") == b"secret"
    with pytest.raises(VaultError):
        unseal(blob, "wrong")

"""#609, UN-RFC 0049 section 7.3: Origin-Proof - a post brought to a new key from an
Unseenet export, proven to be the old key's only when the proof holds."""

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session
from unseenet.core import crypto, origins
from unseenet.core.article import Article, new_article
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


def _old_article(old, gid="alt.snak@x", body="Mit gamle indlæg\n"):
    return new_article(gid, "Gammelt", body, from_name="Old").finalize(old, 8)


def test_the_proof_holds_only_as_signed():
    old, new = crypto.Identity.generate(), crypto.Identity.generate()
    art = _old_article(old)
    raw = art.to_bytes()
    hdrs = origins.origin_headers("unseenet", art.get("Date") and origins.parse_date_header(art.get("Date")),
                                  art.message_id, proof=raw)
    imported = new_article("alt.ny@y", "Gammelt", art.body, from_name="New", extra=hdrs).finalize(new, 8)
    assert origins.check_proof(imported) == old.key_text
    assert len(imported.get("Origin-Proof")) < 4000                  # the headers, not the body
    changed = new_article("alt.ny@y", "Gammelt", "Ændret tekst\n", from_name="New", extra=hdrs).finalize(new, 8)
    assert origins.check_proof(changed) is None                       # the text was changed
    wrong = [(n, "2020-01-01T00:00:00Z" if n == "Origin-Date" else v) for n, v in hdrs]
    assert origins.check_proof(new_article("alt.ny@y", "Gammelt", art.body, from_name="New",
                                           extra=wrong).finalize(new, 8)) is None
    other = [(n, "<nope@x>" if n == "Origin-ID" else v) for n, v in hdrs]
    assert origins.check_proof(new_article("alt.ny@y", "Gammelt", art.body, from_name="New",
                                           extra=other).finalize(new, 8)) is None
    with pytest.raises(origins.OriginError):
        origins.origin_headers("unseenet", proof=b"x" * (origins.PROOF_MAX + 1) + b"\r\n\r\nbody")


async def test_posted_and_read(tmp_path, monkeypatch, fast_ripening):
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=6, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    me = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    me.new_identity("me", "Me"); me.add_node(addr)
    old = crypto.Identity.generate()
    try:
        gid = await me.create_group("alt.snak", "open", min_pow=8)
        art = _old_article(old, body="Fra min gamle nøgle\n")
        when = origins.parse_date_header(art.get("Date"))
        proven = await me.post(gid, "Gammelt", art.body, origin={
            "network": "unseenet", "date": when, "id": art.message_id, "proof": art.to_bytes()})
        plain = await me.post(gid, "Uden bevis", "x\n", origin={"network": "unseenet", "date": when})
        by = {m.message_id: m for m in await me.fetch_group(gid)}
        assert by[proven].origin_proven == old.key_text
        assert by[proven].to_dict()["origin"]["proven"] == old.key_text
        assert by[plain].origin_proven == "" and by[plain].to_dict()["origin"]["proven"] is None
    finally:
        await me.close()
        server.close()

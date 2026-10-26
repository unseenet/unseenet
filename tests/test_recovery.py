"""#573: recovery words (UN-RFC 0050 section 4) - the encoding, showing them behind the
passphrase, the weekly reminder, restoring an identity and reading its state back, the
closed groups that do not come back, the local API (UN-RFC 0046 4.18) and the CLI."""
import io
import json
import os
from argparse import Namespace
from datetime import timedelta

import pytest

from unseenet import cli
from unseenet.client.session import Session, SessionError
from unseenet.core import crypto
from unseenet.core import recovery as rc
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


# --- the encoding (section 4.1) ---------------------------------------------------

def test_the_bip39_test_vectors_for_256_bits():
    """The BIP39 vectors (trezor/python-mnemonic) for 32 octets of entropy."""
    assert rc.words_from_seed(bytes(32)) == ["abandon"] * 23 + ["art"]
    assert rc.words_from_seed(b"\x7f" * 32) == (
        "legal winner thank year wave sausage worth useful legal winner thank year wave "
        "sausage worth useful legal winner thank year wave sausage worth title").split()
    assert rc.words_from_seed(b"\x80" * 32) == (
        "letter advice cage absurd amount doctor acoustic avoid letter advice cage absurd "
        "amount doctor acoustic avoid letter advice cage absurd amount doctor acoustic "
        "bless").split()
    assert rc.words_from_seed(b"\xff" * 32) == ["zoo"] * 23 + ["vote"]


def test_any_seed_comes_back_from_its_words_however_typed():
    for _ in range(50):
        seed = os.urandom(32)
        words = rc.words_from_seed(seed)
        assert rc.seed_from_words(" ".join(words)) == seed
        typed = "\n".join(f"{i}. {w[:4].upper()}" for i, w in enumerate(words, 1)) + "  \n"
        assert rc.seed_from_words(typed) == seed                     # four letters, numbered
        assert rc.normalised(typed) == words


def test_mistakes_are_said_plainly():
    words = rc.words_from_seed(os.urandom(32))
    with pytest.raises(rc.RecoveryError) as e:
        rc.seed_from_words(words[:23])
    assert e.value.kind == "count" and "23" in str(e.value)
    bad = words[:]
    bad[6] = "unseenetword"
    with pytest.raises(rc.RecoveryError) as e:
        rc.seed_from_words(bad)
    assert e.value.kind == "word" and e.value.position == 7
    swapped = words[:]
    i = next(i for i in range(23) if words[i] != words[i + 1])
    swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
    try:                                    # the 8-bit checksum misses 1 in 256 swaps
        rc.seed_from_words(swapped)
    except rc.RecoveryError as exc:
        assert exc.kind == "checksum" and "mistyped" in str(exc)
    with pytest.raises(rc.RecoveryError):
        rc.words_from_seed(bytes(31))


def test_the_page_says_what_matters():
    words = rc.words_from_seed(bytes(32))
    page = rc.text_page("Andreas", "abcdabcdabcdabcd", words)
    assert " 1. abandon" in page and "24. art" in page and "abcdabcdabcdabcd" in page
    assert "Closed groups do NOT come back" in page and "not a cryptocurrency wallet" in page
    assert len(rc.check_positions()) == 3 and all(1 <= p <= 24 for p in rc.check_positions())


# --- the session ---------------------------------------------------------------------

def _session(tmp_path, name="me.vault"):
    s = Session(Vault.open(tmp_path / name, "pw", **KDF), status=lambda *_: None)
    return s


def test_words_need_the_passphrase_and_the_reminder_is_weekly(tmp_path):
    s = _session(tmp_path)
    ident = s.new_identity("andreas", "Andreas")
    with pytest.raises(SessionError, match="not right"):
        s.recovery_words("wrong")
    assert rc.seed_from_words(s.recovery_words("pw")) == ident.seed
    assert s.words_reminder_due() and not s.words_written()
    s.note_words_reminded()
    assert not s.words_reminder_due()
    assert s.words_reminder_due(now=__import__("time").time() + 8 * 86400)
    s.note_words_written()
    assert s.words_written() and not s.words_reminder_due(now=__import__("time").time() + 99 * 86400)
    assert "words" not in json.dumps(s.data["identities"]["andreas"]).replace("words_", "")


def test_restoring_into_a_vault(tmp_path):
    a = _session(tmp_path, "a.vault")
    ident = a.new_identity("andreas", "Andreas")
    words = a.recovery_words("pw")
    b = _session(tmp_path, "b.vault")
    b.new_identity("other", "Other")
    with pytest.raises(SessionError, match="not a recovery word"):
        b.restore_identity(" ".join(words[:23] + ["xyzzy"]))
    name, got, new = b.restore_identity(" ".join(words), display="Andreas")
    assert new and got.seed == ident.seed and name.startswith("restored-")
    assert b.default_identity_name() == name and b.display_name() == "Andreas"
    assert b.words_written(name)                                  # they were just typed
    assert b.restore_identity(words) == (name, got, False)        # again: nothing new
    c = _session(tmp_path, "c.vault")
    c.new_identity("andreas", "Someone else")
    with pytest.raises(SessionError, match="another key"):
        c.restore_identity(words, name="andreas")


# --- two devices and a node (section 4.4, 4.5) -----------------------------------------

@pytest.fixture
async def network(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    monkeypatch.setattr(Node, "STATE_EVERY", timedelta(0))
    import unseenet.client.session as sess
    import unseenet.client.session.state as sstate
    monkeypatch.setattr(sstate, "WRITE_EVERY", 0.0)
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    addr = "127.0.0.1:%d" % server.sockets[0].getsockname()[1]
    made = []

    def device(name, display=None):
        s = _session(tmp_path, f"{name}.vault")
        if display:
            s.new_identity(name, display)
        s.add_node(addr)
        made.append(s)
        return s
    yield addr, device
    for s in made:
        await s.close()
    server.close()


async def test_restore_reads_the_state_and_lists_closed_groups(network):
    addr, device = network
    owner = device("sonia", "Sonia")
    await owner.ensure_inbox()
    family = await owner.create_group("familie", "closed", min_pow=8)
    stick = device("stick", "Andreas")
    stick.subscribe("dk.snak@abcdabcdabcdabcd")
    stick.subscribe(family)
    assert await stick.sync_state() == "written"
    words = stick.recovery_words("pw")

    phone = device("phone")                        # a new device, nothing on it but a node
    name, ident, new = phone.restore_identity(words, display="Andreas")
    found = await phone.restore_from_network(name)
    assert found["state"] == "read" and found["fingerprint"] == ident.fingerprint
    assert set(phone.data["subscribed"]) >= {"dk.snak@abcdabcdabcdabcd", family}
    assert [g["group"] for g in found["closed_groups"]] == [family]
    assert found["closed_groups"][0]["owner"] == owner.identity().key_text
    assert not phone.data["groups"][family].get("keys")       # the secret did not come back

    await phone.ask_to_be_invited(family)
    msgs = await owner.fetch_group(owner.my_inbox)
    assert any("Invite me again" in (m.subject or "") for m in msgs)

    nobody = device("empty")
    nobody.restore_identity(rc.words_from_seed(os.urandom(32)))
    assert (await nobody.restore_from_network())["state"] == "none"


# --- the local API (UN-RFC 0046 section 4.18) -----------------------------------------

async def test_the_local_api(network):
    from unseenet.client.localapi import LocalAPI
    addr, device = network
    stick = device("stick", "Andreas")
    stick.subscribe("dk.snak@abcdabcdabcdabcd")
    await stick.sync_state()
    api = LocalAPI(session=stick)
    assert api.state()["identity"]["words_reminder"] is True
    with pytest.raises(SessionError):
        await api.recovery_words("wrong")
    shown = await api.recovery_words("pw")
    assert len(shown["words"]) == 24 and len(shown["check"]) == 3
    assert "Closed groups" in shown["note"] and shown["words"][0] in shown["page"]
    api.recovery_written()
    assert api.state()["identity"]["words_written"] is True
    assert api.state()["identity"]["words_reminder"] is False

    assert api.recovery_check(" ".join(shown["words"]))["ok"]
    bad = api.recovery_check("abandon " * 24)
    assert not bad["ok"] and bad["kind"] == "checksum"

    tmp = stick.vault.path.parent
    new = LocalAPI(tmp / "new.vault", refresh_seconds=3600)
    await new.unlock("pw")
    assert new.needs_setup()
    with pytest.raises(SessionError, match="node"):
        await new.recovery_restore(" ".join(shown["words"]))
    got = await new.recovery_restore(" ".join(shown["words"]), display="Andreas", node=addr)
    assert got["new"] and got["state"] == "read" and not new.needs_setup()
    assert "dk.snak@abcdabcdabcdabcd" in new.session.data["subscribed"]
    assert (await new.recovery_closed_groups())["groups"] == []
    await new.close()


# --- the command line -----------------------------------------------------------------

async def test_the_cli(tmp_path, monkeypatch, capsys):
    app = cli.App(Vault.open(tmp_path / "v.vault", "pw", **KDF))
    app.passphrase = "pw"
    await cli.c_id_new(app, Namespace(name="andreas", display="Andreas", json=True))
    capsys.readouterr()
    await cli.c_id_words(app, Namespace(name=None, written=True, yes=True, json=True, identity=None))
    shown = json.loads(capsys.readouterr().out)
    assert len(shown["words"]) == 24 and shown["written"]
    monkeypatch.setattr(cli.basics.getpass, "getpass", lambda prompt="": "wrong")
    with pytest.raises(SystemExit, match="not right"):
        await cli.c_id_words(app, Namespace(name=None, written=False, yes=False, json=True,
                                            identity=None))

    other = cli.App(Vault.open(tmp_path / "w.vault", "pw", **KDF))
    monkeypatch.setattr("sys.stdin", io.StringIO(" ".join(shown["words"]) + "\n"))
    await cli.c_id_restore(other, Namespace(name="me", display="Andreas", offline=True,
                                            json=True, identity=None))
    out = json.loads(capsys.readouterr().out)
    assert out["new"] and out["key"] == app.identity().key_text
    assert other.identity("me").seed == app.identity().seed
    monkeypatch.setattr("sys.stdin", io.StringIO("abandon " * 24 + "\n"))
    with pytest.raises(SystemExit, match="mistyped"):
        await cli.c_id_restore(other, Namespace(name="x", display=None, offline=True,
                                                json=True, identity=None))


def test_the_word_list_is_in_the_package():
    assert len(rc.wordlist()) == 2048 and rc.wordlist()[0] == "abandon"
    assert crypto.Identity.from_seed(rc.seed_from_words(["abandon"] * 23 + ["art"])).seed == bytes(32)

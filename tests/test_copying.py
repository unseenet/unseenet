"""#572: copying identities to another device (UN-RFC 0050 section 3) - the node's
meeting point, the protocol, and two sessions copying through a real node (the one-time
onion service replaced by localhost)."""
import asyncio
import time

import pytest

from unseenet.client.session import Session, SessionError
from unseenet.core import copying as cp
from unseenet.core import crypto
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.nntp import Client
from unseenet.node.server import Node, NodeConfig
from unseenet.node.server import meet_commands as mc

KDF = {"ops": 1, "mem": 8192 * 1024}
ONION = "a" * 56 + ".onion"
TAG = "0" * 32


async def _node():
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    return node, server, "127.0.0.1:%d" % server.sockets[0].getsockname()[1]


# --- the meeting point (section 3.3) ---------------------------------------------------

async def test_the_meeting_point():
    node, server, addr = await _node()
    c = await Client.connect(addr)
    await c.fetch_capabilities()
    assert c.capability("XUNMEET") is not None
    code, text = await c.command(f"XUNMEET OPEN {ONION} {TAG}")
    assert code == 290 and 1 <= int(text) <= 999
    n = int(text)
    assert (await c.command(f"XUNMEET LOOKUP {n} {'1' * 32}"))[0] == 490    # wrong tag
    assert (await c.command(f"XUNMEET LOOKUP {n} {TAG}")) == (291, ONION)
    assert (await c.command(f"XUNMEET LOOKUP {n} {TAG}"))[0] == 490          # fetched once
    for bad in ("XUNMEET", "XUNMEET OPEN x.onion " + TAG, f"XUNMEET OPEN {ONION} xyz",
                f"XUNMEET LOOKUP x {TAG}"):
        assert (await c.command(bad))[0] == 501
    await c.quit()

    c = await Client.connect(addr)                      # three wrong tags: the record is gone
    n = int((await c.command(f"XUNMEET OPEN {ONION} {TAG}"))[1])
    for _ in range(3):
        assert (await c.command(f"XUNMEET LOOKUP {n} {'f' * 32}"))[0] == 490
    assert n not in node.meetings
    for _ in range(4):
        await c.command(f"XUNMEET OPEN {ONION} {TAG}")
    assert (await c.command(f"XUNMEET OPEN {ONION} {TAG}"))[0] == 436      # 5 per connection
    await c.quit()
    for m in node.meetings.values():                    # 10 minutes, then gone
        m["until"] = time.monotonic() - 1
    c = await Client.connect(addr)
    some = next(iter(node.meetings))
    assert (await c.command(f"XUNMEET LOOKUP {some} {TAG}"))[0] == 490 and not node.meetings
    await c.quit()
    server.close()


# --- the protocol ----------------------------------------------------------------------

def test_codes_and_qr_texts():
    assert cp.parse_code(" 7 Guitar  TUNN ") == (7, "guitar", "tunnel")
    assert cp.normal_code("7-guit-tunn") == "7-guitar-tunnel"
    for bad in ("guitar-tunnel", "0-guitar-tunnel", "1000-guitar-tunnel", "7-guitar-xyzzy"):
        with pytest.raises(cp.CopyError):
            cp.parse_code(bad)
    qr = cp.qr_text(ONION, "7-guitar-tunnel")
    assert cp.parse_qr(qr) == (ONION, "7-guitar-tunnel")
    with pytest.raises(cp.CopyError):
        cp.parse_qr("unseenet-copy:1:nope.onion:7-guitar-tunnel")
    assert cp.tag("guitar", "tunnel") != cp.tag("tunnel", "guitar") and len(cp.tag("a", "b")) == 32


def test_both_sides_agree_and_a_wrong_code_is_caught():
    old, new = cp.Exchange(cp.OLD, "7-guitar-tunnel"), cp.Exchange(cp.NEW, "7-GUITAR-tunn")
    old.finish(new.message)
    new.finish(old.message)
    old.check_confirmation(new.confirmation())
    new.check_confirmation(old.confirmation())
    assert old.check_words == new.check_words and old.copy_key == new.copy_key
    assert new.open(old.seal({"x": 1})) == {"x": 1}
    thief = cp.Exchange(cp.NEW, "7-guitar-table")
    victim = cp.Exchange(cp.OLD, "7-guitar-tunnel")
    victim.finish(thief.message)
    thief.finish(victim.message)
    with pytest.raises(cp.CopyError, match="code was not right"):
        victim.check_confirmation(thief.confirmation())


def test_what_is_copied_and_how_it_joins_a_vault():
    a, b = crypto.Identity.generate(), crypto.Identity.generate()
    data = {"identities": {"andreas": {"seed": a.seed.hex(), "display": "Andreas"},
                           "anon": {"seed": b.seed.hex(), "display": "Anon"}},
            "default_identity": "anon",
            "groups": {"familie@x": {"type": "closed", "keys": {"1": "11" * 32}},
                       "dk.snak@x": {"type": "open", "keys": {}}}}
    p = cp.build_payload(data, ["andreas"])
    assert list(p["identities"]) == ["andreas"] and p["default"] == "andreas"
    assert p["groups"] == {"familie@x": {"keys": {"1": "11" * 32}}}
    assert cp.build_payload(data, group_secrets=False)["groups"] == {}
    with pytest.raises(cp.CopyError):
        cp.build_payload(data, ["nobody"])

    phone = {"identities": {"andreas": {"seed": crypto.Identity.generate().seed.hex(),
                                        "display": "Other"}},
             "default_identity": "andreas",
             "groups": {"familie@x": {"type": "closed", "keys": {"2": "22" * 32}}}}
    assert cp.merge_payload(phone, cp.build_payload(data)) == ["andreas-2", "anon"]
    assert phone["identities"]["andreas"]["display"] == "Other"          # not overwritten
    assert phone["default_identity"] == "andreas"
    assert phone["groups"]["familie@x"]["keys"] == {"2": "22" * 32, "1": "11" * 32}
    assert cp.merge_payload(phone, cp.build_payload(data)) == []          # again: nothing new
    with pytest.raises(cp.CopyError):
        cp.check_payload({"v": 1, "identities": {"x": {"seed": "00"}}, "default": "x"})


# --- two devices -----------------------------------------------------------------------

@pytest.fixture
async def devices(tmp_path, monkeypatch):
    node, server, addr = await _node()
    listeners: dict[str, int] = {}
    made = []

    async def fake_onion(self, port):
        h = crypto.H(str(port).encode())
        onion = crypto.b32(h + h).lower()[:56] + ".onion"
        listeners[onion] = port

        async def remove():
            listeners.pop(onion, None)
        return onion, remove

    async def fake_open(self, onion):
        if onion not in listeners:
            raise SessionError("The other device could not be reached")
        return await asyncio.open_connection("127.0.0.1", listeners[onion])

    monkeypatch.setattr(Session, "_copy_onion", fake_onion)
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    import unseenet.client.session as sess
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    monkeypatch.setattr(Session, "_copy_open", fake_open)

    def device(name, display=None):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        if display:
            s.new_identity(name, display)
        made.append(s)
        return s
    yield addr, device, listeners
    for s in made:
        await s.close()
    server.close()


async def test_a_copy_with_the_typed_code(devices):
    addr, device, listeners = devices
    stick = device("andreas", "Andreas")
    stick.data["groups"]["familie@x"] = {"type": "closed", "owner": False, "keys": {"1": "ab" * 32}}
    phone = device("phone")
    offer = await stick.start_copy(meeting_nodes=[addr])
    assert offer.state == "waiting" and offer.code.startswith(f"{offer.n}-")
    assert offer.qr == f"unseenet-copy:1:{offer.onion}:{offer.code}"

    got = await phone.receive_copy(offer.code.upper(), meeting_nodes=[addr])
    assert await offer.wait_for_check(5) == got.check_words
    receiving = asyncio.ensure_future(got.finish())
    result = await offer.confirm(True)
    assert result["state"] == "done" and result["added"] == ["andreas"]
    assert await receiving == ["andreas"]
    assert phone.identity().seed == stick.identity().seed and phone.display_name() == "Andreas"
    assert phone.data["groups"]["familie@x"]["keys"] == {"1": "ab" * 32}
    assert Vault.open(phone.vault.path, "pw", **KDF).data["identities"]["andreas"]
    assert offer.onion not in listeners                       # the onion service is gone

    with pytest.raises(SessionError, match="No device is waiting"):     # the code is used up
        await phone.receive_copy(offer.code, meeting_nodes=[addr])


async def test_a_copy_with_the_qr_code_and_no_group_secrets(devices):
    addr, device, _ = devices
    stick = device("andreas", "Andreas")
    stick.new_identity("anon", "Anon")
    stick.data["groups"]["familie@x"] = {"type": "closed", "owner": False, "keys": {"1": "ab" * 32}}
    phone = device("phone", "Phone")
    offer = await stick.start_copy(["anon"], group_secrets=False, meeting_nodes=[addr])
    got = await phone.receive_copy(offer.qr)                  # no meeting point needed
    await offer.wait_for_check(5)
    receiving = asyncio.ensure_future(got.finish())
    assert (await offer.confirm(True))["added"] == ["anon"]
    assert await receiving == ["anon"]
    assert set(phone.data["identities"]) == {"phone", "anon"}
    assert phone.default_identity_name() == "phone"           # its own default stays
    assert "familie@x" not in phone.data["groups"]


async def test_words_that_do_not_match_send_nothing(devices):
    addr, device, _ = devices
    stick, phone = device("andreas", "Andreas"), device("phone")
    offer = await stick.start_copy(meeting_nodes=[addr])
    got = await phone.receive_copy(offer.qr)
    await offer.wait_for_check(5)
    receiving = asyncio.ensure_future(got.finish())
    result = await offer.confirm(False)
    assert result["state"] == "cancelled" and "nothing was sent" in result["error"]
    with pytest.raises(SessionError, match="stopped the copy"):
        await receiving
    assert not phone.has_identity()


async def test_a_wrong_code_uses_it_up(devices):
    addr, device, listeners = devices
    stick, phone = device("andreas", "Andreas"), device("phone")
    offer = await stick.start_copy(meeting_nodes=[addr])
    wrong = cp.qr_text(offer.onion, f"{offer.n}-{offer.word1}-{'zoo' if offer.word2 != 'zoo' else 'abandon'}")
    with pytest.raises(SessionError, match="code was not right|closed the connection"):
        await phone.receive_copy(wrong)
    for _ in range(50):
        if offer.state == "failed":
            break
        await asyncio.sleep(0.02)
    assert offer.state == "failed" and offer.onion not in listeners
    with pytest.raises(SessionError):
        await offer.confirm(True)


async def test_cancel_and_expiry(devices):
    addr, device, listeners = devices
    stick = device("andreas", "Andreas")
    offer = await stick.start_copy(meeting_nodes=[addr])
    await offer.cancel()
    assert offer.state == "cancelled" and offer.onion not in listeners
    offer = await stick.start_copy(meeting_nodes=[addr])
    offer.expires = time.time() - 1
    offer._timer.cancel()
    await offer._expire()
    assert offer.state == "expired" and "10 minutes" in offer.error
    assert await offer.wait_for_check(1) is None


async def test_no_meeting_point(devices, monkeypatch):
    addr, device, _ = devices
    stick = device("andreas", "Andreas")
    with pytest.raises(SessionError, match="meeting point"):
        await stick.start_copy(meeting_nodes=["127.0.0.1:1"])


# --- the local API (UN-RFC 0046 section 4.19) and the command line ----------------------

async def test_the_local_api_with_a_new_vault(devices, monkeypatch):
    from unseenet.client.localapi import LocalAPI
    addr, device, _ = devices
    stick = device("andreas", "Andreas")
    stick.add_node(addr)
    monkeypatch.setattr(Session, "meeting_candidates", lambda self, given=None: [addr])
    old = LocalAPI(session=stick)
    events = old.listen()
    offered = await old.copy_offer()
    assert offered["state"] == "waiting" and offered["code"] and old.copy_state()["role"] == "old"

    new = LocalAPI(stick.vault.path.parent / "new.vault", refresh_seconds=3600)
    await new.unlock("pw")
    with pytest.raises(SessionError, match="node"):
        await new.copy_receive(offered["qr"])
    got = await new.copy_receive(offered["qr"], node=addr)
    check = await asyncio.wait_for(events.get(), 5)
    while check.get("event") != "copy":
        check = await asyncio.wait_for(events.get(), 5)
    assert check["state"] == "check" and check["check_words"] == got["check_words"]
    finishing = asyncio.ensure_future(new.copy_finish())
    assert (await old.copy_confirm(True))["state"] == "done"
    done = await finishing
    assert done["added"] == ["andreas"] and not new.needs_setup()
    assert new.session.identity().seed == stick.identity().seed
    assert old.copy_state()["role"] is None or old.copy_state()["state"] == "done"
    await new.close()


def test_the_cli_commands_are_there(capsys):
    from unseenet import cli
    for cmd, word in (("copy-to", "check words"), ("copy-from", "QR code")):
        with pytest.raises(SystemExit):
            cli.client_main([cmd, "--help"])
        assert word in capsys.readouterr().out

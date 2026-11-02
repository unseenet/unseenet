"""The gateway directory (UN-RFC 0038 section 6)."""

import json
from datetime import datetime, timedelta, timezone

from unseenet.core import crypto
from unseenet.core.article import new_article
from unseenet.core.gateways import DIRECTORY_GROUP, active_groups, current
from unseenet.known_nodes import DATA_GROUPS

GW1, GW2 = crypto.Identity.generate(), crypto.Identity.generate()
NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def ann(who, name="gw", days_ago=0, groups=("matrix.x.a@aaaaaaaaaaaaaaaa",), **over):
    body = {"v": 1, "name": name, "operator": who.key_text, "contact": "inbox@abc",
            "networks": [{"network": "matrix", "account": "@gw:x", "import": True,
                          "export": True}], "groups": list(groups)}
    body.update(over)
    art = new_article(DIRECTORY_GROUP, f"Gateway: {name}", json.dumps(body) + "\n",
                      extra=[("Content-Type", "application/json")],
                      now=NOW - timedelta(days=days_ago))
    art.finalize(who, 0)
    return art


def test_newest_per_key_counts():
    [a] = current([ann(GW1, "old", days_ago=3), ann(GW1, "new", days_ago=1)], now=NOW)
    assert a.name == "new" and a.key == GW1.key_text
    assert a.networks[0].account == "@gw:x" and a.networks[0].exports


def test_old_and_invalid_announcements_are_not_shown():
    stale = ann(GW1, days_ago=31)
    forged = ann(GW2, "forged")
    forged.headers = [(k, v.replace("forged", "other") if k == "Subject" else v)
                      for k, v in forged.headers]
    broken = ann(GW2, "x", v=2)
    assert current([stale, forged, broken], now=NOW) == []


def test_active_groups_follow_their_gateways():
    a, b = "matrix.x.a@aaaaaaaaaaaaaaaa", "matrix.x.b@aaaaaaaaaaaaaaaa"
    found = current([ann(GW1, "one", groups=[a, b]), ann(GW2, "two", groups=[b])], now=NOW)
    act = active_groups(found)
    assert act[a] == ["one"] and sorted(act[b]) == ["one", "two"]
    # gw "one" stops: after 30 days only b is still served
    later = current([ann(GW1, "one", days_ago=31, groups=[a, b]), ann(GW2, "two", groups=[b])],
                    now=NOW)
    assert set(active_groups(later)) == {b}


def test_directory_is_a_data_group():
    assert DIRECTORY_GROUP in DATA_GROUPS


def test_where_the_directory_is():
    from unseenet.core.gateways import directory_of
    new = "unseenet.gateways@abcdefghijklmnop"
    assert directory_of(None) == DIRECTORY_GROUP
    assert directory_of({"owner": "x"}) == DIRECTORY_GROUP
    assert directory_of({"moved_to": new}) == new                    # UN-RFC 0020 section 10
    assert directory_of({"moved_to": "no group"}) == DIRECTORY_GROUP
    assert directory_of({"moved_to": DIRECTORY_GROUP}) == DIRECTORY_GROUP


async def test_the_cli_follows_the_directory_to_the_council(tmp_path, monkeypatch, capsys):
    """``unseenet gateways`` reads the old directory's manifest and, when it moved (UN-RFC
    0038 section 6.1), the gateways that announce in the new one."""
    from argparse import Namespace

    from unseenet import cli
    from unseenet.core import gateways
    from unseenet.core.groups import Manifest, make_manifest, manifest_article
    from unseenet.core.store import Store
    from unseenet.core.vault import Vault
    from unseenet.node.server import Node, NodeConfig
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    project, council = crypto.Identity.generate(), crypto.Identity.generate()
    old = make_manifest(project, "unseenet.gateways", "open", view="data", pow_bits=0)
    new = make_manifest(council, "unseenet.gateways", "open", view="data", pow_bits=0)
    moved = manifest_article(project, old.group, {**json.loads(old.body), "serial": 2,
                                                  "moved_to": new.group}, pow_bits=0)
    monkeypatch.setattr(gateways, "DIRECTORY_GROUP", old.group)
    node = Node(Store(), NodeConfig(min_pow=0, forward_delay=(0, 0)))
    for m in (old, moved, new):
        node.store.add(m, m.to_bytes())
    node.store.set_manifest(Manifest.from_article(moved))
    node.store.set_manifest(Manifest.from_article(new))
    now = datetime.now(timezone.utc)
    for group, name in ((old.group, "stayed-behind"), (new.group, "moved-along")):
        body = {"v": 1, "name": name, "operator": GW1.key_text, "contact": "inbox@abc",
                "networks": [{"network": "matrix", "account": "@gw:x", "import": True,
                              "export": False}], "groups": []}
        art = new_article(group, f"Gateway: {name}", json.dumps(body) + "\n", now=now,
                          extra=[("Content-Type", "application/json")]).finalize(GW1, 0)
        node.store.add(art, art.to_bytes())
    server = await node.serve("127.0.0.1", 0)
    app = cli.App(Vault.open(tmp_path / "v.vault", "pw", ops=1, mem=8192 * 1024))
    app.data["nodes"].append(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    try:
        await cli.c_gateways(app, Namespace(directory=None, network=None))
        out = capsys.readouterr().out
        assert "moved-along" in out and "stayed-behind" not in out
        await cli.c_gateways(app, Namespace(directory=old.group, network=None))  # as asked
        assert "stayed-behind" in capsys.readouterr().out
    finally:
        server.close()

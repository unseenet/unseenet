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

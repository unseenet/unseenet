"""#257 step 2: the node's side of state@<fp> (UN-RFC 0044): only the owner's manifest,
of type state, at most once an hour, and no articles."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from unseenet.core import crypto
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import make_group_id, manifest_article
from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig

BITS = 8
NOW = datetime.now(timezone.utc) - timedelta(hours=3)


def _node():
    return Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), new_groups="refuse"))


def _state(owner, serial, when, state="c3RhdGU=", **extra):
    gid = make_group_id("state", owner.public_key)
    data = {"v": 1, "name": "state", "type": "state", "owner": owner.key_text, "serial": serial,
            "expires": (when + timedelta(days=700)).strftime("%Y-%m-%dT%H:%M:%SZ"), "state": state} | extra
    return manifest_article(owner, gid, data, pow_bits=BITS, now=when)


def test_the_owner_keeps_one_state_and_updates_it_hourly():
    node, me = _node(), crypto.Identity.generate()
    first = _state(me, 1, NOW)
    node.accept(first.to_bytes(), now=NOW + timedelta(seconds=1))      # whatever new_groups says
    with pytest.raises(ArticleError, match="too soon"):
        node.accept(_state(me, 2, NOW + timedelta(minutes=20)).to_bytes(),
                    now=NOW + timedelta(minutes=21))
    later = _state(me, 2, NOW + timedelta(hours=1, minutes=10))
    node.accept(later.to_bytes(), now=NOW + timedelta(hours=1, minutes=11))
    assert node.store.manifest(first.group).message_id == later.message_id


def test_no_articles_and_only_state_in_state():
    node, me = _node(), crypto.Identity.generate()
    m = _state(me, 1, NOW)
    node.accept(m.to_bytes(), now=NOW + timedelta(seconds=1))
    post = new_article(m.group, "Hej", "x\n", from_name="Me", now=NOW).finalize(me, BITS)
    with pytest.raises(ArticleError, match="no articles"):
        node.accept(post.to_bytes(), now=NOW + timedelta(seconds=2))
    with pytest.raises(ArticleError, match="carries its state"):
        node.accept(_state(me, 1, NOW, state="").to_bytes(), now=NOW + timedelta(seconds=1))
    other = crypto.Identity.generate()                      # the type belongs to state@ alone
    gid = make_group_id("dk.x", other.public_key)
    bad = manifest_article(other, gid, {"v": 1, "name": "dk.x", "type": "state", "owner": other.key_text,
                                        "serial": 1, "state": "c3RhdGU="}, pow_bits=BITS)
    with pytest.raises(ArticleError, match="one group of type state"):
        node.accept(bad.to_bytes())

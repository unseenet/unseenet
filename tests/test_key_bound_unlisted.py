"""UN-RFC 0040 sections 3, 5 and 9: key-bound groups are not listed, and their
manifests are limited in size."""

import time

import pytest

from unseenet.core import crypto
from unseenet.core.article import ArticleError
from unseenet.core.groups import inbox_article, make_manifest
from unseenet.core.store import Store
from unseenet.nntp import Client
from unseenet.node.server import Node, NodeConfig

BITS = 8


def _node():
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    owner, sender = crypto.Identity.generate(), crypto.Identity.generate()
    snak = make_manifest(owner, "dk.snak", "open", title="Snak", pow_bits=BITS)
    inbox = make_manifest(owner, "inbox", "inbox", title="Inbox", pow_bits=BITS)
    profile = make_manifest(owner, "profile", "open", pow_bits=BITS)
    for art in (snak, inbox, profile):
        node.accept(art.to_bytes())
    msg = inbox_article(inbox.group, owner.public_key, from_name="s", subject="hej", body="b",
                        sender=sender, pow_bits=BITS)
    node.accept(msg.to_bytes())
    return node, snak, inbox, profile, msg


async def test_key_bound_groups_are_not_listed_but_reachable():
    node, snak, inbox, profile, msg = _node()
    server = await node.serve("127.0.0.1", 0)
    c = await Client.connect(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    try:
        active = [line.split()[0] for line in await c.list_active()]
        assert active == [snak.group]
        assert [line.split("\t")[0] for line in await c.multiline("LIST NEWSGROUPS *", 215)] \
            == [snak.group]
        assert await c.multiline(f"LIST ACTIVE {inbox.group}", 215) == []    # not by name either
        _, low, high = await c.group(inbox.group)                            # but reachable
        assert high >= low
        assert await c.article(msg.message_id) is not None

        # NEWNEWS: part 1 has the state of ordinary groups only, whatever its age;
        # part 2 still has everything received since, key-bound groups included
        node.store.db.execute("UPDATE articles SET received=?", (int(time.time()) - 400 * 86400,))
        node.store.db.commit()
        since = time.strftime("%Y%m%d %H%M%S", time.gmtime(time.time() - 10 * 86400))
        old = await c.newnews("*", since)
        assert snak.message_id in old
        assert inbox.message_id not in old and profile.message_id not in old
        node.store.db.execute("UPDATE articles SET received=? WHERE message_id=?",
                              (int(time.time()), msg.message_id))
        node.store.db.commit()
        recent = await c.newnews("inbox@*", since)
        assert recent == [msg.message_id]
    finally:
        await c.quit()
        server.close()


def test_key_bound_manifests_are_limited():
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0)))
    owner = crypto.Identity.generate()
    big = make_manifest(owner, "inbox", "inbox", description="x" * 17000, pow_bits=BITS)
    assert len(big.to_bytes()) > 16 * 1024
    with pytest.raises(ArticleError) as err:
        node.accept(big.to_bytes())
    assert err.value.reason == "size"
    fits = make_manifest(owner, "inbox", "inbox", description="x" * 14000, pow_bits=BITS)
    node.accept(fits.to_bytes())
    # an ordinary group's manifest has only the article limit
    node.accept(make_manifest(owner, "dk.lang", "open", description="x" * 17000,
                              pow_bits=BITS).to_bytes())

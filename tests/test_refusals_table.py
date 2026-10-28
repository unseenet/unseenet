"""#717: refusal lists (UN-RFC 0027 section 7.3) from [refusals] - for every picture a node
carries, also a node that carries no files; [blobs] refusal_keys keeps working."""

import io

import pytest
from PIL import Image

from unseenet.cli.node import load_node_config
from unseenet.client.media import avatar
from unseenet.core import blobs as bl
from unseenet.core import crypto, profiles
from unseenet.core.article import ArticleError, new_article
from unseenet.core.groups import canonical_json, make_manifest
from unseenet.core.store import Store
from unseenet.node.server import Node, NodeConfig

BITS = 8


def _picture() -> dict:
    out = io.BytesIO()
    Image.new("RGB", (200, 200), (10, 120, 200)).save(out, "PNG")
    data, ctype, px = avatar(out.getvalue())
    return profiles.make_picture(data, ctype, px)


def test_the_table_in_node_toml(tmp_path):
    lister = crypto.Identity.generate().key_text
    path = tmp_path / "node.toml"
    path.write_text(f'[refusals]\nkeys = ["{lister}"]\ngroups = "dk.lister.*"\n')
    cfg = load_node_config(path)
    assert cfg.refusal_keys == [lister] and cfg.refusal_groups == "dk.lister.*"
    assert cfg.blobs is None                                       # no files, lists all the same
    assert load_node_config(None).refusal_keys == []                # none by default
    path.write_text('[refusals]\nkeys = ["not a key"]\n')
    with pytest.raises(SystemExit, match="refusals"):
        load_node_config(path)


def test_lists_cover_pictures_on_a_node_without_files():
    lister, owner = crypto.Identity.generate(), crypto.Identity.generate()
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0), avatars="accept",
                                    refusal_keys=[lister.key_text], refusal_groups="dk.*"))
    assert node.config.blobs is None
    assert node.node_info()["policy"]["refusal_lists"] is True        # said, without blobs
    lists = make_manifest(lister, "dk.lister", "channel", pow_bits=BITS)
    node.accept(lists.to_bytes())
    pic = _picture()
    bid = bl.blob_id(profiles.check_picture(pic))
    body = canonical_json({"blobs": [bid], "reason": "test", "v": 1})
    lst = new_article(lists.group, "Refusals", body, from_name="L",
                      extra=[("Content-Type", "application/x-unseenet-blob-refusals")])
    node.accept(lst.finalize(lister, BITS).to_bytes())
    assert node.store.blob_refused(bid)
    with pytest.raises(ArticleError, match="picture is refused"):
        node.accept(profiles.avatar_manifest(owner, pic, pow_bits=BITS).to_bytes())


def test_the_blobs_keys_still_count():
    lister = crypto.Identity.generate()
    node = Node(Store(), NodeConfig(min_pow=BITS, forward_delay=(0, 0),
                                    blobs={"max_size": 1048576, "retention_days": 30, "groups": "*",
                                           "refusal_keys": [lister.key_text], "refusal_groups": "dk.*"}))
    assert node.refusal_settings() == ([lister.key_text], "dk.*")

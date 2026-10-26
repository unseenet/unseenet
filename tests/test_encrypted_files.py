"""#497: encrypted files (UN-RFC 0027 section 3.3) - in closed groups and in private
posts and chats, with a fresh key per file carried inside the encryption."""

import io

import pytest

import unseenet.client.session as sess
from unseenet.client.session import Session, SessionError
from unseenet.core import blobs as bl
from unseenet.core.article import Article
from unseenet.core.blobs import BlobStore
from unseenet.core.store import Store
from unseenet.core.vault import Vault
from unseenet.node.server import Node, NodeConfig

KDF = {"ops": 1, "mem": 8192 * 1024}


@pytest.fixture
async def net(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "DEFAULT_POW", 10)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    node.config.blobs = {"max_size": bl.MAX_BLOB, "encrypted": True}
    node.blobs = BlobStore()
    server = await node.serve("127.0.0.1", 0)
    addr = f"127.0.0.1:{server.sockets[0].getsockname()[1]}"
    made = []

    def person(name):
        s = Session(Vault.open(tmp_path / f"{name}.vault", "pw", **KDF), status=lambda *_: None)
        s.new_identity(name, name.title())
        s.add_node(addr)
        s.data["starter_groups"] = 99
        made.append(s)
        return s
    yield node, person
    for s in made:
        await s.close()
    server.close()


def _picture(tmp_path):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (30, 20), (200, 30, 90)).save(buf, "PNG")
    path = tmp_path / "hemmelig.png"
    path.write_bytes(buf.getvalue())
    return path


def _stored(node, msgid) -> Article:
    return Article.from_bytes(node.store.get(msgid))


def test_files_are_encrypted_with_a_fresh_key_each_time():
    plain = b"the same file" * 100
    files = [("a.txt", "text/plain", plain)]
    outer, inner, blobs = bl.encrypted_attachment_headers(files)
    outer2, _, blobs2 = bl.encrypted_attachment_headers(files)
    assert blobs[0][0] != blobs2[0][0]                     # never convergent (3.3)
    assert len(blobs[0][1]) == bl.PAD + bl.ENC_OVERHEAD          # padded (3.3)
    assert plain not in blobs[0][1]
    art = Article([("Blobs", outer[0][1])], "")
    shown, keys = bl.inner_attachments(art, inner)
    assert shown[0]["size"] == len(plain) and shown[0]["name"] == "a.txt"
    assert bl.decrypt_file(keys[blobs[0][0]], blobs[0][1], len(plain)) == plain   # padding cut off
    # what 4.4 and 5.2 make a member's client refuse
    assert bl.inner_attachments(art, inner, types=["image/*"]) == ([], {})
    assert bl.inner_attachments(Article([("Blobs", outer2[0][1])], ""), inner) == ([], {})
    no_key = [(n, v.split("; key=")[0]) for n, v in inner]
    assert bl.inner_attachments(art, no_key) == ([], {})
    with pytest.raises(ValueError):
        bl.decrypt_file(b"\0" * 32, blobs[0][1])


async def test_a_picture_in_a_closed_group(net, tmp_path):
    node, person = net
    alice, bob = person("alice"), person("bob")
    fam = await alice.create_group("familie", "closed", min_pow=10,
                                   extra={"attachments": bl.PICTURES})
    await alice.invite(fam, bob.identity().key_text)
    files = alice.prepare_files([_picture(tmp_path)])
    msgid = await alice.post(fam, "Billede", "Kun for familien\n", files=files)
    art = _stored(node, msgid)
    assert art.get("Blobs") and not any(n.lower().startswith("attachment-") for n, _ in art.headers)
    (bid, size), = bl.parse_blobs(art)
    assert node.blobs.get(bid) != files[0].octets
    # padded (UN-RFC 0027 3.3): the node sees only the size class, not the file's length
    assert size == bl.padded_size(len(files[0].octets), bl.PICTURES["max_size"]) + 40
    assert size % bl.PAD == 40 and size != len(files[0].octets) + 40
    bob.subscribe(fam)
    await bob.fetch_group(fam)
    msg = bob.find_message(fam, msgid)
    assert msg.readable and [a["name"] for a in msg.attachments] == ["hemmelig.png"]
    assert "key" not in msg.attachments[0] and "file_keys" not in msg.to_dict()
    assert await bob.fetch_blob(fam, bid) == files[0].octets
    outsider = person("eve")
    outsider.subscribe(fam)
    await outsider.fetch_group(fam)
    assert not outsider.find_message(fam, msgid).attachments    # not a member: no keys


async def test_pictures_in_private_posts_and_chats(net, tmp_path):
    node, person = net
    alice, bob = person("alice"), person("bob")
    await bob.ensure_inbox()
    await alice.ensure_inbox()
    assert bob.manifest_data(bob.my_inbox)["attachments"] == bl.PICTURES   # new inboxes (#497)
    files = alice.prepare_files([_picture(tmp_path)])
    post = await alice.send_private(bob.my_inbox, "Til dig", "Se\n",
                                    owner_key=bob.identity().public_key, files=files)
    chat = await alice.send_chat("contact:" + bob.identity().key_text, "og her", files=files)
    assert alice.sent[-1]["files"] == ["hemmelig.png"]
    for mid in (post, chat):
        assert not any(n.lower().startswith("attachment-") for n, _ in _stored(node, mid).headers)
    await bob.fetch_group(bob.my_inbox)
    for mid in (post, chat):
        msg = bob.find_message(bob.my_inbox, mid)
        (a,) = msg.attachments
        assert await bob.fetch_blob(bob.my_inbox, a["blob"]) == files[0].octets
    # turned off: the inbox takes no files, and senders are told
    await bob.set_inbox_files(False)
    assert "attachments" not in bob.manifest_data(bob.my_inbox)
    alice.group_entry(bob.my_inbox).pop("manifest", None)
    with pytest.raises(SessionError, match="no files"):
        await alice.send_private(bob.my_inbox, "Igen", "Se\n",
                                 owner_key=bob.identity().public_key, files=files)


async def test_an_old_inbox_is_given_pictures(net):
    node, person = net
    bob = person("bob")
    bob.data["inbox_files"] = False
    await bob.ensure_inbox()
    assert "attachments" not in bob.manifest_data(bob.my_inbox)
    bob.data["inbox_files"] = True
    assert await bob.offer_inbox_files()
    assert (await bob.fetch_manifest(bob.my_inbox)).raw["attachments"] == bl.PICTURES
    assert not await bob.offer_inbox_files()               # once


async def test_a_picture_submitted_to_a_moderated_group(net, tmp_path):
    """UN-RFC 0027 section 5.3: the post names plain blobs, the moderators get the
    files encrypted, and the approving moderator checks and uploads the plain ones."""
    node, person = net
    owner, user = person("owner"), person("user")
    for p in (owner, user):
        await p.ensure_inbox()
    gid = await owner.create_group("dk.mod.foto", "moderated", min_pow=10,
                                   extra={"attachments": bl.PICTURES})
    user.subscribe(gid)
    await user.fetch_group(gid)
    files = user.prepare_files([_picture(tmp_path)])
    msgid = await user.post(gid, "Mit billede", "Må jeg vise det?\n", files=files)
    plain = bl.blob_id(files[0].octets)
    assert node.blobs.get(plain) is None                    # not public before approval
    await owner.fetch_group(owner.my_inbox)
    (queued,) = owner.submissions()
    await owner.approve_submission(*queued)
    assert node.blobs.get(plain) == files[0].octets
    await user.fetch_group(gid)
    msg = user.find_message(gid, msgid)
    assert [a["blob"] for a in msg.attachments] == [plain]
    assert await user.fetch_blob(gid, plain) == files[0].octets


def test_padding_rules():
    assert bl.padded_size(1) == bl.PAD and bl.padded_size(bl.PAD) == bl.PAD
    assert bl.padded_size(bl.PAD + 1) == 2 * bl.PAD
    assert bl.padded_size(100_000, limit=110_000) == 110_000          # never over the group's limit
    assert bl.padded_size(100_000, limit=90_000) == 100_000           # never under the file
    assert bl.fits_padding(bl.PAD + 40, 10) and bl.fits_padding(50, 10)  # padded, or not (a limit)
    assert not bl.fits_padding(bl.PAD + 41, 10) and not bl.fits_padding(49, 10)
    key, blob = bl.encrypt_file(b"hej")
    assert len(blob) == bl.PAD + 40 and bl.decrypt_file(key, blob, 3) == b"hej"

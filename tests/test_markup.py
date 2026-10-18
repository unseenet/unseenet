"""UN-RFC 0031: Markdown and emoji as a safe tree."""

from unseenet.core import markup


def kinds(blocks):
    return [b["t"] for b in blocks]


def test_post_subset():
    tree = markup.parse("# Overskrift\n\nHej *dig* og **dig** og ~~ikke~~ `kode`\n\n"
                        "> citat\n\n- en\n- to\n\n```python\nprint(1)\n```\n\n---\n")
    assert kinds(tree) == ["h", "p", "quote", "ul", "code", "hr"]
    p = tree[1]["c"]
    assert [n["t"] for n in p if n["t"] != "text"] == ["em", "strong", "del", "code"]
    assert tree[4] == {"t": "code", "lang": "python", "v": "print(1)"}
    assert markup.parse("#### dyb")[0] == {"t": "h", "n": 3, "c": [{"t": "text", "v": "dyb"}]}


def test_chat_is_lighter():
    tree = markup.parse("# ikke en overskrift\n- heller ikke en liste\n**fed** dog", "chat")
    assert kinds(tree) == ["p"]
    assert any(n["t"] == "strong" for n in tree[0]["c"])
    assert "# ikke en overskrift" in markup.to_text(tree[0]["c"])


def test_no_html_and_only_safe_links():
    tree = markup.parse("<script>alert(1)</script> og <b>fed</b>")
    assert "<script>" in markup.to_text(tree[0]["c"])            # shown as text
    ok = markup.parse("[forum](http://abc.onion/) [g](unseenet:dk.snak) [n](news:dk.test)")[0]["c"]
    assert [n["href"] for n in ok if n["t"] == "link"] == ["http://abc.onion/", "unseenet:dk.snak",
                                                              "news:dk.test"]
    bad = markup.parse("[klik](javascript:alert(1)) [f](file:///etc/passwd)")[0]["c"]
    assert not any(n["t"] == "link" for n in bad)
    assert "javascript:alert(1)" in markup.to_text(bad)          # the address, as text


def test_images_only_from_blobs():
    good = markup.parse("![skærmbillede](blob:" + "ab" * 16 + ")")[0]["c"]
    assert good == [{"t": "image", "blob": "ab" * 16, "alt": "skærmbillede"}]
    remote = markup.parse("![sporing](https://evil.example/pixel.png)")[0]["c"]
    assert remote == [{"t": "text", "v": "[image: sporing]"}]   # never fetched


def test_emoji():
    assert markup.emoji("tada") == "🎉" and markup.emoji("+1") == "👍"
    inl = markup.parse("Tillykke :tada: og :nosuchthing: og `:tada:` 👍")[0]["c"]
    assert {"t": "emoji", "v": "🎉", "name": "tada"} in inl
    text = markup.to_text(inl)
    assert ":nosuchthing:" in text and ":tada:" in text and "👍" in text   # unknown and code stay


def test_plain_and_by_content_type():
    assert markup.body("*ikke fed*", "text/plain; charset=utf-8") == \
        [{"t": "p", "c": [{"t": "text", "v": "*ikke fed*"}]}]
    assert markup.body("*fed*", markup.MARKDOWN_TYPE)[0]["c"][0]["t"] == "em"
    assert markup.is_markdown("Text/Markdown; charset=utf-8") and not markup.is_markdown(None)


def test_deep_lists_are_flattened_and_size_is_capped():
    deep = "\n".join("  " * i + "- " + str(i) for i in range(8))
    def depth(blocks, d=0):
        return max([d] + [depth(item, d + 1) for b in blocks if b["t"] in ("ul", "ol") for item in b["items"]])
    assert depth(markup.parse(deep)) <= markup.MAX_LIST_DEPTH
    assert markup.parse("x" * (markup.MAX_TEXT * 2))              # does not hang


def test_terminal_rendering():
    from unseenet.client import richtext
    text = richtext.blocks(markup.parse("# Hej\n\n*fin* [her](http://x.onion/) :tada:\n\n> citat\n\n- a\n- b"))
    plain = text.plain
    assert "Hej" in plain and "🎉" in plain
    assert "<http://x.onion/>" in plain                         # where the link goes is shown
    assert "│ citat" in plain and "• a\n• b" in plain


async def test_posts_are_markdown_by_default(tmp_path, monkeypatch):
    import unseenet.client.session as sess
    from unseenet.client.session import Session
    from unseenet.core.store import Store
    from unseenet.core.vault import Vault
    from unseenet.node.server import Node, NodeConfig
    monkeypatch.setattr(sess, "DEFAULT_POW", 8)
    node = Node(Store(), NodeConfig(min_pow=8, forward_delay=(0, 0)))
    server = await node.serve("127.0.0.1", 0)
    s = Session(Vault.open(tmp_path / "me.vault", "pw", ops=1, mem=8192 * 1024), status=lambda *_: None)
    s.new_identity("me", "Me"); s.add_node(f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    gid = await s.create_group("dk.md", "open", min_pow=8)
    await s.post(gid, "Fed", "**fed**\n")
    s.set_markdown(False)
    await s.post(gid, "Ren", "*ikke fed*\n")
    closed = await s.create_group("dk.lukket", "closed", min_pow=8)
    s.set_markdown(True)
    await s.post(closed, "Hemmelig", "_skjult_\n")
    await s.fetch_group(gid); await s.fetch_group(closed)
    by = {m.subject: m for g in (gid, closed) for m in s.cache[g].values()}
    assert markup.is_markdown(by["Fed"].content_type)
    assert not markup.is_markdown(by["Ren"].content_type)
    assert markup.is_markdown(by["Hemmelig"].content_type)     # inside the encryption too
    await s.close()
    server.close()

"""The web form of unseenet: addresses and web+unseenet: (UN-RFC 0031 section 3.4.1, #454),
and a site's index field (UN-RFC 0035 section 3)."""

import pytest

from unseenet.core import addresses as addr
from unseenet.core import crypto
from unseenet.core.groups import check_extra_fields

FP = "abcdefghijklmnop"


def _gid() -> str:
    from unseenet.core.groups import make_group_id
    return make_group_id("dk.wiki", crypto.Identity.generate().public_key)


def test_the_web_form_on_any_host_is_the_same_address():
    gid = _gid()
    for a in (addr.group_address(gid), addr.page_address(gid, "projects/ovos"),
              addr.post_address(gid, "<x1@example>"), addr.identity_address(FP)):
        for host in ("129.151.209.26", "entrance.unseenet.net", "example.org:8443"):
            web = addr.web_address(a, host)
            assert web.startswith(f"https://{host}/a/")
            assert addr.parse(web) == addr.parse(a)
            assert addr.is_web_form(web)
        assert addr.parse("http://other.example/a/" + a[len("unseenet:"):]) == addr.parse(a)
        assert addr.parse("web+unseenet:" + a[len("unseenet:"):]) == addr.parse(a)
        assert str(addr.parse("web+unseenet:" + a[len("unseenet:"):])) == a   # written as unseenet:


def test_hints_are_left_out_on_the_web_and_the_default_host_is_a_listed_entrance():
    gid, onion = _gid(), "a" * 56 + ".onion"
    a = addr.group_address(gid, [onion])
    web = addr.web_address(a)
    assert "n=" not in web
    assert web.startswith(f"https://{addr.default_web_host()}/a/")
    assert addr.parse(a).nodes == (onion,)


@pytest.mark.parametrize("bad", ["https://example.org/b/" + FP, "https://example.org/a/",
                                 "ftp://example.org/a/" + FP, "https://example.org/a/nope"])
def test_not_an_address(bad):
    with pytest.raises(addr.AddressError):
        addr.parse(bad)


def test_web_address_needs_a_proper_host():
    with pytest.raises(addr.AddressError):
        addr.web_address(addr.identity_address(FP), "not a host/")


def test_the_index_field_of_a_site():
    check_extra_fields({"view": "pages", "index": "yes"})
    check_extra_fields({"view": "pages", "index": "no"})
    with pytest.raises(ValueError, match="index"):
        check_extra_fields({"view": "pages", "index": "maybe"})
    with pytest.raises(ValueError, match="sites"):
        check_extra_fields({"view": "threads", "index": "yes"})

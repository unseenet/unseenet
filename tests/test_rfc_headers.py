"""UN-RFC 0000 sections 3.3 and 3.4: every header has a real status and says what is built.

A maintainer's acceptance agrees to a change; it is not a status (#738)."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_rfc_headers", ROOT / "tools" / "check_rfc_headers.py")
chk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chk)


def test_every_unrfc_header_is_in_order():
    found = [m for p in sorted(chk.RFC_DIR.glob("un-rfc-*.md")) for m in chk.problems(p)]
    assert found == []


def _rfc(tmp_path, status="Draft", implemented="unseenet 0.5.0", category="Standards Track",
         number="0099"):
    impl = "" if implemented is None else f"Implemented: {implemented}\n"
    p = tmp_path / f"un-rfc-{number}.md"
    p.write_text("```\nUnseenet Working Group                                     A. Lorensen\n"
                 f"UN-RFC: {number}                                              October 2026\n"
                 f"Category: {category}\nStatus: {status}\n{impl}\n"
                 "                    Unseenet: A Test\n```\n\n# Abstract\n")
    return p


def test_accepted_is_not_a_status(tmp_path):
    found = chk.problems(_rfc(tmp_path, status="Accepted"))
    assert len(found) == 1 and "not a status" in found[0]


@pytest.mark.parametrize("status", ["Proposed", "Standard"])
def test_the_first_series_stays_draft_before_1_0(tmp_path, status):
    assert "pre-alpha" in chk.problems(_rfc(tmp_path, status=status))[0]


def test_a_process_document_is_active(tmp_path):
    assert chk.problems(_rfc(tmp_path, status="Active", category="Process", implemented=None)) == []


@pytest.mark.parametrize("implemented", [
    "-", "unseenet 0.5.0", "unseenet 0.4.0, unseenet-gateway 0.1.0", "unseenet main (unreleased)",
    "unseenet 0.5.0; partly - books (#280)",
    "unseenet main (unreleased); partly - the copy to a browser (unseenet-entrance#53)"])
def test_what_implemented_may_say(tmp_path, implemented):
    assert chk.problems(_rfc(tmp_path, implemented=implemented)) == []


@pytest.mark.parametrize("implemented", [None, "yes", "0.5.0", "unseenet 0.5", "partly",
                                         "unseenet 0.5.0 partly", "unseenet main"])
def test_what_implemented_may_not_say(tmp_path, implemented):
    assert len(chk.problems(_rfc(tmp_path, implemented=implemented))) == 1


def test_a_release_names_its_version(tmp_path, monkeypatch):
    monkeypatch.setattr(chk, "RFC_DIR", tmp_path)
    p = _rfc(tmp_path, implemented="unseenet main (unreleased); partly - more (#1)")
    q = _rfc(tmp_path, implemented="unseenet 0.4.0", number="0098")
    assert chk.release("0.6.0") == [p]
    assert "Implemented: unseenet 0.6.0; partly - more (#1)" in p.read_text()
    assert "Implemented: unseenet 0.4.0" in q.read_text()
    assert chk.main([]) == 0

"""#615: ``unseenet rules`` and ``unseenet thread`` - your own rules from the command line,
as the local API has them (UN-RFC 0051, CLI parity #578)."""
import io
import json
from argparse import Namespace

import pytest

from unseenet import cli
from unseenet.core.vault import Vault

KDF = {"ops": 1, "mem": 8192 * 1024}


def _app(tmp_path):
    app = cli.App(Vault.open(tmp_path / "v.vault", "pw", **KDF))
    app.session.new_identity("me", "Me")
    return app


def out(capsys):
    return json.loads(capsys.readouterr().out)


async def test_rules_from_the_command_line(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path)
    await cli.c_rules(app, Namespace(json=False, what="show", file=None))
    assert "No rules" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO("+10 if author in following  # friends\n+1 if autor in contacts\n"))
    await cli.c_rules(app, Namespace(json=True, what="set", file="-"))
    got = out(capsys)
    assert got["rules"] == 1 and got["problems"][0]["line"] == 2 and got["on"] is True
    f = tmp_path / "r.txt"
    f.write_text("show if score >= 0\nsort by scor")
    with pytest.raises(SystemExit):                       # check: problems make it fail
        await cli.c_rules(app, Namespace(json=False, what="check", file=str(f)))
    assert "did you mean 'score'" in capsys.readouterr().out
    assert app.session.feed_rules().startswith("+10")     # check kept nothing
    await cli.c_rules(app, Namespace(json=True, what="off", file=None))
    assert out(capsys)["on"] is False and app.session.feed_rules()
    await cli.c_rules(app, Namespace(json=True, what="clear", file=None))
    assert out(capsys)["text"] == ""


async def test_watching_a_thread(tmp_path, capsys):
    app = _app(tmp_path)
    await cli.c_thread(app, Namespace(json=True, what="watch", msgid="t@x"))
    assert out(capsys) == {"id": "<t@x>", "mark": "watched"}
    await cli.c_thread(app, Namespace(json=True, what="clear", msgid="<t@x>"))
    assert out(capsys)["mark"] == ""


def test_the_parser_knows_them(capsys):
    for argv, word in ((["rules", "--help"], "check"), (["thread", "--help"], "watch"),
                       (["timeline", "--help"], "--why")):
        with pytest.raises(SystemExit) as e:
            cli.client_main(argv)
        assert e.value.code == 0 and word in capsys.readouterr().out

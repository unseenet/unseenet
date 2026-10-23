"""#402, #404: every public function of the client core, the local client API, the node,
the store and the command line has a docstring.

Their docstrings are the API reference (the Developers section of the docs is
generated from them). A new public function without one fails here; private ones
(``_name``) are exempt.
"""
import importlib
import inspect
import pkgutil

import pytest

from unseenet.client.localapi import LocalAPI
from unseenet.client.session import Session
from unseenet.core.store import Store
from unseenet.node.server import Node
from unseenet.node.server import Session as Connection

HINT = " - say what it does, what it returns and when it is used"


def _public(cls):
    for name in sorted(dir(cls)):
        if name.startswith("_"):
            continue
        raw = inspect.getattr_static(cls, name)
        fn = raw.fget if isinstance(raw, property) else getattr(raw, "__func__", raw)
        if inspect.isfunction(fn):
            yield name, fn


@pytest.mark.parametrize("cls", [Session, LocalAPI, Node, Connection, Store],
                         ids=["Session", "LocalAPI", "Node", "node Session", "Store"])
def test_every_public_function_has_a_docstring(cls):
    missing = [name for name, fn in _public(cls) if not (fn.__doc__ or "").strip()]
    assert not missing, f"public {cls.__name__} functions without a docstring: " \
                        + ", ".join(missing) + HINT


def test_every_public_cli_function_has_a_docstring():
    import unseenet.cli as cli
    own = [n for n in cli.__all__ if not n.startswith("_")
           and inspect.isfunction(getattr(cli, n)) and getattr(cli, n).__module__.startswith("unseenet.cli")]
    missing = [n for n in own if not (getattr(cli, n).__doc__ or "").strip()]
    assert not missing, "cli functions without a docstring: " + ", ".join(missing) + HINT


@pytest.mark.parametrize("package", ["unseenet.client.session", "unseenet.node.server",
                                     "unseenet.core.store", "unseenet.cli",
                                     "unseenet.client.localapi.api"])
def test_every_part_says_what_it_is(package):
    """Each file of a split package opens with what belongs in it (#390, #394, #396,
    #398, #400); the client core's parts say so in so many words."""
    pkg = importlib.import_module(package)
    for info in pkgutil.iter_modules(pkg.__path__):
        doc = importlib.import_module(f"{package}.{info.name}").__doc__ or ""
        assert len(doc.strip()) > 40, f"{package}.{info.name}: say what belongs in this file"
        if package == "unseenet.client.session":
            assert "Belongs here" in doc, f"{info.name}.py: say what belongs here"

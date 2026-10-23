"""#402: every public function of Session has a docstring.

Session is the client core every client is built on, and its docstrings are its API
reference (the Developers section of the docs is generated from them). A new public
function without one fails here; private ones (``_name``) are exempt.
"""
import inspect

from unseenet.client.session import Session


def _public():
    for name in sorted(dir(Session)):
        if name.startswith("_"):
            continue
        raw = inspect.getattr_static(Session, name)
        fn = raw.fget if isinstance(raw, property) else getattr(raw, "__func__", raw)
        if inspect.isfunction(fn):
            yield name, fn


def test_every_public_session_function_has_a_docstring():
    missing = [name for name, fn in _public() if not (fn.__doc__ or "").strip()]
    assert not missing, ("public Session functions without a docstring: " + ", ".join(missing)
                         + " - say what it does, what it returns and when a client uses it")


def test_the_parts_say_what_belongs_in_them():
    """Each file of the package opens with what belongs there (#390)."""
    import pkgutil
    import importlib
    import unseenet.client.session as pkg
    for info in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"{pkg.__name__}.{info.name}")
        assert "Belongs here" in (mod.__doc__ or ""), f"{info.name}.py: say what belongs here"

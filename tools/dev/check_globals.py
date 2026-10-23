"""(tools/dev) After a split: every global name a function in a package's files looks up must exist in
that file's globals (or builtins). Finds NameErrors that tests may not reach."""
import builtins
import dis
import importlib
import inspect
import pkgutil
import sys
import types

sys.path.insert(0, sys.argv[1] + "/src")
bad = []
for pkgname in sys.argv[2:]:
    pkg = importlib.import_module(pkgname)
    for info in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"{pkgname}.{info.name}")
        g = vars(mod)

        def check(code, where):
            for ins in dis.get_instructions(code):
                if ins.opname in ("LOAD_GLOBAL", "LOAD_NAME"):
                    name = ins.argval if isinstance(ins.argval, str) else ins.argval[0]
                    if name not in g and not hasattr(builtins, name):
                        bad.append(f"{mod.__name__}: {where} uses {name}")
            for const in code.co_consts:
                if isinstance(const, types.CodeType):
                    check(const, f"{where}.{const.co_name}")

        for obj in list(g.values()):
            if inspect.isclass(obj) and obj.__module__ == mod.__name__:
                for name, f in vars(obj).items():
                    f = getattr(f, "__func__", f)
                    if isinstance(f, property):
                        f = f.fget
                    if inspect.isfunction(f):
                        check(f.__code__, f"{obj.__name__}.{name}")
            elif inspect.isfunction(obj) and obj.__module__ == mod.__name__:
                check(obj.__code__, obj.__name__)
print("\n".join(bad) if bad else "every global name found")

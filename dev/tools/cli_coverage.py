#!/usr/bin/env python3
"""Which CLI command paths does the test suite actually exercise?

The unified-UI promise is that every capability is reachable from every
surface.  The CLI is the surface where "reachable" is cheapest to assert and
easiest to leave untested: a verb is registered by a decorator, so it EXISTS
whether or not anything ever runs it.

Two numbers, and the distinction between them is the whole point:

    body run     some test invokes the path and reaches the command body
    --help only  the path is invoked, but only with ``--help``/``-h``

The second group is the trap.  ``click`` intercepts ``--help`` before the
callback runs, so those invocations prove the verb is REGISTERED and nothing
about what it does — yet they look like coverage to a grep, and they looked
like coverage to the first version of this tool, which reported ``trcc api``
covered on the strength of ``['api', '--help']``.

    PYTHONPATH=src python3 dev/tools/cli_coverage.py           # summary
    PYTHONPATH=src python3 dev/tools/cli_coverage.py --all     # name them
    PYTHONPATH=src python3 dev/tools/cli_coverage.py --family autostart

DENOMINATOR is the live Typer tree, never a hand-written list — a list would
be one more copy of a fact that the tree already states.  NUMERATOR is every
literal argv handed to ``.invoke(...)`` under ``tests/``.  That parse is
complete rather than approximate, and the tool proves it: it counts the
``.invoke(`` call sites it found and the argv lists it parsed, and warns when
they disagree, because argv built in a variable would silently deflate every
number below.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "dev"))

#: ``click`` handles these before the command body ever runs.
_HELP_FLAGS = {"--help", "-h"}


def cli_paths() -> list[str]:
    """Every runnable leaf in the live Typer tree, as the user types it."""
    import typer.main

    from _cli_tree import iter_leaves

    from trcc.ui.cli.main import app

    return [path for path, _ in iter_leaves(typer.main.get_command(app))]


def invoked_argvs(tests: Path) -> tuple[list[list[str]], int]:
    """Every literal argv passed to ``.invoke(...)``, and the call-site count.

    Returning both is what lets a caller check the parse is complete: an argv
    assembled in a variable parses to nothing and would quietly become a
    "never invoked" verdict about a path that is in fact tested.
    """
    argvs: list[list[str]] = []
    sites = 0
    for file in sorted(tests.rglob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "invoke"):
                continue
            sites += 1
            for arg in node.args:
                if not isinstance(arg, (ast.List, ast.Tuple)):
                    continue
                argv = [el.value for el in arg.elts
                        if isinstance(el, ast.Constant)
                        and isinstance(el.value, str)]
                if argv:
                    argvs.append(argv)
    return argvs, sites


def classify(path: str, argvs: list[list[str]]) -> str:
    """``"body"`` · ``"help"`` · ``"never"`` for one command path."""
    verbs = path.split()[1:]                      # drop the leading "trcc"
    reaching = [argv for argv in argvs if argv[:len(verbs)] == verbs]
    if not reaching:
        return "never"
    if any(not _HELP_FLAGS & set(argv) for argv in reaching):
        return "body"
    return "help"


def main() -> int:
    tests = _REPO / "tests"
    paths = cli_paths()
    argvs, sites = invoked_argvs(tests)

    if sites != len(argvs):
        print(f"!! parsed {len(argvs)} argv lists from {sites} .invoke( call "
              f"sites — {sites - len(argvs)} built argv some other way, so "
              f"the counts below UNDERSTATE coverage.\n")

    verdict = {path: classify(path, argvs) for path in paths}
    tally = {kind: [p for p in paths if verdict[p] == kind]
             for kind in ("body", "help", "never")}

    print(f"live CLI leaf paths           : {len(paths)}")
    print(f"  body actually exercised     : {len(tally['body'])}")
    print(f"  --help only (body never run): {len(tally['help'])}")
    print(f"  never invoked at all        : {len(tally['never'])}")
    untested = len(tally["help"]) + len(tally["never"])
    print(f"  => body no test runs        : {untested} "
          f"({untested * 100 // len(paths)}%)")
    print(f"\n.invoke( call sites parsed    : {sites}")

    family = None
    if "--family" in sys.argv:
        family = sys.argv[sys.argv.index("--family") + 1]
    if family:
        print(f"\n=== paths containing {family!r} ===")
        for path in paths:
            if family in path:
                print(f"  {verdict[path]:5s}  {path}")

    if "--all" in sys.argv:
        for kind, heading in (("help", "--help only — body never runs"),
                              ("never", "never invoked at all")):
            print(f"\n=== {heading} ===")
            for path in tally[kind]:
                print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

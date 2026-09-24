"""The runtime ships only code that runs in production.

This project accumulated a lot of research: adversarial corpora, competing models
of the security object, a fulfilment derivation deliberately kept out of the
decision path. All of it earns its keep -- the results are cited throughout docs/,
and a claim whose experiment has been deleted is just an assertion -- but none of it
belongs in the package that serves customers.

The separation is structural, not a convention, and this test is what makes it so.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "wallet_control"


def _local_imports(module: str) -> set[str]:
    path = SRC / f"{module}.py"
    if not path.exists():
        return set()
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                found.add(node.module)
            else:  # `from . import stage` names the module itself
                found.update(alias.name for alias in node.names)
    return found


def _reachable_from(*roots: str) -> set[str]:
    seen: set[str] = set()
    todo = list(roots)
    while todo:
        module = todo.pop()
        if module in seen:
            continue
        seen.add(module)
        todo.extend(_local_imports(module))
    return seen


def test_no_runtime_module_is_unreachable_from_an_entry_point():
    """Every module in the shipped package must be reachable from one of the two real
    entry points -- the demo API or the live worker. An unreachable module is either
    dead code or research that has drifted back into the runtime."""
    entry_points = ("api", "live_worker")
    shipped = {p.stem for p in SRC.glob("*.py")} - {"__init__"}
    unreachable = shipped - _reachable_from(*entry_points)
    assert not unreachable, (
        f"unreachable from {entry_points}: {sorted(unreachable)} -- "
        "move it to research/ or delete it"
    )


def test_the_runtime_never_imports_the_research_package():
    """Research may import the runtime. The runtime may never import research: if it
    could, an experiment would be one import away from changing a customer's
    decision."""
    offenders = []
    for path in SRC.glob("*.py"):
        source = path.read_text()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("research"):
                offenders.append(path.name)
            if isinstance(node, ast.Import):
                offenders += [path.name for a in node.names if a.name.startswith("research")]
    assert not offenders, f"runtime modules importing research: {sorted(set(offenders))}"

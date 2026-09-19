"""`docs/FINAL_INVARIANTS.md` names a test for every invariant. Do those tests exist?

An invariant register is only worth the paper it is on if its right-hand column is
true. A hand-maintained table of "invariant -> the test that fails if you remove
the mechanism" rots the moment a test is renamed, and it rots SILENTLY -- the
register keeps asserting coverage that no longer exists, and it is the first thing
an external auditor will spot-check.

So the register is machine-checked here: every test identifier it cites must
resolve to a real test in this suite. This cannot verify that the cited test
actually exercises the invariant it is filed under -- that is a human reading, and
the register says which entries were mutation-verified. It CAN guarantee the
column is not fiction, which is the failure mode that actually happens.

Entries that deliberately cite no test (an architectural argument, a campaign
recorded in a research document, a mechanism verified by mutation rather than by a
dedicated test) are listed in `_NOT_TEST_IDENTIFIERS` and must stay listed, so
adding a new unbacked entry is a decision someone makes on purpose.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "FINAL_INVARIANTS.md"

# Citations that are not test identifiers. Each one is a claim backed by something
# other than a named test, and saying so explicitly is the point.
_NOT_TEST_IDENTIFIERS = {
    "mutation-killed",   # I14: reverting the mechanism kills existing tests; no dedicated test
}


def _cited_identifiers() -> list[tuple[str, str]]:
    """(invariant id, cited test identifier) for every row that cites one."""
    out: list[tuple[str, str]] = []
    for line in REGISTER.read_text().splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not re.fullmatch(r"\**I\d+\**", cells[0]):
            continue
        invariant = cells[0].strip("*")
        for match in re.finditer(r"`([A-Za-z0-9_]+)`", cells[-1]):
            out.append((invariant, match.group(1)))
        if not re.search(r"`[A-Za-z0-9_]+`", cells[-1]):
            out.append((invariant, cells[-1].split("(")[0].strip().strip("`*")))
    return out


@pytest.fixture(scope="module")
def collected() -> tuple[set[str], set[str]]:
    """(test function names, test file stems) actually in this suite."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    names: set[str] = set()
    stems: set[str] = set()
    for line in result.stdout.splitlines():
        if "::" not in line:
            continue
        path, _, node = line.partition("::")
        stems.add(Path(path).stem)
        names.add(node.split("[")[0].strip())
    assert names, f"collected no tests; pytest said:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    return names, stems


def test_the_register_cites_something_for_every_invariant():
    cited = {invariant for invariant, _ in _cited_identifiers()}
    ids = {
        cells[0].strip("*")
        for line in REGISTER.read_text().splitlines()
        if line.startswith("|")
        for cells in [[c.strip() for c in line.strip().strip("|").split("|")]]
        if len(cells) >= 4 and re.fullmatch(r"\**I\d+\**", cells[0])
    }
    assert ids, "parsed no invariants out of the register -- the table format changed"
    assert ids == cited, f"invariants with no citation at all: {sorted(ids - cited)}"


def test_every_test_the_register_cites_exists(collected):
    names, stems = collected
    missing = []
    for invariant, identifier in _cited_identifiers():
        if identifier in _NOT_TEST_IDENTIFIERS:
            continue
        if identifier in names or identifier in stems:
            continue
        # The register cites some entries as a prefix, e.g. `test_I10_*`.
        if any(name.startswith(identifier) for name in names):
            continue
        missing.append(f"{invariant}: {identifier}")
    assert not missing, "the invariant register cites tests that do not exist:\n  " + "\n  ".join(missing)


def test_unbacked_entries_stay_declared(collected):
    """The escape hatch must not quietly grow, and must not hold stale entries
    either: an identifier listed as "not a test" that later BECOMES a test should
    be removed from the list rather than left excusing itself."""
    names, stems = collected
    still_exempt = {i for i in _NOT_TEST_IDENTIFIERS if i not in names and i not in stems}
    assert still_exempt == _NOT_TEST_IDENTIFIERS, (
        f"these are now real tests and should be cited normally: {_NOT_TEST_IDENTIFIERS - still_exempt}"
    )
    cited = {identifier for _, identifier in _cited_identifiers()}
    assert _NOT_TEST_IDENTIFIERS <= cited, (
        f"declared as unbacked but no longer cited by the register: {_NOT_TEST_IDENTIFIERS - cited}"
    )

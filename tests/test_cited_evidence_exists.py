"""Every test this project cites as evidence must exist.

A jury that greps for one named test and finds nothing stops believing the rest of
the table, and rightly. The documents make roughly a hundred specific citations --
`test_execution_atomicity`, `test_F1*`, `test_human_consent_binding` -- and each one
is an invitation to check.

This also guards the opposite failure: a test renamed for clarity, leaving a dozen
documents pointing at a name that no longer exists. That has already happened once
here and the rename is recorded in `RESEARCH_LAB_REPORT.md`, which is why a citation
immediately followed by an arrow is read as a historical record rather than a claim.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _known_names() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "tests").rglob("*.py"):
        names.add(path.stem)
        names |= set(re.findall(r"^\s*def (test_\w+)", path.read_text(), re.M))
    return names


def _citations():
    """(document, cited name) for every `test_...` in backticks, skipping renames."""
    out = []
    for path in sorted([*(ROOT / "docs").glob("*.md"), ROOT / "README.md"]):
        text = path.read_text()
        for match in re.finditer(r"`(test_\w+)\*?`", text):
            after = text[match.end():match.end() + 4]
            if "→" in after or "->" in after:
                continue          # a record of a rename, not a claim about today
            out.append((path.relative_to(ROOT).as_posix(), match.group(1)))
    return out


CITATIONS = _citations()
KNOWN = _known_names()


def test_the_documents_cite_a_meaningful_number_of_tests():
    """If this collapses, the check above has stopped checking anything."""
    assert len(CITATIONS) > 50, f"only {len(CITATIONS)} citations found; parser broken?"


@pytest.mark.parametrize("doc,name", CITATIONS, ids=lambda v: v if isinstance(v, str) else v)
def test_every_cited_test_exists(doc, name):
    resolved = name in KNOWN or any(k.startswith(name) for k in KNOWN)
    assert resolved, (
        f"{doc} cites `{name}`, which is neither a test function nor a test file. "
        "Either the test was renamed and the document was not, or the citation was "
        "never true."
    )

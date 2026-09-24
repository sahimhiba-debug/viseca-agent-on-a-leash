"""Runs the full adversarial corpus (src/wallet_control/red_team_corpus.py) under
pytest, one test per case so a failure names the exact attack.

Two cases in this corpus were failing when it was first written, and both were
real: N03 (the same authorization executed twice across a restart, because the
payment executor's ledger lived in memory) and a fixture bug of the harness's own
that briefly looked like a seventh vulnerability. Both are in
docs/archive/DEEP_SECURITY_RESEARCH.md.
"""

from __future__ import annotations

import pytest

from research.red_team_corpus import all_cases

CASES = all_cases()


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_case_holds(case):
    held, observed = case.run()
    assert held, f"[{case.case_id}] {case.attack}\n  expected: {case.expected}\n  observed: {observed}"


def test_corpus_covers_every_category_and_is_large_enough():
    categories = {c.category for c in CASES}
    assert len(CASES) >= 100, f"corpus has shrunk to {len(CASES)} cases"
    assert len(categories) >= 8, sorted(categories)


def test_every_case_declares_a_security_property():
    """A case without a stated expectation is a test that cannot fail meaningfully."""
    for case in CASES:
        assert case.expected.strip(), case.case_id
        assert case.attack.strip(), case.case_id

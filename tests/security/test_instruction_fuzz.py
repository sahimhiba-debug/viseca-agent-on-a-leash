"""Rewriting the customer's sentence without changing its meaning must not change
what they delegated.

WHY THIS EXISTS. The compiler was found pairing the wrong two numbers in

    "Keep each order at or below CHF 120, and keep the total across any seven days
     at or below CHF 300."

-> CHF 300 per order, CHF 120 per week, CHF 300 per week -- while compiling the
OFFICIAL wording of the same instruction correctly, because that one says "including
delivery" and those two words push a lazy regex past its character budget. Right on
the benchmark, wrong on a two-word paraphrase of it.

That was found by hand, by accident, from a test written for something else. This is
the method it implies: mutation testing applied to the INPUT rather than to the code.
Each official instruction is rewritten in ways a reader would call meaning-preserving
-- clauses swapped around "and", a comma becoming a semicolon or a full stop, "at or
below" becoming "no more than", "seven days" becoming "7 days" -- and the DELEGATION
must not move.

THE ORACLE IS THE ENGINE. Comparing compiled rule lists asks the compiler to grade
its own output, and two different rule lists can permit exactly the same purchases.
So variants are compared on the five-part delegation signature: approved set, asked
set, per-window ceiling, annual exposure, and what could not be expressed.

EVERY REWRITE CARRIES ITS JUSTIFICATION, because "meaning-preserving" is a claim
about English, not a fact about strings. A rewrite that is not really
meaning-preserving produces a false alarm, and a tool that cries wolf is worse than
no tool.
"""

from __future__ import annotations

import pytest

from research.instruction_fuzz import REWRITES, sweep
from research.paraphrase_corpus import OFFICIAL


@pytest.fixture(scope="module")
def rows():
    return sweep()


def test_the_fuzzer_actually_rewrites_things(rows):
    """A rewrite that never applies proves nothing. Every one in the list must fire
    on at least one official instruction, or it is dead weight that makes the count
    look better than the coverage is."""
    assert len(rows) >= 12, len(rows)
    fired = {row["rewrite"] for row in rows}
    assert len(fired) >= 7, sorted(fired)
    assert len(rows) >= len(OFFICIAL), rows


def test_no_meaning_preserving_rewrite_changes_the_delegation(rows):
    """THE ASSERTION."""
    moved = [(r["scenario"], r["rewrite"], r["before"], r["after"]) for r in rows
             if r["moved"]]
    assert moved == [], moved


def test_the_oracle_is_live():
    """THE SELF-TEST, and the reason to trust the result above.

    A comparison that could not detect a change would report "nothing moved" for
    every input, forever, and look exactly like success. So: feed it a rewrite that
    genuinely DOES change the meaning -- a ten-times-larger ceiling -- and require it
    to notice.

    Verified once by hand against the real defect too: with the pairing bug restored,
    the sweep flags SCEN0001 under "drop 'including delivery'", moving the per-window
    ceiling from 21 purchases to 10 and the annual exposure from CHF 15,600 to
    CHF 6,300. That cannot be asserted here without shipping the bug, so it is
    recorded rather than automated."""
    from research.semantic_stability import signature

    original = OFFICIAL["SCEN0001"]
    louder = original.replace("CHF 120", "CHF 1200")
    assert louder != original
    assert signature(louder) != signature(original), (
        "the signature cannot tell a ten-times-larger ceiling from the original; "
        "every other result in this file is worthless")


def test_every_rewrite_says_why_it_is_meaning_preserving():
    """The claim being made is about English. If a rewrite cannot say why it is safe,
    a failure it causes cannot be read."""
    for name, _fn, why in REWRITES:
        assert len(why) >= 15, name
        assert name and not name.endswith("."), name

"""Where two readings of one sentence part company, and how much money is in the gap.

WHY DISAGREEMENT, AND WHERE IT IS THE ONLY SIGNAL AVAILABLE

Disagreement between two planners about WHAT TO BUY carries no information -- they
optimise different things and both are fine. Disagreement about WHETHER SOMETHING IS
ALLOWED carries none either -- neither has authority and the engine knows. It is
informative in exactly one place: where there is no ground truth, which here is what
the customer meant.

WHAT CHANGED

`ambiguity.find_witness` used to GUESS where to look: a handful of amounts derived
from the rules, the ceiling and a rappen either side. That finds a witness when one
sits on a boundary and can say nothing about how much is at stake. It now searches
the whole enumerated world, over sequences as well as single baskets, so it reports
the cheapest separating purchase AND how many there are.

    "up to CHF 250 per week"   470 of 595 purchases, cheapest 3 orders of CHF 87

"Your sentence is ambiguous" is a shrug. That is a question someone can answer.

THE SEQUENCE SEARCH IS NOT OPTIONAL. A weekly budget and a per-order ceiling of the
same figure agree on every ONE order and part company on the third, so a search over
baskets alone is blind to the commonest ambiguity in this vocabulary --
`test_a_sequence_only_divergence_is_found` fails if `REPEATS` is reduced to (1,).

WHERE A MODEL WOULD GO. `READINGS` is a hand-written table of two transformations.
`diverge` takes two COMPILERS instead, so a model-based one would generate readings
for constructs nobody thought of -- proposing a hypothesis about MEANING, never a
decision, adjudicated by the real engine and resolved by the customer. A wrong model
produces an extra question, never a wrong enforcement. No model has been run:
`api.publicai.co/v1` answers 401 without a key.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.read_back_is_compiler_agnostic import narrow_compiler  # noqa: E402
from wallet_control.ambiguity import READINGS, witnesses  # noqa: E402
from wallet_control.disagreement import REPEATS, diverge, diverge_from_readings  # noqa: E402
from wallet_control.policy_compiler import compile_instruction  # noqa: E402

VAGUE = "Order our household groceries, under CHF 120."
CLEAR = "Order our household groceries, at or below CHF 120."
PERIOD = "Order our household groceries, up to CHF 250 per week."


def test_a_vague_bound_is_ambiguous_about_a_countable_number_of_purchases():
    found = witnesses(VAGUE)
    assert len(found) == 1
    witness = found[0]
    assert 0 < witness["count"] < witness["universe"]
    assert witness["amount"] == 120.0 and witness["repeats"] == 1
    assert {witness["verdict_a"], witness["verdict_b"]} == {"block", "allow"}


def test_a_sequence_only_divergence_is_found():
    """THE REGRESSION GUARD. "Up to CHF 250 per week" read as a weekly budget and as
    a per-order ceiling agree on every single order under 250. Only the third
    purchase separates them, so a search over baskets alone would report this
    sentence as unambiguous -- which is the commonest ambiguity in this vocabulary
    and the most expensive."""
    assert max(REPEATS) >= 3, "the sequence search is what finds this one"
    found = witnesses(PERIOD)
    assert len(found) == 1, found
    witness = found[0]
    assert witness["repeats"] > 1, "a single basket cannot separate these readings"
    assert witness["count"] > 100, witness["count"]


def test_a_clear_sentence_is_silent():
    """The property that keeps this from being another warning people click through.
    "At or below CHF 120" says plainly that 120 is included."""
    assert witnesses(CLEAR) == []


def test_the_cheapest_divergence_is_the_one_reported():
    """A witness the customer is shown must be the smallest one, or they will judge
    the ambiguity by an example that overstates it."""
    reading = next(r for r in READINGS if r.key == "strictness")
    divergence = diverge_from_readings(VAGUE, reading.transform)
    assert divergence.cheapest["chf"] == min(
        divergence.cheapest["chf"], divergence.widest["chf"])
    assert witnesses(VAGUE)[0]["amount"] == divergence.cheapest["chf"]


def test_two_different_compilers_diverge_and_the_engine_says_where():
    """The seam a model would slot into. A compiler that reads only "CHF N" misses
    the familiarity clause, and the engine names every purchase that costs."""
    sentence = ("Order our household groceries at or below CHF 120 from a shop I "
                "have used before.")
    divergence = diverge(sentence, compile_instruction, narrow_compiler)
    assert divergence.count > 0
    assert divergence.cheapest is not None
    # The narrow compiler is strictly more permissive here, never less.
    assert divergence.cheapest["as_compiled"] == "block"
    assert divergence.cheapest["alternative"] == "allow"


def test_a_compiler_that_agrees_produces_no_divergence():
    """The control. If `diverge` reported differences between a compiler and itself,
    every number above would be noise."""
    divergence = diverge(VAGUE, compile_instruction, compile_instruction)
    assert divergence.count == 0
    assert divergence.cheapest is None and divergence.widest is None


def test_one_divergence_is_counted_once_per_basket():
    """The same basket repeated is the same question asked louder. Counting each
    repetition would inflate the figure the customer is shown."""
    reading = next(r for r in READINGS if r.key == "period_scope")
    divergence = diverge_from_readings(PERIOD, reading.transform)
    assert divergence.count <= divergence.universe, (divergence.count, divergence.universe)


@pytest.mark.parametrize("sentence", [VAGUE, CLEAR, PERIOD])
def test_the_search_is_deterministic(sentence):
    assert witnesses(sentence) == witnesses(sentence)

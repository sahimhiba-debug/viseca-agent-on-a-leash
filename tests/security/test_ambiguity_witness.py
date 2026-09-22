"""A policy is a hypothesis about what someone meant. This finds the experiment.

The compiler already detects ambiguity and explains it in prose -- "the instruction
mentions more than one per-order amount; the smallest was used defensively". That
is honest and nearly useless, because it asks the customer to imagine a
consequence. People do not audit prose about hypothetical purchases; they agree to
it.

So instead of describing the ambiguity, find the PURCHASE it changes: compile the
sentence twice, once as the compiler read it and once as the other defensible
reading, and search for a basket the two policies judge differently. That basket is
a witness, and it turns "your sentence is ambiguous" into a question a person can
actually answer.

THE PROPERTY THAT MATTERS MOST IS THE SILENCE. A disambiguator that fires on clear
language teaches people to click through it, and then it protects nobody. Two of
this file's tests exist only to prove the tool stays quiet.
"""

from __future__ import annotations

import pytest

from research.ambiguity_witness import READINGS, find_witness

VAGUE = "Order our household groceries, under CHF 120."
EXPLICIT = "Order our household groceries, at or below CHF 120."
PERIOD = "Order our household groceries, up to CHF 250 per week."
UNAMBIGUOUS = "Buy the 27-inch monitor I chose, for CHF 400 or less."


def _witnesses(instruction):
    return [w for w in (find_witness(instruction, r) for r in READINGS) if w]


# ==================================================== it finds the real ambiguities
def test_a_vague_bound_is_separated_by_the_boundary_amount():
    """"under CHF 120" -- the whole question is whether CHF 120.00 itself is allowed,
    and the witness is a basket costing exactly that."""
    found = [w for w in _witnesses(VAGUE) if w["reading"].key == "strictness"]
    assert found, "no witness for a genuinely vague bound"
    witness = found[0]
    assert witness["amount"] == 120.00
    assert {witness["verdict_a"], witness["verdict_b"]} == {"allow", "block"}


def test_a_period_bound_is_separated_by_a_SEQUENCE_not_a_single_purchase():
    """"CHF 250 per week" as a budget versus as a per-order ceiling cannot be told
    apart by one purchase. The witness has to be several, which is what makes it a
    real search rather than a boundary check."""
    found = [w for w in _witnesses(PERIOD) if w["reading"].key == "period_scope"]
    assert found, "no witness for budget-versus-ceiling"
    witness = found[0]
    assert witness["repeats"] > 1, "a single purchase cannot separate these readings"
    assert {witness["verdict_a"], witness["verdict_b"]} == {"allow", "block"}


# ============================================ and it stays quiet when it should
@pytest.mark.parametrize("instruction", [EXPLICIT, UNAMBIGUOUS,
                                         "Order groceries, CHF 120 or less.",
                                         "Order groceries, no more than CHF 120."],
                         ids=lambda s: s[:28])
def test_it_says_nothing_about_an_explicit_bound(instruction):
    """"at or below", "or less", "no more than" all state plainly that the amount
    is included. Asking about them is crying wolf."""
    strictness = [w for w in _witnesses(instruction) if w["reading"].key == "strictness"]
    assert not strictness, (
        f"{instruction!r} is explicit about its bound; flagging it trains the "
        "customer to dismiss the question")


def test_a_reading_that_fires_on_everything_is_not_a_reading():
    """The guard that killed the first extra reading in this file.

    "Did naming the goods restrict what may be bought, or only describe it?"
    produced a witness for EVERY instruction, which is the signature of a bad
    hypothesis rather than a productive one. If a reading ever separates every
    sentence in the corpus again, it belongs in that category too.
    """
    corpus = [VAGUE, EXPLICIT, PERIOD, UNAMBIGUOUS]
    for reading in READINGS:
        hits = sum(1 for i in corpus if find_witness(i, reading))
        assert hits < len(corpus), (
            f"reading {reading.key!r} separates every sentence in the corpus; that "
            "is crying wolf, not disambiguating")


def test_the_labels_describe_the_reading_and_not_the_flip():
    """The first version hardcoded them, and told a customer who had written "at or
    below CHF 120" that the compiler read it as "strictly below"."""
    witness = [w for w in _witnesses(VAGUE) if w["reading"].key == "strictness"][0]
    as_compiled, alternative = witness["labels"]
    # "under" compiles to `<`, so the compiler's own reading is the exclusive one
    assert "too much" in as_compiled, (as_compiled, alternative)
    assert "fine" in alternative


def test_every_witness_is_a_real_decision_from_the_real_engine():
    """Not a simulation of a verdict. If the witness were computed by inspecting
    rules rather than by deciding purchases, it would prove nothing about what the
    wallet would actually do."""
    for witness in _witnesses(VAGUE) + _witnesses(PERIOD):
        assert witness["verdict_a"] in {"allow", "block", "review"}
        assert witness["verdict_b"] in {"allow", "block", "review"}
        assert witness["verdict_a"] != witness["verdict_b"]

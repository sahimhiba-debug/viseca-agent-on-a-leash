"""Metamorphic properties of the policy compiler, over the five official mandates.

A paraphrase corpus tests wordings someone thought of. Metamorphic testing states
a RELATION that must hold under a transformation, and applies it to every mandate:
transformations that cannot change meaning must not change the policy, and
transformations that must change meaning must change it.

This is where a phrase-pattern compiler is most fragile -- it keys on surface form,
so a comma or a contraction is exactly the kind of thing that can silently move a
rule. Each transformation below says why it belongs in its group.

Policy equality here is the compiled rule SET (field, operator, value, scope,
period_days) plus the uncertainty policy. Rule identity is the right granularity:
`open_questions` are advisory text that may legitimately differ (a reordered
sentence can change which ambiguity is worth mentioning) and are excluded, while
any difference in an enforceable rule is a real change.
"""

from __future__ import annotations

import re

import pytest

from wallet_control.csv_data import load_scenario_catalogue
from wallet_control.policy_compiler import compile_instruction

OFFICIAL = {k: v["cardholder_instruction"] for k, v in load_scenario_catalogue().items()}


def _policy(instruction: str):
    compiled = compile_instruction(instruction)
    return (
        compiled.uncertainty_policy.value,
        frozenset(
            (r.field, r.operator, str(r.value), r.scope or "", r.period_days or 0)
            for r in compiled.hard_rules
        ),
    )


# --- transformations that CANNOT change what the customer asked for ----------------
MEANING_PRESERVING = {
    "trailing whitespace": lambda t: f"  {t}  ",
    "double spaces": lambda t: t.replace(" ", "  "),
    "newlines for spaces": lambda t: t.replace(". ", ".\n"),
    "trailing newline": lambda t: t + "\n",
    "no trailing full stop": lambda t: t.rstrip("."),
    "extra full stop": lambda t: t + ".",
    "contraction do not": lambda t: t.replace("Do not ", "Don't "),
    "uncontract don't": lambda t: t.replace("Don't ", "Do not "),
    "irrelevant sentence appended": lambda t: t + " Thanks very much.",
    "irrelevant sentence prepended": lambda t: "Hello. " + t,
    "polite prefix": lambda t: "Please " + t[0].lower() + t[1:],
    "CHF spacing": lambda t: t.replace("CHF ", "CHF  "),
}

# --- transformations that MUST change what the customer asked on ------------------
MEANING_CHANGING = {
    # NOT here: "drop the uncertainty clause". Removing "Ask me when uncertain" leaves
    # the policy at `ask`, because that IS the default -- so the rules correctly do not
    # move. What must change is that the customer is told the default was assumed, and
    # that is asserted separately below.
    "decline instead of ask": lambda t: t.replace("Ask me when uncertain.", "Decline it when uncertain."),
    "approve instead of ask": lambda t: t.replace("Ask me when uncertain.", "Approve it when uncertain."),
    "ten times the amount": lambda t: re.sub(r"CHF (\d+)", lambda m: f"CHF {int(m.group(1)) * 10}", t, count=1),
}


@pytest.mark.parametrize("scenario_id", sorted(OFFICIAL))
@pytest.mark.parametrize("label", sorted(MEANING_PRESERVING))
def test_meaning_preserving_transformations_do_not_move_the_policy(scenario_id, label):
    original = OFFICIAL[scenario_id]
    transformed = MEANING_PRESERVING[label](original)
    assert _policy(transformed) == _policy(original), (
        f"{scenario_id}: {label!r} changed the enforceable policy"
    )


@pytest.mark.parametrize("scenario_id", sorted(OFFICIAL))
@pytest.mark.parametrize("label", sorted(MEANING_CHANGING))
def test_meaning_changing_transformations_do_move_the_policy(scenario_id, label):
    original = OFFICIAL[scenario_id]
    transformed = MEANING_CHANGING[label](original)
    if transformed == original:
        pytest.skip(f"{label!r} does not apply to {scenario_id}")
    assert _policy(transformed) != _policy(original), (
        f"{scenario_id}: {label!r} should have changed the policy and did not"
    )


@pytest.mark.parametrize("scenario_id", sorted(OFFICIAL))
def test_removing_a_restriction_never_makes_the_policy_larger(scenario_id):
    """Deleting a sentence can only remove constraints. A compiler that ADDS a rule
    when text is removed is reading something that is not there."""
    original = OFFICIAL[scenario_id]
    sentences = [s for s in original.split(". ") if s.strip()]
    if len(sentences) < 2:
        pytest.skip("single-sentence mandate")
    for drop in range(len(sentences)):
        shorter = ". ".join(sentences[:drop] + sentences[drop + 1:])
        if not shorter.endswith("."):
            shorter += "."
        _, fewer = _policy(shorter)
        _, full = _policy(original)
        assert fewer <= full, (
            f"{scenario_id}: dropping sentence {drop} ADDED rules {sorted(fewer - full)}"
        )


@pytest.mark.parametrize("scenario_id", sorted(OFFICIAL))
def test_compilation_is_deterministic(scenario_id):
    """Compiled twice, identical. The mandate a customer confirms must be the mandate
    that gets stored; a compiler with any order-dependence breaks that silently."""
    instruction = OFFICIAL[scenario_id]
    assert _policy(instruction) == _policy(instruction)


@pytest.mark.parametrize("scenario_id", sorted(OFFICIAL))
def test_dropping_the_uncertainty_clause_is_disclosed_rather_than_silent(scenario_id):
    """`ask` is the default, so removing "Ask me when uncertain" leaves the rules
    identical -- correctly. The customer must still be told that a default was
    assumed on their behalf rather than read from what they wrote."""
    original = OFFICIAL[scenario_id]
    stripped = original.replace(" Ask me when uncertain.", "")
    if stripped == original:
        pytest.skip("no uncertainty clause to drop")
    questions = " ".join(compile_instruction(stripped).open_questions).lower()
    assert "no explicit uncertainty preference" in questions, questions


@pytest.mark.parametrize("whitespace", ["  ", "\t", "\n", " \n ", "   "])
def test_whitespace_never_moves_a_rule(whitespace):
    """The fragility this file found. Every pattern in the compiler is written with
    literal spaces, so before normalisation, doubling them lost the per-order ceiling
    in all five official mandates."""
    for instruction in OFFICIAL.values():
        assert _policy(instruction.replace(" ", whitespace)) == _policy(instruction)

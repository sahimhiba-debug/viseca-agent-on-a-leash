"""Does the wallet enforce what the customer asked for, or what the compiler heard?

The engine can be flawless and still enforce the wrong policy, because the first
translation -- English to `hard_rules` -- happens before any of it. This file pins
what that audit found and fixed.

The compiler's module docstring has always claimed it "never treats absence of a
recognizable phrase as silent permission -- unparsed intent becomes an
`open_question` shown to the customer before they confirm". **That claim was false
three ways**, and the third was not a loss but an inversion:

  1. QUANTITY was never represented at all. "Buy ONE ordinary grocery item ..."
     compiled to a policy under which 50 separate CHF 20 purchases were approved
     (CHF 1,000), and a single order with `quantity: 50` was approved too.
  2. RESTRICTIVE PARAPHRASES were silently dropped. Five of eight ordinary wordings
     of the no-add-ons requirement produced no rule -- including "Only add things I
     asked for" -- as did two of eight familiarity wordings.
  3. TEMPORAL SCOPE WAS INVERTED. "up to CHF 250 per week" compiled to
     `billing_amount_chf <= 250 scope=purchase`: a weekly budget became a per-order
     ceiling, so the agent could spend CHF 250 per order indefinitely. The guidance
     then told the customer "Each order must total CHF 250 or less" -- a scope they
     never wrote -- and the open question advised them to consider adding a rolling
     weekly limit, which is precisely what they had written.

An optimiser over 4,800 generated instructions measured the exposure before the fix:
4,032 silent quantity losses, 2,400 temporal, 960 familiarity. After: **0**.

TWO DIFFERENT REPAIRS, deliberately:

  * (3) is a misinterpretation, so it is FIXED -- week/month/day have one ordinary
    meaning in days, and `scope="period"` already expresses it exactly. This can only
    tighten: a period ceiling binds across orders where a purchase ceiling does not.
  * (1) and (2) are absences, so they are DISCLOSED. Broadening patterns fixes the
    paraphrases someone thought of and nothing else; there are indefinitely many ways
    to write a restriction. The coverage check does not try to understand the phrase.
    It notices that the customer used restrictive language of a KIND for which no rule
    exists, and names it back to them before they confirm. It creates no rule and
    changes no decision -- it converts a silent loss into a visible question, which is
    the weakest honest response and the only one that does not require guessing.

Quantity is disclosed rather than enforced because the vocabulary genuinely cannot
express it: `scope` is `purchase` or `period` and technical_details.md closes the set
("No extra rule fields are allowed"). There is no "this many items" and no "this many
orders". Pretending otherwise would be the inventing this project refuses to do.
"""

from __future__ import annotations

import pytest

from wallet_control.csv_data import load_scenario_catalogue
from wallet_control.policy_compiler import compile_instruction

QUANTITY_NOTICE = "specific number of items"


def _questions(instruction: str) -> str:
    return " ".join(compile_instruction(instruction).open_questions).lower()


def _amount_rules(instruction: str):
    """(value, scope, period_days). Operator-free, for the scope assertions below."""
    return [
        (float(r.value), r.scope, r.period_days)
        for r in compile_instruction(instruction).hard_rules
        if r.field == "authorization.billing_amount_chf"
    ]


def _amount_rules_with_operator(instruction: str):
    return [
        (r.operator, float(r.value), r.scope, r.period_days)
        for r in compile_instruction(instruction).hard_rules
        if r.field == "authorization.billing_amount_chf"
    ]


# --------------------------------------------------------------------------- (3)
@pytest.mark.parametrize(
    "phrase,days",
    [("per week", 7), ("a week", 7), ("per month", 30), ("per day", 1),
     ("each week", 7), ("in any 7 days", 7), ("per 14 days", 14)],
)
def test_a_period_qualified_amount_is_a_budget_not_an_order_ceiling(phrase, days):
    rules = _amount_rules(f"Buy clothing for up to CHF 250 {phrase}. Ask me when uncertain.")
    assert (250.0, "period", days) in rules, f"{phrase!r} produced {rules}"
    assert not any(scope == "purchase" for _, scope, _ in rules), (
        f"{phrase!r} also produced a per-order ceiling the customer never wrote: {rules}"
    )


def test_an_unqualified_amount_is_still_an_order_ceiling():
    """The fix must not steal the ordinary reading. "for CHF 20 or less" with no
    period qualifier is a per-order ceiling, as it always was."""
    assert _amount_rules("Buy groceries for CHF 20 or less. Ask me when uncertain.") == [(20.0, "purchase", None)]


def test_both_scopes_survive_when_the_customer_states_both():
    rules = _amount_rules(
        "Order groceries. Keep each order at or below CHF 120 including delivery, and keep the "
        "total across any seven days at or below CHF 300. Ask me when uncertain."
    )
    assert (120.0, "purchase", None) in rules
    assert (300.0, "period", 7) in rules


# --------------------------------------------------------------------------- (1)
@pytest.mark.parametrize(
    "instruction",
    ["Buy one ordinary grocery item for CHF 20 or less. Ask me when uncertain.",
     "Buy exactly one monitor for CHF 400 or less. Ask me when uncertain.",
     "Buy at most one monitor for CHF 400 or less. Ask me when uncertain.",
     "Buy up to three monitors for CHF 400 or less. Ask me when uncertain.",
     "Buy one groceries for up to CHF 250 a week. Ask me when uncertain."],
)
def test_a_quantity_the_vocabulary_cannot_express_is_named_back_to_the_customer(instruction):
    text = _questions(instruction)
    assert QUANTITY_NOTICE in text, instruction
    assert "not enforced" in text, "the disclosure must say plainly that it is not enforced"


def test_the_quantity_notice_does_not_fire_on_the_word_one_used_as_a_pronoun():
    """"a shop that is one I have used before" carries no quantity intent. A bare
    \\bone\\b marker fired on 192 such instructions in the optimiser before it was
    anchored on the verb."""
    assert QUANTITY_NOTICE not in _questions(
        "Buy groceries for CHF 50 or less from a shop that is one I have used before. Ask me when uncertain."
    )


# --------------------------------------------------------------------------- (2)
@pytest.mark.parametrize(
    "clause",
    ["Do not add anything I did not ask for.", "Only add things I asked for.",
     "Do not buy unrequested items.", "Never add extras.", "Buy only requested items.",
     "No extras.", "Do not add extras."],
)
def test_every_no_addons_paraphrase_produces_the_rule_or_says_it_did_not(clause):
    compiled = compile_instruction(f"Buy a monitor for CHF 400 or less. {clause} Ask me when uncertain.")
    has_rule = any(r.field == "item.unrequested_present" for r in compiled.hard_rules)
    disclosed = "forbidding unrequested items" in " ".join(compiled.open_questions)
    assert has_rule or disclosed, f"{clause!r} was dropped in silence"


@pytest.mark.parametrize(
    "clause",
    ["from a shop I use regularly", "from a shop I have used before",
     "from a seller I have bought from before", "from a shop that is one I have used before",
     "only from shops I have used before", "from a familiar shop",
     "from shops I've used before", "from a merchant I have used before"],
)
def test_every_familiarity_paraphrase_produces_the_rule_or_says_it_did_not(clause):
    compiled = compile_instruction(f"Buy groceries for CHF 50 or less {clause}. Ask me when uncertain.")
    has_rule = any(r.field == "merchant.familiar" for r in compiled.hard_rules)
    disclosed = "shop you have used before" in " ".join(compiled.open_questions)
    assert has_rule or disclosed, f"{clause!r} was dropped in silence"


# --------------------------------------------------------------------------- guards
def test_the_five_official_mandates_compile_exactly_as_before():
    """None of this may move the replay. The official amounts and scopes, pinned."""
    expected = {
        "SCEN0000": [(20.0, "purchase", None)],
        "SCEN0001": [(120.0, "purchase", None), (300.0, "period", 7)],
        "SCEN0002": [(200.0, "purchase", None)],
        "SCEN0003": [(250.0, "purchase", None)],
        "SCEN0004": [(400.0, "purchase", None)],
    }
    for scenario_id, scenario in load_scenario_catalogue().items():
        assert sorted(_amount_rules(scenario["cardholder_instruction"])) == sorted(expected[scenario_id]), scenario_id


def test_the_five_official_mandates_keep_their_exact_operators():
    """The OPERATOR is part of the rule and this test did not check it.

    Adding strict-inequality support for "under CHF 50" flipped SCEN0001's per-order
    rule from <= to <, because "at or below CHF 120" contains the word "below". The
    replay did not move -- no official purchase is exactly CHF 120.00 -- so nothing
    failed. A boundary that only bites on one exact value needs an assertion, not a
    replay."""
    expected = {
        "SCEN0000": [("<=", 20.0, "purchase", None)],
        "SCEN0001": [("<=", 120.0, "purchase", None), ("<=", 300.0, "period", 7)],
        "SCEN0002": [("<=", 200.0, "purchase", None)],
        "SCEN0003": [("<=", 250.0, "purchase", None)],
        "SCEN0004": [("<=", 400.0, "purchase", None)],
    }
    for scenario_id, scenario in load_scenario_catalogue().items():
        got = sorted(_amount_rules_with_operator(scenario["cardholder_instruction"]))
        assert got == sorted(expected[scenario_id]), f"{scenario_id}: {got}"


@pytest.mark.parametrize(
    "phrase,operator",
    [("for under CHF 50", "<"), ("for below CHF 50", "<"), ("for less than CHF 50", "<"),
     ("for CHF 50 or less", "<="), ("at or below CHF 50", "<="), ("for no more than CHF 50", "<=")],
)
def test_strict_and_inclusive_limits_are_distinguished(phrase, operator):
    """"under CHF 50" excludes 50; "CHF 50 or less" includes it. Both were <=."""
    rules = _amount_rules_with_operator(f"Buy groceries {phrase}. Ask me when uncertain.")
    assert rules and rules[0][0] == operator, f"{phrase!r} -> {rules}"


def test_the_coverage_check_creates_no_rules():
    """It is disclosure. If it ever produced a rule it could change a decision."""
    with_marker = compile_instruction("Buy one monitor for CHF 400 or less. Ask me when uncertain.")
    without = compile_instruction("Buy a monitor for CHF 400 or less. Ask me when uncertain.")
    assert [r.field for r in with_marker.hard_rules] == [r.field for r in without.hard_rules]
    assert len(with_marker.open_questions) > len(without.open_questions)


@pytest.mark.parametrize(
    "phrase", ["in total", "total", "overall", "altogether", "in all"],
)
def test_an_overall_total_produces_no_order_ceiling_and_says_so(phrase):
    """"no more than CHF 50 IN TOTAL" is the same inversion as "per week", pointing at
    the one scope this vocabulary cannot express at all.

    Reading it as a per-order ceiling told the customer "your CHF 50 limit applies to
    each individual purchase, not to the total" -- contradicting the word they wrote --
    and then explained that a total cannot be set. Creating NO rule and saying so is
    the honest handling; quietly substituting a weaker scope for the one they asked
    for is not.

    Found as a surviving mutant: the behaviour was fixed and disclosed, but nothing
    pinned it, so reverting the fix passed the whole suite.
    """
    compiled = compile_instruction(f"Buy groceries, no more than CHF 50 {phrase}. Ask me when uncertain.")
    amounts = [r for r in compiled.hard_rules if r.field == "authorization.billing_amount_chf"]
    assert not amounts, f"{phrase!r} produced {[(r.operator, r.value, r.scope) for r in amounts]}"
    assert "OVERALL TOTAL" in " ".join(compiled.open_questions), "the loss must be stated"

"""The customer confirms the guidance. The wallet enforces the rules.

Those are two artefacts authored by two different parties -- the customer writes a
sentence, the compiler authors rules, and an explainer authors the plain English
they actually read and agree to. Nothing had ever checked that the last two say the
same thing.

Two real defects came out of asking:

  * "CHF 120 per order, and CHF 300 across any 7 days" compiled to ONE rule -- CHF
    120 as a weekly budget -- because the period pattern's lazy skip jumped over an
    amount. Not silent: every existing safeguard fired and told the customer. Wrong
    all the same.
  * "under CHF 120" enforced `< 120` while the confirmed text said "CHF 120 or
    less". One rappen, in the direction that matters: the text the customer agreed
    to was more permissive than the rule.
"""

from __future__ import annotations

import pytest

from research.confirmation_roundtrip import CORPUS, figures_survive, numeric_fidelity
from wallet_control.policy_compiler import compile_instruction


@pytest.mark.parametrize("instruction", CORPUS, ids=lambda s: s[:34])
def test_the_confirmed_text_states_the_rule_that_is_enforced(instruction):
    """Same number, same operator, same scope, in the words the customer reads."""
    result = numeric_fidelity(instruction)
    assert result["holds"], (
        f"{instruction!r}\n  guidance: {result['guidance']}\n  "
        + "\n  ".join(result["problems"]))


@pytest.mark.parametrize("instruction", CORPUS, ids=lambda s: s[:34])
def test_no_figure_the_customer_wrote_vanishes_without_a_word(instruction):
    result = figures_survive(instruction)
    assert result["holds"], (
        f"{instruction!r}: wrote {result['written']}, rules {result['in_rules']}, "
        f"vanished with no rule and no warning: {result['vanished']}")


# ============================================ the two defects, pinned individually
def test_two_amounts_in_one_sentence_keep_their_own_scopes():
    """The lazy skip used to jump over an amount: CHF 120 paired with "7 days",
    producing a weekly budget of 120 and dropping the 300 entirely."""
    compiled = compile_instruction(
        "Order groceries, at or below CHF 120 per order, and CHF 300 across any 7 days.")
    money = {(r.value, r.scope, r.period_days) for r in compiled.hard_rules
             if r.field == "authorization.billing_amount_chf"}
    assert (120.0, "purchase", None) in money, money
    assert (300.0, "period", 7) in money, money


@pytest.mark.parametrize("phrase,operator,wording", [
    ("Keep each order under CHF 120.", "<", "less than"),
    ("Keep each order at or below CHF 120.", "<=", "or less"),
    ("Nothing over CHF 120.", "<=", "or less"),
])
def test_the_wording_matches_the_operator(phrase, operator, wording):
    """"under" is exclusive. Describing it as "or less" hands the customer a
    confirmation screen one rappen more permissive than the rule behind it."""
    compiled = compile_instruction("Order groceries. " + phrase)
    rule = next(r for r in compiled.hard_rules
                if r.field == "authorization.billing_amount_chf")
    assert rule.operator == operator
    guidance = " ".join(compiled.guidance).lower()
    assert wording in guidance, f"{phrase!r} -> {rule.operator}, guidance says {guidance!r}"


def test_a_period_word_still_pairs_with_its_own_amount():
    """The fix must not break the ordinary case it guards."""
    compiled = compile_instruction("Order groceries at or below CHF 250 per week.")
    money = [r for r in compiled.hard_rules
             if r.field == "authorization.billing_amount_chf"]
    assert [(r.value, r.scope, r.period_days) for r in money] == [(250.0, "period", 7)]

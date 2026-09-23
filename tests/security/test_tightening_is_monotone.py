"""Tightening a mandate must never permit anything it did not permit before.

WHAT THE BRIEF REQUIRES. "The customer must also be able to tighten, update, or
revoke the wallet policy", and `technical_details.md` is explicit that an update may
only narrow: "adding a rule must not weaken a customer's existing restriction".

WHAT THE CODE ARGUED. `Mandate.tighten_hard_rules` only appends, `HardRule` is
frozen, and hard rules are a CONJUNCTION -- so an extra rule is an extra conjunct and
the set can only shrink. Sound about the shape of the code, and this repository has
twice found such arguments to be true of one component and false of the program.

SO IT IS MEASURED, POINTWISE. Not "the set got smaller" but: for every basket in the
world, the verdict after tightening is no more permissive than before. That is
strictly stronger -- a change that refused one purchase and permitted another would
keep the count and still be a widening.

AND IT WAS FALSE. `item.unrequested_present` is evaluated against the categories the
mandate's OWN `item.category` rules name, so one rule's meaning depends on another
rule's presence:

    "nothing unrequested"                        review   (unknown: nothing to compare against)
    "nothing unrequested" + "groceries only"     ALLOW    (pass: basket matches)

Appending a rule -- the canonical tightening -- made the wallet MORE permissive,
because the second rule supplied the fact the first one needed. Reachable from a
plain sentence: "Do not add anything I did not ask for." compiled to exactly that,
alone, with no flag.

THE FIX IS AT THE SOURCE, NOT AT THE PATCH BOUNDARY. An unenforceable rule is no
longer compiled into a rule at all; it is reported as unsupported intent, which is
shown to the customer and blocks automatic confirmation. Policing monotonicity when
PATCH is called would have left the engine able to hold a mandate that means nothing.
"""

from __future__ import annotations

import pytest

from research.tightening import ADDITIONS, sweep
from wallet_control.policy_compiler import compile_instruction


@pytest.fixture(scope="module")
def swept():
    return sweep()


def test_the_sweep_compares_enough_to_mean_something(swept):
    assert swept["baskets"] > 500 and swept["additions"] >= 10
    assert swept["checked"] > 5000, swept


def test_no_tightening_makes_any_purchase_more_permissive(swept):
    """THE ASSERTION. Every basket, every added rule, plus the uncertainty dial."""
    assert swept["violations"] == [], swept["violations"][:5]


def test_the_additions_include_rules_that_actually_bite():
    """Without this, "no tightening widened anything" would be satisfied by a list of
    rules none of which changed a single verdict."""
    from research.tightening import BASE, _verdicts
    from wallet_control.scope import _categories

    compiled = compile_instruction(BASE)
    base_rules = list(compiled.hard_rules)
    category = _categories(base_rules)
    before = _verdicts(base_rules, compiled.uncertainty_policy, category)

    moved = 0
    for rule in ADDITIONS:
        after = _verdicts(base_rules + [rule], compiled.uncertainty_policy, category)
        if any(after[k] != before[k] for k in before):
            moved += 1
    assert moved >= 4, f"only {moved} of the added rules changed any verdict"


def test_an_unenforceable_rule_is_not_compiled_into_a_rule():
    """The source of the one violation that existed. "Unrequested" needs "requested";
    without it the rule answers `unknown` for every purchase, and the missing fact
    arriving later is what made appending a rule widen the policy."""
    alone = compile_instruction("Do not add anything I did not ask for.")
    assert [r.field for r in alone.hard_rules] == []
    assert any("never says WHAT you requested" in u
               for u in alone.unsupported_restrictions)

    with_subject = compile_instruction(
        "Order our household groceries. Do not add anything I did not ask for.")
    fields = [r.field for r in with_subject.hard_rules]
    assert "item.unrequested_present" in fields and "item.category" in fields


def test_the_engine_still_needs_the_pair_and_we_do_not_pretend_otherwise():
    """HONEST SCOPE. The compiler can no longer produce the unenforceable mandate;
    the ENGINE would still evaluate one if it were handed it directly. That is not a
    reachable state through the customer API -- mandates are created from an
    instruction, and PATCH only appends to one that was compiled -- but the invariant
    lives in the compiler, so a future caller that builds rules by hand would have to
    re-establish it. Written down rather than assumed away."""
    from tests.helpers import make_event, make_mandate
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.mandate import HardRule
    from wallet_control.state import HistoryIndex, RunState

    unrequested = HardRule(field="item.unrequested_present", operator="=", value="false")
    mandate = make_mandate(hard_rules=[unrequested])
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})},
                                          available=True), card_id="CA_TEST")
    result = evaluate_authorization(make_event(mandate=mandate, amount=50.0),
                                    mandate, state)
    assert result.decision == "review", (
        "a rule with nothing to compare against must be unknown, not satisfied")

"""Adding a line to a basket must never make a decision more permissive.

Call it basket monotonicity. It is not a rule the customer wrote; it is a property
the evidence model must have, because the alternative is that an agent improves its
odds by submitting LESS information.

`item.size` violated it. A basket of two requested items -- one stating "size 43",
one silent -- passed on the strength of the first, while the silent item alone
escalated. So saying nothing beat lying: an explicit "size 38" was caught, silence
was not. The return-window logic already refused exactly this aggregation
("a silent item's terms are unknown, not whatever the other line said"); the size
rule had not been given the same treatment.
"""

from __future__ import annotations

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex, RunState

M = "ME_KNOWN"
_SEVERITY = {"allow": 0, "review": 1, "block": 2}


def _mandate():
    return make_mandate(
        instruction="Replace my road-running shoes in size 43.",
        hard_rules=[
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=500,
                     currency="CHF", scope="purchase"),
            HardRule(field="item.category", operator="in", value=["sporting_goods"]),
            HardRule(field="item.size", operator="=", value="43"),
        ])


def _line(n, details, name="Road-running shoe", category="sporting_goods"):
    return {"line_no": n, "item_id": f"I{n}", "item_name": name, "item_category": category,
            "quantity": 1, "unit_price": 150.0, "currency": "CHF", "item_details": details}


def _decide(items):
    mandate = _mandate()
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({M})}, available=True), card_id="CA_TEST")
    event = make_event(mandate=mandate, authorization_id="A1", amount=300.0, merchant_id=M, items=items)
    return evaluate_authorization(event, mandate, state).decision


def test_a_silent_line_does_not_inherit_a_size_stated_elsewhere():
    """THE ATTACK. A cheap decoy stating the requested size, beside the item the
    customer would actually receive, which states nothing."""
    assert _decide([_line(1, "size 43")]) == "allow"
    assert _decide([_line(1, "size 43"), _line(2, "")]) != "allow"


def test_stating_nothing_is_never_better_for_the_agent_than_stating_the_wrong_thing():
    """Before the fix, an explicit wrong size was blocked while silence was approved.
    A system that rewards withholding evidence teaches an adversary to withhold it."""
    wrong = _decide([_line(1, "size 43"), _line(2, "size 38")])
    silent = _decide([_line(1, "size 43"), _line(2, "")])
    assert _SEVERITY[silent] >= _SEVERITY[wrong] - 1, (
        f"silence ({silent}) was treated more favourably than a wrong claim ({wrong})")
    assert silent != "allow"


@pytest.mark.parametrize("added", ["", "size 38", "size 43"])
def test_adding_a_line_never_makes_the_decision_more_permissive(added):
    """Basket monotonicity, stated generally."""
    before = _decide([_line(1, "size 43")])
    after = _decide([_line(1, "size 43"), _line(2, added)])
    assert _SEVERITY[after] >= _SEVERITY[before], (
        f"adding a line moved the decision from {before} to {after}")


def test_a_line_outside_the_requested_category_is_not_asked_for_a_size():
    """The other half: the fix must not demand a shoe size from a protection plan.
    `_candidate_items` already filters to the requested category, and this pins it --
    otherwise every mixed basket would escalate for the wrong reason."""
    assert _decide([_line(1, "size 43"),
                    _line(2, "", name="Extended protection plan", category="subscriptions")]) != "review"


def test_all_lines_silent_still_escalates():
    assert _decide([_line(1, ""), _line(2, "")]) == "review"


# --- monotonicity as a general property, not a per-rule fix -----------------------


def test_basket_monotonicity_holds_across_random_mandates_and_baskets():
    """Fuzzed over random mandates, baskets and added lines.

    This found that the FIRST version of the size fix broke the property it was
    written for: by testing for silence before testing for a mismatch, an adversary
    could soften a definite FAIL into a REVIEW by appending an evidence-free line --
    24 violations in 4,000 baskets. Negative evidence has to be decisive first;
    silence is only the open question once nothing contradicts the requirement.
    """
    import random

    categories = ["sporting_goods", "electronics", "groceries", "subscriptions", "gift_card"]
    names = ["Road-running shoe", "27-inch monitor", "Weekly basket",
             "Extended protection plan", "Digital gift voucher"]
    details = ["", "size 43", "size 38", "returns accepted within 30 days",
               "clearance line, sold as final sale", "size 43; returns accepted within 30 days"]
    optional = [
        HardRule(field="item.category", operator="in", value=["sporting_goods"]),
        HardRule(field="item.category", operator="in", value=["electronics"]),
        HardRule(field="item.size", operator="=", value="43"),
        HardRule(field="item.name_contains", operator="=", value="road-running"),
        HardRule(field="order.return_window_days", operator=">=", value=14),
        HardRule(field="item.unrequested_present", operator="=", value="false"),
    ]

    def decide(mandate, items, returnable):
        state = RunState(history=HistoryIndex({"CA_TEST": frozenset({M})}, available=True),
                         card_id="CA_TEST")
        event = make_event(mandate=mandate, authorization_id="A1",
                           amount=50.0 * len(items), merchant_id=M, items=items)
        event["authorization"]["order_returnable"] = returnable
        return evaluate_authorization(event, mandate, state).decision

    rng = random.Random(2026)
    for _ in range(400):
        rules = [HardRule(field="authorization.billing_amount_chf", operator="<=",
                          value=10000, currency="CHF", scope="purchase")]
        rules += rng.sample(optional, rng.randint(1, 3))
        mandate = make_mandate(instruction="Buy road-running shoes in size 43.", hard_rules=rules)
        size = rng.randint(1, 3)
        basket = [_line(i + 1, rng.choice(details), rng.choice(names), rng.choice(categories))
                  for i in range(size)]
        extra = _line(size + 1, rng.choice(details), rng.choice(names), rng.choice(categories))
        returnable = rng.choice(["true", "false", "unknown", "not_applicable"])

        before = decide(mandate, basket, returnable)
        after = decide(mandate, basket + [extra], returnable)
        assert _SEVERITY[after] >= _SEVERITY[before], (
            f"adding a line relaxed {before} -> {after}; rules="
            f"{[r.field for r in rules]} returnable={returnable}")

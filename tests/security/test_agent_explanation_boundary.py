"""What the agent may learn from a decision, and what it may never learn.

The wallet is an ORACLE. Every decision system is: ALLOW versus BLOCK is one bit, and
bits accumulate. Measured on this engine, an agent that sees only the decision
recovers a secret CHF 137 ceiling to within CHF 0.24 in twelve probes -- and spends
CHF 531.49 of the customer's money doing it, because every ALLOW probe is a real
purchase it must keep. That cost is the only thing that makes the oracle tolerable,
and it cannot be removed without removing the wallet.

What CAN be removed is the shortcut. The customer's payload carries the rule's
numeric `value` and twenty evidence strings reading "projected 7-day spend=287.50
CHF". For the customer that is correct -- they own the policy and are entitled to read
it. Handed to the agent, it collapses twelve probes to zero.

So the boundary is not *whether* to explain but *to whom*, and these tests are what
keeps the two audiences apart. They are deliberately paranoid: the agent projection is
searched for any digit, any dotted rule field, and any evidence text, because the
failure mode is someone later "just adding one useful field".
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import agent_view, evaluate_authorization
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.state import HistoryIndex, RunState

MERCHANT = "ME_KNOWN"
AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
SECRET_CEILING = 137.0
SECRET_WINDOW = 289.0


def _mandate(policy=UncertaintyPolicy.ASK):
    return make_mandate(
        instruction="Order our household groceries.",
        uncertainty_policy=policy,
        hard_rules=[
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=SECRET_CEILING, currency="CHF", scope="purchase"),
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=SECRET_WINDOW, currency="CHF", scope="period", period_days=7),
            HardRule(field="merchant.familiar", operator="=", value="true"),
            HardRule(field="item.category", operator="in", value=["groceries"]),
            HardRule(field="order.return_window_days", operator=">=", value=14),
        ],
    )


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT})}, available=True), card_id="CA_TEST")


def _decide(mandate, state, amount, *, aid="AU1", hours=0, category="groceries",
            merchant=MERCHANT, details="returns accepted within 30 days", returnable="true"):
    event = make_event(mandate=mandate, authorization_id=aid, amount=amount,
                       merchant_id=merchant, timestamp=AT + timedelta(hours=hours))
    # Distinct item names per authorization: identical baskets at one merchant trip
    # duplicate suspicion, which would make a period-breach fixture read "review".
    event["authorization"]["items"][0].update(item_name=f"food {aid}", item_category=category, item_details=details)
    event["authorization"]["order_returnable"] = returnable
    return evaluate_authorization(event, mandate, state)


# --------------------------------------------------------------- the leak invariant
POLICY_NUMBERS = (str(SECRET_CEILING), "137", str(SECRET_WINDOW), "289", "14")


@pytest.mark.parametrize(
    "amount,category,merchant,details,returnable",
    [
        (9999.0, "groceries", MERCHANT, "returns accepted within 30 days", "true"),   # amount
        (50.0, "jewellery", MERCHANT, "returns accepted within 30 days", "true"),      # item
        (50.0, "groceries", "ME_STRANGE", "returns accepted within 30 days", "true"),  # merchant
        (50.0, "groceries", MERCHANT, "", "unknown"),                                  # order terms
        (136.99, "groceries", MERCHANT, "returns accepted within 30 days", "true"),    # allow, near the edge
    ],
)
def test_agent_view_leaks_no_policy_values(amount, category, merchant, details, returnable):
    """The agent projection must contain NO number from the policy, no rule field name,
    and no evidence string -- whatever the decision."""
    mandate = _mandate()
    decision = _decide(mandate, _state(), amount, category=category, merchant=merchant,
                       details=details, returnable=returnable)
    blob = json.dumps(agent_view(decision))

    for number in POLICY_NUMBERS:
        assert number not in blob, f"policy value {number!r} leaked to the agent: {blob}"
    assert not re.search(r"\d+\.\d+", blob), f"a decimal figure leaked to the agent: {blob}"
    assert "billing_amount_chf" not in blob and "merchant.familiar" not in blob, blob
    for evidence in decision.evidence:
        assert evidence not in blob, "an evidence string reached the agent"
    assert decision.customer_message not in blob, "the customer message reached the agent"


def test_the_customer_by_contrast_does_see_the_policy():
    """The other half of the invariant. If the customer surface were also stripped,
    this file would be describing a wallet that explains nothing to anyone."""
    mandate = _mandate()
    decision = _decide(mandate, _state(), 9999.0)
    assert "CHF" in decision.customer_message
    assert any("billing_amount_chf" in e for e in decision.evidence)


def test_a_period_breach_and_an_oversized_order_are_told_apart():
    """They used to read the same, and this test used to assert that they must.

    The justification on record was that separating them "would let the agent learn
    WHICH bound it hit and probe the two independently -- twice the information per
    purchase". That was an assertion, and when it was finally measured it did not
    hold. A hostile agent binary-searching the per-order cap while a window cap also
    exists converges IDENTICALLY under both schemes -- 11 probes, a final gap of
    CHF 0.20, CHF 100 of the customer's money spent -- because the agent chooses the
    amount it proposes and can therefore isolate the two bounds by construction. It
    never needed the wallet to tell it apart.

    Measured with one probing strategy, not proved over all of them. What it does
    show is that the stated cost of separating these classes was overstated.

    The benefit is not in doubt: "this one order is too large" and "the rolling
    allowance is used up" call for different moves. The first is fixed by a cheaper
    basket of any size; the second only by fitting what remains, and once the
    remainder is smaller than anything on sale, not by shopping at all. Collapsing
    them made the agent answer two different economic situations identically.
    """
    mandate, state = _mandate(), _state()
    _decide(mandate, state, 100.0, aid="A", hours=0)
    _decide(mandate, state, 100.0, aid="B", hours=1)
    period = _decide(mandate, state, 100.0, aid="C", hours=2)     # pushes the 7-day window over
    oversized = _decide(_mandate(), _state(), 9999.0, aid="D")

    assert period.decision == "block" and oversized.decision == "block"
    assert agent_view(period)["blocked_by"] == ["budget_window"]
    assert "amount" in agent_view(oversized)["blocked_by"]


def test_the_budget_window_class_still_carries_no_number():
    """Naming the KIND of bound must not become naming the bound. The agent may
    learn that a rolling allowance exists and is currently binding; never the cap,
    never the remainder, never the window length."""
    mandate, state = _mandate(), _state()
    for hours, aid in ((0, "W1"), (1, "W2")):
        _decide(mandate, state, 100.0, aid=aid, hours=hours)
    view = agent_view(_decide(mandate, state, 100.0, aid="W3", hours=2))

    assert view["blocked_by"] == ["budget_window"]
    blob = json.dumps(view)
    assert not re.search(r"\d+\.\d+", blob), blob
    for leak in ("300", "period", "7", "days", "remaining", "spent", "window_days"):
        assert leak not in blob.replace("budget_window", ""), f"{leak!r} leaked: {blob}"


def test_the_agent_is_told_when_a_human_is_deciding_but_not_why():
    """"wait" is actionable and carries no policy. "the seller did not state the return
    window" is the customer's business."""
    mandate = _mandate()
    review = _decide(mandate, _state(), 50.0, details="", returnable="unknown")
    assert review.decision == "review"
    view = agent_view(review)
    assert view["awaiting_customer"] is True
    assert "return" not in json.dumps(view).lower()


def test_agent_view_is_a_projection_and_changes_no_decision():
    """It reads a decision that has already been made. If it could influence one, it
    would be part of the engine rather than a view of it."""
    mandate, state = _mandate(), _state()
    first = _decide(mandate, state, 50.0, aid="P1")
    agent_view(first)
    second = _decide(mandate, _state(), 50.0, aid="P1")
    assert first.decision == second.decision
    assert sum(a for _, a in state._approved_spend) == 50.0

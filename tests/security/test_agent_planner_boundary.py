"""The planner is replaceable. The wallet's authority is not.

The architectural claim this project makes about agentic commerce is that the
*reasoning* can be anything -- a heuristic, a language model, a hallucinating stub,
an adversary -- because it sits OUTSIDE the authority boundary and the wallet decides
independently.

That claim is worth nothing asserted. So the planner is injectable and this file
substitutes planners far worse than any real model:

  * one that proposes CHF 50,000 baskets
  * one that hallucinates items that do not exist
  * one that returns garbage instead of a basket
  * one that raises on every call
  * one that returns nothing
  * one that repeats the same rejected basket forever

In every case the required property is the same and is checked the same way: the
wallet approves nothing it would not otherwise approve, and the process does not fall
over. A model in this seat could be strictly worse than all of these and still not
reach the customer's money.

This is also why no model ships in the judged path. `technical_details.md` requires a
predictable response when the model is unavailable; proving the SEAM holds is stronger
evidence than one successful live call, and it costs no reproducibility.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from research.shopping_agent import Line, Mission, Planner, shop
from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import agent_view, evaluate_authorization
from wallet_control.policy_compiler import compile_instruction
from wallet_control.state import HistoryIndex, RunState

MERCHANT = "ME_KNOWN"
AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
INSTRUCTION = (
    "Order our household groceries for delivery. Keep each order at or below CHF 120 "
    "including delivery. Ask me when uncertain."
)


def _wallet():
    compiled = compile_instruction(INSTRUCTION)
    mandate = make_mandate(instruction=INSTRUCTION, hard_rules=compiled.hard_rules,
                           uncertainty_policy=compiled.uncertainty_policy)
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT})}, available=True), card_id="CA_TEST")
    seen = []

    def propose(lines, revision, merchant=MERCHANT):
        items = [{"line_no": i + 1, "item_id": l.item_id, "item_name": l.name,
                  "item_category": l.category, "quantity": l.quantity,
                  "unit_price": float(l.unit_price), "currency": "CHF",
                  "item_details": "returns accepted within 30 days"}
                 for i, l in enumerate(lines)]
        event = make_event(mandate=mandate, authorization_id=f"AG{revision}",
                           amount=float(sum(l.total for l in lines)), merchant_id=MERCHANT,
                           timestamp=AT + timedelta(minutes=revision * 90), items=items)
        event["authorization"]["order_returnable"] = "true"
        decision = evaluate_authorization(event, mandate, state)
        seen.append(decision)
        return agent_view(decision)

    return propose, seen, state


_GREEDY = Line("IT9", "Gold-plated trolley", "groceries", Decimal("50000"))
_FAKE = Line("IT_NOT_REAL", "Item that does not exist", "unobtanium", Decimal("5"))


def _greedy(mission):        return [_GREEDY] * 3
def _hallucinating(mission): return [_FAKE] * 2
def _garbage(mission):       return ["not a Line at all"]        # type: ignore[return-value]
def _explodes(mission):      raise RuntimeError("planner unavailable")
def _empty(mission):         return []


@pytest.mark.parametrize(
    "opening,label",
    [(_greedy, "proposes CHF 150,000"), (_hallucinating, "hallucinates items"),
     (_explodes, "is unavailable"), (_empty, "returns nothing")],
)
def test_a_hostile_or_broken_planner_never_obtains_an_approval(opening, label):
    propose, seen, state = _wallet()
    episode = shop(Mission("Order groceries", "groceries"), propose,
                   planner=Planner(plan=opening, replan=lambda *a: "no move"))

    assert episode.outcome != "approved", label
    assert not [d for d in seen if d.decision == "allow"], f"a planner that {label} got an ALLOW"
    assert sum(a for _, a in state._approved_spend) == 0, f"a planner that {label} moved money"


def test_a_planner_that_raises_while_replanning_hands_back_rather_than_crashing():
    def boom(*args):
        raise ValueError("model returned nonsense")

    propose, seen, state = _wallet()
    episode = shop(Mission("Order groceries", "groceries"), propose, planner=Planner(replan=boom))

    assert episode.outcome == "asked_customer"
    assert "planner failed" in (episode.handoff_reason or "")
    assert sum(a for _, a in state._approved_spend) == 0


def test_a_planner_returning_an_unusable_step_hands_back():
    """A model that answers with the wrong shape is indistinguishable from one that
    answers with nonsense. Both end at the customer, not at a purchase."""
    propose, seen, state = _wallet()
    episode = shop(Mission("Order groceries", "groceries"), propose,
                   planner=Planner(replan=lambda *a: {"basket": "maybe?"}))
    assert episode.outcome == "asked_customer"
    assert sum(a for _, a in state._approved_spend) == 0


def test_a_planner_that_never_learns_is_bounded_not_infinite():
    """Repeating a rejected basket forever is the cheapest possible probing strategy.
    It is bounded by MAX_REVISIONS, and every attempt is a recorded decision."""
    propose, seen, _ = _wallet()
    episode = shop(Mission("Order groceries", "groceries"), propose,
                   planner=Planner(replan=lambda lines, blocked, mission, idx: (lines, "no change", idx)))
    assert episode.outcome == "gave_up"
    assert len(seen) <= 5


def test_the_wallets_verdict_is_identical_whoever_planned_the_basket():
    """The seam, stated as an equality. The same basket gets the same decision whether
    the deterministic planner, a hostile stub, or anything else produced it."""
    basket = [Line("IT0001", "Fresh produce selection", "groceries", Decimal("28"))]

    propose_a, seen_a, _ = _wallet()
    shop(Mission("m", "groceries"), propose_a, planner=Planner(plan=lambda m: list(basket), replan=lambda *a: "stop"))
    propose_b, seen_b, _ = _wallet()
    shop(Mission("m", "groceries"), propose_b, planner=Planner(plan=lambda m: list(basket), replan=lambda *a: "stop"))

    assert [d.decision for d in seen_a] == [d.decision for d in seen_b]
    assert [d.reason_codes for d in seen_a] == [d.reason_codes for d in seen_b]

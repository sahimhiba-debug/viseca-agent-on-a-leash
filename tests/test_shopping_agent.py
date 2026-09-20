"""The agent adapts to a refusal without learning the limit it hit.

This is the project's agentic-depth claim, and it is only worth making if both halves
hold: the agent must genuinely recover from a BLOCK, and it must do so WITHOUT being
handed the policy. The second half is what separates adapting from extracting.

The visible proof is where it lands. An agent that had been told "CHF 120" would
propose CHF 119.99. This one overshoots downward to CHF 87, because all it ever
learned was the word "amount".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from research.shopping_agent import MAX_REVISIONS, Line, plan, revise, shop
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


def _wallet(instruction=INSTRUCTION, *, state_return_window=True):
    compiled = compile_instruction(instruction)
    mandate = make_mandate(instruction=instruction, hard_rules=compiled.hard_rules,
                           uncertainty_policy=compiled.uncertainty_policy)
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT})}, available=True), card_id="CA_TEST")
    seen = []

    def propose(lines, revision):
        items = [{"line_no": i + 1, "item_id": l.item_id, "item_name": l.name,
                  "item_category": l.category, "quantity": l.quantity,
                  "unit_price": float(l.unit_price), "currency": "CHF",
                  "item_details": "returns accepted within 30 days" if state_return_window else ""}
                 for i, l in enumerate(lines)]
        event = make_event(mandate=mandate, authorization_id=f"AG{revision}",
                           amount=float(sum(l.total for l in lines)), merchant_id=MERCHANT,
                           timestamp=AT + timedelta(minutes=revision * 90), items=items)
        event["authorization"]["order_returnable"] = "true" if state_return_window else "unknown"
        decision = evaluate_authorization(event, mandate, state)
        seen.append(decision)
        return agent_view(decision)

    return propose, seen, state


def test_the_agent_recovers_from_a_block_and_succeeds_on_the_merits():
    propose, seen, state = _wallet()
    episode = shop("Order the household groceries", "groceries", propose)

    assert episode.outcome == "approved"
    assert len(episode.attempts) > 1, "the fixture must actually force a refusal"
    assert episode.attempts[0].agent_view["decision"] == "block"
    assert episode.attempts[-1].agent_view["decision"] == "allow"
    # monotonically cheaper: the agent moves in one direction only
    amounts = [a.amount_chf for a in episode.attempts]
    assert amounts == sorted(amounts, reverse=True), amounts
    # and the approval is a real one, recorded by the wallet
    assert sum(a for _, a in state._approved_spend) == episode.attempts[-1].amount_chf


def test_the_agent_never_learns_the_ceiling_it_was_refused_by():
    """The security half. If the agent had the number it would land on it."""
    propose, _, _ = _wallet()
    episode = shop("Order the household groceries", "groceries", propose)
    ceiling = Decimal("120")
    approved = episode.attempts[-1].amount_chf

    assert approved < ceiling
    assert ceiling - approved > Decimal("5"), (
        f"landed at CHF {approved}, suspiciously close to the CHF {ceiling} limit -- "
        "an agent that adapts overshoots; one that extracts does not"
    )
    for attempt in episode.attempts:
        assert set(attempt.agent_view) == {"authorization_id", "decision", "blocked_by", "awaiting_customer"}


def test_the_agent_stops_and_waits_when_a_human_is_asked():
    """A step-up is not a refusal to route around. Retrying it would be the agent
    trying to outrun the customer."""
    # The seller states no return window, so the wallet genuinely cannot decide and
    # must ask the customer -- the only situation in which the agent should wait.
    propose, _, _ = _wallet(
        "Order our household groceries, at or below CHF 900, only if returnable within "
        "14 days. Ask me when uncertain.",
        state_return_window=False,
    )
    episode = shop("Order the household groceries", "groceries", propose)
    assert episode.outcome == "awaiting_customer"
    assert len(episode.attempts) == 1, "the agent must not keep proposing while a human decides"


def test_the_agent_gives_up_rather_than_probing_forever():
    """Bounded revisions. Unbounded adaptation is cheap probing wearing a costume."""
    propose, seen, _ = _wallet(
        "Order our household groceries. Keep each order at or below CHF 1. Ask me when uncertain."
    )
    episode = shop("Order the household groceries", "groceries", propose)
    assert episode.outcome == "gave_up"
    assert len(episode.attempts) <= MAX_REVISIONS + 1


def test_adaptation_cannot_create_authority():
    """A revised basket is re-decided from scratch against the same mandate. The loop
    consumes delegation; it never widens it."""
    propose, seen, _ = _wallet()
    shop("Order the household groceries", "groceries", propose)
    for decision in seen:
        if decision.decision == "allow":
            assert all(e.outcome == "pass" for e in decision.rule_evaluations), (
                "an approval was reached with a rule still failing"
            )


def test_revise_returns_none_when_it_has_no_move_left():
    """The agent must be able to say "I cannot do this", or `shop` would loop."""
    assert revise([Line("I1", "x", "groceries", Decimal("10"))], ["merchant"]) is None
    assert revise([Line("I1", "x", "groceries", Decimal("10"))], []) is None


def test_the_runtime_never_imports_the_agent():
    """The wallet must run identically with this file deleted. The agent is a client,
    and blurring that is the one boundary this project exists to draw."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "wallet_control"
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in getattr(node, "names", [])] + [getattr(node, "module", "") or ""]
                assert not any("shopping_agent" in n or n.startswith("research") for n in names), path

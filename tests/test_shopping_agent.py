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

import pytest

from research.shopping_agent import MAX_REVISIONS, Line, Mission, replan, shop
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

    def propose(lines, revision, merchant=MERCHANT):
        items = [{"line_no": i + 1, "item_id": l.item_id, "item_name": l.name,
                  "item_category": l.category, "quantity": l.quantity,
                  "unit_price": float(l.unit_price), "currency": "CHF",
                  "item_details": "returns accepted within 30 days" if state_return_window else ""}
                 for i, l in enumerate(lines)]
        event = make_event(mandate=mandate, authorization_id=f"AG{revision}",
                           amount=float(sum(l.total for l in lines)),
                           merchant_id=merchant,
                           timestamp=AT + timedelta(minutes=revision * 90), items=items)
        event["authorization"]["order_returnable"] = "true" if state_return_window else "unknown"
        decision = evaluate_authorization(event, mandate, state)
        seen.append(decision)
        return agent_view(decision)

    return propose, seen, state


def test_the_agent_recovers_from_a_block_and_succeeds_on_the_merits():
    propose, seen, state = _wallet()
    episode = shop(Mission("Order the household groceries", "groceries"), propose)

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
    episode = shop(Mission("Order the household groceries", "groceries"), propose)
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
    episode = shop(Mission("Order the household groceries", "groceries"), propose)
    assert episode.outcome == "awaiting_customer"
    assert len(episode.attempts) == 1, "the agent must not keep proposing while a human decides"


def test_the_agent_gives_up_rather_than_probing_forever():
    """Bounded revisions. Unbounded adaptation is cheap probing wearing a costume."""
    propose, seen, _ = _wallet(
        "Order our household groceries. Keep each order at or below CHF 1. Ask me when uncertain."
    )
    episode = shop(Mission("Order the household groceries", "groceries"), propose)
    assert episode.outcome in ("gave_up", "asked_customer")
    assert len(episode.attempts) <= MAX_REVISIONS + 1


def test_adaptation_cannot_create_authority():
    """A revised basket is re-decided from scratch against the same mandate. The loop
    consumes delegation; it never widens it."""
    propose, seen, _ = _wallet()
    shop(Mission("Order the household groceries", "groceries"), propose)
    for decision in seen:
        if decision.decision == "allow":
            assert all(e.outcome == "pass" for e in decision.rule_evaluations), (
                "an approval was reached with a rule still failing"
            )


def test_replan_hands_back_to_the_customer_when_it_has_no_move_left():
    """The agent must be able to say "only you can fix this", or `shop` would loop.
    A handoff is a RESULT, not a failure -- collapsing the two was the old design's
    mistake, and it is why it gave up on five of nine adversarial episodes.

    `merchant` used to be listed here too, on the reasoning that only a customer can
    change which shop is acceptable. That was wrong: the agent cannot change the
    RULE, but it can go to a different shop, and refusing to was how four of eleven
    benchmark episodes were lost with a valid alternative sitting in the catalogue.
    What remains here is the genuinely unanswerable: a refusal with no stated reason,
    and one aimed at the agent's own conduct rather than at the goods."""
    mission = Mission("m", "groceries")
    one = [Line("I1", "x", "groceries", Decimal("10"))]
    assert isinstance(replan(one, [], mission, 0), str)
    for behavioural in ("session", "duplicate", "other"):
        assert isinstance(replan(one, [behavioural], mission, 0), str), behavioural


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


# ===================================================== Phase 4: adversarial episodes
_L = lambda n, p, c="groceries": Line(f"I{n}", n, c, Decimal(str(p)))
_TWO_SHOPS = Mission("Order groceries", "groceries", merchants=("ME0001", "ME0002"))


@pytest.mark.parametrize(
    "label,lines,blocked,expect",
    [
        ("cheapest item unavailable", [_L("a", 95), _L("b", 60)], ["amount"], "replan"),
        ("one item must be removed", [_L("a", 95), _L("b", 60), _L("c", 50)], ["amount"], "replan"),
        ("removal creates a new violation", [_L("a", 95), _L("b", 60, "jewellery")], ["amount", "item"], "replan"),
        ("merchant rejected", [_L("a", 95)], ["merchant"], "replan"),
        ("shop refused AND goods too dear", [_L("a", 95)], ["merchant", "amount"], "replan"),
        ("unrequested item in basket", [_L("a", 95), _L("x", 5, "jewellery")], ["basket"], "replan"),
        ("return policy uncertain", [_L("a", 95)], ["order_terms"], "replan"),
        ("security review: duplicate", [_L("a", 95)], ["duplicate"], "ask"),
        ("session integrity", [_L("a", 95)], ["session"], "ask"),
        ("no reason the agent can act on", [_L("a", 95)], [], "ask"),
    ],
)
def test_the_agent_either_replans_or_asks_but_never_stalls(label, lines, blocked, expect):
    """The old agent gave up on five of these nine. Giving up and handing back are
    different outcomes, and collapsing them is what made it look like a heuristic
    rather than a planner: "only you can fix this" is a RESULT."""
    step = replan(lines, blocked, _TWO_SHOPS, 0)
    if expect == "ask":
        assert isinstance(step, str), f"{label}: expected a handoff, got a replan"
    else:
        assert isinstance(step, tuple) and step[0], f"{label}: expected a replan, got {step!r}"


def test_the_agent_does_not_answer_a_refusal_by_shrinking():
    """Dropping a line loses mission value. A planner whose only move is subtraction
    is a heuristic, and measurably so: the old one answered every refusal by deleting
    its most expensive line, which in benchmark episode K deleted the single basket
    that was actually allowed.

    The new agent re-searches instead, so the test is no longer "it substituted" but
    the stronger "it did not lose ground": told the total was refused, it comes back
    with a cheaper basket that is no smaller than the one it had."""
    mission = Mission("m", "groceries", target_lines=2)
    before = [_L("a", 95), _L("b", 60)]
    step = replan(before, ["amount"], mission, 0)
    assert isinstance(step, tuple), step
    new, why, _ = step
    assert len(new) >= len(before), "the basket lost a line the customer asked for"
    assert sum(l.total for l in new) < sum(l.total for l in before), why


# ====================================== Phase 4: the two properties, named explicitly
def test_NO_POLICY_EXTRACTION():
    """Across a whole episode, nothing the agent observes carries a numeric policy
    value, and the basket it settles on is not at the boundary.

    This is NOT a claim that ALLOW/BLOCK leaks nothing -- it demonstrably leaks about
    one bit per purchase, and we say so. The property is narrower and testable: the
    agent-facing interface adds NO numerical policy information beyond the decision
    signal and a safe constraint class.
    """
    import json
    import re

    propose, _, _ = _wallet()
    episode = shop(Mission("Order the household groceries", "groceries"), propose)
    observed = json.dumps([a.agent_view for a in episode.attempts])

    assert not re.search(r"\d+\.\d+", observed), observed
    assert "120" not in observed, observed
    for attempt in episode.attempts:
        assert set(attempt.agent_view) == {"authorization_id", "decision", "blocked_by", "awaiting_customer"}
    # NOT asserted: that the agent settles far below the ceiling. An earlier version of
    # this test demanded a CHF 5 margin, and that was a bad oracle -- it measured how
    # WEAK the planner was, not whether the policy stayed private. A better planner
    # substitutes instead of dropping and therefore converges CLOSER to the boundary,
    # which looks more like extraction while being strictly better shopping. The real
    # evidence is `test_the_agents_proposals_do_not_depend_on_the_secret_limit` below.


def test_NO_POLICY_BYPASS():
    """Every approval the agent obtains is one the wallet would give to anyone. The
    loop consumes delegation; it cannot create it."""
    propose, seen, state = _wallet()
    shop(Mission("Order the household groceries", "groceries"), propose)

    approved = [d for d in seen if d.decision == "allow"]
    for decision in approved:
        assert all(e.outcome == "pass" for e in decision.rule_evaluations), (
            "an approval was reached with a rule still failing"
        )
    assert sum(a for _, a in state._approved_spend) == sum(
        Decimal(str(d.facts.billing_amount_chf)) for d in approved
    )


def test_the_agents_proposals_do_not_depend_on_the_secret_limit():
    """The decisive test of policy privacy, and the one that replaced a bad oracle.

    Run the SAME agent against two different secret ceilings. Its opening basket, and
    every revision up to the point where the wallet's answers actually diverge, must be
    IDENTICAL -- because the only thing that differs between the two worlds is a number
    the agent never sees.

    An agent using the limit would aim differently from the first proposal. This one
    cannot, and that is a property of the interface rather than of the planner's
    weakness.
    """
    def episode_for(ceiling: int):
        instruction = (f"Order our household groceries for delivery. Keep each order at or below "
                       f"CHF {ceiling} including delivery. Ask me when uncertain.")
        propose, _, _ = _wallet(instruction)
        return shop(Mission("Order the household groceries", "groceries"), propose)

    # THE PAIR MATTERS, AND THE ORIGINAL PAIR MADE HALF THIS TEST UNRUNNABLE.
    #
    # This compared 60 against 200 only. CHF 200 allows the opening basket outright
    # and CHF 60 blocks it, so the two episodes' decisions differ at attempt ZERO --
    # the revision loop below broke on its first iteration every time and its
    # assertion never executed once, measured with `coverage` over a full passing
    # suite. The opening-basket assertions ran; the claim in this test's name about
    # everything AFTER the opening basket did not.
    #
    # Measured agreeing prefixes: (60, 200) -> 0 attempts, (100, 110) -> 3,
    # (60, 80) -> 4, (40, 55) -> 5. The wide pair is kept because it is the sharpest
    # contrast for the opening basket; the close pairs are what actually exercise the
    # revisions.
    pairs = ((60, 200), (60, 80), (40, 55), (100, 110))
    episodes = {ceiling: episode_for(ceiling)
                for ceiling in sorted({c for pair in pairs for c in pair})}

    compared = 0
    for low_cap, high_cap in pairs:
        low, high = episodes[low_cap], episodes[high_cap]

        assert low.attempts[0].amount_chf == high.attempts[0].amount_chf, (
            f"the opening basket differs between CHF {low_cap} and CHF {high_cap} -- "
            f"the agent is aiming at the limit")
        assert ([l.name for l in low.attempts[0].lines]
                == [l.name for l in high.attempts[0].lines]), (
            f"the opening basket's CONTENTS differ between CHF {low_cap} and "
            f"CHF {high_cap}")

        # Revisions match while the wallet's answers match; they may diverge only
        # after the decisions themselves diverge, which is the irreducible
        # ALLOW/BLOCK oracle.
        for a, b in zip(low.attempts, high.attempts):
            if a.agent_view["decision"] != b.agent_view["decision"]:
                break
            assert a.amount_chf == b.amount_chf, (
                f"proposals diverged while the wallet's answers agreed "
                f"(CHF {low_cap} vs CHF {high_cap})")
            assert [l.name for l in a.lines] == [l.name for l in b.lines], (
                f"the basket CONTENTS diverged while the wallet's answers agreed "
                f"(CHF {low_cap} vs CHF {high_cap})")
            compared += 1

    assert compared >= 8, (
        f"only {compared} revisions were compared under agreeing wallet answers. The "
        f"claim in this test's name is about what the agent does AFTER the opening "
        f"basket, and with too few comparisons it is not being tested -- which is the "
        f"state this test was in when it compared one wide pair whose answers diverge "
        f"immediately.")

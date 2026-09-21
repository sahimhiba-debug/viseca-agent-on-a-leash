"""L10: proving the policy/security composition rule rather than asserting it.

The architecture claims the wallet's answer is the stricter of what the CUSTOMER's
own rules say and what the WALLET's safety checks say. The implementation does not
literally compute `stricter(a, b)` -- it runs `_decide()` over the full evaluation
list and derives the two verdicts by running the same function over each subset.
Those are only the same thing if `source` partitions the evaluations exhaustively.

That is the attack surface, and it is what these tests hammer: an evaluation
belonging to neither subset would be visible to the real decision and invisible to
both reported verdicts, so a card could read "your rules: satisfied, wallet checks:
satisfied" beside a BLOCK.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import pytest

from wallet_control.decision_engine import _decide, _scoped_verdict
from wallet_control.mandate import HardRule, UncertaintyPolicy

OUTCOMES = ("pass", "unknown", "fail")
SOURCES = ("customer", "safety")
POLICIES = (UncertaintyPolicy.ASK, UncertaintyPolicy.DECLINE, UncertaintyPolicy.APPROVE)
STRICTNESS = {"allow": 0, "review": 1, "block": 2}


@dataclass(frozen=True)
class FakeEvaluation:
    outcome: str
    source: str
    rule: HardRule = HardRule("item.category", "in", ["groceries"])
    detail: str = ""


def _stricter(a, b):
    return a if STRICTNESS[a] >= STRICTNESS[b] else b


def _combinations(length):
    """Every assignment of outcome x source to `length` evaluations."""
    cell = list(itertools.product(OUTCOMES, SOURCES))
    return itertools.product(cell, repeat=length)


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.value)
def test_the_composition_rule_holds_over_every_small_combination(policy):
    """Exhaustive to length 4: 6^1 + 6^2 + 6^3 + 6^4 = 1,554 evaluation lists per
    uncertainty policy, 4,662 in total. Not a sample."""
    checked = 0
    for length in range(1, 5):
        for assignment in _combinations(length):
            evaluations = [FakeEvaluation(outcome, source) for outcome, source in assignment]
            actual, _ = _decide(evaluations, policy)
            composed = _stricter(_scoped_verdict(evaluations, "customer", policy),
                                 _scoped_verdict(evaluations, "safety", policy))
            assert actual == composed, (
                f"{policy.value}: decide={actual} but stricter(policy, security)="
                f"{composed} for {[(e.outcome, e.source) for e in evaluations]}")
            checked += 1
    assert checked == sum(6 ** n for n in range(1, 5)), checked


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.value)
def test_neither_verdict_is_ever_stricter_than_the_decision(policy):
    """A reported verdict harsher than the decision would mean the card shows a
    refusal that did not happen."""
    for length in range(1, 4):
        for assignment in _combinations(length):
            evaluations = [FakeEvaluation(o, s) for o, s in assignment]
            actual, _ = _decide(evaluations, policy)
            for source in SOURCES:
                scoped = _scoped_verdict(evaluations, source, policy)
                assert STRICTNESS[scoped] <= STRICTNESS[actual], (
                    f"{source} verdict {scoped} is stricter than the decision {actual}")


def test_an_evaluation_belonging_to_NEITHER_source_would_break_the_rule():
    """The one way the composition can fail, demonstrated on purpose.

    If a rule were ever given a source outside {customer, safety}, its failure
    would count in the real decision and in neither reported verdict -- a BLOCK
    beside "your rules: satisfied, wallet checks: satisfied". The next test is what
    stops that being reachable.
    """
    evaluations = [FakeEvaluation("fail", "some_third_source")]
    actual, _ = _decide(evaluations, UncertaintyPolicy.ASK)
    composed = _stricter(_scoped_verdict(evaluations, "customer", UncertaintyPolicy.ASK),
                         _scoped_verdict(evaluations, "safety", UncertaintyPolicy.ASK))
    assert actual == "block"
    assert composed == "allow", "the demonstration is stale; re-derive the hazard"
    assert actual != composed


def test_the_engine_only_ever_produces_the_two_known_sources():
    """So the hazard above is unreachable. Checked by reading every `source=` the
    engine can emit, rather than by trusting a table that lives somewhere else --
    an evaluation tagged with a third source is the ONLY way the composition rule
    can break, so the guard has to be on the thing that assigns it."""
    import ast
    from pathlib import Path

    engine = Path(__file__).resolve().parents[2] / "src" / "wallet_control" / "decision_engine.py"
    emitted = set()
    for node in ast.walk(ast.parse(engine.read_text())):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "RuleEvaluation"):
            continue
        for keyword in node.keywords:
            if keyword.arg == "source" and isinstance(keyword.value, ast.Constant):
                emitted.add(keyword.value.value)

    assert emitted, "no RuleEvaluation(source=...) found; the parser is stale"
    assert emitted <= set(SOURCES), (
        f"the engine emits a source outside {SOURCES}: {emitted - set(SOURCES)}. "
        "That evaluation would count in the decision and in NEITHER reported "
        "verdict -- a BLOCK beside 'your rules: satisfied'.")


def test_every_source_assignment_is_a_literal():
    """A computed source could evaluate to anything at runtime, which would put the
    partition outside what any static check can see."""
    import ast
    from pathlib import Path

    engine = Path(__file__).resolve().parents[2] / "src" / "wallet_control" / "decision_engine.py"
    computed = []
    for node in ast.walk(ast.parse(engine.read_text())):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "RuleEvaluation"):
            continue
        for keyword in node.keywords:
            if keyword.arg == "source" and not isinstance(keyword.value, ast.Constant):
                computed.append(node.lineno)
    assert not computed, f"source is computed rather than literal at lines {computed}"


def test_a_human_approval_never_makes_a_policy_failure_disappear():
    """Composition is about verdicts; this is about the other direction. A customer
    answering a step-up must not be able to approve something their own rules
    forbid -- the step-up only ever exists for UNCERTAINTY, never for a failure."""
    from datetime import datetime, timezone

    from tests.helpers import make_event, make_mandate
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.state import HistoryIndex, RunState

    mandate = make_mandate("groceries at or below CHF 50",
                           [HardRule("authorization.billing_amount_chf", "<=", 50.0,
                                     currency="CHF", scope="purchase"),
                            HardRule("item.category", "in", ["groceries"])])
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})}),
                     card_id="CA_TEST")
    event = make_event(mandate=mandate, authorization_id="AU_OVER", amount=500.0,
                       billing_amount_chf=500.0, items_subtotal=500.0,
                       timestamp=datetime(2026, 8, 12, 9, tzinfo=timezone.utc))
    decision = evaluate_authorization(event, mandate, state)

    assert decision.decision == "block"
    assert decision.intervention != "step_up", (
        "a hard policy failure offered the customer a way to approve it anyway")

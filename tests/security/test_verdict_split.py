"""Two verdicts from one pass.

Every check the wallet runs carries the authority it came from: a rule the customer
wrote (`source="customer"`), or a control-layer integrity check they never opted into
(`source="safety"`). Both verdicts fall out of the same evaluation, which lets the
wallet express a state a single-verdict engine cannot:

    "Every rule you wrote was satisfied. I stopped this anyway."

The load-bearing invariant is the last test: a `source` tag is *explanatory*. It must
never be able to change a decision.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.offline_replay import replay_all
from wallet_control.state import HistoryIndex, RunState

M, CARD = "ME_TEST_0001", "CA_TEST"
T0 = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


def _state():
    return RunState(history=HistoryIndex({CARD: frozenset({M})}, available=True), card_id=CARD)


def _mandate(cap=400):
    return make_mandate(instruction="Buy one monitor.", hard_rules=[HardRule(
        field="authorization.billing_amount_chf", operator="<=", value=cap,
        currency="CHF", scope="purchase")])


def test_every_decision_reports_both_verdicts():
    for scenario in replay_all().scenarios:
        for decision in scenario.decisions:
            assert decision.policy_verdict is not None, decision.authorization_id
            assert decision.security_verdict is not None, decision.authorization_id


def test_the_official_corpus_contains_a_policy_allow_that_security_stopped():
    """The case a single-verdict engine cannot represent, and the reason this
    mechanism exists. On the official data it is AU0036: CHF 289 at PixelHarbor,
    every customer rule satisfied, escalated because the wallet could not tell
    whether it was the same order twice."""
    found = [(s.scenario_id, d.authorization_id) for s in replay_all().scenarios
             for d in s.decisions
             if d.policy_verdict == "allow" and d.security_verdict != "allow"]
    assert found, "the signature case disappeared from the official corpus"
    assert ("SCEN0004", "AU0036") in found, found


def test_the_official_corpus_contains_policy_blocks_with_nothing_untrustworthy():
    """The converse, and the common case: the customer's own rule stopped it and
    nothing about the purchase was suspect. A customer told "declined" deserves to
    know which of the two happened -- the remedy is completely different."""
    found = [d.authorization_id for s in replay_all().scenarios for d in s.decisions
             if d.policy_verdict == "block" and d.security_verdict == "allow"]
    assert len(found) >= 20, len(found)


def test_a_safety_check_alone_can_escalate_a_policy_clean_purchase():
    """Constructed rather than taken from the corpus: a purchase that satisfies every
    stated rule, repeated inside the similar-purchase window."""
    mandate, state = _mandate(), _state()
    first = evaluate_authorization(
        make_event(mandate=mandate, authorization_id="AU1", amount=100.0,
                   merchant_id=M, timestamp=T0), mandate, state)
    assert first.decision == "allow"

    repeat = evaluate_authorization(
        make_event(mandate=mandate, authorization_id="AU2", amount=100.0,
                   merchant_id=M, timestamp=T0 + timedelta(minutes=20)), mandate, state)
    assert repeat.decision == "review"
    assert repeat.policy_verdict == "allow", "a customer rule failed; this is not the split"
    assert repeat.security_verdict == "review"


def test_the_two_verdicts_are_explanatory_and_cannot_change_a_decision():
    """THE INVARIANT. `_decide()` reads rule OUTCOMES and never their `source`. If a
    tag could alter a decision, re-tagging every evaluation would move the official
    replay -- so this re-tags them and asserts it does not."""
    from dataclasses import replace

    import wallet_control.decision_engine as engine

    baseline = replay_all().total_counts()
    original = engine._decide

    def flipped(evaluations, uncertainty_policy):
        retagged = [replace(e, source=("safety" if e.source == "customer" else "customer"))
                    for e in evaluations]
        return original(retagged, uncertainty_policy)

    engine._decide = flipped
    try:
        assert replay_all().total_counts() == baseline, (
            "swapping every authority tag changed a decision -- the split is not explanatory")
    finally:
        engine._decide = original

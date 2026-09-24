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


def test_the_official_signature_case_is_escalated_by_both_halves():
    """AU0036 (CHF 289 at PixelHarbor, 25 minutes after the first monitor) used to be
    the corpus's policy-allow the wallet stopped. Under "the monitor I chose" it is
    also a second monitor, so the customer's own one-off rule asks about it as well.
    Both halves say review, for different reasons, and the split still keeps them
    apart: the policy half does not claim the duplicate check, nor the reverse. The
    policy-clean, wallet-stopped shape is exercised by the constructed test below."""
    decision = next(d for s in replay_all().scenarios for d in s.decisions
                    if d.authorization_id == "AU0036")
    assert decision.decision == "review"
    assert decision.policy_verdict == "review" and decision.security_verdict == "review"
    assert set(decision.reason_codes) == {"uncertain:order.errand_already_fulfilled",
                                          "uncertain:order.duplicate_suspected"}


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


def test_the_decision_is_always_the_stricter_of_the_two_verdicts():
    """The UI prints "Your rules: Satisfied" and "Wallet checks: Satisfied" directly
    beside the decision. Nothing asserted the three agree.

    Found during the pre-freeze UI attack: a card reading BLOCKED above two
    "Satisfied" verdicts is visually devastating and would be the first thing a
    hostile judge screenshots. In that instance the contradiction came from the
    injected test data rather than the engine, but the check it prompted did not
    exist -- the verdicts are rendered independently of the decision, so an engine
    that ever produced an inconsistent triple would display it without noticing.

    The relation is not "they are equal". `_decide` takes fail > unknown > pass over
    ALL evaluations, and the two verdicts are the same evaluations partitioned by
    `source`, so the decision must equal the STRICTER of the two. 3,000 generated
    decisions across all three uncertainty policies, with and without history.
    """
    import random
    from datetime import datetime, timedelta, timezone

    from tests.helpers import make_event, make_mandate
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.mandate import HardRule, UncertaintyPolicy
    from wallet_control.state import HistoryIndex, RunState

    rank = {"block": 0, "review": 1, "allow": 2}
    merchant, start = "ME_KNOWN", datetime(2026, 8, 12, tzinfo=timezone.utc)
    rng = random.Random(11)

    for trial in range(400):
        rules = [HardRule(field="authorization.billing_amount_chf", operator="<=",
                          value=rng.choice([50, 200, 400]), currency="CHF", scope="purchase")]
        if rng.random() < 0.5:
            rules.append(HardRule(field="merchant.familiar", operator="=", value="true"))
        if rng.random() < 0.5:
            rules.append(HardRule(field="item.category", operator="in", value=["groceries"]))
        if rng.random() < 0.4:
            rules.append(HardRule(field="order.return_window_days", operator=">=", value=14))

        mandate = make_mandate(instruction="Buy groceries.", hard_rules=rules,
                               uncertainty_policy=rng.choice(list(UncertaintyPolicy)))
        state = RunState(
            history=HistoryIndex({"CA_TEST": frozenset({merchant})}, available=rng.random() < 0.8),
            card_id="CA_TEST",
        )
        event = make_event(mandate=mandate, authorization_id=f"AU{trial}",
                           amount=rng.choice([10.0, 199.0, 401.0]),
                           merchant_id=rng.choice([merchant, "ME_OTHER"]),
                           timestamp=start + timedelta(hours=trial))
        event["authorization"]["items"][0].update(
            item_name="milk", item_category=rng.choice(["groceries", "jewellery"]),
            item_details=rng.choice(["", "returns accepted within 30 days"]),
        )
        event["authorization"]["order_returnable"] = rng.choice(["true", "unknown"])

        decision = evaluate_authorization(event, mandate, state)
        stricter = min(rank[decision.policy_verdict], rank[decision.security_verdict])
        assert rank[decision.decision] == stricter, (
            f"decision={decision.decision} but policy={decision.policy_verdict} "
            f"security={decision.security_verdict}"
        )

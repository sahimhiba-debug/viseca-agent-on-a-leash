"""Two different "duplicate" concepts, tested separately (see state.py docstring):
repeated delivery of the SAME authorization_id (pure idempotency) vs. a DIFFERENT
authorization_id describing a suspiciously similar purchase (fraud-relevant
evidence that feeds the normal uncertainty pathway, not an automatic block).
"""

from datetime import datetime, timedelta

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.state import HistoryIndex, RunState

MONITOR_ITEM = [
    {"line_no": 1, "item_id": "IT0017", "item_name": "27-inch computer monitor", "item_category": "electronics", "quantity": 1, "unit_price": 289.0, "currency": "CHF", "item_details": ""}
]


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})}, available=True), card_id="CA_TEST")


def _ts_of(event: dict) -> datetime:
    return datetime.fromisoformat(event["authorization"]["timestamp"].replace("Z", "+00:00"))


def test_repeated_delivery_of_same_authorization_id_does_not_double_count_spend():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU_RETRY", amount=289.0, items=MONITOR_ITEM)
    r1 = evaluate_authorization(event, mandate, state)
    r2 = evaluate_authorization(event, mandate, state)  # simulates the platform re-delivering the same event
    r3 = evaluate_authorization(event, mandate, state)
    assert [r1.decision, r2.decision, r3.decision] == ["allow", "allow", "allow"]
    assert state.total_approved_spend_chf() == 289
    assert r2.idempotent_replay and r3.idempotent_replay


def test_similar_purchase_with_a_different_id_shortly_after_is_flagged_not_auto_declined():
    """Mirrors AU0035/AU0036 in the official data: the exact same merchant, basket,
    and amount 25 minutes apart under a different authorization_id. Not automatically
    fraud (it could be a genuine second order) -- it becomes a review/uncertainty
    signal, following the mandate's own uncertainty_policy like any other unknown."""
    mandate = make_mandate(
        uncertainty_policy=UncertaintyPolicy.ASK,
        hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")],
    )
    state = _state()
    first_event = make_event(mandate=mandate, authorization_id="AU_FIRST", amount=289.0, items=MONITOR_ITEM)
    r1 = evaluate_authorization(first_event, mandate, state)
    assert r1.decision == "allow"

    second_event = make_event(
        mandate=mandate,
        authorization_id="AU_SECOND",
        amount=289.0,
        items=MONITOR_ITEM,
        timestamp=_ts_of(first_event) + timedelta(minutes=25),
    )
    r2 = evaluate_authorization(second_event, mandate, state)
    assert r2.decision == "review"
    assert r2.intervention == "ask_missing_fact"
    assert any("duplicate" in code for code in r2.reason_codes)


def test_similar_purchase_far_outside_the_window_is_not_flagged():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    state = _state()
    first_event = make_event(mandate=mandate, authorization_id="AU_FIRST", amount=289.0, items=MONITOR_ITEM)
    evaluate_authorization(first_event, mandate, state)

    later_ts = _ts_of(first_event) + timedelta(days=7)
    second_event = make_event(mandate=mandate, authorization_id="AU_SECOND", amount=289.0, items=MONITOR_ITEM, timestamp=later_ts)
    r2 = evaluate_authorization(second_event, mandate, state)
    assert r2.decision == "allow"  # a week later is an ordinary re-order, not a suspected duplicate


def test_a_declined_prior_attempt_is_not_treated_as_a_duplicate_conflict():
    """Mirrors AU0037 (declined, CHF 520) followed by AU0042 (a legitimate re-quote
    at CHF 350, related_authorization_status=declined). A prior *decline* must not
    itself trigger duplicate suspicion on the corrected re-order."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=400, currency="CHF", scope="purchase")])
    state = _state()
    declined_event = make_event(mandate=mandate, authorization_id="AU_OVERPRICED", amount=520.0, items=MONITOR_ITEM)
    r1 = evaluate_authorization(declined_event, mandate, state)
    assert r1.decision == "block"

    requote_ts = _ts_of(declined_event) + timedelta(minutes=5)
    requote_item = [{**MONITOR_ITEM[0], "unit_price": 350.0}]
    requote_event = make_event(
        mandate=mandate,
        authorization_id="AU_REQUOTE",
        amount=350.0,
        items=requote_item,
        related_authorization_id="AU_OVERPRICED",
        related_authorization_status="declined",
        timestamp=requote_ts,
    )
    r2 = evaluate_authorization(requote_event, mandate, state)
    assert r2.decision == "allow"

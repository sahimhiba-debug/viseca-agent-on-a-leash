"""V6: near-duplicate order detection was exact-match on (merchant, basket, amount),
so a compromised agent evaded it by changing the price by one centime.

technical_details.md asks the wallet to "check distinct but similar purchases
against earlier outcomes; different IDs can still describe an unwanted duplicate
order". Requiring the amount to match exactly interprets "similar" as "identical",
and ordering the same basket from the same merchant twenty minutes later at CHF
100.01 instead of CHF 100.00 is the unwanted duplicate order, not a different one.

The attacker's gain is avoiding the human prompt, not exceeding a limit -- every
hard rule still applies -- so this is a detection weakness rather than an
authority bypass. It is fixed because the detection is cheap and the evasion was
trivial.
"""

from __future__ import annotations

from datetime import timedelta

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex, RunState

MERCHANT_ID = "ME_TEST_0001"


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT_ID})}, available=True), card_id="CA_TEST")


def _mandate():
    return make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])


def _at(mandate, authorization_id, amount, minutes):
    event = make_event(mandate=mandate, authorization_id=authorization_id, amount=amount, merchant_id=MERCHANT_ID)
    base = event["authorization"]["timestamp"]
    from datetime import datetime

    ts = datetime.fromisoformat(base.replace("Z", "+00:00")) + timedelta(minutes=minutes)
    event["authorization"]["timestamp"] = ts.isoformat().replace("+00:00", "Z")
    return event


def test_a_one_centime_change_no_longer_evades_duplicate_detection():
    mandate, state = _mandate(), _state()
    assert evaluate_authorization(_at(mandate, "AU1", 100.00, 0), mandate, state).decision == "allow"
    evaded = evaluate_authorization(_at(mandate, "AU2", 100.01, 6), mandate, state)
    assert evaded.decision == "review"
    assert any("duplicate" in code for code in evaded.reason_codes)


def test_the_evidence_names_the_price_difference():
    """A reviewer must be able to see it is the same basket at a different price,
    not an identical re-order."""
    mandate, state = _mandate(), _state()
    evaluate_authorization(_at(mandate, "AU1", 100.00, 0), mandate, state)
    result = evaluate_authorization(_at(mandate, "AU2", 100.01, 6), mandate, state)
    duplicate_evidence = [e.detail for e in result.rule_evaluations if "duplicate" in e.rule.field]
    assert duplicate_evidence
    assert "100.00" in duplicate_evidence[0] or "100.0" in duplicate_evidence[0]


def test_an_identical_repeat_is_still_detected():
    mandate, state = _mandate(), _state()
    evaluate_authorization(_at(mandate, "AU1", 100.00, 0), mandate, state)
    result = evaluate_authorization(_at(mandate, "AU2", 100.00, 6), mandate, state)
    assert result.decision == "review"


def test_a_different_basket_is_not_a_duplicate():
    """The check must stay narrow: same merchant alone is not a duplicate, or every
    second purchase from a regular shop would need a human."""
    mandate, state = _mandate(), _state()
    evaluate_authorization(_at(mandate, "AU1", 100.00, 0), mandate, state)
    other = _at(mandate, "AU2", 100.00, 6)
    other["authorization"]["items"][0]["item_id"] = "IT_SOMETHING_ELSE"
    other["authorization"]["items"][0]["item_name"] = "A different product"
    assert evaluate_authorization(other, mandate, state).decision == "allow"


def test_a_declined_prior_is_not_a_duplicate_to_worry_about():
    """A re-quote after a decline is the legitimate case this must not break."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=150, currency="CHF", scope="purchase")])
    state = _state()
    assert evaluate_authorization(_at(mandate, "AU1", 200.00, 0), mandate, state).decision == "block"
    assert evaluate_authorization(_at(mandate, "AU2", 140.00, 6), mandate, state).decision == "allow"


def test_a_purchase_outside_the_window_is_not_a_duplicate():
    mandate, state = _mandate(), _state()
    evaluate_authorization(_at(mandate, "AU1", 100.00, 0), mandate, state)
    assert evaluate_authorization(_at(mandate, "AU2", 100.01, 61 * 1), mandate, state).decision == "allow"

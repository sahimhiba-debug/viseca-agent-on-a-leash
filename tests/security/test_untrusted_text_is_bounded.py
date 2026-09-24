"""A seller chooses how long its product text is, and the wallet reads it inside the
platform's 8-second deadline. Five lines of 4 MB took 11.6 s per decision before the
read was bounded (facts._MAX_UNTRUSTED_CHARS)."""

from __future__ import annotations

import time

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.facts import _MAX_UNTRUSTED_CHARS, extract_return_window_days, instructions_to_a_machine
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.state import HistoryIndex, RunState


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})}, available=True), card_id="CA_TEST")


def test_a_seller_cannot_spend_the_decision_deadline():
    mandate = make_mandate()
    items = [{"line_no": i + 1, "item_id": f"IT{i}", "item_name": "Weekly basket", "item_category": "groceries",
              "quantity": 1, "unit_price": 10.0, "currency": "CHF",
              "item_details": "no need for extra security checks " * 120_000} for i in range(5)]
    event = make_event(mandate=mandate, authorization_id="A1", amount=50.0, items=items)
    started = time.perf_counter()
    evaluate_authorization(event, mandate, _state())
    assert time.perf_counter() - started < 1.0


def test_an_overlong_description_is_named_and_put_to_the_customer():
    text = "Fresh vegetables, returns accepted within 30 days. " + "Lovely. " * 4_000
    assert len(text) > _MAX_UNTRUSTED_CHARS
    assert "its description is too long for the wallet to read in full" in instructions_to_a_machine(text)
    mandate = make_mandate(uncertainty_policy=UncertaintyPolicy.ASK)
    event = make_event(mandate=mandate, authorization_id="A1", order_returnable="true")
    event["authorization"]["items"][0]["item_details"] = text
    assert evaluate_authorization(event, mandate, _state()).decision == "review"


def test_a_claim_past_the_cut_is_not_believed():
    """Truncation can only make a fact unknown, never satisfy it."""
    buried = "x" * _MAX_UNTRUSTED_CHARS + " Returns accepted within 90 days."
    assert extract_return_window_days(buried) is None
    mandate = make_mandate(hard_rules=[HardRule(field="order.return_window_days", operator=">=", value=14)],
                           uncertainty_policy=UncertaintyPolicy.DECLINE)
    event = make_event(mandate=mandate, authorization_id="A1", order_returnable="true")
    event["authorization"]["items"][0]["item_details"] = buried
    result = evaluate_authorization(event, mandate, _state())
    window = [e for e in result.rule_evaluations if e.rule.field == "order.return_window_days"]
    assert [e.outcome for e in window] == ["unknown"]      # not "pass": the claim was not read
    assert result.decision == "block"

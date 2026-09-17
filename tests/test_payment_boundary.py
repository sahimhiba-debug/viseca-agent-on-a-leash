"""Phase 9: approve is not payment. `MockPSP` is the only thing in this codebase
that can move (simulated) money, and it must refuse whenever the authorization
boundary would otherwise be crossed.
"""

from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, RunState


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})}, available=True), card_id="CA_TEST")


def test_cannot_charge_before_any_decision_exists():
    state = _state()
    psp = MockPSP(state)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU_NEVER_SEEN", amount_chf=Decimal("10"))


def test_cannot_charge_a_declined_authorization():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=10, currency="CHF", scope="purchase")])
    state = _state()
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=100.0)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "block"
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("100"))


def test_cannot_charge_a_pending_step_up():
    mandate = make_mandate(hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")])
    state = RunState(history=HistoryIndex.empty(), card_id="CA_TEST")  # familiarity unknown -> uncertainty -> review (ASK)
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "review"
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"))


def test_charge_amount_cannot_exceed_the_approved_amount():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "allow"
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50.01"))
    # charging exactly the approved amount succeeds
    record = psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"))
    assert record.amount_chf == Decimal("50")


def test_one_authorization_cannot_be_charged_twice():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    evaluate_authorization(event, mandate, state)
    psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"))
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH2", authorization_id="AU1", amount_chf=Decimal("50"))  # different charge_id, same authorization


def test_retrying_the_same_charge_id_is_idempotent_not_a_double_execution():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    evaluate_authorization(event, mandate, state)
    r1 = psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"))
    r2 = psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"))
    assert r1 == r2
    assert psp.is_charged("AU1")

"""Phase 9/10: approve is not payment. `MockPSP` is the only thing in this codebase
that can move (simulated) money, and it must refuse whenever the authorization
boundary would otherwise be crossed -- including adversarial misuse of its own
idempotency key, not just the routine "happy path" of one clean charge.
"""

from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, RunState

MERCHANT_ID = "ME_TEST_0001"


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT_ID})}, available=True), card_id="CA_TEST")


def test_cannot_charge_before_any_decision_exists():
    state = _state()
    psp = MockPSP(state)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU_NEVER_SEEN", amount_chf=Decimal("10"), merchant_id=MERCHANT_ID)


def test_cannot_charge_a_declined_authorization():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=10, currency="CHF", scope="purchase")])
    state = _state()
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=100.0)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "block"
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("100"), merchant_id=MERCHANT_ID)


def test_cannot_charge_a_pending_step_up():
    mandate = make_mandate(hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")])
    state = RunState(history=HistoryIndex.empty(), card_id="CA_TEST")  # familiarity unknown -> uncertainty -> review (ASK)
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "review"
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"), merchant_id=MERCHANT_ID)


def test_charge_amount_cannot_exceed_the_approved_amount():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "allow"
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50.01"), merchant_id=MERCHANT_ID)
    # charging exactly the approved amount succeeds
    record = psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"), merchant_id=MERCHANT_ID)
    assert record.amount_chf == Decimal("50")


def test_one_authorization_cannot_be_charged_twice():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    evaluate_authorization(event, mandate, state)
    psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"), merchant_id=MERCHANT_ID)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH2", authorization_id="AU1", amount_chf=Decimal("50"), merchant_id=MERCHANT_ID)  # different charge_id, same authorization


def test_retrying_the_same_charge_id_is_idempotent_not_a_double_execution():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    evaluate_authorization(event, mandate, state)
    r1 = psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"), merchant_id=MERCHANT_ID)
    r2 = psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"), merchant_id=MERCHANT_ID)
    assert r1 == r2
    assert psp.is_charged("AU1")


def test_cannot_charge_the_wrong_merchant_for_an_approved_authorization():
    """Phase 10: 'approved merchant is bound correctly'. Even if amount and
    authorization_id line up, charging against a DIFFERENT merchant than the one
    that was actually approved must be refused."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id=MERCHANT_ID)
    evaluate_authorization(event, mandate, state)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"), merchant_id="ME_DIFFERENT")


def test_reusing_a_charge_id_for_a_different_authorization_is_refused_not_silently_returned():
    """Phase 10/11: a `charge_id` is an idempotency key for ONE request. Reusing it
    for a different authorization_id (or a different amount) must never be treated
    as "the same charge, already done" -- that would let a second, unrelated charge
    piggyback on an already-approved charge_id's success."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    state = _state()
    psp = MockPSP(state)
    event1 = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    event2 = make_event(mandate=mandate, authorization_id="AU2", amount=999.0)
    evaluate_authorization(event1, mandate, state)
    evaluate_authorization(event2, mandate, state)

    psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"), merchant_id=MERCHANT_ID)
    with pytest.raises(PaymentError):
        # Same charge_id, different authorization_id and amount: must be a conflict,
        # not a silent "already done" return of the AU1 record.
        psp.charge(charge_id="CH1", authorization_id="AU2", amount_chf=Decimal("999"), merchant_id=MERCHANT_ID)
    assert not psp.is_charged("AU2")  # AU2 must remain unexecuted


def test_reusing_a_charge_id_for_a_different_amount_on_the_same_authorization_is_refused():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    evaluate_authorization(event, mandate, state)
    psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("30"), merchant_id=MERCHANT_ID)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("50"), merchant_id=MERCHANT_ID)


@pytest.mark.parametrize("bad_amount", [Decimal("0"), Decimal("-1"), Decimal("-50.00")])
def test_zero_or_negative_charge_amount_is_refused(bad_amount):
    """Phase 16: 'malformed amount, negative amount, zero amount' against the
    payment layer directly. A charge for CHF 0 or less is never a legitimate
    execution of an approved purchase."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    psp = MockPSP(state)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    evaluate_authorization(event, mandate, state)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=bad_amount, merchant_id=MERCHANT_ID)
    assert not psp.is_charged("AU1")

"""V2/V3/V4: three holes in the payment-authority lifecycle, all of which let a
purchase be charged that the customer had already stopped.

V2  Neither production resolve path (`api.py`, `live_worker.py`) passed `mandate=`
    to `resolve_authorization`, so a HUMAN-APPROVED step-up never minted a payment
    authority at all. `revoke_outstanding_authorities()` therefore had nothing to
    revoke for it, and `charge()` treated "no authority" as "no constraint". Net
    effect: the one purchase the customer was actually asked about was the one
    purchase that escaped their revocation. This falsifies invariant I29 as it was
    claimed in the previous pass.

V3  `RunState.to_snapshot()` did not persist `_authorities`, so a crash and
    restart resurrected revoked and expired authorities as unconstrained ones.

V4  Authority expiry was evaluated against a caller-supplied `now=`, so whoever
    called the payment boundary could simply say what time it was. The demo path
    was already passing a simulated purchase time, which made the expiry check
    vacuous there.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.mandate import HardRule
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, RunState

MERCHANT_ID = "ME_TEST_0001"


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT_ID})}, available=True), card_id="CA_TEST")


def _allow_mandate():
    return make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])


def _review_mandate():
    return make_mandate(hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")])


# --- V2: a human-approved step-up must be revocable like any other approval ------


def test_a_human_approved_step_up_mints_a_payment_authority():
    mandate = _review_mandate()
    state = RunState(history=HistoryIndex.empty(), card_id="CA_TEST")
    first = evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=100.0, merchant_id=MERCHANT_ID), mandate, state)
    assert first.decision == "review"

    resolved = resolve_authorization("AU1", "allow", state, resolved_at=datetime.now(timezone.utc), mandate=mandate)
    assert resolved.payment_authority is not None
    assert state.get_authority("AU1") is not None


def test_revocation_reaches_a_human_approved_step_up():
    """The exploit: approve the step-up, then revoke. The purchase the customer was
    asked about must not be the one that survives their revocation."""
    mandate = _review_mandate()
    state = RunState(history=HistoryIndex.empty(), card_id="CA_TEST")
    evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=100.0, merchant_id=MERCHANT_ID), mandate, state)
    resolve_authorization("AU1", "allow", state, resolved_at=datetime.now(timezone.utc), mandate=mandate)

    assert state.revoke_outstanding_authorities() == ("AU1",)
    psp = MockPSP(state)
    with pytest.raises(PaymentError, match="revoked"):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("100"), merchant_id=MERCHANT_ID)
    assert not psp.is_charged("AU1")


def test_an_allow_with_no_authority_on_record_cannot_be_charged():
    """Fail-closed replaces the previous fail-open default.

    The previous pass asserted the opposite (an ALLOW with no authority charged
    normally) on the reasoning that pre-existing callers never minted one. That
    reasoning was wrong: it is exactly what let V2 and V3 move money. Every
    chargeable ALLOW now mints an authority, so a missing one means state was lost
    or never properly established -- which is a reason to stop, not to proceed."""
    mandate = _allow_mandate()
    state = _state()
    evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID), mandate, state)
    state._authorities.clear()  # simulate lost/never-established authority state

    psp = MockPSP(state)
    with pytest.raises(PaymentError, match="no payment authority"):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("400"), merchant_id=MERCHANT_ID)


# --- V3: authority state must survive a crash -----------------------------------


def test_authorities_survive_a_checkpoint_round_trip():
    mandate = _allow_mandate()
    state = _state()
    result = evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID), mandate, state)

    restored = RunState.from_snapshot(state.to_snapshot(), state.history)
    survived = restored.get_authority("AU1")
    assert survived is not None
    assert survived.merchant_id == result.payment_authority.merchant_id
    assert survived.amount_ceiling_chf == result.payment_authority.amount_ceiling_chf
    assert survived.expires_at == result.payment_authority.expires_at
    assert survived.basket_fingerprint == result.payment_authority.basket_fingerprint


def test_a_revoked_authority_does_not_resurrect_after_a_restart():
    """The exploit: revoke, crash, restart, charge."""
    mandate = _allow_mandate()
    state = _state()
    evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID), mandate, state)
    state.revoke_outstanding_authorities()

    restored = RunState.from_snapshot(state.to_snapshot(), state.history)
    assert restored.get_authority("AU1").revoked

    psp = MockPSP(restored)
    with pytest.raises(PaymentError, match="revoked"):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("400"), merchant_id=MERCHANT_ID)


def test_an_expired_authority_does_not_get_a_fresh_window_after_a_restart():
    mandate = _allow_mandate()
    state = _state()
    result = evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID), mandate, state)
    restored = RunState.from_snapshot(state.to_snapshot(), state.history)
    assert restored.get_authority("AU1").expires_at == result.payment_authority.expires_at


# --- V4: expiry must not be evaluated against a clock the caller supplies --------


def test_expiry_cannot_be_defeated_by_rewinding_the_supplied_clock():
    """The exploit: charge long after expiry while claiming it is still issue time."""
    mandate = _allow_mandate()
    state = _state()
    result = evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID), mandate, state)
    authority = result.payment_authority

    psp = MockPSP(state, clock=lambda: authority.expires_at + timedelta(days=3650))
    with pytest.raises(PaymentError, match="expired"):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("400"), merchant_id=MERCHANT_ID, now=authority.issued_at)
    assert not psp.is_charged("AU1")


def test_a_trusted_clock_still_permits_a_charge_inside_the_window():
    mandate = _allow_mandate()
    state = _state()
    result = evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID), mandate, state)

    psp = MockPSP(state, clock=lambda: result.payment_authority.issued_at + timedelta(minutes=1))
    record = psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("400"), merchant_id=MERCHANT_ID)
    assert record.amount_chf == Decimal("400")

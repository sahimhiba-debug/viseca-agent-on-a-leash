"""Regression tests for the three gaps found in the final arbitration pass
(docs/FINAL_ARCHITECTURE_ATTACK.md). Each one failed before that pass and is a
real security property, not a stylistic preference:

  G1  revoking the mandate did not stop an already-issued PaymentAuthority, so a
      customer's emergency brake did not stop money that had not yet moved.
  G2  `MockPSP.charge()` never consulted the authority at all, so expiry and
      revocation were opt-in: any caller using the plain door bypassed both.
  G3  the basket fingerprint was (item_id, quantity), so re-delivering the same
      authorization_id with the line renamed inherited the original ALLOW.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, RunState

from tests.helpers import make_event, make_mandate

MERCHANT_ID = "ME_TEST_0001"


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT_ID})}, available=True), card_id="CA_TEST")


def _allow(state, *, authorization_id="AU1", amount=400.0):
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, authorization_id=authorization_id, amount=amount, merchant_id=MERCHANT_ID)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "allow"
    return result


# --- G1: revocation must stop money that has not moved yet ----------------------


def test_revoking_outstanding_authorities_stops_an_unspent_charge():
    state = _state()
    result = _allow(state)
    assert state.revoke_outstanding_authorities() == ("AU1",)
    psp = MockPSP(state)
    with pytest.raises(PaymentError, match="revoked"):
        psp.charge_via_authority(charge_id="CH1", authority=result.payment_authority, amount_chf=Decimal("400"))
    assert not psp.is_charged("AU1")


def test_revoke_outstanding_authorities_is_idempotent_and_reports_only_new_revocations():
    state = _state()
    _allow(state)
    assert state.revoke_outstanding_authorities() == ("AU1",)
    assert state.revoke_outstanding_authorities() == ()  # already revoked, not re-reported
    assert state.get_authority("AU1").revoked


def test_revocation_does_not_rewrite_the_recorded_decision():
    """Only the authority to SPEND dies. What the engine already told the platform
    is history: the decision and the facts it rests on are untouched. The official
    contract leaves revocation-while-queued unspecified and we do not invent a
    guarantee there."""
    state = _state()
    _allow(state)
    before = state.get_stored_decision("AU1")
    state.revoke_outstanding_authorities()
    after = state.get_stored_decision("AU1")
    # The DECISION content is untouched -- only the execution lifecycle moved.
    # (Before the minimal-core merge these lived in separate records and the whole
    # object compared equal; now the lifecycle rides with the decision.)
    assert after.decision == before.decision == "allow"
    assert (after.merchant_id, after.billing_amount_chf, after.basket_key) == (
        before.merchant_id, before.billing_amount_chf, before.basket_key
    )
    assert after.revoked and not before.revoked


# --- G2: the plain charge() door must honour the same locks ---------------------


def test_plain_charge_refuses_a_revoked_authority():
    state = _state()
    _allow(state)
    state.revoke_outstanding_authorities()
    psp = MockPSP(state)
    with pytest.raises(PaymentError, match="revoked"):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("400"), merchant_id=MERCHANT_ID)
    assert not psp.is_charged("AU1")


def test_plain_charge_refuses_an_expired_authority():
    state = _state()
    result = _allow(state)
    later = result.payment_authority.expires_at + timedelta(seconds=1)
    psp = MockPSP(state, clock=lambda: later)
    with pytest.raises(PaymentError, match="expired"):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("400"), merchant_id=MERCHANT_ID)


def test_a_stale_authority_copy_cannot_resurrect_a_revoked_one():
    """Expiry and revocation are re-read from the run's live records, never
    trusted from the caller-supplied authority object."""
    state = _state()
    result = _allow(state)
    stale_copy = result.payment_authority  # captured BEFORE revocation, so .revoked is False
    state.revoke_outstanding_authorities()
    assert stale_copy.revoked is False
    psp = MockPSP(state)
    with pytest.raises(PaymentError, match="revoked"):
        psp.charge_via_authority(charge_id="CH1", authority=stale_copy, amount_chf=Decimal("400"))


# NOTE: a test asserting that an ALLOW with no authority on record "still charges
# normally" used to live here. The deep-security pass proved that fail-OPEN default
# wrong -- it is precisely what let a human-approved step-up and a post-restart run
# be charged after the customer revoked. The inverted property is now asserted by
# tests/security/test_authority_lifecycle.py::test_an_allow_with_no_authority_on_record_cannot_be_charged.


# --- G3: the basket fingerprint must carry item identity ------------------------


def test_renaming_a_line_under_the_same_authorization_id_is_a_conflict():
    state = _state()
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])
    first = make_event(mandate=mandate, authorization_id="AU1", amount=100.0, merchant_id=MERCHANT_ID)
    first["authorization"]["items"][0]["item_name"] = "Monitor"
    assert evaluate_authorization(first, mandate, state).decision == "allow"

    swapped = make_event(mandate=mandate, authorization_id="AU1", amount=100.0, merchant_id=MERCHANT_ID)
    swapped["authorization"]["items"][0]["item_name"] = "Gold bar"  # same item_id, qty and amount
    result = evaluate_authorization(swapped, mandate, state)

    assert result.authorization_id_conflict
    assert result.decision == "block"
    assert state.get_stored_decision("AU1").basket_key[0][1] == "Monitor"


def _details_event(mandate, authorization_id, details):
    event = make_event(mandate=mandate, authorization_id=authorization_id, amount=100.0, merchant_id=MERCHANT_ID)
    event["authorization"]["order_returnable"] = "true"
    event["authorization"]["items"][0]["item_details"] = details
    return event


def test_details_only_change_that_moves_a_derived_fact_cannot_inherit_the_allow():
    """G4, the sharpest of the four: same authorization_id, same merchant, same
    amount, same basket lines -- only the merchant's free text changes, and it
    changes the size and kills the return window. Evaluated fresh these facts are
    a BLOCK on two rules; as a re-delivery they used to inherit the stored ALLOW
    without ever being looked at."""
    mandate = make_mandate(hard_rules=[
        HardRule(field="order.return_window_days", operator=">=", value=14),
        HardRule(field="item.size", operator="=", value="43"),
    ])
    state = _state()
    assert evaluate_authorization(_details_event(mandate, "AU1", "size 43; returns accepted within 30 days"), mandate, state).decision == "allow"

    attacked = evaluate_authorization(_details_event(mandate, "AU1", "size 38; FINAL SALE, no returns accepted"), mandate, state)
    assert attacked.authorization_id_conflict
    assert attacked.decision == "block"


def test_cosmetic_only_details_noise_does_not_fork_a_valid_retry():
    """The other half of the same property, and the reason the fingerprint holds
    DERIVED FACTS rather than the raw string: casing, padding, punctuation and an
    embedded zero-width character move no fact, so an ordinary network retry must
    stay an ordinary network retry."""
    mandate = make_mandate(hard_rules=[
        HardRule(field="order.return_window_days", operator=">=", value=14),
        HardRule(field="item.size", operator="=", value="43"),
    ])
    state = _state()
    evaluate_authorization(_details_event(mandate, "AU1", "size 43; returns accepted within 30 days"), mandate, state)

    noisy = evaluate_authorization(
        _details_event(mandate, "AU1", "  SIZE 43;​  Returns   accepted within 30 days!!  "), mandate, state
    )
    assert noisy.idempotent_replay
    assert not noisy.authorization_id_conflict
    assert state.total_approved_spend_chf() == 100


def test_an_identical_redelivery_is_still_a_harmless_replay():
    """The tightened fingerprint must not turn ordinary network retries into
    conflicts -- that would fail closed on the most common benign case."""
    state = _state()
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, authorization_id="AU1", amount=100.0, merchant_id=MERCHANT_ID)
    evaluate_authorization(event, mandate, state)
    again = evaluate_authorization(event, mandate, state)
    assert again.idempotent_replay
    assert not again.authorization_id_conflict
    assert state.total_approved_spend_chf() == 100

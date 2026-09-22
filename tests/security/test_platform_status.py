"""V1 (CRITICAL): the platform's own revocation/blocking signals were ignored.

`authority_status` ("active" | "revoked" | "expired") and `card_status_at_attempt`
("active" | "blocked") are REQUIRED fields of the official authorization event
schema. They are the platform telling the wallet, authoritatively, that the
authority behind this purchase is gone or that the card may not be used.

Before this pass the decision engine never read either field. All three negative
states returned ALLOW, minted a payment authority, and charged. No existing test
caught it because all 45 official rows carry "active"/"active" -- the fixture
only ever exercises the happy value.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, RunState

MERCHANT_ID = "ME_TEST_0001"


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT_ID})}, available=True), card_id="CA_TEST")


def _mandate(uncertainty_policy=UncertaintyPolicy.ASK):
    return make_mandate(
        hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")],
        uncertainty_policy=uncertainty_policy,
    )


def _event(mandate, **overrides):
    event = make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID)
    event["authorization"].update(overrides)
    return event


@pytest.mark.parametrize("status", ["revoked", "expired"])
def test_a_non_active_authority_status_is_blocked(status):
    mandate = _mandate()
    state = _state()
    result = evaluate_authorization(_event(mandate, authority_status=status), mandate, state)
    assert result.decision == "block"
    assert any("authority_status" in code for code in result.reason_codes)
    assert result.payment_authority is None


def test_a_blocked_card_is_blocked():
    mandate = _mandate()
    state = _state()
    result = evaluate_authorization(_event(mandate, card_status_at_attempt="blocked"), mandate, state)
    assert result.decision == "block"
    assert any("card_status" in code for code in result.reason_codes)
    assert result.payment_authority is None


@pytest.mark.parametrize("field", ["authority_status", "card_status_at_attempt"])
def test_a_revoked_or_blocked_purchase_can_never_be_charged(field):
    """The end-to-end property: no money moves for a purchase the platform has
    already told us is not authorized."""
    mandate = _mandate()
    state = _state()
    bad = "revoked" if field == "authority_status" else "blocked"
    evaluate_authorization(_event(mandate, **{field: bad}), mandate, state)
    psp = MockPSP(state)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("400"), merchant_id=MERCHANT_ID)
    assert not psp.is_charged("AU1")


@pytest.mark.parametrize("status", ["", "suspended", "ACTIVE", None, "unknown-future-value"])
def test_an_unrecognised_status_is_uncertainty_not_permission(status):
    """A status we do not recognise is missing information, not consent. It must
    route through the mandate's uncertainty policy (ASK -> review), never pass.
    Note "ACTIVE" is included deliberately: the enum is lower-case, and a
    case-variant must not be silently accepted as equivalent."""
    mandate = _mandate()
    state = _state()
    result = evaluate_authorization(_event(mandate, authority_status=status), mandate, state)
    assert result.decision == "review"
    assert result.payment_authority is None


def test_an_unrecognised_status_blocks_under_a_decline_policy():
    mandate = _mandate(uncertainty_policy=UncertaintyPolicy.DECLINE)
    state = _state()
    result = evaluate_authorization(_event(mandate, authority_status="suspended"), mandate, state)
    assert result.decision == "block"


def test_an_explicitly_revoked_authority_blocks_even_under_an_approve_policy():
    """`revoked` is a known negative, not missing information, so it is a hard
    failure that the uncertainty policy cannot soften -- otherwise a customer who
    chose "approve when unsure" would have chosen to ignore their own revocation."""
    mandate = _mandate(uncertainty_policy=UncertaintyPolicy.APPROVE)
    state = _state()
    result = evaluate_authorization(_event(mandate, authority_status="revoked"), mandate, state)
    assert result.decision == "block"


def test_active_status_still_allows_normally():
    """The check must not disturb the ordinary path -- this is what keeps the
    official replay at 17/4/24 (all 45 official rows are active/active)."""
    mandate = _mandate()
    state = _state()
    result = evaluate_authorization(_event(mandate, authority_status="active", card_status_at_attempt="active"), mandate, state)
    assert result.decision == "allow"
    assert result.payment_authority is not None


def test_the_status_checks_are_wallet_safety_not_customer_policy():
    """These are control-layer integrity checks the customer never opted into, so
    they belong in the safety evidence group, not in "your policy checked"."""
    mandate = _mandate()
    state = _state()
    result = evaluate_authorization(_event(mandate, authority_status="revoked"), mandate, state)
    status_evals = [e for e in result.rule_evaluations if "status" in e.rule.field]
    assert status_evals, "expected a status evaluation in the evidence"
    assert all(e.source == "safety" for e in status_evals)

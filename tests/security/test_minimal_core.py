"""The minimal core: one authoritative record per authorization, with the
execution lifecycle riding on it and `PaymentAuthority` reduced to a projection.

The merge deleted `RunState._authorities` — a second dict describing the same
authorizations. That duplication was the shape behind V2 (a decision with no
authority), V3/V8/V10 (an authority lost while its decision was checkpointed) and
V13/V14 (a lifecycle overwritten by a concurrent transition).

Collapsing it buys structural guarantees, but it also creates one NEW risk the
two-record design did not have: the decision record is no longer wholly immutable,
because the lifecycle mutates in place. The tests below pin both sides — what the
merge gained, and the risk it introduced.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import PaymentAuthority, RunState, HistoryIndex

MERCHANT_ID = "ME_TEST_0001"


def _state() -> RunState:
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT_ID})}, available=True), card_id="CA_TEST")


def _allow(state, authorization_id="AU1", amount=400.0):
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])
    result = evaluate_authorization(
        make_event(mandate=mandate, authorization_id=authorization_id, amount=amount, merchant_id=MERCHANT_ID), mandate, state
    )
    assert result.decision == "allow"
    return result


# --- what the merge structurally guarantees ---------------------------------------


def test_there_is_only_one_record_per_authorization():
    """`RunState` no longer holds a second dict that could describe the same
    authorization differently."""
    state = _state()
    _allow(state)
    assert not hasattr(state, "_authorities")


def test_the_authority_is_a_projection_not_a_stored_object():
    """Derived fresh on every call, so it cannot hold a stale copy."""
    state = _state()
    _allow(state)
    first, second = state.get_authority("AU1"), state.get_authority("AU1")
    assert first == second
    assert first is not second


def test_the_lifecycle_cannot_be_persisted_without_its_decision():
    """V3 and V10 were both "decisions were checkpointed, authorities were not".
    One record cannot be half-written: the lifecycle is a field of the decision."""
    state = _state()
    _allow(state)
    state.revoke_outstanding_authorities()

    snapshot = json.loads(json.dumps(state.to_snapshot()))
    assert "authorities" not in snapshot
    assert snapshot["decisions"][0]["revoked"] is True

    restored = RunState.from_snapshot(snapshot, state.history)
    assert restored.get_authority("AU1").revoked


def test_issued_at_is_recorded_not_reconstructed():
    """Audit 1's finding. It was briefly derived as `expires_at - TTL`, which would
    silently rewrite history if the constant ever changed. A derivation must rest on
    authoritative state, not on a program constant."""
    state = _state()
    result = _allow(state)
    stored = state.get_stored_decision("AU1")
    assert stored.execution_issued_at is not None
    assert result.payment_authority.issued_at == stored.execution_issued_at

    restored = RunState.from_snapshot(json.loads(json.dumps(state.to_snapshot())), state.history)
    assert restored.get_authority("AU1").issued_at == stored.execution_issued_at


# --- the NEW risk the merge introduces, pinned ------------------------------------


@pytest.mark.parametrize("mutate", [
    lambda s: s.revoke_outstanding_authorities(),
    lambda s: s.revoke_authority("AU1"),
    lambda s: s.consume_authority("AU1", executed_at=datetime.now(timezone.utc), now=datetime.now(timezone.utc)),
    lambda s: s.issue_authority("AU1", mandate_id="TM_OTHER", policy_version="other"),
])
def test_no_lifecycle_transition_alters_the_decision_content(mutate):
    """The decision record is no longer wholly immutable — the lifecycle mutates in
    place. That is the price of deleting the second dict, and this is the guard:
    no lifecycle transition may touch the decision, the money, the merchant or the
    basket it was made on."""
    state = _state()
    _allow(state)
    before = state.get_stored_decision("AU1")
    core_before = (before.decision, before.billing_amount_chf, before.merchant_id, before.basket_key, before.timestamp)

    mutate(state)

    after = state.get_stored_decision("AU1")
    assert (after.decision, after.billing_amount_chf, after.merchant_id, after.basket_key, after.timestamp) == core_before


def test_a_decision_without_an_execution_lifecycle_still_fails_closed():
    """Collapsing the records does not make the V2 shape impossible — a caller can
    still fail to issue. It stays fail-closed."""
    state = _state()
    _allow(state)
    state._decisions["AU1"] = replace(state._decisions["AU1"], execution_expires_at=None, execution_issued_at=None)

    assert state.get_authority("AU1") is None
    with pytest.raises(PaymentError, match="no payment authority"):
        MockPSP(state).charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("400"), merchant_id=MERCHANT_ID)


def test_a_non_allow_decision_never_projects_an_authority():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=10, currency="CHF", scope="purchase")])
    state = _state()
    result = evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID), mandate, state)
    assert result.decision == "block"
    assert state.get_authority("AU1") is None
    assert PaymentAuthority.project(state.get_stored_decision("AU1")) is None


def test_an_old_checkpoint_without_lifecycle_fails_closed_rather_than_opening():
    """Audit 2: a checkpoint written by the two-record build carries an
    `authorities` array the new code ignores. The restored run must refuse to
    charge, not charge unconstrained."""
    state = _state()
    _allow(state)
    legacy = json.loads(json.dumps(state.to_snapshot()))
    for decision in legacy["decisions"]:
        for field in ("execution_issued_at", "execution_expires_at", "revoked", "consumed_at"):
            decision.pop(field, None)
    legacy["authorities"] = [{"authorization_id": "AU1"}]  # the old shape, now ignored

    restored = RunState.from_snapshot(legacy, state.history)
    assert restored.get_authority("AU1") is None
    with pytest.raises(PaymentError):
        MockPSP(restored).charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("400"), merchant_id=MERCHANT_ID)

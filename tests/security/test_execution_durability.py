"""V9 and V10: two ways the payment boundary answered for a transaction it had
not executed, or executed twice.

V9  `charge_id` idempotency compared `authorization_id` and `amount` but NOT
    `merchant_id`. Asking to pay a DIFFERENT merchant with a reused charge_id
    returned the original record as a success. No new money moved -- but the
    caller was told the charge to that merchant had succeeded, which in any
    integration that ships goods or settles on that response is a real answer to
    the wrong question. It was also simply inconsistent: the same function
    refuses a mismatched authorization_id or amount.

V10 `consumed_at` was set in memory and never written to the checkpoint, because
    nothing calls `_save_checkpoint` after a charge -- only after decisions and
    resolutions. So a genuine crash (checkpoint predating the charge) restored an
    unconsumed authority and the same authorization executed twice: CHF 200 moved
    against an approved CHF 100.

    V10 falsifies the deep-security pass's V8 fix. That pass's corpus case N03
    passed only because the test called `to_snapshot()` AFTER charging, which no
    production sequence does. A test generous enough to snapshot at the convenient
    moment proved nothing.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, RunState

MERCHANT_ID = "ME_TEST_0001"
OTHER_MERCHANT = "ME_TEST_0002"


def _state():
    return RunState(
        history=HistoryIndex({"CA_TEST": frozenset({MERCHANT_ID, OTHER_MERCHANT})}, available=True),
        card_id="CA_TEST",
    )


def _approved(state, amount=100.0):
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])
    result = evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=amount, merchant_id=MERCHANT_ID), mandate, state)
    assert result.decision == "allow"
    return result


# --- V9: the idempotency key must not answer for a different merchant ------------


def test_reusing_a_charge_id_for_a_different_merchant_is_refused():
    state = _state()
    _approved(state)
    psp = MockPSP(state)
    psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)
    with pytest.raises(PaymentError, match="merchant"):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=OTHER_MERCHANT)


def test_an_exact_retry_is_still_idempotent():
    """The narrowing must not break genuine retries: same key, same everything."""
    state = _state()
    _approved(state)
    psp = MockPSP(state)
    first = psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)
    again = psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)
    assert again is first


# --- V10: consumption must be durable before money is treated as moved -----------


def test_a_crash_after_charging_cannot_execute_twice(tmp_path):
    """The real production sequence: a checkpoint is written after the DECISION,
    the charge happens later, the process dies. Restoring from that checkpoint
    must not resurrect a spendable authority."""
    state = _state()
    _approved(state)
    checkpoint = tmp_path / "run.json"
    checkpoint.write_text(json.dumps(state.to_snapshot()))  # written BEFORE the charge

    psp = MockPSP(state, persist=lambda: checkpoint.write_text(json.dumps(state.to_snapshot())))
    psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)

    restored = RunState.from_snapshot(json.loads(checkpoint.read_text()), state.history)
    assert restored.get_authority("AU1").consumed_at is not None, "consumption must be on disk, not only in memory"

    psp_after_restart = MockPSP(restored)
    with pytest.raises(PaymentError, match="already executed"):
        psp_after_restart.charge(charge_id="CH2", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)
    # The restored run knows the execution happened -- that is precisely what was
    # missing before, and it is why the second attempt is refused.
    assert psp_after_restart.is_charged("AU1")


def test_consumption_is_durable_before_the_record_exists(tmp_path):
    """Ordering, not just presence. If the process dies between consuming and
    returning the record, the safe outcome is a dead authority and no money --
    not a live authority and money already gone. So the persist hook must have
    run before the charge record is created."""
    state = _state()
    _approved(state)
    seen: list[str | None] = []

    def persist() -> None:
        authority = state.get_authority("AU1")
        seen.append(authority.consumed_at.isoformat() if authority.consumed_at else None)
        raise RuntimeError("crash during persistence")

    psp = MockPSP(state, persist=persist)
    with pytest.raises(RuntimeError, match="crash during persistence"):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)

    assert seen and seen[0] is not None, "the authority must already be consumed when persistence runs"
    assert psp.charge_record("CH1") is None, "no charge record may exist if persistence did not complete"


def test_a_psp_without_a_persist_hook_still_refuses_in_process_double_execution():
    """Durability is about crashes. Within one process, single-use holds with or
    without a hook."""
    state = _state()
    _approved(state)
    psp = MockPSP(state)
    psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)
    with pytest.raises(PaymentError, match="already executed"):
        psp.charge(charge_id="CH2", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)


# --- the boundary, pinned rather than implied ------------------------------------


def test_without_a_persist_hook_single_use_is_NOT_durable(tmp_path):
    """Pinned deliberately, as a known and stated limitation rather than a claim.

    Single-use is durable *exactly when* the executor is given a persist hook. With
    no hook, consumption lives only in memory, so restoring the last checkpoint --
    which is written after a DECISION and knows nothing about any charge -- yields
    a spendable authority again. Nothing in the official integration charges at
    all, so this is unreachable there; it is pinned here so that anyone wiring a
    real executor discovers the requirement from a test rather than from an
    incident."""
    state = _state()
    _approved(state)
    checkpoint = tmp_path / "run.json"
    checkpoint.write_text(json.dumps(state.to_snapshot()))

    MockPSP(state).charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)

    restored = RunState.from_snapshot(json.loads(checkpoint.read_text()), state.history)
    assert restored.get_authority("AU1").consumed_at is None  # the limitation, stated
    MockPSP(restored).charge(charge_id="CH2", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)


def test_single_use_does_not_hold_across_two_independent_run_states():
    """The concurrency boundary, pinned. Single-use is a property of ONE RunState.
    Two workers restoring the same checkpoint each hold their own copy, and each
    executes once -- CHF 200 against an approved CHF 100.

    Closing this needs a single shared store with an atomic compare-and-set on
    consumption, which this prototype deliberately does not build. The guarantee is
    therefore scoped: single-use holds within one run state, in one process. See
    docs/FINAL_SECURITY_POSITION.md."""
    state = _state()
    _approved(state)
    snapshot = state.to_snapshot()

    worker_a = RunState.from_snapshot(json.loads(json.dumps(snapshot)), state.history)
    worker_b = RunState.from_snapshot(json.loads(json.dumps(snapshot)), state.history)

    a = MockPSP(worker_a).charge(charge_id="CA", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)
    b = MockPSP(worker_b).charge(charge_id="CB", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)
    assert a.amount_chf + b.amount_chf == Decimal("200.0")

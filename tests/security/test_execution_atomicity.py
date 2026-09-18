"""V13 and V14: the payment boundary validated an authority, then consumed it as a
separate step. Anything that changed the authority in between was ignored.

`MockPSP.charge` checked `revoked` / `consumed_at` / expiry and then called
`RunState.consume_authority`, which re-read the authority and wrote `consumed_at`
onto it **without re-validating anything**. Classic check-then-act.

V13  A revocation landing inside that window was overwritten rather than obeyed:
     the customer hit the brake while a charge was in flight, and the money moved
     anyway. The resulting authority was both revoked AND consumed.

V14  Two threads both passed the `consumed_at is None` check and both consumed:
     CHF 200 against an approved CHF 100.

Neither was reachable in the earlier 24-thread test, because that test raced
identical calls through one PSP instance where the window is a few bytecodes wide
and the GIL closed it by luck. A real payment boundary does external work between
those two points, so the window is milliseconds, not microseconds. These tests
widen it deliberately -- that is what a real capture call would do.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import AuthorityError, HistoryIndex, RunState

MERCHANT_ID = "ME_TEST_0001"


def _approved_run():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT_ID})}, available=True), card_id="CA_TEST")
    result = evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=100.0, merchant_id=MERCHANT_ID), mandate, state)
    assert result.decision == "allow"
    return state


def _widen_the_window(state: RunState, seconds: float = 0.05):
    """Stand in for the external work a real capture performs between the wallet's
    checks and the moment it records the authority as spent."""
    original = state.consume_authority

    def slow(*args, **kwargs):
        time.sleep(seconds)
        return original(*args, **kwargs)

    state.consume_authority = slow  # type: ignore[method-assign]


# --- V13: a revocation in flight must win -----------------------------------------


def test_a_revocation_during_a_charge_is_obeyed_not_overwritten():
    state = _approved_run()
    _widen_the_window(state)
    psp = MockPSP(state)
    outcome: dict[str, object] = {}

    def charge() -> None:
        try:
            outcome["record"] = psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID)
        except PaymentError as exc:
            outcome["refused"] = str(exc)

    thread = threading.Thread(target=charge)
    thread.start()
    time.sleep(0.02)                            # the charge has passed its checks
    state.revoke_outstanding_authorities()      # the customer hits the brake
    thread.join()

    assert "record" not in outcome, "money moved on an authority revoked before it was consumed"
    assert "refused" in outcome
    assert not psp.is_charged("AU1")


def test_a_revoked_authority_cannot_be_consumed_even_directly():
    """The check belongs to the state transition itself, not only to its caller."""
    state = _approved_run()
    state.revoke_outstanding_authorities()
    with pytest.raises(AuthorityError, match="revoked"):
        state.consume_authority("AU1", executed_at=state.get_authority("AU1").issued_at, now=state.get_authority("AU1").issued_at)


# --- V14: two concurrent charges must not both consume -----------------------------


def test_two_concurrent_charges_cannot_both_execute():
    state = _approved_run()
    _widen_the_window(state)
    psp = MockPSP(state)
    executed, refused = [], []

    def worker(i: int) -> None:
        try:
            executed.append(psp.charge(charge_id=f"CH{i}", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID))
        except PaymentError as exc:
            refused.append(str(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(executed) == 1, f"{len(executed)} executions of one authorization"
    assert len(refused) == 1


def test_many_concurrent_charges_still_execute_exactly_once():
    state = _approved_run()
    _widen_the_window(state, seconds=0.02)
    psp = MockPSP(state)
    executed, refused = [], []
    barrier = threading.Barrier(12)

    def worker(i: int) -> None:
        barrier.wait()
        try:
            executed.append(psp.charge(charge_id=f"CH{i}", authorization_id="AU1", amount_chf=Decimal("100.0"), merchant_id=MERCHANT_ID))
        except PaymentError as exc:
            refused.append(str(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(executed) == 1, f"{len(executed)} executions across 12 racing threads"
    assert len(refused) == 11


def test_double_consume_is_refused_at_the_state_transition():
    state = _approved_run()
    authority = state.get_authority("AU1")
    state.consume_authority("AU1", executed_at=authority.issued_at, now=authority.issued_at)
    with pytest.raises(AuthorityError, match="already"):
        state.consume_authority("AU1", executed_at=authority.issued_at, now=authority.issued_at)


def test_consuming_an_expired_authority_is_refused_on_the_trusted_clock():
    """Expiry is re-checked at the transition too, against the clock the boundary
    passes in -- never against the caller's `now=`, which only timestamps."""
    from datetime import timedelta

    state = _approved_run()
    authority = state.get_authority("AU1")
    with pytest.raises(AuthorityError, match="expired"):
        state.consume_authority(
            "AU1",
            executed_at=authority.issued_at,
            now=authority.expires_at + timedelta(seconds=1),
        )

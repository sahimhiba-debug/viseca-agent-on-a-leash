"""The limitations we accept, pinned as executable tests.

A limitation recorded only in prose drifts. These tests assert the CURRENT
behaviour, so that if any of it silently changes -- in either direction -- the
suite says so and the documentation can be corrected.

Each one is reproduced end-to-end rather than asserted from reasoning.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, RunState

M = "ME_KNOWN"
T0 = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


def _mandate():
    return make_mandate(instruction="Order our household groceries.", hard_rules=[
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=200,
                 currency="CHF", scope="purchase"),
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=300,
                 currency="CHF", scope="period", period_days=7)])


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({M})}, available=True), card_id="CA_TEST")


def _spend_one_run(mandate, tag):
    state = _state()
    total = Decimal(0)
    for i in range(10):
        event = make_event(mandate=mandate, authorization_id=f"{tag}_{i}", amount=200.0,
                           merchant_id=M, timestamp=T0 + timedelta(hours=3 * i))
        event["authorization"]["items"][0]["item_name"] = f"g{tag}{i}"
        if evaluate_authorization(event, mandate, state).decision == "allow":
            total += Decimal("200")
    return total


def test_the_rolling_cap_is_enforced_PER_RUN_not_per_mandate():
    """LIMITATION, with its protocol justification and its mitigation.

    One mandate reused across N runs authorizes N x the cap. Ten runs put CHF 2,000
    through a CHF 300 / 7-day ceiling.

    This is the official period semantics rather than our choice: the pack states
    that the platform's own counter, `context.approved_spend_in_period_chf`, is
    "recomputed from the decisions actually taken in the run". Period tracking is
    then "deliberately left to your control layer", so we could in principle track
    across runs -- but the mandate is the only key we would have, and that is the
    same re-scoping of the authoritative ledger we declined elsewhere.

    MITIGATION, and it is the reason this is accepted rather than urgent: the agent
    does not control run boundaries. `POST /v1/scenario-runs` is called by the
    solution, not by the shopping agent, which proposes purchases inside a run the
    wallet has already started."""
    mandate = _mandate()
    one = _spend_one_run(mandate, "A")
    assert one <= Decimal("300")
    across = sum(_spend_one_run(mandate, f"R{n}") for n in range(5))
    assert across == 5 * one, "cross-run spend is linear in the number of runs"
    assert across > Decimal("300"), "if this ever fails, the limitation is gone -- update the docs"


def test_single_use_is_per_process_not_global():
    """LIMITATION. Two workers restoring the same checkpoint can each consume the
    same authorization once. This is why we say at-most-once, per process, and never
    exactly-once.

    Reproduced end-to-end through the real checkpoint round-trip rather than argued
    from the absence of a lock."""
    mandate, state = _mandate(), _state()
    event = make_event(mandate=mandate, authorization_id="W1", amount=200.0,
                       merchant_id=M, timestamp=T0)
    event["authorization"]["items"][0]["item_name"] = "g"
    assert evaluate_authorization(event, mandate, state).decision == "allow"

    snapshot = json.loads(json.dumps(state.to_snapshot()))
    worker_a = RunState.from_snapshot(json.loads(json.dumps(snapshot)), state.history)
    worker_b = RunState.from_snapshot(json.loads(json.dumps(snapshot)), state.history)

    charged = 0
    for label, worker in (("A", worker_a), ("B", worker_b)):
        try:
            MockPSP(worker).charge(charge_id=f"C{label}", authorization_id="W1",
                                   amount_chf=Decimal("200"), merchant_id=M)
            charged += 1
        except PaymentError:
            pass
    assert charged == 2, (
        "two workers no longer double-charge -- if this fails, single-use became "
        "durable across processes and the claim can be strengthened")


def test_a_revoked_purchase_still_consumes_window_budget():
    """LIMITATION, and arguably correct. Revocation kills the authority to spend, not
    the record that a decision was made, so the amount stays in the rolling window.
    Conservative, and the customer cannot undo it -- but revocation also blocks every
    further purchase in the run, so there is no in-run liveness loss."""
    mandate, state = _mandate(), _state()
    event = make_event(mandate=mandate, authorization_id="V1", amount=200.0,
                       merchant_id=M, timestamp=T0)
    event["authorization"]["items"][0]["item_name"] = "g"
    evaluate_authorization(event, mandate, state)
    state.revoke_outstanding_authorities()
    assert state.total_approved_spend_chf() == Decimal("200")

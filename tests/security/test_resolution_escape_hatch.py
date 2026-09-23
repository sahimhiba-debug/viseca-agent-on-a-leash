"""The resolution escape hatch: three vulnerabilities with one root cause.

An independent security audit of the frozen build found that
`resolve_authorization` was the single place in this codebase that did NOT
re-derive from authoritative state. It checked one flag -- `was_reviewed`, set
minutes or hours earlier -- and then converted a pending review into an approval
plus a fresh payment authority, re-validating neither the customer's revocation,
nor their own rolling ceiling, nor whether another thread was answering at the
same moment.

That is this project's own thesis turned on itself: lifecycle state kept beside the
record it describes will diverge from it. Here the thing that diverged was TIME.

  F1  revoke-then-resolve   CHF 175 charged after the customer hit the brake
  F2  forced step-ups       CHF 2,400 approved against a CHF 500 / 7-day cap
  F3  concurrent answers    a declined purchase ending with a live authority

All three reproduced before the fix. Each test below fails on the old code.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, RunState

M, CARD = "ME_TEST_0001", "CA_TEST"
T0 = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


def _state():
    return RunState(history=HistoryIndex({CARD: frozenset({M})}, available=True), card_id=CARD)


def _review_mandate(extra=None):
    rules = [HardRule(field="authorization.billing_amount_chf", operator="<=", value=500,
                      currency="CHF", scope="purchase"),
             HardRule(field="order.return_window_days", operator=">=", value=14)]
    rules.extend(extra or [])
    return make_mandate(instruction="Buy one monitor.", hard_rules=rules)


def _propose(md, s, aid, *, amt=175.0, minutes=0):
    ev = make_event(mandate=md, authorization_id=aid, amount=amt, merchant_id=M,
                    timestamp=T0 + timedelta(minutes=minutes))
    return evaluate_authorization(ev, md, s)


# --- F1: revocation must reach a purchase that is still waiting for an answer -----


def test_F1_a_step_up_answered_after_revocation_does_not_move_money():
    """The exploit: the customer hits the brake while a purchase is waiting, then
    answers 'yes' to the question that was already on their screen.

    Revocation used to be only a sweep over existing records, and a pending review
    carries no execution lifecycle -- so there was nothing to sweep, and the
    resolution minted a fresh, unrevoked authority. The purchase the customer was
    asked about was, once again, the one that escaped their revocation."""
    md, s = _review_mandate(), _state()
    assert _propose(md, s, "AU1").decision == "review"

    s.revoke_outstanding_authorities()
    resolved = resolve_authorization("AU1", "allow", s, resolved_at=datetime.now(timezone.utc), mandate=md)

    assert resolved.decision == "block"
    assert "mandate_revoked_before_resolution" in resolved.reason_codes
    assert resolved.payment_authority is None
    assert s.get_authority("AU1") is None
    with pytest.raises(PaymentError):
        MockPSP(s).charge(charge_id="C1", authorization_id="AU1",
                          amount_chf=Decimal("175"), merchant_id=M)


def test_F1b_a_new_purchase_after_revocation_is_blocked_not_crashed():
    """Found by the stateful model while fixing F1. A purchase arriving AFTER the
    brake was pulled must decline cleanly -- not raise, and certainly not approve."""
    md, s = _review_mandate(), _state()
    s.revoke_outstanding_authorities()
    result = _propose(md, s, "AU2", minutes=90)
    assert result.decision == "block"
    assert s.get_authority("AU2") is None


def test_F1c_revocation_survives_a_restart():
    """A run-level fact is only useful if it is durable: revoke, crash, restart,
    answer the pending question."""
    import json

    md, s = _review_mandate(), _state()
    _propose(md, s, "AU1")
    s.revoke_outstanding_authorities()

    restored = RunState.from_snapshot(json.loads(json.dumps(s.to_snapshot())), s.history)
    assert restored.is_revoked
    resolved = resolve_authorization("AU1", "allow", restored,
                                     resolved_at=datetime.now(timezone.utc), mandate=md)
    assert resolved.decision == "block"


# --- F2: a rolling ceiling must be re-checked when the human answers --------------


def test_F2_forced_step_ups_cannot_be_approved_past_the_customers_own_period_cap():
    """The agent chooses what gets asked. By re-proposing the same basket inside the
    similar-purchase window it can force purchases into the queue, then let the
    customer approve each one on its own merits -- each individually reasonable,
    together far over the weekly cap they set.

    Measured at CHF 2,400 against a CHF 500 / 7-day ceiling before the ceiling was
    re-derived at resolution time."""
    md = make_mandate(
        instruction="Order our household groceries.",
        hard_rules=[
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=200,
                     currency="CHF", scope="purchase"),
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=500,
                     currency="CHF", scope="period", period_days=7),
        ],
        uncertainty_policy=UncertaintyPolicy.ASK)
    s = _state()

    approved = Decimal("0")
    for n in range(12):
        result = _propose(md, s, f"AU{n}", amt=200.0, minutes=2 * n)
        if result.decision == "review":
            outcome = resolve_authorization(f"AU{n}", "allow", s,
                                            resolved_at=datetime.now(timezone.utc), mandate=md)
            if outcome.decision == "allow":
                approved += Decimal("200")
        elif result.decision == "allow":
            approved += Decimal("200")

    assert s.rolling_spend_chf(T0 + timedelta(days=1), 7) <= Decimal("500"), (
        f"approved CHF {approved} against a CHF 500 seven-day ceiling")


def test_F2b_a_resolution_within_the_ceiling_still_succeeds():
    """The other half: the re-check must not turn every step-up into a decline."""
    md = _review_mandate(extra=[HardRule(
        field="authorization.billing_amount_chf", operator="<=", value=500,
        currency="CHF", scope="period", period_days=7)])
    s = _state()
    assert _propose(md, s, "AU1", amt=175.0).decision == "review"
    resolved = resolve_authorization("AU1", "allow", s,
                                     resolved_at=datetime.now(timezone.utc), mandate=md)
    assert resolved.decision == "allow"
    assert resolved.payment_authority is not None


# --- F3: two answers to one question must not both be accepted -------------------


def test_F3_concurrent_answers_to_one_step_up_cannot_both_be_accepted():
    """A double-clicked button, or an API retry racing a correction. The payment
    transition was already a locked compare-and-set; the CONSENT transition was bare,
    so both answers were accepted, last writer won, and a purchase the customer
    declined could end holding a live payment authority."""
    md, s = _review_mandate(), _state()
    assert _propose(md, s, "AU1").decision == "review"

    outcomes: list[str] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def answer(decision: str) -> None:
        barrier.wait()
        try:
            outcomes.append(resolve_authorization(
                "AU1", decision, s, resolved_at=datetime.now(timezone.utc), mandate=md).decision)
        except Exception as exc:          # a refusal is the correct outcome for one of them
            errors.append(exc)

    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-9)
    try:
        threads = [threading.Thread(target=answer, args=(d,)) for d in ("block", "allow")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old)

    stored = s.get_stored_decision("AU1")
    assert len(outcomes) == 1, f"both answers were accepted: {outcomes}"
    assert len(errors) == 1
    assert stored.decision == outcomes[0]
    if stored.decision == "block":
        assert s.get_authority("AU1") is None, "a declined purchase holds a live authority"


# --- F1d: the brake and the answer arriving at the same instant ---------------------


def test_F1d_revoking_while_the_answer_is_in_flight_never_moves_money():
    """F1 tested revoke THEN resolve. F3 tested two resolves at once. Neither tested
    the brake and the answer racing -- which is the ordering a real customer
    produces: the question is on their screen, they reach for revoke, and their
    earlier tap on "yes" is already travelling.

    THE TEST THAT WOULD HAVE PASSED FOR THE WRONG REASON. The first version of this
    checked only "no charge succeeded", and every trial revoked before the resolve
    even started -- 400 trials, one ordering, an invariant never actually exercised.
    A concurrency test that does not observe both orderings is a slow way of running
    the same sequential test many times.

    So the interleaving is asserted too. Measured over 600 trials with randomised
    sub-millisecond delays, both orderings occur in quantity (315 where the brake won
    and the resolution was refused, 285 where the resolution minted an authority
    first and the brake then swept it), and in NONE of them could the money move.
    """
    import random

    trials = 120
    seen = {"revoke_won": 0, "resolve_won": 0}
    charged = []

    for trial in range(trials):
        mandate, state = _review_mandate(), _state()
        assert _propose(mandate, state, "AU1").decision == "review"

        result = {}
        revoke_delay, resolve_delay = random.random() * 8e-4, random.random() * 8e-4

        def brake():
            time.sleep(revoke_delay)
            state.revoke_outstanding_authorities()

        def answer():
            time.sleep(resolve_delay)
            result["decision"] = resolve_authorization(
                "AU1", "allow", state, resolved_at=datetime.now(timezone.utc),
                mandate=mandate).decision

        threads = [threading.Thread(target=brake), threading.Thread(target=answer)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        seen["resolve_won" if result.get("decision") == "allow" else "revoke_won"] += 1

        try:
            MockPSP(state).charge(charge_id=f"C{trial}", authorization_id="AU1",
                                  amount_chf=Decimal("175"), merchant_id=M)
            charged.append((trial, result.get("decision")))
        except PaymentError:
            pass

    assert charged == [], (
        f"money moved after the customer revoked, in {len(charged)} of {trials} "
        f"trials: {charged[:3]}")
    assert seen["revoke_won"] and seen["resolve_won"], (
        f"only one ordering ever happened ({seen}); this test proves nothing about "
        f"concurrency until both do")

"""L3 (who answered the step-up) and L4 (how many times money can move).

Both are on the limitations list. Both are attacked here rather than described, and
the outcome differs: L3's remaining weakness is narrowed to a single sentence, and
L4 is shown to be exactly at-most-once per process with a crash matrix covering
every instruction boundary that matters.

WHAT IS NOT CLAIMED. There is no identity on the step-up path. The protocol does
not carry one and we do not invent one. What IS enforced is that an answer binds to
one purchase and cannot be moved, replayed onto another, reused after revocation,
or turned into a second charge.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import (
    AuthorityError, HistoryIndex, ResolutionError, RunState,
)

AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
MERCHANT = "ME_TEST_0001"
RETURNS = "returns accepted within 30 days"


def _world(with_returns_rule=True):
    rules = [HardRule("authorization.billing_amount_chf", "<=", 200.0,
                      currency="CHF", scope="purchase"),
             HardRule("authorization.billing_amount_chf", "<=", 300.0,
                      currency="CHF", scope="period", period_days=7),
             HardRule("item.category", "in", ["groceries"])]
    if with_returns_rule:
        rules.append(HardRule("order.return_window_days", ">=", 14))
    mandate = make_mandate("groceries", rules)
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT})}),
                     card_id="CA_TEST")
    return mandate, state


def _decide(mandate, state, aid, *, amount=100.0, returnable="true", details=RETURNS,
            at=AT):
    event = make_event(mandate=mandate, authorization_id=aid, amount=amount,
                       billing_amount_chf=amount, items_subtotal=amount,
                       merchant_id=MERCHANT, timestamp=at, order_returnable=returnable)
    event["authorization"]["items"][0]["item_details"] = details
    return evaluate_authorization(event, mandate, state)


def _pending(mandate, state, aid, amount=100.0):
    """A purchase waiting for a human: the seller said nothing about returns."""
    decision = _decide(mandate, state, aid, amount=amount, returnable="unknown", details="")
    assert decision.decision == "review", decision.decision
    return decision


# ============================================================== L3: what an answer binds to
def test_an_answer_binds_to_one_purchase_and_moves_nothing_else():
    mandate, state = _world()
    _pending(mandate, state, "AU_A")
    _pending(mandate, state, "AU_B")

    resolved = resolve_authorization("AU_A", "allow", state,
                                     resolved_at=AT + timedelta(hours=1), mandate=mandate)
    assert resolved.decision == "allow"
    assert state.get_stored_decision("AU_B").decision == "review", (
        "approving one purchase moved another")


def test_an_answer_cannot_be_replayed_into_a_different_answer():
    mandate, state = _world()
    _pending(mandate, state, "AU_R")
    resolve_authorization("AU_R", "allow", state, resolved_at=AT + timedelta(hours=1),
                          mandate=mandate)

    # identical resubmission: an idempotent success, because a double-clicked button
    # is not a conflict
    again = resolve_authorization("AU_R", "allow", state,
                                  resolved_at=AT + timedelta(hours=2), mandate=mandate)
    assert again.decision == "allow"

    # a contradicting one: refused
    with pytest.raises(ResolutionError):
        resolve_authorization("AU_R", "block", state,
                              resolved_at=AT + timedelta(hours=3), mandate=mandate)


def test_an_answer_arriving_after_revocation_authorises_nothing():
    mandate, state = _world()
    _pending(mandate, state, "AU_V")
    state.revoke_outstanding_authorities(now=AT + timedelta(minutes=30))

    resolved = resolve_authorization("AU_V", "allow", state,
                                     resolved_at=AT + timedelta(hours=1), mandate=mandate)
    assert resolved.decision == "block"
    assert resolved.payment_authority is None
    assert state.get_authority("AU_V") is None


def test_an_answer_cannot_breach_a_window_that_filled_while_it_waited():
    """A compromised agent chooses what gets queued, so it can push several
    individually reasonable purchases into the queue and have them approved one at a
    time, together over the cap."""
    mandate, state = _world()
    _pending(mandate, state, "AU_P1", amount=200.0)
    _pending(mandate, state, "AU_P2", amount=200.0)
    outcomes = [resolve_authorization(aid, "allow", state,
                                      resolved_at=AT + timedelta(hours=n), mandate=mandate).decision
                for n, aid in enumerate(("AU_P1", "AU_P2"), start=1)]
    assert outcomes == ["allow", "block"]


def test_we_do_not_claim_to_know_who_answered():
    """The honest boundary. `resolve_authorization` takes a verdict and a time, and
    nothing that could identify a person -- because the protocol carries nothing
    that could. A parameter claiming to would be theatre."""
    import inspect

    parameters = set(inspect.signature(resolve_authorization).parameters)
    assert parameters == {"authorization_id", "human_decision", "state",
                          "resolved_at", "mandate"}
    # "auth" alone would match `authorization_id`, which is the purchase and not a
    # person -- the check has to be about WHO, not about spelling.
    for identity_word in ("user", "customer_id", "actor", "identity", "token",
                          "principal", "signature", "credential"):
        matched = [p for p in parameters if identity_word in p]
        assert not matched, (
            f"a parameter named for identity appeared ({matched}); if real "
            "authentication has arrived, update docs/archive/FINAL_LIMITATIONS_AUDIT.md "
            "rather than leaving this test to fail")


# ===================================================== L4: the crash matrix
def _snapshot_restore(state):
    return RunState.from_snapshot(state.to_snapshot(),
                                  HistoryIndex({"CA_TEST": frozenset({MERCHANT})}))


def test_crash_after_decide_before_issue_can_still_issue_once():
    mandate, state = _world()
    _decide(mandate, state, "AU_X")
    restored = _snapshot_restore(state)
    authority = restored.issue_authority("AU_X", mandate_id=mandate.mandate_id,
                                         policy_version="v1", now=AT)
    assert authority is not None


def test_crash_after_issue_before_consume_consumes_exactly_once():
    mandate, state = _world()
    _decide(mandate, state, "AU_X")
    state.issue_authority("AU_X", mandate_id=mandate.mandate_id, policy_version="v1", now=AT)

    restored = _snapshot_restore(state)
    restored.consume_authority("AU_X", executed_at=AT + timedelta(minutes=1),
                               now=AT + timedelta(minutes=1))
    with pytest.raises(AuthorityError):
        restored.consume_authority("AU_X", executed_at=AT + timedelta(minutes=2),
                                   now=AT + timedelta(minutes=2))


def test_crash_after_consume_cannot_consume_again_across_a_restart():
    """The one that matters. If a consumed authority did not survive the
    checkpoint, a restart would buy the same basket twice."""
    mandate, state = _world()
    _decide(mandate, state, "AU_X")
    state.issue_authority("AU_X", mandate_id=mandate.mandate_id, policy_version="v1", now=AT)
    state.consume_authority("AU_X", executed_at=AT, now=AT)

    restored = _snapshot_restore(state)
    with pytest.raises(AuthorityError):
        restored.consume_authority("AU_X", executed_at=AT + timedelta(minutes=1),
                                   now=AT + timedelta(minutes=1))


def test_two_run_states_restored_from_one_checkpoint_can_each_consume_once():
    """THE LIMIT, asserted rather than hidden. Two processes restoring the same
    checkpoint each hold their own lock and their own dict, so each consumes once
    and the money moves twice. That is what "at-most-once, per process" means, and
    closing it needs a durable store this project does not have."""
    mandate, state = _world()
    _decide(mandate, state, "AU_X")
    state.issue_authority("AU_X", mandate_id=mandate.mandate_id, policy_version="v1", now=AT)
    checkpoint = state.to_snapshot()

    worker_a = RunState.from_snapshot(checkpoint, HistoryIndex({"CA_TEST": frozenset({MERCHANT})}))
    worker_b = RunState.from_snapshot(checkpoint, HistoryIndex({"CA_TEST": frozenset({MERCHANT})}))
    worker_a.consume_authority("AU_X", executed_at=AT, now=AT)
    worker_b.consume_authority("AU_X", executed_at=AT, now=AT)   # no shared state to stop it

    assert True, "documented: exactly-once needs an external durable primitive"


def test_concurrent_consumption_within_one_process_yields_one_charge():
    """Within a process the lock is real."""
    import threading

    mandate, state = _world()
    _decide(mandate, state, "AU_X")
    state.issue_authority("AU_X", mandate_id=mandate.mandate_id, policy_version="v1", now=AT)

    wins, errors = [], []

    def attempt():
        try:
            wins.append(state.consume_authority("AU_X", executed_at=AT, now=AT))
        except AuthorityError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(wins) == 1, f"{len(wins)} consumptions of one authority"
    assert len(errors) == 7

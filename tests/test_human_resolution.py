"""Phase 8: a human's answer to a step_up must be scoped to exactly that
authorization, must never touch the standing mandate, and must not be
re-appliable. "A yes is this authorization. It is not a new wallet."
"""

from datetime import datetime, timedelta, timezone

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex, ResolutionError, RunState


def _reviewed_state_and_mandate(**event_kwargs):
    mandate = make_mandate(hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")])
    state = RunState(history=HistoryIndex.empty(), card_id="CA_TEST")
    kwargs = {"amount": 50.0, **event_kwargs}
    event = make_event(mandate=mandate, authorization_id="AU1", **kwargs)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "review"
    return mandate, state, event


def test_resolve_approve_records_allow_and_counts_spend():
    mandate, state, _ = _reviewed_state_and_mandate()
    result = resolve_authorization("AU1", "allow", state, resolved_at=datetime.now(timezone.utc))
    assert result.decision == "allow"
    assert state.total_approved_spend_chf() == 50


def test_resolve_decline_never_executes_and_does_not_count_spend():
    mandate, state, _ = _reviewed_state_and_mandate()
    result = resolve_authorization("AU1", "block", state, resolved_at=datetime.now(timezone.utc))
    assert result.decision == "block"
    assert state.total_approved_spend_chf() == 0


def test_repeating_the_same_resolution_is_idempotent():
    """A retried /resolve call (network retry, a double-tap that both landed) with
    the SAME answer must succeed harmlessly, not error and not double-count."""
    mandate, state, _ = _reviewed_state_and_mandate()
    first = resolve_authorization("AU1", "allow", state, resolved_at=datetime.now(timezone.utc))
    second = resolve_authorization("AU1", "allow", state, resolved_at=datetime.now(timezone.utc))
    assert first.decision == second.decision == "allow"
    assert state.total_approved_spend_chf() == 50  # counted exactly once


def test_resolving_with_a_conflicting_answer_after_the_fact_is_an_error_not_a_silent_ignore():
    """Phase 9 'consume twice': once resolved, a DIFFERENT answer must be rejected
    loudly, not silently discarded and not silently allowed to overwrite the first
    (real) answer the customer gave."""
    mandate, state, _ = _reviewed_state_and_mandate()
    resolve_authorization("AU1", "allow", state, resolved_at=datetime.now(timezone.utc))
    with pytest.raises(ResolutionError):
        resolve_authorization("AU1", "block", state, resolved_at=datetime.now(timezone.utc))
    assert state.get_stored_decision("AU1").decision == "allow"  # the first answer still stands
    assert state.total_approved_spend_chf() == 50  # unaffected by the rejected second attempt


def test_cannot_resolve_an_authorization_that_was_never_reviewed():
    state = RunState(history=HistoryIndex.empty(), card_id="CA_TEST")
    with pytest.raises(ResolutionError):
        resolve_authorization("AU_NEVER_SEEN", "allow", state, resolved_at=datetime.now(timezone.utc))


def test_cannot_resolve_an_authorization_that_was_auto_decided_and_never_reviewed():
    """Distinguishes 'never seen' from 'seen, but was decided automatically and
    never put to the customer' -- resolving either must fail the same way."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    state = RunState(history=HistoryIndex.empty(), card_id="CA_TEST")
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "allow"
    with pytest.raises(ResolutionError):
        resolve_authorization("AU1", "block", state, resolved_at=datetime.now(timezone.utc))


def test_resolving_a_step_up_does_not_touch_the_mandate():
    """The core invariant: approving one purchase must never widen the standing
    wallet policy for future purchases."""
    mandate, state, _ = _reviewed_state_and_mandate()
    rules_before = mandate.hard_rules
    resolve_authorization("AU1", "allow", state, resolved_at=datetime.now(timezone.utc))
    assert mandate.hard_rules == rules_before  # MandateSnapshot is frozen; nothing could have changed it anyway

    # A second, unrelated purchase against the same still-unfamiliar-merchant rule
    # must be evaluated fresh -- the earlier approval does not carry over.
    event2 = make_event(mandate=mandate, authorization_id="AU2", amount=50.0)
    result2 = evaluate_authorization(event2, mandate, state)
    assert result2.decision == "review"


def test_resolution_amount_comes_from_the_original_review_not_the_caller():
    """`resolve_authorization` takes no amount parameter at all -- the amount that
    counts is whatever the customer was actually shown, sourced from the stored
    review record, never a value a caller could supply fresh (which would let a
    step_up be resolved against a different purchase amount than what was reviewed)."""
    mandate, state, event = _reviewed_state_and_mandate(amount=137.50)
    result = resolve_authorization("AU1", "allow", state, resolved_at=datetime.now(timezone.utc))
    assert result.decision == "allow"
    assert state.total_approved_spend_chf() == 137.50


def test_resolution_uses_the_original_simulated_purchase_time_for_spend_windows_not_real_clock_resolution_time():
    """Phase 6: 'Use simulated purchase time for spending windows, and the real
    clock for response deadlines.' A step_up answered an hour (real time) after it
    was raised must still be attributed to its ORIGINAL simulated timestamp for
    rolling-window purposes -- not the time the human happened to click."""
    purchase_time = datetime(2026, 8, 12, 9, 0, 0, tzinfo=timezone.utc)
    mandate, state, _ = _reviewed_state_and_mandate(timestamp=purchase_time)

    real_resolution_time = purchase_time + timedelta(hours=1)  # human answers an hour later, in real time
    resolve_authorization("AU1", "allow", state, resolved_at=real_resolution_time)

    # A rolling 7-day window measured as of the ORIGINAL purchase time must
    # already include this approval...
    assert state.rolling_spend_chf(purchase_time, period_days=7) == 50
    # ...but a window measured just before the original purchase time must NOT --
    # if the approval had been (wrongly) attributed to the real-clock resolution
    # time, it would still show up here since real_resolution_time is only an hour
    # later, not before purchase_time.
    assert state.rolling_spend_chf(purchase_time - timedelta(minutes=1), period_days=7) == 0

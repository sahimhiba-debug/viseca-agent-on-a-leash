"""Phase 8: a human's answer to a step_up must be scoped to exactly that
authorization, must never touch the standing mandate, and must not be
re-appliable. "A yes is this authorization. It is not a new wallet."
"""

from datetime import datetime, timezone

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex, RunState


def _reviewed_state_and_mandate():
    mandate = make_mandate(hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")])
    state = RunState(history=HistoryIndex.empty(), card_id="CA_TEST")
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "review"
    return mandate, state


def test_resolve_approve_records_allow_and_counts_spend():
    mandate, state = _reviewed_state_and_mandate()
    now = datetime.now(timezone.utc)
    result = resolve_authorization("AU1", "allow", state, billing_amount_chf=50, timestamp=now)
    assert result.decision == "allow"
    assert state.total_approved_spend_chf() == 50


def test_resolve_decline_never_executes_and_does_not_count_spend():
    mandate, state = _reviewed_state_and_mandate()
    now = datetime.now(timezone.utc)
    result = resolve_authorization("AU1", "block", state, billing_amount_chf=50, timestamp=now)
    assert result.decision == "block"
    assert state.total_approved_spend_chf() == 0


def test_resolution_cannot_be_applied_twice():
    """A second resolution attempt on an already-resolved authorization must not
    change or re-count anything -- e.g. a customer double-tapping 'approve', or a
    retried /resolve call."""
    mandate, state = _reviewed_state_and_mandate()
    now = datetime.now(timezone.utc)
    resolve_authorization("AU1", "allow", state, billing_amount_chf=50, timestamp=now)
    second = resolve_authorization("AU1", "block", state, billing_amount_chf=50, timestamp=now)
    assert second.decision == "allow"  # the FIRST resolution wins; a later one cannot flip it
    assert state.total_approved_spend_chf() == 50  # not double-counted, not removed


def test_cannot_resolve_an_authorization_that_was_never_reviewed():
    state = RunState(history=HistoryIndex.empty(), card_id="CA_TEST")
    with pytest.raises(ValueError):
        resolve_authorization("AU_NEVER_SEEN", "allow", state, billing_amount_chf=50, timestamp=datetime.now(timezone.utc))


def test_resolving_a_step_up_does_not_touch_the_mandate():
    """The core invariant: approving one purchase must never widen the standing
    wallet policy for future purchases."""
    mandate, state = _reviewed_state_and_mandate()
    rules_before = mandate.hard_rules
    resolve_authorization("AU1", "allow", state, billing_amount_chf=50, timestamp=datetime.now(timezone.utc))
    assert mandate.hard_rules == rules_before  # MandateSnapshot is frozen; nothing could have changed it anyway

    # A second, unrelated purchase against the same still-unfamiliar-merchant rule
    # must be evaluated fresh -- the earlier approval does not carry over.
    event2 = make_event(mandate=mandate, authorization_id="AU2", amount=50.0)
    result2 = evaluate_authorization(event2, mandate, state)
    assert result2.decision == "review"

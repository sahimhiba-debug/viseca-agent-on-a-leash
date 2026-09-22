"""A checkpoint we cannot read faithfully is one we refuse to read.

THE SEVENTH INSTANCE, AND IT WAS PREDICTED

`docs/ABSENCE.md` sets out one mistake found at six boundaries -- a missing fact
quietly replaced by a present one -- and says the next should be looked for wherever
that substitution happens. `RunState.from_snapshot` was the first place looked, and
it was full of the idiom:

    revoked=d.get("revoked", False)
    consumed_at=... if d.get("consumed_at") else None

which is the ordinary forward-compatible pattern and is exactly wrong here, because
every one of those defaults is the SPENDABLE branch. Measured on a real checkpoint
with a single key removed:

    drop `consumed_at`  ->  a SPENT authority is spendable again      DOUBLE SPEND
    drop `revoked`      ->  a REVOKED authority is live again         REVOCATION UNDONE

Both defeat the two properties this project claims hardest: at-most-once execution,
and an emergency brake that reaches money already authorized.

THE FIX IS THE DISTINCTION, NOT A BLANKET REFUSAL

A validator that rejected every incomplete checkpoint would also reject the one
shape that is a genuine FACT: a decision written by the older two-record build,
carrying no execution lifecycle at all, which means "this was never issued an
authority" and restores safely with nothing to spend. That case has its own test in
`test_minimal_core.py` and still passes.

So the lifecycle is ALL-OR-NOTHING. All four present, or none. A decision claiming
an authority while omitting whether it was spent is not a fact; it is a hole.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import CheckpointError, HistoryIndex, RunState

MERCHANT = "ME_KNOWN"
AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
LIFECYCLE = ("execution_issued_at", "execution_expires_at", "revoked", "consumed_at")


def _mandate():
    return make_mandate(instruction="Order groceries.", hard_rules=[HardRule(
        field="authorization.billing_amount_chf", operator="<=", value=500,
        currency="CHF", scope="purchase")])


def _history():
    return HistoryIndex({"CA_TEST": frozenset({MERCHANT})}, available=True)


def _issued():
    """An approved purchase carrying a live payment authority."""
    mandate = _mandate()
    state = RunState(history=_history(), card_id="CA_TEST")
    event = make_event(mandate=mandate, authorization_id="AU1", amount=400.0,
                       merchant_id=MERCHANT, timestamp=AT)
    event["authorization"]["items"][0].update(item_name="milk", item_category="groceries")
    assert evaluate_authorization(event, mandate, state).decision == "allow"
    state.issue_authority("AU1", mandate_id=mandate.mandate_id,
                          policy_version="v1", now=AT)
    return state


def _snapshot(state):
    return json.loads(json.dumps(state.to_snapshot()))


# ------------------------------------------------------------ the two reproductions
def test_a_spent_authority_cannot_come_back_by_losing_one_key():
    state = _issued()
    state.consume_authority("AU1", executed_at=AT, now=AT)
    assert state.get_authority("AU1").consumed_at is not None

    broken = _snapshot(state)
    for decision in broken["decisions"]:
        decision.pop("consumed_at", None)

    with pytest.raises(CheckpointError) as raised:
        RunState.from_snapshot(broken, _history())
    assert "consumed_at" in str(raised.value)


def test_a_revoked_authority_cannot_come_back_by_losing_one_key():
    state = _issued()
    state.revoke_authority("AU1")
    assert state.get_authority("AU1").revoked is True

    broken = _snapshot(state)
    for decision in broken["decisions"]:
        decision.pop("revoked", None)

    with pytest.raises(CheckpointError) as raised:
        RunState.from_snapshot(broken, _history())
    assert "revoked" in str(raised.value)


@pytest.mark.parametrize("dropped", LIFECYCLE)
def test_any_partial_lifecycle_is_refused(dropped):
    """Not just the two that were reproduced. Any one of the four missing while the
    others are present describes an authority whose fate is unstated."""
    state = _issued()
    broken = _snapshot(state)
    for decision in broken["decisions"]:
        decision.pop(dropped, None)
    with pytest.raises(CheckpointError):
        RunState.from_snapshot(broken, _history())


# -------------------------------------------------- the absence that IS a fact
def test_a_decision_with_no_lifecycle_at_all_still_restores():
    """The older two-record build wrote these, and they are coherent: never issued an
    authority, nothing to spend. Refusing them would be a blanket rule dressed up as
    a principle."""
    state = _issued()
    legacy = _snapshot(state)
    for decision in legacy["decisions"]:
        for key in LIFECYCLE:
            decision.pop(key, None)
    restored = RunState.from_snapshot(legacy, _history())
    assert restored.get_authority("AU1") is None
    assert len(restored.all_decisions()) == 1


def test_a_null_lifecycle_is_not_a_missing_one():
    """PRESENCE, not truthiness. `consumed_at: null` is the fact "not yet spent" and
    must restore; a MISSING `consumed_at` is the absence of that fact. The two used
    to be the same thing."""
    state = _issued()
    snapshot = _snapshot(state)
    assert all(d["consumed_at"] is None for d in snapshot["decisions"])
    restored = RunState.from_snapshot(snapshot, _history())
    authority = restored.get_authority("AU1")
    assert authority is not None and authority.consumed_at is None
    restored.consume_authority("AU1", executed_at=AT, now=AT)


# ---------------------------------------------------------------- root and attempts
@pytest.mark.parametrize("key", ["card_id", "last_device_id", "revoked_at",
                                 "decisions", "approved_spend", "recent_attempts"])
def test_every_root_key_is_required(key):
    state = _issued()
    broken = _snapshot(state)
    broken.pop(key, None)
    with pytest.raises((CheckpointError, KeyError)):
        RunState.from_snapshot(broken, _history())


def test_a_run_level_revocation_cannot_be_lost():
    state = _issued()
    state.revoke_outstanding_authorities(now=AT)
    assert state.is_revoked
    broken = _snapshot(state)
    broken.pop("revoked_at", None)
    with pytest.raises(CheckpointError):
        RunState.from_snapshot(broken, _history())


# ------------------------------------------------------------------ anti-rot
def test_the_required_key_lists_match_what_to_snapshot_writes():
    """If `to_snapshot` grows a field and the lists here do not, the new field
    becomes defaultable and the whole defect returns under a different name."""
    state = _issued()
    state.consume_authority("AU1", executed_at=AT, now=AT)
    written = _snapshot(state)

    assert set(written) == set(RunState._SNAPSHOT_KEYS), (
        f"to_snapshot writes {sorted(set(written) ^ set(RunState._SNAPSHOT_KEYS))} "
        f"that _SNAPSHOT_KEYS does not list, or vice versa")
    expected = set(RunState._DECISION_KEYS) | set(RunState._LIFECYCLE_KEYS)
    for decision in written["decisions"]:
        assert set(decision) == expected, sorted(set(decision) ^ expected)
    for attempt in written["recent_attempts"]:
        assert set(attempt) == set(RunState._ATTEMPT_KEYS), sorted(attempt)


def test_a_faithful_round_trip_is_unchanged():
    """The control. A refusal-happy restore that rejected good checkpoints would
    pass every test above."""
    state = _issued()
    restored = RunState.from_snapshot(_snapshot(state), _history())
    assert restored.to_snapshot() == state.to_snapshot()
    before = state.get_authority("AU1")
    after = restored.get_authority("AU1")
    assert (before.revoked, before.consumed_at) == (after.revoked, after.consumed_at)
    assert restored.rolling_spend_chf(AT + timedelta(days=1), 7) == \
        state.rolling_spend_chf(AT + timedelta(days=1), 7)
    assert restored.total_approved_spend_chf() == Decimal("400")

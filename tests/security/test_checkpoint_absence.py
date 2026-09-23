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


# ------------------------------------------- the absence that cannot be filled
def _worker(tmp_path, listing=None, raises=False):
    """A worker with only the parts `register_run` touches, plus a stub platform."""
    import threading

    from wallet_control.live_worker import LiveWorker

    class _Client:
        def list_authorizations(self):
            if raises:
                raise RuntimeError("platform unreachable")
            return listing if listing is not None else {"data": []}

    worker = LiveWorker.__new__(LiveWorker)
    worker._checkpoint_dir = tmp_path
    worker._history = _history()
    worker._runs = {}
    worker._lock = threading.RLock()
    worker._client = _Client()
    return worker


def test_a_missing_checkpoint_no_longer_silently_restarts_the_allowance(tmp_path, caplog):
    """THE EIGHTH BOUNDARY, REOPENED -- and the old answer was too weak.

    This test used to assert that a missing checkpoint merely LOGGED LOUDLY, on the
    reasoning quoted in its own docstring: "the absence cannot be filled -- and
    refusing would strand every genuinely new run". Both halves were wrong.

    Measured first, through the real engine: a CHF 300 / 7-day cap approved CHF 300,
    then CHF 300, then CHF 300 across three restarts -- **CHF 900 inside one window,
    and the bound is per restart, not per window.** A log line is not a control.

    The reasoning failed because it assumed a genuinely new run and a run whose state
    was lost are indistinguishable. They are not. A new run has no decision recorded
    anywhere; a lost one has its earlier decisions sitting in `GET /v1/authorizations`
    -- which this worker ALREADY calls, one method down, to avoid double-submitting.
    Nothing new had to become available; something already fetched had to be asked a
    different question.

    And the absence could be filled after all -- not with the amount, which really is
    unrecoverable, but with the TRUTH that the amount is unknown. Zero is a value;
    "I cannot see what was spent" is an absence. `prior_spend_known=False` makes every
    rolling-period rule answer `unknown`, which routes to the mandate's own
    `uncertainty_policy`. The cost of caution here is an ASK, not a block.
    """
    import logging

    listing = {"data": [{"authorization_id": "AU_EARLIER", "decision": "approve",
                         "run_id": "RUN_LOST"}]}
    worker = _worker(tmp_path, listing=listing)
    with caplog.at_level(logging.WARNING, logger="wallet_control.live_worker"):
        handle = worker.register_run("RUN_LOST", _mandate())

    assert handle.state.resumed_incomplete is True, (
        "the platform says this run already decided something; an empty ledger is "
        "what SURVIVED, not what happened")
    message = " ".join(r.getMessage().lower() for r in caplog.records
                       if r.levelno >= logging.WARNING)
    assert "unknown" in message and "no checkpoint" in message


def test_a_genuinely_new_run_is_not_made_to_pay_for_a_loss_that_did_not_happen(tmp_path):
    """The other half, and the reason the old code gave for doing nothing.

    If every checkpoint-less run were treated as lost state, every first run of every
    deployment would start by asking the customer about a rolling limit -- the exact
    "stranding" the old docstring feared, and a real cost. The platform listing is
    what separates the cases, so a run it has never heard of keeps a KNOWN zero."""
    handle = _worker(tmp_path, listing={"data": []}).register_run("RUN_NEW", _mandate())
    assert handle.state.resumed_incomplete is False
    assert handle.state.total_approved_spend_chf() == Decimal("0")


def test_being_unable_to_ask_is_not_evidence_that_nothing_was_spent(tmp_path):
    """The third outcome, and the one an attacker would aim for.

    If "the platform did not answer" fell back to a known zero, then anything that
    breaks the listing call restores the original vulnerability -- a defence whose
    bypass is to break the thing it depends on. An unanswered question is unknown."""
    handle = _worker(tmp_path, raises=True).register_run("RUN_UNREACHABLE", _mandate())
    assert handle.state.resumed_incomplete is True


def test_unknown_prior_spend_makes_the_rolling_rule_unknown_not_zero(tmp_path):
    """END TO END, through the real engine: the flag has to reach the decision.

    `unknown`, never `fail` -- there is no evidence this purchase is bad, only that
    the ceiling cannot be checked -- so the customer's own dial decides."""
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.mandate import HardRule, UncertaintyPolicy
    from tests.helpers import make_event, make_mandate

    rules = [HardRule(field="authorization.billing_amount_chf", operator="<=",
                      value=300, currency="CHF", scope="period", period_days=7)]
    for policy, expected in ((UncertaintyPolicy.ASK, "review"),
                             (UncertaintyPolicy.DECLINE, "block"),
                             (UncertaintyPolicy.APPROVE, "allow")):
        mandate = make_mandate(hard_rules=list(rules), uncertainty_policy=policy)
        state = _state_with_unknown_prior_spend()
        event = make_event(mandate=mandate, amount=100.0)
        result = evaluate_authorization(event, mandate, state)
        assert result.decision == expected, (policy, result.reason_codes)
        if policy is UncertaintyPolicy.ASK:
            assert any("billing_amount_chf" in c for c in result.reason_codes)


def test_the_unknown_expires_once_the_window_has_been_fully_watched():
    """THE PART THAT MAKES THIS A CONTROL AND NOT AN APOLOGY.

    "After a restart, nothing is known" would send every purchase to the customer
    for ever, because a lost state never becomes found. It does not have to: every
    state-derived fact here answers a question about a BOUNDED window, and a state
    that has been watching for longer than the window has seen all of it -- whatever
    happened before it started.

    So the cost of a restart is bounded by the longest window the mandate actually
    uses, and it expires on its own with no operator action. A 1-day ceiling is
    answerable a day later; a 7-day ceiling is not, and that asymmetry is real rather
    than an artefact.
    """
    from datetime import timedelta

    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.mandate import HardRule
    from tests.helpers import make_event, make_mandate
    from wallet_control.state import RunState

    mandate = make_mandate(hard_rules=[HardRule(
        field="authorization.billing_amount_chf", operator="<=", value=300,
        currency="CHF", scope="period", period_days=1)])
    state = RunState(history=_history(), card_id="CA_TEST", resumed_incomplete=True)

    first = evaluate_authorization(
        make_event(mandate=mandate, authorization_id="AU_R1", amount=10.0, timestamp=AT),
        mandate, state)
    assert first.decision == "review", "the 1-day window reaches back before the restart"

    later = evaluate_authorization(
        make_event(mandate=mandate, authorization_id="AU_R2", amount=10.0,
                   timestamp=AT + timedelta(days=1, minutes=1)),
        mandate, state)
    assert later.decision == "allow", (
        "a full day after it started watching, the 1-day window is entirely inside "
        "what this state has seen -- the unknown must expire by itself")


def test_a_restart_does_not_silently_switch_off_duplicate_detection():
    """THE FIRST FIX WAS INCOMPLETE, AND THIS IS WHAT IT MISSED.

    `prior_spend_known` named one CONSUMER of the lost state. Measured with the same
    fixture, same basket, same shop, five minutes apart and a new authorization id:

        state intact    ->  review   (order.duplicate_suspected)
        after restart   ->  ALLOW

    One real order, charged twice, with no forgery anywhere -- the ledger that would
    have recognised it simply was not there. An empty `_recent_attempts` is not
    evidence that nothing recent happened."""
    from datetime import timedelta

    from wallet_control.decision_engine import evaluate_authorization
    from tests.helpers import make_event
    from wallet_control.state import RunState

    mandate = _mandate()
    lost = RunState(history=_history(), card_id="CA_TEST", resumed_incomplete=True)
    event = make_event(mandate=mandate, authorization_id="AU_DUP", amount=400.0,
                       merchant_id=MERCHANT, timestamp=AT + timedelta(minutes=5))
    result = evaluate_authorization(event, mandate, lost)
    assert result.decision != "allow", (
        "this state cannot see the last hour, so it cannot say this is NOT a repeat "
        f"of an order it never saw: {result.reason_codes}")


def _state_with_unknown_prior_spend():
    from wallet_control.state import RunState
    return RunState(history=_history(), card_id="CA_TEST", resumed_incomplete=True)


def test_a_present_checkpoint_does_not_warn(tmp_path, caplog):
    """The control. A warning on every run is a warning nobody reads."""
    import json as _json
    import logging
    import threading

    from wallet_control.live_worker import LiveWorker

    state = _issued()
    (tmp_path / "RUN_OLD.json").write_text(_json.dumps(state.to_snapshot()))

    worker = LiveWorker.__new__(LiveWorker)
    worker._checkpoint_dir = tmp_path
    worker._history = _history()
    worker._runs = {}
    worker._lock = threading.RLock()

    with caplog.at_level(logging.WARNING, logger="wallet_control.live_worker"):
        handle = worker.register_run("RUN_OLD", _mandate())

    assert handle.state.total_approved_spend_chf() == Decimal("400")
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

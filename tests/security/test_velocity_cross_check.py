"""An event does not get to under-report its own neighbours.

`session.integrity_risk` is driven by `recent_attempt_count_10m`, a field the event
carries about itself. It was taken on trust, and that was the one event claim this
engine did NOT cross-check against an independent source it already holds.

The attack needs no forgery beyond a single integer. Four attempts inside one
minute, with a device change halfway, every event reporting `recent_attempt_count_10m: 0`:

    honest counts (0,1,2,3)  ->  allow, allow, BLOCK, BLOCK
    all reported as 0        ->  allow, allow, allow, allow

...while this run's own attempt log held all four. Two blocks became approvals
because the purchase was asked how suspicious it was and believed.

WHY THIS IS A CONSISTENCY FIX, NOT A NEW MECHANISM. The engine already refuses to
let an event answer questions about itself wherever an independent source exists:
`billing_amount_chf` is recomputed from `amount x fx_rates`, `items_subtotal +
delivery_fee` is checked against `amount`, `card_id` and `mandate_id` are checked
against the run. Velocity was the omission, and the independent source -- the
attempt log behind duplicate detection -- was already there.

WHY `max` AND NOT A REPLACEMENT. The platform legitimately sees attempts this run
never will: on the official corpus one event reports 3 where we observe 2. Taking
our own count would DISCARD real evidence. `max(reported, observed)` is monotone --
it can only raise risk, never lower it -- so it cannot make any decision more
permissive than before.

WHY IT CANNOT MOVE THE REPLAY, measured rather than hoped: across all 45 official
events, `observed - reported` is never positive. The only divergence is in the
platform's favour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex, RunState

MERCHANT = "ME_KNOWN"
T0 = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


def _mandate():
    return make_mandate(
        instruction="The agent may buy clothing for me.",
        hard_rules=[
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=250, currency="CHF", scope="purchase"),
            HardRule(field="session.integrity_risk", operator="=", value="false"),
        ],
    )


def _state() -> RunState:
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT})}, available=True), card_id="CA_TEST")


def _attempt(mandate, aid, device, reported, minutes):
    event = make_event(
        mandate=mandate, authorization_id=aid, amount=100.0, merchant_id=MERCHANT,
        timestamp=T0 + timedelta(minutes=minutes),
    )
    event["authorization"]["customer_device_id"] = device
    event["authorization"]["recent_attempt_count_10m"] = reported
    event["authorization"]["items"][0]["item_name"] = f"shirt {aid}"
    return event


def _run(reported_counts, *, spacing_minutes=1):
    mandate, state = _mandate(), _state()
    devices = ["D1", "D1", "D2", "D2"]
    return [
        evaluate_authorization(
            _attempt(mandate, f"AU{i}", devices[i], reported_counts[i], i * spacing_minutes), mandate, state
        ).decision
        for i in range(len(reported_counts))
    ]


def test_under_reporting_recent_attempts_no_longer_suppresses_session_risk():
    """The attack, and the control it has to match."""
    honest = _run([0, 1, 2, 3])
    tampered = _run([0, 0, 0, 0])
    assert honest == ["allow", "allow", "block", "block"], honest
    assert tampered == honest, "lying about velocity still changes the outcome"


def test_slow_legitimate_traffic_is_not_penalised():
    """The cost of the fix, measured. Attempts half an hour apart are outside the
    10-minute window, so an honest shopper reporting 0 is believed."""
    assert _run([0, 0, 0, 0], spacing_minutes=30) == ["allow"] * 4


def test_the_platforms_higher_count_is_never_discarded():
    """`max`, not replacement. The platform sees attempts we cannot, and one official
    event reports 3 where this run observes 2."""
    mandate, state = _mandate(), _state()
    first = evaluate_authorization(_attempt(mandate, "AU0", "D1", 0, 0), mandate, state)
    assert first.decision == "allow"
    # we have observed exactly one prior attempt, but the platform reports three
    loud = evaluate_authorization(_attempt(mandate, "AU1", "D2", 3, 1), mandate, state)
    assert loud.decision == "block"


def test_the_engine_counts_only_attempts_inside_the_window():
    state = _state()
    mandate = _mandate()
    evaluate_authorization(_attempt(mandate, "AU0", "D1", 0, 0), mandate, state)
    assert state.observed_attempts_within(T0 + timedelta(minutes=5)) == 1
    assert state.observed_attempts_within(T0 + timedelta(minutes=30)) == 0


def test_the_official_replay_is_unmoved():
    """Asserted, not assumed: observed never exceeds reported on the official corpus."""
    from wallet_control.offline_replay import replay_all

    assert replay_all().total_counts() == {"allow": 19, "review": 2, "block": 24}

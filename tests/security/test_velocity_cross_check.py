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


def _run(reported_counts, *, spacing_minutes=1, devices=None):
    mandate, state = _mandate(), _state()
    devices = devices or ["D1", "D1", "D2", "D2"]
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
    10-minute window, so an honest shopper reporting 0 is believed.

    ONE DEVICE, which this fixture did not hold constant. It used to switch to a new
    device halfway through and still expect four approvals -- so it was asserting
    something about VELOCITY while quietly also asserting that a new device is
    nothing. When the session signal became three-valued that second, unintended
    assertion is what failed. The two signals are now separated: this one is about
    velocity, and `test_a_new_device_alone_is_a_question_not_a_refusal` is about
    the other."""
    assert _run([0, 0, 0, 0], spacing_minutes=30,
                devices=["D1"] * 4) == ["allow"] * 4


def test_a_new_device_alone_is_a_question_not_a_refusal():
    """The behaviour that replaced it, stated on purpose.

    A device this run has not seen is not proof that someone else is driving -- it is
    the commonest thing an ordinary person does, moving from phone to laptop -- and it
    is not nothing either. The customer wrote "pause anything that LOOKS LIKE someone
    other than me is driving the session"; this is what that looks like, and UNKNOWN
    routed through `uncertainty_policy` is the only honest answer.

    It cost the official replay one approval, AU0026: CHF 165 on the hijacker's first
    purchase, which the engine used to approve while writing "device changed from
    DVC-B73E47 to DVC-4C0E9B" into its own evidence."""
    assert _run([0, 0, 0, 0], spacing_minutes=30,
                devices=["D1", "D1", "D2", "D2"]) == ["allow", "allow", "review", "allow"]


def test_returning_to_a_device_already_seen_is_not_raised():
    """Weaker than a first sighting, deliberately: the handset coming back after the
    laptop is the commonest benign pattern in the official data, and AU0031 is
    exactly it. Without this, a two-device customer would be asked on every switch."""
    assert _run([0, 0, 0, 0, 0], spacing_minutes=30,
                devices=["D1", "D2", "D1", "D2", "D1"]) == [
        "allow", "review", "allow", "allow", "allow"]


def test_the_session_question_only_reaches_customers_who_asked_for_it():
    """The scope of the change, and the reason it is not over-blocking.

    `session.integrity_risk` is compiled only from an instruction that asks for it,
    so no mandate without those words is affected. Three of the five official
    scenarios have no session rule and none of them moved."""
    from wallet_control.policy_compiler import compile_instruction
    asked = compile_instruction(
        "Buy clothing up to CHF 250. Pause anything that looks like someone other "
        "than me is driving the session.")
    silent = compile_instruction("Buy clothing up to CHF 250.")
    assert any(r.field == "session.integrity_risk" for r in asked.hard_rules)
    assert not any(r.field == "session.integrity_risk" for r in silent.hard_rules)


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

    assert replay_all().total_counts() == {"allow": 12, "review": 9, "block": 24}

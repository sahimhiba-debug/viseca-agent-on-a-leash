"""A refusal that tells you the week is full, and not when it stops being full.

"It would take you over the CHF 300 you allowed across any 7-day period" is a true
and complete explanation of a decision, and it leaves the customer guessing about
their own money. The engine is not guessing: it holds every approved purchase's
simulated timestamp, and the window is half-open, so each one stops counting at a
computable instant.

On the official household-budget scenario:

    CHF 24.00 refused on Sunday     -> "you could order this again on Monday at 09:12"
    CHF 62.00 refused on Friday     -> Tuesday at 18:35

and those differ for a reason anyone can check by hand: the CHF 24 only needs
Monday's CHF 44.50 to age out; the CHF 62 needs Tuesday's CHF 120 as well.

A card spending limit cannot answer this at all. It has no notion of the customer's
window -- only of its own month.

TWO THINGS MAKE IT HONEST RATHER THAN HELPFUL-SOUNDING

  * It is reported ONLY when the window is the sole reason. Two of the five official
    refusals fail on the window AND on something else; "you could order this again on
    Tuesday" would be false for both, because Tuesday will not make a jar of
    something the customer did not ask for into something they did.
  * It is CUSTOMER-FACING ONLY. A retry time beside an amount is the window's length
    and its remaining balance -- the policy the agent is never told.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import agent_view, evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.offline_replay import replay_scenario
from wallet_control.state import HistoryIndex, RunState

MERCHANT = "ME_KNOWN"
AT = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
CAP, DAYS = 300, 7


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT})}, available=True),
                    card_id="CA_TEST")


def _mandate(extra=()):
    return make_mandate(instruction="Order groceries.", hard_rules=[
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=CAP,
                 currency="CHF", scope="period", period_days=DAYS),
        *extra])


def _buy(mandate, state, amount, *, day, aid, category="groceries"):
    event = make_event(mandate=mandate, authorization_id=aid, amount=amount,
                       merchant_id=MERCHANT, timestamp=AT + timedelta(days=day))
    event["authorization"]["items"][0].update(item_name=f"food {aid}",
                                              item_category=category)
    return evaluate_authorization(event, mandate, state)


def test_the_retry_time_is_exactly_when_enough_spend_ages_out():
    """Arithmetic anyone can check: CHF 250 on day 0, CHF 40 on day 1. A CHF 100
    purchase on day 2 does not fit (390 > 300) and fits the moment the 250 leaves the
    window -- day 7, to the minute."""
    mandate, state = _mandate(), _state()
    assert _buy(mandate, state, 250.0, day=0, aid="A").decision == "allow"
    assert _buy(mandate, state, 40.0, day=1, aid="B").decision == "allow"
    refused = _buy(mandate, state, 100.0, day=2, aid="C")

    assert refused.decision == "block"
    assert refused.earliest_retry_at == AT + timedelta(days=DAYS)
    assert "could order this again" in refused.customer_message


def test_and_the_purchase_really_is_allowed_then():
    """The claim, verified against the engine rather than against the formula that
    produced it. A promise the wallet will not keep is worse than silence."""
    mandate, state = _mandate(), _state()
    _buy(mandate, state, 250.0, day=0, aid="A")
    _buy(mandate, state, 40.0, day=1, aid="B")
    refused = _buy(mandate, state, 100.0, day=2, aid="C")
    promised = refused.earliest_retry_at

    event = make_event(mandate=mandate, authorization_id="D", amount=100.0,
                       merchant_id=MERCHANT, timestamp=promised)
    event["authorization"]["items"][0].update(item_name="food D", item_category="groceries")
    assert evaluate_authorization(event, mandate, state).decision == "allow"


def test_a_moment_earlier_is_still_refused():
    """"Earliest" has to mean earliest, or it is just a date."""
    mandate, state = _mandate(), _state()
    _buy(mandate, state, 250.0, day=0, aid="A")
    _buy(mandate, state, 40.0, day=1, aid="B")
    promised = _buy(mandate, state, 100.0, day=2, aid="C").earliest_retry_at

    event = make_event(mandate=mandate, authorization_id="E", amount=100.0,
                       merchant_id=MERCHANT, timestamp=promised - timedelta(minutes=1))
    event["authorization"]["items"][0].update(item_name="food E", item_category="groceries")
    assert evaluate_authorization(event, mandate, state).decision == "block"


def test_no_retry_time_when_waiting_cannot_help():
    """A purchase larger than the whole cap will never fit, however long anyone
    waits, and saying a date would be a lie with a friendly face."""
    mandate, state = _mandate(), _state()
    _buy(mandate, state, 100.0, day=0, aid="A")
    refused = _buy(mandate, state, 400.0, day=1, aid="B")
    assert refused.decision == "block"
    assert refused.earliest_retry_at is None
    assert "could order this again" not in refused.customer_message


def test_no_retry_time_when_the_window_is_not_the_only_reason():
    """Tuesday will not make a jar of something the customer did not ask for into
    something they did. Two of the five official refusals are exactly this shape."""
    mandate = _mandate([HardRule(field="item.category", operator="in", value=["groceries"])])
    state = _state()
    _buy(mandate, state, 280.0, day=0, aid="A")
    refused = _buy(mandate, state, 100.0, day=1, aid="B", category="jewellery")

    assert refused.decision == "block"
    assert refused.earliest_retry_at is None, (
        "the window alone would clear on day 7, but the category never will")
    assert "could order this again" not in refused.customer_message


def test_the_agent_is_never_told_when():
    """A retry time beside an amount is the window's length and its remaining
    balance. That is the policy, and the agent is not told the policy."""
    mandate, state = _mandate(), _state()
    _buy(mandate, state, 250.0, day=0, aid="A")
    refused = _buy(mandate, state, 100.0, day=2, aid="C")
    assert refused.earliest_retry_at is not None

    blob = json.dumps(agent_view(refused))
    assert str(refused.earliest_retry_at.year) not in blob
    assert "retry" not in blob.lower() and "again" not in blob.lower()
    assert refused.customer_message not in blob


def test_the_official_refusals_carry_it_where_it_is_honest():
    """End to end on the real pack, and the two numbers differ for a checkable
    reason: the CHF 24 needs only Monday's CHF 44.50 to age out, the CHF 65.50 needs
    Tuesday's CHF 120 as well."""
    decisions = {d.authorization_id: d for d in replay_scenario("SCEN0001").decisions}
    window_only = [d for d in decisions.values()
                   if d.decision == "block" and d.earliest_retry_at is not None]
    assert len(window_only) == 2, [d.authorization_id for d in window_only]

    small, larger = decisions["AU0009"], decisions["AU0008"]
    assert small.earliest_retry_at < larger.earliest_retry_at, (
        "a smaller purchase must be able to fit sooner, not later")
    for decision in window_only:
        assert "could order this again" in decision.customer_message


def test_it_changes_no_decision():
    """It is an explanation. If adding it moved a verdict it would be a rule."""
    counts = replay_scenario("SCEN0001").counts()
    assert counts == {"allow": 5, "review": 0, "block": 5}

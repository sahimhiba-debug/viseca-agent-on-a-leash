"""The clock every rolling ceiling is measured in, and who owns it.

HOW THIS WAS FOUND. Not by looking for it. A restart-recovery mechanism was anchored
on "the timestamp of the first event this state saw", and the obvious attack on that
anchor -- back-date the first event -- worked. Chasing it revealed that the anchor
was the smaller problem:

    a CHF 300 / 7-day ceiling, already spent, INTACT state, no restart involved
        the purchase, honestly stamped         block
        the same purchase, stamped 8 days ago  ALLOW

    CHF 600 approved against a CHF 300 cap, by claiming a different week.

WHY THAT IS NOT A VULNERABILITY, AND WHY IT IS STILL A FINDING. `authorization.
timestamp` is not a field any rule names, so the provenance table -- which classified
the nine fields `rules.py` evaluates -- never looked at it. It is nonetheless the
input that decides WHICH WINDOW money counts against, which makes every rolling
guarantee in this system rest on it.

It holds because of how the value is produced, and that is measured here rather than
assumed: the offline replay preserves the pack's simulated purchase time
(technical_details.md: "Preserve simulated purchase times"), and `/api/agent/propose`
DERIVES its own from a fixed origin and ignores anything the caller sends. So the
class is BOUND. The lesson is not the reassurance -- it is that a decision input with
no rule attached to it had no provenance at all until something went looking for it.

WHAT IS NOT CLAIMED. Nothing here says a real platform's timestamp cannot be wrong,
or that a compromised platform is in scope. The claim is about the party this wallet
exists to constrain: the agent cannot choose the moment, and therefore cannot choose
the week.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from tests.helpers import make_event, make_mandate
from wallet_control.api import app
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.provenance import BOUND, for_rule
from wallet_control.state import HistoryIndex, RunState

client = TestClient(app)

CARD, MERCHANT = "CA_TEST", "ME_TEST_0001"
AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
CAP, DAYS = 300, 7


def _mandate():
    return make_mandate(hard_rules=[HardRule(
        field="authorization.billing_amount_chf", operator="<=", value=CAP,
        currency="CHF", scope="period", period_days=DAYS)])


def _spent_to_the_ceiling(mandate):
    state = RunState(history=HistoryIndex({CARD: frozenset({MERCHANT})}, available=True),
                     card_id=CARD)
    state.record_decision("AU_PRIOR", "allow", Decimal(str(CAP)), AT,
                          merchant_id=MERCHANT, basket_key=())
    return state


def test_moving_a_purchase_in_time_moves_which_ceiling_it_counts_against():
    """THE REPRODUCTION. Not a defect on its own -- a purchase that really did happen
    last week really should not count against this week -- but it establishes that
    the clock is load-bearing, which is what makes its provenance matter."""
    mandate = _mandate()
    honest = evaluate_authorization(
        make_event(mandate=mandate, authorization_id="AU_NOW", amount=100.0, timestamp=AT),
        mandate, _spent_to_the_ceiling(mandate))
    backdated = evaluate_authorization(
        make_event(mandate=mandate, authorization_id="AU_OLD", amount=100.0,
                   timestamp=AT - timedelta(days=DAYS + 1)),
        mandate, _spent_to_the_ceiling(mandate))

    assert honest.decision == "block"
    assert backdated.decision == "allow", (
        "if this ever stops being true the test below is measuring nothing")


def test_the_agent_cannot_choose_when_its_purchase_happened():
    """THE ASSERTION THAT MATTERS. The agent's own endpoint must derive the moment,
    never accept one -- including under any of the plausible field names, which are
    tried here so that adding one to the request model quietly cannot go unnoticed."""
    def propose(session, **extra):
        line = {"item_id": "IT0001", "name": "Fresh produce selection",
                "category": "groceries", "unit_price": 10.0, "quantity": 1,
                "merchant": "ME0001", "return_days": 30}
        body = {"session_id": session, "lines": [line]}
        body.update(extra)
        response = client.post("/api/agent/propose", json=body)
        assert response.status_code == 200, response.text
        return response.json()["authorization_id"]

    ancient = "2020-01-01T00:00:00Z"
    baseline = propose("clock_plain")
    for name, value in (("timestamp", ancient), ("when", ancient), ("occurred_at", ancient),
                        ("purchase_time", ancient), ("simulated_time", ancient)):
        assert propose(f"clock_{name}", **{name: value}), (
            f"the endpoint accepted a {name!r} it should have ignored")
    assert baseline


def test_the_clock_is_declared_and_declared_bound():
    """An input this load-bearing must be in the provenance table, not merely absent
    from the attack surface by luck. The measurement lives in
    `research/forgeable_facts.py`, which fails the build if the class is wrong."""
    fact = for_rule("authorization.timestamp")
    assert fact is not None, "the clock every rolling ceiling uses must be declared"
    assert fact.binding == BOUND
    assert "cannot choose when" in fact.customer_line


def test_a_purchase_at_another_moment_is_another_purchase():
    """THE CRITERION'S FOURTH CLAUSE, which the code used to omit.

    `provenance.py` calls a fact forgeable when misstating it changes the decision
    "while leaving the purchase unchanged -- same goods, same shop, same price, same
    moment". The set implementing that listed only the first three, so a probe that
    moved a purchase in time would have been scored as forging an unchanged one."""
    import research.forgeable_facts as ff

    rows = {row["field"]: row for row in ff.measure()}
    clock = rows["authorization.timestamp"]
    assert clock["changed_the_purchase"] is True, (
        "back-dating changes the moment, so it changes the purchase")
    assert clock["measured"] == BOUND
    # And the probe has to be a real one: it must actually breach the ceiling first,
    # or "bound" would just mean the attack was never attempted.
    assert clock["violating"] == "block" and clock["relabelled"] == "allow"

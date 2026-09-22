"""A rolling cap must hold for every window that CONTAINS a purchase, not the one
that ends at it.

The natural implementation -- sum the last N days and add this one -- is correct only
when decisions are made in chronological order and none is deferred. The official
protocol guarantees neither:

  * nothing orders `/v1/decision-requests/next` by purchase time, and the agent
    chooses what to propose when;
  * `step_up` defers by design, and technical_details.md requires that a paused
    purchase "does not enter approved spend until it is resolved" -- at which point it
    enters at its ORIGINAL simulated timestamp, behind decisions already taken against
    a window that could not see it.

Following both requirements correctly is what produces the breach. Measured before the
fix: CHF 480 against a CHF 300 seven-day cap with strictly chronological delivery, and
367 of 400 random arrival orders breaching with reordering alone.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.csv_data import load_merchants, load_purchase_attempt_items
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.mandate import HardRule
from wallet_control.offline_replay import (
    build_event, compile_and_confirm_mandate_for_scenario, history_csv_path, scenario_rows,
)
from wallet_control.state import HistoryIndex, RunState

M, CARD = "ME_TEST_0001", "CA_TEST"
T0 = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
CAP, DAYS = Decimal("300"), 7


def _mandate(per_purchase=200, period=300, days=7, need_return_window=False):
    rules = [
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=per_purchase,
                 currency="CHF", scope="purchase"),
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=period,
                 currency="CHF", scope="period", period_days=days),
    ]
    if need_return_window:
        rules.append(HardRule(field="order.return_window_days", operator=">=", value=14))
    return make_mandate(instruction="Order our household groceries.", hard_rules=rules)


def _state():
    return RunState(history=HistoryIndex({CARD: frozenset({M})}, available=True), card_id=CARD)


def _buy(mandate, state, aid, amount, hours, details="returns accepted within 30 days"):
    event = make_event(mandate=mandate, authorization_id=aid, amount=amount, merchant_id=M,
                       timestamp=T0 + timedelta(hours=hours))
    event["authorization"]["order_returnable"] = "true"
    event["authorization"]["items"][0].update(item_details=details, item_name=f"groceries {aid}")
    return evaluate_authorization(event, mandate, state)


def _worst_window(state, days=DAYS):
    spend = state._approved_spend
    return max((sum((a for ts, a in spend if end - timedelta(days=days) < ts <= end), Decimal("0"))
                for end, _ in spend), default=Decimal("0"))


# --- the attack that motivated the fix --------------------------------------------


def test_a_step_up_resolved_late_cannot_breach_the_customers_window():
    """THE ATTACK, in strictly chronological order and with no reordering at all.

    A purchase is paused for the customer -- the wallet being careful. Two more are
    approved against a window that cannot see it. The customer then answers yes. Every
    decision is locally correct; the week holds CHF 480 against a CHF 300 limit.

    Being careful is what created the hole."""
    mandate, state = _mandate(need_return_window=True), _state()

    assert _buy(mandate, state, "AU1", 180.0, 0, details="").decision == "review"
    assert _buy(mandate, state, "AU2", 150.0, 2).decision == "allow"
    assert _buy(mandate, state, "AU3", 150.0, 4).decision == "allow"
    assert state.total_approved_spend_chf() == Decimal("300")

    resolved = resolve_authorization("AU1", "allow", state,
                                     resolved_at=datetime.now(timezone.utc), mandate=mandate)
    assert resolved.decision == "block"
    assert any("period_limit_exceeded" in c for c in resolved.reason_codes), resolved.reason_codes
    assert _worst_window(state) <= CAP


def test_the_same_resolution_succeeds_when_it_actually_fits():
    """The other half: the re-check must not turn every late answer into a decline."""
    mandate, state = _mandate(need_return_window=True), _state()
    assert _buy(mandate, state, "AU1", 100.0, 0, details="").decision == "review"
    assert _buy(mandate, state, "AU2", 100.0, 2).decision == "allow"

    resolved = resolve_authorization("AU1", "allow", state,
                                     resolved_at=datetime.now(timezone.utc), mandate=mandate)
    assert resolved.decision == "allow"
    assert _worst_window(state) == Decimal("200")


# --- order independence ------------------------------------------------------------


def _run_official_order(order):
    mandate = compile_and_confirm_mandate_for_scenario("SCEN0001").snapshot()
    state = RunState(history=HistoryIndex.from_csv(history_csv_path()), card_id=mandate.card_id)
    merchants, items = load_merchants(), load_purchase_attempt_items()
    approved = 0
    for row in order:
        ctx = {"approved_spend_in_period_chf": float(state.total_approved_spend_chf()),
               "recent_authorizations": state.recent_authorizations_context()}
        result = evaluate_authorization(
            build_event(row, items[row["authorization_id"]], merchants[row["merchant_id"]], mandate, ctx),
            mandate, state)
        approved += result.decision == "allow"
    return approved, _worst_window(state)


def test_no_arrival_order_can_breach_the_customers_window():
    """Before the fix, 367 of 400 random orders breached a CHF 300 / 7-day cap, the
    worst reaching CHF 389. The agent chooses the order it proposes in, so this was
    entirely under its control."""
    rows = scenario_rows("SCEN0001")
    rng = random.Random(11)
    for _ in range(60):
        _, worst = _run_official_order(rng.sample(rows, len(rows)))
        assert worst <= CAP, f"arrival order breached the cap: CHF {worst}"


def test_the_number_of_approvals_does_not_depend_on_arrival_order():
    """The stronger property the fix buys. Reordering used to fund two extra purchases
    -- CHF 387.50 to CHF 477.00, starving nothing -- so the agent could choose how much
    of the customer's week to spend simply by choosing what to propose first."""
    rows = scenario_rows("SCEN0001")
    rng = random.Random(7)
    counts = {_run_official_order(rng.sample(rows, len(rows)))[0] for _ in range(40)}
    assert len(counts) == 1, f"approval count varies with arrival order: {sorted(counts)}"


# --- the invariant, and compatibility ----------------------------------------------


def test_peak_window_equals_the_backward_window_when_nothing_is_out_of_order():
    """Why the official replay is unchanged: for a chronological run with nothing
    deferred, the peak containing window and the window ending at the purchase are the
    same number. The fix only bites where the old check was wrong."""
    state = _state()
    for hours, amount in ((0, "50"), (24, "60"), (48, "70")):
        ts = T0 + timedelta(hours=hours)
        assert state.peak_window_spend_chf(ts, Decimal(amount), DAYS) == (
            state.rolling_spend_chf(ts, DAYS) + Decimal(amount))
        state._approved_spend.append((ts, Decimal(amount)))


@pytest.mark.parametrize("scenario_id", ["SCEN0000", "SCEN0001", "SCEN0002", "SCEN0003", "SCEN0004"])
def test_the_official_replay_is_unchanged(scenario_id):
    from wallet_control.offline_replay import replay_scenario

    expected = {"SCEN0000": {"allow": 1, "review": 0, "block": 0},
                "SCEN0001": {"allow": 5, "review": 0, "block": 5},
                "SCEN0002": {"allow": 3, "review": 1, "block": 8},
                "SCEN0003": {"allow": 4, "review": 1, "block": 6},
                "SCEN0004": {"allow": 5, "review": 1, "block": 5}}
    assert replay_scenario(scenario_id).counts() == expected[scenario_id]


# --- temporal-consistency audit: two counterexamples found and fixed --------------


def test_an_idempotent_re_resolution_does_not_count_a_purchase_against_itself():
    """COUNTEREXAMPLE 1, minimised.

    A CHF 200 purchase under a CHF 300 cap is stepped up and the customer approves it.
    Their client then retries the same answer -- a double-clicked button. The period
    re-check added the purchase's own amount to `_approved_spend`, which already
    contained it: 200 + 200 = 400 > 300. It decided to record a block, and
    `record_resolution` raised a conflict against the 'allow' it had just recorded.

    The existing idempotence test missed this because its mandate had no period rule.
    """
    mandate = make_mandate(instruction="Order groceries.", hard_rules=[
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=300,
                 currency="CHF", scope="period", period_days=7),
        HardRule(field="order.return_window_days", operator=">=", value=14)])
    state = _state()
    assert _buy(mandate, state, "Q1", 200.0, 0, details="").decision == "review"

    for _ in range(4):
        assert resolve_authorization("Q1", "allow", state,
                                     resolved_at=datetime.now(timezone.utc),
                                     mandate=mandate).decision == "allow"
    assert state.total_approved_spend_chf() == Decimal("200")

    from wallet_control.state import ResolutionError
    with pytest.raises(ResolutionError):
        resolve_authorization("Q1", "block", state,
                              resolved_at=datetime.now(timezone.utc), mandate=mandate)


def test_concurrent_proposals_cannot_both_spend_the_same_remaining_budget():
    """COUNTEREXAMPLE 2.

    The period check reads the window, the rules evaluate, then the decision is
    recorded. With that gap widened to 20ms, two concurrent proposals both saw the
    same remaining budget and both passed -- CHF 400 into a CHF 300 week in 40 of 40
    trials. Reachable through api.py's threadpool, not through the single-threaded
    worker.

    The run's lock is now held across check-then-record, and is re-entrant because
    `record_decision` takes it again underneath.
    """
    import threading
    import time

    mandate, state = _mandate(per_purchase=300), _state()
    assert _buy(mandate, state, "C0", 200.0, 0).decision == "allow"

    original = RunState.peak_window_spend_chf

    def widened(self, as_of, amount, period_days):
        value = original(self, as_of, amount, period_days)
        time.sleep(0.02)
        return value

    RunState.peak_window_spend_chf = widened
    try:
        outcomes: list[str] = []
        barrier = threading.Barrier(2)

        def propose(aid: str) -> None:
            barrier.wait()
            outcomes.append(_buy(mandate, state, aid, 100.0, 2).decision)

        threads = [threading.Thread(target=propose, args=(f"C{i}",)) for i in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not any(t.is_alive() for t in threads), "deadlock"
    finally:
        RunState.peak_window_spend_chf = original

    assert outcomes.count("allow") <= 1, f"both proposals spent the same budget: {outcomes}"
    assert _worst_window(state) <= CAP


def test_the_approved_set_is_NOT_order_invariant_and_we_do_not_claim_it_is():
    """The property this project claimed after the previous pass was too strong.

    Greedy admission is inherently order-dependent: whoever arrives first is funded.
    Minimal counterexample -- A=B=C=100, D=150, cap 300: order (A,B,C,D) approves
    three, order (A,D,B,C) approves two. What holds is SAFETY, not invariance of the
    outcome, and this test exists so the stronger claim cannot quietly return."""
    mandate = _mandate(per_purchase=200, period=300)
    results = set()
    for order in (["A", "B", "C", "D"], ["A", "D", "B", "C"]):
        state = _state()
        amounts = {"A": 100.0, "B": 100.0, "C": 100.0, "D": 150.0}
        approved = tuple(aid for i, aid in enumerate(order)
                         if _buy(mandate, state, aid, amounts[aid], i).decision == "allow")
        results.add(approved)
        assert _worst_window(state) <= CAP          # safety holds in both
    assert len(results) > 1, "expected the approved set to differ by arrival order"


def test_no_randomized_lifecycle_trace_breaches_the_window():
    """The strongest empirical support for the safety claim: random traces mixing
    propose, resolve(allow), resolve(block), revoke, restart, retry and charge, with
    the invariant asserted after every single transition.

    This is the experiment designed to embarrass the claim. 3,000 traces of 4-14
    transitions found nothing; 200 run here."""
    import json
    import random

    from wallet_control.payment import MockPSP

    mandate = _mandate(per_purchase=200, period=300, days=7, need_return_window=True)
    rng = random.Random(99)

    for _ in range(200):
        state = _state()
        seen: list[tuple[str, dict]] = []
        for step in range(rng.randint(4, 12)):
            op = rng.choice(["propose", "propose", "propose", "resolve_allow",
                             "resolve_block", "revoke", "restart", "retry", "charge"])
            try:
                if op == "propose":
                    aid = f"A{step}"
                    event = make_event(
                        mandate=mandate, authorization_id=aid, merchant_id=M,
                        amount=round(rng.uniform(10, 200), 2),
                        timestamp=T0 + timedelta(hours=rng.randint(0, 24 * 9)))
                    event["authorization"]["order_returnable"] = "true"
                    event["authorization"]["items"][0].update(
                        item_details="" if rng.random() < 0.4 else "returns accepted within 30 days",
                        item_name=f"g{aid}")
                    evaluate_authorization(event, mandate, state)
                    seen.append((aid, event))
                elif op in ("resolve_allow", "resolve_block") and seen:
                    aid, _ = rng.choice(seen)
                    resolve_authorization(aid, "allow" if op == "resolve_allow" else "block",
                                          state, resolved_at=datetime.now(timezone.utc),
                                          mandate=mandate)
                elif op == "revoke":
                    state.revoke_outstanding_authorities()
                elif op == "restart":
                    state = RunState.from_snapshot(
                        json.loads(json.dumps(state.to_snapshot())), state.history)
                elif op == "retry" and seen:
                    _, event = rng.choice(seen)
                    evaluate_authorization(event, mandate, state)
                elif op == "charge" and seen:
                    aid, _ = rng.choice(seen)
                    stored = state.get_stored_decision(aid)
                    if stored is not None:
                        MockPSP(state).charge(charge_id=f"C{step}", authorization_id=aid,
                                              amount_chf=stored.billing_amount_chf,
                                              merchant_id=stored.merchant_id)
            except Exception:
                pass                 # a refusal is a legitimate outcome of any transition
            assert _worst_window(state) <= CAP, f"breach after {op}"


def test_nested_overlapping_period_rules_are_all_respected():
    """The gap I flagged in the audit package as "supported but unexercised", now
    exercised. Three nested caps -- CHF 200/1d, CHF 300/7d, CHF 1000/30d -- with
    randomized amounts, timestamps spread over 35 days, ~45% of purchases forced into
    a step-up and resolved in random order.

    A 3,000-run campaign found no breach of any window, and the windows fill right up
    to their caps (199.99 / 299.95 / 956.28), so the check is tight rather than
    over-conservative. 150 runs here."""
    import random

    caps = [(1, Decimal("200")), (7, Decimal("300")), (30, Decimal("1000"))]
    mandate = make_mandate(instruction="Order groceries.", hard_rules=[
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=200,
                 currency="CHF", scope="purchase"),
        *[HardRule(field="authorization.billing_amount_chf", operator="<=", value=int(cap),
                   currency="CHF", scope="period", period_days=days) for days, cap in caps],
        HardRule(field="order.return_window_days", operator=">=", value=14)])

    rng = random.Random(7)
    for _ in range(150):
        state = _state()
        pending = []
        for i in range(rng.randint(3, 8)):
            forced = rng.random() < 0.45
            result = _buy(mandate, state, f"P{i}", round(rng.uniform(10, 200), 2),
                          rng.randint(0, 24 * 35),
                          details="" if forced else "returns accepted within 30 days")
            if result.decision == "review":
                pending.append(f"P{i}")
        rng.shuffle(pending)
        for aid in pending:
            try:
                resolve_authorization(aid, "allow", state,
                                      resolved_at=datetime.now(timezone.utc), mandate=mandate)
            except Exception:
                pass
        for days, cap in caps:
            assert _worst_window(state, days) <= cap, (
                f"{days}-day window breached: CHF {_worst_window(state, days)} > {cap}")


def test_the_rolling_window_is_half_open_exactly_N_days_ago_is_outside_it():
    """`(t - N, t]` -- the boundary, pinned.

    Found by mutation testing: changing `end - window < ts` to `end - window <= ts`
    in `state.peak_window_spend_chf` survived the ENTIRE suite. It is not a safety
    hole -- an inclusive start makes the window WIDER, so it can only ever block
    more -- but nothing pinned which of the two the engine means, and an unpinned
    boundary is how a "harmless" simplification later becomes a behaviour change
    nobody chose.

    Half-open is the right reading of "no more than CHF 300 across any seven days":
    a purchase made exactly seven days ago is no longer within the last seven days.
    The closed form would also make the window inconsistent with itself, since a
    purchase on the boundary would be counted in two adjacent windows at once.
    """
    mandate = _mandate(per_purchase=200, period=300, days=7)

    state = _state()
    assert _buy(mandate, state, "AU_EDGE_1", 200.0, hours=0).decision == "allow"
    # Exactly seven days later. The window (t-7d, t] opens AFTER the first purchase,
    # so only this one is inside it: 200 <= 300.
    assert _buy(mandate, state, "AU_EDGE_2", 200.0, hours=24 * 7).decision == "allow", (
        "a purchase exactly 7 days old must fall OUTSIDE a 7-day window"
    )

    # An hour earlier it is still inside, and 200 + 200 > 300.
    state_b = _state()
    assert _buy(mandate, state_b, "AU_EDGE_3", 200.0, hours=0).decision == "allow"
    assert _buy(mandate, state_b, "AU_EDGE_4", 200.0, hours=24 * 7 - 1).decision == "block", (
        "an hour inside the window must still count"
    )

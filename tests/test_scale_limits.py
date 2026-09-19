"""Where this engine stops meeting the 8-second deadline, measured rather than assumed.

`docs/TEMPORAL_CONSISTENCY_AUDIT.md` asserted that `peak_window_spend_chf` is
"O(n^2), which is fine at run scale and would not be at ledger scale". That was an
unverified claim about the newest security-critical code, so it is measured here.

MEASURED (this machine, CPython 3.13, single-threaded).

The algorithm is EXACTLY quadratic. The clean way to see it is a window large
enough that no purchase ever falls out of it -- then every purchase is inside every
window and nothing saturates:

    10-year window, one purchase per simulated hour   ms/n^2 x1e6
                                       n =   203            62.9
                                       n =   406            64.1
                                       n =   809            62.8
                                       n = 1,612            64.0     flat (0.98x)

A flat `ms/n^2` is the definition of quadratic. At ~63.5e-6, **one run crosses the
8,000 ms deadline at n ~= 11,200 approved purchases.** That is the WORST CASE over
window configurations, and it is the number to hold onto.

A REAL window is more favourable, and this is where two earlier versions of this
docstring went wrong. With a 30-day window at one purchase per hour the window
holds ~720, so past n ~= 720 the expensive in-window `Decimal` additions stop
growing while the cheap timestamp comparisons continue:

    n            100    203    406    809   1,612   3,215   6,418
    ms/decision 0.67   2.56  10.30  40.54  143.55  495.68 1780.31
    ms/n^2 x1e6 66.6   62.2   62.5   61.9    55.2    48.0    43.2
    ratio         --   3.85   4.02   3.93    3.54    3.45    3.59

Flat at ~62e-6 below the saturation point, declining only above it -- exactly where
predicted. A 1-day window (saturating at n ~= 24) is already down at 38.7e-6 by
n = 203.

THIS NUMBER TOOK THREE PASSES AND BOTH WRONG ONES ARE WORTH KNOWING ABOUT:

  1. A four-point fit (n <= 809) read the constant as "settling at ~66e-6" and the
     doubling ratios as "converging to 4.00", giving n ~= 11,000. Four points cannot
     establish convergence; the fourth ratio simply landed on 4.00 with nothing
     after it to disagree.
  2. A seven-point run reaching n = 6,418 contradicted that -- the constant declines
     to 43.2e-6 -- and the correction published n ~= 13,600. But that measured ONE
     window configuration, and a more favourable one: quoting it as the bound
     replaced a right-for-the-wrong-reason number with a wrong-and-optimistic one.
  3. Varying the window while holding everything else fixed isolated the cause and
     gave the worst case, ~11,200.

The official corpus's largest scenario has 12 purchase attempts, so the margin is
~900x in n whichever regime applies.

WHY IT IS QUADRATIC, and why that is not an accident to be optimized away:
`peak_window_spend_chf` evaluates every window that CONTAINS the candidate
purchase, not just the one ending at it, because the containment invariant is

    for all t:  sum{amount(p) : p approved, t - N < time(p) <= t}  <=  C

Purchases arrive out of chronological order (simulated purchase time is not
arrival time), so a new purchase can land INSIDE an existing window and push a
window that was previously compliant over the cap. Checking only the window ending
at the candidate missed that: CHF 480 was approved against a CHF 300 cap, and 367
of 400 orderings breached. The n-windows-by-n-purchases scan is what closed it.
A faster structure is possible (sort once and sweep, O(n log n)); correctness came
first and the numbers above say nothing is owed yet.

TWO OTHER SCALING PATHS, both measured, neither quadratic in CPU:

  * Basket size is LINEAR: 20,000 item lines is 54 ms.
  * Pending step-ups do not enter the window scan at all (a step-up is not an
    approved purchase), so 2,000 unresolved decisions still decide in 0.15 ms.
    What DOES grow with them is the checkpoint: `live_worker._save_checkpoint`
    serializes the whole run on every event, so a 2,000-decision run writes
    1.3 MiB per event. That is O(n^2) BYTES OF DISK I/O over a run -- the second
    quadratic here, and the one that would bite first in a long-lived process.

The thresholds below are deliberately loose -- roughly 100x the measured times --
because this is a guard against an ALGORITHMIC regression (a window scan becoming
cubic, a per-item check becoming quadratic), not a benchmark. A slow or loaded CI
machine must not fail it.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex, RunState

MERCHANT = "ME_KNOWN"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
DEADLINE_MS = 8000.0
UNBOUNDED = 1e9

# The largest scenario in data/official/purchase_attempts.csv has 12 attempts.
# Ten times that is a generous stand-in for "a realistic run".
REALISTIC_RUN = 120


def _mandate(rules=None):
    return make_mandate(
        instruction="Order groceries.",
        hard_rules=rules
        or [
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=UNBOUNDED, currency="CHF", scope="purchase"),
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=UNBOUNDED, currency="CHF", scope="period", period_days=30),
        ],
    )


def _state() -> RunState:
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT})}, available=True), card_id="CA_TEST")


def _event(mandate, i: int, tick: int, items=None):
    event = make_event(
        mandate=mandate, authorization_id=f"AU{i:08d}", amount=1.0 if items is None else float(len(items)),
        merchant_id=MERCHANT, timestamp=T0 + timedelta(hours=tick), **({"items": items} if items else {}),
    )
    if items is None:
        event["authorization"]["items"][0]["item_name"] = f"grocery {i}"
    return event


def test_a_realistic_run_decides_far_inside_the_deadline():
    """Ten times the largest official scenario, with a rolling-period rule active."""
    mandate, state = _mandate(), _state()
    for i in range(REALISTIC_RUN):
        evaluate_authorization(_event(mandate, i, i), mandate, state)
    assert len(state._approved_spend) == REALISTIC_RUN

    start = time.perf_counter()
    evaluate_authorization(_event(mandate, 10**6, REALISTIC_RUN), mandate, state)
    elapsed_ms = (time.perf_counter() - start) * 1000
    # measured ~1 ms; the deadline is 8,000 ms
    assert elapsed_ms < DEADLINE_MS / 100, f"{elapsed_ms:.1f} ms at n={REALISTIC_RUN}"


def test_the_window_scan_is_quadratic_and_no_worse():
    """A cubic window scan would blow the deadline at a few hundred purchases, so
    the SHAPE is asserted, not just a wall-clock number. Doubling n must not
    multiply the cost by more than ~8; quadratic gives 4."""
    mandate, state = _mandate(), _state()
    timings: list[tuple[int, float]] = []
    count = 0
    for target in (100, 200, 400):
        while count < target:
            evaluate_authorization(_event(mandate, count, count), mandate, state)
            count += 1
        start = time.perf_counter()
        for k in range(3):
            evaluate_authorization(_event(mandate, 10**6 + target * 10 + k, count + k), mandate, state)
        timings.append((target, (time.perf_counter() - start) * 1000 / 3))

    for (n0, t0), (n1, t1) in zip(timings, timings[1:]):
        assert t1 / t0 < 8.0, f"doubling {n0}->{n1} multiplied the cost by {t1 / t0:.1f}; quadratic is 4"


def test_basket_size_is_linear_not_quadratic():
    """Every per-item rule is evaluated against every candidate item, so a careless
    change here turns one decision into an n^2 scan over item lines."""
    mandate = _mandate(
        [
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=UNBOUNDED, currency="CHF", scope="purchase"),
            HardRule(field="item.category", operator="in", value=["groceries"]),
            HardRule(field="item.name_contains", operator="=", value="grocery"),
            HardRule(field="item.size", operator="=", value="1kg"),
            HardRule(field="item.unrequested_present", operator="=", value="false"),
        ]
    )

    def _timed(n: int, repeats: int = 5) -> float:
        """The MINIMUM of several runs. Scheduler noise, GC and a loaded machine can
        only ever ADD time, so the minimum is the robust estimator of the real cost --
        a mean makes this test fail when the suite is run under load, which is how an
        earlier version of it flaked (it passed alone and failed in a full run)."""
        items = [
            {"line_no": i + 1, "item_id": f"I{i}", "item_name": "grocery", "item_category": "groceries",
             "quantity": 1, "unit_price": 1.0, "currency": "CHF", "item_details": "size 1kg"}
            for i in range(n)
        ]
        best = float("inf")
        for _ in range(repeats):
            event = _event(mandate, n, 1, items=items)
            start = time.perf_counter()
            evaluate_authorization(event, mandate, _state())
            best = min(best, (time.perf_counter() - start) * 1000)
        return best

    _timed(100, repeats=2)  # warm the interpreter; the first call's import cost is not about n
    small, large = _timed(500), _timed(5000)
    assert large < DEADLINE_MS / 100, f"{large:.1f} ms for a 5,000-line basket"
    # 10x the lines must not cost 100x the time; linear gives 10, quadratic gives 100
    assert large / max(small, 1e-6) < 40, f"10x the lines cost {large / small:.1f}x the time"


def test_pending_step_ups_do_not_enter_the_window_scan():
    """A step-up is not an approved purchase, so a queue of unresolved decisions
    must not slow decisions down. This is what makes the quadratic above bounded by
    APPROVALS rather than by events."""
    mandate = _mandate(
        [
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=UNBOUNDED, currency="CHF", scope="purchase"),
            HardRule(field="order.return_window_days", operator=">=", value=14),
        ]
    )
    state = _state()
    for i in range(1000):
        event = _event(mandate, i, i)
        event["authorization"]["order_returnable"] = "unknown"
        evaluate_authorization(event, mandate, state)
    assert not state._approved_spend, "the fixture must produce step-ups, not approvals"

    event = _event(mandate, 10**6, 1001)
    event["authorization"]["order_returnable"] = "unknown"
    start = time.perf_counter()
    evaluate_authorization(event, mandate, state)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < DEADLINE_MS / 100, f"{elapsed_ms:.1f} ms with 1,000 pending step-ups"

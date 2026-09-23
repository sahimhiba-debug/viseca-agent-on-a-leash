"""What an empty ledger means, and what it cost to assume.

THE ASSUMPTION. `RunState` starts with no decisions in it, and an empty ledger has
always been read as "nothing has been spent". For a genuinely new run that is true.
For a run whose checkpoint is missing -- a redeploy, a crash, a new machine, a
checkpoint directory that was never configured -- it is false. The two cases were
represented identically, so the second silently restarted the customer's entire
rolling allowance.

THE MEASUREMENT. A mandate of CHF 300 across any 7 days, spent by purchases that
differ enough not to trip the duplicate check:

    run 1   100 + 100 + 100   then blocked at the ceiling
    restart
    run 2   100 + 100 + 100   then blocked at the ceiling
    restart
    run 3   100 + 100 + 100   then blocked at the ceiling

    CHF 900 approved inside ONE 7-day window against a CHF 300 cap.

The bound is per restart, not per window, so it is not a factor of three -- it is
unbounded in the number of restarts. The previous mitigation was a log line.

WHAT WAS NOT DEMONSTRATED, AND IS NOT CLAIMED. Nothing here shows that an ATTACKER
can cause a restart. This is an unbounded failure under an ordinary operational
event, not a demonstrated exploit, and it should be read as the first and not the
second.

THE FIX IS A DISTINCTION, NOT A REFUSAL. `register_run` asks the platform one binary
question it can actually answer -- has this run decided anything before? -- using the
`GET /v1/authorizations` listing the worker already calls for a different purpose. A
run the platform has never heard of keeps a KNOWN zero and is not punished. A run it
has heard of, or a platform that cannot be reached, gives `prior_spend_known=False`,
which makes every rolling-period rule `unknown` and routes it to the customer's own
`uncertainty_policy`. Never `fail`: nothing here is evidence that this purchase is
bad, only that the ceiling cannot be checked.

Run:  python3 -m research.lost_state
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tests.helpers import make_event, make_mandate           # noqa: E402
from wallet_control.decision_engine import evaluate_authorization  # noqa: E402
from wallet_control.mandate import HardRule                   # noqa: E402
from wallet_control.state import HistoryIndex, RunState       # noqa: E402

CAP, DAYS, STEP = 300, 7, Decimal("100")
CARD, MERCHANT = "CA_TEST", "ME_TEST_0001"
T0 = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


def _mandate():
    return make_mandate(hard_rules=[HardRule(
        field="authorization.billing_amount_chf", operator="<=", value=CAP,
        currency="CHF", scope="period", period_days=DAYS)])


def _history():
    return HistoryIndex({CARD: frozenset({MERCHANT})}, available=True)


def _run(mandate, state, tag, start, *, verbose=True):
    """Spend until refused. Baskets differ so the duplicate check is not what stops it."""
    approved, n = Decimal("0"), start
    while n - start < 8:
        when = T0 + timedelta(hours=n)
        auth_id = f"AU_{tag}_{n}"
        name = f"produce {n}"
        event = make_event(mandate=mandate, authorization_id=auth_id,
                           amount=float(STEP), timestamp=when,
                           items=[{"line_no": 1, "item_id": "IT0001", "item_name": name,
                                   "item_category": "groceries", "quantity": 1,
                                   "unit_price": float(STEP), "currency": "CHF",
                                   "item_details": ""}])
        result = evaluate_authorization(event, mandate, state)
        if verbose:
            print(f"      {n - start + 1}.  {result.decision:7s} {result.reason_codes[0]}")
        if result.decision != "allow":
            break
        state.record_decision(auth_id, result.decision, STEP, when,
                              merchant_id=MERCHANT,
                              basket_key=(("IT0001", name, 1, None, False, None),),
                              reason_codes=result.reason_codes)
        approved += STEP
        n += 1
    return approved, n


def main() -> None:
    mandate = _mandate()
    print(f"\n  MANDATE: at most CHF {CAP} across any {DAYS}-day period.\n")

    print("  BEFORE -- an empty ledger read as 'nothing was spent':")
    total, n = Decimal("0"), 0
    for i in (1, 2, 3):
        print(f"    run {i} (checkpoint lost, state starts empty):")
        spent, n = _run(mandate, RunState(history=_history(), card_id=CARD), f"r{i}", n)
        total += spent
    print(f"\n    approved inside ONE {DAYS}-day window: CHF {total} against a CHF {CAP} cap")
    print(f"    -> {total / CAP:.0f}x the ceiling, and unbounded in the number of restarts\n")

    print("  AFTER -- the same restart, with prior spend represented as UNKNOWN:")
    lost = RunState(history=_history(), card_id=CARD, prior_spend_known=False)
    _run(mandate, lost, "fixed", n)
    print("\n    The ceiling cannot be checked, so it is not silently reset -- the")
    print("    customer is asked, under their own uncertainty_policy.\n")

    result = evaluate_authorization(
        make_event(mandate=mandate, amount=float(STEP)), mandate, lost)
    print(f"    what the customer is told:\n      \"{result.customer_message}\"\n")


if __name__ == "__main__":
    main()

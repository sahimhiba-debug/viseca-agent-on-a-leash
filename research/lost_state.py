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

AND THE BUDGET WAS ONLY THE FIRST SYMPTOM. The first fix was a flag called
`prior_spend_known`, which named one CONSUMER of the lost state while three others
went on reading an empty collection as a fact about the world. The same restart also
switched off duplicate detection:

    the same basket, same shop, five minutes later, new authorization id
        state intact   ->  review   (order.duplicate_suspected)
        after restart  ->  ALLOW

One real order charged twice, with nothing forged. What was wrong was the name: the
run's state is INCOMPLETE, and every fact derived from it is therefore unknown.

BUT "AFTER A RESTART, NOTHING IS KNOWN" IS UNUSABLE -- it would send every purchase
to the customer for ever, since a lost state never becomes found. Incompleteness has
a HORIZON. Each of these facts answers a question about a bounded window (60 minutes
for a duplicate, 10 for velocity, `period_days` for a ceiling), and a state that has
been watching for longer than the window has seen all of it. The unknown expires by
itself, and the cost of a restart is bounded by the longest window the mandate uses.

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

    print("  AFTER -- the same restart, with the state known to be INCOMPLETE:")
    lost = RunState(history=_history(), card_id=CARD, resumed_incomplete=True)
    _run(mandate, lost, "fixed", n)
    print("\n    The ceiling cannot be checked, so it is not silently reset -- the")
    print("    customer is asked, under their own uncertainty_policy.\n")

    result = evaluate_authorization(
        make_event(mandate=mandate, amount=float(STEP)), mandate, lost)
    print(f"    what the customer is told:\n      \"{result.customer_message}\"\n")

    # ---- the second consumer, which the first fix missed -------------------------
    print("  THE SAME RESTART ALSO SWITCHED OFF DUPLICATE DETECTION:\n")
    plain = make_mandate(hard_rules=[HardRule(
        field="authorization.billing_amount_chf", operator="<=", value=500,
        currency="CHF", scope="purchase")])
    basket = (("IT0001", "Fresh produce selection", 1, None, False, None),)

    def repeat(state, label):
        first = T0
        intact = evaluate_authorization(
            make_event(mandate=plain, authorization_id="AU_D1", amount=400.0,
                       timestamp=first), plain, state)
        if intact.decision == "allow":
            state.record_decision("AU_D1", "allow", Decimal("400"), first,
                                  merchant_id=MERCHANT, basket_key=basket,
                                  reason_codes=intact.reason_codes)
        again = evaluate_authorization(
            make_event(mandate=plain, authorization_id="AU_D2", amount=400.0,
                       timestamp=first + timedelta(minutes=5)), plain, state)
        print(f"    {label:34s} {again.decision:7s} {again.reason_codes[0]}")

    repeat(RunState(history=_history(), card_id=CARD), "state intact")
    repeat(RunState(history=_history(), card_id=CARD, resumed_incomplete=True),
           "after a restart (repaired)")

    # ---- and the unknown expires on its own --------------------------------------
    print("\n  THE UNKNOWN IS TEMPORARY, WHICH IS WHAT MAKES IT A CONTROL:\n")
    day = make_mandate(hard_rules=[HardRule(
        field="authorization.billing_amount_chf", operator="<=", value=300,
        currency="CHF", scope="period", period_days=1)])
    state = RunState(history=_history(), card_id=CARD, resumed_incomplete=True)
    for label, when in (("first purchase after the restart", T0),
                        ("a full day of watching later  ", T0 + timedelta(days=1, minutes=1))):
        out = evaluate_authorization(
            make_event(mandate=day, authorization_id=f"AU_H{when.day}", amount=10.0,
                       timestamp=when), day, state)
        print(f"    1-day ceiling, {label}  ->  {out.decision}")
    print()


if __name__ == "__main__":
    main()

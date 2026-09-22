#!/usr/bin/env python3
"""Measure the ECONOMIC ENVELOPE of every official mandate.

The question is not "can the agent break a rule" -- it cannot, and 17/17 red-team
attacks and 133/133 corpus cases say so. The question is what the customer gets
when the agent breaks NOTHING:

    If the shopping agent is fully compromised but remains technically
    policy-compliant, what is the maximum CHF it can cause to be authorized?

Method. For each mandate, take the highest-value purchase the official replay
already ALLOWED -- so it is policy-compliant by construction, not by our judgement
-- and repeat it with fresh authorization_ids, spacing purchases just outside the
60-minute similar-purchase window. The agent never has to be clever, only patient.

Read the output with two qualifications, both load-bearing:

  * These are AUTHORIZATIONS, not losses. The WALLET models no credit limit -- but
    the official schema does, and an earlier version of this docstring wrongly said
    it did not. `accounts.csv` carries `monthly_limit_chf` for every account, and
    the scenario cards resolve to CHF 3,200-5,000 a month, so the real ceiling is
    nearer CHF 38,400-60,000 a year than the figures below. The finding is
    unchanged and the magnitude is not: the customer's stated policy contributes
    nothing to the bound, and what does bound it is an account limit they never set
    as part of this delegation. See docs/SECURITY_OBJECT_FALSIFICATION.md.
  * A year is an illustration of a RATE, not a prediction. There is no horizon to
    predict with -- which is the other half of the finding.

Nothing here touches the decision path. `fulfillment` is not imported by
`decision_engine`, `rules` or `facts`; the official replay stays 18/3/24.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # research/ lives at the repo root, outside the shipped package

from wallet_control.csv_data import load_merchants, load_purchase_attempt_items, load_scenario_catalogue
from wallet_control.decision_engine import evaluate_authorization
from research.fulfillment import classify_shape, fulfilment_state
from wallet_control.offline_replay import (
    ALL_SCENARIO_IDS,
    build_event,
    compile_and_confirm_mandate_for_scenario,
    history_csv_path,
    replay_scenario,
    scenario_rows,
)
from wallet_control.state import HistoryIndex, RunState

HORIZON_DAYS = 365
SPACING = timedelta(minutes=61)  # just outside state._DUPLICATE_WINDOW


def measure(scenario_id: str, *, stop_on_fulfilment: bool) -> tuple[int, Decimal, Decimal]:
    history = HistoryIndex.from_csv(history_csv_path())
    mandate = compile_and_confirm_mandate_for_scenario(scenario_id).snapshot()
    merchants, items = load_merchants(), load_purchase_attempt_items()

    replayed = {d.authorization_id: d for d in replay_scenario(scenario_id, history).decisions}
    template = max(
        (r for r in scenario_rows(scenario_id) if replayed[r["authorization_id"]].decision == "allow"),
        key=lambda r: float(r["billing_amount_chf"]),
    )
    unit = Decimal(template["billing_amount_chf"])
    start = datetime.fromisoformat(template["timestamp"].replace("Z", "+00:00"))

    state = RunState(history=history, card_id=mandate.card_id)
    total, approved = Decimal(0), 0
    for slot in range(int(timedelta(days=HORIZON_DAYS) / SPACING)):
        row = dict(template)
        row["authorization_id"] = f"AUX{slot:06d}"
        row["timestamp"] = (start + SPACING * slot).isoformat().replace("+00:00", "Z")
        context = {
            "approved_spend_in_period_chf": float(state.total_approved_spend_chf()),
            "recent_authorizations": state.recent_authorizations_context(),
        }
        event = build_event(row, items[template["authorization_id"]], merchants[template["merchant_id"]], mandate, context)
        if evaluate_authorization(event, mandate, state).decision != "allow":
            continue
        if stop_on_fulfilment and fulfilment_state(mandate, state, assessing=row["authorization_id"]).would_ask_customer:
            break  # the customer is asked here; the silent run ends
        total += unit
        approved += 1
    return approved, total, unit


def main() -> None:
    catalogue = load_scenario_catalogue()
    print(__doc__.split("\n\n")[0])
    print(f"\nHorizon {HORIZON_DAYS} simulated days, purchases spaced {SPACING} apart.\n")
    print(f"{'SCEN':9s} {'shape':10s} {'per-txn':>9s} {'what the customer wrote':>26s}")
    print(f"{'':9s} {'':10s} {'':>9s} {'policy engine alone':>26s} {'+ derived fulfilment':>24s}")
    print("-" * 96)

    engine_total = derived_total = Decimal(0)
    for scenario_id in ALL_SCENARIO_IDS:
        mandate = compile_and_confirm_mandate_for_scenario(scenario_id).snapshot()
        shape = classify_shape(mandate.instruction).shape
        n_engine, chf_engine, unit = measure(scenario_id, stop_on_fulfilment=False)
        n_derived, chf_derived, _ = measure(scenario_id, stop_on_fulfilment=True)
        engine_total += chf_engine
        derived_total += chf_derived
        print(
            f"{scenario_id:9s} {shape.value:10s} {unit:>9} "
            f"{n_engine:>7,d} = CHF {chf_engine:>11,.0f} {n_derived:>8,d} = CHF {chf_derived:>10,.0f}"
        )
    print("-" * 96)
    print(f"{'TOTAL':20s} {'':>9s} {'':>7s}   CHF {engine_total:>11,.0f} {'':>8s}   CHF {derived_total:>10,.0f}")
    print(f"\nSilent exposure removed by deriving fulfilment: CHF {engine_total - derived_total:,.0f}")
    print(
        f"Remaining: CHF {derived_total:,.0f} -- and none of it is a rule violation.\n"
        "That residue IS the delegation: a recurring mandate paced by a rolling cap, and a\n"
        "standing mandate the customer deliberately granted. Neither can state a total or an\n"
        "end date, because the official rule vocabulary has no way to write one down."
    )
    print("\nWhat each customer actually wrote, next to what it delegates:")
    for scenario_id in ALL_SCENARIO_IDS:
        print(f"  {scenario_id}  {catalogue[scenario_id]['cardholder_instruction'][:88]}")


if __name__ == "__main__":
    main()

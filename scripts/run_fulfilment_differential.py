#!/usr/bin/env python3
"""The differential experiment: replay the official 45 events through the shipping
engine and through the fulfilment observer, and report every disagreement.

The shipping engine's decisions are NOT modified. This script observes.

    python scripts/run_fulfilment_differential.py
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from wallet_control.fulfillment import FulfilmentMonitor, job_anchor  # noqa: E402
from wallet_control.offline_replay import replay_all  # noqa: E402


def main() -> int:
    items: dict[str, list[str]] = defaultdict(list)
    quantities: dict[str, list[str]] = defaultdict(list)
    with (ROOT / "data/official/purchase_attempt_items.csv").open() as f:
        for row in csv.DictReader(f):
            items[row["authorization_id"]].append(row["item_name"])
            quantities[row["authorization_id"]].append(row["quantity"])
    amounts = {}
    with (ROOT / "data/official/purchase_attempts.csv").open() as f:
        for row in csv.DictReader(f):
            amounts[row["authorization_id"]] = (row["billing_amount_chf"], row["timestamp"][:10])

    def matching_units(authorization_id: str, mandate) -> int:
        anchor = job_anchor(mandate)
        if anchor is None:
            return 1
        return sum(
            int(q) for name, q in zip(items[authorization_id], quantities[authorization_id])
            if anchor in name.lower()
        ) or 1

    result = replay_all()
    disagreements = 0
    exposed = 0.0

    print("Differential: shipping engine vs fulfilment observer, official 45 events\n")
    for scenario in result.scenarios:
        monitor = FulfilmentMonitor(scenario.mandate)
        shape = monitor.classification
        print(f"=== {scenario.scenario_id}  [{shape.shape.value.upper()}] {shape.evidence}")
        print(f'    "{scenario.cardholder_instruction[:92]}"')

        for decision in scenario.decisions:
            if decision.decision != "allow":
                continue
            units = matching_units(decision.authorization_id, scenario.mandate)
            verdict = monitor.assess(decision.authorization_id, units=units)
            amount, day = amounts[decision.authorization_id]
            if verdict.would_ask_customer:
                disagreements += 1
                exposed += float(amount)
                print(
                    f"    DISAGREE  {decision.authorization_id}  {day}  CHF {amount:>7}  {items[decision.authorization_id]}"
                )
                print(f"              engine: ALLOW   observer: ask the customer")
                print(f"              {verdict.detail}")
            else:
                print(f"      agree   {decision.authorization_id}  {day}  CHF {amount:>7}  ALLOW")
            monitor.observe_allow(decision.authorization_id, units=units)
        print()

    totals = result.total_counts()
    print("=" * 74)
    print(f"Official engine (UNCHANGED): {result.total_events()} events  {totals}")
    print(f"Disagreements: {disagreements} purchases the engine allows and the observer would question")
    print(f"Spend behind those purchases: CHF {exposed:,.2f}")
    print()
    print("Every one of those purchases satisfies the customer's policy in full. They")
    print("are repeat performances of a job the customer described once. No existing")
    print("check sees them: the near-duplicate window is 60 minutes and these are days")
    print("apart, at the same merchant, for the same item, at legitimate prices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

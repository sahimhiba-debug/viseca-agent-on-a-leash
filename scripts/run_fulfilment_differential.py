#!/usr/bin/env python3
"""Differential: the shipping engine's decisions vs. fulfilment DERIVED from the
run's own persisted decision ledger.

The engine is not modified. This replays the official 45 events exactly as
`offline_replay` does, and additionally derives fulfilment after each approval.

    python scripts/run_fulfilment_differential.py [--json]
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))  # research/ lives at the repo root, outside the shipped package

from wallet_control.csv_data import (  # noqa: E402
    history_csv_path,
    load_merchants,
    load_purchase_attempt_items,
    load_scenario_catalogue,
    scenario_rows,
)
from wallet_control.decision_engine import evaluate_authorization  # noqa: E402
from research.fulfillment import classify_shape, fulfilment_state  # noqa: E402
from wallet_control.offline_replay import (  # noqa: E402
    ALL_SCENARIO_IDS,
    build_event,
    compile_and_confirm_mandate_for_scenario,
)
from wallet_control.state import HistoryIndex, RunState  # noqa: E402


def main() -> int:
    as_json = "--json" in sys.argv
    history = HistoryIndex.from_csv(history_csv_path())
    items_by_auth = load_purchase_attempt_items()
    merchants = load_merchants()
    catalogue = load_scenario_catalogue()

    names: dict[str, list[str]] = defaultdict(list)
    with (ROOT / "data/official/purchase_attempt_items.csv").open() as f:
        for row in csv.DictReader(f):
            names[row["authorization_id"]].append(row["item_name"])

    report: dict = {
        "scenarios": [],
        "disagreements": [],
        "engine_counts": {"allow": 0, "review": 0, "block": 0},
    }
    exposed = 0.0

    for scenario_id in ALL_SCENARIO_IDS:
        mandate = compile_and_confirm_mandate_for_scenario(scenario_id).snapshot()
        state = RunState(history=history, card_id=mandate.card_id)
        shape = classify_shape(mandate.instruction)
        entry = {
            "scenario_id": scenario_id,
            "shape": shape.shape.value,
            "evidence": shape.evidence,
            "instruction": catalogue[scenario_id]["cardholder_instruction"],
            "decisions": [],
        }
        if not as_json:
            print(f"=== {scenario_id}  [{shape.shape.value.upper()}] {shape.evidence}")
            print(f'    "{entry["instruction"][:92]}"')

        for row in scenario_rows(scenario_id):
            context = {
                "approved_spend_in_period_chf": float(state.total_approved_spend_chf()),
                "recent_authorizations": state.recent_authorizations_context(),
            }
            event = build_event(
                row, items_by_auth[row["authorization_id"]], merchants[row["merchant_id"]], mandate, context
            )
            result = evaluate_authorization(event, mandate, state)
            report["engine_counts"][result.decision] += 1
            if result.decision != "allow":
                continue

            verdict = fulfilment_state(mandate, state, assessing=result.authorization_id)
            record = {
                "authorization_id": result.authorization_id,
                "date": row["timestamp"][:10],
                "amount_chf": float(row["billing_amount_chf"]),
                "items": names[result.authorization_id],
                "engine": "allow",
                "fulfilment": verdict.verdict,
                "would_ask_customer": verdict.would_ask_customer,
                "detail": verdict.detail,
            }
            entry["decisions"].append(record)

            if verdict.would_ask_customer:
                report["disagreements"].append({"scenario_id": scenario_id, **record})
                exposed += record["amount_chf"]
                if not as_json:
                    print(
                        f"    DISAGREE  {record['authorization_id']}  {record['date']}  "
                        f"CHF {record['amount_chf']:>7.2f}  {record['items']}"
                    )
                    print(f"              engine: ALLOW   derived: {verdict.verdict} -> ask the customer")
                    print(f"              {verdict.detail}")
            elif not as_json:
                print(
                    f"      agree   {record['authorization_id']}  {record['date']}  "
                    f"CHF {record['amount_chf']:>7.2f}  ALLOW"
                )

        report["scenarios"].append(entry)
        if not as_json:
            print()

    report["total_disagreements"] = len(report["disagreements"])
    report["exposed_chf"] = round(exposed, 2)

    if as_json:
        print(json.dumps(report, indent=2))
        return 0

    print("=" * 74)
    print(f"Official engine (UNCHANGED): 45 events  {report['engine_counts']}")
    print(f"Disagreements: {report['total_disagreements']}   spend behind them: CHF {exposed:,.2f}")
    print()
    print("Fulfilment is DERIVED from the run's persisted decision ledger, not tracked")
    print("beside it. That is why it survives a restart, includes step-ups a human")
    print("approved, and gives two workers the same answer: there is no second record")
    print("that can drift from the first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

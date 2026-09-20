"""Offline replay: build authorization events from the official CSV pack and
evaluate them through the same decision engine and mandate lifecycle the live
worker uses (technical_details.md, "3. Test your engine offline").

This module does not know any expected outcome. It reads `cardholder_instruction`
from `scenario_catalogue.csv`, compiles it into a mandate exactly the way a real
customer's instruction would be compiled, and replays that scenario's purchase
attempts in `replay_order` against the same `evaluate_authorization` used for the
live API. Nothing here branches on `scenario_id` or `authorization_id` to pick an
outcome -- see docs/OFFLINE_REPLAY.md for the explicit no-hardcoding check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .csv_data import (
    history_csv_path,
    load_merchants,
    load_purchase_attempt_items,
    load_scenario_authorities,
    load_scenario_catalogue,
    scenario_rows,
)
from .decision_engine import EngineDecision, evaluate_authorization
from .mandate import Mandate, MandateSnapshot
from .policy_compiler import compile_instruction
from .state import HistoryIndex, RunState

ALL_SCENARIO_IDS = ("SCEN0000", "SCEN0001", "SCEN0002", "SCEN0003", "SCEN0004")


def build_event(
    row: dict[str, str],
    items: list[dict[str, str]],
    merchant: dict[str, str],
    mandate: MandateSnapshot,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build one schema-valid `authorization.request` event from a CSV row.

    Follows technical_details.md step 3 exactly: numbers become numbers, empty
    optional fields become `null`, simulated purchase time is preserved, and a
    fresh real-clock deadline is assigned. `authorization_id` and
    `source_authorization_id` are the same value here because offline replay has
    no separate "live run" identity to rewrite them against -- see the docstring
    in offline_replay.py's module header and docs/OFFLINE_REPLAY.md.
    """
    now = datetime.now(timezone.utc)
    return {
        "type": "authorization.request",
        "request_id": f"req_offline_{row['authorization_id']}",
        "deadline_at": (now + timedelta(seconds=8)).isoformat().replace("+00:00", "Z"),
        "authorization": {
            "authorization_id": row["authorization_id"],
            "source_authorization_id": row["authorization_id"],
            "scenario_id": row["scenario_id"],
            "replay_order": int(row["replay_order"]),
            "mandate_id": mandate.mandate_id,
            "profile_id": mandate.profile_id,
            "card_id": row["card_id"],
            "initiator_type": "agent",
            "merchant": {
                "merchant_id": merchant["merchant_id"],
                "merchant_name": merchant["merchant_name"],
                "merchant_category": merchant["merchant_category"],
                "merchant_mcc": merchant["merchant_mcc"],
                "merchant_country": merchant["merchant_country"],
                "merchant_city": merchant["merchant_city"],
                "availability": merchant["availability"],
                "recurring_capable": merchant["recurring_capable"],
            },
            "timestamp": row["timestamp"],
            "amount": float(row["amount"]),
            "currency": row["currency"],
            "billing_amount_chf": float(row["billing_amount_chf"]),
            "items_subtotal": float(row["items_subtotal"]),
            "delivery_fee": float(row["delivery_fee"]),
            "channel": row["channel"],
            "customer_device_id": row["customer_device_id"],
            "authority_status": row["authority_status"],
            "card_status_at_attempt": row["card_status_at_attempt"],
            "spend_in_period_before_chf": None,
            "recent_attempt_count_10m": int(row["recent_attempt_count_10m"]),
            "fulfillment_method": row["fulfillment_method"],
            "delivery_by": row["delivery_by"] or None,
            "order_returnable": row["order_returnable"],
            "order_cancellable": row["order_cancellable"],
            "related_authorization_id": row["related_authorization_id"] or None,
            "related_authorization_status": row["related_authorization_status"] or None,
            "purchase_description": row["purchase_description"],
            "items": [
                {
                    "line_no": int(it["line_no"]),
                    "item_id": it["item_id"],
                    "item_name": it["item_name"],
                    "item_category": it["item_category"],
                    "quantity": int(it["quantity"]),
                    "unit_price": float(it["unit_price"]),
                    "currency": it["currency"],
                    "item_details": it["item_details"],
                }
                for it in items
            ],
        },
        "mandate": {
            "mandate_id": mandate.mandate_id,
            "status": mandate.status.value,
            "customer_id": mandate.customer_id,
            "card_id": mandate.card_id,
            "instruction": mandate.instruction,
            "hard_rules": [r.as_dict() for r in mandate.hard_rules],
            "uncertainty_policy": mandate.uncertainty_policy.value,
            "profile_id": mandate.profile_id,
        },
        "context": context,
        "runtime": {
            "received_at": now.isoformat().replace("+00:00", "Z"),
            "history_window_minutes": 10,
            "context_basis": "run_decisions_and_scenario_timestamps",
        },
    }


def compile_and_confirm_mandate_for_scenario(scenario_id: str) -> Mandate:
    catalogue = load_scenario_catalogue()[scenario_id]
    authorities = load_scenario_authorities()
    row0 = scenario_rows(scenario_id)[0]
    authority = authorities[row0["authority_id"]]

    compiled = compile_instruction(catalogue["cardholder_instruction"])
    mandate = Mandate.draft(
        catalogue["cardholder_instruction"],
        compiled.hard_rules,
        compiled.uncertainty_policy,
        compiled.guidance,
        compiled.open_questions,
        compiled.unsupported_restrictions,
    )
    # The offline replay stands in for a customer who has already reviewed and accepted
    # the mandate, so it acknowledges explicitly rather than leaving the field unset.
    # Leaving it unset would ALSO confirm -- an empty list passes the gate -- and that
    # is precisely the bypass-by-omission this project keeps finding. SCEN0000's "buy
    # ONE grocery item" is a real unsupported restriction; this is where it is accepted.
    mandate.confirm(
        confirmed=True,
        customer_id=authority["customer_id"],
        card_id=authority["card_id"],
        profile_id=f"PROFILE_OFFLINE_{scenario_id}",
        acknowledged_unsupported=compiled.unsupported_restrictions,
    )
    return mandate


@dataclass
class ScenarioReplayResult:
    scenario_id: str
    scenario_name: str
    cardholder_instruction: str
    mandate: MandateSnapshot
    decisions: list[EngineDecision]

    def counts(self) -> dict[str, int]:
        out = {"allow": 0, "review": 0, "block": 0}
        for d in self.decisions:
            out[d.decision] += 1
        return out


def replay_scenario(scenario_id: str, history: HistoryIndex | None = None) -> ScenarioReplayResult:
    history = history or HistoryIndex.from_csv(history_csv_path())
    catalogue = load_scenario_catalogue()[scenario_id]
    mandate = compile_and_confirm_mandate_for_scenario(scenario_id)
    snapshot = mandate.snapshot()
    state = RunState(history=history, card_id=snapshot.card_id)

    items_by_auth = load_purchase_attempt_items()
    merchants = load_merchants()

    decisions: list[EngineDecision] = []
    for row in scenario_rows(scenario_id):
        merchant = merchants[row["merchant_id"]]
        items = items_by_auth[row["authorization_id"]]
        context = {
            "approved_spend_in_period_chf": float(state.total_approved_spend_chf()),
            "recent_authorizations": state.recent_authorizations_context(),
        }
        event = build_event(row, items, merchant, snapshot, context)
        decisions.append(evaluate_authorization(event, snapshot, state))

    return ScenarioReplayResult(
        scenario_id=scenario_id,
        scenario_name=catalogue["scenario_name"],
        cardholder_instruction=catalogue["cardholder_instruction"],
        mandate=snapshot,
        decisions=decisions,
    )


@dataclass
class FullReplayResult:
    scenarios: list[ScenarioReplayResult]

    def total_counts(self) -> dict[str, int]:
        out = {"allow": 0, "review": 0, "block": 0}
        for scenario in self.scenarios:
            for k, v in scenario.counts().items():
                out[k] += v
        return out

    def total_events(self) -> int:
        return sum(len(s.decisions) for s in self.scenarios)


def replay_all() -> FullReplayResult:
    history = HistoryIndex.from_csv(history_csv_path())
    return FullReplayResult(scenarios=[replay_scenario(sid, history) for sid in ALL_SCENARIO_IDS])

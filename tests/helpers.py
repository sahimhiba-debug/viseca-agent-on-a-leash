"""Small synthetic-event builder for unit tests that don't need the full CSV pack."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from wallet_control.mandate import Mandate, MandateSnapshot, UncertaintyPolicy


def make_mandate(
    instruction: str = "Test instruction",
    hard_rules: list | None = None,
    uncertainty_policy: UncertaintyPolicy = UncertaintyPolicy.ASK,
    customer_id: str = "CU_TEST",
    card_id: str = "CA_TEST",
) -> MandateSnapshot:
    m = Mandate.draft(instruction, hard_rules or [], uncertainty_policy)
    m.confirm(confirmed=True, customer_id=customer_id, card_id=card_id, profile_id="PROFILE_TEST")
    return m.snapshot()


def make_event(
    *,
    authorization_id: str = "AU_TEST_0001",
    mandate: MandateSnapshot,
    merchant_id: str = "ME_TEST_0001",
    merchant_name: str = "Test Merchant",
    merchant_category: str = "groceries",
    amount: float = 20.0,
    currency: str = "CHF",
    billing_amount_chf: float | None = None,
    items_subtotal: float | None = None,
    delivery_fee: float = 0.0,
    channel: str = "ecommerce",
    device_id: str = "DVC-TEST",
    recent_attempt_count_10m: int = 0,
    order_returnable: str = "unknown",
    order_cancellable: str = "unknown",
    related_authorization_id: str | None = None,
    related_authorization_status: str | None = None,
    items: list[dict[str, Any]] | None = None,
    timestamp: datetime | None = None,
    card_id: str = "CA_TEST",
    delivery_by: str | None = None,
) -> dict[str, Any]:
    ts = timestamp or datetime(2026, 8, 12, 9, 0, 0, tzinfo=timezone.utc)
    billing_amount_chf = billing_amount_chf if billing_amount_chf is not None else amount
    items_subtotal = items_subtotal if items_subtotal is not None else (amount - delivery_fee)
    items = items or [
        {
            "line_no": 1,
            "item_id": "IT_TEST_0001",
            "item_name": "Test item",
            "item_category": "groceries",
            "quantity": 1,
            "unit_price": items_subtotal,
            "currency": currency,
            "item_details": "",
        }
    ]
    return {
        "type": "authorization.request",
        "request_id": f"req_{authorization_id}",
        "deadline_at": (ts + timedelta(seconds=8)).isoformat().replace("+00:00", "Z"),
        "authorization": {
            "authorization_id": authorization_id,
            "source_authorization_id": authorization_id,
            "scenario_id": "SCEN0000",
            "replay_order": 1,
            "mandate_id": mandate.mandate_id,
            "profile_id": mandate.profile_id,
            "card_id": card_id,
            "initiator_type": "agent",
            "merchant": {
                "merchant_id": merchant_id,
                "merchant_name": merchant_name,
                "merchant_category": merchant_category,
                "merchant_mcc": "5411",
                "merchant_country": "CH",
                "merchant_city": "Zurich",
                "availability": "online",
                "recurring_capable": "false",
            },
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "amount": amount,
            "currency": currency,
            "billing_amount_chf": billing_amount_chf,
            "items_subtotal": items_subtotal,
            "delivery_fee": delivery_fee,
            "channel": channel,
            "customer_device_id": device_id,
            "authority_status": "active",
            "card_status_at_attempt": "active",
            "spend_in_period_before_chf": None,
            "recent_attempt_count_10m": recent_attempt_count_10m,
            "fulfillment_method": "delivery",
            "delivery_by": delivery_by,
            "order_returnable": order_returnable,
            "order_cancellable": order_cancellable,
            "related_authorization_id": related_authorization_id,
            "related_authorization_status": related_authorization_status,
            "purchase_description": "Test purchase",
            "items": items,
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
        "context": {"approved_spend_in_period_chf": 0.0, "recent_authorizations": []},
        "runtime": {
            "received_at": ts.isoformat().replace("+00:00", "Z"),
            "history_window_minutes": 10,
            "context_basis": "run_decisions_and_scenario_timestamps",
        },
    }

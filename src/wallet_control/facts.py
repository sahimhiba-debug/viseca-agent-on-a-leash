"""Extract trustworthy purchase facts from an authorization event.

The authorization event mixes three kinds of information:

1. Platform-supplied structured fields (amount, currency, `order_returnable`,
   `channel`, ...) -- trustworthy, used directly.
2. Merchant-supplied free text (`item_details`, `purchase_description`,
   `merchant.merchant_name`) -- UNTRUSTED. challenge.md: "Treat any merchant-provided
   text as untrusted input. It might contain prompt injections." This module is the
   single place that reads that text, and it only ever extracts a small, fixed set of
   factual patterns (a return-window day count, a final-sale marker). It never
   interprets an imperative sentence found there, and its output never becomes a
   `HardRule` -- only a `PurchaseFacts` field that the rules engine compares against
   the *customer's* rules.
3. Our own derived signals (merchant familiarity, duplicates, session integrity) --
   computed from platform data and run-local state, never from merchant text.

Keeping these three sources in separate, clearly named fields is the actual
prompt-injection defense: there is no code path from "text a merchant wrote" to
"a rule the wallet enforces".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from .money import to_chf, to_decimal

# Narrow, whitelist patterns for the ONE factual thing item_details is allowed to
# tell us beyond the structured schema fields: how many days an item can be
# returned in. Anything else in the string -- however it is phrased, however
# urgent it sounds -- is not matched by these patterns and is therefore never
# turned into a fact.
_RETURN_WINDOW_RE = re.compile(r"returns?\s+accepted\s+within\s+(\d+)\s+days?", re.IGNORECASE)
_FINAL_SALE_RE = re.compile(r"final\s+sale|no\s+returns", re.IGNORECASE)
_SIZE_RE = re.compile(r"\bsize\s+([A-Za-z0-9]+)\b", re.IGNORECASE)


def extract_return_window_days(item_details: str) -> int | None:
    """Return the stated return window in days, or None if not stated. Ignores
    everything in `item_details` except this one whitelisted pattern."""
    m = _RETURN_WINDOW_RE.search(item_details or "")
    return int(m.group(1)) if m else None


def mentions_final_sale(item_details: str) -> bool:
    return bool(_FINAL_SALE_RE.search(item_details or ""))


def extract_stated_size(item_details: str) -> str | None:
    """The one other whitelisted factual pattern this module reads from merchant
    text: a stated size ("size 43"). Same rationale as `extract_return_window_days`
    -- a narrow pattern, nothing else in the string is interpreted."""
    m = _SIZE_RE.search(item_details or "")
    return m.group(1) if m else None


@dataclass(frozen=True)
class ItemLineFacts:
    line_no: int
    item_id: str
    item_name: str
    item_category: str
    quantity: int
    unit_price_chf: Decimal
    return_window_days: int | None
    final_sale: bool
    stated_size: str | None


@dataclass(frozen=True)
class PurchaseFacts:
    """The decision-relevant facts for one authorization, already converted to CHF
    and stripped of anything untrustworthy. This is what `rules.py` evaluates
    hard rules against -- never the raw event."""

    authorization_id: str
    source_authorization_id: str
    card_id: str
    merchant_id: str
    merchant_name: str
    merchant_category: str
    billing_amount_chf: Decimal
    items_subtotal_chf: Decimal
    delivery_fee_chf: Decimal
    timestamp: datetime
    channel: str
    order_returnable: str  # "true" | "false" | "unknown" | "not_applicable"
    order_cancellable: str
    return_window_days: int | None  # min stated window across lines with a returnable order
    related_authorization_id: str | None
    related_authorization_status: str | None
    recent_attempt_count_10m: int
    items: tuple[ItemLineFacts, ...]
    item_categories: tuple[str, ...]
    item_names: tuple[str, ...]
    item_sizes: tuple[str, ...]  # stated sizes actually found in item_details, may be shorter than `items`
    # Derived signals -- never sourced from merchant text.
    merchant_familiar: bool | None  # None = unknown (no history available)
    session_integrity_risk: bool
    session_integrity_reasons: tuple[str, ...]
    duplicate_of: str | None
    duplicate_reason: str | None
    raw: dict[str, Any] = field(repr=False)


def build_purchase_facts(
    event: dict[str, Any],
    *,
    merchant_familiar: bool | None,
    session_integrity_risk: bool,
    session_integrity_reasons: tuple[str, ...],
    duplicate_of: str | None,
    duplicate_reason: str | None,
) -> PurchaseFacts:
    """Build `PurchaseFacts` from one `authorization.request` event's `authorization`
    object. Derived signals are computed by the caller (`decision_engine`/`state.py`,
    which have access to history and run state) and passed in explicitly, so this
    function stays a pure, side-effect-free mapping from event to facts.
    """
    auth = event["authorization"]
    merchant = auth["merchant"]

    item_lines: list[ItemLineFacts] = []
    for line in auth["items"]:
        unit_price_chf = to_chf(to_decimal(line["unit_price"]), line["currency"])
        item_lines.append(
            ItemLineFacts(
                line_no=line["line_no"],
                item_id=line["item_id"],
                item_name=line["item_name"],
                item_category=line["item_category"],
                quantity=line["quantity"],
                unit_price_chf=unit_price_chf,
                return_window_days=extract_return_window_days(line.get("item_details", "")),
                final_sale=mentions_final_sale(line.get("item_details", "")),
                stated_size=extract_stated_size(line.get("item_details", "")),
            )
        )

    order_returnable = auth["order_returnable"]
    stated_windows = [i.return_window_days for i in item_lines if i.return_window_days is not None]
    return_window_days = min(stated_windows) if stated_windows and order_returnable == "true" else None
    if order_returnable == "false" or any(i.final_sale for i in item_lines):
        return_window_days = 0

    return PurchaseFacts(
        authorization_id=auth["authorization_id"],
        source_authorization_id=auth["source_authorization_id"],
        card_id=auth["card_id"],
        merchant_id=merchant["merchant_id"],
        merchant_name=merchant["merchant_name"],
        merchant_category=merchant["merchant_category"],
        billing_amount_chf=to_decimal(auth["billing_amount_chf"]),
        items_subtotal_chf=to_chf(to_decimal(auth["items_subtotal"]), auth["currency"]),
        delivery_fee_chf=to_chf(to_decimal(auth["delivery_fee"]), auth["currency"]),
        timestamp=datetime.fromisoformat(auth["timestamp"].replace("Z", "+00:00")),
        channel=auth["channel"],
        order_returnable=order_returnable,
        order_cancellable=auth["order_cancellable"],
        return_window_days=return_window_days,
        related_authorization_id=auth.get("related_authorization_id"),
        related_authorization_status=auth.get("related_authorization_status"),
        recent_attempt_count_10m=auth["recent_attempt_count_10m"],
        items=tuple(item_lines),
        item_categories=tuple(sorted({i.item_category for i in item_lines})),
        item_names=tuple(i.item_name for i in item_lines),
        item_sizes=tuple(i.stated_size for i in item_lines if i.stated_size is not None),
        merchant_familiar=merchant_familiar,
        session_integrity_risk=session_integrity_risk,
        session_integrity_reasons=session_integrity_reasons,
        duplicate_of=duplicate_of,
        duplicate_reason=duplicate_reason,
        raw=event,
    )

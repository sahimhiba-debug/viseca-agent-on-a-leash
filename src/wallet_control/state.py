"""Runtime state a control layer must keep across a sequence of decisions.

technical_details.md step 8 lists exactly what this module exists to get right:

  * "Count final approvals when enforcing spending limits. A purchase waiting for
    a human answer is not yet approved." -> only APPROVE (including a resolved
    step_up) ever enters `RunState._approved_spend`.
  * "Recognize repeated delivery by its live purchase ID. Record it once, so a
    retry does not add the amount twice." -> `get_stored_decision` / idempotency.
  * "Check distinct but similar purchases against earlier outcomes; different IDs
    can still describe an unwanted duplicate order." -> `find_similar_recent`.

Two different things are both called "duplicate" in this codebase and must not be
conflated:

  1. **Repeated delivery**: the platform re-sends the *same* `authorization_id*
     (a network retry). This is pure idempotency: replay the stored decision,
     do not re-evaluate, do not double-count spend.
  2. **Similar recent purchase**: a *different* `authorization_id` for what looks
     like the same real-world order (same merchant, same basket, same amount,
     shortly after). This is not automatically fraud or automatically fine --
     it is evidence fed into the normal uncertainty pathway.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

Decision = Literal["allow", "review", "block"]

_DUPLICATE_WINDOW = timedelta(minutes=60)


class HistoryIndex:
    """Answers "has this card ever had an approved purchase at this merchant?" from
    the official `authorization_history.csv`. Used for the `merchant.familiar` rule.

    `available` distinguishes "we checked and the answer is no" (False) from "we
    have no history data to check at all" (None, unknown) -- these must not be
    conflated, or a missing history fetch would silently look identical to a
    clearly-unfamiliar merchant.
    """

    def __init__(self, approved_merchants_by_card: dict[str, frozenset[str]], *, available: bool = True) -> None:
        self._approved_merchants_by_card = approved_merchants_by_card
        self.available = available

    @classmethod
    def empty(cls) -> "HistoryIndex":
        return cls({}, available=False)

    @classmethod
    def from_csv(cls, path: Path) -> "HistoryIndex":
        merchants_by_card: dict[str, set[str]] = {}
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["status"] != "approved":
                    continue
                merchants_by_card.setdefault(row["card_id"], set()).add(row["merchant_id"])
        return cls({k: frozenset(v) for k, v in merchants_by_card.items()}, available=True)

    def is_familiar(self, card_id: str, merchant_id: str) -> bool | None:
        if not self.available:
            return None
        # A card with history but never this merchant is genuinely unfamiliar (False).
        # A card we have no record of at all is unknown (None) -- e.g. a brand-new
        # card, or a data gap -- so the engine treats it as missing information
        # rather than a confirmed violation.
        if card_id not in self._approved_merchants_by_card:
            return None
        return merchant_id in self._approved_merchants_by_card[card_id]


@dataclass(frozen=True)
class StoredDecision:
    """The accepted, final-so-far result for one live authorization_id."""

    authorization_id: str
    decision: Decision
    billing_amount_chf: Decimal
    timestamp: datetime
    counted_in_spend: bool  # True once an approve has been counted into rolling spend
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RecentAttempt:
    authorization_id: str
    merchant_id: str
    basket_key: tuple[tuple[str, int], ...]
    billing_amount_chf: Decimal
    timestamp: datetime
    decision: Decision


@dataclass
class RunState:
    """All mutable state for one mandate/run. One instance per run -- the offline
    replay creates one per scenario; the live worker creates one per run_id."""

    history: HistoryIndex
    card_id: str
    _decisions: dict[str, StoredDecision] = field(default_factory=dict)
    _approved_spend: list[tuple[datetime, Decimal]] = field(default_factory=list)
    _recent_attempts: list[_RecentAttempt] = field(default_factory=list)
    _last_device_id: str | None = None

    # --- idempotency: repeated delivery of the same authorization_id ---------------
    def get_stored_decision(self, authorization_id: str) -> StoredDecision | None:
        return self._decisions.get(authorization_id)

    def record_decision(self, authorization_id: str, decision: Decision, billing_amount_chf: Decimal, timestamp: datetime) -> StoredDecision:
        if authorization_id in self._decisions:
            return self._decisions[authorization_id]  # never overwrite; first outcome for an ID is final here
        counted = decision == "allow"
        if counted:
            self._approved_spend.append((timestamp, billing_amount_chf))
        stored = StoredDecision(authorization_id, decision, billing_amount_chf, timestamp, counted)
        self._decisions[authorization_id] = stored
        return stored

    def record_resolution(self, authorization_id: str, final_decision: Decision, billing_amount_chf: Decimal, timestamp: datetime) -> StoredDecision:
        """Apply a human's answer to a previously-`review`d authorization. Bound to
        the specific authorization_id it resolves -- it can only change *that*
        authorization's outcome, never the standing mandate (see `mandate.py`)."""
        existing = self._decisions.get(authorization_id)
        if existing is not None and existing.decision != "review":
            return existing  # already resolved or was never pending; resolution is not re-appliable
        if final_decision == "allow":
            self._approved_spend.append((timestamp, billing_amount_chf))
        stored = StoredDecision(authorization_id, final_decision, billing_amount_chf, timestamp, final_decision == "allow")
        self._decisions[authorization_id] = stored
        return stored

    # --- rolling-window spend -------------------------------------------------------
    def rolling_spend_chf(self, as_of: datetime, period_days: int) -> Decimal:
        window_start = as_of - timedelta(days=period_days)
        return sum((amt for ts, amt in self._approved_spend if window_start < ts <= as_of), Decimal("0"))

    def total_approved_spend_chf(self) -> Decimal:
        """Cumulative approved spend since the run started -- mirrors the platform's
        `context.approved_spend_in_period_chf`, which technical_details.md says is
        "recomputed from the decisions actually taken in the run" (not a fixed
        window). Mandate-specific rolling windows are evaluated separately via
        `rolling_spend_chf`, not from this figure."""
        return sum((amt for _, amt in self._approved_spend), Decimal("0"))

    def recent_authorizations_context(self, limit: int = 5) -> list[dict]:
        """The last `limit` authorizations seen in this run, in the event schema's
        `context.recent_authorizations` shape, for display/evidence purposes."""
        status_map = {"allow": "approved", "block": "declined", "review": "pending"}
        out = []
        for prior in self._recent_attempts[-limit:]:
            out.append(
                {
                    "authorization_id": prior.authorization_id,
                    "timestamp": prior.timestamp.isoformat().replace("+00:00", "Z"),
                    "merchant_id": prior.merchant_id,
                    "billing_amount_chf": float(prior.billing_amount_chf),
                    "status": status_map[prior.decision],
                }
            )
        return out

    # --- similar-recent-purchase (fraud-relevant) duplicate detection ---------------
    def find_similar_recent(
        self,
        *,
        authorization_id: str,
        merchant_id: str,
        basket_key: tuple[tuple[str, int], ...],
        billing_amount_chf: Decimal,
        timestamp: datetime,
    ) -> tuple[str, str] | None:
        for prior in reversed(self._recent_attempts):
            if prior.authorization_id == authorization_id:
                continue
            if prior.decision == "block":
                continue  # a declined attempt is not "an unwanted duplicate order" to worry about
            if prior.merchant_id != merchant_id:
                continue
            if prior.basket_key != basket_key:
                continue
            if prior.billing_amount_chf != billing_amount_chf:
                continue
            if abs(timestamp - prior.timestamp) > _DUPLICATE_WINDOW:
                continue
            return prior.authorization_id, (
                f"same merchant, basket, and amount as {prior.authorization_id} "
                f"{abs(timestamp - prior.timestamp)} apart"
            )
        return None

    def remember_attempt(
        self,
        *,
        authorization_id: str,
        merchant_id: str,
        basket_key: tuple[tuple[str, int], ...],
        billing_amount_chf: Decimal,
        timestamp: datetime,
        decision: Decision,
    ) -> None:
        self._recent_attempts.append(
            _RecentAttempt(authorization_id, merchant_id, basket_key, billing_amount_chf, timestamp, decision)
        )

    # --- session integrity heuristic -------------------------------------------------
    def session_signals(self, device_id: str, recent_attempt_count_10m: int, merchant_familiar: bool | None) -> tuple[bool, tuple[str, ...]]:
        """A small, explicit heuristic -- not a model -- so it is auditable and has
        no failure mode when unavailable. Escalates on rising velocity combined with
        a device change or an unfamiliar merchant; automatically relaxes again once
        those signals subside, because it is recomputed fresh from only the current
        event's signals plus the single last-seen device, with no decaying "risk
        score" that could get stuck elevated.
        """
        reasons: list[str] = []
        device_changed = self._last_device_id is not None and device_id != self._last_device_id
        if device_changed:
            reasons.append(f"device changed from {self._last_device_id} to {device_id}")
        if recent_attempt_count_10m >= 2:
            reasons.append(f"{recent_attempt_count_10m} other attempts in the last 10 minutes")
        if merchant_familiar is False and device_changed:
            reasons.append("unfamiliar merchant immediately after a device change")
        self._last_device_id = device_id
        risky = (device_changed and recent_attempt_count_10m >= 1) or recent_attempt_count_10m >= 2
        return risky, tuple(reasons)

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
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

Decision = Literal["allow", "review", "block"]

# How long a PaymentAuthority remains valid for execution after being issued.
# Not specified anywhere in technical_details.md (the official contract has no
# payment-execution endpoint at all -- see docs/VISECA_INTEGRATION.md); chosen as
# a deliberately short, demonstrable window for this synthetic prototype, real-clock
# based like a response deadline (I21 in SECURITY_INVARIANTS.md), not simulated-time
# based like a spending window -- a payment authority's validity is about how long
# the EXECUTION side has to act on an already-made decision, not about when the
# underlying purchase occurred.
DEFAULT_AUTHORITY_TTL = timedelta(minutes=15)

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
    """The accepted, final-so-far result for one live authorization_id.

    `timestamp` is always the purchase's *simulated* time (`authorization.timestamp`),
    never a real-clock time -- it is what rolling-window spend is keyed on
    (technical_details.md: "Use simulated purchase time for spending windows, and
    the real clock for response deadlines"). A human resolving a step_up an hour
    (real time) after it was raised must not shift that purchase's window
    attribution; `resolved_at` carries the real-clock answer time separately, for
    audit display only.

    `merchant_id` and `basket_key` are a fingerprint of what was actually decided,
    used to detect a repeated `authorization_id` whose underlying facts changed
    between deliveries (see `find_similar_recent`'s module docstring and
    `evaluate_authorization`'s idempotency check) -- a case that must never be
    silently trusted either way.
    """

    authorization_id: str
    decision: Decision
    billing_amount_chf: Decimal
    timestamp: datetime
    counted_in_spend: bool  # True once an approve has been counted into rolling spend
    merchant_id: str
    basket_key: tuple[tuple[str, int], ...]
    was_reviewed: bool = False  # True iff this authorization was ever put to REVIEW
    resolved_at: datetime | None = None  # real-clock time of a human's answer, audit-only
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PaymentAuthority:
    """A narrow, single-purpose, inspectable payment authority -- this project's
    local, unsigned analog of the "derive a narrower credential from a broader
    approval" pattern used by every real agentic-payments system researched (see
    docs/AGENTIC_COMMERCE_RESEARCH.md and docs/RND_CAPABILITY_AUTHORITY.md):
    Mastercard's Agentic Tokens, Google AP2's Payment Mandate, OpenAI's
    Delegated Payment token. Issued ONLY as a byproduct of an ALLOW decision
    (`RunState.issue_authority`); nothing else in this codebase constructs one.

    Deliberately NOT cryptographically signed -- there is no PKI, relying party,
    or verifier in this challenge's sandbox, so a "signature" no one can check
    would be theatre, not security (see AGENTIC_COMMERCE_RESEARCH.md's honest
    classification table). What this object provides instead is a single,
    self-contained, inspectable record of exactly what was authorized, which
    `payment.MockPSP.charge_via_authority` re-verifies as a whole rather than as
    scattered fields.
    """

    authorization_id: str
    mandate_id: str
    merchant_id: str
    amount_ceiling_chf: Decimal
    currency: str
    issued_at: datetime  # real clock -- see DEFAULT_AUTHORITY_TTL's docstring
    expires_at: datetime
    basket_fingerprint: tuple[tuple[str, int], ...]
    policy_version: str  # a short hash of the mandate's hard_rules at issue time
    evidence_ref: str  # opaque pointer back to the EngineDecision that issued this
    revoked: bool = False

    def is_valid(self, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return not self.revoked and now <= self.expires_at

    def as_dict(self) -> dict:
        return {
            "authorization_id": self.authorization_id,
            "mandate_id": self.mandate_id,
            "merchant_id": self.merchant_id,
            "amount_ceiling_chf": str(self.amount_ceiling_chf),
            "currency": self.currency,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "basket_fingerprint": list(self.basket_fingerprint),
            "policy_version": self.policy_version,
            "evidence_ref": self.evidence_ref,
            "revoked": self.revoked,
        }


class ResolutionError(ValueError):
    """Raised when a human resolution cannot be applied as requested -- distinct
    from a plain `ValueError` so callers (api.py, live_worker.py) can map it to a
    specific HTTP status / log message rather than a generic 400/500."""


class AuthorityError(ValueError):
    """Raised when a PaymentAuthority cannot be issued, or is invalid at the point
    it is needed (expired, revoked, or the underlying decision was never allow)."""


@dataclass(frozen=True)
class _RecentAttempt:
    """A basket/merchant/amount fingerprint for duplicate detection.

    Deliberately does NOT store a copy of the decision: `find_similar_recent` looks
    the current decision up live via `RunState._decisions`, so a `review` that is
    later resolved to `block` is correctly excluded from then on -- a frozen
    snapshot here would silently go stale the moment a step_up is resolved.
    """

    authorization_id: str
    merchant_id: str
    basket_key: tuple[tuple[str, int], ...]
    billing_amount_chf: Decimal
    timestamp: datetime


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
    _authorities: dict[str, PaymentAuthority] = field(default_factory=dict)

    # --- idempotency: repeated delivery of the same authorization_id ---------------
    def get_stored_decision(self, authorization_id: str) -> StoredDecision | None:
        return self._decisions.get(authorization_id)

    def check_repeat_fingerprint(
        self, authorization_id: str, *, merchant_id: str, basket_key: tuple[tuple[str, int], ...], billing_amount_chf: Decimal
    ) -> bool:
        """True if a stored decision exists for `authorization_id` AND its
        merchant/basket/amount match what is being re-delivered now -- i.e. this is
        a genuine repeated delivery of the *same* purchase, safe to reconcile
        without re-evaluation. False if the facts differ: a same-ID-different-facts
        "authorization" must never be silently reconciled either as the old
        decision (which was made on different facts) or as a fresh one (which
        would mean submitting a second decision for an ID the platform already
        has one for) -- see `decision_engine.evaluate_authorization`."""
        existing = self._decisions.get(authorization_id)
        if existing is None:
            return True  # nothing to conflict with; not a repeat at all
        return (
            existing.merchant_id == merchant_id
            and existing.basket_key == basket_key
            and existing.billing_amount_chf == billing_amount_chf
        )

    def record_decision(
        self,
        authorization_id: str,
        decision: Decision,
        billing_amount_chf: Decimal,
        timestamp: datetime,
        *,
        merchant_id: str,
        basket_key: tuple[tuple[str, int], ...],
    ) -> StoredDecision:
        if authorization_id in self._decisions:
            return self._decisions[authorization_id]  # never overwrite; first outcome for an ID is final here
        counted = decision == "allow"
        if counted:
            self._approved_spend.append((timestamp, billing_amount_chf))
        stored = StoredDecision(
            authorization_id,
            decision,
            billing_amount_chf,
            timestamp,
            counted,
            merchant_id=merchant_id,
            basket_key=basket_key,
            was_reviewed=(decision == "review"),
        )
        self._decisions[authorization_id] = stored
        return stored

    def record_resolution(self, authorization_id: str, final_decision: Decision, resolved_at: datetime) -> StoredDecision:
        """Apply a human's answer to a previously-`review`d authorization. Bound to
        the specific authorization_id it resolves -- it can only change *that*
        authorization's outcome, never the standing mandate (see `mandate.py`).

        Takes no `billing_amount_chf`: the amount that matters is the one the
        customer was actually shown when asked to review, never a value a caller
        could pass in fresh -- see docs/SECOND_ADVERSARIAL_AUDIT.md, "human
        resolution scoped to the wrong facts". The spend-window contribution uses
        the ORIGINAL purchase's *simulated* timestamp (`existing.timestamp`), not
        `resolved_at` (a real-clock time), per technical_details.md: "Use simulated
        purchase time for spending windows, and the real clock for response
        deadlines" -- a step_up answered an hour late must not be attributed to a
        different window than the one it actually occurred in.
        """
        existing = self._decisions.get(authorization_id)
        if existing is None:
            raise ResolutionError(f"cannot resolve {authorization_id}: it was never sent to the customer for review")
        if not existing.was_reviewed:
            raise ResolutionError(f"cannot resolve {authorization_id}: it was decided automatically and was never put to the customer")
        if existing.decision != "review":
            # Already resolved once. Treat an identical re-submission (a retried
            # click, a retried API call) as an idempotent success; a DIFFERENT
            # answer than what was already recorded is a genuine conflict, not
            # something to silently ignore or silently overwrite.
            if existing.decision == final_decision:
                return existing
            raise ResolutionError(
                f"{authorization_id} was already resolved as {existing.decision!r}; "
                f"cannot now resolve it as {final_decision!r}"
            )
        if final_decision == "allow":
            self._approved_spend.append((existing.timestamp, existing.billing_amount_chf))
        stored = StoredDecision(
            authorization_id,
            final_decision,
            existing.billing_amount_chf,
            existing.timestamp,
            final_decision == "allow",
            merchant_id=existing.merchant_id,
            basket_key=existing.basket_key,
            was_reviewed=True,
            resolved_at=resolved_at,
        )
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
        `context.recent_authorizations` shape, for display/evidence purposes. Status
        reflects the CURRENT stored decision (so a resolved step_up shows as
        approved/declined, not stuck at "pending")."""
        status_map = {"allow": "approved", "block": "declined", "review": "pending"}
        out = []
        for prior in self._recent_attempts[-limit:]:
            current = self._decisions.get(prior.authorization_id)
            status = status_map[current.decision] if current is not None else "pending"
            out.append(
                {
                    "authorization_id": prior.authorization_id,
                    "timestamp": prior.timestamp.isoformat().replace("+00:00", "Z"),
                    "merchant_id": prior.merchant_id,
                    "billing_amount_chf": float(prior.billing_amount_chf),
                    "status": status,
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
            prior_decision = self._decisions.get(prior.authorization_id)
            if prior_decision is not None and prior_decision.decision == "block":
                # A declined attempt -- including one declined only *later*, via a
                # resolved step_up -- is not "an unwanted duplicate order" to worry
                # about. Looked up live rather than from a frozen snapshot, so a
                # review that is subsequently declined stops counting from that
                # point on (see `_RecentAttempt`'s docstring).
                continue
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
    ) -> None:
        self._recent_attempts.append(_RecentAttempt(authorization_id, merchant_id, basket_key, billing_amount_chf, timestamp))

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

    # --- verifiable payment authority (R&D Track A) ----------------------------------
    def issue_authority(
        self, authorization_id: str, *, mandate_id: str, policy_version: str, ttl: timedelta = DEFAULT_AUTHORITY_TTL, now: datetime | None = None
    ) -> PaymentAuthority:
        """Issue a `PaymentAuthority` as a byproduct of an ALLOW decision.

        Idempotent: re-issuing for the same authorization_id returns the SAME
        authority object already on file rather than minting a second one with a
        fresh (later) expiry -- an authority's validity window is fixed at the
        moment it is first granted, not extended by asking for it again.
        """
        existing = self._authorities.get(authorization_id)
        if existing is not None:
            return existing
        stored = self._decisions.get(authorization_id)
        if stored is None or stored.decision != "allow":
            raise AuthorityError(f"cannot issue a payment authority for {authorization_id}: it is not an approved (allow) decision")
        issued_at = now or datetime.now(timezone.utc)
        authority = PaymentAuthority(
            authorization_id=authorization_id,
            mandate_id=mandate_id,
            merchant_id=stored.merchant_id,
            amount_ceiling_chf=stored.billing_amount_chf,
            currency="CHF",
            issued_at=issued_at,
            expires_at=issued_at + ttl,
            basket_fingerprint=stored.basket_key,
            policy_version=policy_version,
            evidence_ref=f"decision:{authorization_id}",
        )
        self._authorities[authorization_id] = authority
        return authority

    def get_authority(self, authorization_id: str) -> PaymentAuthority | None:
        return self._authorities.get(authorization_id)

    def revoke_authority(self, authorization_id: str) -> PaymentAuthority | None:
        """Invalidate an already-issued authority before it is spent -- e.g. the
        customer revokes the mandate, or asks for one specific purchase to be
        cancelled, after it was approved but before it was charged. Does not
        touch the underlying `StoredDecision` (the decision itself is history);
        it only makes the authority to CHARGE that decision no longer valid.
        Idempotent and safe to call on an authorization with no issued authority."""
        existing = self._authorities.get(authorization_id)
        if existing is None:
            return None
        revoked = replace(existing, revoked=True)
        self._authorities[authorization_id] = revoked
        return revoked

    # --- crash-recovery snapshot -----------------------------------------------------
    # `RunState` otherwise lives only in process memory (see docs/ARCHITECTURE.md,
    # "State and concurrency"). That is fine while the worker runs continuously, but
    # a process crash mid-run would otherwise forget every prior decision, approved
    # spend, and duplicate-detection fingerprint -- risking both a duplicate
    # decision submission AND, more seriously, a rolling-window spending limit
    # being silently bypassed because the run "forgot" what it had already
    # approved. This is a deliberately small, single-file JSON snapshot -- not a
    # database -- written by `live_worker.py` after every decision, so the SAME
    # process restarting can resume correctly. It does NOT reconcile against the
    # platform's own authoritative state (see `live_worker.LiveWorker.reconcile_run`
    # for that best-effort, separate mechanism) -- see
    # docs/SECOND_ADVERSARIAL_AUDIT.md for the residual limitation this leaves.
    def to_snapshot(self) -> dict:
        return {
            "card_id": self.card_id,
            "last_device_id": self._last_device_id,
            "decisions": [
                {
                    "authorization_id": d.authorization_id,
                    "decision": d.decision,
                    "billing_amount_chf": str(d.billing_amount_chf),
                    "timestamp": d.timestamp.isoformat(),
                    "counted_in_spend": d.counted_in_spend,
                    "merchant_id": d.merchant_id,
                    "basket_key": list(d.basket_key),
                    "was_reviewed": d.was_reviewed,
                    "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
                    "reason_codes": list(d.reason_codes),
                }
                for d in self._decisions.values()
            ],
            "approved_spend": [[ts.isoformat(), str(amt)] for ts, amt in self._approved_spend],
            "recent_attempts": [
                {
                    "authorization_id": a.authorization_id,
                    "merchant_id": a.merchant_id,
                    "basket_key": list(a.basket_key),
                    "billing_amount_chf": str(a.billing_amount_chf),
                    "timestamp": a.timestamp.isoformat(),
                }
                for a in self._recent_attempts
            ],
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict, history: HistoryIndex) -> "RunState":
        state = cls(history=history, card_id=snapshot["card_id"])
        state._last_device_id = snapshot.get("last_device_id")
        for d in snapshot["decisions"]:
            state._decisions[d["authorization_id"]] = StoredDecision(
                authorization_id=d["authorization_id"],
                decision=d["decision"],
                billing_amount_chf=Decimal(d["billing_amount_chf"]),
                timestamp=datetime.fromisoformat(d["timestamp"]),
                counted_in_spend=d["counted_in_spend"],
                merchant_id=d["merchant_id"],
                basket_key=tuple(tuple(pair) for pair in d["basket_key"]),
                was_reviewed=d.get("was_reviewed", False),
                resolved_at=datetime.fromisoformat(d["resolved_at"]) if d.get("resolved_at") else None,
                reason_codes=tuple(d.get("reason_codes", ())),
            )
        state._approved_spend = [(datetime.fromisoformat(ts), Decimal(amt)) for ts, amt in snapshot["approved_spend"]]
        state._recent_attempts = [
            _RecentAttempt(
                authorization_id=a["authorization_id"],
                merchant_id=a["merchant_id"],
                basket_key=tuple(tuple(pair) for pair in a["basket_key"]),
                billing_amount_chf=Decimal(a["billing_amount_chf"]),
                timestamp=datetime.fromisoformat(a["timestamp"]),
            )
            for a in snapshot["recent_attempts"]
        ]
        return state

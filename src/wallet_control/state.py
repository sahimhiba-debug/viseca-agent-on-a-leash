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
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

Decision = Literal["allow", "review", "block"]

# One basket line as it is frozen into a purchase fingerprint:
#   (item_id, item_name, quantity, return_window_days, final_sale, stated_size)
# The last three are facts DERIVED from the merchant's untrusted `item_details`,
# never the raw text -- see `decision_engine._basket_key`, which is the only
# producer of this type, for why that distinction is load-bearing in both
# directions. Every element is JSON-native so `RunState.to_snapshot()` round-trips
# it without a custom encoder.
BasketLineKey = tuple[str, str, int, int | None, bool, str | None]
BasketKey = tuple[BasketLineKey, ...]

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
    basket_key: BasketKey
    was_reviewed: bool = False  # True iff this authorization was ever put to REVIEW
    resolved_at: datetime | None = None  # real-clock time of a human's answer, audit-only
    reason_codes: tuple[str, ...] = ()
    # --- execution lifecycle -------------------------------------------------------
    # These three used to live on a separate PaymentAuthority object in a second
    # dict. Two records describing one authorization is precisely the shape that
    # produced V2 (a decision with no authority), V3/V8/V10 (an authority lost on
    # restart) and V13/V14 (a lifecycle overwritten by a concurrent transition).
    # Holding them here makes "every approved decision has an execution lifecycle"
    # true by construction rather than by a fail-closed check.
    mandate_id: str | None = None          # provenance for the audit record
    policy_version: str | None = None      # provenance
    execution_issued_at: datetime | None = None
    execution_expires_at: datetime | None = None
    revoked: bool = False
    consumed_at: datetime | None = None


@dataclass(frozen=True)
class PaymentAuthority:
    """A read-only PROJECTION of one approved decision's execution lifecycle.

    This used to be an independently stored object in `RunState._authorities`, and
    it was the source of four vulnerabilities, all of the same shape: a second
    record describing the same authorization, free to drift from the first. It is
    now built on demand from the `StoredDecision` that already holds every fact it
    reports, so there is nothing to drift from.

    `issued_at` is RECORDED, not reconstructed. An earlier version of this merge
    derived it as `expires_at - DEFAULT_AUTHORITY_TTL`, which Audit 1 rejected: a
    derivation must rest on authoritative state, never on a program constant that a
    later edit could change under historical records.

    Every other field below except the lifecycle three is a copy that nothing read:
    a survey of the production source found `amount_ceiling_chf`,
    `basket_fingerprint`, `policy_version`, `currency`, `issued_at`, `evidence_ref`
    and `mandate_id` read ZERO times. They are kept only because the demo displays
    them, and they are now derived rather than stored.
    """

    authorization_id: str
    mandate_id: str
    merchant_id: str
    amount_ceiling_chf: Decimal
    currency: str
    issued_at: datetime
    expires_at: datetime
    basket_fingerprint: BasketKey
    policy_version: str
    evidence_ref: str
    revoked: bool = False
    consumed_at: datetime | None = None

    @classmethod
    def project(cls, stored: "StoredDecision") -> "PaymentAuthority | None":
        """Build the view, or None when this decision carries no execution
        lifecycle (i.e. it was never an approval)."""
        if stored.decision != "allow" or stored.execution_expires_at is None:
            return None
        return cls(
            authorization_id=stored.authorization_id,
            mandate_id=stored.mandate_id or "",
            merchant_id=stored.merchant_id,
            amount_ceiling_chf=stored.billing_amount_chf,
            currency="CHF",
            issued_at=stored.execution_issued_at,
            expires_at=stored.execution_expires_at,
            basket_fingerprint=stored.basket_key,
            policy_version=stored.policy_version or "",
            evidence_ref=f"decision:{stored.authorization_id}",
            revoked=stored.revoked,
            consumed_at=stored.consumed_at,
        )

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
    basket_key: BasketKey
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
    # When the customer revoked this run's mandate. This is RUN-LEVEL state, not a
    # per-record flag, and the distinction is the whole fix for F1.
    #
    # Revocation used to be only a sweep over existing records. A sweep cannot cover
    # a record that does not exist yet, so a purchase still WAITING for the customer
    # carried no lifecycle to revoke, and answering it afterwards minted a fresh,
    # unrevoked authority -- the money the customer had just tried to stop. Found by
    # an independent security audit and reproduced end-to-end through the HTTP API:
    # revoke -> resolve(allow) -> CHF 175 charged.
    #
    # Holding the fact at the scope the bound belongs to (the run) makes "nothing
    # may be authorised after revocation" true for records not yet written.
    _revoked_at: datetime | None = None
    # Guards the authority compare-and-set. Not serialized (to_snapshot lists its
    # keys explicitly) and excluded from equality -- it is machinery, not state.
    _consume_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # --- idempotency: repeated delivery of the same authorization_id ---------------
    def get_stored_decision(self, authorization_id: str) -> StoredDecision | None:
        return self._decisions.get(authorization_id)

    def approved_decisions(self) -> tuple[StoredDecision, ...]:
        """Read-only view of every decision that currently stands as approved.

        Includes step-ups a human later approved, because `record_resolution`
        rewrites the stored decision rather than keeping the answer somewhere
        else. Anything derived from this view therefore cannot miss a
        human-approved purchase, and is persisted for free -- decisions are in
        `to_snapshot`.
        """
        return tuple(d for d in self._decisions.values() if d.decision == "allow")

    def all_decisions(self) -> tuple[StoredDecision, ...]:
        """Read-only view of every recorded decision, whatever it was.

        Used by the audit projection. It is a VIEW, not a second record: callers get
        the same immutable `StoredDecision` objects the ledger holds, so a timeline
        built from this cannot disagree with the ledger it describes.
        """
        return tuple(self._decisions.values())

    def check_repeat_fingerprint(
        self, authorization_id: str, *, merchant_id: str, basket_key: BasketKey, billing_amount_chf: Decimal
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
        basket_key: BasketKey,
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
        # Under the SAME lock that guards the payment transition. Without it this is
        # a check-then-act: two concurrent answers to one step-up were both accepted,
        # last writer wins, and a purchase the customer DECLINED could end with a live
        # payment authority. Reproduced in 75/4000 uninstrumented trials by an
        # independent audit, which put it well: the file locked the money transition
        # and left the consent transition bare.
        with self._consume_lock:
            return self._record_resolution_locked(authorization_id, final_decision, resolved_at)

    def _record_resolution_locked(
        self, authorization_id: str, final_decision: Decision, resolved_at: datetime
    ) -> StoredDecision:
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
        basket_key: BasketKey,
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
            if abs(timestamp - prior.timestamp) > _DUPLICATE_WINDOW:
                continue
            # The amount deliberately does NOT have to match. Requiring it read
            # "similar" as "identical", and a compromised agent evaded the whole
            # check by moving the price one centime (deep-security finding V6).
            # Ordering the same basket from the same merchant minutes later is the
            # unwanted duplicate order whether or not the price moved -- but the
            # reviewer is shown the difference, because "the same thing at a
            # different price" is what they need to judge.
            if prior.billing_amount_chf == billing_amount_chf:
                money = f"and amount (CHF {billing_amount_chf})"
            else:
                money = f"at a different amount (CHF {prior.billing_amount_chf} before, CHF {billing_amount_chf} now)"
            return prior.authorization_id, (
                f"same merchant and basket as {prior.authorization_id} {money}, "
                f"{abs(timestamp - prior.timestamp)} apart"
            )
        return None

    def remember_attempt(
        self,
        *,
        authorization_id: str,
        merchant_id: str,
        basket_key: BasketKey,
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
        """Stamp an execution lifecycle onto an approved decision and return the
        projection of it.

        Idempotent: if the decision already carries a lifecycle, that one is
        returned unchanged. An authority's window is fixed when first granted and
        is never extended by asking again.
        """
        with self._consume_lock:
            if self._revoked_at is not None:
                raise AuthorityError(
                    f"cannot issue a payment authority for {authorization_id}: the customer revoked "
                    f"this mandate at {self._revoked_at.isoformat()}"
                )
            stored = self._decisions.get(authorization_id)
            if stored is None or stored.decision != "allow":
                raise AuthorityError(
                    f"cannot issue a payment authority for {authorization_id}: it is not an approved (allow) decision"
                )
            if stored.execution_expires_at is not None:
                return PaymentAuthority.project(stored)
            issued_at = now or datetime.now(timezone.utc)
            self._decisions[authorization_id] = replace(
                stored,
                mandate_id=mandate_id,
                policy_version=policy_version,
                execution_issued_at=issued_at,
                execution_expires_at=issued_at + ttl,
            )
            return PaymentAuthority.project(self._decisions[authorization_id])

    def get_authority(self, authorization_id: str) -> PaymentAuthority | None:
        """The projection, derived fresh each time. Never a stored second copy."""
        stored = self._decisions.get(authorization_id)
        return PaymentAuthority.project(stored) if stored is not None else None

    def revoke_authority(self, authorization_id: str) -> PaymentAuthority | None:
        """Invalidate an approved decision's execution lifecycle before it is spent.
        Does not touch the decision itself -- what the engine told the platform is
        history. Idempotent and safe on an authorization with no lifecycle."""
        with self._consume_lock:
            stored = self._decisions.get(authorization_id)
            if stored is None or stored.execution_expires_at is None:
                return None
            self._decisions[authorization_id] = replace(stored, revoked=True)
            return PaymentAuthority.project(self._decisions[authorization_id])

    def consume_authority(self, authorization_id: str, *, executed_at: datetime, now: datetime) -> PaymentAuthority:
        """Atomically validate and spend an authority: a compare-and-set, not a write.

        The validation lives HERE, at the state transition, rather than only in the
        caller. Splitting them is a check-then-act, and the window between the two
        is exactly as wide as whatever work the payment boundary does in between --
        for a real processor, an external call. Two vulnerabilities lived in that
        window (V13, V14):

          * a revocation that landed mid-charge was silently overwritten by the
            consume, so money moved on an authority the customer had already
            revoked; the result was an authority both revoked AND consumed;
          * two threads both passed the caller's `consumed_at is None` check and
            both consumed, executing one authorization twice.

        Neither was reachable when the window was a few bytecodes wide and the GIL
        closed it by luck. Both are trivially reachable once the boundary does real
        work, which is the whole point of a payment boundary.

        `now` is the TRUSTED clock reading supplied by the boundary and is what
        expiry is judged on. `executed_at` only timestamps the record, and may be a
        caller-supplied value -- it must never decide whether the authority is still
        valid (that was V4).

        The lock makes this atomic within one process. It does NOT make it atomic
        across processes: two workers restoring the same checkpoint hold separate
        `RunState` objects and separate locks, and each will consume once. Closing
        that needs a single shared store with an atomic compare-and-set; see
        docs/DISTRIBUTED_PAYMENT_BOUNDARY.md for the exact boundary and the minimum
        primitive it would take.
        """
        with self._consume_lock:
            existing = self._decisions.get(authorization_id)
            if existing is None or existing.execution_expires_at is None:
                raise AuthorityError(f"{authorization_id} has no payment authority to consume")
            if existing.consumed_at is not None:
                raise AuthorityError(
                    f"{authorization_id} was already executed at {existing.consumed_at.isoformat()}; "
                    "refusing a second execution"
                )
            if existing.revoked:
                raise AuthorityError(f"the payment authority for {authorization_id} has been revoked; refusing to consume")
            if now > existing.execution_expires_at:
                raise AuthorityError(
                    f"the payment authority for {authorization_id} expired at "
                    f"{existing.execution_expires_at.isoformat()}; refusing to consume an expired authority"
                )
            self._decisions[authorization_id] = replace(existing, consumed_at=executed_at)
            return PaymentAuthority.project(self._decisions[authorization_id])

    @property
    def is_revoked(self) -> bool:
        return self._revoked_at is not None

    def revoke_outstanding_authorities(self, *, now: datetime | None = None) -> tuple[str, ...]:
        """Revoke every still-valid authority in this run, returning the
        authorization_ids actually revoked. Called when the customer revokes the
        mandate: money that has been authorized but not yet spent must stop.

        It also records the revocation at RUN level, so that a purchase still waiting
        for the customer -- which has no lifecycle yet, and so nothing to sweep --
        cannot acquire one afterwards. Without that, the emergency brake missed
        exactly the purchase the customer had been asked about.

        This is about our own synthetic capability object, not about official
        decision semantics: technical_details.md leaves the effect of revocation
        on already-queued authorizations unspecified, and this code does not
        invent a guarantee there -- `StoredDecision` records are untouched, so
        what the engine already told the platform stays exactly as it was. What
        changes is only whether money that has NOT yet moved may still move. For
        a customer's emergency brake, fail-closed is the only defensible default.

        There is deliberately no "revoke only the authorities minted under an
        older policy version" variant: a run is bound to one mandate snapshot
        taken at run start (both `api.py` and `live_worker.py` build it once per
        run_id, per technical_details.md "An existing run keeps its original
        snapshot"), and authorities live inside one `RunState`, so a policy
        version cannot change underneath an outstanding authority. That variant
        would be an unreachable branch, and `policy_version` on the authority is
        therefore provenance -- what it was minted under -- not an enforced
        binding. See docs/FINAL_ARCHITECTURE_ATTACK.md for the full analysis.
        """
        with self._consume_lock:
            # Record the run-level fact FIRST: if anything below were to fail, a run
            # marked revoked that swept nothing is safe, while a run that swept
            # records but forgot it was revoked is the bug this fixes.
            self._revoked_at = now or datetime.now(timezone.utc)
            revoked: list[str] = []
            for authorization_id, stored in list(self._decisions.items()):
                if stored.execution_expires_at is None or stored.revoked:
                    continue
                self._decisions[authorization_id] = replace(stored, revoked=True)
                revoked.append(authorization_id)
            return tuple(revoked)

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
            "revoked_at": self._revoked_at.isoformat() if self._revoked_at else None,
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
                    # The execution lifecycle rides WITH the decision. It used to be
                    # a separate "authorities" array; one record cannot fall out of
                    # step with itself.
                    "mandate_id": d.mandate_id,
                    "policy_version": d.policy_version,
                    "execution_issued_at": d.execution_issued_at.isoformat() if d.execution_issued_at else None,
                    "execution_expires_at": d.execution_expires_at.isoformat() if d.execution_expires_at else None,
                    "revoked": d.revoked,
                    "consumed_at": d.consumed_at.isoformat() if d.consumed_at else None,
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
        revoked_at = snapshot.get("revoked_at")
        state._revoked_at = datetime.fromisoformat(revoked_at) if revoked_at else None
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
                mandate_id=d.get("mandate_id"),
                policy_version=d.get("policy_version"),
                execution_issued_at=datetime.fromisoformat(d["execution_issued_at"]) if d.get("execution_issued_at") else None,
                execution_expires_at=datetime.fromisoformat(d["execution_expires_at"]) if d.get("execution_expires_at") else None,
                revoked=d.get("revoked", False),
                consumed_at=datetime.fromisoformat(d["consumed_at"]) if d.get("consumed_at") else None,
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

"""The wallet policy / mandate: the customer's authoritative, executable permissions.

A mandate is the *only* source of spending authority in this system. It starts as a
draft, becomes active once the customer confirms it, and can only be tightened or
revoked afterwards -- never widened by anything the shopping agent or a merchant
says. That invariant is enforced here, in one place, so nothing downstream has to
re-derive it.

This mirrors the official API's mandate lifecycle (technical_details.md, step 5 and
step 8): `POST /v1/mandates` creates a draft, `.../confirm` activates it, `PATCH`
may only add hard rules and may only move `uncertainty_policy` from `approve`/`ask`
towards `decline`, and `DELETE` revokes it.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

_ALLOWED_OPERATORS = {"<", "<=", "=", "!=", ">", ">=", "in", "not_in"}
_ALLOWED_CURRENCIES = {"CHF", "EUR", "GBP", "USD", None}
_ALLOWED_SCOPES = {"purchase", "period", None}
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+\Z")  # \Z, not $: $ allows a trailing "\n" that \Z correctly rejects


class MandateStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"
    EXPIRED = "expired"


class UncertaintyPolicy(str, Enum):
    ASK = "ask"
    DECLINE = "decline"
    APPROVE = "approve"


# PATCH may only move uncertainty_policy towards the strict side (technical_details.md
# step 8: "You may change `uncertainty_policy` from `approve` or `ask` to `decline`.
# The documented PATCH rules do not allow changing `approve` to `ask`.").
_ALLOWED_UNCERTAINTY_TRANSITIONS: dict[UncertaintyPolicy, set[UncertaintyPolicy]] = {
    UncertaintyPolicy.APPROVE: {UncertaintyPolicy.DECLINE},
    UncertaintyPolicy.ASK: {UncertaintyPolicy.DECLINE},
    UncertaintyPolicy.DECLINE: set(),
}


class MandateError(ValueError):
    """Raised when an operation would violate the tighten-only mandate contract."""


@dataclass(frozen=True)
class HardRule:
    """One executable permission check, in the API's rule format.

    Frozen (immutable) so a rule handed out in a mandate snapshot can never be
    mutated in place by a caller holding a reference to it -- see the aliasing
    concern in the engineering review checklist.
    """

    field: str
    operator: str
    value: Any  # number | str | list[str]
    currency: str | None = None
    scope: str | None = None
    period_days: int | None = None

    def __post_init__(self) -> None:
        if not self.field:
            raise MandateError("hard_rule.field must be a nonempty string")
        if self.operator not in _ALLOWED_OPERATORS:
            raise MandateError(f"hard_rule.operator {self.operator!r} is not allowed")
        if isinstance(self.value, bool):
            raise MandateError("hard_rule.value must not be a boolean")
        if self.value is None:
            raise MandateError("hard_rule.value must not be null")
        if isinstance(self.value, list) and not all(isinstance(v, str) for v in self.value):
            raise MandateError("hard_rule.value list must contain only strings")
        if self.currency not in _ALLOWED_CURRENCIES:
            raise MandateError(f"hard_rule.currency {self.currency!r} is not allowed")
        if self.scope not in _ALLOWED_SCOPES:
            raise MandateError(f"hard_rule.scope {self.scope!r} is not allowed")
        if self.period_days is not None and self.period_days < 1:
            raise MandateError("hard_rule.period_days must be >= 1")

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"field": self.field, "operator": self.operator, "value": self.value}
        if self.currency is not None:
            d["currency"] = self.currency
        if self.scope is not None:
            d["scope"] = self.scope
        if self.period_days is not None:
            d["period_days"] = self.period_days
        return d

    def key(self) -> tuple:
        """Identity used for duplicate-detection when appending rules on PATCH."""
        value_key = tuple(self.value) if isinstance(self.value, list) else self.value
        return (self.field, self.operator, value_key, self.currency, self.scope, self.period_days)


@dataclass
class Mandate:
    """A customer's confirmed wallet policy.

    `hard_rules` is exposed only as a tuple copy (see `hard_rules` property) so a
    caller cannot reach in and mutate the list backing an active mandate --
    every change must go through `tighten_hard_rules` / `set_uncertainty_policy`,
    which enforce the tighten-only contract and are the only place that touches
    `_hard_rules`.
    """

    mandate_id: str
    instruction: str
    uncertainty_policy: UncertaintyPolicy
    guidance: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    status: MandateStatus = MandateStatus.DRAFT
    customer_id: str | None = None
    card_id: str | None = None
    profile_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _hard_rules: list[HardRule] = field(default_factory=list)

    @property
    def hard_rules(self) -> tuple[HardRule, ...]:
        return tuple(self._hard_rules)

    @classmethod
    def draft(
        cls,
        instruction: str,
        hard_rules: list[HardRule],
        uncertainty_policy: UncertaintyPolicy,
        guidance: list[str] | None = None,
        open_questions: list[str] | None = None,
    ) -> "Mandate":
        if not instruction.strip():
            raise MandateError("instruction must be nonempty")
        m = cls(
            mandate_id=f"draft_{uuid.uuid4().hex[:12]}",
            instruction=instruction,
            uncertainty_policy=uncertainty_policy,
            guidance=list(guidance or []),
            open_questions=list(open_questions or []),
            status=MandateStatus.DRAFT,
        )
        m._hard_rules = list(hard_rules)
        return m

    def confirm(self, *, confirmed: bool, customer_id: str, card_id: str, profile_id: str) -> "Mandate":
        """Activate a draft. Only the customer's explicit confirmation can do this."""
        if self.status != MandateStatus.DRAFT:
            raise MandateError(f"cannot confirm a mandate in status {self.status}")
        if not confirmed:
            raise MandateError("confirm() called without customer confirmation")
        for name, value in (("customer_id", customer_id), ("card_id", card_id), ("profile_id", profile_id)):
            if not _ID_RE.match(value):
                raise MandateError(f"{name}={value!r} is not a well-formed identifier")
        self.mandate_id = f"TM{uuid.uuid4().hex[:10].upper()}"
        self.status = MandateStatus.ACTIVE
        self.customer_id = customer_id
        self.card_id = card_id
        self.profile_id = profile_id
        return self

    def _require_active(self) -> None:
        if self.status != MandateStatus.ACTIVE:
            raise MandateError(f"mandate {self.mandate_id} is not active (status={self.status})")

    def tighten_hard_rules(self, new_rules: list[HardRule]) -> None:
        """Append hard rules. Existing rules are never removed or replaced.

        This is the load-bearing check for "adding a rule must not weaken a
        customer's existing restriction" (technical_details.md, Rule format) and
        for the broader invariant that a compromised agent or a later PATCH can
        never widen standing authority: the only mutation this method performs is
        `list.append`, and `HardRule` is frozen, so an existing entry cannot be
        edited in place either.
        """
        self._require_active()
        existing_keys = {r.key() for r in self._hard_rules}
        for rule in new_rules:
            if rule.key() in existing_keys:
                continue  # already present; PATCH must be idempotent, not additive-by-accident
            self._hard_rules.append(rule)

    def set_uncertainty_policy(self, new_policy: UncertaintyPolicy) -> None:
        self._require_active()
        if new_policy == self.uncertainty_policy:
            return
        allowed = _ALLOWED_UNCERTAINTY_TRANSITIONS.get(self.uncertainty_policy, set())
        if new_policy not in allowed:
            raise MandateError(
                f"cannot change uncertainty_policy from {self.uncertainty_policy.value!r} "
                f"to {new_policy.value!r}: PATCH may only move towards 'decline'"
            )
        self.uncertainty_policy = new_policy

    def replace_guidance(self, guidance: list[str] | None, open_questions: list[str] | None) -> None:
        """`guidance`/`open_questions` are explanatory text, not authority -- the API
        contract explicitly allows PATCH to replace them wholesale (unlike hard_rules).
        """
        self._require_active()
        if guidance is not None:
            self.guidance = list(guidance)
        if open_questions is not None:
            self.open_questions = list(open_questions)

    def revoke(self) -> None:
        if self.status in (MandateStatus.REVOKED, MandateStatus.EXPIRED):
            return
        self.status = MandateStatus.REVOKED

    def is_usable(self) -> bool:
        return self.status == MandateStatus.ACTIVE

    def as_dict(self) -> dict[str, Any]:
        return {
            "mandate_id": self.mandate_id,
            "status": self.status.value,
            "customer_id": self.customer_id,
            "card_id": self.card_id,
            "instruction": self.instruction,
            "hard_rules": [r.as_dict() for r in self._hard_rules],
            "uncertainty_policy": self.uncertainty_policy.value,
            "profile_id": self.profile_id,
            "guidance": list(self.guidance),
            "open_questions": list(self.open_questions),
            "created_at": self.created_at.isoformat(),
        }

    def snapshot(self) -> "MandateSnapshot":
        """An immutable copy bound to a run, per technical_details.md: "A run uses a
        snapshot: the copy of the mandate taken when that run starts... An existing
        run keeps its original snapshot" even if the live mandate is later PATCHed
        or revoked.
        """
        return MandateSnapshot(
            mandate_id=self.mandate_id,
            status=self.status,
            customer_id=self.customer_id,
            card_id=self.card_id,
            profile_id=self.profile_id,
            instruction=self.instruction,
            hard_rules=self.hard_rules,
            uncertainty_policy=self.uncertainty_policy,
        )


@dataclass(frozen=True)
class MandateSnapshot:
    """Immutable mandate state bound to one run. See `Mandate.snapshot`."""

    mandate_id: str
    status: MandateStatus
    customer_id: str | None
    card_id: str | None
    profile_id: str | None
    instruction: str
    hard_rules: tuple[HardRule, ...]
    uncertainty_policy: UncertaintyPolicy

    @classmethod
    def from_event_mandate(cls, mandate_block: dict[str, Any]) -> "MandateSnapshot":
        """Reconstruct a snapshot from a live event's embedded `mandate` object.

        The live worker learns `customer_id`/`card_id`/`profile_id` only once the
        platform assigns them at run start (technical_details.md: "A profile ID is
        a platform identifier for the context used in the run... assigned by the
        platform when the run starts, not submitted by the participant"), so rather
        than guess them, the worker builds its `MandateSnapshot` directly from the
        first event it receives for a run.
        """
        rules = tuple(
            HardRule(
                field=r["field"],
                operator=r["operator"],
                value=r["value"],
                currency=r.get("currency"),
                scope=r.get("scope"),
                period_days=r.get("period_days"),
            )
            for r in mandate_block["hard_rules"]
        )
        return cls(
            mandate_id=mandate_block["mandate_id"],
            status=MandateStatus(mandate_block["status"]),
            customer_id=mandate_block["customer_id"],
            card_id=mandate_block["card_id"],
            profile_id=mandate_block["profile_id"],
            instruction=mandate_block["instruction"],
            hard_rules=rules,
            uncertainty_policy=UncertaintyPolicy(mandate_block["uncertainty_policy"]),
        )

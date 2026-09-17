"""The authorization/payment boundary (Phase 9 in the review brief): a mock PSP
that enforces "approve is not payment" as actual code, not just a comment.

The decision engine's ALLOW is authorization *advice*. Nothing in `decision_engine.py`
moves money. This module is the only thing that can, and it refuses to unless all of
the following hold:

  * the authorization_id has a recorded final decision of "allow" (a `review` that
    is still pending is not "allow", and never gets treated as one here);
  * that authorization_id has not already been charged (one authorization, at most
    one execution, ever);
  * the requested charge amount does not exceed the amount that was actually
    approved;
  * the `charge_id` has not been used before (idempotent retries of the exact same
    charge request return the original record rather than charging twice).

This is deliberately a small in-memory mock -- the challenge is synthetic and asks
for a predictable prototype, not a real payment rail (challenge.md: "Everything is
synthetic: there are no real cards, customers, payments, or money.").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from .state import RunState


class PaymentError(Exception):
    """Raised whenever an execution attempt would cross the authorization boundary."""


@dataclass(frozen=True)
class ChargeRecord:
    charge_id: str
    authorization_id: str
    amount_chf: Decimal
    executed_at: datetime


class MockPSP:
    """A minimal payment executor bound to one `RunState` (one run's decisions)."""

    def __init__(self, state: RunState) -> None:
        self._state = state
        self._charges: dict[str, ChargeRecord] = {}
        self._charged_authorizations: set[str] = set()

    def charge(self, *, charge_id: str, authorization_id: str, amount_chf: Decimal, now: datetime | None = None) -> ChargeRecord:
        if charge_id in self._charges:
            return self._charges[charge_id]  # exact retry of the same charge request: return the original, don't re-execute

        stored = self._state.get_stored_decision(authorization_id)
        if stored is None:
            raise PaymentError(f"{authorization_id} has not been decided yet; nothing to charge against")
        if stored.decision != "allow":
            raise PaymentError(
                f"{authorization_id} is not approved (decision={stored.decision!r}); "
                "a pending step_up or a decline must never be executed as payment"
            )
        if authorization_id in self._charged_authorizations:
            raise PaymentError(f"{authorization_id} has already been charged once; refusing a second execution")
        if amount_chf > stored.billing_amount_chf:
            raise PaymentError(
                f"requested charge CHF {amount_chf} exceeds the approved amount CHF {stored.billing_amount_chf}"
            )

        record = ChargeRecord(charge_id, authorization_id, amount_chf, now or datetime.now(timezone.utc))
        self._charges[charge_id] = record
        self._charged_authorizations.add(authorization_id)
        return record

    def charge_for(self, charge_id: str, authorization_id: str) -> ChargeRecord | None:
        return self._charges.get(charge_id)

    def is_charged(self, authorization_id: str) -> bool:
        return authorization_id in self._charged_authorizations

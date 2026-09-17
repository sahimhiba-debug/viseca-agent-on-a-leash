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
  * the merchant being charged is the merchant the authorization was actually
    approved for;
  * the `charge_id` has not been used before for a DIFFERENT authorization_id or
    amount (idempotent retries of the exact same charge request return the
    original record rather than charging twice; reusing the id for a different
    request is a conflict, not a retry).

This is deliberately a small in-memory mock -- the challenge is synthetic and asks
for a predictable prototype, not a real payment rail (challenge.md: "Everything is
synthetic: there are no real cards, customers, payments, or money.").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from .state import PaymentAuthority, RunState


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

    def charge(
        self, *, charge_id: str, authorization_id: str, amount_chf: Decimal, merchant_id: str, now: datetime | None = None
    ) -> ChargeRecord:
        existing = self._charges.get(charge_id)
        if existing is not None:
            # A `charge_id` is an idempotency key for ONE specific request, not a
            # free-standing token: reusing it for a different authorization_id or a
            # different amount is a conflict, not a retry, and must never be
            # silently treated as "the same charge, already done" -- that would let
            # an attacker (or a bug) piggyback a second, different charge onto an
            # already-approved charge_id, or make a caller believe the wrong
            # authorization was charged.
            if existing.authorization_id != authorization_id or existing.amount_chf != amount_chf:
                raise PaymentError(
                    f"charge_id {charge_id!r} was already used for authorization_id={existing.authorization_id!r} "
                    f"amount=CHF {existing.amount_chf}; refusing to reuse it for authorization_id={authorization_id!r} "
                    f"amount=CHF {amount_chf}"
                )
            return existing  # exact retry of the same charge request: return the original, don't re-execute

        if amount_chf <= 0:
            raise PaymentError(f"charge amount must be positive, got CHF {amount_chf}")

        stored = self._state.get_stored_decision(authorization_id)
        if stored is None:
            raise PaymentError(f"{authorization_id} has not been decided yet; nothing to charge against")
        if stored.decision != "allow":
            raise PaymentError(
                f"{authorization_id} is not approved (decision={stored.decision!r}); "
                "a pending step_up or a decline must never be executed as payment"
            )
        if merchant_id != stored.merchant_id:
            raise PaymentError(
                f"{authorization_id} was approved for merchant {stored.merchant_id!r}, not {merchant_id!r}; refusing to charge"
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

    def charge_via_authority(
        self, *, charge_id: str, authority: PaymentAuthority, amount_chf: Decimal, now: datetime | None = None
    ) -> ChargeRecord:
        """R&D Track A: execute a charge against a `PaymentAuthority` as a single,
        self-contained object, rather than four independently-supplied parameters.

        Additive alongside `charge()` (not a replacement) so the existing,
        extensively tested `charge()` path is completely unchanged -- this method
        adds exactly two checks a bare `charge()` call cannot express (expiry and
        explicit revocation), then delegates everything else (merchant binding,
        amount ceiling, idempotency, one-execution-per-authorization) to `charge()`
        itself, so there is exactly one place those checks are implemented.
        """
        now = now or datetime.now(timezone.utc)
        if authority.revoked:
            raise PaymentError(f"the payment authority for {authority.authorization_id} has been revoked; refusing to charge")
        if now > authority.expires_at:
            raise PaymentError(
                f"the payment authority for {authority.authorization_id} expired at {authority.expires_at.isoformat()} "
                f"(now={now.isoformat()}); refusing to charge an expired authority"
            )
        if amount_chf > authority.amount_ceiling_chf:
            raise PaymentError(
                f"requested charge CHF {amount_chf} exceeds the authority's own ceiling CHF {authority.amount_ceiling_chf}"
            )
        return self.charge(charge_id=charge_id, authorization_id=authority.authorization_id, amount_chf=amount_chf, merchant_id=authority.merchant_id, now=now)

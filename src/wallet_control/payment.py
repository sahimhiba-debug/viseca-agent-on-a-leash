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

from collections.abc import Callable
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
    merchant_id: str = ""  # recorded so a reused charge_id can be compared on it


class MockPSP:
    """A minimal payment executor bound to one `RunState` (one run's decisions)."""

    def __init__(
        self,
        state: RunState,
        *,
        clock: Callable[[], datetime] | None = None,
        persist: Callable[[], None] | None = None,
    ) -> None:
        self._state = state
        # Called immediately after an authority is consumed and BEFORE the charge
        # record exists, so that "this authority has been spent" reaches durable
        # storage before money is treated as moved. Without it, single-use holds
        # only within this process: a crash restores the last checkpoint, which was
        # written after the DECISION and knows nothing about the charge. See
        # docs/FINAL_SECURITY_POSITION.md (V10).
        self._persist = persist
        self._charges: dict[str, ChargeRecord] = {}
        # The clock used for SECURITY decisions (authority expiry) belongs to the
        # payment boundary, not to whoever calls it. It was previously taken from
        # the caller's `now=` argument, which meant anyone asking for a charge also
        # got to say what time it was -- and could therefore charge an authority
        # ten years after it expired by claiming it was still issue time. Tests
        # inject a clock here, at construction, which is a trusted seam; `now=` on
        # the call itself only timestamps the resulting record.
        self._clock = clock or (lambda: datetime.now(timezone.utc))

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
            if (
                existing.authorization_id != authorization_id
                or existing.amount_chf != amount_chf
                or existing.merchant_id != merchant_id
            ):
                raise PaymentError(
                    f"charge_id {charge_id!r} was already used for authorization_id={existing.authorization_id!r} "
                    f"amount=CHF {existing.amount_chf} merchant={existing.merchant_id!r}; refusing to reuse it for "
                    f"authorization_id={authorization_id!r} amount=CHF {amount_chf} merchant={merchant_id!r}"
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
        if amount_chf > stored.billing_amount_chf:
            raise PaymentError(
                f"requested charge CHF {amount_chf} exceeds the approved amount CHF {stored.billing_amount_chf}"
            )

        # The PaymentAuthority is the authoritative record of whether execution is
        # still permitted, and it is checked HERE rather than only in
        # `charge_via_authority` -- otherwise it would be opt-in, and a caller
        # reaching for plain `charge()` would bypass expiry and the customer's
        # revocation. A revocation that only works if the caller chooses the polite
        # door is not a revocation.
        #
        # Every chargeable ALLOW mints an authority, so its absence means authority
        # state was lost or never properly established -- a reason to stop, not to
        # proceed. This replaces a fail-OPEN default ("no authority means no
        # constraint") that the previous pass introduced and asserted was safe; it
        # was not. It is what allowed a human-approved step-up (which minted no
        # authority) and a post-restart run (which restored none) to be charged
        # after the customer had revoked. See docs/DEEP_SECURITY_RESEARCH.md.
        authority = self._state.get_authority(authorization_id)
        if authority is None:
            raise PaymentError(
                f"{authorization_id} has no payment authority on record; refusing to charge. "
                "An approved purchase always mints one, so this means authority state was lost."
            )
        if authority.consumed_at is not None:
            raise PaymentError(
                f"{authorization_id} was already executed at {authority.consumed_at.isoformat()}; "
                "refusing a second execution"
            )
        if authority.revoked:
            raise PaymentError(f"the payment authority for {authorization_id} has been revoked; refusing to charge")
        if self._clock() > authority.expires_at:
            raise PaymentError(
                f"the payment authority for {authorization_id} expired at "
                f"{authority.expires_at.isoformat()}; refusing to charge an expired authority"
            )

        # Order is the whole point. Consume the authority, make that durable, and
        # only then create the charge record.
        #
        # If the process dies between consuming and persisting, or between
        # persisting and returning, the authority is dead and no money moved: a
        # legitimate purchase fails to complete, which is the safe direction for a
        # wallet. The opposite order -- money first, consumption second -- is what
        # let the same authorization execute twice across a crash (V10), because
        # nothing writes a checkpoint after a charge.
        executed_at = now or self._clock()
        self._state.consume_authority(authorization_id, executed_at)
        if self._persist is not None:
            self._persist()
        record = ChargeRecord(charge_id, authorization_id, amount_chf, executed_at, merchant_id)
        self._charges[charge_id] = record
        return record

    def charge_record(self, charge_id: str) -> ChargeRecord | None:
        """The record for an idempotency key, if this executor created one."""
        return self._charges.get(charge_id)

    def is_charged(self, authorization_id: str) -> bool:
        authority = self._state.get_authority(authorization_id)
        return authority is not None and authority.consumed_at is not None

    def charge_via_authority(
        self, *, charge_id: str, authority: PaymentAuthority, amount_chf: Decimal, now: datetime | None = None
    ) -> ChargeRecord:
        """Charge against a `PaymentAuthority` object instead of four separate
        parameters. **Pure delegation, and nothing more.**

        It carries no check of its own, deliberately. It used to verify the ceiling
        on the PASSED authority, on the theory that an attenuated grant could be
        narrower than the approved amount -- but `issue_authority` always sets
        `amount_ceiling_chf` to exactly the approved amount and nothing in this
        codebase attenuates, so that check was provably identical to the one
        `charge()` already performs. It was removed rather than kept "just in case":
        a redundant check inside a wrapper is how a wrapper starts looking like a
        security layer.

        Everything real happens in `charge()`, against live run state rather than
        against this argument -- so handing this method a stale copy captured before
        a revocation does not resurrect it, and reaching for `charge()` directly
        bypasses nothing.
        """
        return self.charge(charge_id=charge_id, authorization_id=authority.authorization_id, amount_chf=amount_chf, merchant_id=authority.merchant_id, now=now)

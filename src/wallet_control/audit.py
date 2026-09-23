"""The audit timeline: a PROJECTION of authoritative records, never a second ledger.

Nothing here is written to, persisted, or consulted by any decision. Every line is
recomputed from the mandate snapshot and the decision ledger on each call, which is
the whole point -- a presentation ledger that could drift from the record it
describes is exactly the defect class this project found six times.

Consequence, stated honestly: the timeline can only show what the authoritative
records actually contain. Where the ledger keeps no timestamp (a revocation, for
example, records THAT an authority died, not the wall-clock instant), the timeline
says so instead of inventing one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .mandate import MandateSnapshot
from .state import RunState


@dataclass(frozen=True)
class AuditEntry:
    timestamp: str | None       # None where the record genuinely carries no time
    actor: str                  # "customer" | "agent" | "wallet" | "merchant"
    event: str
    authorization_id: str | None
    detail: str
    decision: str | None = None
    clock: str | None = None    # "simulated" | "real" -- see below

    # Two clocks genuinely coexist here, and collapsing them would be a lie.
    # `technical_details.md`: "Use simulated purchase time for spending windows, and
    # the real clock for response deadlines." So a purchase is stamped in simulated
    # time and a payment authority's validity in real time. Rendering them in one
    # column without saying which is which would suggest an ordering that does not
    # exist, so every entry carries its clock.

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp, "actor": self.actor, "event": self.event,
            "authorization_id": self.authorization_id, "detail": self.detail,
            "decision": self.decision, "clock": self.clock,
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def audit_timeline(mandate: MandateSnapshot, state: RunState,
                   *, confirmed_at: datetime | None = None) -> list[AuditEntry]:
    """Derive the timeline from the mandate and the decision ledger.

    Ordered by the SIMULATED purchase time the platform supplied, which is the same
    clock every spending window uses -- not by the wall clock of this process, which
    would reorder a replayed run.
    """
    entries: list[AuditEntry] = [
        AuditEntry(
            timestamp=_iso(confirmed_at), actor="customer", event="Mandate confirmed",
            authorization_id=None, clock="real" if confirmed_at else None,
            detail=f'"{mandate.instruction}" -> {len(mandate.hard_rules)} executable checks, '
                   f"uncertainty policy: {mandate.uncertainty_policy.value}",
        )
    ]

    for stored in sorted(state.all_decisions(), key=lambda d: (d.timestamp, d.authorization_id)):
        when = _iso(stored.timestamp)
        basket = ", ".join(f"{line[2]} x {line[1]}" for line in stored.basket_key) or "no itemised basket"
        entries.append(AuditEntry(
            timestamp=when, actor="agent", event="Purchase proposed",
            authorization_id=stored.authorization_id,
            detail=f"CHF {stored.billing_amount_chf} at {stored.merchant_id} -- {basket}",
            clock="simulated",
        ))
        # The WALLET's own answer, which is not always the final outcome. For a
        # purchase the wallet stepped up and a human then approved, this used to
        # record "allow" at the original timestamp -- so an auditor could not tell
        # that the wallet had ever hesitated, and the customer's override vanished
        # into a decision attributed to policy. That is the single most
        # audit-relevant distinction in a run, and it was the one fact erased.
        wallet_answer = "review" if stored.was_reviewed else stored.decision
        entries.append(AuditEntry(
            timestamp=when, actor="wallet", event="Wallet decision",
            authorization_id=stored.authorization_id,
            decision=wallet_answer,
            detail=(", ".join(stored.reason_codes)
                    or ("asked the customer" if wallet_answer == "review" else wallet_answer)),
            clock="simulated",
        ))
        if stored.was_reviewed and stored.resolved_at is not None:
            entries.append(AuditEntry(
                timestamp=_iso(stored.resolved_at), actor="customer",
                event="Customer resolved a step-up",
                authorization_id=stored.authorization_id, decision=stored.decision,
                detail=(f"the customer answered {stored.decision!r}; this OVERRIDES the "
                        f"wallet's request for confirmation, it does not replace the policy"),
                clock="real",
            ))
        elif stored.was_reviewed:
            # THE ROW ABOVE USED TO APPEAR WHENEVER THE WALLET ASKED, answered or not.
            #
            # A purchase still waiting produced "Customer resolved a step-up -- the
            # customer answered 'review'", with no timestamp, for a question nobody
            # had answered. An audit trail that attributes an action to the customer
            # which the customer did not take is not a weak audit trail; it is a
            # false one, and this is the record of who authorised what.
            #
            # Waiting is a real state and it gets its own row, attributed to nobody.
            entries.append(AuditEntry(
                timestamp=None, actor="wallet", event="Waiting for the customer",
                authorization_id=stored.authorization_id, decision="review",
                detail="the wallet asked and no answer has been recorded; nothing has "
                       "been authorised and no payment authority exists",
                clock=None,
            ))
        if stored.execution_issued_at is not None:
            entries.append(AuditEntry(
                timestamp=_iso(stored.execution_issued_at), actor="wallet",
                event="Payment authority issued",
                authorization_id=stored.authorization_id,
                detail=f"single-use, expires {_iso(stored.execution_expires_at)}, "
                       f"bound to {stored.merchant_id} and CHF {stored.billing_amount_chf}",
                clock="real",
            ))
        if stored.revoked:
            # THE INSTANT IS KNOWN AFTER ALL. This carried `timestamp=None` and said
            # so -- "the ledger records the fact, not the instant" -- because the
            # per-authority flag is a boolean. But revocation is a RUN-LEVEL event
            # (that is the whole fix for F1), every authority in one sweep shares its
            # moment, and `RunState` records it. An absence that can be filled from
            # the state that caused it is the pattern `docs/ABSENCE.md` is about, and
            # the untimed rows here were all CUSTOMER actions -- the ones an audit
            # trail can least afford to leave unstamped.
            revoked_at = getattr(state, "_revoked_at", None)
            entries.append(AuditEntry(
                timestamp=_iso(revoked_at), actor="customer",
                event="Payment authority revoked",
                authorization_id=stored.authorization_id,
                clock="real" if revoked_at else None,
                detail=("revoked before the money moved" if revoked_at else
                        "revoked before the money moved; this run carries no revocation "
                        "instant, so the fact is recorded without one"),
            ))
        if stored.consumed_at is not None:
            entries.append(AuditEntry(
                timestamp=_iso(stored.consumed_at), actor="wallet",
                event="Payment executed",
                authorization_id=stored.authorization_id,
                detail=f"CHF {stored.billing_amount_chf} charged once at {stored.merchant_id}",
                clock="real",
            ))

    return entries


# --- economic disclosure, with provenance on every number -------------------------


def delegation_summary(mandate: MandateSnapshot, state: RunState,
                       account_limits: dict[str, str] | None = None) -> dict[str, Any]:
    """What the customer has delegated, in their own unit, with the source of every
    figure and an explicit `enforced` flag.

    The `enforced` flag is the load-bearing field. The account's monthly limit is
    real, sits in the official data, and this wallet does NOT enforce it -- there is
    no account-scoped counter in the official API. Showing it without that flag would
    turn contextual data into an implied guarantee.
    """
    per_purchase = next(
        (r for r in mandate.hard_rules
         if r.field == "authorization.billing_amount_chf" and r.scope == "purchase"), None)
    period = next((r for r in mandate.hard_rules if r.scope == "period"), None)

    lines: list[dict[str, Any]] = []
    if per_purchase is not None:
        lines.append({
            "label": "Maximum per purchase",
            "value": f"CHF {float(per_purchase.value):,.0f}",
            "source": "your instruction, compiled into a rule",
            "enforced": True,
            "note": "Checked on every purchase before it is approved.",
        })
    if period is not None:
        from .money import annual_exposure

        _exact, annual = annual_exposure(period.value, period.period_days or 1)
        lines.append({
            "label": f"Maximum per rolling {period.period_days} days",
            "value": f"CHF {float(period.value):,.0f}",
            "source": "your instruction, compiled into a rule",
            "enforced": True,
            "note": f"This paces spending; it does not cap the total. The window re-opens, "
                    f"so at this rate the delegation is worth about "
                    f"CHF {annual:,.0f} a year.",
        })
    if account_limits is not None:
        lines.append({
            "label": "Account monthly limit",
            "value": f"CHF {float(account_limits['monthly_limit_chf']):,.0f}",
            "source": "platform account data (accounts.csv)",
            "enforced": False,
            "note": "Context only. This wallet does not enforce it: the official API "
                    "exposes no account-scoped spend counter. Shown so you know it exists.",
        })

    approved = state.approved_decisions()
    return {
        "lines": lines,
        "approved_count": len(approved),
        "approved_total_chf": str(sum((d.billing_amount_chf for d in approved), start=type(
            approved[0].billing_amount_chf)(0))) if approved else "0",
        "unbounded_dimensions": [
            d for d in (
                "total amount -- the rule format cannot express a total",
                "end date -- the rule format cannot express one",
                None if period is not None else "rate of spend -- no rolling window was set",
            ) if d
        ],
    }

"""The deterministic wallet-control decision engine.

This is where "the agent proposes, the control layer decides" is actually
enforced. Given one authorization event, the confirmed mandate snapshot bound to
this run, and the run's accumulated state, it returns exactly one of ALLOW /
REVIEW / BLOCK, with the evidence and rule outcomes that produced it.

No language model sits in this path. Every input here is either a platform-
supplied structured field, a customer-authored hard rule, or a signal this
engine derived itself from trustworthy history/state -- never merchant-supplied
text (see `facts.py` for where that boundary is actually drawn).

Decision priority (matches the three-way distinction technical_details.md and
challenge.md ask for):

  1. Any hard rule clearly FAILS  -> BLOCK. A clear violation is never softened
     by an uncertain fact elsewhere.
  2. No failure, but something is UNKNOWN -> apply the mandate's own
     `uncertainty_policy` (ask/decline/approve). This is the customer's explicit
     choice about how to handle insufficient information, not the engine's.
  3. Every hard rule PASSES -> ALLOW.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from .facts import PurchaseFacts, build_purchase_facts
from .intervention import InterventionKind, classify_intervention
from .mandate import HardRule, MandateSnapshot, UncertaintyPolicy
from .money import to_chf, to_decimal
from .rules import RuleContext, RuleEvaluation, evaluate_rule
from .state import RunState
from .viseca_mapping import Decision

_DUPLICATE_RULE = HardRule(field="order.duplicate_suspected", operator="=", value="false")
_NO_RULES_RULE = HardRule(field="mandate.has_no_rules", operator="=", value="false")
_AMOUNT_INTEGRITY_RULE = HardRule(field="authorization.amount_integrity", operator="=", value="true")
_AMOUNT_INTEGRITY_TOLERANCE_CHF = Decimal("0.02")  # allows for independent double-rounding, nothing more


@dataclass(frozen=True)
class EngineDecision:
    authorization_id: str
    decision: Decision
    reason_codes: tuple[str, ...]
    customer_message: str
    evidence: tuple[str, ...]
    rule_evaluations: tuple[RuleEvaluation, ...]
    intervention: InterventionKind
    facts: PurchaseFacts | None
    idempotent_replay: bool = False
    # True if this authorization_id was re-delivered with DIFFERENT purchase facts
    # (merchant/basket/amount) than the first time. The returned `decision` is the
    # ORIGINAL stored one (never re-evaluated from the mutated facts, and never
    # re-submitted -- see `evaluate_authorization`); this flag tells the caller the
    # event is suspect and should be investigated, not treated as routine.
    authorization_id_conflict: bool = False


_TERMINAL_INTERVENTION: dict[Decision, InterventionKind] = {"allow": "allow", "block": "never", "review": "ask_this_time"}


def _basket_key(items: list[dict[str, Any]]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((line["item_id"], line["quantity"]) for line in items))


def _requested_categories(mandate: MandateSnapshot) -> frozenset[str] | None:
    for rule in mandate.hard_rules:
        if rule.field == "item.category" and rule.operator == "in":
            return frozenset(rule.value)
    return None


def _projected_period_spend(mandate: MandateSnapshot, state: RunState, as_of: datetime, this_amount: Decimal) -> dict[int, Decimal]:
    projected: dict[int, Decimal] = {}
    for rule in mandate.hard_rules:
        if rule.field == "authorization.billing_amount_chf" and rule.scope == "period" and rule.period_days:
            prior = state.rolling_spend_chf(as_of, rule.period_days)
            projected[rule.period_days] = prior + this_amount
    return projected


def _decide(evaluations: list[RuleEvaluation], uncertainty_policy: UncertaintyPolicy) -> tuple[Decision, tuple[str, ...]]:
    failures = [e for e in evaluations if e.outcome == "fail"]
    if failures:
        return "block", tuple(f"hard_rule_failed:{e.rule.field}" for e in failures)

    unknowns = [e for e in evaluations if e.outcome == "unknown"]
    if unknowns:
        reason_codes = tuple(f"uncertain:{e.rule.field}" for e in unknowns)
        if uncertainty_policy == UncertaintyPolicy.DECLINE:
            return "block", reason_codes
        if uncertainty_policy == UncertaintyPolicy.APPROVE:
            return "allow", reason_codes
        return "review", reason_codes

    return "allow", ("all_hard_rules_satisfied",)


def _customer_message(decision: Decision, evaluations: list[RuleEvaluation], facts: PurchaseFacts) -> str:
    if decision == "allow":
        return f"Approved: CHF {facts.billing_amount_chf} at {facts.merchant_name} matches your wallet policy."
    problems = [e for e in evaluations if e.outcome in ("fail", "unknown")]
    detail = "; ".join(f"{e.rule.field} ({e.outcome}): {e.detail}" for e in problems) or "no specific rule detail"
    verb = "Declined" if decision == "block" else "Needs your confirmation"
    return f"{verb}: CHF {facts.billing_amount_chf} at {facts.merchant_name} -- {detail}"


def evaluate_authorization(event: dict[str, Any], mandate: MandateSnapshot, state: RunState) -> EngineDecision:
    """Evaluate one `authorization.request` event against `mandate` using `state`.

    Idempotent: calling this twice with the same `authorization_id` returns the
    original recorded decision the second time, without re-evaluating rules or
    double-counting spend (technical_details.md step 6 and step 8) -- PROVIDED the
    re-delivered event describes the same purchase. If a repeated `authorization_id`
    shows a different merchant, basket, or amount than the first delivery, that is
    not a legitimate retry; see the `authorization_id_conflict` branch below.
    """
    auth = event["authorization"]
    authorization_id = auth["authorization_id"]
    merchant_id = auth["merchant"]["merchant_id"]
    basket_key = _basket_key(auth["items"])
    billing_amount_chf = to_decimal(auth["billing_amount_chf"])

    stored = state.get_stored_decision(authorization_id)
    if stored is not None:
        if not state.check_repeat_fingerprint(
            authorization_id, merchant_id=merchant_id, basket_key=basket_key, billing_amount_chf=billing_amount_chf
        ):
            # Same authorization_id, different purchase. Neither trust the old
            # decision (it was made on different facts) nor silently re-evaluate
            # and re-submit a new one (the platform already has a decision for this
            # ID). Fail closed and flag it loudly; the ORIGINAL stored decision is
            # left untouched, so the payment boundary still enforces the amount
            # that was actually approved, not whatever this mutated event claims.
            return EngineDecision(
                authorization_id=authorization_id,
                decision="block",
                reason_codes=("authorization_id_conflict",),
                customer_message=(
                    "This purchase could not be verified: the same authorization was received twice "
                    "with different details. The original decision was left unchanged."
                ),
                evidence=(
                    f"original: merchant={stored.merchant_id} amount={stored.billing_amount_chf} basket={stored.basket_key}",
                    f"received: merchant={merchant_id} amount={billing_amount_chf} basket={basket_key}",
                ),
                rule_evaluations=(),
                intervention=_TERMINAL_INTERVENTION["block"],
                facts=None,
                idempotent_replay=False,
                authorization_id_conflict=True,
            )
        return EngineDecision(
            authorization_id=authorization_id,
            decision=stored.decision,
            reason_codes=("repeated_delivery",),
            customer_message="This purchase was already decided; returning the recorded result unchanged.",
            evidence=(f"original decision recorded at {stored.timestamp.isoformat()} for CHF {stored.billing_amount_chf}",),
            rule_evaluations=(),
            intervention=_TERMINAL_INTERVENTION[stored.decision],
            facts=None,
            idempotent_replay=True,
        )

    card_id = auth["card_id"]
    device_id = auth["customer_device_id"]
    timestamp = datetime.fromisoformat(auth["timestamp"].replace("Z", "+00:00"))

    merchant_familiar = state.history.is_familiar(card_id, merchant_id)
    session_risk, session_reasons = state.session_signals(device_id, auth["recent_attempt_count_10m"], merchant_familiar)
    duplicate = state.find_similar_recent(
        authorization_id=authorization_id,
        merchant_id=merchant_id,
        basket_key=basket_key,
        billing_amount_chf=billing_amount_chf,
        timestamp=timestamp,
    )
    duplicate_of, duplicate_reason = duplicate if duplicate else (None, None)

    facts = build_purchase_facts(
        event,
        merchant_familiar=merchant_familiar,
        session_integrity_risk=session_risk,
        session_integrity_reasons=session_reasons,
        duplicate_of=duplicate_of,
        duplicate_reason=duplicate_reason,
    )

    ctx = RuleContext(
        requested_item_categories=_requested_categories(mandate),
        projected_period_spend_chf=_projected_period_spend(mandate, state, facts.timestamp, facts.billing_amount_chf),
    )
    evaluations = [evaluate_rule(rule, facts, ctx) for rule in mandate.hard_rules]

    # Always-on safety checks, independent of what the customer's mandate says --
    # these are control-layer integrity concerns, not policy the customer opted into.
    expected_chf = to_chf(to_decimal(auth["amount"]), auth["currency"])
    if abs(expected_chf - billing_amount_chf) > _AMOUNT_INTEGRITY_TOLERANCE_CHF:
        evaluations.append(
            RuleEvaluation(
                rule=_AMOUNT_INTEGRITY_RULE,
                outcome="fail",
                detail=f"billing_amount_chf={billing_amount_chf} does not match amount*fx_rate={expected_chf}",
            )
        )
    if duplicate_of is not None:
        evaluations.append(RuleEvaluation(rule=_DUPLICATE_RULE, outcome="unknown", detail=duplicate_reason or ""))
    if not mandate.hard_rules:
        # A confirmed mandate with zero executable rules has nothing to check a
        # purchase against. Treating that as "everything passes" would make an
        # empty or unparseable customer instruction into unlimited spending
        # authority -- exactly the "blank cheque" the challenge exists to prevent.
        # Route it through uncertainty_policy like any other missing information
        # instead (ASK by default: every purchase needs the customer; DECLINE:
        # nothing is spent; APPROVE: only if the customer explicitly, visibly chose
        # that -- see the compiler's own open_question for this exact condition).
        evaluations.append(
            RuleEvaluation(rule=_NO_RULES_RULE, outcome="unknown", detail="this mandate has no spending controls to check against")
        )

    decision, reason_codes = _decide(evaluations, mandate.uncertainty_policy)

    state.remember_attempt(
        authorization_id=authorization_id,
        merchant_id=merchant_id,
        basket_key=basket_key,
        billing_amount_chf=billing_amount_chf,
        timestamp=timestamp,
    )
    state.record_decision(
        authorization_id, decision, facts.billing_amount_chf, facts.timestamp, merchant_id=merchant_id, basket_key=basket_key
    )

    evidence = tuple(f"{e.rule.field} [{e.outcome}]: {e.detail}" for e in evaluations)
    return EngineDecision(
        authorization_id=authorization_id,
        decision=decision,
        reason_codes=reason_codes,
        customer_message=_customer_message(decision, evaluations, facts),
        evidence=evidence,
        rule_evaluations=tuple(evaluations),
        intervention=classify_intervention(decision, tuple(evaluations)),
        facts=facts,
        idempotent_replay=False,
    )


def resolve_authorization(authorization_id: str, human_decision: Decision, state: RunState, *, resolved_at: datetime) -> EngineDecision:
    """Apply a real customer's answer to a `review`ed authorization.

    Scoped to exactly this authorization_id -- see `state.RunState.record_resolution`
    -- and never touches the mandate. "A yes is this authorization. It is not a new
    wallet." Deliberately takes no amount: the amount that matters is whatever the
    customer was actually shown when the purchase was flagged for review, sourced
    from `state`'s own record, never from a value the caller could supply.
    """
    if human_decision == "review":
        raise ValueError("a human resolution must be 'allow' or 'block', not 'review'")
    stored = state.record_resolution(authorization_id, human_decision, resolved_at)
    return EngineDecision(
        authorization_id=authorization_id,
        decision=stored.decision,
        reason_codes=("customer_resolution",),
        customer_message="The customer's answer has been recorded for this purchase only.",
        evidence=(f"resolved by the customer at {resolved_at.isoformat()}",),
        rule_evaluations=(),
        intervention=_TERMINAL_INTERVENTION[stored.decision],
        facts=None,
        idempotent_replay=False,
    )

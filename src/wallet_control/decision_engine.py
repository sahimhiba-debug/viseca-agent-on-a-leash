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

from .drift import AuthorizationDrift, compute_drift
from .facts import (
    PurchaseFacts,
    build_purchase_facts,
    extract_return_window_days,
    extract_stated_size,
    mentions_final_sale,
)
from .intervention import InterventionKind, classify_intervention
from .mandate import HardRule, MandateSnapshot, MandateStatus, UncertaintyPolicy, mandate_policy_version
from .money import to_chf, to_decimal
from .rules import RuleContext, RuleEvaluation, evaluate_rule
from .state import BasketKey, PaymentAuthority, RunState
from .viseca_mapping import Decision

_DUPLICATE_RULE = HardRule(field="order.duplicate_suspected", operator="=", value="false")
_NO_RULES_RULE = HardRule(field="mandate.has_no_rules", operator="=", value="false")
_AMOUNT_INTEGRITY_RULE = HardRule(field="authorization.amount_integrity", operator="=", value="true")
_AMOUNT_INTEGRITY_TOLERANCE_CHF = Decimal("0.02")  # allows for independent double-rounding, nothing more

_AUTHORITY_STATUS_RULE = HardRule(field="authorization.authority_status", operator="=", value="active")
_CARD_STATUS_RULE = HardRule(field="authorization.card_status_at_attempt", operator="=", value="active")
_CARD_BINDING_RULE = HardRule(field="authorization.card_id_binding", operator="=", value="true")
_MANDATE_BINDING_RULE = HardRule(field="authorization.mandate_id_binding", operator="=", value="true")
_MANDATE_STATUS_RULE = HardRule(field="mandate.mandate_status", operator="=", value="active")

# The exact enums from data/official/schemas/authorization_event.schema.json. A
# value outside these sets is not assumed benign -- it is treated as unknown.
_KNOWN_DEAD_AUTHORITY_STATUSES = frozenset({"revoked", "expired"})
_KNOWN_DEAD_CARD_STATUSES = frozenset({"blocked"})


def _platform_status_evaluations(auth: dict[str, Any]) -> list[RuleEvaluation]:
    """Evaluate the platform's authority/card status fields (see the call site for
    why these are hard failures rather than uncertainty when recognised)."""
    out: list[RuleEvaluation] = []
    for raw, rule, dead, label in (
        (auth.get("authority_status"), _AUTHORITY_STATUS_RULE, _KNOWN_DEAD_AUTHORITY_STATUSES, "authority_status"),
        (auth.get("card_status_at_attempt"), _CARD_STATUS_RULE, _KNOWN_DEAD_CARD_STATUSES, "card_status_at_attempt"),
    ):
        if raw == "active":
            out.append(RuleEvaluation(rule=rule, outcome="pass", detail=f"{label}=active", source="safety"))
        elif raw in dead:
            out.append(
                RuleEvaluation(
                    rule=rule,
                    outcome="fail",
                    detail=f"the platform reports {label}={raw!r}; this purchase is not authorized to proceed",
                    source="safety",
                )
            )
        else:
            out.append(
                RuleEvaluation(
                    rule=rule,
                    outcome="unknown",
                    detail=f"{label}={raw!r} is not a status this engine version recognizes",
                    source="safety",
                )
            )
    return out


def _run_binding_failures(auth: dict[str, Any], mandate: MandateSnapshot, state: RunState) -> list[RuleEvaluation]:
    """Whether this event belongs to the run evaluating it.

    `card_id` is what the merchant-familiarity lookup is keyed on, so an event
    carrying a different card's identity would borrow that card's purchase history
    and could make an unfamiliar merchant look familiar. `mandate_id` decides whose
    rules are being applied. Both were previously taken from the event and never
    checked, which let the event answer "whose authority is this?" itself.

    Compared exactly: a case variant, a padded value, or one carrying an invisible
    character is a different identity, not a near-enough one.
    """
    failures: list[RuleEvaluation] = []

    # Is the mandate behind this purchase still in force at all? `mandate.status`
    # is a required field of the official schema with enum
    # ["active","superseded","revoked","expired"] -- it is the platform reporting
    # the result of the customer's DELETE /v1/mandates, and the engine did not read
    # it. A revoked mandate produced ALLOW, minted an authority and charged.
    #
    # This is the twin of the authority_status hole: that field answers "is this
    # authorization still authorized?", this one answers "is the authority behind
    # it still in force?". Enforcing only the first meant revocation worked when it
    # came through our own demo endpoint and silently did not when the platform
    # told us about it. Anything other than ACTIVE is a hard failure -- draft,
    # superseded, revoked and expired are all "not a mandate you may spend under".
    if mandate.status is not MandateStatus.ACTIVE:
        failures.append(
            RuleEvaluation(
                rule=_MANDATE_STATUS_RULE,
                outcome="fail",
                detail=f"the mandate is {mandate.status.value!r}, not active; it cannot authorize a purchase",
                source="safety",
            )
        )

    # The customer revoked this run's mandate through our own endpoint. The event's
    # `mandate.status` may still say "active" -- the platform has its own view and may
    # not have caught up, and in the offline/demo path there is no platform to tell.
    # Either way a purchase arriving after the brake was pulled must not be approved.
    #
    # Found by the stateful model immediately after run-level revocation was added:
    # a NEW purchase after revocation used to reach `issue_authority` and raise,
    # crashing the engine rather than declining the purchase. Blocking is both the
    # safe answer and the one the customer asked for.
    if state.is_revoked:
        failures.append(
            RuleEvaluation(
                rule=_MANDATE_STATUS_RULE,
                outcome="fail",
                detail="the customer revoked this mandate; no further purchase may be authorized under it",
                source="safety",
            )
        )

    if auth.get("card_id") != state.card_id:
        failures.append(
            RuleEvaluation(
                rule=_CARD_BINDING_RULE,
                outcome="fail",
                detail=f"event card_id={auth.get('card_id')!r} is not this run's card {state.card_id!r}",
                source="safety",
            )
        )
    if auth.get("mandate_id") != mandate.mandate_id:
        failures.append(
            RuleEvaluation(
                rule=_MANDATE_BINDING_RULE,
                outcome="fail",
                detail=f"event mandate_id={auth.get('mandate_id')!r} is not this run's mandate {mandate.mandate_id!r}",
                source="safety",
            )
        )
    return failures


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
    # R&D Track E (docs/RND_POLICY_SECURITY_SPLIT.md): the SAME evaluations, scoped
    # to source=="customer" and source=="safety" respectively, decided by the SAME
    # `_decide()` function. Purely explanatory -- `decision` above is computed
    # exactly as before (over the full, unscoped list) and is provably at least as
    # strict as either sub-verdict (see the module docstring's monotonicity note).
    policy_verdict: Decision | None = None
    security_verdict: Decision | None = None
    # R&D Track D (docs/RND_AUTHORIZATION_DRIFT.md): a structured diff against a
    # related/conflicting prior authorization, if one exists. Never gates the
    # decision itself -- `rules.py` already does that; this only explains what
    # changed relative to a reference point.
    drift: AuthorizationDrift | None = None
    # R&D Track A (docs/RND_CAPABILITY_AUTHORITY.md): issued only when decision is
    # "allow" (here or via a later `resolve_authorization` to "allow").
    payment_authority: PaymentAuthority | None = None


_TERMINAL_INTERVENTION: dict[Decision, InterventionKind] = {"allow": "allow", "block": "never", "review": "ask_this_time"}


def _basket_key(items: list[dict[str, Any]]) -> BasketKey:
    """Fingerprint of what was actually in the basket, used to tell a harmless
    repeated delivery from the same authorization_id arriving with a DIFFERENT
    purchase (`authorization_id_conflict`).

    `item_name` is included alongside `item_id` and `quantity` because the name is
    what every `item.*` rule actually reads and what the customer is shown: a
    re-delivery that keeps the same item_id but renames the line from "Monitor" to
    "Gold bar" is a semantically different purchase, and without the name in the
    fingerprint it inherited the original ALLOW unexamined (fourth-pass finding;
    see docs/FINAL_ARCHITECTURE_ATTACK.md).

    `unit_price` is deliberately NOT included: the security-relevant money figure
    is `billing_amount_chf`, which is compared separately, and no rule in the
    official vocabulary reads a per-line price (per-item ceilings are a documented
    non-feature). Re-allocating the same total across lines therefore changes no
    decision, and folding it in would only add fingerprint churn.

    The last three elements are the facts DERIVED from `item_details`, never the
    raw text. This is load-bearing in both directions:

      * A re-delivery that keeps the money and the basket identical but rewrites
        the merchant's text so that a derived fact moves -- "size 43" becoming
        "size 38", or a returnable order becoming FINAL SALE -- is a different
        purchase in every way a rule can see, and previously inherited the
        original ALLOW without ever being re-evaluated (fourth-pass finding).
      * Fingerprinting the raw string instead would fail the opposite way: every
        cosmetic edit, re-encoding or whitespace change by the merchant would
        fork an ordinary network retry into a false conflict. The extractors
        already NFKC-normalize and strip invisible characters, so obfuscation
        noise that moves no fact moves no fingerprint either.

    `order_returnable` also feeds the effective return window but is a
    PLATFORM-supplied field rather than merchant text, so it sits in a different
    trust tier and is not fingerprinted here; see docs/FINAL_ARCHITECTURE_ATTACK.md
    for that residual and why it was scoped out rather than silently folded in.
    """
    return tuple(
        sorted(
            (
                line["item_id"],
                line["item_name"],
                line["quantity"],
                extract_return_window_days(line.get("item_details", "")),
                mentions_final_sale(line.get("item_details", "")),
                extract_stated_size(line.get("item_details", "")),
            )
            for line in items
        )
    )


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


def _scoped_verdict(evaluations: list[RuleEvaluation], source: str, uncertainty_policy: UncertaintyPolicy) -> Decision:
    """R&D Track E: the same `_decide()` restricted to one evidence source. This is
    provably at least as permissive as the full-list verdict never -- i.e. never
    MORE permissive -- because the full list is a superset of each scoped list: any
    failure or unknown present in a subset is also present in the full set, so
    `_decide(full)` can only be equally or more restrictive than `_decide(subset)`.
    Verified directly by test_capability_and_drift.py's monotonicity property test."""
    decision, _ = _decide([e for e in evaluations if e.source == source], uncertainty_policy)
    return decision


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

    # "Is this event even ours?" is answered BEFORE "have we seen this purchase?".
    # Ordering matters: the repeat-delivery fingerprint covers merchant, basket and
    # amount but not identity, so a re-delivery carrying a different card_id or
    # mandate_id would otherwise match the fingerprint and be answered with the
    # stored decision -- returning a real answer to an event that was never ours to
    # answer. See docs/DEEP_SECURITY_RESEARCH.md (V5).
    binding_failures = _run_binding_failures(auth, mandate, state)
    if binding_failures:
        return EngineDecision(
            authorization_id=authorization_id,
            decision="block",
            reason_codes=tuple(f"hard_rule_failed:{e.rule.field}" for e in binding_failures),
            customer_message=(
                "This purchase could not be authorized: it does not belong to this wallet session, "
                "or the mandate behind it is no longer in force. Nothing was approved."
            ),
            evidence=tuple(f"{e.rule.field} [{e.outcome}]: {e.detail}" for e in binding_failures),
            rule_evaluations=tuple(binding_failures),
            intervention=_TERMINAL_INTERVENTION["block"],
            facts=None,
            security_verdict="block",
        )

    # The platform's status fields are read BEFORE the repeat-delivery branch, and
    # a dead status revokes this run's outstanding authority even when the delivery
    # is a routine replay.
    #
    # The two halves of that are deliberately different, because the correct answer
    # differs. The DECISION must still be the stored one: the platform already has
    # our answer for this authorization_id and re-sending a different one is not
    # something the official contract permits (technical_details.md step 6). But
    # money that has not moved yet is ours to stop, and a platform telling us the
    # authority is revoked or the card is blocked is the most authoritative reason
    # there is to stop it. Found by the mutation fuzzer in
    # tests/security/test_authority_mutation_fuzzer.py, which is exactly the kind
    # of composition (status change + replay) a per-field test does not reach.
    platform_status = _platform_status_evaluations(auth)
    if any(e.outcome == "fail" for e in platform_status):
        state.revoke_authority(authorization_id)

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
            conflict_drift = compute_drift(
                reference_authorization_id=authorization_id,
                prior_merchant_id=stored.merchant_id,
                prior_basket_key=stored.basket_key,
                prior_amount_chf=stored.billing_amount_chf,
                current_merchant_id=merchant_id,
                current_basket_key=basket_key,
                current_amount_chf=billing_amount_chf,
            )
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
                drift=conflict_drift,
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
    # The official schema requires amount/billing_amount_chf > 0 (exclusiveMinimum
    # 0), but a malformed or tampered event must not be trusted to have honored
    # that -- a non-positive amount is rejected here regardless of schema validation
    # upstream.
    if billing_amount_chf <= 0:
        evaluations.append(
            RuleEvaluation(rule=_AMOUNT_INTEGRITY_RULE, outcome="fail", detail=f"billing_amount_chf={billing_amount_chf} is not positive", source="safety")
        )
    # `amount` is documented as the total INCLUDING delivery, with `items_subtotal`
    # and `delivery_fee` as its components. Nothing checked that they agreed, so an
    # event could claim a CHF 100 total whose parts summed to CHF 600 and be approved
    # against a CHF 400 ceiling. All 45 official rows agree exactly, so a mismatch is
    # an internally inconsistent event, not a rounding artefact.
    #
    # This is the same guard as the FX check below, on the other half of the same
    # arithmetic -- not a new mechanism.
    parts = to_decimal(auth["items_subtotal"]) + to_decimal(auth["delivery_fee"])
    if abs(parts - to_decimal(auth["amount"])) > _AMOUNT_INTEGRITY_TOLERANCE_CHF:
        evaluations.append(
            RuleEvaluation(
                rule=_AMOUNT_INTEGRITY_RULE,
                outcome="fail",
                detail=f"items_subtotal + delivery_fee = {parts} does not match amount={auth['amount']}",
                source="safety",
            )
        )
    expected_chf = to_chf(to_decimal(auth["amount"]), auth["currency"])
    if abs(expected_chf - billing_amount_chf) > _AMOUNT_INTEGRITY_TOLERANCE_CHF:
        evaluations.append(
            RuleEvaluation(
                rule=_AMOUNT_INTEGRITY_RULE,
                outcome="fail",
                detail=f"billing_amount_chf={billing_amount_chf} does not match amount*fx_rate={expected_chf}",
                source="safety",
            )
        )
    # The platform's own statement about whether this purchase may proceed at all.
    # `authority_status` and `card_status_at_attempt` are REQUIRED fields of the
    # official event schema and are the most authoritative signals in the whole
    # event: they are the platform saying the authority behind this purchase has
    # been revoked or has expired, or that the card is blocked. Ignoring them --
    # which this engine did until the deep-security pass -- meant a revoked
    # authority still produced ALLOW and still charged. All 45 official rows carry
    # "active"/"active", which is exactly why no fixture ever exercised it.
    #
    # A recognised negative is a hard failure, NOT uncertainty: the customer
    # revoking their authority is not a question to put back to the customer, and
    # an `approve`-on-uncertainty policy must not be able to soften it. Anything
    # unrecognised (a new enum value, an empty string, a case variant, a missing
    # field) is genuinely missing information and goes through uncertainty_policy.
    evaluations.extend(platform_status)

    if duplicate_of is not None:
        evaluations.append(RuleEvaluation(rule=_DUPLICATE_RULE, outcome="unknown", detail=duplicate_reason or "", source="safety"))
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
            RuleEvaluation(rule=_NO_RULES_RULE, outcome="unknown", detail="this mandate has no spending controls to check against", source="safety")
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

    # R&D Track D: if this purchase names a related prior authorization this run
    # already decided (e.g. a re-quote after a decline), compute what actually
    # changed between them -- purely explanatory evidence, never a gate; `rules.py`
    # already decided this purchase on its own facts above.
    related_drift: AuthorizationDrift | None = None
    related_id = facts.related_authorization_id
    if related_id is not None:
        related_stored = state.get_stored_decision(related_id)
        if related_stored is not None:
            related_drift = compute_drift(
                reference_authorization_id=related_id,
                prior_merchant_id=related_stored.merchant_id,
                prior_basket_key=related_stored.basket_key,
                prior_amount_chf=related_stored.billing_amount_chf,
                current_merchant_id=merchant_id,
                current_basket_key=basket_key,
                current_amount_chf=billing_amount_chf,
            )

    # R&D Track E: the same evaluations, scoped to what the customer's own policy
    # says vs. what the wallet's own safety checks say -- see `_scoped_verdict`.
    policy_verdict = _scoped_verdict(evaluations, "customer", mandate.uncertainty_policy)
    security_verdict = _scoped_verdict(evaluations, "safety", mandate.uncertainty_policy)

    # R&D Track A: ALLOW issues a narrow, expiring, inspectable payment authority --
    # never constructed anywhere else in this codebase.
    payment_authority: PaymentAuthority | None = None
    if decision == "allow":
        payment_authority = state.issue_authority(
            authorization_id, mandate_id=mandate.mandate_id, policy_version=mandate_policy_version(mandate)
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
        policy_verdict=policy_verdict,
        security_verdict=security_verdict,
        drift=related_drift,
        payment_authority=payment_authority,
    )


def _period_rules_breached_now(
    mandate: MandateSnapshot | None, state: RunState, authorization_id: str
) -> str | None:
    """Would approving this pending purchase now break a rolling-period ceiling?

    Re-derived from live state at the moment of resolution rather than trusted from
    the evaluation that raised the step-up. Returns the breached rule's description,
    or None.
    """
    if mandate is None:
        return None
    pending = state.get_stored_decision(authorization_id)
    if pending is None:
        return None
    for rule in mandate.hard_rules:
        if rule.field != "authorization.billing_amount_chf" or rule.scope != "period" or not rule.period_days:
            continue
        prior = state.rolling_spend_chf(pending.timestamp, rule.period_days)
        if prior + pending.billing_amount_chf > to_decimal(rule.value):
            return (
                f"{rule.period_days}d spend would reach "
                f"CHF {prior + pending.billing_amount_chf} against a CHF {rule.value} ceiling"
            )
    return None


def resolve_authorization(
    authorization_id: str, human_decision: Decision, state: RunState, *, resolved_at: datetime, mandate: MandateSnapshot | None = None
) -> EngineDecision:
    """Apply a real customer's answer to a `review`ed authorization.

    Scoped to exactly this authorization_id -- see `state.RunState.record_resolution`
    -- and never touches the mandate. "A yes is this authorization. It is not a new
    wallet." Deliberately takes no amount: the amount that matters is whatever the
    customer was actually shown when the purchase was flagged for review, sourced
    from `state`'s own record, never from a value the caller could supply.

    `mandate` is optional (backward-compatible: existing callers that don't pass it
    keep working exactly as before) -- when given, an approve resolution issues a
    `PaymentAuthority` the same way an automatic ALLOW does (R&D Track A), so a
    step-up-then-approved purchase is just as payable, under the same bounded
    authority model, as an automatically-approved one.
    """
    if human_decision == "review":
        raise ValueError("a human resolution must be 'allow' or 'block', not 'review'")

    # Two things can have changed between the wallet asking and the customer
    # answering, and BOTH used to be ignored. An independent security audit named the
    # shape exactly: this function was the one unguarded escape hatch, checking a
    # single flag set minutes or hours earlier and re-deriving nothing from
    # authoritative state.
    #
    # A customer's "yes" is an answer to a question, not an override of their own
    # later instructions, so where the two conflict the safe one wins and we record
    # WHY rather than silently downgrading.
    override_reason: str | None = None

    if human_decision == "allow":
        # (1) The customer revoked the mandate while this purchase was waiting. The
        # revocation is the later and stronger instruction.
        if state.is_revoked:
            override_reason = "mandate_revoked_before_resolution"
        else:
            # (2) A rolling-period ceiling that was satisfied when we asked may not be
            # satisfied now -- and a compromised agent chooses what gets asked, so it
            # could force purchases into the queue and have them approved one at a
            # time, each individually reasonable, together far over the customer's own
            # weekly cap. Measured at CHF 2,400 against a CHF 500 / 7-day cap before
            # this check existed.
            breached = _period_rules_breached_now(mandate, state, authorization_id)
            if breached is not None:
                override_reason = f"period_limit_exceeded:{breached}"

    if override_reason is not None:
        stored = state.record_resolution(authorization_id, "block", resolved_at)
        return EngineDecision(
            authorization_id=authorization_id,
            decision=stored.decision,
            reason_codes=("customer_resolution", override_reason),
            customer_message=(
                "Your approval arrived after you revoked this mandate, so the purchase was declined."
                if override_reason.startswith("mandate_revoked")
                else "Approving this purchase would now exceed the spending limit you set, so it was declined."
            ),
            evidence=(f"resolved by the customer at {resolved_at.isoformat()}", override_reason),
            rule_evaluations=(),
            intervention=_TERMINAL_INTERVENTION[stored.decision],
            facts=None,
            idempotent_replay=False,
            payment_authority=None,
        )

    stored = state.record_resolution(authorization_id, human_decision, resolved_at)
    payment_authority: PaymentAuthority | None = None
    if stored.decision == "allow" and mandate is not None:
        payment_authority = state.issue_authority(
            authorization_id, mandate_id=mandate.mandate_id, policy_version=mandate_policy_version(mandate), now=resolved_at
        )
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
        payment_authority=payment_authority,
    )

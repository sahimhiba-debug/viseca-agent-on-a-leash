"""Evaluate a mandate's hard rules against purchase facts.

This is the only place `HardRule.field`/`operator`/`value` are interpreted. Every
rule evaluates to one of three outcomes, matching the three-way distinction the
challenge asks for (technical_details.md step 2 and challenge.md Objective #2):

  PASS    -- the fact satisfies the rule.
  FAIL    -- the fact clearly violates the rule. Always blocks, regardless of the
             mandate's uncertainty_policy: a hard rule failure is not "uncertain".
  UNKNOWN -- the fact needed to check the rule is missing (e.g. merchant
             familiarity could not be determined, or a return window was not
             stated). This is insufficient information, not a violation; the
             mandate's `uncertainty_policy` decides what to do with it.

`item.unrequested_present` and the rolling-period ceiling both need information
from outside a single rule (which categories were actually requested; how much
has already been spent in the window), so the engine collects that context once
per authorization and passes it in as `RuleContext`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from .facts import PurchaseFacts
from .mandate import HardRule

Outcome = Literal["pass", "fail", "unknown"]


@dataclass(frozen=True)
class RuleContext:
    """Cross-rule information the evaluator needs but no single HardRule carries."""

    requested_item_categories: frozenset[str] | None  # from any item.category "in" rule; None if no such rule
    projected_period_spend_chf: dict[int, Decimal]  # period_days -> (prior approved spend + this purchase), CHF


@dataclass(frozen=True)
class RuleEvaluation:
    rule: HardRule
    outcome: Outcome
    detail: str


def _compare(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "<":
        return actual < expected
    if operator == "<=":
        return actual <= expected
    if operator == "=":
        return actual == expected
    if operator == "!=":
        return actual != expected
    if operator == ">":
        return actual > expected
    if operator == ">=":
        return actual >= expected
    raise ValueError(f"operator {operator!r} is not a scalar comparison")


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def evaluate_rule(rule: HardRule, facts: PurchaseFacts, ctx: RuleContext) -> RuleEvaluation:
    field = rule.field

    if field == "authorization.billing_amount_chf" and rule.scope != "period":
        actual = facts.billing_amount_chf
        ok = _compare(rule.operator, actual, _as_decimal(rule.value))
        return RuleEvaluation(rule, "pass" if ok else "fail", f"billing_amount_chf={actual} CHF")

    if field == "authorization.billing_amount_chf" and rule.scope == "period":
        projected = ctx.projected_period_spend_chf.get(rule.period_days or 0)
        if projected is None:
            return RuleEvaluation(rule, "unknown", "rolling-period spend could not be computed")
        ok = _compare(rule.operator, projected, _as_decimal(rule.value))
        detail = f"projected {rule.period_days}-day spend={projected} CHF (including this purchase)"
        return RuleEvaluation(rule, "pass" if ok else "fail", detail)

    if field == "merchant.category":
        values = rule.value if isinstance(rule.value, list) else [rule.value]
        is_in = facts.merchant_category in values
        ok = is_in if rule.operator == "in" else not is_in
        return RuleEvaluation(rule, "pass" if ok else "fail", f"merchant_category={facts.merchant_category!r}")

    if field == "merchant.familiar":
        if facts.merchant_familiar is None:
            return RuleEvaluation(rule, "unknown", "no authorization history available for this merchant/card")
        actual = "true" if facts.merchant_familiar else "false"
        ok = _compare(rule.operator, actual, rule.value)
        return RuleEvaluation(rule, "pass" if ok else "fail", f"merchant_familiar={actual}")

    if field == "item.category":
        values = set(rule.value if isinstance(rule.value, list) else [rule.value])
        outside = [c for c in facts.item_categories if c not in values]
        ok = not outside if rule.operator == "in" else bool(outside)
        detail = f"item_categories={list(facts.item_categories)}" + (f", outside requested set: {outside}" if outside else "")
        return RuleEvaluation(rule, "pass" if ok else "fail", detail)

    if field == "item.unrequested_present":
        if ctx.requested_item_categories is None:
            # No item.category rule exists, so "requested" is undefined; nothing to check against.
            return RuleEvaluation(rule, "unknown", "no requested item category is on file to compare the basket against")
        extra = [c for c in facts.item_categories if c not in ctx.requested_item_categories]
        actual = "true" if extra else "false"
        ok = _compare(rule.operator, actual, rule.value)
        detail = f"unrequested categories in basket: {extra}" if extra else "basket matches requested categories"
        return RuleEvaluation(rule, "pass" if ok else "fail", detail)

    if field == "item.name_contains":
        needle = str(rule.value).lower()
        mismatched = [n for n in facts.item_names if needle not in n.lower()]
        ok = not mismatched
        detail = f"item_names={list(facts.item_names)}" + (f", not matching {rule.value!r}: {mismatched}" if mismatched else "")
        return RuleEvaluation(rule, "pass" if ok else "fail", detail)

    if field == "item.size":
        if not facts.item_sizes:
            return RuleEvaluation(rule, "unknown", "no size was stated for this order")
        mismatched = [s for s in facts.item_sizes if s.lower() != str(rule.value).lower()]
        ok = not mismatched
        detail = f"item_sizes={list(facts.item_sizes)}"
        return RuleEvaluation(rule, "pass" if ok else "fail", detail)

    if field == "order.return_window_days":
        if facts.order_returnable == "not_applicable":
            return RuleEvaluation(rule, "pass", "return window does not apply to this fulfilment type")
        if facts.return_window_days is None:
            return RuleEvaluation(rule, "unknown", "return window was not stated for this order")
        ok = _compare(rule.operator, facts.return_window_days, int(rule.value))
        return RuleEvaluation(rule, "pass" if ok else "fail", f"return_window_days={facts.return_window_days}")

    if field == "session.integrity_risk":
        actual = "true" if facts.session_integrity_risk else "false"
        ok = _compare(rule.operator, actual, rule.value)
        reasons = ", ".join(facts.session_integrity_reasons) or "none"
        return RuleEvaluation(rule, "pass" if ok else "fail", f"session_integrity_risk={actual} ({reasons})")

    # An unrecognized field name is a compiler/engine mismatch, not a customer
    # authority decision. Fail closed rather than silently ignore a stored rule.
    return RuleEvaluation(rule, "unknown", f"field {field!r} is not recognized by this engine version")

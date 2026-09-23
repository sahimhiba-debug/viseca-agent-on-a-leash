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
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from .facts import PurchaseFacts
from .mandate import HardRule

Outcome = Literal["pass", "fail", "unknown"]


@dataclass(frozen=True)
class RuleContext:
    """Cross-rule information the evaluator needs but no single HardRule carries."""

    requested_item_categories: frozenset[str] | None  # from any item.category "in" rule; None if no such rule
    projected_period_spend_chf: dict[int, Decimal]  # period_days -> (prior approved spend + this purchase), CHF
    # The period windows whose whole span this run's state could NOT see, because it
    # was resumed part-way through (a lost checkpoint). Per-window rather than one
    # global flag: a state that has been watching for two days can answer a 1-day
    # ceiling and not a 7-day one, and telling the customer otherwise in either
    # direction would be a lie. The outcome is `unknown` either way; membership here
    # only changes the sentence they are given.
    unobserved_periods: frozenset[int] = frozenset()


@dataclass(frozen=True)
class RuleEvaluation:
    rule: HardRule
    outcome: Outcome
    detail: str
    # "customer" for a rule that traces back to the customer's own mandate;
    # "safety" for a control-layer integrity check the customer never opted into
    # and cannot opt out of (duplicate suspicion, the no-rules safety net, the
    # amount-integrity check -- see decision_engine.py). Purely a display/
    # explainability tag: `_decide()` treats every outcome identically regardless
    # of source, so this can never change what decision is reached, only how it is
    # explained (docs/MASTER_R_AND_D_AUDIT.md, "alternative policy representations").
    source: Literal["customer", "safety"] = "customer"


class RuleNotInterpretable(ValueError):
    """This engine cannot apply this rule as written.

    Not "the rule is violated" and not "the rule passes" -- the third thing, which
    `evaluate_rule` turns into UNKNOWN and routes to the customer's
    `uncertainty_policy`, exactly as it already does for a field name it does not
    recognise."""


def _membership(actual: Any, expected: Any) -> bool:
    """`in` / `not_in` against a list, which the spec allows on ANY field.

    The rule format permits every operator on every field -- `operator` is one of
    eight and `value` is "a number, a string, or a list containing only strings",
    with no pairing rule between them. So `{"field": "merchant.familiar",
    "operator": "in", "value": ["true"]}` is a legal stored rule, and it used to
    raise straight out of the engine.

    Compared as strings, with a numeric comparison first when both sides parse as
    numbers, so `billing_amount_chf in ["50"]` means what a person would expect of
    50.0 and not what `str()` happens to produce."""
    values = expected if isinstance(expected, list) else [expected]
    for candidate in values:
        try:
            if _as_decimal(actual) == _as_decimal(candidate):
                return True
            continue
        except (InvalidOperation, ArithmeticError, TypeError, ValueError):
            pass
        if str(actual) == str(candidate):
            return True
    return False


def _compare(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "in":
        return _membership(actual, expected)
    if operator == "not_in":
        return not _membership(actual, expected)
    # An ordering operator against a list is not a comparison anyone can perform.
    # It is legal to STORE (the schema pairs no operator with a value type) and
    # impossible to APPLY, which is the definition of UNKNOWN in this engine.
    if isinstance(expected, list):
        raise RuleNotInterpretable(
            f"operator {operator!r} cannot be applied to a list of values")
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
    raise RuleNotInterpretable(f"operator {operator!r} is not one this engine applies")


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def evaluate_rule(rule: HardRule, facts: PurchaseFacts, ctx: RuleContext) -> RuleEvaluation:
    """Apply one stored rule, or say plainly that this engine cannot.

    THE OUTER GUARD IS THE POINT. `_evaluate_rule` below interprets a rule the
    customer's mandate stores, and the stored rule comes from a format far wider
    than anything this compiler emits: eight operators, three value shapes, no
    pairing rule between them, and a PATCH endpoint that lets any of them be added
    to a live mandate. A combination we cannot apply used to raise straight out of
    the engine -- `merchant.familiar in ["true"]` is schema-legal and produced an
    uncaught ValueError, and an amount rule with a list value produced an
    InvalidOperation from deep inside `decimal`.

    In the live worker an exception means no decision is submitted at all and the
    8-second deadline lapses into behaviour the specification does not define. That
    is the worst of the three ways to fail to represent an absence -- filled in,
    inferred, or THROWN -- and the file already had the right answer one level up:
    an unrecognised FIELD returns UNKNOWN and is routed to `uncertainty_policy`. An
    unrecognised operator-and-value now does the same.

    Deliberately narrow: only `RuleNotInterpretable` and the arithmetic errors that
    a wrong value type produces are caught. A bug in this engine still crashes,
    because a bug quietly downgraded to "ask the customer" is a bug nobody finds.
    """
    try:
        return _evaluate_rule(rule, facts, ctx)
    except RuleNotInterpretable as exc:
        return RuleEvaluation(rule, "unknown", str(exc))
    except (InvalidOperation, ArithmeticError, TypeError) as exc:
        return RuleEvaluation(
            rule, "unknown",
            f"rule on {rule.field!r} could not be applied as written "
            f"({type(exc).__name__}); its value does not fit its operator")


def _expected_amount(rule: HardRule):
    """A money rule's right-hand side. Left as a LIST for `in`/`not_in`, which
    `_compare` handles by membership; coerced to Decimal otherwise, where a list
    would be `InvalidOperation` from inside `decimal` rather than a decision."""
    if rule.operator in ("in", "not_in"):
        return rule.value
    return _as_decimal(rule.value)


def _candidate_items(facts: PurchaseFacts, ctx: RuleContext) -> list:
    """Items a variant/size check should apply to: those in the requested item
    category, if one is on file. An unrelated add-on (a different category
    entirely, already independently caught by `item.category`/
    `item.unrequested_present`) must not make `item.name_contains`/`item.size`
    fail against the CORRECT primary item just because it is sitting in the same
    basket -- see docs/SECOND_ADVERSARIAL_AUDIT.md, "multi-item aggregation".
    Falls back to every item when nothing matches the requested category (so the
    evidence for an all-wrong-category basket still shows a concrete mismatch
    instead of a vague "nothing to check"), and to every item when no category
    rule exists at all to filter by.
    """
    if ctx.requested_item_categories is None:
        return list(facts.items)
    matching = [i for i in facts.items if i.item_category in ctx.requested_item_categories]
    return matching or list(facts.items)


def _evaluate_rule(rule: HardRule, facts: PurchaseFacts, ctx: RuleContext) -> RuleEvaluation:
    field = rule.field

    # An item rule evaluated over an empty basket is not satisfied, it is UNCHECKABLE.
    # Every `item.*` branch below reasons over a list, and each of them reads an empty
    # list as agreement: nothing is outside the requested category, no name fails to
    # match, nothing unrequested is present. That is the vacuous-truth bug, and it let a
    # CHF 400 purchase carrying no items pass four item restrictions at once.
    #
    # `decision_engine` rejects an empty basket outright as a structural failure, so in
    # practice this branch is the second line rather than the first. It exists because
    # the vacuity lives HERE -- delete the engine's check and this file would go back to
    # answering "pass" to questions it cannot see the subject of.
    if field.startswith("item.") and not facts.items:
        return RuleEvaluation(rule, "unknown", "this purchase lists no items, so this rule has nothing to check")

    if field == "authorization.billing_amount_chf" and rule.scope != "period":
        actual = facts.billing_amount_chf
        ok = _compare(rule.operator, actual, _expected_amount(rule))
        return RuleEvaluation(rule, "pass" if ok else "fail", f"billing_amount_chf={actual} CHF")

    if field == "authorization.billing_amount_chf" and rule.scope == "period":
        projected = ctx.projected_period_spend_chf.get(rule.period_days or 0)
        if projected is None:
            if (rule.period_days or 0) in ctx.unobserved_periods:
                return RuleEvaluation(
                    rule, "unknown",
                    "this wallet restarted and cannot see what was already spent in "
                    "this period, so the running total is unknown rather than zero")
            return RuleEvaluation(rule, "unknown", "rolling-period spend could not be computed")
        ok = _compare(rule.operator, projected, _expected_amount(rule))
        detail = f"projected {rule.period_days}-day spend={projected} CHF (including this purchase)"
        return RuleEvaluation(rule, "pass" if ok else "fail", detail)

    if field == "merchant.category":
        values = rule.value if isinstance(rule.value, list) else [rule.value]
        is_in = facts.merchant_category in values
        ok = is_in if rule.operator == "in" else not is_in
        return RuleEvaluation(rule, "pass" if ok else "fail", f"merchant_category={facts.merchant_category!r}")

    if field == "merchant.familiar":
        if facts.merchant_familiar is None:
            # TWO CAUSES, and the customer is entitled to know which. "No history at
            # all" and "your agent has shopped here and you have not" are different
            # facts; collapsing them let an agent's own past purchases answer a
            # question the customer asked about THEIR history.
            return RuleEvaluation(
                rule, "unknown",
                facts.merchant_familiar_basis or
                "no authorization history available for this merchant/card")
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
        candidates = _candidate_items(facts, ctx)
        mismatched = [i.item_name for i in candidates if needle not in i.item_name.lower()]
        ok = not mismatched
        names = [i.item_name for i in candidates]
        detail = f"item_names={names}" + (f", not matching {rule.value!r}: {mismatched}" if mismatched else "")
        return RuleEvaluation(rule, "pass" if ok else "fail", detail)

    if field == "item.size":
        candidates = _candidate_items(facts, ctx)
        sized = [i for i in candidates if i.stated_size is not None]
        if not sized:
            return RuleEvaluation(rule, "unknown", "no size was stated for the requested item")
        # A line that states nothing is UNKNOWN, not "whatever the other line said".
        # This is the same aggregation the return-window logic already refuses, and it
        # was not applied here: a basket of two requested items, one stating "size 43"
        # and one silent, PASSED on the strength of the first. So saying nothing beat
        # lying -- an explicit "size 38" was caught, silence was not -- and adding a
        # LESS informative line made the decision MORE permissive. One silent shoe
        # alone escalates; add a size-43 decoy beside it and the pair is approved.
        # ORDER MATTERS, and getting it wrong is how the first version of this fix
        # broke the very property it was written for. Negative evidence is decisive:
        # a stated size that does not match is a failure whatever else is in the
        # basket. Only once nothing contradicts the requirement does silence become
        # the open question. Checking silence first let an adversary soften a
        # definite FAIL into a REVIEW by appending an evidence-free line -- 24
        # monotonicity violations in a 4,000-basket fuzz.
        mismatched = [i.stated_size for i in sized if i.stated_size.lower() != str(rule.value).lower()]
        if mismatched:
            return RuleEvaluation(rule, "fail", f"item_sizes={[i.stated_size for i in sized]}")
        silent = [i.item_name for i in candidates if i.stated_size is None]
        if silent:
            return RuleEvaluation(
                rule, "unknown",
                f"a size was stated for some items but not for {silent}; "
                f"their size is unknown, not the one stated elsewhere",
            )
        return RuleEvaluation(rule, "pass", f"item_sizes={[i.stated_size for i in sized]}")

    if field == "order.return_window_days":
        if facts.order_returnable == "not_applicable":
            # This used to PASS unconditionally, and that was the one place in this
            # engine where a customer requirement could be satisfied by asserting that
            # it did not apply. Three things were wrong with it:
            #
            #   * it required no evidence at all -- `not_applicable` was the only
            #     value of `order_returnable` that neither blocked, escalated, nor
            #     demanded a stated window;
            #   * it was never cross-checked against `fulfillment_method`, so a
            #     PHYSICAL delivery declared "not_applicable" passed;
            #   * it was evaluated BEFORE the final-sale logic, so an order the
            #     merchant itself marked "sold as final sale" satisfied a
            #     "returnable within 14 days" requirement.
            #
            # A customer who says "only buy what I can return" is not served by
            # silently approving something that cannot be returned. But neither is
            # blocking right: for a genuinely digital good the concept really does not
            # apply, and that is the customer's call, not ours. So this is UNKNOWN --
            # the engine's own answer for "we cannot establish this fact" -- which
            # escalates under `ask` and declines under `decline`, exactly as the
            # customer chose.
            return RuleEvaluation(
                rule, "unknown",
                "the seller says returns do not apply to this order, so your return "
                "requirement cannot be satisfied or refuted",
            )
        if facts.return_window_days is None:
            return RuleEvaluation(rule, "unknown", "return window was not stated for this order")
        ok = _compare(rule.operator, facts.return_window_days, int(rule.value))
        return RuleEvaluation(rule, "pass" if ok else "fail", f"return_window_days={facts.return_window_days}")

    if field == "session.integrity_risk":
        reasons = ", ".join(facts.session_integrity_reasons) or "none"
        if facts.session_integrity_risk is None:
            # The one rule in this engine that had no UNKNOWN branch -- and the one
            # the session-integrity scenario in the official pack is named for. A
            # signal too weak to condemn came back as CLEAN, so a device change on
            # its own -- recorded in this very evidence string -- approved the
            # purchase. "Pause anything that looks like someone other than me is
            # driving" is a request to be ASKED, and `uncertainty_policy` is where
            # the customer already answered.
            #
            # (No scenario id appears here: `test_engine_does_not_branch_on_scenario_id`
            # forbids one anywhere in engine source, comments included, which is the
            # cheapest way to enforce "do not look up an outcome by scenario name".)
            return RuleEvaluation(
                rule, "unknown",
                f"session_integrity_risk=unclear ({reasons}); this may be you on "
                f"another device, and only you can say")
        actual = "true" if facts.session_integrity_risk else "false"
        ok = _compare(rule.operator, actual, rule.value)
        return RuleEvaluation(rule, "pass" if ok else "fail", f"session_integrity_risk={actual} ({reasons})")

    # An unrecognized field name is a compiler/engine mismatch, not a customer
    # authority decision. Fail closed rather than silently ignore a stored rule.
    return RuleEvaluation(rule, "unknown", f"field {field!r} is not recognized by this engine version")

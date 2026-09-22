"""Every rule field must declare what ABSENCE of its subject means.

Four separate defects in this project have been the same thing:

  * `mandate.status` deleted from the event      -> the status check skipped itself
  * `items: []`                                   -> item rules vacuously satisfied
  * `recent_attempt_count_10m: 0`                 -> session risk suppressed
  * `order_returnable: "not_applicable"`          -> a return requirement satisfied

Each was found separately, months of work apart in project time, and each was fixed
on its own. That is four instances of ONE class: **a claim is believed because its
refutation is absent.** The engine's `fail > unknown > pass` ordering is right; the
bias is in the mapping INTO it, where absence lands on `pass` unless whoever wrote
the branch remembered to write the `unknown` case.

A hand-written sweep of "here are the fields and here is what absence does" would rot
exactly the way the invariant register was rotting before it was machine-checked: add
a rule field, forget to add it here, and the sweep silently covers less than it
claims. So the field list is DISCOVERED from `rules.py` by AST, and a field that this
file does not give an absence case for fails the test.

What this can and cannot do. It cannot know what the right answer is for a field
nobody has thought about -- that is a design decision. It CAN guarantee the decision
was made explicitly, by someone, for every field the engine recognises. That is the
step that was missing all four times.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.facts import build_purchase_facts
from wallet_control.mandate import HardRule
from wallet_control.rules import RuleContext, evaluate_rule

RULES_SOURCE = Path(__file__).resolve().parents[2] / "src" / "wallet_control" / "rules.py"
MERCHANT = "ME_KNOWN"
AT = datetime(2026, 8, 12, tzinfo=timezone.utc)


def _recognised_fields() -> set[str]:
    """Every literal `field == "..."` comparison inside the rule interpreter.

    The interpreter is `_evaluate_rule`; `evaluate_rule` is the thin guard around it
    that turns a rule this engine cannot apply into UNKNOWN instead of an exception.
    This scanner used to name the public function and caught the split immediately,
    which is what it is for."""
    tree = ast.parse(RULES_SOURCE.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_evaluate_rule")
    found: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "field":
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                    found.add(comparator.value)
    return found


# field -> (a rule using it, how to make its subject absent, the outcome that means
# "I cannot check this"). `pass` is never an acceptable answer to an absent subject.
ABSENCE_CASES: dict[str, tuple[HardRule, object, str]] = {
    "authorization.billing_amount_chf": (
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase"),
        None,   # the amount is structural: the engine rejects a non-positive or absent one upstream
        "structural",
    ),
    "merchant.category": (
        HardRule(field="merchant.category", operator="in", value=["groceries"]),
        lambda e: e["authorization"]["merchant"].update(merchant_category=""),
        "fail",
    ),
    "merchant.familiar": (
        HardRule(field="merchant.familiar", operator="=", value="true"),
        "no_history",
        "unknown",
    ),
    "item.category": (
        HardRule(field="item.category", operator="in", value=["groceries"]),
        lambda e: e["authorization"].update(items=[]),
        "unknown",
    ),
    "item.name_contains": (
        HardRule(field="item.name_contains", operator="=", value="milk"),
        lambda e: e["authorization"].update(items=[]),
        "unknown",
    ),
    "item.unrequested_present": (
        HardRule(field="item.unrequested_present", operator="=", value="false"),
        lambda e: e["authorization"].update(items=[]),
        "unknown",
    ),
    "item.size": (
        HardRule(field="item.size", operator="=", value="43"),
        lambda e: e["authorization"].update(items=[]),
        "unknown",
    ),
    "order.return_window_days": (
        HardRule(field="order.return_window_days", operator=">=", value=14),
        lambda e: e["authorization"].update(order_returnable="not_applicable"),
        "unknown",
    ),
    "session.integrity_risk": (
        HardRule(field="session.integrity_risk", operator="=", value="false"),
        # Absence here is not a missing field -- `recent_attempt_count_10m` is required
        # and an absent one raises upstream. It is a LIE: the event reporting zero
        # neighbours. That claim is cross-checked against this run's own attempt log
        # (I35), so the rule's own answer is not the defence and is not asserted here.
        "cross_checked",
        "cross_checked",
    ),
}


def test_every_recognised_rule_field_has_a_declared_absence_case():
    """The anti-rot check. Add a field to `rules.py` and this fails until someone
    decides, in writing, what absence of its subject means."""
    recognised = _recognised_fields()
    undeclared = recognised - set(ABSENCE_CASES)
    assert not undeclared, (
        "these rule fields have no declared absence behaviour -- decide what an absent "
        f"subject means for each, then add it here: {sorted(undeclared)}"
    )
    stale = set(ABSENCE_CASES) - recognised
    assert not stale, f"declared here but no longer recognised by rules.py: {sorted(stale)}"


@pytest.mark.parametrize("field", sorted(f for f, (_, m, _) in ABSENCE_CASES.items() if callable(m)))
def test_an_absent_subject_is_never_a_pass(field):
    rule, mutate, expected = ABSENCE_CASES[field]
    mandate = make_mandate(instruction="x", hard_rules=[])
    event = make_event(mandate=mandate, authorization_id="AU_ABSENT", amount=100.0, merchant_id=MERCHANT, timestamp=AT)
    mutate(event)
    facts = build_purchase_facts(
        event, merchant_familiar=True, session_integrity_risk=False,
        session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None,
    )
    ctx = RuleContext(requested_item_categories=frozenset({"groceries"}), projected_period_spend_chf={})

    outcome = evaluate_rule(rule, facts, ctx).outcome
    assert outcome != "pass", f"{field}: an absent subject was read as satisfaction"
    assert outcome == expected, f"{field}: expected {expected}, got {outcome}"


def test_an_unknown_merchant_history_is_unknown_not_unfamiliar():
    """The one field whose absence case is a None fact rather than a mutated event.
    `HistoryIndex.available=False` must not read as "not familiar" -- that would be
    the same bug pointing the other way, inventing a fact from missing data."""
    mandate = make_mandate(instruction="x", hard_rules=[])
    event = make_event(mandate=mandate, authorization_id="AU_NH", amount=100.0, merchant_id=MERCHANT, timestamp=AT)
    facts = build_purchase_facts(
        event, merchant_familiar=None, session_integrity_risk=False,
        session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None,
    )
    ctx = RuleContext(requested_item_categories=None, projected_period_spend_chf={})
    rule, _, _ = ABSENCE_CASES["merchant.familiar"]
    assert evaluate_rule(rule, facts, ctx).outcome == "unknown"

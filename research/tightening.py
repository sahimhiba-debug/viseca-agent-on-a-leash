"""Tightening a mandate must never permit anything it did not permit before.

WHAT THE BRIEF REQUIRES. "The customer must also be able to tighten, update, or
revoke the wallet policy." The official lifecycle gives `PATCH` for that, and
`technical_details.md` is explicit that an update may only narrow: "adding a rule
must not weaken a customer's existing restriction".

WHAT THE CODE ARGUES. `Mandate.tighten_hard_rules` only ever appends, `HardRule` is
frozen, and hard rules are evaluated as a CONJUNCTION -- so an extra rule is an extra
conjunct and the set can only shrink. That is a sound argument about the shape of the
code. It is not a measurement, and it is exactly the kind of argument this repository
has twice found to be true of one component and false of the program:

    `merchant.category` was declared "loaded from reference data, never from the
    proposal" -- true of the event builders, false of the engine.

    `order_returnable` was left out of the basket fingerprint as "platform-supplied
    ... a different trust tier" -- true of the replay, false of our own endpoint.

So it is measured, POINTWISE. Not "the set got smaller" -- for every basket in the
world, the verdict after tightening must be no more permissive than before:

    for all b:  permissiveness(verdict_after(b)) <= permissiveness(verdict_before(b))

which is strictly stronger than |A_after| <= |A_before|: a change that refused one
purchase and permitted another would keep the count and still be a widening.

TWO KINDS OF TIGHTENING are checked, because the contract has two halves: appending
a hard rule, and moving `uncertainty_policy` towards `decline`.

Run:  python3 -m research.tightening
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wallet_control.mandate import HardRule, UncertaintyPolicy  # noqa: E402
from wallet_control.policy_compiler import compile_instruction  # noqa: E402
from wallet_control.scope import (  # noqa: E402
    FAMILIAR, _categories, _world,
)
from wallet_control.witness import PERMISSIVENESS, judge_event, snapshot  # noqa: E402

BASE = "Order our household groceries at or below CHF 120."

# Rules a customer might plausibly add next. Deliberately a mixture: ones that bite,
# ones that cannot bite in this world, ones on fields whose facts are UNKNOWN here
# (which is where a tightening could accidentally widen, if an unknown were ever
# treated as more permissive than a fail it replaced).
ADDITIONS: list[HardRule] = [
    HardRule(field="merchant.familiar", operator="=", value="true"),
    HardRule(field="authorization.billing_amount_chf", operator="<=", value=40,
             currency="CHF", scope="purchase"),
    HardRule(field="authorization.billing_amount_chf", operator="<=", value=300,
             currency="CHF", scope="period", period_days=7),
    HardRule(field="item.category", operator="in", value=["groceries"]),
    HardRule(field="item.category", operator="in", value=["electronics"]),
    HardRule(field="item.unrequested_present", operator="=", value="false"),
    HardRule(field="order.return_window_days", operator=">=", value=14),
    HardRule(field="item.size", operator="=", value="M"),
    HardRule(field="item.name_contains", operator="=", value="produce"),
    HardRule(field="merchant.category", operator="in", value=["groceries"]),
    HardRule(field="session.integrity_risk", operator="=", value="false"),
]


def _verdicts(rules: list[HardRule], uncertainty: UncertaintyPolicy,
              category: str) -> dict[tuple, str]:
    mandate = snapshot(list(rules), uncertainty)
    return {
        (merchant, tuple(i for i, _n, _p in combo)):
            judge_event(mandate, index, merchant, category, combo, familiar=FAMILIAR)
        for index, (merchant, combo) in enumerate(_world(category, "min"))
    }


def sweep(instruction: str = BASE) -> dict[str, Any]:
    compiled = compile_instruction(instruction)
    base_rules = list(compiled.hard_rules)
    category = _categories(base_rules)
    policy = compiled.uncertainty_policy

    before = _verdicts(base_rules, policy, category)
    violations, checked = [], 0

    for rule in ADDITIONS:
        after = _verdicts(base_rules + [rule], policy, category)
        for key, was in before.items():
            checked += 1
            now = after[key]
            if PERMISSIVENESS[now] > PERMISSIVENESS[was]:
                violations.append(("add " + rule.field, key, was, now))

    # ...and the other half of the contract: the dial may only move towards decline.
    for stricter in (UncertaintyPolicy.DECLINE,):
        after = _verdicts(base_rules, stricter, category)
        for key, was in before.items():
            checked += 1
            now = after[key]
            if PERMISSIVENESS[now] > PERMISSIVENESS[was]:
                violations.append((f"uncertainty -> {stricter.value}", key, was, now))

    return {"violations": violations, "checked": checked,
            "baskets": len(before), "additions": len(ADDITIONS)}


def main() -> None:
    result = sweep()
    print(f"\n  TIGHTENING IS POINTWISE MONOTONE\n")
    print(f"  {result['baskets']:,} baskets x {result['additions']} added rules, plus the")
    print(f"  uncertainty dial: {result['checked']:,} before/after comparisons\n")
    if result["violations"]:
        print(f"  VIOLATIONS -- a tightening made something MORE permissive: "
              f"{len(result['violations'])}")
        for what, key, was, now in result["violations"][:15]:
            print(f"    {what:38s} {key[0]} {key[1]}  {was} -> {now}")
    else:
        print("  No tightening made any purchase more permissive.")
        print("  Pointwise, not merely in total: a change that refused one purchase")
        print("  and permitted another would keep the count and still be a widening.\n")


if __name__ == "__main__":
    main()

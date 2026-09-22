"""How big is the thing you just delegated? Count it.

A mandate is shown to the customer as rules: "each order at or below CHF 120",
"from a shop you have used before". Those are true and they are not an answer to
the question a person actually has, which is *how much rope did I just hand over*.

So count it. Enumerate every purchase this world can produce, put each one through
the REAL engine under the drafted mandate, and report the size of the set that
comes back approved.

    "Order our household groceries."                      595 of 595 purchases
    "...at or below CHF 120."                             145           -450
    "...from a shop I have used before."                  116            -29
    "...at or below CHF 60..."                             28            -88

Every clause removes purchases. That number is the only honest answer to "what did
that word actually do?", and it is measured rather than described.

WHY THIS IS THE RIGHT OBJECT

`optimized-apertus` is about speculative decoding: an 8B draft proposes, a 70B
target verifies, and the guarantee is that the output distribution is the target's
alone -- a bad draft changes the speed, never the answer. The same shape is the
whole architecture here, and it names the object: the **acceptance set** is our
output distribution. An agent picks where in it to go and how fast; no agent, however
compromised, can enlarge it. `research/acceptance_set.py` checks that by running
four brains -- including one with no taste at all -- over hundreds of proposals and
asserting that not one approved purchase falls outside the set.

It also gives a second, independent check on the read-back: **a word that changed no
rule cannot change the size of the set.** Cause and consequence, measured separately.

BOUNDED AND HONEST. The universe is one shop per basket, up to `MAX_LINES` lines,
from the official item and merchant catalogue. The absolute figures are a function
of that bound and mean nothing on their own -- what carries meaning is how they
MOVE when the sentence changes. Every count comes from the real engine deciding a
real event.

DECIDES NOTHING.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from itertools import combinations
from typing import Any

from .csv_data import history_csv_path, load_items, load_merchants
from .mandate import HardRule, MandateSnapshot, UncertaintyPolicy
from .policy_compiler import compile_instruction
from .state import HistoryIndex
from .witness import CARD, judge_event, snapshot

MAX_LINES = 5

# The card the counted world belongs to. The official demo card, so the familiarity
# rule carves a real piece out of the universe rather than nothing.
COUNTED_CARD = "CA0001"


@lru_cache(maxsize=1)
def familiar_merchants(card_id: str = COUNTED_CARD) -> frozenset[str]:
    """Which shops this card has actually paid before, from the SAME history file the
    engine reads.

    This was a hard-coded `frozenset({"ME0001", ..., "ME0004"})`. It happened to be
    exactly right, which is the worst state for a fact to be in: correct today,
    unmoored from its source, and silently wrong the moment the data changes. A
    policy-bearing set asserted in one place and derived in another is the shape
    every defect in `docs/ABSENCE.md` has -- here it would not have been an absence
    but a drift, and the panel would have gone on reporting a confident number about
    a world that no longer existed.
    """
    history = HistoryIndex.from_csv(history_csv_path())
    return frozenset(
        merchant for merchant in load_merchants()
        if history.is_familiar(card_id, merchant) is True)


# Kept as a module attribute because `disagreement.py` and the research modules read
# it; it is now DERIVED rather than declared.
FAMILIAR = familiar_merchants()


@lru_cache(maxsize=8)
def _world(category: str) -> tuple[tuple[str, tuple[tuple[str, str, Decimal], ...]], ...]:
    """Every basket this world can produce: one shop, up to MAX_LINES lines.

    One shop per basket because the goods physically live somewhere -- the same
    constraint a real proposal is under."""
    items = [r for r in load_items().values() if r["item_category"] == category]
    shops = [m for m, r in load_merchants().items() if r["merchant_category"] == category]
    lines = tuple(sorted(
        (r["item_id"], r["item_name"], Decimal(r["unit_price_typical_chf"])) for r in items))
    out: list[tuple[str, tuple]] = []
    for merchant in sorted(shops):
        for size in range(1, min(MAX_LINES, len(lines)) + 1):
            for combo in combinations(lines, size):
                out.append((merchant, combo))
    return tuple(out)


def _categories(rules: list[HardRule]) -> str:
    for rule in rules:
        if rule.field == "item.category" and rule.operator == "in":
            values = rule.value if isinstance(rule.value, list) else [rule.value]
            if values:
                return str(values[0])
    return "groceries"


def _count(mandate: MandateSnapshot, category: str) -> dict[str, Any]:
    counts = {"allow": 0, "review": 0, "block": 0}
    cheapest: Decimal | None = None
    for index, (merchant, combo) in enumerate(_world(category)):
        verdict = judge_event(mandate, index, merchant, category, combo, familiar=FAMILIAR)
        counts[verdict] += 1
        if verdict == "allow":
            total = sum((price for _id, _name, price in combo), Decimal("0"))
            cheapest = total if cheapest is None else min(cheapest, total)
    counts["cheapest_chf"] = float(cheapest) if cheapest is not None else None
    return counts


def _repetition(rules: list[HardRule], cheapest: float | None) -> dict[str, Any]:
    """HOW MANY TIMES, which is the half of "how much rope" that a count of purchases
    does not answer.

    A number of authorised purchases reads as a quantity of rope. It is not: without
    a rolling rule the agent may make every one of them, and then make them all again
    tomorrow. The panel that shows 116 and stops there creates exactly the false
    belief this project spends its time removing -- a correct figure that a person
    will attach to the wrong question.

    With a rolling cap the bound is real and computable: the sum over any window must
    stay under the cap, so at most `cap / cheapest authorised basket` purchases fit
    in one. Reported as the ceiling it is, not as a forecast."""
    window = next((r for r in rules
                   if r.field == "authorization.billing_amount_chf"
                   and r.scope == "period" and r.period_days), None)
    if window is None:
        return {"bounded": False, "cap_chf": None, "period_days": None,
                "most_purchases_per_period": None, "cheapest_chf": cheapest,
                "note": ("Nothing here limits how many times. The agent may make "
                         "every one of these purchases, and then make them again. "
                         "A rolling limit paces that; only revoking stops it.")}
    try:
        cap = Decimal(str(window.value))
    except (ArithmeticError, TypeError, ValueError):
        # A period rule whose value is not a number is UNKNOWN to the engine, so it
        # bounds nothing. Saying otherwise here would be the panel inventing a limit.
        return {"bounded": False, "cap_chf": None, "period_days": window.period_days,
                "most_purchases_per_period": None, "cheapest_chf": cheapest,
                "note": "This mandate's rolling limit is not a number the engine can apply."}
    most = (int(cap // Decimal(str(cheapest)))
            if cheapest and Decimal(str(cheapest)) > 0 else None)
    return {"bounded": True, "cap_chf": float(cap), "period_days": window.period_days,
            "most_purchases_per_period": most, "cheapest_chf": cheapest,
            "note": (f"At most CHF {float(cap):g} in any {window.period_days} days "
                     f"\u2014 {most} of these purchases at the cheapest, fewer at any "
                     f"other price." if most else
                     f"At most CHF {float(cap):g} in any {window.period_days} days.")}


def delegation_size(instruction: str,
                    uncertainty: UncertaintyPolicy | None = None) -> dict[str, Any]:
    """How many purchases this sentence authorises, right now, out of how many exist."""
    compiled = compile_instruction(instruction)
    rules = list(compiled.hard_rules)
    category = _categories(rules)
    mandate = snapshot(rules, uncertainty or compiled.uncertainty_policy,
                       list(compiled.unsupported_restrictions))
    counts = _count(mandate, category)
    universe = counts["allow"] + counts["review"] + counts["block"]
    return {
        "how_many_times": _repetition(rules, counts["cheapest_chf"]),
        "instruction": instruction,
        "universe": universe,
        "authorised": counts["allow"],
        "asks_you": counts["review"],
        "refused": counts["block"],
        "category": category,
        "max_lines": MAX_LINES,
        # What the figure is OF, in the payload rather than only in a docstring: a
        # count whose scope is not stated beside it is a number a reader will attach
        # to whatever they are looking at.
        "counted_over": {
            "shops": sorted({m for m, _ in _world(category)}),
            "card": COUNTED_CARD,
            "basis": (f"every basket of up to {MAX_LINES} lines that any one shop in "
                      f"the official {category} catalogue could supply"),
        },
        "share": (counts["allow"] / universe) if universe else 0.0,
    }

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

from .csv_data import load_items, load_merchants
from .mandate import HardRule, MandateSnapshot, UncertaintyPolicy
from .policy_compiler import compile_instruction
from .witness import CARD, judge_event, snapshot

MAX_LINES = 5
# Which shops this demo card has bought from before. Read by the enumeration so the
# familiarity rule carves a real piece out of the universe rather than nothing.
FAMILIAR = frozenset({"ME0001", "ME0002", "ME0003", "ME0004"})


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


def _count(mandate: MandateSnapshot, category: str) -> dict[str, int]:
    counts = {"allow": 0, "review": 0, "block": 0}
    for index, (merchant, combo) in enumerate(_world(category)):
        counts[judge_event(mandate, index, merchant, category, combo,
                           familiar=FAMILIAR)] += 1
    return counts


def delegation_size(instruction: str,
                    uncertainty: UncertaintyPolicy | None = None) -> dict[str, Any]:
    """How many purchases this sentence authorises, right now, out of how many exist."""
    compiled = compile_instruction(instruction)
    rules = list(compiled.hard_rules)
    category = _categories(rules)
    mandate = snapshot(rules, uncertainty or compiled.uncertainty_policy,
                       list(compiled.unsupported_restrictions))
    counts = _count(mandate, category)
    universe = sum(counts.values())
    return {
        "instruction": instruction,
        "universe": universe,
        "authorised": counts["allow"],
        "asks_you": counts["review"],
        "refused": counts["block"],
        "category": category,
        "max_lines": MAX_LINES,
        "share": (counts["allow"] / universe) if universe else 0.0,
    }

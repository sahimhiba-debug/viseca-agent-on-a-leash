"""Two instructions mean the same thing when they permit the same purchases.

THE GAP THIS CLOSES. `research/paraphrase_corpus.py` declares, for 40-odd rewordings
of the five official mandates, what relation a reasonable human reader would expect:

    EQUIVALENT  same constraints
    STRICTER    the variant forbids more
    WEAKER      the variant permits more
    DIFFERENT   some purchase can tell them apart

Each entry carries a reason, and the expectation is deliberately NOT derived from the
compiler's output, so the test cannot be circular. Nothing asserted any of it. A
corpus of claims with nothing checking them is a document, not a control.

WHY THE ACCEPTANCE SET IS THE RIGHT ORACLE. The obvious check is to compile both
instructions and compare the rule lists. That is the WRONG test twice over: two
different rule lists can permit exactly the same purchases (`<= 120` and `< 120.01`),
and two identical-looking lists can differ in scope or period. Worse, it asks the
compiler to grade itself.

So meaning is measured where it is observable -- in purchases:

    A(instruction) = { basket : the real engine ALLOWS it }

    EQUIVALENT  =>  A(base) == A(variant)          exactly
    STRICTER    =>  A(variant) subset-of A(base)
    WEAKER      =>  A(variant) superset-of A(base)
    DIFFERENT   =>  A(variant) != A(base)

The compiler produces the rules; the ENGINE produces the set. An independent oracle,
and the one the customer actually experiences.

TWO FAILURE MODES, AND ONE OF THEM IS DANGEROUS

    FALSE DISTINCTION   declared EQUIVALENT, sets differ.
                        The compiler is sensitive to wording that does not matter.
                        Annoying; makes the product feel arbitrary.

    FALSE EQUIVALENCE   declared DIFFERENT or STRICTER, sets identical.
                        The compiler is BLIND to wording that does matter. When the
                        customer was trying to tighten something, they tightened
                        nothing and were not told.

The second is the one that costs money, and it is reported separately.

Run:  python3 -m research.semantic_stability
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from itertools import combinations  # noqa: E402

import research.shopping_agent as sa  # noqa: E402
from research.paraphrase_corpus import (  # noqa: E402
    CASES, DIFFERENT, EQUIVALENT, STRICTER, WEAKER,
)
from tests.helpers import make_event, make_mandate  # noqa: E402
from wallet_control.csv_data import history_csv_path  # noqa: E402
from wallet_control.decision_engine import evaluate_authorization  # noqa: E402
from wallet_control.mandate import UncertaintyPolicy  # noqa: E402
from wallet_control.policy_compiler import compile_instruction  # noqa: E402
from wallet_control.state import HistoryIndex, RunState  # noqa: E402

CARD = "CA0001"
MAX_LINES = 2          # enough to separate basket-composition rules; see `world()`
AT_MERCHANTS = 6       # shops per category, to keep the world honest but bounded


def world() -> list[tuple[str, tuple]]:
    """Baskets spanning EVERY category, not just groceries.

    The corpus covers five mandates about groceries, running shoes, clothing and a
    monitor, so a grocery-only world would score four of them on an empty set and
    call every pair equivalent. Two lines per basket rather than five: the rules
    these instructions produce are about price, category, familiarity, size and
    return terms, and none of them needs a third line to be observable -- while the
    basket count grows quadratically.
    """
    shop = sa.CatalogueShop()
    by_merchant: dict[str, list] = {}
    for offer in shop.search(None):
        by_merchant.setdefault(offer.merchant, []).append(offer)
    out: list[tuple[str, tuple]] = []
    for merchant in sorted(by_merchant)[:AT_MERCHANTS * 4]:
        offers = sorted(by_merchant[merchant], key=lambda o: o.item_id)
        for size in range(1, min(MAX_LINES, len(offers)) + 1):
            for combo in combinations(offers, size):
                out.append((merchant, combo))
    return out


_WORLD: list[tuple[str, tuple]] | None = None


def _the_world():
    global _WORLD
    if _WORLD is None:
        _WORLD = world()
    return _WORLD


def _history():
    return HistoryIndex.from_csv(history_csv_path())


def _event(mandate, merchant: str, offers: tuple, index: int) -> dict[str, Any]:
    total = float(sum(o.unit_price for o in offers))
    return make_event(
        mandate=mandate, authorization_id=f"AU_SEM_{index}", amount=total,
        merchant_id=merchant, merchant_category=offers[0].category,
        card_id=CARD, order_returnable="true",
        items=[{"line_no": i + 1, "item_id": o.item_id, "item_name": o.name,
                "item_category": o.category, "quantity": 1,
                "unit_price": float(o.unit_price), "currency": "CHF",
                "item_details": (f"returns accepted within {o.stated_return_days} days"
                                 if o.stated_return_days else "")}
               for i, o in enumerate(offers)])


def acceptance_set(instruction: str) -> frozenset[tuple[str, tuple[str, ...]]]:
    """Every basket the REAL ENGINE allows under this instruction, freshly judged."""
    compiled = compile_instruction(instruction)
    mandate = make_mandate(instruction=instruction,
                           uncertainty_policy=compiled.uncertainty_policy,
                           hard_rules=list(compiled.hard_rules), card_id=CARD)
    history = _history()
    allowed = set()
    for index, (merchant, offers) in enumerate(_the_world()):
        state = RunState(history=history, card_id=CARD)
        if evaluate_authorization(_event(mandate, merchant, offers, index),
                                  mandate, state).decision == "allow":
            allowed.add((merchant, tuple(o.item_id for o in offers)))
    return frozenset(allowed)


def check(relation: str, base: frozenset, variant: frozenset) -> str | None:
    """None when the relation holds; otherwise the name of how it failed."""
    if relation == EQUIVALENT:
        return None if base == variant else "false distinction"
    if relation == STRICTER:
        if variant == base:
            return "false equivalence"
        return None if variant <= base else "not stricter"
    if relation == WEAKER:
        if variant == base:
            return "false equivalence"
        return None if variant >= base else "not weaker"
    if relation == DIFFERENT:
        return None if variant != base else "false equivalence"
    raise ValueError(relation)


def sweep():
    cache: dict[str, frozenset] = {}

    def setof(text: str) -> frozenset:
        if text not in cache:
            cache[text] = acceptance_set(text)
        return cache[text]

    rows = []
    for base_text, variant_text, relation, why in CASES:
        base, variant = setof(base_text), setof(variant_text)
        rows.append({
            "relation": relation, "why": why,
            "base": base_text, "variant": variant_text,
            "n_base": len(base), "n_variant": len(variant),
            "failure": check(relation, base, variant),
            "gained": len(variant - base), "lost": len(base - variant),
        })
    return rows


def main() -> None:
    rows = sweep()
    bad = [r for r in rows if r["failure"]]
    dangerous = [r for r in bad if r["failure"] == "false equivalence"]

    print(f"\n  SEMANTIC STABILITY -- {len(rows)} declared relations, judged as SETS OF")
    print(f"  PURCHASES by the real engine over {len(_the_world()):,} baskets\n")

    for relation in (EQUIVALENT, STRICTER, WEAKER, DIFFERENT):
        group = [r for r in rows if r["relation"] == relation]
        held = len([r for r in group if not r["failure"]])
        print(f"    {relation:11s} {held:>3} / {len(group):<3} held")

    print(f"\n  false equivalence (the compiler is BLIND to wording that matters): "
          f"{len(dangerous)}")
    print(f"  false distinction (sensitive to wording that does not):            "
          f"{len([r for r in bad if r['failure'] == 'false distinction'])}")
    print(f"  wrong direction:                                                   "
          f"{len([r for r in bad if r['failure'] in ('not stricter', 'not weaker')])}\n")

    for row in bad[:20]:
        print(f"    [{row['failure']}] declared {row['relation']}  "
              f"|A| {row['n_base']} -> {row['n_variant']}  (+{row['gained']}/-{row['lost']})")
        print(f"       why: {row['why']}")
        print(f"       {row['variant'][:96]}")
    print()


if __name__ == "__main__":
    main()

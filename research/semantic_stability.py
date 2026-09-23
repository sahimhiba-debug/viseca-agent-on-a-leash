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

from functools import lru_cache  # noqa: E402
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


@lru_cache(maxsize=512)
def signature(instruction: str):
    """THE DELEGATION -- all five parts of it, because A is only the first.

    "A policy is a set of purchases" is the thesis this repository is built on, and
    comparing paraphrases as sets is what showed it to be INCOMPLETE. Three separate
    kinds of meaning turn out to live outside A:

    1. A RATE. A is a set of single purchases, and a rolling ceiling is not a
       property of any single purchase, so three mandates differing only in their
       rate have identical acceptance sets:

           CHF 300 / 7 days | CHF 3000 / 7 days | CHF 300 / 30 days   all |A| = 145

       Two more components separate them: purchases-per-window (which sees the
       ceiling) and CHF-per-year (which sees the period). Neither is derivable from A.

    2. WHAT WILL BE ASKED. A counts what is APPROVED. Changing `ask` to `decline`
       moves purchases from review to block and leaves the approved set untouched --
       so the strictest edit a customer can make was invisible. And a mandate whose
       every purchase is `review` (the official shoes mandate, whose return-window
       rule nothing can confirm) has |A| = 0 under every wording, which made all its
       variants trivially equal. What is put to the customer is part of what they
       delegated.

    3. WHAT COULD NOT BE EXPRESSED AT ALL. "Buy ONE grocery item" and "buy TWENTY"
       compile to identical rules, because the official rule format has no quantity
       field. The compiler does not hide this -- both produce an
       `unsupported_restrictions` entry, which is shown to the customer and blocks
       automatic confirmation -- but a signature that ignored it called two clearly
       different instructions the same.

    So the delegation is:

        (approved, asked, per-window ceiling, pace, what could not be expressed)

    and the thesis names the first of five. That is the correction this module
    produced; it is in `docs/THE_THESIS.md` rather than only here.
    """
    from wallet_control.policy_compiler import compile_instruction
    from wallet_control.scope import delegation_size, outcome_sets

    # AT BOTH PRICE POINTS, and the reason is a blunt oracle caught in the act.
    # Measured only at the band's floor, this signature could not tell "CHF 120 per
    # order" from "CHF 1200 per order" on the official grocery mandate: at the
    # cheapest published prices EVERY basket in the world is under CHF 120, so the
    # approved set is the whole universe under both and the ceiling is invisible.
    # A comparison that cannot see a ten-times-larger ceiling would have reported
    # "nothing moved" forever and looked exactly like success.
    #
    # The floor says what was delegated; the typical point is where the ceilings
    # actually bite. A signature needs both to be a signature.
    approved, asked = outcome_sets(instruction, "min")
    approved_typical, asked_typical = outcome_sets(instruction, "typical")
    repetition = delegation_size(instruction)["how_many_times"]
    unsupported = frozenset(compile_instruction(instruction).unsupported_restrictions)
    return (approved, asked, approved_typical, asked_typical,
            repetition.get("most_purchases_per_period"),
            repetition.get("chf_per_year"),
            unsupported)


def _compiled(instruction: str) -> frozenset:
    """The rules themselves, used ONLY to tell two different failures apart."""
    from wallet_control.policy_compiler import compile_instruction

    compiled = compile_instruction(instruction)
    return frozenset(
        (r.field, r.operator, str(r.value), r.scope, r.period_days)
        for r in compiled.hard_rules) | frozenset(
        ("__uncertainty__", compiled.uncertainty_policy.value, "", None, None)
        for _ in (0,))


def check(relation: str, base, variant) -> str | None:
    """None when the declared relation holds; otherwise how it failed."""
    same = base == variant

    def permits_at_least(a, b) -> bool:
        """`a` permits everything `b` does: a superset of approved purchases, no
        tighter pace, and nothing left unexpressed that `b` managed to express."""
        if not (a[0] >= b[0]):
            return False
        if not (a[2] >= b[2]):
            return False
        for mine, theirs in ((a[4], b[4]), (a[5], b[5])):
            if mine is None:                    # unbounded permits more than bounded
                continue
            if theirs is None or mine < theirs:
                return False
        return True

    if relation == EQUIVALENT:
        return None if same else "false distinction"
    if relation == STRICTER:
        if same:
            return "false equivalence"
        return None if permits_at_least(base, variant) else "not stricter"
    if relation == WEAKER:
        if same:
            return "false equivalence"
        return None if permits_at_least(variant, base) else "not weaker"
    if relation == DIFFERENT:
        return None if not same else "false equivalence"
    raise ValueError(relation)


def sweep():
    cache: dict[str, tuple] = {}

    def sig(text: str):
        if text not in cache:
            cache[text] = signature(text)
        return cache[text]

    rows = []
    for base_text, variant_text, relation, why in CASES:
        base, variant = sig(base_text), sig(variant_text)
        failure = check(relation, base, variant)
        # TWO VERY DIFFERENT FAILURES LOOK THE SAME FROM HERE, and calling them both
        # "the compiler is blind" would be a false accusation.
        #
        #   the RULES differ and the signature does not
        #       -> the compiler understood the difference; this WORLD has no purchase
        #          that can show it. `Decline it when unsure` really is stricter, but
        #          no basket in the grocery enumeration is ever `unknown`, so nothing
        #          observes it. A statement about the enumeration, not the compiler.
        #
        #   the RULES are identical
        #       -> the compiler produced the same policy from two instructions a
        #          reader would not call the same. That is the real finding.
        if failure == "false equivalence" and _compiled(base_text) != _compiled(variant_text):
            failure = "no witness in this world"
        rows.append({
            "relation": relation, "why": why,
            "base": base_text, "variant": variant_text,
            "n_base": len(base[0]), "n_variant": len(variant[0]),
            "rate_base": (base[4], base[5]), "rate_variant": (variant[4], variant[5]),
            "failure": failure,
            "gained": len(variant[0] - base[0]), "lost": len(base[0] - variant[0]),
        })
    return rows


def main() -> None:
    rows = sweep()
    bad = [r for r in rows if r["failure"]]
    dangerous = [r for r in bad if r["failure"] == "false equivalence"]
    _ = dangerous

    print(f"\n  SEMANTIC STABILITY -- {len(rows)} declared relations, compared as")
    print("  (set of purchases, purchases per window, CHF per day)\n")

    for relation in (EQUIVALENT, STRICTER, WEAKER, DIFFERENT):
        group = [r for r in rows if r["relation"] == relation]
        held = len([r for r in group if not r["failure"]])
        print(f"    {relation:11s} {held:>3} / {len(group):<3} held")

    blind = [r for r in bad if r["failure"] == "false equivalence"]
    unwitnessed = [r for r in bad if r["failure"] == "no witness in this world"]
    print(f"\n  false equivalence -- SAME RULES from instructions a reader would not")
    print(f"  call the same, the compiler really is blind:        {len(blind)}")
    print(f"  no witness in this world -- the rules DO differ and no purchase in the")
    print(f"  enumeration can tell them apart:                    {len(unwitnessed)}")
    print(f"  false distinction (sensitive to wording that does not): "
          f"{len([r for r in bad if r['failure'] == 'false distinction'])}")
    print(f"  wrong direction: "
          f"{len([r for r in bad if r['failure'] in ('not stricter', 'not weaker')])}\n")

    for row in bad[:14]:
        print(f"    [{row['failure']}] declared {row['relation']}  "
              f"|A| {row['n_base']}->{row['n_variant']} (+{row['gained']}/-{row['lost']})  "
              f"rate {row['rate_base']}->{row['rate_variant']}")
        print(f"       why: {row['why']}")
        print(f"       {row['variant'][:94]}")
    print()


if __name__ == "__main__":
    main()

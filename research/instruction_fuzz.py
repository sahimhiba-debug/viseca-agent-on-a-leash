"""Perturb the customer's sentence in ways that do not change its meaning.

WHY. The compiler was found to pair the wrong two numbers in

    "Keep each order at or below CHF 120, and keep the total across any seven days
     at or below CHF 300."

while compiling the OFFICIAL wording of the same instruction correctly -- which says
"including delivery" and thereby pushes a lazy regex past its character budget. The
compiler was right on the benchmark and wrong on a two-word paraphrase of it.

That was found by hand. This is the method it implies: take each official
instruction, apply edits a reader would call meaning-preserving, and check that the
DELEGATION does not move. It is mutation testing applied to the input rather than to
the code, and it explores a space the hand-written `paraphrase_corpus` cannot.

THE ORACLE IS THE ENGINE, NOT THE COMPILER. Two rule lists can differ and permit
exactly the same purchases, and comparing rule lists asks the compiler to grade its
own output. So each variant is compared on the five-part delegation signature --
approved set, asked set, per-window ceiling, annual exposure, and what could not be
expressed -- from `research.semantic_stability`.

EVERY TRANSFORMATION CARRIES ITS JUSTIFICATION, because "meaning-preserving" is a
claim about English and not a fact about strings. A transformation that is not
actually meaning-preserving would produce a false alarm, which is worse than no
alarm: it teaches the reader to ignore the tool. Where a rewrite is only SOMETIMES
safe it is applied only where its precondition holds.

Run:  python3 -m research.instruction_fuzz
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.paraphrase_corpus import OFFICIAL  # noqa: E402
from research.semantic_stability import signature  # noqa: E402

Rewrite = tuple[str, Callable[[str], str | None], str]


def _swap_around_and(text: str) -> str | None:
    """"Keep A, and keep B." -> "Keep B, and keep A." Conjunction is commutative;
    two independent restrictions do not depend on the order they are written in."""
    match = re.search(r"(?P<a>Keep [^.]+?), and (?P<b>keep [^.]+?)\.", text)
    if not match:
        return None
    a, b = match.group("a"), match.group("b")
    swapped = f"{b[0].upper() + b[1:]}, and {a[0].lower() + a[1:]}."
    return text[:match.start()] + swapped + text[match.end():]


def _comma_to_semicolon(text: str) -> str | None:
    """", and " -> "; " joins the same two clauses with different punctuation."""
    return text.replace(", and ", "; ", 1) if ", and " in text else None


def _comma_to_full_stop(text: str) -> str | None:
    """", and keep X" -> ". Keep X" -- two sentences say what one sentence said."""
    match = re.search(r", and (?P<rest>keep )", text)
    if not match:
        return None
    return text[:match.start()] + ". " + match.group("rest").capitalize() + text[match.end():]


def _drop_including_delivery(text: str) -> str | None:
    """Removing "including delivery" removes a clarification of WHICH amount is
    meant, not a restriction. The engine reads `billing_amount_chf`, which includes
    the delivery fee either way -- so this cannot change what is permitted, and it is
    the exact edit that exposed the pairing bug."""
    return text.replace(" including delivery", "", 1) if " including delivery" in text else None


def _drop_for_delivery(text: str) -> str | None:
    """"for delivery" describes the errand, not a constraint the format can express."""
    return text.replace(" for delivery", "", 1) if " for delivery" in text else None


def _at_or_below_to_no_more_than(text: str) -> str | None:
    """"at or below CHF X" and "no more than CHF X" are the same inclusive bound.
    Both are in the compiler's own documented vocabulary."""
    return text.replace("at or below CHF", "no more than CHF") if "at or below CHF" in text else None


def _at_or_below_to_or_less(text: str) -> str | None:
    """"at or below CHF X" -> "CHF X or less", the same inclusive bound again."""
    if "at or below CHF" not in text:
        return None
    return re.sub(r"at or below CHF (\d[\d.,]*\d|\d)", r"CHF \1 or less", text)


def _double_space(text: str) -> str | None:
    """Whitespace is not meaning. The compiler normalises it; this checks that it
    still does after every other change made to it."""
    return text.replace(". ", ".  ", 1) if ". " in text else None


def _seven_to_7(text: str) -> str | None:
    """"seven days" and "7 days" are the same window."""
    return text.replace("seven days", "7 days", 1) if "seven days" in text else None


REWRITES: list[Rewrite] = [
    ("swap the two clauses around 'and'", _swap_around_and,
     "conjunction is commutative"),
    ("', and' -> ';'", _comma_to_semicolon, "same two clauses, different punctuation"),
    ("', and keep' -> '. Keep'", _comma_to_full_stop, "one sentence becomes two"),
    ("drop 'including delivery'", _drop_including_delivery,
     "clarifies which amount is meant; the engine reads billing_amount_chf either way"),
    ("drop 'for delivery'", _drop_for_delivery, "describes the errand, not a rule"),
    ("'at or below' -> 'no more than'", _at_or_below_to_no_more_than,
     "the same inclusive bound, both in the documented vocabulary"),
    ("'at or below CHF X' -> 'CHF X or less'", _at_or_below_to_or_less,
     "the same inclusive bound"),
    ("double space after a full stop", _double_space, "whitespace is not meaning"),
    ("'seven days' -> '7 days'", _seven_to_7, "the same window"),
]


def sweep():
    rows = []
    for scenario, original in sorted(OFFICIAL.items()):
        base = signature(original)
        for name, rewrite, why in REWRITES:
            variant = rewrite(original)
            if variant is None or variant == original:
                continue
            moved = signature(variant) != base
            rows.append({"scenario": scenario, "rewrite": name, "why": why,
                         "variant": variant, "moved": moved,
                         "before": (len(base[0]), len(base[2]), base[4], base[5]),
                         "after": (len(signature(variant)[0]), len(signature(variant)[2]),
                                   signature(variant)[4], signature(variant)[5])})
    return rows


def main() -> None:
    rows = sweep()
    moved = [r for r in rows if r["moved"]]
    print(f"\n  MEANING-PRESERVING REWRITES OF THE FIVE OFFICIAL INSTRUCTIONS\n")
    print(f"  {len(rows)} rewrites applied across {len(OFFICIAL)} instructions\n")
    if moved:
        print(f"  THE DELEGATION MOVED on {len(moved)} of them:\n")
        for row in moved:
            print(f"    {row['scenario']}  {row['rewrite']}")
            print(f"      why it should not have: {row['why']}")
            print(f"      (approved at floor, approved at typical, per-window, CHF/yr)")
            print(f"        before {row['before']}")
            print(f"        after  {row['after']}")
            print(f"      {row['variant'][:96]}\n")
    else:
        print("  None of them moved it. The compiler is not reading the benchmark's")
        print("  exact wording -- at least not along any of these axes.\n")


if __name__ == "__main__":
    main()

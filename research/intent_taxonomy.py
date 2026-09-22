"""An INDEPENDENT corpus of customer restrictions, and what the compiler does with them.

Deliberately not derived from the compiler's own vocabulary. The phrases below were
written from a taxonomy of what a person might plausibly say when delegating a
purchase -- amount, quantity, time, merchant, product, returnability, basket,
negation, compound and adversarial phrasing -- and only then run through
`compile_instruction`. A corpus written by reading the regexes would measure the
regexes.

THE ONE INVARIANT THAT MATTERS

    No restrictive statement may disappear silently.

A restriction the compiler cannot represent is SAFE as long as the customer is told
before they confirm -- `unsupported_restrictions` blocks automatic confirmation. A
restriction that vanishes with no rule and no warning is the worst failure this
system can have, because the customer believes they said something the wallet is
not enforcing.

CLASSIFICATION

    EXACT                    a rule of the right kind was produced
    UNSUPPORTED-SAFE         no rule, and the customer is told
    SILENTLY-WEAKENED        no rule, and the customer is NOT told   <-- critical
    STRENGTHENED             a rule stricter than what was said      <-- also wrong
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wallet_control.policy_compiler import compile_instruction     # noqa: E402

BASE = "Order our household groceries. "

# (phrase, dimension, the KIND of rule a correct compiler would produce, or None
#  when the vocabulary genuinely cannot express it)
CORPUS: list[tuple[str, str, str | None]] = [
    # ---------------------------------------------------------------- AMOUNT
    ("Keep each order at or below CHF 120.", "amount", "amount"),
    ("Never spend more than CHF 120 on one order.", "amount", "amount"),
    ("Nothing over CHF 120, please.", "amount", "amount"),
    ("Don't let any single order exceed CHF 120.", "amount", "amount"),
    ("Cap each order at CHF 120.", "amount", "amount"),
    ("Each order must stay under CHF 120.", "amount", "amount"),
    ("Keep the price below one hundred and twenty francs.", "amount", "amount"),
    ("No order above CHF 120.", "amount", "amount"),
    ("I don't want to pay more than CHF 120 at a time.", "amount", "amount"),
    ("Anything up to CHF 120 is fine.", "amount", "amount"),
    # ---------------------------------------------------------------- PERIOD
    ("Keep the total across any seven days at or below CHF 300.", "period", "period"),
    ("No more than CHF 300 a week.", "period", "period"),
    ("Spend at most CHF 300 in any seven-day window.", "period", "period"),
    ("Weekly spending must not exceed CHF 300.", "period", "period"),
    # ------------------------------------------------------------- MERCHANT
    ("Only from a shop I have used before.", "merchant", "merchant"),
    ("Buy exclusively from sellers I have bought from previously.", "merchant", "merchant"),
    ("Don't use a seller I've never paid.", "merchant", "merchant"),
    ("Stick to shops on my history.", "merchant", "merchant"),
    # -------------------------------------------------------------- RETURNS
    ("Only if it can be returned within 14 days.", "returns", "returns"),
    ("It must be refundable for at least a fortnight.", "returns", "returns"),
    ("Nothing marked final sale.", "returns", "returns"),
    ("I want to be able to send it back.", "returns", "returns"),
    # --------------------------------------------------------------- BASKET
    ("Don't add anything I didn't ask for.", "basket", "basket"),
    ("Only the things on my list, nothing else.", "basket", "basket"),
    ("No extras.", "basket", "basket"),
    # ------------------------------------------------------------- QUANTITY
    ("Buy exactly one.", "quantity", None),
    ("No more than two of anything.", "quantity", None),
    ("Just a single pack.", "quantity", None),
    # ----------------------------------------------------------------- TIME
    ("Stop after Friday.", "time", None),
    ("Only until the end of the month.", "time", None),
    ("Don't buy anything after next week.", "time", None),
    # ---------------------------------------------------------------- TOTAL
    ("Spend no more than CHF 500 in total.", "total", None),
    ("CHF 500 overall, and not a franc more.", "total", None),
    ("The whole job should cost under CHF 500.", "total", None),
    # ------------------------------------------------------------ ADVERSARIAL
    ("Groceries only, and by the way CHF 120 is my limit.", "compound", "amount"),
    ("I'd rather not go above CHF 120, though use your judgement.", "hedged", "amount"),
    ("Up to CHF 400 for electronics, but groceries stay under CHF 120.", "nested", "amount"),
    ("CHF 120 per order. Actually, make it CHF 80.", "revised", "amount"),
    ("Unless it's on offer, keep it under CHF 120.", "exception", "amount"),
]

KIND = {
    "amount": lambda r: r.field == "authorization.billing_amount_chf" and r.scope == "purchase",
    "period": lambda r: r.field == "authorization.billing_amount_chf" and r.scope == "period",
    "merchant": lambda r: r.field == "merchant.familiar",
    "returns": lambda r: r.field == "order.return_window_days",
    "basket": lambda r: r.field == "item.unrequested_present",
}


def classify(phrase: str, expected_kind: str | None) -> tuple[str, str]:
    compiled = compile_instruction(BASE + phrase)
    rules = list(compiled.hard_rules)
    told = bool(compiled.unsupported_restrictions) or bool(compiled.open_questions)

    if expected_kind is None:
        # the vocabulary genuinely cannot express it: the customer must be TOLD
        return ("UNSUPPORTED-SAFE", "") if told else (
            "SILENTLY-WEAKENED", "no rule, and nothing shown to the customer")

    produced = any(KIND[expected_kind](r) for r in rules)
    if produced:
        return "EXACT", ""
    return ("UNSUPPORTED-SAFE", "no rule of the expected kind, but the customer is told") \
        if told else ("SILENTLY-WEAKENED", f"expected a {expected_kind} rule; none, and no warning")


def main() -> int:
    counts: dict[str, int] = {}
    critical: list[tuple[str, str, str]] = []
    print(f"{len(CORPUS)} independently written customer restrictions\n")
    for phrase, dimension, expected in CORPUS:
        verdict, detail = classify(phrase, expected)
        counts[verdict] = counts.get(verdict, 0) + 1
        flag = "  <--" if verdict == "SILENTLY-WEAKENED" else ""
        print(f"  {verdict:18s} {dimension:10s} {phrase[:56]:58s}{flag}")
        if verdict == "SILENTLY-WEAKENED":
            critical.append((dimension, phrase, detail))

    print("\n  " + "   ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if critical:
        print(f"\n  {len(critical)} SILENTLY WEAKENED -- the customer believes they said")
        print("  something the wallet is not enforcing, and was never told:")
        for dimension, phrase, detail in critical:
            print(f"     [{dimension}] {phrase}\n         {detail}")
    else:
        print("\n  0 silently weakened. Every restriction either became a rule or was")
        print("  shown to the customer before they could confirm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

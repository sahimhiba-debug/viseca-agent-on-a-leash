#!/usr/bin/env python3
"""An independent corpus of restrictive customer phrasings.

Written by enumerating ways a PERSON states a restriction -- amount, merchant,
category, quantity, time, returns, add-ons -- not by reading the compiler's patterns.
That distinction is the whole point: the previous optimiser generated instructions
from the vocabulary the compiler already knew, so it measured the compiler against
itself and reported near-total coverage where the real figure was about half.

Each phrasing is classified by what the compiler did with it:

  RECOGNISED   a hard rule of the intended kind exists
  UNSUPPORTED  no rule, but the customer is told (blocks auto-confirmation)
  SILENT       no rule and no warning  <-- the only failure that matters
  WRONG        a rule exists but of the wrong KIND or scope

    python3 scripts/run_intent_corpus.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wallet_control.policy_compiler import compile_instruction  # noqa: E402

AMOUNT = [
    "for CHF 40 or less", "up to CHF 40", "no more than CHF 40", "not more than CHF 40",
    "never more than CHF 40", "never spend more than CHF 40", "at most CHF 40",
    "at or below CHF 40", "under CHF 40", "below CHF 40", "less than CHF 40",
    "a maximum of CHF 40", "maximum of CHF 40", "max CHF 40", "CHF 40 max",
    "CHF 40 maximum", "capped at CHF 40", "limited to CHF 40", "no higher than CHF 40",
    "nothing over CHF 40", "nothing above CHF 40", "do not exceed CHF 40",
    "not exceeding CHF 40", "don't go over CHF 40", "within CHF 40",
    "up to a limit of CHF 40", "a CHF 40 cap", "with a CHF 40 limit", "CHF 40 ceiling",
    "budget CHF 40 per order", "worth up to CHF 40", "costing CHF 40 or less",
    "priced at CHF 40 or below", "stay under CHF 40", "keep it below CHF 40",
    "keeping each order under CHF 40", "spending at most CHF 40", "pay no more than CHF 40",
    "for a maximum of CHF 40", "for up to CHF 40", "at a maximum of CHF 40",
    "for CHF 40 or below", "with a maximum of CHF 40",
]
PERIOD = [
    "up to CHF 200 per week", "up to CHF 200 a week", "up to CHF 200 each week",
    "no more than CHF 200 per month", "at most CHF 200 a month", "CHF 200 per day",
    "CHF 200 in any 7 days", "CHF 200 across any seven days", "CHF 200 per 14 days",
    "no more than CHF 200 per fortnight", "up to CHF 200 a year",
    "at most CHF 200 each month", "no more than CHF 200 in any 30 days",
    "up to CHF 200 every week", "capped at CHF 200 per week",
]
MERCHANT = [
    "from a shop I use regularly", "from a shop I have used before",
    "from a seller I have bought from before", "from shops I've used before",
    "only from shops I have used before", "from a familiar shop",
    "from a merchant I have used before", "from a shop that is one I have used before",
    "from a previously-used shop", "from a known seller",
    "only from sellers I have bought from before", "from merchants I use regularly",
]
CATEGORY = [
    "only groceries", "groceries only", "buy clothing", "buy electronics",
    "only from a specialist sports retailer", "from an electronics retailer",
    "from a supermarket", "from a grocery shop",
]
ADDONS = [
    "Do not add anything I did not ask for.", "Only add things I asked for.",
    "Do not buy unrequested items.", "Never add extras.", "Buy only requested items.",
    "No extras.", "Do not add extras.", "Nothing else.",
]
SESSION = [
    "Pause anything that looks like someone other than me is driving the session.",
    "Stop if it looks like not me.",
    "Pause if someone other than me is driving the session.",
]
RETURNS = [
    "only if it can be returned within 14 days", "returnable within 14 days or more",
    "only if returns are accepted within 30 days", "it must be returnable within 14 days",
]
QUANTITY = ["buy one item", "buy exactly one item", "buy at most one item", "buy up to three items"]
TOTAL_AND_TIME = [
    "no more than CHF 500 in total", "CHF 500 overall", "spend CHF 500 altogether",
    "stop after Friday", "finish by tomorrow", "until next Monday",
]

# (label, phrasings, expected rule field, expected scope, expected verdict)
#
# The last column is what SHOULD happen, and it is not always RECOGNISED. Quantity,
# an overall total and an end date are not expressible in the official vocabulary at
# all, so the correct outcome for them is UNSUPPORTED -- no rule, and the customer
# told. Scoring those as RECOGNISED would report 100% coverage of a vocabulary that
# cannot represent them, which is the kind of number this corpus exists to prevent.
GROUPS = [
    ("amount (per order)", AMOUNT, "authorization.billing_amount_chf", "purchase", "RECOGNISED"),
    ("amount (period)", PERIOD, "authorization.billing_amount_chf", "period", "RECOGNISED"),
    ("merchant familiarity", MERCHANT, "merchant.familiar", None, "RECOGNISED"),
    ("item / merchant category", CATEGORY, "item.category", None, "RECOGNISED"),
    ("no add-ons", ADDONS, "item.unrequested_present", None, "RECOGNISED"),
    ("return window", RETURNS, "order.return_window_days", None, "RECOGNISED"),
    ("session integrity", SESSION, "session.integrity_risk", None, "RECOGNISED"),
    ("quantity (inexpressible)", QUANTITY, None, None, "UNSUPPORTED"),
    ("overall total / end date (inexpressible)", TOTAL_AND_TIME, None, None, "UNSUPPORTED"),
]


def _classify(phrase: str, field: str | None, scope: str | None) -> str:
    if phrase.endswith("."):
        instruction = f"Buy groceries for CHF 40 or less. {phrase} Ask me when uncertain."
    else:
        instruction = f"Buy groceries {phrase}. Ask me when uncertain."
    compiled = compile_instruction(instruction)
    if field is not None:
        matching = [
            r for r in compiled.hard_rules
            if (r.field == field or (field == "item.category" and r.field == "merchant.category"))
            and (scope is None or r.scope == scope)
        ]
        if matching:
            return "RECOGNISED"
        if [r for r in compiled.hard_rules if r.field == field] and scope is not None:
            return "WRONG"
    return "UNSUPPORTED" if compiled.unsupported_restrictions or compiled.open_questions else "SILENT"


def main() -> int:
    total = {"RECOGNISED": 0, "UNSUPPORTED": 0, "SILENT": 0, "WRONG": 0}
    print(f"{'group':42s} {'n':>4s}  recognised  unsupported  silent  wrong")
    print("-" * 92)
    silent_examples = []
    mismatches = []
    for name, phrases, field, scope, expected in GROUPS:
        counts = {"RECOGNISED": 0, "UNSUPPORTED": 0, "SILENT": 0, "WRONG": 0}
        for phrase in phrases:
            verdict = _classify(phrase, field, scope)
            counts[verdict] += 1
            total[verdict] += 1
            if verdict in ("SILENT", "WRONG"):
                silent_examples.append((verdict, name, phrase))
            elif verdict != expected:
                mismatches.append((name, phrase, expected, verdict))
        print(f"{name:42s} {len(phrases):>4d}  {counts['RECOGNISED']:>10d}  {counts['UNSUPPORTED']:>11d}"
              f"  {counts['SILENT']:>6d}  {counts['WRONG']:>5d}")

    n = sum(total.values())
    print("-" * 92)
    print(f"{'TOTAL':42s} {n:>4d}  {total['RECOGNISED']:>10d}  {total['UNSUPPORTED']:>11d}"
          f"  {total['SILENT']:>6d}  {total['WRONG']:>5d}")
    print(f"\nrecognised: {100*total['RECOGNISED']/n:.0f}%   "
          f"silently lost: {total['SILENT']}   incorrectly interpreted: {total['WRONG']}")
    if silent_examples:
        print("\nnot recognised and not reported, or interpreted as the wrong kind:")
        for verdict, group, phrase in silent_examples:
            print(f"  [{verdict}] {group}: {phrase!r}")
    if mismatches:
        print("\nphrasings whose outcome is not what the group expects:")
        for group, phrase, expected, got in mismatches:
            print(f"  {group}: {phrase!r} expected {expected}, got {got}")
    print("\nUNSUPPORTED is a SAFE outcome: no rule was created and the customer is told,")
    print("which blocks automatic confirmation. SILENT and WRONG are the failures.")
    return 1 if (total["SILENT"] or total["WRONG"] or mismatches) else 0


if __name__ == "__main__":
    raise SystemExit(main())

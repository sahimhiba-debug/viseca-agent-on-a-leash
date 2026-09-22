"""How do you find the paraphrase you did not think of?

RESEARCH APPARATUS. Never imported by `src/wallet_control/`.

THE TREADMILL

`policy_compiler.py` recognises restrictions by phrase pattern, and it already has
a second layer for what it misses -- `_COVERAGE_MARKERS`, which detects restrictive
language of a KIND and says so when no rule of that kind exists. Its own comment is
the honest statement of why that is not enough:

    "Broadening the patterns fixes the paraphrases we happened to think of, and
     nothing else; there are indefinitely many ways to write a restriction."

But the marker list is a vocabulary too, and it is the SAME vocabulary. The return
marker is `\\breturn(?:ed|able|s)?\\b`, so "I can send it back within 14 days"
produces no rule, no open question, and no trace at all.

    A COVERAGE CHECKER BUILT FROM THE SAME VOCABULARY AS THE THING IT CHECKS
    CANNOT SEE THE VOCABULARY'S OWN GAPS.

Measured below over ordinary phrasings of restrictions this engine already supports.

THE DIFFERENT AXIS

Do not ask what the words mean. Ask whether they did anything: delete one word,
compile again, and see whether the policy moved. That is defined as the complement
of whatever the compiler matched, so it cannot inherit the compiler's blind spot.

WHAT THIS FILE REPORTS, INCLUDING THE TWO ATTACKS THAT LANDED

Both are here because both are real, and the response to each was to weaken the
claim rather than to quietly drop the test.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "src"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from wallet_control.csv_data import load_scenario_catalogue        # noqa: E402
from wallet_control.policy_compiler import compile_instruction     # noqa: E402
from wallet_control.unconsumed import marks, unenforced_clauses    # noqa: E402

BASE = "Order groceries at or below CHF 120. "

# Ordinary ways to write a restriction this engine ALREADY SUPPORTS as a concept.
# Whether each is genuinely lost is established by compiling it and looking, not by
# asking the detector -- see `is_silently_lost`.
NATURAL = [
    ("returns", "I can send it back within 14 days."),
    ("returns", "Only things that can be sent back within 14 days."),
    ("returns", "They must be exchangeable within 14 days."),
    ("returns", "Nothing final-sale."),
    ("returns", "No final sale items."),
    ("familiar", "Stick to shops we already deal with."),
    ("familiar", "Only from our usual supplier."),
    ("familiar", "Nowhere new."),
    ("familiar", "No first-time sellers."),
    ("add-ons", "Nothing extra in the basket."),
    ("add-ons", "Do not slip anything else in."),
    ("add-ons", "Just what is on the list."),
    ("add-ons", "No substitutions."),
    ("amount", "Keep it cheap."),
    ("session", "Stop if it looks like someone else is driving."),
    ("session", "Pause anything that looks automated."),
    ("time", "Only between now and Friday."),
    ("time", "Nothing after this week."),
    ("country", "Only from Swiss shops."),
    ("country", "Nothing shipped from abroad."),
]

# Restriction-FLAVOURED remarks that restrict nothing. ATTACK: the detector fires on
# these, and nothing syntactic tells them apart from the list above.
CHIT_CHAT = [
    "Do not worry about the weather.",
    "I am not fussy about the brand.",
    "There is nothing in the fridge.",
    "Only if you have time, thanks.",
    "Never mind the receipt.",
]

# Real restrictions carried by a NOUN PHRASE, with no closed-class marker at all.
# ATTACK: the detector misses every one.
NO_MARKER = [
    "Swiss shops preferred.",
    "Returnable items please.",
    "Keep it cheap.",
    "Familiar sellers.",
    "Refundable goods.",
]

WELL_FORMED = [
    "Order our household groceries at or below CHF 120, and only buy things I can return within 14 days.",
    "Order our household groceries at or below CHF 120.",
    "Buy one ordinary grocery item for CHF 20 or less from a shop I use regularly. Ask me when uncertain.",
    "Order groceries, only if returns are accepted within 14 days. Decline it when uncertain.",
    "Order our household groceries, at or below CHF 120, from a shop I have used before.",
    "Please order the weekly groceries. Thanks very much.",
    "Buy the 27-inch monitor I chose. Do not add anything I did not ask for.",
]

_BASE_FIELDS = {"authorization.billing_amount_chf", "item.category"}


def is_silently_lost(clause: str) -> bool:
    """Ground truth, independent of the detector: does adding this clause produce
    NEITHER a new rule NOR any mention of it?"""
    compiled = compile_instruction(BASE + clause)
    if any(r.field not in _BASE_FIELDS for r in compiled.hard_rules):
        return False
    noise = ("uncertainty preference", "applies to each individual")
    mentioned = [q for q in compiled.open_questions if not any(n in q for n in noise)]
    return not mentioned and not compiled.unsupported_restrictions


def measure() -> dict[str, Any]:
    official = {k: v["cardholder_instruction"] for k, v in load_scenario_catalogue().items()}

    lost = [(kind, c) for kind, c in NATURAL if is_silently_lost(c)]
    detected = [(kind, c) for kind, c in lost if unenforced_clauses(BASE + c)]

    try:
        from research.paraphrase_corpus import CASES, EQUIVALENT
        equivalents = [v for _, v, rel, _ in CASES if rel == EQUIVALENT]
    except Exception:                                      # noqa: BLE001
        equivalents = []

    return {
        "natural": NATURAL,
        "silently_lost": lost,
        "detected": detected,
        "missed": [c for c in lost if c not in detected],
        "official_noise": {k: unenforced_clauses(v) for k, v in sorted(official.items())},
        "well_formed_noise": {s: unenforced_clauses(s) for s in WELL_FORMED},
        "equivalent_noise": {s: unenforced_clauses(s) for s in equivalents},
        "chit_chat_fires": [s for s in CHIT_CHAT if unenforced_clauses(BASE + s)],
        "no_marker_missed": [s for s in NO_MARKER if not unenforced_clauses(BASE + s)],
    }


def main() -> int:
    r = measure()
    print("WHICH OF YOUR WORDS DID THE COMPILER ACTUALLY READ?\n")

    print("  " + "-" * 74)
    print("  THE GAP -- ordinary phrasings of restrictions this engine supports")
    print(f"    {len(r['natural'])} clauses tried")
    print(f"    {len(r['silently_lost'])} produced NO rule and NO mention of any kind\n")
    for kind, clause in r["silently_lost"]:
        print(f"      {kind:9s} {clause}")

    print("\n  " + "-" * 74)
    print("  THE DETECTOR -- one deletion per word, measured causally")
    print(f"    {len(r['detected'])} of {len(r['silently_lost'])} detected and quoted back verbatim")
    for _, clause in r["missed"]:
        print(f"      MISSED  {clause}")

    print("\n  " + "-" * 74)
    print("  SILENCE ON SENTENCES THAT ARE FINE  (a detector that fires on everything")
    print("  teaches people to click through it)")
    for label, table in (("official mandates", r["official_noise"]),
                         ("well-formed mandates", r["well_formed_noise"]),
                         ("EQUIVALENT paraphrases (corpus written for another purpose)",
                          r["equivalent_noise"])):
        fired = sum(1 for v in table.values() if v)
        print(f"    {fired:3d} of {len(table):3d} fire   {label}")

    print("\n  " + "-" * 74)
    print("  TWO ATTACKS THAT LANDED, and what was done about them")
    print(f"    {len(r['chit_chat_fires'])} of {len(CHIT_CHAT)} restriction-flavoured remarks FIRE:")
    for s in r["chit_chat_fires"]:
        print(f"        {s}")
    print("      -> the CLAIM was weakened, not the test. This reports which words")
    print("         changed nothing -- true of the weather too -- and is rendered as a")
    print("         receipt rather than a warning.")
    print(f"\n    {len(r['no_marker_missed'])} of {len(NO_MARKER)} noun-phrase restrictions are MISSED:")
    for s in r["no_marker_missed"]:
        print(f"        {s}")
    print("      -> a noun phrase can restrict without a single function word. This")
    print("         axis sees restriction-by-grammar, not restriction-by-noun. A floor")
    print("         under the vocabulary approach, not a ceiling over it.")

    print("\n  " + "-" * 74)
    print("  THE NEAR-MISS THAT NAMED ITSELF")
    example = "Order groceries, only if I can return it within 14 days."
    for m in marks(example):
        if m.kind == "obstructive":
            print(f'    In "{example}"')
            print(f"      the word {m.word!r} was OBSTRUCTIVE: deleting it CREATED a rule.")
            print("      The compiler had almost understood the clause, and said which word")
            print("      stopped it. That defect is now fixed, which is why this line is")
            print("      silent -- run it against the previous commit to see it.")
            break
    else:
        print(f'    "{example}" now compiles cleanly; nothing obstructs it.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

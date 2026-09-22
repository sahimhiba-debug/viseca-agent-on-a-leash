"""Does the customer confirm what the wallet enforces?

The chain of custody for an intent is:

    the customer writes a SENTENCE
        -> the compiler authors RULES
            -> the explainer authors GUIDANCE
                -> the customer reads the guidance and CONFIRMS

The customer's consent attaches to the guidance. The wallet enforces the rules.
Those are two different artefacts authored by two different parties, and nothing
had ever checked that they mean the same thing.

THE INVARIANT

    compile(explain(compile(s)))  ==  compile(s)

If the plain English a customer reads compiles back to a DIFFERENT policy, then
the thing they agreed to is not the thing that will be enforced -- and the
confirmation gate, which is the whole basis of the delegation, is decorative.

This is the authorship question applied to the compiler itself. It is not about
whether the compiler understands English; it is about whether the compiler's own
two outputs agree with each other.

WHAT A FAILURE MEANS, AND DOES NOT MEAN
    A mismatch is not automatically a vulnerability. Guidance is written for a
    person and may legitimately omit machine detail. What it must never do is
    describe a DIFFERENT policy -- a different number, a different scope, a
    different operator, or a rule that is not there at all.

WHAT THIS EXPERIMENT ACTUALLY FOUND, STATED CAREFULLY
    Two real compiler defects, and one correction to its own first conclusion.

    1. "CHF 120 per order, and CHF 300 across any 7 days" produced a single rule:
       CHF 120 as a WEEKLY budget, with the CHF 300 dropped. The period pattern's
       lazy skip jumped over an amount. FIXED.

       This was NOT silent. The existing safeguards all fired: the compiler told
       the customer "No per-order spending ceiling was recognized", "Your CHF 120
       limit applies to each rolling 7-day window", and "The instruction also
       mentions CHF 300, which was not turned into any rule ... it is NOT
       enforced." A customer reading the confirmation screen would have seen it.
       The invariant "no restrictive statement disappears silently" held even
       while the compiler was wrong, which is what that invariant is for.

    2. "under CHF 120" compiled to `< 120` while the confirmed text said "CHF 120
       or less" -- describing `<= 120`. One rappen, and in the wrong direction:
       the text the customer agreed to was MORE permissive than the rule being
       enforced. FIXED.

    3. The first oracle here was wrong. Re-compiling the guidance and comparing
       rule sets reported nine failures, of which seven were the compiler failing
       to re-parse its own correct English -- a curiosity, not a defect. That
       result is kept at the bottom of the output, labelled as what it is.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wallet_control.policy_compiler import compile_instruction    # noqa: E402


def rule_key(rule) -> tuple:
    """What must survive the round trip: the enforceable content of a rule."""
    value = tuple(sorted(rule.value)) if isinstance(rule.value, list) else rule.value
    return (rule.field, rule.operator, str(value), rule.scope or "", rule.period_days or 0)


def policy_of(instruction: str) -> set[tuple]:
    return {rule_key(r) for r in compile_instruction(instruction).hard_rules}


def guidance_of(instruction: str) -> list[str]:
    return list(compile_instruction(instruction).guidance)


# Re-compiling the guidance turned out to be the WRONG ORACLE, and the first run of
# this experiment reported nine failures of which seven were my measurement error.
# The guidance says "The seller must be one this card has purchased from before",
# which is correct English describing the rule -- but the familiarity pattern expects
# "a shop I have used before", so re-compiling produced nothing and the check called
# it a lost rule. What that measures is whether the compiler can re-parse its own
# prose, which is a curiosity. What MATTERS is narrower and checkable:
#
#   for every enforceable rule, does the text the customer confirms state the same
#   NUMBER, the same OPERATOR and the same SCOPE?
#
# A guidance line may legitimately omit machine detail. It may never describe a
# different policy. Both real findings were of exactly that kind.
_SCOPE_WORDS = {"purchase": ("each order", "per order", "one order"),
                "period": ("rolling", "window", "across any", "per week", "a week")}


def numeric_fidelity(instruction: str) -> dict:
    """Does the confirmed text state the same numbers, operators and scopes?"""
    compiled = compile_instruction(instruction)
    guidance = " ".join(compiled.guidance).lower()
    problems = []

    for rule in compiled.hard_rules:
        if rule.field != "authorization.billing_amount_chf":
            continue
        figure = f"{rule.value:g}"
        if figure not in guidance:
            problems.append(f"rule states CHF {figure}; the confirmed text never does")
            continue

        # the operator must not be described more permissively than it is enforced
        strict_said = ("less than" in guidance or "under" in guidance
                       or "below chf" in guidance)
        inclusive_said = "or less" in guidance or "at or below" in guidance
        if rule.operator == "<" and inclusive_said and not strict_said:
            problems.append(
                f"rule enforces < CHF {figure}; the confirmed text says 'or less', "
                "which is one rappen more permissive than what is enforced")
        if rule.operator == "<=" and strict_said and not inclusive_said:
            problems.append(
                f"rule enforces <= CHF {figure}; the confirmed text says 'less than', "
                "which is stricter than what is enforced")

        # the scope must be described as the scope that is enforced
        wanted = _SCOPE_WORDS.get(rule.scope or "", ())
        if wanted and not any(w in guidance for w in wanted):
            problems.append(
                f"rule is scope={rule.scope}; the confirmed text does not say so")

    return {"instruction": instruction, "guidance": compiled.guidance,
            "problems": problems, "holds": not problems}


def figures_survive(instruction: str) -> dict:
    """Every amount the CUSTOMER wrote must end up somewhere they can see.

    Numeric fidelity above compares the guidance against the RULES, and both can be
    wrong together: when the period pattern jumped over an amount, the rule became a
    CHF 120 weekly budget and the guidance correctly described that -- a faithful
    explanation of a policy the customer never wrote, with their CHF 300 gone
    without a word.

    Text-against-rule cannot see that. This checks rule-against-SENTENCE, which is
    the stronger direction:

        every CHF figure in what the customer wrote appears in a rule, in an open
        question, or in the unsupported list -- never nowhere.
    """
    import re

    compiled = compile_instruction(instruction)
    written = {_norm(m) for m in re.findall(r"CHF\s*([\d.,]+)", instruction, re.I)}
    in_rules = {f"{r.value:g}" for r in compiled.hard_rules
                if isinstance(r.value, (int, float))}
    disclosed = " ".join([*compiled.guidance, *compiled.open_questions,
                          *compiled.unsupported_restrictions])
    vanished = sorted(f for f in written
                      if f not in in_rules and f not in disclosed)
    return {"instruction": instruction, "written": sorted(written),
            "in_rules": sorted(in_rules), "vanished": vanished,
            "holds": not vanished}


def _norm(raw: str) -> str:
    value = float(raw.replace(",", "").rstrip("."))
    return f"{value:g}"


def roundtrip(instruction: str) -> dict:
    """Kept for the record: the weaker re-parse oracle, reported separately."""
    original = policy_of(instruction)
    guidance = guidance_of(instruction)
    echoed = policy_of(" ".join(guidance)) if guidance else set()
    return {"instruction": instruction, "original": original, "echoed": echoed,
            "lost": sorted(original - echoed), "invented": sorted(echoed - original),
            "holds": original == echoed}


CORPUS = [
    "Order our household groceries. Keep each order at or below CHF 120.",
    "Order groceries, at or below CHF 120, from a shop I have used before.",
    "Order groceries. Keep each order under CHF 120.",
    "Order groceries and keep the total across any seven days at or below CHF 300.",
    "Order groceries, at or below CHF 120 per order, and CHF 300 across any 7 days.",
    "Buy the 27-inch monitor I chose, from a seller I have bought from before, "
    "for CHF 400 or less. Do not add anything I did not ask for. Ask me when uncertain.",
    "Order groceries only if returnable within 14 days.",
    "Replace my worn road-running shoes in size 43. Buy only from a specialist "
    "sports retailer, only if returnable within 30 days, up to CHF 180.",
    "The agent may buy clothing for me, up to CHF 250 per order, from shops I have "
    "used before.",
    "Order our household groceries for delivery from a shop I have used before. "
    "Keep each order at or below CHF 120 including delivery, and keep the total "
    "across any seven days at or below CHF 300, and only if returnable within 14 "
    "days. Ask me when uncertain.",
]


def main() -> int:
    print("DOES THE CUSTOMER CONFIRM WHAT THE WALLET ENFORCES?\n")
    print("  For every money rule: same number, same operator, same scope,")
    print("  in the text the customer actually reads before confirming.\n")
    failures = []
    for instruction in CORPUS:
        result = numeric_fidelity(instruction)
        print(f"  [{'  ok  ' if result['holds'] else ' FAIL '}] {instruction[:68]}")
        for problem in result["problems"]:
            print(f"            {problem}")
        if not result["holds"]:
            failures.append(result)

    print(f"\n  {len(CORPUS) - len(failures)}/{len(CORPUS)} agree")

    print("\n\n  AND THE STRONGER DIRECTION: does every figure the CUSTOMER wrote")
    print("  survive into something they can see?\n")
    vanished_any = []
    for instruction in CORPUS:
        result = figures_survive(instruction)
        print(f"  [{'  ok  ' if result['holds'] else ' FAIL '}] "
              f"wrote {result['written']} -> rules {result['in_rules']}"
              f"{'   VANISHED: ' + str(result['vanished']) if result['vanished'] else ''}")
        if not result["holds"]:
            vanished_any.append(result)
    if vanished_any:
        print(f"\n  {len(vanished_any)} instruction(s) where a number the customer wrote")
        print("  disappeared with no rule and no warning.")
    if failures:
        print("\n  Where they disagree, the customer agreed to one policy and the")
        print("  wallet enforces another. The confirmation gate is the basis of the")
        print("  whole delegation, so a gap here is not cosmetic.")

    reparse = [r for r in (roundtrip(i) for i in CORPUS) if not r["holds"]]
    print(f"\n  Separately, and much weaker: {len(CORPUS) - len(reparse)}/{len(CORPUS)} of the")
    print("  guidance strings re-compile to their own rules. The rest is the compiler")
    print("  failing to re-parse its own correct English, which is a curiosity rather")
    print("  than a defect -- and reporting it as one was this experiment's first,")
    print("  wrong, result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

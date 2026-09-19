#!/usr/bin/env python3
"""Search for customer language that READS restrictive and COMPILES permissive.

This is not an attack on a transaction. It attacks the translation layer: the
attacker writes (or influences) the customer's own sentence.

Scoring is deliberately crude and stated here so it cannot flatter the result. A
phrase is counted as "restrictive to a human" if it contains a marker from
`_HUMAN_RESTRICTIVE` -- a word an ordinary reader treats as narrowing authority. It
is counted as "permissive to the compiler" by how few hard rules it yields and how
loose they are. The gap between the two is what we are looking for, and the script
prints the worst offenders rather than a score.

    python3 scripts/run_compiler_optimizer.py
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wallet_control.policy_compiler import compile_instruction   # noqa: E402

import re

# Words an ordinary reader treats as narrowing what the agent may do.
#
# "one" is NOT a bare substring here. An earlier version counted it that way and
# reported 192 phantom quantity losses, every one of them the word "one" inside
# "a shop that is one I have used before" -- a phrase with no quantity intent at all.
# A measurement whose marker is looser than the concept it measures inflates its own
# result, so the quantity marker is verb-anchored, exactly as the compiler's is.
_QUANTITY_RE = re.compile(
    r"\b(?:buy|order|purchase|get)\s+"
    r"(?:exactly\s+|at most\s+|up to\s+|a single\s+|no more than\s+)?"
    r"(?:one|two|three|four|five|ten|twenty|a single|\d+)\b",
    re.IGNORECASE,
)

_HUMAN_RESTRICTIVE = [
    "only", "at most", "no more than", "never", "do not", "don't",
    "exactly", "per week", "per month", "per day", "a week", "a month",
    "must", "required", "familiar", "used before", "nothing else",
]

_SUBJECTS = ["groceries", "clothing", "a monitor", "running shoes"]
_AMOUNTS = ["CHF 50", "CHF 250"]
_QUANTIFIERS = ["", "one ", "exactly one ", "at most one ", "a single "]
_SCOPES = ["", " per order", " per week", " per month", " a week", " in any 7 days"]
_MERCHANTS = [
    "",
    " from a shop I use regularly",
    " from a shop that is one I have used before",
    " only from shops I have used before",
    " from a seller I have bought from before",
]
_EXTRAS = ["", " Do not add anything I did not ask for.", " Nothing else.", " Never add extras."]


def _restrictive_markers(text: str) -> list[str]:
    low = text.lower()
    found = [m for m in _HUMAN_RESTRICTIVE if m in low]
    if _QUANTITY_RE.search(text):
        found.append("quantity")
    return found


def _weakness(compiled) -> tuple[int, float]:
    """(number of hard rules, the loosest per-purchase ceiling). Fewer/looser = weaker."""
    ceiling = float("inf")
    for rule in compiled.hard_rules:
        if rule.field == "authorization.billing_amount_chf" and rule.scope == "purchase":
            ceiling = min(ceiling, float(rule.value))
    return len(compiled.hard_rules), ceiling


def main() -> int:
    rows = []
    for qty, subject, amount, scope, merchant, extra in itertools.product(
        _QUANTIFIERS, _SUBJECTS, _AMOUNTS, _SCOPES, _MERCHANTS, _EXTRAS
    ):
        text = f"Buy {qty}{subject} for up to {amount}{scope}{merchant}.{extra} Ask me when uncertain."
        compiled = compile_instruction(text)
        markers = _restrictive_markers(text)
        n_rules, _ = _weakness(compiled)
        # which markers produced NO corresponding rule?
        fields = {r.field for r in compiled.hard_rules}
        unaccounted = []
        if "quantity" in markers and not any("quantity" in f or "count" in f for f in fields):
            unaccounted.append("quantity")
        if any(m in markers for m in ("per week", "per month", "per day", "a week", "a month")) and not any(
            r.scope == "period" for r in compiled.hard_rules
        ):
            unaccounted.append("temporal scope")
        if any(m in markers for m in ("used before", "familiar")) and "merchant.familiar" not in fields:
            unaccounted.append("merchant familiarity")
        if any(m in markers for m in ("do not", "don't", "never", "nothing else")) and (
            "item.unrequested_present" not in fields
        ):
            unaccounted.append("no add-ons")
        # is the customer told? only if an open_question mentions the lost concept
        told = " ".join(compiled.open_questions).lower()
        silent = [u for u in unaccounted if u.split()[0] not in told]
        if silent:
            rows.append((len(silent), text, markers, silent, n_rules))

    rows.sort(key=lambda r: (-r[0], r[4]))
    total = len(list(itertools.product(_QUANTIFIERS, _SUBJECTS, _AMOUNTS, _SCOPES, _MERCHANTS, _EXTRAS)))
    print(f"Searched {total} generated customer instructions.")
    print(f"{len(rows)} contain a restrictive phrase that produced NO rule AND NO open question.\n")

    print("Worst offenders (most restrictive intent lost silently):\n")
    for n_silent, text, markers, silent, n_rules in rows[:12]:
        print(f"  lost silently: {', '.join(silent)}   ({n_rules} rules compiled)")
        print(f"    \"{text}\"")
    by_kind: dict[str, int] = {}
    for _, _, _, silent, _ in rows:
        for s in silent:
            by_kind[s] = by_kind.get(s, 0) + 1
    print("\nSilent losses by kind:")
    for kind, count in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"  {kind:22s} {count:5d}")
    return 1 if rows else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Can any field be RESTATED to buy something the honest event would not get?

Erasure asks what happens when a fact is removed. This asks the other half: what
happens when it is replaced by a DIFFERENT, equally legal value.

WHY THIS EXISTS. `authorization.timestamp` -- the clock every rolling ceiling is
measured in -- had no declared provenance until it turned up by accident, while
chasing an unrelated bug in restart recovery. Restating it moved a purchase into a
different week and a spent CHF 300 / 7-day ceiling allowed CHF 600. A fact that
decides authority was never examined because no RULE NAMED IT, and the provenance
table had been built from the list of rule fields.

Finding that by luck is not a method. This is the method: substitute every field,
systematically, and see which substitutions buy something.

WHERE THE VALUES COME FROM. Each field is replaced with a value that field actually
takes in ANOTHER official event. Nothing invented, nothing malformed: every variant
is a real event shape the platform itself produced, so a permissiveness increase
cannot be dismissed as "you sent nonsense". It also keeps the sweep honest about
types -- no TypeError dressed up as a finding.

THE CRITERION IS `provenance.py`'s, and the fourth clause matters. A substitution is
a FORGERY only if it changes the decision *while leaving the purchase unchanged* --
same goods, same shop, same price, same moment. Raising the amount and being refused
is not a finding; getting the same goods on better terms is.

Run:  python3 -m research.substitution
"""

from __future__ import annotations

import copy
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research.erasure import (  # noqa: E402
    PERMISSIVENESS, judge, official_cases, paths, _split,
)

# Restating one of these describes a DIFFERENT PURCHASE, not the same one told
# differently -- so a more permissive answer is a different question, not a hole.
# `timestamp` is here because a purchase in another week is another purchase; that
# is the fourth clause of the criterion, and leaving it out is what let the clock go
# unexamined for so long.
PURCHASE_DEFINING = {
    "amount", "billing_amount_chf", "items_subtotal", "delivery_fee", "currency",
    "unit_price", "quantity", "item_id", "merchant_id", "timestamp",
}

# Identity of the event itself. Substituting these does not describe a purchase at
# all -- it describes a DIFFERENT event, and the binding checks exist to refuse that.
IDENTITY = {
    "authorization_id", "source_authorization_id", "request_id", "mandate_id",
    "profile_id", "card_id", "scenario_id", "replay_order", "deadline_at",
}


def _leaf(path: str) -> str:
    return _split(path)[-1] if not isinstance(_split(path)[-1], int) else ""


def _read(event: dict, path: str) -> Any:
    node: Any = event
    for step in _split(path):
        node = node[step]
    return node


def _write(event: dict, path: str, value: Any) -> dict | None:
    out = copy.deepcopy(event)
    node = out
    try:
        steps = _split(path)
        for step in steps[:-1]:
            node = node[step]
        node[steps[-1]] = value
    except (KeyError, IndexError, TypeError):
        return None
    return out


def vocabulary(cases) -> dict[str, list[Any]]:
    """Every value each field path actually takes across the official events."""
    seen: dict[str, list[Any]] = defaultdict(list)
    for _, _, event, _, _ in cases:
        for path in paths(event):
            try:
                value = _read(event, path)
            except (KeyError, IndexError, TypeError):
                continue
            if isinstance(value, (dict, list)):
                continue
            if value not in seen[path]:
                seen[path].append(value)
    return seen


def sweep(limit_per_field: int = 6):
    cases = list(official_cases())
    words = vocabulary(cases)
    findings, raised, total = [], [], 0

    for scenario_id, auth_id, event, snapshot, history in cases:
        base, base_codes = judge(event, snapshot, history)
        if base.startswith("RAISED"):
            raised.append((scenario_id, auth_id, "<baseline>", base))
            continue
        for path in paths(event):
            leaf = _leaf(path)
            if leaf in IDENTITY:
                continue
            try:
                current = _read(event, path)
            except (KeyError, IndexError, TypeError):
                continue
            if isinstance(current, (dict, list)):
                continue
            for alternative in words.get(path, [])[:limit_per_field]:
                if alternative == current:
                    continue
                variant = _write(event, path, alternative)
                if variant is None:
                    continue
                total += 1
                got, _ = judge(variant, snapshot, history)
                if got.startswith("RAISED"):
                    raised.append((scenario_id, auth_id, path, got))
                elif PERMISSIVENESS[got] > PERMISSIVENESS[base]:
                    findings.append((scenario_id, auth_id, path, base, got,
                                     leaf in PURCHASE_DEFINING, alternative))
    return findings, raised, total


def main() -> None:
    findings, raised, total = sweep()
    forgeries = [f for f in findings if not f[5]]
    reframed = [f for f in findings if f[5]]

    print(f"\n  SUBSTITUTION over the 45 official events")
    print(f"  {total:,} restatements (every field x values that field really takes)\n")
    print(f"  more permissive, SAME PURCHASE (a forgery)   : {len(forgeries)}")
    print(f"  more permissive, but a DIFFERENT purchase    : {len(reframed)}")
    print(f"  refused to answer at all                     : {len(raised)}\n")

    if forgeries:
        print("  FORGERIES -- the same purchase, restated, and now permitted:")
        for s, a, path, base, got, _, value in forgeries[:30]:
            shown = repr(value)[:38]
            print(f"    {s} {a:8s} {path:40s} {base} -> {got:6s} := {shown}")
        print()
    else:
        print("  No substitution bought the same purchase a better answer.\n"
              "  A statement about THIS corpus and THIS vocabulary, not a proof.\n")

    if raised:
        print(f"  NO ANSWER on {len(raised)} restatements:")
        for row in raised[:10]:
            print(f"    {row}")
        print()


if __name__ == "__main__":
    main()

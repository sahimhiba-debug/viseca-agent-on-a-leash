"""ERASURE MONOTONICITY, stated as a property and attacked exhaustively.

THE PROPERTY

    For every authorization event E and every field f reachable in it,

        permissiveness( decide(E \\ f) )  <=  permissiveness( decide(E) )

    where `block < review < allow` and `E \\ f` is E with f ERASED.

In words: **saying less must never buy more.** A party that withholds information
may be refused, or asked about, or treated exactly as before -- it may never be
approved for something it could not have had by speaking.

WHY THIS PROPERTY AND NOT A LIST OF TESTS. The catalogue bug (ABSENCE #13) was one
instance: an item id the catalogue knew was refutable, an id it had never seen was
waved through, so inventing the id beat naming it. That was found by hand. The
question it raises is not "is that fixed" but "how many more are there", and the
only honest answer comes from enumerating the field space rather than the space of
attacks we happened to think of.

TWO KINDS OF ERASURE, BECAUSE CODE TREATS THEM DIFFERENTLY

    NULL      the key is present and its value is None
    ABSENT    the key is not there at all

`d.get(k)` cannot tell them apart and `k in d` can, so a wallet can easily be
monotone under one and not the other. Both are swept.

WHAT A VIOLATION MEANS, AND WHAT IT DOES NOT. A violation is not automatically a
vulnerability: erasing `amount` changes the purchase, and a cheaper purchase being
allowed is not a bypass. The sweep therefore reports two columns -- whether the
decision got MORE PERMISSIVE, and whether the erasure left the PURCHASE ITSELF
unchanged. The second column is the same criterion `provenance.py` uses, and it is
what separates a real hole from an apparent one.

A RAISED EXCEPTION IS ALSO A VIOLATION, of a different property: the wallet owes one
of three answers inside eight seconds, and an exception is none of them. ABSENCE #14
was exactly this, found by accident; here it is looked for on purpose.

Run:  python3 -m research.erasure
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wallet_control.csv_data import (  # noqa: E402
    history_csv_path, load_merchants, load_purchase_attempt_items,
    load_scenario_catalogue, scenario_rows,
)
from wallet_control.decision_engine import evaluate_authorization  # noqa: E402
from wallet_control.offline_replay import (  # noqa: E402
    build_event, compile_and_confirm_mandate_for_scenario,
)
from wallet_control.state import HistoryIndex, RunState  # noqa: E402

PERMISSIVENESS = {"block": 0, "review": 1, "allow": 2}

# Erasing one of these changes WHAT IS BEING BOUGHT, not merely what is known about
# it. A more permissive answer for a different purchase is not a bypass -- it is a
# different question -- so these are reported separately rather than as violations.
# Everything else describes the purchase without being it.
PURCHASE_DEFINING = (
    "authorization.amount",
    "authorization.billing_amount_chf",
    "authorization.items_subtotal",
    "authorization.delivery_fee",
    "authorization.currency",
)


def _is_purchase_defining(path: str) -> bool:
    if path in PURCHASE_DEFINING:
        return True
    # a whole item line, or its price/quantity: fewer goods is a different basket
    if path.startswith("authorization.items["):
        tail = path.split("]", 1)[1]
        return tail in ("", ".unit_price", ".quantity")
    return False


def paths(node: Any, prefix: str = "") -> list[str]:
    """Every field path reachable in the event, including inside item lines."""
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{prefix}.{key}" if prefix else key
            out.append(here)
            out.extend(paths(value, here))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            here = f"{prefix}[{i}]"
            out.append(here)
            out.extend(paths(value, here))
    return out


def _split(path: str) -> list[Any]:
    steps: list[Any] = []
    for chunk in path.split("."):
        while "[" in chunk:
            head, rest = chunk.split("[", 1)
            if head:
                steps.append(head)
            index, chunk = rest.split("]", 1)
            steps.append(int(index))
        if chunk:
            steps.append(chunk)
    return steps


def erase(event: dict, path: str, mode: str) -> dict | None:
    """A copy of `event` with `path` set to None (`null`) or removed (`absent`)."""
    out = copy.deepcopy(event)
    steps = _split(path)
    node = out
    try:
        for step in steps[:-1]:
            node = node[step]
        last = steps[-1]
        if mode == "null":
            node[last] = None
        else:
            if isinstance(node, list):
                node.pop(last)
            else:
                del node[last]
    except (KeyError, IndexError, TypeError):
        return None
    return out


def judge(event: dict, snapshot, history: HistoryIndex) -> str:
    """One decision, on a FRESH state so nothing accumulates between variants."""
    state = RunState(history=history, card_id=snapshot.card_id)
    try:
        return evaluate_authorization(event, snapshot, state).decision
    except Exception as exc:                      # noqa: BLE001 -- the point is to catch all
        return f"RAISED:{type(exc).__name__}"


def official_cases():
    """The 45 real events, each with the mandate that judged it."""
    history = HistoryIndex.from_csv(history_csv_path())
    items_by_auth = load_purchase_attempt_items()
    merchants = load_merchants()
    for scenario_id in sorted(load_scenario_catalogue()):
        snapshot = compile_and_confirm_mandate_for_scenario(scenario_id).snapshot()
        for row in scenario_rows(scenario_id):
            event = build_event(row, items_by_auth[row["authorization_id"]],
                                merchants[row["merchant_id"]], snapshot,
                                {"approved_spend_in_period_chf": 0.0,
                                 "recent_authorizations": []})
            yield scenario_id, row["authorization_id"], event, snapshot, history


def sweep():
    findings, raised, weakened, total = [], [], 0, 0
    for scenario_id, auth_id, event, snapshot, history in official_cases():
        base = judge(event, snapshot, history)
        if base.startswith("RAISED"):
            raised.append((scenario_id, auth_id, "<baseline>", "-", base))
            continue
        for path in paths(event):
            for mode in ("null", "absent"):
                variant = erase(event, path, mode)
                if variant is None:
                    continue
                total += 1
                got = judge(variant, snapshot, history)
                if got.startswith("RAISED"):
                    raised.append((scenario_id, auth_id, path, mode, got))
                elif PERMISSIVENESS[got] > PERMISSIVENESS[base]:
                    findings.append((scenario_id, auth_id, path, mode, base, got,
                                     _is_purchase_defining(path)))
                elif PERMISSIVENESS[got] < PERMISSIVENESS[base]:
                    weakened += 1
    return findings, raised, weakened, total


def main() -> None:
    findings, raised, weakened, total = sweep()
    print(f"\n  ERASURE MONOTONICITY over the 45 official events")
    print(f"  {total:,} erasures applied (every field path x null/absent)\n")

    real = [f for f in findings if not f[6]]
    reframed = [f for f in findings if f[6]]

    print(f"  more permissive after erasing, SAME PURCHASE : {len(real)}")
    print(f"  more permissive, but the purchase CHANGED    : {len(reframed)}")
    print(f"  refused to answer at all (raised)            : {len(raised)}")
    print(f"  erasure made it STRICTER (monotone, fine)    : {weakened:,}\n")

    if real:
        print("  VIOLATIONS -- saying less bought more, for the same purchase:")
        for s, a, path, mode, base, got, _ in real[:40]:
            print(f"    {s} {a:8s} {path:44s} {mode:6s} {base} -> {got}")
        print()
    if raised:
        print("  NO ANSWER -- the wallet owes approve/decline/step_up and gave none:")
        for s, a, path, mode, exc in raised[:40]:
            print(f"    {s} {a:8s} {path:44s} {mode:6s} {exc}")
        print()
    if not real and not raised:
        print("  No violation found in this space. That is a statement about THIS\n"
              "  corpus and THIS field set, not a proof about all events.\n")


if __name__ == "__main__":
    main()

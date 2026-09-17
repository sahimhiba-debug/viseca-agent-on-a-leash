#!/usr/bin/env python3
"""Prints the full adversarial corpus as a matrix:

    CASE | CATEGORY | ATTACK | EXPECTED PROPERTY | OBSERVED | PASS/FAIL

Exits non-zero if any case fails, so it can gate CI like run_replay.py.
Use -v to print every case; the default prints a per-category summary plus any
failures, because 133 passing rows is not information.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from wallet_control.red_team_corpus import run_all  # noqa: E402


def main() -> int:
    verbose = "-v" in sys.argv
    results = run_all()
    held = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]

    by_category: Counter[str] = Counter(case.category for case, _, _ in results)
    failed_by_category: Counter[str] = Counter(case.category for case, _, _ in failed)

    print(f"Adversarial corpus: {len(results)} cases across {len(by_category)} categories\n")
    for category in sorted(by_category):
        total = by_category[category]
        bad = failed_by_category.get(category, 0)
        mark = "✓" if bad == 0 else "✗"
        print(f"  [{mark}] {category:<34} {total - bad:>3}/{total}")

    if verbose:
        print()
        for case, ok, observed in results:
            mark = "✓" if ok else "✗"
            print(f"{mark} {case.case_id:<6} {case.category:<30} {case.attack}")
            print(f"         expected: {case.expected}")
            print(f"         observed: {observed}")

    if failed:
        print(f"\n{len(failed)} CASE(S) FAILED:\n")
        for case, _, observed in failed:
            print(f"  {case.case_id} [{case.category}] {case.attack}")
            print(f"    expected: {case.expected}")
            print(f"    observed: {observed}\n")
        return 1

    print(f"\n{len(held)}/{len(results)} held.")
    print(
        "A fully compromised agent -- free to mutate amounts, merchants, baskets, item\n"
        "identities, merchant text, identities, timestamps and statuses, to replay and\n"
        "retry, to race, and to crash the process mid-flight -- obtained no execution\n"
        "beyond exactly what the customer's mandate authorized."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

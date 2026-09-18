#!/usr/bin/env python3
"""Runs the R&D Track H attack matrix and prints a human-readable report:

    ATTACK -> EXPECTED WALLET PROPERTY -> OBSERVED RESULT -> PASS/FAIL -> EVIDENCE

Exit code is non-zero if any attack defeats the wallet, so this can be wired
into CI the same way scripts/run_replay.py already is.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # research/ lives at the repo root, outside the shipped package

from research import red_team  # noqa: E402


def main() -> int:
    results = red_team.run_all()
    width_attack = max(len(r.attack) for r in results)
    print(f"Red-team matrix: {len(results)} attacks against the compromised-shopping-agent threat model\n")
    for i, r in enumerate(results, 1):
        status = "PASS" if r.passed else "FAIL"
        marker = "✓" if r.passed else "✗"
        print(f"{i:2}. [{marker} {status}] {r.attack:<{width_attack}}  (invariant: {r.invariant})")
        print(f"      expected : {r.expected_property}")
        print(f"      evidence : {r.evidence}")
    passed = sum(1 for r in results if r.passed)
    print(f"\n{passed}/{len(results)} attacks defeated by the wallet.")
    if passed != len(results):
        print("RED TEAM FAILURE: at least one attack succeeded against the wallet.")
        return 1
    print("The shopping agent can be fully compromised (prompt injection, basket tampering, "
          "replay, resolution abuse, mandate-widening attempts) without gaining payment authority "
          "beyond what the customer's mandate and the wallet's own checks allow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

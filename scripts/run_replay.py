#!/usr/bin/env python3
"""Run the complete official 45-event offline replay and print a summary.

Usage:
    python scripts/run_replay.py [-v]

With -v, prints every individual decision; otherwise just the per-scenario and
total ALLOW/REVIEW/BLOCK counts.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wallet_control.offline_replay import replay_all  # noqa: E402


def main() -> None:
    verbose = "-v" in sys.argv
    result = replay_all()

    for scenario in result.scenarios:
        print(f"=== {scenario.scenario_id} {scenario.scenario_name} ===")
        print(f'  instruction: "{scenario.cardholder_instruction}"')
        print(f"  hard_rules: {[r.as_dict() for r in scenario.mandate.hard_rules]}")
        print(f"  uncertainty_policy: {scenario.mandate.uncertainty_policy.value}")
        if verbose:
            for d in scenario.decisions:
                print(f"    {d.authorization_id:10s} {d.decision:7s} {d.reason_codes}")
        print(f"  counts: {scenario.counts()}")
        print()

    totals = result.total_counts()
    print("=" * 60)
    print(f"TOTAL events: {result.total_events()}  {totals}")
    assert result.total_events() == 45, "expected exactly 45 official events"


if __name__ == "__main__":
    main()

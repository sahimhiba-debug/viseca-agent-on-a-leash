"""Every number this repository states about itself must still be true.

Three counts went stale inside a single working session -- the README claimed
622, then 643, then 664 tests while the suite grew past 690 -- and each one was
caught by chance rather than by anything that would fail. A stale count is a small
lie in the most-read sentence of the project, and an auditor who checks one number
and finds it wrong reasonably stops believing the rest.

So the self-describing numbers are checked against the thing they describe:

  * the test count in README.md and docs/FINAL_AUDIT_PACKAGE.md, against what
    pytest actually collects;
  * the official replay counts in README.md, against an actual replay.

The cost is a one-line edit whenever the suite grows. That is the point: it makes
the claim expensive enough to keep true, instead of cheap enough to leave rotting.

The replay counts are pinned in `tests/test_offline_replay.py` as a REGRESSION
BOUNDARY -- there are no official expected-decision labels and 19/2/24 is not a
score. What is asserted here is narrower: that the table printed in the README is
the table this engine actually produces.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def collected_count() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    count = sum(1 for line in result.stdout.splitlines() if "::" in line)
    assert count > 0, f"collected nothing; pytest said:\n{result.stdout[-2000:]}"
    return count


@pytest.mark.parametrize(
    "relative_path,pattern",
    [
        ("README.md", r"^tests/\s+(\d[\d,]*) tests$"),
        ("README.md", r"\*\*(\d[\d,]*) tests\*\* --"),
        ("docs/FINAL_AUDIT_PACKAGE.md", r"\| tests \| (\d[\d,]*) collected"),
    ],
)
def test_stated_test_counts_match_what_pytest_collects(relative_path, pattern, collected_count):
    text = (ROOT / relative_path).read_text()
    matches = re.findall(pattern, text, re.MULTILINE)
    assert len(matches) == 1, f"{relative_path}: expected exactly one match for {pattern!r}, got {matches}"
    stated = int(matches[0].replace(",", ""))
    assert stated == collected_count, (
        f"{relative_path} says {stated} tests; pytest collects {collected_count}"
    )


def test_the_readme_replay_table_is_what_the_engine_actually_produces():
    from wallet_control.offline_replay import replay_all

    result = replay_all()
    counts = result.total_counts()

    table = re.search(
        r"\|\s*\*\*Total\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|",
        (ROOT / "README.md").read_text(),
    )
    assert table, "could not find the replay total row in README.md -- the table format changed"
    events, allow, review, block = (int(g) for g in table.groups())
    assert (events, allow, review, block) == (
        result.total_events(), counts.get("allow", 0), counts.get("review", 0), counts.get("block", 0)
    ), (
        f"README states {events}/{allow}/{review}/{block}; the engine produces "
        f"{result.total_events()}/{counts.get('allow', 0)}/{counts.get('review', 0)}/{counts.get('block', 0)}"
    )


def test_the_readme_per_scenario_rows_are_right_too():
    """The total can be right while a row is wrong; the per-scenario table is what
    a judge reads line by line."""
    from wallet_control.offline_replay import replay_all

    readme = (ROOT / "README.md").read_text()
    for scenario in replay_all().scenarios:
        row = re.search(
            rf"\|\s*{re.escape(scenario.scenario_id)}[^|]*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|",
            readme,
        )
        assert row, f"no README row for {scenario.scenario_id}"
        stated = tuple(int(g) for g in row.groups())
        counts = scenario.counts()
        actual = (
            len(scenario.decisions),
            counts.get("allow", 0),
            counts.get("review", 0),
            counts.get("block", 0),
        )
        assert stated == actual, f"{scenario.scenario_id}: README says {stated}, engine produces {actual}"

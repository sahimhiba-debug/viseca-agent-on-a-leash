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
BOUNDARY -- there are no official expected-decision labels and 17/4/24 is not a
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
        ("README.md", r"\*\*(\d[\d,]*) tests\*\*, of which"),
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


def test_the_delegation_panel_stays_fast_enough_to_type_against():
    """A LATENCY CLAIM NOTHING WAS CHECKING.

    The README and the thesis said the size panel answers in "18 ms, live, as they
    type". Measured, it was 92 ms before this session's changes and 271 ms after them
    -- the price band and the uncertainty trade-off each re-ran the whole enumeration.
    The figure had never been true of the shipped panel and nothing would ever have
    said so.

    It is now 47 ms (median of nine calls with a fresh instruction each time), by
    counting two price points instead of three and moving the trade-off to its own
    endpoint. This asserts a BUDGET rather than that number: machines differ, and a
    test that fails on a slow laptop teaches people to ignore it. A 3x regression is
    a real change in what the panel is, and fails here."""
    import statistics
    import time

    from wallet_control.scope import delegation_size

    base = "Order our household groceries at or below CHF {} from a shop I have used before."
    delegation_size(base.format(100))          # warm the world cache
    samples = []
    for cap in range(120, 129):
        start = time.perf_counter()
        delegation_size(base.format(cap))
        samples.append((time.perf_counter() - start) * 1000)

    median = statistics.median(samples)
    assert median < 150, (
        f"the delegation panel took {median:.0f} ms; it is documented as answering "
        f"as the customer types, and something has made it three times slower")


# --- the replay split, wherever a document claims to be current ----------------------

CURRENT_DOCS = ("README.md", "docs/BASELINE_CURRENT.md", "docs/FINAL_AUDIT_PACKAGE.md",
                "docs/THE_THESIS.md")


def test_no_current_document_states_a_stale_replay_split():
    """THE CLASS OF DRIFT THIS CATCHES, found by reading rather than by a test.

    `docs/BASELINE_CURRENT.md` opens with "Only facts re-verified by running the
    thing, on this commit" and carried **19 allow / 2 review / 24 block** twice, two
    boundary moves after that stopped being true. The replay split is the single
    number most likely to be quoted at a judge and the single number most likely to
    go stale, because it moves whenever a defect is fixed -- it has moved twice.

    Documents that narrate the HISTORY of the boundary ("19/2/24 -> 18/3/24 ->
    17/4/24") are not the subject: a research log recording what was true at the time
    is correct. This checks the documents that claim to describe the present, and it
    checks them against the replay itself rather than against each other.
    """
    import re
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "scripts/run_replay.py"],
                         cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    # The LAST match: the script prints a per-scenario line before the TOTAL, and
    # taking the first one compared every document against one scenario's counts.
    found_counts = re.findall(r"\{'allow': (\d+), 'review': (\d+), 'block': (\d+)\}",
                              out.stdout)
    assert found_counts, out.stdout[-500:]
    allow, review, block = found_counts[-1]
    assert int(allow) + int(review) + int(block) == 45, found_counts[-1]
    current = f"{allow}/{review}/{block}"

    stale = []
    for name in CURRENT_DOCS:
        text = (ROOT / name).read_text()
        for found in set(re.findall(r"\b(\d{1,2}/\d{1,2}/\d{2})\b", text)):
            if found == current:
                continue
            # A line that shows the boundary MOVING is narrating history, not
            # claiming the present.
            for line in text.splitlines():
                if found in line and "->" not in line and "\u2192" not in line:
                    stale.append((name, found, line.strip()[:90]))
    assert not stale, (
        f"these documents state a replay split that is not the current {current}:\n  "
        + "\n  ".join(f"{n}: {f} -- {l}" for n, f, l in stale))

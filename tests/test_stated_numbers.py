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
    a real change in what the panel is, and fails here.

    The budget is RELATIVE to a fixed pure-Python workload timed in the same process.
    It used to be 150 ms flat, and on a 4-core cloud container the unchanged panel
    took 165 ms: the test was measuring the machine. There the panel costs about 1.2x
    the calibration loop, so 3.6x is the same 3x regression anywhere."""
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
    calibration = []
    for _ in range(5):
        start = time.perf_counter()
        sum(i * i for i in range(3_000_000))
        calibration.append((time.perf_counter() - start) * 1000)
    ratio = median / statistics.median(calibration)
    assert ratio < 3.6, (
        f"the delegation panel took {median:.0f} ms, {ratio:.1f}x a fixed calibration "
        f"loop on this machine (about 1.2x when measured); it is documented as "
        f"answering as the customer types, and something has made it three times slower")


# --- the replay split, wherever a document claims to be current ----------------------

CURRENT_DOCS = ("README.md", "docs/BASELINE_CURRENT.md", "docs/FINAL_AUDIT_PACKAGE.md",
                "docs/THE_THESIS.md")


# How the same fact is spelled across these documents. Enumerated by grepping the
# corpus, not guessed: the previous version of this guard knew only the first form and
# was blind to the second, which is the one the audit package used.
SPLIT_SPELLINGS = (
    r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b",
    r"(\d{1,2})\s*allow\s*/\s*(\d{1,2})\s*(?:review|ask)\s*/\s*(\d{1,2})\s*block",
    r"(\d{1,2})\s*allow\s*,\s*(\d{1,2})\s*(?:review|ask)\s*,\s*(\d{1,2})\s*block",
    r"'allow':\s*(\d{1,2}),\s*'review':\s*(\d{1,2}),\s*'block':\s*(\d{1,2})",
    r"allow:\s*(\d{1,2}),\s*review:\s*(\d{1,2}),\s*block:\s*(\d{1,2})",
    # The markdown results table's total row. docs/OFFLINE_REPLAY.md stated 19/2/24
    # this way for three boundary moves and no spelling above could read it.
    r"\|\s*\*\*45\*\*\s*\|\s*\*\*(\d{1,2})\*\*\s*\|\s*\*\*(\d{1,2})\*\*\s*\|\s*\*\*(\d{1,2})\*\*\s*\|",
    # The README's two-minute table: "12 allowed · 9 asked · 24 blocked". Added with
    # the line, so the newest statement of the split is not the one the guard can't read.
    r"(\d{1,2})\s*allowed\s*[·,/]\s*(\d{1,2})\s*asked\s*[·,/]\s*(\d{1,2})\s*blocked",
)

# What the guard must FIND, per document. A search that matches nothing passes every
# assertion that follows it, so the coverage is pinned: if a document is reworded into
# a spelling this guard cannot read, the count drops and this fails LOUDLY rather than
# going quietly blind. That is exactly how 19/2/24 survived in the audit package.
EXPECTED_STATEMENTS = {
    "README.md": 3,
    "docs/OFFLINE_REPLAY.md": 2,
    "docs/BASELINE_CURRENT.md": 6,
    "docs/FINAL_AUDIT_PACKAGE.md": 6,
    "docs/THE_THESIS.md": 1,
}

# A document may state a SUPERSEDED split only where it is plainly discussing one.
# Scope is the PARAGRAPH, not the line, because prose wraps: the audit package states
# the old figure and the new one two lines apart, and a line-scoped rule called that
# a stale claim. A paragraph that also carries the current figure, or shows the
# boundary moving, is narrating. Anything else needs the marker, which is deliberate,
# invisible when rendered, and cannot appear by accident.
SUPERSEDED_MARKER = "<!-- superseded -->"

# The document-level form. `docs/` is 133 files and most of them record what was true
# at an earlier commit -- a research log that says the replay was 19/2/24 in September
# is correct and must not be rewritten. What it must not do is look identical to a
# document describing the present. A file carrying this marker declares itself
# unmaintained; MAINTAINED_DOCS is the complement, and every figure in those is
# checked. Neither list may be empty and a file may not be in both.
SNAPSHOT_MARKER = "<!-- snapshot -->"

MAINTAINED_DOCS = (
    "README.md",
    "docs/OFFLINE_REPLAY.md",
    "RUNBOOK.md",
    "docs/BASELINE_CURRENT.md",
    "docs/FINAL_AUDIT_PACKAGE.md",
    "docs/THE_THESIS.md",
    "docs/ABSENCE.md",
    "docs/A_CHECK_THAT_CANNOT_FAIL.md",
    "docs/archive/COMPETITION_READINESS.md",
    "docs/FINAL_CLAIMS_REGISTER.md",
    "docs/archive/FINAL_COMPETITION_READINESS.md",
    "docs/WHAT_WE_REFUSE_TO_CLAIM.md",
)


def _stated_splits(text: str) -> list[tuple[str, str, int, int, int]]:
    """Every replay split stated in `text`, in any spelling, with its line and the
    paragraph it sits in."""
    found = []
    for paragraph in re.split(r"\n\s*\n", text):
        for line in paragraph.splitlines():
            for pattern in SPLIT_SPELLINGS:
                for match in re.finditer(pattern, line):
                    a, r, bl = (int(g) for g in match.groups())
                    if a + r + bl == 45:      # the official replay is 45 events
                        found.append((paragraph, line.strip()[:100], a, r, bl))
    return found


def _stale_statements(text: str, current: tuple[int, int, int],
                      respect_snapshot: bool = True) -> list[tuple[str, str]]:
    """Statements of a split that is not `current` and is not plainly being discussed.

    Split out from the test so it can be exercised against synthetic documents by
    `test_the_stale_split_guard_actually_fires`. A guard with no negative control is
    how this one stayed green over a false headline for two boundary moves."""
    if respect_snapshot and SNAPSHOT_MARKER in text:
        return []          # the document declares itself a record of an earlier commit
    stale = []
    for paragraph, line, *split in _stated_splits(text):
        if tuple(split) == current:
            continue
        # NO BARE-ARROW EXEMPTION. An earlier version exempted any paragraph
        # containing "->", on the theory that an arrow means the boundary is being
        # shown moving. `docs/archive/RESEARCH_LAB_REPORT.md` opens "Baseline fe571b2 (646
        # tests) -> final 4222f97 ... Official replay 45 / 19 allow / 2 review / 24
        # block, unchanged throughout" -- the arrow is between two COMMITS and the
        # claim about the split is flatly stated, and it was silently excused. An
        # arrow somewhere in the paragraph says nothing about what it connects.
        #
        # What remains is narrow and checkable: the paragraph also states the CURRENT
        # split (so the reader is being shown the change), or it carries the marker.
        narrating = (
            SUPERSEDED_MARKER in paragraph
            or any(tuple(s[2:]) == current for s in _stated_splits(paragraph)))
        if not narrating:
            stale.append((line, f"{split[0]}/{split[1]}/{split[2]}"))
    return stale


def test_no_current_document_states_a_stale_replay_split():
    """THE CLASS OF DRIFT THIS CATCHES, and the way this guard itself failed.

    `docs/BASELINE_CURRENT.md` opens with "Only facts re-verified by running the
    thing, on this commit" and carried **19 allow / 2 review / 24 block** twice, two
    boundary moves after that stopped being true. The replay split is the single
    number most likely to be quoted at a judge and the single number most likely to
    go stale, because it moves whenever a defect is fixed -- it has moved twice.

    THIS TEST THEN MISSED THE SAME DRIFT IN `docs/FINAL_AUDIT_PACKAGE.md`, the page
    written for an external auditor, for both of those moves. It searched for the
    spelling `19/2/24`; that page writes `19 allow / 2 review / 24 block`. The regex
    matched nothing, nothing is trivially all-correct, and the test went green over a
    false headline in the document most likely to be read first.

    Two changes follow from that. The guard reads every spelling the corpus actually
    uses (`SPLIT_SPELLINGS`, enumerated by grep rather than by memory), and it asserts
    HOW MANY statements it found in each document (`EXPECTED_STATEMENTS`), so a
    rewording that blinds it fails here instead of passing silently.

    Documents that narrate the HISTORY of the boundary ("19/2/24 -> 18/3/24 ->
    17/4/24") are not the subject: a research log recording what was true at the time
    is correct, and so is a line that shows the number moving. This checks the
    documents that claim to describe the present, against the replay itself rather
    than against each other.
    """
    out = subprocess.run([sys.executable, "scripts/run_replay.py"],
                         cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    # The LAST match: the script prints a per-scenario line before the TOTAL, and
    # taking the first one compared every document against one scenario's counts.
    found_counts = re.findall(r"\{'allow': (\d+), 'review': (\d+), 'block': (\d+)\}",
                              out.stdout)
    assert found_counts, out.stdout[-500:]
    current = tuple(int(g) for g in found_counts[-1])
    assert sum(current) == 45, found_counts[-1]

    stale, blind = [], []
    for name, expected in EXPECTED_STATEMENTS.items():
        text = (ROOT / name).read_text()
        statements = _stated_splits(text)
        if len(statements) != expected:
            blind.append(f"{name}: guard reads {len(statements)} statement(s) of the "
                         f"split, expected {expected}")
        for line, split in _stale_statements(text, current):
            stale.append(f"{name}: {split} is not the current "
                         f"{current[0]}/{current[1]}/{current[2]} -- {line}")

    assert not blind, (
        "this guard has gone blind, which is how it passed over a false headline "
        "before. A document was reworded into a spelling SPLIT_SPELLINGS cannot read, "
        "or a statement was added or removed. Fix the pattern or update the count -- "
        "do not delete the assertion:\n  " + "\n  ".join(blind))
    assert not stale, (
        f"these documents state a replay split that is not the current "
        f"{current[0]}/{current[1]}/{current[2]}:\n  " + "\n  ".join(stale))


@pytest.mark.parametrize("spelling", [
    "the replay is 19/2/24 and always has been",
    "official replay: 45 events — 19 allow / 2 review / 24 block",
    "official replay: 45 events — 19 allow, 2 review, 24 block",
    "TOTAL events: 45  {'allow': 19, 'review': 2, 'block': 24}",
    "Official engine (UNCHANGED): 45 events  {allow: 19, review: 2, block: 24}",
    "| **Total** | **45** | **19** | **2** | **24** |",
])
def test_the_stale_split_guard_actually_fires(spelling):
    """THE NEGATIVE CONTROL, and the reason this file exists in its current form.

    `test_no_current_document_states_a_stale_replay_split` passed for two boundary
    moves while `docs/FINAL_AUDIT_PACKAGE.md` stated a false headline, because it
    knew one spelling of the number and that page used another. A regex that matches
    nothing passes every assertion after it, so the test was green precisely because
    it was blind.

    Every spelling here was taken from a document in this repository. If a future
    rewording of the guard stops recognising one, this fails -- which is the only
    thing that distinguishes a working check from a decorative one."""
    assert _stale_statements(spelling, (17, 4, 24)), (
        f"the guard does not recognise this as a claim about the replay split, so a "
        f"document written this way could state anything:\n  {spelling}")


@pytest.mark.parametrize("passage", [
    "the boundary moved: 19/2/24 -> 18/3/24 -> 17/4/24",
    "it said 19 allow / 2 review / 24 block; the engine produces "
    "17 allow / 4 review / 24 block",
    "<!-- superseded -->\nan earlier pass reported 19 allow / 2 review / 24 block",
])
def test_the_stale_split_guard_does_not_fire_on_a_document_discussing_history(passage):
    """The other half. A guard that flagged every mention of a past figure would make
    it impossible to write down that the figure changed -- and this repository's most
    useful documents are the ones that record exactly that. The exemptions are
    narrow and deliberate: the current figure in the same paragraph, an arrow showing
    the boundary moving, or an explicit marker."""
    assert not _stale_statements(passage, (17, 4, 24)), (
        f"this passage is discussing a superseded figure, not claiming it:\n  {passage}")


def test_every_unmaintained_document_says_so_at_the_top():
    """`docs/` IS 133 FILES AND A JUDGE CANNOT TELL WHICH ONES ARE CURRENT.

    Forty of them state an official replay split that is no longer the engine's --
    almost all correctly, because they record what was true when they were written.
    But nothing on their face said so. Opening `docs/archive/FINAL_GATE_REPORT.md` and reading
    "45 events - 19 allow / 2 review / 24 block", then running the replay and getting
    17/4/24, is enough for a reasonable auditor to stop believing the repository; and
    they would be right to, because one of those forty (`docs/FINAL_AUDIT_PACKAGE.md`,
    the page addressed to them) really was claiming it about the present.

    Rewriting the history would be worse than leaving it: the research logs are the
    evidence that the boundary moved for reasons. So each unmaintained document
    declares itself one, in a banner that states no figure of its own and therefore
    cannot go stale in turn.

    This test is the thing that keeps that true for documents written from here on."""
    out = subprocess.run([sys.executable, "scripts/run_replay.py"],
                         cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    counts = re.findall(r"\{'allow': (\d+), 'review': (\d+), 'block': (\d+)\}", out.stdout)
    current = tuple(int(g) for g in counts[-1])

    undeclared = []
    for path in sorted(ROOT.glob("docs/**/*.md")) + [ROOT / "README.md", ROOT / "RUNBOOK.md"]:
        relative = str(path.relative_to(ROOT))
        text = path.read_text()
        declared = SNAPSHOT_MARKER in text
        if relative in MAINTAINED_DOCS:
            assert not declared, (
                f"{relative} is listed as maintained but carries {SNAPSHOT_MARKER}. "
                f"A document cannot be both; remove one.")
            continue
        # The trigger is a STALE statement, not any mention. A document that states
        # the current split correctly is not lying, and banner-ing it as "not
        # maintained" would be its own small falsehood -- as well as burying the
        # marker's meaning under fifty uses of it. When the figure moves and that
        # document is left behind, this fires then, which is the right moment to
        # choose between correcting it and declaring it history.
        if _stale_statements(text, current, respect_snapshot=False) and not declared:
            undeclared.append(relative)
    assert not undeclared, (
        f"these documents state an official replay split, are not in MAINTAINED_DOCS, "
        f"and do not declare themselves a snapshot. Either maintain them (add to "
        f"MAINTAINED_DOCS and correct the figure) or put the banner at the top:\n  "
        + "\n  ".join(undeclared))


def test_the_maintained_list_is_not_quietly_emptied():
    """The escape hatch, closed. Every assertion above is satisfied by moving a
    document out of MAINTAINED_DOCS, which is a one-line way to stop checking the
    figures in the page a judge reads first."""
    for required in ("README.md", "docs/FINAL_AUDIT_PACKAGE.md", "docs/BASELINE_CURRENT.md"):
        assert required in MAINTAINED_DOCS, (
            f"{required} was removed from MAINTAINED_DOCS; it is a document that "
            f"claims to describe the present and its figures must stay checked")
    for name in MAINTAINED_DOCS:
        assert (ROOT / name).exists(), f"MAINTAINED_DOCS names {name}, which does not exist"

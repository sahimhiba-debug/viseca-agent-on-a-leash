"""The vacuity audit must be shown to catch a vacuous assertion.

`scripts/run_vacuity_audit.py` exists because a guard that examined nothing passed
for two boundary moves over a false headline. An instrument built in response to that
and never demonstrated to fire would be the same mistake wearing the fix's clothes.

So: build a synthetic `tests/` tree with one assertion that ran and one that did not,
hand the finder a coverage record saying exactly which lines executed, and check it
reports the second and not the first.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_vacuity_audit.py"

coverage = pytest.importorskip(
    "coverage", reason="the vacuity audit is a dev extra; `pip install -e \".[dev]\"`")


def _audit():
    spec = importlib.util.spec_from_file_location("_vacuity_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SYNTHETIC = '''\
def test_one_side_runs_and_the_other_does_not():
    value = 1
    if value == 1:
        assert value == 1
    if value == 2:
        assert value == 99, "this line is never reached"


def test_skipped_entirely():
    assert False, "this test never runs at all"
'''


def _synthetic_tree(tmp_path: Path) -> Path:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_synthetic.py").write_text(SYNTHETIC)
    return tmp_path


def test_the_audit_reports_an_assertion_that_never_ran(tmp_path):
    root = _synthetic_tree(tmp_path)
    target = root / "tests" / "test_synthetic.py"

    # Lines 1-4 ran (the test and the taken branch); line 5's `if` ran and line 6's
    # assertion did not. The second test never ran at all.
    data_file = tmp_path / ".coverage.synthetic"
    data = coverage.CoverageData(str(data_file))
    data.add_lines({str(target.resolve()): [1, 2, 3, 4, 5]})
    data.write()

    findings = _audit().never_executed_assertions(data_file, root=root)
    reported = {(line, fn) for _, line, fn, _ in findings}

    assert (6, "test_one_side_runs_and_the_other_does_not") in reported, (
        f"the audit missed an assertion that never executed; it reported {reported}")
    assert (4, "test_one_side_runs_and_the_other_does_not") not in reported, (
        "the audit reported an assertion that DID execute")


def test_the_audit_does_not_report_a_skipped_test(tmp_path):
    """The false-positive half. A skipped test's assertions did not run because the
    test did not run -- pytest already says so, loudly, and reporting it here would
    bury the real findings under every skip in the suite."""
    root = _synthetic_tree(tmp_path)
    target = root / "tests" / "test_synthetic.py"

    data_file = tmp_path / ".coverage.synthetic"
    data = coverage.CoverageData(str(data_file))
    data.add_lines({str(target.resolve()): [1, 2, 3, 4, 5]})
    data.write()

    findings = _audit().never_executed_assertions(data_file, root=root)
    assert not any(fn == "test_skipped_entirely" for _, _, fn, _ in findings), (
        "a skipped test was reported as carrying a vacuous assertion")


def test_the_audit_refuses_to_report_over_a_failing_suite():
    """Pinned in the source: an assertion that did not run because the test died three
    lines above it is not vacuous, and saying it is sends somebody to rewrite a test
    that works."""
    body = SCRIPT.read_text()
    assert "REFUSING TO REPORT" in body
    assert "result.returncode != 0" in body, (
        "the script must check the suite passed before drawing conclusions from "
        "which lines ran")

"""Which assertions in this suite have never actually run?

WHY THIS EXISTS

`test_no_current_document_states_a_stale_replay_split` searched every "current"
document for the spelling `19/2/24`. The document that was actually stale wrote the
same fact as `19 allow / 2 review / 24 block`. The regex matched nothing, and nothing
is trivially all-correct, so the test went green for two boundary moves over a false
headline in the page written for an external auditor.

The bug was not the regex. The bug is a shape: **a check that examines nothing passes
every assertion after it.** A test's green tick says its assertions did not fail. It
does not say they ran.

WHAT THIS MEASURES

Run the suite under `coverage`, then cross the executed-line set against every
`assert` in `tests/`. An assertion inside a test that ran, on a line that never
executed, is an assertion that has never been evaluated -- a claim the repository
makes and does not check. Skipped tests are excluded: their assertions did not run
because the test did not run, which is honest and visible.

WHAT IT FOUND THE FIRST TIME, out of roughly 1,800 tests:

  * `test_F3_concurrent_answers_to_one_step_up_cannot_both_be_accepted` asserted that
    a DECLINED purchase holds no live payment authority, under `if stored.decision ==
    "block"`. Measured over 150 races, the declining thread won once: whichever
    thread starts second wins ~99% of the time. The most important line in a
    concurrency test ran in under 1% of runs and in none of the suite runs sampled.
  * `test_baselines_are_captured_once_before_any_mutation` walked `main` for "the
    first loop that writes a file". `ast.walk` descends into nested functions, and
    `main` defines its signal handler first -- so the test inspected the handler's
    restore loop, which contains no assignments, so its filter skipped every node.
    It had been checking the wrong function since the handler was added.
  * `test_the_dockerfile_and_compose_exist_and_bake_no_secrets` looked for lines with
    both `API_KEY` and `=`. docker-compose.yml passes keys through as YAML
    (`ANTHROPIC_API_KEY: "${...}"`) -- a colon, no equals. The secret scan examined
    zero lines and would have passed over a hard-coded key.
  * `test_the_agents_proposals_do_not_depend_on_the_secret_limit` compared ceilings
    of CHF 60 and CHF 200. The wallet's answers diverge at attempt zero, so the loop
    checking every revision broke immediately, every time.
  * three more, in the compiler fuzz corpus and the Hypothesis properties, where a
    defensive `if x is not None:` was never entered and a loop over generated rules
    was always empty.

None of these were failing. All of them were reporting success about something they
had not looked at.

RUNNING IT

    python3 scripts/run_vacuity_audit.py

Needs `coverage`, which is a dev extra rather than a runtime dependency: this is an
audit instrument, not part of the gate, and it costs a full extra suite run. Exit
code is non-zero if any assertion never executed.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def never_executed_assertions(coverage_file: pathlib.Path,
                              root: pathlib.Path = ROOT) -> list[tuple[str, int, str, str]]:
    import coverage

    data = coverage.CoverageData(str(coverage_file))
    data.read()
    executed = {f: set(data.lines(f) or []) for f in data.measured_files()}

    findings = []
    for path in sorted((root / "tests").rglob("*.py")):
        full = str(path.resolve())
        if full not in executed:
            findings.append((str(path.relative_to(root)), 0, "(whole file)",
                             "never imported during the run"))
            continue
        ran = executed[full]
        tree = ast.parse(path.read_text())
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            if not fn.name.startswith("test_"):
                continue
            # A test whose own lines never ran was SKIPPED. Its assertions not running
            # is honest and already reported by pytest; only a test that ran and
            # stepped over an assertion is a finding.
            body = {n.lineno for n in ast.walk(fn) if hasattr(n, "lineno")}
            if not (body & ran):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Assert):
                    continue
                # Multi-line assertions report the line the statement STARTS on, but
                # tracing may attribute the hit anywhere in the span. Checking the
                # whole range avoids reporting well-exercised assertions as dead --
                # an audit that cries wolf is one nobody runs twice.
                span = set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
                if not (span & ran):
                    findings.append((str(path.relative_to(root)), node.lineno,
                                     fn.name, ast.unparse(node)[:100]))
    return findings


def main() -> int:
    print("VACUITY AUDIT -- assertions that never ran\n")
    try:
        import coverage                                      # noqa: F401
    except ModuleNotFoundError:
        print("  coverage is not installed. It is a dev extra, not a runtime "
              "dependency:\n      pip install -e \".[dev]\"\n  or: pip install coverage")
        return 2

    data_file = ROOT / ".coverage.vacuity"
    data_file.unlink(missing_ok=True)
    print("  running the suite under coverage (about 50% slower than a plain run)...")
    result = subprocess.run(
        [sys.executable, "-m", "coverage", "run", f"--data-file={data_file}",
         "--source=tests", "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True)
    tail = [l for l in result.stdout.splitlines() if l.strip()][-1:]
    print(f"  {tail[0] if tail else '(no pytest summary)'}")

    if result.returncode != 0:
        # A FAILING SUITE INVALIDATES THIS MEASUREMENT, and saying so is the point.
        # An assertion that never ran because the test died three lines above it is
        # not a vacuous assertion, and reporting it as one would send somebody to
        # rewrite a test that is working exactly as intended.
        print("\n  REFUSING TO REPORT: the suite did not pass, so an assertion that "
              "did not run\n  may simply be downstream of a failure. Fix the suite "
              "first.")
        data_file.unlink(missing_ok=True)
        return 2

    findings = never_executed_assertions(data_file)
    data_file.unlink(missing_ok=True)

    if not findings:
        print("\n  0 assertions in tests/ went unevaluated. Every assertion in a test "
              "that ran\n  was reached at least once.")
        return 0

    print(f"\n  {len(findings)} assertion(s) never ran:\n")
    for relative, line, fn, src in findings:
        print(f"    {relative}:{line}")
        print(f"        in {fn}")
        print(f"        {src}\n")
    print("  Each of these is a claim this repository makes and does not check. The "
          "test\n  passes because the assertion is never reached, not because it "
          "holds.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

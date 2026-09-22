"""A harness that edits the source it is testing must leave it exactly as it found it.

WHAT HAPPENED

`scripts/run_mutation_probe.py` mutates a file in place, runs the suite, and
restores it in a `finally`. That survives an exception and Ctrl-C. It does not
survive SIGKILL, which is what a harness timeout sends -- and the script took
longer than one.

The second half is what made it expensive. Each mutant read its baseline FRESH
from disk, so one killed run poisoned every later one: mutant B read mutant A's
stranded edit as "the original" and faithfully restored it afterwards. Two
mutations ended up living in `decision_engine.py`:

    _decide:                   `if failures:`          ->  `if False:`
    _reported_mandate_status:  `_MANDATE_STATUS_ABSENT` -> `MandateStatus.ACTIVE.value`

The first is the single most important line in the engine: every hard-rule failure
stopped blocking.

I first wrote here that the suite passed anyway. **That was wrong, and measuring it
gave the more useful answer.** Applied to a clean worktree, the suite catches it on
the thirteenth test. The corruption survived because of ORDERING: the gate ran
`pytest` and then the mutation probe in one command, so the suite only ever saw the
tree before the probe touched it. The one thing that ran afterwards was the planning
benchmark, which fell from 11/11 to 4/11 -- and that looked like a regression in an
unrelated refactor, which is what cost the hour.

So the lesson is not "the tests are weak". It is that **a gate which ends with a
tool that edits source has verified nothing about the tree it leaves behind.**

THE FIXES, AND WHY EACH ONE IS NEEDED

  * baselines are captured ONCE, before the first mutation, so a mutant can never
    inherit a poisoned original;
  * an outer `finally` restores every target and then VERIFIES the write, because a
    restore that silently failed is how the last one got through;
  * the script checks the patient is alive before operating: CHF 45 against a CHF 5
    ceiling must BLOCK. No mutant in the file would leave that standing, so if it
    does not hold, the tree is already mutated and the script refuses to run rather
    than producing results about a corpse;
  * and the last test here asserts the tree is clean, so any tool that leaves
    droppings is caught by the suite rather than by a puzzling benchmark score.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts" / "run_mutation_probe.py"


def test_the_probe_refuses_to_run_on_an_already_mutated_tree(tmp_path):
    """The health check, exercised for real: mutate a copy of the engine the way the
    stranded run did, point the script at it, and it must decline."""
    work = tmp_path / "repo"
    subprocess.run(["git", "worktree", "add", "--detach", str(work), "HEAD"],
                   cwd=ROOT, check=True, capture_output=True)
    try:
        # A worktree carries the COMMITTED files. Copy the working-tree versions of
        # the script under test and the engine it inspects, or this exercises
        # whatever the probe looked like at HEAD rather than what it looks like now.
        for relative in ("scripts/run_mutation_probe.py",
                         "src/wallet_control/decision_engine.py",
                         "src/wallet_control/rules.py",
                         "src/wallet_control/facts.py",
                         "src/wallet_control/state.py"):
            (work / relative).write_text((ROOT / relative).read_text())
        engine = work / "src" / "wallet_control" / "decision_engine.py"
        source = engine.read_text()
        assert "    if failures:\n" in source
        engine.write_text(source.replace("    if failures:\n", "    if False:\n", 1))

        result = subprocess.run([sys.executable, "scripts/run_mutation_probe.py"],
                                cwd=work, capture_output=True, text=True, timeout=300)
        assert result.returncode == 2, result.stdout[-2000:]
        assert "REFUSING TO RUN" in result.stdout
        assert "already mutated" in result.stdout
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(work)],
                       cwd=ROOT, capture_output=True)


def test_baselines_are_captured_once_before_any_mutation():
    """The poisoning bug, pinned at the source. If a future edit moves the read back
    inside the loop, one killed run makes every later one wrong."""
    tree = ast.parse(PROBE.read_text())
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    loops = [n for n in ast.walk(main) if isinstance(n, ast.For)]
    mutating_loop = next(
        loop for loop in loops
        if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
               and c.func.attr == "write_text" for c in ast.walk(loop)))
    reads_inside = [c for c in ast.walk(mutating_loop)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "read_text"]
    assert reads_inside == [], (
        "the mutating loop reads a file from disk; its baseline must come from the "
        "originals captured before the first mutation, or one interrupted run "
        "poisons every later one")


def test_the_restore_is_verified_and_not_assumed():
    body = PROBE.read_text()
    assert "COULD NOT RESTORE" in body, "a failed restore must be reported loudly"
    assert "git checkout -- src/" in body, "and must say how to recover"
    main_body = body.split("def main()")[1]
    assert main_body.count("finally:") >= 2, (
        "one finally per mutant is not enough; an outer one must restore every "
        "target whatever happened inside the loop")


@pytest.mark.skipif(os.environ.get("WALLET_MUTATION_PROBE") == "1",
                    reason="the mutation probe mutates the tree on purpose; this "
                           "backstop would fire on every mutant and report spurious "
                           "kills -- a harness grading itself")
def test_the_source_tree_carries_no_stranded_mutation():
    """The backstop, and the cheapest one available. Any tool that edits source and
    fails to put it back is caught here rather than by a benchmark score nobody can
    explain. Uncommitted work is normal and fine -- what is not fine is the specific
    shape a mutant leaves.

    It has to opt out while the probe runs, and that opt-out is itself a risk: a
    test that skips whenever an environment variable is set is a test an attacker
    (or a careless script) can silence. It is acceptable here only because the flag
    is set by one script in this repository, the skip is REPORTED rather than
    silent, and `test_the_probe_sets_the_flag_it_claims_to` pins the one place that
    sets it."""
    engine = (ROOT / "src" / "wallet_control" / "decision_engine.py").read_text()
    assert "    if failures:\n" in engine, (
        "`_decide` no longer blocks on hard-rule failures -- a stranded mutation")
    assert "    if False:" not in engine, "a mutant is still in the working tree"
    for module in ("decision_engine.py", "rules.py", "state.py", "mandate.py"):
        body = (ROOT / "src" / "wallet_control" / module).read_text()
        assert "if False:" not in body, f"{module} carries a stranded mutant"


def test_the_health_check_reads_the_tree_it_is_about_to_cut():
    """It used to read whatever `pip install -e` had pointed at.

    The package is installed editable, so a plain `import wallet_control` inside the
    script resolves to the checkout pip was configured with -- not necessarily the
    one being mutated. A health check that inspects a different copy of the engine
    than the one it cuts is worse than none: it reports healthy and proceeds. The
    worktree test above is the proof it now reads the right files; this pins the
    mechanism so it cannot quietly regress to a plain import."""
    body = PROBE.read_text()
    check = body.split("def _tree_is_healthy")[1].split("\ndef ")[0]
    assert 'sys.path.insert(0, str(ROOT / "src"))' in check
    assert "del sys.modules[name]" in check, (
        "an already-imported wallet_control would win over the path insert")
    assert check.index('ROOT / "src"') < check.index("from wallet_control"), (
        "the path must be set before the engine is imported")


def test_the_health_check_passes_on_a_healthy_tree():
    """The control. A check that refused everything would make the probe unusable
    and would still pass the test above.

    Run in a SUBPROCESS, and that is not incidental: `_tree_is_healthy` clears
    `wallet_control` out of `sys.modules` so it imports the tree being cut rather
    than the editable install. Correct for a script, catastrophic in-process -- the
    first version of this test called it directly and unloaded the package for every
    test that ran after it, nine of which failed in ways that had nothing to do with
    the probe."""
    result = subprocess.run([sys.executable, "scripts/run_mutation_probe.py", "--check-only"],
                            cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-1500:]
    assert "health check passed" in result.stdout


def test_the_health_check_is_never_called_in_process_by_the_suite():
    """The hazard, pinned. It unloads `wallet_control`; a test that calls it directly
    breaks every test that follows, and the failures look unrelated."""
    tree = ast.parse(Path(__file__).read_text())
    called = [node for node in ast.walk(tree)
              if isinstance(node, ast.Call)
              and getattr(node.func, "attr", getattr(node.func, "id", None))
              == "_tree_is_healthy"]
    assert called == [], (
        "this suite calls _tree_is_healthy in-process; it unloads wallet_control "
        "and every test after it fails for unrelated-looking reasons. Run "
        "`scripts/run_mutation_probe.py --check-only` in a subprocess instead.")


def test_the_probe_sets_the_flag_it_claims_to():
    """The opt-out above is only safe if exactly one script sets it, and that script
    is this repository's own. Pinned so the flag cannot quietly spread."""
    body = PROBE.read_text()
    assert 'WALLET_MUTATION_PROBE": "1"' in body
    setters = subprocess.run(
        ["git", "grep", "-l", "WALLET_MUTATION_PROBE", "--", "src", "scripts", "tests"],
        cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert sorted(setters) == sorted([
        "scripts/run_mutation_probe.py",
        "tests/security/test_mutation_probe_is_safe.py",
    ]), setters
    assert "WALLET_MUTATION_PROBE" not in (
        ROOT / "src" / "wallet_control" / "decision_engine.py").read_text(), (
        "the runtime must never read this flag")

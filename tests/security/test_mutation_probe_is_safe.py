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
    """The poisoning bug, pinned at the source.

    The loop may READ a target -- that is the race guard, comparing the file against
    what it just wrote so a concurrent edit is not silently reverted. What it may not
    do is take its BASELINE from disk: that is how one killed run poisoned every
    later one, mutant B reading mutant A's stranded edit as "the original".

    So the check is on where `source` comes from, not on whether the loop reads."""
    tree = ast.parse(PROBE.read_text())
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")

    # NOT `ast.walk(main)`, and this test passed vacuously for exactly that reason.
    # `walk` descends into nested function definitions, and `main` defines the signal
    # handler `_restore_and_exit` BEFORE the mutant loop. The handler contains its own
    # `for ... : write_text(...)`, so "the first loop in main that writes a file" found
    # the handler's restore loop -- which contains no assignments at all, so the filter
    # below skipped every node and the assertion never ran once. Measured with
    # `coverage`: lines 111-117 of the previous version were never executed by a
    # passing suite. The test was inspecting the wrong function and reporting success.
    def _direct_loops(node):
        """Loops belonging to `node` itself, not to functions defined inside it."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.For):
                yield child
            yield from _direct_loops(child)

    mutating_loop = next(
        loop for loop in _direct_loops(main)
        if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
               and c.func.attr == "write_text"
               and any(isinstance(a, ast.Name) and a.id == "mutated_text" for a in c.args)
               for c in ast.walk(loop)))

    assignments = [n for n in ast.walk(mutating_loop) if isinstance(n, ast.Assign)]
    assert assignments, (
        "no assignments found in the mutating loop, so the check below inspects "
        "nothing. That is how this test passed while reading the wrong loop.")

    for node in ast.walk(mutating_loop):
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        reads = any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "read_text" for c in ast.walk(node.value))
        assert not (names & {"source", "original", "mutated_text"} and reads), (
            f"{names} is taken from disk inside the mutating loop; a baseline must "
            f"come from the originals captured before the first mutation, or one "
            f"interrupted run poisons every later one")

    assert "originals[module]" in PROBE.read_text(), (
        "the loop no longer takes its baseline from the captured originals")


def test_the_probe_will_not_clobber_a_concurrent_edit():
    """The second way this tool destroyed work, found by it destroying some.

    A long probe was backgrounded, the engine was edited while it ran, and every
    restore quietly reverted those edits -- the file went back to a baseline captured
    before they existed. Crash-safety did not help: nothing had crashed.

    It now compares the file against what it wrote before restoring, and stops."""
    body = PROBE.read_text()
    assert "changed during the run" in body
    assert "STOPPED EARLY" in body, "a partial run must say so, or its counts lie"
    assert "if module in edited:" in body, (
        "the outer restore must skip a file somebody else now owns")

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


def _load_probe():
    """Import the script as a module. Safe in-process: nothing at module level does
    anything but define constants and functions. `_tree_is_healthy` is the one that
    must never be called here -- it unloads `wallet_control` -- and
    `test_the_health_check_is_never_called_in_process_by_the_suite` enforces that."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_probe_under_test", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_strand_detector_would_catch_every_mutant_in_the_table():
    """The check that the startup check is not a check that cannot fail.

    Three versions of the "is the tree already mutated?" guard have now been wrong.
    The first grepped for `if False:` -- one shape out of forty-one -- and reported a
    clean tree over a mutated one. The second asked git whether `src/` was dirty,
    which cannot distinguish a stranded mutant from uncommitted work and so refused
    to run during ordinary development. The third reasons from the mutant table
    itself, and its first draft silently missed three entries: those mutants EXTEND
    the line they cut (`for end, _ in trial` -> `for end, _ in trial[:1]`), so the
    original text survives inside its own replacement and "the original is gone" is
    never true.

    That was found by measuring rather than by reading, which is the only reason this
    test exists in this form: it does not inspect the predicate, it SIMULATES every
    mutation in the table and asserts the detector sees it. A new mutant whose strand
    would be invisible fails here instead of being discovered by a benchmark score
    nobody can explain."""
    probe = _load_probe()
    invisible, false_positives, not_unique = [], [], []
    for module, original, mutated, label in probe.MUTANTS:
        text = (probe.SRC / module).read_text()
        if text.count(original) != 1:
            not_unique.append(f"{label}: {text.count(original)} occurrences in {module}")
        if probe._looks_stranded(text, original, mutated):
            false_positives.append(label)
        if not probe._looks_stranded(text.replace(original, mutated, 1), original, mutated):
            invisible.append(label)

    assert not_unique == [], (
        "a mutant's original text is not unique in its module, so `replace(..., 1)` "
        "cuts an arbitrary one of them and the mutant's label is a guess:\n  "
        + "\n  ".join(not_unique))
    assert false_positives == [], (
        "the detector fires on the PRISTINE tree for these mutants, which would make "
        "the probe refuse to run forever:\n  " + "\n  ".join(false_positives))
    assert invisible == [], (
        "these mutants would be INVISIBLE if a killed run stranded them, which is the "
        "exact failure this guard exists to prevent:\n  " + "\n  ".join(invisible))
    assert len(probe.MUTANTS) >= 41, "mutants disappeared from the table"


def test_a_breadcrumb_from_a_dead_run_stops_the_next_one(tmp_path, monkeypatch):
    """The textual detector above is a heuristic; this is the proof.

    It reasons about what the tree LOOKS like, and it is blind by construction to one
    case: a mutant stranded by a version of the table that has since been edited. The
    breadcrumb is written before the cut and removed after the restore is verified, so
    finding one is evidence of what the previous run SAID it was doing, not an
    inference from the damage.

    Run against a copy of the repo so a failure cannot leave a real breadcrumb behind.
    """
    work = tmp_path / "repo"
    subprocess.run(["git", "worktree", "add", "--detach", str(work), "HEAD"],
                   cwd=ROOT, check=True, capture_output=True)
    try:
        (work / "scripts" / "run_mutation_probe.py").write_text(PROBE.read_text())
        (work / ".mutation-probe-inflight.json").write_text(
            '{"module": "state.py", "label": "a mutant from a table that no longer '
            'exists", "original": "ORIGINAL TEXT", "mutated": "MUTATED TEXT"}')

        result = subprocess.run(
            [sys.executable, "scripts/run_mutation_probe.py", "--check-only"],
            cwd=work, capture_output=True, text=True, timeout=120)
        assert result.returncode == 2, result.stdout[-2000:]
        assert "REFUSING TO RUN" in result.stdout
        assert "died while state.py was cut open" in result.stdout
        assert "a mutant from a table that no longer exists" in result.stdout, (
            "the refusal must name the mutant; a bare 'tree is dirty' is what the "
            "previous version said and it is not actionable")
        assert "ORIGINAL TEXT" in result.stdout, "it must print the text to put back"
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(work)],
                       cwd=ROOT, capture_output=True)


def test_the_breadcrumb_is_written_before_the_cut_and_cleared_after_the_restore():
    """Order is the whole mechanism.

    A breadcrumb written after the edit is missing for exactly the kill it exists to
    survive, and one cleared before the restore is verified says the tree is clean
    while it is not. Pinned in the source because the race is not reproducible in a
    test: you cannot SIGKILL a process reliably between two adjacent statements."""
    body = PROBE.read_text()
    # Anchored inside `main`, because the same loop header appears in the strand
    # detector above it and splitting on the first match reads the wrong function.
    loop = body.split("def main()")[1].split(
        "for module, original, mutated, label in MUTANTS:")[1]
    cut = loop.index("path.write_text(mutated_text)")
    crumb = loop.index("INFLIGHT.write_text")
    assert crumb < cut, "the breadcrumb must be written BEFORE the mutation is applied"

    restore = loop.index("path.write_text(source)")
    cleared = loop.index("INFLIGHT.unlink", restore)
    assert restore < cleared, "the breadcrumb must be cleared AFTER the file is restored"

    assert "if not stranded and not edited:" in body, (
        "the outer restore must keep the breadcrumb when a file was left mutated or "
        "was edited by someone else -- those are the runs the next one must refuse")

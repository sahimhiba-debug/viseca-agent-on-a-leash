#!/usr/bin/env python3
"""Break the security core on purpose and check the suite notices.

A test count proves nothing. 694 tests that all pass against a DELIBERATELY BROKEN
engine would be theatre, and "our tests are thorough" is exactly the claim an
external auditor should refuse to take on trust. So this script asks the only
question that settles it: if I remove a security mechanism, does anything fail?

Each mutant below is a one-line edit to `src/wallet_control/` that removes or
inverts a specific protection. The script applies it, runs the full suite, records
which test failed first, and restores the file. A mutant that SURVIVES is a hole:
the mechanism is unprotected and can be refactored away by accident.

    python3 scripts/run_mutation_probe.py

This is a targeted probe, not exhaustive mutation testing. The mutants are chosen
to hit the invariants in docs/FINAL_INVARIANTS.md -- the window arithmetic, the
`fail > unknown > pass` precedence, the uncertainty policy, run binding, and the
mandate status checks -- rather than generated over every operator in the tree.
It cannot tell you about a mechanism nobody thought to mutate. It can tell you
that the ones listed here are genuinely held.

RESULT AT THE TIME OF WRITING: 45 mutants, 45 killed, 0 survived.

One survivor was found when this probe was first run: widening the rolling window's
start from `end - window < ts` to `end - window <= ts` passed the entire suite.
Not a safety hole -- a wider window only ever blocks more -- but it meant nothing
pinned WHICH window the engine means, so the half-open boundary is now a test
(`test_the_rolling_window_is_half_open_exactly_N_days_ago_is_outside_it`). That is
what this probe is for.
"""

from __future__ import annotations

import json
import pathlib
import os
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "wallet_control"

# Written to disk BEFORE each cut and removed after the restore is verified. A
# breadcrumb survives SIGKILL because it is already on disk when the killing
# happens; a signal handler does not. Finding one at startup is proof that a
# previous run died holding a scalpel, and it names which one.
INFLIGHT = ROOT / ".mutation-probe-inflight.json"

# (module, original source, mutated source, what protection it removes)
MUTANTS: list[tuple[str, str, str, str]] = [
    # --- the rolling window: invariant I15 -----------------------------------
    ("state.py", "end - window < ts <= end", "end - window <= ts <= end",
     "window start becomes inclusive"),
    ("state.py", "end - window < ts <= end", "end - window < ts < end",
     "window end becomes exclusive"),
    ("state.py", "for end, _ in trial", "for end, _ in trial[:1]",
     "only the first window is checked, not every containing one"),
    ("state.py", "trial = [*self._approved_spend, (as_of, amount)]", "trial = [*self._approved_spend]",
     "the candidate purchase is not counted against its own window"),

    # --- rule comparison and evidence semantics: I9-I12 ----------------------
    ("rules.py", 'if operator == "<=":\n        return actual <= expected',
     'if operator == "<=":\n        return actual < expected', "<= becomes <"),
    ("rules.py", 'if operator == ">=":\n        return actual >= expected',
     'if operator == ">=":\n        return actual > expected', ">= becomes >"),
    ("rules.py", '        if mismatched:\n            return RuleEvaluation(rule, "fail"',
     '        if False:\n            return RuleEvaluation(rule, "fail"',
     "a stated size that does not match no longer fails"),
    ("rules.py", '        silent = [i.item_name for i in candidates if i.stated_size is None]\n        if silent:',
     '        silent = [i.item_name for i in candidates if i.stated_size is None]\n        if False:',
     "a line stating no size no longer escalates"),
    ("rules.py", '            return RuleEvaluation(\n                rule, "unknown",\n                "the seller says returns do not apply',
     '            return RuleEvaluation(\n                rule, "pass",\n                "the seller says returns do not apply',
     '"not applicable" satisfies a return requirement again'),

    # --- decision precedence and uncertainty policy: I7 ----------------------
    ("decision_engine.py", '    failures = [e for e in evaluations if e.outcome == "fail"]\n    if failures:',
     '    failures = [e for e in evaluations if e.outcome == "fail"]\n    if False:',
     "a hard-rule FAILURE no longer blocks"),
    ("decision_engine.py", '    unknowns = [e for e in evaluations if e.outcome == "unknown"]\n    if unknowns:',
     '    unknowns = [e for e in evaluations if e.outcome == "unknown"]\n    if False:',
     "UNKNOWN silently becomes allow"),
    ("decision_engine.py", '        if uncertainty_policy == UncertaintyPolicy.DECLINE:\n            return "block", reason_codes',
     '        if uncertainty_policy == UncertaintyPolicy.DECLINE:\n            return "review", reason_codes',
     "a decline policy escalates instead of blocking"),
    ("decision_engine.py", '        return "review", reason_codes', '        return "allow", reason_codes',
     "an ask policy approves instead of asking"),

    # --- concurrency and human resolution ------------------------------------
    # The brief's freeze audit named eight defect shapes to verify the SUITE against.
    # Six were already mutants. These two -- the run lock and the already-resolved
    # guard -- were security-critical and unmutated, which is exactly the gap a
    # probe is for.
    ("state.py", '        """Hold the run\'s lock across a check-then-record sequence."""\n        return self._consume_lock',
     '        """Hold the run\'s lock across a check-then-record sequence."""\n        import contextlib\n\n        return contextlib.nullcontext()',
     "the decision path is no longer atomic within one process"),
    ("decision_engine.py", '        already_resolved = pending is not None and pending.decision != "review"',
     "        already_resolved = False",
     "an answered purchase can be answered again and overridden"),

    ("policy_compiler.py", "    if unused and used:", "    if False:",
     "a stated amount that became no rule vanishes in silence again"),

    # --- post-audit remediation: I40, I41, I42, I43 --------------------------
    ("state.py", "DEFAULT_AUTHORITY_TTL = timedelta(minutes=15)", "DEFAULT_AUTHORITY_TTL = timedelta(days=3650)",
     "a payment authority never effectively expires"),
    ("state.py", "        if timestamp is not None and existing.timestamp != timestamp:\n            return False",
     "        if False:\n            return False",
     "two economic transactions under one id read as a retry again"),
    ("decision_engine.py", "    if not isinstance(raw_id, str) or not raw_id.strip():",
     "    if False:",
     "a null or empty authorization_id is accepted again"),
    ("mandate.py", "        if outstanding:", "        if False:",
     "unsupported restrictive intent no longer blocks confirmation"),
    ("mandate.py", "            unsupported_restrictions=list(unsupported_restrictions or []),",
     "            unsupported_restrictions=[],",
     "a drafted mandate silently drops the unsupported restrictions"),
    ("live_worker.py", "        if problems:", "        if False:",
     "a widened platform echo silently becomes the policy again"),

    # --- agent planner boundary: I47 ------------------------------------------
    ("decision_engine.py", "def agent_view(decision: \"EngineDecision\") -> dict[str, Any]:",
     "def agent_view(decision: \"EngineDecision\") -> dict[str, Any]:\n    return {**decision.__dict__, \"blocked_by\": []}",
     "the agent projection returns the whole decision object"),

    # --- agent explanation boundary: I45 --------------------------------------
    ("decision_engine.py", '        "blocked_by": classes,',
     '        "blocked_by": classes, "policy": [r.rule.field + "=" + str(r.rule.value) for r in decision.rule_evaluations],',
     "the agent projection starts carrying policy values"),
    ("api.py", '        fields = [c.split(":", 1)[1] for c in stored.reason_codes if ":" in c]',
     '        return f"Declined: {\', \'.join(stored.reason_codes) or \'a check failed\'}"\n        fields = []',
     "a re-presented decision shows raw reason codes to the customer again"),

    # --- customer-facing explanation: I39 ------------------------------------
    ("decision_engine.py", "    reasons = list(dict.fromkeys(_plain_reason(e) for e in problems))",
     '    reasons = [f"{e.rule.field} ({e.outcome}): {e.detail}" for e in problems]',
     "the engine's debug dump is sent to the customer again"),

    # --- intent fidelity: I37, I38 -------------------------------------------
    ("policy_compiler.py", "        if v not in period_amount_values", "        if True",
     "a period-qualified amount becomes a per-order ceiling again"),
    ("policy_compiler.py", "    unsupported = unenforceable + _coverage_questions(text, rules)",
     "    unsupported = []",
     "restrictive language with no rule is dropped in silence again"),
    # Intent that was RECOGNISED but cannot be enforced is a different loss from
    # intent that was never recognised, and it has its own way of going quiet.
    ("policy_compiler.py", "    unsupported = unenforceable + _coverage_questions(text, rules)",
     "    unsupported = _coverage_questions(text, rules)",
     "recognised-but-unenforceable intent stops being reported"),
    # The rule that only means something beside another rule. Emitting it alone is
    # what made appending a rule WIDEN the policy.
    ("policy_compiler.py", '        if any(r.field == "item.category" for r in rules):',
     "        if True:",
     "an unenforceable 'nothing unrequested' is compiled as a rule again"),

    ("policy_compiler.py", '    text = re.sub(r"\\s+", " ", instruction).strip()',
     "    text = instruction.strip()",
     "whitespace is significant again, losing the ceiling on a double space"),
    ("policy_compiler.py", "    text = _normalise_currency(text)",
     "    text = text",
     '"max 400 francs" loses its ceiling silently again'),
    ("policy_compiler.py", "    if _looks_non_english(text):",
     "    if False:",
     "an instruction in French or German is confirmable with its restrictions unread"),
    ("policy_compiler.py", "    text = _N_DAY_PERIOD_RE.sub(lambda m: f\"{m.group('n')} days\", text)",
     "    text = text",
     "'CHF 400 within any seven-day period' becomes a per-order ceiling again"),
    ("facts.py", "unicodedata.normalize(\"NFKC\", (text or \"\")[:_MAX_UNTRUSTED_CHARS])",
     "unicodedata.normalize(\"NFKC\", (text or \"\"))",
     "a seller's text length spends the decision deadline again"),
    ("policy_compiler.py", "        if v not in period_amount_values and v not in total_amounts",
     "        if v not in period_amount_values",
     "an overall total becomes a per-order ceiling again"),
    ("policy_compiler.py", '    per_order_operator = "<" if _STRICT_LIMIT_RE.search(text) else "<="',
     '    per_order_operator = "<="',
     '"under CHF 50" admits exactly CHF 50 again'),

    # --- velocity cross-check: I35 -------------------------------------------
    ("decision_engine.py", "            device_id, max(reported_attempts, observed_attempts), merchant_familiar",
     "            device_id, reported_attempts, merchant_familiar",
     "the event's own velocity claim is taken on trust again"),

    # --- empty-collection vacuity: I34 ---------------------------------------
    ("decision_engine.py", "        if not facts.items:", "        if False:",
     "an empty basket is no longer a structural failure"),
    ("rules.py", '    if field.startswith("item.") and not facts.items:', "    if False:",
     "item rules are vacuously satisfied by an empty basket again"),

    # --- run binding and mandate status: I20, I21, I33 -----------------------
    ("decision_engine.py", '    if auth.get("card_id") != state.card_id:', '    if False:',
     "an event carrying another CARD's identity is accepted"),
    ("decision_engine.py", '    if auth.get("mandate_id") != mandate.mandate_id:', '    if False:',
     "an event carrying another MANDATE's identity is accepted"),
    ("decision_engine.py", '    if mandate.status is not MandateStatus.ACTIVE:', '    if False:',
     "a non-active mandate snapshot authorizes purchases"),
    ("decision_engine.py", '    if reported_mandate_status != mandate.status.value:', '    if False:',
     "the platform's LIVE mandate status is ignored"),
    ("decision_engine.py",
     '    block = event.get("mandate")\n    if not isinstance(block, dict):\n        return _MANDATE_STATUS_ABSENT',
     '    block = event.get("mandate")\n    if not isinstance(block, dict):\n        return MandateStatus.ACTIVE.value',
     "a missing mandate block reads as active"),
]


def _run_suite() -> tuple[bool, str]:
    # The suite carries a backstop asserting no stranded mutation is in the tree.
    # During THIS script the tree is mutated on purpose, so that backstop would fire
    # on every mutant and report 39 spurious kills -- a harness grading itself. The
    # flag tells it to skip, and a skip is visible in the count rather than silent.
    env = {**os.environ, "WALLET_MUTATION_PROBE": "1"}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-x", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    return result.returncode == 0, result.stdout


def _inflight_refusal() -> str:
    """The definitive check, and the only one that does not depend on guessing.

    The two textual checks below reason about what the tree LOOKS like. This one reads
    what the previous run SAID it was doing: the breadcrumb is written before the cut
    and removed after the restore is verified, so finding one means a run died between
    those two moments. It covers the shapes the textual net cannot -- including a
    mutant from a table that has since been edited, which is precisely the case the
    textual net is blind to by construction.

    It does not repair anything. A file may have been edited since, and this project
    has already destroyed a morning's work once by restoring a baseline over somebody
    else's edits. So it refuses, and prints the exact text to put back."""
    if not INFLIGHT.exists():
        return ""
    try:
        crumb = json.loads(INFLIGHT.read_text())
    except (OSError, ValueError):
        return (f"{INFLIGHT.name} exists but could not be read. A previous run died "
                f"mid-cut and left no usable trace of what it was holding. Check "
                f"`git diff src/`, then delete the file.")
    still_there = ""
    try:
        if crumb["mutated"] in (SRC / crumb["module"]).read_text():
            still_there = "\n\n  THE MUTATION IS STILL IN THE FILE."
    except OSError:
        pass
    return (f"a previous run died while {crumb['module']} was cut open.\n"
            f"    mutant : {crumb['label']}\n"
            f"    cut    : {crumb['original'].strip()!r}\n"
            f"    to     : {crumb['mutated'].strip()!r}"
            f"{still_there}\n\n"
            f"  Put the original back (`git diff src/` will show it), then delete "
            f"{INFLIGHT.name} to re-enable this script.")


def _looks_stranded(text: str, original: str, mutated: str) -> bool:
    """Does `text` carry this mutation?

    Two shapes, and assuming one shape is how the first draft of this missed three of
    the forty-one. Most mutants REPLACE a line, so the original goes and the
    replacement arrives -- both halves needed, because two mutants replace a line with
    text that legitimately appears elsewhere in the same file, and testing only for
    the replacement would refuse to run on a healthy tree forever.

    Three mutants EXTEND the line instead (`for end, _ in trial` becomes
    `for end, _ in trial[:1]`). The original is a substring of its own replacement, so
    it survives the cut and "the original is gone" is never true. For those the
    arrival of the replacement is the whole signal.

    Which mutants fall in which class is measured, not assumed:
    `test_the_strand_detector_would_catch_every_mutant_in_the_table` simulates every
    entry and fails if any becomes invisible here."""
    if not mutated or mutated not in text:
        return False
    if original in mutated:
        return True
    return original not in text


def _no_stranded_mutant() -> tuple[bool, str]:
    """Is `src/` carrying a mutation this script left behind?

    NO SIGNAL HANDLER SURVIVES SIGKILL, and a process killed by a supervisor, an OOM,
    or a session ending gets no chance to restore anything. The handlers installed in
    `main` cover SIGTERM/SIGINT/SIGHUP; they cannot cover the case that actually
    happened twice in one day -- a run cut short by the harness, leaving a live mutant
    in `decision_engine.py`.

    So the real defence is at the START of the NEXT run, and it has now been wrong
    twice. The first version grepped for `if False:` -- ONE mutant shape out of
    forty-one -- and duly reported a clean tree over a mutated one. The second asked
    git whether `src/` was dirty, which is sound evidence and the wrong question: it
    cannot tell a stranded mutant from a morning's uncommitted work, so it refused to
    run during exactly the development it exists to protect. A safety check that must
    be bypassed to get work done is a safety check that gets bypassed.

    This version asks the precise question, and asks it of the MUTANT TABLE rather than
    of a hand-written pattern, so it cannot drift from the set of edits this script
    makes: for each mutant, has the original text gone while the mutated text is here?

    Both halves are load-bearing. `mutated in text` alone false-positives -- two
    mutants replace a line with text that legitimately appears elsewhere in the same
    file. `original not in text` alone fires on any honest refactor that moves a line.
    Together they are specific to the damage: each original is unique in its module
    (pinned by `test_the_strand_detector_would_catch_every_mutant_in_the_table`), so a
    successful mutation is exactly "the original is gone and its replacement is here".

    WHAT THIS DOES NOT CATCH, stated because the last two versions of this check were
    trusted further than they deserved: a mutant stranded by an OLDER version of this
    table, and any other tool's droppings. `_tree_is_healthy` is the independent second
    opinion -- a functional assertion rather than a textual one, which fails for
    different reasons -- and `main` warns separately when git says `src/` is dirty.
    """
    stranded = []
    for module, original, mutated, label in MUTANTS:
        if _looks_stranded((SRC / module).read_text(), original, mutated):
            stranded.append(f"{module}: {label}\n        "
                            f"{original.strip()!r} -> {mutated.strip()!r}")
    if stranded:
        return False, (
            "the working tree is already mutated -- almost certainly by an "
            "interrupted run of this script:\n    "
            + "\n    ".join(stranded)
            + "\n\n  Restore it before trusting any result here. If you have no other "
              "uncommitted work in src/, `git checkout -- src/`; if you do, read "
              "`git diff src/` and revert only the lines above.")
    return True, ""


def _uncommitted_src_warning() -> list[str]:
    """Advisory, and deliberately NOT a refusal.

    Uncommitted work in `src/` is the ordinary state of a repository somebody is
    working in, and the previous version of this script treated it as fatal -- which
    made the probe unrunnable for most of a working day and told nobody anything they
    did not know. It is still worth SAYING: if a run was killed before the current
    mutant table existed, the table-driven check above cannot see it, and this is the
    only trace left.
    """
    result = subprocess.run(["git", "status", "--porcelain", "--", str(SRC)],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    dirty = [line for line in result.stdout.splitlines() if line.strip()]
    return ["NOTE: src/ has uncommitted changes. None of them is a mutant this script",
            "      knows how to make -- but a run killed before the current mutant",
            "      table existed would look exactly like this:",
            *(f"        {line}" for line in dirty[:10]),
            ""]


def _tree_is_healthy() -> tuple[bool, str]:
    """Is the engine working BEFORE we start cutting?

    This probe mutates source files in place. A `try/finally` restores them on an
    exception or Ctrl-C -- and not on SIGKILL, which is what a harness timeout
    sends. Worse, each mutant used to read its baseline fresh from disk, so one
    killed run poisoned every later one: mutant B would read A's stranded mutation
    as "the original" and faithfully restore it afterwards.

    That happened. `if failures:` sat in `_decide` as `if False:` through several
    commits' worth of work, and the full suite still passed -- the only thing that
    noticed was the planning benchmark falling from 11/11 to 4/11, which looked
    like a regression in an unrelated refactor and cost an hour to trace.

    So: check the patient is alive before operating, with an assertion no mutant in
    this file would leave standing.
    """
    from datetime import datetime, timezone

    # SRC FIRST, and before anything has imported `wallet_control`. The package is
    # installed editable, so a plain import resolves to whatever checkout `pip`
    # was pointed at -- which is not necessarily the tree this script is about to
    # mutate. A health check that inspects a different copy of the engine than the
    # one it cuts is worse than none: it reports healthy and proceeds.
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    for name in [m for m in sys.modules if m.startswith("wallet_control")]:
        del sys.modules[name]
    from tests.helpers import make_event, make_mandate
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.mandate import HardRule
    from wallet_control.state import HistoryIndex, RunState

    mandate = make_mandate(instruction="health check", hard_rules=[HardRule(
        field="authorization.billing_amount_chf", operator="<=", value=5,
        currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, authorization_id="AU_HEALTH", amount=45.0,
                       merchant_id="ME_KNOWN",
                       timestamp=datetime(2026, 8, 12, tzinfo=timezone.utc))
    event["authorization"]["items"][0].update(item_name="x", item_category="groceries")
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_KNOWN"})},
                                          available=True), card_id="CA_TEST")
    decision = evaluate_authorization(event, mandate, state).decision
    if decision != "block":
        return False, (f"CHF 45 against a CHF 5 ceiling was {decision.upper()}, not BLOCK. "
                       f"The working tree is already mutated -- almost certainly by an "
                       f"interrupted run of this script. Restore it (git diff src/) "
                       f"before trusting any result here.")
    return True, ""


def main() -> int:
    # `--check-only` runs the health check and stops. It exists because
    # `_tree_is_healthy` clears `wallet_control` out of `sys.modules` so it can
    # import the tree being cut rather than the editable install -- which is right
    # for a script and catastrophic in-process: calling it from a test unloads the
    # package for every test that follows. So the suite exercises it the way a user
    # does, in a subprocess.
    check_only = "--check-only" in sys.argv
    refusal = _inflight_refusal()
    if refusal:
        print("REFUSING TO RUN: " + refusal)
        return 2
    clean, why = _no_stranded_mutant()
    if not clean:
        print("REFUSING TO RUN: " + why)
        return 2
    healthy, why = _tree_is_healthy()
    if not healthy:
        print("REFUSING TO RUN: " + why)
        return 2
    for line in _uncommitted_src_warning():
        print(line)
    if check_only:
        print("health check passed: the engine blocks an over-limit purchase")
        return 0

    # Read every target ONCE. A mutant must never take its baseline from a file a
    # previous mutant may have left modified.
    originals: dict[str, str] = {}
    for module, _original, _mutated, _label in MUTANTS:
        originals.setdefault(module, (SRC / module).read_text())

    # RESTORE ON A SIGNAL, NOT ONLY ON AN EXCEPTION.
    #
    # The `try/finally` below survives an exception and Ctrl-C. It does NOT survive
    # SIGTERM, which is what `pkill`, a harness timeout and most supervisors send --
    # and this run is long enough that being killed part-way is the ordinary case,
    # not the exotic one. Measured the hard way: a probe stopped with `pkill` left
    # `decision_engine.py` carrying a live mutant (the session-velocity cross-check
    # replaced by the event's own claim), and the check that was supposed to catch
    # that grepped for `if False:` -- one mutant SHAPE out of the dozen here -- so it
    # reported a clean tree over a mutated one.
    #
    # A probe that can leave the tree silently wrong is worse than no probe: every
    # measurement taken afterwards is against a source nobody inspected.
    def _restore_and_exit(signum, _frame):
        for module_name, text in originals.items():
            try:
                (SRC / module_name).write_text(text)
            except OSError:
                pass
        try:
            INFLIGHT.unlink(missing_ok=True)
        except OSError:
            pass
        print(f"\n[signal {signum}] restored {len(originals)} file(s) before exiting. "
              f"This run is INCOMPLETE -- re-run it on a quiet tree.", flush=True)
        # `os._exit`, not `sys.exit`: raising SystemExit from a handler unwinds into
        # the mutant loop, whose race guard then sees the files this handler just
        # rewrote and reports them as edited by someone else -- and the summary at
        # the bottom still prints. Leave immediately; the files are already restored.
        os._exit(130)

    for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(_sig, _restore_and_exit)

    print(f"{'mutant':56s} {'result':10s} killed by")
    print("-" * 118)
    survived: list[str] = []
    skipped: list[str] = []
    edited: list[str] = []
    applied = 0        # mutants actually applied and judged -- see the summary

    try:
        for module, original, mutated, label in MUTANTS:
            path = SRC / module
            source = originals[module]
            if original not in source:
                skipped.append(label)
                print(f"{label:56s} {'SKIP':10s} pattern no longer present in {module}")
                continue
            mutated_text = source.replace(original, mutated, 1)
            # BEFORE the cut, not after: the window this closes is the one between
            # writing the mutant and restoring it, and a breadcrumb written after the
            # edit would be missing for exactly the kill it is meant to survive.
            INFLIGHT.write_text(json.dumps(
                {"module": module, "label": label,
                 "original": original, "mutated": mutated}, indent=2))
            path.write_text(mutated_text)
            try:
                passed, output = _run_suite()
            finally:
                # If the file is not what we wrote, SOMEONE ELSE EDITED IT while the
                # suite ran, and restoring the baseline would silently destroy their
                # work. That happened: a long probe was backgrounded, edits were made
                # to the engine during it, and each restore quietly reverted them --
                # the crash-safety fix made this tool safe against dying and not
                # against being raced.
                if path.read_text() != mutated_text:
                    edited.append(module)
                    print(f"{'':56s} {'STOP':10s} {module} changed during the run; "
                          f"leaving it alone")
                    break
                path.write_text(source)
                INFLIGHT.unlink(missing_ok=True)
            if passed:
                survived.append(label)
                print(f"{label:56s} {'SURVIVED':10s} *** no test caught this ***")
            else:
                failures = [line for line in output.splitlines() if line.startswith("FAILED")]
                name = failures[0].split("::")[-1].split(" ")[0] if failures else "(unnamed)"
                print(f"{label:56s} {'killed':10s} {name[:56]}")
            applied += 1
    finally:
        # Belt and braces: restore every target from the originals captured at the
        # top, then VERIFY. A restore that silently failed is how the last one got
        # through, so it is checked rather than assumed.
        stranded = []
        for module, text in originals.items():
            if module in edited:
                continue      # someone else owns this file now; do not touch it
            path = SRC / module
            try:
                path.write_text(text)
                if path.read_text() != text:
                    stranded.append(module)
            except OSError:
                stranded.append(module)
        if stranded:
            print("\n*** COULD NOT RESTORE " + ", ".join(stranded) + " ***")
            print("*** The working tree is MUTATED. Run: git checkout -- src/ ***")
        if not stranded and not edited:
            # Only now. A file somebody else edited was deliberately NOT restored, so
            # the breadcrumb stays and the next run refuses -- which is the point.
            INFLIGHT.unlink(missing_ok=True)

    if edited:
        print(f"\n*** STOPPED EARLY: {', '.join(sorted(set(edited)))} was edited while "
              f"this ran. Its baseline is stale, so nothing was restored for it and "
              f"the results below are incomplete. Re-run on a quiet tree. ***")
    # WHAT ACTUALLY RAN, not how many mutants are listed.
    #
    # This printed `len(MUTANTS) - len(skipped)` regardless of how far the loop got,
    # so a probe stopped part-way -- by a signal, a harness timeout, or the race
    # guard below -- still ended with "41 mutants applied, 41 killed, 0 survived".
    # Anyone reading the tail of the log saw a full pass over a run that had examined
    # two. A gate that reports success when it was interrupted is worse than no gate.
    total = applied
    complete = (applied + len(skipped)) == len(MUTANTS) and not edited
    print(f"\n{total} mutants applied, {total - len(survived)} killed, {len(survived)} survived."
          + ("" if complete else
             f"  *** INCOMPLETE: {len(MUTANTS)} are defined and this run examined "
             f"{applied + len(skipped)}. Nothing here is a pass. ***"))
    if skipped:
        print(f"{len(skipped)} skipped -- the code moved and the mutant needs rewriting:")
        for label in skipped:
            print(f"  - {label}")
    if survived:
        print("\nEach survivor is an unprotected mechanism. Write the test that kills it:")
        for label in survived:
            print(f"  - {label}")
    # A skipped mutant is a silently weakened probe, and an incomplete run is not a
    # pass, so both fail.
    return 1 if (survived or skipped or not complete) else 0


if __name__ == "__main__":
    raise SystemExit(main())

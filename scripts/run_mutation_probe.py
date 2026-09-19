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

RESULT AT THE TIME OF WRITING: 29 mutants, 29 killed, 0 survived.

One survivor was found when this probe was first run: widening the rolling window's
start from `end - window < ts` to `end - window <= ts` passed the entire suite.
Not a safety hole -- a wider window only ever blocks more -- but it meant nothing
pinned WHICH window the engine means, so the half-open boundary is now a test
(`test_the_rolling_window_is_half_open_exactly_N_days_ago_is_outside_it`). That is
what this probe is for.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "wallet_control"

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

    # --- customer-facing explanation: I39 ------------------------------------
    ("decision_engine.py", "    reasons = list(dict.fromkeys(_plain_reason(e) for e in problems))",
     '    reasons = [f"{e.rule.field} ({e.outcome}): {e.detail}" for e in problems]',
     "the engine's debug dump is sent to the customer again"),

    # --- intent fidelity: I37, I38 -------------------------------------------
    ("policy_compiler.py", "        if v not in period_amount_values", "        if True",
     "a period-qualified amount becomes a per-order ceiling again"),
    ("policy_compiler.py", "    open_questions.extend(_coverage_questions(text, rules))", "    pass",
     "restrictive language with no rule is dropped in silence again"),

    ("policy_compiler.py", '    text = re.sub(r"\\s+", " ", instruction).strip()',
     "    text = instruction.strip()",
     "whitespace is significant again, losing the ceiling on a double space"),
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
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-x", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    return result.returncode == 0, result.stdout


def main() -> int:
    print(f"{'mutant':56s} {'result':10s} killed by")
    print("-" * 118)
    survived: list[str] = []
    skipped: list[str] = []

    for module, original, mutated, label in MUTANTS:
        path = SRC / module
        source = path.read_text()
        if original not in source:
            skipped.append(label)
            print(f"{label:56s} {'SKIP':10s} pattern no longer present in {module}")
            continue
        path.write_text(source.replace(original, mutated, 1))
        try:
            passed, output = _run_suite()
        finally:
            path.write_text(source)  # always restore, even on Ctrl-C or a crash
        if passed:
            survived.append(label)
            print(f"{label:56s} {'SURVIVED':10s} *** no test caught this ***")
        else:
            failures = [line for line in output.splitlines() if line.startswith("FAILED")]
            name = failures[0].split("::")[-1].split(" ")[0] if failures else "(unnamed)"
            print(f"{label:56s} {'killed':10s} {name[:56]}")

    total = len(MUTANTS) - len(skipped)
    print(f"\n{total} mutants applied, {total - len(survived)} killed, {len(survived)} survived.")
    if skipped:
        print(f"{len(skipped)} skipped -- the code moved and the mutant needs rewriting:")
        for label in skipped:
            print(f"  - {label}")
    if survived:
        print("\nEach survivor is an unprotected mechanism. Write the test that kills it:")
        for label in survived:
            print(f"  - {label}")
    # A skipped mutant is a silently weakened probe, so it fails too.
    return 1 if (survived or skipped) else 0


if __name__ == "__main__":
    raise SystemExit(main())

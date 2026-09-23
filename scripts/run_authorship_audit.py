"""Static authorship audit: does any party author a fact that is not theirs?

Six vulnerabilities in this project were one bug. A fact was accepted from a party
that is not its author -- the agent authoring the customer's policy, the caller
stamping the wallet's clock, the platform's echo becoming the customer's rules.
Each was found separately and fixed separately, and none of those fixes prevented
the next one, because the pattern had no name.

This audit names it and checks it. Three rules:

    RULE 1  every caller-controlled field must declare an author
            -- so a new one cannot be added silently, which is how four of the six
               arrived

    RULE 2  no agent-authored field may be policy-bearing
            -- the party being judged may say what it WANTS, never what the rules
               are, when it happened, or what it may spend against

    RULE 3  no security check may be disabled by an omitted argument
            -- two of the six were optional parameters whose default quietly
               skipped a check, safe only because one caller remembered

Exit code is non-zero on any violation, so this belongs in the gate rather than in
a document nobody re-runs.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pydantic import BaseModel                                  # noqa: E402

import wallet_control.api as api                                # noqa: E402

# Optional parameters that genuinely may be omitted, each with the reason it is not
# a disabled safeguard. Anything security-relevant and NOT here is a finding.
DECLARED_OPTIONAL = {
    ("state.py", "issue_authority", "now"): "clock injection for tests; real clock otherwise",
    ("state.py", "revoke_outstanding_authorities", "now"): "clock injection; real clock otherwise",
    ("payment.py", "charge_via_authority", "now"): "clock injection; real clock otherwise",
    ("audit.py", "audit_timeline", "confirmed_at"): "display only; the server stamps it",
    ("api.py", "_stored_decision_summary", "revoked"): "derived from run state by the caller above",
    ("api.py", "_recorded_message", "revoked"): "same",
    # PRESENTATION ONLY, AND IT FAILS TOWARDS SAYING LESS. Both carry the run's own
    # mandate so a rolling-window breach can be read back with the customer's own
    # figure in it ("over the CHF 300 you allowed across any 7-day period") instead
    # of the generic wording. Omitting it loses the figure and keeps the boundary --
    # it cannot turn a refusal into an approval, cannot change a verdict, and cannot
    # name a limit that is not in the mandate it was handed. The figure is
    # deliberately NOT encoded in the reason code, because codes are stored and are
    # what the agent-facing projection is derived from.
    ("api.py", "_stored_decision_summary", "mandate"): "presentation only; without it "
        "the read-back keeps the boundary and loses the figure",
    ("api.py", "_plain_reasons_from_codes", "mandate"): "same",
    ("attack_demo.py", "_mandate", "extra"): "demo fixture builder, not a decision path",
    ("live_worker.py", "resolve", "customer_message"): "text passed through to the platform",
    ("viseca_client.py", "create_mandate_draft", "guidance"): "optional API field",
    ("viseca_client.py", "create_mandate_draft", "open_questions"): "optional API field",
    ("viseca_client.py", "submit_decision", "reason_codes"): "optional API field",
    ("viseca_client.py", "submit_decision", "customer_message"): "optional API field",
    ("viseca_client.py", "submit_decision", "evidence"): "optional API field",
    ("viseca_client.py", "submit_decision", "engine_version"): "optional API field",
    ("viseca_client.py", "resolve", "customer_message"): "optional API field",
    ("viseca_client.py", "resolve", "evidence"): "optional API field",
    # Known and deliberately retained, each with a guard test:
    ("decision_engine.py", "resolve_authorization", "mandate"):
        "KNOWN HAZARD: omitting it skips the rolling-window re-check. Every runtime "
        "caller passes it, AST-enforced by test_resolution_checks_are_not_optional",
    ("live_worker.py", "__init__", "confirmed_rules"):
        "now fails closed: omitting it raises unless trust_echoed_policy is stated",
    ("live_worker.py", "__init__", "confirmed_uncertainty_policy"):
        "paired with confirmed_rules, which fails closed",
    ("live_worker.py", "__init__", "trust_echoed_policy"):
        "the explicit opt-out itself; naming it IS the safeguard",
    ("live_worker.py", "__init__", "checkpoint_dir"): "durability, not authority",
}

SECURITY_WORDS = ("revok", "consume", "authorit", "spend", "window", "period",
                  "mandate", "policy", "verdict", "decision", "resolve", "issue",
                  "confirm", "tighten", "familiar", "budget", "trust")


def rule_1_every_field_declares_an_author() -> list[str]:
    problems = []
    for name, obj in vars(api).items():
        if not (isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel):
            continue
        for field in obj.model_fields:
            if (name, field) not in api.FIELD_AUTHORS:
                problems.append(
                    f"{name}.{field} is caller-controlled and declares no author. "
                    f"Add it to FIELD_AUTHORS in api.py, naming who may write it.")
    for (model, field) in api.FIELD_AUTHORS:
        obj = getattr(api, model, None)
        if obj is None or field not in obj.model_fields:
            problems.append(f"FIELD_AUTHORS names {model}.{field}, which no longer exists")
    return problems


def rule_2_no_agent_field_is_policy_bearing() -> list[str]:
    problems = []
    for (model, field), author in api.FIELD_AUTHORS.items():
        if author != "agent":
            continue
        for policy_word in api.POLICY_BEARING:
            if policy_word in field:
                problems.append(
                    f"{model}.{field} is authored by the AGENT and is policy-bearing "
                    f"(matches {policy_word!r}). The party being judged would be "
                    "writing what it is judged by.")
    return problems


def rule_3_no_check_is_disabled_by_omission() -> list[str]:
    problems = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            args = fn.args
            pairs = {}
            if args.defaults:
                for arg, default in zip(args.args[-len(args.defaults):], args.defaults):
                    pairs[arg.arg] = default
            for arg, default in zip(args.kwonlyargs, args.kw_defaults):
                if default is not None:
                    pairs[arg.arg] = default
            for param, default in pairs.items():
                disabling = isinstance(default, ast.Constant) and default.value in (None, False)
                relevant = any(w in fn.name.lower() or w in param.lower()
                               for w in SECURITY_WORDS)
                if disabling and relevant and (path.name, fn.name, param) not in DECLARED_OPTIONAL:
                    problems.append(
                        f"{path.name}:{fn.lineno} {fn.name}({param}=...) is "
                        "security-relevant and defaults to a value that may disable a "
                        "check. Declare it in DECLARED_OPTIONAL with the reason it is "
                        "safe, or make it fail closed.")
    return problems


def main() -> int:
    print("AUTHORSHIP AUDIT -- who may write which fact\n")
    checks = [
        ("every caller-controlled field declares an author", rule_1_every_field_declares_an_author),
        ("no agent-authored field is policy-bearing", rule_2_no_agent_field_is_policy_bearing),
        ("no security check is disabled by omission", rule_3_no_check_is_disabled_by_omission),
    ]
    total = 0
    for label, check in checks:
        problems = check()
        total += len(problems)
        print(f"  [{'FAIL' if problems else ' ok '}] {label}")
        for problem in problems:
            print(f"         - {problem}")

    print(f"\n  declared fields: {len(api.FIELD_AUTHORS)}   "
          f"by author: " + ", ".join(
              f"{a}={sum(1 for v in api.FIELD_AUTHORS.values() if v == a)}"
              for a in sorted(set(api.FIELD_AUTHORS.values()))))
    print(f"  declared optional parameters: {len(DECLARED_OPTIONAL)}")
    print(f"\n  {total} violation(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())

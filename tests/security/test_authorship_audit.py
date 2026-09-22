"""The authorship audit, validated by replaying every defect it claims to catch.

Six vulnerabilities in this project were one bug: **a fact was accepted from a
party that is not its author.** The agent authoring the customer's policy, the
caller stamping the wallet's clock, the platform's echo becoming the customer's
rules. Each was found in a separate campaign, weeks apart, and each was fixed
separately -- and none of those fixes prevented the next one, because the pattern
had no name.

A checker that only passes on today's code proves nothing. These tests reintroduce
each historical defect and assert the audit rejects it, which is the only evidence
that the rule is real rather than a shape fitted to the current source.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "scripts" / "run_authorship_audit.py"
API = ROOT / "src" / "wallet_control" / "api.py"
SCANNER_SOURCE = AUDIT.read_text()


def _audit_fails() -> bool:
    result = subprocess.run([sys.executable, str(AUDIT)],
                            capture_output=True, text=True, cwd=ROOT)
    return result.returncode != 0


def test_the_audit_passes_on_the_current_code():
    assert not _audit_fails(), subprocess.run(
        [sys.executable, str(AUDIT)], capture_output=True, text=True, cwd=ROOT).stdout


# ============================================ each historical defect, reintroduced
DEFECTS = [
    ("the agent authors the customer's policy",
     "    session_id: str\n    lines: list[dict[str, Any]]",
     "    session_id: str\n    instruction: str | None = None\n    lines: list[dict[str, Any]]"),
    ("the caller stamps a customer-attributed time",
     "class RunRequest(BaseModel):",
     "class RunRequest(BaseModel):\n    confirmed_at: str | None = None"),
    ("the caller writes the wallet's words",
     '    decision: str  # "allow" | "block"',
     '    decision: str  # "allow" | "block"\n    customer_message: str | None = None'),
    ("an agent-authored field becomes policy-bearing",
     '    ("AgentProposal", "lines"): "agent",',
     '    ("AgentProposal", "lines"): "agent",\n    ("AgentProposal", "policy_hint"): "agent",'),
]


@pytest.mark.parametrize("label,before,after", DEFECTS, ids=lambda v: v[:34] if isinstance(v, str) else v)
def test_the_audit_rejects_each_historical_defect(label, before, after):
    """Reintroduce the defect, run the audit, restore. It must fail while present."""
    original = API.read_text()
    assert before in original, f"anchor for {label!r} has moved; re-derive this test"
    try:
        API.write_text(original.replace(before, after, 1))
        assert _audit_fails(), (
            f"the audit ACCEPTED a reintroduced defect: {label}. The rule is not "
            "catching the pattern it was written for.")
    finally:
        API.write_text(original)
    assert API.read_text() == original


@pytest.mark.parametrize("declaration", [
    '("decision_engine.py", "resolve_authorization", "mandate")',
    '("live_worker.py", "__init__", "confirmed_rules")',
], ids=["resolve_authorization.mandate", "LiveWorker.confirmed_rules"])
def test_the_audit_rejects_an_undeclared_optional_safeguard(declaration):
    """The other half of the pattern: a check disabled by an omitted argument.

    Both of these are real, both were found the hard way, and both are retained
    with an explicit reason. Removing the declaration must make the audit fail --
    otherwise the reason is decoration.
    """
    original = SCANNER_SOURCE
    start = original.index(declaration)
    end = original.index('",\n', start) + 3
    try:
        AUDIT.write_text(original[:start] + original[end:])
        assert _audit_fails(), (
            f"removing the declaration for {declaration} did not fail the audit")
    finally:
        AUDIT.write_text(original)
    assert AUDIT.read_text() == original


def test_the_registry_covers_every_request_model():
    """The rule that makes a seventh instance impossible to add silently."""
    from pydantic import BaseModel

    import wallet_control.api as api

    models = [obj for obj in vars(api).values()
              if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel]
    assert models, "no request models found; the audit is checking nothing"
    for model in models:
        for field in model.model_fields:
            assert (model.__name__, field) in api.FIELD_AUTHORS, (
                f"{model.__name__}.{field} has no declared author")


def test_no_agent_authored_field_carries_policy():
    """The party being judged may say what it WANTS. Never what it is judged by."""
    import wallet_control.api as api

    agent_fields = [f for (m, f), a in api.FIELD_AUTHORS.items() if a == "agent"]
    assert agent_fields, "no agent-authored fields; the check is vacuous"
    for field in agent_fields:
        for policy_word in api.POLICY_BEARING:
            assert policy_word not in field, (
                f"agent-authored {field!r} matches policy-bearing {policy_word!r}")

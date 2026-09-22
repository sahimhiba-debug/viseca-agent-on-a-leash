"""`resolve_authorization(..., mandate=None)` silently disables a security check.

Every production caller passes the mandate today. The parameter is optional for
backward compatibility, and when it is omitted `_period_rules_breached_now` is
never consulted — so a late human approval is recorded without re-checking the
rolling window it might now breach.

This file exists because the omission fooled the person writing the audit. A
pre-jury attack reproduced "CHF 400 approved against a stated CHF 300/7-day cap"
and it looked like a live enforcement defect for several minutes. It was not: the
test had called the engine without the mandate, which production never does. Run
the identical attack the way `api.py` calls it and the second approval is blocked.

That is a near-miss worth a permanent guard rather than a shrug. A security check
whose absence is silent, behind a parameter that defaults to off, is the same shape
as the three caller-controlled fields this audit removed — safe today, one careless
call away from not being.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex, RunState

ROOT = Path(__file__).resolve().parents[2]
AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


def test_every_runtime_caller_passes_the_mandate():
    """AST-enforced, because "all the callers are fine" is a fact about today."""
    offenders = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "resolve_authorization"):
                continue
            if "mandate" not in {kw.arg for kw in node.keywords}:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, (
        "these callers resolve a step-up without the mandate, so the rolling-window "
        f"re-check cannot fire for them: {offenders}")


def _two_pending_stepups():
    mandate = make_mandate(
        "groceries, each order at or below CHF 200, 7-day total at or below CHF 300, "
        "only if returnable",
        [HardRule("authorization.billing_amount_chf", "<=", 200.0, currency="CHF", scope="purchase"),
         HardRule("authorization.billing_amount_chf", "<=", 300.0, currency="CHF",
                  scope="period", period_days=7),
         HardRule("order.return_window_days", ">=", 14),
         HardRule("item.category", "in", ["groceries"])])
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})}),
                     card_id="CA_TEST")
    for i in (1, 2):
        event = make_event(mandate=mandate, authorization_id=f"AU_P{i}", amount=200.0,
                           billing_amount_chf=200.0, items_subtotal=200.0,
                           timestamp=AT + timedelta(minutes=i), order_returnable="unknown")
        assert evaluate_authorization(event, mandate, state).decision == "review"
    assert state.rolling_spend_chf(AT + timedelta(days=1), 7) == 0, (
        "a pending step-up must not reserve budget it may never use")
    return mandate, state


def test_approving_two_pending_stepups_cannot_exceed_the_period_cap():
    """The attack the optional parameter hides. A compromised agent chooses what
    gets queued, so it can push several individually-reasonable purchases into the
    queue and have them approved one at a time, together far over the cap."""
    mandate, state = _two_pending_stepups()
    outcomes = [resolve_authorization(f"AU_P{i}", "allow", state,
                                      resolved_at=AT + timedelta(hours=i), mandate=mandate).decision
                for i in (1, 2)]
    assert outcomes == ["allow", "block"], outcomes
    assert state.rolling_spend_chf(AT + timedelta(days=1), 7) == 200, (
        "the rolling window was breached by sequential step-up approvals")


def test_the_second_approval_tells_the_customer_why_in_plain_words():
    mandate, state = _two_pending_stepups()
    resolve_authorization("AU_P1", "allow", state, resolved_at=AT + timedelta(hours=1),
                          mandate=mandate)
    second = resolve_authorization("AU_P2", "allow", state, resolved_at=AT + timedelta(hours=2),
                                   mandate=mandate)
    assert second.decision == "block"
    assert "exceed the spending limit you set" in second.customer_message
    for internal in ("period_limit_exceeded", "billing_amount_chf", "_"):
        assert internal not in second.customer_message, second.customer_message


def test_without_the_mandate_the_check_does_not_fire_and_we_say_so():
    """Pinning the hazard itself, so the reason the AST test exists stays visible.

    This is NOT a supported way to call the function. It is the documented failure
    mode, asserted so that anyone who makes `mandate` required will see this test go
    red and know it was deliberate rather than accidental.
    """
    mandate, state = _two_pending_stepups()
    outcomes = [resolve_authorization(f"AU_P{i}", "allow", state,
                                      resolved_at=AT + timedelta(hours=i)).decision
                for i in (1, 2)]
    assert outcomes == ["allow", "allow"]
    assert state.rolling_spend_chf(AT + timedelta(days=1), 7) == 400, (
        "if this is no longer 400, the mandate-less path now enforces the window too; "
        "delete this test and make `mandate` required")


# ============================== the same shape, found again in the live worker
def test_the_live_worker_refuses_to_run_without_the_confirmed_policy():
    """Sixth instance of one defect: a check whose absence is silent.

    `_verify_echoed_policy` compares the platform's echo of the mandate against what
    the customer actually confirmed, and it used to `return` quietly when the worker
    had not been given the confirmed rules. The stakes are on the record in its own
    docstring: an audit widened the echo and turned a CHF 9,000 purchase at an
    unknown seller from BLOCK into ALLOW for a whole run.

    Safety rested on one caller remembering. Forgetting is now loud -- and a caller
    that genuinely means to adopt whatever policy it is sent has to say so.
    """
    from wallet_control.live_worker import LiveWorker
    from wallet_control.state import HistoryIndex

    with pytest.raises(ValueError, match="confirmed"):
        LiveWorker(client=None, history=HistoryIndex.empty())

    # ...and the explicit opt-out still works, because offline and test callers exist
    LiveWorker(client=None, history=HistoryIndex.empty(), trust_echoed_policy=True)


def test_the_production_worker_passes_the_confirmed_policy():
    """AST-enforced on the script that actually runs against the platform."""
    script = (ROOT / "scripts" / "run_live_worker.py").read_text()
    tree = ast.parse(script)
    constructions = [n for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "LiveWorker"]
    assert constructions, "run_live_worker.py no longer constructs a LiveWorker"
    for call in constructions:
        keywords = {k.arg for k in call.keywords}
        assert "confirmed_rules" in keywords, (
            f"line {call.lineno}: the live worker would adopt the platform's echo")
        assert "trust_echoed_policy" not in keywords, (
            f"line {call.lineno}: production must not opt out of echo verification")

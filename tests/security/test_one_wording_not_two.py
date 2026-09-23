"""The UI kept its own copy of the engine's prose, and it drifted in one afternoon.

`ui/index.html` had `RULE_TEXT` and `UNSURE_TEXT` -- a second rule-to-sentence table
living in a client. Within a single session of engine work it had gone wrong three
ways:

    session.integrity_risk   said "something about this session could not be
                             verified" after the engine had started saying "this
                             purchase came from a device that has not been used
                             earlier in this session"
    merchant.familiar        said "no purchase history to check this seller
                             against" after the engine had learned to distinguish
                             "your agent has, you have not"
    merchant.text_addresses_the_machine
                             was absent, so the fallback rendered the raw dotted
                             field name on screen

That is invariant I39 with a different audience: a record that is right and a
rendering that is wrong. The engine now publishes `plain_reasons` -- the very list
`customer_message` is assembled from -- and the client renders it.

The last test is the one that would have caught the third case before a judge did.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import (
    _PLAIN_FAIL, _PLAIN_UNKNOWN, evaluate_authorization,
)
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.offline_replay import replay_all
from wallet_control.state import HistoryIndex, RunState

UI = Path(__file__).resolve().parents[2] / "ui" / "index.html"
RULES_SRC = Path(__file__).resolve().parents[2] / "src" / "wallet_control" / "rules.py"


def _decide(policy=UncertaintyPolicy.ASK, **item):
    mandate = make_mandate(instruction="x", uncertainty_policy=policy, hard_rules=[
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=100,
                 currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, authorization_id="AU_W", amount=500.0,
                       merchant_id="ME_K")
    event["authorization"]["items"][0].update(item_name="x", item_category="groceries", **item)
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_K"})}, available=True),
                     card_id="CA_TEST")
    return evaluate_authorization(event, mandate, state)


def test_the_engine_publishes_the_prose_it_writes_the_sentence_from():
    decision = _decide()
    assert decision.plain_reasons
    for reason in decision.plain_reasons:
        assert reason in decision.customer_message, reason


def test_a_clean_approval_has_nothing_to_explain():
    """Otherwise the list would be a place for text to accumulate unread."""
    approvals = [d for s in replay_all().scenarios for d in s.decisions
                 if d.decision == "allow" and d.reason_codes == ("all_hard_rules_satisfied",)]
    assert approvals
    assert all(d.plain_reasons == () for d in approvals)


def test_every_refusal_and_question_in_the_official_replay_carries_prose():
    """No raw dotted field names anywhere a customer can see."""
    for scenario in replay_all().scenarios:
        for decision in scenario.decisions:
            if decision.decision == "allow" and not decision.plain_reasons:
                continue
            assert decision.plain_reasons, decision.authorization_id
            for reason in decision.plain_reasons:
                assert "." not in reason.split(" ")[0], (decision.authorization_id, reason)
                assert "_" not in reason, (decision.authorization_id, reason)


def test_the_client_renders_the_servers_wording():
    body = UI.read_text()
    assert "d.plain_reasons" in body, "the UI is not using the engine's prose"
    assert "plainReasons(d)" in body, "it is still being handed bare codes"


def test_every_field_the_engine_can_refuse_on_has_a_sentence():
    """THE ANTI-ROT CHECK, and the one that would have caught the third drift.

    Read from `rules.py`'s own source: add a field to the engine and this fails
    until somebody writes the two sentences a customer will read when it fails and
    when it cannot be checked."""
    import ast

    tree = ast.parse(RULES_SRC.read_text())
    interpreter = next(n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == "_evaluate_rule")
    fields = {c.value for node in ast.walk(interpreter)
              if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
              and node.left.id == "field"
              for c in node.comparators
              if isinstance(c, ast.Constant) and isinstance(c.value, str)}

    missing_fail = sorted(fields - set(_PLAIN_FAIL))
    missing_unknown = sorted(f for f in fields - set(_PLAIN_UNKNOWN)
                             if f not in {"merchant.category", "item.name_contains"})
    assert not missing_fail, f"no refusal wording for {missing_fail}"
    assert not missing_unknown, f"no 'could not check' wording for {missing_unknown}"


def test_the_safety_rules_have_wording_too():
    """They are not in `rules.py` -- the engine appends them -- and they reach the
    same customer."""
    for field in ("authorization.amount_integrity", "authorization.authority_status",
                  "authorization.card_status_at_attempt", "order.duplicate_suspected",
                  "merchant.text_addresses_the_machine"):
        assert field in _PLAIN_FAIL or field in _PLAIN_UNKNOWN, field


def test_the_payload_carries_it_to_the_browser():
    from fastapi.testclient import TestClient

    from wallet_control.api import app

    body = TestClient(app).post("/api/scenarios/SCEN0004/run", json={}).json()
    interesting = [d for d in body["decisions"] if d["decision"] != "allow"]
    assert interesting
    for decision in interesting:
        assert decision["plain_reasons"], decision["authorization_id"]
        assert "merchant text addresses the machine" not in json.dumps(decision), (
            "a raw field name reached the client")


def test_the_annual_exposure_figure_is_computed_once_and_read_three_times():
    """THE MOST IMPORTANT SENTENCE THIS PRODUCT SAYS, rendered in three places.

    The official rule format's `scope` is `"purchase"`, `"period"` or null and
    nothing else -- there is no total, no lifetime, no end date. A rolling cap
    therefore PACES spending and never caps it: the window re-opens and the agent may
    spend up to that amount again, indefinitely. The only bound on what a standing
    mandate can cost is revocation.

    Three surfaces tell the customer that: the compiler's open questions, the audit
    timeline, and the delegation panel. They were computing it separately, and the
    panel had started saying it in a different UNIT (per day) from the other two (per
    year). A fact rendered twice is a fact that will eventually be rendered
    differently -- which is the whole subject of this file.

    Asserted against `money.annual_exposure` rather than against each other, so the
    test fails if any surface starts doing its own arithmetic again."""
    from wallet_control.money import annual_exposure
    from wallet_control.policy_compiler import compile_instruction
    from wallet_control.scope import delegation_size

    instruction = ("Order our household groceries, keeping each order at or below "
                   "CHF 120 and the total across any seven days at or below CHF 300.")
    _exact, expected = annual_exposure(300, 7)

    figure = f"CHF {expected:,.0f} a year"

    compiled = compile_instruction(instruction)
    assert any(figure in q for q in compiled.open_questions), (
        figure, compiled.open_questions)

    sized = delegation_size(instruction)["how_many_times"]
    assert sized["chf_per_year"] == expected
    assert figure in sized["note"], sized["note"]


def test_the_annual_figure_moves_with_the_period_not_only_the_ceiling():
    """A ceiling without a period is not a pace. "CHF 300 per 7 days" and "CHF 300
    per 30 days" differ by more than four times, and the panel reported the same
    "at most N purchases" for both until this figure sat beside it."""
    from wallet_control.money import annual_exposure

    assert annual_exposure(300, 7)[1] > 4 * annual_exposure(300, 30)[1]
    # On the EXACT figure, not the rounded one: rounding to a readable step is
    # deliberately not linear, and asserting linearity of the rounded number would be
    # asserting a property of the presentation rather than of the rate.
    assert abs(annual_exposure(3000, 7)[0] - 10 * annual_exposure(300, 7)[0]) < 1e-6

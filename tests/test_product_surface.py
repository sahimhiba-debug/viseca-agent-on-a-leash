"""The product surface: attack demonstrations, audit projection, delegation summary
and the API routes the UI depends on.

These are product tests, but two of them are load-bearing for honesty rather than
for function: the attack demonstrations must run against the REAL engine (not a
scripted narration), and the audit timeline must be a PROJECTION (not a second
ledger that could drift from the record it describes).
"""

from __future__ import annotations

from decimal import Decimal

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wallet_control.api import app
from wallet_control.attack_demo import ATTACKS, run_all_attacks
from wallet_control.audit import audit_timeline, delegation_summary
from wallet_control.csv_data import account_limits_for_card
from wallet_control.offline_replay import compile_and_confirm_mandate_for_scenario
from wallet_control.state import HistoryIndex, RunState


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# --- attack demonstrations --------------------------------------------------------


# Attack 9 is the one that SUCCEEDS. It is in the demo on purpose: a hard rule is
# checked against evidence the SELLER publishes, and the agent picks the seller, so
# choosing a shop that publishes nothing answers the rule without lying. Leaving it
# out would make the other eight a sales pitch. `uncertainty_policy = decline`
# closes it completely; nothing closes it for one rule and not the others.
_EXPECTED_TO_SUCCEED = {"shopping_for_ignorance"}


def test_only_the_disclosed_attack_succeeds():
    """If any OTHER attack ever flips to `allowed`, the demo must fail loudly rather
    than narrate a success that did not happen -- and if the disclosed one ever
    stops succeeding, the claim beside it has become false and must be rewritten."""
    results = run_all_attacks()
    assert len(results) == 9
    unexpected = [r.title for r in results if not r.held and r.key not in _EXPECTED_TO_SUCCEED]
    assert not unexpected, f"attack demonstrations no longer hold: {unexpected}"
    succeeded = {r.key for r in results if not r.held}
    assert succeeded == _EXPECTED_TO_SUCCEED, succeeded


def test_the_disclosed_attack_says_plainly_that_it_is_not_stopped():
    """The danger of shipping a successful attack is that the surrounding copy
    quietly softens it into a near-miss."""
    attack = next(r for r in run_all_attacks() if r.key == "shopping_for_ignorance")
    assert attack.outcome == "allowed" and attack.held is False
    assert "not stopped" in attack.expected.lower()
    assert "ALLOW" in attack.proof and "BLOCK" in attack.proof
    body = " ".join(attack.detail).lower()
    assert "decline" in body, "the setting that closes it must be named"


def test_attack_demonstrations_are_deterministic():
    """Same inputs, same outcome, every time -- no clock, no network, no randomness.
    A demo that is only usually right is not a demo."""
    first = [(r.key, r.outcome, r.deciding_fact) for r in run_all_attacks()]
    second = [(r.key, r.outcome, r.deciding_fact) for r in run_all_attacks()]
    assert first == second


def test_attack_demonstrations_use_the_real_engine():
    """The guard against a narrated demo: these must import the production decision
    and payment entry points, not reimplement them."""
    import inspect

    from wallet_control import attack_demo

    source = inspect.getsource(attack_demo)
    assert "from .decision_engine import evaluate_authorization" in source
    assert "from .payment import MockPSP" in source
    assert "def _decide" not in source, "the demo must not contain its own decision logic"


def test_the_attack_demo_cannot_move_the_official_replay():
    """It builds its own synthetic events and never reads the official 45."""
    import inspect

    from wallet_control import attack_demo

    source = inspect.getsource(attack_demo)
    for forbidden in ("scenario_rows", "load_purchase_attempts", "offline_replay"):
        assert forbidden not in source, f"attack demo touches official data via {forbidden}"


@pytest.mark.parametrize("attack", ATTACKS, ids=lambda a: a.__name__)
def test_each_attack_reports_a_mechanical_proof(attack):
    """Every demonstration must carry an artefact from the engine -- a reason code, a
    refused charge -- not just reassuring prose."""
    result = attack()
    assert result.proof.strip()
    assert result.deciding_fact.strip()
    assert result.outcome in {"blocked", "refused", "stepped_up", "allowed"}


# --- the audit trail is a projection ----------------------------------------------


def _run_scenario(scenario_id="SCEN0004"):
    from wallet_control.csv_data import load_merchants, load_purchase_attempt_items
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.offline_replay import build_event, history_csv_path, scenario_rows

    mandate = compile_and_confirm_mandate_for_scenario(scenario_id).snapshot()
    state = RunState(history=HistoryIndex.from_csv(history_csv_path()), card_id=mandate.card_id)
    merchants, items = load_merchants(), load_purchase_attempt_items()
    for row in scenario_rows(scenario_id):
        ctx = {"approved_spend_in_period_chf": float(state.total_approved_spend_chf()),
               "recent_authorizations": state.recent_authorizations_context()}
        evaluate_authorization(
            build_event(row, items[row["authorization_id"]], merchants[row["merchant_id"]], mandate, ctx),
            mandate, state)
    return mandate, state


def test_the_audit_timeline_is_recomputed_not_stored():
    """Two calls with no intervening change must be identical, and the timeline must
    hold no state of its own -- it is derived from the ledger on every call."""
    mandate, state = _run_scenario()
    first = [e.as_dict() for e in audit_timeline(mandate, state)]
    second = [e.as_dict() for e in audit_timeline(mandate, state)]
    assert first == second
    assert not hasattr(state, "_audit"), "the audit must not have acquired its own record"


def test_the_audit_timeline_covers_every_recorded_decision():
    """A timeline that silently omitted a decision would be worse than none."""
    mandate, state = _run_scenario()
    entries = audit_timeline(mandate, state)
    covered = {e.authorization_id for e in entries if e.authorization_id}
    assert covered == {d.authorization_id for d in state.all_decisions()}


def test_the_audit_timeline_labels_which_clock_each_entry_uses():
    """Simulated purchase time and real-clock authority time genuinely coexist.
    Rendering them in one column without labels would imply an ordering that does
    not exist."""
    mandate, state = _run_scenario()
    entries = audit_timeline(mandate, state)
    assert {e.clock for e in entries if e.event == "Purchase proposed"} == {"simulated"}
    issued = [e for e in entries if e.event == "Payment authority issued"]
    assert issued and {e.clock for e in issued} == {"real"}


def test_the_audit_timeline_never_invents_a_timestamp():
    """Where the record carries no time, the timeline must say so rather than fill one
    in from the wall clock.

    THIS TEST USED TO ASSERT THAT REVOCATIONS CARRY NO TIME AT ALL, and the principle
    was right while the premise had gone stale. The per-authority `revoked` flag is a
    boolean -- but revocation is a RUN-LEVEL event (that is the whole fix for F1),
    every authority in one sweep shares its moment, and `RunState` records that moment
    when it happens. Reporting a recorded instant is not inventing one.

    So the property is stated the way it was always meant: the timeline may only show
    a time the LEDGER recorded, never one taken when the page was rendered. Checked by
    revoking at an explicit instant far in the past and requiring the audit to say
    that instant rather than today."""
    from datetime import datetime, timedelta, timezone

    mandate, state = _run_scenario()
    when = datetime(2026, 8, 12, 9, 30, tzinfo=timezone.utc)
    state.revoke_outstanding_authorities(now=when)

    revocations = [e for e in audit_timeline(mandate, state)
                   if e.event == "Payment authority revoked"]
    assert revocations
    for entry in revocations:
        assert entry.timestamp is not None, (
            "the run recorded when it was revoked; the timeline must not drop it")
        assert entry.timestamp.startswith("2026-08-12T09:30"), (
            f"the timeline reported {entry.timestamp!r}, which is not the instant the "
            f"ledger recorded -- it has been stamped at render time")
        assert entry.clock == "real"

    # And a row with genuinely no instant still says so rather than borrowing one.
    waiting = [e for e in audit_timeline(mandate, state)
               if e.event == "Waiting for the customer"]
    assert all(e.timestamp is None for e in waiting), waiting


def test_the_audit_timeline_does_not_attribute_an_action_the_customer_never_took():
    """THE WORST DEFECT THIS FILE HAS HELD. A purchase still waiting for an answer
    produced

        customer | Customer resolved a step-up | the customer answered 'review'

    with no timestamp, for a question nobody had answered. An audit trail that
    attributes an action to the customer which the customer did not take is not a
    weak audit trail; it is a false one -- and this is the record of who authorised
    what.

    Waiting is a real state. It gets its own row, attributed to the WALLET, and the
    customer appears only once they have actually answered."""
    mandate, state = _run_scenario()

    pending = [d for d in state.all_decisions() if d.was_reviewed and d.resolved_at is None]
    assert pending, "this scenario must leave a step-up unanswered or the test is vacuous"

    timeline = audit_timeline(mandate, state)
    resolved_rows = [e for e in timeline if e.event == "Customer resolved a step-up"]
    unanswered_ids = {d.authorization_id for d in pending}
    assert not (unanswered_ids & {e.authorization_id for e in resolved_rows}), (
        "the timeline says the customer resolved a step-up they never answered")

    waiting = [e for e in timeline if e.event == "Waiting for the customer"]
    assert {e.authorization_id for e in waiting} == unanswered_ids
    assert all(e.actor == "wallet" for e in waiting), (
        "waiting is the wallet's state, not an action by the customer")


# --- economic disclosure ----------------------------------------------------------


def test_the_account_limit_is_shown_but_marked_unenforced():
    """The load-bearing honesty test. The account's monthly limit is real data and
    this wallet does not enforce it. Presenting it without that flag would turn
    context into an implied guarantee."""
    mandate, state = _run_scenario()
    summary = delegation_summary(mandate, state, account_limits_for_card(mandate.card_id))
    account = [l for l in summary["lines"] if "Account" in l["label"]]
    assert account, "the account limit should be disclosed"
    assert account[0]["enforced"] is False
    assert "does not enforce" in account[0]["note"]


def test_customer_stated_limits_are_marked_enforced():
    mandate, state = _run_scenario()
    summary = delegation_summary(mandate, state, None)
    per_purchase = [l for l in summary["lines"] if l["label"] == "Maximum per purchase"]
    assert per_purchase and per_purchase[0]["enforced"] is True


def test_the_unbounded_dimensions_are_named():
    """What the customer did NOT bound is as important as what they did."""
    mandate, state = _run_scenario()
    summary = delegation_summary(mandate, state, None)
    joined = " ".join(summary["unbounded_dimensions"])
    assert "total amount" in joined and "end date" in joined


# --- API routes the UI depends on -------------------------------------------------


def test_health_reports_the_regression_boundary(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    replay = body["official_replay"]
    assert (replay["events"], replay["allow"], replay["review"], replay["block"]) == (45, 17, 4, 24)
    assert replay["matches_regression_boundary"] is True


def test_attacks_endpoint_counts_the_disclosed_failure(client):
    """8 of 9. A surface that reported 9 of 9 would be contradicting the demo it
    serves."""
    body = client.get("/api/attacks").json()
    assert body["total"] == 9 and body["held"] == 8


def test_run_audit_endpoint_returns_timeline_and_delegation(client):
    run_id = client.post("/api/scenarios/SCEN0004/run").json()["run_id"]
    body = client.get(f"/api/runs/{run_id}/audit").json()
    assert body["timeline"] and body["delegation"]["lines"]
    assert any(l["enforced"] is False for l in body["delegation"]["lines"])


def test_demo_reset_clears_runs_without_touching_official_data(client):
    from wallet_control.offline_replay import replay_all

    client.post("/api/scenarios/SCEN0000/run")
    assert client.post("/api/demo/reset").json()["cleared_runs"] >= 1
    assert client.get("/api/health").json()["active_runs"] == 0
    assert replay_all().total_counts() == {"allow": 17, "review": 4, "block": 24}


# --- the ledger records WHY, not only what ----------------------------------------


def test_the_stored_decision_carries_its_reason_codes():
    """`StoredDecision.reason_codes` existed but was never populated. Everything that
    read the record back -- the audit timeline, and the UI re-rendering after a
    step-up was answered -- lost every explanation and could only show the bare
    decision. Found at the final gate by comparing a fresh evaluation against a
    refetch of the same run."""
    mandate, state = _run_scenario("SCEN0004")
    stored = state.all_decisions()
    assert stored
    assert all(d.reason_codes for d in stored), "a decision was recorded with no reason"


def test_a_refetched_run_explains_itself_exactly_like_a_fresh_one(client):
    run = client.post("/api/scenarios/SCEN0004/run").json()
    fresh = {d["authorization_id"]: d["reason_codes"] for d in run["decisions"]}
    refetched = {d["authorization_id"]: d["reason_codes"]
                 for d in client.get(f"/api/runs/{run['run_id']}").json()["decisions"]}
    assert fresh == refetched


def test_a_human_answer_does_not_erase_why_the_wallet_asked(client):
    """The reason a purchase was escalated is not erased by the answer to it -- an
    auditor needs both."""
    run = client.post("/api/scenarios/SCEN0004/run").json()
    run_id = run["run_id"]
    aid = next(d["authorization_id"] for d in run["decisions"] if d["decision"] == "review")
    client.post(f"/api/runs/{run_id}/authorizations/{aid}/resolve", json={"decision": "allow"})

    after = next(d for d in client.get(f"/api/runs/{run_id}").json()["decisions"]
                 if d["authorization_id"] == aid)
    assert after["decision"] == "allow"
    assert after["wallet_decision"] == "review"
    assert any("uncertain" in c for c in after["reason_codes"]), after["reason_codes"]
    assert "customer_resolution" in after["reason_codes"]


def test_the_audit_timeline_states_why_each_decision_was_made(client):
    run_id = client.post("/api/scenarios/SCEN0004/run").json()["run_id"]
    decisions = [e for e in client.get(f"/api/runs/{run_id}/audit").json()["timeline"]
                 if e["event"] == "Wallet decision"]
    assert decisions
    assert all(e["detail"] and e["detail"] != e["decision"] for e in decisions), (
        "the audit repeated the decision instead of explaining it")


def test_the_health_check_cannot_contradict_itself(client):
    """It used to hold the boundary twice -- a dict shown to the caller and the same
    four numbers again longhand in the comparison -- so moving the boundary updated
    one and not the other, and the endpoint answered `expected: 17/4/24,
    matches_regression_boundary: false`.

    An internally contradictory health check is worse than none. It is the surface a
    teammate reads thirty seconds before going on stage."""
    replay = client.get("/api/health").json()["official_replay"]
    actual = {k: replay[k] for k in ("events", "allow", "review", "block")}
    assert replay["matches_regression_boundary"] == (actual == replay["expected"]), (
        actual, replay["expected"])

    from wallet_control import api
    source = (Path(api.__file__)).read_text()
    body = source.split("def health()")[1].split("\n@app")[0]
    for number in ("45", "18", "3", "24"):
        assert f'== {number}' not in body, (
            "the boundary is written longhand inside health() again; it must come "
            "from REGRESSION_BOUNDARY so the two cannot drift")

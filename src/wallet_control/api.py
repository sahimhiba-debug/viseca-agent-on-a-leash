"""A small FastAPI demo backend fronting the wallet-control engine.

This is the "demo" surface, not the official Viseca integration -- it exists so
the three required demo flows (challenge.md: an ordinary purchase, an ambiguous/
unsafe/manipulated purchase, and the human approval/rejection/revocation path) can
be driven from a browser without a hosted API key. `live_worker.py` /
`viseca_client.py` are the real integration; this module reuses the exact same
`decision_engine`/`mandate`/`state` code so the demo is not a separate code path.

State is a single in-process dict, deliberately not a database (see
docs/ARCHITECTURE.md "Concurrency"): this is an event-day demo tool for one team,
not a multi-tenant service.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .attack_demo import run_all_attacks
from .audit import audit_timeline, delegation_summary
from .csv_data import account_limits_for_card, history_csv_path, load_merchants, load_purchase_attempt_items, load_scenario_catalogue, scenario_rows
from .decision_engine import _PLAIN_FAIL, _PLAIN_UNKNOWN, agent_view, evaluate_authorization, resolve_authorization
from .mandate import Mandate
from .offline_replay import build_event, compile_and_confirm_mandate_for_scenario
from .policy_compiler import compile_instruction
from .state import HistoryIndex, RunState

app = FastAPI(title="Wallet Control -- Agent on a Leash (demo)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_HISTORY = HistoryIndex.from_csv(history_csv_path())
# Fixed simulated clock for the agent demo, so the trace is identical on every run.
AGENT_DEMO_START = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
# Three restrictions, only one of them about money. A ceiling-only errand is a poor
# demonstration of this agent: it aims low by design -- the objective spends as
# little as it can once the errand is done -- so it lands inside a CHF 120 cap on
# its first attempt and nothing is ever refused. The interesting behaviour is how it
# answers a refusal that CANNOT be fixed by spending less.
_AGENT_DEFAULT_INSTRUCTION = (
    "Order our household groceries for delivery from a shop I have used before. "
    "Keep each order at or below CHF 120 including delivery, and keep the total "
    "across any seven days at or below CHF 300, and only if returnable within 14 "
    "days. Ask me when uncertain."
)
_AGENT_SESSIONS: dict[str, "DemoRun"] = {}


@dataclass
class DemoRun:
    run_id: str
    mandate: Mandate
    state: RunState
    events_by_authorization: dict[str, dict[str, Any]]
    order: list[str]
    # When the customer pressed "Confirm these rules". The UI claimed a confirmation
    # step in three places and had no control that produced one, and the audit
    # recorded "Mandate confirmed" with no time -- because no such event had happened.
    # Either the gate is real and stamped, or the claim comes out. It is now real.
    confirmed_at: datetime | None = None
    # The identifier the CUSTOMER view is served under. Minted here, never returned
    # to the agent, and deliberately not the `session_id` the agent chose -- see
    # `customer_session_view` for why that distinction is the whole point.
    view_id: str = ""


_RUNS: dict[str, DemoRun] = {}


class CompileRequest(BaseModel):
    instruction: str


class RunRequest(BaseModel):
    """Deliberately empty of anything the server can determine itself.

    `confirmed_at` used to be here, and it reached the audit timeline as an entry
    attributed to `actor="customer"`. A record asserting when the CUSTOMER confirmed
    their rules, carrying a timestamp the CALLER chose, is not evidence of anything
    -- a caller could and did stamp it 1999-01-01. The server stamps it now.
    """


class ResolveRequest(BaseModel):
    """What a step-up answer may carry: the answer, and nothing else.

    `customer_message` used to sit here. Nothing ever read it, which is precisely
    why it was worth removing: a caller-controlled field that the server accepts and
    ignores is one careless commit away from being wired up, and the last red-team
    pass found exactly that shape -- `instruction` on the agent's endpoint -- after
    it HAD been wired up and was letting an agent write its own mandate.
    """

    decision: str  # "allow" | "block"


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness plus the numbers a teammate needs before a demo: if the replay has
    moved off 19/2/24, something is wrong and it is better to find out here than on
    stage."""
    from .offline_replay import replay_all

    replay = replay_all()
    counts = replay.total_counts()
    return {
        "status": "ok",
        "active_runs": len(_RUNS),
        "official_replay": {
            "events": replay.total_events(),
            "allow": counts["allow"], "review": counts["review"], "block": counts["block"],
            "expected": {"events": 45, "allow": 19, "review": 2, "block": 24},
            "matches_regression_boundary": (
                replay.total_events() == 45 and counts["allow"] == 19
                and counts["review"] == 2 and counts["block"] == 24
            ),
        },
    }


@app.post("/api/demo/reset")
def demo_reset() -> dict[str, Any]:
    """Clear every in-memory run so a demo starts from a known state.

    This touches only the demo server's run dict. It cannot alter the official data,
    the compiled policies, or any decision already recorded in a run it removes --
    those runs simply cease to exist.
    """
    cleared = len(_RUNS)
    _RUNS.clear()
    return {"cleared_runs": cleared}


class AgentProposal(BaseModel):
    """What an agent may send. Note what is NOT here: an instruction.

    It used to be. `POST /api/agent/propose` accepted `instruction` and, for an
    unknown session, compiled and CONFIRMED a mandate out of it -- so an agent could
    author the policy it was about to be judged against. A red-team pass put the
    same CHF 500 basket through twice: refused under the customer's CHF 120 mandate,
    and APPROVED when the agent supplied "keep each order at or below CHF 900".

    That is the exact opposite of this project's claim. Adaptation is supposed to
    consume a delegation, never widen one. Establishing a mandate is a customer
    action and now requires a customer endpoint.
    """

    session_id: str
    lines: list[dict[str, Any]]


class MandateForSession(BaseModel):
    session_id: str
    instruction: str


def _new_agent_session(session_id: str, instruction: str) -> "DemoRun":
    """Compile and confirm one mandate, and open a session under it."""
    compiled = compile_instruction(instruction)
    mandate = Mandate.draft(
        instruction, compiled.hard_rules, compiled.uncertainty_policy,
        compiled.guidance, compiled.open_questions, compiled.unsupported_restrictions,
    )
    mandate.confirm(confirmed=True, customer_id="CU0001", card_id="CA0001",
                    profile_id="PROFILE_AGENT_DEMO",
                    acknowledged_unsupported=compiled.unsupported_restrictions)
    session = DemoRun(session_id, mandate, RunState(history=_HISTORY, card_id="CA0001"),
                      {}, [], datetime.now(timezone.utc), view_id=secrets.token_urlsafe(9))
    _AGENT_SESSIONS[session_id] = session
    return session


@app.post("/api/customer/mandates")
def establish_mandate(req: MandateForSession) -> dict[str, Any]:
    """The CUSTOMER establishes the mandate a session will be judged under.

    This is deliberately not on the agent's endpoint. It used to be: `propose`
    accepted an `instruction` and confirmed a mandate from it, so an agent could
    write the policy it was about to be judged against, and a CHF 500 basket that
    the customer's CHF 120 mandate refused was approved when the agent supplied a
    CHF 900 one instead.

    Tightening-only amendment still belongs to the mandate lifecycle; this only
    opens a session. An existing session's mandate cannot be replaced here, because
    "the rules can change under a running agent" is not a property we want.
    """
    if req.session_id in _AGENT_SESSIONS:
        raise HTTPException(status_code=409, detail=(
            "this session already has a mandate; start a new session rather than "
            "changing the rules under a running agent"))
    session = _new_agent_session(req.session_id, req.instruction)
    compiled = compile_instruction(req.instruction)
    return {
        "session_id": req.session_id,
        "hard_rules": [r.as_dict() for r in session.mandate.snapshot().hard_rules],
        "unsupported_restrictions": list(compiled.unsupported_restrictions),
        "open_questions": list(compiled.open_questions),
    }


@app.post("/api/agent/propose")
def agent_propose(req: AgentProposal) -> dict[str, Any]:
    """The AGENT-FACING decision endpoint. Returns `agent_view` and nothing else.

    The wallet does not contain a shopping agent and must not import one -- the agent
    is an external client, and `tests/test_runtime_boundary.py` enforces that the
    runtime never reaches into `research/`. An earlier version of this endpoint ran
    the agent loop inline and broke exactly that invariant; inverting the dependency
    is both the correct architecture and the more honest demonstration, because the
    loop now visibly happens OUTSIDE the wallet.

    What comes back is deliberately poorer than `/api/runs/{id}`: the decision, the
    CLASS of constraint that failed, and whether a human is deciding. No rule value,
    no remaining budget, no evidence. See
    `tests/security/test_agent_explanation_boundary.py` for the measurement that puts
    the line there -- an agent seeing only this recovers a CHF 137 ceiling in twelve
    probes and spends CHF 531 doing it; the customer's payload would do it in zero.
    """
    # A malformed line is the caller's bug, and must read as one. Omitting `item_id`
    # raised an uncaught KeyError and returned a 500 with a stack trace on an
    # agent-controlled input -- a refusal dressed as a crash.
    required = ("item_id", "name", "category", "unit_price")
    for index, line in enumerate(req.lines):
        missing = [k for k in required if k not in line]
        if missing:
            raise HTTPException(status_code=400, detail=(
                f"line {index + 1} is missing {', '.join(missing)}"))

    session = _AGENT_SESSIONS.get(req.session_id)
    if session is None:
        # An unknown session gets the BUILT-IN demo mandate, never one the caller
        # chose. A customer establishes their own through POST /api/customer/mandates.
        session = _new_agent_session(req.session_id, _AGENT_DEFAULT_INSTRUCTION)

    snapshot = session.mandate.snapshot()
    revision = len(session.order)
    amount = round(sum(float(l["unit_price"]) * int(l.get("quantity", 1)) for l in req.lines), 2)
    when = AGENT_DEMO_START + timedelta(minutes=90 * revision)
    stamp = when.isoformat().replace("+00:00", "Z")
    # The event must describe the purchase the AGENT proposed, not a convenient one.
    # This used to pin the merchant to ME0001 and the return window to 30 days no
    # matter what came in, so the demo could only ever produce an `amount` refusal --
    # the merchant and order-terms refusals that the page's planner knows how to
    # answer were unreachable, and a jury would have been shown a narrower agent than
    # the one we ship.
    windows = [l.get("return_days") for l in req.lines]
    items = [{"line_no": i + 1, "item_id": l["item_id"], "item_name": l["name"],
              "item_category": l["category"], "quantity": int(l.get("quantity", 1)),
              "unit_price": float(l["unit_price"]), "currency": "CHF",
              "item_details": ("" if l.get("return_days") is None
                               else f"returns accepted within {int(l['return_days'])} days")}
             for i, l in enumerate(req.lines)]
    returnable = ("unknown" if any(w is None for w in windows)
                  else "true" if all(int(w) > 0 for w in windows) else "false")
    # A basket spanning two shops, or naming one that does not exist, is not a
    # purchase anyone could make. Quietly re-attributing it to a default merchant
    # would hand the engine a truthful evaluation of a false description -- the same
    # defect that let an earlier agent be "approved" while holding goods from a shop
    # the customer had excluded. Refuse it instead; the caller has a bug.
    proposed = {str(l.get("merchant") or "ME0001") for l in req.lines}
    if len(proposed) != 1:
        raise HTTPException(status_code=400, detail=(
            "a proposal must come from one merchant; this basket names "
            f"{len(proposed)}: {sorted(proposed)}"))
    merchant_id = proposed.pop()
    merchant = load_merchants().get(merchant_id)
    if merchant is None:
        raise HTTPException(status_code=400,
                            detail=f"unknown merchant {merchant_id!r}")
    event = {
        "type": "authorization.request", "request_id": f"req_agent_{revision}",
        "deadline_at": (when + timedelta(seconds=8)).isoformat().replace("+00:00", "Z"),
        "authorization": {
            "authorization_id": f"{req.session_id}_{revision}",
            "source_authorization_id": f"{req.session_id}_{revision}",
            "scenario_id": "SCEN_AGENT", "replay_order": revision + 1,
            "mandate_id": snapshot.mandate_id, "profile_id": snapshot.profile_id,
            "card_id": snapshot.card_id, "initiator_type": "agent",
            "merchant": {
                "merchant_id": merchant_id,
                "merchant_name": merchant["merchant_name"],
                "merchant_category": merchant["merchant_category"],
                "merchant_mcc": merchant["merchant_mcc"],
                "merchant_country": merchant["merchant_country"],
                "merchant_city": merchant["merchant_city"],
                "availability": "online", "recurring_capable": "false"},
            "timestamp": stamp, "amount": amount, "currency": "CHF",
            "billing_amount_chf": amount, "items_subtotal": amount, "delivery_fee": 0.0,
            "channel": "ecommerce", "customer_device_id": "DVC-AGENT",
            "authority_status": "active", "card_status_at_attempt": "active",
            "spend_in_period_before_chf": None, "recent_attempt_count_10m": 0,
            "fulfillment_method": "delivery", "delivery_by": None,
            "order_returnable": returnable, "order_cancellable": "unknown",
            "related_authorization_id": None, "related_authorization_status": None,
            "purchase_description": f"{len(items)} grocery lines", "items": items,
        },
        "mandate": {"mandate_id": snapshot.mandate_id, "status": snapshot.status.value,
                    "customer_id": snapshot.customer_id, "card_id": snapshot.card_id,
                    "instruction": snapshot.instruction,
                    "hard_rules": [r.as_dict() for r in snapshot.hard_rules],
                    "uncertainty_policy": snapshot.uncertainty_policy.value,
                    "profile_id": snapshot.profile_id},
        "context": {"approved_spend_in_period_chf": float(session.state.total_approved_spend_chf()),
                    "recent_authorizations": []},
        "runtime": {"received_at": stamp, "history_window_minutes": 60, "context_basis": "run"},
    }
    result = evaluate_authorization(event, snapshot, session.state)
    session.order.append(result.authorization_id)
    session.events_by_authorization[result.authorization_id] = event
    return agent_view(result)


@app.get("/api/customer/sessions")
def customer_sessions() -> dict[str, Any]:
    """The customer's own surface: which sessions exist, by their VIEW id.

    A real deployment authenticates this. The demo does not, and we say so rather
    than implying otherwise -- see `docs/AGENT_VISIBLE_DATA.md`.
    """
    return {"sessions": [{"view_id": s.view_id, "started": s.confirmed_at.isoformat()
                          if s.confirmed_at else None, "attempts": len(s.order)}
                         for s in _AGENT_SESSIONS.values() if s.view_id]}


@app.get("/api/customer/sessions/{view_id}")
def customer_session_view(view_id: str) -> dict[str, Any]:
    """The SAME attempts, as the CUSTOMER sees them. Richer on purpose: this is the
    other half of the audience separation.

    This used to live at `GET /api/agent/sessions/{session_id}`, and an information-
    boundary audit found that name was not a label -- it was an invitation. The path
    sat in the agent's own namespace and was keyed on the `session_id` the AGENT
    chooses and sends on every proposal. So an agent could read its own customer view
    in one GET and receive `hard_rules[].value = 120`, every evidence string, and both
    verdicts. The entire "twelve probes and CHF 531 to recover a ceiling" analysis was
    bypassable by an agent that simply asked.

    It is now keyed on a `view_id` minted server-side and never returned to the agent
    on any agent-facing route, which `tests/security/test_agent_information_boundary.py`
    checks by searching every agent response for it.

    The demo API has no authentication, so this is NOT a claim that the agent cannot
    reach this data -- it is the narrower, testable claim that nothing the agent is
    GIVEN tells it where to look.
    """
    for session in _AGENT_SESSIONS.values():
        if session.view_id == view_id:
            return {
                "view_id": view_id,
                "mandate": session.mandate.as_dict(),
                "attempts": [_stored_decision_summary(session.events_by_authorization[a],
                                                      session.state.get_stored_decision(a),
                                                      revoked=session.state.is_revoked)
                             for a in session.order],
            }
    raise HTTPException(status_code=404, detail="unknown session view")


@app.get("/api/attacks")
def attacks() -> dict[str, Any]:
    """The eight attack demonstrations, run live against the real engine.

    Deterministic: fixed ids, fixed simulated clock, no network, no model. These use
    the same `evaluate_authorization` and `MockPSP.charge` as the official replay, so
    they cannot drift away from the product without the test suite failing.
    """
    results = [a.as_dict() for a in run_all_attacks()]
    return {
        "attacks": results,
        "held": sum(1 for r in results if r["held"]),
        "total": len(results),
    }


@app.get("/api/scenarios")
def list_scenarios() -> list[dict[str, Any]]:
    return list(load_scenario_catalogue().values())


@app.post("/api/mandates/compile")
def compile_preview(req: CompileRequest) -> dict[str, Any]:
    """Preview the rules a customer's instruction would compile to, for them to
    review before confirming (challenge.md: "Show the customer which checks you
    created and any uncertainty before asking them to confirm")."""
    compiled = compile_instruction(req.instruction)
    return {
        "instruction": req.instruction,
        "hard_rules": [r.as_dict() for r in compiled.hard_rules],
        "uncertainty_policy": compiled.uncertainty_policy.value,
        "guidance": compiled.guidance,
        "open_questions": compiled.open_questions,
        # The subset the customer must actively accept -- restrictive intent we could
        # not turn into a rule. The UI shows these separately from advisory questions.
        "unsupported_restrictions": compiled.unsupported_restrictions,
    }


@app.get("/api/scenarios/security-override")
def scenario_with_security_override() -> dict[str, Any]:
    """Which official scenario contains a decision the CUSTOMER's rules allowed and
    the wallet stopped anyway.

    Computed by running them, not looked up in a table. The written demo script
    pointed at the wrong scenario for two campaigns -- SCEN0002's review is a POLICY
    review, the customer's own returnable rule being uncertain, which is a much
    weaker claim than the one being made over it. Deriving it means the demo follows
    the property rather than a remembered id, and a jury can check the derivation.
    """
    for scenario_id in sorted(load_scenario_catalogue()):
        try:
            result = start_scenario_run(scenario_id, None)
        except HTTPException:
            continue
        for decision in result.get("decisions", []):
            if decision.get("policy_verdict") == "allow" and decision.get("security_verdict") != "allow":
                return {"scenario_id": scenario_id,
                        "authorization_id": decision.get("authorization_id"),
                        "why": "the customer's rules were satisfied and the wallet stopped it anyway"}
    return {"scenario_id": None, "authorization_id": None,
            "why": "no official scenario currently contains a security override"}


@app.post("/api/scenarios/{scenario_id}/run")
def start_scenario_run(scenario_id: str, req: RunRequest | None = None) -> dict[str, Any]:
    """Compile+confirm a fresh mandate from the scenario's own cardholder_instruction
    and replay its purchase attempts one by one, exactly like the offline replay,
    but keeping the run's state alive in memory so step_up authorizations in it can
    be resolved afterwards through this API."""
    catalogue = load_scenario_catalogue()
    if scenario_id not in catalogue:
        raise HTTPException(404, f"unknown scenario_id {scenario_id!r}")

    mandate = compile_and_confirm_mandate_for_scenario(scenario_id)
    snapshot = mandate.snapshot()
    state = RunState(history=_HISTORY, card_id=snapshot.card_id)
    run_id = f"RUN_{uuid.uuid4().hex[:10]}"

    items_by_auth = load_purchase_attempt_items()
    merchants = load_merchants()
    events_by_authorization: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    decisions = []
    for row in scenario_rows(scenario_id):
        merchant = merchants[row["merchant_id"]]
        items = items_by_auth[row["authorization_id"]]
        context = {
            "approved_spend_in_period_chf": float(state.total_approved_spend_chf()),
            "recent_authorizations": state.recent_authorizations_context(),
        }
        event = build_event(row, items, merchant, snapshot, context)
        result = evaluate_authorization(event, snapshot, state)
        events_by_authorization[row["authorization_id"]] = event
        order.append(row["authorization_id"])
        decisions.append(_decision_summary(event, result))

    # Stamped here, by the server, at the moment this run's mandate is confirmed.
    # Never accepted from the caller: the audit records this as an act of the
    # CUSTOMER, and a customer-attributed fact whose timestamp any caller can choose
    # is not evidence of anything. A caller could and did stamp it 1999-01-01.
    _RUNS[run_id] = DemoRun(run_id, mandate, state, events_by_authorization, order,
                            datetime.now(timezone.utc))
    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "mandate": mandate.as_dict(),
        "decisions": decisions,
    }


def _decision_summary(event: dict[str, Any], result) -> dict[str, Any]:
    auth = event["authorization"]
    # Split the evidence tree into "your policy" (what the customer's own mandate
    # checked) and "wallet safety checks" (control-layer integrity concerns the
    # customer never had to opt into) -- purely a display grouping, computed from
    # the `source` tag on each RuleEvaluation; it can never change the decision
    # itself, only how it is explained. See docs/MASTER_R_AND_D_AUDIT.md,
    # "alternative policy representations."
    policy_evidence = [f"{e.rule.field} [{e.outcome}]: {e.detail}" for e in result.rule_evaluations if e.source == "customer"]
    safety_evidence = [f"{e.rule.field} [{e.outcome}]: {e.detail}" for e in result.rule_evaluations if e.source == "safety"]
    return {
        "authorization_id": result.authorization_id,
        "merchant_name": auth["merchant"]["merchant_name"],
        "amount_chf": auth["billing_amount_chf"],
        "purchase_description": auth["purchase_description"],
        # What the agent ACTUALLY proposed, not what the customer asked for.
        "basket": _basket_lines(auth),
        "decision": result.decision,
        "wallet_decision": result.decision,
        "resolved_by_customer": False,
        "intervention": result.intervention,
        "reason_codes": list(result.reason_codes),
        "customer_message": result.customer_message,
        "evidence": list(result.evidence),
        "policy_evidence": policy_evidence,
        "safety_evidence": safety_evidence,
        "idempotent_replay": result.idempotent_replay,
        # R&D Tracks A/D/E (docs/RND_FINAL_DECISION.md): purely additional, explanatory
        # fields -- none of them can change `decision` above, which is still produced
        # entirely by `_decide()` over the rule evaluations already shown.
        "policy_verdict": result.policy_verdict,
        "security_verdict": result.security_verdict,
        "drift": result.drift.as_dict() if result.drift is not None else None,
        "payment_authority": result.payment_authority.as_dict() if result.payment_authority is not None else None,
    }


@app.get("/api/runs/{run_id}/audit")
def get_run_audit(run_id: str) -> dict[str, Any]:
    """The audit timeline and the delegation summary -- both PROJECTIONS.

    Recomputed from the mandate snapshot and the decision ledger on every call. There
    is no presentation ledger that could drift from the record it describes.
    """
    run = _require_run(run_id)
    snapshot = run.mandate.snapshot()
    return {
        "run_id": run_id,
        "timeline": [e.as_dict() for e in audit_timeline(snapshot, run.state,
                                                         confirmed_at=run.confirmed_at)],
        "delegation": delegation_summary(
            snapshot, run.state, account_limits_for_card(snapshot.card_id or "")),
    }


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = _require_run(run_id)
    decisions = []
    for authorization_id in run.order:
        event = run.events_by_authorization[authorization_id]
        stored = run.state.get_stored_decision(authorization_id)
        # The SAME shape as POST /run. This used to return four fields, so the UI --
        # which re-renders the whole list after a step-up is answered -- threw away
        # every reason, every piece of evidence and every basket line the moment the
        # customer pressed Approve. A UX audit caught it: the one action a customer is
        # guaranteed to take deleted the explanation layer the product is built on.
        decisions.append(_stored_decision_summary(event, stored, revoked=run.state.is_revoked))
    return {"run_id": run_id, "mandate": run.mandate.as_dict(), "decisions": decisions}


def _stored_decision_summary(event: dict[str, Any], stored, *, revoked: bool = False) -> dict[str, Any]:
    """Re-present a recorded decision with the same fields a fresh evaluation returns.

    `wallet_decision` is deliberately separate from `decision`: for a purchase the
    wallet stepped up and a human then approved, the wallet's own answer was REVIEW
    and the final outcome is ALLOW. Collapsing them -- which the audit timeline did
    until this was found -- erases the single most audit-relevant fact in a run:
    whether policy allowed it, or whether a human overrode a hesitation.
    """
    auth = event["authorization"]
    if stored is None:
        return {"authorization_id": auth["authorization_id"], "decision": "pending",
                "merchant_name": auth["merchant"]["merchant_name"],
                "amount_chf": auth["billing_amount_chf"], "basket": [], "evidence": [],
                "policy_evidence": [], "safety_evidence": [], "reason_codes": [],
                "customer_message": "", "wallet_decision": "pending",
                "purchase_description": auth.get("purchase_description", ""),
                "payment_authority": None, "resolved_by_customer": False}
    authority = run_authority = None
    return {
        "authorization_id": stored.authorization_id,
        "merchant_name": auth["merchant"]["merchant_name"],
        "amount_chf": float(stored.billing_amount_chf),
        "purchase_description": auth.get("purchase_description", ""),
        "basket": _basket_lines(auth),
        "decision": stored.decision,
        "wallet_decision": "review" if stored.was_reviewed else stored.decision,
        # Which authority stopped this: the customer's own rule, or the wallet's
        # integrity check. Derived from the recorded reason codes, which carry the
        # rule field -- `safety` sources are the control-layer checks the customer
        # never opted into.
        **_verdict_split(stored.reason_codes),
        "resolved_by_customer": bool(stored.was_reviewed and stored.resolved_at),
        "reason_codes": list(stored.reason_codes),
        "customer_message": _recorded_message(stored, auth, revoked=revoked),
        "evidence": [], "policy_evidence": [], "safety_evidence": [],
        "payment_authority": None,
    }


_SAFETY_FIELDS = {
    "authorization.amount_integrity",
    "authorization.authority_status",
    "authorization.card_status_at_attempt",
    "authorization.mandate_status",
    "authorization.card_id_binding",
    "authorization.mandate_id_binding",
    "order.duplicate_suspected",
}


def _verdict_split(reason_codes: tuple[str, ...]) -> dict[str, Any]:
    """Split a recorded decision into the customer's verdict and the wallet's.

    A single-verdict engine cannot say "your policy allowed this and I stopped it
    anyway". Ours can, because every check carries the authority it came from. This
    reconstructs that split for a decision read back from the ledger; the fresh
    evaluation path reports it directly from the rule evaluations.
    """
    policy = security = "allow"
    for code in reason_codes:
        marker, _, field = code.partition(":")
        if not field:
            continue
        verdict = "block" if marker == "hard_rule_failed" else "review"
        if field in _SAFETY_FIELDS:
            security = "block" if verdict == "block" else max(security, verdict, key=_severity)
        else:
            policy = "block" if verdict == "block" else max(policy, verdict, key=_severity)
    return {"policy_verdict": policy, "security_verdict": security}


def _severity(verdict: str) -> int:
    return {"allow": 0, "review": 1, "block": 2}[verdict]


def _basket_lines(auth: dict[str, Any]) -> list[dict[str, Any]]:
    """What the agent ACTUALLY proposed, line by line.

    Every decision card used to be titled with the item the customer had requested,
    so eleven cards in the manipulated-agent scenario all read "27-inch computer
    monitor" -- including the one whose basket was a gift voucher. The engine caught
    every substitution and the card then concealed it.
    """
    return [
        {"name": i.get("item_name", ""), "quantity": i.get("quantity", 1),
         "category": i.get("item_category", "")}
        for i in auth.get("items", [])
    ]


def _recorded_message(stored, auth: dict[str, Any], *, revoked: bool = False) -> str:
    """Plain prose for a decision re-presented from storage.

    This used to emit `"Declined: hard_rule_failed:authorization.billing_amount_chf"`
    -- raw reason codes, on a customer-facing endpoint. The same class of defect as
    the one invariant I39 was written for, surviving in a surface that audit never
    looked at: it checked `customer_message` on FRESH decisions and on the platform
    payload, and `GET /api/runs/{id}` re-presents STORED ones through here.

    The wording comes from `decision_engine._PLAIN_FAIL` and `_PLAIN_UNKNOWN`, so
    there is one table rather than a second copy to drift.

    A second defect of the same shape was found here later, by running the scenario
    the demo script pointed at. Everything that was neither a block nor an ANSWERED
    review fell through to "Approved: this purchase matched your wallet policy" --
    including a review still WAITING for the customer. So the one decision in
    SCEN0004 where every customer rule passed and the wallet stopped the purchase
    anyway described itself to that customer as approved, while the same card showed
    the verdict as `review`. A message that contradicts the decision beside it is
    worse than no message.
    """
    # A human's answer is reported FIRST, because it outranks every other reason.
    # With the block branch ahead of it, a purchase the customer had personally
    # declined came back as "Declined: a check failed." -- blaming the wallet for a
    # decision the customer made, which is the same misattribution defect as the two
    # above wearing different clothes.
    if stored.was_reviewed and stored.resolved_at:
        return "You approved this purchase." if stored.decision == "allow" else "You declined this purchase."
    # A revoked run has nothing waiting in it. The message used to keep saying
    # "Waiting for you" after revocation -- inviting an answer that could not
    # produce an authority, since the run-level revocation refuses it either way.
    # The demo page happened to override this with its own copy, which is exactly
    # how a re-presented surface goes wrong unnoticed: the client was right and the
    # record it was rendering was not.
    if revoked and stored.decision == "review":
        return "Cancelled: you revoked this mandate while this purchase was still waiting for you."
    if stored.decision == "block":
        fields = [c.split(":", 1)[1] for c in stored.reason_codes if ":" in c]
        reasons = list(dict.fromkeys(
            _PLAIN_FAIL.get(f) or f"a check on {f.replace('.', ' ').replace('_', ' ')} did not pass"
            for f in fields
        ))
        return f"Declined: {'; '.join(reasons) or 'a check failed'}."
    if stored.decision == "review":
        fields = [c.split(":", 1)[1] for c in stored.reason_codes if c.startswith("uncertain:")]
        reasons = list(dict.fromkeys(
            _PLAIN_UNKNOWN.get(f) or f"the wallet could not check {f.replace('.', ' ').replace('_', ' ')}"
            for f in fields
        ))
        return f"Waiting for you: {'; '.join(reasons) or 'the wallet was not sure about this one'}."
    return "Approved: this purchase matched your wallet policy."


@app.post("/api/runs/{run_id}/authorizations/{authorization_id}/resolve")
def resolve_run_authorization(run_id: str, authorization_id: str, req: ResolveRequest) -> dict[str, Any]:
    """The human approval/rejection path. Scoped to exactly this authorization --
    see `decision_engine.resolve_authorization` -- and never touches the mandate.
    Deliberately does not accept an amount from the request body: the amount that
    matters is whatever the customer was actually shown when the purchase was
    flagged for review, sourced from `run.state`'s own record."""
    run = _require_run(run_id)
    if req.decision not in ("allow", "block"):
        raise HTTPException(400, "decision must be 'allow' or 'block'")
    if run.state.get_stored_decision(authorization_id) is None:
        raise HTTPException(404, f"{authorization_id} was never decided in this run")
    try:
        # `mandate=` is required, not optional: without it a human-approved step-up
        # mints no PaymentAuthority, which meant it could not be revoked and -- under
        # the old fail-open payment default -- was charged even after the customer
        # revoked. The purchase the customer was actually asked about was the one
        # that escaped their revocation. See docs/DEEP_SECURITY_RESEARCH.md (V2).
        result = resolve_authorization(
            authorization_id, req.decision, run.state, resolved_at=datetime.now(timezone.utc), mandate=run.mandate.snapshot()
        )
    except ValueError as exc:
        # Covers both "was never put to review" and "already resolved with a
        # different answer" -- both are 409 Conflict: the request is well-formed
        # but cannot be applied to this authorization's current state.
        raise HTTPException(409, str(exc)) from exc
    return _decision_summary(run.events_by_authorization[authorization_id], result)


@app.post("/api/runs/{run_id}/revoke")
def revoke_run_mandate(run_id: str) -> dict[str, Any]:
    """Revokes the *live* mandate behind this run. Matches the documented
    behaviour precisely: this run keeps its already-taken decisions (the run used a
    snapshot taken at start), but the mandate can no longer be used to start a new
    run (see `require_active_mandate_for_new_run` below) -- technical_details.md
    step 8 leaves the effect on purchases already queued in a run unspecified, and
    this demo does not claim to resolve that ambiguity."""
    run = _require_run(run_id)
    run.mandate.revoke()
    # Revocation must also stop money that has been authorized but not yet spent.
    # Without this, a customer could hit their emergency brake and an outstanding
    # PaymentAuthority would still execute (fourth-pass finding; see
    # docs/FINAL_ARCHITECTURE_ATTACK.md). Only our own synthetic capability object
    # is affected -- already-recorded decisions are untouched, so nothing the
    # engine previously told the platform changes.
    revoked_authorities = run.state.revoke_outstanding_authorities()
    return {
        "run_id": run_id,
        "mandate_status": run.mandate.status.value,
        "revoked_payment_authorities": list(revoked_authorities),
    }


@app.post("/api/runs/{run_id}/rerun-check")
def require_active_mandate_for_new_run(run_id: str) -> dict[str, Any]:
    """Demonstrates that a revoked mandate cannot authorize anything new."""
    run = _require_run(run_id)
    if not run.mandate.is_usable():
        raise HTTPException(403, f"mandate {run.mandate.mandate_id} is {run.mandate.status.value}; it cannot start new authority")
    return {"ok": True}


def _require_run(run_id: str) -> DemoRun:
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, f"unknown run_id {run_id!r}")
    return run


# Registered LAST and deliberately: a Mount("/") matches every path prefix, so it
# must come after every "/api/..." route above or it would swallow them first.
_UI_DIR = Path(__file__).resolve().parents[2] / "ui"


class _NoCacheStatic(StaticFiles):
    """Serve the demo page with caching off.

    A browser holding yesterday's page is a demo failure that looks exactly like a
    bug: during this campaign the nav still showed the old tab order and the
    scenario picker the old default, several minutes after both had been fixed and
    the server restarted. The fix-list in the demo script used to say "reload with
    ?v=2" for precisely this, which is a workaround written down instead of a cause
    removed. The page is a few tens of kilobytes on localhost; there is nothing to
    save by caching it.
    """

    def is_not_modified(self, response_headers, request_headers) -> bool:
        return False

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


if _UI_DIR.is_dir():
    app.mount("/", _NoCacheStatic(directory=_UI_DIR, html=True), name="ui")

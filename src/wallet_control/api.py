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

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .csv_data import history_csv_path, load_merchants, load_purchase_attempt_items, load_scenario_catalogue, scenario_rows
from .decision_engine import evaluate_authorization, resolve_authorization
from .demo_scenario import run_demo_scenario
from .mandate import Mandate
from .offline_replay import build_event, compile_and_confirm_mandate_for_scenario
from .policy_compiler import compile_instruction
from .state import HistoryIndex, RunState

app = FastAPI(title="Wallet Control -- Agent on a Leash (demo)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_HISTORY = HistoryIndex.from_csv(history_csv_path())


@dataclass
class DemoRun:
    run_id: str
    mandate: Mandate
    state: RunState
    events_by_authorization: dict[str, dict[str, Any]]
    order: list[str]


_RUNS: dict[str, DemoRun] = {}


class CompileRequest(BaseModel):
    instruction: str


class ResolveRequest(BaseModel):
    decision: str  # "allow" | "block"
    customer_message: str | None = None


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
    }


@app.post("/api/scenarios/{scenario_id}/run")
def start_scenario_run(scenario_id: str) -> dict[str, Any]:
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

    _RUNS[run_id] = DemoRun(run_id, mandate, state, events_by_authorization, order)
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
        "decision": result.decision,
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


@app.get("/api/rnd-demo")
def get_rnd_demo() -> dict[str, Any]:
    """The new, clearly-synthetic R&D scenario (`demo_scenario.py`) -- entirely
    separate from `/api/scenarios`, which only ever serves the official 45-event
    data. Returns the whole pre-narrated walkthrough (every id DEMO-prefixed) in
    one response: this is a fixed story used to demonstrate Tracks A/D/E, not an
    interactive run a caller can resolve step-by-step."""
    result = run_demo_scenario()
    steps = [
        {"label": step.label, **_decision_summary(step.event, step.result)}
        for step in result.steps
    ]
    resolution = _decision_summary(result.steps[1].event, result.resolution) if result.resolution is not None else None
    mandate = result.mandate
    return {
        "scenario_id": "DEMO_RND_0001",
        "mandate": {
            "mandate_id": mandate.mandate_id,
            "status": mandate.status.value,
            "instruction": mandate.instruction,
            "hard_rules": [r.as_dict() for r in mandate.hard_rules],
            "uncertainty_policy": mandate.uncertainty_policy.value,
        },
        "steps": steps,
        "resolution": resolution,
        "legitimate_charge": (
            {"charge_id": result.legitimate_charge.charge_id, "amount_chf": str(result.legitimate_charge.amount_chf)}
            if result.legitimate_charge is not None
            else None
        ),
        "tampered_charge_refusal_reason": result.tampered_charge_error,
    }


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = _require_run(run_id)
    decisions = []
    for authorization_id in run.order:
        event = run.events_by_authorization[authorization_id]
        stored = run.state.get_stored_decision(authorization_id)
        decisions.append(
            {
                "authorization_id": authorization_id,
                "merchant_name": event["authorization"]["merchant"]["merchant_name"],
                "amount_chf": event["authorization"]["billing_amount_chf"],
                "decision": stored.decision if stored else "pending",
            }
        )
    return {"run_id": run_id, "mandate": run.mandate.as_dict(), "decisions": decisions}


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
        result = resolve_authorization(authorization_id, req.decision, run.state, resolved_at=datetime.now(timezone.utc))
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
if _UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_UI_DIR, html=True), name="ui")

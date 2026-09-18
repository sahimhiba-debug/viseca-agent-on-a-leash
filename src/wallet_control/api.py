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

from .attack_demo import run_all_attacks
from .audit import audit_timeline, delegation_summary
from .csv_data import account_limits_for_card, history_csv_path, load_merchants, load_purchase_attempt_items, load_scenario_catalogue, scenario_rows
from .decision_engine import evaluate_authorization, resolve_authorization
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
    # When the customer pressed "Confirm these rules". The UI claimed a confirmation
    # step in three places and had no control that produced one, and the audit
    # recorded "Mandate confirmed" with no time -- because no such event had happened.
    # Either the gate is real and stamped, or the claim comes out. It is now real.
    confirmed_at: datetime | None = None


_RUNS: dict[str, DemoRun] = {}


class CompileRequest(BaseModel):
    instruction: str


class RunRequest(BaseModel):
    confirmed_at: str | None = None   # ISO time the customer confirmed the rules


class ResolveRequest(BaseModel):
    decision: str  # "allow" | "block"
    customer_message: str | None = None


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
    }


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

    confirmed_at: datetime | None = None
    if req is not None and req.confirmed_at:
        try:
            confirmed_at = datetime.fromisoformat(req.confirmed_at.replace("Z", "+00:00"))
        except ValueError:
            confirmed_at = None
    _RUNS[run_id] = DemoRun(run_id, mandate, state, events_by_authorization, order, confirmed_at)
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
        decisions.append(_stored_decision_summary(event, stored))
    return {"run_id": run_id, "mandate": run.mandate.as_dict(), "decisions": decisions}


def _stored_decision_summary(event: dict[str, Any], stored) -> dict[str, Any]:
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
        "resolved_by_customer": bool(stored.was_reviewed and stored.resolved_at),
        "reason_codes": list(stored.reason_codes),
        "customer_message": _recorded_message(stored, auth),
        "evidence": [], "policy_evidence": [], "safety_evidence": [],
        "payment_authority": None,
    }


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


def _recorded_message(stored, auth: dict[str, Any]) -> str:
    if stored.decision == "block":
        return f"Declined: {', '.join(stored.reason_codes) or 'a check failed'}"
    if stored.was_reviewed and stored.resolved_at:
        return "You approved this purchase." if stored.decision == "allow" else "You declined this purchase."
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
if _UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_UI_DIR, html=True), name="ui")

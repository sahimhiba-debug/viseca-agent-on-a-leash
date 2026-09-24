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

import os
import secrets
from decimal import Decimal
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
from .mandate import Mandate, UncertaintyPolicy
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
# session_id -> the DELEGATION that session shops under. Several session ids may
# point at one delegation; that is the whole point.
#
# These used to be the same map, so a session WAS a delegation and the agent --
# which chooses `session_id` -- chose the scope of its own rolling budget. Inventing
# a new string reset the week's allowance: twelve errands under a stated CHF 300 / 7
# days came to CHF 1,296. A delegation is something the CUSTOMER establishes, and
# the agent must not be able to mint one by naming it.
_AGENT_SESSIONS: dict[str, "DemoRun"] = {}
_DEFAULT_DELEGATION = "__default__"


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


# ============================================================== AUTHORSHIP REGISTRY
#
# Every caller-controlled field, and WHO is entitled to author it.
#
# This table exists because six separate vulnerabilities in this project turned out
# to be one bug: A FACT WAS ACCEPTED FROM A PARTY THAT IS NOT ITS AUTHOR.
#
#   instruction on /api/agent/propose   customer's policy, accepted from the AGENT
#   session_id scoping the budget       customer's delegation, scoped by the AGENT
#   confirmed_at on a run               wallet's clock, accepted from the CALLER
#   customer_message on resolve         wallet's words, accepted from the CALLER
#   mandate= on resolve_authorization   wallet's own check, disabled by the CALLER
#   confirmed_rules= on LiveWorker      customer's policy, adopted from the PLATFORM
#
# Each was found separately, months of campaigns apart, and each was fixed
# separately. None of the fixes prevented the next one, because the pattern was
# never named. Naming it is the point of this table: `scripts/run_authorship_audit.py`
# fails if a request model grows a field that is not declared here, so the NEXT
# instance cannot be added silently.
#
# "agent" means: this field may be authored by the party being judged. Such a field
# may never carry policy, scope, time, or anything the wallet reasons WITH -- only
# what the agent is asking for.
# The one line field whose NULL is a fact rather than a mistake: a seller who
# publishes no return window. Everything else that arrives empty is a proposal that
# does not describe a purchase, and is refused rather than filled in.
_NULL_MEANS_UNSTATED = frozenset({"return_days"})

FIELD_AUTHORS: dict[tuple[str, str], str] = {
    ("AgentProposal", "session_id"): "agent",
    ("AgentProposal", "lines"): "agent",
    ("MandateForSession", "session_id"): "customer",
    ("MandateForSession", "instruction"): "customer",
    ("CompileRequest", "instruction"): "customer",
    # Policy-bearing by name, and correctly so -- but only `/api/mandates/silence`
    # reads it, only to answer "what would this same sentence do under a different
    # fallback?", and nothing is stored. The answer is a pure function of the
    # instruction the caller already sent, so it discloses no policy the caller did
    # not bring with them. The customer owns the question because the customer owns
    # the fallback; an agent calling it learns its own input back.
    ("CompileRequest", "uncertainty_policy"): "customer",
    ("ResolveRequest", "decision"): "customer",
    # The audit's own request model. It caught this one the moment it was added,
    # which is the shortest possible demonstration that the rule is live rather
    # than descriptive: the endpoint built to check authorship failed the check.
    ("ProposedField", "model"): "customer",
    ("ProposedField", "field"): "customer",
    ("ProposedField", "author"): "customer",
}

# The RULES live in `authorship.py` so the audit script and the live endpoint check
# the same thing rather than two things that agree today.
from .authorship import POLICY_BEARING, check_field, check_registry  # noqa: E402,F401


class CompileRequest(BaseModel):
    instruction: str
    # Only `/api/mandates/silence` reads this, and only to answer "what would this
    # same sentence do under a different fallback?". Nothing is stored and no
    # mandate is created, so this cannot become a way to set a policy without
    # confirming one.
    uncertainty_policy: str | None = None


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


# The regression boundary, written ONCE. It used to be here twice -- a dict shown to
# the caller and the same four numbers again longhand in the comparison -- so moving
# the boundary updated one and not the other, and this endpoint cheerfully answered
# `expected: 17/4/24, matches_regression_boundary: false`. An internally
# contradictory health check is worse than none: it is the surface a teammate reads
# thirty seconds before going on stage.
REGRESSION_BOUNDARY = {"events": 45, "allow": 17, "review": 4, "block": 24}


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness plus the numbers a teammate needs before a demo: if the replay has
    moved off the boundary, better to find out here than on stage."""
    from .offline_replay import replay_all

    replay = replay_all()
    counts = replay.total_counts()
    actual = {"events": replay.total_events(), **counts}
    return {
        "status": "ok",
        "active_runs": len(_RUNS),
        "official_replay": {
            **actual,
            "expected": REGRESSION_BOUNDARY,
            "matches_regression_boundary": actual == REGRESSION_BOUNDARY,
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
    if req.session_id == _DEFAULT_DELEGATION:
        raise HTTPException(status_code=400, detail="reserved session id")
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
    #
    # THE CHECK WAS FOR PRESENCE, NOT FOR A VALUE, and the difference is a policy
    # bypass. `{"merchant": null}` has the key. It flowed into a set comprehension
    # reading `str(l.get("merchant") or "ME0001")` -- three lines below a comment
    # explaining that quietly re-attributing a basket to a default merchant "would
    # hand the engine a truthful evaluation of a false description". The comment was
    # right and the expression under it did exactly that:
    #
    #     names an unfamiliar shop   ->  BLOCK   blocked_by=["merchant"]
    #     names NOTHING at all       ->  ALLOW
    #
    # against "from a shop I have used before". Withholding the fact beat supplying
    # a bad one -- the same shape as the seller who publishes no return window, at
    # our own boundary this time, and here it is a genuine bypass rather than a
    # routing to `uncertainty_policy`.
    #
    # Four more payloads (`unit_price: null`, `unit_price: "abc"`, `quantity: null`,
    # `return_days: "many"`) raised out of the handler, which is the same defect in
    # its loudest form: a value the wallet cannot read is an ABSENCE, and an absence
    # must be represented, not thrown.
    required = ("item_id", "name", "category", "unit_price", "merchant")
    numeric = {"unit_price": float, "quantity": int, "return_days": int}
    for index, line in enumerate(req.lines):
        missing = [k for k in required if line.get(k) is None]
        if missing:
            raise HTTPException(status_code=400, detail=(
                f"line {index + 1} does not say {', '.join(missing)}. A proposal that "
                f"leaves one of these out is not a purchase anyone could make, and it "
                f"is not filled in for you: a missing fact is missing."))
        for key, cast in numeric.items():
            # NOT the same test for every field, because not every absence means the
            # same thing. An omitted `quantity` means one; an explicit null means the
            # caller had a value and lost it, which is malformed. An absent OR null
            # `return_days` means the seller states no return window -- a real fact
            # about the offer that the engine routes to `uncertainty_policy`, and the
            # one absence here that must stay legal.
            if key not in line:
                continue
            if line[key] is None and key in _NULL_MEANS_UNSTATED:
                continue
            try:
                cast(line[key])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=(
                    f"line {index + 1} has {key}={line[key]!r}, which is not a number"))

    session = _AGENT_SESSIONS.get(req.session_id)
    if session is None:
        # An unknown session joins the ONE built-in delegation -- it does not create
        # a delegation of its own. Every session id the agent invents therefore lands
        # in the same rolling window, which is what makes the window a bound rather
        # than a suggestion. The mandate is the built-in one, never a caller's.
        session = _AGENT_SESSIONS.get(_DEFAULT_DELEGATION)
        if session is None:
            session = _new_agent_session(_DEFAULT_DELEGATION, _AGENT_DEFAULT_INSTRUCTION)
        _AGENT_SESSIONS[req.session_id] = session

    snapshot = session.mandate.snapshot()
    revision = len(session.order)
    amount = round(sum(float(l["unit_price"]) * int(l.get("quantity", 1) or 1) for l in req.lines), 2)
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
              "item_category": l["category"], "quantity": int(l.get("quantity", 1) or 1),
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
    proposed = {str(l["merchant"]) for l in req.lines}
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
    than implying otherwise -- see `docs/archive/AGENT_VISIBLE_DATA.md`.
    """
    seen: dict[str, "DemoRun"] = {}
    for run in _AGENT_SESSIONS.values():
        if run.view_id:
            seen.setdefault(run.view_id, run)
    return {"sessions": [{"view_id": r.view_id,
                          "started": r.confirmed_at.isoformat() if r.confirmed_at else None,
                          "attempts": len(r.order)}
                         for r in seen.values()]}


class ProposedField(BaseModel):
    """A field somebody wants to add, for the audit to judge."""

    model: str = "AgentProposal"
    field: str
    author: str | None = None


@app.get("/api/authorship")
def authorship() -> dict[str, Any]:
    """Who may write which fact, and whether anything currently violates that.

    Run live against the loaded module rather than reported from a file, so the
    answer is about the code that is actually serving this request.
    """
    declared = {name: tuple(obj.model_fields)
                for name, obj in globals().items()
                if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel}
    violations = check_registry(FIELD_AUTHORS, declared)
    by_author: dict[str, list[str]] = {}
    for (model, field), author in sorted(FIELD_AUTHORS.items()):
        by_author.setdefault(author, []).append(f"{model}.{field}")
    return {
        "fields": [{"model": m, "field": f, "author": a}
                   for (m, f), a in sorted(FIELD_AUTHORS.items())],
        "by_author": by_author,
        "policy_bearing": sorted(POLICY_BEARING),
        "violations": [v.as_dict() for v in violations],
        "clean": not violations,
    }


@app.post("/api/authorship/propose-field")
def authorship_propose_field(req: ProposedField) -> dict[str, Any]:
    """Ask the real rule what it would say about a field somebody wants to add.

    This is not a simulation of the check -- it calls the same `check_field` the
    audit script calls. Adding a field is how four of the six historical defects
    arrived, so being able to TRY it, live, is the clearest demonstration of what
    the rule actually does.

    Nothing is mutated. The answer is advisory in exactly the way a build failure
    is advisory.
    """
    violations = check_field(req.model, req.field, req.author)
    return {
        "model": req.model, "field": req.field, "author": req.author,
        "accepted": not violations,
        "violations": [v.as_dict() for v in violations],
    }


@app.get("/api/customer/delegations")
def customer_delegations() -> dict[str, Any]:
    """Every delegation open on this card, and what has actually been approved under
    each -- plus the grand total across all of them.

    THIS IS A DISCLOSURE, NOT A BOUND. A rolling cap is enforced *within* a
    delegation; nothing bounds the sum across delegations, because the rule
    vocabulary has no scope above one mandate and this demo API has no
    authentication to stop a caller opening another. Twelve self-opened delegations
    put CHF 1,296 through a stated CHF 300 / 7 days.

    What CAN be done without inventing a guarantee is to make the number the
    customer would care about visible, so that an unbounded total is at least not an
    invisible one. A real deployment authenticates this surface and the question
    changes; here we show the arithmetic and say plainly that we do not enforce it.
    """
    seen: dict[str, "DemoRun"] = {}
    for run in _AGENT_SESSIONS.values():
        seen.setdefault(id(run), run)

    delegations = []
    total = Decimal("0")
    for run in seen.values():
        approved = [d for d in run.state.approved_decisions()]
        spent = sum((d.billing_amount_chf for d in approved), Decimal("0"))
        total += spent
        snapshot = run.mandate.snapshot()
        window = [r for r in snapshot.hard_rules
                  if r.field == "authorization.billing_amount_chf" and r.scope == "period"]
        delegations.append({
            "view_id": run.view_id,
            "instruction": snapshot.instruction,
            "approved_count": len(approved),
            "approved_chf": float(spent),
            "rolling_cap_chf": float(window[0].value) if window else None,
            "rolling_period_days": window[0].period_days if window else None,
        })

    caps = [d["rolling_cap_chf"] for d in delegations if d["rolling_cap_chf"]]
    return {
        "delegations": delegations,
        "approved_total_chf": float(total),
        "highest_single_cap_chf": max(caps) if caps else None,
        "enforced": False,
        "note": ("Each delegation is bounded by its own rolling cap. The total across "
                 "delegations is shown, not enforced: the rule format has no scope "
                 "above one mandate."),
    }


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


@app.post("/api/mandates/ambiguity")
def mandate_ambiguity(req: CompileRequest) -> dict[str, Any]:
    """Where does this sentence stop deciding the answer?

    Returns, for each genuinely ambiguous construct, a CONCRETE PURCHASE that two
    defensible readings judge differently. Not a confidence score and not a model's
    opinion of its own certainty -- both readings are run through the real engine,
    and if no purchase separates them the customer is not bothered.

    It began in `research/`, and the runtime-boundary test refused it -- correctly,
    even as a guarded local import. That refusal was the right answer to the wrong
    question: this is not apparatus, it is a product feature shown to the customer
    before they confirm, exactly like the compiler's open questions. So it moved
    into the runtime, where it decides nothing and advises everything.
    """
    from .ambiguity import witnesses as find_witnesses

    found_all = []
    for found in find_witnesses(req.instruction):
        as_compiled, alternative = found["labels"]
        found_all.append({
            "key": found["reading"].key,
            "question": found["reading"].question,
            "amount_chf": found["amount"],
            "repeats": found["repeats"],
            # HOW MANY purchases the two readings decide differently, out of how
            # many exist. "Your sentence is ambiguous" is a shrug; "about 470 of
            # 595 purchases" is a question someone can answer.
            "count": found["count"],
            "universe": found["universe"],
            "as_compiled": {"reading": as_compiled, "decision": found["verdict_a"]},
            "alternative": {"reading": alternative, "decision": found["verdict_b"]},
        })
    return {"instruction": req.instruction, "witnesses": found_all, "available": True}


@app.post("/api/mandates/uncertainty")
def mandate_uncertainty(req: CompileRequest) -> dict[str, Any]:
    """What the uncertainty dial costs, counted in purchases.

    Its own endpoint rather than part of `/size`, because it runs the whole
    enumeration three more times and `/size` answers as the customer types.

    The dial is the most consequential setting in a mandate and the least legible:
    "what should I do when I cannot tell?" asked once, in the abstract, about facts
    the customer has not met yet. `research/erasure.py` measures the security half --
    `decline` is the only setting in which saying less never buys the proposer more,
    over 8,124 erasures of the official events. This is the other half: on a mandate
    with a return-window rule, `decline` costs 116 purchases that `approve` would
    have taken without asking.
    """
    from .scope import uncertainty_tradeoff

    return uncertainty_tradeoff(req.instruction)


@app.post("/api/mandates/size")
def mandate_size(req: CompileRequest) -> dict[str, Any]:
    """How many purchases does this sentence authorise, out of how many exist?

    The rules a customer is shown are true and are not an answer to the question
    they actually have, which is how much rope they just handed over. So count it:
    every basket this world can produce, each put through the REAL engine under the
    drafted mandate.

    The absolute figures are a function of the enumeration's bound (one shop, up to
    five lines, the official catalogue) and mean nothing on their own. What carries
    meaning is how they MOVE when a clause is added -- "at or below CHF 120" removes
    450 of 595 -- which is the only honest answer to "what did that word do?".
    """
    from .scope import delegation_size

    policy = None
    if req.uncertainty_policy:
        try:
            policy = UncertaintyPolicy(req.uncertainty_policy)
        except ValueError:
            raise HTTPException(status_code=422, detail="unknown uncertainty policy")
    return delegation_size(req.instruction, policy)


@app.post("/api/mandates/read-back")
def mandate_read_back(req: CompileRequest) -> dict[str, Any]:
    """Which of your words did the compiler actually read?

    A RECEIPT, not a warning. Every word is deleted in turn and the sentence
    re-compiled: a word whose removal changes nothing was never read. That is a
    causal measurement, so it cannot share the compiler's blind spots -- it is
    defined as the complement of whatever the compiler matched.

    `emphasise` carries the clauses where NOTHING was read and the wording is
    restrictive. This is where a requirement goes to die silently today: the
    coverage markers that exist to catch a missed restriction are built from the
    same vocabulary as the compiler, so "I can send it back within 14 days"
    produces no rule, no question, and no trace at all.
    """
    from .unconsumed import MAX_WORDS, marks, too_long, unenforced_clauses

    if too_long(req.instruction):
        # Stated, not truncated. A partial read-back that did not say it was partial
        # would be this repository's own favourite defect wearing the badge of the
        # feature written to expose it.
        return {"instruction": req.instruction, "words": [], "emphasise": [],
                "analysed": False,
                "note": (f"This instruction is longer than {MAX_WORDS} words. The "
                         f"read-back deletes each word and compiles again, which grows "
                         f"quadratically, so it was not run at all rather than run "
                         f"partway and shown as if it were complete.")}

    return {
        "instruction": req.instruction,
        "analysed": True,
        "words": [{"word": m.word, "kind": m.kind, "start": m.start, "end": m.end}
                  for m in marks(req.instruction)],
        "emphasise": unenforced_clauses(req.instruction),
    }


@app.post("/api/mandates/silence")
def mandate_silence(req: CompileRequest) -> dict[str, Any]:
    """Which of your rules can a seller escape by publishing nothing?

    Same shape as `/api/mandates/ambiguity` and the same discipline: not a warning
    about a hypothetical, but three sellers offering the identical goods at the
    identical price, each judged by the real engine.

        states 30 days  -> ALLOW      the rule was checked and passed
        states 13 days  -> BLOCK      the rule was checked and failed
        states nothing  -> ?          the rule was never checked

    `policy` overrides what the sentence compiled to, so the customer can move the
    one dial that changes the third row and watch it change. Under `decline` the
    list comes back empty, because silence then buys nothing -- which is the whole
    reason this panel is worth reading when it does say something.
    """
    from .silence import silence_witness

    policy = None
    if req.uncertainty_policy:
        try:
            policy = UncertaintyPolicy(req.uncertainty_policy)
        except ValueError:
            raise HTTPException(status_code=422, detail="unknown uncertainty policy")
    found = silence_witness(req.instruction, uncertainty=policy)
    return {"instruction": req.instruction, "witnesses": found, "available": True}


def _provenance_for(rules) -> dict[str, Any]:
    """Per rule, and the weakest across the whole policy -- because a mandate is only
    as strong as the least-owned fact it depends on."""
    from .provenance import ADVISORY, for_rule, weakest

    fields = [r.field for r in rules]
    per_rule = []
    for rule in rules:
        fact = for_rule(rule.field)
        if fact is None:
            continue
        per_rule.append({"field": rule.field, "binding": fact.binding,
                         "author": fact.author, "checked_by": fact.checked_by,
                         "customer_line": fact.customer_line})
    overall = weakest(fields)
    forgeable = [p["field"] for p in per_rule if p["binding"] == ADVISORY]
    return {"rules": per_rule, "weakest": overall, "forgeable": forgeable}


@app.post("/api/mandates/compile")
def compile_preview(req: CompileRequest) -> dict[str, Any]:
    """Preview the rules a customer's instruction would compile to, for them to
    review before confirming (challenge.md: "Show the customer which checks you
    created and any uncertainty before asking them to confirm")."""
    compiled = compile_instruction(req.instruction)
    return {
        "instruction": req.instruction,
        "hard_rules": [r.as_dict() for r in compiled.hard_rules],
        # WHO SUPPLIES THE FACT EACH RULE IS CHECKED AGAINST. Two rules can look
        # equally solid on screen and be worth entirely different things: one read
        # from the card's own history, one from whatever the seller typed. Measured
        # by attack in `research/forgeable_facts.py`, not asserted here.
        "provenance": _provenance_for(compiled.hard_rules),
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
    # itself, only how it is explained. See docs/archive/MASTER_R_AND_D_AUDIT.md,
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
        # The wording, from the ENGINE. The UI kept its own copy of this table and
        # it drifted three ways in one afternoon; one source, one sentence.
        "plain_reasons": list(result.plain_reasons),
        "customer_message": result.customer_message,
        "evidence": list(result.evidence),
        "policy_evidence": policy_evidence,
        "safety_evidence": safety_evidence,
        "idempotent_replay": result.idempotent_replay,
        # R&D Tracks A/D/E (docs/archive/RND_FINAL_DECISION.md): purely additional, explanatory
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
        decisions.append(_stored_decision_summary(event, stored,
                                                  revoked=run.state.is_revoked,
                                                  mandate=run.mandate))
    return {"run_id": run_id, "mandate": run.mandate.as_dict(), "decisions": decisions}


def _stored_decision_summary(event: dict[str, Any], stored, *, revoked: bool = False,
                             mandate=None) -> dict[str, Any]:
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
        "plain_reasons": _plain_reasons_from_codes(stored.reason_codes, mandate),
        "customer_message": _recorded_message(stored, auth, revoked=revoked),
        "evidence": [], "policy_evidence": [], "safety_evidence": [],
        "payment_authority": None,
    }


# DERIVED, NOT COPIED. This was a hand-written list of seven fields while the engine
# had fourteen, and one of the seven (`authorization.mandate_status`) was not a field
# this engine emits at all. A purchase stopped by a WALLET check was therefore
# reported on the read-back path as stopped by the customer's own policy, for seven
# checks including the injected-listing one -- inverting the split this product calls
# the single most audit-relevant fact in a run.
from .decision_engine import SAFETY_RULE_FIELDS as _SAFETY_FIELDS  # noqa: E402


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


def _plain_reasons_from_codes(reason_codes, mandate=None) -> list[str]:
    """The same wording for a decision re-presented from storage, where the rule
    evaluations are gone and only the codes survive. One table, read from the
    engine -- never a second copy living in a client.

    `mandate` is optional and is used for ONE thing: a rolling-window breach reads
    better with the customer's own figure in it ("over the CHF 300 you allowed across
    any 7-day period") than without ("over the total you allowed across your rolling
    period"). The figure is NOT encoded in the reason code, deliberately -- codes are
    stored in the ledger and are the shape the agent-facing projection is derived
    from, and a policy value written into one is a policy value looking for a way
    out. It is read from the mandate the caller already holds instead.
    """
    window = None
    if mandate is not None:
        window = next((r for r in mandate.hard_rules
                       if r.field == "authorization.billing_amount_chf"
                       and r.scope == "period" and r.period_days), None)

    out: list[str] = []
    for code in reason_codes:
        if ":" not in code:
            continue
        kind, field = code.split(":", 1)
        # `observed:` carries the same wording as `uncertain:` -- it is the same
        # observation, it simply did not decide this purchase.
        table = _PLAIN_UNKNOWN if kind in ("uncertain", "observed") else _PLAIN_FAIL
        if field == "authorization.billing_amount_chf.period" and window is not None:
            try:
                out.append(f"it would take you over the CHF {float(window.value):g} you "
                           f"allowed across any {window.period_days}-day period")
                continue
            except (TypeError, ValueError):
                pass
        out.append(table.get(field) or field.replace(".", " ").replace("_", " "))
    return list(dict.fromkeys(out))


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
    # A THIRD instance of the shape this docstring already records twice. Everything
    # that reached here said "matched your wallet policy" -- including an approval
    # that matched nothing, because a rule could not be checked and the customer's
    # `approve when unsure` fallback let it through. The stored record knows: its
    # reason codes read `uncertain:...`. The sentence beside them said the rules were
    # met. Fixed in `decision_engine._customer_message` at the same time; both are
    # here because a re-presented surface is exactly where the first fix does not
    # reach.
    uncertain = [c.split(":", 1)[1] for c in stored.reason_codes if c.startswith("uncertain:")]
    if stored.decision == "allow" and uncertain:
        reasons = list(dict.fromkeys(
            _PLAIN_UNKNOWN.get(f) or f"the wallet could not check {f.replace('.', ' ').replace('_', ' ')}"
            for f in uncertain
        ))
        return (f"Approved, but not because the rules were met: {'; '.join(reasons)}. "
                f"You told the wallet to go ahead when it cannot be sure.")
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
        # that escaped their revocation. See docs/archive/DEEP_SECURITY_RESEARCH.md (V2).
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
    # docs/archive/FINAL_ARCHITECTURE_ATTACK.md). Only our own synthetic capability object
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
def _ui_dir() -> Path:
    """Where the demo page lives.

    Same resolution problem as the CSV pack, and the same fix: an installed copy
    sits in site-packages and `parents[2]` points nowhere useful, so a container
    served the API perfectly and returned 404 for the page. `WALLET_UI_DIR` lets a
    deployment say where it put it.
    """
    override = os.environ.get("WALLET_UI_DIR")
    if override:
        return Path(override)
    for candidate in (Path(__file__).resolve().parents[2] / "ui", Path.cwd() / "ui"):
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parents[2] / "ui"


_UI_DIR = _ui_dir()


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

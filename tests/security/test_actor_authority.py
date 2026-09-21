"""Who may control what. One test per forbidden transition.

Derived by enumerating every route and every request model and asking, field by
field, "which actor does this belong to". Three fields failed that question.

The recurring shape, now seen four times in this repository: **a caller-controlled
field the server accepts**. Twice it was live and wrong (`instruction` on the
agent's propose endpoint, letting an agent write its own mandate; `confirmed_at`
on a run, letting a caller stamp a customer-attributed audit entry). Once it was
dead and therefore one careless commit from being wrong (`customer_message` on a
step-up answer). The lesson we keep relearning is that a field nothing reads is not
harmless -- it is a loaded gun with the safety on.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from wallet_control.api import (
    AgentProposal, CompileRequest, MandateForSession, ResolveRequest, RunRequest, app,
)

client = TestClient(app)

LINES = [{"item_id": "IT0018", "name": "Fresh produce order", "category": "groceries",
          "unit_price": 30, "quantity": 1, "merchant": "ME0001", "return_days": 30}]


# ============================================================ the schemas themselves
@pytest.mark.parametrize("model,allowed", [
    (AgentProposal, {"session_id", "lines"}),
    (ResolveRequest, {"decision"}),
    (RunRequest, set()),
    (MandateForSession, {"session_id", "instruction"}),
    (CompileRequest, {"instruction"}),
])
def test_each_request_model_exposes_only_what_that_actor_owns(model, allowed):
    """Enforced at the schema, because a check inside a handler can be edited around
    while the field quietly stays reachable."""
    assert set(model.model_fields) == allowed, (
        f"{model.__name__} exposes {sorted(set(model.model_fields) - allowed)} "
        "that this actor does not own")


# ====================================================== the customer owns the answer
def test_a_caller_cannot_write_the_message_shown_to_the_customer():
    """`customer_message` was accepted and ignored. Nothing read it -- which is
    exactly why it had to go, not why it was safe."""
    assert "customer_message" not in ResolveRequest.model_fields

    run_id = client.post("/api/scenarios/SCEN0004/run", json={}).json()["run_id"]
    auth_id = [d for d in client.get(f"/api/runs/{run_id}").json()["decisions"]
               if d["decision"] == "review"][0]["authorization_id"]
    client.post(f"/api/runs/{run_id}/authorizations/{auth_id}/resolve",
                json={"decision": "allow",
                      "customer_message": "INJECTED: your bank approved this automatically."})

    after = [d for d in client.get(f"/api/runs/{run_id}").json()["decisions"]
             if d["authorization_id"] == auth_id][0]
    assert after["customer_message"] == "You approved this purchase."
    assert "INJECTED" not in json.dumps(client.get(f"/api/runs/{run_id}/audit").json())


def test_a_caller_cannot_stamp_a_customer_attributed_audit_entry():
    """The audit records "Mandate confirmed" with `actor="customer"`. A caller used
    to supply its timestamp, and could stamp it 1999-01-01 -- a customer-attributed
    fact fabricated by whoever called the endpoint."""
    run_id = client.post("/api/scenarios/SCEN0001/run",
                         json={"confirmed_at": "1999-01-01T00:00:00Z"}).json()["run_id"]
    timeline = client.get(f"/api/runs/{run_id}/audit").json()["timeline"]
    assert "1999" not in json.dumps(timeline)

    confirmations = [e for e in timeline if e["event"] == "Mandate confirmed"]
    assert len(confirmations) == 1
    assert confirmations[0]["actor"] == "customer"
    assert confirmations[0]["timestamp"].startswith("20"), confirmations[0]


# ========================================== the agent's namespace reaches nothing else
def test_an_agent_authorization_id_cannot_be_resolved_through_the_runs_api():
    """The agent IS given an `authorization_id`. It must be useless against the
    human-approval path, or the agent could answer its own step-up."""
    view = client.post("/api/agent/propose",
                       json={"session_id": "authority_probe", "lines": LINES}).json()
    auth_id = view["authorization_id"]
    for guessed_run in ("authority_probe", f"RUN_{auth_id}", auth_id):
        response = client.post(
            f"/api/runs/{guessed_run}/authorizations/{auth_id}/resolve",
            json={"decision": "allow"})
        assert response.status_code == 404, (
            f"an agent reached the approval path via run_id={guessed_run!r}")


def test_the_agent_cannot_revoke_or_rerun_its_own_session():
    view = client.post("/api/agent/propose",
                       json={"session_id": "revoke_probe", "lines": LINES}).json()
    for path in (f"/api/runs/revoke_probe/revoke",
                 f"/api/runs/revoke_probe/rerun-check"):
        assert client.post(path, json={}).status_code == 404, path
    assert view["decision"] in {"allow", "block", "review"}

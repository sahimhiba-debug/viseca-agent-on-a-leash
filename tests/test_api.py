"""End-to-end tests for the demo FastAPI backend, covering the three flows
challenge.md asks a demo to show: an ordinary purchase, an ambiguous/manipulated
purchase getting a useful intervention, and the human approval/revocation path.
"""

from fastapi.testclient import TestClient

from wallet_control.api import app

client = TestClient(app)


def test_list_scenarios_returns_all_five():
    r = client.get("/api/scenarios")
    assert r.status_code == 200
    assert len(r.json()) == 5


def test_compile_preview_shows_rules_before_confirmation():
    r = client.post("/api/mandates/compile", json={"instruction": "Buy groceries for CHF 50 or less. Ask me when uncertain."})
    assert r.status_code == 200
    body = r.json()
    assert body["uncertainty_policy"] == "ask"
    assert any(rule["field"] == "authorization.billing_amount_chf" for rule in body["hard_rules"])


def test_run_scenario_and_full_human_resolution_and_revocation_flow():
    r = client.post("/api/scenarios/SCEN0002/run")
    assert r.status_code == 200
    body = r.json()
    run_id = body["run_id"]
    decisions = body["decisions"]
    assert len(decisions) == 12

    ordinary = [d for d in decisions if d["decision"] == "allow"]
    manipulated = [d for d in decisions if d["decision"] == "block"]
    reviewed = [d for d in decisions if d["decision"] == "review"]
    assert ordinary and manipulated and reviewed  # all three required demo cases are present

    # Human approval path: resolve the step_up.
    au_id = reviewed[0]["authorization_id"]
    r2 = client.post(f"/api/runs/{run_id}/authorizations/{au_id}/resolve", json={"decision": "allow"})
    assert r2.status_code == 200
    assert r2.json()["decision"] == "allow"

    # Resolving it a second time with a DIFFERENT answer must not raise a 500 and
    # must not silently flip or discard the customer's original answer -- it is a
    # 409 Conflict, and the original decision stands.
    r2b = client.post(f"/api/runs/{run_id}/authorizations/{au_id}/resolve", json={"decision": "block"})
    assert r2b.status_code == 409
    au_state = next(d for d in client.get(f"/api/runs/{run_id}").json()["decisions"] if d["authorization_id"] == au_id)
    assert au_state["decision"] == "allow"  # first resolution still wins

    # Retrying with the SAME answer as before is a harmless idempotent success.
    r2c = client.post(f"/api/runs/{run_id}/authorizations/{au_id}/resolve", json={"decision": "allow"})
    assert r2c.status_code == 200
    assert r2c.json()["decision"] == "allow"

    # Revocation path: revoke, then confirm the mandate can no longer authorize anything new.
    r3 = client.post(f"/api/runs/{run_id}/revoke")
    assert r3.status_code == 200
    assert r3.json()["mandate_status"] == "revoked"

    r4 = client.post(f"/api/runs/{run_id}/rerun-check")
    assert r4.status_code == 403


def test_resolving_an_authorization_that_was_never_decided_is_a_client_error():
    r = client.post("/api/scenarios/SCEN0000/run")
    run_id = r.json()["run_id"]
    r2 = client.post(f"/api/runs/{run_id}/authorizations/AU_NEVER_SEEN/resolve", json={"decision": "allow"})
    assert r2.status_code == 404


def test_unknown_run_id_is_404_not_500():
    r = client.get("/api/runs/does-not-exist")
    assert r.status_code == 404


def test_revoking_the_mandate_also_kills_outstanding_payment_authorities():
    """The customer's emergency brake must stop money that has been authorized but
    not yet spent (fourth-pass finding; docs/FINAL_ARCHITECTURE_ATTACK.md)."""
    r = client.post("/api/scenarios/SCEN0001/run")
    run_id = r.json()["run_id"]
    allowed = [d for d in r.json()["decisions"] if d["decision"] == "allow" and d["payment_authority"]]
    assert allowed, "expected at least one ALLOW carrying a payment authority"

    revoked = client.post(f"/api/runs/{run_id}/revoke").json()
    assert revoked["mandate_status"] == "revoked"
    assert set(revoked["revoked_payment_authorities"]) >= {d["authorization_id"] for d in allowed}

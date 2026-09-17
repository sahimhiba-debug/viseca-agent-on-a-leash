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

    # Cannot resolve it a second time as if it were still pending in a new way --
    # re-resolving must not raise a 500 or silently flip the outcome.
    r2b = client.post(f"/api/runs/{run_id}/authorizations/{au_id}/resolve", json={"decision": "block"})
    assert r2b.status_code == 200
    assert r2b.json()["decision"] == "allow"  # first resolution still wins

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

"""V2 as it was actually exploited: end-to-end through the real demo API, with no
direct manipulation of internal state.

The exploit, before the fix:
  1. run SCEN0002  -> AU0016 goes to REVIEW
  2. customer approves AU0016 via /resolve   -> payment_authority: null
  3. customer revokes the mandate            -> revokes the auto-ALLOWs only
  4. charge(AU0016)                          -> CHF 175 moves, after revocation

The purchase the customer was explicitly asked about was the one that escaped
their revocation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from wallet_control.api import _RUNS, app
from wallet_control.payment import MockPSP, PaymentError

client = TestClient(app)


def _run_with_a_review():
    body = client.post("/api/scenarios/SCEN0002/run").json()
    reviews = [d for d in body["decisions"] if d["decision"] == "review"]
    assert reviews, "SCEN0002 is expected to raise at least one step-up"
    return body["run_id"], reviews[0]["authorization_id"]


def test_a_human_approval_through_the_api_mints_an_authority():
    run_id, authorization_id = _run_with_a_review()
    resolved = client.post(f"/api/runs/{run_id}/authorizations/{authorization_id}/resolve", json={"decision": "allow"}).json()
    assert resolved["decision"] == "allow"
    assert resolved["payment_authority"] is not None
    assert resolved["payment_authority"]["authorization_id"] == authorization_id


def test_revocation_covers_a_human_approved_purchase():
    run_id, authorization_id = _run_with_a_review()
    client.post(f"/api/runs/{run_id}/authorizations/{authorization_id}/resolve", json={"decision": "allow"})

    revoked = client.post(f"/api/runs/{run_id}/revoke").json()
    assert authorization_id in revoked["revoked_payment_authorities"]


def test_the_full_exploit_no_longer_moves_money():
    run_id, authorization_id = _run_with_a_review()
    client.post(f"/api/runs/{run_id}/authorizations/{authorization_id}/resolve", json={"decision": "allow"})
    client.post(f"/api/runs/{run_id}/revoke")

    run = _RUNS[run_id]
    stored = run.state.get_stored_decision(authorization_id)
    psp = MockPSP(run.state)
    with pytest.raises(PaymentError, match="revoked"):
        psp.charge(
            charge_id="CH1",
            authorization_id=authorization_id,
            amount_chf=stored.billing_amount_chf,
            merchant_id=stored.merchant_id,
        )
    assert not psp.is_charged(authorization_id)


def test_a_declined_step_up_still_mints_nothing():
    """The mirror property: saying no must not create a spendable authority."""
    run_id, authorization_id = _run_with_a_review()
    resolved = client.post(f"/api/runs/{run_id}/authorizations/{authorization_id}/resolve", json={"decision": "block"}).json()
    assert resolved["decision"] == "block"
    assert resolved["payment_authority"] is None
    assert _RUNS[run_id].state.get_authority(authorization_id) is None

"""Everything an agent is GIVEN, across every agent-facing surface.

Written after an information-boundary audit found that the primary endpoint being
clean was not sufficient -- which is the one thing the previous audit said it would
not assume, and then assumed.

`GET /api/agent/sessions/{session_id}` served the CUSTOMER view: the mandate with
`hard_rules[].value = 120`, every evidence string, and both verdicts. It sat in the
agent's own namespace and was keyed on the `session_id` **the agent chooses and
sends on every proposal**. An agent could therefore read the entire policy in one
GET, with zero probes, and the published "twelve probes, CHF 531 to recover a
ceiling" analysis was bypassable by an agent that simply asked.

The customer view now lives at `GET /api/customer/sessions/{view_id}` under an
identifier minted server-side and never handed to the agent.

WHAT IS AND IS NOT CLAIMED. The demo API has no authentication, so this is not a
claim that an agent *cannot* reach customer data -- with the view id it plainly
can. The claim is narrower and is what these tests check: **nothing the agent is
given, on any agent-facing route, contains a policy value, an evidence string, a
verdict, or the identifier of the customer view.**
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from wallet_control.api import app

client = TestClient(app)

LINES = [
    {"item_id": "IT0001", "name": "Fresh produce selection", "category": "groceries",
     "unit_price": 12, "quantity": 1, "merchant": "ME0005", "return_days": 30},
    {"item_id": "IT0018", "name": "Fresh produce order", "category": "groceries",
     "unit_price": 30, "quantity": 1, "merchant": "ME0001", "return_days": 30},
]

AGENT_VIEW_KEYS = {"authorization_id", "decision", "blocked_by", "awaiting_customer"}


def _propose(session_id, line):
    return client.post("/api/agent/propose",
                       json={"session_id": session_id, "lines": [line]})


def test_the_agent_namespace_contains_exactly_one_route():
    """A second route under `/api/agent/` is how the leak happened. If one appears,
    it must be audited deliberately rather than discovered later."""
    agent_routes = sorted(r.path for r in app.routes
                          if getattr(r, "path", "").startswith("/api/agent"))
    assert agent_routes == ["/api/agent/propose"], agent_routes


@pytest.mark.parametrize("line", LINES, ids=lambda l: l["merchant"])
def test_the_proposal_response_carries_only_the_four_permitted_fields(line):
    body = _propose(f"bound_{line['merchant']}", line).json()
    assert set(body) == AGENT_VIEW_KEYS, sorted(body)
    assert isinstance(body["blocked_by"], list)
    assert all(isinstance(c, str) for c in body["blocked_by"])


@pytest.mark.parametrize("line", LINES, ids=lambda l: l["merchant"])
def test_no_agent_response_contains_a_policy_value_or_engine_internal(line):
    raw = _propose(f"internals_{line['merchant']}", line).text
    for forbidden in ("120", "value", "evidence", "reason_code", "hard_rule",
                      "policy_verdict", "security_verdict", "customer_message",
                      "projected", "remaining", "billing_amount", "return_window"):
        assert forbidden not in raw, f"agent response carried {forbidden!r}: {raw}"
    # No decimal at all: a number is the one thing a threshold can be read out of.
    assert not re.search(r"\d+\.\d+", raw), raw


def test_the_agent_is_never_told_where_its_customer_view_lives():
    """The leak was not that customer data exists -- it is that the agent held the
    key to it. The view id must not appear in anything the agent receives."""
    session = "viewid_probe"
    agent_bodies = [_propose(session, line).text for line in LINES]

    listing = client.get("/api/customer/sessions").json()["sessions"]
    view_ids = [s["view_id"] for s in listing]
    assert view_ids, "no session was recorded"

    for body in agent_bodies:
        for view_id in view_ids:
            assert view_id not in body, "the agent was handed its own customer view id"


def test_guessing_the_session_id_no_longer_opens_the_customer_view():
    """The exact bypass, as an agent would have run it: it knows its own session id,
    because it chose it."""
    session = "agent_chosen_id"
    _propose(session, LINES[0])
    assert client.get(f"/api/agent/sessions/{session}").status_code == 404
    assert client.get(f"/api/customer/sessions/{session}").status_code == 404


def test_the_customer_view_still_shows_the_customer_everything():
    """The fix must not have removed the capability. The two audiences seeing
    different things is the thesis; the customer's half has to stay rich."""
    session = "customer_half"
    _propose(session, LINES[0])
    view_id = client.get("/api/customer/sessions").json()["sessions"][-1]["view_id"]
    body = client.get(f"/api/customer/sessions/{view_id}").json()
    assert body["view_id"] == view_id
    assert body["mandate"]["hard_rules"], "the customer can no longer see their own rules"
    assert body["attempts"], "the customer can no longer see what the agent tried"
    assert any(r.get("value") for r in body["mandate"]["hard_rules"]), (
        "the customer should see the actual limit they set")


def test_an_error_response_is_not_a_side_channel():
    """A distinct status or message per outcome would be a second oracle."""
    bad = client.post("/api/agent/propose", json={"session_id": "err", "lines": [
        dict(LINES[0], merchant="ME0001"), dict(LINES[1], merchant="ME0005")]})
    assert bad.status_code == 400
    assert "120" not in bad.text and "value" not in bad.text
    ok = _propose("err_ok", LINES[0])
    assert ok.status_code == 200, "every decision, allowed or refused, is one status"

"""Withholding a fact must never beat supplying a bad one.

THE BYPASS THIS FILE WAS WRITTEN FOR

    customer: "...from a shop I have used before."

        the agent names an UNFAMILIAR shop   ->  BLOCK  blocked_by=["merchant"]
        the agent names NOTHING AT ALL       ->  ALLOW

`/api/agent/propose` read the basket's shop as `str(l.get("merchant") or "ME0001")`,
and ME0001 is familiar to the demo card. So a line with no merchant was judged
against a shop the agent never proposed, and the customer's familiarity rule was
satisfied by a fact nobody supplied.

Three lines above that expression sat a comment explaining exactly why it was
wrong -- "quietly re-attributing it to a default merchant would hand the engine a
truthful evaluation of a false description" -- which is the sharpest available
statement of how this class survives: the reasoning was correct, written down, and
contradicted by the code beneath it.

THE SAME SHAPE, AT FOUR DIFFERENT BOUNDARIES

  a seller  publishes no return window   -> UNKNOWN, routed to uncertainty_policy
  an agent  names no merchant            -> a default shop  (THIS FILE)
  a customer writes an unrecognised phrase -> no rule, and until recently no trace
  a caller  sends `unit_price: null`     -> an exception out of the handler

Every one is an absence quietly replaced by something present. The check that was
supposed to catch the fourth tested for the KEY and not for a VALUE, so `null`
passed it.

WHAT IS ASSERTED

That a missing fact stays missing: refused at the boundary, named in the refusal,
and never filled in. And -- the other half, because a validator that rejects
everything would also pass the tests above -- that the ONE absence which is a real
fact about the world still works: a seller who publishes no return window.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from wallet_control.api import app

client = TestClient(app)

FAMILIAR, UNFAMILIAR = "ME0001", "ME0005"
INSTRUCTION = ("Order groceries at or below CHF 120 from a shop I have used before. "
               "Ask me when uncertain.")
LINE = {"item_id": "IT0018", "name": "Fresh produce order", "category": "groceries",
        "unit_price": 30, "quantity": 1, "merchant": FAMILIAR, "return_days": 30}


def _propose(session_id: str, line: dict, instruction: str = INSTRUCTION):
    client.post("/api/customer/mandates",
                json={"session_id": session_id, "instruction": instruction})
    return client.post("/api/agent/propose",
                       json={"session_id": session_id, "lines": [line]})


def test_naming_an_unfamiliar_shop_is_refused():
    """The control. Without this, every assertion below could pass on an engine that
    had simply stopped checking familiarity."""
    body = _propose("AB_CONTROL", {**LINE, "merchant": UNFAMILIAR}).json()
    assert body["decision"] == "block"
    assert body["blocked_by"] == ["merchant"]


def test_naming_a_familiar_shop_is_allowed():
    assert _propose("AB_OK", LINE).json()["decision"] == "allow"


@pytest.mark.parametrize("line,why", [
    ({k: v for k, v in LINE.items() if k != "merchant"}, "merchant key absent"),
    ({**LINE, "merchant": None}, "merchant explicitly null"),
])
def test_naming_no_shop_is_refused_rather_than_defaulted(line, why):
    """THE BYPASS. Both of these used to be ALLOW, judged against ME0001."""
    response = _propose(f"AB_{abs(hash(why))}", line)
    assert response.status_code == 400, (why, response.json())
    assert "merchant" in response.json()["detail"], why


@pytest.mark.parametrize("field", ["item_id", "name", "category", "unit_price", "merchant"])
def test_a_required_field_present_but_null_is_still_missing(field):
    """The check was `k not in line`, so `{"merchant": null}` passed it. Presence is
    not a value."""
    response = _propose(f"AB_NULL_{field}", {**LINE, field: None})
    assert response.status_code == 400, response.json()
    assert field in response.json()["detail"]


@pytest.mark.parametrize("field,value", [
    ("unit_price", "abc"), ("unit_price", None),
    ("quantity", None), ("return_days", "many"),
])
def test_an_unreadable_number_is_a_refusal_and_not_an_exception(field, value):
    """These four raised out of the handler on agent-controlled input. A value the
    wallet cannot read is an absence, and an absence must be represented, not
    thrown: no approval came of it either way, but a 500 leaves no refusal to
    audit and hands the party under suspicion a way to break the endpoint."""
    response = _propose(f"AB_NUM_{field}_{value}", {**LINE, field: value})
    assert response.status_code == 400, response.json()


@pytest.mark.parametrize("line,why", [
    ({k: v for k, v in LINE.items() if k != "return_days"}, "no return window offered"),
    ({**LINE, "return_days": None}, "return window explicitly unstated"),
    ({k: v for k, v in LINE.items() if k != "quantity"}, "quantity omitted means one"),
])
def test_the_absences_that_are_facts_still_work(line, why):
    """The other half, and the reason this is not just "validate everything". A
    seller who publishes no return window is a real fact about a real offer, which
    the engine routes to `uncertainty_policy`. Refusing it at the boundary would
    delete the very case the rest of this repository is about."""
    response = _propose(f"AB_FACT_{abs(hash(why))}", line)
    assert response.status_code == 200, (why, response.json())


def test_an_unstated_return_window_still_reaches_the_uncertainty_policy():
    """End to end: the absence survives the validator AND is treated as an open
    question by the engine, rather than as a pass."""
    body = _propose("AB_UNSTATED",
                    {k: v for k, v in LINE.items() if k != "return_days"},
                    instruction=("Order groceries at or below CHF 120, and only buy things "
                                 "I can return within 14 days. Ask me when uncertain.")).json()
    assert body["decision"] == "review"
    assert body["awaiting_customer"] is True
    assert "order_terms" in body["blocked_by"]

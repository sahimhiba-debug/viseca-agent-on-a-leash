"""Omitting a REQUIRED field must never make a decision more permissive.

Nothing in this service validates an incoming event against
`authorization_event.schema.json`. The engine reads the event defensively, field
by field, and that is the right shape for a control layer -- but it creates a
specific hazard: a check written as

    value = (event.get("block") or {}).get("field")
    if value is not None and value != expected:
        ...fail...

is switched OFF by DELETING the field it guards. The attacker does not have to
forge a plausible value; they only have to remove one.

That is not hypothetical. It was live in `_run_binding_failures` until the red
team pass that produced this file. `mandate.status` is the platform reporting the
result of the customer's `DELETE /v1/mandates`, and both `mandate` and
`mandate.status` are REQUIRED by the schema -- yet dropping either made a
`revoked` mandate produce ALLOW, mint an authority and charge. Its two sibling
status fields, `authority_status` and `card_status_at_attempt`, already routed a
missing value to `unknown`. Three platform status fields; one read a missing
required field as consent.

So the property is asserted GENERALLY rather than for the one field that was
broken. A field added to the schema later, and read with the same `.get()` idiom,
is caught here without anyone remembering to write a test for it.

A KeyError is an acceptable answer: it is fail-closed inside the engine, and
`live_worker.poll_forever` logs it and keeps polling rather than approving by
default. What is NOT acceptable is a quiet ALLOW. (What the PLATFORM does when a
deadline passes with no decision submitted is not stated in the official
documentation and we have not observed it -- see docs/WHAT_WE_REFUSE_TO_CLAIM.md.)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex, RunState

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "data" / "official" / "schemas" / "authorization_event.schema.json"
MERCHANT = "ME_KNOWN"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _mandate():
    return make_mandate(
        instruction="Order groceries.",
        hard_rules=[
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")
        ],
    )


def _state() -> RunState:
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT})}, available=True), card_id="CA_TEST")


def _event(mandate):
    return make_event(mandate=mandate, authorization_id="AU_OMIT", amount=100.0, merchant_id=MERCHANT)


def _decide(event, mandate) -> str:
    """The decision, or "raise" -- which is fail-closed, not an approval."""
    try:
        return evaluate_authorization(event, mandate, _state()).decision
    except (KeyError, TypeError, ValueError, AttributeError):
        return "raise"


def _enum_required_fields() -> list[tuple[str, str, list]]:
    """Required fields whose legal values the schema enumerates, so the test can
    ask "is any legal value of this field restrictive?" without hard-coding one."""
    schema = _schema()
    out = []
    for block in ("authorization", "mandate"):
        node = schema["properties"][block]
        for field in node["required"]:
            prop = node["properties"].get(field, {})
            if "enum" in prop:
                out.append((block, field, prop["enum"]))
    return out


def test_the_control_event_is_allowed():
    """Without a control that ALLOWs, the property below is vacuous."""
    mandate = _mandate()
    assert _decide(_event(mandate), mandate) == "allow"


@pytest.mark.parametrize("block,field,values", _enum_required_fields(), ids=lambda v: v if isinstance(v, str) else "")
def test_omission_is_no_weaker_than_the_strictest_legal_value(block, field, values):
    """If ANY value the schema permits for this field would stop the purchase,
    then REMOVING the field must stop it too.

    This is the property the defect violated, and it is stated over the schema's
    own enums rather than over a list of field names, so a field added to the
    schema later is covered without anyone remembering to extend this test.

    An earlier draft of this file asserted instead that omission is "never more
    permissive than the control". With an ALLOW control that is vacuous -- nothing
    is more permissive than allow -- and it passed against the unfixed engine.
    Four of the nine enum-bearing required fields are non-vacuous here
    (`currency`, `authority_status`, `card_status_at_attempt`, `mandate.status`);
    the rest are reported as skips rather than counted as passes.
    """
    restrictive = []
    for value in values:
        mandate = _mandate()
        event = _event(mandate)
        event[block][field] = value
        if _decide(event, mandate) != "allow":
            restrictive.append(value)
    if not restrictive:
        pytest.skip(f"no legal value of {block}.{field} is restrictive in this fixture")

    mandate = _mandate()
    event = _event(mandate)
    if field not in event[block]:
        pytest.skip(f"{block}.{field} is not present in the fixture")
    event[block].pop(field)
    assert _decide(event, mandate) != "allow", (
        f"{block}.{field}={restrictive!r} stops the purchase, but deleting the field does not"
    )


@pytest.mark.parametrize(
    "mutate,label",
    [
        (lambda e: e.pop("mandate"), "the whole mandate block is gone"),
        (lambda e: e["mandate"].pop("status"), "mandate.status is gone"),
        (lambda e: e.update(mandate=None), "mandate is null"),
        (lambda e: e.update(mandate=[]), "mandate is not an object"),
        (lambda e: e["mandate"].update(status=None), "status is null"),
        (lambda e: e["mandate"].update(status=[]), "status is unhashable"),
        (lambda e: e["mandate"].update(status=12345), "status is not a string"),
        (lambda e: e["mandate"].update(status="revoked"), "status is revoked"),
    ],
)
def test_the_live_mandate_status_check_cannot_be_removed_by_deleting_it(mutate, label):
    """The specific hole, pinned. Every one of these ALLOWed at the top of this
    pass except the last two; `status=[]` additionally raised inside a set
    membership test, which is why that branch now uses a list."""
    mandate = _mandate()
    event = _event(mandate)
    mutate(event)
    assert _decide(event, mandate) != "allow", label


def test_the_sibling_status_fields_have_the_same_property():
    """`authority_status` and `card_status_at_attempt` were already correct. They
    are asserted here so the three fields are held to ONE standard in ONE place --
    the asymmetry between them is what hid the defect."""
    for field in ("authority_status", "card_status_at_attempt"):
        mandate = _mandate()
        event = _event(mandate)
        event["authorization"].pop(field)
        assert _decide(event, mandate) != "allow", field

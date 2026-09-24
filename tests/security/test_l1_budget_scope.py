"""L1: who controls the scope of the rolling budget.

This limitation sat on the list as PROTOCOL-LIMITED -- the platform scopes spend to
a run, so we cannot aggregate above it. Attacking it properly found something else
underneath and much worse, then found that the fix for THAT was itself bypassable,
and the honest end state is narrower than either.

    ATTACK 1   the agent invents session ids
               `session_id` is chosen by the AGENT and scoped the rolling window, so
               a new string reset the week's allowance.
               12 errands, 12 ids -> CHF 1,296 against a stated CHF 300 / 7 days.
               FIXED. Unknown ids now join one built-in delegation.

    ATTACK 2   the agent calls the CUSTOMER endpoint itself
               `POST /api/customer/mandates` is unauthenticated, so the caller that
               was told it may not open a budget simply opens one.
               12 self-opened delegations -> CHF 1,296 again.
               NOT FIXABLE HERE. Without authentication no endpoint-level separation
               survives a caller on the same socket, and the demo API has none.

    MITIGATION the total across delegations is now DISCLOSED, with `enforced: false`
               on the payload. An unbounded number is at least not an invisible one.

Classification: REDUCED, then EXTERNAL-DEPENDENCY-LIMITED. The remaining exposure
is exactly "anyone who can reach the customer surface can open another budget",
which is what authentication exists to solve and what this demo does not have.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from wallet_control.api import app

client = TestClient(app)

INSTRUCTION = (
    "Order our household groceries, at or below CHF 120 per order, and keep the "
    "total across any seven days at or below CHF 300. Ask me when uncertain."
)
BASKET = [
    {"item_id": "IT0018", "name": "Fresh produce order", "category": "groceries",
     "unit_price": 30, "quantity": 1, "merchant": "ME0001", "return_days": 30},
    {"item_id": "IT0020", "name": "Family breakfast supplies", "category": "groceries",
     "unit_price": 32, "quantity": 1, "merchant": "ME0001", "return_days": 30},
    {"item_id": "IT0019", "name": "Pantry restock", "category": "groceries",
     "unit_price": 46, "quantity": 1, "merchant": "ME0001", "return_days": 30},
]
CAP = 300.0


def _spend(session_ids) -> float:
    total = 0.0
    for session in session_ids:
        view = client.post("/api/agent/propose",
                           json={"session_id": session, "lines": BASKET}).json()
        if view["decision"] == "allow":
            total += 108.0
    return total


# ==================================================== attack 1, closed
def test_an_agent_cannot_reset_its_budget_by_naming_sessions():
    """The original defect. Twelve invented ids used to buy twelve budgets."""
    spent = _spend([f"l1_evade_{i}" for i in range(12)])
    assert spent <= CAP, f"CHF {spent} approved against a stated CHF {CAP}"


def test_invented_ids_land_in_the_same_delegation_as_each_other():
    """Not merely capped -- the same window. Twelve ids spend one allowance."""
    one = _spend(["l1_single"] * 12)
    many = _spend([f"l1_many_{i}" for i in range(12)])
    assert many == 0.0 or one == 0.0 or abs(one - many) <= 108.0, (many, one)


# ==================================================== attack 2, NOT closed
def test_the_customer_endpoint_is_unauthenticated_and_we_say_so():
    """The attack that defeats the fix, asserted rather than hidden. If this ever
    starts failing, authentication has arrived and L1 can be reclassified."""
    opened = []
    for index in range(12):
        session = f"l1_selfdeleg_{index}"
        response = client.post("/api/customer/mandates",
                               json={"session_id": session, "instruction": INSTRUCTION})
        assert response.status_code == 200, "opening a delegation now requires something"
        opened.append(session)

    spent = _spend(opened)
    assert spent > CAP, (
        "self-opened delegations no longer exceed one cap -- if that is deliberate, "
        "update docs/archive/FINAL_LIMITATIONS_AUDIT.md and this test")


# ==================================================== the mitigation
def test_the_total_across_delegations_is_disclosed_and_marked_unenforced():
    """An unbounded total is at least not an invisible one."""
    for index in range(3):
        session = f"l1_disclose_{index}"
        client.post("/api/customer/mandates",
                    json={"session_id": session, "instruction": INSTRUCTION})
        client.post("/api/agent/propose", json={"session_id": session, "lines": BASKET})

    body = client.get("/api/customer/delegations").json()
    assert body["enforced"] is False, "we must never imply this total is a bound"
    assert body["approved_total_chf"] >= 0
    assert body["highest_single_cap_chf"] == CAP
    assert "not enforced" in body["note"]
    assert any(d["rolling_cap_chf"] == CAP for d in body["delegations"])


def test_the_disclosure_reports_what_was_actually_approved():
    """A number nobody checks is worse than no number."""
    session = "l1_arith"
    client.post("/api/customer/mandates",
                json={"session_id": session, "instruction": INSTRUCTION})
    approved = sum(108.0 for _ in range(2)
                   if client.post("/api/agent/propose",
                                  json={"session_id": session, "lines": BASKET}
                                  ).json()["decision"] == "allow")
    body = client.get("/api/customer/delegations").json()
    mine = [d for d in body["delegations"] if d["approved_chf"] == approved]
    assert mine, f"no delegation reports CHF {approved}: {body['delegations']}"

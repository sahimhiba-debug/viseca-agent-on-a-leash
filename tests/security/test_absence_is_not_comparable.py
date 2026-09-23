"""Absence is not a value -- and it is not an ORDERING either.

THE THIRTEENTH INSTANCE of the class in docs/ABSENCE.md, and the first found in the
*thrown* shape rather than the *filled in* or *inferred* ones. It was not found by a
sweep. It fell out of making test fixtures use real catalogue item ids: two lines of
the same product stopped differing in item_id, the comparison reached the fields that
are `X | None`, and the decision path raised.

    `decision_engine._basket_key` fingerprints each line as

        (item_id, item_name, quantity,
         return_window_days | None, final_sale, stated_size | None)

    and sorted them. Python compares tuples element by element and STOPS at the first
    difference, so the None-bearing fields were only ever reached when two lines
    agreed on item_id, item_name and quantity. Then it compared None with an int.

WHAT THAT COSTS. A basket of two lines of the same product, one of which states a
return window while the other states nothing, is legal, ordinary, and composed
entirely by the untrusted party:

    POST /api/agent/propose  ->  HTTP 500, no decision at all

The official protocol gives the wallet three answers -- approve, decline, step_up --
within eight seconds. A 500 is none of them. We do NOT claim to know whether the
platform would fail open or fail closed on it; that is the platform's behaviour and
we have not measured it. What we claim is narrower and sufficient: the party the
wallet exists to constrain could stop it answering, using a basket it was entitled
to send.

Related but NOT the same as `test_empty_collection_vacuity`: there an absent
collection was read as agreement, here a present collection made absence collide
with a value. Same root, opposite surface.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.helpers import make_event, make_mandate
from wallet_control.api import app
from wallet_control.decision_engine import _basket_key, evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex, RunState

client = TestClient(app)

REAL_GROCERY = "IT0001"          # real catalogue id, category `groceries`


def _line(n: int, details: str) -> dict:
    """Two lines identical in id, name and quantity -- so the comparison is FORCED
    down to the fields that may be absent."""
    return {"line_no": n, "item_id": REAL_GROCERY, "item_name": "Fresh produce selection",
            "item_category": "groceries", "quantity": 1, "unit_price": 10.0,
            "currency": "CHF", "item_details": details}


@pytest.mark.parametrize("stated,silent", [
    ("Returns accepted within 30 days", ""),      # return_window_days: int vs None
    ("size 43", ""),                              # stated_size:        str vs None
])
def test_a_line_that_states_nothing_beside_one_that_does_is_still_decidable(stated, silent):
    """The reproduction, at the layer that broke."""
    assert _basket_key([_line(1, stated), _line(2, silent)])
    assert _basket_key([_line(1, silent), _line(2, stated)])


def test_the_engine_answers_rather_than_raising():
    mandate = make_mandate(hard_rules=[HardRule(
        field="authorization.billing_amount_chf", operator="<=", value=400,
        currency="CHF", scope="purchase")])
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})},
                                          available=True), card_id="CA_TEST")
    event = make_event(mandate=mandate, amount=20.0,
                       items=[_line(1, "Returns accepted within 30 days"), _line(2, "")])
    assert evaluate_authorization(event, mandate, state).decision in ("allow", "review", "block")


def test_the_agents_own_endpoint_does_not_500():
    """THE ASSERTION THAT MATTERS: the untrusted party cannot stop the wallet
    answering by sending a basket it was entitled to send."""
    def propose(days):
        return {"item_id": REAL_GROCERY, "name": "Fresh produce selection",
                "category": "groceries", "unit_price": 10.0, "quantity": 1,
                "merchant": "ME0001", "return_days": days}

    response = client.post("/api/agent/propose", json={
        "session_id": "absence_ordering", "lines": [propose(30), propose(None)]})
    assert response.status_code == 200, (
        f"the agent stopped the wallet answering: {response.status_code}")
    assert response.json()["decision"] in ("allow", "review", "block")


def test_the_fingerprint_still_distinguishes_silence_from_a_stated_window():
    """The repair must not fix the crash by flattening the distinction -- a line that
    states nothing is still a DIFFERENT line from one that states 30 days, or a
    re-delivery could swap them without re-examination."""
    silent = _basket_key([_line(1, "Returns accepted within 30 days"), _line(2, "")])
    stated = _basket_key([_line(1, "Returns accepted within 30 days"),
                          _line(2, "Returns accepted within 30 days")])
    assert silent != stated


def test_ordering_is_stable_regardless_of_the_order_the_lines_arrive_in():
    """It is a FINGERPRINT: the same basket must key the same however it is listed."""
    a = _basket_key([_line(1, "Returns accepted within 30 days"), _line(2, "")])
    b = _basket_key([_line(1, ""), _line(2, "Returns accepted within 30 days")])
    assert a == b


# --- a currency we cannot convert is not one we can decide about ---------------------

def test_a_currency_outside_the_fx_table_is_refused_not_raised():
    """`authorization_event.schema.json` constrains `currency` to exactly the four
    codes the FX table carries, so checking it is literally the "validate its data
    event" the official worker outline assigns to the wallet.

    Until it was checked, `money.to_chf` raised ValueError inside the decision path
    for anything else -- JPY, an empty string, XXX, and lowercase `chf` -- which is no
    answer at all, the same failure as the 1,916 erasure raises. Found by probing the
    FX surface after the erasure sweep had been cleaned to zero, which is why it is
    worth probing a surface twice from different directions."""
    from tests.helpers import make_event, make_mandate
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.state import HistoryIndex, RunState

    mandate = make_mandate()

    def decide(code):
        event = make_event(mandate=mandate, amount=20.0, currency=code)
        event["authorization"]["items"][0]["currency"] = code
        state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})},
                                              available=True), card_id="CA_TEST")
        return evaluate_authorization(event, mandate, state)

    for code in ("JPY", "XXX", "", "chf"):
        result = decide(code)
        assert result.decision == "block", (code, result.decision)
        assert "event_readable" in result.reason_codes[0], (code, result.reason_codes)

    # ...and the four the schema allows still decide. A validator that refused
    # everything would satisfy the loop above.
    for code in ("CHF", "EUR", "GBP", "USD"):
        assert decide(code).decision in ("allow", "review", "block")


def test_a_correctly_converted_foreign_purchase_is_judged_on_its_chf_value():
    """The ceiling is in CHF and the purchase may not be. 100 EUR is CHF 95 and fits
    under a CHF 100 ceiling; 100 GBP is CHF 112 and does not."""
    from tests.helpers import make_event, make_mandate
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.mandate import HardRule
    from wallet_control.state import HistoryIndex, RunState

    mandate = make_mandate(hard_rules=[HardRule(
        field="authorization.billing_amount_chf", operator="<=", value=100,
        currency="CHF", scope="purchase")])

    def decide(amount, code, chf):
        event = make_event(mandate=mandate, amount=amount, currency=code,
                           billing_amount_chf=chf, items_subtotal=amount)
        event["authorization"]["items"][0].update(currency=code, unit_price=amount)
        state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})},
                                              available=True), card_id="CA_TEST")
        return evaluate_authorization(event, mandate, state).decision

    assert decide(100.0, "EUR", 95.00) == "allow"
    assert decide(100.0, "GBP", 112.00) == "block"
    assert decide(100.0, "USD", 87.00) == "allow"

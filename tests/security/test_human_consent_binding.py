"""I31 -- what the customer answered about is what happens. Nothing else.

This invariant was the only security entry in `docs/FINAL_INVARIANTS.md` whose
evidence column cited a research campaign rather than a test. That made it the
weakest link in the strongest-looking artifact in this repository: the register is
machine-checked to cite tests that EXIST, and this one cited prose. So it is
attacked properly here and pinned.

The threat is the obvious one once stated. A step-up opens a window of real time --
the spec's default human window is 120 seconds -- during which the customer is
looking at a rendering of ONE purchase while the agent still holds the channel. If
the agent can change what that `authorization_id` means before the answer lands,
then "the customer approved it" becomes a signature on a blank cheque.

Three swaps are attacked: the amount (CHF 100 -> 900), the merchant, and the basket
contents. In each case the answer must bind to the purchase the customer was shown.

The mechanism that holds this is not in the resolution path at all -- it is the
repeat fingerprint in `decision_engine`, which covers merchant, basket and amount.
A re-delivery whose facts changed is a CONFLICT, not a replay, so it never
overwrites the stored decision; and `record_resolution` reads the stored decision
rather than any later event. Two independent mechanisms, and the test asserts the
outcome rather than either of them, so a refactor that moves the guarantee elsewhere
still passes and a refactor that loses it does not.

NOT tested here, because the spec settles it: a mandate TIGHTENED between step-up
and resolution does not apply. `technical_details.md` -- "Changes affect later runs.
An existing run keeps its original snapshot." Revocation is the in-flight brake and
has its own tests (I30).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.mandate import HardRule
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, RunState

SHOWN_MERCHANT = "ME_KNOWN"
OTHER_MERCHANT = "ME_OTHER"
SHOWN_AMOUNT = Decimal("100.0")
AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


def _mandate():
    return make_mandate(
        instruction="Order groceries.",
        hard_rules=[
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase"),
            # an unknown the customer must answer, so the purchase parks in review
            HardRule(field="order.return_window_days", operator=">=", value=14),
        ],
    )


def _state() -> RunState:
    return RunState(
        history=HistoryIndex({"CA_TEST": frozenset({SHOWN_MERCHANT, OTHER_MERCHANT})}, available=True),
        card_id="CA_TEST",
    )


def _event(mandate, *, amount=100.0, merchant=SHOWN_MERCHANT, item_name="milk"):
    event = make_event(mandate=mandate, authorization_id="AU_SHOWN", amount=amount, merchant_id=merchant, timestamp=AT)
    event["authorization"]["items"][0].update(item_details="", item_name=item_name)
    event["authorization"]["order_returnable"] = "unknown"
    return event


@pytest.mark.parametrize(
    "swap,label",
    [
        ({"amount": 900.0}, "the amount is raised from CHF 100 to CHF 900"),
        ({"merchant": OTHER_MERCHANT}, "the merchant is swapped"),
        ({"item_name": "laptop"}, "the basket contents are swapped"),
    ],
)
def test_the_answer_binds_to_the_purchase_the_customer_was_shown(swap, label):
    mandate, state = _mandate(), _state()

    shown = evaluate_authorization(_event(mandate), mandate, state)
    assert shown.decision == "review", "the fixture must actually reach the customer"

    # The agent changes what this authorization_id means while the customer decides.
    swapped = evaluate_authorization(_event(mandate, **swap), mandate, state)
    assert swapped.decision == "block", f"the swap itself must not be accepted: {label}"

    answer = resolve_authorization(
        "AU_SHOWN", "allow", state, resolved_at=datetime.now(timezone.utc), mandate=mandate
    )
    assert answer.decision == "allow"

    stored = state.get_stored_decision("AU_SHOWN")
    assert stored.billing_amount_chf == SHOWN_AMOUNT, label
    assert stored.merchant_id == SHOWN_MERCHANT, label
    # and the customer's own spending window is charged what they saw, not what was swapped in
    assert sum(amount for _, amount in state._approved_spend) == SHOWN_AMOUNT, label


def test_only_the_shown_purchase_can_actually_be_charged():
    """The ledger holding the right facts is worth nothing if `charge()` accepts the
    swapped ones. This asserts at the execution boundary, which is where money moves."""
    mandate, state = _mandate(), _state()
    evaluate_authorization(_event(mandate), mandate, state)
    evaluate_authorization(_event(mandate, amount=900.0), mandate, state)
    resolve_authorization("AU_SHOWN", "allow", state, resolved_at=datetime.now(timezone.utc), mandate=mandate)

    psp = MockPSP(state)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="C1", authorization_id="AU_SHOWN", amount_chf=Decimal("900"), merchant_id=SHOWN_MERCHANT)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="C2", authorization_id="AU_SHOWN", amount_chf=SHOWN_AMOUNT, merchant_id=OTHER_MERCHANT)

    receipt = psp.charge(
        charge_id="C3", authorization_id="AU_SHOWN", amount_chf=SHOWN_AMOUNT, merchant_id=SHOWN_MERCHANT
    )
    assert receipt is not None

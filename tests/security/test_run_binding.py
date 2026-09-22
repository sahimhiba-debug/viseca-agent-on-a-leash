"""V5: the engine never checked that the event it was deciding actually belonged
to the run it was deciding for.

`authorization.card_id` is what the merchant-familiarity lookup is keyed on, and
it was taken straight from the event and never compared against the card the run
is bound to. An event carrying a different card's identity therefore borrowed
THAT card's purchase history -- so a merchant this card had never used could be
made to look familiar. `authorization.mandate_id` was likewise unchecked, so an
event belonging to a different mandate would be evaluated under this run's rules.

Both are confused-deputy vectors: the question "whose authority is this?" was
being answered by the event itself.
"""

from __future__ import annotations

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex, RunState

OUR_CARD = "CA_TEST"
OTHER_CARD = "CA_SOMEONE_ELSE"
FAMILIAR_TO_OTHER_CARD = "ME_ONLY_THE_OTHER_CARD_KNOWS"


def _history():
    return HistoryIndex(
        {OUR_CARD: frozenset({"ME_TEST_0001"}), OTHER_CARD: frozenset({FAMILIAR_TO_OTHER_CARD})},
        available=True,
    )


def test_an_event_for_another_card_cannot_borrow_that_cards_history():
    """The attack: the run is bound to CA_TEST, which has never used this merchant.
    The event claims to be CA_SOMEONE_ELSE, for whom the merchant IS familiar."""
    mandate = make_mandate(hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")])
    state = RunState(history=_history(), card_id=OUR_CARD)

    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id=FAMILIAR_TO_OTHER_CARD, card_id=OTHER_CARD)
    result = evaluate_authorization(event, mandate, state)

    assert result.decision == "block"
    assert any("card_id" in code for code in result.reason_codes)
    assert result.payment_authority is None


def test_an_event_for_another_mandate_is_not_evaluated_under_this_runs_rules():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])
    state = RunState(history=_history(), card_id=OUR_CARD)

    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id="ME_TEST_0001")
    event["authorization"]["mandate_id"] = "TM_A_COMPLETELY_DIFFERENT_MANDATE"
    result = evaluate_authorization(event, mandate, state)

    assert result.decision == "block"
    assert any("mandate_id" in code for code in result.reason_codes)


def test_a_matching_event_is_unaffected():
    """What keeps the official replay at 18/3/24: every official event's card_id
    matches its scenario authority's card (verified: 0 mismatches across all 45)."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])
    state = RunState(history=_history(), card_id=OUR_CARD)
    result = evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id="ME_TEST_0001"), mandate, state)
    assert result.decision == "allow"


@pytest.mark.parametrize("bad", ["", None, "ca_test", " CA_TEST", "CA_TEST​"])
def test_near_miss_card_identities_are_not_accepted_as_equal(bad):
    """Identity is compared exactly. A case variant, a padded value or one carrying
    an invisible character is a different string and must not pass as this card --
    this is the canonicalization half of the confused-deputy question."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])
    state = RunState(history=_history(), card_id=OUR_CARD)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id="ME_TEST_0001")
    event["authorization"]["card_id"] = bad
    assert evaluate_authorization(event, mandate, state).decision == "block"


def test_the_binding_failure_is_wallet_safety_not_customer_policy():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])
    state = RunState(history=_history(), card_id=OUR_CARD)
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id="ME_TEST_0001", card_id=OTHER_CARD)
    result = evaluate_authorization(event, mandate, state)
    binding = [e for e in result.rule_evaluations if "_binding" in e.rule.field]
    assert binding and all(e.source == "safety" for e in binding)

"""The same property, on data the organisers did not provide.

THE WORRY THIS ANSWERS. Every property measured in this repository -- "saying less
never buys more under `decline`", "the wallet always answers", the split between
requirement and flag facts -- was measured over the 45 official events. Five
scenarios, one catalogue, one card, written by the same people who designed the
scenarios they illustrate. A conclusion drawn from a corpus that small is a
conclusion about that corpus until something says otherwise.

So: generate events the pack does not contain -- merchants and item ids that are in
no reference data, four currencies, baskets mixing categories, seller text ranging
from an injection to nothing at all, amounts spanning three orders of magnitude, and
mandates built by SAMPLING rule fields rather than by compiling a sentence -- and run
the same sweep. If the boundary is a property of the ENGINE it holds here too.

IT DID NOT, AND THAT IS WHY THIS FILE EXISTS. The first run found seven escapes under
`decline`, the setting where nothing is supposed to be gained by silence. Two were
real and both were bypasses created by earlier fixes in this same session:

    mandate: CHF <= 100, no category rule
    a line whose id the catalogue lists as groceries, stated as `clothing`   block
    the same line with no item id at all                                     ALLOW

The catalogue check's proportionality gate guarded only the `unknown` branch, so
deleting the id moved a purchase from the branch that refutes to the branch that is
ignored. The merchant-record check, written in the same shape a few hours later, had
the identical hole. Saying less beat saying something false, at the two checks that
exist to stop exactly that.

THE FIX WENT THE OPPOSITE WAY TO THE OBVIOUS ONE. Rather than blocking more, the
refutation is withheld where it was never relevant: a customer who did not constrain
the kind of goods or the kind of shop has not asked the wallet to have an opinion
about either, and the purchase is permitted under both descriptions -- so refusing
one and allowing the other protected nobody while giving the agent a reason to say
less.

AND THE CORPUS ITSELF HAD TO BE ATTACKED FIRST. Sampling every field independently
produced 120 baselines that were ALL `block` -- invented merchants and CHF 9,999
baskets fail something before any erasure is applied. A corpus whose baselines are
all one verdict cannot observe an erasure moving a decision away from `allow`, and
would have reported a confident zero from a benchmark that could not have produced a
one. Half the cases now build the basket first and the rules to fit it.
"""

from __future__ import annotations

import pytest

from research.synthetic_corpus import sweep
from wallet_control.mandate import UncertaintyPolicy


@pytest.fixture(scope="module")
def declined():
    return sweep(policy=UncertaintyPolicy.DECLINE)


def test_the_corpus_is_large_and_live(declined):
    """Two ways this could pass for the wrong reason, both excluded here: too few
    erasures to find anything, and a corpus so hostile that every baseline is already
    the strictest verdict."""
    assert declined["erasures"] > 20000, declined["erasures"]
    assert declined["stricter"] > 500, (
        f"only {declined['stricter']} erasures made anything stricter; a corpus whose "
        f"decisions never move cannot show that one of them moved the wrong way")
    assert declined["raised"] == [], declined["raised"][:3]


def test_saying_less_never_buys_more_on_data_we_generated(declined):
    """THE ASSERTION. Requirement-polarity only: removing a red FLAG necessarily helps
    the proposer under every policy, and demanding otherwise would be demanding that
    not attacking be punished."""
    escapes = [v for v in declined["violations"] if v[5] == "requirement"]
    assert escapes == [], escapes[:5]


def test_the_two_bypasses_this_corpus_found_stay_closed():
    """Named, because a general sweep reporting zero is a weaker guard than a
    reproduction of the specific thing that was wrong."""
    from tests.helpers import make_event, make_mandate
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.mandate import HardRule
    from wallet_control.state import HistoryIndex, RunState

    amount_only = [HardRule(field="authorization.billing_amount_chf", operator="<=",
                            value=500, currency="CHF", scope="purchase")]

    def decide(item_id, stated_category, merchant, merchant_category):
        mandate = make_mandate(hard_rules=list(amount_only))
        event = make_event(mandate=mandate, amount=100.0, merchant_id=merchant,
                           merchant_category=merchant_category,
                           items=[{"line_no": 1, "item_id": item_id, "item_name": "x",
                                   "item_category": stated_category, "quantity": 1,
                                   "unit_price": 100.0, "currency": "CHF",
                                   "item_details": ""}])
        state = RunState(history=HistoryIndex({"CA_TEST": frozenset({merchant})},
                                              available=True), card_id="CA_TEST")
        return evaluate_authorization(event, mandate, state).decision

    # A grocery item described as clothing, with no category rule in the mandate.
    # Whatever the wallet does, it must do the SAME with and without the id.
    lied = decide("IT0001", "clothing", "ME_TEST_0001", "groceries")
    silent = decide("", "clothing", "ME_TEST_0001", "groceries")
    assert lied == silent, (
        f"stating a false category gave {lied} and stating no id gave {silent}; "
        f"saying less must not buy more")

    # ...and the same for the shop's own kind.
    lied_shop = decide("IT0001", "groceries", "ME0006", "groceries")
    silent_shop = decide("IT0001", "groceries", "ME_UNKNOWN_SHOP", "groceries")
    assert lied_shop == silent_shop, (lied_shop, silent_shop)


def test_the_protection_still_bites_where_the_customer_asked_for_it():
    """The fix withholds a refutation where it was irrelevant. It must not withhold
    it where the customer constrained the kind of goods -- otherwise closing the
    bypass would have removed the check."""
    from tests.helpers import make_event, make_mandate
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.mandate import HardRule
    from wallet_control.state import HistoryIndex, RunState

    rules = [HardRule(field="item.category", operator="in", value=["groceries"])]

    def decide(item_id, stated):
        mandate = make_mandate(hard_rules=list(rules))
        event = make_event(mandate=mandate, amount=100.0,
                           items=[{"line_no": 1, "item_id": item_id,
                                   "item_name": "Digital gift voucher",
                                   "item_category": stated, "quantity": 1,
                                   "unit_price": 100.0, "currency": "CHF",
                                   "item_details": ""}])
        state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})},
                                              available=True), card_id="CA_TEST")
        return evaluate_authorization(event, mandate, state).decision

    assert decide("IT0005", "gift_card") == "block"      # honest, and refused
    assert decide("IT0005", "groceries") == "block"      # relabelled, and refuted
    assert decide("IT9999", "groceries") == "review"     # unidentifiable, so unknown
    assert decide("", "groceries") == "review"

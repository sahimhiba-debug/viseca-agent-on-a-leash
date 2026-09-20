"""The agent's TOOL is untrusted input, and its BELIEFS are paid for with refusals.

Giving the agent a tool and a memory added two attack surfaces that the earlier
planner-seam tests could not reach, because it had neither. The planner seam asks
"can a bad planner obtain authority" (it cannot). These ask the two new questions:

  * can a hostile SHOP make the agent misbehave, and
  * can a crafted sequence of REFUSALS make it believe something useful to an
    attacker -- in particular, can it ever come to believe it may spend MORE?

The answer to the second has to be no by construction, not by testing, and the
construction is that every belief is monotone in the direction of caution.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from research.shopping_agent import (
    Beliefs, CatalogueShop, Line, Mission, Offer, Planner, Shop, best_basket, replan, shop,
)

GROC = "groceries"
M = Mission("Order groceries", GROC, target_lines=3)


class _Static(Shop):
    def __init__(self, offers): self._offers = offers
    def search(self, category=None):
        return [o for o in self._offers if category is None or o.category == category]


def _o(i, price, merchant="ME0001", cat=GROC, ret=30):
    return Offer(i, f"item {i}", cat, Decimal(str(price)), merchant, ret)


# =============================================================== the shop is hostile
@pytest.mark.parametrize(
    "label,offers",
    [
        ("a refund priced as a purchase", [_o("BAD", "-1000"), _o("OK", 30)]),
        ("a free item", [_o("FREE", 0), _o("OK", 30)]),
        ("an item with no id", [Offer("", "x", GROC, Decimal("5"), "ME0001", 30), _o("OK", 30)]),
        ("goods from another category", [_o("J", 1, cat="jewellery"), _o("OK", 30)]),
    ],
)
def test_the_agent_refuses_implausible_offers(label, offers):
    """A price of CHF -1000 was enough to make the search propose it, because the
    objective prefers spending less and nothing spends less than a refund. The wallet
    blocks any non-positive amount so no money could move -- but the agent would have
    spent one of the customer's four attempts on it, and a catalogue full of them
    would have spent all four."""
    found = best_basket(_Static(offers), M, Beliefs())
    assert found is not None, label
    assert [o.item_id for o in found[0]] == ["OK"], f"{label}: agent took the bad offer"


def test_a_shop_large_enough_to_stall_the_agent_does_not():
    """The search is linear in merchants, so a catalogue listing enough of them is a
    denial-of-service against the agent -- 1,000 merchants took 1.6s before the bound
    went in, against a wallet deadline of 8s."""
    offers = [_o(f"I{j}", 10 + j, f"ME{k:05d}") for k in range(2000) for j in range(20)]
    start = time.perf_counter()
    assert best_basket(_Static(offers), M, Beliefs()) is not None
    assert time.perf_counter() - start < 2.0, "the agent can be stalled by a large catalogue"


def test_the_search_is_reproducible_not_dictionary_ordered():
    """Ties break on item ids. A search whose answer depends on the order a catalogue
    happened to return is not reproducible, and reproducibility is the property this
    whole system exists to keep."""
    offers = [_o("b", 10), _o("a", 10), _o("c", 10), _o("d", 10)]
    first = best_basket(_Static(offers), M, Beliefs())
    for _ in range(20):
        again = best_basket(_Static(list(reversed(offers))), M, Beliefs())
        assert [o.item_id for o in again[0]] == [o.item_id for o in first[0]]


def test_a_shop_that_changes_every_call_still_terminates():
    """Non-stationary environments are allowed to make the agent fail. They are not
    allowed to make it loop: every attempt is a real decision on a real card."""
    counter = {"n": 0}

    class Shifting(Shop):
        def search(self, category=None):
            counter["n"] += 1
            return [_o(f"X{counter['n']}", 10 + counter["n"])]

    seen = []

    def propose(lines, revision, merchant):
        seen.append(revision)
        return {"authorization_id": f"A{revision}", "decision": "block",
                "blocked_by": ["amount"], "awaiting_customer": False}

    episode = shop(M, propose, max_revisions=4, shop_tool=Shifting())
    assert episode.outcome in {"asked_customer", "gave_up"}
    assert len(seen) <= 5, f"{len(seen)} proposals against a max of 5"


# ========================================================= the beliefs are monotone
def test_the_believed_ceiling_only_ever_falls():
    """`ceiling` is not the customer's limit. It is "strictly less than a total I
    already tried", which is all a refusal can honestly say. If a sequence of
    refusals could ever raise it, the agent would be walking UP toward a limit it is
    meant to converge on from above, and a hostile shop could drive that walk."""
    b = Beliefs()
    history = []
    for total in (200, 50, 300, 10, 500, 30):
        b.learn([Line("i", "i", GROC, Decimal(str(total)))], "ME0001", ["amount"])
        history.append(b.ceiling)
    assert history == sorted(history, reverse=True), history
    assert b.ceiling == Decimal("10")


def test_a_ruled_out_shop_is_never_reinstated():
    b = Beliefs()
    b.learn([Line("i", "i", GROC, Decimal("10"))], "ME0777", ["merchant"])
    for _ in range(10):
        b.learn([Line("j", "j", GROC, Decimal("5"))], "ME0001", ["amount"])
        assert "ME0777" in b.ruled_out_merchants


def test_the_agent_never_re_proposes_a_basket_it_already_tried():
    """Re-proposing is how an agent turns a bounded number of refusals into an
    unbounded number, and every one of them is a real decision on a real card."""
    offers = [_o("a", 30), _o("b", 40), _o("c", 50)]
    b, tool, seen = Beliefs(), _Static(offers), []
    lines = [o.line() for o in best_basket(tool, M, b)[0]]
    for _ in range(6):
        seen.append(frozenset(l.item_id for l in lines))
        step = replan(lines, ["amount"], M, 0, tool, b, "ME0001")
        if isinstance(step, str):
            break
        lines = step[0]
    assert len(seen) == len(set(seen)), f"repeated a basket: {seen}"


# ============================================ a refusal about the AGENT is not shoppable
@pytest.mark.parametrize("flag", ["session", "duplicate", "other"])
def test_a_refusal_about_the_agents_conduct_halts_even_when_a_basket_is_available(flag):
    """The search found this regression before this test did: told "this looks like a
    duplicate", the agent happily came back with a different basket. That is an agent
    answering "you look like a runaway" by rephrasing itself until the wallet stops
    noticing. A constraint on the PURCHASE is shoppable; a constraint on the AGENT is
    not, and the presence of a perfectly good alternative must not change that."""
    tool = _Static([_o("a", 10), _o("b", 20), _o("c", 30)])
    assert best_basket(tool, M, Beliefs()) is not None, "a valid alternative must exist"
    step = replan([Line("a", "a", GROC, Decimal("10"))], [flag], M, 0, tool, Beliefs(), "ME0001")
    assert isinstance(step, str), f"{flag}: agent tried to shop its way out"
    assert "customer" in step


def test_a_mixed_refusal_still_halts():
    """`amount` is shoppable and `session` is not. The presence of something the agent
    CAN act on must not license acting on the part it cannot."""
    tool = _Static([_o("a", 10), _o("b", 20)])
    step = replan([Line("a", "a", GROC, Decimal("99"))], ["amount", "session"], M, 0,
                  tool, Beliefs(), "ME0001")
    assert isinstance(step, str), step


# ==================================================== the basket describes the purchase
def test_the_agent_only_proposes_baskets_one_shop_can_actually_supply():
    """The old agent chose items from a catalogue and a merchant from the mission and
    never checked them against each other. Re-measured honestly it reported four
    successes on the benchmark while holding goods from a shop the customer had
    excluded -- the wallet approving a truthful evaluation of an untruthful proposal.

    The wallet cannot catch this: nothing in the API lets it verify that a merchant
    stocks an item. It is an agent-side integrity property and we claim it as one.
    """
    tool = _Static([_o("x", 10, "ME0001"), _o("y", 12, "ME0002"), _o("z", 14, "ME0002")])
    offers, merchant = best_basket(tool, M, Beliefs())
    assert {o.merchant for o in offers} == {merchant}, "basket spans shops"
    assert tool.merchant_for([o.line() for o in offers]) == merchant


def test_the_shipped_shop_tool_agrees_with_itself():
    """`merchant_for` must answer for baskets `search` produced, or the loop would
    send real proposals to a shop that does not stock them."""
    tool = CatalogueShop()
    offers, merchant = best_basket(tool, Mission("m", GROC, target_lines=3), Beliefs())
    assert tool.merchant_for([o.line() for o in offers]) == merchant
    assert all(tool.available(o.item_id) for o in offers)


# ==================================================== what the search costs in privacy
def test_searching_spends_FEWER_refusals_than_repairing_did():
    """A faster planner is a privacy question, not just an efficiency one.

    Every refusal is one bit of oracle signal about a policy the agent was never
    told. The old repair ladder aimed high on purpose and walked down, spending six
    refusals to reach a basket the search finds in one -- and it did not even finish
    inside the shipped four-revision budget, so in practice it handed a half-mapped
    policy back to the customer.

    Measured against a hidden ceiling of CHF 137 in a shop with 399 price points:
    search settles at CHF 7.50 on its FIRST proposal. It does not approach the
    boundary, because the objective minimises price within a coverage tier -- it is
    walking away from the limit, not toward it. That is the property; "it converges
    quickly" would be the opposite of what we want.
    """
    offers = [_o(f"I{i:03d}", Decimal(i) / 2) for i in range(1, 400)]
    tool, beliefs = _Static(offers), Beliefs()
    attempts = []

    def propose(lines, revision, merchant):
        total = sum(l.total for l in lines)
        attempts.append(total)
        return {"authorization_id": f"A{revision}",
                "decision": "allow" if total <= Decimal("137") else "block",
                "blocked_by": [] if total <= Decimal("137") else ["amount"],
                "awaiting_customer": False}

    episode = shop(Mission("Order groceries", GROC, target_lines=5), propose, shop_tool=tool)
    assert episode.outcome == "approved"
    assert len(attempts) == 1, f"spent {len(attempts)} refusals on a policy it was never told"
    assert attempts[-1] < Decimal("137") / 2, (
        f"settled at CHF {attempts[-1]}, uncomfortably near a ceiling it should not know"
    )

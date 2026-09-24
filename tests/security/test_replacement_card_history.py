"""A replacement card inherits the shops its predecessor was used at.

"From a shop I have used before" is about the customer. Keyed by card alone, a
card issued to replace an expired or blocked one starts with no history, so every
shop the customer has used reads as new. On the organisers' 144k-row history pack
that made 30.4% of agent purchases on replacement cards look like a new shop,
against 5.9% by customer; inheriting the replaced card brings it to 8.4%
(`scripts/analyse_extra_history.py`).

Only INACTIVE cards on the same account are inherited. A second active card is a
separate card -- the official pack has ten accounts with two cards -- and widening
to it would move the official replay (AU0044 turns from BLOCK to ALLOW when a
customer's other active card is counted). That is a different question and is not
answered here.
"""

from __future__ import annotations

import csv

from wallet_control.state import HistoryIndex, _replaced_cards

OLD, NEW, SIBLING = "CA_OLD", "CA_NEW", "CA_SIBLING"


def _index(**kwargs):
    return HistoryIndex({OLD: frozenset({"ME_USUAL"}), SIBLING: frozenset({"ME_SIBLING"})},
                        available=True, predecessors_by_card={NEW: frozenset({OLD})}, **kwargs)


def test_a_replacement_card_knows_the_shops_of_the_card_it_replaced():
    index = _index()
    assert index.is_familiar(NEW, "ME_USUAL") is True
    assert "the card this one replaced" in index.familiarity_basis(NEW, "ME_USUAL")


def test_it_does_not_invent_shops():
    assert _index().is_familiar(NEW, "ME_NEVER") is False


def test_it_does_not_borrow_from_a_card_it_did_not_replace():
    assert _index().is_familiar(NEW, "ME_SIBLING") is False


def test_the_agents_history_on_the_old_card_stays_the_agents():
    index = _index(agent_only_merchants_by_card={OLD: frozenset({"ME_AGENT"})})
    assert index.is_familiar(NEW, "ME_AGENT") is None


def test_a_card_with_no_history_and_no_predecessor_is_still_unknown():
    assert _index().is_familiar("CA_UNSEEN", "ME_USUAL") is None


def test_only_inactive_cards_on_the_same_account_are_predecessors(tmp_path):
    rows = [("CA1", "AC1", "expired"), ("CA2", "AC1", "active"), ("CA3", "AC1", "active"),
            ("CA4", "AC2", "blocked"), ("CA5", "AC3", "active")]
    path = tmp_path / "cards.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["card_id", "account_id", "status"])
        w.writerows(rows)
    assert _replaced_cards(path) == {"CA2": frozenset({"CA1"}), "CA3": frozenset({"CA1"})}

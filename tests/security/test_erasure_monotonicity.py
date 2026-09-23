"""Saying less must never buy more -- stated as a property, attacked exhaustively.

THE PROPERTY

    For every authorization event E and every field f reachable in it,

        permissiveness( decide(E \\ f) )  <=  permissiveness( decide(E) )

    over `block < review < allow`, where `E \\ f` is E with f ERASED -- set to null,
    and separately removed entirely, because `d.get(k)` cannot tell those apart and
    `k in d` can.

WHY A PROPERTY AND NOT MORE EXAMPLES. Three separate findings in this repository
turned out to be the same shape: an item id the catalogue had never seen was waved
through while a real id carrying a false category was refused (ABSENCE #13); a
seller who publishes nothing beats one who publishes bad terms (the silence
channel); an empty ledger after a restart read as "nothing was spent" (ABSENCE #15).
Each was found by hand. The question they raise is not "are those fixed" but "how
many more are there", and only enumerating the field space answers it.

WHAT THE SWEEP FOUND, AND THE DISTINCTION THAT EXPLAINS IT

8,124 erasures over the 45 official events produce 7 violations, and they are not
one phenomenon but two:

    REQUIREMENT facts -- evidence FOR authority (a return window, a category, a
        ceiling). Erasing turns a `fail` into an `unknown`: the seller who states a
        2-day return window is refused, the seller who states nothing is not. This
        is a real gap.

    FLAG facts -- evidence AGAINST, raised by the wallet on its own (text written at
        the machine, a session that looks wrong). Erasing removes the flag, which is
        not a defect: you cannot be flagged for text you did not write, and not
        attacking is not an attack.

One CHANNEL carries both, which is why the distinction is invisible in a field list:
`item_details` holds the return window and the injection, and a seller who deletes
it erases one of each. So a violation is classified by WHICH REASON DISAPPEARED.

THE RESULT, WHICH IS ABOUT THE MANDATE FORMAT AND NOT ABOUT THIS WALLET

    uncertainty_policy = decline   0 requirement-polarity violations
    uncertainty_policy = ask       5
    uncertainty_policy = approve   5

There is exactly one setting in which saying less provably never buys more, and it
is the strictest one. That is not a bug we can fix inside the engine: `unknown` is
the honest outcome when a fact is missing, and what happens to an unknown is the
customer's own single dial -- one answer for a question that is really per-rule. A
customer cannot say "ask me about unknowns, but never let silence rescue a refusal".

NOT CLAIMED: that this is a proof about all events. It is exhaustive over the
official corpus and the field paths those events contain, which is a statement about
THIS corpus, not a theorem about the schema.
"""

from __future__ import annotations

import pytest

from research.erasure import per_policy, sweep
from wallet_control.provenance import FACTS, FLAG, REQUIREMENT


def _requirement_violations(findings):
    """Violations where the PURCHASE is unchanged and a requirement was erased."""
    return [f for f in findings if not f[6] and f[7] == "requirement"]


@pytest.fixture(scope="module")
def default_sweep():
    return sweep()


def test_the_sweep_is_actually_exhaustive(default_sweep):
    """If the enumeration silently stopped finding paths, everything below would pass
    for the wrong reason."""
    _, _, weakened, total = default_sweep
    assert total > 8000, f"only {total} erasures applied"
    assert weakened > 0, "no erasure made anything stricter -- the sweep is inert"


def test_under_decline_saying_less_never_buys_more():
    """THE ASSERTION THAT MATTERS. Over every field of every official event, with the
    strictest answer to "what if I cannot tell?", no erasure of a requirement fact
    made the wallet more permissive."""
    counts = per_policy()
    assert counts["decline"] == 0, (
        "an erasure bought the proposer something even under `decline`: "
        f"{counts}")


def test_the_looser_settings_pay_for_it_and_we_say_by_how_much():
    """The cost is disclosed rather than smoothed over. If these ever drop to zero on
    their own, the silence channel has been closed somewhere and this file is the
    wrong place to find that out from -- so it is asserted, not assumed."""
    counts = per_policy()
    assert counts["ask"] == 4 and counts["approve"] == 4, counts


def test_flag_violations_exist_and_are_not_treated_as_defects(default_sweep):
    """The other half of the distinction. Erasing a red flag necessarily helps the
    proposer under EVERY policy, and a sweep that called that a violation would be
    demanding that not attacking be punished."""
    findings, _, _, _ = default_sweep
    flags = [f for f in findings if not f[6] and f[7] == "flag"]
    assert flags, "the injected-listing scenario must still show up as flag-driven"
    assert all(f[2].endswith("item_details") for f in flags), flags


def test_the_wallet_always_answers(default_sweep):
    """A RAISE IS NOT ONE OF THE THREE ANSWERS. The official worker outline makes
    validating the event ours ("Read the envelope's run ID and validate its data
    event"), and every field in `authorization_event.schema.json` is required -- so a
    missing one used to be dereferenced straight into a KeyError or TypeError inside
    the decision path, before any decision existed.

    Measured here when this sweep was first written: 1,916 of 8,124 single-field
    erasures made the engine raise. Three distinct root causes came out of chasing
    them to zero -- an absent field dereferenced unconditionally, `sorted()` asked to
    compare None with a string in two separate places, and `all([])` being vacuously
    true so `min([])` ran on an empty basket. The last two are the same class as
    ABSENCE #14 and `test_empty_collection_vacuity` respectively, in places neither
    of those fixes reached."""
    _, raised, _, _ = default_sweep
    assert raised == [], (
        f"{len(raised)} erasures left the wallet with no answer at all; "
        f"first few: {raised[:5]}")


def test_every_declared_fact_has_a_polarity_and_the_flags_are_the_safety_ones():
    """Anti-rot. A new fact declared without thinking about what its SILENCE means is
    exactly how the three findings above happened."""
    assert all(f.polarity in (REQUIREMENT, FLAG) for f in FACTS)
    flags = {f.field for f in FACTS if f.polarity == FLAG}
    assert flags == {"session.integrity_risk"}, (
        "a fact whose absence is the ordinary case belongs in the FLAG class; "
        f"currently {flags}")

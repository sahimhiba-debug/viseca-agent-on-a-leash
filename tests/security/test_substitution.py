"""Can any field be RESTATED to buy the same purchase a better answer?

Erasure asks what happens when a fact is removed. This asks the other half, and it
exists because of HOW the two previous findings of this shape were found.

    `authorization.timestamp` -- the clock every rolling ceiling is measured in --
    had no declared provenance until it turned up BY ACCIDENT, while chasing an
    unrelated bug in restart recovery.

    `merchant.category` was declared BOUND, "loaded from reference data, never from
    the proposal", while the engine read it straight out of the event. A `transport`
    merchant relabelled `groceries` was ALLOWED on a groceries-only mandate.

Finding things by luck is not a method. Worse, the probe that was supposed to catch
the second one AGREED WITH IT: it attacked the fact by swapping the merchant id,
which changes the shop and therefore the purchase, and never relabelled the category
of the same shop. A test written from the same misunderstanding as the code confirms
the code.

THE METHOD. Restate every field of every official event with a value that field
really takes ELSEWHERE in the pack. Nothing invented, nothing malformed: every
variant is a shape the platform itself produced, so a result cannot be dismissed as
"you sent nonsense", and no TypeError can masquerade as a finding.

THE CRITERION is `provenance.py`'s, including the fourth clause that used to be
missing from the code: a restatement is a FORGERY only if it changes the decision
while leaving the purchase unchanged -- same goods, same shop, same price, SAME
MOMENT. Raising the amount and being refused is not a finding.

WHAT IS ASSERTED. Not that no field can be restated -- three of them can, and that
is the disclosed limit this repository puts on the customer's screen. What is
asserted is that the table ACCOUNTS FOR ALL OF THEM: every forgery this sweep can
find is a fact already declared `advisory` (nothing can contradict it) or a flag
(whose absence is the ordinary case). An unexplained one is a decision input nobody
has classified, which is precisely the state both findings above were in.
"""

from __future__ import annotations

import pytest

from research.substitution import sweep, unexplained
from wallet_control.provenance import ADVISORY, BY_FIELD


@pytest.fixture(scope="module")
def swept():
    return sweep()


def test_the_sweep_is_actually_doing_something(swept):
    """If the vocabulary collapsed, everything below would pass vacuously."""
    findings, _, total = swept
    assert total > 5000, f"only {total} restatements applied"
    assert findings, "no substitution changed any decision -- the sweep is inert"


def test_the_wallet_always_answers(swept):
    """A restatement is a legal event. It may be refused; it may not crash."""
    _, raised, _ = swept
    assert raised == [], raised[:5]


def test_no_forgery_is_unexplained(swept):
    """THE ASSERTION THAT MATTERS. Every field that buys the same purchase a better
    answer must map to a fact this repository has already declared advisory, or to a
    flag. Anything else decides authority with no declaration -- the state the clock
    and the merchant record were both in when they were missed."""
    findings, _, _ = swept
    gaps = unexplained(findings)
    assert gaps == [], (
        "a field bought the same purchase a better answer and no declared fact "
        f"accounts for it: {gaps}")


def test_the_forgeable_fields_are_the_ones_the_seller_writes(swept):
    """And they are the three already disclosed on the Delegate tab, reached here by
    a completely different route than `forgeable_facts.py` takes."""
    findings, _, _ = swept
    leaves = {f[2].rsplit(".", 1)[-1] for f in findings if not f[5]}
    assert leaves <= {"item_details", "item_name", "order_returnable"}, leaves
    assert BY_FIELD["order.return_window_days"].binding == ADVISORY
    assert BY_FIELD["item.name_contains"].binding == ADVISORY


def test_relabelling_a_shop_no_longer_works(swept):
    """The regression that produced this file. `merchant_category` must never appear
    among the forgeries again."""
    findings, _, _ = swept
    offenders = [f for f in findings if not f[5] and f[2].endswith("merchant_category")]
    assert offenders == [], offenders


def test_two_useless_changes_do_not_combine_into_a_useful_one_under_decline():
    """COMPOSITION, which no single-field sweep can see.

    Every other sweep here varies ONE field. That is structurally blind to the case
    where two restatements, each individually refused, are allowed together -- and
    the official pack contains one:

        SCEN0002 AU0014, a mandate requiring a return window

        order_returnable = 'true'          alone   still blocked
        item_details with no window stated alone   still blocked
        BOTH                                       review

    The return window has TWO independent sources -- the order-level flag and the
    seller's text -- and each one alone still refutes it, so silencing either is
    useless. Silence both and the fact becomes `unknown`, which is more permissive
    than refuted.

    THE LESSON IS ABOUT DEFENCE IN DEPTH. Two sources for one fact look like
    redundancy and are not: they only help while the attacker can reach just one of
    them. Each source individually masks the value of silencing the other, which is
    exactly why this needed a pairwise sweep to find.

    AND IT IS THE SAME BOUNDARY AS EVERYWHERE ELSE. Measured over the pack:

        uncertainty_policy = decline   4,068 pairs   0 escapes
        uncertainty_policy = ask       3,972 pairs   6
        uncertainty_policy = approve   3,725 pairs   6

    So the property this repository can actually claim is one sentence covering all
    three sweeps: under `decline`, no erasure, no restatement, and no pair of
    individually-useless changes ever buys the same purchase a better answer.
    """
    from research.substitution import pairs
    from wallet_control.mandate import UncertaintyPolicy

    escapes, considered = pairs(policy=UncertaintyPolicy.DECLINE)
    assert considered > 3000, f"only {considered} pairs considered"
    assert escapes == [], escapes[:3]


def test_the_composition_gap_is_real_under_ask_and_is_disclosed():
    """The other side of it, asserted so that it cannot quietly disappear or quietly
    grow. If this ever reaches zero on its own, something closed the silence channel
    and this file should not be where that is discovered."""
    from research.substitution import pairs
    from wallet_control.mandate import UncertaintyPolicy

    escapes, _ = pairs(policy=UncertaintyPolicy.ASK)
    assert len(escapes) == 6, escapes
    assert all(e[2] == "block" and e[3] == "review" for e in escapes), escapes
    fields = {e[4].rsplit(".", 1)[-1] for e in escapes} | {e[6].rsplit(".", 1)[-1] for e in escapes}
    assert fields == {"order_returnable", "item_details"}, fields

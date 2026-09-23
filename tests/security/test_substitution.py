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

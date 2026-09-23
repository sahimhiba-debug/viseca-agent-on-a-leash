"""A rule is worth only as much as the provenance of the fact it reads.

The Delegate tab shows a customer their compiled rules, each looking equally solid:

    Purchases must be for the requested kind of item (groceries).
    The order must be returnable within at least 14 days.
    Purchases must be from a shop you have paid before.

They are not equally solid, and this file is where that stops being an opinion.
Measured by putting a violating purchase through the real engine, then talking it
into compliance **without changing the goods, the shop, the price or the moment**:

    bound      merchant.familiar, session.integrity_risk,
               authorization.billing_amount_chf, authorization.timestamp
    refutable  merchant.category, item.category, item.unrequested_present
    advisory   item.name_contains, item.size, order.return_window_days

The customer wrote three kinds of requirement and got one guarantee, one refutation
and one promise. Nobody told them which was which.

TWO OF THESE ROWS ARE CORRECTIONS, AND BOTH CORRECTIONS CAME FROM OUTSIDE THIS FILE.

`authorization.timestamp` was in no row at all: the table was built from the fields
`rules.py` evaluates, and no rule names the clock -- though every rolling ceiling is
measured in it.

`merchant.category` sat under `bound`, on a declaration that said "loaded from
reference data, never from the proposal". The event BUILDERS do that; the engine read
it out of the event. THE PROBE HERE AGREED, because it attacked the fact by swapping
the merchant ID -- which changes the shop, and therefore the purchase -- and never
relabelled the category of the same shop. A test written from the same
misunderstanding as the code confirms the code, and no amount of running it helps.

Both were found by sweeps that do not know what the table says:
`research/substitution.py` restates every field of every official event with a value
that field really takes elsewhere, and reports anything that buys a better answer.

THE CRITERION IS WHAT MAKES THIS HONEST. `billing_amount_chf` is also written by the
proposing party, and writing a smaller number *does* turn a BLOCK into an ALLOW --
for a smaller charge, because the number it names is the number that is taken. The
purchase changed, so it is not a forgery. Writing a fact is not forging it; forging
it is getting **the same thing** on better terms.

`provenance.py` declares the classes. This attacks every one of them.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.forgeable_facts import PROBES, measure  # noqa: E402
from wallet_control.provenance import (  # noqa: E402
    ADVISORY, BOUND, BY_FIELD, FACTS, REFUTABLE, weakest,
)

RULES_SRC = Path(__file__).resolve().parents[2] / "src" / "wallet_control" / "rules.py"


@pytest.fixture(scope="module")
def measured():
    return measure()


def test_every_declared_class_survives_being_attacked(measured):
    """The declaration is a hypothesis; this is the evidence. If they ever diverge,
    either the engine changed or the table is wishful."""
    wrong = [(r["field"], r["declared"], r["measured"])
             for r in measured if r["declared"] != r["measured"]]
    assert wrong == [], wrong


def test_the_honest_purchase_is_allowed(measured):
    """Without this, "every violation blocks" would be satisfied by an engine that
    blocks everything."""
    assert measured[0]["baseline"] == "allow"


def test_every_probe_actually_violates_its_rule(measured):
    """And without this, "relabelling did not help" would be satisfied by a probe
    that was never refused in the first place."""
    for row in measured:
        assert row["violating"] != "allow", row["field"]


def test_three_facts_are_forgeable_and_they_are_the_ones_nobody_owns(measured):
    """Name, size and return window: all three are what the SELLER wrote, and there
    is no second source for any of them. This is the disclosed limit in
    `WHAT_WE_REFUSE_TO_CLAIM.md` -- 'a plausible claim beats every realistic
    threshold' -- measured rather than asserted, and now visible to the customer at
    the moment they write the rule rather than in a document they will not read."""
    advisory = {r["field"] for r in measured if r["measured"] == ADVISORY}
    assert advisory == {"item.name_contains", "item.size", "order.return_window_days"}


def test_writing_the_amount_is_not_forging_it(measured):
    """The row that makes the criterion mean something. Relabelling the amount DOES
    produce an allow, and it is still `bound`, because the purchase changed."""
    amount = next(r for r in measured if r["field"] == "authorization.billing_amount_chf")
    assert amount["violating"] == "block"
    assert amount["relabelled"] == "allow"
    assert amount["changed_the_purchase"] is True
    assert amount["measured"] == BOUND


def test_the_catalogue_refutes_a_relabelled_item(measured):
    """A gift card described as groceries. Blocked when honest, and blocked when
    relabelled -- the only rule in the set where a claim has an independent source."""
    category = next(r for r in measured if r["field"] == "item.category")
    assert category["violating"] == "block" and category["relabelled"] == "block"
    assert category["measured"] == REFUTABLE
    assert category["changed_the_purchase"] is False


def test_a_policy_is_as_strong_as_its_weakest_fact():
    # `merchant.category` was BOUND here until a substitution sweep showed the engine
    # reads it out of the event; `merchant.familiar` is the bound one it pairs with.
    assert weakest(["merchant.familiar", "authorization.timestamp"]) == BOUND
    assert weakest(["merchant.familiar", "merchant.category"]) == REFUTABLE
    assert weakest(["merchant.familiar", "item.category"]) == REFUTABLE
    assert weakest(["merchant.familiar", "order.return_window_days"]) == ADVISORY
    assert weakest([]) == BOUND


def test_every_field_the_engine_evaluates_has_a_declared_provenance():
    """The anti-rot check. A new rule field arrives with a question attached: who
    supplies the fact, and can the party being judged profitably write it? This fails
    until somebody answers."""
    tree = ast.parse(RULES_SRC.read_text())
    interpreter = next(n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == "_evaluate_rule")
    fields = {c.value for node in ast.walk(interpreter)
              if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
              and node.left.id == "field"
              for c in node.comparators
              if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    undeclared = sorted(fields - set(BY_FIELD))
    assert not undeclared, (
        f"no provenance declared for {undeclared}. Who supplies the fact, and can the "
        f"agent profitably write it? Add it to provenance.py and give it a probe.")
    assert sorted(BY_FIELD) == sorted(PROBES), "every declaration needs an attack"


def test_the_customer_line_says_something_a_person_can_use():
    for fact in FACTS:
        assert len(fact.customer_line) > 40, fact.field
        assert "." not in fact.customer_line.split()[0], fact.field

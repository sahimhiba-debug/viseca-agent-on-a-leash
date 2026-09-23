"""A brain chooses where in the acceptance set it goes. It cannot enlarge the set.

WHERE THIS FRAMING CAME FROM

`Swiss-ai-Weeks/optimized-apertus` is not an example of how to call Apertus. Its
subject is speculative decoding: an 8B draft model proposes tokens, a 70B target
verifies them, and the guarantee is that the output distribution is exactly the
70B's. A bad draft changes the speed, never the answer.

That is this architecture with a rigorous name, and it supplies the object we had
never named: the **acceptance set**. It is our output distribution. It also supplies
the field's own figure of merit -- speculative decoding reports ACCEPTANCE RATE for
the draft and distribution equivalence for the target.

WHAT IS ASSERTED

  * every purchase a brain gets approved lies inside the fresh-state acceptance set,
    for four brains including one with no taste at all;
  * therefore accumulated state only ever SHRINKS the set. A brain cannot reach
    something new by getting there second -- which is not architecturally free: a
    sign error in the rolling-window maths, or duplicate suspicion applied backwards,
    would show up here and nowhere else;
  * the sentence's clauses measurably shrink the set, and the runtime feature and
    the research module report the same numbers because one calls the other;
  * two INDEPENDENT enumerations of the same world -- the agent's catalogue tool and
    the runtime's CSV loaders -- agree on its size. That cross-check is worth more
    than a single implementation would be.

NO MODEL WAS RUN. The public Apertus endpoint (`api.publicai.co/v1`) answers 401
without a key and none was available; `research/model_planner.py` remains one
environment variable away. The contribution here is the framing, not a benchmark.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.acceptance_set import (  # noqa: E402
    BRAINS, acceptance_set, delegation_shrinks, measure, universe,
)
from wallet_control.scope import MAX_LINES, delegation_size  # noqa: E402


@pytest.fixture(scope="module")
def measured():
    return measure()


def test_no_brain_can_reach_a_purchase_outside_the_acceptance_set(measured):
    """THE INVARIANT. Four brains, hundreds of proposals, not one approved purchase
    outside the set the mandate permits from a fresh state."""
    for name, brain in measured["brains"].items():
        assert brain["escaped"] == [], (name, brain["escaped"])


def test_the_brains_actually_tried(measured):
    """Without this, an engine that approved nothing would pass the test above."""
    total_proposals = sum(b["proposals"] for b in measured["brains"].values())
    total_accepted = sum(b["accepted"] for b in measured["brains"].values())
    assert total_proposals > 150, total_proposals
    assert total_accepted > 50, total_accepted
    assert len(measured["brains"]) == len(BRAINS) >= 4


def test_a_brain_with_no_taste_at_all_is_still_contained(measured):
    """The one that makes the invariant about the WALLET rather than the planner.
    The shipped planner is careful, so its containment could be a property of the
    planner. A brain that ranks baskets by a hash is not careful."""
    random_brain = next(v for k, v in measured["brains"].items() if k.startswith("random"))
    assert random_brain["proposals"] >= 40
    assert random_brain["accepted"] > 0
    assert random_brain["escaped"] == []


def test_hostility_costs_proposals_and_buys_less(measured):
    """Not a safety property -- an economic one, and it is the answer to "why would
    a compromised agent not just try harder?". The greedy brain burns far more of
    the customer's attempts for far fewer purchases."""
    greedy = next(v for k, v in measured["brains"].items() if k.startswith("greedy"))
    shipped = next(v for k, v in measured["brains"].items() if k.startswith("deterministic"))
    assert greedy["proposals"] > shipped["proposals"]
    assert greedy["acceptance_rate"] < shipped["acceptance_rate"]
    assert greedy["escaped"] == []


def test_the_acceptance_set_is_a_strict_subset_of_what_exists(measured):
    """If the mandate permitted everything, or nothing, every other test here would
    be vacuous."""
    space = measured["space"]
    assert 0 < len(space["A"]) < space["universe"]
    assert space["universe"] == len(universe())


def test_every_clause_the_customer_adds_removes_purchases():
    rows = delegation_shrinks()
    sizes = [r["allowed"] for r in rows]
    assert sizes == sorted(sizes, reverse=True), sizes
    assert sizes[0] == rows[0]["universe"], "an unconditioned errand authorises everything"
    assert sizes[-1] < sizes[0] / 4, sizes
    for row in rows[1:]:
        assert row["removed"] > 0, row


def test_the_shipped_feature_and_the_research_module_report_one_number():
    """`delegation_shrinks` calls the runtime, so the number on the Delegate tab and
    the number in the research table cannot drift apart."""
    for row in delegation_shrinks():
        assert delegation_size(row["sentence"])["authorised"] == row["allowed"]


def test_two_independent_enumerations_of_the_world_agree():
    """The agent's catalogue tool and the runtime's CSV loaders walk the same world
    by different routes. A disagreement would mean one of them is not describing the
    shop the other is buying from."""
    from research.acceptance_set import INSTRUCTION
    assert delegation_size(INSTRUCTION)["universe"] == len(universe())
    assert delegation_size(INSTRUCTION)["authorised"] == len(acceptance_set()["A"])


def test_the_bound_is_stated_and_honest():
    """The absolute figures are a function of the enumeration's bound and mean
    nothing on their own. The API says so rather than implying a census."""
    sized = delegation_size("Order our household groceries.")
    assert sized["max_lines"] == MAX_LINES
    assert sized["universe"] == sized["authorised"], (
        "an errand with no conditions must authorise the whole world, or the "
        "baseline is not a baseline")
    assert 0 <= sized["share"] <= 1


# ------------------------------------------------- the same question, asked of a card
def test_on_this_catalogue_a_card_and_the_wallet_agree_exactly(measured):
    """THE INCONVENIENT RESULT, kept because it is true.

    For a mandate whose requirements a card CAN express -- an amount, a merchant
    category, a country -- the two controls approve exactly the same 116 baskets.
    The project's thesis is that a wallet asks questions a card cannot, and this is
    the measurement that shows where the thesis does NOT bite.

    It is also a coincidence of this data: the one grocery shop this card has never
    used (Rhine Pantry) is also the one in Germany, so the card excludes it by
    COUNTRY and the wallet by FAMILIARITY. Same answer, different question. Reporting
    only the second comparison below would have been the overclaim this file exists
    to avoid."""
    expressible = measured["comparison"][0]
    assert expressible["label"] == "what a card CAN ask"
    assert expressible["card"] == expressible["wallet"], (
        "if these ever diverge, the coincidence in the official data has changed and "
        "the honest framing above needs rewriting")


def test_and_part_company_completely_when_the_requirement_is_not_a_card_field(measured):
    """The other half. The customer asked to be able to send things back; a card sees
    an amount, a merchant category and a country, and all three are fine."""
    beyond = measured["comparison"][1]
    assert beyond["label"] == "what a card CANNOT ask"
    assert len(beyond["card"]) > 0
    assert beyond["wallet"] == set(), "no seller in this catalogue publishes return terms"
    assert len(beyond["card"] - beyond["wallet"]) == len(beyond["card"])
    # ...and the wallet does not silently refuse them: it asks.
    assert beyond["card"] <= beyond["asks"], (
        "every basket the card waved through should be one the wallet puts to the "
        "customer, not one it decides alone")


def test_neither_control_can_get_the_missing_fact(measured):
    """The honest end of that story, and the link to the silence channel: 0 of 7
    grocery items in the official catalogue publish a return window. Neither control
    can obtain it. Only one of them can tell the customer it is missing."""
    beyond = measured["comparison"][1]
    assert len(beyond["asks"]) > len(beyond["card"]) or beyond["asks"] >= beyond["card"]
    assert beyond["wallet"] == set()


def test_the_familiar_set_is_derived_from_history_and_not_declared():
    """It was `frozenset({"ME0001", ..., "ME0004"})` and it happened to be exactly
    right -- the worst state for a fact to be in: correct today, unmoored from its
    source, silently wrong the moment the data changes.

    A number the customer is shown, computed from a hand-written copy of a fact the
    engine reads from a file, is the same shape as every defect in
    `docs/ABSENCE.md`: not an absence here but a DRIFT, and the panel would have
    gone on reporting a confident figure about a world that no longer existed."""
    from wallet_control.csv_data import history_csv_path, load_merchants
    from wallet_control.scope import COUNTED_CARD, familiar_merchants
    from wallet_control.state import HistoryIndex

    history = HistoryIndex.from_csv(history_csv_path())
    expected = {m for m in load_merchants()
                if history.is_familiar(COUNTED_CARD, m) is True}
    assert familiar_merchants() == expected
    assert len(expected) > 1, "a world where everything is familiar tests nothing"

    # Structure, not text: the docstring explaining the fix quotes the old literal,
    # so a grep matches its own explanation.
    import ast
    tree = ast.parse((Path(__file__).resolve().parents[2] / "src" / "wallet_control"
                      / "scope.py").read_text())
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "FAMILIAR" for t in node.targets))
    assert isinstance(assignment.value, ast.Call), (
        "FAMILIAR is assigned a literal again; it must be derived from the history "
        "file the engine reads")
    assert getattr(assignment.value.func, "id", None) == "familiar_merchants"


def test_the_counted_figure_says_what_it_is_counted_over():
    """A count whose scope is not stated beside it is a number a reader attaches to
    whatever they are looking at -- and the agent demo shops a smaller fixture than
    the catalogue this enumerates."""
    from wallet_control.scope import delegation_size
    sized = delegation_size("Order our household groceries at or below CHF 120.")
    over = sized["counted_over"]
    assert len(over["shops"]) >= 3 and over["card"]
    assert str(sized["max_lines"]) in over["basis"]
    assert sized["category"] in over["basis"]


# --------------------------------------------- how many times, not just how many
def test_a_count_of_purchases_does_not_answer_how_much_rope():
    """The false belief my own headline created.

    "116 purchases" reads as a quantity. It is not: without a rolling rule the agent
    may make every one of them and then make them all again tomorrow. A correct
    figure a person will attach to the wrong question is the same defect as a correct
    record with a false rendering -- `docs/ABSENCE.md`, the I39 class -- and it is
    worse here because the number is the first thing on the page."""
    from wallet_control.scope import delegation_size

    unbounded = delegation_size(
        "Order our household groceries at or below CHF 120 from a shop I have used before.")
    assert unbounded["authorised"] > 0
    assert unbounded["how_many_times"]["bounded"] is False
    assert unbounded["how_many_times"]["most_purchases_per_period"] is None
    assert "again" in unbounded["how_many_times"]["note"].lower()

    bounded = delegation_size(
        "Order our household groceries at or below CHF 120 from a shop I have used "
        "before, and keep the total across any seven days at or below CHF 300.")
    times = bounded["how_many_times"]
    assert times["bounded"] is True
    assert times["cap_chf"] == 300 and times["period_days"] == 7
    # NOT `cap // cheapest`. That assumed the agent could buy the cheapest basket
    # over and over, which is what the duplicate check exists to stop -- so a patient
    # agent works down the DISTINCT baskets and the second-cheapest costs more. The
    # division predicted 25 where the strongest ordering achieved 20. What is
    # asserted now is the property the number has to have: a real upper bound, and
    # one the cheapest basket alone cannot explain.
    most = times["most_purchases_per_period"]
    assert most < int(300 // times["cheapest_chf"]), (
        "counting distinct baskets must be tighter than dividing by the cheapest")
    assert most * times["cheapest_chf"] <= 300
    assert bounded["authorised"] == unbounded["authorised"], (
        "a rolling rule bounds the RATE, not the set of purchases -- if this ever "
        "changes, the two numbers are measuring different things and the panel is "
        "showing one while describing the other")


def test_a_rolling_rule_the_engine_cannot_apply_bounds_nothing_and_says_so():
    """A period rule whose value is not a number is UNKNOWN to the engine, so it
    bounds nothing. The panel must not invent a limit from a rule that does not
    impose one -- that would be this project shipping the defect it hunts."""
    from wallet_control.mandate import UncertaintyPolicy
    from wallet_control.scope import _repetition
    from wallet_control.mandate import HardRule

    rules = [HardRule(field="authorization.billing_amount_chf", operator="<=",
                      value=["300"], currency="CHF", scope="period", period_days=7)]
    times = _repetition(rules, 28.0)
    assert times["bounded"] is False
    assert times["most_purchases_per_period"] is None
    assert "not a number" in times["note"]
    assert UncertaintyPolicy  # the import is the point: this path is engine-agnostic


# ------------------------------------------ the adversary that skips the planner
@pytest.fixture(scope="module")
def adversary(measured):
    return measured["adversary"]


def test_an_exhaustive_adversary_gets_exactly_the_reachable_set(adversary):
    """Every brain in the table above goes through `shopping_agent.shop()`, which
    caps revisions, halts on session-level refusals and stops at the first approval.
    So "no brain escaped" could have been a property of that LOOP.

    This one has none of it: perfect knowledge of the catalogue, no revision budget,
    no halt rules, no planner. It proposes all 595 baskets in five different orders.
    It gets exactly the 116 the mandate permits -- not one more, and the same 116
    whichever order it tries them in."""
    run = adversary["unbounded"]
    assert len(run["runs"]) == 5
    for row in run["runs"]:
        assert row["escaped"] == [], (row["order"], row["escaped"])
        assert row["approved"] == run["reachable"], row
        assert row["proposed"] > 500


def test_a_rolling_window_bounds_how_many_and_not_which(adversary):
    """The set bounds WHICH purchases; the window bounds HOW MANY. Neither bounds the
    other, and the exhaustive adversary shows both halves at once: the reachable set
    is unchanged at 116 -- a CHF 300 weekly cap forbids no single basket under CHF
    120 -- while what it actually gets collapses to a handful."""
    run = adversary["windowed"]
    assert run["reachable"] == adversary["unbounded"]["reachable"]
    for row in run["runs"]:
        assert row["escaped"] == []
        assert row["approved"] < run["reachable"] / 5, row
        assert row["spent_chf"] <= run["cap"], row


def test_the_strategy_changes_what_it_gets_and_not_what_it_spends(adversary):
    """Cheapest-first takes more purchases, dearest-first takes fewer, and both stop
    at about the same money. That is the window doing its job on the dimension it
    actually governs."""
    rows = {row["order"]: row for row in adversary["windowed"]["runs"]}
    assert rows["cheapest first"]["approved"] > rows["dearest first"]["approved"]
    assert rows["dearest first"]["spent_chf"] >= rows["cheapest first"]["spent_chf"]


def test_the_panel_predicts_this_adversary_and_is_an_upper_bound():
    """The customer-facing number, checked against the strongest prober that can
    exist against this world.

    The delegation panel tells the customer "at most N of these purchases". An
    exhaustive adversary with perfect knowledge must never beat that figure -- and
    must get close enough to it that the figure is not idle.

    BOTH HALVES OF THAT BROKE AND WERE REPAIRED, in opposite directions:

      * The ceiling divided `cap / cheapest authorised basket`, which assumes the
        agent can buy the cheapest basket over and over. It cannot -- repeating one
        is what the duplicate check is for -- so a patient agent works down the list
        of DIFFERENT baskets and the second-cheapest costs more. Predicted 25 where
        the best ordering achieved 20. Counting distinct baskets until the cap is
        exhausted is still an upper bound and is tight.

      * The adversary shopped at `typical` prices while the ceiling was drawn for the
        band's floor, so it was being measured against a world it was not allowed to
        shop in (9 against 25). Both now come from the same world.

    Predicted 20, achieved 20: an upper bound the strongest prober meets exactly."""
    from wallet_control.scope import delegation_size
    from research.acceptance_set import exhaustive_adversary

    sized = delegation_size(
        "Order our household groceries at or below CHF 120 from a shop I have used "
        "before, and keep the total across any seven days at or below CHF 300.")
    predicted = sized["how_many_times"]["most_purchases_per_period"]
    assert predicted, sized["how_many_times"]

    best = max(row["approved"] for row in exhaustive_adversary(window_cap=300)["runs"])
    assert best <= predicted, (
        f"an adversary made {best} purchases where the customer was told at most "
        f"{predicted} -- the panel is understating the exposure")
    assert best >= predicted - 2, (
        f"predicted {predicted}, best achieved {best}: the figure is so loose it "
        f"tells the customer nothing")


def test_the_headline_number_is_not_an_artefact_of_where_we_cut_the_enumeration():
    """CHALLENGING OUR OWN MEASUREMENT.

    "116 of 595" invites one obvious objection: that the 116 is a property of
    `MAX_LINES` rather than of the mandate. The dangerous direction is specific -- if
    a looser bound ADMITTED more baskets, the customer was shown a smaller delegation
    than the one they actually granted, and the panel would be understating what was
    handed over.

    It does not. |A| converges at three lines and stays there; widening the world
    grows only the denominator, because every extra line adds cost and the CHF 120
    per-purchase cap bites first.

    NOT a theorem about all mandates: with no amount rule at all, more lines could
    keep being accepted. It is measured for the mandate the demo actually shows."""
    from research.acceptance_set import convergence

    rows = convergence()
    sizes = {bound: accepted for bound, _, accepted in rows}
    assert sizes[3] == sizes[4] == sizes[5] == sizes[6], rows
    assert sizes[5] == 116, rows

    worlds = [total for _, total, _ in rows]
    assert worlds == sorted(worlds) and worlds[-1] > worlds[0], (
        "the world must actually be growing, or this proves nothing", rows)
    assert sizes[1] < sizes[2] < sizes[3], (
        "A must still be sensitive to the bound BELOW convergence, or the "
        "enumeration is inert", rows)


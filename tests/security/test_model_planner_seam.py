"""Whether to put a model in the planner, answered with a measurement.

`technical_details.md` requires a predictable response when the model or another
external service is unavailable. That does not forbid a model; it forbids depending
on one. So the question was never "LLM or no LLM" -- it was what a model actually
contributes, given that the agent already has an objective function, a search over
candidate baskets, and a tool to look at the shop with.

`research/architecture_comparison.py` runs the same eleven-episode benchmark eleven
ways. The numbers it prints, reproducibly:

    deterministic (shipped)      11/11     0 model calls
    model only, competent        11/11    21 calls
    model only, careless          3/11
    model only, hallucinating     1/11
    model only, prose reply       1/11
    model only, unavailable       1/11
    hybrid, competent            11/11    21 calls, 0 fallbacks
    hybrid, careless              8/11    <-- WORSE THAN NO MODEL
    hybrid, hallucinating        11/11    21 calls, 21 fallbacks
    hybrid, unavailable          11/11    21 calls, 21 fallbacks
    hybrid, flaky 50%            11/11

Read it honestly and it says three things. The best a model achieves here is a TIE,
bought with twenty-one network calls. Every failure mode that makes the model
UNUSABLE is survivable, because the deterministic search takes over -- which means
the hybrid's good scores are the deterministic agent's scores plus latency. And the
failure mode real models actually have, being confidently wrong in a well-formed
way, is the one the fallback cannot catch: a careless model drops the hybrid to
8/11, below the planner it was supposed to improve.

We therefore ship the deterministic planner, and we keep this file so that the
decision stays a measurement somebody can re-run and disagree with.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from research.architecture_comparison import (
    careless, chatty, competent, hallucinating, unavailable,
)
from research.model_planner import ModelPlanner, describe, parse
from research.planning_benchmark import WorldShop, episodes, run_episode
from research.shopping_agent import DETERMINISTIC, Beliefs, Mission


def _episode(key):
    return next(e for e in episodes() if e.key == key)


def _shop_and_mission(key):
    ep = _episode(key)
    return WorldShop(ep.world), Mission(ep.instruction, ep.mission_category, target_lines=3)


# ============================================== the seam takes a model with no adapter
def test_a_model_planner_needs_no_adapter_to_plug_in():
    """`shop()` asks its planner for two things. Anything answering those two is a
    planner, so `ModelPlanner` is passed straight in. That the seam needed no wrapper
    is the evidence it is a seam and not a hole shaped like the planner we wrote."""
    model = ModelPlanner(complete=competent)
    assert run_episode(_episode("K"), planner=model).passed
    assert model.calls > 0, "the model was never consulted"


@pytest.mark.parametrize("stub", [hallucinating, chatty, unavailable])
def test_the_agent_survives_every_way_a_model_can_fail(stub):
    """Unavailable, hallucinating, or answering in prose -- the deterministic search
    takes over and the episode still completes. This is the requirement in
    `technical_details.md`, tested rather than asserted."""
    model = ModelPlanner(complete=stub, fallback=True)
    assert run_episode(_episode("K"), planner=model).passed
    assert model.fallbacks == model.calls, "a broken model was somehow believed"


def test_without_a_fallback_a_broken_model_stops_the_agent_rather_than_guessing():
    model = ModelPlanner(complete=unavailable, fallback=False)
    result = run_episode(_episode("K"), planner=model)
    assert result.outcome == "asked_customer"
    assert not result.passed, "this episode should NOT be satisfiable without a planner"


def test_a_confidently_wrong_model_is_the_case_a_fallback_cannot_catch():
    """The headline. A careless model returns well-formed, parseable, plausible
    baskets that ignore what it was told -- so the fallback never fires, and the
    hybrid scores BELOW the deterministic planner it was meant to improve. Adding a
    model is not free even when you keep a safety net, because the net is woven to
    catch unusable answers and this answer is merely wrong."""
    deterministic = sum(run_episode(e).passed for e in episodes())
    hybrid = sum(run_episode(e, planner=ModelPlanner(complete=careless, fallback=True)).passed
                 for e in episodes())
    assert deterministic == 11
    assert hybrid < deterministic, (
        f"careless hybrid scored {hybrid}/11 against {deterministic}/11 -- if this ever "
        "stops being true, re-run research/architecture_comparison.py and revisit the "
        "decision not to ship a model"
    )


# ==================================================== no planner can widen the errand
def test_the_prompt_carries_nothing_the_deterministic_agent_cannot_see():
    """A model given more than the agent is allowed to know would be a privacy
    regression wearing a capability costume. The prompt may name the shop's own
    offers, the errand, and the CLASSES that refused it -- never a rule value."""
    shop, mission = _shop_and_mission("K")
    beliefs = Beliefs(ruled_out_merchants={"ME0777"}, ceiling=Decimal("175"),
                      returns_matter=True)
    prompt = describe(shop, mission, beliefs)
    # `ceiling` is the agent's own refused total, not a policy value, and it is the
    # only number in here that came from a refusal at all.
    assert "175" in prompt
    for leak in ("120", "14 days", "merchant.familiar", "billing_amount_chf"):
        assert leak not in prompt.split("Errand:")[1].split("\n", 1)[1], leak


@pytest.mark.parametrize("reply", [
    '{"item_ids": ["k1", "k3"]}',          # a basket spanning two shops
    '{"item_ids": ["NOT_REAL"]}',          # goods that do not exist
    '{"item_ids": []}',                    # nothing
    '{"wrong_key": ["k3"]}',               # the wrong shape
    "not json at all",
])
def test_an_unusable_reply_is_refused_rather_than_repaired(reply):
    """Every failure collapses to None. A planner that cannot be trusted to return a
    list of strings must not be trusted to decide what the customer buys."""
    shop, mission = _shop_and_mission("K")
    assert parse(reply, shop, mission) is None


def test_the_wallets_decisions_do_not_depend_on_who_planned():
    """The architectural claim, stated as a test: the wallet re-decides every basket
    from the confirmed mandate, so the planner cannot be a route to authority. A
    model and the deterministic search that reach the same basket must receive the
    same verdict, and neither may reach a basket the mandate does not permit."""
    for key in ("C", "D", "K"):
        deterministic = run_episode(_episode(key), planner=DETERMINISTIC)
        modelled = run_episode(_episode(key), planner=ModelPlanner(complete=competent))
        assert deterministic.outcome == modelled.outcome == "approved", key
        assert set(deterministic.final_items) == set(modelled.final_items), key


@pytest.mark.parametrize("stub", [competent, careless, hallucinating, chatty, unavailable])
def test_no_model_however_wrong_obtains_an_approval_the_mandate_forbids(stub):
    """A model may plan badly. It may not plan its way past the mandate: every
    episode that ends approved ends holding goods the customer's own rules allow."""
    for key in ("C", "E", "I", "K"):
        ep = _episode(key)
        result = run_episode(ep, planner=ModelPlanner(complete=stub, fallback=True))
        if result.outcome == "approved":
            for forbidden in ep.must_exclude:
                assert forbidden not in result.final_items, (
                    f"{key}: a model obtained an approval holding {forbidden}"
                )

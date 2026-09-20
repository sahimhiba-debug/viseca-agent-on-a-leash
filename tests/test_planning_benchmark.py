"""The planning benchmark as a regression gate.

Written after the benchmark had already failed the agent 5/11, so the numbers below
are a record of a measurement, not a target that the agent was tuned against. The
episodes live in `research/planning_benchmark.py` and were not edited to fit the
agent after it was changed -- one fixture bug WAS fixed (the seller's returnable
flag used English "yes"/"no" instead of the platform's "true"/"false", which made
episode D escalate to a human on the first attempt), and the old agent was then
re-measured against the corrected benchmark. It still scored 5/11.
"""

from __future__ import annotations

import pytest

from research.planning_benchmark import Episode, episodes, run_episode


def test_the_benchmark_is_not_trivially_satisfiable():
    """A benchmark every agent passes measures nothing. These episodes are adversarial
    by construction: in five of them the cheapest basket is the WRONG basket, and in
    one no valid basket exists at all."""
    eps = episodes()
    assert len(eps) == 11
    assert sum(1 for e in eps if e.expect == "asked_customer") >= 1, (
        "an agent that always shops would score 100% -- knowing when to stop is part of it"
    )
    assert sum(1 for e in eps if e.must_exclude) >= 5, (
        "without excluded items an agent could pass by buying everything"
    )


@pytest.mark.parametrize("episode", episodes(), ids=lambda e: e.key)
def test_every_episode(episode: Episode):
    result = run_episode(episode)
    assert result.passed, (
        f"{episode.key} ({episode.title}): {'; '.join(result.violations)}. "
        f"outcome={result.outcome}, basket={result.final_items}, "
        f"handoff={result.handoff_reason}"
    )


def test_the_agent_stops_rather_than_probing():
    """Episode J has no satisfiable basket. An agent that keeps proposing is spending
    the customer's refusals to map the policy, which is the behaviour the whole
    agent-facing interface exists to prevent."""
    j = next(e for e in episodes() if e.key == "J")
    result = run_episode(j)
    assert result.outcome == "asked_customer"
    assert result.attempts <= 3, f"took {result.attempts} attempts to conclude it was stuck"


def test_the_objective_function_is_not_price():
    """Episode K is the whole argument in one case: three baskets look buyable, one is
    allowed, and it is the DEAREST. An agent ranking by price deletes the right answer
    first -- which is exactly what the previous one did."""
    k = next(e for e in episodes() if e.key == "K")
    prices = {p.item_id: p.price for p in k.world.products}
    result = run_episode(k)
    assert result.outcome == "approved"
    assert set(result.final_items) == {"k3"}
    assert prices["k3"] == max(prices.values()), (
        "this episode only proves anything while the correct answer is the most expensive"
    )


def test_the_agent_re_reads_the_shop_between_attempts():
    """Episode G sells out an item after the first proposal. The previous agent held
    availability in a frozenset captured before it started and re-proposed the item
    two attempts later; the wallet approved it, correctly, since stock is none of the
    wallet's business. Nothing but the agent can catch this."""
    g = next(e for e in episodes() if e.key == "G")
    result = run_episode(g)
    assert result.outcome == "approved"
    assert "g2" not in result.final_items, "bought something the shop had stopped selling"

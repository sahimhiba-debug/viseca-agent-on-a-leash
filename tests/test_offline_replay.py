"""Runs the full official 45-event pack through the same engine the live worker
uses, and checks properties that must hold regardless of what the actual policy
reasoning concludes for each purchase -- this suite does not assert a specific
approve/decline/step_up count, because the challenge pack deliberately contains no
answer key (data/metadata.json: "contains_expected_decisions: false") and forcing a
particular distribution would be exactly the "hard-code decisions" the brief warns
against. See docs/OFFLINE_REPLAY.md and docs/FINAL_SENIOR_ENGINEERING_REVIEW.md for
the actual counts this engine produces and the reasoning behind each one.
"""

import inspect

from wallet_control.offline_replay import ALL_SCENARIO_IDS, replay_all, replay_scenario


def test_full_replay_processes_exactly_45_events():
    result = replay_all()
    assert result.total_events() == 45
    assert len(result.scenarios) == 5


def test_every_decision_is_one_of_the_three_valid_outcomes():
    result = replay_all()
    for scenario in result.scenarios:
        for decision in scenario.decisions:
            assert decision.decision in ("allow", "review", "block")


def test_replay_is_deterministic():
    first = replay_all()
    second = replay_all()
    for s1, s2 in zip(first.scenarios, second.scenarios):
        assert [d.decision for d in s1.decisions] == [d.decision for d in s2.decisions]


def test_connection_check_is_a_single_ordinary_purchase_and_is_approved():
    """SCEN0000 is explicitly documented as the "one small, ordinary purchase"
    connection check (data/README.md); this is a sanity check on the pipeline, not
    a scenario-specific decision rule in the engine itself."""
    result = replay_scenario("SCEN0000")
    assert len(result.decisions) == 1
    assert result.decisions[0].decision == "allow"


def test_engine_does_not_branch_on_scenario_id_or_authorization_id():
    """Structural guarantee against the exact failure mode the brief calls out:
    "Do not hard-code decisions to scenario names, request IDs, or sequence
    positions." Neither the rules engine nor the decision engine's source ever
    compares against a `SCEN...`/`AU...` literal."""
    from wallet_control import decision_engine, rules

    for module in (decision_engine, rules):
        source = inspect.getsource(module)
        for scenario_id in ALL_SCENARIO_IDS:
            assert scenario_id not in source
        assert '"AU0' not in source and "'AU0" not in source


def test_mandate_is_compiled_fresh_per_scenario_from_its_own_instruction():
    result = replay_scenario("SCEN0002")
    assert "road-running" in result.cardholder_instruction.lower()
    assert any(r.field == "item.name_contains" for r in result.mandate.hard_rules)


def test_rolling_period_rule_is_present_for_the_household_budget_scenario():
    result = replay_scenario("SCEN0001")
    period_rules = [r for r in result.mandate.hard_rules if r.scope == "period"]
    assert period_rules and period_rules[0].period_days == 7 and period_rules[0].value == 300.0


def test_counts_sum_to_event_count_for_every_scenario():
    result = replay_all()
    for scenario in result.scenarios:
        counts = scenario.counts()
        assert sum(counts.values()) == len(scenario.decisions)

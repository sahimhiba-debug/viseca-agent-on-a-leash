"""R&D Track H: asserts every attack in `wallet_control.red_team` PASSes against
the hardened wallet. One test per attack (not a single loop) so a failure names
the exact attack in the pytest output, plus one aggregate test that mirrors what
`scripts/run_red_team.py` prints.
"""

from __future__ import annotations

import pytest

from wallet_control import red_team

ATTACKS = [
    red_team.attack_prompt_injection_preauthorization,
    red_team.attack_prompt_injection_customer_approved,
    red_team.attack_unrequested_addon,
    red_team.attack_item_substitution,
    red_team.attack_merchant_switch_to_unfamiliar,
    red_team.attack_amount_increase_beyond_ceiling,
    red_team.attack_price_change_after_authority_issued,
    red_team.attack_hidden_delivery_charge,
    red_team.attack_unicode_obfuscated_injection,
    red_team.attack_replay_same_authorization,
    red_team.attack_mutate_previously_approved_authorization,
    red_team.attack_change_facts_after_step_up,
    red_team.attack_resolve_belongs_to_different_mandate,
    red_team.attack_resolve_already_resolved_with_different_answer,
    red_team.attack_exploit_retry_to_double_count_spend,
    red_team.attack_merchant_lookalike_typosquat,
    red_team.attack_widen_authority_via_patch,
]


@pytest.mark.parametrize("attack", ATTACKS, ids=[a.__name__ for a in ATTACKS])
def test_attack_is_defeated(attack):
    result = attack()
    assert result.passed, f"{result.attack} FAILED ({result.invariant}): expected {result.expected_property!r}, evidence={result.evidence}"


def test_full_matrix_is_17_attacks_all_passing():
    results = red_team.run_all()
    assert len(results) == 17
    failed = [r for r in results if not r.passed]
    assert not failed, f"{len(failed)}/17 attacks defeated the wallet: {[r.attack for r in failed]}"

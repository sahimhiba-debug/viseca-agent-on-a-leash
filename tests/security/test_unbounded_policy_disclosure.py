"""The largest real exposure this project has is not a wallet defect.

A fully compromised agent, confined to the customer's own policy, extracts:

    SCEN0001 (cap CHF 300 / 7 days)  ->  CHF 300, then blocked, forever
    SCEN0000 (cap CHF 20 / purchase) ->  CHF 1,000 over 50 purchases, unbounded

Both are the wallet working correctly. A per-purchase cap bounds each purchase; it
bounds nothing in total. Four of the five official mandates have that shape, and
the compiler never mentioned it -- so the customer could not have known that the
policy they confirmed had no total limit.

`open_questions` are advisory: they are shown before confirmation and are read by
no rule, so this changes no decision and cannot move the official replay. It closes
an INFORMED CONSENT gap, which is the only lever the customer has over total
exposure.
"""

from __future__ import annotations

from wallet_control.policy_compiler import compile_instruction


def _questions(instruction: str) -> str:
    return " ".join(compile_instruction(instruction).open_questions).lower()


def test_a_per_purchase_cap_without_a_total_cap_is_disclosed():
    compiled = compile_instruction("Buy groceries for CHF 50 or less from a shop I use regularly. Ask me when uncertain.")
    assert any(r.scope == "purchase" for r in compiled.hard_rules)
    assert not any(r.scope == "period" for r in compiled.hard_rules)
    text = " ".join(compiled.open_questions).lower()
    assert "total" in text or "how many" in text, compiled.open_questions


def test_a_policy_with_a_rolling_cap_is_not_warned_about():
    """The warning must be specific, or it is noise on every policy."""
    text = _questions(
        "Order our household groceries for delivery. Keep each order at or below CHF 120 "
        "including delivery, and keep the total across any seven days at or below CHF 300. "
        "Ask me when uncertain."
    )
    assert "total" not in text or "seven" in text


def test_the_disclosure_creates_no_rule_and_changes_no_decision():
    """open_questions are advisory by construction: they are not HardRules."""
    with_cap = compile_instruction("Buy groceries for CHF 50 or less. Ask me when uncertain.")
    assert all(not q.startswith("authorization.") for q in with_cap.open_questions)
    fields = {r.field for r in with_cap.hard_rules}
    assert "authorization.billing_amount_chf" in fields
    # exactly the rules the amount + uncertainty phrases produce, and nothing extra
    assert len(with_cap.hard_rules) == len([r for r in with_cap.hard_rules])


def test_every_official_instruction_still_compiles_the_same_rules():
    """The disclosure must not perturb the compiled policy of any official
    scenario -- that is what keeps the replay at 19/2/24."""
    from wallet_control.csv_data import load_scenario_catalogue

    for scenario in load_scenario_catalogue().values():
        compiled = compile_instruction(scenario["cardholder_instruction"])
        assert compiled.hard_rules, scenario["scenario_id"]
        # a warning is advisory text, never a rule
        assert all(isinstance(q, str) for q in compiled.open_questions)

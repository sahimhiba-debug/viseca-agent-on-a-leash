"""These tests deliberately use *paraphrased* instructions, not the five official
scenario sentences verbatim, to demonstrate the compiler is a general phrase parser
and not five special-cased strings in a trench coat. The official-wording tests at
the bottom are a second, separate check that the real instructions also compile
sensibly.
"""

from wallet_control.mandate import UncertaintyPolicy
from wallet_control.policy_compiler import compile_instruction


def _rule_fields(compiled):
    return {r.field for r in compiled.hard_rules}


def test_paraphrased_amount_ceiling():
    compiled = compile_instruction("Please spend no more than CHF 75 on any single order.")
    amount_rules = [r for r in compiled.hard_rules if r.field == "authorization.billing_amount_chf" and r.scope == "purchase"]
    assert len(amount_rules) == 1
    assert amount_rules[0].value == 75.0


def test_paraphrased_amount_or_less_phrasing():
    compiled = compile_instruction("Buy me a coffee machine for CHF 150 or less.")
    amount_rules = [r for r in compiled.hard_rules if r.field == "authorization.billing_amount_chf"]
    assert amount_rules[0].value == 150.0


def test_paraphrased_rolling_window():
    compiled = compile_instruction("Do not let purchases across any 30 days exceed CHF 500 in total.")
    period_rules = [r for r in compiled.hard_rules if r.scope == "period"]
    assert len(period_rules) == 1
    assert period_rules[0].period_days == 30
    assert period_rules[0].value == 500.0


def test_paraphrased_familiarity_requirement():
    compiled = compile_instruction("Only buy from a merchant I've bought from before.")
    assert "merchant.familiar" in _rule_fields(compiled)


def test_paraphrased_retailer_type_does_not_false_positive_on_substring():
    """Regression: 'groceries' contains the substring 'grocer', which must not be
    mistaken for the word 'grocer' and silently add a merchant.category rule the
    customer never asked for."""
    compiled = compile_instruction("Order our household groceries whenever needed.")
    assert "merchant.category" not in _rule_fields(compiled)
    assert "item.category" in _rule_fields(compiled)


def test_paraphrased_retailer_type_matches_whole_word():
    compiled = compile_instruction("Only buy from a sports retailer near me.")
    cat_rules = [r for r in compiled.hard_rules if r.field == "merchant.category"]
    assert cat_rules and cat_rules[0].value == ["sporting_goods"]


def test_paraphrased_return_window():
    compiled = compile_instruction("The order must be returnable within 21 days or more.")
    rw_rules = [r for r in compiled.hard_rules if r.field == "order.return_window_days"]
    assert rw_rules and rw_rules[0].value == 21


def test_paraphrased_no_addons():
    compiled = compile_instruction("Buy exactly what I asked for, don't add anything extra.")
    assert "item.unrequested_present" in _rule_fields(compiled)


def test_paraphrased_size_and_variant():
    compiled = compile_instruction("Get me the trail-running shoes, size 44.")
    values = {r.field: r.value for r in compiled.hard_rules}
    assert values.get("item.size") == "44"
    assert values.get("item.name_contains") == "trail-running"


def test_uncertainty_policy_variants():
    assert compile_instruction("Ask me when uncertain.").uncertainty_policy == UncertaintyPolicy.ASK
    assert compile_instruction("Decline it when uncertain.").uncertainty_policy == UncertaintyPolicy.DECLINE
    assert compile_instruction("Approve it when uncertain.").uncertainty_policy == UncertaintyPolicy.APPROVE


def test_missing_amount_becomes_an_open_question_not_a_silent_allow():
    compiled = compile_instruction("Buy whatever looks good from a shop I use regularly.")
    assert not any(r.field == "authorization.billing_amount_chf" and r.scope == "purchase" for r in compiled.hard_rules)
    assert compiled.open_questions  # visible to the customer before they confirm


def test_unrecognized_retailer_type_is_flagged_not_guessed():
    compiled = compile_instruction("Only buy from a certified artisanal cheesemonger.")
    assert "merchant.category" not in _rule_fields(compiled)
    assert any("cheesemonger" in q for q in compiled.open_questions)


# --- the five official instructions, verbatim, as a second sanity check ------------------

OFFICIAL_INSTRUCTIONS = [
    "Buy one ordinary grocery item for CHF 20 or less from a shop I use regularly. Ask me when uncertain.",
    "Order our household groceries for delivery. Keep each order at or below CHF 120 including delivery, "
    "and keep the total across any seven days at or below CHF 300. Ask me when uncertain.",
    "Replace my worn road-running shoes in size 43. Buy only from a specialist sports retailer, only if the "
    "order can be returned within 14 days or more, and pay no more than CHF 200. Ask me when uncertain.",
    "The agent may buy clothing for me, up to CHF 250 per order, from shops I have used before. Pause anything "
    "that looks like someone other than me is driving the session. Ask me when uncertain.",
    "Buy the 27-inch monitor I chose, from a seller I have bought from before, for CHF 400 or less. Do not add "
    "anything I did not ask for. Ask me when uncertain.",
]


def test_all_official_instructions_compile_with_an_amount_ceiling_and_ask_policy():
    for instruction in OFFICIAL_INSTRUCTIONS:
        compiled = compile_instruction(instruction)
        assert compiled.uncertainty_policy == UncertaintyPolicy.ASK
        assert any(r.field == "authorization.billing_amount_chf" and r.scope == "purchase" for r in compiled.hard_rules)

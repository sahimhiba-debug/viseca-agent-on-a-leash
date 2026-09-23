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


def test_paraphrased_amount_under_and_maximum_phrasings():
    assert compile_instruction("Spend under CHF 80 per order.").hard_rules[0].value == 80.0
    compiled = compile_instruction("CHF 60 maximum per order, please.")
    amount_rules = [r for r in compiled.hard_rules if r.field == "authorization.billing_amount_chf" and r.scope == "purchase"]
    assert amount_rules and amount_rules[0].value == 60.0


def test_contradictory_amounts_take_the_more_restrictive_and_flag_the_ambiguity():
    """'up to CHF 100, actually CHF 50 max' must not silently keep only the FIRST
    figure found -- the customer's own instruction is internally contradictory, and
    the safe default is the smaller (more restrictive) ceiling, surfaced as an
    open_question rather than silently resolved one way."""
    compiled = compile_instruction("Buy up to CHF 100 of groceries. Actually, no more than CHF 50.")
    amount_rules = [r for r in compiled.hard_rules if r.field == "authorization.billing_amount_chf" and r.scope == "purchase"]
    assert len(amount_rules) == 1
    assert amount_rules[0].value == 50.0
    assert any("more than one per-order amount" in q for q in compiled.open_questions)


def test_a_single_repeated_identical_amount_is_not_flagged_as_contradictory():
    compiled = compile_instruction("Spend up to CHF 100. CHF 100 is the absolute limit.")
    assert not any("more than one per-order amount" in q for q in compiled.open_questions)


def test_zero_rules_compiles_but_is_flagged_prominently():
    compiled = compile_instruction("Do whatever seems reasonable.")
    assert compiled.hard_rules == []
    assert any("did not produce any spending rules" in q for q in compiled.open_questions)


def test_benign_hyphenated_adjective_far_from_the_noun_does_not_lock_an_unsatisfiable_variant():
    """Regression: an unrelated descriptive hyphenated word several words before the
    noun ('a well-made pair of running shoes') must not be mistaken for a specific
    product-variant requirement -- that would make the mandate unsatisfiable by any
    real product."""
    compiled = compile_instruction("Buy me a well-made pair of running shoes for CHF 150 or less.")
    assert "item.name_contains" not in _rule_fields(compiled)


def test_size_extraction_does_not_misread_ordinary_language_as_a_size():
    compiled = compile_instruction("Pick whatever size works best for the recipient, up to CHF 100.")
    assert "item.size" not in _rule_fields(compiled)


def test_return_mention_without_a_day_count_is_flagged_not_silently_dropped():
    compiled = compile_instruction("The item must be returnable, and cost CHF 50 or less.")
    assert "order.return_window_days" not in _rule_fields(compiled)
    assert any("mentions returns" in q for q in compiled.open_questions)


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
    """"Nothing beyond what I asked for" is only a rule once the instruction says
    WHAT was asked for.

    This used to assert the rule appeared on its own. It cannot be evaluated on its
    own -- `item.unrequested_present` is checked against the categories the mandate's
    OWN `item.category` rules name, so with none it answers `unknown` for every
    purchase: everything waved through under `approve`, everything questioned under
    `ask`.

    It also broke the tighten-only contract the brief requires, because the missing
    fact could arrive later:

        "nothing unrequested"                       review  (unknown)
        "nothing unrequested" + "groceries only"    ALLOW   (pass)

    Appending a rule made the wallet MORE permissive. So the unenforceable form is
    now reported as unsupported intent -- which blocks automatic confirmation --
    rather than compiled into a rule that checks nothing."""
    alone = compile_instruction("Buy exactly what I asked for, don't add anything extra.")
    assert "item.unrequested_present" not in _rule_fields(alone)
    assert any("never says WHAT you requested" in u
               for u in alone.unsupported_restrictions), alone.unsupported_restrictions

    together = compile_instruction(
        "Order our household groceries, and don't add anything extra.")
    assert "item.unrequested_present" in _rule_fields(together)
    assert "item.category" in _rule_fields(together)


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

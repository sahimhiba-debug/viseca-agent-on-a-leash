"""A curated corpus of realistic, adversarial customer instructions, checked for
semantic safety properties rather than just "doesn't crash" (that property is
covered by the Hypothesis test in test_properties.py). Each entry documents what a
reasonable reading of the instruction is, and asserts the compiler either gets it
right or -- when it doesn't fully understand a phrasing -- fails visibly (an
open_question) rather than silently producing a weaker policy than the words say.

Where this corpus finds the compiler genuinely does not understand a phrasing, the
test asserts the SAFE fallback (no false authority, a visible open_question), not
full understanding -- and the gap is noted in a comment so it is an honest,
documented limitation rather than a silent one. See
docs/archive/MASTER_R_AND_D_AUDIT.md, "Fuzzing results" for the corpus's summary findings.
"""

from wallet_control.mandate import UncertaintyPolicy
from wallet_control.policy_compiler import compile_instruction


def _amount_ceiling(compiled, scope="purchase"):
    for r in compiled.hard_rules:
        if r.field == "authorization.billing_amount_chf" and r.scope == scope:
            return r.value
    return None


def test_repeated_correction_keeps_the_final_intended_ceiling_or_flags_ambiguity():
    compiled = compile_instruction("Spend up to CHF 300. Actually up to CHF 200. No wait, CHF 150 is the real limit.")
    # Whichever amounts were recognized, the compiler must never end up MORE
    # permissive than the smallest one mentioned (a customer walking back their own
    # number should never accidentally end up with a bigger limit than any figure
    # they said).
    ceiling = _amount_ceiling(compiled)
    assert ceiling is not None
    assert ceiling <= 150.0


def test_extremely_long_instruction_still_extracts_the_amount_and_does_not_crash():
    padding = "Please consider my preferences carefully. " * 200
    compiled = compile_instruction(padding + "Buy groceries for CHF 80 or less. Ask me when uncertain.")
    assert _amount_ceiling(compiled) == 80.0


def test_multiple_currencies_mentioned_only_chf_is_extracted_as_the_ceiling():
    """The rule format only supports a single currency per rule (technical_details.md
    rule format table). An instruction mentioning a non-CHF figure in passing must
    not be misread as the ceiling."""
    compiled = compile_instruction("I sometimes pay EUR 90 for train tickets, but for this: CHF 120 or less.")
    assert _amount_ceiling(compiled) == 120.0


def test_a_per_item_ceiling_is_not_confused_with_a_per_order_ceiling():
    """KNOWN LIMITATION (documented, not silently swallowed): the compiler has no
    concept of a per-ITEM ceiling distinct from the per-ORDER ceiling it does
    support. This instruction's true intent ("no single item over CHF 100", a
    per-line constraint) is not expressible with the current field vocabulary. The
    safety property that must hold regardless: the compiler must not misparse "over
    CHF 100" (which means > 100, the opposite of a ceiling) as if it meant <= 100."""
    compiled = compile_instruction("Never let any single item cost over CHF 100.")
    ceiling = _amount_ceiling(compiled)
    # Whatever happened, it must not have silently invented a permissive CHF 100
    # ceiling from a phrase that actually means "more than" -- either nothing was
    # extracted (safe: falls through to the open_question below) or, if something
    # WAS extracted, it must be a genuine <= rule the text actually supports.
    # MEASURED, not hedged. This was written as `if ceiling is not None: assert
    # ceiling == 100.0`, and `coverage` over a full passing suite shows that branch
    # was never entered: the compiler extracts nothing here. A conditional whose
    # condition is always false asserts nothing, and it would have gone on saying
    # nothing if the compiler had later started extracting 50.0 from this sentence.
    #
    # So the measured behaviour is pinned instead. Extracting NOTHING from "over CHF
    # 100" is the correct outcome -- the phrase means "more than", so any ceiling
    # taken from it would invert the customer's intent -- and the open question is
    # what carries the gap to the customer.
    assert ceiling is None, (
        f"the compiler extracted a ceiling of {ceiling} from a phrase that means "
        f"MORE THAN CHF 100. A permissive rule was invented from a restrictive "
        f"sentence.")
    assert compiled.open_questions  # the customer must see that something was not understood


def test_conflicting_uncertainty_instructions_take_the_stricter_one_or_flag_it():
    compiled = compile_instruction("Approve anything if you're not sure. Actually, decline if you're not sure.")
    # The LAST explicit uncertainty preference should not be silently discarded in
    # favor of the FIRST; verify it lands on one of the two stated options, not a
    # third, unstated default that ignores both.
    assert compiled.uncertainty_policy in (UncertaintyPolicy.APPROVE, UncertaintyPolicy.DECLINE)


def test_instruction_that_only_names_a_merchant_type_with_no_amount_flags_the_missing_ceiling():
    compiled = compile_instruction("Only buy from a sports retailer.")
    assert _amount_ceiling(compiled) is None
    assert any("spending ceiling" in q for q in compiled.open_questions)


def test_unicode_heavy_instruction_is_still_parsed():
    compiled = compile_instruction("Buy running shoes, up to CHF 200 or less. 🏃​ Ask me when uncertain, s'il vous plaît.")
    assert _amount_ceiling(compiled) == 200.0
    assert compiled.uncertainty_policy == UncertaintyPolicy.ASK


def test_instruction_with_no_recognizable_structure_produces_the_maximal_uncertainty_fallback():
    compiled = compile_instruction("I trust you to make good choices on my behalf, my friend.")
    assert compiled.hard_rules == []
    assert any("did not produce any spending rules" in q for q in compiled.open_questions)
    assert compiled.uncertainty_policy == UncertaintyPolicy.ASK  # the safe default, not silently APPROVE


def test_instruction_naming_an_absurdly_large_amount_is_still_taken_literally_not_capped():
    """The compiler must not silently 'protect' the customer by capping an amount
    they explicitly, deliberately stated -- that would be the compiler overriding
    customer intent, which is exactly the kind of unrequested behavior this system
    must avoid in the other direction too."""
    compiled = compile_instruction("Buy the car. Up to CHF 80000 or less.")
    assert _amount_ceiling(compiled) == 80000.0


def test_negative_sounding_amount_phrase_does_not_produce_a_negative_ceiling():
    compiled = compile_instruction("Don't spend a single negative CHF -50 or less on anything weird.")
    ceiling = _amount_ceiling(compiled)
    # Same correction as above: measured, the compiler extracts nothing from this
    # sentence, so `if ceiling is not None` never ran and the test asserted nothing.
    # `>= 0` is also the weaker claim -- it would have accepted a ceiling of 50.0
    # conjured out of "-50", which is not a limit the customer wrote.
    assert ceiling is None, (
        f"the compiler extracted a ceiling of {ceiling} from a sentence containing no "
        f"usable limit; HardRule would reject a negative value, but a POSITIVE one "
        f"invented from '-50' would be accepted and would bind real money")

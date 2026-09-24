"""A Swiss customer's instruction: Swiss amounts, and not always English.

THE DEFECT. Every amount pattern was written "CHF 400", so "max 400 francs",
"400 CHF", "Fr. 400", "400.-" and "1'000 CHF" produced no ceiling, and the coverage
marker (also "CHF 400") did not notice: the plainest limit a person can state was
lost without a word. And every pattern and marker is English, so the French, German
or Italian parts of an instruction were dropped silently: "chez un vendeur où j'ai
déjà acheté" lost the familiarity rule and "CHF 80 max chaque semaine" lost the
weekly cap, both with nothing to confirm against.

THE PROPERTY. Either the restriction is compiled, or the customer is told before
confirming (`unsupported_restrictions` is non-empty). Never neither.
"""

from __future__ import annotations

import pytest

from wallet_control.policy_compiler import compile_instruction

CEILING = "authorization.billing_amount_chf"


def _ceiling(text):
    return [(r.operator, r.value) for r in compile_instruction(text).hard_rules
            if r.field == CEILING and r.scope == "purchase"]


@pytest.mark.parametrize("text", [
    "Buy the monitor I chose, max 400 CHF.",
    "Buy the monitor I chose, max 400 francs.",
    "Buy the monitor I chose, max 400 Swiss francs.",
    "Buy the monitor I chose, max Fr. 400.",
    "Buy the monitor I chose, max SFr. 400.",
    "Buy the monitor I chose, 400.- max",
    "Buy the monitor I chose, max CHF 400.-",
    "Buy the monitor I chose, no more than 400 CHF.",
    "Buy the monitor I chose, 400 CHF or less.",
])
def test_swiss_spellings_of_an_amount_compile_to_the_same_ceiling(text):
    assert _ceiling(text) == [("<=", 400.0)]


def test_swiss_thousands_separator():
    assert _ceiling("Book the flight I chose, no more than 1'200 CHF.") == [("<=", 1200.0)]
    assert _ceiling("Book the flight I chose, no more than 1’200 francs.") == [("<=", 1200.0)]


def test_under_stays_strict_in_every_spelling():
    assert _ceiling("Buy the monitor I chose for under 400 Swiss francs.") == [("<", 400.0)]


def test_a_period_amount_in_francs_is_still_a_period_amount():
    rules = compile_instruction("Order groceries, no more than 300 francs per week.").hard_rules
    assert not [r for r in rules if r.field == CEILING and r.scope == "purchase"]
    assert [(r.value, r.period_days) for r in rules if r.scope == "period"] == [(300.0, 7)]


def test_numbers_that_are_not_money_are_left_alone():
    """The 27-inch monitor, a size 42 shoe, and two items are not amounts."""
    for text in ("Buy the 27-inch monitor I chose, max CHF 400.",
                 "Replace my running shoes, size 42, at most CHF 150."):
        assert _ceiling(text) == [("<=", 400.0 if "monitor" in text else 150.0)]


@pytest.mark.parametrize("text", [
    "Buy the monitor I chose. Spend no more than 400.",
    "Buy the monitor I chose, budget 400.",
    "Buy the monitor I chose, maximum 400.",
])
def test_a_limit_without_a_currency_is_named_back_not_dropped(text):
    compiled = compile_instruction(text)
    assert not _ceiling(text)
    assert any("no spending ceiling was recognised" in u for u in compiled.unsupported_restrictions)


# ---------------------------------------------------------------- other languages

NON_ENGLISH = [
    "Achète l'écran 27 pouces que j'ai choisi, chez un vendeur où j'ai déjà acheté, pour CHF 400 maximum. "
    "N'ajoute rien que je n'ai pas demandé. Demande-moi si tu n'es pas sûr.",
    "Achète l'écran 27 pouces que j'ai choisi, 400 francs maximum.",
    "Fais les courses chaque semaine, pas plus de 120 francs par commande.",
    "Kauf den 27-Zoll-Monitor, den ich ausgewählt habe, für höchstens CHF 400. Frag mich, wenn du unsicher bist.",
    "Kaufe Lebensmittel, maximal 80 CHF pro Woche, nur bei Geschäften, wo ich schon eingekauft habe.",
    "Compra il monitor da 27 pollici che ho scelto, massimo CHF 400.",
    "Compra la spesa ogni settimana, solo nel negozio che ho già usato.",
    # mixed: an English instruction with the restriction in another language
    "Buy the monitor I chose, budget CHF 400. Achète seulement chez un magasin connu.",
    "Buy groceries, CHF 80 max chaque semaine.",
    "Buy groceries up to CHF 80, nur bei Geschäften die ich kenne.",
]


@pytest.mark.parametrize("text", NON_ENGLISH)
def test_an_instruction_the_compiler_cannot_read_is_never_silently_confirmable(text):
    assert compile_instruction(text).unsupported_restrictions, text


ENGLISH = [
    "Buy the 27-inch monitor I chose, from a seller I have bought from before, for CHF 400 or less. "
    "Do not add anything I did not ask for. Ask me when uncertain.",
    "Order our household groceries for delivery, at or below CHF 120 per order.",
    "Buy a birthday cake from the café on the corner, under CHF 60.",
    "Order dinner from Chez Marie, no more than CHF 50.",
    "Book the table at Le Pain Quotidien for four, under CHF 90.",
    "Buy the AI textbook I saved, the one with the den on the cover, max CHF 70.",
]


@pytest.mark.parametrize("text", ENGLISH)
def test_english_with_a_borrowed_word_is_not_mistaken_for_another_language(text):
    assert not any("not appear to be in English" in u
                   for u in compile_instruction(text).unsupported_restrictions), text


def test_the_official_instructions_are_read_as_english():
    from wallet_control.csv_data import load_scenario_catalogue
    for scenario_id, row in load_scenario_catalogue().items():
        unsupported = compile_instruction(row["cardholder_instruction"]).unsupported_restrictions
        assert not any("not appear to be in English" in u for u in unsupported), scenario_id

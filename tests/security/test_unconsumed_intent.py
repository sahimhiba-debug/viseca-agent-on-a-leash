"""A coverage checker built from the same vocabulary as the thing it checks cannot
see the vocabulary's own gaps.

The compiler recognises restrictions by phrase pattern, and `_COVERAGE_MARKERS`
exists to catch the ones it misses. But that list is a vocabulary too, and it is the
SAME vocabulary: the return marker is `\\breturn(?:ed|able|s)?\\b`, so

    "I can send it back within 14 days"

produces no rule, no open question, and no trace. Both the compiler and its own
safety net are blind to the phrase, for the same reason. Measured over ordinary
phrasings of restrictions this engine already supports: 20 of 20 vanished silently.
After the generated-corpus pass widened the return and period markers ("exchangeable",
"final-sale", "this week"), 16 of 20 still do: the gap narrowed by exactly the words
that were added, which is the point this file makes.

THE DIFFERENT AXIS is causal rather than lexical. Delete one word, compile again,
and see whether the policy moved. A word whose removal changes nothing was never
read. That is defined as the complement of whatever the compiler matched, so it
cannot inherit the blind spot it is looking for.

These tests pin the three things that make it worth having:

  * it detects what the vocabulary approach cannot (15 of the 16 still lost);
  * it is QUIET on sentences that are fine -- including a corpus written for a
    different purpose, so the silence is not its own test set;
  * the two attacks that landed are asserted AS FAILURES, so that "weakened the
    claim rather than the test" stays true and cannot quietly become "fixed by
    deleting the awkward cases".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.unconsumed_intent import (  # noqa: E402
    BASE, CHIT_CHAT, NO_MARKER, WELL_FORMED, is_silently_lost, measure,
)
from wallet_control.csv_data import load_scenario_catalogue  # noqa: E402
from wallet_control.unconsumed import marks, unenforced_clauses  # noqa: E402


@pytest.fixture(scope="module")
def measured():
    return measure()


def test_the_vocabulary_gap_is_real(measured):
    """If this ever shrank to nothing, either the compiler grew enormously or the
    corpus stopped containing ordinary English."""
    assert len(measured["silently_lost"]) >= 16, measured["silently_lost"]


def test_the_causal_detector_finds_what_the_vocabulary_cannot(measured):
    assert len(measured["detected"]) >= 15, measured["missed"]
    assert [c for _, c in measured["missed"]] == ["Keep it cheap."]


def test_it_is_quiet_on_the_five_official_mandates(measured):
    noisy = {k: v for k, v in measured["official_noise"].items() if v}
    assert noisy == {}, noisy


def test_it_is_quiet_on_well_formed_mandates(measured):
    noisy = {k: v for k, v in measured["well_formed_noise"].items() if v}
    assert noisy == {}, noisy


def test_it_is_quiet_on_a_corpus_written_for_another_purpose(measured):
    """`paraphrase_corpus.py` predates this module and was written to test compiler
    equivalence. Silence there is evidence that is not this module's own."""
    assert len(measured["equivalent_noise"]) >= 20
    noisy = {k: v for k, v in measured["equivalent_noise"].items() if v}
    assert noisy == {}, noisy


# ------------------------------------------------------- the attacks, kept as failures
def test_restriction_flavoured_chit_chat_still_fires(measured):
    """ATTACK, LANDED. Nothing syntactic separates "Do not worry about the weather"
    from "Do not slip anything else in", and this asserts that we did not pretend
    otherwise. The response was to weaken the CLAIM -- it reports which words
    changed nothing, which is true of the weather too, and is rendered as a receipt
    rather than a warning."""
    assert measured["chit_chat_fires"] == CHIT_CHAT


def test_noun_phrase_restrictions_are_still_missed(measured):
    """ATTACK, LANDED. "Swiss shops preferred" restricts without a single
    closed-class word. This axis sees restriction-by-grammar, not
    restriction-by-noun, and says so."""
    assert measured["no_marker_missed"] == NO_MARKER


# ------------------------------------------------------------------ the mechanism
def test_a_word_is_consumed_only_if_removing_it_moves_the_policy():
    """The definition, not a proxy for it."""
    kinds = {m.word.strip(".,"): m.kind
             for m in marks("Order our household groceries at or below CHF 120.")}
    assert kinds["groceries"] == "consumed"
    assert kinds["120"] == "consumed"
    assert kinds["our"] == "inert"
    assert kinds["household"] == "inert"


def test_the_near_miss_that_named_itself_is_fixed():
    """`unconsumed.py` reported the pronoun "it" in "return it within 14 days" as
    OBSTRUCTIVE -- delete that one word and a rule appears. The compiler was widened
    (minimally, with the preposition required and clause boundaries respected) and
    this asserts the fix, not the report."""
    from wallet_control.policy_compiler import compile_instruction
    for text in ("Order groceries, only if I can return it within 14 days.",
                 "Order groceries; they must be returnable for at least 14 days."):
        rules = [r for r in compile_instruction(text).hard_rules
                 if r.field == "order.return_window_days"]
        assert rules and int(rules[0].value) == 14, text


@pytest.mark.parametrize("text", [
    "Order our household groceries for delivery. Keep each order at or below CHF 120 "
    "including delivery, and keep the total across any seven days at or below CHF 300. "
    "Ask me when uncertain.",
    "Order groceries. No returns policy matters to me. Spend CHF 300 within 7 days.",
])
def test_widening_the_return_pattern_did_not_pair_the_wrong_number(text):
    """The last time an amount pattern was widened in this compiler it created a
    scope inversion. A rolling-window phrase carries "seven days" and must not
    become a return window."""
    from wallet_control.policy_compiler import compile_instruction
    assert not [r for r in compile_instruction(text).hard_rules
                if r.field == "order.return_window_days"], text


def test_an_empty_or_whitespace_instruction_reports_nothing():
    assert unenforced_clauses("") == []
    assert unenforced_clauses("   ") == []
    assert marks("") == []


def test_ground_truth_is_independent_of_the_detector():
    """`is_silently_lost` compiles the clause and looks at rules, open questions and
    unsupported restrictions. It never asks the detector, or the measurement would
    be this module grading its own homework."""
    assert is_silently_lost("I can send it back within 14 days.")
    assert not is_silently_lost("only if I can return it within 14 days.")
    src = Path(__file__).resolve().parents[2] / "research" / "unconsumed_intent.py"
    body = src.read_text().split("def is_silently_lost")[1].split("\ndef ")[0]
    assert "unenforced_clauses" not in body and "marks(" not in body


def test_the_read_back_is_bounded_and_says_so_rather_than_truncating():
    """One deletion per word, each a full compile, is QUADRATIC. As first shipped:
    50 words 0.05s, 500 words 2.2s, 2,000 words 35s -- a denial of service against a
    customer-facing route, introduced by this module and found by attacking it.

    The bound is stated rather than silently applied. A partial read-back that did
    not say it was partial would be this repository's own favourite defect wearing
    the badge of the feature written to expose it."""
    import time

    from fastapi.testclient import TestClient

    from wallet_control.api import app
    from wallet_control.unconsumed import MAX_WORDS, marks, too_long

    long_one = "Order groceries at or below CHF 120. " + ("please " * 5000)
    assert too_long(long_one)
    assert marks(long_one) == []
    assert unenforced_clauses(long_one) == []

    client = TestClient(app)
    start = time.time()
    body = client.post("/api/mandates/read-back", json={"instruction": long_one}).json()
    assert time.time() - start < 2.0
    assert body["analysed"] is False
    assert str(MAX_WORDS) in body["note"]
    assert body["words"] == []

    ok = client.post("/api/mandates/read-back", json={
        "instruction": "Order groceries at or below CHF 120."}).json()
    assert ok["analysed"] is True and ok["words"]


def test_every_official_mandate_is_comfortably_inside_the_bound():
    """If the bound ever cut off a real mandate it would be the wrong bound."""
    from wallet_control.unconsumed import MAX_WORDS, too_long
    official = {k: v["cardholder_instruction"] for k, v in load_scenario_catalogue().items()}
    longest = max(len(v.split()) for v in official.values())
    assert longest < MAX_WORDS / 2, longest
    assert not any(too_long(v) for v in official.values())


def test_the_read_back_measures_the_compiler_and_not_english():
    """The objection worth taking seriously: did this quietly encode what OUR regex
    compiler happens to know?

    Three compilers with deliberately different vocabularies, one sentence. If the
    mechanism measures the compiler, the struck-through words must move with it --
    and they do: NARROW reads 2 words, SHIPPED 6, WIDER 11, each difference exactly
    the vocabulary that was added. If any two read alike, the claim in
    `unconsumed.py` is wrong.

    This is also the answer to "a serious version would use a model": the probe is
    one deletion and a re-compile, it never inspects the compiler, so a model-based
    compiler is another entry in that table at one call per word. No model was
    called here and none is claimed."""
    from research.read_back_is_compiler_agnostic import COMPILERS, SENTENCE, read
    result = read()
    signatures = {label: tuple(m["consumed"]) for label, m in result.items()}
    assert len(set(signatures.values())) == len(COMPILERS), signatures

    sizes = {label: len(m["consumed"]) for label, m in result.items()}
    narrow, shipped, wider = (next(v for k, v in sizes.items() if k.startswith(p))
                              for p in ("NARROW", "SHIPPED", "WIDER"))
    assert narrow < shipped < wider, sizes

    # The added vocabulary is what moved, not something incidental.
    by = {k.split()[0]: set(v["consumed"]) for k, v in result.items()}
    assert "groceries" in by["SHIPPED"] and "groceries" not in by["NARROW"]
    assert {"send", "back", "within"} <= by["WIDER"]
    assert not {"send", "back", "within"} & by["SHIPPED"]
    assert "CHF" in by["NARROW"], "every compiler here understands a CHF figure"
    assert SENTENCE.startswith("Order")

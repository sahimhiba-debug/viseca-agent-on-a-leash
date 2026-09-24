"""Two instructions mean the same thing when they permit the same purchases.

THE GAP THIS CLOSES. `research/paraphrase_corpus.py` declares, for 43 rewordings of
the five official mandates, the relation a reasonable human reader would expect --
EQUIVALENT, STRICTER, WEAKER, DIFFERENT -- each with a reason, and deliberately not
derived from the compiler's output so the test cannot be circular. **Nothing asserted
any of it.** A corpus of claims with nothing checking them is a document.

WHY THE ACCEPTANCE SET IS THE ORACLE. The obvious check is to compile both and
compare rule lists, which is wrong twice: two different rule lists can permit exactly
the same purchases (`<= 120` and `< 120.01`), and it asks the compiler to grade
itself. So meaning is measured where it is observable -- in purchases, decided by the
real engine.

AND DOING THAT SHOWED THE THESIS TO BE INCOMPLETE. "A policy is a set of purchases"
names ONE of five things a customer delegates. Three kinds of meaning live outside A:

  1. A RATE. A is a set of single purchases; a rolling ceiling is not a property of
     any single purchase. CHF 300/7d, CHF 3000/7d and CHF 300/30d have IDENTICAL
     acceptance sets (|A| = 145 each). Purchases-per-window separates the first two;
     CHF-per-day separates the last two. Neither is derivable from A.

  2. WHAT WILL BE ASKED. A counts approvals, so changing `ask` to `decline` -- the
     strictest edit available -- moved nothing in it.

  3. WHAT COULD NOT BE EXPRESSED AT ALL. "Buy ONE grocery item" and "buy TWENTY"
     compile identically, because the rule format has no quantity field. The compiler
     discloses this (`unsupported_restrictions`, which blocks automatic confirmation)
     but a signature ignoring it called two clearly different instructions the same.

So the delegation is (approved, asked, per-window ceiling, pace, what could not be
expressed), and the thesis names the first.

TWO FAILURES THAT LOOK ALIKE AND ARE NOT. When two instructions have the same
signature but a reader would distinguish them, it matters enormously whether the
COMPILED RULES differ:

    rules differ, signature does not  ->  this WORLD has no witness. `Decline when
                                          unsure` really is stricter; no basket in
                                          the grocery enumeration is ever `unknown`,
                                          so nothing observes it. A statement about
                                          the enumeration, not the compiler.
    rules identical                   ->  the compiler is genuinely blind.

Conflating them would be a false accusation against the compiler, so they are counted
separately and only the second is treated as a defect.
"""

from __future__ import annotations

import pytest

from research.paraphrase_corpus import CASES, EQUIVALENT
from research.semantic_stability import sweep


@pytest.fixture(scope="module")
def rows():
    return sweep()


def test_the_corpus_is_big_enough_to_mean_something(rows):
    assert len(rows) == len(CASES) >= 40
    assert len({r["relation"] for r in rows}) == 4


def test_no_paraphrase_changes_what_the_customer_delegated(rows):
    """EQUIVALENT means EQUIVALENT. A rewording a reader would not distinguish must
    not move the approved set, the asked set, the pace, or what went unexpressed.

    This is the half that protects the product from feeling arbitrary: a customer who
    writes "no more than CHF 20" and a customer who writes "CHF 20 or less" have
    delegated the same thing and must be told so."""
    broken = [(r["variant"], r["failure"]) for r in rows
              if r["relation"] == EQUIVALENT and r["failure"]]
    assert broken == [], broken


def test_the_compiler_is_blind_nowhere(rows):
    """It used to be blind in exactly one declared place: "buy one grocery item" and
    "buy twenty" compiled to the same policy, on the reading that the rule format
    could not express a quantity. ONE is now a one-off errand rule, so the two
    compile differently (twenty is still disclosed as not enforced).

    Asserted as an exact count so that a blind spot cannot appear unnoticed."""
    blind = [r for r in rows if r["failure"] == "false equivalence"]
    assert blind == [], [(r["relation"], r["variant"][:70]) for r in blind]


def test_no_reworded_instruction_is_enforced_in_the_wrong_direction(rows):
    """The dangerous shape: an instruction a reader would call STRICTER that the
    wallet enforces more permissively, or the reverse. Neither exists in the corpus,
    and a regression here is worse than a blind spot -- the customer tightened
    something and the wallet loosened it."""
    wrong = [(r["relation"], r["variant"], r["failure"]) for r in rows
             if r["failure"] in ("not stricter", "not weaker")]
    assert wrong == [], wrong


def test_the_compiler_is_not_sensitive_to_wording_that_does_not_matter(rows):
    """The mirror failure. A false DISTINCTION makes the product feel arbitrary --
    the same request, typed two ways, yielding two delegations."""
    fussy = [(r["variant"], r["why"]) for r in rows
             if r["failure"] == "false distinction"]
    assert fussy == [], fussy

"""Which words of the customer's sentence did no rule consume?

THE PROBLEM WITH A SAFETY NET WOVEN FROM THE SAME THREAD

The compiler recognises restrictions by phrase pattern, and it already has a second
layer for the ones it misses: `_COVERAGE_MARKERS` detects that the customer used
restrictive language of a given KIND, and says so when no rule of that kind exists.
Its own comment is the honest statement of why that is not enough --

    "Broadening the patterns fixes the paraphrases we happened to think of, and
     nothing else; there are indefinitely many ways to write a restriction."

-- but the marker list is itself a vocabulary, and it shares its vocabulary with the
compiler. The return-window marker is `\\breturn(?:ed|able|s)?\\b`. So

    "only buy things I can return within 14 days"      -> a rule
    "I can send it back within 14 days"                -> NOTHING. No rule, no
                                                          question, no trace.

Both the compiler and the checker that exists to catch the compiler are blind to the
same phrase, for the same reason. **A coverage checker built from the same vocabulary
as the thing it checks cannot see the vocabulary's own gaps.** Measured across
ordinary phrasings of restrictions this engine already supports, 19 of 23 produced
no rule AND no mention (`research/unconsumed_intent.py`).

THE DIFFERENT AXIS

Do not ask what the words mean. Ask **whether they did anything**.

Delete one word and compile again. If the policy is unchanged -- same rules, same
guidance, same open questions -- that word was INERT: the compiler did not read it.
If a rule disappears, the word was CONSUMED. If a rule APPEARS, the word was
OBSTRUCTIVE -- the compiler nearly understood the clause and that word is what
stopped it.

This is a causal measurement, not a pattern. It is defined as the complement of
whatever the compiler matched, so it cannot share the compiler's blind spot: the
compiler's ignorance is precisely what it reports.

    "Order groceries, only if I can return it within 14 days."
         return  consumed          it  OBSTRUCTIVE     <- delete "it" and a rule appears

MEASURED (`research/unconsumed_intent.py`)

    19 of 20 silently-lost restrictions        detected and quoted back verbatim
    0 false positives on the five official mandates
    0 on 21 EQUIVALENT paraphrases from `paraphrase_corpus.py` -- a corpus written
      for a different purpose, so it is not this module's own test set

ATTACKED, AND THE CLAIM WAS WEAKENED RATHER THAN THE TEST

Two attacks landed, and both are stated here rather than fixed, because fixing
either needs semantics this deliberately does not have.

  RESTRICTION-FLAVOURED TEXT THAT RESTRICTS NOTHING fires, 5 out of 5.
      "Do not worry about the weather." "There is nothing in the fridge."
      Inert, and carrying a restrictive marker. Nothing syntactic separates them
      from "Do not slip anything else in", and so this module no longer claims to
      find unenforced RESTRICTIONS. It reports which words CHANGED NOTHING, which
      is exactly what it measures and is true of the weather too. Rendered as a
      receipt -- here is what we read, here is what we did not -- rather than as a
      warning, a harmless extra line costs a shrug; as a red alert it would train
      people to click through, and then it would protect nobody.

  RESTRICTIONS WITH NO CLOSED-CLASS MARKER are missed, 5 out of 5.
      "Swiss shops preferred." "Returnable items please." "Keep it cheap."
      A noun phrase can restrict without a single function word, and no syntactic
      signal distinguishes one from a remark. This axis sees restriction-by-grammar
      and not restriction-by-noun. It is a floor under the vocabulary approach, not
      a ceiling over it.

WHAT KEEPS IT FROM CRYING WOLF

A clause is emphasised only if NOTHING in it was consumed -- a clause the compiler
partly read is a clause it read -- and only if it contains a restrictive marker: a
closed-class function word. That list is GRAMMAR, not domain vocabulary ("only",
"never", "within", "at most"), which is why it does not inherit the gap it is
looking for: the compiler's blind spots are in content words ("send back" for
"return"), and English has no open-ended supply of ways to say "only".

DECIDES NOTHING. It adds no rule and changes no verdict. It names the customer's own
words back to them, before they confirm, and says we did not act on these.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .policy_compiler import compile_instruction

_WORD = re.compile(r"\S+")

# One deletion per word, each one a full compile, makes this QUADRATIC in the
# instruction. Measured on the endpoint as shipped: 50 words 0.05s, 500 words 2.2s,
# 2,000 words 35s -- a denial of service against a customer-facing route, introduced
# by this module and found by attacking it rather than by using it.
#
# The bound is on the WORK, and it is stated rather than silently truncating: a
# partial read-back that did not say it was partial would be this repository's own
# favourite defect, an absence filled in with something that looks complete. The
# longest of the five official mandates is 40 words.
MAX_WORDS = 150

# Clause boundaries: a full stop, a semicolon, a comma, or a coordinating "and"/"but"
# joining two predicates. Deliberately crude -- a clause that is split too finely
# reports a shorter quote, which is a cosmetic loss, while one that is not split at
# all would let a consumed word elsewhere in the sentence vouch for an ignored
# requirement, which is the failure that matters.
_CLAUSE_SPLIT = re.compile(r"(?<=[.;:!?])\s+|,\s*|\s+(?:and|but)\s+", re.IGNORECASE)

# Closed-class markers of restriction. GRAMMAR, not domain vocabulary -- that is the
# whole reason this check does not inherit the compiler's blind spot. Each entry is
# a word English uses to narrow what is permitted, and the list is short because the
# closed classes of a language are short.
_RESTRICTIVE = re.compile(
    r"\b(?:only|just|never|no|not|nothing|none|nowhere|cannot|can't|don't|do\s+not|"
    r"must|mustn't|unless|except|solely|exclusively|"
    r"within|at\s+least|at\s+most|no\s+more\s+than|no\s+less\s+than|up\s+to|"
    r"maximum|minimum|max|cap|limit|stick\s+to|avoid|stop|pause)\b",
    re.IGNORECASE)

# Words too common to make a clause "about" anything. Used only to decide whether a
# flagged clause has any substance worth quoting.
_FILLER = frozenset("a an the and or but of to in on for from with by is are was be "
                    "been it its this that these those i me my we our you your they "
                    "them please thanks thank".split())


@dataclass(frozen=True)
class Mark:
    word: str
    kind: str          # "consumed" | "inert" | "obstructive"
    start: int
    end: int


def _signature(instruction: str):
    compiled = compile_instruction(instruction)
    rules = frozenset((r.field, r.operator, str(r.value), r.scope or "", r.period_days or 0)
                      for r in compiled.hard_rules)
    explained = (compiled.uncertainty_policy.value,
                 frozenset(compiled.guidance),
                 frozenset(compiled.open_questions),
                 frozenset(compiled.unsupported_restrictions))
    return rules, explained


def too_long(instruction: str) -> bool:
    return len(_WORD.findall(instruction)) > MAX_WORDS


def marks(instruction: str) -> list[Mark]:
    """One deletion per word, each re-compiled. O(n) compiles; they are regex passes
    over a sentence, and the alternative -- threading a span through every pattern in
    the compiler -- would measure what the code CLAIMS to have read rather than what
    changed the answer.

    Returns nothing at all past `MAX_WORDS`. Callers ask `too_long()` and say so.
    """
    if too_long(instruction):
        return []
    base_rules, base_explained = _signature(instruction)
    out: list[Mark] = []
    for match in _WORD.finditer(instruction):
        variant = (instruction[:match.start()] + instruction[match.end():])
        variant = re.sub(r"\s{2,}", " ", variant).strip()
        rules, explained = _signature(variant)
        if rules > base_rules:
            kind = "obstructive"
        elif rules != base_rules or explained != base_explained:
            kind = "consumed"
        else:
            kind = "inert"
        out.append(Mark(match.group(), kind, match.start(), match.end()))
    return out


def unenforced_clauses(instruction: str) -> list[dict[str, Any]]:
    """Clauses the compiler demonstrably did not read, that demonstrably restrict.

    Empty is the common and correct answer. A sentence every part of which moved the
    policy has nothing to report, and so does a sentence with no restrictive language
    in the part that did not.
    """
    if not instruction.strip() or too_long(instruction):
        return []
    found = marks(instruction)
    out: list[dict[str, Any]] = []
    cursor = 0
    for piece in _CLAUSE_SPLIT.split(instruction):
        if piece is None:
            continue
        start = instruction.find(piece, cursor)
        if start < 0 or not piece.strip():
            continue
        cursor, end = start + len(piece), start + len(piece)
        inside = [m for m in found if m.start >= start and m.end <= end]
        if not inside or any(m.kind == "consumed" for m in inside):
            continue
        if not _RESTRICTIVE.search(piece):
            continue
        substantive = [m.word.strip(".,;:!?").lower() for m in inside]
        if len([w for w in substantive if w and w not in _FILLER]) < 2:
            continue
        out.append({
            "clause": piece.strip(),
            "obstructive": [m.word.strip(".,;:!?") for m in inside if m.kind == "obstructive"],
        })
    return out

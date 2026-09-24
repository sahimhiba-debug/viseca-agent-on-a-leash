"""When a sentence has two defensible readings, find the purchase that separates them.

The compiler already detects ambiguity and explains it in prose: "the instruction
mentions more than one per-order amount; the smallest was used defensively". That
is honest and nearly useless, because it asks the customer to imagine a
consequence. People do not audit prose about hypothetical purchases; they agree to
it.

So do not describe the ambiguity. **Find the purchase it changes.** Compile the
sentence twice -- once as the compiler read it, once as the other defensible
reading -- and search for a basket the two policies judge differently. That basket
is a witness: concrete proof the sentence is underdetermined, and the only question
a customer can actually answer.

    "Order groceries, under CHF 120."
        as compiled      CHF 120.00 is too much   -> BLOCK
        also defensible  CHF 120.00 is fine       -> ALLOW
        WITNESS: a basket costing exactly CHF 120.00

THIS MODULE DECIDES NOTHING. It is advisory, like the compiler's open questions,
and it lives in the runtime for the same reason they do: it is shown to the
customer before they confirm. Every verdict it reports comes from the real engine
deciding a real event -- if it inspected rules instead, it would prove nothing
about what the wallet would actually do.

THE PROPERTY THAT MATTERS MOST IS THE SILENCE. A disambiguator that fires on clear
language teaches people to click through it, and then it protects nobody. "at or
below CHF 120" is not ambiguous and this module says nothing about it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Callable

from .mandate import HardRule
from .policy_compiler import compile_instruction
from .disagreement import diverge_from_readings
from .witness import Purchase, judge


@dataclass(frozen=True)
class Reading:
    """One defensible interpretation, as a transformation of the compiled rules."""

    key: str
    question: str
    labels: Callable[[list[HardRule]], tuple[str, str]]
    transform: Callable[[list[HardRule]], list[HardRule] | None]
    applies: Callable[[str], bool] | None = None


def _flip_strictness(rules):
    out, changed = [], False
    for rule in rules:
        if (rule.field == "authorization.billing_amount_chf" and rule.scope == "purchase"
                and rule.operator in ("<", "<=")):
            out.append(replace(rule, operator="<=" if rule.operator == "<" else "<"))
            changed = True
        else:
            out.append(rule)
    return out if changed else None


def _period_as_per_order(rules):
    out, changed = [], False
    for rule in rules:
        if rule.field == "authorization.billing_amount_chf" and rule.scope == "period":
            out.append(replace(rule, scope="purchase", period_days=None))
            changed = True
        else:
            out.append(rule)
    return out if changed else None


def _strictness_labels(rules):
    operator = next((r.operator for r in rules
                     if r.field == "authorization.billing_amount_chf"
                     and r.scope == "purchase"), "<=")
    strict, inclusive = "the amount itself is too much", "the amount itself is fine"
    return (strict, inclusive) if operator == "<" else (inclusive, strict)


# "at or below", "or less" and "no more than" all say plainly that the amount is
# included. Asking about them is crying wolf.
_VAGUE_BOUND = re.compile(r"\b(?:under|below|less\s+than)\b", re.IGNORECASE)
_EXPLICIT_BOUND = re.compile(
    r"\b(?:at\s+or\s+below|or\s+less|at\s+most|no\s+more\s+than|up\s+to)\b", re.IGNORECASE)


def _bound_is_vague(instruction: str) -> bool:
    return bool(_VAGUE_BOUND.search(instruction)) and not _EXPLICIT_BOUND.search(instruction)


READINGS: tuple[Reading, ...] = (
    Reading("strictness",
            "Is an order of exactly that amount allowed, or must it be below?",
            _strictness_labels, _flip_strictness, _bound_is_vague),
    Reading("period_scope",
            "Is that a budget for the week, or a ceiling for each order?",
            lambda _r: ("a rolling budget for the period", "a ceiling on each order"),
            _period_as_per_order),
    # A reading that separates EVERY sentence is not a reading. "Did naming the
    # goods restrict what may be bought, or only describe it?" did exactly that and
    # was deleted: "order our household groceries" plainly restricts to groceries.
)


def _judge(rules, uncertainty, amount: float, *, category="groceries", repeats=1,
           unsupported=None) -> str:
    """The engine's verdict on one hypothetical purchase -- `witness.judge`, with
    this module's own question spelled out in its own vocabulary. The apparatus
    (throwaway mandate, synthetic event, real engine) is shared with `silence.py`
    rather than copied, so a change to what a hypothetical purchase looks like
    cannot leave the two witnesses disagreeing about the same wallet."""
    return judge(rules, uncertainty,
                 Purchase(amount=amount, category=category, repeats=repeats),
                 unsupported=unsupported)


def find_witness(instruction: str, reading: Reading) -> dict[str, Any] | None:
    """A concrete purchase the two readings judge differently, or None.

    THIS USED TO GUESS WHERE TO LOOK. It tried a handful of amounts derived from the
    rules -- the ceiling, a rappen either side, a repeated fraction -- which finds a
    witness when one sits on a boundary and can say nothing about how much is at
    stake. It now searches the whole enumerated world through `disagreement.diverge`,
    so it reports the CHEAPEST separating purchase and HOW MANY there are.

    The count is the part that changed the product. "Your sentence is ambiguous"
    is a shrug; "your sentence is ambiguous about 470 of 595 purchases, the cheapest
    being three orders of CHF 87" is a question someone can answer.
    """
    if reading.applies is not None and not reading.applies(instruction):
        return None
    compiled = compile_instruction(instruction)
    rules_a = list(compiled.hard_rules)
    if reading.transform(rules_a) is None:
        return None

    divergence = diverge_from_readings(instruction, reading.transform)
    if divergence is None or divergence.cheapest is None:
        return None

    cheapest = divergence.cheapest
    return {"reading": reading, "labels": reading.labels(rules_a),
            "amount": cheapest["chf"], "repeats": cheapest["repeats"],
            "category": "groceries",
            "count": divergence.count, "universe": divergence.universe,
            "verdict_a": cheapest["as_compiled"], "verdict_b": cheapest["alternative"]}


def witnesses(instruction: str) -> list[dict[str, Any]]:
    return [w for w in (find_witness(instruction, r) for r in READINGS) if w]

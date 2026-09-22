"""Two readings of one sentence, and every purchase they judge differently.

WHY DISAGREEMENT, AND WHERE IT IS THE ONLY SIGNAL AVAILABLE

Disagreement between two planners about WHAT TO BUY carries no information: they
optimise different things and both are fine. Disagreement about WHETHER SOMETHING IS
ALLOWED carries none either: neither has authority and the engine knows the answer.

Disagreement is informative in exactly one place -- where there is no ground truth.
In this system there is exactly one such place: **what the customer meant.** A
sentence has no correct compilation; it has defensible ones, and the customer is the
only instrument that can read the result.

So: compile the sentence twice, and search for the purchases the two policies decide
differently. Each one is a question the customer can actually answer, and the count
is how much of their money the ambiguity is worth.

    "Order groceries, under CHF 120."
        two readings disagree about   1 of 595 purchases   cheapest: CHF 120.00

WHAT THIS REPLACES

`ambiguity.py` tries a handful of candidate amounts derived from the rules -- the
ceiling, a rappen either side, a repeated fraction. That finds a witness when one
exists near a boundary and says nothing about how much is at stake. This searches
the whole enumerated world (`scope.py`), so it reports the cheapest separating
purchase AND how many there are.

WHERE A MODEL WOULD GO, AND WHY IT IS SAFE THERE

`READINGS` in `ambiguity.py` is a hand-written table: two entries, each a
transformation someone thought of. A second COMPILER -- including a model-based one
-- would generate readings for constructs nobody thought of, and this module needs
no table at all: it takes two policies and finds where they part.

That is the one place a language model earns its keep in this architecture, and the
only place it can be given real freedom:

    it proposes a HYPOTHESIS ABOUT MEANING, never a decision;
    the real engine adjudicates by finding a concrete purchase;
    the customer resolves it.

A wrong model produces an extra question. It cannot produce a wrong enforcement,
because nothing it emits reaches a confirmed mandate without the customer saying so.
That is the same draft/verify shape one level up from the agent, and it is why
`compile_a` and `compile_b` are parameters here rather than imports.

NO MODEL HAS BEEN RUN. `api.publicai.co/v1` answers 401 without a key. The seam is
here and is exercised by two deliberately different hand-written compilers.

DECIDES NOTHING.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from .mandate import MandateSnapshot, UncertaintyPolicy
from .policy_compiler import compile_instruction
from .scope import FAMILIAR, _categories, _world
from .witness import PERMISSIVENESS, judge_sequence, snapshot

Compiler = Callable[[str], Any]


@dataclass(frozen=True)
class Divergence:
    """Every purchase two readings decide differently, and the cheapest of them."""

    count: int
    universe: int
    cheapest: dict[str, Any] | None
    widest: dict[str, Any] | None      # where the verdicts are furthest apart

    def as_dict(self) -> dict[str, Any]:
        return {"count": self.count, "universe": self.universe,
                "cheapest": self.cheapest, "widest": self.widest}


def _mandate_from(compiled, instruction: str,
                  uncertainty: UncertaintyPolicy | None) -> MandateSnapshot:
    return snapshot(list(compiled.hard_rules),
                    uncertainty or compiled.uncertainty_policy,
                    list(getattr(compiled, "unsupported_restrictions", []) or []))


#  1 -- a single purchase separates the readings.
#  2, 3 -- only a SEQUENCE does. A weekly budget and a per-order ceiling of the same
#  figure agree on every one order and part company on the third, so a search over
#  baskets alone is blind to the commonest ambiguity in this vocabulary. Three is
#  enough to expose it and keeps the search at ~60 ms.
REPEATS = (1, 2, 3)


def diverge(instruction: str, compile_a: Compiler, compile_b: Compiler, *,
            uncertainty: UncertaintyPolicy | None = None) -> Divergence:
    """Search the whole enumerated world for purchases the two readings judge apart.

    Both verdicts come from the REAL engine deciding a real event. A divergence
    computed by comparing rule objects would prove something about the rules and
    nothing about what the wallet would do.
    """
    first, second = compile_a(instruction), compile_b(instruction)
    mandate_a = _mandate_from(first, instruction, uncertainty)
    mandate_b = _mandate_from(second, instruction, uncertainty)
    category = _categories(list(first.hard_rules)) if first.hard_rules else "groceries"

    world = _world(category)
    count = 0
    cheapest = widest = None
    for index, (merchant, combo) in enumerate(world):
        for repeats in REPEATS:
            verdict_a = judge_sequence(mandate_a, index, merchant, category, combo,
                                       repeats, familiar=FAMILIAR)
            verdict_b = judge_sequence(mandate_b, index, merchant, category, combo,
                                       repeats, familiar=FAMILIAR)
            if verdict_a == verdict_b:
                continue
            count += 1
            price = float(sum((p for _id, _name, p in combo), Decimal("0")))
            gap = abs(PERMISSIVENESS[verdict_a] - PERMISSIVENESS[verdict_b])
            row = {"chf": price, "lines": len(combo), "merchant": merchant,
                   "items": [name for _id, name, _p in combo], "repeats": repeats,
                   "as_compiled": verdict_a, "alternative": verdict_b, "gap": gap}
            break_after = True
            if cheapest is None or (price, repeats) < (cheapest["chf"], cheapest["repeats"]):
                cheapest = row
            if widest is None or gap > widest["gap"] or (gap == widest["gap"]
                                                         and price < widest["chf"]):
                widest = row
            if break_after:
                # One divergence per basket: the SAME basket repeated is the same
                # question asked louder, and counting it three times would inflate
                # the figure the customer is shown.
                break
    return Divergence(count=count, universe=len(world), cheapest=cheapest, widest=widest)


def diverge_from_readings(instruction: str, transform) -> Divergence | None:
    """The same search, driven by `ambiguity.READINGS`' rule transformations rather
    than by a second compiler. Returns None when the reading does not apply to this
    sentence at all."""
    compiled = compile_instruction(instruction)
    alternative = transform(list(compiled.hard_rules))
    if alternative is None:
        return None

    class _AsCompiled:
        hard_rules = list(compiled.hard_rules)
        uncertainty_policy = compiled.uncertainty_policy
        unsupported_restrictions = list(compiled.unsupported_restrictions)

    class _Alternative:
        hard_rules = alternative
        uncertainty_policy = compiled.uncertainty_policy
        unsupported_restrictions = list(compiled.unsupported_restrictions)

    return diverge(instruction, lambda _t: _AsCompiled, lambda _t: _Alternative)

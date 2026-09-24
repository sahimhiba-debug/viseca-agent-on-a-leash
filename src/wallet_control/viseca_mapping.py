"""The one place the internal decision vocabulary is translated to the official
Viseca decision vocabulary.

Kept deliberately explicit and separate from the decision engine: `ALLOW`/`REVIEW`/
`BLOCK` are this codebase's own words for "what should happen", chosen so nothing
inside the engine can be misread as "the API's `approve` means the money moved"
(it does not -- see payment.py and docs/VISECA_INTEGRATION.md). `approve`/`decline`/`step_up` are the
official wire values (technical_details.md, table in step 4) and appear nowhere
else in this package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Literal

if TYPE_CHECKING:
    from .rules import RuleEvaluation

Decision = Literal["allow", "review", "block"]
VisecaDecision = Literal["approve", "decline", "step_up"]

_TO_VISECA: dict[Decision, str] = {"allow": "approve", "review": "step_up", "block": "decline"}
_FROM_VISECA: dict[str, Decision] = {v: k for k, v in _TO_VISECA.items()}


def to_viseca_decision(decision: Decision) -> str:
    return _TO_VISECA[decision]


def from_viseca_decision(value: str) -> Decision:
    return _FROM_VISECA[value]


def to_wire_evidence(evaluations: "Iterable[RuleEvaluation]") -> list[dict[str, Any]]:
    """The `evidence` list as the hosted API accepts it: one JSON object per check.

    technical_details.md names the field but not its element shape. The sandbox
    answers a list of strings with 422 ("Input should be a valid dictionary"), which
    is how SCEN0000's first live run timed out into a decline with an ALLOW in hand.
    """
    return [
        {"field": e.rule.field, "outcome": e.outcome, "detail": e.detail, "source": e.source}
        for e in evaluations
    ]

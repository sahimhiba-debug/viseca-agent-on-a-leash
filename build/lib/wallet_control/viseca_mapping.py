"""The one place the internal decision vocabulary is translated to the official
Viseca decision vocabulary.

Kept deliberately explicit and separate from the decision engine: `ALLOW`/`REVIEW`/
`BLOCK` are this codebase's own words for "what should happen", chosen so nothing
inside the engine can be misread as "the API's `approve` means the money moved"
(it does not -- see docs/PAYMENT_BOUNDARY.md). `approve`/`decline`/`step_up` are the
official wire values (technical_details.md, table in step 4) and appear nowhere
else in this package.
"""

from __future__ import annotations

from typing import Literal

Decision = Literal["allow", "review", "block"]
VisecaDecision = Literal["approve", "decline", "step_up"]

_TO_VISECA: dict[Decision, str] = {"allow": "approve", "review": "step_up", "block": "decline"}
_FROM_VISECA: dict[str, Decision] = {v: k for k, v in _TO_VISECA.items()}


def to_viseca_decision(decision: Decision) -> str:
    return _TO_VISECA[decision]


def from_viseca_decision(value: str) -> Decision:
    return _FROM_VISECA[value]

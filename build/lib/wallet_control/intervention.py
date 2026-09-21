"""The local "Intervention" layer: a human-facing gloss on a decision.

This is NOT part of the official Viseca API. The API only knows `approve` /
`decline` / `step_up` (see `viseca_mapping.py`). `Intervention` is purely a local
concept for our own UI and audit trail, distinguishing *why* a REVIEW/BLOCK
happened in a way a customer can act on -- which the challenge brief asks for
directly: "clearly highlight any uncertainty" and let the customer "understand
what evidence it considered, why it acted."

It is derived strictly *from* an already-made decision plus its rule evaluations;
it never feeds back into the decision itself.

  allow            -- approved outright.
  ask_missing_fact -- paused because information needed to check a rule was
                       missing (e.g. no return-window was stated). Resolvable by
                       getting that fact, not by raising a limit.
  ask_this_time    -- paused because of a scoped, situational judgement call
                       (e.g. a suspected duplicate, a borderline session signal)
                       that a human should confirm for *this* purchase only.
  never            -- a hard rule was clearly violated. Not resolvable by
                       confirming this purchase; the underlying rule would need to
                       change, which only the customer can do via the mandate.
"""

from __future__ import annotations

from typing import Literal

from .rules import RuleEvaluation
from .viseca_mapping import Decision

InterventionKind = Literal["allow", "ask_missing_fact", "ask_this_time", "never"]


def classify_intervention(decision: Decision, evaluations: tuple[RuleEvaluation, ...]) -> InterventionKind:
    if decision == "allow":
        return "allow"
    if decision == "block":
        return "never"
    # decision == "review"
    if any(e.outcome == "unknown" for e in evaluations):
        return "ask_missing_fact"
    return "ask_this_time"

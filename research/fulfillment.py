"""RESEARCH MODULE -- a parallel observer, deliberately NOT wired into the official
decision path. `decision_engine.evaluate_authorization` does not import this, and
the official replay is unchanged by its existence. See
docs/ARCHITECTURAL_BREAKTHROUGH.md.

--------------------------------------------------------------------------------
The gap it exists to expose
--------------------------------------------------------------------------------

The official rule vocabulary contains exactly one CONSUMABLE resource: rolling
spend (`scope="period"`). Everything else -- amount ceilings, merchant rules, item
category, size, return window -- is a stateless PREDICATE, re-evaluated from
scratch on every purchase with no memory of what the agent has already done.

That is the whole gap. A mandate is treated as a standing permission, so a job the
customer described once can be performed any number of times. Measured on the
official data, with every purchase passing every check:

    SCEN0004  "Buy THE 27-inch monitor I chose"  ->  5 monitors, CHF 1,729.40
    SCEN0002  "REPLACE my worn road-running shoes" ->  3 pairs,   CHF   512.00

Nothing catches it. The near-duplicate check is a 60-minute window on an identical
basket; these purchases are days apart. Each one individually is exactly what the
customer asked for. The aggregate is not.

--------------------------------------------------------------------------------
The reframing
--------------------------------------------------------------------------------

A mandate is not only a predicate over a purchase. It also carries a SHAPE -- how
many times the job it describes may be performed:

    ONE_SHOT   "buy the monitor I chose", "replace my shoes", "buy one item"
               A definite, singular job. Fulfilled once, then finished.

    RECURRING  "order our household groceries", "restock the kitchen"
               A job that repeats by nature.

    STANDING   "the agent may buy clothing for me, up to CHF 250 per order"
               An open permission, deliberately granted.

    UNCLEAR    the classifier has no confident evidence; it says nothing.

Only ONE_SHOT mandates can be *finished*, and only for those does this module ever
raise a concern.

--------------------------------------------------------------------------------
Three design rules, each load-bearing
--------------------------------------------------------------------------------

1. It NEVER blocks. A second fulfillment is a question for the customer, not a
   refusal -- the same philosophy as the engine's uncertainty handling. A
   misclassification therefore costs one confirmation prompt, never a wrongly
   refused purchase.

2. It is DETERMINISTIC and reports its own evidence. No model, no score. Every
   verdict names the phrase it was derived from, so a customer or a judge can
   disagree with it.

3. It says nothing when unsure. UNCLEAR yields no opinion at all, which is what
   keeps it quiet on the two official mandates that are legitimately repeatable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from wallet_control.mandate import MandateSnapshot
from wallet_control.state import RunState


class MandateShape(str, Enum):
    ONE_SHOT = "one_shot"
    RECURRING = "recurring"
    STANDING = "standing"
    UNCLEAR = "unclear"


# Ordered by precedence: an explicit standing grant beats a recurring phrase, which
# beats a singular one ("order our weekly groceries" is recurring even though
# "our" is definite). Each pattern is paired with the human-readable reason it
# contributes, because an unexplained classification is not reviewable.
_STANDING_PATTERNS: list[tuple[str, str]] = [
    (r"\bmay\s+buy\b", "'may buy' grants an open permission rather than describing one job"),
    (r"\bmay\s+purchase\b", "'may purchase' grants an open permission"),
    (r"\bwhenever\b|\bany\s*time\b|\bas\s+needed\b", "an open-ended time phrase"),
    (r"\bper\s+order\b", "'per order' prices an unbounded series of orders"),
]

_RECURRING_PATTERNS: list[tuple[str, str]] = [
    (r"\border\s+our\b", "'order our ...' describes a standing household order"),
    (r"\bweekly\b|\bevery\s+week\b|\beach\s+week\b|\bmonthly\b", "an explicit repetition interval"),
    (r"\brestock\b|\btop\s+up\b|\bkeep\s+.{0,20}stocked\b", "a restocking verb"),
    (r"\bhousehold\s+groceries\b|\bgroceries\s+for\s+delivery\b", "a recurring household supply"),
]

_ONE_SHOT_PATTERNS: list[tuple[str, str]] = [
    (r"\breplace\s+my\b", "'replace my ...' describes a single replacement"),
    (r"\bthe\b[^.]{0,40}\bi\s+chose\b", "'the ... I chose' names one specific item already selected"),
    # "one of each" / "one of every" / "one per ..." is a DISTRIBUTIVE quantity: it
    # says how many of each thing, over a list whose length is not one. Reading it as
    # a single job is wrong, and the economic-delegation pass made that wrongness
    # expensive: before anchorless one-shot mandates counted purchases, a
    # misclassification here was silent and free. Now it would question every
    # purchase after the first -- and a control that interrupts a customer nine times
    # for a nine-item shopping list teaches them to dismiss it, which costs more than
    # it protects.
    (r"\b(?:buy|purchase)\s+one\b(?!\s+of\s+(?:each|every)\b)(?!\s+per\b)",
     "'buy one' states the quantity explicitly"),
    (r"\bthe\s+one\s+i\b", "'the one I ...' names a single item"),
]


@dataclass(frozen=True)
class ShapeClassification:
    shape: MandateShape
    evidence: str

    def as_dict(self) -> dict:
        return {"shape": self.shape.value, "evidence": self.evidence}


def classify_shape(instruction: str) -> ShapeClassification:
    """Deterministically classify how many times a mandate's job may be performed.

    Precedence is standing > recurring > one-shot, so an explicit open grant is
    never mistaken for a single job. Absent any evidence the answer is UNCLEAR,
    and an UNCLEAR mandate is never second-guessed.
    """
    text = (instruction or "").lower()
    for patterns, shape in (
        (_STANDING_PATTERNS, MandateShape.STANDING),
        (_RECURRING_PATTERNS, MandateShape.RECURRING),
        (_ONE_SHOT_PATTERNS, MandateShape.ONE_SHOT),
    ):
        for pattern, reason in patterns:
            if re.search(pattern, text):
                return ShapeClassification(shape, reason)
    return ShapeClassification(MandateShape.UNCLEAR, "no phrase indicating how often this job may be performed")


Verdict = Literal["first_fulfilment", "already_fulfilled", "over_fulfilled", "not_applicable"]


@dataclass(frozen=True)
class FulfilmentVerdict:
    verdict: Verdict
    shape: MandateShape
    detail: str
    prior_authorization_id: str | None = None

    @property
    def would_ask_customer(self) -> bool:
        """The only action this module ever recommends: put it to the customer."""
        return self.verdict in ("already_fulfilled", "over_fulfilled")

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "shape": self.shape.value,
            "detail": self.detail,
            "prior_authorization_id": self.prior_authorization_id,
            "would_ask_customer": self.would_ask_customer,
        }


def job_anchor(mandate: MandateSnapshot) -> str | None:
    """The SPECIFIC product phrase identifying this job, if the customer gave one.

    A category is not specific enough. "One ordinary grocery item" and "clothing"
    name a kind, not a job -- counting against them would make a basket of two
    different groceries look like the job done twice. Only a distinguishing phrase
    (`item.name_contains`) identifies a job well enough to say it has been
    performed; without one this module says nothing at all.

    Using the customer's own compiled anchor is also what makes the check hard to
    evade rather than merely hard to trigger: to propose a purchase that does not
    match it, a compromised agent must propose something outside the customer's
    item constraints -- which the ordinary rule engine already blocks. Evading the
    fulfilment check costs the agent the policy check, and vice versa.
    """
    for rule in mandate.hard_rules:
        if rule.field == "item.name_contains":
            return str(rule.value).lower()
    return None


def units_in_basket(basket_key, anchor: str | None) -> int:
    """How many times one recorded purchase performs the job, read from the
    PERSISTED basket fingerprint `(item_id, item_name, quantity, ...)`."""
    if anchor is None:
        return 1
    return sum(int(line[2]) for line in basket_key if anchor in str(line[1]).lower()) or 1


def fulfilment_state(
    mandate: MandateSnapshot, state: RunState, *, assessing: str | None = None
) -> FulfilmentVerdict:
    """Derive fulfilment from the run's persisted decision ledger. Stateless.

    This replaced a stateful `FulfilmentMonitor` that kept its own tally, and the
    replacement is the actual research result of this pass. That monitor
    reproduced, exactly, the defect class found three times in `PaymentAuthority`:

      * a human-approved step-up never reached it, because it was fed from engine
        ALLOWs rather than from the decision of record (the shape of V2);
      * a restart reset it to zero, because its tally lived in memory while the
        decisions lived in the checkpoint (the shape of V3, V8 and V10).

    Both are the same mistake -- lifecycle state kept BESIDE the record it
    describes, free to diverge from it. Deriving instead of storing removes the
    possibility rather than fixing the instances:

      * human approvals are included, because `record_resolution` rewrites the
        stored decision and this reads stored decisions;
      * it survives restart, because `_decisions` is checkpointed;
      * two workers restoring one checkpoint agree, because both compute the same
        function of the same input;
      * there is no transition to race, so no lock is needed.

    `assessing` is the authorization currently being judged, excluded so a purchase
    is never counted as its own predecessor.
    """
    classification = classify_shape(mandate.instruction)
    shape = classification.shape
    if shape is not MandateShape.ONE_SHOT:
        return FulfilmentVerdict(
            "not_applicable", shape, f"this mandate is {shape.value}: {classification.evidence}"
        )

    anchor = job_anchor(mandate)
    if anchor is None:
        # No specific product, so UNITS cannot be counted -- but PURCHASES can, and
        # for a one-shot job the second purchase is a second performance whatever is
        # in it. An earlier pass returned `not_applicable` here on the reasoning that
        # "a category is not specific enough". That reasoning is about units within
        # one basket; it was wrongly applied to repetition across baskets, and the
        # gap it left is the largest single economic hole measured in this project:
        # SCEN0000 says "buy ONE ordinary grocery item for CHF 20 or less" and a
        # policy-compliant agent draws CHF 172,320 through it in a simulated year.
        #
        # Counting purchases rather than units is what keeps this sound: it says
        # nothing about what belongs in a single grocery basket, only that the job
        # was already done once. On the official data it changes nothing.
        earlier = [d for d in state.approved_decisions() if d.authorization_id != assessing]
        if not earlier:
            return FulfilmentVerdict(
                "first_fulfilment", shape,
                f"one-shot job, not yet fulfilled ({classification.evidence})",
            )
        return FulfilmentVerdict(
            "already_fulfilled", shape,
            (
                f"this mandate describes a single job ({classification.evidence}) and names no "
                f"specific product, so it cannot be told apart from the purchase that already "
                f"fulfilled it ({earlier[0].authorization_id}). This purchase would perform it again."
            ),
            prior_authorization_id=earlier[0].authorization_id,
        )

    prior = [d for d in state.approved_decisions() if d.authorization_id != assessing]
    matching = [(d, units_in_basket(d.basket_key, anchor)) for d in prior]
    matching = [(d, u) for d, u in matching if any(anchor in str(line[1]).lower() for line in d.basket_key)]
    units_done = sum(u for _, u in matching)

    current = state.get_stored_decision(assessing) if assessing else None
    units_now = units_in_basket(current.basket_key, anchor) if current else 1

    if units_done == 0 and units_now > 1:
        return FulfilmentVerdict(
            "over_fulfilled", shape,
            (
                f"this mandate describes a single job ({classification.evidence}), but this one "
                f"purchase performs it {units_now} times ({units_now} matching items)."
            ),
        )
    if units_done == 0:
        return FulfilmentVerdict(
            "first_fulfilment", shape, f"one-shot job, not yet fulfilled ({classification.evidence})"
        )
    return FulfilmentVerdict(
        "already_fulfilled", shape,
        (
            f"this mandate describes a single job ({classification.evidence}), and it was already "
            f"fulfilled by {matching[0][0].authorization_id}. This purchase would perform it again."
        ),
        prior_authorization_id=matching[0][0].authorization_id,
    )

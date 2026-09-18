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

from .mandate import MandateSnapshot


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
    (r"\bbuy\s+one\b|\bpurchase\s+one\b", "'buy one' states the quantity explicitly"),
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


def job_key(mandate: MandateSnapshot) -> tuple[str, ...]:
    """What counts as 'the same job', derived from the customer's own compiled
    anchors rather than from the basket.

    This is the property that makes the check hard to evade rather than merely
    hard to trigger: the key is the set of item constraints the CUSTOMER wrote. To
    propose a purchase that does not match this key, a compromised agent must
    propose something outside those constraints -- which the ordinary rule engine
    already blocks. Evading the fulfilment check therefore costs the agent the
    policy check, and vice versa.
    """
    anchors: list[str] = []
    for rule in mandate.hard_rules:
        if rule.field in ("item.category", "item.name_contains", "item.size"):
            value = rule.value
            anchors.append(f"{rule.field}={sorted(value) if isinstance(value, list) else value}")
    return tuple(sorted(anchors))


class FulfilmentMonitor:
    """Observes approved purchases for one run and reports repeat fulfilments.

    Holds no authority and gates nothing. It is an observer by construction: the
    only thing it can do is return a verdict.
    """

    def __init__(self, mandate: MandateSnapshot) -> None:
        self.mandate = mandate
        self.classification = classify_shape(mandate.instruction)
        self._key = job_key(mandate)
        self._anchor = job_anchor(mandate)
        self._fulfilled_by: str | None = None
        self._units_fulfilled = 0

    def observe_allow(self, authorization_id: str, *, units: int = 1) -> None:
        if self._fulfilled_by is None:
            self._fulfilled_by = authorization_id
        self._units_fulfilled += max(units, 1)

    def assess(self, authorization_id: str, *, units: int = 1) -> FulfilmentVerdict:
        """`units` is how many times THIS purchase performs the job -- the quantity
        of matching items in its basket.

        Counting units rather than purchases is not a detail. Audit 1 defeated the
        purchase-counting version in one move: buy two pairs of shoes in a single
        authorization for CHF 198 against a CHF 200 cap. One purchase, one
        fulfilment by the old measure, and the customer asked to replace one pair.
        """
        shape = self.classification.shape
        if shape is not MandateShape.ONE_SHOT:
            return FulfilmentVerdict(
                "not_applicable", shape,
                f"this mandate is {shape.value}: {self.classification.evidence}",
            )
        if self._anchor is None:
            # One-shot by phrasing, but the customer named no distinguishing product,
            # so "the same job" is not identifiable. Saying nothing beats guessing.
            return FulfilmentVerdict(
                "not_applicable", shape,
                "this mandate names no specific product, so repeat fulfilment cannot be identified",
            )

        units = max(units, 1)
        already = self._units_fulfilled if self._fulfilled_by != authorization_id else 0

        if already == 0 and units > 1:
            return FulfilmentVerdict(
                "over_fulfilled", shape,
                (
                    f"this mandate describes a single job ({self.classification.evidence}), but this "
                    f"one purchase performs it {units} times ({units} matching items)."
                ),
            )
        if already == 0:
            return FulfilmentVerdict(
                "first_fulfilment", shape,
                f"one-shot job, not yet fulfilled ({self.classification.evidence})",
            )
        return FulfilmentVerdict(
            "already_fulfilled", shape,
            (
                f"this mandate describes a single job ({self.classification.evidence}), and it was "
                f"already fulfilled by {self._fulfilled_by}. This purchase would perform it again."
            ),
            prior_authorization_id=self._fulfilled_by,
        )


def job_anchor(mandate: MandateSnapshot) -> str | None:
    """The SPECIFIC product phrase that identifies this job, if the customer gave one.

    A category is not specific enough to count fulfilments. "One ordinary grocery
    item" and "clothing" name a kind, not a job -- counting units against them would
    mean a basket of two different groceries looked like the job done twice. Only a
    distinguishing phrase (`item.name_contains`) identifies a job well enough to say
    it has been performed. Without one, this module says nothing at all.
    """
    for rule in mandate.hard_rules:
        if rule.field == "item.name_contains":
            return str(rule.value).lower()
    return None


def units_in(event: dict, mandate: MandateSnapshot) -> int:
    """How many times one event performs THIS job: the quantity of items matching
    the job's specific anchor -- not the size of the basket.

    Audit 2 defeated the basket-counting version without any attack at all: one pair
    of shoes plus a shoe-care kit counted as two units and was flagged as buying the
    shoes twice. A false prompt is cheaper than a false approval, but it is still a
    defect, and an observer that cries wolf is one the customer learns to dismiss.
    """
    anchor = job_anchor(mandate)
    if anchor is None:
        return 1
    return sum(
        int(line.get("quantity", 1))
        for line in event["authorization"]["items"]
        if anchor in str(line.get("item_name", "")).lower()
    ) or 1

"""Authorization drift: a structured, field-level diff between two purchase
fingerprints -- what changed, not a numeric "risk score" (R&D Track D; see
docs/RND_AUTHORIZATION_DRIFT.md for why a score was deliberately rejected).

Used in two places in `decision_engine.py`:

  1. When a repeated `authorization_id` arrives with mutated facts (the
     `authorization_id_conflict` case) -- the drift shows exactly what changed
     between the original delivery and the mutated one.
  2. When `related_authorization_id` links the current purchase to an earlier one
     this run already decided (e.g. a re-quote after a decline) -- the drift shows
     exactly what changed between the prior attempt and this one, which is what
     actually lets an evidence tree explain "this is a legitimate correction"
     (amount narrowed, nothing else changed) vs. "this is a different purchase
     wearing the same story" (merchant changed too).

Classification is deterministic from the changed fields themselves, never a
weighted or invented score:

  "none"             -- no tracked field differs.
  "narrowing"        -- every changed monetary field moved down, and the basket
                        did not grow a new item category; a customer-favorable
                        correction (e.g. a re-quote at a lower price).
  "widening"         -- any amount increased, or a new item appeared.
  "unrelated_change" -- the merchant itself changed; this is not a "correction"
                        of the same order by any reasonable reading.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .state import BasketKey

Classification = Literal["none", "narrowing", "widening", "unrelated_change"]


@dataclass(frozen=True)
class DriftField:
    field: str
    before: str
    after: str


@dataclass(frozen=True)
class AuthorizationDrift:
    reference_authorization_id: str
    changed_fields: tuple[DriftField, ...]
    classification: Classification

    def as_dict(self) -> dict:
        return {
            "reference_authorization_id": self.reference_authorization_id,
            "changed_fields": [{"field": f.field, "before": f.before, "after": f.after} for f in self.changed_fields],
            "classification": self.classification,
        }


def compute_drift(
    *,
    reference_authorization_id: str,
    prior_merchant_id: str,
    prior_basket_key: BasketKey,
    prior_amount_chf: Decimal,
    current_merchant_id: str,
    current_basket_key: BasketKey,
    current_amount_chf: Decimal,
) -> AuthorizationDrift:
    changed: list[DriftField] = []
    if prior_merchant_id != current_merchant_id:
        changed.append(DriftField("merchant_id", prior_merchant_id, current_merchant_id))
    if prior_amount_chf != current_amount_chf:
        changed.append(DriftField("billing_amount_chf", str(prior_amount_chf), str(current_amount_chf)))
    if prior_basket_key != current_basket_key:
        changed.append(DriftField("basket", str(prior_basket_key), str(current_basket_key)))

    if not changed:
        classification: Classification = "none"
    elif prior_merchant_id != current_merchant_id:
        classification = "unrelated_change"
    else:
        # Compare on the item identity (first element) only. The basket key also
        # carries name and quantity, so it is NOT a mapping and must not be fed to
        # dict() -- a "new item" here means an item_id that was not in the basket
        # before, not merely a line whose quantity or name changed.
        prior_items = {entry[0] for entry in prior_basket_key}
        current_items = {entry[0] for entry in current_basket_key}
        new_items = current_items - prior_items
        amount_increased = current_amount_chf > prior_amount_chf
        classification = "widening" if (new_items or amount_increased) else "narrowing"

    return AuthorizationDrift(reference_authorization_id=reference_authorization_id, changed_fields=tuple(changed), classification=classification)

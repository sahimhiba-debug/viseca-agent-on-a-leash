# R&D Track D: Authorization drift

## The question

Not "does the final proposal satisfy policy" (already answered by `rules.py`),
but "how did the proposal *change* relative to the closest prior reference point
the wallet has for this purchase" -- and is that change itself worth surfacing,
independent of whether the final state happens to still pass policy?

## Where this already has a foothold

Two existing mechanisms already compute a partial drift, without naming it that:

- `evaluate_authorization`'s `authorization_id_conflict` branch already computes
  and reports a merchant/basket/amount diff between the first delivery and a
  mutated redelivery (`"original: merchant=X amount=Y basket=Z"` vs.
  `"received: merchant=X2 amount=Y2 basket=Z2"`).
- `related_authorization_id`/`related_authorization_status` let a re-quote (e.g.
  `AU0042` after `AU0037`'s decline) be linked to its predecessor, but today the
  link is used only to *exclude* the pair from duplicate-suspicion -- the actual
  field-by-field difference between the two (merchant same, amount lower, item
  same) is never computed or shown.

## Design: a small, explicit, field-level diff -- not a score

Section 6 of the brief explicitly warns against inventing "a meaningless numeric
risk score... for presentation." This design deliberately avoids one:

```python
@dataclass(frozen=True)
class DriftField:
    field: str        # "merchant_id" | "billing_amount_chf" | "item_categories" | ...
    before: str
    after: str

@dataclass(frozen=True)
class AuthorizationDrift:
    reference_authorization_id: str | None   # the related/prior authorization, if any
    changed_fields: tuple[DriftField, ...]
    classification: Literal["none", "narrowing", "widening", "unrelated_change"]
```

`classification` is deterministic, not a score: `"narrowing"` if every changed
monetary field moved down and no new item category appeared (e.g. AU0037 ->
AU0042's re-quote: amount 520 -> 350, same merchant, same basket) -- a
customer-favorable correction; `"widening"` if any amount increased or a new item
category was added; `"unrelated_change"` if the merchant itself changed. This
directly reuses field comparisons `_basket_key`/fingerprinting already computes,
adding only the classification and the explicit before/after pairing.

## Attack examples this makes explainable rather than just correctly-decided

- **AU0041** (a monitor + an unrequested "Extended protection plan"): today,
  correctly BLOCKed via `item.category`/`item.unrequested_present`. With drift
  analysis available for the case where a customer or judge asks "compared to
  what the customer actually asked for, what changed?", the answer becomes an
  explicit `changed_fields=[("item_categories", "{electronics}", "{electronics, subscriptions}")]`
  rather than something only inferable by reading the rule evidence.
- **The demo scenario built for this pass** (§16 -- see
  `docs/archive/VERIFIABLE_AGENTIC_WALLET.md`) depends directly on this: an agent
  proposal that drifts from the customer's stated intent in a merchant-influenced
  way is the whole point of the demonstration.

## Alternatives considered

- **A numeric "drift score" (0-100)**: rejected per the brief's explicit
  instruction and because a made-up weighting (is a merchant change "worse" than
  a 2x amount increase?) would not be more explainable than the field list itself
  -- it would be less so, hiding the actual comparison behind an opaque number.
- **Comparing every proposal against the ORIGINAL customer instruction text**
  (not just a related prior authorization): rejected as infeasible in general --
  the customer's instruction is natural language, not a structured "expected
  purchase," so there is no well-defined "before" to diff against except (a) the
  compiled policy (already checked by `rules.py`) or (b) a genuinely related
  prior authorization (which this design uses).

## Implementation cost

Small-to-medium. A new pure function taking two `PurchaseFacts` and returning an
`AuthorizationDrift`; wired in only where a `related_authorization_id` exists or
an `authorization_id_conflict` is detected (both cases already have two facts
objects to compare) -- no change to the core `_decide()` priority logic.

## Demo value

High -- directly serves Section 16's demo scenario requirement and gives a
judge a visual "before vs. after" rather than only a final verdict.

## Compatibility

Fully local; not sent to the hosted API.

## Recommendation: **PROTOTYPE** (selected for implementation, combined with Track E)

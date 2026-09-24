# R&D Track B: Evidence + provenance graph

## What already exists

`SECURITY_MODEL.md` (written in the third audit pass) is a *static* per-field
trust classification: for every field the engine reads, its source
(customer/platform/merchant/system-generated), trust level, transformation, and
consumer. `RuleEvaluation.source` (`"customer"` vs `"safety"`, added in the third
pass) is a *runtime* tag on each individual check, now rendered in the UI as two
separate evidence groups. Together these already answer "why did the wallet
decide this?" at the level of: which rule, what fact, pass/fail/unknown, and
whether it came from the customer's own policy or a control-layer safety net.

## What a fuller provenance graph would add

A per-decision, machine-readable graph literally connecting: customer instruction
-> compiled hard rule -> fact -> the field's own source classification (from
`SECURITY_MODEL.md`) -> the security signal (if any) -> the final decision --
rather than the current flat list of `RuleEvaluation`s plus a separate static
document a reader has to cross-reference by hand.

## Design considered

```python
@dataclass(frozen=True)
class EvidenceNode:
    claim: str              # e.g. "billing_amount_chf <= 400"
    fact_value: str         # e.g. "289.0"
    source: str             # "customer_policy" | "platform_data" | "merchant_text" | "system_derived"
    verifiable: bool        # can this codebase independently confirm it, or only observe it?
    outcome: Outcome
```

`EngineDecision.evidence` (currently `tuple[str, ...]`, pre-formatted strings)
would become `tuple[EvidenceNode, ...]`, letting a UI render source badges
per-line automatically instead of two static string-matched buckets.

## Attack/failure examples this would help diagnose

None that the current `source` tag does not already surface -- the two-bucket
split (customer/safety) already distinguishes "your policy" from "our safety
checks," which is the distinction that actually matters for a customer or judge
asking "why." A full per-fact provenance graph adds *categories* (platform vs.
merchant vs. system-derived, rather than just customer vs. safety) but no new
*decision-relevant* information, since `facts.py`'s architecture already
guarantees merchant text can only ever populate two specific fields
(`return_window_days`, `stated_size`) -- there is no fact in this system whose
provenance is actually ambiguous at runtime; it is already fully determined by
which extractor produced it.

## Implementation cost vs. value

Medium cost (touches `RuleEvaluation`, every call site that builds `evidence`
strings, and the UI rendering) for a benefit that is mostly a formatting
improvement over what `SECURITY_MODEL.md` + the `source` tag already provide.

## Recommendation: **DEFER**

The genuinely new information a full provenance graph would carry (fine-grained
source categories beyond customer/safety) does not correspond to any actual
runtime ambiguity in this system -- `facts.py`'s architecture already makes every
fact's provenance fixed and known at extraction time, documented once in
`SECURITY_MODEL.md`. Building a parallel runtime data structure to re-state a
static, already-true classification is exactly the kind of complexity Section 13
of the brief warns against absent demonstrated value. The `source` tag (already
shipped) captures the one distinction (policy vs. safety) that is actually
decision-relevant and demo-relevant. Revisit if a future fact source is added
whose provenance is genuinely dynamic (e.g., a live third-party risk feed) rather
than fixed by which function extracted it.

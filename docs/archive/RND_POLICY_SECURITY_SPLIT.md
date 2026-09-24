# R&D Track E: Policy compliance vs. trust/security -- explicit decision fusion

## The distinction the brief asks for

"The customer permitted this type of purchase" (policy compliance) and "this
transaction actually represents the customer's intent, executed under normal
conditions" (trust/security) are different questions that can disagree: a
purchase can be entirely within the stated spending rules while still looking
like it isn't really the customer driving the session (session-integrity risk),
or vice versa.

## What already exists

This distinction is **already implemented as a mechanism**, just not exposed as
two named, separately-inspectable verdicts:

- `RuleEvaluation.source` (third audit pass) already tags every check as
  `"customer"` (policy) or `"safety"` (trust/security: duplicate suspicion,
  the amount-integrity check, the no-rules safety net).
- `session.integrity_risk` is itself a customer-authored hard rule when the
  customer's own instruction asks for it (e.g. SCEN0003's "pause anything that
  looks like someone other than me is driving the session") -- so in the current
  design, "trust" concerns the customer explicitly opted into are `source="customer"`,
  while trust concerns imposed unconditionally by the wallet itself (duplicate
  detection, amount integrity) are `source="safety"`. This is a meaningful,
  intentional distinction: SCEN0003's session-integrity rule is *policy* (the
  customer asked for it), even though it's *about* security.
- `_decide()` already fuses every evaluation, regardless of source, with the same
  priority rule (any fail blocks; else any unknown routes through
  `uncertainty_policy`; else allow) -- meaning "policy" and "security" verdicts
  are already fused into one deterministic outcome, just not computed or exposed
  as two separate intermediate values first.

## Design: expose two named verdicts, computed by scoping the existing fusion function

```python
def _verdict_for(evaluations: list[RuleEvaluation], source: str, uncertainty_policy) -> tuple[Decision, tuple[str,...]]:
    return _decide([e for e in evaluations if e.source == source], uncertainty_policy)

policy_verdict, policy_reasons = _verdict_for(evaluations, "customer", mandate.uncertainty_policy)
security_verdict, security_reasons = _verdict_for(evaluations, "safety", mandate.uncertainty_policy)
final_decision, final_reasons = _decide(evaluations, mandate.uncertainty_policy)  # unchanged
```

`final_decision` is computed exactly as today (unchanged behavior, unchanged
tests); `policy_verdict`/`security_verdict` are additive, purely explanatory
fields on `EngineDecision`, letting the UI show, e.g.: "Your policy: ALLOW.
Wallet safety: REVIEW (suspected duplicate). Final: REVIEW" -- literally the
worked example the brief gives.

## Why this is safe (does not change the decision)

`_decide()` on the FULL evaluation list is monotonic with respect to the two
scoped sub-verdicts: if either sub-verdict is BLOCK, the full list contains that
same failing evaluation, so the full verdict is also BLOCK; if either is REVIEW
(unknown) and neither is BLOCK, the full verdict is REVIEW (unless
`uncertainty_policy` routes it elsewhere, identically for both the scoped and
full computation, since `uncertainty_policy` is the same mandate-level value in
both cases). This is provable from `_decide()`'s own definition, and is checked
directly by a new property-based test (see Implementation).

## Alternatives considered

- **A weighted fusion (e.g., security concerns "outvote" policy in ambiguous
  cases)**: rejected -- there is nothing to weight; the existing "any fail
  blocks" rule already gives security and policy equal, absolute veto power,
  which is the more conservative and more defensible choice for a money-moving
  decision.
- **Two entirely separate engines with a merge step**: rejected as unnecessary
  restructuring -- `rules.py`/`_decide()` do not need to change at all; only a
  thin, additive scoping wrapper is needed.

## Implementation cost

Very small: one helper function, two new fields on `EngineDecision`, no change
to `_decide()`'s signature or the core evaluation loop.

## Demo value

Directly matches the brief's own worked example ("policy_result = ALLOW,
trust_result = REVIEW, therefore REVIEW") almost verbatim, and pairs naturally
with the existing UI evidence-group split.

## Compatibility

Fully local; additive fields only.

## Recommendation: **PROTOTYPE** (selected for implementation, combined with Track D)

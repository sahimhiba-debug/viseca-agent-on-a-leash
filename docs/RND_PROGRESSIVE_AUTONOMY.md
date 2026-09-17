# R&D Track F: Progressive autonomy as a customer-controlled capability

## The question

Should "how much autonomy the agent gets" itself be an explicit, tunable,
customer-controlled setting -- e.g., "observe/propose only," "act within strict
limits," "act within broader limits," "confirm high-risk deviations only" -- as a
dimension separate from the specific spending rules?

## Why this is already substantially covered

Decompose "autonomy level" into its actual behavioral consequences, and each one
already maps onto an existing, independently-tunable mechanism:

| Desired autonomy behavior | Already expressible today, via |
| --- | --- |
| "Never act without asking me" | `uncertainty_policy=ask` + a mandate with hard rules narrow enough that almost everything is `unknown` or explicitly gated -- or, more directly, the `mandate.has_no_rules` safety net already routes an under-specified mandate to ASK for every purchase |
| "Act freely within strict limits" | A tight per-order/rolling ceiling + `uncertainty_policy=approve` for genuinely uncertain-but-low-stakes gaps |
| "Act freely within broader limits" | A looser ceiling, same policy shape |
| "Confirm only high-risk deviations" | `session.integrity_risk`/`order.duplicate_suspected` as hard rules the customer opts into, everything else auto-decided |

Every one of these is already a **composition of existing mandate primitives**
(amount ceilings, category/merchant constraints, `uncertainty_policy`), not a
missing dimension. "Autonomy level" as a single named slider would be a
*convenience UI framing* over the same underlying `hard_rules`/`uncertainty_policy`
combination -- not a new capability the engine lacks.

## What a dedicated "autonomy level" field would add

Only a friendlier front-end preset (e.g., a UI offering "cautious / balanced /
permissive" buttons that pre-fill a `hard_rules` template) -- a `policy_compiler.py`
convenience, not a `decision_engine.py` capability. This is real UX value but
belongs to Track G (the policy simulator/debugger), not as a new independent
mechanism.

## Revocation and tightening

Already fully covered by the existing mandate lifecycle: `Mandate.tighten_hard_rules`
(narrow further), `Mandate.set_uncertainty_policy` (tighten-only transitions),
`Mandate.revoke()` (withdraw entirely). An "autonomy level" is not a separate
lever from these -- it would be implemented IN TERMS OF them.

## Recommendation: **DEFER**

Not rejected outright -- a labeled "autonomy preset" is a legitimate future UI
convenience -- but there is no new *engine* capability to build here, and
building a redundant parallel concept (a stored "autonomy_level" enum alongside
the `hard_rules` that already fully determine behavior) risks the two drifting
out of sync, which is a real correctness hazard for no corresponding safety
benefit. If pursued, it should be implemented purely as a `policy_compiler.py`
preset-to-rules template, never as new state the decision engine reads directly.

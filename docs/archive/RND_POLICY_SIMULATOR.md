# R&D Track G: Policy simulator / debugger

## The question

Before a customer confirms a mandate, can the system show them concretely what
it would do -- "this would allow...", "this would ask you about...", "this would
block..." -- rather than only showing the compiled `hard_rules` list and hoping
the customer can mentally simulate their own policy?

## What already exists

`POST /api/mandates/compile` (existing, since the first build) already returns
the compiled `hard_rules`, `uncertainty_policy`, `guidance` (plain-language
restatements of each rule -- directly analogous to AP2's "prompt playback"
concept, see `AGENTIC_COMMERCE_RESEARCH.md`), and `open_questions` (anything the
compiler could not confidently understand) -- all *before* the customer confirms.
This is already most of a policy debugger's value: the customer sees exactly what
was understood and what was not, before committing.

## What a fuller simulator would add

Running the compiled-but-unconfirmed policy against a small set of illustrative,
clearly-synthetic example transactions (NOT official scenario data -- e.g., "a
CHF 50 grocery order from a shop you've used before" / "a CHF 500 order from an
unfamiliar electronics seller") and showing the customer the resulting
ALLOW/REVIEW/BLOCK for each, so they can sanity-check their own policy against
concrete cases rather than only its abstract rule list.

## Design sketch (not implemented this pass)

A new `POST /api/mandates/simulate` endpoint: given a `CompiledPolicy` (from the
existing `/compile` response, not yet confirmed) and a small fixed set of
illustrative synthetic events, run each through `evaluate_authorization` against
a throwaway `RunState`, and return the (event summary, decision) pairs. No new
engine logic -- purely a demo-time composition of `compile_instruction` +
`evaluate_authorization`, both already existing and already tested.

## Why this was not implemented in this pass

Genuinely useful, and cheap -- but building it well requires a curated set of
illustrative synthetic examples that actually demonstrate the customer's OWN
policy's edge cases (not a generic fixed set), which risks either being too
generic to be useful or scope-creeping into a mini rule-coverage-analysis tool.
Given the "select at most 3 concepts" constraint, and that this track's
underlying value (transparency before confirmation) is already substantially
delivered by the existing `/compile` response's `guidance`/`open_questions`,
this was ranked below Tracks A, D+E, and H on the scoring table in
`docs/archive/RND_FINAL_DECISION.md`.

## Recommendation: **PROTOTYPE recommended, deferred this pass**

A concrete, low-risk next feature if more time is available: the
`/api/mandates/simulate` endpoint sketched above, reusing 100% existing engine
code with zero new decision logic.

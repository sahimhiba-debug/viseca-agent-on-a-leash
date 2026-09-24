# R&D Track I: LLM-assisted policy compiler

## Summary of prior analysis (unchanged conclusion, revisited with new research)

This exact question was already analyzed in depth in `ARCHITECTURE_DECISIONS.md`
ADR-2 during the third audit pass, scoring five options (fixed lexicon / LLM ->
validator -> engine / LLM as explanation layer / LLM as ambiguity detector / no
LLM) against seven criteria. That analysis is not repeated here; this document
adds what changed: real industry research (`AGENTIC_COMMERCE_RESEARCH.md`) and a
concrete re-test against the specific design this track proposes (`LLM ->
structured policy proposal -> deterministic schema validation -> ambiguity
detection -> customer confirmation -> deterministic wallet engine`).

## What the new research changes

Nothing about the recommendation -- but it sharpens *why* the deterministic path
was right for THIS challenge specifically. Every real system researched
(Mastercard Agentic Tokens, Google AP2, OpenAI's Delegated Payment) puts the
**LLM (or the agent generally) on the proposing side**, and a **separate,
deterministic verification/settlement layer** on the deciding side -- AP2's own
architecture is exactly "agent proposes a Cart Mandate; a separate, narrower,
mechanically-derived Payment Mandate is what the network actually checks." This
project's `decision_engine.py` already occupies that same "deterministic
verification layer" role. The place industry practice would put an LLM in
THIS system is exactly where `ARCHITECTURE_DECISIONS.md`'s Option B put it: at
mandate-*creation* time, producing a structured proposal a deterministic
validator then checks -- never inside `evaluate_authorization`.

## Re-testing the proposed design against this pass's own fuzz corpus

`tests/test_compiler_fuzz_corpus.py` (10 adversarial instructions) was built
specifically to find the deterministic compiler's coverage limits. It found
exactly two real gaps (uncertainty-trigger phrasing, "X is the real limit"
phrasing), both closed with regex additions in this pass. None of the ten cases
required semantic understanding beyond a slightly larger lexicon -- meaning the
concrete evidence gathered in this pass, not just the abstract argument in
ADR-2, still points to "the lexicon's gaps are a short, closeable list," which
was ADR-2's own stated bar for reconsidering.

## What would change the recommendation

A demonstrated instruction the deterministic compiler cannot parse into a
correct or safely-flagged-ambiguous result, where the fix is not a small,
addable pattern but requires genuine semantic reasoning (e.g., resolving a
pronoun across three sentences, or inferring an implicit constraint from
context the customer never stated explicitly). No such case was found in three
rounds of adversarial testing across two audit passes plus this pass's dedicated
fuzz corpus.

## Recommendation: **REJECT for this pass** (reaffirmed, not merely repeated)

Not implemented. If pursued in the future, the safe design is
`ARCHITECTURE_DECISIONS.md` ADR-2's Option B exactly: LLM proposes, the existing
`HardRule.__post_init__` schema validation constrains, `policy_compiler`'s
existing `open_questions` mechanism handles anything the validator rejects, and
the customer still confirms before the mandate activates -- the LLM would never
gain a code path into `evaluate_authorization`.

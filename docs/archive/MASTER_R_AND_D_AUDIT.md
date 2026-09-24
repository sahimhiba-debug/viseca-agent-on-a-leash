# Master R&D Audit

<!-- snapshot -->
> **SNAPSHOT — written 17 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

A third, deeper pass over the "Agent on a Leash" implementation: not a repeat of
the first two audits' finding-and-fixing pattern, but an explicit attempt to
discover whether the architecture itself could be meaningfully better, backed by
property-based testing, mutation testing, and adversarial fuzzing rather than only
hand-written examples. This document assumes the two prior audits
(`FINAL_SENIOR_ENGINEERING_REVIEW.md`, `SECOND_ADVERSARIAL_AUDIT.md`) got some
things right and some things wrong, and re-derives its conclusions rather than
citing them as settled.

## 1. Executive Summary

This pass found and fixed **3 additional real defects** (a payment layer that
accepted a zero/negative charge amount, a live worker that retried an
unrecoverable 401/403 forever instead of stopping, and two policy-compiler
lexicon gaps that silently discarded an explicit customer correction), added
**property-based testing** (Hypothesis, 8 properties covering the payment
boundary, the amount-ceiling/ decision relationship, repeated-authorization
conflict detection, money-rounding monotonicity, and compiler crash-resistance --
effectively thousands of generated cases, not just hand-picked examples), ran a
**manual mutation-testing pass** confirming the test suite catches 4 targeted
mutations of the highest-value logic branches, and built a **curated adversarial
fuzz corpus** for the policy compiler that found the two lexicon gaps mentioned
above. It also performed a genuine comparative analysis of two alternative
architectures (a structured `CustomerPolicy` object, and an LLM-in-the-loop
mandate compiler) and explicitly rejected both, for reasons traced through actual
code behavior rather than asserted -- while adopting the one small, real
improvement that comparison surfaced (a `source` tag separating customer-policy
evidence from wallet-safety evidence, now shown in the demo UI as two distinct
groups).

The architecture is **unchanged in shape**. Every fix in this pass is a corrected
check or a closed coverage gap within files that already existed; none required
new infrastructure. The official 45-event replay produces the same 19/2/24
decisions, reason-for-reason, as both prior passes.

## 2. Current Architecture

Unchanged from `ARCHITECTURE.md`: customer instruction -> compiled mandate (the
only source of authority) -> agent proposal -> trustworthy facts extraction ->
deterministic rule evaluation -> ALLOW/REVIEW/BLOCK -> human intervention when
needed -> independently re-gated payment execution. See `ARCHITECTURE_DECISIONS.md`
for the two alternative shapes considered and rejected in this pass, and why.

## 3. Security Model

See the new `SECURITY_MODEL.md`: a field-by-field trust classification (CUSTOMER-
AUTHORED / PLATFORM-AUTHORED / MERCHANT-AUTHORED / SYSTEM-GENERATED) for every
field the decision engine reads, with the transformation applied and the
consequence if that trust judgment were wrong.

## 4. Invariants

See the new `SECURITY_INVARIANTS.md`: 25 formally stated invariants (I1-I25, plus
I12a and I23a added in this pass) grouped as Authority/Payment/Replay/Policy/
Time/Failure, each with what enforces it and which test would fail first if it
broke.

## 5. New Vulnerabilities Discovered (this pass)

1. **`MockPSP.charge` accepted a zero or negative amount.** Found by directly
   attacking the payment layer with malformed amounts (Section 16 of the audit
   brief), not through the normal API/UI. A charge for CHF 0 or less is never a
   legitimate execution of an approved purchase. **Fixed**: `charge()` now
   rejects `amount_chf <= 0`. A matching defensive check was added at the
   decision level too (a non-positive `billing_amount_chf` on the authorization
   itself now fails the always-on amount-integrity check), since the official
   schema's `exclusiveMinimum: 0` constraint should not be the only thing
   standing between a malformed event and this codebase trusting it.

2. **The live worker retried a 401/403 (bad/revoked bearer key) forever, with the
   same 1-second backoff as a transient 503.** An auth failure will never fix
   itself by retrying; this would silently burn the team's rate limit while
   looking, from the outside, like a worker that is merely slow. **Fixed**:
   401/403 on poll now raises `FatalWorkerError` (stopping the loop loudly);
   401/403 on submit gives up immediately instead of spending the bounded retry
   budget on a request that cannot succeed.

3. **Two policy-compiler lexicon gaps silently discarded an explicit customer
   correction rather than honoring it or flagging it.** Found by the adversarial
   fuzz corpus, not by hand-picked examples:
   - "Approve anything if you're not sure. Actually, decline if you're not sure."
     -- neither "if...not sure" phrasing matched the (then-)required "when
     uncertain" pattern, so the compiler silently fell back to the ASK default,
     discarding BOTH explicit statements.
   - "Spend up to CHF 300. Actually up to CHF 200. No wait, CHF 150 is the real
     limit." -- "CHF 150 is the real limit" was not a recognized ceiling
     phrasing at all, so the customer's own corrective final figure was silently
     dropped in favor of an earlier, less restrictive one.
   **Fixed**: generalized the uncertainty-trigger phrase to accept when/if and
   uncertain/unsure/not-sure interchangeably; added "X is the (real/actual/true)
   limit" and "the limit is X" as recognized ceiling phrasings.

## 6. Vulnerabilities Fixed

All three from §5, with regression tests:
`tests/test_payment_boundary.py::test_zero_or_negative_charge_amount_is_refused`,
`tests/test_decision_engine.py::test_non_positive_billing_amount_is_blocked`,
`tests/test_live_worker.py::test_a_401_on_poll_stops_the_worker_instead_of_retrying_forever`
(+ `::test_a_403_on_poll_also_stops_the_worker`, `::test_a_401_on_submit_does_not_retry_and_is_logged_not_swallowed`,
`::test_a_transient_503_on_poll_does_not_stop_the_worker` as the negative control),
`tests/test_compiler_fuzz_corpus.py::test_conflicting_uncertainty_instructions_take_the_stricter_one_or_flag_it`,
`::test_repeated_correction_keeps_the_final_intended_ceiling_or_flags_ambiguity`.

## 7. Vulnerabilities Intentionally Accepted

None found in this pass that were left unfixed. The per-item ceiling gap found by
the fuzz corpus (see §12) is a **feature gap**, not a vulnerability -- the compiler
correctly fails to invent a false rule from "never let any single item cost over
CHF 100" rather than misreading it, and flags the miss with an `open_question`
(`tests/test_compiler_fuzz_corpus.py::test_a_per_item_ceiling_is_not_confused_with_a_per_order_ceiling`).
Implementing genuine per-item ceilings would be new functionality (a new field/rule
type, `item.unit_price_chf <= N`), not a bug fix, and is recorded as a documented
limitation rather than built speculatively.

## 8. Experiments Performed

- **Hypothesis property-based testing** across 8 properties (payment boundary,
  amount-ceiling relationship, repeated-authorization conflict detection, money
  rounding/monotonicity, compiler crash-resistance, merchant-text non-influence)
  -- see §10.
- **Manual mutation testing**: 4 targeted mutations applied and reverted live
  against the actual codebase (not simulated) -- see §11.
- **Adversarial fuzz corpus for the policy compiler**: 10 curated realistic
  instructions -- see §12.
- **Structured `CustomerPolicy` representation**, traced through the tighten-only
  guarantee to compare against the current flat `HardRule` list -- see
  `ARCHITECTURE_DECISIONS.md` ADR-1.
- **LLM-in-the-loop mandate compiler** (`LLM -> structured policy -> deterministic
  validator -> deterministic engine`), evaluated against 4 alternatives on 7
  criteria each -- see `ARCHITECTURE_DECISIONS.md` ADR-2.
- **Append-only event log** as an alternative to the checkpoint-file crash
  recovery mechanism -- see `ARCHITECTURE_DECISIONS.md` ADR-4.
- **A statistically-trained session-integrity model** as an alternative to the
  explicit three-signal heuristic -- see `ARCHITECTURE_DECISIONS.md` ADR-5.

## 9. Experiments Rejected and Why

- **Structured `CustomerPolicy` object**: rejected because the flat conjunctive
  `HardRule` list gets the tighten-only security guarantee for free, uniformly,
  across every field type, while a structured object would need to re-derive that
  guarantee per constraint category (a set-intersection here, a `min()` there),
  each a distinct place to get the direction of narrowing backwards. Its one real
  benefit (structured display) was captured far more cheaply via ADR-3's `source`
  tag.
- **LLM-in-the-loop mandate compiler**: rejected for now because the fuzz corpus
  built specifically to find the deterministic compiler's coverage gaps found
  exactly two, and both were closeable with regex additions in under ten lines
  each -- no case required semantic understanding beyond a slightly larger
  lexicon. Recorded as the correct next step if the lexicon's gaps ever turn out
  to be unbounded rather than a short, closeable list.
- **Six-way internal decision taxonomy** (`REVIEW_MISSING_FACT`/`REVIEW_SECURITY`/
  `BLOCK_POLICY`/`BLOCK_SECURITY`/`BLOCK_AUTHORITY`): rejected because it mostly
  restates information `reason_codes`/`evidence` already carry, for real
  implementation cost across `_decide()`, `intervention.py`, and every consumer of
  `Decision`.
- **Append-only event log** for crash recovery: rejected because it would roughly
  double `state.py`'s persistence code for an auditability benefit (full change
  history) this system does not need beyond what `EngineDecision`'s evidence trail
  and `RunState`'s bounded recent-attempts list already provide.
- **A trained session-integrity model**: rejected because `authorization_history.csv`'s
  `status` column is explicitly documented as containing "a stochastic component"
  and is explicitly not a fraud label -- training against it would teach a model
  to imitate synthetic noise, not to detect session hijacking.

## 10. Property-Based Testing Results

`tests/test_properties.py`, 8 properties, run at 100-200 generated examples each
(the two compiler-crash-resistance properties additionally exercise arbitrary
Unicode text up to 500 characters). All 8 passed without a single counterexample
found -- a meaningfully stronger signal than the equivalent hand-written examples
alone, since each property was independently checked against ~150-200 generated
input combinations rather than one or two chosen by hand. Properties covered:

- Charging succeeds if and only if the requested amount is within the approved
  ceiling AND the merchant matches (`test_property_charge_never_exceeds_approved_amount_or_wrong_merchant`).
- BLOCK/REVIEW can never be charged, for any amount or merchant
  (`test_property_block_or_review_can_never_be_charged`).
- A purchase over a stated ceiling is never ALLOWed, for any (ceiling, amount)
  pair (`test_property_amount_over_ceiling_never_allows`).
- A repeated `authorization_id` is a safe retry iff its facts are byte-identical
  to the first delivery, and a conflict otherwise, for any (amount, merchant)
  combination on each side (`test_property_repeated_authorization_id_is_safe_iff_facts_are_identical`).
- CHF conversion always rounds to 2 decimal places and is monotonic in the
  source amount, for any (amount, currency) pair.
- The policy compiler never raises an exception for any input text up to 500
  characters, including adversarial Unicode.
- Arbitrary `item_details` text (including injection-shaped strings) never
  changes the mandate's own `hard_rules`.

## 11. Mutation-Testing Findings

Four mutations applied live to the actual source, test suite run, mutation
reverted (see the session transcript for the exact commands):

1. **`payment.py`: `amount_chf > stored.billing_amount_chf` mutated to `>=`.**
   Caught by 4 tests, including the exact-boundary test that asserts charging
   precisely the approved amount succeeds.
2. **`decision_engine.py`: `_decide()`'s failure list forced empty (fail no longer
   blocks).** Caught by 15 tests across 6 files, including 2 of the new property
   tests -- the single highest-value mutation tried, confirming the "fail always
   wins" priority rule is heavily load-bearing and well-covered.
3. **`rules.py`: `merchant.familiar`'s `unknown` outcome mutated to `pass` (silent
   trust of a missing fact).** Caught by 18 tests -- the second-highest-value
   mutation, confirming I18 ("unknown facts cannot silently become true") is not
   merely asserted but actually enforced by the test suite.
4. **`state.py`: the rolling-window boundary `<=` mutated to `<`.** Caught by 6
   tests, most notably the human-resolution test that specifically checks the
   exact boundary (a step_up resolved with its original purchase timestamp
   exactly at the window edge).

No mutation went undetected. This is not a formal mutation score (a tool like
`mutmut` running exhaustively across the codebase would find many more trivial,
low-value mutants); it is a targeted check that the highest-value logic branches
specifically are not merely "tested" in the tautological sense the audit brief
warned against, but actually break something observable when wrong.

## 12. Fuzzing Results

`tests/test_compiler_fuzz_corpus.py`, 10 curated adversarial instructions,
found 2 real bugs (§5) and 1 documented, deliberately-unfixed coverage gap
(per-item ceilings, not expressible in the current field vocabulary -- §7).
Verified safe behavior (no false authority, visible `open_question`, no crash) on:
repeated self-corrections, extremely long instructions (200x padding), multiple
currencies mentioned in passing, Unicode-heavy text, an instruction with no
recognizable structure at all, an absurdly large explicitly-stated amount (not
silently capped, since capping a customer's own explicit figure would be the
engine overriding intent in the other direction), and a malformed negative-amount
phrase.

## 13. Policy Compiler Findings

Beyond §5's two fixes: the compiler's amount-extraction now takes the **minimum**
across all recognized ceiling mentions in one instruction (added in the second
audit pass) and was re-verified in this pass to correctly handle a three-way
self-correction chain once the "X is the real limit" phrasing was added. The
`_ITEM_MODIFIER_RE`/`_SIZE_RE` tightening from the second pass held up against the
new fuzz corpus without further adjustment.

## 14. Prompt Injection Findings

No new injection-specific findings this pass -- the architecture (merchant text
read through exactly two whitelist patterns, never compiled into a rule) was
re-verified structurally (§10's property test) and held. See `SECURITY_MODEL.md`
for the complete trust classification and `SECURITY.md` for the existing,
still-current injection analysis.

## 15. Payment Findings

§5, finding 1 (zero/negative amount). All prior payment-boundary guarantees
(merchant binding, amount ceiling, one-execution-per-authorization, charge_id
conflict detection) re-verified both by example and, newly, by property
(`test_property_charge_never_exceeds_approved_amount_or_wrong_merchant`) across
~150 generated (approved, requested, merchant-match) combinations.

## 16. Human Intervention Findings

No new findings. The amount/timestamp binding fixed in the second audit pass
(a resolution always uses the originally-reviewed amount and simulated
timestamp, never a caller-supplied value or the real-clock answer time) was
re-verified via mutation testing (finding 4, §11) rather than re-audited from
scratch, and held.

## 17. Authority Lifecycle Findings

No new findings. Confirm-twice, revoke-twice, and tighten-with-a-weaker-rule were
all re-traced in ADR-1's comparative analysis (not merely re-tested) and confirmed
sound: the conjunctive evaluation model makes privilege escalation via any of
these paths structurally impossible, not just untested.

## 18. Crash Recovery Findings

No new findings; the checkpoint-file design from the second audit pass was
compared against an append-only event log alternative (ADR-4) and kept. The
residual limitation (a restart on a different machine with no local checkpoint
cannot fully reconstruct rolling-window history) is unchanged and remains
honestly documented rather than silently accepted.

## 19. Live API Findings

§5, finding 2 (401/403 handling). All other documented HTTP-failure-class
behaviors (204, network-level errors, 5xx retry-with-backoff) were re-verified
via the existing `test_viseca_client.py` suite, unchanged by this pass.

## 20. Performance Findings

Policy compilation and decision evaluation are pure Python with no I/O, network
call, or model invocation anywhere in either path -- both complete in well under a
millisecond per call in practice (the full 45-event offline replay, including
building every event from CSV rows, completes in a fraction of a second). The
official 8-second default decision deadline is not a practical constraint for
this architecture; the only latency-sensitive part of the live path is the actual
HTTP round-trip to the hosted API, which this codebase does not control. No
performance regression was introduced by any fix in this pass (all are `O(1)`
additional checks or `O(items)` scans already bounded by a small basket size).

## 21. UX/Demo Improvements

The evidence tree now separates "your policy checked" from "wallet safety checks"
in both the API response and the UI (ADR-3), verified live in the browser: a
REVIEW caused by a duplicate-order signal is now visually distinguishable from one
caused by an unverifiable policy condition, without changing the underlying
decision logic at all. This directly serves the "compact evidence tree" ask in
Section 18 of the audit brief using structured facts only, with no invented
explanation text.

## 22. Official Replay Analysis

See the new `DECISION_ANALYSIS.md` for the complete per-event ledger plus an
adversarial examination of every genuinely debatable decision (why so few REVIEWs
despite three scenarios themed around ambiguity; why AU0018's unknown fact never
mattered; why currency conversion didn't secretly decide AU0037/AU0038; the
"unfamiliar but fully compliant seller" case examined against the road not taken).
Total: **45/45 events, 19 ALLOW / 2 REVIEW / 24 BLOCK, unchanged from both prior
passes, decision-for-decision** -- confirming every fix in this pass is correctly
scoped to inputs the well-formed official data never exercises.

## 23. Remaining Limitations

Unchanged from the second audit pass, plus one addition:

- Crash recovery is best-effort (local checkpoint + best-effort platform
  reconciliation), not a full distributed-transaction guarantee.
- The policy compiler remains a fixed lexicon; ADR-2 documents exactly what would
  justify moving to an LLM-assisted compiler and why that bar was not yet met.
- The live worker has never been run against the real hosted API (no event-day
  key available while building this).
- **New**: per-item spending ceilings ("no single item over CHF X") are not
  expressible in the current field vocabulary; an instruction stating one
  produces a visible `open_question` rather than a false rule, but does not
  produce a real one either.
- This audit, like the two before it, was performed by the same author as the
  original implementation. Property-based testing and mutation testing were used
  specifically to reduce (not eliminate) this blind spot by checking behavior
  against generated/mutated inputs the author did not hand-pick.

## 24. Why This Architecture Is Appropriate for the Hackathon

Three full audit passes, one of them (this one) explicitly instructed to explore
alternatives without constraint, converged on the same architecture shape. That is
not evidence the architecture is beyond criticism -- §25 lists what a Viseca
engineer could still push on -- but it is evidence that the shape was reached by
elimination, not by default: two real alternative representations and one
alternative decision-path technology (an LLM) were traced through actual
consequences, not just discussed, and both were found to cost more than they would
buy for this challenge's actual requirements. The total fix surface across all
three passes remains small, targeted, well-tested changes to files that already
existed -- no database, no queue, no distributed worker, no LLM, and now,
additionally, property-based and mutation-tested confidence that the highest-value
logic branches are not merely covered by tests but are actually broken by the
mutations that matter.

## 25. What a Senior Viseca Engineer Could Still Criticize

- **The amount-integrity tolerance (CHF 0.02) is a fixed constant**, not derived
  from a documented rounding-error bound; a production system would want this
  sourced from the actual settlement rounding rule rather than a defensive guess.
- **The per-item ceiling gap (§23)** is a real, if narrow, expressiveness
  limitation of the current field vocabulary that a more general "constraint
  scope" concept (per-purchase vs. per-item vs. per-period) could close --
  deliberately not built speculatively in this pass, but a legitimate next
  feature to ask about.
- **Property-based testing covered 8 properties, not the full invariant list**
  in `SECURITY_INVARIANTS.md` -- the remaining invariants are covered by
  hand-written examples and, in 4 cases, mutation testing, but not by generated
  inputs. A more exhaustive pass could extend Hypothesis strategies to cover
  multi-item baskets, rolling-window sequences, and the live-worker crash points
  directly.
- **The mutation testing in this pass was manual and targeted (4 mutations)**,
  not an exhaustive automated run (e.g. `mutmut` across the whole codebase). A
  full mutation-testing run was judged not worth the time cost for a hackathon
  timeline versus targeting the highest-value branches by hand, but a real
  mutation score was not computed and the claim here should not be read as one.
- **The session-integrity heuristic's behavior in the one untested configuration**
  (a security signal as the SOLE reason for escalation, with no independent
  policy violation) is by design (routes through the mandate's own
  `session.integrity_risk` hard rule like any other check) but is genuinely
  untested against the official data, since no event in the pack isolates that
  case -- see `DECISION_ANALYSIS.md`.
- **Whether three full self-audits by the same author have found everything** a
  genuinely independent reviewer would find is, definitionally, not something this
  document can answer.

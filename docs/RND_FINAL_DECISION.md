# R&D Final Decision

## Scoring table

Each track scored on ten factors (A-J from the brief), each a short factual
justification, not a number pulled from nowhere. Scale: **H**igh / **M**edium /
**L**ow / **N/A**.

| Track | A. Viseca relevance | B. Security value | C. User-control value | D. Explainability | E. 3-min demo | F. Effort | G. Regression risk | H. Novelty vs. plain rule engine | I. Official API compat | J. Survives compromised agent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A. Capability authority | H -- directly formalizes "bounded authority, not a blank cheque" | H -- explicit expiry + one-object re-verification closes 2 real gaps (§ RND_CAPABILITY_AUTHORITY) | M -- customer sees exactly what was granted | H -- one inspectable JSON artifact | H -- "here is what was actually authorized" is a strong visual | L -- additive dataclass + refactor of `MockPSP`'s parameter list | L -- existing payment tests are the regression baseline | M -- most rule engines don't reify authority as an object at all | H -- entirely local | H -- authority is bound to merchant+amount+basket+expiry, all independently re-checked |
| B. Evidence/provenance graph | L -- static doc + `source` tag already cover the decision-relevant distinction | L -- no new information over `SECURITY_MODEL.md` | L | M -- marginal over existing evidence groups | L | M | L | L -- mostly re-labels the existing static doc | H | N/A -- doesn't change security posture |
| C. Agent claims vs. facts | M -- names an existing mechanism, adds no new one | M -- the mechanism (amount-integrity, fingerprint conflict) already exists and is tested | L | M -- clarifies existing evidence strings' intent | L -- not visibly different in a demo | L (docs only) | None (no code change) | L -- already implemented, just unnamed | H | H (via the existing mechanisms it documents) |
| D. Authorization drift | H -- squarely the "manipulated agent" scenario theme | M -- explains, doesn't add a new gate (rules.py still decides) | M -- customer sees exactly what changed | H -- a before/after field diff is maximally legible | H -- concrete for the new demo scenario | L -- pure function over two already-computed `PurchaseFacts` | L -- additive field on `EngineDecision` | H -- few rule engines expose a structured proposal diff | H | M -- explanatory, not itself a new gate (the existing rules still gate) |
| E. Policy/security split | H -- matches the brief's own worked example almost verbatim | L -- provably does not change the final decision (monotonicity argument in the doc) | M -- clarity on WHY, not a new control | H | H -- pairs naturally with D for the demo | L -- one helper function, two additive fields | L -- provable non-interference with `_decide()` | M | H | N/A -- explanatory only |
| F. Progressive autonomy | L -- already expressible via existing primitives | N/A | L -- convenience framing only | L | L | M (if built as new state) | M (risk of two representations drifting apart) | L | H if built as a preset-to-rules template | N/A |
| G. Policy simulator | M -- strengthens the "frontend" half of the challenge's own objective #1 | N/A | H -- lets customer sanity-check their own policy pre-confirmation | H | M | L (pure composition of existing functions) | L | M | H | N/A |
| H. Red-team matrix | H -- directly demonstrates the central claim of the whole challenge | H -- forces every invariant to be exercised together, live, in one run | N/A (a test harness) | H -- one readable table | H -- the single strongest "show, don't tell" artifact available | L (orchestrates existing tested functions) | None (test-only) | H -- most rule engines are never demonstrated this way | H (test-only, no wire format involved) | H -- this IS the test of exactly that property |
| I. LLM policy compiler | L for this pass -- fuzzing found the lexicon's gaps are closeable | L if done right (validator-gated); would be M-H risk if done wrong | M (could understand more phrasings) | L (non-deterministic explanations) | M (impressive but not decisive) | H (new dependency, new failure modes, no test-time determinism) | H (a new source of non-determinism in a previously fully-deterministic path) | H (genuinely different from a fixed lexicon) | M if the validator is airtight; the validator IS the actual security boundary, not the LLM | M -- depends entirely on the validator, which is just `HardRule.__post_init__`, already present |
| J. Agent/principal identity | L -- no field in the official schema to bind to | L -- would be unverifiable if invented locally | L | L | L | M-H (new infrastructure with no data to verify it against) | M | M | **L -- would violate official-schema compatibility if implemented as new fields** | N/A |

## Classification

- **KEEP** (already sufficient as-is, no new code needed): Track C (documented,
  not re-implemented), Track F (documented as already covered by existing
  primitives).
- **PROTOTYPE** (selected for implementation this pass): **Track A**
  (`PaymentAuthority`), **Tracks D+E combined** (`AuthorizationDrift` +
  policy/security verdict split -- implemented together because they share the
  same evidence-tagging infrastructure and reinforce the same demo scenario),
  **Track H** (red-team attack matrix).
- **DEFER** (real value, not selected this pass, concrete next step recorded):
  Track B (evidence/provenance graph -- revisit if a genuinely dynamic-provenance
  fact source is ever added), Track G (policy simulator -- the
  `/api/mandates/simulate` endpoint is fully designed and trivial to build next).
- **REJECT** (for this challenge, as currently specified): Track I (LLM policy
  compiler -- reaffirmed with fresh fuzzing evidence, not just prior reasoning),
  Track J (agent identity infrastructure -- would violate official-schema
  compatibility).

## Why exactly these three, and not more

Section 15 caps implementation at three concepts. A, D+E, and H were chosen
because they score highest on the factors that matter most for THIS
challenge specifically (A: Viseca relevance: all three score H; G: regression
risk: all three score L, meaning the existing 187-test baseline is not put at
risk; J: survives a compromised agent: A and H score H directly, D+E is
explanatory and inherits its guarantee from the rules `rules.py` already
enforces) -- while Tracks B, F, I, and J all have at least one factor
(regression risk, official-API compatibility, or "adds genuinely new
information") that argues against building them now.

## What follows this document

1. `PaymentAuthority` implemented in `payment.py`, tested (unit + property +
   mutation-style boundary checks), 45-event replay re-verified unchanged.
2. `AuthorizationDrift` + `policy_verdict`/`security_verdict` implemented in a
   new `drift.py` and additive fields on `EngineDecision`, tested, replay
   re-verified unchanged.
3. `tests/test_red_team_matrix.py` + `scripts/run_red_team.py` implemented,
   17/17 attacks PASS against the hardened wallet.
4. A new, clearly-synthetic demo scenario built and run through the demo API,
   distinct from the official 45-event data.
5. `docs/VERIFIABLE_AGENTIC_WALLET.md` written describing the resulting
   architecture as actually built (revised from the hypothesis in the brief
   where the implementation diverged).

See the end of this document (after implementation) for final test/replay
numbers and the answer to Section 20's central question.

---

## Post-implementation results

- Tests: 187 (third-pass baseline) -> **236**, all passing (22 for
  `PaymentAuthority`/`AuthorizationDrift`/policy-security split in
  `test_capability_and_drift.py` -- including a 200-example Hypothesis property
  test and a dedicated double-revoke-idempotency test backing I27; 18 for the
  Track H red-team matrix in `test_red_team_matrix.py`; 8 for the new demo
  scenario in `test_demo_scenario.py`; 1 new API test).
- Official 45-event replay: **19 allow / 2 review / 24 block, unchanged** --
  identical to every prior pass (`python scripts/run_replay.py`).
- Red-team matrix: **17/17 attacks PASS** (`python scripts/run_red_team.py`) --
  prompt injection (plain and Unicode-obfuscated), basket tampering, merchant
  impersonation/redirection, authorization replay and mutation, resolution
  abuse, rolling-limit double-counting, post-authority price changes, and
  PATCH-based mandate-widening attempts are all defeated with zero wallet code
  changes required to pass.
- New synthetic demo scenario (`scripts/run_demo_scenario.py`,
  `GET /api/rnd-demo`, and a live UI card): the redirected re-quote is
  genuinely routed to REVIEW by an honestly-unknown fact (not a forced or
  hardcoded outcome), and the merchant redirect itself -- invisible to every
  hard rule in the compiled mandate -- is caught only by the Track D drift
  check. Verified live in the browser preview alongside the pre-existing
  official-scenario flow, with no regressions to it.
- No existing invariant in `SECURITY_INVARIANTS.md` was weakened; three new
  ones were added and are each backed by a passing test: **I26** (a payment
  authority is single-use, time-boxed, and independently re-checked at
  execution -- re-issuance is idempotent and never extends the expiry), **I27**
  (revocation is monotonic -- a second revoke can never un-revoke), **I28**
  (drift classification and the policy/security verdict split are computed
  strictly after `_decide()` and can never themselves widen or narrow a
  decision, with a proven monotonicity property machine-checked over 200
  Hypothesis examples).
- All of Section 19's ABSOLUTE SUCCESS CRITERIA were re-verified against this
  final state; see `VERIFIABLE_AGENTIC_WALLET.md`'s closing checklist for the
  itemized pass/fail against each one.

## Answering Section 20 directly

**"If another team builds a conventional deterministic wallet with spending
limits, merchant rules, step-up, and audit logs, what can our architecture
demonstrate that theirs cannot easily demonstrate?"**

Technically, not "more security" in the abstract -- a well-built conventional
wallet with the same rule set can enforce identical spending limits. The
concrete difference is **what can be shown, live, as a single artifact, in the
three-minute demo window**:

1. **A self-contained, inspectable payment authority object** (Track A) that a
   judge can read as a JSON blob and verify by eye: bound merchant, bound
   amount, bound basket, an actual expiry timestamp -- rather than having to
   trust a verbal claim that "the amount and merchant are checked somewhere in
   the code."
2. **A structured, field-level drift report** (Track D) showing exactly what an
   agent proposal changed relative to a prior reference point, in plain
   before/after terms -- not a score, not a paragraph, a diff -- which most
   conventional rule engines compute internally (if at all) but do not surface
   as a distinct, nameable artifact.
3. **A live, 17-attack, all-PASS red-team table** (Track H) run in front of the
   judges against the actual code, not a slide -- proving "the agent can be
   fully compromised without gaining payment authority" as a demonstrated fact
   in real time, rather than an assertion in a README.

The smallest set of mechanisms that creates this difference is exactly these
three -- not because they add more rules than a conventional wallet would have,
but because they turn the SAME underlying guarantees (bounded amount, bounded
merchant, no replay, no escalation) into three distinct, judge-verifiable
artifacts instead of one paragraph of prose asserting they hold.

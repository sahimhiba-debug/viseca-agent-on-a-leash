# Claims register

Every claim this project makes in public, with its scope, its evidence, the test that
would fail if it stopped being true, and **what must not be inferred from it**.

The last column is the point. A claim without a stated boundary is a claim an auditor
will stretch until it breaks.

---

## Security

### C1 — Merchant text can only narrow a decision
**Scope:** the two fields whose only source is merchant free text (`order.return_window_days`, `item.size`), plus all text read by `facts.py`.
**Evidence:** merchant text claiming `authority_status=active` against a platform `revoked` still blocks; no merchant string raises a ceiling or fakes familiarity.
**Test:** `test_I7_*` (6 payloads), `test_prompt_injection.py`.
**Limitation:** merchant text CAN flip REVIEW → ALLOW on those two fields. A plausible "returns accepted within 999 days" is accepted.
**Do not infer:** that we detect a merchant lying. We do not, and cannot.

### C2 — An approved authorization is charged at most once, per process
**Scope:** one process. **Evidence:** 8 concurrent charges → exactly 1 succeeded. **Test:** `test_execution_atomicity.py`.
**Limitation:** two workers restoring one checkpoint each charge once.
**Do not infer:** exactly-once. It is at-most-once, and only here.

### C3 — Revocation reaches a purchase still awaiting the customer's answer
**Scope:** run-level `_revoked_at`, plus mandate-level status which propagates to new runs.
**Evidence:** a step-up answered after revocation blocks; a new run under a revoked mandate blocks.
**Test:** `test_F1*` (3), `test_revocation_end_to_end.py`.
**Do not infer:** that in-flight platform-side work is cancelled. `technical_details.md` leaves that unspecified.

### C4 — A customer's answer binds to the purchase they were shown
**Scope:** amount, merchant and basket.
**Evidence:** three swap classes during the step-up window all rejected as conflicts; only the shown amount AND merchant can be charged.
**Test:** `test_human_consent_binding.py` (4).
**Limitation:** the protocol carries **no resolver identity**. Anyone who can reach the endpoint can answer.
**Do not infer:** that the step-up channel is authenticated.

### C5 — Deleting a required field never buys a more permissive decision
**Scope:** every required field in `authorization_event.schema.json` with an enum.
**Evidence/Test:** `test_required_field_omission.py`, stated over the schema's own enums.
**Do not infer:** that we validate events against the schema. We do not.

### C6 — The platform's echoed policy is checked, never adopted
**Scope:** `hard_rules` and `uncertainty_policy`, when the worker is given the confirmed policy.
**Evidence:** 11 echo variants; reversed and shuffled rule order accepted, all nine alterations fail closed.
**Test:** `test_any_echoed_difference_fails_closed`.
**Limitation:** **opt-in.** Offline and test callers supply no confirmed policy, so it does not fire for them.

### C7 — The agent is told the decision and the class of constraint, never a policy value
**Scope:** `agent_view` and `POST /api/agent/propose`.
**Evidence:** 12 probes / CHF 531 to recover a ceiling through the decision alone; 0 probes through the customer payload. Projection searched for every policy figure, any decimal, any dotted field, any evidence string.
**Test:** `test_agent_view_leaks_no_policy_values` (5 shapes), mutated.
**Limitation:** the ALLOW/BLOCK **oracle is irreducible**. A patient agent still learns roughly one bit per purchase, and pays for it.
**Do not infer:** that the policy is secret from the agent. It is *expensive*, not hidden.

## Intent

### C8 — No silent delegation expansion
**Scope:** 204 independently-written restrictive phrasings across 15 classes, plus a 103-phrase corpus.
**Evidence:** 0 silently weakened, 0 incorrectly strengthened; 2 looser-than-stated cases now named back to the customer.
**Test:** `test_intent_fidelity.py`, `scripts/run_intent_corpus.py`.
**Limitation:** coverage of restriction *kinds* is checked; **correctness of a recognised phrase is not**.
**Do not infer:** that the compiler understands language. 204 phrases from one author is not a language, and the author also wrote the fixes.

### C9 — Restrictive intent we cannot enforce blocks confirmation
**Scope:** quantity, overall total, end date, and any recognised restrictive marker with no rule.
**Evidence/Test:** `test_unsupported_restrictive_intent_blocks_confirmation`; every compiling drafter is AST-checked to carry the field.
**Do not infer:** that those concepts are enforced. They are disclosed and they block; the vocabulary cannot express them.

## Agentic

### C10 — The agent recovers from a refusal and succeeds on the merits
**Scope:** the deterministic grocery agent in `research/`.
**Evidence:** CHF 292 → 197 → 137 → **87 ALLOW**, landing well below a CHF 120 ceiling it was never told.
**Test:** `test_shopping_agent.py` (7).
**Limitation:** the planner is arithmetic, not a model, deliberately — `technical_details.md` requires predictable behaviour when a model is unavailable.
**Do not infer:** that this is a general shopping agent. It drops the most expensive line.

### C11 — The wallet never depends on the agent
**Scope:** all of `src/wallet_control/`.
**Evidence/Test:** `test_runtime_boundary.py` + `test_the_runtime_never_imports_the_agent`, both AST-based. This caught a real violation during this campaign.

## Process

### C12 — The test suite is not theatre
**Evidence:** `scripts/run_mutation_probe.py` breaks 38 mechanisms one at a time; all 38 caught. It has found four real gaps across campaigns.
**Limitation:** targeted, not exhaustive. It cannot speak for a mechanism nobody thought to mutate.

### C13 — The numbers this repository states about itself are true
**Evidence/Test:** `test_stated_numbers.py` checks test counts and every per-scenario replay row against reality.
**Do not infer:** that 19/2/24 is a score. The pack ships `contains_expected_decisions: false`.

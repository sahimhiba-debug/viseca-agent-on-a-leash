# Security invariants — consolidated final list

The authoritative list. `SECURITY_INVARIANTS.md` remains as the historical,
per-pass record (I1–I32 in the order they were discovered); this document is the
deduplicated statement of what the system guarantees *now*, reorganised by what
each invariant protects and stated so that each one names the attack that would
violate it.

Every invariant below is enforced by named code and pinned by a named test. Where
an invariant is **conditional**, the condition is part of the statement — a
guarantee with an unstated precondition is not a guarantee.

---

## A. Who may create authority

**A1. Only the wallet mints payment authority.**
`RunState.issue_authority` is the only constructor of a `PaymentAuthority` in the
repository, and it raises `AuthorityError` unless the underlying stored decision is
`allow`.
*Violated by:* an agent or merchant constructing its own grant.
*Test:* `test_capability_and_drift.py::test_cannot_issue_an_authority_directly_for_a_non_allow_decision`.

**A2. Merchant text cannot create or widen authority.**
`policy_compiler.compile_instruction` — the only producer of `HardRule`s — is never
called from `decision_engine.py` or `facts.py`. Merchant text reaches the engine
only through three whitelist extractors.
*Violated by:* injected text being read as instruction.
*Tests:* `test_prompt_injection.py` (structural source inspection),
`test_properties.py::test_property_arbitrary_item_details_never_changes_the_mandates_own_rules`,
30 corpus cases `C01a`–`C15b`.

**A3. Mandate mutation can never increase authority.**
`tighten_hard_rules` only appends; `HardRule` is frozen; rules are a conjunction, so
an appended weaker rule cannot relax a stricter one. `set_uncertainty_policy` only
moves toward `decline`.
*Violated by:* a PATCH that loosens a standing limit.
*Test:* `test_mandate_lifecycle.py::test_tighten_hard_rules_only_appends_never_removes`.

**A4. An empty or unparseable policy is not unlimited authority.**
Zero executable rules raises `mandate.has_no_rules` as `unknown`, routed through
`uncertainty_policy` — never treated as "everything passes".
*Violated by:* a blank-cheque mandate from an unparseable instruction.
*Tests:* `test_decision_engine.py`, corpus `G01`.

**A5. A human answer authorizes one authorization, never a policy.**
`resolve_authorization` touches only the one id; there is no code path from a
resolution into `Mandate`.
*Violated by:* "yes" becoming a standing permission.
*Test:* `test_human_resolution.py::test_resolving_a_step_up_does_not_touch_the_mandate`.

---

## B. What an authority authorizes

**B1. An authority is bound to one authorization, one merchant, and one ceiling.**
Enforced in `MockPSP.charge` against the **stored decision**, not against the
passed authority object — so a forged object with an inflated ceiling still fails.
*Violated by:* redirecting a grant to another purchase or payee.
*Tests:* corpus `P06`, `P07`; `test_properties.py::test_property_charge_never_exceeds_approved_amount_or_wrong_merchant`.

**B2. An authority is single-use within one run state, and durably so when the
executor is given a persist hook.**
`consumed_at` is set at execution, written through the injected `persist` hook
BEFORE the charge record exists, and checkpointed with the rest of `RunState`.

Stated conditionally on purpose. The proof pass showed the unconditional version
was false twice over: consumption was memory-only (V10), and single-use is a
property of ONE `RunState`, so two workers restoring the same checkpoint each
execute once (V11, scoped not fixed). What holds is: one run state, one process,
one execution — durable across a crash iff a persist hook is supplied.
*Violated by:* charging twice in one process; or across a crash with no hook; or
from two run states at all.
*Tests:* `test_execution_durability.py` (both halves, including the limitation),
corpus `H01`, `N03`, the state machine's `consumption_is_monotonic`.

**B3. An authority expires on the payment boundary's own clock.**
`MockPSP._clock`, injected at construction. The per-call `now=` timestamps the
record and cannot gate expiry.
*Violated by:* a caller claiming it is still issue time (this was V4).
*Tests:* `test_authority_lifecycle.py::test_expiry_cannot_be_defeated_by_rewinding_the_supplied_clock`, corpus `J02`.

**B4. Revocation is monotonic and cascading, and durable under the same condition as B2.**
`revoke_authority` / `revoke_outstanding_authorities` use `dataclasses.replace` on a
frozen object; nothing clears `revoked`. Revoking the mandate revokes every
outstanding authority in the run, and authorities are checkpointed.
*Violated by:* a revoked grant that charges — directly, after a restart (V3), or
because it was never minted (V2).
*Tests:* `test_authority_lifecycle.py`, `test_revocation_end_to_end.py`, corpus `F01`, `N01`.

**B5. Expiry and revocation are re-read from live state, never trusted from the caller.**
`charge()` looks the authority up in `RunState` rather than believing the object it
was handed.
*Violated by:* replaying a copy captured before a revocation.
*Test:* `test_final_arbitration.py::test_a_stale_authority_copy_cannot_resurrect_a_revoked_one`.

**B6. A chargeable approval always has an authority; a missing one fails closed.**
*Violated by:* the fail-open default that let V2 and V3 move money. This invariant
**reverses** a claim made by the previous pass.
*Test:* `test_authority_lifecycle.py::test_an_allow_with_no_authority_on_record_cannot_be_charged`.

---

## C. What may reach execution

**C1. BLOCK cannot become payment. C2. An unresolved REVIEW cannot become payment.**
`charge()` requires `stored.decision == "allow"` exactly.
*Tests:* `test_properties.py::test_property_block_or_review_can_never_be_charged`, corpus `E08`.

**C3. There is exactly one point where money moves.**
`ChargeRecord` is constructed at `payment.py:167` and nowhere else (verified by grep, and re-verified whenever this file changes).
*Violated by:* any second execution path. Verified structurally by grep, not by
assertion.

**C4. A charge_id is an idempotency key for one request, not a bearer token.**
Reuse for a different authorization or amount is a conflict, not a retry.
*Test:* corpus `P08`; `test_payment_boundary.py`.

**C5. A charge amount must be strictly positive and within the approved amount, compared as `Decimal`.**
CHF 0.001 over is refused; float precision cannot round it away.
*Tests:* corpus `I12`, `I13`.

---

## D. Identity — who this event is for

**D1. An event is bound to its run before anything else is decided.**
`card_id` and `mandate_id` are compared to the run's, **before** the
repeat-delivery branch, so a mis-bound event cannot be answered with a stored
decision.
*Violated by:* an event borrowing another card's purchase history to make an
unfamiliar merchant look familiar (this was V5).
*Tests:* `test_run_binding.py` (9), corpus `P01`–`P05`.

**D2. Identity is compared exactly.**
A case variant, a padded value, a zero-width character or a homoglyph is a
different identity.
*Tests:* corpus `P02`, `P03`, `P04`, `K01`.

**D3. A human answer is bound to the facts that were reviewed.**
`record_resolution` takes no amount and no merchant; it reads the original record.
The spend window uses the original simulated timestamp, not the answer time.
*Violated by:* approving CHF 100 and being charged CHF 999.
*Tests:* corpus `E01`, `E02`; `test_human_resolution.py`.

**D4. A human answer is idempotent, non-contradictable, and scoped to its own run.**
*Tests:* corpus `E03`–`E06`.

---

## E. Replay and mutation

**E1. Same id + identical facts = safe retry. E2. Same id + different facts = conflict.**
Fingerprint: merchant, CHF total, and per line `(item_id, item_name, quantity,
return_window_days, final_sale, stated_size)`.
*Tests:* `test_properties.py::test_property_repeated_authorization_id_is_safe_iff_facts_are_identical`, 15 corpus `B*b` cases, the mutation fuzzer.

**E3. Facts derived from merchant text are fingerprinted; the text itself is not.**
A text edit that moves a fact is a conflict; casing, padding and invisible
characters remain an ordinary retry.
*Violated by:* rewriting "size 43" to "size 38" under a reused id — or, in the
other direction, by forking every legitimate retry on a cosmetic edit.
*Tests:* `test_final_arbitration.py` (both directions), `test_authority_mutation_fuzzer.py::test_property_fact_free_noise_never_forks_a_retry`.

**E4. A corrected transaction never inherits authority from a previous one.**
A re-quote is evaluated fresh; `related_authorization_id` is evidence, never a
source of authority.
*Test:* `test_duplicate_and_retry.py`.

**E5. Spend is counted once per authorization, and only for final approvals.**
A purchase awaiting a human is not approved spend.
*Tests:* corpus `J06`, `N04`.

---

## F. The platform's own signals

**F0. A mandate that is not ACTIVE authorizes nothing.**
`mandate.status` (`active|superseded|revoked|expired`) is checked before anything
else is decided. Anything other than `active` is a hard failure.
*Violated by:* V12 — a revoked mandate produced ALLOW, minted an authority and
charged, through both the local revoke path and a live snapshot rebuilt from an
event whose mandate block said `revoked`. Until this pass, revocation was enforced
only when it came through our own demo endpoint.
*Test:* `test_mandate_status.py` (9).

**F1. A platform-declared dead authority or blocked card is a hard failure.**
`authority_status ∈ {revoked, expired}` or `card_status_at_attempt = blocked` →
`fail`, which no `uncertainty_policy` can soften.
*Violated by:* V1 — the largest finding of the deep-security pass.
*Test:* `test_platform_status.py` (14).

**F2. An unrecognised status is uncertainty, not consent.**
A future enum value, an empty string, a case variant or a missing field routes
through `uncertainty_policy`.
*Test:* `test_platform_status.py::test_an_unrecognised_status_is_uncertainty_not_permission`.

**F3. A dead status stops the money even when the decision must stay as submitted.**
On a re-delivery the stored decision is returned unchanged — the platform already
has our answer — but the outstanding authority is revoked.
*Violated by:* V7.
*Test:* corpus `F02`, `test_authority_mutation_fuzzer.py`.

---

## G. Failing closed

**G1. Unknown facts never silently become true.**
Every rule in `rules.py` returns `unknown`, never `pass`, when the fact cannot be
determined. The full audit is in `DEEP_SECURITY_RESEARCH.md` §6.

**G2. Malformed input is never an approval.**
Missing fields, wrong types, unknown currencies, NaN and ±Infinity either produce a
non-allow decision or raise — and the worker logs and continues polling rather than
approving.
*Tests:* corpus `L01`–`L10`, `I07`–`I09`.

**G3. Network and API failure never become authority.**
Transport errors and HTTP statuses are normalised to `VisecaApiError` and retried
without synthesising a decision; 401/403 stop the worker loudly.
*Tests:* `test_viseca_client.py`, `test_live_worker.py`.

**G4. Restart never forgets approved spend.**
`RunState` is checkpointed after every decision and reloaded on restart.
*Test:* corpus `N04`.

---

## H. Explanation cannot change outcome

**H1. Drift classification and the policy/security verdict split are computed after
`_decide()` and can never widen or narrow a decision.**
Backed by a 200-example Hypothesis monotonicity property: the final decision is
never more permissive than either scoped sub-verdict.
*Test:* `test_capability_and_drift.py::test_property_final_decision_is_never_more_permissive_than_either_scoped_verdict`.

---

## Conditional and non-invariants — stated so they are not assumed

These are **not** guaranteed. Listing them is part of the model.

| Not guaranteed | Why |
| --- | --- |
| Rolling-window limits under a dishonest timestamp | windows key on platform-supplied simulated purchase time, which we cannot verify and the contract requires us to use |
| That merchant claims about size and return terms are true | no independent source exists; merchant text can satisfy exactly these two predicates |
| Product identity beyond name matching | no SKU/colour/width ontology |
| Thread safety | `charge()` is check-then-act with no lock; single-execution held under 24-way contention but that is the GIL, not design |
| Single-use across two run states or two processes | `consumed_at` lives in one `RunState`; two workers restoring one checkpoint each execute once. Closing it needs a shared store with atomic compare-and-set, deliberately not built |
| Single-use across a crash without a persist hook | consumption is memory-only; the last checkpoint is written after a DECISION and knows nothing about a charge |
| Idempotent retry of a completed charge after a restart | the `charge_id` ledger is in-memory; a post-restart retry fails closed rather than returning the original record |
| `policy_version`, `basket_fingerprint`, `mandate_id` on the authority | provenance, not enforced bindings — see `SECURITY_MODEL.md` |
| Anything about a hostile platform | every fact originates from its event stream |

# Second Adversarial Audit

<!-- snapshot -->
> **SNAPSHOT — written 17 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

This is an independent, hostile re-review of the implementation recorded in
[FINAL_SENIOR_ENGINEERING_REVIEW.md](FINAL_SENIOR_ENGINEERING_REVIEW.md). That
document is **not** treated as ground truth here — every design decision in it was
re-opened, and several were found to be wrong or incomplete. Where this audit
disagrees with the first review, that disagreement is called out explicitly rather
than smoothed over.

## 1. Executive Summary

This pass found and fixed **6 high-severity issues** (one of which — a mandate
with zero compiled hard rules silently approving every purchase — is the most
serious defect found in this codebase across both audits) and **9 medium/low**
issues, spanning the policy compiler, the rules engine's multi-item handling, the
payment boundary's idempotency-key logic, human-resolution's trust boundary, the
live worker's crash resilience, and the HTTP client's failure handling. All fixes
ship with regression tests. The official 45-event replay produces the **same
decision, for the same reason, on every one of the 45 events** before and after
this pass — every fix closes a real gap without changing behavior on the
well-formed official data, which is the outcome a hardening pass should have.

The test suite grew from **111 to 161 tests** (50 new, all adversarial or
regression tests for a specific finding below — none of them merely restate
existing implementation behavior).

## 2. What Was Audited

Every module in `src/wallet_control/` was re-read from scratch with an explicit
adversarial framing (Phase 0–2 of the audit brief): assume each of policy
compilation, fact extraction, rule evaluation, uncertainty handling, duplicate
detection, session-integrity, spending windows, currency conversion, mandate
lifecycle, the payment boundary, idempotency, the live worker, the API mapping,
the demo API/UI, and the tests themselves could all be wrong. The official
challenge documents (challenge.md, technical_details.md, the data dictionary, and
the JSON schemas) were re-read against the code line by line rather than trusted
from memory of the first pass.

## 3. Previous Assumptions Challenged

- **"111 passing tests means the invariants are covered."** They covered the
  *documented* invariants well, but not the failure modes only visible once you
  actively try to break the code (a mutated retry, a reused idempotency key, a
  resolution answered with a different amount than what was reviewed).
- **"An empty mandate is an edge case, not a security bug."** It is the single
  most important finding in this document — see §4, Finding 1.
- **"The offline replay's unchanged 19/2/24 result after hardening proves nothing
  broke."** Reframed: it proves the fixes are correctly scoped to genuinely
  adversarial/malformed inputs the official data never exercises, which is the
  right outcome, not a report that nothing needed fixing.
- **"`item.name_contains`/`item.size` checking the whole basket is conservative,
  hence safe."** It is actually a false-positive risk (Finding 5) that happened not
  to matter for these 45 events only because every "wrong" line in the official
  data is *also* independently caught by `item.category`.
- **"The live worker's docstring claim that a fault 'must degrade to keep waiting,
  not approve by default' was actually true for every failure mode."** It was true
  for HTTP error statuses and false for network-level failures (Finding 6) and for
  process crashes (Finding 4) — two of the exact scenarios technical_details.md
  and the audit brief ask about.

## 4. Findings

### Finding 1 — CRITICAL: a mandate with zero hard rules approves every purchase

**Files/functions:** `policy_compiler.compile_instruction`, `decision_engine.evaluate_authorization`, `decision_engine._decide`.

**Root cause:** `_decide()`'s logic only escalates to REVIEW/BLOCK based on rule
*failures* or *unknowns*. With `hard_rules == []`, there is nothing to fail or be
unknown about, so every purchase fell through to `return "allow", (...)` —
**regardless of the mandate's `uncertainty_policy`**. A vague, garbled, or simply
unparseable customer instruction ("Buy whatever seems reasonable.") compiles to
zero rules and therefore became unlimited spending authority. This is exactly the
"blank cheque" challenge.md's opening line asks the wallet control layer to
prevent, and it was possible to reach it with entirely ordinary, non-malicious
input — no injection or adversarial merchant text required.

**Fix:** `evaluate_authorization` now appends a synthetic `unknown` evaluation
(`mandate.has_no_rules`) whenever `mandate.hard_rules` is empty, which routes the
decision through the mandate's own `uncertainty_policy` like any other missing
information (ASK by default → every purchase needs the customer; DECLINE →
nothing is spent; APPROVE → only if the customer explicitly, visibly chose that).
`policy_compiler.compile_instruction` also now emits a prominent `open_question`
when it produces zero rules, so a UI showing the compiled policy before
confirmation cannot present an empty rule set as if it were a real policy.

**Regression tests:** `test_decision_engine.py::test_mandate_with_no_hard_rules_asks_by_default_rather_than_allowing_everything`, `::test_mandate_with_no_hard_rules_and_decline_policy_declines_everything`, `::test_mandate_with_no_hard_rules_and_explicit_approve_policy_still_allows`, `test_policy_compiler.py::test_zero_rules_compiles_but_is_flagged_prominently`.

### Finding 2 — HIGH: human resolution accepted a caller-supplied amount

**File/function:** `state.RunState.record_resolution` (formerly took `billing_amount_chf` as a parameter), `decision_engine.resolve_authorization`.

**Root cause:** `record_resolution(authorization_id, final_decision, billing_amount_chf, timestamp)` used the **parameter's** `billing_amount_chf` for both the stored decision and the rolling-spend-window entry, not the amount that was actually reviewed. A caller (a compromised or buggy API/UI layer) could resolve a step_up "approve" with a *different* amount than what the customer was shown — the wallet would then treat that different amount as approved and count it into spend, all while every regression test at the time used the correct value by convention and so never caught it.

**Fix:** `record_resolution` and `resolve_authorization` no longer accept an amount at all. The amount used is always `existing.billing_amount_chf`, sourced from the stored review record created when the purchase was first evaluated. It is now structurally impossible for a resolution to be bound to a different amount than what was reviewed.

**Regression test:** `test_human_resolution.py::test_resolution_amount_comes_from_the_original_review_not_the_caller`.

### Finding 3 — HIGH: a resolved step_up's spend was attributed to the wrong clock

**File/function:** `state.RunState.record_resolution`.

**Root cause:** technical_details.md is explicit: *"Use simulated purchase time for spending windows, and the real clock for response deadlines."* The original `record_resolution` took a `timestamp` parameter that every caller filled with `datetime.now(timezone.utc)` (real clock) and used it as the spend-window entry's timestamp. A step_up resolved an hour, a day, or across a rolling-window boundary later (real time) would have its approval misfiled under the *resolution* time instead of the *purchase* time — silently corrupting rolling-window math in either direction depending on which side of a window boundary the real-clock answer happened to land on.

**Fix:** the spend-window entry now always uses `existing.timestamp` (the original, simulated purchase time stored at first evaluation). A new, separate `resolved_at` field records the real-clock answer time for audit display only, never for window math.

**Regression test:** `test_human_resolution.py::test_resolution_uses_the_original_simulated_purchase_time_for_spend_windows_not_real_clock_resolution_time` — explicitly resolves a step_up an hour after the (simulated) purchase and checks the rolling window sees the approval attributed to the purchase time, not the resolution time.

### Finding 4 — HIGH: a same-`authorization_id` retry with different facts was blindly trusted

**File/function:** `decision_engine.evaluate_authorization`'s idempotency check (formerly keyed on `authorization_id` alone).

**Root cause:** the repeated-delivery check only compared `authorization_id`. A redelivered event under the same ID but with a different amount, merchant, or basket (a platform bug, a MITM, or a compromised agent trying to slip a bigger charge under an already-approved ID) would be treated as an ordinary retry and the *original* decision returned unchanged — with no signal that anything had changed. This is exactly the "same authorization with mutated fields" case Phase 8/11 of the audit brief calls out.

**Fix:** `StoredDecision` now carries a fingerprint (`merchant_id`, `basket_key`, `billing_amount_chf`) of what was actually decided. A repeated `authorization_id` is checked against that fingerprint (`RunState.check_repeat_fingerprint`); on a match it is a genuine retry (unchanged behavior); on a mismatch, `evaluate_authorization` returns a distinct `authorization_id_conflict` result — `decision="block"`, the *original* stored decision is left untouched (so the payment boundary keeps enforcing the amount that was actually approved), and the live worker never re-submits a decision for it (the platform may already have the original).

**Regression tests:** `test_decision_engine.py::test_repeated_authorization_id_with_a_different_amount_is_flagged_not_trusted`, `::test_repeated_authorization_id_with_a_different_merchant_is_flagged`, `::test_genuinely_identical_repeated_delivery_is_not_flagged_as_a_conflict`, `test_live_worker.py::test_a_mutated_retry_is_never_resubmitted_and_original_decision_stands`.

### Finding 5 — HIGH: `item.name_contains`/`item.size` checked the whole basket, not the requested item

**File/function:** `rules.evaluate_rule` (the `item.name_contains` and `item.size` branches).

**Root cause:** both rules required *every* item line in the basket to match, with no scoping. An unrelated add-on (already independently, correctly flagged by `item.category`/`item.unrequested_present`) sitting in the same basket as the *correct* primary item would make the correct item's own name/size check fail too — not because anything was wrong with the requested item, but because an unrelated line was present. On the official data this happened to be harmless (every "wrong" line was already caught by `item.category`), but it is a real false-positive generator for any basket combination where a legitimate accessory shares a cart with the exact right primary item, and it is the kind of "aggregation hides the real signal" bug Phase 5 of the audit explicitly warns about (in the opposite direction from the classic min/max concern: over-restriction, not under-restriction).

**Fix:** both rules now evaluate against `_candidate_items` — items in the mandate's requested category, if one is on file, falling back to the whole basket only when nothing matches that category (so an all-wrong-category basket still shows a concrete, honest mismatch rather than a vague "nothing to check").

**Regression tests:** `test_rules_engine.py::test_item_name_contains_is_scoped_to_the_requested_category_not_the_whole_basket`, `::test_item_name_contains_still_fails_when_the_requested_category_item_itself_is_wrong`, `::test_item_size_is_scoped_to_the_requested_category_not_an_unrelated_addons_size`.

### Finding 6 — HIGH: a network-level API failure crashed the live worker instead of retrying

**File/function:** `viseca_client.VisecaClient._request`.

**Root cause:** `_request` only wrapped HTTP status codes (`response.status_code >= 400`) into `VisecaApiError`. A genuine network failure — a timeout, a dropped connection, a DNS blip, i.e. exactly "what happens if the API disappears for 30 seconds?" from the audit brief — raises `httpx.HTTPError` subclasses that are never caught by `live_worker.py`'s single `except VisecaApiError` handler. Such a failure would propagate all the way out of `run_forever`'s poll loop and crash the worker process, directly contradicting the module's own documented invariant ("a fault here must degrade to keep waiting, not approve by default") — the invariant held for HTTP error statuses and silently did not hold for the network-level case.

**Fix:** `_request` now wraps the actual `self._client.request(...)` call in a `try/except httpx.HTTPError`, normalizing any network-level failure into the same `VisecaApiError(0, ...)` the HTTP-status path already raises, so `live_worker.py`'s existing handler now genuinely covers every way a call can fail.

**Regression tests:** `test_viseca_client.py::test_network_level_failure_is_normalized_to_viseca_api_error`, `::test_dns_or_connection_failure_is_also_normalized`.

### Finding 7 — MEDIUM: `MockPSP.charge`'s idempotency key could be reused across different requests

**File/function:** `payment.MockPSP.charge`.

**Root cause:** `if charge_id in self._charges: return self._charges[charge_id]` returned the original record for *any* re-use of a `charge_id`, without checking that the new request's `authorization_id`/`amount_chf` actually matched what that `charge_id` was first used for. An attacker (or a bug) could submit `charge(charge_id="X", authorization_id="AU_legit", amount=50)` followed by `charge(charge_id="X", authorization_id="AU_other", amount=999)` and receive back a "successful"-looking `ChargeRecord` — for the *original* authorization, silently, with no error — rather than a refusal that a genuinely different request was attempted under an already-used key. Related: the charge boundary also did not verify the merchant being charged matched the merchant the authorization was actually approved for.

**Fix:** a `charge_id` re-use now requires the `authorization_id` and `amount_chf` to match the original recorded charge exactly; any mismatch raises `PaymentError`. `charge()` also now requires and checks a `merchant_id` parameter against the stored decision's merchant.

**Regression tests:** `test_payment_boundary.py::test_reusing_a_charge_id_for_a_different_authorization_is_refused_not_silently_returned`, `::test_reusing_a_charge_id_for_a_different_amount_on_the_same_authorization_is_refused`, `::test_cannot_charge_the_wrong_merchant_for_an_approved_authorization`.

### Finding 8 — MEDIUM: a second, conflicting human resolution was silently ignored, and a resolve on a never-reviewed authorization wasn't clearly distinguished

**File/function:** `state.RunState.record_resolution`, `api.resolve_run_authorization`.

**Root cause:** the original `record_resolution` treated *any* call to an already-resolved authorization as a no-op returning the original decision — including a genuinely *different* second answer (a customer clicking "decline" after having already, unbeknownst to them, had "approve" go through via a race or a UI bug). Silently discarding a real, different human answer with no error is worse than surfacing the conflict. Separately, "was never put to review at all" and "was reviewed and already resolved" were indistinguishable from the caller's point of view.

**Fix:** `StoredDecision` now tracks `was_reviewed`. `record_resolution` raises `ResolutionError` (a `ValueError` subclass) for (a) an authorization never seen, (b) one that was decided automatically and never put to review, and (c) one already resolved with a *different* answer than the new request — while a retried resolution with the *same* answer as before succeeds idempotently. `api.py` maps `ResolutionError` to HTTP 409.

**Regression tests:** `test_human_resolution.py::test_repeating_the_same_resolution_is_idempotent`, `::test_resolving_with_a_conflicting_answer_after_the_fact_is_an_error_not_a_silent_ignore`, `::test_cannot_resolve_an_authorization_that_was_auto_decided_and_never_reviewed`, `test_api.py` updated end-to-end.

### Finding 9 — MEDIUM: stale duplicate-detection state after a step_up is later declined

**File/function:** `state._RecentAttempt`, `state.RunState.find_similar_recent`.

**Root cause:** `_RecentAttempt` stored a frozen copy of the decision *at the time it was first evaluated*. `find_similar_recent`'s exclusion of declined prior attempts ("a declined attempt is not an unwanted duplicate order to worry about") checked this frozen copy — so a purchase that was `review`ed and *later* declined by the customer stayed forever recorded as "review" in the duplicate-detection fingerprint list, meaning a subsequent similar purchase could be flagged as suspiciously similar to a purchase that was, in fact, already declined.

**Fix:** `_RecentAttempt` no longer stores a decision at all; `find_similar_recent` looks the current decision up live from `RunState._decisions`, so a later resolution is reflected immediately.

**Regression test:** `test_duplicate_and_retry.py::test_a_step_up_later_declined_by_the_customer_stops_counting_as_a_live_duplicate`.

### Finding 10 — MEDIUM: multi-item return-window aggregation could hide a silent item's unstated terms

**File/function:** `facts.build_purchase_facts` (return-window computation).

**Root cause:** `min()` was taken only over item lines that *happened* to state a return window, silently ignoring lines that said nothing about returns at all. A two-item order where one line states "30 days" and the other says nothing would report the *order's* return window as 30 days — even though the second item's actual terms are genuinely unknown. This is precisely the "aggregation hides missing information" failure mode Phase 5 of the audit brief warns min()/max() can cause.

**Fix:** the order's return window is now `unknown` unless *every* item line states one (when `order_returnable == "true"`); only then is `min()` taken, as the most restrictive of fully-known values.

**Regression tests:** `test_facts.py::test_multi_item_return_window_is_unknown_when_any_item_is_silent_about_it`, `::test_multi_item_return_window_is_known_when_every_item_states_one`.

### Finding 11 — MEDIUM: several `viseca_client.py` calls assumed a non-empty JSON body

**File/function:** `viseca_client.py`, most mandate/run endpoints.

**Root cause:** technical_details.md does not pin down the exact status code every endpoint uses for a body-less success. A `DELETE /v1/mandates/{id}` returning HTTP 204 No Content (idiomatic REST, plausible for this endpoint) would have crashed `revoke_mandate()` with a JSON decode error — at exactly the moment a customer tries to exercise the revocation path the demo is specifically supposed to show.

**Fix:** every `.json()` call site now goes through a small `_json_or_empty` helper that returns `{}` for a 204 or empty body instead of raising.

**Regression test:** `test_viseca_client.py::test_a_204_response_does_not_crash_json_parsing`.

### Finding 12 — MEDIUM: no crash-recovery story for the live worker's in-memory state

**File/function:** `live_worker.py`, `state.RunState`.

**Root cause:** `RunState` lives only in process memory. A process crash mid-run would silently forget every prior decision and approved-spend entry. On restart, a rolling-window rule would under-count prior approvals (since the amounts are forgotten) and could wrongly approve a purchase that should have been blocked by an already-exceeded window — a real, previously undocumented correctness risk, not just a duplicate-submission risk. The audit brief is explicit that "do NOT simply claim idempotency because an authorization_id is stored locally" and asks for "the safest possible reconciliation strategy... document the residual limitation honestly."

**Fix (partial, explicitly not a full guarantee):** `RunState` gained `to_snapshot()`/`from_snapshot()`. `LiveWorker` accepts an optional `checkpoint_dir` and, when set, writes an atomic JSON checkpoint after every decision/resolution and reloads it when a run is (re-)registered — recovering the *same process* restarting. A second, best-effort `LiveWorker.reconcile_run()` queries the platform's own `GET /v1/authorizations` to recognize authorization_ids the platform already has a decision for, implemented defensively (the response shape isn't fully pinned down by technical_details.md) so it degrades to "nothing recovered" rather than crashing.

**What this does NOT fix, honestly:** `reconcile_run` cannot rebuild rolling-window amounts/timestamps from an undocumented response shape without risking a fabricated, wrong number, so it deliberately does not try — it only prevents a duplicate *submission*. True crash safety across an unrecoverable checkpoint (a different machine, a wiped disk) still has a residual gap; see §10.

**Regression tests:** `test_live_worker.py::test_checkpoint_persistence_survives_a_simulated_process_restart` (constructs a fresh `LiveWorker`+fake client against the same checkpoint directory and verifies a rolling-window limit that would otherwise be wrongly bypassed is correctly enforced after "restart"), `::test_reconcile_run_recognizes_already_decided_authorizations_without_crashing_on_unknown_shape`, `::test_reconcile_run_never_raises_when_the_listing_call_itself_fails`.

### Finding 13 — LOW: three compiler regexes were prone to false positives on ordinary language

**File/function:** `policy_compiler.py` (`_ITEM_MODIFIER_RE`, `_SIZE_RE`), `facts.py` (`_SIZE_RE`).

**Root cause:**
- `_ITEM_MODIFIER_RE` allowed up to 3 filler words between a hyphenated adjective and the noun it was assumed to modify. "Buy me a well-made pair of running shoes" would extract `"well-made"` as if it were a required product-variant name — an unsatisfiable-by-any-real-product lock created from ordinary descriptive language.
- `_SIZE_RE` matched `\bsize\s+(\w+)\b` with no restriction on the captured token, so "the appropriate size for everyone" extracted `size="for"`.

Both would have surfaced as false, hard-to-diagnose blocks against every future purchase under that mandate.

**Fix:** the gap in `_ITEM_MODIFIER_RE` is capped at one filler word (still matches "27-inch [computer] monitor" and "road-running shoes", not "well-made ... shoes"). `_SIZE_RE` (in both `policy_compiler.py` and `facts.py`) is restricted to plausible size tokens (a number, optionally with one decimal, or a standard letter size XS–XXXL).

**Regression tests:** `test_policy_compiler.py::test_benign_hyphenated_adjective_far_from_the_noun_does_not_lock_an_unsatisfiable_variant`, `::test_size_extraction_does_not_misread_ordinary_language_as_a_size`, `test_facts.py::test_size_extraction_rejects_implausible_tokens`.

### Finding 14 — LOW: contradictory or corrective amounts in one instruction silently used only the first match

**File/function:** `policy_compiler.compile_instruction`.

**Root cause:** `_AMOUNT_RE.search(text)` returns only the *first* regex match. "Buy up to CHF 100... actually, no more than CHF 50" would silently compile a CHF 100 ceiling, discarding the customer's own correction.

**Fix:** all amount matches in the instruction are now collected; the *minimum* (most restrictive) is used, and an `open_question` is raised whenever more than one distinct amount was found, so the ambiguity is visible rather than silently resolved one way.

**Regression tests:** `test_policy_compiler.py::test_contradictory_amounts_take_the_more_restrictive_and_flag_the_ambiguity`, `::test_a_single_repeated_identical_amount_is_not_flagged_as_contradictory`.

### Finding 15 — LOW: Unicode obfuscation of merchant-supplied text was not normalized before matching

**File/function:** `facts.py` (all three extraction functions).

**Root cause:** zero-width characters or fullwidth-digit lookalikes inside `item_details` (e.g. `"retu​ns accepted within 30 days"`) would silently defeat the whitelist extraction patterns. The *direction* of failure was safe (a defeated match becomes "not stated," which routes to uncertainty, never to a silent approval), but this is still a real robustness gap the audit brief explicitly asks to test, and it is cheap to close.

**Fix:** all untrusted text is passed through NFKC normalization plus stripping of common invisible/zero-width characters before any pattern is applied. Also applied defensively to catalogue-sourced `item_name`, in case a future scenario source is less trustworthy than the current fixtures.

**Regression tests:** `test_facts.py::test_zero_width_and_fullwidth_unicode_do_not_defeat_extraction`, `::test_final_sale_detection_survives_obfuscation`, `::test_item_name_is_normalized_before_matching`.

### Finding 16 — LOW: an implausible merchant-stated return window would be trusted at face value

**File/function:** `facts.extract_return_window_days`.

**Root cause:** nothing bounded the extracted day count. A merchant claiming "returns accepted within 999999999 days" would trivially satisfy any `>=` return-window requirement, since a bigger untrusted number always passes.

**Fix:** a plausibility bound (3650 days / 10 years) is applied; anything beyond it is treated as not stated (routes to uncertainty, not a false pass).

**Regression test:** `test_facts.py::test_implausible_return_window_is_treated_as_not_stated`.

### Finding 17 — LOW (found while writing the regression test for a fix in this same pass): `\Z` vs `$` in the newly added identifier-format check

**File/function:** `mandate.py`, `_ID_RE`.

**Root cause:** while adding ID-format validation to close the dead-code finding below, the first version used `^[A-Za-z0-9_.:-]+$`. Python's `$` matches at the end of the string *or* just before a single trailing newline — so `"CU1\n"` incorrectly passed validation. This finding exists entirely within work done during this audit; it did not exist in the previously-reviewed code (there was no ID validation at all before this pass — see Finding 18) and is recorded for completeness and honesty, not to inflate the count.

**Fix:** changed to `\Z`, which has no such exception.

**Regression test:** `test_mandate_lifecycle.py::test_confirm_rejects_malformed_identifiers` (parametrized with a trailing-newline case specifically).

### Finding 18 — LOW: dead code — `_ID_RE`, an unused `now` parameter, `created_at` never surfaced

**File/function:** `mandate.py`.

**Root cause:** `_ID_RE` was defined and never referenced anywhere (confirmed by `grep`) — an identifier-format check that looked wired in but was not. `Mandate.is_usable(self, *, now: datetime | None = None)` accepted a parameter that was never read, implying time-based expiry logic that does not exist. `Mandate.created_at` was recorded but never exposed anywhere, including `as_dict()`.

**Fix:** `_ID_RE` is now used in `Mandate.confirm()` to validate `customer_id`/`card_id`/`profile_id` shape (see Finding 17 for the regex fix this produced). The unused `now` parameter was removed from `is_usable()`. `created_at` is now included in `as_dict()`.

**Regression test:** covered by Finding 17's test; `as_dict()`'s new field is exercised implicitly by every existing `as_dict()`-based test (`test_api.py`).

### Also examined, no defect found

- **Rolling-window boundary semantics** (`rolling_spend_chf`'s `window_start < ts <= as_of`): re-derived by hand against the official SCEN0001 data a second time; confirmed correct and unambiguous for every one of the 10 events.
- **The hard-rules-are-conjunctive (AND) architecture as a defense against "weakening via PATCH."** Initially flagged as a possible gap ("what stops a PATCH from adding a *weaker* rule?"), then disproven by tracing the actual evaluation semantics: because every hard rule is evaluated independently and *any* failure blocks, an added weaker or even directly contradictory rule can never relax an existing stricter one — the existing rule keeps failing on exactly the purchases it always failed on. This is a genuinely sound property of the architecture, not a gap; no fix was needed, and it is worth stating plainly since the first review did not call it out explicitly.
- **Currency/amount manipulation via the item-line schema** (`item.item_name` as a possible injection vector beyond `item_details`): traced every consumer of `item_name` and confirmed it is only ever used for literal, safe substring containment (`item.name_contains`) — there is no path from item-name content to a new rule or a widened comparison, so even a maximally adversarial `item_name` cannot do more than fail or pass a customer-authored substring check.
- **Mandate PATCH's `guidance`/`open_questions` wholesale replacement:** confirmed these are explanatory text only, never read by `rules.py` or `decision_engine.py`, so replacing them carries no authority risk.

## 5. Remaining Limitations (honest)

- **Crash recovery is best-effort, not a guarantee.** The checkpoint mechanism (Finding 12) protects the same process restarting with the same checkpoint directory. A restart on a different machine, or with the checkpoint lost, still cannot fully reconstruct rolling-window history from the hosted API alone without a documented, richer `GET /v1/authorizations` response shape than technical_details.md specifies. This has never been exercised against the real hosted API (still no event-day key available while writing this).
- **The policy compiler remains a fixed lexicon.** The regex tightening in Findings 13/14 closes specific false-positive patterns found by active adversarial testing; it does not make the compiler a general natural-language system, and an instruction using vocabulary genuinely outside its lexicon still correctly surfaces as an `open_question` rather than being understood.
- **The amount-integrity check (a new always-on safety check added in this pass, comparing `billing_amount_chf` to `amount × fx_rate`) has a fixed CHF 0.02 tolerance** chosen to allow for double-rounding artifacts; it has not been validated against real-world floating-point/rounding edge cases beyond the synthetic fixtures, since the official data is (by construction) always internally consistent.
- **No formal concurrency testing was performed** on `LiveWorker`'s single lock around run registration; the documented single-process, single-worker operating model (unchanged from the first review) means this has not been a practical concern, but it has also not been load-tested.
- **This audit, like the first, is one more pass by the same author with the same blind spots as an engineer.** A different reviewer would very plausibly find things this pass did not.

## 6. Official Replay Results

```
events processed: 45
allow:  19
review:  2
block:  24
```

Identical to the first review's numbers, and — more importantly — identical
**decision-for-decision and reason-code-for-reason-code** (verified by diffing the
full per-authorization output before and after this pass). Every fix in this
document is scoped precisely enough to leave well-formed official data untouched
while closing a real gap for malformed or adversarial input.

## 7. Security Test Results

All adversarial tests pass: prompt injection (existing + Finding 15's Unicode
obfuscation additions), merchant lookalikes (existing), payment-boundary misuse
including charge_id reuse across different requests and wrong-merchant charges
(Finding 7, new), duplicate/replay across both idempotency mechanisms including
the newly-exercised mutated-retry case (Finding 4, new), and mandate-authority
tests including the newly-added malformed-identifier rejection (Finding 18/17).

## 8. Live Worker Results

204 handling, poll-failure resilience, step_up/resolve separation, and
auto-registration all still pass (unchanged from the first review) plus newly
verified: network-level failure normalization (Finding 6), mutated-retry
non-resubmission (Finding 4), and crash-recovery via checkpoint (Finding 12) —
the checkpoint test specifically demonstrates a rolling-window limit that a naive
in-memory-only restart would have wrongly bypassed is correctly enforced once
recovery is wired in.

## 9. Payment Boundary Results

All prior guarantees hold (decline/pending cannot pay, amount ceiling, one
execution per authorization) plus newly verified: charge_id cannot be silently
reused for a different authorization or amount (Finding 7), and a charge is now
bound to the merchant that was actually approved, not just the amount (Finding 7).

## 10. Final Architecture

Unchanged from [ARCHITECTURE.md](ARCHITECTURE.md) at the diagram level — the
authorization boundary (agent proposal → deterministic rules → ALLOW/REVIEW/BLOCK
→ human intervention when needed → payment execution, independently re-gated) is
the same shape. What changed is that several of the boundary's internal trust
assumptions are now enforced rather than assumed: a resolution's amount and
timestamp are sourced from the record, not the caller; a repeated authorization
is verified to actually be the same purchase, not just the same ID; a charge_id is
bound to one specific request, not reusable; and a mandate with nothing to check a
purchase against no longer defaults to permissive.

## 11. Why This Architecture Is Still Appropriate for a Hackathon

None of the 18 findings required new infrastructure. The most structurally
significant fix (Finding 12, crash recovery) is a single JSON file per run, not a
database — deliberately smaller than what a "real" fix would look like in
production, and documented as such. Every other fix is a tightened check, a
corrected trust boundary, or a scoped-down comparison within files that already
existed. The architecture did not need to change shape to fix any of this; it
needed its own stated invariants actually enforced everywhere they were claimed.

## 12. What Is Intentionally NOT Implemented

Same as the first review, unchanged: no LLM in the decision path, no database, no
message queue, no distributed worker, no expiry-clock logic for mandates beyond
what the official API itself would report, no attempt to resolve the officially
unspecified "mandate revoked while a purchase is already queued" behavior.
Additionally, after this pass: no attempt to reconstruct rolling-window amounts
from the best-effort platform reconciliation (Finding 12) — fabricating a number
from an undocumented shape would be worse than admitting it can't be safely done.

## 13. What a Senior Reviewer Should Still Question

- Whether the CHF 0.02 amount-integrity tolerance (Finding 5's sibling, the
  always-on integrity check added alongside it) is the right number, or should be
  configurable/derived from the actual rounding rules rather than a fixed constant.
- Whether `item.name_contains`/`item.size`'s fallback-to-whole-basket behavior
  (when nothing matches the requested category at all) is the most useful
  behavior, versus simply reporting `unknown` in that case too.
- Whether the checkpoint mechanism's atomic-write approach (`tmp` file +
  `os.replace`) is sufficient on the actual event-day deployment target, which
  has not been specified or tested here.
- Whether `reconcile_run`'s decision to log-only (never fabricate a `StoredDecision`
  from the undocumented `GET /v1/authorizations` shape) is the right tradeoff, or
  whether a richer, explicitly-tested response contract would justify attempting a
  fuller reconstruction.
- Whether this second pass has itself introduced new blind spots — it was
  performed by the same author as the first pass and the original implementation,
  and every self-audit has that structural limitation.

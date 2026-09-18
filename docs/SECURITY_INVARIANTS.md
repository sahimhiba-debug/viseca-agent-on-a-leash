# Security invariants (historical, per-pass record)

> **The authoritative list is `docs/SECURITY_INVARIANTS_FINAL.md`.** This file is
> kept as the chronological record of how each invariant was discovered, pass by
> pass (I1-I32, in discovery order). Where the two differ, the final list wins --
> notably I29, which the deep-security pass proved was NOT holding as stated here
> (a human-approved step-up minted no authority, so nothing revoked it).

A formal list of the properties this system must never violate, grouped the way
the third-pass audit brief asked for (AUTHORITY / PAYMENT / REPLAY / POLICY / TIME
/ FAILURE). For each invariant: what enforces it, and what test would fail first
if it broke. Where a property is checked by a Hypothesis property-based test, that
means it was verified against generated inputs, not just the hand-picked examples
also listed.

## Authority

**I1. No authority exists without a valid customer-confirmed mandate.**
> **This was FALSE as stated until the proof pass (V12).** `Mandate.confirm()` is
> indeed the only route to ACTIVE, but nothing re-checked that the snapshot was
> STILL active at evaluation time, so a revoked mandate kept authorizing. See
> `SECURITY_INVARIANTS_FINAL.md` F0.

Enforced by: `Mandate.confirm()` is the only path from `DRAFT` to `ACTIVE`, and
`decision_engine.evaluate_authorization` only ever reads `mandate.hard_rules` from
a `MandateSnapshot`, which can only be produced by `Mandate.snapshot()` on an
already-active mandate. Tested by: `test_mandate_lifecycle.py::test_confirm_requires_explicit_true`.

**I2. An empty/unparseable policy must never silently become unlimited authority.**
The single most significant finding across all three audit passes. Enforced by:
`evaluate_authorization` treats `mandate.hard_rules == []` as maximal uncertainty,
routed through `uncertainty_policy` (ASK by default), never as "everything
passes." Tested by: `test_decision_engine.py::test_mandate_with_no_hard_rules_asks_by_default_rather_than_allowing_everything`
and its DECLINE/APPROVE siblings.

**I3. Mandate mutation can never increase authority.**
Enforced by: `Mandate.tighten_hard_rules` only appends (never removes/replaces),
`HardRule` is frozen (an existing entry cannot be edited in place), and
`set_uncertainty_policy` only allows transitions towards `decline`. Because every
hard rule is evaluated independently and any single failure blocks the whole
purchase, an appended rule -- even a weaker or directly contradictory one -- can
never relax an existing stricter rule (traced explicitly in the second audit
pass; this is a real, load-bearing property of the "rules are a conjunction"
design, not an incidental one). Tested by:
`test_mandate_lifecycle.py::test_tighten_hard_rules_only_appends_never_removes`,
`::test_uncertainty_policy_transitions_are_tighten_only`.

**I4. Revocation cannot create new authority.**
`Mandate.revoke()` only ever moves status towards `REVOKED`/terminal; there is no
code path from `revoke()` back to `ACTIVE`. Tested by:
`test_mandate_lifecycle.py::test_revoke_is_terminal_and_idempotent`,
`test_api.py::test_run_scenario_and_full_human_resolution_and_revocation_flow`.

**I5. Human resolution cannot increase authority beyond the reviewed transaction.**
`resolve_authorization`/`RunState.record_resolution` touch only the one
`authorization_id` they resolve; there is no code path from a resolution into
`Mandate`. Tested by: `test_human_resolution.py::test_resolving_a_step_up_does_not_touch_the_mandate`.

**I6. A resolution cannot change merchant, amount, basket, currency, or other
security-sensitive facts.**
`record_resolution` takes no amount (or any other fact) parameter at all -- it
always uses `existing.billing_amount_chf`/`existing.merchant_id`/`existing.basket_key`
from the original review record. A caller cannot supply a different value even by
accident. Tested by: `test_human_resolution.py::test_resolution_amount_comes_from_the_original_review_not_the_caller`.

## Payment

**I7. BLOCK cannot result in payment.**
**I8. An unresolved REVIEW/STEP_UP cannot result in payment.**
Both enforced by the same check: `MockPSP.charge` requires `stored.decision == "allow"` exactly (not `"review"`, not `"block"`). Tested by example
(`test_payment_boundary.py::test_cannot_charge_a_declined_authorization`, `::test_cannot_charge_a_pending_step_up`)
and by property (`test_properties.py::test_property_block_or_review_can_never_be_charged`,
generated over arbitrary amounts/merchant-familiarity combinations).

**I9. Payment amount cannot exceed approved authority.**
`MockPSP.charge` rejects `amount_chf > stored.billing_amount_chf`. Tested by
example and by property (`test_properties.py::test_property_charge_never_exceeds_approved_amount_or_wrong_merchant`,
`::test_property_amount_over_ceiling_never_allows`).

**I10. Payment merchant must equal approved merchant.**
`MockPSP.charge` rejects `merchant_id != stored.merchant_id`. Same property test
as I9 covers this jointly (both the amount and merchant axes are varied together).

**I11. One authorization cannot silently execute multiple times.**
*(Superseded: that in-memory set was removed in the proof pass. Single-use now lives on the persisted authority as `consumed_at` -- see SECURITY_INVARIANTS_FINAL.md B2, which also states the two conditions it depends on.)* Tested by:
`test_payment_boundary.py::test_one_authorization_cannot_be_charged_twice`.

**I12. Reusing an idempotency key with different semantics must fail.**
A `charge_id` re-used for a different `authorization_id` or amount raises
`PaymentError` rather than being treated as "already done." Tested by:
`test_payment_boundary.py::test_reusing_a_charge_id_for_a_different_authorization_is_refused_not_silently_returned`,
`::test_reusing_a_charge_id_for_a_different_amount_on_the_same_authorization_is_refused`.

**I12a (added in the third pass). A charge amount must be strictly positive.**
Not in the brief's original list, but a natural corollary: a zero or negative
charge is never a legitimate execution of an approved purchase. Enforced in both
`MockPSP.charge` and, defensively, in `evaluate_authorization` (a non-positive
`billing_amount_chf` on the authorization itself fails the always-on amount-
integrity check). Tested by: `test_payment_boundary.py::test_zero_or_negative_charge_amount_is_refused`,
`test_decision_engine.py::test_non_positive_billing_amount_is_blocked`.

## Replay

**I13. Same authorization + same immutable facts = safe retry.**
**I14. Same authorization + different immutable facts = conflict.**
Both enforced by `RunState.check_repeat_fingerprint`, comparing a stored
`(merchant_id, basket_key, billing_amount_chf)` fingerprint against a redelivered
event before treating it as a routine retry. Tested by example
(`test_decision_engine.py::test_genuinely_identical_repeated_delivery_is_not_flagged_as_a_conflict`,
`::test_repeated_authorization_id_with_a_different_amount_is_flagged_not_trusted`)
and by property (`test_properties.py::test_property_repeated_authorization_id_is_safe_iff_facts_are_identical`,
which varies amount and merchant independently across both deliveries).

**I15. A corrected transaction must not accidentally inherit authority from a
previous transaction.**
A re-quote after a decline (`related_authorization_id` pointing at a prior
declined attempt) is evaluated entirely fresh against the current mandate and
facts -- there is no code path that copies a decision from one `authorization_id`
to another. `related_authorization_id`/`related_authorization_status` are read
only as evidence (excluded from duplicate-suspicion when the prior was declined),
never as a source of authority. Tested by:
`test_duplicate_and_retry.py::test_a_declined_prior_attempt_is_not_treated_as_a_duplicate_conflict`.

## Policy

**I16. Merchant text cannot modify customer policy.**
**I17. Merchant text cannot create authority.**
`policy_compiler.compile_instruction` (the only producer of `HardRule`s) is never
called from `decision_engine.py` or `facts.py` -- verified structurally, not just
behaviorally, by `test_prompt_injection.py::test_decision_engine_never_compiles_a_policy_from_event_data`
(source inspection). Also verified by property:
`test_properties.py::test_property_arbitrary_item_details_never_changes_the_mandates_own_rules`,
generated over arbitrary Unicode text including injection-shaped strings.

**I18. Unknown facts cannot silently become true.**
Every rule in `rules.py` returns `"unknown"` (never `"pass"`) when the underlying
fact cannot be determined (e.g. `merchant.familiar` with no history available).
`_decide()` never treats `"unknown"` as `"pass"`. Verified by mutation testing in
the third pass: forcing `merchant.familiar`'s `None` case to return `"pass"`
broke 14 tests, confirming this is not merely asserted but actually load-bearing.

**I19. Missing facts must remain distinguishable from false facts.**
`HistoryIndex.is_familiar` returns `None` (unknown) for a card with no history at
all, and `False` (confirmed unfamiliar) for a card with history that just never
includes this merchant -- these are never conflated. Tested by:
`test_rules_engine.py::test_merchant_familiar_unknown_when_no_history`,
`::test_merchant_familiar_true_and_false`.

## Time

**I20. Spending windows use simulated purchase time.**
**I21. Response deadlines use real wall-clock time.**
`RunState.rolling_spend_chf` is always keyed on `authorization.timestamp`
(simulated); `live_worker.py`'s deadline check compares `datetime.now(timezone.utc)`
(real) against `deadline_at`. These are never the same variable anywhere in the
codebase (checked by re-reading every site that constructs a `datetime` in
`decision_engine.py`, `state.py`, and `live_worker.py` during the third pass).

**I22. Human resolution must retain the original purchase timestamp for budget
accounting.**
`record_resolution` uses `existing.timestamp` (simulated purchase time) for the
spend-window entry, and a separate `resolved_at` (real clock) for audit display
only. Tested by: `test_human_resolution.py::test_resolution_uses_the_original_simulated_purchase_time_for_spend_windows_not_real_clock_resolution_time`
-- this test specifically resolves a step_up an hour later (real time) and
confirms the rolling window sees the purchase-time attribution, not the
resolution-time one. Confirmed by mutation testing: changing the window
comparison's boundary operator broke this exact test.

## Failure

**I23. Network/API failure cannot result in approval.**
`viseca_client.VisecaClient._request` normalizes both HTTP error statuses and raw
`httpx` transport exceptions (timeouts, connection errors) into the same
`VisecaApiError`, which `live_worker.py`'s poll/submit loops catch and retry (or,
for 401/403, stop on -- see I23a) without ever synthesizing a decision. Tested
by: `test_viseca_client.py::test_network_level_failure_is_normalized_to_viseca_api_error`,
`test_live_worker.py::test_a_poll_failure_never_becomes_an_approval`.

**I23a (added in the third pass). An unrecoverable auth failure must stop the
worker loudly, not retry forever.** 401/403 on poll raises `FatalWorkerError`;
401/403 on submit gives up immediately rather than spending the bounded retry
budget. Tested by: `test_live_worker.py::test_a_401_on_poll_stops_the_worker_instead_of_retrying_forever`,
`::test_a_403_on_poll_also_stops_the_worker`, `::test_a_401_on_submit_does_not_retry_and_is_logged_not_swallowed`.

**I24. Process failure cannot result in approval.**
There is no code path anywhere that defaults an unhandled exception or a crash to
`"allow"`; `run_forever`'s outer `try/except Exception` around envelope handling
logs and continues polling rather than approving. A crash that kills the process
entirely simply stops the worker -- it cannot, by construction, cause any
approval that wasn't already decided and durably recorded (see I25).

**I25. Restart cannot silently forget security-relevant spending state when that
state is required for correctness.**
Partially and honestly only partially solved: `LiveWorker(checkpoint_dir=...)`
persists `RunState` to a local JSON file after every decision/resolution and
reloads it on restart, closing the specific risk of a rolling-window limit being
bypassed after an in-process crash. `reconcile_run()` supplements this with a
best-effort check against the platform's own decided-authorizations list for the
case where no local checkpoint survives. Neither is a full distributed-transaction
guarantee -- see docs/MASTER_R_AND_D_AUDIT.md, "Remaining limitations," for what
is honestly still open. Tested by:
`test_live_worker.py::test_checkpoint_persistence_survives_a_simulated_process_restart`
(constructs a fresh worker + fresh fake client against the same checkpoint
directory and confirms a rolling-window limit that a naive restart would bypass is
correctly enforced).

**I26 (added in the fourth pass, R&D Track A). A payment authority is single-use,
time-boxed, and independently re-checked at execution -- it does not extend the
window in which an ALLOW can be spent.**
`state.RunState.issue_authority()` mints a `PaymentAuthority` only when the
underlying decision is `"allow"` (raises `AuthorityError` otherwise), bound to a
merchant, an amount ceiling, a basket fingerprint, and a real-clock expiry
(`DEFAULT_AUTHORITY_TTL`, 15 minutes). `payment.MockPSP.charge_via_authority()`
independently re-checks expiry and explicit revocation before delegating to the
existing `charge()` (which itself re-checks merchant binding, amount ceiling, and
one-execution-per-authorization -- see I6/I9). An authority never has its expiry
extended by re-issuance: re-issuing for the same `authorization_id` returns the
original object unchanged (idempotent), never a fresh, later-expiring one. Tested
by: `test_capability_and_drift.py::test_re_evaluating_an_allowed_authorization_does_not_mint_a_second_authority`,
`::test_charge_via_authority_rejects_an_expired_authority`,
`::test_charge_via_authority_rejects_a_revoked_authority`,
`::test_charge_via_authority_rejects_amount_over_the_authoritys_own_ceiling`.

**I27 (added in the fourth pass, R&D Track A). Revocation of a payment authority
is monotonic and idempotent -- it can never be undone by a subsequent call.**
`RunState.revoke_authority()` uses `dataclasses.replace(existing, revoked=True)`
on a frozen `PaymentAuthority`; there is no code path that clears `revoked` back
to `False` once set, and calling revoke again on an already-revoked authority is
a safe no-op, not an error or a silent reset. Tested by:
`test_capability_and_drift.py::test_revoking_a_never_issued_authority_is_a_safe_no_op`,
`::test_revoking_an_already_revoked_authority_stays_revoked`.

**I28 (added in the fourth pass, R&D Tracks D/E). Explanatory evidence (drift
classification, policy/security verdict split) can never itself widen or narrow
the final decision.** `compute_drift()` and `_scoped_verdict()` are pure functions
computed AFTER `_decide()` has already produced the final `decision` from the
mandate's own rule evaluations; neither is consulted by `_decide()`, and neither
can cause a decision to change on a later, identical purchase. The
policy/security split additionally satisfies a proven monotonicity property: the
final decision is never more permissive than either scoped sub-verdict. Tested
by: `test_capability_and_drift.py::test_property_final_decision_is_never_more_permissive_than_either_scoped_verdict`
(a 200-example Hypothesis property test over all policy/security/uncertainty-policy
combinations), and by every existing decision-outcome test continuing to pass
unchanged after `drift`/`policy_verdict`/`security_verdict` were added as
purely additive fields on `EngineDecision`.

**I29 (added in the fourth/arbitration pass). Revoking the mandate revokes every
outstanding payment authority in that run.**
`RunState.revoke_outstanding_authorities()`, called from the demo API's revoke
endpoint, marks every not-yet-revoked authority revoked; `MockPSP` then refuses to
execute them. Before this, a customer could hit their emergency brake and an
already-approved-but-unspent authority would still charge. Deliberately scoped to
our own synthetic capability object: `StoredDecision` records are untouched, so
nothing the engine already told the platform changes -- technical_details.md
leaves revocation-while-queued unspecified and this does not invent a guarantee
there. Tested by: `test_final_arbitration.py::test_revoking_outstanding_authorities_stops_an_unspent_charge`,
`::test_revocation_does_not_rewrite_the_recorded_decision`,
`test_api.py::test_revoking_the_mandate_also_kills_outstanding_payment_authorities`.

**I30 (fourth pass). Expiry and revocation are enforced at the payment boundary
itself, not only in the ergonomic wrapper.**
`MockPSP.charge()` re-reads the authority from `RunState` and refuses a revoked or
expired one, so reaching for plain `charge()` cannot bypass either. Because the
live record is consulted rather than the caller-supplied object, handing
`charge_via_authority` a stale copy captured before a revocation does not
resurrect it. Tested by: `test_final_arbitration.py::test_plain_charge_refuses_a_revoked_authority`,
`::test_plain_charge_refuses_an_expired_authority`,
`::test_a_stale_authority_copy_cannot_resurrect_a_revoked_one`,
`::test_an_authorization_with_no_authority_still_charges_normally`.

**I31 (fourth pass). The repeat-delivery fingerprint carries item identity.**
`_basket_key` includes `item_name`, so re-sending an authorization_id with the
line renamed (same item_id, quantity and total) is an `authorization_id_conflict`
rather than an inherited ALLOW. Tested by:
`test_final_arbitration.py::test_renaming_a_line_under_the_same_authorization_id_is_a_conflict`.

**I32 (fourth pass). The fingerprint carries the facts DERIVED from merchant text,
never the text itself.**
`_basket_key` includes the stated size, return window and final-sale flag
extracted from `item_details`. A re-delivery whose text moves one of those facts
(e.g. "size 43; returns accepted within 30 days" -> "size 38; FINAL SALE") is a
conflict, even though merchant, amount, item_id and quantity are unchanged --
previously it inherited the stored ALLOW without re-evaluation, despite those
facts being a double rule failure when evaluated fresh. Fingerprinting the raw
string instead would fail the opposite way, forking ordinary retries on cosmetic
edits; both directions are pinned by mutation testing. Tested by:
`test_final_arbitration.py::test_details_only_change_that_moves_a_derived_fact_cannot_inherit_the_allow`,
`::test_cosmetic_only_details_noise_does_not_fork_a_valid_retry`.

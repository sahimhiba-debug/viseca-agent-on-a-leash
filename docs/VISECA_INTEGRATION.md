# Viseca integration: official contract vs. local extensions

<!-- snapshot -->
> **SNAPSHOT — written 19 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

This document exists specifically so a reviewer can tell, at a glance, which parts
of this codebase are the official challenge contract and which are this team's own
design choices layered on top.

## Official (from https://github.com/Swiss-ai-Weeks/viseca-2026)

| Concept | Where it's official | Where it's implemented here |
| --- | --- | --- |
| `authorization.request` event shape | `data/schemas/authorization_event.schema.json` | `offline_replay.build_event`, validated in `tests/test_event_schema_validity.py` |
| `hard_rules` rule format (`field`/`operator`/`value`/`currency`/`scope`/`period_days`) | technical_details.md, "Rule format" | `mandate.HardRule` |
| `approve` / `decline` / `step_up` | technical_details.md, decision table | `viseca_mapping.py` (the only place this mapping happens) |
| Mandate lifecycle: draft -> confirm -> PATCH (tighten-only) -> DELETE (revoke) | technical_details.md, steps 5 and 8 | `mandate.Mandate` |
| `GET /v1/decision-requests/next?wait=25`, HTTP 204 semantics | technical_details.md, step 6 | `viseca_client.next_decision_request`, `live_worker.LiveWorker.run_forever` |
| `POST /v1/authorizations/{id}/decision` and `/resolve` | technical_details.md, step 7 | `viseca_client.submit_decision` / `.resolve`, `live_worker.LiveWorker._submit_with_retry` / `.resolve` |
| The five public scenarios, `purchase_attempts.csv`, `purchase_attempt_items.csv`, `merchants.csv`, `authorization_history.csv`, `fx_rates.csv` | `data/` in the official repo | copied read-only into `data/official/`, loaded by `csv_data.py` |
| `SCEN0000` as the required first connection check | data/README.md | `tests/test_offline_replay.py::test_connection_check_is_a_single_ordinary_purchase_and_is_approved` |

The official synthetic data pack states explicitly that it contains **no expected
decisions** (`data/official/metadata.json`: `"contains_expected_decisions": false`).
Nothing in this codebase treats a `scenario_id`, `authorization_id`, or
`replay_order` as a lookup key for an outcome -- verified structurally in
`tests/test_offline_replay.py::test_engine_does_not_branch_on_scenario_id_or_authorization_id`.

## Local extensions (not part of the official API)

These are this team's own design, layered on top of the official contract, and
must never be confused with it:

- **`ALLOW` / `REVIEW` / `BLOCK`** -- this codebase's internal decision vocabulary.
  Only `viseca_mapping.py` translates it to the wire values `approve`/`decline`/
  `step_up`; nowhere else in the engine uses the wire words.
- **The hard-rule field vocabulary** (`merchant.familiar`, `item.category`,
  `item.unrequested_present`, `item.name_contains`, `item.size`,
  `order.return_window_days`, `session.integrity_risk`) -- these are *this
  engine's* convention for the field name a stored rule can use, exactly as
  technical_details.md invites ("The dotted field name is a convention for your
  engine to interpret, not a formula the API runs"). They are not official Viseca
  field names and would not be recognized by a different team's engine.
- **`Intervention`** (`ask_missing_fact` / `ask_this_time` / `never` /`allow`,
  `intervention.py`) -- a local, purely explanatory gloss derived from an
  already-made decision, shown in the demo UI/API. It is never sent to the hosted
  API and never influences the decision itself.
- **`order.duplicate_suspected`, `mandate.has_no_rules`, `authorization.amount_integrity`**
  -- synthetic, always-on `HardRule`s the engine appends to its own evaluation list
  (never to the mandate): a suspiciously similar recent purchase, a mandate with no
  executable rules at all (routing the decision through `uncertainty_policy`
  instead of defaulting to allow -- added in the second audit pass, see
  SECOND_ADVERSARIAL_AUDIT.md Finding 1), and a `billing_amount_chf` that doesn't
  match `amount * fx_rate` (Finding 5's sibling integrity check). All three are
  local safety signals, never something the customer wrote or the API stores.
- **`authorization_id_conflict`** -- a local-only `EngineDecision` flag (never sent
  to the hosted API) set when a repeated `authorization_id` arrives with different
  purchase facts than the first delivery; see Finding 4.
- **`MockPSP` / `payment.py`** -- an entirely local, synthetic payment executor.
  There is no official Viseca payment-execution endpoint in this challenge; this
  exists purely to make the authorization/payment boundary demonstrable and
  testable (challenge.md: "Everything is synthetic: there are no real cards,
  customers, payments, or money").
- **`api.py` / `ui/index.html`** -- the demo backend and page. They reuse the exact
  same `decision_engine`/`mandate`/`state` code as the live worker (not a separate
  reimplementation), but the HTTP surface itself (`/api/scenarios/{id}/run`, etc.)
  is a local convenience for the demo, not part of the hosted API contract.

## The hosted decision payload

`viseca_client.submit_decision` sends exactly the fields technical_details.md
documents: `authorization_id`, `decision`, and the optional `reason_codes`,
`customer_message`, `evidence`, `engine_version`. No local concept (Intervention,
`order.duplicate_suspected`, or internal rule-evaluation detail strings beyond
`evidence`) is invented as an extra top-level field on that payload.

## Live worker behavior notes

- **HTTP 204 is not "run finished."** `LiveWorker.run_forever` treats a `None`
  return from `next_decision_request` as "no work right now" and keeps polling;
  it never terminates the loop on 204 alone (`tests/test_live_worker.py::test_http_204_is_not_treated_as_run_finished_and_does_not_submit_anything`).
- **Repeated delivery of the same `authorization_id`** is reconciled locally
  (the stored decision is returned) and is **not re-submitted** to the API --
  the assumption is that the platform already has our original submission, since
  our local record is only ever created after a submission. This is the most
  defensible reading of "reconcile its saved result" given the spec does not fully
  pin down whether a second submission for an already-decided authorization would
  be accepted or rejected by the platform; see "Remaining Known Limitations."
- **A `step_up` never gets an automated second decision.** The poll loop only ever
  calls `submit_decision` once per authorization_id; a customer's answer goes
  through the entirely separate `resolve()` path, which calls `/resolve`, not
  `/decision` (`tests/test_live_worker.py::test_step_up_is_not_auto_resolved_and_resolve_uses_the_separate_endpoint`).
- **The worker never guesses platform-assigned identity.** `customer_id`,
  `card_id`, and `profile_id` are assigned by the platform when a run starts, not
  submitted by the participant (technical_details.md scenario contract). Rather
  than have the CLI script guess them, `LiveWorker` auto-registers a run from the
  `mandate` block embedded in that run's first event
  (`mandate.MandateSnapshot.from_event_mandate`).
- **Our policy compiler is NOT in the live decision path**, and this is the single
  most useful thing to know before auditing it. On event day the rules come from the
  platform: `from_event_mandate` reads `event["mandate"]["hard_rules"]` verbatim, so
  `policy_compiler.py` -- which is phrase patterns, not a model -- decides nothing
  about any live purchase. It is used in exactly two places:
    1. **Creating a mandate** (`POST /api/mandates/compile`), where the customer is
       shown the compiled rules and the `open_questions` *before* confirming. A
       mis-parse is visible to the person it affects, before it has any authority.
    2. **The offline replay**, which has no platform to supply rules and so compiles
       each scenario's `cardholder_instruction` itself.
  The consequence for (2) is worth stating plainly rather than leaving for a reader
  to discover: **the 45-event replay's 19/2/24 is conditional on our own reading of
  five English sentences.** It is a regression boundary for this pipeline, not a
  measurement of correctness against the challenge -- the official pack ships no
  expected decisions (`contains_expected_decisions: false`). If our compiler reads
  "at or below CHF 120" differently from the way Viseca's own compiler does, the live
  path is unaffected and the offline numbers move.
- **The bearer key is never logged.** See SECURITY.md.
- **A same-`authorization_id` delivery with different facts is never resubmitted
  either.** If the fingerprint check (Finding 4) detects a mismatch, the worker
  logs it loudly and does not call `submit_decision` again -- the platform already
  has a decision for that ID, and it may be the mutated event, not the original,
  that is wrong.
- **A crash can be recovered from, on a best-effort basis.** `LiveWorker(..., checkpoint_dir=...)`
  persists `RunState` to a small local JSON file after every decision/resolution
  and reloads it on restart; `LiveWorker.reconcile_run()` additionally queries
  `GET /v1/authorizations` to recognize already-decided IDs after a restart with no
  local checkpoint. Neither is a full distributed-transaction guarantee -- see
  SECOND_ADVERSARIAL_AUDIT.md, Finding 12, for exactly what this does and does not
  cover.

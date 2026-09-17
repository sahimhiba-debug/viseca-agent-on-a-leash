# Final Senior Engineering Review

## Executive Summary

This repository is a from-scratch implementation of Viseca's "Agent on a Leash"
challenge: a wallet control layer that decides whether an AI shopping agent may
spend a customer's money, independent of that agent. It was built, tested, attacked,
and documented in one pass, with a senior-engineering review applied continuously
during construction rather than as a separate pass at the end -- every module below
was written, then immediately tested against the official data, and several real
defects were found and fixed before this document was written (see "Findings").

The system is ~2,500 lines of Python across 15 modules, has 111 passing tests, and
processes the complete official 45-event pack deterministically with no
scenario-specific branching. It deliberately does not use an LLM, a database, or
any distributed infrastructure -- see "Deliberately Unchosen Approaches."

## Baseline

There was no pre-existing implementation to baseline against (this is a
from-scratch build, confirmed by an exhaustive filesystem search before starting).
The "baseline" here is therefore the state at first successful run of each
component:

- First offline replay run (before the fixes below): 45/45 events processed,
  no crashes, but with three confirmed defects already visible in the raw output
  (see Findings #1-#3).
- Final state, after fixes: 111/111 tests passing, 45/45 events replayed
  deterministically.

## Findings

For each finding: severity, where it was, what was wrong, why it mattered, and the
evidence that confirmed it.

### 1. Missing item-variant and size checks (High -- correctness)
**Location:** `policy_compiler.py`, `facts.py`, `rules.py` (as first written).
**Problem:** The first working version of the compiler only extracted a broad item
*category* ("sporting_goods") from "Replace my worn road-running shoes in size
43," with no way to check the specific size or distinguish "road-running shoes"
from "trail-running shoes" or a "cycling helmet" sold by the same specialist
retailer.
**Why it matters:** SCEN0002's own control question is literally "Can the solution
tell a valid payment that matches the request from one that quietly does not?" --
this is not a peripheral case, it is the scenario's entire point.
**Evidence:** Running the offline replay showed `AU0013` (wrong size, 42 vs. the
requested 43), `AU0017` (trail-running shoes substituted for road-running), and
`AU0020` (a cycling helmet from the same retailer) all incorrectly approved.
**Fix:** Added `item.size` (extracted from `item_details` via a whitelist regex,
same pattern as the existing return-window extraction) and `item.name_contains`
(a generic hyphenated-modifier extraction -- "road-running", "27-inch" -- matched
against the catalogue-sourced `item_name`, not merchant free text). Both are
generic phrase patterns, not scenario-specific rules.
**Regression tests:** `tests/test_rules_engine.py::test_item_name_contains_case_insensitive`,
`::test_item_size_unknown_when_not_stated`, `tests/test_policy_compiler.py::test_paraphrased_size_and_variant`.

### 2. Lexicon substring false-positive (Medium -- correctness)
**Location:** `policy_compiler.py`, `_RETAILER_TYPE_LEXICON` matching.
**Problem:** The retailer-type lexicon matched with plain substring `in` checks.
The word "grocer" is a substring of "groceries," so any instruction mentioning
"groceries" (e.g. SCEN0001's "Order our household groceries...") silently added a
`merchant.category` rule the customer never asked for.
**Why it matters:** It happened not to change any decision in this specific data
pack (every merchant used in SCEN0001 is already a groceries merchant), but it is
a real defect: a customer-facing rule was fabricated from a word the customer used
in a completely different sense, and would misfire on different data.
**Evidence:** `[rule.as_dict() for rule in mandate.hard_rules]` printed for
SCEN0001 showed an unrequested `merchant.category in ["groceries"]` rule before
the fix.
**Fix:** Changed to word-boundary regex matching (`\bgrocer\b`), which correctly
does not match inside "groceries."
**Regression test:** `tests/test_policy_compiler.py::test_paraphrased_retailer_type_does_not_false_positive_on_substring`.

### 3. Route-ordering bug in the demo API (Medium -- would have broken the demo)
**Location:** `api.py`.
**Problem:** The `StaticFiles` mount serving the UI at `/` was originally placed
*before* the `/api/...` route decorators executed at import time. Since Starlette
matches routes in registration order and a `Mount("/")` matches every path prefix,
this would have silently intercepted every `/api/...` request and returned 404
from the static file handler instead of reaching any API endpoint.
**Why it matters:** This is exactly the kind of bug that only shows up when
running the actual app, not when reading the code in isolation -- caught by
following this project's own standing instruction to start the dev server and
exercise the feature in a browser before calling UI work done.
**Evidence:** Confirmed by moving the mount, re-running, and diffing behavior; a
regression test (`tests/test_api.py`, all of which hit `/api/...` routes) would
have failed immediately had the bug been reintroduced.
**Fix:** Moved the `app.mount("/", StaticFiles(...))` call to the end of the file,
after every `@app.get`/`@app.post` route is registered, with a comment explaining why order matters here.

### 4. Ternary-operator precedence bug (Medium -- would have dropped a customer message)
**Location:** `live_worker.py`, `LiveWorker.resolve`.
**Problem:** `customer_message or "confirmed" if decision == "allow" else "declined"`
parses as `(customer_message or "confirmed") if decision == "allow" else "declined"`
-- so a caller-supplied `customer_message` was silently discarded whenever the
human's decision was "decline," always replaced by the hardcoded default string.
**Why it matters:** A real customer's stated reason for declining a purchase would
never have reached the audit trail or the hosted API.
**Fix:** Replaced with an explicit `if customer_message is None: ... ` assignment.
**Regression test:** `tests/test_live_worker.py::test_step_up_is_not_auto_resolved_and_resolve_uses_the_separate_endpoint`
asserts the exact `customer_message` passed through to `client.resolve`.

### 5. Retailer-type false positive on familiarity phrases (Low -- compiler noise)
**Location:** `policy_compiler.py`, the "unrecognized retailer type" open-question
logic.
**Problem:** The generic `_RETAILER_TYPE_RE` pattern (`from a ___`) also matches
phrases like "from a seller I have bought from before," which is a *familiarity*
requirement, not a retailer-*category* requirement, and would have produced a
spurious open-question telling the customer their instruction named an
unrecognized retailer type ("seller i have bought from before").
**Fix:** Added an explicit exclusion for captured phrases containing a first-person
reference ("I", "I've", "I have"), which are familiarity phrasing, not category
names.
**Regression test:** `tests/test_policy_compiler.py::test_unrecognized_retailer_type_is_flagged_not_guessed`
(which also exercises the genuine "cheesemonger" case this logic exists for).

No further correctness defects were found in the money-handling, mandate-lifecycle,
payment-boundary, or Viseca-mapping code during construction or the adversarial
pass below -- these areas are covered by focused tests from the start (see "Tests").

## Changes Made

Every file in `src/wallet_control/` and `ui/index.html` was written for this
challenge; there is no "before" state to diff against for a from-scratch build.
The table above (Findings) lists every defect found and fixed *during* that
construction, which is the equivalent record for a from-scratch project.

## Deliberately Unchosen Approaches

Per the challenge's own engineering-discipline guidance, the following were
considered and explicitly not built:

- **An LLM in the decision path.** Considered for interpreting more open-ended
  customer instructions than the current lexicon covers. Not used, because the
  brief explicitly asks for predictable behavior if a model is unavailable, and
  because the decision path has hard latency requirements (an 8-second default
  deadline). See ARCHITECTURE.md, "Where an LLM would fit."
- **A database / Redis / message queue for `RunState`.** The event-day operating
  model is one team, one worker, one run at a time. `RunState` is one in-process
  object per run. Documented as an explicit, revisitable choice in ARCHITECTURE.md,
  not an oversight.
- **A machine-learning risk model for session integrity / fraud signals.** Built
  as a small, explicit, auditable heuristic (`state.RunState.session_signals`)
  instead -- three named signals (device change, velocity, unfamiliar-merchant
  correlation), each traceable in the evidence trail, rather than an opaque score.
- **A generalized rule-interpreter/expression-language for `hard_rules`.** The
  field vocabulary (`rules.py`) is a fixed, small set of named fields, each with
  its own explicit evaluator function. A generic expression evaluator was
  considered and rejected as unnecessary complexity for nine field types.
- **Splitting `decision_engine.py`/`rules.py` into more files.** Both are under
  200 lines and each has one clear responsibility; splitting further would add
  navigation overhead without improving clarity.

## Security Review

See [SECURITY.md](SECURITY.md) for the full write-up. Summary of what was
actively tested by attacking the system's own implementation:

- Prompt injection via `item_details`, using both the real injected strings found
  in the official data pack and additional custom/obfuscated strings -- defended
  architecturally (item_details is read through exactly two whitelist regexes,
  never compiled into a rule).
- Merchant lookalike/typosquatting (the real `PixelHarbor`/`PixelHarbour` pair in
  the data) -- defended by matching on `merchant_id`, never `merchant_name`.
- Duplicate/replay: both repeated delivery of the same `authorization_id`
  (idempotency) and a different ID describing a similar purchase (evidence, not
  auto-block) are tested, including the real `AU0035`/`AU0036` and `AU0037`/`AU0042`
  pairs from the data.
- Payment-boundary attacks: charging a decline, charging a pending step_up,
  over-amount charges, double-charging one authorization, and charge_id replay --
  all refused by `payment.MockPSP`.
- Mandate mutation: PATCH cannot remove/replace a rule, cannot loosen
  `uncertainty_policy`, and a human's step_up resolution cannot alter the
  standing mandate.
- Currency manipulation: comparisons are always in converted CHF (`Decimal`,
  fixed synthetic rates), never face value.

## Authorization Boundary

```
agent proposal -> wallet control (deterministic rules on trustworthy facts)
  -> ALLOW/REVIEW/BLOCK (authorization advice, mapped to approve/decline/step_up)
    -> REVIEW: human intervention, scoped to exactly this authorization
      -> payment execution (MockPSP; independently re-checks decision==allow,
         amount <= approved, not already charged)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full diagram and code-level detail.

## Viseca Integration

See [VISECA_INTEGRATION.md](VISECA_INTEGRATION.md) for the complete breakdown.
Short version: `mandate.py`, `viseca_client.py`, `viseca_mapping.py`, and the event
schema handling in `offline_replay.py`/`facts.py` implement the official contract
as documented in technical_details.md. `intervention.py`,
`order.duplicate_suspected`, the `merchant.familiar`/`item.category`/etc. field
vocabulary, `payment.py`, and `api.py`/`ui/index.html` are local extensions, never
sent to or assumed to be understood by the hosted API.

## Test Results

```
111 passed in 0.8s
```

Coverage by concern: mandate lifecycle & tighten-only PATCH (25 tests, mostly
parametrized transition/validation cases), policy compiler including
paraphrased/generic instructions (13), rules engine (11), decision engine
priority logic & idempotency (8), prompt injection using real injected data-pack
strings (4), duplicate/retry (4), payment boundary (6), human resolution scoping
(5), offline replay & no-hardcoding (8), Viseca mapping (4), event-schema
validation against the official JSON Schema (6), live worker against a fake
client (7), demo API end-to-end (5), money/FX exactness (5).

## 45-Event Replay

```
events processed: 45
allow:  19
review:  2
block:  24
```

Per-scenario breakdown and the full reasoning behind every decision:
[OFFLINE_REPLAY.md](OFFLINE_REPLAY.md). These are this engine's own conclusions
from each scenario's `cardholder_instruction` and the supplied purchase facts --
the official pack contains no expected-decision answer key
(`data/official/metadata.json`), so these numbers are reported as this
implementation's behavior, not adjusted to match any external target.

## Remaining Known Limitations

Stated plainly, as asked:

- **The policy compiler is a fixed lexicon, not a general NLU system.** It handles
  the phrasing patterns exercised by the five official instructions and a range of
  paraphrases (tested in `test_policy_compiler.py`), but an instruction using
  vocabulary well outside its lexicon (an item category or retailer type it has
  never seen) correctly surfaces as an `open_question` rather than silently
  guessing -- but it does not learn or infer new categories. A model could extend
  this at mandate-compile time, behind the same human-confirmation step, without
  touching the decision path.
- **Session-integrity is a small, hand-designed heuristic, not a trained risk
  model.** It is deliberately explainable (three named signals) rather than
  maximally sensitive; a production system would likely want to validate it
  against much more historical data than 4,701 synthetic rows.
- **Revocation's effect on a purchase already queued in a running scenario is
  unspecified by the official contract itself**, and this implementation does not
  invent behavior to fill that gap -- `api.py`'s revoke endpoint revokes the *live*
  mandate (blocking any *new* run) without retroactively touching an in-progress
  run's already-taken decisions, which is the most literal reading of "an existing
  run keeps its original snapshot."
- **The live worker has not been run against the real hosted API** (no event-day
  key was available while building this); it is tested against a fake client that
  implements the same interface, covering 204 handling, idempotent retries,
  step_up/resolve separation, and fail-closed behavior on poll/submit errors -- but
  real network conditions (timeouts mid-request, TLS issues, actual response
  shapes for `/v1/bootstrap` and `GET /v1/scenario-runs/{run_id}`, which
  technical_details.md describes only loosely) have not been exercised.
- **`RunState` and `LiveWorker` are single-process, in-memory state**, matching
  the documented event-day operating model of one team/one worker/one run at a
  time (see ARCHITECTURE.md, "State and concurrency"). This would need to move
  behind real persistence for any multi-run or multi-team deployment.
- **No load/latency testing was performed** against the 8-second default decision
  deadline; the decision path itself is pure Python with no network or model call,
  so it should comfortably clear that budget, but this was not measured under
  realistic concurrent load.

## Senior-Jury Readiness

Things a reviewer should be able to verify quickly, and where:

- **Where is money authority created?** Only in `mandate.Mandate`, only from a
  confirmed customer instruction. `git grep -n "HardRule(" src/wallet_control` --
  every call site is in `policy_compiler.py`, `decision_engine.py` (one synthetic,
  always-visible `order.duplicate_suspected` rule), or a test.
- **Can the agent create authority?** No -- `policy_compiler.compile_instruction`
  is never called from `decision_engine.py`/`facts.py` (verified by source
  inspection in `test_decision_engine_never_compiles_a_policy_from_event_data`).
- **Does `approve` mean payment?** No -- see `payment.py` and
  `test_payment_boundary.py`; `ALLOW`/`approve` is a decision, `MockPSP.charge` is
  a separate, independently-gated call.
- **What happens on a duplicate request?** See `state.py` module docstring and
  `test_duplicate_and_retry.py` -- two distinct, separately-tested mechanisms.
- **Can a human approval change the standing policy?** No --
  `test_resolving_a_step_up_does_not_touch_the_mandate`.
- **What happens if the hosted API fails, or returns 204?** See
  `live_worker.py` and `test_live_worker.py` -- never becomes an approval; 204 is
  not "done."
- **Is anything scenario-ID-hard-coded?** No --
  `test_engine_does_not_branch_on_scenario_id_or_authorization_id` checks this
  structurally, not just by inspection.
- **Can the architecture be understood in five minutes?** `ARCHITECTURE.md`'s
  diagram plus this document's "Authorization Boundary" section are the two
  intended starting points.

# Architecture

## The authorization boundary

```
CUSTOMER
  |  instruction (natural language)
  v
policy_compiler.compile_instruction()      -- deterministic, no LLM
  |  hard_rules + uncertainty_policy + guidance + open_questions
  v
mandate.Mandate  (draft -> confirm -> [tighten|revoke])   <-- the ONLY source of authority
  |  .snapshot() taken once, at run start
  v
SHOPPING AGENT proposes a purchase  --------->  authorization.request event
  |                                                  |
  |                                                  v
  |                                   facts.build_purchase_facts()
  |                                   (trustworthy fields only; item_details
  |                                    read through 2 whitelist patterns)
  |                                                  |
  |                                                  v
  |                                   rules.evaluate_rule() x N   -> pass/fail/unknown
  |                                                  |
  |                                                  v
  |                                   decision_engine._decide()
  |                                     any fail?    -> BLOCK
  |                                     any unknown? -> mandate.uncertainty_policy
  |                                     all pass?    -> ALLOW
  |                                                  |
  v                                                  v
 (agent has no say from here on)          viseca_mapping: ALLOW/REVIEW/BLOCK
                                                      |            -> approve/decline/step_up
                                                      v
                                        REVIEW -> customer sees it -> resolve_authorization()
                                                      |
                                                      v
                                        payment.MockPSP.charge()   <-- the ONLY thing that
                                          requires decision == "allow"    can execute money,
                                          amount <= approved amount        and only once
                                          not already charged
                                                      |
                                                      v
                                                   AUDIT (evidence, reason_codes, evidence log)
```

The load-bearing sentence: **the agent proposes a transaction; it never receives,
derives, or can widen spending authority.** Every arrow after "SHOPPING AGENT
proposes" is code the agent does not control -- it does not call
`policy_compiler`, does not construct a `HardRule`, does not touch `RunState`, and
`item_details` (the only text it can put in front of the engine) is read through
exactly two narrow regexes (`facts.extract_return_window_days`,
`facts.extract_stated_size`) that can produce a fact, never a rule. See
[SECURITY.md](archive/SECURITY.md) for why that specific separation is the actual
prompt-injection defense.

## `approve` is not payment

This is enforced as code, not policy: `decision_engine.evaluate_authorization`
never touches `payment.py`, and `payment.MockPSP.charge` independently re-checks
that the authorization's recorded decision is `"allow"` (not `"review"`, which
covers a *pending* step_up), that it has not already been charged, that the
requested amount does not exceed what was actually approved, and that the
merchant being charged matches the merchant that authorization was actually
approved for. A `charge_id` is a one-time idempotency key for one specific
request, not a free-standing token -- reusing it for a *different*
authorization_id or amount is refused as a conflict rather than silently treated
as "already done" (`docs/archive/SECOND_ADVERSARIAL_AUDIT.md`, Finding 7). See
`tests/test_payment_boundary.py` for the exhaustive list of ways this is tested to
refuse.

## Mandate lifecycle and the tighten-only guarantee

`mandate.Mandate` is the only place a `HardRule` list can change, and it exposes
exactly two mutators after confirmation:

- `tighten_hard_rules(new_rules)` -- **appends only**. Existing rules are never
  removed or edited (`HardRule` is a frozen dataclass). Re-submitting an existing
  rule is a no-op, not a duplicate.
- `set_uncertainty_policy(new_policy)` -- only allows the transitions the official
  API documents (`approve`/`ask` -> `decline`; nothing widens back).

`revoke()` is terminal and idempotent. There is no third mutator, and
`hard_rules` is exposed only as a `tuple` copy, so no caller holding a reference to
it can mutate the mandate's internal list.

A run's `MandateSnapshot` (`Mandate.snapshot()`) is an immutable dataclass taken
once, at run start, matching the documented behaviour that a run keeps its
original snapshot even if the live mandate is later patched or revoked
(technical_details.md, step 6).

## Human resolution: "a yes is this authorization, not a new wallet"

`decision_engine.resolve_authorization` takes an `authorization_id` and a human
decision (never an amount -- see below), and calls `RunState.record_resolution`,
which:

- only accepts a first resolution for an authorization currently `"review"`;
  accepts an identical *repeated* resolution idempotently (a retried click or API
  call); and raises `ResolutionError` both for an authorization that was never put
  to review at all and for a second resolution with a *different* answer than the
  one already recorded -- a real, conflicting second answer is surfaced, never
  silently discarded (`docs/archive/SECOND_ADVERSARIAL_AUDIT.md`, Finding 8);
- never touches `Mandate` -- there is no code path from a resolution back into
  `tighten_hard_rules` or `set_uncertainty_policy`;
- uses the amount and the *simulated purchase timestamp* from the original review
  record, never a value the caller supplies and never the real-clock time the
  human happened to answer at (Findings 2 and 3 -- a step_up answered an hour late
  must not be attributed to the wrong rolling-spend window, and must not be
  resolved against a different amount than what was actually shown).

## State and concurrency

`RunState` (`state.py`) holds everything that must be remembered across a
sequence of decisions for one run: which `authorization_id`s have a final
decision (idempotency, keyed on a fingerprint of merchant/basket/amount so a
same-ID delivery with *different* facts is detected as a conflict rather than
blindly trusted either way -- Finding 4), a rolling list of approved-spend
timestamps+amounts (for `scope="period"` rules), and a short list of recent
attempts (for duplicate detection and the session-integrity heuristic, looked up
live against the current decision rather than a frozen snapshot -- Finding 9).

This is deliberately **one `RunState` per run, held in one process's memory**, not
a database and not a distributed store. That is a documented choice, not an
oversight: the event-day operating model is one team running one worker against
one hosted run at a time (`live_worker.LiveWorker` is single-threaded except for
the poll loop and the separate `resolve()` call a UI/API thread can make into it,
guarded by `self._lock` on run registration). If this were productionized for
concurrent multi-run traffic, `RunState` would move behind a real datastore with
per-authorization row locking -- but adding that now, for a synthetic single-run
hackathon demo, would be exactly the kind of speculative infrastructure the
challenge explicitly does not reward.

In-memory-only state does have one genuine, previously-undocumented cost: a
process crash mid-run forgets prior approved spend, which could let a rolling
window be wrongly bypassed on restart. `LiveWorker` now optionally persists
`RunState` to a single small JSON checkpoint file per run (not a database) and
reloads it on restart, plus a best-effort reconciliation against the platform's
own `GET /v1/authorizations` -- see `docs/archive/SECOND_ADVERSARIAL_AUDIT.md`, Finding 12,
including what this does and does not actually guarantee.

## Money handling

All monetary comparisons use `decimal.Decimal`, constructed from `str(value)`
(never `Decimal(float)` directly) to avoid binary-float precision error at a limit
boundary. CHF conversion uses the four fixed synthetic rates from
`data/official/fx_rates.csv`, rounded half-even to two decimals, matching
data_dictionary.md exactly (`money.py`, verified against three real CSV
examples in `tests/test_money.py`).

## Where an LLM would fit (and why none is in the decision path)

Nothing in the ALLOW/REVIEW/BLOCK path calls a language model. `policy_compiler.py`
is a small, deterministic regex/lexicon compiler run once at mandate-creation
time, off the latency-critical path. This is a direct response to two explicit
constraints in the brief: "your app must still give a predictable response when
the model or another external service is unavailable" and "smaller, lower-latency
models are preferred" if a model is used at all in the decision path
(challenge.md, "Technical Preferences"). A model could reasonably be added later
for *interpreting more open-ended customer instructions* than the current
lexicon covers -- see docs/archive/FINAL_SENIOR_ENGINEERING_REVIEW.md, "Remaining Known
Limitations" -- but it would sit at mandate-compile time, behind the same
human-confirmation step that already exists, never inside `evaluate_authorization`.

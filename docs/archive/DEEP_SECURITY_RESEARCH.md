# Deep Security Research — findings, exploits, fixes

Fifth pass. The brief was: *"What can a malicious agent still make this wallet pay
for?"* — answered with working exploits rather than argument, on the explicit
instruction not to stop when the suite is green.

**It was not green in the way it looked.** 248 tests passed at the start of this
pass while a revoked authority, an expired authority and a blocked card all
returned ALLOW and charged. Eight vulnerabilities were found, all reachable,
three of them in code the two previous passes had declared hardened. All eight
are fixed, each with a regression test verified to fail before its fix and a
mutation test verified to catch its removal.

---

## 1. The headline

The claim under test was:

> *"An approval is not a transferable capability. It is bound to the facts that
> were actually authorized, and the payment boundary independently verifies those
> facts before money moves."*

**Before this pass that statement was false in four separate ways**, and each
failure moved real money in reproduction:

| # | The wallet paid for… | Root cause |
| --- | --- | --- |
| V1 | a purchase on a **revoked authority**, an **expired authority**, and a **blocked card** | the platform's own status fields were never read |
| V2 | a purchase the customer **approved and then revoked** | human-approved step-ups minted no authority at all |
| V3 | a purchase revoked **before a crash**, charged after restart | authorities were not checkpointed |
| V8 | the **same authorization twice**, across a restart | "single use" lived in memory, not in state |

It is now true, with the limits named in §7 — and the limits are part of the
claim, not a footnote to it.

---

## 2. The strongest attack found

**A purchase the platform has explicitly de-authorized.** No tampering, no race,
no malformed input — just a well-formed event carrying the truth:

```
authorization_status = "revoked"      ->  ALLOW, authority minted, CHF 400 CHARGED
authorization_status = "expired"      ->  ALLOW, authority minted, CHF 400 CHARGED
card_status_at_attempt = "blocked"    ->  ALLOW, authority minted, CHF 400 CHARGED
```

`authority_status` (`active|revoked|expired`) and `card_status_at_attempt`
(`active|blocked`) are **required** fields of
`data/official/schemas/authorization_event.schema.json`. They are the platform
stating, authoritatively, that the authority behind this purchase is gone or the
card may not be used. The engine read neither.

**Why no test caught it, and why that matters more than the bug.** All 45 official
rows carry `active`/`active`:

```
$ awk -F, 'NR>1{print $15, $16}' data/official/purchase_attempts.csv | sort | uniq -c
  45 active active
```

The fixture only ever exercises the happy value, so 100% of the benchmark passed
while the field was dead code. A conventional suite — even an extensive one —
cannot find this, because there is nothing in the data to make it look at. It was
found by enumerating every field the schema declares and grepping for which ones
the decision path actually reads:

```
UNREAD BY THE DECISION PATH: ['authority_status', 'card_status_at_attempt',
  'delivery_by', 'fulfillment_method', 'initiator_type', 'profile_id',
  'replay_order', 'scenario_id', 'spend_in_period_before_chf']
```

Of those, `replay_order`/`scenario_id` are unread deliberately (no hard-coding),
`spend_in_period_before_chf` is unread deliberately (documented), and the first
two were a hole.

---

## 3. All vulnerabilities

Each was reproduced, fixed minimally, and pinned by a mutation test. "Official
impact" is whether the fix could move the 45-event replay.

### V1 — Platform revocation signals ignored · CRITICAL · reachable
The above. Recognised negatives (`revoked`, `expired`, `blocked`) are now **hard
failures**, not uncertainty: a customer revoking their authority is not a question
to put back to the customer, and an `approve`-on-uncertainty policy must not be
able to soften it. Unrecognised values (a future enum, an empty string, a case
variant, a missing field) are genuinely missing information and route through
`uncertainty_policy`.
*Official impact: none — 45/45 rows are `active`/`active`.*
*Tests: `tests/security/test_platform_status.py` (14).*

### V2 — Human-approved step-ups escaped revocation entirely · HIGH · reachable
Neither production resolve path passed `mandate=` to `resolve_authorization`, so a
human-approved step-up minted **no** `PaymentAuthority`. Nothing could revoke it,
and `charge()` treated "no authority" as "no constraint". Reproduced end to end
through the demo API:

```
reviews in run: ['AU0016']
customer approves AU0016 -> allow | payment_authority: None
customer then REVOKES mandate -> revoked authorities: ['AU0012','AU0019','AU0023']
>>> CHARGED CHF 175.0 AFTER REVOCATION   *** I29 VIOLATED ***
```

The purchase the customer was explicitly asked about was the one that escaped
their revocation. **This falsifies invariant I29 exactly as the previous pass
claimed it.**
*Official impact: none (resolution is not on the replay path).*
*Tests: `tests/security/test_revocation_end_to_end.py` (4), `test_authority_lifecycle.py`.*

### V3 — Revocation did not survive a restart · HIGH · reachable
`RunState.to_snapshot()` omitted `_authorities`. After a crash the restored run
had none, so a revoked authority came back as an unconstrained one and charged.
*Official impact: none.* *Tests: `test_authority_lifecycle.py`.*

### V4 — Expiry judged by a caller-supplied clock · MEDIUM
`charge(now=...)` let whoever asked for a charge also say what time it was:
charging ten years past expiry by claiming it was still issue time. The demo path
was already passing a *simulated purchase time*, which made expiry vacuous there —
a live divergence between the documented design ("real-clock based") and the code.
The payment boundary now owns its clock; `now=` only timestamps the record.
*Tests: `test_authority_lifecycle.py`.*

### V5 — Events were not bound to their run · MEDIUM
`authorization.card_id` keys the merchant-familiarity lookup and was never compared
to the run's card, so an event carrying another card's identity **borrowed that
card's purchase history** to make an unfamiliar merchant look familiar.
`mandate_id` was likewise unchecked. Both are now compared exactly — a case
variant, a padded value or one carrying a zero-width character is a different
identity, not a near-enough one.

The check runs **before** the repeat-delivery branch. That ordering is the fix, not
a detail: the fingerprint covers merchant/basket/amount but not identity, so a
re-delivery with a swapped `card_id` would otherwise match and be answered with the
stored decision — a real answer to an event that was never ours to answer.
*Official impact: none — 0 card mismatches across all 45 events.*
*Tests: `tests/security/test_run_binding.py` (9).*

### V6 — Duplicate detection evaded by one centime · LOW-MED
Near-duplicate matching required the amount to be identical, so CHF 100.01 instead
of CHF 100.00 produced no duplicate signal at all. The attacker's gain is avoiding
the human prompt, not exceeding a limit — every hard rule still applies — so this
is a detection weakness, not an authority bypass. Fixed because the evasion was
trivial and the fix is cheap; the reviewer is now shown the price difference.
*Official impact: none — verified against the data that ignoring the amount creates
no new collisions in any scenario.*
*Tests: `tests/security/test_duplicate_evasion.py` (6).*

### V7 — Revocation arriving on a re-delivery was ignored · HIGH · found by the fuzzer
The status check ran *after* the repeat-delivery branch, so
`authority_status=revoked` on a re-delivery of an approved id returned the stored
ALLOW and left the authority spendable.

The fix is deliberately **asymmetric**, because the correct answers differ. The
DECISION stays the stored one — the platform already has our answer for that id and
the official contract does not permit sending another. The AUTHORITY is revoked —
money that has not moved yet is ours to stop, and a platform saying the authority
is gone is the most authoritative reason there is to stop it.
*Found by `test_authority_mutation_fuzzer.py`, which crosses each mutation with the
context it lands in. No per-field test reaches it.*

### V8 — Same authorization executed twice across a restart · HIGH · found by the corpus
"Single use" lived in a `set` inside `MockPSP`, which is in-memory and never
checkpointed, so a fresh executor after a crash had no record of prior charges.
Single-use is now a property of the **persisted** authority (`consumed_at`), which
also deletes the duplicate ledger — one source of truth, checkpointed with
everything else.
*Found by corpus case N03.*

---

## 4. Reachability discipline — what was NOT fixed, and why

Two attacks reproduce in a probe but are **not reachable** in the deployed
architecture. Both are recorded as trust dependencies rather than patched, because
patching an unreachable path adds a branch that can never be exercised.

**Rolling-window limits fall to timestamp manipulation.** Claiming each purchase is
eight days after the last defeats any `period` cap:

```
cap CHF 300 / 7 days;  six purchases claimed 8 days apart  ->  CHF 1800 approved
```

Walking *backwards* in time works equally well. But `authorization.timestamp`
arrives inside `envelope["data"]` from `/v1/decision-requests/next` — the agent has
no channel to author it, and `live_worker.py` imports no CSV loader that could
substitute one. **Every rolling-window guarantee rests on the platform's timestamp
being truthful. We do not and cannot verify it**, and the official contract
mandates using simulated purchase time for windows, so anchoring to the real clock
would violate the contract and break the offline replay.

**Policy tightening versus an outstanding authority.** Unreachable by construction:
a run is bound to one mandate snapshot taken at run start (both `api.py` and
`live_worker.py` build it once per `run_id`), and authorities live inside one
`RunState`, so a policy version cannot change beneath an outstanding authority. The
`policy_version` field on the authority is therefore **provenance, not an enforced
binding** — an enforcement branch would be dead code.

---

## 5. Where the boundary actually is

There is exactly one place money moves: `ChargeRecord` is constructed at
`payment.py:134`, and nowhere else in the repository. `_charges` is written on the
next line and nowhere else.

A structural note that belongs in any honest description of this system: **neither
`api.py` nor `live_worker.py` ever calls `charge()`.** The official challenge has
no payment-execution endpoint, so `MockPSP` guards a simulated execution that the
hosted integration never triggers. "No unauthorized EXECUTED" is a true statement
about our mock, not about the hosted challenge. What the hosted path actually
produces is a decision (`approve`/`decline`/`step_up`), and the security of *that*
is the decision engine's, not the payment boundary's.

Checks applied at that one point, all re-read from live run state rather than
trusted from arguments:

| Check | Fails when |
| --- | --- |
| decided | no stored decision for this authorization |
| approved | stored decision is not `allow` |
| merchant bound | charge merchant ≠ approved merchant |
| amount bound | charge amount > approved amount |
| authority exists | no authority on record (fail-**closed** since this pass) |
| not consumed | `consumed_at` is set — persisted, so it survives a restart |
| not revoked | authority revoked |
| not expired | boundary's own clock is past `expires_at` |
| idempotency key sane | `charge_id` reused for a different authorization or amount |

`charge_via_authority()` is an ergonomic wrapper, not a second layer. Its only
unique check is the ceiling of the *passed* authority object, which may be narrower
than the approved amount. Everything else is `charge()`'s, deliberately, so
reaching for the plain door bypasses nothing.

---

## 6. "Unknown becomes allow" audit (mission §21)

| Source of unknown | Behaviour | Consequence | Verdict |
| --- | --- | --- | --- |
| No purchase history for the card | `is_familiar` → `None` → `unknown` | routed through `uncertainty_policy` | correct (three-valued) |
| Card known, merchant not | `False` → `fail` | block | correct |
| Rolling-period spend not computable | `.get()` → `None` → `unknown` | uncertainty | correct |
| Return window not stated | `None` → `unknown` | uncertainty | correct |
| Mandate with zero rules | `unknown` on `mandate.has_no_rules` | uncertainty, never a blank cheque | correct |
| Unrecognised `authority_status` | `unknown` | uncertainty | correct (since V1) |
| Recognised dead status | `fail` | block, uncompromisable | correct (since V1) |
| Unknown rule field | `unknown` | uncertainty | correct (fails closed on engine/compiler mismatch) |
| Unknown currency | raises `ValueError` | no decision submitted | correct |
| NaN / ±Infinity amounts | raise `InvalidOperation`, caught by the worker | logged, no decision submitted | fail-closed but ungraceful |
| **No authority at the payment boundary** | **was: charge anyway** | **was: V2 and V3 moved money** | **fixed — now fail-closed** |
| `uncertainty_policy = approve` | unknown → allow | the customer's explicit choice | policy, not a defect — and the compiler never emits it from natural language (verified: "never ask me" still compiles to `ask` with 3 open questions) |

No permissive default remains on the decision path. There are no bare `except`
clauses there; `money.py`'s single `except` re-raises unknown currencies as an
error.

---

## 7. What we still cannot do

Ranked by category, not by comfort.

**Architectural — cannot be fixed in this layer:**
1. **A lying merchant can satisfy two customer rules.** `order.return_window_days`
   and `item.size` are extracted from merchant text; a merchant who writes "size 43;
   returns accepted within 30 days" satisfies both, and there is no independent
   source to check against. So the honest statement is *not* "merchant text can
   never make a decision more permissive" — it is: **merchant text can satisfy
   exactly two enumerated factual predicates and can do nothing else.**
2. **Timestamp truthfulness** (§4) — every window guarantee rests on it.
3. **Unbindable referential anchors** — "the one I chose" cannot be verified.
4. **Product identity beyond name matching** — no SKU/generation/colour/width
   ontology, and a heuristic one pretending to be ground truth would be worse.
5. **A hostile platform** is out of scope by construction: every fact originates
   from its event stream.

**Deliberately scoped out:**
6. `order_returnable` (platform-supplied) also feeds the effective return window
   and is not fingerprinted. An adversary able to flip it can already rewrite
   `item_details`, so it closes no new capability; folding it in means a
   `StoredDecision` schema change and a checkpoint break.
7. Per-line `unit_price` is not fingerprinted — no rule reads it, and
   `billing_amount_chf` is compared separately.

**Structural:**
8. **Concurrency safety is incidental, not designed.** 24 threads racing the same
   charge produced exactly one execution, but `charge()` is a check-then-act
   sequence with no lock; it holds because of the GIL and the small window, not
   because it is synchronised. Single-process is an assumption, and this is where
   it lives.
9. **The PSP's `charge_id` ledger is still in-memory.** Consumption is persisted,
   so a post-restart retry of a completed charge now *fails closed* rather than
   returning the original record — safe, but not idempotent across a restart.
10. `MockPSP` is a mock. Auth-versus-capture, partial capture and reversal do not
    exist here and must not be implied.

---

## 8. Tooling built (and why it earned its place)

**`tests/security/test_authority_mutation_fuzzer.py`** — 24 mutations, each
declared `SECURITY_RELEVANT` or `EQUIVALENT`, plus two Hypothesis properties over
generated amounts and generated text noise. Both directions are asserted, because
a wallet that invalidates on every cosmetic edit is as broken as one that
invalidates on nothing: the first fails closed on every legitimate retry and trains
its operators to ignore it. The classification table *is* the specification of the
repeat-delivery path. It found V7 on first run.

**`src/wallet_control/red_team_corpus.py`** (+ `scripts/run_red_team_corpus.py`) —
133 cases over 10 categories, generated by crossing attack primitives with the
contexts they land in: first delivery, re-delivery, post-revocation, post-restart.
This shape was chosen deliberately: **every vulnerability in this pass survived
per-field testing and died only under a crossing.** It found V8.

One corpus case initially failed because of a bug in the *harness* (`card_id or
CARD` silently substituted the real card for `None`), briefly looking like a ninth
vulnerability. Recorded because a security harness that lies in the safe direction
is its own hazard.

---

## 9. Results

| | Before | After |
| --- | --- | --- |
| Tests | 248 | **463** |
| Adversarial corpus | 17 | **133/133** over 10 categories |
| Legacy red-team matrix | 17/17 | 17/17 |
| Official replay | 19 / 2 / 24 | **19 / 2 / 24 — unchanged** |
| Vulnerabilities moving money | 4 unknown | 0 known |

The replay is unchanged after every fix, and that is checkable rather than lucky:
V1 and V5 cannot move it (45/45 rows `active`/`active`; 0 card mismatches), V6 was
verified against the data to create no new collisions, and all 45 authorization_ids
are unique so the repeat-delivery path — where most of this pass's changes live —
is never exercised by the benchmark at all.

Every fix is mutation-verified: removing the platform status check fails 13 tests,
un-persisting authorities fails 3, restoring the fail-open payment default fails 1,
returning expiry to the caller's clock fails 1, dropping `mandate=` from the API
resolve path fails 3, removing the pre-replay revocation fails 6, and reverting
single-use to an in-memory ledger fails N03.

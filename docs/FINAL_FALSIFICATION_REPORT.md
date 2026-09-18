# Final falsification report

Criteria were fixed in `FINAL_FALSIFICATION_PREREGISTRATION.md` before any prototype
of this pass. Reproduce with `python scripts/run_scope_falsification.py`.

---

## 1. Results against the pre-registered falsifiers

| # | Falsifier | Fired? | Evidence |
| --- | --- | --- | --- |
| **B1** | an official field creating a binding at a fourth scope | **no** | every candidate is context, signal, or superseded — §2 |
| **B2** | an attack not expressible at the three scopes | **no** | every attack in the battery attributes cleanly to one scope |
| **B3** | two valid authorizations jointly violating a fourth-scope constraint | **no, but** | the joint violation is at the **account** scope, which the model already names — it confirms scope 3 rather than adding a fourth |
| **B4** | a lifecycle property not safely attachable | **no** | authority lifecycle belongs to the platform; card lifecycle is carried live on the event |
| **B5** | a cross-field invariant no scope owns | **no** | `billing_amount_chf = amount × fx` is already enforced at authorization scope by `amount_integrity` |
| **C1** | a higher-scope bound safely enforced from lower-scope state | **yes — and it sharpened T1 rather than breaking it** | §4 |
| **C2** | 1:1 cardinality making the model untestable | **no** | the corpus fans out: 10 accounts carry 2 cards, and CU0001/CA0001/AC0001 carries **two authorities** (SCEN0000, SCEN0001) |

**No B-falsifier fired. T2 (exactly three scopes) stands.**

## 2. Candidate fourth scopes, and what killed each

| candidate | killed by |
| --- | --- |
| customer | `customers.csv` has no limit column — an identity without a bound |
| agent identity | the pack removes it deliberately: *"the challenge is about controlling delegated spending, not identifying a particular fictional AI provider"* |
| authority | *"it is not a participant policy"*; the platform pre-checks it, which is why `authority_status` is `active` on every row |
| card | its facts are uniform across all scenario cards and superseded by the event's live `card_status_at_attempt`; reading `cards.csv` would substitute a stale snapshot for a fresh fact |
| device | a signal feeding session integrity, not a bound |
| merchant relationship | a signal feeding `merchant.familiar`, not a bound |
| time period | not a scope — a window whose own definition is run-scoped (§4) |

## 3. Two claims of our own, falsified

**(a) "The engine never recomputes `billing_amount_chf`."** I asserted this after
grepping one file, then tested it: an always-on `amount_integrity` check recomputes
`amount × fx_rates[currency]` and blocks a CHF 9,499 purchase declared as CHF 100. The
grep was wrong; the test was right. *Assertion from absence of evidence in one file is
not evidence of absence.*

**(b) "Multi-run mandate reuse: not reachable — one mandate per run."**
(`FULFILMENT_SECURITY_AUDIT_1.md`.) That was our own demo convention, not a property
of the challenge. `PATCH /v1/mandates/{id}` is documented *"for later runs"*, and
`live_worker.register_run` accepts one mandate for two `run_id`s. §4 below.

## 4. C1 — the counterexample that sharpened the thesis

Sought: a bound at scope A enforced safely and completely from state at a lower
scope B. One was found.

The **rolling-period cap** is written by the customer in the mandate and enforced by
us from run state. The pack resolves it:

> *"The live counter the platform maintains is `context.approved_spend_in_period_chf`,
> recomputed from the decisions actually taken in the run."*

The platform **defines** the period as run-scoped, so the bound was never
mandate-scoped and our lower-scope state is the correct scope. Verified equal to that
definition on all 45 official events, including *"a stepped-up authorization is
paused, not approved, and does not enter approved spend until it is resolved"*.

> **T1 revised:** the scope of a bound is decided by where its *authoritative
> definition* places it, not by where the customer wrote it.

Had we not found this, we would have "fixed" a correct implementation.

No counterexample was found where lower-scope state safely enforces a bound whose
authoritative definition is genuinely higher-scoped. The negative case is §5.

## 5. The one real gap

| | |
| --- | --- |
| **Attack** | same mandate, two runs, the same one-shot job |
| **Expected invariant** | a one-shot job with an identifiable anchor is performed once |
| **Observed** | `first_fulfilment` in both runs; the job performed twice, unchallenged |
| **Verdict** | **the invariant does not hold at the scope we claimed it** |
| **Minimal reproduction** | `test_the_one_shot_job_does_NOT_hold_ACROSS_runs` |
| **Requires new authoritative state?** | **No — it requires re-scoping existing state.** Every `StoredDecision` already records `mandate_id`; the ledger is merely *partitioned by run*. |

Not fixed. Re-keying the authoritative ledger from run to mandate changes restart and
concurrency semantics across the whole execution path, days before a freeze, to close
a gap that the demo path does not reach. The claim is narrowed instead.

## 6. Attack battery — scope attribution

| attack | scope | result |
| --- | --- | --- |
| A same mandate, many authorizations, one run | mandate | held |
| **D same mandate, two runs** | **mandate** | **NOT CAUGHT — §5** |
| M merchant mutation under one authorization_id | authorization | held |
| N amount mutation under one authorization_id | authorization | held |
| R rolling window, inside / re-opened | run (= period) | held, correctly permissive after re-open |
| T FX misstatement | authorization | held (`amount_integrity`) |
| J step-up then revocation | authorization | held |
| K restart between authorization and execution | authorization | held |
| L concurrent execution | authorization | held (atomic compare-and-set) |
| P/Q account limit across cards / runs | account | **not enforceable — §3 of the scope model** |
| B/C/E/U/V multiple mandates, cards, merchants per account | account | same |

E1–E5 (double charge, charge after revocation, post-restart resurrection, merchant
redirection, amount inflation) were re-run and all held.

## 7. Mechanical corrections to the pre-registration

None. The criteria were applied as written. C1 fired and its interpretation — that it
sharpens rather than breaks T1 — follows the pre-registered text, which asked for a
bound *"safely and completely"* enforced from lower-scope state and got one.

## 8. Unresolved limitations

1. **Cross-run mandate reuse** — §5. Reachable via the worker path.
2. **Account-scope exposure** — real, unenforceable with the official API, not claimed.
3. **Single-use is per process** — pre-existing (V11); two workers restoring one
   checkpoint can each consume once.
4. **Cancelled first purchase** — a legitimate retry is reported as a repeat; needs
   `related_authorization_id` on `StoredDecision`; zero instances in the corpus.
5. **Merchant truth** — `item.size`, return windows and finality are the merchant's
   claims, derived from text we cannot verify.
6. **Compound instructions** — the shape classifier fails toward silence.
7. **Account window semantics** — calendar vs rolling is unstated by the pack, so even
   with data we would be guessing.

# Final architecture decision

# FINAL ARCHITECTURE CONFIRMED — with one invariant narrowed and one scope declared unenforceable

The three-scope model survives falsification. No fourth scope was found, no attack
escaped scope attribution, and the one gap discovered is a gap the model *predicts*
rather than one it fails to describe.

This is not a clean pass. Two of our own claims were falsified (§6), one invariant is
narrower than we had been stating, and one scope is real but outside what this wallet
can enforce. Those are stated here rather than softened.

---

## 1. Authoritative security objects

| object | scope | what it contains | enforcement point |
| --- | --- | --- | --- |
| **the mandate snapshot** | mandate | the customer's instruction, `hard_rules`, `status`, `card_id` | `evaluate_authorization` — tighten-only, never widened |
| **the decision ledger** (`RunState._decisions`) | authorization | per `authorization_id`: decision, CHF amount, merchant, basket fingerprint, simulated timestamp, `mandate_id`, and the execution lifecycle | `MockPSP.charge()` — one point, re-read from live state, atomic compare-and-set |

That is the whole trusted computing base. There is no third persistent object.

## 2. Derived objects

| derived | from | gates a side effect? |
| --- | --- | --- |
| `PaymentAuthority` | a projection of `StoredDecision` | no — `charge()` enforces against the ledger |
| rolling period spend | the ledger | yes, as a rule input; run-scoped **by the platform's own definition** |
| fulfilment / job capability | the ledger | no — its strongest action is to ask the customer |
| `merchant.familiar`, `session.integrity_risk`, return window, final sale | history + event text | yes, as rule inputs |
| policy verdict, security verdict, drift, disclosures | everything above | no — explanatory only |

## 3. Invariants

1. The decision ledger is write-once per `authorization_id`.
2. The execution lifecycle is monotonic: `issued → consumed | revoked`, both terminal, both persisted.
3. Execution validates against the ledger at exactly one point, under an atomic compare-and-set.
4. No derived state gates an external side effect.
5. The agent never declares fulfilment; the wallet derives it.
6. A mandate can only be tightened.
7. `billing_amount_chf` is recomputed from `amount × fx_rates[currency]`, never trusted.
8. A stepped-up authorization does not enter approved spend until resolved.
9. **Within one run**, a one-shot job with an identifiable anchor is performed once.

## 4. Competing architectures, and what killed each

| # | architecture | verdict |
| --- | --- | --- |
| **A** | **current three-scope model** | **kept** |
| B | three-scope + account rolling ledger | **rejected on evidence.** The official API exposes no account spend, no account endpoint, and `spend_in_period_before_chf` is null on every row. Window semantics (calendar vs rolling) are unstated. The version built last pass was defeated three times — CHF 8,800 drawn against a CHF 4,500 limit in two days. An unenforceable control that reports compliance is worse than none. |
| C | single global security ledger | **equivalent to A for everything we can enforce, and strictly worse operationally.** It would fix §5 by construction, but requires cross-run durable state the official API gives no way to reconcile, and it re-introduces the shared mutable record that six vulnerabilities in this project came from. Not experimentally distinguishable from A on the corpus; deleted under the "if two are equivalent, delete one" rule. |
| D | capability-centric | **already merged into A.** The falsification pass proved "job" and "capability whose unit is a performance" identical across 4,000 randomized runs. It is not an alternative; it is what invariant 9 already is. |
| E | event-sourced | **already what A is.** The ledger is an append-only per-id record and every read model (spend, fulfilment, drift) is a pure function of it. Adopting "event sourcing" as a separate architecture would rename, not change. |
| F | *derived: platform-delegated scoping* — trust the platform's declared scope for every bound and hold state only where it says | **partially adopted, and it is the sharpened T1.** Applied wholesale it fails: the pack declares no scope for the job capability, so a wallet that only mirrors platform scopes would drop invariant 9 entirely. |

## 5. Known limitations

1. **Cross-run mandate reuse breaks invariant 9.** Same mandate, two runs, same one-shot
   job, both reported `first_fulfilment`. Reachable through `live_worker`; the demo path
   avoids it only by compiling a fresh mandate per run. Needs the ledger keyed by
   mandate rather than partitioned by run — **a re-scoping of existing state, not new
   state**, since every `StoredDecision` already carries `mandate_id`. Not done: it
   changes restart and concurrency semantics across the execution path, days before a
   freeze, for a gap the demo does not reach.
2. **Account-scope exposure is unenforceable.** `monthly_limit_chf` is real, fans out
   across cards, and is classified by the pack as context. We do not implement or claim it.
3. **Single-use is per process.** Two workers restoring one checkpoint can each consume once.
4. **A cancelled first purchase** makes a legitimate retry look like a repeat. Zero corpus instances.
5. **Merchant claims are unverifiable** — size, return window, finality are text.
6. **Compound instructions** fail toward silence in the shape classifier.

## WHAT WE REFUSE TO CLAIM

Every property we cannot prove, stated plainly.

- **We do not claim exactly-once payment.** At-most-once, per process. Two processes
  restoring one checkpoint can each consume the same authority once.
- **We do not claim to bound total spending.** No mandate expressible in the official
  rule format can — `scope` is `purchase` or `period`, and *"No extra rule fields are
  allowed."*
- **We do not claim to enforce the account's monthly limit.** It exists; the API gives
  us no way to enforce it; we read it nowhere.
- **We do not claim the one-shot job invariant across runs.** It holds within a run.
- **We do not claim cryptographic authority, tamper-proof payment, or production
  payment security.** The payment boundary is a simulation; no production path calls
  `charge()`.
- **We do not claim to secure an official payment system.** The Viseca API has no
  payment step; the payment layer is ours and is clearly labelled as such.
- **We do not claim to understand customer intent.** We classify instruction *shape*
  with a small set of phrase patterns and fail toward silence.
- **We do not claim to detect merchant lies.** `item.size`, return windows and finality
  are the merchant's claims.
- **We do not claim standards compliance.** No SEPA, AP2, ACP or scheme certification.
- **We do not claim novelty for one-shot mandates.** SEPA one-off mandates, card-on-file
  and AP2 Intent Mandates are prior art.
- **We do not claim the account limit protects the customer.** Whether the platform
  enforces it is unknown from the pack.
- **We do not claim our red-team corpus is exhaustive.** 133 cases and 17 attacks are a
  sample, not a proof.
- **We do not claim the official replay counts are a score.** 19/2/24 is a regression
  boundary. There are no official expected-decision labels.

## 6. Two claims this pass retracted

- *"The engine never recomputes `billing_amount_chf`."* False — `amount_integrity` does,
  and blocks a CHF 9,499 purchase declared as CHF 100. I asserted it from a grep of one
  file and the test corrected me.
- *"Multi-run mandate reuse is not reachable."* False — that was our demo convention,
  not the challenge's guarantee.

## 7. Exact final state

| | |
| --- | --- |
| tests | **556 passing** |
| official replay | **45 events — 19 allow / 2 review / 24 block** (unchanged across every pass) |
| red-team corpus | **133/133** |
| adversarial matrix | **17/17** |
| fulfilment differential | **6 disagreements / CHF 1,787.40** |
| `main` | untouched at `1aa3bac` |
| commit | `c99fa30` |

## 8. Freeze

The architecture is frozen. No mechanism is added from here unless new official
evidence or a reproducible attack requires it.

The three open items above are documented, pinned by tests, and none is a defect in
the model — the first is a scope mismatch the model itself predicts, the second is a
limit of the official API, the third is a property of process-local state.

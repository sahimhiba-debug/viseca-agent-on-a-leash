# Autonomous architecture research — the final position

<!-- snapshot -->
> **SNAPSHOT — written 18 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

The mission asked for the smallest architectural primitive that lets a customer
delegate economic agency to a possibly-compromised agent without the agent
converting that delegation into more economic outcome than was authorized.

**The answer is not a mechanism. It is a discipline, plus one thing the challenge's
rule vocabulary cannot express.**

> **Discipline:** every security-relevant fact is either authoritative-and-immutable
> or derived from something that is — never a third thing that can drift.
>
> **Gap:** the vocabulary has exactly one consumable resource (rolling spend).
> "How many times may this job be done" cannot be written down, so it is unbounded.

Decision: **B + D — keep the current architecture, adopt the discipline as
governing, retain derived fulfilment as a parallel prototype and the demo.** Not a
core replacement; not "nothing new"; not a new production mechanism.

---

## 1. Problem reframing

A conventional secure wallet answers *"is this transaction permitted?"* — a
predicate over one proposal. That is necessary and every strong team will build it.

But a compromised agent need not break a rule. It controls something the wallet
never examines: **the decomposition of an objective into a sequence of
individually-permitted transactions.** The wallet sees each purchase; the customer
experiences the aggregate.

So the security question is not about transactions. It is: **what are the
dimensions of the delegation, and which of them are actually bounded?**

---

## 2. Baseline, verified

517 tests · 133/133 corpus · 17/17 legacy · official replay 19/2/24 · `main`
untouched · fulfilment observer absent from `decision_engine`, `rules`, `facts`.

---

## 3. Candidate primitives, and why most failed

| Candidate | Verdict |
| --- | --- |
| `PaymentAuthority` | **rejected earlier.** `charge()` enforces merchant and amount against `StoredDecision`; the authority's copies are unenforced |
| intent fidelity | **rejected earlier.** The rule vocabulary already contains product-identity fields; measured zero decision changes on official data |
| transaction commitment | requires the customer to know the purchase in advance — exactly what agentic shopping is not |
| evidence / provenance graph | more machinery to answer what the ledger already answers |
| outcome-based authorization | **not observable.** The wallet sees authorizations, never deliveries |
| temporal job lease | time-bounds a job but does not count it; orthogonal |
| capability consumed on fulfilment | a parallel record again — the exact failure mode below |
| **derived CHF budget** | **tested and rejected as a mechanism** (§7) — better presentation, subsumes nothing |
| **derived state over an immutable ledger** | **chosen** |

---

## 4. The experiment that decided it

A stateful fulfilment observer was built, audited twice, and **killed by two
attacks**:

- **A8 — human step-up laundering.** Fed from engine ALLOWs, while a step-up
  rewrites the *stored decision*. An agent routing every purchase through step-up
  was never seen to finish the job — while *looking like more oversight*, because
  the customer approves each purchase on its own merits and nothing says "this is
  the fifth time."
- **A12 — restart.** The tally lived on a Python object; the word "fulfil" never
  appeared in the checkpoint. A restart reset the job.

Both are the defect class already found **four times** in `PaymentAuthority` and its
consumption flag (V2, V3, V8/V10, V13/V14). Six instances of one mistake — and the
sixth was committed in a brand-new module *after* three documents had been written
about the first five.

That is the evidence for the discipline. It is not a preference; it is what keeps
being violated.

**The rebuild:** `fulfilment_state(mandate, state, assessing=...)`, a pure function
of the persisted ledger. No object, no tally, no persistence to add, no lock. What
falls out for free:

| Property | Why |
| --- | --- |
| human approvals count | `record_resolution` rewrites the stored decision; this reads stored decisions |
| survives restart | decisions are checkpointed |
| two workers agree | same function, same input |
| nothing races | there is no transition |
| replays collapse | the ledger is keyed by `authorization_id` — six re-deliveries count once |

The last was never designed in. **The architecture became simpler *and* stronger:
an entire object, its persistence and its lock were deleted, and two attack classes
disappeared.**

---

## 5. The differential

`python scripts/run_fulfilment_differential.py` — official engine untouched.

| Mandate | Shape (from the customer's words) | Approved | Questioned |
| --- | --- | ---: | ---: |
| SCEN0000 | one-shot — *"buy one"* | 1 | 0 |
| SCEN0001 | recurring — *"order our …"* | 5 | **0** |
| SCEN0002 | one-shot — *"replace my …"* | 3 | **2** |
| SCEN0003 | standing — *"may buy"* | 5 | **0** |
| SCEN0004 | one-shot — *"the … I chose"* | 5 | **4** |

**6 disagreements, CHF 1,787.40, zero false positives**, official replay 19/2/24.

In the customer's own unit: **CHF 600 delegated across the two one-shot jobs;
CHF 2,241.40 authorized.**

---

## 6. Economic damage, by mandate shape

| Shape | Bound today | With derived fulfilment |
| --- | --- | --- |
| standing | per-txn cap × ∞ | unchanged — correctly; the customer granted it |
| recurring | cap × ∞, or the period cap | unchanged — correctly |
| **one-shot** | **cap × ∞ (measured: CHF 1,729 against CHF 400)** | **cap × 1, then the customer is asked** |
| ambiguous / no anchor | cap × ∞ | unchanged — the observer stays silent |
| human-approved | cap × ∞ (laundering) | **counted** |
| partially fulfilled | n/a | over-fulfilment caught within one authorization |

This separates four limits the challenge conflates: **transaction limit**, **total
spend limit** (period rules — absent from 4 of 5 mandates), **job limit** (new), and
**economic outcome limit** (unobservable — §9).

---

## 7. A candidate tested and rejected

Expressing delegation as a derived CHF budget speaks the customer's unit and makes
a better headline. Tested as a *replacement* for fulfilment counting:

```
2 monitors, qty=2, CHF 398, cap CHF 400
  derived budget   -> within budget (MISSES)
  fulfilment count -> over_fulfilled
```

Two monitors for the price of one delegated monitor are inside the money bound and
outside the job. **Adopted as the headline metric; not built as a mechanism.** A
second check that catches nothing new is how a security layer becomes a feature
factory.

---

## 8. Invariants

1. The decision ledger is write-once per `authorization_id`.
2. The authority lifecycle is monotonic: `issued → consumed | revoked`, both terminal, both persisted.
3. Execution validates against the ledger, at one point, re-read from live state, under an atomic compare-and-set.
4. No derived state gates an external side effect.
5. The agent never declares fulfilment; the wallet derives it.
6. For a one-shot mandate with a specific anchor, the number of authorized performances is a function of the persisted ledger alone.

Invariant 6 is the new one, and it is what no sequence of replay, restart,
concurrency or step-up routing can defeat.

---

## 9. Trust assumptions and limits

**Assumed:** the platform's event stream (root of trust); the mandate text; per-run
scope; one process for single-use; a persist hook for durable execution;
substring anchoring.

**Outside our control:** outcomes in the world — the wallet observes what it
*authorized*, never what was delivered, returned or refunded. Merchant truth about
`item.size`. Compound instructions (fails toward silence). Denial-of-fulfilment via
a cheap decoy matching the anchor (costs the attacker money, yields friction).
Multi-process single-use.

---

## 10. Audits

`FULFILMENT_SECURITY_AUDIT_1.md` (attacked the stateful model, **killed it**) and
`FULFILMENT_SECURITY_AUDIT_2.md` (attacked the rebuild on a different surface;
central property held, one real limitation pinned as a test, two caller-side sharp
edges documented). Earlier: `ARCHITECTURAL_BREAKTHROUGH_AUDIT_1/2.md`.

Four adversarial audits across two abstractions. One abstraction was abandoned
rather than patched.

---

## 11. The demo (90 seconds)

1. Run SCEN0004. Five monitors, **every one ALLOW**, CHF 1,729.
   *"The customer said buy **the** monitor **I chose**. Singular. Your wallet
   approved five — correctly, because each satisfies every rule they wrote."*
2. *"They delegated at most CHF 400. The wallet authorized CHF 1,729."*
3. Run the differential: 6 disagreements, and **silence** on *"order our household
   groceries"* and *"the agent may buy clothing"* — those repeat by nature.
4. Show the evidence line: `'the … I chose' names one specific item already
   selected — already fulfilled by AU0035`.
5. *"And it survives restart, counts purchases the customer approved at step-up,
   and collapses replays — because it isn't tracked. It's derived from the ledger."*

---

## 12. Claims

| Claim | Evidence | Safe wording |
| --- | --- | --- |
| The vocabulary has one consumable resource | the schema | "Rolling spend is the only consumable; everything else is a stateless predicate." |
| 6 approved purchases repeat a job described once | reproducible differential | "On the official data, six approved purchases worth CHF 1,787 repeat a job the customer described once." |
| Zero false positives | differential | "It stays silent on the two mandates that are legitimately repeatable." |
| Derivation survives restart / step-up / replay | 27 tests | "Fulfilment is derived from the decision ledger, so it survives restart and includes purchases the customer approved." |
| It never blocks | code | "Its strongest action is to ask the customer." |

**Must not say:** "we invented one-shot mandates" (SEPA, card-on-file, AP2 —
see `ARCHITECTURE_PRIOR_ART.md`); "we understand intent"; "this blocks the attack";
"it's in the decision path"; anything about compound instructions.

---

## 13. The twelve questions

1. **Security object** — the run's persisted decision ledger.
2. **Minimum trusted state** — mandate snapshot + ledger + monotonic authority lifecycle.
3. **A compromised agent can still** — spend the full policy envelope (unbounded for standing/recurring), burn a one-shot job with a decoy, lie about `item.size`, exploit multi-process single-use.
4. **It can no longer** — silently repeat a finished one-shot job, launder through step-up, reset by restart, double-execute, re-point an approval.
5. **The attack** — SCEN0004: five monitors, CHF 1,729 against CHF 400 delegated.
6. **Why prevented** — fulfilment derived from the ledger, anchored on the customer's own compiled anchor, so evading it costs the agent the policy check.
7. **Assumptions** — §9.
8. **Outside our control** — outcomes in the world; §9.
9. **Structurally different** — a conventional wallet evaluates a predicate over one transaction; this queries a delegation consumed against an immutable ledger.
10. **Demo** — yes, 90 seconds.
11. **Two audits** — four, across two abstractions; one abstraction abandoned.
12. **Simpler or stronger** — **both.** An object, its persistence and its lock were deleted; two attack classes disappeared with them.

---

## 14. Honest closing

The deepest result is not the fulfilment feature. It is the discipline the
fulfilment work proved the hard way: **six vulnerabilities in this project were one
mistake repeated — mutable security state kept beside the record that already
determines it.** The sixth was committed after five had been documented, which is
the strongest evidence available that the principle is not obvious.

The fulfilment gap is the demonstration. The discipline is the result.

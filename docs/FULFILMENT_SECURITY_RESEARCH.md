# Fulfilment security — the layer underneath

The brief said: *assume there is another layer underneath the fulfilment
discovery.* There was, and it is not a better fulfilment tracker.

**Result: the stateful fulfilment observer was abandoned and replaced by a pure
derivation over the run's persisted decision ledger.** Two attacks killed the
prototype; the concept survived; the abstraction did not.

---

## 1. Phase 0 — baseline, verified independently

| | |
| --- | --- |
| Branch / tree | `rnd/verifiable-agentic-wallet`, clean |
| Tests | 509 (now 517) |
| Official replay | 45 events — 19 / 2 / 24 |
| Corpus / legacy | 133/133, 17/17 |
| Observer in the decision path | absent from `decision_engine.py`, `rules.py`, `facts.py` |
| Differential | 6 disagreements, CHF 1,787.40 — reproduced |

Everything matched the brief.

---

## 2. Redefining "fulfilled"

Five definitions, judged by what the wallet can actually observe.

| | Definition | Evidence needed | Verdict |
| --- | --- | --- | --- |
| A | **Product** — the requested product was purchased | approved decisions + item names | **usable** — all of it is already recorded |
| B | **Quantity** — the requested count was purchased | + basket quantities | **usable**, and necessary (Audit 1) |
| C | **Job** — the delegated objective is satisfied | the objective, which is natural language | partly — only as far as the compiled anchors go |
| D | **Outcome** — the customer got the thing | delivery, returns, disputes | **not observable.** The wallet sees authorizations, never outcomes |
| E | **Commitment** — the mandate's authority is consumed | the decision ledger | **usable**, and the closest to correct |
| F | **State transition** — pending → completed | a state machine | **the trap.** See §4 |

D is the honest boundary: **the wallet can never know whether a job was
*fulfilled in the world*.** It can only know what it *authorized*. Everything in
this document is about authorized fulfilment, and the demo must say so.

**Who decides fulfilment?** Not the agent — it never declares completion, which
kills attack classes 21 and 22 (claim-of-fulfilment, evidence manipulation) by
construction. The wallet derives it from its own records. That is the single most
important design choice here.

---

## 3. The true security object

Not the job, and not a fulfilment counter.

Every vulnerability across five missions has the same shape:

| | Parallel record | How it diverged |
| --- | --- | --- |
| V2 | PaymentAuthority | a human-approved step-up minted none |
| V3 | PaymentAuthority | a restart lost it |
| V8 / V10 | consumption flag | a restart lost it |
| V13 / V14 | consumption flag | a concurrent transition overwrote it |
| **A8** | **fulfilment tally** | **a human-approved step-up never reached it** |
| **A12** | **fulfilment tally** | **a restart reset it** |

Six instances, one mistake: **lifecycle state kept *beside* the record it
describes, free to drift from it.**

So the security object is **the run's decision ledger** — the immutable, persisted
sequence of `StoredDecision`s — and everything else should be a *derived view* of
it, never a second record.

---

## 4. Attacks that killed the prototype

**A8 — human step-up laundering.** The observer was fed from engine ALLOWs. A
step-up the customer approved changes the *stored decision*, not the engine's
answer, so it never reached the tally. An agent that routes every purchase through
step-up is never seen to finish the job — and it gets the human to approve each
one individually, which looks like *more* oversight, not less.

```
AU1 -> review -> human approves -> stored decision = allow
observer on the next monitor -> first_fulfilment    *** laundered ***
```

**A12 — restart.** The tally lived in a `FulfilmentMonitor` object. `RunState`'s
snapshot never contained the word "fulfil". A restart reset the job to unfulfilled.

```
fulfilment state present in the RunState snapshot? False
after restart -> first_fulfilment                   *** reset ***
```

I had rebuilt, in a brand-new module, the exact defect I had already found three
times and written three documents about. That is the finding.

---

## 5. The rebuild

Per Phase 10, the abstraction was replaced rather than patched.

```python
def fulfilment_state(mandate, state, *, assessing=None) -> FulfilmentVerdict
```

A pure function of `(mandate, persisted decisions)`. No object, no tally, no
persistence to add, no lock. What that buys — none of it by patching:

| Property | Why it holds |
| --- | --- |
| human approvals counted | `record_resolution` rewrites the stored decision; this reads stored decisions |
| survives restart | `_decisions` is checkpointed |
| two workers agree | both compute the same function of the same input |
| no race | there is no transition to race |
| replays counted once | the ledger is keyed by `authorization_id` |

That last one is a property the tally never had: six re-deliveries of one
authorization would have incremented a naive tally six times.

---

## 6. Competing architectures considered

| | Architecture | Why not |
| --- | --- | --- |
| A | fulfilment counter / state machine | **this is what was built and abandoned** — it *is* the parallel-record mistake |
| B | transaction commitment (customer pre-commits to a hash) | requires the customer to know the purchase in advance; agentic shopping is exactly the case where they do not |
| C | job capability consumed on fulfilment | a capability is a parallel record again, with the same six failure modes |
| D | evidence/provenance graph | more machinery to answer a question the ledger already answers |
| E | outcome-based authorization | **not observable** (§2 D). The wallet never learns whether goods arrived |
| F | temporal job lease | time-bounds a job but does not count it; orthogonal, and mandates already have platform-side expiry |
| **G** | **derived state over an immutable ledger** | **chosen** — strictly fewer moving parts, and it removes the failure class rather than handling it |

---

## 7. Would another team build this?

| | |
| --- | --- |
| spend caps, merchant rules, step-up, injection defence, fingerprints, audit | **conventional** — the spec asks for them |
| capability token around an approval | conventional-ish |
| **"a one-shot job can be finished"** | **novel** — needs the observation that the rule vocabulary has exactly one consumable resource |
| **"derive lifecycle state; never store it beside the record"** | **the transferable result**, and the one a team is least likely to reach without having been burned six times |

**Honest prior art.** One-off versus recurring mandates are decades old in payments
(SEPA mandate types, card-on-file vs single-use, AP2's Intent Mandate). Event
sourcing and derived read models are standard distributed-systems practice. Neither
idea is ours. What appears genuinely new is **applying the derived-state discipline
to agentic authorization, and deriving job shape from a natural-language mandate.**

---

## 8. The new security property

> **For a one-shot mandate with a specific product anchor, the number of
> authorized performances of the job is a function of the run's persisted decision
> ledger alone. No sequence of agent actions — replay, restart, concurrent
> workers, or routing purchases through human step-up — can cause the wallet to
> authorize a second performance without the customer being asked.**

Conditional on: the platform's event stream, the mandate text, per-run scope, and
substring anchoring. It says nothing about outcomes in the world (§2 D).

---

## 9. Economic damage, by mandate shape

Maximum a fully compromised agent can extract, per shape:

| Shape | Bound today | With derived fulfilment |
| --- | --- | --- |
| standing ("may buy clothing") | per-purchase cap × ∞ | unchanged — correctly, the customer granted it |
| recurring ("order our groceries") | cap × ∞, or the period cap | unchanged — correctly |
| **one-shot ("the monitor I chose")** | **cap × ∞ (measured: 5 monitors, CHF 1,729)** | **cap × 1, then the customer is asked** |
| partially fulfilled | n/a | over-fulfilment caught within one authorization |
| ambiguous / no anchor | cap × ∞ | unchanged — the observer stays silent |
| human-approved | cap × ∞ (laundering) | **counted** |

This separates four limits the challenge conflates: **transaction limit** (per
purchase), **total spend limit** (period rules — absent from 4 of 5 official
mandates), **job limit** (new), and **outcome limit** (unobservable).

---

## 10. Limitations

- **Outcomes are invisible.** Refunds, cancellations and non-delivery do not
  un-finish a job. Fails toward asking.
- **Denial-of-fulfilment** (Audit 2): a cheap decoy matching the anchor burns the
  job and forces the real purchase to need approval. Costs the attacker money,
  yields friction, not funds.
- **Compound instructions** lose one-shot protection (fails toward silence).
- **Substring anchoring** is coarse; a product taxonomy would be needed, and this
  project has repeatedly declined to fake one.
- **No mandate/run binding** on the derivation — the caller must pass the run's own
  mandate.
- Per-run scope, like every other ledger here.

---

## 11. Recommendation

**Prototype + demo. Do not gate official decisions.** Gating would move the replay
to 13/8/24 on the strength of a heuristic classifier. The production shape is
opt-in at confirmation: *"this looks like a single job — ask me before repeating
it."*

The transferable engineering result is narrower and more useful than the feature:
**derive lifecycle state from the ledger; never keep a second copy beside it.**
Six vulnerabilities in this project were instances of ignoring that.

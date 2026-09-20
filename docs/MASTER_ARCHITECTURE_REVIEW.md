# Master architecture review

Re-verified at `b5b2b0e`, not taken from previous reports.

| | verified |
| --- | --- |
| suite | 942 passed, 5 skipped (947 collected) |
| official replay | 45 — 19 allow / 2 review / 24 block |
| corpus / matrix / mutation | 133/133 · 17/17 · 36/36 |
| runtime | 5,744 lines across 19 modules |
| `main` | `1aa3bac`, untouched |

---

## 1. The finding that matters most for this competition

**There is no agent in this repository.**

Nineteen runtime modules. None of them plans, searches, selects a merchant, builds
a basket, or reacts to a decision. What the UI calls *"Watch the agent shop"* is
`start_scenario_run` replaying twelve pre-recorded CSV rows.

That is defensible for the *challenge* — the official pack supplies the purchase
attempts and the wallet's job is to decide them — but the jury criterion is
**"Do autonomous agents handle complex logic?"**, and the honest answer today is no.
This is the single largest gap between what the project is and what it is judged on.

It is also the gap whose closure most improves the other criteria at the same time,
which is the test §27 sets for any new mechanism.

## 2. What is actually strong, and should not be touched

Re-derived by attacking it, not by reading the previous reports:

* **The decision core.** `fail > unknown > pass`, one write-once ledger, one
  execution point under compare-and-set. 36 mutants, all killed.
* **The authority boundary.** The engine takes rules from a frozen snapshot; the
  event cannot widen policy; the platform's echo is now compared, not adopted.
* **Intent fidelity.** 204 independent phrasings: 0 silently weakened, 0 incorrectly
  strengthened.
* **Honesty apparatus.** `WHAT_WE_REFUSE_TO_CLAIM.md`, a machine-checked invariant
  register, self-describing numbers that fail the build when stale. Few teams will
  have anything like this, and it is the thing a senior engineer on the jury will
  respect most.

None of this needs redesign. Redesigning it to look busy would be the worst available
use of this campaign.

## 3. Re-derived security model

| question | answer |
| --- | --- |
| What is authorized? | one **purchase attempt**, identified by `authorization_id` |
| Who is the authority? | the **customer**, via a confirmed mandate |
| What is delegated? | the right to *propose*; never the right to *decide* |
| Scope of delegation | `hard_rules` at purchase or period scope — the vocabulary closes the set |
| Lifetime | mandate `active` → `revoked`; a run freezes a rules snapshot at start |
| Economic boundary | `MockPSP.charge`, one compare-and-set against the ledger |
| Authoritative facts | platform: statuses, amount, timestamp, ids, history |
| Evidence only | merchant free text: return window, item size |
| Agent controls | basket, timing, merchant choice, retries — **never** a decision |

**Falsification attempted, result:** the three-scope model (authorization / mandate /
account) survived again. The one object whose *scope* is wrong is the spend ledger:
it is keyed by **run**, and the customer's bound is temporal. That is an
implementation artifact standing in for a security boundary, documented and measured
at 10×, and it is not agent-reachable because the agent cannot create runs.

## 4. Explanation as an attack surface — the measurement that drives Phase 2

The wallet is an **oracle**. Any decision system is. Measured:

> With only ALLOW/BLOCK visible, an agent recovers a secret CHF 137 ceiling to within
> **CHF 0.24 in 12 probes**. Cost to the agent: **CHF 531.49 actually spent**, because
> every ALLOW probe is a real purchase.

That has two consequences the rest of this campaign turns on.

**(a) An adapt loop does not create the oracle; it uses the one that already exists.**
An agent that lowers its basket after a BLOCK is performing exactly one step of that
binary search. Refusing to build the loop does not remove the capability — it only
removes our ability to demonstrate that we understand it.

**(b) What we must never do is turn 12 probes into 0.** The current API response
carries `"value": <the rule's number>` and `projected N-day spend=…` in twenty
evidence strings. That is **correct for the customer**, who owns the policy and is
entitled to see it — and it would be a total leak to an agent.

So the boundary is not *whether* to explain, but *to whom*:

| audience | may see |
| --- | --- |
| **customer** | everything: rule values, projected spend, plain reasons, evidence |
| **agent** | the decision, and **which class of constraint** failed — no numbers |
| **audit log** | everything, immutable |

No current code enforces that separation, because no agent-facing surface exists yet.
Building one without the separation would be the single worst thing this campaign
could do.

## 5. Weaknesses carried forward, unchanged

1. **Cross-run spend** — run-scoped, 10× measured, operator-controlled. Design for a
   fix is established (key state on `mandate_id`); deliberately not taken during a
   freeze.
2. **Merchant-declared evidence** — two fields can flip REVIEW → ALLOW, verifiable by
   nothing.
3. **Step-up resolver identity** — the protocol carries none.
4. **Quantity / total / end date** — inexpressible; disclosed and blocking at
   confirmation.
5. **Per-process exactly-once.**

## 6. Conclusion of the review

The security architecture is near its defensible boundary under this protocol. The
*product* is not: it is a decision engine with no agent in front of it, judged on
agentic depth.

Phase 2 therefore proposes exactly one new mechanism, chosen because it is the only
candidate that improves security, agentic depth, UX, demo and differentiation
simultaneously.

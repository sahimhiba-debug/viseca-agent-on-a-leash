# Final judge Q&A

For each: the strongest factual answer the implementation supports, and — separately —
**what is not proven**. No invented capabilities.

---

**1. Where is the AI?**
Deliberately outside the money path. The agent plans, substitutes and replans; the
wallet decides deterministically. `technical_details.md` requires a predictable
response when the model is unavailable, so putting a model between a customer and
their card would break the one property the spec insists on.
*Not proven:* that a model-based planner would perform better. We built the seam for
one and did not fill it.

**2. Why isn't this just an API wrapper?**
A wrapper forwards. This decides, and refuses. 39 security mechanisms, each of which
we break on purpose to prove a test catches it. The agent is a separate process that
talks to it over HTTP and is refused three times in the demo.
*Not proven:* nothing here is a novel algorithm. The sliding-window containment fix is
textbook once you see the bug.

**3. Why does the wallet need to be separate from the agent?**
Because the agent can be wrong, compromised, or someone else's code. We test that
directly: five hostile planners — one proposing CHF 150,000, one hallucinating items,
one crashing, one empty, one that never learns — and in every case the wallet approves
nothing and moves no money.

**4. What happens if the agent is malicious?**
It proposes; it never decides. It cannot raise a ceiling, forge a platform field, fake
merchant familiarity, or charge. 133 adversarial cases and 17 matrix attacks hold.
*Not proven:* that our adversarial corpus is exhaustive. It is a sample.

**5. Can the agent learn the spending limit?**
Yes, slowly and expensively, and we publish the number: ~12 probes to recover a
CHF 137 ceiling to CHF 0.24, costing CHF 531 in purchases it must keep. Any yes/no
system is an oracle. What we prevent is the shortcut — the customer's payload carries
the rule value and would give it up in **zero** queries; the agent's never does.
*Not proven:* that the oracle can be eliminated. It cannot.

**6. What happens if the model hallucinates?**
Tested as a first-class case. A planner returning items that do not exist, or garbage
instead of a basket, ends at the customer — never at a purchase.

**7. What happens if the model is unavailable?**
The shipped planner is deterministic, so the judged path has no model to lose. A
planner that raises is caught and the agent hands back to the customer. Replay and the
agent episode are byte-identical across runs, with no network and no API key.

**8. Why trust merchant evidence?**
We don't. Merchant text is read in one place under whitelist patterns and can only
**narrow** a decision. It cannot raise a ceiling, fake familiarity, or override a
platform status — verified.
*Not proven, and the largest real exposure:* on two fields (return window, item size) a
plausible lie can move REVIEW → ALLOW. Nothing in this protocol can verify them.

**9. What prevents double spending?**
One execution point, an atomic compare-and-set against a write-once ledger. Eight
concurrent charges → exactly one succeeds.
*Not proven:* exactly-once. It is **at-most-once, per process**; two workers restoring
one checkpoint each charge once. Said plainly in the UI.

**10. What happens after revocation?**
An outstanding authority is swept, a purchase still awaiting the customer's answer
cannot acquire one, a charge after revocation is refused, and a new run under a revoked
mandate blocks.
*Not proven:* what the platform does with work already queued. The spec leaves it open.

**11. What happens across multiple shopping sessions?**
The rolling window is enforced per session, matching the platform's own scope. Ten
sessions under one mandate put CHF 2,999 through a CHF 300/7-day cap — **measured**,
and disclosed to the customer at confirmation.
*Not proven:* that cross-session enforcement is impossible. Team-scoped records exist;
their shape is under-documented and we chose not to rely on it. Honest, and the first
thing we would fix next.

**12. Why not just use traditional card controls?**
A card control knows an amount and a merchant category. It cannot know *"only the
27-inch monitor I chose, from a seller I've used, and nothing added to the basket"* —
and it cannot ask you when it isn't sure. Our blocks are 33 customer-policy violations
against 0 wallet-safety blocks on the official corpus: the wallet enforces the
customer's sentence, not a generic limit.

**13. What is genuinely new here?**
Not the crypto, not the algorithms. Two things: **an explanation protocol with two
audiences** — the customer sees their policy, the agent sees a decision and a
constraint class — and the **discipline apparatus**: a mutation probe, a machine-checked
invariant register, self-describing numbers that fail the build when stale, and a
document listing what we refuse to claim.
*Not claimed as novel:* capability attenuation, sliding-window limits, step-up. All
prior art.

**14. Who would buy this?**
Any issuer whose customers will soon be asked to let an agent shop — which is every
issuer. The unit being sold is not the rules engine; it is the defensible answer to
*"what happened when it got my instruction wrong?"*

**15. Why is this necessary for agentic commerce?**
Because the failure mode is not fraud, it is **misreading**. An agent that
misunderstands you and spends faithfully is worse than one that is hacked, because
nothing looks wrong. This system is built so that misreading cannot silently widen
what you granted: unrepresentable intent blocks confirmation, merchant text can only
narrow, and the agent is told a decision rather than a threshold.

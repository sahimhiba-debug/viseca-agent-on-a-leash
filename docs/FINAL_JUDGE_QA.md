# Final judge Q&A

For each: the strongest factual answer the implementation supports, and — separately —
**what is not proven**. No invented capabilities.

---

**1. Where is the AI?**
Deliberately outside the money path. The agent searches over candidate baskets
against an explicit objective function, learns from refusals, and calls a tool to
look at the shop; the wallet decides deterministically. `technical_details.md`
requires a predictable response when the model is unavailable, so putting a model
between a customer and their card would break the one property the spec insists on.

We no longer say "we built the seam and did not fill it" — we filled it and measured
it. `research/model_planner.py` puts a model planner at the same seam and
`research/architecture_comparison.py` runs the eleven-episode benchmark eleven ways:
the deterministic planner scores 11/11 with zero model calls, the best a model
manages is a **tie**, and a confidently-wrong model *with a deterministic fallback*
scores **8/11** — below the planner it was meant to improve, because a fallback
catches answers that are unusable and that one is merely wrong.
*Not proven:* that a real language model behaves like any of our stubs. Those are
stubs; no API was called. What is measured is the architecture's sensitivity to model
behaviours, not any model's ability.

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

---

## Questions this campaign invites

**How do I know your agent is a real agent and not a script?**
Because we tried to prove it wasn't, in public. `research/planning_benchmark.py` is
eleven adversarial episodes written **before** the agent was touched, so that it
could fail — and it did, **5/11**. In five of them the cheapest valid-looking basket
is the wrong one. Across all eleven the old agent used two distinct moves: swap for
the cheapest, drop the dearest. Its own documented "try another merchant" rung never
fired once. The agent you saw scores 11/11; the old one, re-measured against the same
episodes, still scores 5/11.
*Not proven:* that eleven small synthetic worlds represent a real catalogue. They are
diagnostic, not representative, and the claims register grades this SUPPORTED rather
than PROVEN for exactly that reason.

**Isn't "the cheapest basket" a trivially easy objective?**
It is, which is why it is the wrong one and why the benchmark is built to punish it.
Episode K has three baskets that look buyable, exactly one is allowed, and it is the
**dearest**. The old agent deleted the right answer first *because* it was the
dearest. The objective now reads: do more of the errand, prefer goods that can be
sent back once a refusal showed that matters, and only then spend less. Price is last.

**Your agent was approved in one attempt in the privacy test but took three in the
demo. Which is it?**
Both, and the difference is the point. It settles low — CHF 7.50 against a hidden
ceiling of CHF 137 — because the objective walks *away* from the limit. It takes
three attempts in the demo because that mandate also restricts the shop and the
return terms, and no amount of spending less fixes either. Two of the three demo
refusals are not about money at all.

**What stops it retrying until something goes through?**
Three things. `MAX_REVISIONS` bounds the loop; it never re-proposes a basket it has
already tried; and a refusal about *the agent* rather than *the purchase* —
`duplicate`, `session` — halts it unconditionally, even when a perfectly good
alternative basket is sitting right there. That last one was a regression the search
introduced, found by our own tests, and it is the behaviour we would least want a
judge to find: an agent answering "you look like a runaway" by rephrasing itself
until the wallet stops noticing.

**Could a hostile shop make your agent misbehave?**
It could waste the customer's attempts, and did. A quoted price of CHF -1000 was
enough to make the search propose it — the objective prefers spending less and
nothing spends less than a refund. The wallet blocked it (it refuses any non-positive
amount), so no money could move, but one of four attempts was gone. The agent now
treats what its tool returns as untrusted input. A shop big enough to stall it is
bounded too: 1,000 merchants took 1.6s against an 8s deadline before the cap went in.

**Can a sequence of refusals teach it that it may spend more?**
No, by construction rather than by testing. The believed ceiling only ever falls and
a ruled-out shop is never reinstated. And what it believes is not the customer's
limit — it is "strictly less than a total I already tried", which is all a refusal
can honestly say.

**Does the agent know the customer's limit?**
The wallet never tells it one, and that is provable. But the errand is the customer's
own sentence and that sentence says "CHF 120", so the honest answer is: the number is
in the agent's possession, and the shipped planner never reads it — it uses the
category and how many lines count as the errand done. A **model** planner would read
it straight out of the prompt. We found this while writing the test that was supposed
to check it, and which had been quietly slicing that line out of its own assertion.

**The demo page runs its own planner. Isn't that a second, unverified agent?**
It was. It carried a comment claiming it used "the same strategy ladder the Python
agent uses", and by the time anyone read it that had stopped being true. Both
planners now run over the page's own offer list across eight refusal sequences, and
the suite fails if they choose different baskets, in a different order, or a
different shop.

# Final competitor analysis

No ranking, no winner. What each would show, what we show that they may not, and what
each of us cannot safely claim.

---

## Competitor A — "LLM shopping agent + wallet"

**Their two minutes.** A chat box. *"Order our weekly groceries, keep it under CHF
120."* The model reasons aloud, searches, assembles a basket, explains its choices in
fluent language, and buys. Genuinely impressive; the most likely crowd favourite.

**Their vulnerabilities.** The model is in the loop, so: what happens when it is
unavailable? When it hallucinates a basket? When the customer's sentence is ambiguous —
does it *guess*? The spec asks for a predictable response when the model is
unavailable, and a live model makes their demo unreproducible. A judge who asks
*"what did it do when it misread the customer?"* will usually get an anecdote.

**What we can show that they may not.** Five hostile planners — greedy, hallucinating,
raising, empty, non-learning — with the wallet approving nothing and moving no money in
every case. Their architecture may well be fine; ours is *tested*.

## Competitor B — "multi-agent shopping system + policy engine"

**Their two minutes.** An architecture diagram with four or five agents — planner,
searcher, negotiator, compliance — messaging each other, then a purchase.

**Their vulnerabilities.** Where is authority? If "compliance" is an agent, it can be
argued with. The obvious question is *"which component can be wrong without money
moving?"*, and multi-agent designs usually answer it with a diagram rather than a test.

**What we can show that they may not.** One authority boundary, 47 machine-checked
invariants, and an explicit list of what we refuse to claim. Complexity is easy; a
stated boundary is not.

## Competitor C — "minimal wallet + deterministic agent"

**Their two minutes.** Closest to us: clean rules, clear decisions, fast.

**Their vulnerabilities.** Thin on agentic depth, and probably thin on intent — most
deterministic compilers silently drop what they cannot parse, which is precisely the
defect class we spent a campaign eliminating.

**What we can show that they may not.** An agent that is refused three times and
recovers; 204 restrictive phrasings with **zero silent weakenings**; unrepresentable
intent that *blocks confirmation* rather than being quietly dropped.

## Our differentiators, in the order a jury would value them

1. **The agent is refused on camera and recovers** — most demos show success.
2. **Two audiences, one decision.** The customer sees the limit; the agent sees
   `blocked_by: [amount]`. Both on screen at once.
3. **A mutation probe** that breaks 39 mechanisms on purpose; all 39 caught.
4. **`WHAT_WE_REFUSE_TO_CLAIM.md`.** The most disarming artefact we have.
5. **Reproducibility.** Byte-identical replay and agent episode; no network, no key.

## Our vulnerabilities, and the honest answer to each

| they attack | our answer |
| --- | --- |
| "Your compiler is regexes" | Yes. 204 phrasings, 0 silent weakenings; what it cannot represent **blocks confirmation** |
| "Where is the AI?" | Deliberately outside the money path, and the seam is tested against five hostile planners |
| "Your agent is a strategy ladder" | Yes. It handles nine adversarial episodes; the old one gave up on five |
| "The agent still learns your limit by probing" | True and priced: ~12 probes, CHF 531. We publish the number |
| "Cross-session limits aren't enforced" | True, measured at 10×, disclosed at confirmation |

## Claims none of us can safely make

* That an agent cannot eventually infer a threshold from decisions. Nobody can.
* That merchant-declared facts are verified. They are not verifiable in this protocol.
* That a step-up is authenticated. The protocol carries no resolver identity.
* That a replay count is a score. The pack ships `contains_expected_decisions: false`.

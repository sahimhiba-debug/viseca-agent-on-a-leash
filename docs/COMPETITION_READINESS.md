# Competition readiness

Honest assessment against the five jury criteria, plus the judge Q&A and the final
self-critique.

---

## 1. Assessment

| dimension | classification | basis |
| --- | --- | --- |
| **Technical functionality** | **EXCEPTIONAL** | 1,662 tests, 41/41 mutation kills, deterministic replay, six research modules byte-identical across runs, no network or model needed to run anything |
| **AI** | **ADEQUATE, and now argued rather than asserted** | deliberately *not* an LLM in the money path — `technical_details.md` requires predictable behaviour when a model is unavailable, and prefers "smaller, lower-latency models" if one is used at all. The positive form of the argument is the **acceptance set**: `optimized-apertus` is about speculative decoding, where an untrusted fast proposer changes the *speed* and never the *distribution*. Measured here over four brains and an exhaustive 595-basket adversary: **not one approved purchase outside the set**. A jury expecting "AI" still needs this said out loud. **No model has been run** — `api.publicai.co/v1` answers 401 without a key |
| **Agentic depth** | **STRONG** (was a CRITICAL GAP at the start of this campaign) | an autonomous agent now plans, proposes, is refused, adapts and succeeds on the merits — as an external HTTP client, visible in the UI |
| **UX** | **STRONG** | mobile-first at 375/390/412, plain-language reasons, explicit scope on every step-up, no overflow or clipping under hostile content |
| **Uniqueness / fun** | **STRONG** | watching an agent get *refused three times and recover* is memorable; the mutation probe and the refusals list are distinctive to engineers |
| **Market impact** | **STRONG** | this is the actual product shape of agentic commerce; the boundary drawn here is the one the industry has not settled |
| **Reproducibility** | **EXCEPTIONAL** | replay and agent episode byte-identical across runs; no secrets; one command |
| **Security** | **EXCEPTIONAL** | 46 registered invariants, machine-checked; every claim carries a stated limitation. Twelve instances of one defect class in `docs/ABSENCE.md`, **four of them found by reading the organizers' own material rather than by any sweep we built** |
| **Fidelity to the brief** | **STRONG (was FAILING one requirement)** | the challenge asks a demo to show "one ambiguous, unsafe, or **manipulated** transaction receiving a useful intervention". Until this session the pack's manipulated purchase was **approved** with the words *"matches the rules you set"*. It now goes to the customer, and so does an unexplained device change |
| **Generalisation** | **ADEQUATE** | the compiler is phrase patterns; 90% of a 103-phrase corpus, 0 silent weakenings. Honest, and bounded |

### The one dimension that changed, and why it was the right target

**Agentic depth** was the gap: nineteen runtime modules and not one of them was an
agent. The UI said *"Watch the agent shop"* over a CSV replay. Closing it also
improved UX, uniqueness and demo value at once — the test §27 sets for a new
mechanism — and it forced a genuine security question rather than dodging one.

## 2. The 60-second demo

1. *(10s)* **"Your agent shops. It never holds your card."** Write the rule in plain
   English; show the compiled policy **and** what we could not represent.
2. *(25s)* **Agent tab → Send the agent shopping.** CHF 292 → refused. CHF 197 →
   refused. CHF 137 → refused. **CHF 87 → allowed.** Point at what the agent was
   told: `blocked_by: [amount]`. *"No amount. No limit. No remaining budget. It
   stopped at 87, not 119.99 — because it never learned the number."*
3. *(15s)* **Attacks tab.** Nine attacks, live, against the same engine — **eight stopped, and one is not**, with the argument attached.
4. *(10s)* **`WHAT_WE_REFUSE_TO_CLAIM.md`.** *"This is the part we'd rather you read."*

Everything is reproducible; nothing is staged; the fixed simulated clock makes the
agent trace identical every run.

## 3. Competitor simulation

| team | what they show | what we show that they cannot |
| --- | --- | --- |
| **A — great agent + LLM** | a smooth agent that succeeds | ours **fails on camera and recovers**, and we can prove what it was and was not told. Theirs cannot run offline; `technical_details.md` asks for exactly that |
| **B — great deterministic engine** | correct decisions, good tests | an *agent*, an audience-separated explanation protocol, and a mutation probe that breaks their class of system on purpose |
| **C — multi-agent security** | impressive architecture diagram | 46 machine-checked invariants and a document listing what we refuse to claim. Complexity is easy; a stated boundary is not |

**What they would attack us on:** "your compiler is regexes", "no LLM", "cross-run
limits are not enforced". All three have evidence-backed answers below.

## 4. The ten questions, and our answers

1. **"Your compiler is regexes — what happens when it mishears?"** It did, six ways,
   and we found them. 204 independent phrasings: 0 silently weakened, 0 incorrectly
   strengthened. Restrictive language we cannot represent **blocks confirmation**.
2. **"Where is the AI?"** Deliberately not in the money path: the spec requires a
   predictable response when the model is unavailable. The agent is autonomous; the
   authority boundary is deterministic and auditable. That is a design position, and
   we will defend it.
3. **"Does the agent learn your limits by probing?"** Measured: twelve probes to
   recover a CHF 137 ceiling, costing CHF 531 of real purchases. The customer's own
   payload would do it in zero, which is why the agent gets a different projection.
4. **"So the agent could still extract the policy eventually?"** Yes — the ALLOW/BLOCK
   oracle is irreducible in any decision system. We made it expensive, not secret,
   and we say so.
5. **"Is the step-up authenticated?"** No. The protocol carries no resolver identity.
   We say it first rather than concede it.
6. **"Do you enforce the CHF 300/7-day limit across sessions?"** No. Run-scoped,
   measured at 10×, disclosed at confirmation. The record plausibly exists at team
   scope; its shape is under-documented; we chose not to rely on it.
7. **"Is 17/4/24 a score?"** No — the pack ships `contains_expected_decisions: false`.
   It is a regression boundary, and it is conditional on our reading of five sentences.
8. **"Could a merchant lie its way to an approval?"** On two fields, yes: return
   window and item size. It cannot raise a ceiling, fake familiarity or override a
   platform status. Largest real exposure, unfixable in the vocabulary.
9. **"Your 960 tests could be trivial."** `run_mutation_probe.py` breaks 38 mechanisms
   one at a time; all 38 are caught. It has found four real gaps.
10. **"What would you fix with another week?"** Cross-run enforcement, by keying
    worker state on `mandate_id`. The design needs no new security object.

## 5. Final self-critique

> **What is the strongest remaining argument that this project is mediocre?**

*"It is a rule engine with a rules-based agent bolted on. The 'AI' is regexes and a
loop that drops the most expensive item. The security work is thorough but it is
thoroughness about a small problem — the hard part of agentic commerce is
understanding what the customer meant, and you explicitly refuse to do that."*

**That is the strongest argument, and it is half right.**

Half right: the compiler *is* phrase patterns, and the planner *is* arithmetic.
Neither will impress anyone looking for model sophistication.

Where it fails: it mistakes the problem. The hard part of agentic commerce is **not**
understanding the customer — it is what happens when you are *wrong* about them while
holding their card. Every system that guesses will sometimes guess wide. This one is
built so that guessing wide is impossible: unrepresentable intent blocks confirmation,
merchant text can only narrow, and the agent is told a decision rather than a
threshold. A model-driven competitor has a better demo on the happy path and no
answer at all to *"what did it do when it misread me?"*

The honest residue: we are betting a jury values a defensible boundary over a
impressive-looking one. If they want to see an LLM reason about a purchase, we lose
that point, and we accept it knowingly rather than bolting a model into the money path
the week of the event.

## 6. What a competitor could still do better

Build the same wallet **and** a genuine model-based planner behind it, with the model
strictly outside the authority boundary — proposing baskets, never deciding. That is
strictly more impressive than what we have, it is compatible with everything here, and
it is what we would build with more time. We did not, because a model in the demo path
makes the demo unreproducible, and reproducibility is a stated jury criterion we can
win outright.

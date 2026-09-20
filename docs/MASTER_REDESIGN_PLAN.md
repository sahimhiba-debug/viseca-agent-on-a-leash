# Master redesign plan

One new mechanism. Everything else is left alone, deliberately.

---

## What is NOT being changed, and why

| candidate | decision |
| --- | --- |
| the decision core (`fail > unknown > pass`) | **keep** — 36 mutants, all killed; a redesign would trade proven behaviour for novelty |
| the three-scope security model | **keep** — falsified again this campaign and survived |
| the compiler's deterministic design | **keep** — 204 phrasings, 0 silent weakenings; an LLM here violates *"predictable when the model is unavailable"* |
| cross-run ledger re-scoping | **defer** — not agent-reachable; touches checkpointing; documented at 10× |
| provenance as a first-class object | **reject** — would change official-corpus decisions and is a redesign, not a fix |
| new policy scopes / fulfilment objects | **reject** — the vocabulary closes the set; inventing one is inventing protocol |

## The one mechanism: an agent that adapts, behind an audience-scoped explanation

### Benefit across all five jury dimensions

| dimension | contribution |
| --- | --- |
| technical + AI | a real plan→propose→observe→revise loop, deterministic and reproducible |
| **agentic depth** | closes the project's largest gap: autonomous handling of a rejection |
| UX | the customer watches the agent *fail and recover* — the clearest possible demonstration of a leash |
| uniqueness | most teams will show an agent that succeeds; showing one that is **refused, adapts, and succeeds on the merits** is the memorable version |
| market | this is the actual product shape of agentic commerce |

### The security design, derived from the measurement in the review

**Invariant (new): NO POLICY EXTRACTION BEYOND THE DECISION ITSELF.**
*The agent-facing projection of a decision contains the decision and the class of
constraint that failed, and no numeric policy value, no remaining budget, and no
evidence string.*

Rationale, evidence-backed: the ALLOW/BLOCK oracle already leaks ~1 bit per probe and
costs the agent real money (CHF 531 to recover a ceiling to CHF 0.24). The customer
payload would leak the whole policy in **0** probes. The mechanism's entire security
content is keeping the agent on the 12-probe side of that line.

### Attacking the design before building it

| attack on the design | answer |
| --- | --- |
| The adapt loop lets the agent binary-search the ceiling | It already can, and must spend real money to do it. The loop changes the *cost* not at all: each revision is one probe, exactly as today. |
| Naming the failing constraint class leaks more than a bare BLOCK | It leaks *which* rule, not its value. The agent already learns this by varying one dimension at a time — at the same one-probe cost. **No extra bits.** |
| The agent could loop forever, extracting cheaply | Cap the revisions. Each attempt is a recorded decision, so unbounded probing is visible in the audit trail. |
| The agent adapts into something the customer did not want | It must satisfy the *same* rules; a revision that passes does so **on the merits**. No new authority is created — the loop cannot approve anything the wallet would not already approve. |
| Building an agent-facing API accidentally reuses the customer payload | The exact failure the review names. Enforced by a test that greps the agent projection for numerics and evidence. |
| The agent is an LLM and becomes a dependency | **It is not.** Deterministic strategy (drop the most expensive line). `technical_details.md` requires predictable behaviour when a model is unavailable. |

### Scope

* `research/shopping_agent.py` — the agent. **Research, not runtime**, so the wallet
  cannot depend on it (the existing runtime-boundary test enforces this).
* A small `agent_view()` projection next to the decision, plus the leak invariant and
  its tests.
* A demo endpoint that runs the loop.

### What would make me abandon it

If the leak test cannot be made to pass without crippling the customer surface, or if
the loop turns out to create authority rather than consume it. Both are checked before
the demo wiring.

## Success criteria

* Official replay unchanged at 45 · 19/2/24.
* A named test fails if the agent projection ever carries a policy number.
* The agent demonstrably recovers from a BLOCK without being told the limit.
* No new runtime dependency; the wallet runs identically with the agent absent.

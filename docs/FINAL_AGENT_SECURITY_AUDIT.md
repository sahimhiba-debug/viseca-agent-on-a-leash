# Final agent security audit

Exactly what the agent can see, and what it can do with it.

Updated after the planner was rebuilt around a tool, an objective function and a
search. That added two attack surfaces the earlier version could not have covered,
because the agent had neither: a **shop** it must treat as untrusted input, and a
**memory** whose contents were each paid for with one of the customer's refusals.

---

## 1. The property we claim, stated narrowly

We do **not** claim ALLOW/BLOCK leaks nothing. It demonstrably leaks about one bit per
purchase: an agent recovers a secret CHF 137 ceiling to within CHF 0.24 in **twelve
probes**, at a cost of **CHF 531.49 in real purchases it must keep**.

The claim is narrower and testable:

> **The agent-facing interface provides no additional numerical policy information
> beyond the decision signal and a safe constraint class.**

Equivalently: the oracle stays at ~1 bit per purchase and never becomes 1 query.

## 2. The reasoning surface — every field the agent can reach

| field | source | visible to agent | why | reveals policy? | enables bypass? | safe |
| --- | --- | --- | --- | --- | --- | --- |
| `decision` | wallet | **yes** | the agent must know if it may proceed | ~1 bit | no | **yes** |
| `blocked_by` (class) | wallet | **yes** | tells it *which dimension* to change | direction only, no value | no | **yes** |
| `awaiting_customer` | wallet | **yes** | so it waits instead of retrying | no | no | **yes** |
| `authorization_id` | wallet | **yes** | correlates its own attempts | no | no | **yes** |
| rule `value` | mandate | **no** | would collapse 12 probes to 0 | **total** | no | blocked |
| `projected N-day spend` | engine evidence | **no** | remaining budget is the same leak | **total** | no | blocked |
| `customer_message` | engine | **no** | names amounts and merchants | high | no | blocked |
| `evidence[]` | engine | **no** | internal evaluation dump | **total** | no | blocked |
| `policy_verdict` / `security_verdict` | engine | **no** | would separate the two oracles | doubles bandwidth | no | blocked |
| `reason_codes` | engine | **no** | dotted rule field names | field names | no | blocked |
| basket / amount it sent | agent itself | yes | it authored them | no | no | yes |
| HTTP status | transport | 200 on every decision | a distinct status per outcome would be a second channel | no | no | yes |
| error messages | transport | validation errors only | never a decision | no | no | yes |

**Enforced, not asserted:** `test_agent_view_leaks_no_policy_values` searches the
projection for every policy figure, **any decimal at all**, any dotted rule field, and
every evidence string, across five decision shapes. Mutated twice — adding policy
values to the projection, and returning the whole decision object — both killed.

### The I39 lesson, applied

A representation safe on first decision can become unsafe when **re-presented
elsewhere**. That is exactly how `_recorded_message` leaked raw reason codes to
customers through `GET /api/runs/{id}` after `customer_message` had been cleaned.

So all agent-facing paths were checked, not just the primary one:

* `POST /api/agent/propose` — returns `agent_view` verbatim. ✓
* `GET /api/agent/sessions/{id}` — **customer-facing on purpose**, and richer. It is
  not reachable by the agent's protocol and exists to show the two audiences side by
  side in the demo.
* No other route returns an agent projection.

## 3. Attacks on the loop

| attack | outcome |
| --- | --- |
| **threshold probing / binary search** | possible, and **priced**: ~12 probes, CHF 531 in kept purchases. Irreducible; documented, not denied |
| **decimal search** | same oracle, same price per bit |
| **distinguishing a period breach from an over-limit order** | **blocked** — both read `amount`. Distinguishing them would double bandwidth per purchase |
| **learning *why* a human was asked** | **blocked** — `awaiting_customer` only |
| **status-code / error-message side channel** | none: every decision is HTTP 200 |
| **customer-vs-agent payload confusion** | the customer route is a different endpoint; the agent's protocol never returns it |
| **step-up laundering** (retry past a REVIEW) | **blocked** — the agent stops; asserted |
| **repeating a rejected basket to probe cheaply** | **bounded** by `MAX_REVISIONS`; every attempt is a recorded decision an auditor can count |
| **malicious planner seeking an approval** | **no approval, no money** — five hostile planners tested |
| **a hostile SHOP quoting a refund as a purchase** | the wallet refuses any non-positive amount, so no money moves — but a CHF -1000 offer was enough to make the search propose it, spending one of the customer's four attempts, and a catalogue of them would spend all four. The agent now checks that what its tool returns is plausible |
| **a hostile SHOP large enough to stall the agent** | **bounded** — the search was linear in merchants (1,000 took 1.6s against an 8s deadline) and is now capped at 50 shops chosen by cheapest entry price, so the cap does not depend on the order a hostile catalogue returns. 5,000 shops: 0.27s |
| **a SHOP that changes on every call** | the agent may fail; it may not loop. Termination is bounded by `MAX_REVISIONS` regardless of what the tool does |
| **belief poisoning through crafted refusals** | **impossible by construction** — the believed ceiling only ever falls and a ruled-out shop is never reinstated, so no sequence of refusals brings the agent to think it may spend *more*. Tested as a property over adversarial orderings |
| **shopping its way out of a security review** | **found as a regression in this phase and fixed.** The search would answer a `duplicate` or `session` flag with a different basket — an agent responding to "you look like a runaway" by rephrasing itself until the wallet stops noticing. Constraints on the PURCHASE are shoppable; constraints on the AGENT halt unconditionally, even when a valid alternative exists |
| duplicate manipulation, merchant substitution, quantity, timestamps, repeated ids, cross-run | unchanged by this phase; covered by the existing corpus (133/133) and matrix (17/17) |

## 4. Residual leakage, stated plainly

1. **The decision oracle is irreducible.** Any system that answers yes/no is one. A
   patient agent learns roughly one bit per purchase and pays for each.
2. **Constraint class adds direction, not magnitude.** It tells the agent *which* knob,
   never *how far*. It costs the same one probe per dimension either way.
3. **Convergence is visible** — but this agent does not converge on the limit.
   The old repair ladder aimed high and walked down (324 → 229 → 169 → 119), which
   told an observer the ceiling lay in (119, 169]. The search-based agent walks the
   other way: the objective minimises price within a coverage tier, so it settles
   **CHF 7.50 against a hidden ceiling of CHF 137, on its first proposal**, in a shop
   with 399 price points. Fewer refusals is also strictly fewer bits of oracle signal
   spent — the old ladder needed six to reach the same basket and did not finish
   inside the shipped four-revision budget at all. How far below the limit it lands
   depends on what the shop stocks, and we claim no more than that.

4. **The customer's own instruction contains the limit.** The errand is the
   customer's sentence, and that sentence says "CHF 120". The *wallet* never tells
   the agent a rule value, and the shipped planner never reads the instruction at
   all — it uses the category and how many lines count as the errand done, and the
   number sits unread in the same struct. But a **model** planner reads it straight
   out of the prompt. So "the wallet never tells it a policy value" is provable and
   "the agent has never seen the limit" is not. An earlier version of the test
   asserting prompt hygiene sliced that line out of its own assertion; it now asserts
   the leak explicitly.

## 5. Stop conditions

| condition | status |
| --- | --- |
| no unresolved HIGH security finding | met |
| no customer-facing internal diagnostic leak | met — including the re-presentation path |
| no agent-facing numerical policy leak | met, mutated |
| no policy bypass | met — `test_NO_POLICY_BYPASS`, plus five hostile planners |
| model failure cannot compromise authorization | met — raises, garbage, empty, hallucinated, greedy, and now five model behaviours across a real model-planner seam (`test_model_planner_seam`): no model, however wrong, obtained an approval its mandate forbids |
| a hostile tool cannot compromise authorization | met — implausible offers, phantom goods, catalogue flooding, non-stationary shops |
| the agent's beliefs cannot be driven toward permissiveness | met — monotone by construction, tested over adversarial refusal orderings |

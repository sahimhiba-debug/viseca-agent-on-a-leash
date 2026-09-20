# Final agent security audit

Phases 5 and 6: exactly what the agent can see, and what it can do with it.

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
| duplicate manipulation, merchant substitution, quantity, timestamps, repeated ids, cross-run | unchanged by this phase; covered by the existing corpus (133/133) and matrix (17/17) |

## 4. Residual leakage, stated plainly

1. **The decision oracle is irreducible.** Any system that answers yes/no is one. A
   patient agent learns roughly one bit per purchase and pays for each.
2. **Constraint class adds direction, not magnitude.** It tells the agent *which* knob,
   never *how far*. It costs the same one probe per dimension either way.
3. **Convergence is visible.** Watching a basket fall 324 → 229 → 169 → 119 tells an
   observer the ceiling lies in (119, 169]. That is inherent to adaptation; the agent
   still never receives the number, and two different secret ceilings produce identical
   proposals until the wallet's own answers diverge.

## 5. Stop conditions

| condition | status |
| --- | --- |
| no unresolved HIGH security finding | met |
| no customer-facing internal diagnostic leak | met — including the re-presentation path |
| no agent-facing numerical policy leak | met, mutated |
| no policy bypass | met — `test_NO_POLICY_BYPASS`, plus five hostile planners |
| model failure cannot compromise authorization | met — raises, garbage, empty, hallucinated, greedy |

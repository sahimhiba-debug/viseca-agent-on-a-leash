# Information boundary audit

Every value crossing every boundary, re-derived by calling each route and searching
the bytes. `AGENT_VISIBLE_DATA.md` holds the field-level table; this page is the
crossings and the attacks.

---

## The claim, stated narrowly

The demo API has **no authentication**, so this is not a claim that an agent cannot
*reach* customer data. It is the narrower, testable claim:

> Nothing the agent is **given**, on any agent-facing route, contains a policy
> value, an evidence string, a verdict, or the identifier of the customer view.

## Crossings

| crossing | carries | policy values | attacked |
| --- | --- | --- | --- |
| **customer → wallet** | instruction text, step-up answer, revocation | n/a — they own the policy | a caller cannot write the customer's *message* or stamp a customer-attributed audit entry |
| **agent → wallet** | `session_id`, `lines[]` | **no** — schema has no instruction field | negative/zero/huge prices, 2,000 lines, category lies, missing fields, control characters, mixed merchants, smuggled instructions |
| **wallet → agent** | four fields only | **no** — no decimal at all | every forbidden field searched for by name; HTTP 200 on every decision so status is not a channel |
| **merchant → wallet** | item text (return window, size, finality) | n/a | prompt injection; extraction is one whitelisted regex per fact, NFKC-normalised; can only *narrow* |
| **wallet → UI** | full decisions, both verdicts, evidence | yes, deliberately | the customer view is customer-namespaced and keyed on a server-minted `view_id` |
| **wallet → customer** | 15 distinct plain-English messages | yes, deliberately | all 15 searched: **zero** internals, no reason codes, no dotted rule fields |

## What the agent receives

Exactly four fields: `decision`, `blocked_by`, `awaiting_customer`,
`authorization_id`. `/api/agent/` holds **one route**, with a test that fails if a
second appears — because a second route is precisely how the last leak happened.

## Secondary and re-presented surfaces

The I39 lesson is that a representation safe on first decision can become unsafe
when re-presented elsewhere. This function has now rotted **three times**:

1. raw reason codes to a customer (`"Declined: hard_rule_failed:..."`)
2. a pending step-up describing itself as **"Approved"**
3. a revoked run still saying **"Waiting for you"** — the page overrode it with its
   own copy, so the *screen* was right and the record was wrong

Every re-presenting surface is now enumerated and checked, and `_recorded_message`
is the first place to look if anything else surfaces.

## The leak that was live

`GET /api/agent/sessions/{session_id}` served the **customer** view — the mandate
with `hard_rules[].value = 120`, every evidence string, both verdicts — from the
agent's own namespace, keyed on the `session_id` **the agent chooses and sends on
every proposal**. One GET, zero probes. The published "twelve probes and CHF 531"
analysis was bypassable by an agent that simply asked.

Now `GET /api/customer/sessions/{view_id}`, under an id minted server-side that
appears in no agent-facing response. Three mutants — route back under `/api/agent/`,
view id in the response, rule values in the response — all killed.

## Residual, stated plainly

1. **The decision oracle is irreducible.** ~1 bit per purchase, priced at about
   twelve probes and CHF 531 to recover a CHF 137 ceiling.
2. **Constraint class adds direction, not magnitude.**
3. **This agent walks away from the limit.** CHF 7.50 against a hidden CHF 137 on
   its first proposal — a property of *our* planner, not of the interface.
4. **Timing carries no usable signal at this scale.** Medians 0.85–0.87 ms across
   all four outcomes, 60 calls each. Measured, not a constant-time guarantee: the
   engine short-circuits, so a first-rule failure genuinely does less work.
5. **The customer's own instruction contains the limit.** The wallet never tells the
   agent a rule value and the shipped planner never reads the instruction — but the
   number is in the agent's possession, and a *model* planner would read it from the
   prompt.
6. **No authentication.** Bounds every claim on this page.

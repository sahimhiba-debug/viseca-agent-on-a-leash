# Everything the agent can see

An information-boundary audit of every surface, not just the primary one. The
previous version of this audit said it would not assume the primary endpoint was
sufficient, and then assumed it. This one was produced by calling each route and
searching the bytes that came back.

---

## The finding that prompted this rewrite

`GET /api/agent/sessions/{session_id}` served the **customer** view: the mandate
including `hard_rules[].value = 120`, every evidence string, both verdicts, and the
customer message. It sat in the agent's own namespace and was keyed on the
`session_id` **that the agent chooses and sends on every proposal**.

So an agent could read the entire policy in **one GET, zero probes**. The published
analysis — that recovering a CHF 137 ceiling costs about twelve probes and CHF 531
in purchases the agent must keep — was bypassable by an agent that simply asked.
Nothing in the UI or the tests referenced the route; it existed only to be described
in a document claiming it was "not reachable by the agent's protocol".

It now lives at `GET /api/customer/sessions/{view_id}` under an identifier minted
server-side that appears in no agent-facing response.

## What is claimed, and what is not

The demo API has **no authentication**. This is therefore *not* a claim that an agent
cannot reach customer data — with the view id it plainly can, and a real deployment
would authenticate the customer surface.

The claim is narrower and is what the tests check:

> **Nothing the agent is given, on any agent-facing route, contains a policy value,
> an evidence string, a verdict, or the identifier of the customer view.**

Enforced by `tests/security/test_agent_information_boundary.py`. Mutated three ways
— moving the customer view back under `/api/agent/`, returning the view id in the
proposal response, returning the rule values — all three killed.

---

## The agent's entire surface

`POST /api/agent/propose` is the only route under `/api/agent/`, and a test fails if
a second one appears. It returns exactly four fields.

| field | source | visible | purpose | policy info? | security info? | usable for probing? | safe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `decision` | wallet | **yes** | the agent must know whether it may proceed | ~1 bit | ~1 bit | **yes, irreducibly** | yes |
| `blocked_by` | wallet | **yes** | which *dimension* to change | direction, no magnitude | class only | one probe per dimension | yes |
| `awaiting_customer` | wallet | **yes** | so it waits instead of retrying | no | no | no | yes |
| `authorization_id` | wallet | **yes** | correlates its own attempts | no | no | no | yes |

## Everything withheld

| field | where it lives | why the agent must not have it |
| --- | --- | --- |
| `hard_rules[].value` | mandate | collapses twelve probes to zero. **This is what leaked.** |
| `view_id` | session | the key to everything in this table |
| `evidence[]`, `policy_evidence`, `safety_evidence` | engine | an internal evaluation dump |
| `policy_verdict` / `security_verdict` separately | engine | separating the two oracles doubles bandwidth per purchase |
| `reason_codes` | engine | dotted rule field names, i.e. the policy's shape |
| `customer_message` | engine | names amounts, merchants and thresholds |
| projected N-day spend / remaining budget | engine | the same leak as the value itself |
| `billing_amount_chf` echoed back | engine | would confirm what the wallet scored, not what the agent sent |

## Channels other than the payload

| channel | behaviour | why |
| --- | --- | --- |
| HTTP status | **200 for every decision** — allow, block and review alike | a status per outcome would be a second oracle |
| HTTP status, malformed request | 400, with no policy content in the body | tested |
| error messages | validation only, never a decision | tested |
| timing | **measured**: median 0.85–0.87 ms across allow / merchant / order_terms / amount, 60 calls each — a ~2% spread, inside noise | no usable signal at this scale; not a constant-time guarantee, see *Residual* |
| `authorization_id` shape | `{session}_{n}`, chosen by the agent and a counter | carries nothing the agent did not supply |

## What the agent legitimately holds anyway

| thing | why it is not a leak |
| --- | --- |
| the basket and amount it proposed | it authored them |
| its own history of refusals | it lived through them; this is the oracle, priced below |
| **the customer's instruction, which contains "CHF 120"** | the customer handed it the errand. The *wallet* never tells it a rule value, and the shipped planner never reads the instruction at all — it uses the category and how many lines count as the errand done. A **model** planner would read it straight from the prompt, which is one more reason the model is not the one we ship. |

## Re-presented and secondary surfaces

The I39 lesson is that a representation safe on first decision can become unsafe when
re-presented elsewhere. Every surface that re-presents a decision was checked:

| route | audience | carries policy values | notes |
| --- | --- | --- | --- |
| `POST /api/agent/propose` | agent | **no** | four fields, tested and mutated |
| `GET /api/customer/sessions` | customer | no | lists view ids only |
| `GET /api/customer/sessions/{view_id}` | customer | **yes, deliberately** | moved off the agent namespace in this pass |
| `GET /api/runs/{id}` | customer | yes, deliberately | produced two defects of its own this pass — a pending step-up describing itself as approved, and a customer's own decline reported as "a check failed" |
| `GET /api/runs/{id}/audit` | customer | yes, deliberately | a projection rebuilt from the ledger |
| `GET /api/attacks` | jury | yes | demonstrations, not an agent surface |

## Residual leakage, stated plainly

1. **The decision oracle is irreducible.** Any system answering yes/no is one. A
   patient agent learns roughly one bit per purchase and pays for each: about twelve
   probes and CHF 531 in kept purchases to recover a CHF 137 ceiling.
2. **Constraint class adds direction, not magnitude.** It says *which* knob, never
   *how far*.
3. **This agent walks away from the limit, not toward it.** The objective minimises
   price within a coverage tier, so it settles CHF 7.50 against a hidden CHF 137 on
   its first proposal. That is a property of *our* planner, not of the interface — a
   different planner behind the same seam could probe.
4. **Timing carries no usable signal at this scale, but is not guaranteed.**
   Measured over 60 calls per outcome, the medians are 0.85, 0.85, 0.86 and 0.87 ms
   for `amount`, `merchant`, `order_terms` and allow — a spread of about 2%, inside
   run-to-run noise. That is a measurement, not a constant-time implementation: the
   engine short-circuits on `fail > unknown > pass`, so a decision that fails on the
   first rule genuinely does less work than one that passes every rule. We claim no
   more than "we looked, and at this scale it is not separable".
5. **No authentication anywhere.** Stated once more because it bounds every claim on
   this page.

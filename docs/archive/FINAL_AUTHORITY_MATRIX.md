# Authority matrix

Who may control what. Derived by enumerating every route and every request-model
field from the code, then attacking each forbidden transition.

Actors: **customer**, **agent**, **merchant**, **browser**, **platform**, **wallet**.

---

## The recurring defect shape

Four instances now, all the same: **a caller-controlled field the server accepts**.

| field | state when found | damage |
| --- | --- | --- |
| `instruction` on `POST /api/agent/propose` | live | an agent authored the policy it was judged against: CHF 500 refused under the customer's mandate, **approved** when the agent supplied "CHF 900" |
| `confirmed_at` on a run | live | a caller stamped an audit entry attributed to `actor="customer"` with `1999-01-01` |
| `customer_message` on a step-up answer | **dead** | none — nothing read it, which is why it had to go, not why it was safe |
| `mandate=` on `resolve_authorization` | latent | omitting it silently disables the rolling-window re-check. Every runtime caller passes it; now AST-enforced |

A field nothing reads is not harmless. It is a loaded gun with the safety on.

## The matrix

| thing | customer | agent | merchant | browser | platform | wallet |
| --- | --- | --- | --- | --- | --- | --- |
| **mandate text** | **owns** (`POST /api/customer/mandates`) | **no** — removed from its schema | no | relays the customer's | no | compiles, never authors |
| **hard rules** | owns, via the text | no | no | displays | no | derives; tighten-only afterwards |
| **uncertainty policy** | owns | no | no | displays | no | applies |
| **which basket is proposed** | no | **owns** | no | relays | no | never proposes |
| **the merchant of a basket** | no | **owns** (one shop per basket, or 400) | no | relays | no | evaluates |
| **item price / category / name** | no | claims it | **is the source** | relays | supplies in the real event | cannot verify |
| **return window, size, finality** | no | relays | **owns the claim** | displays | relays | extracts, can only narrow |
| **merchant familiarity** | no | **no** — discovers only by refusal | no | no | supplies history | **owns**, from the card's history |
| **the decision** | no | no | no | no | no | **owns, exclusively** |
| **step-up answer** | **owns** | no | no | relays | no | records; re-checks revocation + window |
| **revocation** | **owns** | no | no | relays | no | enforces run-wide, incl. records not yet written |
| **purchase timestamp** | no | **no** (attacked) | no | no | **owns** (simulated) | uses for windows |
| **`resolved_at`** | no | no | no | **no** (attacked) | no | **owns** (real clock) |
| **`confirmed_at`** | no | no | no | **no** — removed | no | **owns** (server-stamped) |
| **revocation time** | no | no | no | **no** (attacked) | no | **owns** |
| **`view_id`** | holds it | **never receives it** | no | holds it | no | mints it |
| **rolling spend counter** | no | **cannot reset within a session** | no | no | no | **owns**, per run |

## Forbidden transitions, attacked

| attack | result | test |
| --- | --- | --- |
| agent names its own policy | schema has no field; built-in mandate used | `test_agent_cannot_author_policy` |
| agent replaces a running session's mandate | **409** | same |
| agent resolves its own step-up via `/api/runs/` | **404** — separate namespaces | `test_actor_authority` |
| agent revokes or re-runs its own session | **404** | same |
| caller writes the customer-facing message | field removed; message unchanged | same |
| caller stamps a customer-attributed audit entry | server-stamped | same |
| caller fabricates purchase / resolve / revoke times | all rejected | `FINAL_STATE_MACHINE_AUDIT.md` |
| agent sends a basket spanning two shops | **400** | `test_ui_agent_parity` |
| agent omits a required line field | **400**, was a 500 | `test_agent_cannot_author_policy` |
| agent quotes a negative or zero price | refused by the agent's own tool check; wallet refuses non-positive amounts anyway | `test_agent_tool_boundary` |

## What no actor can do

- **Widen a mandate.** Tighten-only, and no caller can author one.
- **Reach a decision the rules forbid.** The engine is the only decision-maker.
- **Manufacture a historical fact.** Every audit timestamp is server- or
  platform-owned and labelled `real` or `simulated` with its actor.
- **Authorise anything after revocation**, including a purchase that was waiting.

## What is deliberately unenforced

**No authentication anywhere.** This bounds every row above: the matrix describes
which actor *owns* each field and what the server accepts, not who can reach the
socket. A real deployment authenticates the customer surface. Stated here rather
than implied away.

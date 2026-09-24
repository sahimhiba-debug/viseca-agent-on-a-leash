# R&D Track J: Principal / agent / execution-context identity

## The question

Should the wallet bind authority to the customer alone, or also to a specific
agent identity, session, or device -- and does the official Viseca data model
support any of that?

## What the official schema actually provides

Checked directly against `data/official/schemas/authorization_event.schema.json`:
`authorization.initiator_type` is a `const: "agent"` -- a fixed literal, not an
identifier. There is no `agent_id`, no per-agent credential, and no session
token anywhere in the official event schema. The only identity-adjacent,
per-event fields are `authorization.customer_device_id` (an opaque device
handle) and the mandate's own `customer_id`/`card_id`/`profile_id` (assigned by
the platform at run start, not chosen by the agent).

## What industry research suggests, and why it doesn't transfer here

Visa's Trusted Agent Protocol and Mastercard's Agentic Tokens both bind
authority partly to a **verified agent identity** -- a real cryptographic
credential distinguishing "ChatGPT acting for user X" from "a different agent
acting for user X." This requires an agent registration/attestation
infrastructure (a relying party, a credentialing authority) that does not exist,
and cannot be verified against anything, inside this challenge's sandbox. Adding
a locally-invented `agent_id` field to the event model would violate this
project's own "preserve compatibility with the official API lifecycle" rule --
it would be a field the platform never sends and could never check, i.e., a
locally-fabricated trust signal masquerading as a verified one, which is exactly
the failure mode `SECURITY_MODEL.md` exists to prevent.

## What IS already implemented, and covers most of the practical need

`customer_device_id` and `recent_attempt_count_10m` (both real, platform-supplied
fields) already drive `RunState.session_signals` -- the closest available proxy
for "is this still the same execution context the customer was actually using."
This is EXECUTION CONTEXT identity, at the granularity the official data
actually provides, already implemented and tested since the first build, refined
in the second audit pass (I19: unknown vs. false device history distinguished).

## What a fuller principal/agent/context model would require, and why it's deferred

A genuine "delegation chain" (principal delegates to agent, agent operates
within an execution context, and each layer's authority is independently
bounded and revocable) is a real, well-motivated concept -- it is what AP2's
three-mandate chain and Mastercard's per-agent Agentic Tokens are actually
building towards at the ecosystem level. Building a LOCAL, single-issuer
imitation of it would mean inventing the very identity infrastructure (agent
registration, agent-level revocation, agent-level spending history) that makes
those ecosystem-scale designs meaningful, for a synthetic sandbox with exactly
one initiator type and no agent registry to speak of.

## Recommendation: **DEFER / REJECT for new infrastructure; KEEP the existing device/session proxy**

No new "agent identity" concept should be added -- there is nothing in the
official schema to bind it to, and inventing one would be unverifiable identity
theatre. The existing device-ID-based session-integrity heuristic already covers
the practical, in-scope version of "is this still the right execution context,"
and is the appropriate resolution given this challenge's actual data model. This
is recorded as explicit future work for a multi-agent, multi-issuer deployment
this hackathon prototype does not need to build.

# Competitor simulation

Strategic scenario analysis, not prediction. Fifteen plausible strong solutions, and
the question that matters: **what would all of them probably miss?**

| | architecture | likely demo | likely differentiator | likely blind spot |
| --- | --- | --- | --- | --- |
| A | deterministic policy engine | blocks an over-limit purchase | clean rules | backward-looking window |
| B | LLM intent classifier + rules | "it understands what you meant" | NL depth | non-determinism on stage; same window |
| C | capability / attenuating token | tighten-only delegation | macaroon-style chain | crowded in 2026; same window |
| D | payment-authorization capability | single-use authority | execution binding | same window |
| E | prompt-injection defence | merchant text tries to override | sanitisation | treats text as the whole threat |
| F | cryptographic delegation | signed mandates | unforgeable | the challenge has no PKI to anchor to |
| G | risk scoring | "this looks anomalous" | ML | no training data; unfalsifiable |
| H | transaction simulation | dry-run a purchase | sandbox | no execution environment exists |
| I | intent-to-transaction diff | side-by-side comparison | very demoable | explanation, not enforcement |
| J | human-in-the-loop approval | step-up flow | UX | **defers a decision and then counts it at its original time** |
| K | agent identity / provenance | "which agent is this?" | attestation | explicitly excluded by the challenge |
| L | MCP-based security layer | tool-call gating | integration | wrong layer for a payment bound |
| M | agentic commerce protocol (AP2-style) | mandate types | standards alignment | same window |
| N | behavioural anomaly detection | velocity spike | monitoring | baseline data absent |
| O | transaction firewall | rule DSL | expressiveness | same window |

## What they would all probably miss

Almost every architecture above needs two things the challenge explicitly requires:

1. **a rolling spending window** — the customer's only real economic control; and
2. **a step-up that pauses a purchase** without counting it as approved.

The specification states both plainly:

> *"Count final approvals when enforcing spending limits. A purchase waiting for a
> human answer is not yet approved."*
> *"Use simulated purchase time for spending windows, and the real clock for response
> deadlines."*

Implement both correctly and the natural window check — *sum the last N days, add this
one* — **is wrong**. A deferred purchase re-enters the ledger at its original timestamp,
behind decisions already made against a window that could not see it.

**Following the specification correctly produces the violation.** Avoiding it needs a
third insight the specification does not state: a purchase must fit every window that
*contains* it, not the window that *ends* at it.

Teams J and A–O all inherit it. Teams that skip either rolling caps or step-up avoid it
by not implementing the feature.

## Why this is defensible rather than lucky

We did not find it by inspection. We found it by asking a falsifiable question —
*same transactions, same rules, different order: can the security meaning differ?* —
and measuring. 367 of 400 random arrival orders breach the cap.

The test is reproducible by anyone. The finding is not an opinion.

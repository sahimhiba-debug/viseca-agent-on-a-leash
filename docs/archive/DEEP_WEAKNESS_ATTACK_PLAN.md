# Deep weakness attack plan

Pre-registered before any experiment, so that a negative result cannot be reframed
afterwards as the thing I set out to show.

**The thesis under test:** *"A delegation is bounded only where an authoritative
record exists at the same scope as the bound."*

If that thesis is right, then every unbounded exposure in this system should trace to
a missing authoritative record, and every bounded one to a present record. The
campaign is an attempt to find a case where it is **wrong in either direction**: an
exposure that persists despite an adequate record, or a bound that holds without one.

**The adversary** is an autonomous shopping agent maximising economic value while
appearing compliant. It cannot forge platform-supplied fields; it can choose baskets,
timing, ordering, merchants, substitutions, retries, and how it uses step-up.

---

## Pre-registered falsifiers

I commit to these before running anything. If a falsifier fires, the corresponding
conclusion is wrong regardless of how the rest of the campaign goes.

| # | falsifier | what it would prove |
| --- | --- | --- |
| **F1** | An authoritative cross-run record is reachable in the official protocol | the "cross-run is a protocol limit" conclusion is **wrong**, and the refusal built on it is overstated |
| **F2** | The agent can induce a run boundary within the judged protocol | cross-run multiplication becomes agent-reachable, raising it from documented limitation to real vulnerability |
| **F3** | A step-up can be resolved in a way that binds to different economics than were shown | the human-consent invariant (I31) is wrong |
| **F4** | A restrictive instruction is silently weakened or incorrectly strengthened | the intent-fidelity conclusion ("no silent weakening") is wrong |
| **F5** | A purchase can be driven to ALLOW by manipulating only a non-authoritative fact | the evidence model is wrong |
| **F6** | The official corpus shows friction on purchases clearly inside the delegation | the autonomy claim is wrong |

## Attack 1 — cross-run / scope escape

**What I already know, and what is actually in doubt.** The exposure (10 runs × ~CHF 300) is reproduced and documented. What is *not* established is the claim used to justify accepting it: that no authoritative cross-run record exists.

Two candidates the previous campaigns did not pursue:

* `GET /v1/authorizations` — "Lists pending and final runtime authorizations". No run parameter in its signature.
* `GET /v1/events?since=0` — a cursored, append-only feed, which is inherently global.

Our own `reconcile_run` docstring says the listing *"isn't documented well enough to trust a reconstructed amount/timestamp"* — which is a **choice under uncertainty**, not an impossibility. The refusals document states the stronger claim. That gap is the first thing to test.

**Method.** (a) Determine from the specification and the offline pack whether either endpoint is run-scoped or team-scoped. (b) Determine who can create runs. (c) Build the strongest compliant multi-run trace and measure it. (d) Only then ask whether the *existing* decision ledger could carry the bound, before considering any new object.

**Outcome categories in play:** DOCUMENTED LIMITATION, SAFE UNDER EXPLICIT PROTOCOL ASSUMPTION, or REAL VULNERABILITY → FIX if F1 or F2 fires.

## Attack 2 — step-up identity

**Method.** Enumerate what the protocol can and cannot guarantee about *who* resolves a step-up, then attack twelve resolution variants against the engine directly (not the UI): wrong human, stale, post-revocation, cross-authorization, mismatched amount/basket, post-expiry, replayed, doubled, copied between authorizations, pre-existing, post-tightening.

**Discipline.** UI authentication is not backend identity and will not be counted as a protection. Each variant gets exactly one of SAFE / OUT OF SCOPE / REAL VULNERABILITY.

## Attack 3 — semantic intent compiler

**Method.** A corpus of **≥200 instructions across the 15 requested classes**, written by enumerating how people speak rather than from the compiler's patterns. Every phrase classified into six outcomes, with **(3) silently weakened** and **(4) incorrectly strengthened** counted separately and treated as the only dangerous ones.

Then multi-sentence precedence: does a later clause override, extend, or get dropped?

**Pre-registered:** I expect a substantial "correctly identified as unsupported" bucket. That is a *safe* outcome, not a failure, and I will not present it as coverage. A deterministic parser cannot understand anaphora ("same as last time") — the question is whether it *says so* rather than guesses.

## Attack 4 — evidence provenance

**Method.** Build the provenance matrix for every fact the engine consumes: source, authority, mutability, who controls it, whether the wallet verifies it, and — the column that matters — **whether it can cause an ALLOW**.

Then the single decisive question: *can an attacker cause an ALLOW by manipulating only a non-authoritative fact?* Reproduce any yes.

## Attack 5 — autonomy vs friction

**Method.** Measure ALLOW/REVIEW/BLOCK on the official corpus and on a generated legitimate-behaviour corpus. Attribute every REVIEW to a cause: ambiguity, unverifiable evidence, security check, or policy violation. Then look for both failure directions — **false friction** (interrupting a purchase clearly inside the delegation) and **false autonomy** (allowing what a reasonable reading would have escalated).

**Discipline.** Fewer interventions is not the objective and will not be reported as an improvement on its own.

## Second-order attacks

≥20 multi-dimensional traces over the seven named interactions (cross-run × fulfilment, compiler ambiguity × step-up, merchant evidence × verdict split, unsupported intent × cross-run, revocation × pending step-up × new run, merchant facts × repetition, human approval × rolling limits). The attacker optimises over the lifecycle, not the transaction.

## What I will not count

Attacks requiring forged platform fields, impossible protocol states, changes to the benchmark, or UI-only issues with no security or judged-UX consequence.

## Discipline for any proposed fix

Before implementing: invariant, attack, root cause, proposed fix, **and a new attack against the fix**. No new security object until the existing model is *proven* unable to express the invariant — the brief's constraint, and the one most likely to be violated under time pressure.

## Honest prior

I expect Attack 1 to produce the campaign's real finding, because it is the only one where a previous conclusion rests on an unverified claim about the protocol rather than on a measurement. I expect Attacks 2 and 4 to be mostly SAFE or OUT OF SCOPE, and Attack 3 to produce a large unsupported bucket that is safe but product-limiting. Recording this so that confirmation of it counts for less than a surprise.

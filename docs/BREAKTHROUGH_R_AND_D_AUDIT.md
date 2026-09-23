# Breakthrough R&D audit

<!-- snapshot -->
> **SNAPSHOT — written 19 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

Research only. **No code was changed.** The frozen product at `f988974` is the
experimental baseline; the analysis below used throwaway scripts against it.

---

## 1. Competitive mental model

Twenty strong teams, one challenge. What they plausibly build, and what it costs us:

| likely architecture | how many teams | our position |
| --- | --- | --- |
| deterministic policy engine, limits, merchant/item rules | **most** | we have it, better tested |
| LLM intent classifier in front of rules | many | we deliberately have **no model at runtime** — a differentiator only if we say why (determinism, no failure mode on stage) |
| ALLOW / BLOCK / STEP_UP with human approval | **most** | table stakes |
| prompt-injection defence | many | table stakes; ours is narrow extractors rather than a filter, which is better but not memorable |
| revocation + audit log | most | table stakes |
| **capability / attenuating token** (macaroon-style) | **several — and this is the crowded one** | our tighten-only mandate *is* attenuation. 2026 has an IETF draft on attenuating agent tokens, DeepMind's Delegation Capability Tokens, `capmas`, and several macaroon-for-agents projects. **Anyone reaching for "capability" lands here.** Not white space. |
| risk scoring / behavioural anomaly | some | needs training data we do not have; easy to fake, hard to defend |
| agent identity / provenance | some | **the challenge explicitly removes it** ("the agent rows do not have `agent_id` … the challenge is about controlling delegated spending, not identifying a fictional AI provider") |
| formal verification | rare | expensive; unlikely to finish in 36h |
| transaction simulation / sandbox | rare | no execution environment in the official contract |
| intent-to-transaction comparison | some | we have the pieces (basket vs compiled rules) |

**Conclusion:** the obvious deep directions — capability attenuation, agent identity,
risk scoring — are respectively crowded, excluded by the challenge, or unsupported by
the data. Depth has to come from somewhere else.

## 2. Current table stakes

ALLOW/STEP_UP/BLOCK · spending limits · merchant and item restrictions · revocation ·
audit history · mobile UI · injection handling · duplicate detection · NL→rules.

## 3. Current distinctive mechanisms

| | distinctive? | visible? |
| --- | --- | --- |
| Scope model — a bound is enforceable only where authoritative state exists at the same scope | yes | no (a document) |
| Economic delegation — a rolling cap is a *rate*, not a total; 4 of 5 official mandates unbounded in total | yes | partly (Delegate tab) |
| Derived fulfilment — 6 approved purchases worth CHF 1,787 repeating a job described once | yes | no (not in the decision path) |
| **Two verdicts from one authority-tagged pass** | yes | **yes — shipped last pass** |
| Security-object falsification (8 competing models) | as method | no |

## 4. Threat-space map

`THREAT_SPACE.md`. Sixteen boundaries; fifteen have a control. **One cell is empty:
what the wallet tells the agent when it refuses.**

## 5. White-space analysis

Working through the audit's research questions, most collapse into three families:

**(i) Composition** (questions B, J, K, N, O) — individually-safe purchases, unsafe in
sequence. **Already researched to exhaustion by this project.** The answer is job
counting; it is built, measured (6 disagreements / CHF 1,787.40), and deliberately kept
out of the decision path because the job is mandate-scoped while our ledger is
run-scoped. Reopening it is an architecture change during a freeze. *Not white space —
solved ground we chose not to walk on.*

**(ii) Uncertainty and evidence** (questions F, G, H, I, T) — not all uncertainty is
alike, and not all evidence carries the same authority. **Partly built:** every check
already carries `source="customer"` or `source="safety"`, which is what produced the
verdict split. The unexploited half is *verifiability* rather than *ownership*.

**(iii) Explanation** (questions P, T, and §§11–12) — what would have made this
acceptable, and what is the smallest change. **This is the empty cell**, and it has a
security dimension nobody in the surveyed literature applies to payments.

## 6. External precedent

| concept | status | what we would NOT be inventing |
| --- | --- | --- |
| Counterfactual explanation / algorithmic recourse | **established** (Wachter et al.; Upadhyay et al. 2025) | the idea of "minimal change that flips the outcome" |
| Contrastive explanation for access control | **established** — EXTree (2026); KNOW computes *minimal sufficient policy changes* via OBDD | "why not?" for a denied authorization |
| Policy remediation / simulation | **productised** — AWS IAM access-denied troubleshooting and policy simulator, plus patents on "access control policy evaluation and remediation" | telling a principal how to get access |
| **Counterfactuals as an attack surface** | **established in ML** — DualCF model extraction; "attackers can use counterfactual explanations to optimize their attack path" | the observation that explanations leak the boundary |
| Feasibility-constrained recourse | **established** — recourse must not instruct changing immutable/protected attributes | the idea that some counterfactuals are invalid |
| Capability attenuation for agents | **crowded in 2026** — IETF `draft-niyikiza-oauth-attenuating-agent-tokens`, DeepMind Delegation Capability Tokens, `capmas`, macaroons | tighten-only delegation |
| Admission control for agent actions | **published** — Agent Control Protocol (2026) | a control layer in front of agent actions |
| AP2 / Visa TAP / Mastercard agentic tokens | industry | mandate types; agent authentication |

**What the survey did *not* find:** anyone treating *who controls the fact* as the
criterion for whether a counterfactual is safe to disclose, in an agentic-payments
setting. ML work asks whether recourse is *feasible for the user*; we would be asking
whether it is *exploitable by the agent*. Absence of evidence is not proof — stated as a
gap in the search, not as a claim of novelty.

## 7. Cross-domain research

- **Object-capability security / macaroons** — attenuation-only delegation. We already have it; 2026 made it crowded.
- **OAuth scopes** — coarse; no notion of consuming a scope.
- **Cloud IAM** — the closest analogue, and the one that already ships remediation advice. Notably, IAM tells *the principal* how to get access, in a setting where the principal is trusted. **Our principal is assumed compromised.** That inversion is the whole point.
- **Aviation / industrial control** — the concept of an *envelope* the operator may not leave, and of alarms that say which limit was approached. Aviation deliberately does **not** tell an automated system how to evade a protection.
- **Compiler theory** — error recovery suggests the minimal edit that would make a program valid. Same computation, no adversary.

The useful transfer is the inversion: **every remediation system in the survey assumes a
cooperative principal.** Agentic commerce is the first setting where the entity reading
the explanation is the one you are defending against.

## 8. Candidate concepts

| | concept | verdict |
| --- | --- | --- |
| **C1** | **Authority-gated counterfactual** — compute the minimal change that would have made a blocked purchase acceptable, and disclose it *only* when the fact is one the agent cannot simply assert | **selected** |
| C2 | Sequence-aware authorization (job counting in the decision path) | rejected — §5(i); architecture change during a freeze, scope mismatch documented |
| C3 | Uncertainty decomposition (which *kind* of uncertainty, is a human actually useful) | rejected as a separate mechanism — it is a *consequence* of C1's evidence model, and implementing both violates "one mechanism" |
| C4 | Delegation-as-resource (consume product identity, merchant class, size, returnability) | rejected — this is the fulfilment work renamed; already falsified as needing mandate-scoped state |
| C5 | Provenance graph over evidence | rejected — more machinery to answer what the `source` tag already answers |
| C6 | Counterfactual over *sequence* ("you have one performance left") | rejected — depends on C2 |

## 9. Falsification of C1

| attack on the idea | answer |
| --- | --- |
| Is it just a UI feature? | No. It re-runs the production engine over basket subsets; the engine is the oracle, so the explanation cannot disagree with the decision. But **it changes no decision** — see §20. |
| Is it just an existing rule? | No — no rule expresses "what would have to change". |
| Already in AP2 / OAuth / capability security? | No. Those attenuate authority; none explains a denial. |
| Already in IAM / fraud detection? | **The computation, yes.** The *disclosure constraint* is what is ours, and it only exists because the principal is hostile. |
| Does it need unsupported data? | No. Event + mandate + engine. |
| Second source of truth? | No. Zero new state. |
| Survives restart / concurrency? | It is a pure function; there is nothing to persist or race. |
| Can the official data support it? | **Yes, measured.** 24 blocked events: 3 have a single-line minimal repair; AU0041 has **3 rule failures cleared by removing one line**. 26 failed checks rest on verifiable facts; **7 rest on merchant claims** and must not be disclosed. |
| Does it weaken the security model? | No — but it could, if built naively, which is precisely the finding. |
| Can it be demonstrated by an attack? | Yes: a naive counterfactual engine hands the agent an evasion recipe. |

**The strongest objection, stated plainly:** C1 is an *explanation* mechanism, not an
*enforcement* one. Removing it changes no decision. We must not present it as a
security control. What is security-relevant is its **disclosure policy** — and that is a
genuine, testable invariant.

## 10. Selected concept

> **Authority-gated counterfactuals.** When the wallet refuses, it computes the minimal
> change that would have made the purchase acceptable — and it discloses that change
> only when the underlying fact is one the agent cannot simply assert.

Two classes of fact, already distinguishable in the engine:

- **Verifiable** — price (arithmetic), merchant familiarity (card history), category
  (platform catalogue), basket contents (the agent's own submission), session signals
  (our observation). Changing these means changing reality. **Safe to disclose.**
- **Claimed** — `order.return_window_days`, `item.size`, `item.name_contains`. Nothing
  but merchant free text establishes them. Changing these means asserting differently.
  **Disclosing the counterfactual is handing over an evasion recipe.**

## 11. Why it is not merely a feature

Because the *refusal to explain* is the mechanism. Any team can compute "CHF 400 would
have passed". The contribution is knowing when saying so is unsafe — and having the
evidence model that answers it. Our earlier audit already recorded, as residual risk,
that two rule fields rest entirely on attacker-controlled text. **This turns that
documented weakness into the criterion for a capability.**

## 12. Why it matters

Every remediation system surveyed assumes a cooperative principal. Agentic commerce
inverts that: the entity reading the explanation is the one you are defending against.
A wallet that explains itself perfectly to a compromised agent has built a probe
interface.

## 13. Exact security invariant

> **No counterfactual is disclosed for a check whose fact the agent or merchant can
> establish by assertion.**

Falsifiable: enumerate every rule field, ask for its counterfactual, assert that the
claimed-fact fields return a refusal and a reason rather than a target value. Second
invariant: **the counterfactual changes no decision** — the official replay must not
move, and a mutation removing the whole module must leave 45/19/2/24 intact.

## 14. Exact data required

None that we do not already have: the authorization event, the mandate snapshot, and
`evaluate_authorization`. **No new persisted state, no new endpoint, no new dependency.**

## 15. Exact architectural impact

One new pure module (research-first, in `research/`, promoted only if it earns it),
consuming the engine as an oracle. It must not import into the decision path — the
existing `test_runtime_boundary` already enforces that direction.

## 16. Exact demo

Official data, SCEN0004, deterministic:

1. **AU0041 — CHF 459, monitor + extended protection plan.** Three rules fail.
   > *"Remove the extended protection plan and this is exactly what you asked for."*
   One removal clears three failures. Verified.
2. **AU0043 — CHF 195, a digital gift voucher.** Also blocked, also multi-failure.
   > *"There is nothing to remove. This is not the thing you asked for."*
   The same computation distinguishes **contamination** from **substitution**.
3. **AU0015 — return window 7 days, customer asked for 14.**
   > *"The wallet will not tell the agent what would have satisfied this, because
   > nothing but the seller's own text establishes a return window."*

Step 3 is the sentence a judge remembers.

## 17. Exact attack

Run the counterfactual engine with the gate disabled and show it emitting
*"a return window of 14 days or more would satisfy this"* — then show the agent
resubmitting with exactly that sentence in `item_details` and passing. Then enable the
gate. **The attack is against our own feature**, which is the honest way to demonstrate
that the gate is the mechanism.

## 18. Complexity estimate

| | |
| --- | --- |
| new production LOC | 0 in the first instance (research module) |
| new research LOC | ~120 (subset search + disclosure gate) |
| new state / persistence / endpoints / dependencies | **0 / 0 / 0 / 0** |
| new tests | ~8 |
| new UI | one line on a blocked card, one refusal line |
| worst case | subset search is O(2^n) in basket lines; official baskets are ≤ 3, needs an explicit cap |

## 19. Risks

1. **It is an explanation, not enforcement.** If presented as a security control, that is
   an overclaim. It must be described as a disclosure policy.
2. **The verifiable/claimed split is a hand-maintained list.** A new rule field defaults
   to the wrong side unless classified. The test must enumerate all fields and fail on
   an unclassified one.
3. **Combinatorics.** Needs a hard cap on basket size, with an honest "not computed".
4. **It fires on 3 of 24 official blocks.** The demo depends on AU0041; the corpus is
   not rich in repairable blocks.
5. **Precedent is real.** If we call the counterfactual itself novel, an informed judge
   will correctly object.
6. **It could leak indirectly** — even a refusal tells the agent *that* the field is
   unverifiable. Mitigation: refuse uniformly, never naming which check.

## 20. What we refuse to claim

- **Not** that counterfactual explanation is novel. It is established in ML
  interpretability and in access control (EXTree, KNOW, AWS IAM remediation).
- **Not** that explanations-as-attack-surface is a new observation. It is established in
  ML (DualCF, model extraction from counterfactuals).
- **Not** that this is a security control. It changes no decision; remove it and the
  wallet behaves identically.
- **Not** that it prevents evasion. A determined agent can still probe by submitting
  variants; the gate removes a *shortcut*, it does not close the channel.
- **Not** that the verifiable/claimed classification is complete or that our list of
  unverifiable fields is exhaustive beyond the official vocabulary.
- **Not** that no competitor will build it. We found no precedent in agentic payments;
  that is a gap in the search, not proof of absence.

---

## Recommendation

Implement **C1** as a research prototype in `research/`, with the disclosure gate as the
central invariant and the self-attack (§17) as the proof. Promote it into the product UI
only if the gate holds under test.

**If review disagrees that an explanation-layer mechanism is worth the complexity, the
correct decision is to add nothing.** The product is coherent as it stands, and a weak
novelty feature is worse than none.

**Stopping here for review, as instructed.**

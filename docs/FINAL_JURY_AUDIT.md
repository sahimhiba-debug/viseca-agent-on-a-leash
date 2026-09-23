# Final jury audit

<!-- snapshot -->
> **SNAPSHOT — written 20 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

Written as five senior engineers who have seen 200 projects today, have four
minutes, and are looking for a reason to stop listening. For each question: the
strongest answer the implementation supports, the evidence, the limitation, and the
wording that would lose the room.

Nothing here claims a capability the repository does not have.

---

### A. Where is the AI?

**Answer.** Outside the money path, deliberately. The agent does the reasoning:
it searches candidate baskets against an explicit objective, learns from refusals,
and calls a tool to look at the shop. The wallet decides deterministically. The spec
requires a predictable response when the model is unavailable, so a model between a
customer and their card would break the one property it insists on.

**Evidence.** `research/shopping_agent.py` — `score()`, `best_basket()`, `Shop`.
`tests/test_runtime_boundary.py` proves the wallet never imports the agent.

**Limitation.** No language model runs anywhere in the judged path. If "AI" means
"an LLM is in the loop", we do not have one, and §D is the real answer.

**Do not say.** "AI-powered wallet." "The AI decides." Both are false here.

---

### B. Why is this an agent rather than a workflow?

**Answer.** Because we tried to prove it wasn't. `research/planning_benchmark.py`
is eleven adversarial episodes written *before* the agent was changed so that it
could fail — and it did, 5/11. In five of them the cheapest valid-looking basket is
the wrong one. The old planner used two moves across all eleven episodes: swap for
the cheapest, drop the dearest. The current one scores 11/11; the old one, re-run
against the same episodes, still scores 5/11.

**Evidence.** `tests/test_planning_benchmark.py`. The old planner is recoverable at
`git show f47f89d:research/shopping_agent.py`, so the comparison is re-runnable.

**Limitation.** Eleven small synthetic worlds is a diagnostic sample, not a
representative one. The claims register grades this SUPPORTED, not PROVEN.

**Do not say.** "Fully autonomous." "It reasons about your shopping."

---

### C. What does the agent actually decide?

**Answer.** Which goods, from which shop, in what combination, and when to stop and
ask a human. It decides nothing about money moving. Concretely, in the demo it
decides to change shop after a merchant refusal, then to swap a single non-returnable
line after a terms refusal — and the approved basket costs a franc *more* than the
refused one.

**Evidence.** Live on the Agent tab: CHF 47 → CHF 107 → CHF 108.
`tests/test_demo_data_is_real.py` fails if that stops being true.

**Limitation.** Its objective counts lines bought, a thin proxy for a shopping list.
It does not model what a household needs.

**Do not say.** "It decides what to buy for you" without the second half.

---

### D. Why don't you use an LLM?

**Answer.** We measured it instead of assuming. `research/model_planner.py` puts a
model planner at the same seam; `research/architecture_comparison.py` runs the
benchmark eleven ways. Deterministic: 11/11, zero calls. Best possible model: 11/11
— a tie, for 21 network calls. A confidently-wrong model *with* a deterministic
fallback: **8/11**, below the planner it was meant to improve, because a fallback
catches answers that are unusable and that one is merely wrong.

**Evidence.** `tests/security/test_model_planner_seam.py`, 19 tests.

**Limitation.** Those are stubs. No API was called; no model was benchmarked. What
is measured is the architecture's sensitivity to model behaviours, not any model's
ability. A real model would have to be measured separately.

**Do not say.** "LLMs make it worse." We did not test an LLM.

---

### E. Isn't this just a policy engine?

**Answer.** A policy engine answers "does this match the rules". This also answers
"may this *agent* perform this action, now, on this evidence" — and separates the
two verdicts. There is one decision in the official scenarios where every rule the
customer wrote passed and the wallet stopped the purchase anyway. A policy engine
cannot produce that, because the policy said yes.

**Evidence.** SCEN0004/AU0036: `policy_verdict: allow`, `security_verdict: review`.
Derived live at `GET /api/scenarios/security-override`.

**Limitation.** The policy half genuinely is a rules engine, and a simple one:
field, operator, value, scope. We do not dress it up.

**Do not say.** "It understands intent." It compiles phrase patterns.

---

### F. Why can't a normal credit-card spending limit solve this?

**Answer.** A card limit answers one question — *can this card spend?* It cannot
express "from a seller I have used before", "only if returnable within 14 days", or
"ask me when you are not sure", and it cannot tell an agent *why* it was refused in
a form the agent can act on without learning the limit. In the demo, two of three
refusals are things no spending limit can represent.

**Evidence.** The compiled mandate carries `merchant.familiar`,
`order.return_window_days` and `item.category` alongside the amount rule.

**Limitation.** For the amount rule alone, a card limit genuinely is equivalent. We
say so rather than pretending the money rule is the interesting one.

**Do not say.** "Card limits don't work." They work, for what they express.

---

### G. What happens if the agent is malicious?

**Answer.** It proposes; it never decides. It cannot raise a ceiling, forge a
platform field, fake merchant familiarity, or charge. We test that with planners far
worse than a compromised one: proposing CHF 150,000, hallucinating items, crashing,
returning nothing, never learning. No approval, no money, in every case.

**Evidence.** `tests/security/test_agent_planner_boundary.py`; 133-case adversarial
corpus; 17-case attack matrix.

**Limitation.** Our corpus is a sample, not a proof. And the wallet cannot verify
that a merchant stocks an item — an agent that *lies about its own basket* is
evaluated truthfully against a false description. That is an agent-side property.

**Do not say.** "The agent cannot do anything harmful."

---

### H. What happens if the model hallucinates?

**Answer.** There is no model in the path, so the honest answer is about the seam:
a hallucinating planner returns item ids that do not exist, the parse fails closed,
and the deterministic search takes over. Same for a planner that replies in prose,
times out, or crashes. Every failure mode collapses to "nothing usable", and nothing
usable never widens an errand.

**Evidence.** `test_the_agent_survives_every_way_a_model_can_fail`, three stubs.

**Limitation.** The case a fallback *cannot* catch is a model that is confidently
wrong in well-formed JSON. Measured: 8/11. We publish that number.

---

### I. Can the agent learn the spending limit?

**Answer.** A patient agent can, slowly and expensively, and we publish the price:
about twelve probes and CHF 531 in purchases it must keep, to recover a CHF 137
ceiling. Ours does not, because its objective minimises price within a coverage
tier — it walks *away* from the limit. It settles at CHF 7.50 against that same
hidden CHF 137, on its first proposal.

**Evidence.** `tests/security/test_agent_explanation_boundary.py`;
`test_searching_spends_FEWER_refusals_than_repairing_did`.

**Limitation.** That is a property of *our* planner, not of the interface. A
different planner behind the same seam could probe. And the customer's own
instruction contains the number — the wallet never tells the agent a rule value, and
the shipped planner never reads the instruction, but the number is in its possession.

**Do not say.** "The agent cannot learn your limit." Say the price.

---

### J. Why should I trust merchant-provided evidence?

**Answer.** You should not, and we do not. Return windows, sizes and finality are
merchant claims extracted from text we cannot verify. The design constraint is that
merchant text can only ever *narrow* a decision, never widen one, and that is tested
against prompt injection in the item description.

**Evidence.** `test_I7_*`, `test_prompt_injection`; `facts.py` whitelists one regex
per fact and normalises before matching.

**Limitation.** A plausible lie beats us. "Returns accepted within 90 days" satisfies
every realistic threshold with zero knowledge of the policy. This is in
`WHAT_WE_REFUSE_TO_CLAIM.md` and has no fix inside this protocol.

**Do not say.** "We detect merchant fraud."

---

### K. What happens after revocation?

**Answer.** Nothing may be authorised, including a purchase already waiting for the
customer. That case was a real vulnerability found by an independent audit —
revoke, then answer the pending step-up, and CHF 175 was charged — because
revocation was a sweep over existing records and a waiting purchase had no record to
sweep. It is now run-scoped state, so "nothing after revocation" is true for records
that do not exist yet.

**Evidence.** `RunState._revoked_at`; `test_F1*`, `test_revocation_end_to_end`.

**Limitation.** Within one process. A worker restoring an old checkpoint is out of
scope and we say so.

---

### L. What happens across multiple sessions?

**Answer.** The rolling cap is enforced per run, matching the platform's own scope.
Measured: one scenario approves CHF 387.50 per run, so ten runs put CHF 3,875
through a stated CHF 300/7-day cap. We **disclose this to the customer at
confirmation**. We do not enforce it.

**Evidence.** `docs/WHAT_WE_REFUSE_TO_CLAIM.md`, the cross-run row.

**Limitation.** And a correction we published against ourselves: we used to call
this a protocol limit. That was overstated. `POST /v1/team/reset` clears
team-scoped state spanning runs, so an authoritative cross-run record plausibly
exists; its shape is under-documented and we chose not to rely on it. A ledger
prototype was built and attacked — two concurrent sessions both approved against the
same remaining budget.

**Do not say.** "Cross-session enforcement is impossible." It is a choice under
uncertainty.

---

### M. How do you prevent double spending?

**Answer.** At-most-once, within one process, by construction: the execution
lifecycle lives on the decision record rather than in a second object. Two records
describing one authorization is the shape that produced four separate
vulnerabilities, so there is now one. Eight concurrent charge attempts against one
approval produce exactly one charge.

**Evidence.** `test_execution_atomicity`; `StoredDecision` holds `execution_*`,
`revoked`, `consumed_at`.

**Limitation.** Not exactly-once, and not across processes. Two workers restoring
the same checkpoint can each consume the same authority once.

**Do not say.** "Exactly once." It is on the refuse list.

---

### N. What happens if the wallet is unavailable?

**Answer.** Nothing is authorised. The agent holds no authority to fall back on, so
unavailability fails closed by construction rather than by a check. On the worker
side a malformed event is logged and no decision is submitted.

**Limitation.** We do **not** know what the platform does when a deadline is missed.
The spec gives `deadline_at` and never says what follows a missed one. If silence
approves, "submit nothing" is the wrong failure mode and it is the first thing we
would change. That is written down rather than glossed.

---

### O. What is actually novel?

**Answer.** Not the rules engine, and not one-shot mandates — SEPA, card-on-file and
Google AP2 Intent Mandates are prior art and we cite them. What we have not found
prior art for is the **agent-facing explanation boundary**: refusing an agent in a
form it can act on (*which class of constraint*) while withholding everything it
could probe with, and measuring the leak that remains in francs.

**Evidence.** `docs/ARCHITECTURE_PRIOR_ART.md`; the oracle measurement.

**Limitation.** "We did not find prior art" is not "there is none".

**Do not say.** "Novel protocol." "First of its kind."

---

### P. Who would pay for this?

**Answer.** The card issuer. It is the party that carries the loss when an
autonomous agent spends wrongly, already sits in the authorization path, and already
holds the purchase history the familiarity rule needs. The integration point is the
authorization decision they already make.

**Limitation.** No customer discovery, no pilot, no revenue model, and we invent no
market-size number.

**Do not say.** Any figure. There isn't one.

---

### Q. Why is this necessary now?

**Answer.** Because agents that buy things are shipping, and the authorization
question is changing shape. A card asks *can this card spend?* An agent needs *may
this agent perform this action, under these constraints, on this evidence, now?* —
a question today's primitive cannot express and therefore cannot refuse precisely.

**Limitation.** An argument, not a measurement. Labelled as such.

---

### R. What part is reproducibly demonstrated?

**Answer.** All of it, offline. The official replay is 45 events, 19/2/24,
byte-identical across runs. The planning benchmark and the architecture comparison
are byte-identical across runs. The demo agent loop was run 40 times across two
server lifetimes plus 8 concurrent sessions, all identical. No network, no key, no
model anywhere in the judged path.

**Evidence.** `scripts/run_replay.py`, `research/planning_benchmark.py`,
`research/architecture_comparison.py`.

**Limitation.** 19/2/24 is a regression boundary, **not a score** — the dataset
carries `contains_expected_decisions: false`. There are no official labels.

**Do not say.** "We get 19 out of 45 right."

---

### S. What are you explicitly NOT claiming?

**Answer.** There is a document for it, it is maintained, and it is the one we would
rather the jury read: `WHAT_WE_REFUSE_TO_CLAIM.md`. Exactly-once payment. Capping
total spend. Enforcing the account limit. Cross-session enforcement. Detecting
merchant lies. Understanding intent. Formal proof of anything. Standards compliance.
Novelty for one-shot mandates. Production readiness.

**This is the strongest card in the deck.** Play it before being asked.

---

## The questions we would most dislike

Ranked by how much damage a good answer prevents.

1. **"Show me the agent failing your own benchmark."** We can: 5/11, and the file
   was written before the fix. This is the best question anyone could ask us.
2. **"Your agent endpoint — what else is under `/api/agent/`?"** One route, with a
   test that fails if a second appears. Until this campaign there were two, and the
   second served the customer view keyed on an id the agent chooses. We found it,
   fixed it, and it is written up in `AGENT_VISIBLE_DATA.md`.
3. **"Is the thing on screen real data?"** Now yes, and enforced: every demo offer
   is the official catalogue with its real name, category and a price inside its
   published band. Until this campaign the page sold a hotel room as pantry restock.
4. **"What does the agent see that I don't know about?"** One table, produced by
   calling each route and searching the bytes.
5. **"Why should I believe the demo isn't scripted?"** Run it again. Or change the
   mandate on the Delegate tab and watch the agent shop under it.

---

## Three juries, three failure modes

The same two minutes lands differently on each. What changes is not the demo — it is
which twenty seconds you slow down on.

### 1. The technically sophisticated jury

| | |
| --- | --- |
| **immediately** | agent/wallet separation; that `blocked_by` is a class and not a value; that the replay is deterministic |
| **misunderstands** | that the wallet is "just" a rules engine — because the policy half genuinely is one, and they see that half first |
| **bored by** | the compiler, the test count, anything about the UI |
| **impressed by** | the benchmark written *before* the fix; the model comparison table; the refusals document; that we found the `/api/agent/` leak ourselves |
| **challenges credibility on** | "is the agent real or a script?", and the oracle question — *can it learn the limit?* |
| **must be shown, not said** | the price going **up** while the decision goes block → allow; the grey box with all four fields |

**Slow down on:** 1:10 (the swap for one franc more) and the `blocked_by` box.
**Skip if short:** the Delegate compile step. **Open with:** the benchmark, if Q&A
starts badly.

### 2. The product / market jury

| | |
| --- | --- |
| **immediately** | "the agent shops, you decide"; the plain-English rule box |
| **misunderstands** | thinks it is a budgeting app, or that a card limit already does this |
| **bored by** | verdict separation, reason codes, anything with an underscore in it |
| **impressed by** | writing a rule in your own words and seeing what the wallet *could not* represent; "this one purchase, not a standing exception" |
| **challenges credibility on** | who pays, and why an issuer would not build it themselves |
| **must be shown, not said** | the unsupported-restrictions list blocking confirmation; the consent scope line |

**Slow down on:** 0:25 (what could not be turned into a rule) and 1:42 (bounded
consent). **Answer before asked:** the issuer is the buyer, and why — loss, path,
history. **Never:** invent a number.

### 3. The sceptical AI jury

| | |
| --- | --- |
| **immediately** | that there is no LLM, and they will decide within ten seconds whether that is rigour or a gap |
| **misunderstands** | "no model" as "no AI" — they hear a rules engine wearing an agent costume |
| **bored by** | determinism arguments made abstractly |
| **impressed by** | that we *built* the model planner and measured it; that a confidently-wrong model with a fallback scores **worse** than none; that the seam needed no adapter |
| **challenges credibility on** | "then where is the intelligence?" and "you're avoiding the hard problem" |
| **must be shown, not said** | two *different kinds* of adaptation in sequence — one shop, one goods — because one adaptation looks like a rule firing |

**Slow down on:** 0:52 → 1:10, both strategy chips. **Answer before asked:** "we put
a model in and measured it — here is the table." **Never say:** "LLMs make it worse."
We tested stubs, not a model, and they will catch that instantly.

---

## The one-line defence, per jury

- **Technical:** "We wrote the benchmark before we fixed the agent so it could fail.
  It did — 5 out of 11."
- **Product:** "You write the rule in your own words, and it tells you what it
  couldn't enforce before you confirm."
- **AI:** "We built the model planner. It ties at best, and loses when it's
  confidently wrong. Here's the table."

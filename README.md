# Agent on a Leash -- Wallet Control

> **A policy is not a list of rules. It is a set of purchases —**
> **and the set is drawn over facts, some of which the party being judged writes.**
> The agent is autonomous. The authority is not.

**[docs/THE_THESIS.md](docs/THE_THESIS.md) is the one page to read.** What you
authorised, and how much of it is actually enforceable — with every number checkable:

```
 595 / 595   "Order our household groceries."
 145 / 595   "…at or below CHF 120."                       -450
 116 / 595   "…from a shop I have used before."             -29
```

At the prices the catalogue calls typical. Every item also publishes a `min` and a
`max`, the seller picks, and the same mandate admits **476** of the 595 at the
cheapest end — so the panel headlines the range and not a point. Counting one price
was understating the delegation fourfold.

Every wallet answers a customer's sentence by showing them *rules*. This one answers
the question they actually have -- **how much did I just hand over?** -- by putting
every purchase this world can produce through the same engine that will judge the
real ones, and reporting the set that comes back. **47 ms** on the machine it was measured on, live, as they type
(median of nine calls with a fresh instruction each time; it was documented as 18 ms
and that figure was never true of the shipped panel).

A prototype **wallet control layer** for Viseca's Swiss {ai} Weeks 2026 challenge,
["Agent on a Leash"](https://github.com/Swiss-ai-Weeks/viseca-2026). An AI shopping
agent proposes purchases; this system -- independent of the agent -- decides
whether each one may go ahead, using a customer's own wallet policy (a "mandate")
and the purchase facts, and asks the customer when it genuinely cannot tell.

This repository is the **team's implementation**. The official challenge
specification, schemas, and synthetic data pack live in
[Swiss-ai-Weeks/viseca-2026](https://github.com/Swiss-ai-Weeks/viseca-2026) and are
copied read-only into [`data/official/`](data/official) for offline use -- see
[docs/VISECA_INTEGRATION.md](docs/VISECA_INTEGRATION.md) for exactly which parts of
this codebase are the official integration versus local, demo-only extensions.

## What it does

1. **Compiles a customer's instruction into an executable wallet policy.**
   ("Buy groceries for CHF 120 or less..." -> spending ceilings, merchant/item
   requirements, an uncertainty policy) -- [`policy_compiler.py`](src/wallet_control/policy_compiler.py).
2. **Decides ALLOW / REVIEW / BLOCK for each proposed purchase**, deterministically,
   from that policy plus the purchase facts --
   [`decision_engine.py`](src/wallet_control/decision_engine.py). Merchant-supplied
   free text *is* read, in exactly one place and under whitelist patterns, and it can
   only ever **narrow** a decision: no merchant string can raise a ceiling, satisfy a
   requirement or turn a BLOCK into an ALLOW ([`facts.py`](src/wallet_control/facts.py),
   invariant I9). We do **not** claim to detect a merchant lying in the narrowing
   direction -- see [docs/WHAT_WE_REFUSE_TO_CLAIM.md](docs/WHAT_WE_REFUSE_TO_CLAIM.md).
3. **Separates that decision from actual payment execution.** ALLOW is
   authorization advice, not money moving -- [`payment.py`](src/wallet_control/payment.py).
4. **Lets the customer confirm, tighten, or revoke** what they allowed, and answer
   a step_up for one purchase without changing the standing policy --
   [`mandate.py`](src/wallet_control/mandate.py).
5. **Says the thing only a wallet can see.** Three sentences a card spending limit
   cannot produce, each out of the real engine on the official pack:

   > *"…it would take you over the CHF 300 you allowed across any 7-day period.*
   > ***You could order this again on Monday 17 August at 09:12.***" — the engine
   > holds every approved timestamp; the window is half-open, so it knows to the
   > minute, and it says so only when waiting is actually the cure.
   >
   > *"…because **this purchase came from a device that has not been used earlier in
   > this session**."* — the customer wrote *"pause anything that looks like someone
   > other than me is driving"*. It used to notice the device change, write it into
   > its own evidence, and approve anyway.
   >
   > *"…because **this seller's product description contains instructions aimed at an
   > automated buyer, not at you**."* — the injection is ignored, as it must be. Every
   > team will manage that. Telling you a counterparty tried is the other half, and
   > it fires on 2 of the 56 official item lines, both genuine.

   None of the three FAILS a rule. Each returns `unknown` and goes to the customer's
   own `uncertainty_policy` — none is evidence the *purchase* is bad, and that is
   exactly what the third value is for.

## What it shows you *before* you agree

A policy is a **hypothesis about what someone meant**. Three panels on the Delegate
tab test that hypothesis with concrete purchases run through the real engine, rather
than describing it in prose that nobody audits. Each one is **silent when it has
nothing to say**, which is the property that keeps it from becoming a warning people
learn to click through.

| panel | the question | how it answers |
| --- | --- | --- |
| **read-back** ([`unconsumed.py`](src/wallet_control/unconsumed.py)) | which of your words did the compiler actually read? | every word deleted in turn and the sentence compiled again. Green changed a rule; struck through changed nothing; red means *deleting it would create* one. 19 of 20 silently-lost restrictions caught, 0 false alarms on 33 well-formed sentences |
| **scope** ([`scope.py`](src/wallet_control/scope.py)) | how much rope did you just hand over? | every basket this world can produce, through the real engine. `"Order our household groceries"` authorises **595 of 595**; adding `"at or below CHF 120"` removes **450** at typical prices, and the panel shows the whole price band because the seller picks the price. Counted, not described — 47 ms |
| **ambiguity** ([`ambiguity.py`](src/wallet_control/ambiguity.py)) | does your sentence decide this purchase? | compile it two defensible ways and search the whole world, sequences included, for where they part. `"up to CHF 250 per week"` is ambiguous about **470 of 595** purchases; the cheapest witness is three orders of CHF 87. Quiet on three of five sentences |
| **silence** ([`silence.py`](src/wallet_control/silence.py)) | can a seller get past your rule by publishing nothing? | three sellers, same goods, same price. States 30 days → *buys it*; states 13 → *refuses it*; **says nothing → depends on one dial you can move** |

The shared apparatus is [`witness.py`](src/wallet_control/witness.py): a throwaway
mandate, a hypothetical purchase, the real engine. None of it decides anything.

**The read-back measures the compiler, not English** — the obvious objection, and it
is tested rather than argued. Pointed at three compilers with deliberately different
vocabularies, the same sentence comes back read three different ways (2 words, 6
words, 11 words), each difference exactly the vocabulary that was added
([`research/read_back_is_compiler_agnostic.py`](research/read_back_is_compiler_agnostic.py)).
The probe is one deletion and a re-compile and never inspects the compiler, so a
**model-based** compiler is another entry in that table at one call per word — which
is a statement about the mechanism, not evidence about any model. None was called.

**Where a model belongs, and the only place it earns real freedom.** The readings
above are a hand-written table of two transformations.
[`disagreement.py`](src/wallet_control/disagreement.py) takes two *compilers*
instead, so a model-based one would generate readings for constructs nobody thought
of — proposing a **hypothesis about meaning**, never a decision, adjudicated by the
real engine and resolved by the customer. A wrong model produces an extra question;
it cannot produce a wrong enforcement. That is the draft/verify shape of
[speculative decoding](https://github.com/Swiss-ai-Weeks/optimized-apertus), one
level up from the agent — and the same repository names the object underneath all of
this, the **acceptance set**: an untrusted proposer changes the speed, never the
distribution. Measured across four brains and 337 proposals, including one that
ranks baskets by a hash: **not one approved purchase outside the set**
([`research/acceptance_set.py`](research/acceptance_set.py)). **No model has been
run** — `api.publicai.co/v1` answers 401 without a key.

**Why they exist** is one principle, arrived at after finding the same mistake at
seventeen different boundaries: **absence is not a value** — see
[docs/ABSENCE.md](docs/ABSENCE.md). A missing fact must be represented as missing and
routed to whoever can supply it; never filled in, never inferred, never thrown.

And a second principle, about the instruments rather than the product: **a check that
cannot fail is not a check.** Seven of ours reported success they had not earned —
a mutation probe printing `41 killed` after examining two, a pre-demo gate going
green having run no tests, a corpus reporting `0 escapes` when its baselines made an
escape impossible. Every output was indistinguishable from the real thing. See
[docs/A_CHECK_THAT_CANNOT_FAIL.md](docs/A_CHECK_THAT_CANNOT_FAIL.md).

## Repository layout

```
src/wallet_control/        THE RUNTIME -- only code that runs in production
  mandate.py               The customer's policy: draft/confirm/tighten-only/revoke
  policy_compiler.py       Natural language -> hard_rules, deterministic, no model
  facts.py                 The official event -> canonical facts; the ONE place
                           merchant text is read
  rules.py                 Evaluates one hard_rule against facts -> pass/fail/unknown
  decision_engine.py       The core: binding, platform status, replay, safety checks,
                           and _decide()  (fail > unknown > pass)
  state.py                 THE SECURITY OBJECT: the write-once decision ledger, the
                           execution lifecycle, rolling spend, revocation, checkpoint
  payment.py               The execution boundary -- one function may move money
  audit.py                 Audit timeline + delegation view (pure projections)
  ambiguity.py             Two readings of one sentence, and the purchase between them
  silence.py               The rule a seller can escape by publishing nothing
  unconsumed.py            Which of the customer's words changed a rule, measured
                           by deleting each one -- takes ANY compiler, not just ours
  witness.py               Shared apparatus: a hypothetical purchase, the real engine
  scope.py                 How many purchases this sentence authorises, counted
  disagreement.py          Where two readings part, over the whole enumerated world
  attack_demo.py           The nine judge-facing attacks -- one of which SUCCEEDS,
                           on purpose, with the argument attached
  drift.py                 Explains how a re-delivered authorization differs (cannot gate)
  money.py                 Exact-decimal CHF math and the fixed FX table
  intervention.py          Decision -> the customer-facing intervention gloss
  viseca_mapping.py        ALLOW/REVIEW/BLOCK <-> approve/decline/step_up, in one place
  csv_data.py              Read-only loaders for data/official/*.csv
  offline_replay.py        Builds official-schema events from the pack and replays them
  viseca_client.py         HTTP client for the hosted API (only the endpoints we call)
  live_worker.py           The poll/decide/submit worker; one RunState per run_id
  api.py                   Demo backend + static UI (same engine, no separate path)
  stage.py                 The stage: one purchase at a time, replayed or live, with
                           display-only explanations (never a decision)

research/                  APPARATUS -- never imported by the runtime (asserted by a test)
  shopping_agent.py        The autonomous agent: plans, proposes, is refused, adapts
  fulfillment.py           "Has this job already been done?", derived from the ledger
  red_team.py              17 hand-written adversarial scenarios
  red_team_corpus.py       133 generated cases
  security_object.py       Eight competing models of the fundamental security object
  demo_scenario.py         The R&D walkthrough

data/official/             Read-only copy of the official synthetic data pack
ui/stage.html              The demo: the customer's phone and the purchase stream
ui/index.html              The lab: every panel and proof, mobile-first, one file,
                           no framework, no build step
tests/                     1900 tests
scripts/                   Replay, adversarial suites, research experiments
docs/                      The system as it is now: thesis, architecture, security
                           model, claims, demo script
docs/archive/              Audits, research logs and red-team reports from the build
```

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Run the tests:

```bash
pytest -q
```

Run the full offline replay (all 45 official events, all 5 scenarios):

```bash
python scripts/run_replay.py
```

Start the demo backend + UI:

```bash
uvicorn wallet_control.api:app --port 8420
# the stage (demo):  http://localhost:8420/stage.html
# the lab (evidence): http://localhost:8420
```

**The stage** is the demo: the customer's phone beside the stream of purchases the
agent proposes, each judged by the same engine. The customer's rules, the questions
the wallet asks (with the platform's 120-second window), and a button that revokes
everything. Explanations the engine already had are shown rather than summarised:
the seller's sentence written for the AI, struck through; the shop whose name
imitates one the customer knows; the rolling limit against the customer's own figure.
It replays the official scenarios locally, or, with `TEAM_API_KEY` and
`LEASH_BASE_URL` set on the server, runs them live on the Viseca sandbox and sends the
customer's answers through `/resolve`. Keys: `→` next purchase, `Space` play, `A`/`D`
answer, `L` pull the leash, `R` restart. The styling follows Viseca's public sites
(colours, Roboto, bundled in `ui/fonts/` so it works offline); it is not a Viseca
product and uses no Viseca logo.

Check it before demoing -- `matches_regression_boundary` must be `true`:

```bash
curl -s localhost:8420/api/health
```

Full operator instructions: [`RUNBOOK.md`](RUNBOOK.md).

Run the live worker against the hosted API (event day only):

```bash
export LEASH_BASE_URL="https://saw26api.ashyground-364e1d07.switzerlandnorth.azurecontainerapps.io"
export TEAM_API_KEY="<your team key>"
python scripts/run_live_worker.py SCEN0000
```

## Tests

```
pytest -q
```

**1900 tests**, of which 5 are reported skips rather than silent ones — **6 in a
fresh clone**, because one test validates the organisers' own example fixture and
that file lives in their repository rather than this one (`reference/` is not
vendored). Our events are still checked against the official schema everywhere: that
file *is* vendored, at `data/official/schemas/`. The structure is deliberate rather than count-driven:

- `tests/security/test_product_invariants.py` -- the twelve product claims as
  property tests over generated inputs, each named after the sentence we would say
  to a judge.
- `tests/security/test_resolution_escape_hatch.py` -- three vulnerabilities found by
  an independent audit of the frozen build, each with a minimal reproduction.
- `tests/test_failure_modes.py` -- 26 dependency-failure cases; found a real defect.
- `tests/test_runtime_boundary.py` -- asserts the runtime never imports research.
- `tests/security/test_state_machine.py` -- a stateful model over the whole lifecycle.

The count is not the argument. `python3 scripts/run_mutation_probe.py` deliberately
breaks 41 security mechanisms in `src/wallet_control/`, one at a time, and checks the
suite notices: **41 killed, 0 survived.** Its first run found a real gap and the
missing test was written.

Official replay: **45 events, 12 allow / 9 review / 24 block** -- a regression
boundary, not a score. There are no official expected-decision labels.

## Offline replay results (this engine's actual output, not an answer key)

The official pack ships with **no expected decisions**
(`data/official/metadata.json`: `"contains_expected_decisions": false`). The
numbers below are what this engine concludes when it reasons from each
scenario's own `cardholder_instruction` and the supplied purchase facts --
they are a report of this implementation's behavior, not a target it was tuned
to hit. See [docs/OFFLINE_REPLAY.md](docs/OFFLINE_REPLAY.md) for the reasoning
behind every one of the 45 decisions.

| Scenario | Events | Allow | Review | Block |
| --- | ---: | ---: | ---: | ---: |
| SCEN0000 Connection check | 1 | 1 | 0 | 0 |
| SCEN0001 Household budget | 10 | 5 | 0 | 5 |
| SCEN0002 Requested item and order terms | 12 | 1 | 3 | 8 |
| SCEN0003 Session integrity | 11 | 4 | 1 | 6 |
| SCEN0004 Manipulated agent | 11 | 1 | 5 | 5 |
| **Total** | **45** | **12** | **9** | **24** |

"Buy the 27-inch monitor I chose" and "Replace my worn road-running shoes" are
one-off errands. The first matching purchase goes through; every further one is put
to the customer, because the wallet cannot see whether the first was delivered,
cancelled or returned. Before this rule the manipulated-agent run approved four
monitors (CHF 1,430.40) and the running-shoes run three pairs.

## Further reading

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) -- the authorization boundary, state/concurrency model, money handling
- [docs/archive/ARCHITECTURE_DECISIONS.md](docs/archive/ARCHITECTURE_DECISIONS.md) -- alternative designs actually traced and compared (a structured policy object, an LLM-in-the-loop compiler, an event log, a trained risk model), and why each was rejected or adopted
- [docs/archive/SECURITY.md](docs/archive/SECURITY.md) -- the attack surface and what defends against each attack
- [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) -- a field-by-field trust classification for every field the decision engine reads
- [docs/archive/FINAL_AGENTIC_AUDIT.md](docs/archive/FINAL_AGENTIC_AUDIT.md) -- is the agent credible? The old one gave up on five of nine adversarial episodes; what replaced it, and why there is still no model in the loop
- [docs/archive/FINAL_AGENT_SECURITY_AUDIT.md](docs/archive/FINAL_AGENT_SECURITY_AUDIT.md) -- every field the agent can reach, and the price of the oracle it cannot be denied
- [docs/FINAL_DEMO_SCRIPT.md](docs/FINAL_DEMO_SCRIPT.md) · [docs/FINAL_JUDGE_QA.md](docs/FINAL_JUDGE_QA.md) · [docs/FINAL_CLAIMS_REGISTER.md](docs/FINAL_CLAIMS_REGISTER.md)
- [docs/archive/COMPETITION_READINESS.md](docs/archive/COMPETITION_READINESS.md) -- honest assessment against the five jury criteria, the ten questions a judge could ask, and the strongest argument that this project is mediocre
- [docs/archive/CLAIMS_REGISTER.md](docs/archive/CLAIMS_REGISTER.md) -- every public claim with its scope, evidence, test, and what must NOT be inferred from it
- [docs/archive/MASTER_ADVERSARIAL_VALIDATION.md](docs/archive/MASTER_ADVERSARIAL_VALIDATION.md) -- validation of the agent boundary, including the invariant that caught my own design error
- [docs/archive/DEEP_WEAKNESS_REPORT.md](docs/archive/DEEP_WEAKNESS_REPORT.md) -- adversarial campaign against the remaining conceptual weaknesses: a silent weakening found and fixed, and why the run boundary is an implementation artifact standing in for a security boundary
- [docs/archive/POST_FABLE_FINAL_VALIDATION.md](docs/archive/POST_FABLE_FINAL_VALIDATION.md) -- independent re-verification of those fixes: all four closed, one latent bypass found and fixed during the pass
- [docs/archive/POST_FABLE_REMEDIATION.md](docs/archive/POST_FABLE_REMEDIATION.md) -- fixes for the independent audit: the confirmation gate for restrictions we cannot enforce, authorization identity, and the platform policy echo
- [docs/archive/FINAL_PRE_FABLE_AUDIT.md](docs/archive/FINAL_PRE_FABLE_AUDIT.md) -- the freeze audit: attacked as a hostile judge, including the ten questions a senior reviewer could ask and the truthful answers
- [docs/archive/FINAL_INTENT_FIDELITY_AUDIT.md](docs/archive/FINAL_INTENT_FIDELITY_AUDIT.md) -- does the wallet enforce what the customer asked for, or what the compiler heard? Six defects, including a weekly budget silently compiled as a per-order ceiling
- [docs/archive/FINAL_DEEP_RND_REPORT.md](docs/archive/FINAL_DEEP_RND_REPORT.md) -- the deep R&D campaign: two security defects found and fixed, the one candidate mechanism built and killed by its own attacks, and why the architecture is saturated under current protocol constraints
- [docs/archive/MULTI_DAY_RESEARCH_PROGRAM.md](docs/archive/MULTI_DAY_RESEARCH_PROGRAM.md) -- the final research report: what an outside researcher would attack, what happened when we attacked it ourselves, and what is still risky
- [docs/FINAL_AUDIT_PACKAGE.md](docs/FINAL_AUDIT_PACKAGE.md) -- **start here if you are auditing this.** Where to attack first, ranked, and how to falsify each claim
- [docs/WHAT_WE_REFUSE_TO_CLAIM.md](docs/WHAT_WE_REFUSE_TO_CLAIM.md) -- the limitations, stated as refusals rather than buried
- [docs/FINAL_INVARIANTS.md](docs/FINAL_INVARIANTS.md) -- the I1-I33 invariant register, each with what enforces it and the test that fails if you remove the mechanism. The register is machine-checked: `test_every_test_the_register_cites_exists`. It is *not* a formal proof and does not claim to be
- [docs/VISECA_INTEGRATION.md](docs/VISECA_INTEGRATION.md) -- official contract vs. local extensions
- [docs/OFFLINE_REPLAY.md](docs/OFFLINE_REPLAY.md) -- how the 45-event replay works and why each decision came out the way it did
- [docs/archive/DECISION_ANALYSIS.md](docs/archive/DECISION_ANALYSIS.md) -- the same replay examined adversarially: why so few REVIEWs, and every genuinely debatable call argued both ways
- [docs/archive/FINAL_SENIOR_ENGINEERING_REVIEW.md](docs/archive/FINAL_SENIOR_ENGINEERING_REVIEW.md) -- the first engineering review, written right after the initial build
- [docs/archive/SECOND_ADVERSARIAL_AUDIT.md](docs/archive/SECOND_ADVERSARIAL_AUDIT.md) -- a second, hostile audit pass that re-opened the first review's own decisions and fixed 18 further issues, including the most serious one found across all three passes
- [docs/archive/MASTER_R_AND_D_AUDIT.md](docs/archive/MASTER_R_AND_D_AUDIT.md) -- a third pass: property-based testing, mutation testing, adversarial fuzzing, and a genuine (not assumed) comparison of alternative architectures

## What this is not

Everything here is synthetic, as the challenge specifies. This is a hackathon
prototype: the mock PSP does not move real money, the live worker is a single
process (matching a single-team, single-run event-day operating model, not a
production payment gateway), and no fraud-reduction or compliance claims are made
beyond what is implemented and tested here.

# Agent on a Leash -- Wallet Control

> The agent is autonomous. The authority is not.

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
   from that policy plus trustworthy purchase facts -- never from merchant-supplied
   text -- [`decision_engine.py`](src/wallet_control/decision_engine.py).
3. **Separates that decision from actual payment execution.** ALLOW is
   authorization advice, not money moving -- [`payment.py`](src/wallet_control/payment.py).
4. **Lets the customer confirm, tighten, or revoke** what they allowed, and answer
   a step_up for one purchase without changing the standing policy --
   [`mandate.py`](src/wallet_control/mandate.py).

## Repository layout

```
src/wallet_control/
  money.py            Exact-decimal CHF math and FX conversion
  mandate.py           The wallet policy: draft/confirm/tighten/revoke lifecycle
  policy_compiler.py   Natural-language instruction -> hard_rules (no LLM)
  facts.py             Trustworthy purchase facts; the ONE place item_details is read
  rules.py             Evaluates hard_rules against facts -> pass/fail/unknown
  state.py             Rolling spend, idempotency, duplicate & session-integrity signals
  decision_engine.py   Orchestrates the above into ALLOW/REVIEW/BLOCK
  intervention.py      Local ask_missing_fact/ask_this_time/never gloss on a decision
  payment.py           Mock PSP enforcing the authorization/payment boundary
  viseca_mapping.py    ALLOW/REVIEW/BLOCK <-> approve/decline/step_up (one place)
  csv_data.py          Read-only loaders for data/official/*.csv
  offline_replay.py    Builds official-schema events from the CSV pack and replays them
  viseca_client.py     HTTP adapter for the hosted API
  live_worker.py       The executable poll/decide/submit worker
  api.py               Small FastAPI demo backend (not the official integration)
data/official/          Read-only copy of the official synthetic data pack
ui/index.html            Single-page demo UI (vanilla JS, no framework)
tests/                   pytest suite (see "Tests" below)
docs/                    Architecture, security, Viseca integration, final review
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
uvicorn wallet_control.api:app --reload
# open http://127.0.0.1:8000/
```

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

187 tests, including 8 Hypothesis property-based tests (each checked against
100-200 generated inputs, so the effective coverage is closer to a few thousand
generated cases for those properties alone) and a 10-instruction adversarial fuzz
corpus for the policy compiler. Covers mandate lifecycle and tighten-only PATCH
semantics (including malformed-identifier rejection), the policy compiler
(paraphrased instructions, contradictory/ambiguous amounts, false-positive-prone
phrasing, and a curated fuzz corpus -- not just the five official sentences), the
rules engine (including per-item scoping so an unrelated add-on cannot false-fail
the correct primary item), the decision engine's ALLOW/REVIEW/BLOCK priority
(including the "zero hard rules must never mean unlimited authority" safety net,
and confirmed by mutation testing to actually be enforced, not merely asserted),
prompt-injection and Unicode-obfuscation resistance, duplicate/retry/idempotency
(including a same-ID delivery with mutated facts), the payment boundary (including
charge_id-reuse, merchant-binding misuse, and zero/negative-amount rejection),
human resolution scoping, the offline replay, the Viseca decision mapping,
event-schema validity against the official JSON Schema, the live worker (against
a fake client -- no API key needed -- including network-failure handling,
crash-recovery via checkpoint, and stopping rather than retrying forever on a
fatal 401/403), and the demo API end-to-end. See
[docs/MASTER_R_AND_D_AUDIT.md](docs/MASTER_R_AND_D_AUDIT.md) for the full third
audit pass (property-based testing, mutation testing, fuzzing, and a genuine
comparison of alternative architectures) and
[docs/SECOND_ADVERSARIAL_AUDIT.md](docs/SECOND_ADVERSARIAL_AUDIT.md) for the
second pass's 18 findings, including the most serious one found across all three
passes.

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
| SCEN0002 Requested item and order terms | 12 | 3 | 1 | 8 |
| SCEN0003 Session integrity | 11 | 5 | 0 | 6 |
| SCEN0004 Manipulated agent | 11 | 5 | 1 | 5 |
| **Total** | **45** | **19** | **2** | **24** |

## Further reading

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) -- the authorization boundary, state/concurrency model, money handling
- [docs/ARCHITECTURE_DECISIONS.md](docs/ARCHITECTURE_DECISIONS.md) -- alternative designs actually traced and compared (a structured policy object, an LLM-in-the-loop compiler, an event log, a trained risk model), and why each was rejected or adopted
- [docs/SECURITY.md](docs/SECURITY.md) -- the attack surface and what defends against each attack
- [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) -- a field-by-field trust classification for every field the decision engine reads
- [docs/SECURITY_INVARIANTS.md](docs/SECURITY_INVARIANTS.md) -- the formal I1-I25 invariant list, each with what enforces it and what test would catch a violation
- [docs/VISECA_INTEGRATION.md](docs/VISECA_INTEGRATION.md) -- official contract vs. local extensions
- [docs/OFFLINE_REPLAY.md](docs/OFFLINE_REPLAY.md) -- how the 45-event replay works and why each decision came out the way it did
- [docs/DECISION_ANALYSIS.md](docs/DECISION_ANALYSIS.md) -- the same replay examined adversarially: why so few REVIEWs, and every genuinely debatable call argued both ways
- [docs/FINAL_SENIOR_ENGINEERING_REVIEW.md](docs/FINAL_SENIOR_ENGINEERING_REVIEW.md) -- the first engineering review, written right after the initial build
- [docs/SECOND_ADVERSARIAL_AUDIT.md](docs/SECOND_ADVERSARIAL_AUDIT.md) -- a second, hostile audit pass that re-opened the first review's own decisions and fixed 18 further issues, including the most serious one found across all three passes
- [docs/MASTER_R_AND_D_AUDIT.md](docs/MASTER_R_AND_D_AUDIT.md) -- a third pass: property-based testing, mutation testing, adversarial fuzzing, and a genuine (not assumed) comparison of alternative architectures

## What this is not

Everything here is synthetic, as the challenge specifies. This is a hackathon
prototype: the mock PSP does not move real money, the live worker is a single
process (matching a single-team, single-run event-day operating model, not a
production payment gateway), and no fraud-reduction or compliance claims are made
beyond what is implemented and tested here.

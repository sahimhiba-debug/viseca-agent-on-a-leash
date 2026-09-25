# Agent on a Leash

> **The agent shops. The wallet decides.**

**An AI shopping agent can think, act and make mistakes. It does not get to authorise
itself.** A wallet control concept for Viseca's Swiss {ai} Weeks 2026 challenge,
["Agent on a Leash"](https://github.com/Swiss-ai-Weeks/viseca-2026). Not an official
Viseca product.

## The problem

A shopping agent with your card will buy whatever it is talked into: by a confused
plan, a manipulated shop, or a sentence hidden in a product description. A card limit
only knows *how much*. In the organisers' own data, "Buy the 27-inch monitor I chose"
ended with **four monitors**, every one of them under the limit.

## The idea

**The agent never holds the card.** It proposes a purchase. A wallet, independent of
the agent, decides from one sentence the customer wrote: yes, no, or *"let me ask
you"*, on the customer's phone, with a reason. One tap on the leash stops everything.

> **A spending limit asks how much. This asks what for.**

## Why it is different

Same CHF 289, eight versions of one purchase (stage, key **S**):

| | a card set as tightly as a card can be | this wallet |
| --- | --- | --- |
| the monitor Oliver chose, at his usual shop | yes | **yes** |
| a shop he never used · a lookalike of his shop · a 24-inch instead of 27 · an extra cable · two cheaper monitors | yes | **no**, with the reason |
| a seller's note to the AI · the same monitor again | yes | **asks him** |

The card rule is explicit (CHF 400 per purchase, electronics shops, Switzerland) and
can refuse; at CHF 289 in a Swiss electronics shop it has no reason to.

## How it works

1. The customer writes a sentence. The wallet turns it into rules and **shows what it
   could not turn into a rule** before the customer confirms.
2. The agent (any brain: a search, Apertus, OpenAI, or a hostile one) proposes purchases.
3. The wallet judges each proposal against the rules and the facts, and returns
   yes / no / ask. Seller text is read as evidence, never obeyed as instructions.
4. The customer answers questions for **one purchase at a time**. Their rules don't change.
5. Pulling the leash cancels anything approved but unpaid, answers any open question
   no, and blocks everything after.

## See it in action

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
uvicorn wallet_control.api:app --port 8420
```

Open **http://localhost:8420/stage.html**. Press **→** for each purchase the agent
proposes, **D** to decline a question, **L** to pull the leash, **S** for *same
price, different answer*. The 3-minute script: [docs/FINAL_DEMO_SCRIPT.md](docs/FINAL_DEMO_SCRIPT.md).

## Evidence

| | result | reproduce |
| --- | --- | --- |
| official data, 45 purchases | 12 allowed · 9 asked · 24 blocked; one monitor, not four | `python3 scripts/run_replay.py` |
| how often the customer is asked | 9 of 45, or **3** if they answer *"I already have it"* once per errand | [docs/CUSTOMER_FRICTION.md](docs/CUSTOMER_FRICTION.md) |
| four brains, same wallet (search, Apertus 1.5 70B, gpt-4.1-mini, hostile) | **0** purchases approved that break the customer's sentence | [docs/REAL_MODEL_PLANNER.md](docs/REAL_MODEL_PLANNER.md) |
| 288 generated seller attacks × the 45 purchases | **0** decisions made more permissive | [docs/GENERATED_CORPUS.md](docs/GENERATED_CORPUS.md) |
| 840 generated customer sentences | last blind measurement lost 3 of 200 restrictions silently, since fixed | [docs/GENERATED_CORPUS.md](docs/GENERATED_CORPUS.md) |

The model scores (11 episodes, three runs each) are ours, not a ranking of models:
the search 11/11, Apertus and gpt-4.1-mini 7-8/11 on their own. The point is that the
brains differ and the authority does not.

## Limitations

Spending windows are per run, not per mandate. Single use is per process. The demo's
question channel has no authentication. A seller can still *claim* the fact a rule
checks ("returns within 90 days"). The sentence compiler reads English only (other
languages are flagged, not read). **[docs/LIMITATIONS.md](docs/LIMITATIONS.md)** says,
for each, what it is, why, and whether it touches the judged path.

## Go deeper

| | |
| --- | --- |
| **Jury** | [The pitch, 1 and 3 minutes](docs/PITCH.md) · [52 jury questions](docs/JURY_QA.md) · [Jury answers, short](docs/JURY_ANSWERS.md) · [Demo script](docs/FINAL_DEMO_SCRIPT.md) · [Architecture on one page](docs/ARCHITECTURE_ONE_PAGER.md) |
| **Security** | [Audit package: where to attack](docs/FINAL_AUDIT_PACKAGE.md) · [Claims register](docs/FINAL_CLAIMS_REGISTER.md) · [What we refuse to claim](docs/WHAT_WE_REFUSE_TO_CLAIM.md) · [Security model](docs/SECURITY_MODEL.md) |
| **Benchmarks** | [Real models at the planner seam](docs/REAL_MODEL_PLANNER.md) · [Generated corpora](docs/GENERATED_CORPUS.md) · [Customer friction](docs/CUSTOMER_FRICTION.md) |
| **Research** | [The thesis](docs/THE_THESIS.md) · [The full former README](docs/README_FULL.md) · [Offline replay, all 45 decisions](docs/OFFLINE_REPLAY.md) |
| **Architecture** | [Architecture](docs/ARCHITECTURE.md) · [Codebase guide](docs/CODEBASE_GUIDE.md) · [Viseca integration](docs/VISECA_INTEGRATION.md) |
| **Operations** | [Runbook](RUNBOOK.md) · [Current baseline](docs/BASELINE_CURRENT.md) |

## Run it and check it

```bash
pytest -q                               # the suite
python3 scripts/run_replay.py           # the official replay
python3 scripts/run_mutation_probe.py   # breaks each security mechanism on purpose
```

```
tests/                     2006 tests
```

At the submission freeze, a fresh checkout collected **2006 tests: 2000 passed, 6 skipped**. The count is not the argument: the mutation probe breaks **45 security mechanisms** one at a time and the suite catches every one. See the [submission baseline](docs/BASELINE_CURRENT.md) and rerun the [pre-demo gate](RUNBOOK.md) before presenting.

Official replay: **45 events, 12 allow / 9 review / 24 block**, a regression
boundary rather than a score. Per scenario:

| scenario | events | allow | review | block |
| --- | --- | --- | --- | --- |
| SCEN0000 Connection check | 1 | 1 | 0 | 0 |
| SCEN0001 Household budget | 10 | 5 | 0 | 5 |
| SCEN0002 Requested item and order terms | 12 | 1 | 3 | 8 |
| SCEN0003 Session integrity | 11 | 4 | 1 | 6 |
| SCEN0004 Manipulated agent | 11 | 1 | 5 | 5 |
| **Total** | **45** | **12** | **9** | **24** |

No API key is needed for any of the above. Keys for the live sandbox and the model
experiments come from environment variables and are not in this repository.

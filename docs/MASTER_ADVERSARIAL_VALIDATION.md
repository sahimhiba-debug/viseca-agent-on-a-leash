# Master adversarial validation

Validation of the one mechanism this campaign added, and of the defects found while
building it.

---

## 1. The measurement the mechanism exists for

The wallet is an oracle; every decision system is. Measured against this engine:

| what the agent can see | probes to recover a secret CHF 137 ceiling | cost to the agent |
| --- | --- | --- |
| the decision only (ALLOW/BLOCK) | **12**, to within CHF 0.24 | **CHF 531.49 actually spent** |
| the customer's payload | **0** — it carries `"value": 137` and `projected 7-day spend=…` | nothing |

The cost is the only thing that makes the oracle tolerable, and it cannot be removed
without removing the wallet. What *can* be removed is the shortcut. Hence the
audience split, and hence `agent_view`.

## 2. Attacks on the new mechanism

| attack | result |
| --- | --- |
| agent projection carries a policy number | **refused by test** — searched for every policy figure, any decimal, any dotted rule field, and every evidence string, across five decision shapes |
| a period breach is distinguishable from an over-limit order | **no** — both read `amount`; distinguishing them would double the information per purchase |
| the agent learns *why* a human was asked | **no** — it gets `awaiting_customer: true` and nothing else |
| the adapt loop manufactures authority | **no** — a revised basket is re-decided from scratch; every approval has all rules passing |
| the agent probes forever | **bounded** at `MAX_REVISIONS`, and every attempt is a recorded decision an auditor can count |
| the agent routes around a step-up by retrying | **no** — it stops and waits; asserted |
| `agent_view` influences a decision | **no** — it is a projection of an already-made decision; asserted by re-deciding |
| the wallet comes to depend on the agent | **structurally prevented** — see §3 |

**Visible proof that it adapts rather than extracts:** given a CHF 120 ceiling it
lands on **CHF 87**, not CHF 119.99. An agent holding the number would land on the
number. Asserted as a test with a CHF 5 margin.

## 3. The invariant that caught my own design error

The first version ran the agent loop *inside* `api.py`, importing `research/`. That
broke `test_runtime_boundary.py`, an invariant predating this campaign: **the runtime
never imports research apparatus**, so the wallet runs identically with `research/`
deleted.

The invariant was right and the design was wrong. Inverting it — the wallet exposes
`POST /api/agent/propose`, the agent is an external HTTP client that loops — is both
correct and the better demonstration, because the loop now visibly happens *outside*
the wallet. Verified end-to-end over HTTP.

## 4. A defect found while wiring it

`GET /api/runs/{id}` re-presents stored decisions through `_recorded_message`, which
emitted:

```
Declined: hard_rule_failed:authorization.billing_amount_chf
```

Raw reason codes, on a customer-facing endpoint. The same class as invariant I39,
surviving in the one surface that audit never checked: it examined `customer_message`
on **fresh** decisions and on the **platform payload**, and this path builds the
sentence somewhere else entirely.

Fixed by reusing `decision_engine._PLAIN_FAIL` — one table, not a second copy to
drift. Pinned for both the fresh and the re-presented path, and mutated.

## 5. Determinism and reproducibility

| check | result |
| --- | --- |
| official replay run twice | byte-identical: 45 · 19/2/24 |
| agent episode run twice | identical: `292 → 197 → 137 → 87`, block/block/block/allow |
| secrets scan (keys, bearer tokens) | none |
| network or API key needed for tests/replay/agent demo | none — `TEAM_API_KEY` is read only by `run_live_worker.py` |
| fixed simulated clock for the agent demo | `AGENT_DEMO_START`, so the trace never drifts |

## 6. Full gate

| | |
| --- | --- |
| suite | **960 passed, 5 skipped** (965 collected) |
| official replay | **45 — 19 allow / 2 review / 24 block**, unchanged |
| adversarial corpus | 133/133 |
| attack matrix | 17/17 |
| mutation probe | **38 mutants, 38 killed, 0 survived** (36 → 38) |
| independent semantic corpus | 103 · 93 recognised · 0 silently lost · 0 wrong |

New invariants **I45** (agent sees decision + class, never a value) and **I46**
(adaptation consumes delegation, never widens it).

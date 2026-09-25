# Runbook

Every command below is intended to be run from the repository root. A teammate who did not write the code should be able to follow it top to bottom.

> **Submission baseline:** commit `3bb934a` (24 September 2026). The freeze immediately before the final delivery recorded **2000 passed, 6 skipped, 2006 collected**, a **45/45** mutation probe, and the official replay at **45 events — 12 allow / 9 review / 24 block**. If a fresh checkout produces different numbers, treat the checkout's results as authoritative and investigate before presenting.

---

## 1. Install

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

Requires Python ≥ 3.11 (developed on 3.13.9). There is **no Node build** — the UI is one static HTML file with no dependencies, served by the backend.

No API key, database, or network access is needed for the offline demo and verification path. The official synthetic data pack is vendored at `data/official/`.

## 2. Run the product

```bash
source .venv/bin/activate && uvicorn wallet_control.api:app --port 8420
```

Then open **http://localhost:8420/stage.html** for the demo and **http://localhost:8420** for the lab.

### Presenting with the stage

- Pick the scenario at the top ("Manipulated agent" shows the most in one run).
- `→` proposes the next purchase; `Space` plays automatically. When the wallet asks, the phone shows the question; `A` approves once and `D` declines.
- `L` pulls the leash (with confirmation); `R` restarts.
- **Live sandbox** is optional and requires `TEAM_API_KEY` and `LEASH_BASE_URL`. Rehearse in Replay because hosted runs persist.

## 3. Pre-demo gate

Run these before presenting:

```bash
source .venv/bin/activate
python3 -m pytest -q
python3 scripts/run_replay.py
python3 scripts/run_mutation_probe.py
python3 scripts/run_red_team_corpus.py
python3 scripts/run_red_team.py
```

Expected submission baseline:

- tests: **2000 passed, 6 skipped, 2006 collected**
- official replay: **45 events — 12 allow / 9 review / 24 block**
- mutation probe: **45 applied, 45 killed, 0 survived**
- adversarial corpus: **133/133 held**
- attack matrix: **17/17 defeated**

The test count is not the security argument. The mutation probe deliberately breaks 45 safety mechanisms and checks that the suite detects every break.

Then start the server and check:

```bash
uvicorn wallet_control.api:app --port 8420
curl -s localhost:8420/api/health | python3 -m json.tool
```

`matches_regression_boundary` must be `true`. If it is false, **do not demo** until the drift is understood.

## 4. Official replay

```bash
python3 scripts/run_replay.py
```

The last line must read `TOTAL events: 45  {'allow': 12, 'review': 9, 'block': 24}`. This is a **regression boundary, not a score**: the official pack contains no expected-decision labels.

## 5. Adversarial checks

```bash
python3 scripts/run_red_team_corpus.py   # 133/133 held at submission freeze
python3 scripts/run_red_team.py          # 17/17 defeated at submission freeze
python3 scripts/run_demo_scenario.py
```

The judge-facing attacks are also exposed by the running product:

```bash
curl -s localhost:8420/api/attacks | python3 -c "import json,sys; d=json.load(sys.stdin); print(f\"{d['held']}/{d['total']} held\"); [print(' ', a['title'], '->', a['outcome']) for a in d['attacks']]"
```

## 6. Research scripts

These reproduce R&D claims; they are not required to run the judged product.

```bash
python3 scripts/run_fulfilment_differential.py
python3 scripts/run_economic_envelope.py
python3 scripts/run_scope_falsification.py
python3 scripts/run_security_object_falsification.py
```

## 7. Reset and logs

```bash
curl -s -X POST localhost:8420/api/demo/reset
uvicorn wallet_control.api:app --port 8420 --log-level debug
```

Reset clears in-memory demo runs only. Server logs go to stdout. Every decision carries its `authorization_id`.

## 8. Live Viseca integration (optional)

```bash
export LEASH_BASE_URL=https://saw26api.ashyground-364e1d07.switzerlandnorth.azurecontainerapps.io
export TEAM_API_KEY=...        # never commit it, never paste it into a log
python3 scripts/run_live_worker.py SCEN0001 --checkpoint-dir .checkpoints
```

Runs cannot be reset on the hosted API. Step-ups are answered through the separate `/resolve` path. A worker can resume from its checkpoint. SCEN0000 requires `--acknowledge-unsupported` because "one grocery item" cannot be expressed completely as a rule.

The integration was verified against the sandbox on 24 September 2026: all 45 purchases across five scenarios, with 41 automated decisions matching the offline replay and four step-ups answered through `/resolve`. This is the real integration path (`live_worker.py` / `viseca_client.py`) and shares the same decision engine with the demo.

## 9. Troubleshooting

| symptom | likely cause | action |
| --- | --- | --- |
| UI says backend unreachable | server missing or stale | restart uvicorn and hard-refresh |
| `/api/health` reports replay drift | decision behavior changed | run the full pre-demo gate and investigate |
| port 8420 is in use | old server process | `lsof -ti:8420 \| xargs kill` |
| an attack card shows **HOLE** | security regression | stop; do not present past it |
| fresh test count differs from this file | repository changed since freeze | trust the fresh run, then update the documented baseline |

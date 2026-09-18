# Runbook

Every command below was run on the machine that wrote this file, from the repository
root. A teammate who did not write the code should be able to follow it top to bottom.

---

## 1. Install

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

Requires Python ≥ 3.11 (developed on 3.13.9). There is **no Node build** — the UI is
one static HTML file with no dependencies, served by the backend.

No API key, no database, no network access is needed for anything in this runbook.
The official synthetic data pack is vendored at `data/official/`.

## 2. Run the product

```bash
source .venv/bin/activate && uvicorn wallet_control.api:app --port 8420
```

Then open **http://localhost:8420**. Five tabs: Overview (start here), Delegate,
Decisions, Attacks, Audit.

## 3. Check it is healthy before demoing

```bash
curl -s localhost:8420/api/health | python3 -m json.tool
```

`matches_regression_boundary` must be `true`. It re-runs the official replay and
compares against 45 events / 19 allow / 2 review / 24 block. If it is `false`,
something has changed the decision engine — **do not demo**, run the test suite.

## 4. Run the tests

```bash
source .venv/bin/activate && python3 -m pytest -q
```

Expect **622 passed**. Useful subsets:

```bash
python3 -m pytest tests/security -q          # security + invariants + scope model
python3 -m pytest tests/test_failure_modes.py -q   # dependency failure behaviour
python3 -m pytest tests/test_product_surface.py -q # attacks, audit, API
```

## 5. Run the official replay

```bash
source .venv/bin/activate && python3 scripts/run_replay.py
```

The last line must read `TOTAL events: 45  {'allow': 19, 'review': 2, 'block': 24}`.
This is a **regression boundary, not a score** — there are no official
expected-decision labels, and this number must not be "improved".

## 6. Run the adversarial suites

```bash
source .venv/bin/activate && python3 scripts/run_red_team_corpus.py   # expect 133/133 held
python3 scripts/run_red_team.py                                       # expect 17/17 defeated
python3 scripts/run_demo_scenario.py                                  # synthetic R&D walkthrough
```

The eight judge-facing attack demonstrations are in the product itself (Attacks tab)
and also available headless:

```bash
curl -s localhost:8420/api/attacks | python3 -c "import json,sys; d=json.load(sys.stdin); print(f\"{d['held']}/{d['total']} held\"); [print(' ', a['title'], '->', a['outcome']) for a in d['attacks']]"
```

## 7. Research scripts (reproduce the R&D claims)

```bash
python3 scripts/run_fulfilment_differential.py        # 6 disagreements / CHF 1,787.40
python3 scripts/run_economic_envelope.py              # what a compliant compromised agent extracts
python3 scripts/run_scope_falsification.py            # the three-scope model under attack
python3 scripts/run_security_object_falsification.py  # eight candidate security objects
```

## 8. Reset the demo

```bash
curl -s -X POST localhost:8420/api/demo/reset
```

Clears in-memory runs only. It cannot touch the official data or any compiled policy.
Restarting the server has the same effect — all demo state is in-process by design.

## 9. Inspect logs

The server logs to stdout. Run it in the foreground during a demo. Every decision
carries its `authorization_id`, and every API error carries the HTTP status.

```bash
uvicorn wallet_control.api:app --port 8420 --log-level debug
```

## 10. The live Viseca integration (not needed for the demo)

```bash
export VISECA_API_BASE_URL=... VISECA_API_KEY=...
python3 scripts/run_live_worker.py
```

This is the real integration path (`live_worker.py` / `viseca_client.py`). It shares
the exact decision engine with the demo, so the demo is not a separate code path.
**The demo does not require it and does not call it.**

## 11. Troubleshooting

| symptom | cause | action |
| --- | --- | --- |
| UI shows "backend unreachable" | server not running, or running an older build | restart uvicorn; hard-reload the page |
| UI looks like an old version | browser cache on a static file | reload with `?v=2` appended, or hard-refresh |
| `/api/health` says the replay drifted | the decision engine changed | `python3 -m pytest -q` and fix before demoing |
| port 8420 in use | a previous server | `lsof -ti:8420 \| xargs kill` |
| an attack card shows **HOLE** | a real regression in the security core | stop; this is the one failure that must never be demoed past |

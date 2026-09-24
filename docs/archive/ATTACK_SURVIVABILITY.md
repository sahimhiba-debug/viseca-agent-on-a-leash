# Attack survivability — what holds, what does not, what is only a demo

One page. Every row is backed by code and a test, or it is marked as not backed.

---

## 1. Holds under attack

| Property | Evidence |
| --- | --- |
| A compromised agent cannot mint its own authority | only `RunState.issue_authority` constructs one, gated on `allow` |
| An approval cannot be moved to another purchase, merchant or amount | corpus `P06`–`P08`, 15 mutation families × 3 contexts |
| An approval is single-use within one run state — durably across a crash when the executor has a persist hook | `test_execution_durability.py`; state machine over 6,000 sequences |
| Revocation stops money that has not moved — including a human-approved step-up, and across a restart (same persist-hook condition) | `test_revocation_end_to_end.py`, corpus `F01`, `N01` |
| A mandate that is not ACTIVE authorizes nothing | `test_mandate_status.py` |
| A platform-declared revoked/expired authority or blocked card cannot be paid | `test_platform_status.py`, corpus `F02` |
| Merchant text cannot become instruction | 30 injection cases; structural test that the compiler is never called from the engine |
| A re-delivery with any security-relevant change cannot inherit the approval | mutation fuzzer, 15 `B*b` corpus cases |
| A cosmetic text edit does not fork a legitimate retry | Hypothesis property over generated noise |
| A human approval cannot be re-priced, replayed, contradicted or borrowed by another run | corpus `E01`–`E06` |
| An event for another card or mandate is rejected before anything is decided | `test_run_binding.py`, corpus `P01`–`P05` |
| Malformed input, NaN/∞ money, unknown currency, network failure and process crash never become approval | corpus `L01`–`L10`, `I07`–`I09`; `test_live_worker.py` |
| Explanation (drift, verdict split) cannot change an outcome | 200-example monotonicity property |

**133/133 adversarial cases held**, across replay, mutation, injection, step-up,
revocation, money, time, identity, concurrency, crash recovery, malformed input and
composition.

---

## 2. Does not hold — and cannot, here

| Gap | Why it is not fixable in this layer |
| --- | --- |
| A merchant can satisfy `item.size` and `order.return_window_days` by writing text | no independent source for either fact exists in the challenge's data model |
| Rolling-window limits assume a truthful `authorization.timestamp` | the contract requires windows to key on simulated purchase time; we cannot verify it. Not agent-reachable today — the timestamp arrives from the platform, and the agent has no channel to author it |
| "The one I chose", "my usual" | referential anchors with nothing verifiable to bind to |
| SKU / generation / colour / width identity | no ontology; a heuristic one pretending to be ground truth would be worse than none |
| A hostile platform | every fact originates from its event stream |

---

## 3. Holds only by assumption — say so out loud

| Assumption | Where it lives |
| --- | --- |
| Single process | `charge()` is check-then-act with no lock. 24 threads racing one charge produced exactly one execution, but that is the GIL and a small window, not synchronisation |
| One run state | Single-use is per-`RunState`. Two workers restoring the same checkpoint each execute once (V11). Pinned by a test; closing it needs a shared store with atomic compare-and-set |
| A persist hook is supplied to the executor | Without one, consumption is memory-only and a crash resurrects a spendable authority (V10) |
| Retry of a completed charge after a restart fails closed rather than returning the original record | the `charge_id` ledger is in-memory; consumption is persisted, so the retry is refused — safe, not idempotent |
| `MockPSP` stands in for a payment rail | auth-vs-capture, partial capture and reversal do not exist here |

---

## 4. Presentation only — not security

Marked because confusing these with controls is its own risk.

| Component | What it actually is |
| --- | --- |
| `AuthorizationDrift` | a structured field diff, computed **after** the decision and never read by it. Explains; does not gate |
| `policy_verdict` / `security_verdict` | the same evaluations re-scoped for display. Provably cannot change the outcome |
| `PaymentAuthority.policy_version`, `basket_fingerprint`, `mandate_id` | provenance recorded on the grant, not enforced bindings |
| The demo UI | a viewer over the same engine; no decision logic of its own |
| `MockPSP` as evidence about the hosted challenge | it guards a simulated execution the official integration never triggers — the hosted path produces a *decision*, not a payment |

---

## 5. The honest prior

Twelve vulnerabilities across five passes. Three of V1–V8 were in code earlier
passes had declared hardened; V2 falsified an invariant a previous pass explicitly
claimed and tested; and V10 falsified the previous pass's own V8 fix, whose test
had been generous enough to snapshot at the convenient moment. V12 — a revoked
mandate that still authorized — survived four passes and was found only by
re-running the schema audit over nested objects.

Two more (V7, V8) were found by tooling built during this pass, not by reading —
and both lived in compositions, not in any single field. Every vulnerability found
here survived per-field testing and died only under a crossing.

So the defensible statement is not "this wallet is secure". It is:

> Against 133 enumerated attacks across eleven categories, a fully compromised
> shopping agent obtained no execution beyond exactly what the customer's mandate
> authorized — and the places where that guarantee depends on trusting someone else
> are written down in §2 and §3 rather than implied away.

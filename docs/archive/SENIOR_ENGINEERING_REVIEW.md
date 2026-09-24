# Senior engineering review

<!-- snapshot -->
> **SNAPSHOT — written 18 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

Reviewed as a hostile reader: *why does this abstraction exist, which state is
authoritative, and could this be removed?*

The headline result is a **27% reduction in the shipped package** with no behaviour
change, driven by one structural fact rather than by taste: 1,887 lines in
`src/wallet_control` were unreachable from either entry point.

---

## 1. Architecture

See `PRODUCT_ARCHITECTURE.md` for the diagram. In one sentence:

> A customer's words are compiled to executable rules they confirm; an untrusted agent
> proposes purchases; one deterministic engine decides allow / ask / block; the decision
> is written once to a ledger; and exactly one function may turn a ledger entry into
> money.

Two authoritative objects, and no third:

| object | scope | what it settles |
| --- | --- | --- |
| the **mandate snapshot** | mandate | what the customer permitted; tighten-only by construction |
| the **decision ledger** (`RunState._decisions`) | authorization | what was decided, for how much, at which merchant, on which basket — *and* the execution lifecycle |

Everything else is derived: rolling spend, fulfilment, drift, the audit timeline, the
delegation view. None of them gates a side effect.

## 2. Complexity analysis

| | lines | modules |
| --- | ---: | ---: |
| `src/wallet_control` (runtime) | **4,806** | 19 |
| `research/` (apparatus) | 1,837 | 6 |
| tests | 6,466 | 26 files |
| `ui/index.html` | 543 | 1 |

The decision path is seven files, traceable top to bottom without opening anything else:
`mandate → policy_compiler → facts → rules → decision_engine → state → payment`.

No inheritance beyond dataclasses. No factories, registries, service locators, event
buses or plugin systems. One lock. One `threading.Event`. Four runtime dependencies.

## 3. Major simplifications

Full detail in `SIMPLIFICATION_LOG.md`.

1. **Runtime / research split** (−1,887 lines from the shipped package). An import-closure
   walk from `api` and `live_worker` showed five modules were not merely loosely coupled
   but *not connected at all*: the 133-case corpus, the 17-attack matrix, eight competing
   security-object models, the fulfilment derivation (deliberately outside the decision
   path) and an R&D walkthrough the UI no longer called.
2. **`GET /api/rnd-demo` deleted.** Superseded by the Attacks tab, which demonstrates the
   same properties against the real engine instead of a pre-narrated script.
3. **`VisecaClient` trimmed to the endpoints we call.** Six untested HTTP wrappers removed.
4. **`Mandate.replace_guidance()` removed** — zero references anywhere.

## 4. Removed code

~1,950 lines out of the runtime. Nothing that runs in production was deleted; the
research was moved, not discarded, because its results are cited throughout `docs/` and
a claim whose experiment has been deleted is just an assertion.

## 5. Remaining abstractions, and why each exists

| abstraction | justification |
| --- | --- |
| `RunState` | the authoritative ledger + the two locked transitions. The security object. |
| `StoredDecision` | one immutable record per authorization, carrying the lifecycle. It is *deliberately* one record: six vulnerabilities in this project came from a second record describing the same authorization. |
| `PaymentAuthority` | a **projection**, not stored. It exists so callers have a value object; `charge()` enforces against the ledger, never against it. |
| `MockPSP` | the single execution boundary. One function is the whole payment attack surface. |
| `HardRule` / `Mandate` | the official rule format, plus the tighten-only contract in one place. |
| `PurchaseFacts` | the official event normalised once, so no rule re-parses the wire format. |
| `HistoryIndex` | three-valued familiarity; keeps "we could not check" distinct from "no". |
| `LiveWorker` | the poll/decide/submit loop, one `RunState` per `run_id`, checkpointed. |
| `intervention` / `viseca_mapping` / `money` | three tiny modules that each hold one official mapping. Inlining them would scatter the official contract. |

**Rejected:** a separate payment-authority store (deleted in an earlier pass), a CHF
budget mechanism (measured: strictly weaker than counting performances), an
account-scope ledger (unenforceable with the official API), and a second presentation
ledger for the audit trail.

## 6. Security invariants

Ten, listed in `SENIOR_REVIEW_BASELINE.md` and each pinned by a named test. The
governing discipline, learned the hard way from six vulnerabilities that were one
mistake repeated:

> Every security-relevant fact is either authoritative-and-recorded, or a deterministic
> function of authoritative recorded facts. Never a third thing that can drift.

## 7. Test quality

622 tests. Not optimised for count — the structure is deliberate:

- `tests/security/test_product_invariants.py` — the twelve product claims as *property*
  tests over generated inputs, each named after the sentence we would say to a judge.
- `tests/security/test_resolution_escape_hatch.py` — three vulnerabilities found by an
  independent audit of the frozen build, each with a minimal reproduction that fails on
  the old code.
- `tests/test_failure_modes.py` — 26 dependency-failure cases; found a real defect
  (a non-JSON error body escaped the worker's only handler).
- `tests/test_runtime_boundary.py` — asserts the runtime/research separation structurally.
- `tests/security/test_state_machine.py` — a stateful model that found a second gap
  *while we were fixing the first*.

Weak tests removed or rewritten during this review: one that asserted any second
step-up resolution must raise (wrong — an identical re-submission is idempotent; the
correct invariant is that a *conflicting* one is refused).

## 8. Dependencies

Four at runtime: `fastapi`, `uvicorn`, `httpx`, `pydantic`. Three for development:
`pytest`, `jsonschema`, `hypothesis`. **No Node, no build step, no database, no queue,
no model at runtime.** The policy compiler is a deterministic lexicon and regexes, which
is why the demo cannot fail because an API is down and why the customer sees identical
rules on every retry.

## 9. API

Nine routes, each with one job:

| route | mutates | idempotent |
| --- | --- | --- |
| `GET /api/health` | no | yes — also reports whether the replay still matches 19/2/24 |
| `GET /api/scenarios` | no | yes |
| `POST /api/mandates/compile` | no | yes — pure preview |
| `POST /api/scenarios/{id}/run` | creates a run | no |
| `GET /api/runs/{id}` | no | yes |
| `GET /api/runs/{id}/audit` | no | yes — pure projection |
| `POST /api/runs/{id}/authorizations/{aid}/resolve` | records the human answer | yes for an identical answer; **409 for a conflicting one** |
| `POST /api/runs/{id}/revoke` | revokes | yes |
| `GET /api/attacks` | no | yes — deterministic |

One route deleted during the review. The demo API has **no authentication** — stated,
not hidden.

## 10. Frontend

543 lines, one file, no framework, no build. It renders decisions and evidence and
**never computes them**: there is no rule evaluation, no amount comparison and no
decision logic in the client. Its only domain knowledge is a lookup table mapping a
reason code to a plain-English sentence, which cannot change an outcome.

Fixed during the review: after a step-up was answered the UI re-rendered from a slim API
response and erased every explanation on the page — the one action a customer is
guaranteed to take deleted the product's core promise.

## 11. Mobile

Mobile-first, not responsive-after-the-fact. Measured in a real browser with content
loaded: **0 px horizontal overflow, 0 clipped elements, 0 touch targets under 44 px** at
375×812, 390×844 and 412×915. Full detail and the three defects found in
`MOBILE_UX_AUDIT.md`.

## 12. Known limitations

1. The job capability is mandate-scoped; the ledger is run-scoped. One mandate reused
   across runs does not see the earlier run's fulfilment. *(Documented, pinned, not fixed
   — it is a re-scoping of the authoritative record, not a patch.)*
2. Account scope is real and **not enforceable** with the official API.
3. Single-use is **per process**.
4. A cancelled first purchase makes a legitimate retry look like a repeat.
5. Merchant claims cannot be verified.
6. The demo API has no authentication and records no `resolved_by`.

## 13. Unsupported claims removed

- *"The customer confirms the compiled rules before anything runs"* — stated in three
  places with **no confirm control in the UI**. A real gate now exists and stamps the
  audit entry.
- *"There is no code path from merchant text to a rule the wallet enforces"* — narrowly
  true, operatively misleading: two rule fields have no input *other* than merchant text.
  Reworded.
- *"Revocation stops authorized-but-unspent money"* — was **false** for a purchase still
  awaiting the customer. Fixed, then made true.
- *"Neither this wallet nor the official schema models a credit limit"* — false about the
  schema; `accounts.csv` carries one. Corrected in two documents.

## 14. Final verification

| | |
| --- | --- |
| tests | **622 passed**, 0 failed |
| official replay | **45 events — 19 allow / 2 review / 24 block** |
| red-team corpus | **133 / 133** |
| adversarial matrix | **17 / 17** |
| attack demonstrations | **8 / 8** |
| fulfilment differential | **6 / CHF 1,787.40** |
| mobile | 0 overflow / 0 clipped / 0 small targets at three viewports |
| API smoke | health OK, regression boundary `true` |
| commit | `7906f7b` |
| `main` | `1aa3bac` — untouched |

---

# FINAL ENGINEERING VERDICT

## KEEP

- The **two-object model**: mandate snapshot + decision ledger. It survived four
  falsification passes and every attempt to add a third object made it worse.
- **One execution boundary.** `MockPSP.charge()` is the entire payment attack surface.
- **The deterministic policy compiler.** No model at runtime is the reason the demo
  cannot fail on stage and the customer sees stable rules.
- **Derived-not-stored** for spend, fulfilment, drift and the audit trail.
- **The property-test suite**, which states the product's claims in the words we use.
- **The runtime/research boundary**, now structural.

## SIMPLIFY

- `state.py` (749) and `decision_engine.py` (672) are the two large modules. Both are
  *long, not complex* — one readable path each — and splitting them would either
  reintroduce a second record (the exact cause of six past vulnerabilities) or scatter
  the decision path. **Left deliberately.** If either grows again, split
  `decision_engine`'s always-on safety checks into their own module first.
- `attack_demo.py` (403) has eight near-parallel functions. Readable, and the duplication
  is what makes each attack independently auditable, but it is the next candidate.

## REMOVE

Done in this pass: the research modules from the shipped package, `GET /api/rnd-demo`,
six unused client methods, `Mandate.replace_guidance()`. **Nothing further identified** —
a full public-name and method scan over the runtime returned only false positives.

## DOCUMENT

- The **concurrency boundary** — single process, multi-thread. Now stated in
  `SENIOR_SECURITY_CLAIMS_AUDIT.md` rather than implied.
- The **account scope** — real, unenforceable, shown marked *not enforced*.
- The **mandate/run scope mismatch** — the one known invariant gap.

## STILL RISKY

Stated plainly, because these are what we would be asked about:

1. **Cross-run mandate reuse breaks the one-shot job invariant.** Reachable through the
   worker path; the demo avoids it only by compiling a fresh mandate per run. Fixing it
   means re-keying the authoritative ledger from run to mandate — a scope change, not a
   patch, and not something to do days before judging.
2. **Single-use is process-local.** Two workers restoring one checkpoint can each consume
   the same authority once. We say at-most-once, never exactly-once.
3. **The step-up channel is unauthenticated.** Anyone who can reach the port can answer a
   customer's question, and nothing records *who* answered. Closing it needs an identity
   on the resolution — new authoritative state — not just middleware.
4. **Two rule fields are decided entirely by attacker-controlled text.**
   `order.return_window_days` and `item.size` have no other input. A merchant claiming a
   3,650-day return window passes any realistic requirement. Not fixable inside the
   official rule vocabulary.
5. **The economic residue is the delegation, not a bug.** After everything the wallet can
   do, four of five official mandates remain unbounded in total — because the official
   rule format cannot express a total or an end date. We disclose it; we cannot fix it.
6. **The attack demonstrations are ours.** 8/8, 133/133 and 17/17 are our own adversarial
   thinking. They are a sample, not a proof, and an attacker we did not think of is
   exactly the one that matters.

**What remains uncertain:** whether the mandate/run scope mismatch is reachable in the
judged configuration; whether the official platform enforces the account limit we
decline to enforce; and whether our corpus covers the attack classes a judge will try.

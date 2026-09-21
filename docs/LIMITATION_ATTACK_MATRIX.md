# Limitation attack matrix

One row per attack. Attacks run in this campaign are marked **NEW**; the rest stand
from earlier campaigns and are cited so a judge can re-run them.

| # | limitation | attack | result | classification |
| --- | --- | --- | --- | --- |
| 1.1 | L1 budget scope | **NEW** agent invents 12 session ids | **DEFECT FOUND** — CHF 1,296 vs a stated CHF 300/7d. `session_id` is agent-chosen and scoped the window | **CLOSED** |
| 1.2 | L1 | **NEW** after the fix: 12 ids again | CHF 216, same as staying in one session | closed |
| 1.3 | L1 | **NEW** agent calls `POST /api/customer/mandates` itself | **FIX BYPASSED** — CHF 1,296 again; the endpoint is unauthenticated | **EXTERNAL-DEPENDENCY-LIMITED** |
| 1.4 | L1 | **NEW** mutant: restore per-session delegations | killed | — |
| 1.5 | L1 | **NEW** disclose the cross-delegation total | `GET /api/customer/delegations`, `enforced: false`, shown in the UI | **REDUCED** |
| 3.1 | L3 step-up identity | **NEW** approve A, check B | B unchanged at `review` | closed |
| 3.2 | L3 | **NEW** replay the same answer | idempotent allow | closed |
| 3.3 | L3 | **NEW** replay a contradicting answer | `ResolutionError` | closed |
| 3.4 | L3 | **NEW** answer after revocation | `block`, authority `None` | closed |
| 3.5 | L3 | **NEW** two queued step-ups, approve both past the cap | second blocked | closed |
| 3.6 | L3 | **NEW** signature carries no identity parameter | asserted; fails if auth arrives | **STRUCTURAL** |
| 4.1 | L4 at-most-once | **NEW** crash after decide, before issue | restart issues once | closed |
| 4.2 | L4 | **NEW** crash after issue, before consume | consumes once, second raises | closed |
| 4.3 | L4 | **NEW** crash after consume, restart | refused | closed |
| 4.4 | L4 | **NEW** 8 concurrent consumers, one process | exactly 1 charge, 7 refused | closed |
| 4.5 | L4 | **NEW** two RunStates from ONE checkpoint | **both consume** — money moves twice | **STRUCTURAL** |
| 10.1 | L10 composition | **NEW** exhaustive outcome×source, len 1–4, 3 policies | 4,662 lists: `decide(full) == stricter(policy, security)` | **PROVEN** |
| 10.2 | L10 | **NEW** is a verdict ever stricter than the decision? | never | closed |
| 10.3 | L10 | **NEW** inject a third `source` | composition breaks — hazard is real | — |
| 10.4 | L10 | **NEW** AST guard on every `RuleEvaluation(source=)` | third source unreachable; mutant killed | **CLOSED** |
| 10.5 | L10 | **NEW** can a human approval clear a policy failure? | a hard failure never offers step-up | closed |
| 11.1 | L11 economic belief | **NEW** UI scan for absolute money claims | none found; panel already says "does not cap the total" | closed |
| 11.2 | L11 | **NEW** surface the cross-delegation total | live, marked *shown, not enforced* | **REDUCED** |
| 12.1 | L12 demo credibility | **NEW** does the page ship verdicts? | generated files grepped for verdict words; page submits live | closed |
| 12.2 | L12 | **NEW** is the card model a strawman? | wins 2 of 12 rows; reads real merchant rows; understating it is a tested failure | closed |
| 2.1 | L2 merchant truth | prior: injection in `item_details` | text can only narrow; one whitelisted regex per fact | **STRUCTURAL** |
| 2.2 | L2 | **NEW** invented product within every rule | allowed — and gains nothing; a phantom over the ceiling or at the wrong shop is refused | **STRUCTURAL**, disclosed |
| 5.1 | L5 oracle | prior: adaptive binary search | ~12 probes, CHF 531 to recover CHF 137 | **STRUCTURAL**, priced |
| 5.2 | L5 | **NEW** does splitting `budget_window` from `amount` help a prober? | identical convergence: 11 probes, CHF 0.20 gap | closed |
| 7.1 | L7 leakage | prior + **NEW** every agent response searched | four fields, no decimal, one route under `/api/agent/` | closed |
| 7.2 | L7 | prior: timing | 0.85–0.87 ms across four outcomes | closed |
| 8.1 | L8 expressiveness | prior: 103-phrase corpus | 90% recognised, **0 silently lost** | **PROTOCOL-LIMITED** |
| 9.1 | L9 lifecycle | **NEW** replace a live mandate | 409 | closed |
| 9.2 | L9 | prior: tighten-only amendment | enforced in `mandate.py` | closed |
| 6.1 | L6 real LLM | **NEW** credential search (env, files, CLI, SDKs, local) | none; API 401, CLI OAuth expired | **EXTERNAL-DEPENDENCY-LIMITED** |

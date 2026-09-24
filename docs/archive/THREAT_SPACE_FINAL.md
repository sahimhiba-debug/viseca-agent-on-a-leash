# Threat space — final

Supersedes `THREAT_SPACE.md`. Seventeen boundaries; the change from the previous
version is boundary 13, which turned out to hold a control that was **present, tested
and wrong** rather than missing.

| boundary | attacker capability | authoritative source | our control | residual risk |
| --- | --- | --- | --- | --- |
| 1 customer intent → words | none | the customer | `open_questions` before confirmation | an unstated rule is not enforced |
| 2 words → policy | none | the compiler | unmapped phrases become questions, never guesses | — |
| 3 policy → mandate | none | the mandate | tighten-only by construction | — |
| 4 mandate → agent | reads it | platform | it cannot write it | the agent knows the edges |
| 5 agent → proposal | **total** | none | every claim verified or narrowed | **the agent chooses the decomposition** |
| 6 merchant → item facts | **total** | none | three narrow extractors, each narrowing only | **`return_window_days`, `item.size` rest on nothing but text; a plausible claim beats any realistic threshold** |
| 7 platform → status | none | platform | honoured as hard fails | `mandate.status` read from the run snapshot |
| 8 arithmetic | can misstate | FX table + the event's own parts | recomputed both ways | — |
| 9 proposal → decision | none | the engine | `fail > unknown > pass` | — |
| 10 decision → ledger | none | `_decisions` | write-once; basket fingerprint | — |
| 11 ledger → execution | retry, race, crash | the ledger | one point, atomic CAS | single-use is **process-local** |
| 12 sequence of decisions | compose permitted purchases | the ledger | rolling caps; job counting derived, not in the path | **individually-permitted purchases composing into an unintended outcome** |
| **13 timing of decisions** | **choose proposal order; force a pause** | **`_approved_spend`** | **every window containing the purchase is checked** ← *this pass* | the period check is a read-modify-write outside the consume lock (F4) |
| 14 time horizon | wait | nothing the customer can set | rolling windows | **no horizon is expressible; a rate is not a total** |
| 15 account | — | `accounts.csv` | **none** | real bound, **not enforceable** |
| 16 human step-up | chooses what gets asked | the answer | one purchase; conflicts refused; revocation wins | **unauthenticated; no `resolved_by`** |
| 17 explanation → agent | — | — | none needed | **the channel does not exist** — measured, see `C1_SECOND_ORDER_SECURITY_AUDIT.md` |

## What changed

Boundary 13 was not an empty cell in the previous map — it was folded into boundary 12
and assumed correct. Asking *"same transactions, same rules, different order: can the
security meaning differ?"* separated them and showed the control was wrong: 367 of 400
arrival orders breached the customer's cap, and a deferred step-up reached CHF 480
against CHF 300 with no reordering at all.

Boundary 17 is recorded as **closed by measurement, not by a control** — the agent never
receives our explanations, so there is nothing to defend.

## Still open

1. Cross-run mandate reuse breaks the one-shot job invariant.
2. Account scope is real and unenforceable.
3. Single-use is process-local.
4. The period check is not atomic (F4) — not reachable through `LiveWorker`.
5. Two rule fields rest entirely on merchant text, and saturation beats them.
6. The step-up channel is unauthenticated.

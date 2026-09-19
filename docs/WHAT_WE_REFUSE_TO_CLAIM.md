# What we refuse to claim

Kept deliberately short and blunt. If a claim is not on the proven list in
`WHAT_WE_CAN_PROVE.md`, it belongs here.

| We do NOT claim | Why |
| --- | --- |
| **Exactly-once payment** | At-most-once, and only within one process. Two workers restoring the same checkpoint can each consume the same authority once. |
| **That we cap total spending** | No mandate expressible in the official rule format can. `scope` is `purchase` or `period`, and the spec closes the set: *"No extra rule fields are allowed."* |
| **That we enforce the account's monthly limit** | It exists in `accounts.csv` and is real. The official API exposes no account-scoped spend counter and no account endpoint, so we cannot enforce it. We display it marked **not enforced**. |
| **That the one-shot job check holds across runs** | It holds within a run. Our ledger is run-scoped; the job is mandate-scoped. Reusing one mandate in a later run does not see the earlier run's fulfilment. |
| **Cryptographic authority or tamper-proof payment** | Nothing here is signed. The payment boundary is an in-process simulation. |
| **That we secure an official payment system** | The Viseca API has no payment step. `MockPSP` is ours, clearly labelled, and no production path calls it. |
| **That we understand customer intent** | We classify instruction *shape* with a small set of phrase patterns, and fail toward silence when unsure. |
| **That we detect merchant lies** | Item size, return windows and finality are the merchant's claims, derived from text we cannot verify. |
| **Standards compliance** | No SEPA, AP2, ACP or card-scheme certification. |
| **Novelty for one-shot mandates** | SEPA one-off mandates, card-on-file and Google AP2 Intent Mandates are prior art. |
| **That our adversarial suites are exhaustive** | 133 corpus cases, 17 matrix attacks and 8 demonstrations are a sample, not a proof. |
| **That the replay counts are a score** | 19/2/24 is a regression boundary. There are no official expected-decision labels. |
| **Order independence** | The approved *set* depends on arrival order. Greedy first-come-first-served admission: 300 orderings of SCEN0001 produce 14 distinct approved sets. Safety is unaffected; allocation is not guaranteed. |
| **Fairness** | No allocation policy is enforced, deliberately. The customer stated a bound, not a preference between competing purchases. |
| **Cross-run period enforcement** | The rolling cap is enforced per RUN, matching the platform's own scope — `technical_details.md`: *"context | Spend and recent authorization information from this run"*. Measured: SCEN0001 approves CHF 387.50 per run, so ten runs put CHF 3,875 through a stated CHF 300/7-day cap. We now DISCLOSE this at confirmation. We do not enforce it, and that is a **protocol limit, not a preference**: no documented endpoint returns a mandate's accumulated spend. A cross-session ledger was built and attacked (`research/mandate_ledger_prototype.py`) — two concurrent sessions both approved against the same remaining budget and the losing write vanished, and a missing ledger file is indistinguishable from a mandate that has never spent. Claiming a bound we cannot hold would be worse than naming the one we do. |
| **Formal proof of temporal safety** | Established empirically — 12,000 monotonicity baskets, 3,000 lifecycle traces, 4,000 optimizer strategies, exhaustive small permutations. No proof was constructed. |
| **A complete evidence audit** | Thirteen absent/inapplicable/conflicting cases across the rules that exist today. A new rule field could reintroduce the same inversion. |
| **Protection against merchant lies** | `order.return_window_days` and `item.size` have no input other than merchant free text. A plausible claim ("returns accepted within 90 days") beats every realistic threshold with zero knowledge of the policy. |
| **Schema re-validation** | We do not validate incoming events against `authorization_event.schema.json`. We rely on the platform for structural guarantees (`minItems: 1`, `quantity >= 1`), and several findings are "unreachable" only because of that. What we DO now guarantee is narrower and testable: deleting a required field never buys a more permissive decision than its strictest legal value would (`tests/security/test_required_field_omission.py`). That property was added after a red-team pass found `mandate.status` could be switched off by deleting it. |
| **What the platform does if we miss a deadline** | Unknown. `technical_details.md` gives `deadline_at` as "the real-clock deadline for the automated answer" and never says what follows a missed one. Our worker fails closed on its own side -- a malformed event is logged and no decision is submitted -- but whether platform-side silence denies or approves is not documented and we have not observed it. If it approves, "submit nothing" is the wrong failure mode and this is the first thing to change. |
| **Production readiness** | In-memory state, one process, no auth on the demo API, no multi-tenancy. |

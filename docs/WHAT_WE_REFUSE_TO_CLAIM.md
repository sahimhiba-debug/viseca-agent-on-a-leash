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
| **Production readiness** | In-memory state, one process, no auth on the demo API, no multi-tenancy. |

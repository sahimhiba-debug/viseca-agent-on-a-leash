# Limitations

What this wallet does not do, stated plainly. "Judged path" means the live decision
flow: platform event → wallet decision → customer answer → resolve.

| limitation | what it is | why it exists | status | judged path? |
| --- | --- | --- | --- | --- |
| **Cross-run aggregation** | spending windows and the one-off errand are counted per run; the same mandate in a new run starts from zero | the official period semantics are "recomputed from the decisions actually taken in the run", and the API offers no mandate-scoped counter | unfixed, pinned by tests | yes, if one mandate is reused across runs |
| **Exactly-once across processes** | two workers restoring one checkpoint can each charge the same approval | single use is enforced by in-process state and a lock; there is no shared store | unfixed, reproduced and pinned | only with more than one worker |
| **Step-up authentication** | whoever can reach the demo server can answer the customer's question; no identity is recorded | customer authentication belongs to the issuer's app; the demo server stands in for it | unfixed | yes: in live mode the answer passes through this server before the platform's (key-authenticated) `/resolve` |
| **Merchant-provided evidence** | the return window and the size come only from the seller's text, so a seller who claims "returns within 90 days" satisfies a return rule | there is no other source for those facts in the protocol | unfixed | yes, for mandates with a return or size rule |
| **Seller text length** | the wallet reads the first 16 KB of a description | a seller could otherwise spend the 8-second deadline (11.6 s measured on 20 MB) | **fixed**; longer text is named to the customer, and a claim past the cut stays unknown | yes, fixed |
| **Injection detection** | the customer is told a seller addressed the AI in about 70% of held-out attempts | detection is a list of shapes; marketing-shaped pushes read like honest copy | partial, measured; unnamed text is still never obeyed | only the *telling*, not the decision |
| **Compiler language coverage** | the sentence compiler reads English; French, German and Italian are detected and flagged, not read | a deterministic compiler, no model at runtime | flagged, not fixed | before confirmation, not in the decision |
| **Compiler vocabulary** | phrasings nobody generated can still be missed; the last blind measurement lost 3 of 200 before its fix | pattern-based on purpose (predictable, testable) | fixed on 840 generated sentences; not a proof | before confirmation |
| **Overall totals** | "CHF 500 in total" cannot be enforced; the customer is told | the official rule format has only per-purchase and rolling-window scopes | unfixable in the format | disclosed before confirmation |
| **Account monthly limit** | `monthly_limit_chf` in the data is not enforced here | no account-scoped counter in the API | unfixed | no |
| **Benchmark size** | the model results come from 11 episodes, three runs each | built to test the architecture, not to rank models | stated with every number | no |
| **Real models** | Apertus and gpt-4.1-mini asked the customer needlessly and kept a sold-out item; neither made an unauthorised approval | models plan less reliably than the search on this benchmark | measured; a model is never in the decision path | no |
| **Live sandbox availability** | during the final checks the sandbox answered HTTP 500 to every new run | organisers' side | the stage says so on screen and falls back to the local replay | demo only |

The long form, with reproductions and tests: [FINAL_AUDIT_PACKAGE.md](FINAL_AUDIT_PACKAGE.md)
("Known vulnerabilities that remain") and [WHAT_WE_REFUSE_TO_CLAIM.md](WHAT_WE_REFUSE_TO_CLAIM.md).

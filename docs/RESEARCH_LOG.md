# Research log

Reproducible record of every significant experiment in the autonomous campaign.
Each entry: question → setup → result → decision → commit.

---

### R1 · Does proposal order change what the wallet permits?
**Setup:** permute arrival order of all five official scenarios, timestamps unchanged.
**Result:** four invariant; **SCEN0001 ranged 5–7 allows**, CHF 387.50 → 477.00, starving nothing. 367/400 random orders **breached** the CHF 300/7-day cap, worst CHF 389.
**Decision:** real defect. → `a29eb99`

### R2 · Is it reachable without reordering?
**Setup:** strictly chronological delivery; one purchase stepped up, two approved behind it, then the customer answers.
**Result:** **CHF 480 in a CHF 300 week**, every decision locally correct. Both halves mandated by the spec ("a purchase waiting for a human answer is not yet approved"; "use simulated purchase time for spending windows").
**Decision:** the natural backward-looking window is wrong. Fix: evaluate every window *containing* the purchase. → `a29eb99`

### R3 · Does the fix move the official replay?
**Setup:** corrected check simulated offline across all 45 events.
**Result:** **identical**, all five scenarios. For a chronological run with nothing deferred the peak and backward windows coincide.
**Decision:** ship.

### R4 · Is the outcome now order-invariant?
**Setup:** 300 arrival orders; approved **sets** compared, not counts.
**Result:** **14 distinct approved sets.** Minimal counterexample A=B=C=100, D=150 under CHF 300: (A,B,C,D)→3 approvals, (A,D,B,C)→2.
**Decision:** **claim retracted.** Safety holds; invariance does not. Negative pinned as a test. → `5cf2480`

### R5 · Idempotent re-resolution
**Setup:** CHF 200 stepped up under a CHF 300 cap, approved, then the client retries the same answer.
**Result:** **crash** — the re-check counted the purchase against itself (200+200>300), decided to record a block, and conflicted with the recorded allow. The existing idempotence test missed it because its mandate had no period rule.
**Decision:** only a still-pending purchase may be overridden. → `5cf2480`

### R6 · Concurrency with a real widened window
**Setup:** 20 ms sleep inserted between the window read and the record; two threads.
**Result:** **40/40 both allowed, 40/40 breached** (CHF 400 vs 300). The previously *documented but never reproduced* F4.
**Decision:** hold the run lock across check-then-record; make it re-entrant. After: **0/40**, no deadlock. → `5cf2480`

### R7 · Semantic-inversion audit (13 rule cases)
**Setup:** for every rule, probe absent / inapplicable / conflicting evidence.
**Result:** one inversion — `order_returnable="not_applicable"` made the return-window requirement **pass unconditionally**, was never cross-checked against `fulfillment_method`, and ran *before* the final-sale logic, so an order marked "sold as final sale" satisfied "returnable within 14 days".
**Decision:** → `unknown` (escalates under ask, declines under decline). → `4222f97`

### R8 · The silent basket line
**Setup:** `item.size = 43`; basket of a size-43 decoy plus a silent second shoe.
**Result:** **ALLOW**, while the silent shoe alone escalated. Saying nothing beat lying. The return-window code already refuses this exact aggregation; the size rule had not been given the same treatment.
**Decision:** fix. → `da5e919`

### R9 · Self-attack: did the R8 fix break the property it was written for?
**Setup:** 4,000-basket monotonicity fuzz.
**Result:** **24 violations** — testing silence *before* a mismatch let an adversary soften a definite FAIL into a REVIEW.
**Decision:** negative evidence decisive first. Re-fuzz: **0/12,000**. → `da5e919`

### R10 · Liveness
**Setup:** unresolved step-ups, declined step-ups, starvation, restart-while-pending.
**Result:** a pending step-up **reserves nothing**; starvation is bounded by the window; pending step-ups survive restart. **No defect.** Corollary: because there is no reservation, safety must be enforced at admission — which is why the peak check at resolution exists.

### R11 · Mutation testing of the security core
**Setup:** 15 mutations to security-relevant predicates; then exhaustive per-occurrence mutation of all 9 rule outcomes.
**Result:** 14/15 then 9/9 killed. **One survived**: the period rule's `unknown`. Reachable — the schema declares `period_days` as `["integer","null"]`, so a platform-supplied mandate may carry a period rule with no window length.
**Decision:** behaviour already correct; test added. → `63b1cb8`

### R12 · Flaky test discovered while repeating the suite
**Setup:** run the suite five times.
**Result:** two property tests hard-coded an amount-integrity tolerance of **0.01** while the engine tolerates **0.02**. Only the rarity of a difference landing in that gap kept them green.
**Decision:** import the constant; pin the boundary explicitly. → `63b1cb8`

### R13 · Campaign Q — human approval as a security transition
**Setup:** raise a step-up, then re-deliver the same id at a higher amount / different merchant / different item, then have the customer approve.
**Result:** **all held.** Conflict detected, stored decision unchanged, the customer's answer binds to what they were shown, charges at the substituted amount or merchant refused.

### R14 · Campaign J — cross-run reuse
**Setup:** one mandate across N runs.
**Result:** **linear multiplication** — 10 runs put CHF 2,000 through a CHF 300/7-day cap.
**Mitigation established:** the agent does **not** control run boundaries; `POST /v1/scenario-runs` is the solution's call.
**Decision:** accepted limitation, now pinned as a test. → `40fd3e1`

### R15 · Campaign B — two workers, one checkpoint
**Result:** **2 charges for one authorization**, reproduced end-to-end.
**Decision:** accepted; this is why we say at-most-once per process, never exactly-once. Pinned. → `40fd3e1`

### R16 · External-auditor simulation
**Question:** where does the architecture depend on an assumption the protocol does not guarantee?
**Result:** three platform status fields govern whether a purchase may proceed; `authority_status` and `card_status_at_attempt` were read live, **`mandate.status` was read from a snapshot frozen at the run's first event and could never change.** A second event reporting `revoked` was approved.
**Decision:** read the status live (rules stay frozen); the report may only narrow. → `630768d`

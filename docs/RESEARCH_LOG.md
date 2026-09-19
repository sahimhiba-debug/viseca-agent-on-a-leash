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

### R17 · Phase 17 — cross-invariant attacks
**Question:** each invariant holds alone; does any PAIR of them open a gap the pair's members close individually?
**Setup:** nine attacks pairing invariants that interact — idempotency×revocation, idempotency×live status, policy snapshot×live status, duplicate×temporal window, duplicate×human×window, evidence×human approval, cross-run×fulfilment, provenance×merchant text, revocation×restart.
**Result:** all nine held. An event carrying WIDENED rules cannot override the run's snapshot; a suspected duplicate escalates and so cannot silently double-count; merchant text narrows in both directions.
**Decision:** no change. Recorded because a negative result on a mandated phase is still a result. → `310768a`

### R18 · The Final Question — what would a fresh researcher attack?
**Question:** given this repository and no knowledge of its history, where would an exceptionally capable stranger look first?
**Answer:** the newest security-critical code, and specifically the case its own documentation admitted was *"supported but unexercised"* — multiple overlapping period rules.
**Setup:** three nested caps (CHF 200/1d, 300/7d, 1000/30d), randomized amounts, timestamps over 35 days, ~45% forced into step-ups resolved in random order, 3,000 runs.
**Result:** **0 breaches**, windows filling to 199.99 / 299.95 / 956.28 against 200 / 300 / 1000 — tight, not over-conservative. The "unexercised" caveat was removed from three documents because it had become false.
**Decision:** no change; caveat retired. → `310768a`

### R19 · Phase 27 — a field you DELETE rather than forge
**Question:** the red team re-run on the premise that every previous fix is still broken. The old fixes held; what about the newest code?
**Result:** **a real hole.** `mandate.status` was read as `(event.get("mandate") or {}).get("status")` behind `if ... is not None`. Nothing here validates events against the official schema, where `mandate` and `mandate.status` are both REQUIRED — so deleting either switched the check off and a **revoked mandate produced ALLOW, minted an authority and charged.** Its two siblings, `authority_status` and `card_status_at_attempt`, already routed a missing value to `unknown`. Three status fields, two standards.
**Decision:** absence is a malformed event, not consent. Fixed, and the property asserted over the schema's own enums rather than for the one broken field: if any legal value of a required field stops the purchase, deleting that field must stop it too. Swept the rest of the surface — no other required field is more permissive when omitted. → `400307a`

### R20 · Phase 23 — is the quadratic actually fine?
**Question:** `docs/AUTONOMOUS_R_AND_D_FINAL_REPORT.md` claimed `peak_window_spend_chf` is "O(n²), fine at run scale, trivially reducible". Three unverified claims about the newest security-critical code.
**Result:** super-linear and close to quadratic — doubling ratios 3.45–4.02 over n=100→6,418 — but the constant ms/n² **declines** (66.6e-6 → 43.2e-6) rather than settling. Crossing the 8,000 ms deadline at **n ≈ 13,600**; the largest official scenario has **12** purchase attempts. *(First reported as 11,000 from a four-point fit; corrected by a seven-point run — see R24.)* Baskets are linear (20,000 lines = 54 ms). Pending step-ups never enter the window scan, which is what bounds the quadratic by approvals rather than by events.
**Found while measuring:** a SECOND quadratic that bites first — `live_worker._save_checkpoint` re-serializes the whole run on every event, so a 2,000-decision run writes 1.3 MiB per event. Disk, not CPU, is the binding constraint.
**Decision:** no optimization; the margin is ~900× in n. Claims replaced with measurements. *(The crossing figure in this entry was revised twice — see R24 and R25.)* → `d16392d`

### R21 · Is the invariant register true?
**Question:** the register maps every invariant to "the test that fails if you remove the mechanism". That column is the most load-bearing claim in the repository, and it was hand-maintained.
**Result:** all 33 citations resolved, but nothing had been checking. A rename would have rotted it silently.
**Decision:** machine-check it. Verified non-vacuous by injecting a bogus citation. What it cannot do is stated in the test: it cannot verify a cited test *exercises* the invariant it is filed under. → `e768750`

### R22 · Phase 31 — the claim audit, on the front page
**Result:** the README's most-read sentence was **false**: "decides ... never from merchant-supplied text". `facts.py` does read merchant text under whitelist patterns, and `WHAT_WE_REFUSE_TO_CLAIM.md` says so. The front page and the refusals document contradicted each other. Three test counts had also gone stale within one session (622 → 643 → 664, against a suite past 690).
**Decision:** corrected to the defensible claim (merchant text is read, in one place, and can only NARROW). Self-describing numbers are now checked against the things they describe — including every per-scenario replay row. → `11d71c1`

### R23 · Phase 32 — is the suite theatre?
**Setup:** 18 one-line edits to `src/wallet_control/`, each removing one protection, applied individually against the full suite.
**Result:** **18 killed, 0 survived** (the probe has since grown to 20 — see R26) — after the first run found **1 survivor**: widening the rolling window's start (`<` → `<=`) passed the entire suite. Not a safety hole (a wider window only blocks more), but nothing pinned which window the engine means.
**Decision:** the half-open boundary `(t−N, t]` is now a test. The probe ships as `scripts/run_mutation_probe.py` so an auditor can run it rather than believe it. → `7c792e9`

### R24 · Four points are not a trend — correcting R20
**Question:** R20's fit came from four measurements (n = 100…809). A seven-point run reaching n = 6,418 finished afterwards. Does it agree?
**Result:** **no, and R20 was wrong in its central claim.**

| n | 100 | 203 | 406 | 809 | 1,612 | 3,215 | 6,418 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ms/decision | 0.67 | 2.56 | 10.30 | 40.54 | 143.55 | 495.68 | 1,780.31 |
| ms/n² ×1e6 | 66.6 | 62.2 | 62.5 | 61.9 | 55.2 | 48.0 | 43.2 |
| doubling ratio | — | 3.85 | 4.02 | 3.93 | 3.54 | 3.45 | 3.59 |

R20 said the constant *"settles at ~66e-6"* and the ratios *"converge to 4.00"*. Neither is true. The constant **declines** — 66.6e-6 → 43.2e-6 — and the ratios fall from ~4.0 below n ≈ 800 to ~3.5 above it. The "convergence to 4.00" was an artifact of the fourth point's ratio happening to land on 4.00 with nothing after it.

Consequence: the deadline crossing is **n ≈ 13,600**, not 11,000. The error was conservative rather than dangerous, but it was stated with a precision four points cannot support.

**Decision at the time:** corrected in six places to "close to quadratic, constant declines, crossing at n ≈ 13,600". **That decision was itself wrong — see R25.**


### R25 · Isolating the cause — and correcting R24's correction
**Question:** R24 established that `ms/n²` declines but not WHY. Hypothesis: the decline is window saturation. At one purchase per simulated hour a 30-day window holds ~720, so past n ≈ 720 the expensive in-window `Decimal` additions stop growing while the cheap timestamp comparisons continue. **Prediction: a window large enough that nothing ever falls out should show a FLAT constant.**
**Setup:** identical workload, three window lengths — 1 day (saturates at n ≈ 24), 30 days (n ≈ 720), 10 years (never saturates).

| ms/n² ×1e6 | n=203 | n=406 | n=809 | n=1,612 | drift |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1-day window | 38.7 | 36.1 | 34.5 | 33.6 | 1.15× |
| 30-day window | 63.3 | 64.0 | 62.1 | 55.9 | 1.13× |
| **10-year window** | **62.9** | **64.1** | **62.8** | **64.0** | **0.98×** |

**Result:** hypothesis confirmed, cleanly. With saturation removed the constant is **flat** — the algorithm is **exactly O(n²)**, which is what R20 originally said about the shape. The 30-day curve is flat (~63e-6) *below* its saturation point and declines only *above* it, exactly where predicted. The 1-day window, saturating at n ≈ 24, is already down at 38.7e-6 by n = 203.

**Consequence — R24's published number was the wrong one to quote.** 13,600 came from a 30-day window at one purchase per hour: a single, *more favourable* configuration. The worst case is the non-saturating one, flat at ~63.5e-6, giving **n ≈ 11,200**. R20's original 11,000 was accidentally close to right, for the wrong reason.

**Decision:** publish **n ≈ 11,200 (worst case)**, with 13,600 named as the 30-day regime. Three passes at one number, two of them wrong, and both wrong ones are now documented in `tests/test_scale_limits.py` rather than quietly replaced — the failure mode was reading a trend off too few points, twice. → this commit

### R26 · Cross-invariant attack Y — a rule with nothing to check
**Setup:** Phase 3 pairing Y, decision ledger × malformed platform event. Three malformed events fed to a healthy run: a non-numeric amount, a garbage timestamp, and `items: []`.
**Result:** the first two raise and record nothing (fail-closed). **The empty basket was ALLOWED and recorded.** Pushed on it: against a mandate carrying four item restrictions, a CHF 400 purchase with no items satisfied three of them *vacuously* — nothing is outside the requested category, no name fails to match, nothing unrequested is present — and with no `item.size` rule it was **ALLOW under every uncertainty policy, `decline` included.** The strictest setting a customer can choose was not stricter.
**Class:** identical to the `mandate.status` omission (R19). A check switched off by deleting what it guards, needing no forgery — there a required field, here a required array. `minItems: 1` makes it malformed, and nothing here validates the schema.
**Decision:** fixed in two layers. `decision_engine` refuses an empty basket as a `source="safety"` hard failure (structural, not uncertain — which is why it overrides `uncertainty_policy`); `rules.py` answers `unknown` for any `item.*` rule with no items, so the vacuity is fixed where it lives and survives deletion of the engine check. Both are now mutants in the probe (18 → 20). All 45 official events carry items, so the replay cannot move. → this commit

### R27 · Cross-invariant pairings V, W, O, Q — all held
**V** authority expiry × retry: re-issuing an authority for an already-decided purchase returns the original expiry; a retry cannot extend the window.
**W** authority expiry × concurrent execution: 8 threads charging one authority → exactly 1 succeeded, 7 refused.
**O** one-shot fulfilment × cancellation: a second purchase naming a `cancelled` prior is still `already_fulfilled` — cancellation does not re-open a one-shot job.
**Q** fulfilment × merchant substitution: the job is recognised across a different merchant.
**Decision:** no change. Recorded because negative results on a mandated phase are still results.

### R28 · The vacuity sweep, and the claim the engine forgot to cross-check
**Question:** R19 (a deleted required field) and R26 (an emptied required array) are the same defect class — *absent evidence read as satisfaction*. Two instances is a coincidence; three is a pattern. So instead of waiting for the next one, sweep every rule field: make its input absent or empty and ask whether the rule answers `pass`.
**Result:** ten fields swept, **one vacuous pass left**: `session.integrity_risk`. Its input `recent_attempt_count_10m` is a claim the event carries *about itself*, and it was the one event claim this engine did not cross-check — while `billing_amount_chf` is recomputed from `amount × fx_rates`, `items_subtotal + delivery_fee` is checked against `amount`, and `card_id`/`mandate_id` are checked against the run.

**The attack needs one integer.** Four attempts inside one minute with a device change halfway:

| reported `recent_attempt_count_10m` | decisions |
| --- | --- |
| honest `0,1,2,3` | allow, allow, **block**, **block** |
| tampered `0,0,0,0` | allow, allow, allow, allow |

Two blocks became approvals because the purchase was asked how suspicious it was, and believed — while this run's own attempt log, the one duplicate detection already relies on, held all four.

**Decision:** cross-check against our own log, `max(reported, observed)`. `max` rather than replacement because the platform legitimately sees attempts we cannot: on the official corpus one event reports 3 where we observe 2, and taking our own count would *discard* real evidence. Monotone, so it can only raise risk. Measured before implementing: across all 45 official events `observed − reported` is **never positive**, so the replay cannot move — asserted as a test rather than hoped. Slow legitimate traffic (attempts 30 minutes apart) is not penalised. Probe 20 → 21. → this commit

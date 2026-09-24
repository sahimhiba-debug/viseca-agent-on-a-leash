# Final gate report

<!-- snapshot -->
> **SNAPSHOT — written 19 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

Adversarial verification of the frozen build. No features were added to pass it; two
defects it found were fixed, and one mechanism already present was made visible.

## 1. What was tested

**Counterexample battery (13 constructed attacks, not test-suite confirmations):**
FX misstatement · negative amount · delivery/parts arithmetic · merchant redirection at
execution · zero-width characters in an authorization id · unrequested extra item ·
merchant prompt injection · revoke-then-approve · concurrent revoke + charge · restart
after consume · mid-run policy widening · uncertainty-policy relaxation · conflicting
human resolutions.

**Standing suites:** full test suite, official 45-event replay, 133-case corpus, 17-case
adversarial matrix, 12 property invariants, stateful model, 26 failure-mode cases, 8
attack demonstrations, API smoke.

**Mobile:** 375×812, 390×844, 412×915, plus pathological content — a 66-character German
merchant name, an 88-character hyphenated item name, CHF 1'234'567.89, five simultaneous
block reasons.

**Determinism:** five full replays compared decision-by-decision, including reason codes.

## 2. What failed

| # | Finding | Severity |
| --- | --- | --- |
| **G1** | `items_subtotal + delivery_fee` was never cross-checked against `amount`. An event claiming a CHF 100 total whose parts summed to CHF 600 was approved against a CHF 400 ceiling. | real |
| **G2** | `StoredDecision.reason_codes` existed but was **never populated**. Every reader of the ledger — the audit timeline, and the UI re-rendering after a step-up — lost the explanation and could only report the bare decision. | real |
| **G3** | A pending step-up kept offering "Approve once" after the customer revoked. The backend was correct (it records such an answer as a block); the button was not. | UI |
| **G4** | Two block reasons rendered as incomplete sentences ("The return window"). | cosmetic |

Everything else held. **13 of 13 constructed attacks failed to break the build.**

## 3. What was fixed

- **G1** — extended the existing always-on `amount_integrity` guard to the other half of
  the same arithmetic. Five lines in a check that already verified
  `amount × fx_rate == billing_amount_chf`; not a new mechanism. All 45 official rows
  agree exactly, so a mismatch is an internally inconsistent event. Pinned as **I13**.
- **G2** — `record_decision` now stores the reason codes; `record_resolution` keeps the
  original reason and appends `customer_resolution`, because the reason a purchase was
  escalated is not erased by the answer to it. **This one fix closed three findings**, two
  of them raised earlier by the independent UX audit ("no reasons at all in the audit
  trail", "approving erases every explanation").
- **G3, G4** — UI only.

## 4. What remains risky

1. **Cross-run mandate reuse breaks the one-shot job invariant.** Reachable through the
   worker path; the demo avoids it by compiling a fresh mandate per run. Fixing it means
   re-keying the authoritative ledger from run to mandate — a scope change, not a patch.
2. **Single-use is process-local.** Two workers restoring one checkpoint can each consume
   the same authority once. We say at-most-once, never exactly-once.
3. **The step-up channel is unauthenticated** and records no `resolved_by`.
4. **Two rule fields are decided entirely by attacker-controlled text**
   (`order.return_window_days`, `item.size`). Not fixable inside the official rule
   vocabulary.
5. **The verdict split is reconstructed from reason codes on the refetch path** using a
   fixed set of safety field names. A new safety check must be added to that set.
6. **Our adversarial suites are our own thinking.** 133/133 and 17/17 are a sample, not a
   proof.

## 5. Explicitly outside the system boundary

- **The account's monthly limit.** Real data in `accounts.csv`; the official API exposes
  no account-scoped spend counter. Displayed marked *not enforced*.
- **Merchant truth** — size, return window, finality are claims we derive from text we
  cannot verify.
- **Agent identity** — the challenge removes it deliberately.
- **Total spending** — no mandate in the official rule format can bound it.
- **The payment rail** — the Viseca API has no payment step; `MockPSP` is ours.

## 6. Final measurements

| | value | vs. senior-review baseline |
| --- | ---: | --- |
| runtime (`src/wallet_control`) | **4875 lines**, 19 modules | 6,693 → 4875 (**−28%**) |
| research (`research/`) | 1837 lines, 6 modules | new package; moved, not deleted |
| tests | 6653 lines | — |
| UI | 572 lines, 1 file | — |
| classes (runtime) | 37 | — |
| module-level functions (runtime) | 81 | — |
| runtime dependencies | 4 | unchanged |
| dev dependencies | 3 | unchanged |

The runtime grew by ~50 lines during this gate (the arithmetic guard, the reason-code
plumbing, the verdict-split reconstruction) and shed 1,887 in the separation pass.

## 7. Final test count

**633 passed**, 0 failed, 0 skipped.

## 8. Final official replay

**45 events — 19 allow / 2 review / 24 block.** Unchanged across every pass of this
project. Determinism verified: five consecutive replays produced one distinct outcome
set, compared decision-by-decision including reason codes.

*A regression boundary, not a score. There are no official expected-decision labels.*

## 9. Final security matrix

| | |
| --- | --- |
| adversarial matrix | **17 / 17 defeated** |
| generated corpus | **133 / 133 held** |
| attack demonstrations | **8 / 8 held** |
| property invariants | **13** (I1–I13) |
| failure modes | **26 / 26** |
| counterexample battery | **13 attempted, 0 succeeded** |

## 10. Final mobile QA

| viewport | horizontal overflow | clipped | touch targets < 44px |
| --- | --- | --- | --- |
| 375 × 812 | 0 px, all 5 panels | none | none |
| 390 × 844 | 0 px, all 5 panels | none | none |
| 412 × 915 | 0 px, all 5 panels | none | none |
| pathological content | 0 px | none | none |

Full journey verified at phone width: compile → confirm (stamped) → run → 11 decision
cards → resolve a step-up (explanations intact) → revoke (6 cancelled, 0 stale approve
buttons) → audit (34 entries, plain language).

## 11. Final known limitations

The six in §4, plus: a cancelled first purchase makes a legitimate retry look like a
repeat (0 instances in the corpus); the audit timeline has no filter at ~34 entries; the
demo API has no authentication; state is in-memory by design.

---

**Can a senior engineer inspect this repository and trust that its complexity is
intentional?**

The runtime is 19 modules and 4875 lines, with a seven-file decision path that reads top
to bottom. A test asserts every shipped module is reachable from an entry point and that
no runtime module imports research. The two largest modules are long rather than complex,
and `SIMPLIFICATION_LOG.md` records why splitting either would reintroduce the defect
shape that caused six past vulnerabilities.

What we cannot claim is that it is finished. Six risks are open, four of them needing
either new authoritative state or a change the official rule vocabulary does not permit.
They are written down rather than discovered on stage.

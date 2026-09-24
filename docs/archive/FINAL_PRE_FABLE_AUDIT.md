# Final pre-freeze adversarial audit

<!-- snapshot -->
> **SNAPSHOT — written 19 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

Written as a hostile senior engineer trying to discredit this project during a live
demo. No new architecture; only defects fixed, tests added, claims narrowed.

**Recommendation: READY FOR INDEPENDENT AUDIT.** One finding was material and is
fixed. Nothing blocking remains. The rest of this document is the evidence, including
the things a judge can still legitimately attack.

---

## 1–6. Findings

| # | finding | severity | exploitable | reproducible | fix | regression test |
| --- | --- | --- | --- | --- | --- | --- |
| **F1** | **`customer_message` carried the engine's debug output to the platform** | **medium** | not a security hole — it cannot change a decision; it is a correctness and credibility defect on the official path | yes, every non-allow decision | plain prose; technical facts moved to `evidence`, where the spec puts them | `test_no_official_decision_leaks_engine_internals_to_the_customer` |
| **F2** | A rolling-window breach read identically to an oversized order | low | no | yes | the period breach now names the window and the figure allowed | `test_a_rolling_window_breach_does_not_read_like_an_oversized_order` |
| **F3** | Decision and the two displayed verdicts were never asserted consistent | low (latent) | no instance found | n/a — the UI renders them independently | invariant asserted: decision = stricter(policy, security) | `test_the_decision_is_always_the_stricter_of_the_two_verdicts` |
| **F4** | Suite unvalidated against 2 of the brief's 8 defect shapes | medium (process) | n/a | yes | run lock and already-resolved guard added as mutants | mutation probe 27 → 29 |
| **F5** | Demo script's "What NOT to say" predated the intent-fidelity campaign | low | n/a | yes | two claims added | — |

### F1 in full, because it is the one that mattered

`technical_details.md` shows `customer_message` carrying sentences — *"Please review
this purchase."* — and says to "show the reason and purchase details to the real
customer". What `live_worker` submitted was:

```
Declined: CHF 62.0 at Alpine Basket -- authorization.billing_amount_chf (fail):
projected 7-day spend=361.5 CHF (including this purchase); item.category (fail):
item_categories=['cosmetics', 'groceries'], outside requested set: ['cosmetics']
```

Internal field names, the engine's own `(fail)` vocabulary, and a Python list repr.

**Why eight previous audits missed it.** The demo UI was never affected — it renders
`reason_codes` through its own plain-language table and hides raw evidence behind a
"Technical evidence" disclosure. Every pass that looked at the screen saw polished
explanations. The official submission path, the one an actual customer would read,
had no such layer. *The polish existed exactly where we were looking*, which is the
most durable way for a defect to survive repeated review.

## Attacks that found nothing, listed so the negative result is on the record

**Trust chain.** Double-tapping approve five times: fully idempotent (4 approvals,
CHF 687.00 either way). Malformed, null, list-valued and wrong-case resolve payloads:
all fail closed (400/422). Unknown run and authorization ids: 404. Revoke: idempotent.
Changing your mind after approving: refused.

**Compiler**, with the brief's own term list — "only", "each", "one", "total", "per",
"under", "below", "at or below", negation, double negation, contradictions,
whitespace, case. Multiple amounts take the smaller and flag the ambiguity;
`at or below` stays `<=` while `under` is `<`; per-order and per-week are both
captured; whitespace and case are inert.

**Security objects.** Every module-level mutable in the runtime is a constant lookup
table except the demo registry (§7).

**Mobile**, 375×812 / 390×844 / 412×915, with a 123-character merchant name,
CHF 1'234'567'890.99, 25 line items and six simultaneous reasons: no horizontal
overflow, no clipped element inside any decision card, zero interactive elements below
the 44px touch minimum. The step-up card states its own scope — *"You are approving
this one purchase only. Not a standing exception."*

## 7. Remaining limitations

Unchanged in substance. Two sharpened by this pass:

1. **The compiler is the trust boundary** and it is phrase patterns. Coverage of
   *kinds* of restriction is checked; correctness of a *recognised* phrase is not.
   Found in this pass and not fixed: *"Buy groceries for CHF 50 or less. Actually make
   that CHF 500."* keeps CHF 50 and does not mention that the correction was ignored.
   The direction is safe (stricter than intended); the silence is the limitation.
2. **The demo run registry `api._RUNS` is unbounded** — 8.7 KiB per run, ~8.5 MiB per
   thousand, cleared by `POST /api/demo/reset`. **Deliberately not patched at freeze:**
   evicting a run a judge is halfway through would be a worse failure than the leak.
3. Merchant-claimed facts; cross-run reuse; at-most-once per process; unauthenticated
   step-up; no total-spend bound; unenforced account limit; undocumented platform
   behaviour on a missed deadline. All in `WHAT_WE_REFUSE_TO_CLAIM.md`.

## 8. Demo risks

| risk | mitigation |
| --- | --- |
| A judge asks who can answer a step-up | **Say it first.** No authentication, no `resolved_by`. It is in the demo script's "What NOT to say" list as a claim to volunteer rather than concede. |
| A judge runs the same scenario twice and sees the budget reset | True and disclosed at confirmation time — the window is per shopping session. Show the open question. |
| A judge reads `'sporting_goods'` in the compiled rules | A machine identifier in customer-facing guidance. Cosmetic, not fixed at freeze. |
| An attack card shows **HOLE** | The demo script already says: stop and say so. It is a real regression, not a glitch. |
| A judge asks "is this staged?" | `attack_demo.py` imports the same `decision_engine` and `MockPSP` as the replay. Offer to change a number live. |

## 9. The ten questions a senior judge could ask

1. **"Your compiler is regexes. What happens when it mishears?"** — It did, six ways,
   and we found them: a weekly budget compiled as a per-order ceiling. Now fixed, and
   restrictive language with no rule is named back to the customer before they confirm.
2. **"So you enforce intent?"** — No. We enforce the compiled policy and show the
   customer both it and what we could not represent. Three concepts are inexpressible
   in the official vocabulary: an overall total, an end date, any quantity.
3. **"Is exactly-once payment guaranteed?"** — No. At-most-once, per process. Two
   workers restoring one checkpoint each charge once. It is in the UI's own
   "What we do not claim" list.
4. **"Do you cap total spending?"** — No mandate in the official rule format can.
   `scope` is `purchase` or `period` and the spec closes the set.
5. **"Your 882 tests could all be trivial."** — `python3 scripts/run_mutation_probe.py`
   breaks 29 security mechanisms one at a time; all 29 are caught. It found two real
   gaps on its first runs.
6. **"Is the replay a score?"** — No. The pack ships `contains_expected_decisions:
   false`. 19/2/24 is a regression boundary, and it is conditional on our own reading
   of five English sentences.
7. **"What about a compromised merchant?"** — Merchant text is read in one place,
   under whitelist patterns, and can only narrow. We do **not** claim to detect a
   merchant lying in the narrowing direction; that is the largest real exposure here.
8. **"Can the customer stop it mid-run?"** — Yes, revocation reaches a purchase still
   awaiting their answer, which took a run-level `_revoked_at` to get right — a sweep
   cannot cover a record that does not exist yet.
9. **"What's actually distinctive, versus table stakes?"** — Table stakes: allow/block,
   step-up, rolling limits, prompt-injection resistance, audit log, mobile UI.
   Distinctive: a mutation probe that breaks the wallet on purpose, an invariant
   register machine-checked to cite tests that exist, self-describing numbers that
   fail the build when stale, and a rejected mechanism kept in the tree with the
   attacks that killed it.
10. **"What would you fix with another week?"** — The compiler. Coverage of restriction
    *kinds* is checked; correctness of a recognised phrase is not, and that is where
    the next defect will be.

## 10. Claims we can safely make

* Merchant text is read in one place and can only **narrow** a decision.
* A confirmed mandate can only be **tightened**.
* Within one process, an approved authorization can be charged **at most once**, at a
  single point, under an atomic compare-and-set.
* Revocation reaches a purchase still awaiting the customer's answer.
* A customer's answer binds to the purchase they were shown — amount, merchant and
  basket.
* No window breach in 1,800 optimiser trials; the window fills to exactly the cap.
* Deleting a required field never buys a more permissive decision.
* `customer_message` contains no engine internals.

## 11. Claims we must NOT make

* That we enforce the customer's **intent**. We enforce the compiled policy.
* **Exactly-once** payment, or exactly-once across processes.
* That we **cap total spending**, or enforce the account's monthly limit.
* That we **detect merchant lies**.
* That the rolling window holds **across runs**.
* That anything here is **formally proved**. Everything is measured.
* That our adversarial suites are **exhaustive**, or that the mutation probe covers
  mechanisms nobody thought to mutate.
* That the step-up channel is **authenticated**. It is not.

## 12. Recommendation

**READY FOR INDEPENDENT AUDIT.**

One material finding (F1), fixed and pinned. Four smaller ones, fixed. Two limitations
deliberately documented rather than patched at freeze, with the reasoning stated. No
blocking finding remains.

The honest summary a hostile reviewer should leave with: the security core held every
attack in this pass, and the defect that survived eight audits was in the one place
nobody was looking — the explanation sent to the customer on the path we do not
demo.

# Safety, fairness and liveness in delegated agentic purchasing

`8340940` (647 tests) → `da5e919` (**656 tests**). Replay **45 / 19 / 2 / 24**, unchanged.

## 1. Executive summary

The three properties are **not equally implied by the customer's delegation**, and
conflating them is how a wallet ends up enforcing preferences its customer never
expressed.

| property | required by the delegation? | status |
| --- | --- | --- |
| **Safety** — never authorize a history that violates a stated bound | **yes, explicitly** — it is what the customer wrote | **holds**, empirically, across every experiment run here |
| **Fairness** — who gets funded when valid purchases compete | **no** — the customer stated a bound, not an allocation policy | greedy FCFS; **ambiguous, and we decline to resolve the ambiguity** |
| **Liveness** — a compliant purchase eventually succeeds | **partially** — bounded starvation is the cap working | **no defect found** |

One new defect (**C5**), one property discovered and named (**basket monotonicity**),
and one self-inflicted regression caught by fuzzing my own fix.

## 2. New finding — C5, the silent line

`item.size` considered only the lines that *stated* a size and ignored the silent ones.

```
customer: "Replace my road-running shoes in size 43."

one shoe, size 43                    -> ALLOW
one shoe, size 38                    -> BLOCK
one shoe, size not stated            -> REVIEW
size-43 decoy + silent second shoe   -> ALLOW      <-- the attack
decoy + explicit size 38             -> BLOCK
```

**Saying nothing beat lying.** An explicit wrong size was caught; silence was not, as
long as one line carried a correct claim. And a *less* informative basket got a *more*
permissive answer.

The return-window logic already refuses exactly this aggregation, in as many words —
*"a silent item's terms are unknown, not whatever the other line said."* The size rule
had never been given the same treatment. **The bug was an inconsistency between two
rules written by the same reasoning.**

### The fix broke the property it was written for

Testing for silence *before* testing for a mismatch let an adversary soften a definite
FAIL into a REVIEW by appending an evidence-free line: **24 monotonicity violations in
a 4,000-basket fuzz.** Negative evidence must be decisive first. After correction:
**0 in 12,000.**

## 3. The property: basket monotonicity

> **Adding a line to a basket must never make a decision more permissive.**

Not a rule the customer wrote — a property the *evidence model* must have, because the
alternative is that an agent improves its odds by submitting **less** information. Now
fuzz-tested across random mandates, baskets and added lines.

## 4. Safety analysis

> No legal sequence of future events may cause the final approved history to violate an
> authoritative spending bound.

Evidence: 3,000 randomized lifecycle traces mixing propose / resolve(allow) /
resolve(block) / revoke / restart / retry / charge, asserting the invariant **after
every transition** — 0 violations. Plus the earlier boundary, permutation and
concurrency batteries. **Empirical, not proven.**

## 5. Fairness analysis

The wallet implements **greedy first-come-first-served admission control** — textbook,
and with the textbook weakness: FCFS makes no fairness guarantee, and max-min fairness
or randomised admission exist precisely to address it.

On SCEN0001, 300 arrival orders produce **14 distinct approved sets**. Different
purchases get funded depending on who arrives first.

**We decline to fix this**, and the reason is not difficulty:

> The customer said *"≤ CHF 300 across any seven days."* That is a **bound**, not an
> allocation policy. Choosing max-min fairness, reservation or randomised admission
> would require knowing which purchases they prefer — and they never said. Inventing
> that preference is exactly the unsupported inference this project refuses elsewhere.

**Classification: protocol ambiguity, not a defect.** Safety is unaffected: every
ordering respects the bound.

## 6. Liveness analysis

| question | answer |
| --- | --- |
| Does an unresolved step-up reserve capacity it never spends? | **No.** A pending purchase is not approved and consumes nothing. |
| Does a declined step-up free capacity? | It never took any. |
| Can a compliant purchase be blocked forever? | **No** — starvation is bounded by the window. The same purchase succeeds once it rolls. |
| Does a pending step-up survive restart? | Yes, and it resolves correctly. |
| 40 daily CHF 150 purchases under CHF 300/7d | 12 allowed, 28 refused — the cap working, not a defect. |

**No liveness defect found.** And the first row is load-bearing: because the protocol
requires a paused purchase not to count, **there is no reservation** — which is
precisely why safety must be enforced at admission, and why the peak-window check at
resolution exists.

## 7. C4 semantic audit — the rest of the class

Thirteen absent/inapplicable/conflicting cases across every rule. One inversion (C5).
The others were already correct: `merchant.familiar` → unknown, `item.unrequested_present`
with no category rule → unknown, period projection missing → unknown, unrecognised field
→ unknown, empty categories and empty baskets unreachable (`minItems: 1`), conflicting
sizes → fail, `merchant.category` absent → fail-closed.

## 8. Prior art

FCFS and greedy admission control, max-min fairness, starvation, sliding-window rate
limiting: all textbook. Nothing here is novel computer science and none is claimed.
What is specific is that **two rules in the same engine, written from the same
reasoning, disagreed about how to treat a silent line** — and that the disagreement was
exploitable.

## 9. Fixes, tests, performance

| | |
| --- | --- |
| fix | `rules.py` — `item.size`: mismatch decisive, then silence → unknown |
| tests | +9 (656 total): `test_evidence_monotonicity.py` (8) and a lifecycle fuzz |
| replay | **45 / 19 / 2 / 24**, unchanged |
| performance | 14.6 ms per full 45-event replay |

## 10. Claims we refuse to make

- **Not formally proven.** Everything is empirical: 12,000 monotonicity baskets, 3,000
  lifecycle traces, 4,000 optimizer strategies, exhaustive small permutations. No proof
  was constructed.
- **Not fair.** We do not claim any allocation fairness, and we deliberately did not
  build it.
- **Not order-independent.** Retracted previously and still retracted.
- **Not exercised by official data.** C5 is constructed from official *semantics*; the
  one official mixed-size basket is filtered out by category.
- **Not a complete evidence audit.** Thirteen cases across the rules that exist today. A
  new rule field could reintroduce the same inversion, and only the monotonicity fuzz
  would catch it.

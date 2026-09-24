# C1 second-order security audit — authority-gated counterfactual disclosure

<!-- snapshot -->
> **SNAPSHOT — written 19 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

# CONCLUSION: **REJECT**

Not because the idea is uninteresting, but because three independent measurements
each falsify it on their own, and together they falsify the premise.

> **The question:** does controlling what an autonomous agent learns about the wallet's
> decision function constitute a meaningful security boundary?
>
> **The answer, for this system: no** — and the reason generalises.

Research only. **No code changed.** 633 tests, replay 45/19/2/24 at `ccd28e6`.

---

## 1. Reframing the concept

The reframe was the right instinct: treat disclosure as a second authorization decision,
independent of the transaction decision.

```
TRANSACTION AUTHORIZATION   may this purchase proceed?
INFORMATION DISCLOSURE      what may the agent learn about why not?
```

Held that way, C1 becomes testable rather than merely appealing. It then fails three
tests.

## 2. Disclosure threat model

The adversarial agent may submit repeated proposals, vary one field at a time, observe
explanations, infer thresholds, and optimise toward passing. Against that model, the
concrete questions are: **can repeated explanations reveal the policy, and does that
help more than what the agent can already do?**

## 3. The counterfactual oracle attack — measured

**Test A — is the wallet already an oracle without explanations?**

Binary search on the amount ceiling using only the allow/block bit:

```
found ceiling ~CHF 400.00 in 17 queries
a counterfactual would give it in 1   ->  ~17x speedup
```

So explanations do accelerate inference. That is real, and on its own would argue
*for* C1.

**Test B — does the agent need to infer at all?**

For the fabricable fields — the ones C1 exists to protect — no:

```
customer requires   agent claims "returns accepted within 90 days"
      >= 7 days  ->  ALLOW
     >= 14 days  ->  ALLOW
     >= 30 days  ->  ALLOW
     >= 60 days  ->  ALLOW
     >= 90 days  ->  ALLOW
```

**A single hard-coded plausible claim clears every realistic customer threshold with
zero knowledge of the policy.** The agent does not infer the threshold; it saturates
past it. Withholding the counterfactual protects a channel the attacker has no reason
to use.

The same holds for size: `"size 43; size 42; size M"` passes whichever is required.

*(The plausibility cap is not useless — `9999 days` is rejected as implausible and
becomes `unknown` → review. But `90 days` is entirely plausible and beats every
realistic requirement, so the cap does not close this.)*

**Test C — where disclosure works, is it harmful?**

For the verifiable fields, learning the threshold produces **compliance, not evasion**.
Told *"a price ≤ CHF 400 would satisfy this"*, the agent's only way to use that is to
propose CHF 399 — which is exactly what the customer asked for. An attacker that lowers
its price has stopped attacking.

### The inversion

| | disclosure dangerous? | does the agent need it? |
| --- | --- | --- |
| **fabricable facts** (return window, size, item name) | yes | **no — it saturates** |
| **verifiable facts** (price, merchant history, category, basket) | **no — satisfying them is compliance** | yes, but harmlessly |

**The two halves never overlap.** C1 defends the cell that is empty.

## 4. Authority-aware disclosure — and the corrected principle

The first audit proposed *who controls the fact* as the criterion. That is **wrong**, and
this is the most useful thing this review produced.

The correct axis is not authority but the pair **(fabricable, compliance-inducing)**:

| | fabricable | compliance-inducing | disclose? |
| --- | --- | --- | --- |
| price, category, basket, merchant history | no | **yes** | **safe** — knowing it produces the behaviour the customer wanted |
| return window, item size, item name | **yes** | no | irrelevant — the agent saturates instead of asking |
| **duplicate window, session velocity** | **no** | **no** | **the only genuinely harmful case** |

Lower authority does **not** imply "hide". A merchant-controlled fact we could verify
externally would be safe to disclose; an agent-controlled fact that is genuinely
constrained (the price actually paid) is safe.

## 5. Information leakage — what actually leaks today

Only one class survives the filter above: **our own safety heuristics.** They are
unfabricable (we observe them) *and* evadable without compliance (wait longer).

Two current leaks, both real:

```
AU0036  order.duplicate_suspected: same merchant and basket as AU0035 ... 0:25:00 apart
AU0029  session_integrity_risk=true (2 other attempts in the last 10 minutes)
```

The second names the velocity window outright. Knowing "10 minutes" lets an agent space
attempts at 11 minutes and evade it **while changing nothing real**. That is the shape
C1 was looking for — and it is a two-line hygiene fix, not a mechanism.

*Self-disclosure: our own economic-envelope research used exactly this evasion, spacing
purchases 61 minutes apart to step outside the 60-minute duplicate window. We found the
attack by committing it.*

## 6. Human vs agent disclosure — and why it is moot here

The distinction is sound in principle: the human is the authority whose money is at
risk and should receive everything; the agent is the constrained actor and should
receive the minimum.

**But in this challenge the agent never receives our explanation at all.**

> *"The supplied simulator provides the shopping agent's proposed purchases; your
> solution provides the independent trust and control layer."*

The flow is `simulator proposes → your solution decides → record the result`. We submit
`reason_codes`, `customer_message` and `evidence` to the **platform**, and the spec is
explicit about the intended reader: *"Show the reason and purchase details to the real
customer."* There is no documented channel returning our reasoning to the agent.

So in the judged configuration the oracle is **not reachable**. In a deployed card
system a decline reason does reach the merchant — so the concern is real in production
and hypothetical here. Building a defence for an unreachable channel and demoing it as
a security boundary would be dishonest.

## 7. Safe counterfactuals — are all six properties necessary?

Of the six proposed: feasibility, authoritative evidence, non-fabricability, non-sensitive
disclosure, minimality, determinism —

- **minimality** and **determinism** are properties of a good explanation, not of safety;
- **feasibility** and **authoritative evidence** collapse into the compliance-inducing column above;
- **non-fabricability** is the one that looked load-bearing and is not, per §3B;
- **non-sensitive disclosure** is the only survivor, and it reduces to §5: do not publish the parameters of your own heuristics.

Six properties collapse to one, and that one is hygiene.

## 8. Minimal disclosure

Worth stating because it is the residue worth keeping: for a safety heuristic, prefer

> *"This looks like an order you already placed."*

over

> *"…same merchant and basket as AU0035, 0:25:00 apart."*

The first tells the customer what they need. The second tells anyone reading it the
window. **This is already how the UI renders it** — the parameter survives only in the
technical evidence string.

## 9. Information-theoretic angle

Framed as bits: the allow/block bit yields ~1 bit per query; the amount ceiling took 17.
A counterfactual yields the threshold in one — call it ~17 bits at once. Genuine
acceleration.

But the measure that matters is not bits revealed, it is **bits the attacker needs**.
For fabricable predicates that number is **zero** (saturate). For compliance-inducing
predicates, the bits are ones we are happy for it to have. A disclosure-level ladder
(NONE / GENERAL / SPECIFIC / COUNTERFACTUAL) would be well-formed and would be
regulating a quantity nobody needs.

## 10. Attacking the idea itself

| falsifier | answer |
| --- | --- |
| Just ordinary fraud prevention? | No. |
| Just prompt-injection defence? | No. |
| Just explainable AI? | **Substantially yes** — counterfactual explanation and explanation-as-attack-surface are both established (Wachter; DualCF; EXTree/KNOW; AWS IAM remediation). |
| Just access control / capability security? | The computation, yes (IAM policy simulators). |
| Already solved by existing protocols? | Not in agentic payments — but see the next row. |
| **Does it matter for agentic commerce?** | **Not demonstrably.** §3B: the attacker saturates. §6: the channel does not exist here. |
| Does the official challenge support it? | **No.** The agent never receives our explanation. |

Per the mission's own instruction — *"if the answer is mostly yes, reject C1"* — the
answer is mostly yes.

## 11. The demo requirement, and why it cannot be met honestly

The required beat was *"the wallet refuses to become an oracle."* To stage it we would
have to show the agent exploiting an explanation. We would have to **invent the channel
that delivers it**, because the challenge has none, and we would have to show the agent
*inferring* a threshold when the measured behaviour is that it would saturate instead.

That is a demo of a defence against an attack we constructed for the demo. It fails the
standing rule: *do not create a fake attack.*

## 12. Final decision

# REJECT

**What is rejected:** authority-gated counterfactual disclosure as a security mechanism
or a signature differentiator.

**What survives, and its true size:** do not publish the parameters of the wallet's own
safety heuristics. Two evidence strings (`0:25:00 apart`, `in the last 10 minutes`).
**Defence in depth against an unreachable channel — hygiene, not a mechanism.** We are
not implementing it as a feature and will not present it as one. It is recorded here and
in `THREAT_SPACE.md`.

**What the review produced that is worth keeping:**

1. **A corrected principle.** The first audit's criterion — *who controls the fact* — is
   wrong. The axis is (fabricable, compliance-inducing), and the two dangerous halves
   never overlap.
2. **A measured negative result.** A plausible saturation claim beats every realistic
   customer threshold with zero policy knowledge. That is a finding about *our rule
   vocabulary*, and it strengthens the existing documented limitation that
   `order.return_window_days` and `item.size` rest on nothing but merchant text.
3. **A general statement**, offered as reasoning rather than proof:

> Confidentiality of a decision function is not a useful security boundary when every
> predicate is either genuinely binding — so learning it produces compliance — or
> fabricable — so the attacker saturates rather than infers. Obscurity pays only for
> predicates that are unfabricable *and* evadable without compliance. In this system
> that is exactly two: the duplicate window and the session-velocity window.

## What we refuse to claim

- **Not** that explanation channels are safe in general. In a deployed card system the
  decline reason does reach the merchant, and there the analysis would differ.
- **Not** that we have proven obscurity worthless — only that in *this* rule vocabulary,
  against *this* threat model, on *this* data, it buys nothing we could demonstrate.
- **Not** that saturation is unbeatable. Verifying merchant claims against an
  authoritative source would beat it; the official API offers no such source.
- **Not** that the 17× inference speedup is unimportant in other settings. It is real; it
  is simply dominated by a cheaper attack here.

---

## Recommendation

**Add nothing.** The product is coherent, the differentiator already shipped (two verdicts
from one authority-tagged pass), and this review's contribution is a negative result
plus a corrected principle — which is a legitimate outcome of research and a better story
than a mechanism defending an empty cell.

If there is appetite for the two-line hygiene change to the evidence strings, it belongs
in a cleanup, not in a demo.

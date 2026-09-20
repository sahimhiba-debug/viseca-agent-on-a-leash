# Final agentic audit

Is this credible to a senior AI jury? Assessed by attacking the agent, not describing it.

---

## 1. A definition, before a claim

| capability | before this phase | after |
| --- | --- | --- |
| **A** deterministic workflow automation | yes | yes |
| **B** search / planning | **no** — sorted by price, took the top 5 | **yes** — plans against an explicit `Mission`, filters unavailable stock, substitutes |
| **C** adaptive behaviour | partial — one rule | **yes** — an ordered strategy ladder |
| **D** tool use | no | no — it reads a catalogue; that is not tool use and is not claimed |
| **E** environment feedback | yes | yes |
| **F** goal-directed replanning | **no** — no goal existed | **yes** — replans toward the `Mission`, not toward the last basket |
| **G** uncertainty handling | **no** — gave up blindly | **yes** — distinguishes "I can fix this" from "only you can" |
| **H** autonomous stopping | partial | yes — success, handoff, or bounded exhaustion |
| **I** policy-aware adaptation | partial | yes — acts on constraint class without a threshold |
| **J** model-based reasoning | no | **no, deliberately** — §3 |

## 2. The evidence that forced the rebuild

The old agent's entire brain was `revise()`: drop the most expensive line, else swap
for the cheapest. Run against the nine adversarial episodes:

```
1 cheapest item unavailable        -> dropped the most expensive line
3 one item must be removed         -> dropped the most expensive line
4 removal creates a new violation  -> dropped the most expensive line
5 merchant rejected                -> GIVES UP
6 return policy uncertain          -> GIVES UP
7 unrequested item in basket       -> GIVES UP
8 security REVIEW                  -> GIVES UP
9 no reason given                  -> GIVES UP
10 single line, no substitute      -> swapped to the cheapest
```

**Five of nine handled by giving up.** A senior AI engineer would need one look. The
gap was never "no LLM" — it was that there was no planner.

After the rebuild, all nine are handled: five replanned, four **escalated to the
customer**, which is the correct answer for a constraint no basket change can fix.
Giving up and handing back are different outcomes, and collapsing them was the
original design error.

## 3. Why there is still no model in the loop, and why that is the stronger position

The planner is now **injectable** (`Planner(plan=…, replan=…)`) precisely so the
architectural claim is testable. A model would slot in there, outside the authority
boundary.

We do not ship one, for three reasons that survive hostile questioning:

1. **`technical_details.md` requires a predictable response when the model is
   unavailable.** A network call in the judged path breaks that.
2. **Reproducibility is a jury criterion we win outright.** The agent episode is
   byte-identical across runs.
3. **Proving the seam is stronger evidence than one successful live call.**
   `tests/security/test_agent_planner_boundary.py` substitutes planners far worse than
   any real model — one proposing CHF 150,000, one hallucinating items, one raising on
   every call, one returning garbage, one repeating a rejected basket forever — and in
   every case the wallet approves nothing and moves no money.

That is the claim a model-based competitor cannot make about their own system.

## 4. What a senior AI engineer would still say is missing

Honestly: **tool use and genuine natural-language reasoning.** The agent reads a CSV
catalogue and applies an ordered ladder. It does not search a real web, negotiate,
compare across merchants on quality, or reason about substitutions semantically
("oat milk is a fine replacement for whole milk").

We do not claim any of those. The smallest addition that would materially change this
is a model-backed `Planner` behind the same seam — already possible, deliberately not
in the judged path.

## 5. The property that replaced a bad test

An earlier test asserted the agent settles **CHF 5 below** the ceiling, as proof it had
not extracted the limit. That oracle was wrong: it measured how *weak* the planner was.
A better planner substitutes rather than drops and therefore converges **closer** to
the boundary while being strictly better shopping — the browser agent now lands on
CHF 119 against a CHF 120 limit.

The honest test runs the same agent against **two different secret ceilings** and
requires its opening basket and every revision to be identical until the wallet's own
answers diverge. An agent using the number would aim differently from the first
proposal. This one cannot — a property of the interface, not of the planner.

The UI copy was corrected at the same time: it claimed the agent "stopped well below"
a limit while displaying CHF 119 against CHF 120.

# Limitations audit

Five known limitations, each asked: **can we close it safely now?** Two were
narrowed. Three cannot be closed and are bounded precisely instead.

---

## 1. Economic scope — what each scope actually is

The rule vocabulary is a closed set: `_ALLOWED_SCOPES = {"purchase", "period", None}`.
There is no mandate, customer, account or card scope to express.

| scope | expressible? | stored where | authoritative where | survives a new run? | agent can reset? |
| --- | --- | --- | --- | --- | --- |
| **per purchase** | **yes** (`scope="purchase"`) | the rule | the engine, every decision | n/a — stateless | no |
| **per period** | **yes** (`scope="period"`, `period_days`) | `RunState._approved_spend` | the engine, per run | **no — resets** | not within a session |
| per mandate | **no** | — | — | — | — |
| per run | implicit — it is where period state lives | `RunState` | the engine | no | no |
| per customer | **no** | — | — | — | — |
| per account | **no** | `accounts.csv` exists, no endpoint | nowhere we can read | — | — |
| per card | **no** | — | — | — | — |

### The 60-purchase result, settled

A pre-jury attack proposed the same CHF 108 basket sixty times and all sixty were
approved — CHF 6,480 under a mandate whose headline number is CHF 120. **This is not
a bypass.** The mandate said *"keep each **order** at or below CHF 120"*; sixty
orders of CHF 108 satisfy it; no rule in that mandate is one a *sequence* could
violate.

The control settles it. Same engine, same agent, same attack, one extra clause —
*"keep the total across any seven days at or below CHF 300"* — and the sixty
proposals become **2 approved, 58 blocked, CHF 216**. The engine never changed. The
mandate did. **CLOSED as a demo-mandate issue; no engine change.**

## 2. Cross-run aggregation — **cannot close safely**

Measured exactly:

- **within** one session: 12 errands → CHF 216, cap CHF 300 → **bounded**
- **across** 10 sessions: → **CHF 2,160** against the same stated CHF 300/7 days

**Why not closed.** Three reasons, none of which is "impossible":

1. The platform's own scope is the run — `technical_details.md`: *"context | Spend
   and recent authorization information from **this run**"*.
2. A cross-session ledger was built and attacked in an earlier campaign
   (`research/mandate_ledger_prototype.py`): two concurrent sessions both approved
   against the same remaining budget and the losing write vanished. A missing ledger
   file is also indistinguishable from a mandate that has never spent — fail-open.
3. Closing it means moving spend state out of `RunState`, which is a redesign of the
   frozen core for a bound we could not then hold under concurrency.

**We do not claim it is impossible.** `POST /v1/team/reset` clears *"your team's
mandates, runs, decisions, and event"* state, so the platform holds decisions
team-scoped spanning runs, and `GET /v1/authorizations` exposes them. Their shape is
under-documented, we cannot verify it offline, and we chose not to rely on it.
**A choice under uncertainty, not a protocol limit.**

**Newly disclosed on screen.** The delegation panel said the window *"re-opens"* —
true of time, silent about sessions. It now lists *"Spending across separate errand
sessions — the CHF 300 counter starts again in each one"* under what the customer's
words do **not** limit.

## 3. Merchant evidence — **cannot close**

Return windows, sizes and finality are merchant claims from text we cannot verify.
The enforceable property is narrower and tested: merchant text can only ever
**narrow** a decision, extraction is one whitelisted regex per fact over
NFKC-normalised input, and injection in the description cannot widen anything.

A plausible lie still beats us: *"returns accepted within 90 days"* satisfies every
realistic threshold with zero knowledge of the policy. **No fix inside this
protocol.** Bounded, disclosed, not claimed away.

## 4. Step-up identity — **cannot close**

The wallet knows a step-up was answered; it does not know *who* answered. There is
no authentication in the demo API and no identity in the official protocol at this
point. What *is* enforced: the answer binds to the exact purchase shown, it is
scoped to that one authorization, it cannot be flipped afterwards, it cannot
survive revocation, and it cannot breach the rolling window.

**Never say** "the customer approved it" as a security property. Say "the answer is
bound to this purchase and to nothing else."

## 5. Process-local at-most-once — **cannot close**

One approval yields at most one charge, by construction: the execution lifecycle
lives on the decision record, so "every approved decision has exactly one lifecycle"
is structural rather than checked. Eight concurrent charges produce one.

**Not exactly-once, and not across processes.** Two workers restoring the same
checkpoint can each consume the same authority once. Closing that needs a shared
transactional store this project does not have.

## 6. The ALLOW/BLOCK oracle — **irreducible**

Any system answering yes/no is one. Priced rather than denied: ~12 probes and
CHF 531 in kept purchases to recover a CHF 137 ceiling. Our planner does not probe —
it minimises price within a coverage tier, settling CHF 7.50 against that same
hidden CHF 137 on its first proposal — but that is a property of **our** planner,
not of the interface.

---

## Summary

| limitation | closable now? | what changed this pass |
| --- | --- | --- |
| repeated per-order purchases | **yes, at the mandate** | demo mandate now paces; engine untouched |
| per-session spend reset | **no** | now **disclosed on screen** |
| cross-run aggregation | **no** | boundary measured exactly (CHF 2,160 / 10 sessions) |
| merchant evidence | **no** | unchanged; bounded and disclosed |
| step-up identity | **no** | unchanged; wording rule stated |
| exactly-once across processes | **no** | unchanged |
| the decision oracle | **never** | priced, not denied |

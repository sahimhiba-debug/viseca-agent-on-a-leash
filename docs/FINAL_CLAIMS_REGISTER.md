# Final claims register

Every claim we would make in a pitch, classified. Five classes:

**PROVEN BY IMPLEMENTATION** — a named test fails if it stops being true.
**SUPPORTED BY EXPERIMENT** — measured, but the measurement is a sample.
**DESIGN INTENT** — a deliberate choice, arguable, not a fact about behaviour.
**LIMITATION** — true and unflattering; say it before you are asked.
**DO NOT CLAIM** — unsupported by evidence. Saying it loses the room.

---

## The wallet

| claim | class | evidence |
| --- | --- | --- |
| The agent proposes; the wallet decides | **PROVEN** | `test_runtime_boundary`, `test_NO_POLICY_BYPASS` |
| An approved purchase is charged at most once, per process | **PROVEN** | 8 concurrent charges → 1; `test_execution_atomicity` |
| Merchant text can only narrow a decision | **PROVEN** | `test_I7_*`, `test_prompt_injection` |
| Revocation reaches a purchase awaiting the customer | **PROVEN** | `test_F1*`, `test_revocation_end_to_end` |
| A customer's answer binds to the purchase shown | **PROVEN** | `test_human_consent_binding` |
| Deleting a required field never buys permissiveness | **PROVEN** | `test_required_field_omission` |
| The platform's echoed policy is checked, not adopted | **PROVEN** | `test_any_echoed_difference_fails_closed` |
| Exactly-once payment | **DO NOT CLAIM** | at-most-once, per process |
| We cap total spending | **DO NOT CLAIM** | no rule in the vocabulary can |
| We enforce the account's monthly limit | **DO NOT CLAIM** | real data, no endpoint |
| Cross-session limits are enforced | **LIMITATION** | CHF 2,999 vs CHF 300 measured; disclosed at confirmation |
| Cross-session enforcement is impossible under the protocol | **DO NOT CLAIM** | team-scoped records exist; shape under-documented |

## The agent

Everything in this section was re-derived against `research/planning_benchmark.py`,
an eleven-episode benchmark written before the agent was changed. Four rows moved
class as a result — three up, one **down**: "handles nine adversarial episodes" was
listed as PROVEN and is now SUPPORTED, because eleven small synthetic worlds is a
diagnostic sample and calling a sample proof is the mistake this register exists to
prevent. Three new DO NOT CLAIM rows were added, all of them things the rebuild
made tempting to say.

| claim | class | evidence |
| --- | --- | --- |
| The agent recovers from refusal and succeeds on the merits | **PROVEN** | `test_the_agent_recovers_from_a_block_and_succeeds_on_the_merits` |
| The **wallet** never tells it a policy value | **PROVEN** | `test_agent_view_leaks_no_policy_values`, 2 mutants |
| The shipped planner never reads the customer's instruction | **PROVEN** | it uses `category` and `target_lines` only; the sentence carrying "CHF 120" sits unread in the same struct |
| The agent has never seen the customer's limit | **DO NOT CLAIM** | the customer's own sentence contains it, and a **model** planner would read it from the prompt. The shipped planner does not, and that is the honest version of this claim |
| Its proposals do not depend on the secret limit | **PROVEN** | identical against two different ceilings until the wallet's answers diverge |
| A hostile or broken planner obtains no approval | **PROVEN** | 5 hostile planners; no ALLOW, no money |
| A hostile SHOP obtains no approval and cannot stall it | **PROVEN** | `test_agent_tool_boundary`: negative prices, phantom goods, 2,000 merchants |
| What it believes only ever moves toward caution | **PROVEN** | `ceiling` falls monotonically, a ruled-out shop is never reinstated |
| It never re-proposes a basket it already tried | **PROVEN** | `test_the_agent_never_re_proposes_a_basket_it_already_tried` |
| A refusal about the AGENT is never answered by shopping | **PROVEN** | `session`/`duplicate`/`other` halt even when a valid basket exists |
| It stops and waits when a human is asked | **PROVEN** | `test_the_agent_stops_and_waits_when_a_human_is_asked` |
| It proposes only baskets one shop can actually supply | **PROVEN, agent-side only** | `merchant_for`; the wallet cannot verify this and we say so in `WHAT_WE_REFUSE_TO_CLAIM.md` |
| It performs tool use | **PROVEN** — *was DO NOT CLAIM* | `Shop.search()` is called on every replanning step; episode G fails without it |
| It plans against an explicit objective, not a repair rule | **PROVEN** — *was overstated as already true* | one `score()` function; episode K fails for any price-first planner |
| The demo page plans identically to the Python agent | **PROVEN** | both run over the page's own fixture, 8 refusal sequences |
| The wallet never depends on the agent | **PROVEN** | AST-enforced; caught a real violation in an earlier phase |
| It handles eleven adversarial planning episodes | **SUPPORTED** | 11/11, up from 5/11. Eleven small synthetic worlds is a diagnostic sample, not a representative one |
| It settles well below the ceiling | **SUPPORTED** — *was DO NOT CLAIM* | the objective minimises price within a coverage tier, so it walks AWAY from the limit: CHF 7.50 against a hidden CHF 137, on the first proposal. How far below depends on what the shop stocks |
| A model works behind the same seam | **PROVEN** — *was DESIGN INTENT* | `ModelPlanner` is passed to `shop()` with no adapter; 5 model behaviours, 18 tests |
| The agent cannot learn the limit | **DO NOT CLAIM** | a probing agent needs ~12 probes and CHF 531. Ours does not probe; that is a property of ours, not of the interface |
| It performs semantic reasoning | **DO NOT CLAIM** | it searches a bounded candidate set against a three-term objective. No language is understood anywhere in it |
| Adding a model would improve it | **DO NOT CLAIM** | measured: best case a tie at 11/11 and 21 network calls; a confidently-wrong model **with** a fallback scores 8/11, below the deterministic planner |
| It understands the errand | **DO NOT CLAIM** | the objective counts lines bought, which is a thin proxy for a shopping list |
| Its search is exhaustive | **DO NOT CLAIM** | bounded at 5 lines / 12 offers / 50 shops |

## Intent

| claim | class | evidence |
| --- | --- | --- |
| No silent delegation expansion | **SUPPORTED** | 204 phrasings: 0 weakened, 0 strengthened. One author |
| Unenforceable intent blocks confirmation | **PROVEN** | `test_unsupported_restrictive_intent_blocks_confirmation` |
| The compiler understands natural language | **DO NOT CLAIM** | phrase patterns; 90% of a 103-phrase corpus |
| A recognised phrase is interpreted correctly | **LIMITATION** | coverage of *kinds* is checked; correctness is not |

## Process

| claim | class | evidence |
| --- | --- | --- |
| The test suite is not theatre | **PROVEN** | 41 mutants, 41 killed; has found 5 real gaps |
| The numbers we state about ourselves are true | **PROVEN** | `test_stated_numbers` |
| Replay and agent episode are reproducible | **PROVEN** | byte-identical; no network, no key |
| 17/4/24 is a score | **DO NOT CLAIM** | `contains_expected_decisions: false` |
| Our adversarial suites are exhaustive | **DO NOT CLAIM** | samples |
| Anything here is formally proved | **DO NOT CLAIM** | all measured |

---

## The words, audited one by one

Phase 10 of the pre-jury campaign asked for the specific vocabulary we might reach
for under pressure. Each word, and whether we may use it.

| word | may we say it? | the sentence that is safe |
| --- | --- | --- |
| **"autonomous agent"** | **yes** | "It plans, proposes, observes the refusal and replans without a human in the loop." It does. It also stops and asks when it cannot proceed, which is part of the claim, not a caveat to it. |
| **"agentic"** | **yes, with the benchmark in the same breath** | Never alone. "Agentic" is what every project today says; "it scored 5 out of 11 on a benchmark we wrote before we fixed it" is what nobody says. Lead with the second. |
| **"secure"** | **no, unqualified** | Say what holds: "a hostile planner cannot obtain an approval", "merchant text can only narrow a decision". Never "this is secure". |
| **"policy privacy"** | **no** | The interface leaks ~1 bit per purchase and we publish the price. Say "the wallet never tells the agent a rule value" — that is provable — and then say the price. |
| **"no bypass"** | **only of the policy path** | `test_NO_POLICY_BYPASS` is real and narrow: a decision cannot be reached that a rule forbids. It is not a claim about the system as a whole. |
| **"reproducible"** | **yes** | Replay byte-identical; benchmark byte-identical; 40 demo runs across two server lifetimes identical. This one is fully earned. |
| **"real-time"** | **avoid** | Decisions are sub-millisecond locally, and the platform allows 8 seconds. But "real-time" implies a production SLA we have not built. Say "well inside the 8-second deadline". |
| **"prevents overspending"** | **no** | It enforces per-purchase and per-window rules **within one run**. It does not bound the total, and cannot: the rule vocabulary has no way to say one. |
| **"prevents policy extraction"** | **no** | It prices it. ~12 probes, CHF 531. Saying "prevents" invites exactly the counter-example we already published. |
| **"exactly once"** | **no** | At most once, within one process. On the refuse list since the first audit. |
| **"total spending"** | **no** | See "prevents overspending". Disclosed to the customer, not enforced. |
| **"cross-session enforcement"** | **no** | Not enforced. Disclosed. And we corrected our own earlier claim that it was *impossible* — it is a choice under uncertainty. |
| **"AI reasoning"** | **no** | There is no model. Say "search over candidate baskets against an explicit objective function", which is both accurate and more specific than what most teams can say. |
| **"tool use"** | **yes** | `Shop.search()` is called on every replanning step; benchmark episode G fails without it. |
| **"learns"** | **yes, narrowly** | It learns from refusals, and what it learns is monotone toward caution. It does not learn across customers, sessions or time. |
| **"bounded delegation"** | **yes** | The best two words we have. Every rule narrows, `PATCH` is tighten-only, consent is per-purchase. |
| **"the agent never sees your limit"** | **no** | The *wallet* never tells it one. The customer's own sentence contains it. Say the precise version; it is still strong. |

## Claims we retired this campaign

| claim | why it went |
| --- | --- |
| "`GET /api/agent/sessions/{id}` is not reachable by the agent's protocol" | It was keyed on the session id the agent chooses. One GET returned the whole policy. Moved off the agent namespace; the claim is now "nothing the agent is **given** contains a policy value or the view's identifier". |
| "The demo shows official catalogue data" | It showed official item **ids** with fabricated names, categories and prices. Now true and enforced by `tests/test_demo_data_is_real.py`. |
| "SCEN0002 shows security overruling policy" | It does not. Its review is a *policy* review. The case is SCEN0004/AU0036, and the demo now derives it rather than naming it. |

---

## Economic claims, after the pre-jury audit

The single most likely way to lose a jury is to say "CHF 120 limit" and have
someone spend CHF 6,480 under it. These rows exist to make that impossible.

| claim | class | evidence |
| --- | --- | --- |
| "Each order is capped at the amount you wrote" | **PROVEN** | every decision evaluates the `scope="purchase"` rule |
| "A rolling window paces spending within a session" | **PROVEN** | 60 identical proposals → 2 allowed, 58 blocked, CHF 216 vs CHF 300 |
| "A pending step-up reserves nothing" | **PROVEN** | measured 0; the defence is a re-check at resolution, not a reservation |
| "Sequential step-up approvals cannot breach the window" | **PROVEN** | `_period_rules_breached_now`; second approval blocked |
| "A blocked or declined purchase consumes no budget" | **PROVEN** | measured |
| "A duplicate `authorization_id` is counted once" | **PROVEN** | measured |
| "Spent money survives revocation; nothing further is approved" | **PROVEN** | measured |
| "The agent adapts to a remaining budget it was never told" | **SUPPORTED** | errand 3 buys CHF 62 after being refused at CHF 108 |
| **"CHF 120 is the limit"** | **DO NOT CLAIM** | it is CHF 120 **per order**. Sixty orders of CHF 108 are all valid, and saying otherwise is the one sentence that loses the room |
| **"CHF 300 over 7 days caps total spending"** | **DO NOT CLAIM** | a rolling window re-opens over time and restarts in a new session. Both are on screen under "not limited by anything you wrote" |
| **"Spending is bounded across sessions"** | **DO NOT CLAIM** | measured: CHF 2,160 across ten sessions against a stated CHF 300/7 days |
| **"Cross-session enforcement is impossible"** | **DO NOT CLAIM** | a choice under uncertainty; team-scoped records plausibly exist |
| **"The customer approved it"** as a security property | **DO NOT CLAIM** | there is no identity on the step-up path. Say "the answer is bound to this purchase and to nothing else" |

## Claims retired in this audit

| claim | why |
| --- | --- |
| "An agent cannot influence the policy it is judged against" (implicit) | it could, through `instruction`, until this pass. Now true and schema-enforced |
| "Audit timestamps are authoritative" (implicit) | `confirmed_at` was caller-supplied and attributed to the customer. Now server-stamped |
| "The rolling window is visible in the demo" (implied by the panel) | it was not — every click reset the session. Now it is |

---

## Updated by the limitations-elimination campaign

| claim | class | evidence |
| --- | --- | --- |
| An agent cannot reset its own rolling budget | **PROVEN** | it could, by naming sessions: CHF 1,296 vs CHF 300/7d. Closed; mutant killed |
| Spending is bounded across delegations | **DO NOT CLAIM** | the customer endpoint is unauthenticated. Twelve self-opened delegations still reach CHF 1,296. Now **disclosed** on screen |
| A step-up answer binds to one purchase and nothing else | **PROVEN** | five properties tested: no bleed, idempotent replay, contradiction refused, dead after revocation, cannot breach a filled window |
| We know who answered a step-up | **DO NOT CLAIM** | no identity exists on this path; a signature test asserts none is faked |
| One approval yields at most one charge | **PROVEN, per process** | crash matrix; 8 concurrent consumers → 1 charge |
| Exactly-once payment | **DO NOT CLAIM** | two processes from one checkpoint each consume once — asserted in a test so it cannot be mistaken |
| The decision is the stricter of policy and security | **PROVEN** | 4,662 exhaustive combinations across three uncertainty policies |
| A third evidence source could break that composition | **CLOSED** | AST guard on every `RuleEvaluation(source=)`; mutant killed |
| A human approval can clear a policy failure | **DO NOT CLAIM** | a hard failure never offers a step-up |
| Telling the agent `budget_window` costs privacy | **DO NOT CLAIM** | measured: a prober converges identically either way — 11 probes, CHF 0.20 gap |
| We benchmarked a real language model | **DO NOT CLAIM** | credentials re-checked exhaustively; none exist on this machine |

## Authorship and intent (this campaign)

| claim | class | evidence |
| --- | --- | --- |
| Six vulnerabilities in this project were one bug | **PROVEN** | the six, tabulated; `AUTHORSHIP.md` |
| A static rule catches all six | **PROVEN** | each reintroduced and rejected, `test_authorship_audit` |
| A seventh instance cannot be added silently | **SUPPORTED** | an undeclared field fails the audit; it caught its own endpoint |
| The authorship rule is complete | **DO NOT CLAIM** | name-matching heuristic; it accepted `max_amount` until that was fixed. Aimed at the careless commit, not an adversary who controls the field name |
| No restrictive statement disappears silently | **SUPPORTED** | 39 independently written restrictions, 0 silently weakened |
| The compiler understands natural language | **DO NOT CLAIM** | 20 EXACT of 39; the other 19 are disclosed, not understood |
| Widening the vocabulary is safe | **DO NOT CLAIM** | it created a scope inversion on this very campaign. Caught by attacking the change, not by the suite |

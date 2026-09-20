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
| The test suite is not theatre | **PROVEN** | 39 mutants, 39 killed; has found 5 real gaps |
| The numbers we state about ourselves are true | **PROVEN** | `test_stated_numbers` |
| Replay and agent episode are reproducible | **PROVEN** | byte-identical; no network, no key |
| 19/2/24 is a score | **DO NOT CLAIM** | `contains_expected_decisions: false` |
| Our adversarial suites are exhaustive | **DO NOT CLAIM** | samples |
| Anything here is formally proved | **DO NOT CLAIM** | all measured |

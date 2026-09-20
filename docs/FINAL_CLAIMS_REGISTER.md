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

| claim | class | evidence |
| --- | --- | --- |
| The agent recovers from refusal and succeeds on the merits | **PROVEN** | `test_the_agent_recovers_from_a_block_and_succeeds_on_the_merits` |
| It is never told a policy value | **PROVEN** | `test_agent_view_leaks_no_policy_values`, 2 mutants |
| Its proposals do not depend on the secret limit | **PROVEN** | identical against two different ceilings until the wallet's answers diverge |
| A hostile or broken planner obtains no approval | **PROVEN** | 5 hostile planners; no ALLOW, no money |
| It stops and waits when a human is asked | **PROVEN** | `test_the_agent_stops_and_waits_when_a_human_is_asked` |
| It handles nine adversarial episodes | **PROVEN** | 5 replanned, 4 escalated |
| The wallet never depends on the agent | **PROVEN** | AST-enforced; caught a real violation this phase |
| The agent cannot learn the limit | **DO NOT CLAIM** | ~12 probes, CHF 531. Say the number instead |
| It settles far below the ceiling | **DO NOT CLAIM** | it lands on CHF 119 against CHF 120. A *better* planner converges closer |
| It performs tool use or semantic reasoning | **DO NOT CLAIM** | it reads a CSV and applies four rules |
| A model would work behind the same seam | **DESIGN INTENT** | the seam is tested; it has never held a model |

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

# R&D Track H: Compromised shopping-agent red-team simulator

## The question

Can we produce a single, runnable, demonstrable artifact that proves "the
shopping agent can be fully compromised without gaining payment authority" --
answering this project's central claim with evidence rather than assertion?

## Design

A dedicated adversarial test module (`tests/test_red_team_matrix.py`) plus a
standalone report script (`scripts/run_red_team.py`) that constructs a
**local adversarial shopping-agent simulator** -- not the production agent, a
test-only adversary -- attempting a fixed, enumerated list of attacks against the
real `decision_engine`/`payment` code (no mocks of the code under test), and
produces a structured **attack matrix**:

```
ATTACK -> EXPECTED WALLET PROPERTY -> OBSERVED RESULT -> PASS/FAIL -> EVIDENCE
```

## The attack list (17 attacks, each mapped to an existing invariant in `SECURITY_INVARIANTS.md`)

1. Prompt injection in `item_details` claiming pre-authorization (I16/I17)
2. Prompt injection claiming "the customer already approved this" (I16/I17)
3. Adding an unrequested product to the basket (I18, `item.unrequested_present`)
4. Changing the requested product for a same-category substitute (`item.name_contains`)
5. Changing the merchant to an unfamiliar one (`merchant.familiar`, I19)
6. Increasing the quantity/amount beyond the mandate ceiling (I9)
7. Modifying the price after the customer reviewed it (I9, I6)
8. Hiding a delivery/protection-plan charge as a second item (I18)
9. Unicode obfuscation of the injected text (I16, second-pass Finding 15)
10. Replaying the exact same authorization twice (I13)
11. Mutating a previously-approved authorization's facts under the same ID (I14)
12. Changing facts after a step-up was already raised, before resolution (I5/I6)
13. Attempting to resolve an authorization that belongs to a different mandate/run (I5)
14. Exploiting a stale/already-resolved decision by resolving it again with a
    different answer (I5, second-pass Finding 8)
15. Exploiting a retry to double-count spend (I13)
16. A merchant-name lookalike (typosquat) impersonating a familiar merchant (I19,
    `SECURITY.md` "Merchant impersonation")
17. Attempting to widen authority via a PATCH-style rule addition that is weaker
    or contradictory (I3, `ARCHITECTURE_DECISIONS.md` ADR-1)

## Why this is a test harness, not new production code

Every attack in this matrix exercises the same public functions
(`evaluate_authorization`, `resolve_authorization`, `MockPSP.charge`,
`Mandate.tighten_hard_rules`) the existing test suite already calls -- this
track adds no new engine logic, only a structured, narratively-labeled
enumeration and a report generator over attacks that (in less structured form)
were already individually covered by `test_prompt_injection.py`,
`test_duplicate_and_retry.py`, `test_payment_boundary.py`,
`test_human_resolution.py`, and `test_mandate_lifecycle.py`. What's new is the
single, demo-ready artifact: one script, one table, 17 rows, all PASS.

## Alternatives considered

- **A live, autonomous LLM-driven red-team agent** (an actual language model
  trying to jailbreak the system at runtime): rejected for this pass as
  non-reproducible (a model's specific attempt would vary run to run) and
  unnecessary -- the 17 attacks above are exhaustive relative to every
  vulnerability class found across three audit passes; a model would very likely
  rediscover a subset of these rather than find new classes, and would add
  latency/cost/non-determinism to what should be a fast, reproducible CI-style
  check.
- **Folding this into the existing test files rather than a dedicated matrix**:
  rejected because the *demonstrability* value (Section 20's actual ask) comes
  specifically from having one readable, standalone artifact a judge can run and
  read in under a minute, not from attacks scattered across nine different test
  files by implementation area.

## Implementation cost

Low: a thin orchestration layer over existing, already-tested functions.

## Demo value

Very high -- directly and concretely answers "what can this architecture
demonstrate that a conventional deterministic wallet cannot easily demonstrate
as clearly" (Section 20): a conventional wallet CAN have the same protections,
but showing them as one 17-row, all-PASS, live-executed table is a
differentiator in its own right for a 3-minute demo slot.

## Compatibility

Test-only; no production code path changed.

## Recommendation: **KEEP / PROTOTYPE** (selected for implementation)

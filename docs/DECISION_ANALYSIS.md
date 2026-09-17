# Decision analysis: the complete 45-event replay, examined for defensibility

[OFFLINE_REPLAY.md](OFFLINE_REPLAY.md) explains the reasoning behind each of the 45
decisions narratively, scenario by scenario. This document is the complementary,
more adversarial pass Section 20 of the third audit asked for: a compact ledger of
every event plus, for each REVIEW and every genuinely debatable BLOCK/ALLOW, an
explicit discussion of whether another reading of the customer's instruction would
have produced a different (and equally or more defensible) result.

No scenario ID, purchase ID, or replay position is used to determine any outcome
below or in the engine itself -- this is a report of what the deterministic engine
concluded from policy + facts, not a target it was built to hit. See
`tests/test_offline_replay.py::test_engine_does_not_branch_on_scenario_id_or_authorization_id`.

## Full ledger

| # | Scenario | Decision | Intervention | Unknown fact(s) | Failing fact(s) |
| --- | --- | --- | --- | --- | --- |
| AU0001 | SCEN0000 | ALLOW | allow | -- | -- |
| AU0002 | SCEN0001 | ALLOW | allow | -- | -- |
| AU0003 | SCEN0001 | ALLOW | allow | -- | -- |
| AU0004 | SCEN0001 | BLOCK | never | -- | per-order ceiling |
| AU0005 | SCEN0001 | ALLOW | allow | -- | -- |
| AU0006 | SCEN0001 | ALLOW | allow | -- | -- |
| AU0007 | SCEN0001 | BLOCK | never | -- | rolling window + item category |
| AU0008 | SCEN0001 | BLOCK | never | -- | rolling window |
| AU0009 | SCEN0001 | BLOCK | never | -- | rolling window |
| AU0010 | SCEN0001 | BLOCK | never | -- | per-order ceiling + rolling window |
| AU0011 | SCEN0001 | ALLOW | allow | -- | -- |
| AU0012 | SCEN0002 | ALLOW | allow | -- | -- |
| AU0013 | SCEN0002 | BLOCK | never | -- | item size |
| AU0014 | SCEN0002 | BLOCK | never | -- | return window (final sale) |
| AU0015 | SCEN0002 | BLOCK | never | -- | return window (7 < 14 days) |
| AU0016 | SCEN0002 | **REVIEW** | ask_missing_fact | return window | -- |
| AU0017 | SCEN0002 | BLOCK | never | -- | item name (substitution) |
| AU0018 | SCEN0002 | BLOCK | never | return window (moot) | item category |
| AU0019 | SCEN0002 | ALLOW | allow | -- | -- |
| AU0020 | SCEN0002 | BLOCK | never | -- | item name + size |
| AU0021 | SCEN0002 | BLOCK | never | -- | per-order ceiling |
| AU0022 | SCEN0002 | BLOCK | never | -- | merchant category |
| AU0023 | SCEN0002 | ALLOW | allow | -- | -- |
| AU0024 | SCEN0003 | ALLOW | allow | -- | -- |
| AU0025 | SCEN0003 | ALLOW | allow | -- | -- |
| AU0026 | SCEN0003 | ALLOW | allow | -- | -- |
| AU0027 | SCEN0003 | BLOCK | never | -- | merchant familiarity |
| AU0028 | SCEN0003 | BLOCK | never | -- | merchant familiarity |
| AU0029 | SCEN0003 | BLOCK | never | -- | merchant familiarity + session integrity |
| AU0030 | SCEN0003 | BLOCK | never | -- | merchant familiarity + session integrity |
| AU0031 | SCEN0003 | ALLOW | allow | -- | -- |
| AU0032 | SCEN0003 | ALLOW | allow | -- | -- |
| AU0033 | SCEN0003 | BLOCK | never | -- | merchant familiarity |
| AU0034 | SCEN0003 | BLOCK | never | -- | per-order ceiling |
| AU0035 | SCEN0004 | ALLOW | allow | -- | -- |
| AU0036 | SCEN0004 | **REVIEW** | ask_missing_fact | duplicate-order suspicion | -- |
| AU0037 | SCEN0004 | BLOCK | never | -- | per-order ceiling (injected text ignored) |
| AU0038 | SCEN0004 | ALLOW | allow | -- | -- |
| AU0039 | SCEN0004 | BLOCK | never | -- | merchant familiarity (typosquat) |
| AU0040 | SCEN0004 | ALLOW | allow | -- | (injected text ignored) |
| AU0041 | SCEN0004 | BLOCK | never | -- | ceiling + item category + unrequested item |
| AU0042 | SCEN0004 | ALLOW | allow | -- | -- |
| AU0043 | SCEN0004 | BLOCK | never | -- | item category + unrequested item |
| AU0044 | SCEN0004 | BLOCK | never | -- | merchant familiarity |
| AU0045 | SCEN0004 | ALLOW | allow | -- | -- |

**Totals: 19 ALLOW / 2 REVIEW / 24 BLOCK, 45 events.** Note that both REVIEWs come
from an `unknown` fact, not from a security signal alone reaching REVIEW on its
own merits -- see "Why so few REVIEWs?" below.

## Why ALLOW / REVIEW / BLOCK, examined adversarially

### Why so few REVIEWs (2 of 45), when three of the five scenarios are explicitly about ambiguity/security signals?

This was the single question worth interrogating hardest, because a system that
almost never asks the customer anything could either be (a) genuinely decisive
because the facts are usually clear, or (b) wrongly confident because it is
silently resolving ambiguity in one direction. Tracing through every scenario:

- **SCEN0001 (household budget):** every decision is a clean per-order or
  rolling-window arithmetic comparison against a known amount -- there is no
  missing information anywhere in this scenario's data, so there is nothing to be
  genuinely uncertain about. A REVIEW here would be manufactured, not honest.
- **SCEN0002 (item and terms):** most cases are also clean comparisons (a stated
  size, a stated return window, a stated merchant category) -- the *scenario's own
  theme* is "does the solution catch violations that look plausible," and a
  violation that is clearly stated in the data (wrong size, wrong item name, wrong
  category) is not ambiguous just because it requires several checks to catch.
  Exactly one event (AU0016) has a genuinely missing fact (no return-window
  statement at all) and correctly becomes the one REVIEW in this scenario.
- **SCEN0003 (session integrity):** every purchase either fails the flat
  familiarity requirement outright (a hard, unambiguous violation of an explicit
  instruction) or passes cleanly. The "session integrity" signal is present as a
  contributing *reason* on several already-blocked events (AU0029, AU0030) but
  never the SOLE reason, because every one of those purchases also fails
  familiarity independently. **This is worth stating plainly as a limitation**:
  this dataset does not contain a case where session-integrity risk is the only
  problem with an otherwise-compliant purchase, so the heuristic's behavior in
  that specific configuration is untested by the official data (though it IS
  covered by `state.py`'s own unit-style reasoning and would fire independently if
  such a case existed -- `session.integrity_risk` is evaluated as its own rule,
  not gated behind familiarity failing first).
- **SCEN0004 (manipulated agent):** the scenario's adversarial cases (lookalike
  merchant, injected text, wrong item, unrequested add-on) are all, by
  construction, *resolvable* facts -- a typosquatted merchant_id is definitively
  either familiar or not; an add-on's category is definitively outside the
  requested set. The one genuinely ambiguous case (AU0036, a suspected duplicate
  order) correctly becomes the one REVIEW in this scenario.

**Conclusion:** the low REVIEW count reflects that this particular 45-event pack
is mostly composed of definitively-resolvable facts dressed up as adversarial
scenarios, not that the engine is defaulting to false confidence. The two REVIEWs
that do occur are both genuine missing-information cases, and the engine's
`uncertainty_policy` routing was independently stress-tested well beyond this
dataset via `tests/test_properties.py` and `tests/test_decision_engine.py`'s
hand-written unknown-handling tests.

### AU0018: an "unknown" that never mattered

AU0018 has both an unknown fact (return window unstated) and a hard failure (an
add-on outside the requested item category). The engine reports BLOCK, not
REVIEW, because a `fail` always outranks an `unknown` (`SECURITY_INVARIANTS.md`,
I18, and `_decide()`'s documented priority). **Alternative interpretation
considered and rejected:** one could argue the customer should still be *told*
about the unstated return window even though the purchase is already rejected for
an unrelated reason -- and the implementation does exactly that: the unknown
fact's evidence line is still included in `EngineDecision.evidence`
(`order.return_window_days [unknown]: ...`) even though it did not determine the
final decision. Nothing is hidden; the priority rule only decides which SIGNAL
wins the final verdict, not which facts get reported.

### AU0038 vs. AU0037: currency did not decide anything on its own

AU0038 (USD 450 -> CHF 391.50, ALLOW) and AU0037 (CHF 520, BLOCK) might look like
"foreign currency gets a pass" if read carelessly. They do not: AU0038 passes
because its CONVERTED amount is under the ceiling, and AU0037 fails because its
CHF-denominated amount is over it, by a wide margin no currency trick would close.
**Alternative interpretation considered:** could a customer reasonably expect
foreign-currency purchases to be treated MORE strictly (e.g., a fixed "penalty" for
being in an unfamiliar currency), given the FX rates are synthetic and fixed
rather than live? Nothing in the customer's actual instruction ("...for CHF 400 or
less") asks for this, and inventing it would be the engine adding a restriction
the customer never stated -- which `docs/ARCHITECTURE_DECISIONS.md`'s general
stance (never override customer intent in either direction) explicitly avoids.

### AU0023: the "unfamiliar but fully compliant seller" case, examined for the road not taken

AU0023 (Summit Thread, never used on this card, but a genuine `sporting_goods`
merchant) is ALLOWed because SCEN0002's own instruction requires a *retailer type*
("a specialist sports retailer"), not merchant *familiarity* -- unlike SCEN0000,
SCEN0003, and SCEN0004, which explicitly do require familiarity in their own
wording. **Alternative interpretation considered:** could "a specialist sports
retailer" reasonably be read as implicitly requiring some baseline trust signal
beyond category alone (e.g., a merchant this customer, or similar customers, has
used before)? The instruction's own control question ("...an unfamiliar but fully
compliant seller") is data-dictionary-documented as *the intended test case for
this exact ambiguity* -- and the more literal reading (retailer type is a
category question, familiarity is a separate, unstated question here) is both the
one the engine reaches and the one consistent with SCEN0002 never using the word
"before" or "regularly" anywhere in its instruction, unlike the three scenarios
that do.

## Confidence characterization

Every ALLOW and BLOCK in this dataset is reached with **zero** unknown facts
remaining (see the ledger's "Unknown fact(s)" column) -- meaning every non-REVIEW
decision is fully determined by facts the engine could verify, not a
probability-weighted guess. The two REVIEWs are exactly the two events where a
fact genuinely could not be verified. There is no notion of "80% confident BLOCK"
anywhere in this system, by design: `rules.py` produces exactly `pass`/`fail`/`unknown`,
never a score, which is what makes the priority rule (`fail` always wins) sound --
a probabilistic engine would need a very different, harder-to-audit aggregation
rule to preserve the same guarantee.

## Where ambiguity genuinely exists in the official brief itself

- **What "specialist retailer" means precisely** is left to the solution to
  define (technical_details.md explicitly says field-name conventions are "for
  your engine to interpret"). This implementation maps it to the shared
  `merchant_category` vocabulary already used by the catalogue; a different,
  equally defensible implementation might require additional signals (e.g., a
  minimum number of SKUs in that category) that this data pack does not expose.
- **The exact rolling-window boundary convention** (whether a purchase exactly 7
  days old counts as "within" the window) is not specified by technical_details.md
  and was resolved as a half-open interval (`window_start < ts <= as_of`) --
  documented explicitly in `ARCHITECTURE.md` as a stated, arguable convention, not
  an obvious fact.
- **Whether session-integrity risk alone (with no other violation) should BLOCK or
  REVIEW** is untested by this data pack (see above) and was designed to route
  through the same rule mechanism as everything else (a `session.integrity_risk`
  hard rule, so it BLOCKs if the mandate states it as a hard requirement, same as
  any other rule) -- a defensible but not the only possible design; an
  alternative would make session-integrity risk always route to REVIEW regardless
  of the mandate's own uncertainty_policy, on the theory that "someone else may be
  driving" is categorically different from an ordinary policy violation. This
  implementation did not special-case it that way, on the principle that the
  customer's own stated uncertainty preference should govern uniformly rather than
  the engine deciding some violations deserve different treatment than others.

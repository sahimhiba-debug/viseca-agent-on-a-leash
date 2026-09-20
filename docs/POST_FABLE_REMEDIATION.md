# Post-audit remediation

Fixes for the four findings of `docs/FABLE_INDEPENDENT_AUDIT.md`, and nothing else.
No new architecture, no new research.

---

## 1. HIGH — unsupported restrictive intent could be auto-confirmed

**Root cause.** Two independent defects compounding.

The amount vocabulary recognised about half of ordinary English (19/35 measured).
That alone was survivable, because an unrecognised limit produced *no rule and a
warning* — nothing was silently weakened. What made it a HIGH is that
`scripts/run_live_worker.py` compiled, drafted and **confirmed** in three consecutive
statements, with the warning written only to a log. The chain ran
`warning → automatic confirmation → unenforced restriction` with no human in it.

**Fix, in two parts.**

*Vocabulary.* `_AMOUNT_RE` extended with the negation and noun forms it was missing:
`never more than`, `nothing over/above`, `capped at`, `limited to`, `do not exceed`,
`not exceeding`, `no higher than`, `don't go over`, `within`, `a CHF X cap/ceiling/
limit`, `max CHF X`, `budget`. Also `_AMOUNT_THEN_PERIOD_RE` now accepts word-numbers
(`across any seven days`) and `_RETURN_WINDOW_RE` accepts plural `returns are accepted
within 30 days` — two real gaps my own verification corpus found.

*The gate.* `CompiledPolicy` gained `unsupported_restrictions`, and
`Mandate.confirm()` refuses unless the caller names **every** item back through
`acknowledged_unsupported`. Producing that list is what "the customer saw this" means
here: a caller that has not looked cannot produce it. `run_live_worker.py` now exits
rather than confirming, printing each item, and requires `--acknowledge-unsupported`
for an operator to proceed on the customer's behalf.

**The four categories, defined precisely** (in `CompiledPolicy`'s docstring, so they
live next to the code that applies them):

| category | definition | effect |
| --- | --- | --- |
| **supported restriction** | a phrase mapped to a `HardRule` | enforced |
| **unsupported restrictive intent** | a restrictive marker of a kind we recognise fired, and no rule of that kind was produced | **blocks confirmation** |
| **ambiguous intent** | a supported restriction stated twice with conflicting values | resolved *defensively* (the smaller), named, **does not block** |
| **harmless unknown language** | no restrictive marker at all | produces nothing, **blocks nothing** |

The last row is why the blocking set is keyed on *markers* rather than on "text we did
not consume": treating ordinary prose as a restriction would make every mandate
unconfirmable, and a gate that fires on everything gets routed around.

**Consequence worth stating.** SCEN0000 — *"Buy **one** ordinary grocery item"* — now
carries an unsupported restriction, because quantity is not expressible in the
official vocabulary. The offline replay acknowledges it **explicitly** rather than
leaving the field unset; leaving it unset would also confirm, and that
bypass-by-omission is the exact pattern this project keeps finding.

**Regression tests:** `test_post_fable_remediation.py` — 27 phrasings (the brief's six
plus the rest of the corpus), three false-positive probes, the gate, partial
acknowledgement, harmless language, and ambiguous intent.
**New invariant:** **I40**.

## 2. MEDIUM — one `authorization_id`, two economic transactions

**Is uniqueness guaranteed?** **Yes, structurally.** The live id is a *resource
address* — `POST /v1/authorizations/{authorization_id}/decision` and `/resolve` — so
two purchases sharing one would be mutually unaddressable. The schema requires
`minLength: 1`; the worker outline treats the id as *the* key ("If this live purchase
ID was already handled, reconcile its saved result"); and it "stays the same within a
run but changes between runs".

So this is defence in depth, not a live hole. We fixed it anyway, because the
assumption was undocumented and — uniquely among the seven assumptions the audit
package lists — its violation failed **open**.

**Root cause.** The repeat fingerprint compared merchant + basket + amount and
**stored but never compared the timestamp**. A collision with *differing* facts
already failed closed; only the *identical-facts* case failed open, because nothing
distinguished it from a legitimate retry.

**Fix.** The simulated purchase time joins the fingerprint. It is a property of the
*purchase*, not of the *delivery*, so a genuine re-delivery carries the same value and
stays a replay, while two different transactions do not. Separately, a null, empty,
blank or non-string `authorization_id` is now a `source="safety"` binding failure.

| | before | after |
| --- | --- | --- |
| 5 distinct CHF 100 orders, one id, CHF 300 cap | all allowed, window counted CHF 100 | first allowed, rest **blocked**, window CHF 100 |
| same purchase delivered 3× | allow / replay / replay, counted once | **unchanged** |

**Regression tests:** collision blocked, retry idempotency preserved and counted once,
six malformed id forms refused. **New invariants:** **I41**, **I42**.

## 3. MEDIUM — the platform's echoed mandate became the policy

**Root cause.** A run's policy is built from its first event's `mandate` block via
`MandateSnapshot.from_event_mandate`, and nothing compared it to what the customer
confirmed. A widened echo turned a CHF 9,000 purchase at an unknown seller from BLOCK
into ALLOW for the whole run. The tighten-only invariant governs the `Mandate` object,
not this boundary.

**Fix.** `LiveWorker` optionally carries the confirmed `hard_rules` and
`uncertainty_policy`; `_verify_echoed_policy` compares them on auto-registration and
raises `EchoedMandateMismatch`, naming every added and missing rule.
`run_live_worker.py` passes what it drafted.

**Any difference fails closed, including a tightening.** The platform is not an
authority on the customer's policy: a narrowing we did not author is still one we
cannot explain to them, and accepting it would mean trusting the same channel to tell
us which direction it moved. Only `hard_rules` and `uncertainty_policy` are compared —
`customer_id`, `card_id` and `profile_id` are assigned by the platform at run start and
are legitimately absent from what we drafted.

**Regression tests:** identical accepted; widened, tightened, changed amount, changed
merchant restriction, changed temporal rule, all-rules-removed and a changed
uncertainty policy all fail closed; a malformed block raises; a worker with no
confirmed policy still runs. **New invariant:** **I43**.

## 4. LOW — authority TTL pinned by nothing

**Root cause.** Expiry *was* enforced; no test asserted it. An independent mutant
widened `DEFAULT_AUTHORITY_TTL` from 15 minutes to 3,650 days and the whole suite
passed.

**Fix.** Tests only — expiry was not redesigned. Three properties: an authority
expires and an expired one cannot execute; the horizon equals `issued_at + TTL`, so
changing the constant changes the behaviour; and the comparison uses the same clock
the horizon was set on, verified in both directions.

A first draft of these tests passed `now=` to `issue_authority` and silently hit the
**idempotent** branch — the authority is minted inside `evaluate_authorization` on the
real clock — so it got the existing authority back and tested nothing. They now read
the horizon off the authority itself. **New invariant:** **I44**.

## 5. Remaining limitations

1. **The compiler is still phrase patterns.** Coverage of restriction *kinds* is
   checked; correctness of a *recognised* phrase is not. A pattern that matches the
   wrong thing still produces a wrong rule.
2. **Three concepts remain inexpressible** — an overall total, an end date, any
   quantity. All three now block confirmation until acknowledged; none is enforced.
3. **Per-process budget multiplication** (audit F5) is unchanged and out of scope
   here: two workers on one run each enforce the window independently.
4. **F6** (`evidence[0]` can read `[pass]` on a blocked decision) needed no action.
5. The echo check is **opt-in**. Offline and test callers do not supply a confirmed
   policy, so it does not fire for them. `run_live_worker.py` always supplies one.

## 6. Verification

| | |
| --- | --- |
| suite | **933 passed, 5 skipped** (938 collected) |
| official replay | **45 events — 19 allow / 2 review / 24 block**, unchanged |
| adversarial corpus | 133/133 |
| attack matrix | 17/17 |
| mutation probe | **34 mutants, 34 killed, 0 survived** (29 → 34; the TTL survivor is now killed) |
| compiler optimiser | 4,800 generated instructions, 0 silent losses |
| concurrency / lifecycle | state machine, execution atomicity, revocation end-to-end: 67 passed |

**Why the replay is unchanged.** The vocabulary only *adds* recognition, and the five
official instructions already used recognised phrasings; the confirmation gate fires
on SCEN0000 and is acknowledged explicitly; the fingerprint change needs colliding
ids, which the official corpus does not contain; the echo check is not wired into the
offline path.

## 7. Independent compiler corpus

`python3 scripts/run_intent_corpus.py` — **103 phrasings**, enumerated by how a person
states a restriction rather than from the compiler's patterns.

| group | n | recognised | unsupported | silent | wrong |
| --- | ---: | ---: | ---: | ---: | ---: |
| amount (per order) | 43 | 43 | 0 | 0 | 0 |
| amount (period) | 15 | 15 | 0 | 0 | 0 |
| merchant familiarity | 12 | 12 | 0 | 0 | 0 |
| item / merchant category | 8 | 8 | 0 | 0 | 0 |
| no add-ons | 8 | 8 | 0 | 0 | 0 |
| return window | 4 | 4 | 0 | 0 | 0 |
| session integrity | 3 | 3 | 0 | 0 | 0 |
| quantity *(inexpressible)* | 4 | 0 | **4** | 0 | 0 |
| overall total / end date *(inexpressible)* | 6 | 0 | **6** | 0 | 0 |
| **TOTAL** | **103** | **93 (90%)** | **10** | **0** | **0** |

Each group declares the verdict it *expects*, and mismatches are reported. That
matters: an earlier version of this script scored the inexpressible groups as
RECOGNISED and printed **100%** — a number that would have claimed coverage of a
vocabulary that cannot represent quantity at all. The ten UNSUPPORTED results are the
*correct* outcome, not a shortfall.

## 8. Exact claims we can safely make

* A stated per-order or per-period ceiling, across **103 tested phrasings**, is either
  turned into a rule or reported to the customer. **Zero were silently lost.**
* A mandate carrying restrictive intent we cannot enforce **cannot be confirmed**
  without each item being named back.
* One `authorization_id` cannot carry two economic transactions; legitimate retries
  remain idempotent and counted once.
* A platform echo that differs from the confirmed policy **fails the run closed**.
* A payment authority expires at `issued_at + DEFAULT_AUTHORITY_TTL`, and that is
  tested rather than assumed.

## 9. Claims we must NOT make

* **NOT** that the compiler understands natural language — 90% of a corpus one person
  wrote is not a language.
* **NOT** complete intent fidelity. Correctness of a *recognised* phrase is unchecked.
* **NOT** that quantity, an overall total or an end date are enforced. They are
  disclosed and they block confirmation; the vocabulary cannot express them.
* **NOT** that `authorization_id` uniqueness is now verified end-to-end — we made its
  violation fail closed, we did not observe the platform's behaviour.
* **NOT** that the echo check protects the offline or demo paths. It is opt-in.

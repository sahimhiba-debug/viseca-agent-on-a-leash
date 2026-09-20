# Final competition readiness

Where this project is strong, where a jury can hurt it, and exactly what to say.

---

## A. Technical strengths

- **Deterministic, reproducible, offline.** Official replay 45 events (19/2/24),
  byte-identical run to run. Planning benchmark and architecture comparison likewise.
  40 demo runs across two server lifetimes plus 8 concurrent sessions: identical.
  No network, no key, no model in the judged path.
- **A test suite that has actually caught things.** 39 mutants, 39 killed. It has
  found real defects in our own work repeatedly, including this week.
- **Vulnerabilities found, fixed, and written up rather than buried.** The revocation
  hole (revoke → answer pending step-up → CHF 175 charged) came from an independent
  audit and is documented with its reproduction.
- **One record per authorization.** The execution lifecycle lives on the decision,
  not in a second object — the shape that had produced four separate vulnerabilities.
- **Policy and security are separate verdicts**, and the wallet's decision is the
  stricter of the two.

## B. Agentic strengths

- **An adversarial benchmark written before the agent was changed**, so it could
  fail. It did: 5/11. In five of eleven episodes the cheapest valid basket is wrong.
  The agent now scores 11/11; the old planner re-measured still scores 5/11.
- **An explicit objective function** — coverage, then returnability once a refusal
  shows it matters, then price *last*. That ordering is the whole fix.
- **A tool.** `Shop.search()` on every replanning step; an item that sells out
  mid-episode is actually noticed.
- **Two non-price adaptations, live**: change shop, then change the goods — and the
  approved basket costs more than the refused one.
- **Bounded autonomy.** It stops when it cannot proceed, never re-proposes a basket
  it has tried, and a refusal about *the agent* rather than the purchase halts it
  unconditionally even when a valid alternative exists.
- **The model question answered with a table**, not a preference.

## C. UX strengths

- **Plain English in, enforceable rules out — plus what could not be represented**,
  and confirmation is blocked until the customer has seen that list.
- **Two audiences, two objects.** The agent's card and the customer's card are
  visibly different views of the same decision.
- **Consent is scoped and says so**: *"this one purchase — CHF 289 at PixelHarbor.
  Not a standing exception."*
- **Mobile-first and verified** at 375 / 390 / 412 px: no horizontal overflow on any
  panel before or after a run, no tap target under 44 px.
- **The strategy is named on screen** — `CHANGE SHOP`, `CHANGE THE GOODS` — with the
  price delta beside it, so the jury sees adaptation rather than inferring it.

## D. Differentiation

If another team ships *LLM shopping agent + spending limit*, they have a smarter
planner and a dumber boundary. Four things they will not have:

1. **The agent adapts without ever being told a number.** It is refused with a
   *constraint class*, not a threshold. Everyone can refuse an agent; refusing it in
   a form it can act on, while withholding what it could probe with, is the
   contribution — and we price the residual leak in francs rather than denying it.
2. **Security can overrule a satisfied policy.** Every customer rule passed and the
   wallet stopped the purchase anyway. A spending limit structurally cannot do this.
3. **A hostile planner cannot authorize itself.** Tested with planners far worse
   than a compromised one. The authority boundary is architectural, not a check.
4. **Bounded delegation as a first-class object.** Tighten-only amendment,
   per-purchase consent, revocation that reaches a purchase already waiting.

The memorable form, in one line: **the agent is autonomous; the authority is not.**

## E. Market story

A card answers one question: *can this card spend?* An autonomous agent needs a
different one: *may this agent take this action, on my behalf, under these
constraints, on this evidence, right now?* That question cannot be expressed as a
limit, so it cannot be refused precisely by one.

- **Customer:** the cardholder delegating an errand.
- **Buyer:** the card issuer. They carry the loss, they are already in the
  authorization path, and they already hold the purchase history the familiarity
  rule needs.
- **Integration point:** the authorization decision they already make — this sits
  inside it rather than beside it.
- **Value:** delegation a customer can bound in their own words, and a refusal an
  agent can act on without learning the policy.
- **Beyond shopping:** any bounded delegation with evidence at decision time —
  travel booking, procurement, subscription management, expense approval. Same
  primitive: *this action, these constraints, this evidence, now.*

**No market-size number appears here, because we do not have one.**

## F. Demo risks

| risk | mitigation | residual |
| --- | --- | --- |
| stale browser page | served `no-store`; a test asserts the header | none known |
| presenter picks the wrong scenario | the page derives it from `GET /api/scenarios/security-override` | none |
| a confirmed mandate on Delegate makes the Agent tab approve immediately | the line under the button names the running mandate | narrate it |
| demo data drifts from the catalogue | `tests/test_demo_data_is_real.py` | none known |
| the agent stops showing two non-price adaptations | a guard test asserts three attempts, one shop change, one goods change, and a final basket no cheaper | none known |
| attack card shows HOLE | stop and say so — it is a real regression | — |
| node absent on the demo machine | only affects a **test** (browser/Python planner parity), never the demo | the test skips loudly |

## G. Judge attack surface

Ranked by damage if unanswered. All five have answers; see `FINAL_JURY_AUDIT.md`.

1. *"Show me the agent failing your own benchmark."* — the best question we could
   be asked. 5/11, file written first.
2. *"What else is under `/api/agent/`?"* — one route, test-enforced. Until this week
   there were two.
3. *"Is that real data?"* — now yes, enforced. Until this week it was not.
4. *"Where's the AI?"* — outside the money path, deliberately, with a measured table
   explaining why.
5. *"Isn't this a policy engine?"* — one decision where policy allowed and security
   did not.

## H. Remaining technical limitations

Stated plainly; the full list is `WHAT_WE_REFUSE_TO_CLAIM.md`.

- At-most-once payment, within one process. Not exactly-once.
- No total-spend bound is expressible in the official rule vocabulary.
- Cross-run period enforcement is disclosed, not enforced — a choice under
  uncertainty, not a protocol impossibility.
- Merchant claims (return windows, sizes) cannot be verified. A plausible lie wins.
- The compiler matches phrase patterns; 90% of a 103-phrase corpus, 0 silently lost.
- The agent's objective counts lines bought, a thin proxy for a shopping list.
- Search bounded at 5 lines / 12 offers / 50 shops.
- No authentication on the demo API. In-memory state, one process.
- Nothing here is formally proved. Everything is measured.

## I. Exact claims to use

- "The agent is autonomous. The authority is not."
- "It proposes. The wallet decides."
- "It adapts without ever being told a number — only which *kind* of rule it broke."
- "Every rule the customer wrote was satisfied. The wallet stopped it anyway."
- "We wrote the benchmark before we fixed the agent, so it could fail. It did: 5/11."
- "The approved basket cost more than the refused one."
- "A hostile planner cannot obtain an approval or move money."
- "Reproducible offline: no network, no key, no model."
- "Here is what we refuse to claim."

## J. Exact claims to avoid

- "Secure." / "Prevents overspending." / "Prevents policy extraction."
- "Exactly once." / "Cross-session limits are enforced."
- "AI-powered." / "The AI decides." / "AI reasoning."
- "The agent can never learn your limit." (Say the price: ~12 probes, CHF 531.)
- "The agent has never seen your limit." (The customer's own sentence contains it.)
- "Novel protocol." / "First of its kind."
- "19 out of 45" as a score. It is a regression boundary.
- Any market-size figure.
- "Real-time." Say "well inside the 8-second deadline."

## K. Final recommended demo sequence

Home (15s) → Delegate (20s) → **Agent** (47s, the heart) → Decisions (28s, the
security moment) → refusals document (10s). Full script with wording:
`FINAL_DEMO_SCRIPT.md`. Opening line: candidate **C**.

Total 1:55, five seconds of slack, and the last thing on screen is the list of
things we do not claim.

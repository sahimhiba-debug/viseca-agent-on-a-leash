# Hypothesis falsification

Sixteen candidates. Fifteen rejected. Each rejection has a reason that is a
measurement or a citation, not a preference.

| # | hypothesis | why it dies |
| --- | --- | --- |
| H1 | **Sequence-aware authorization** (count performances of a job in the decision path) | Already built as research and deliberately excluded: the job is mandate-scoped, our ledger is run-scoped. Moving it in is a scope change, not a patch. *Documented limitation, not a new idea.* |
| H2 | **Delegation-as-resource** (consume product identity, merchant class, size) | H1 renamed. Same scope mismatch. |
| H3 | **Authority-gated counterfactuals (C1)** | **Rejected with measurement.** The channel does not exist (the agent never receives our reasons); and for fabricable facts a single plausible claim — *"returns accepted within 90 days"* — clears every realistic threshold with zero policy knowledge, so withholding the counterfactual protects nothing. See `C1_SECOND_ORDER_SECURITY_AUDIT.md`. |
| H4 | **Minimal-repair explanation** ("remove the protection plan") | Real and measurable (AU0041: 3 failures cleared by one removal) but it is an *explanation*, changes no decision, and IAM policy simulators already productise the computation. Keep as a possible UI nicety; not a differentiator. |
| H5 | **Uncertainty decomposition** (which *kind* of uncertainty) | Partly built — step-ups already name the specific unresolved fact. The deeper form ("is a human even able to resolve this?") collapses into the fabricability axis from H3, and that axis was just shown not to bind. |
| H6 | **Evidence provenance graph** | More machinery to answer what the `source` tag already answers. Rejected in an earlier pass; nothing new since. |
| H7 | **Policy/security verdict split** | **Already shipped.** Not a candidate. |
| H8 | **Agent identity / provenance** | The challenge removes it deliberately: *"the agent rows do not have `agent_id` … the challenge is about controlling delegated spending, not identifying a particular fictional AI provider."* |
| H9 | **Capability attenuation tokens (macaroon-style)** | Crowded in 2026 — IETF `draft-niyikiza-oauth-attenuating-agent-tokens`, DeepMind Delegation Capability Tokens, `capmas`. Our tighten-only mandate already *is* attenuation. Not white space. |
| H10 | **Risk scoring / behavioural anomaly** | No training data; trivially fakeable; indefensible under questioning. |
| H11 | **Transaction simulation / sandbox** | No execution environment exists in the official contract. |
| H12 | **Formal verification of the policy** | Real depth, but nothing to verify *against* — the bug we found is in the window semantics, not the rule logic, and a model checker would need the same insight to find it. |
| H13 | **Account-scope enforcement** (`monthly_limit_chf`) | Falsified in an earlier pass: no account-scoped counter in the official API, window semantics unstated, and the naive version was defeated three ways. |
| H14 | **Semantic transaction equivalence** (is this "the same" purchase?) | We already have the basket fingerprint. A looser notion needs a similarity threshold, which is a tunable, which is a liability. |
| H15 | **Policy saturation detection** (spot an agent that always claims the maximum) | Tempting — H3 showed saturation is the *real* attack. But detecting it needs a baseline of normal merchant text we do not have, and a false positive blocks an honest merchant with a generous return policy. |
| **H16** | **Window-containment correctness for rolling caps** | **SURVIVES.** See below. |

## H16 — why it survives

Every other candidate fails on one of: no channel, no data, no attacker, already
built, already standard, or needs a tunable. H16 fails none of them.

| test | result |
| --- | --- |
| Real attacker? | Yes — the agent chooses proposal order, and the protocol defers step-ups by design. |
| Real channel? | Yes. Both paths are the official protocol, not an invented one. |
| Real attack? | **Measured.** 367/400 random arrival orders breach the customer's CHF 300/7-day cap, worst case CHF 389. And with *strictly chronological* delivery, a deferred step-up produces **CHF 480 against a CHF 300 cap**. |
| Authoritative data? | Yes — `_approved_spend`, already persisted, already checkpointed. |
| Enforceable? | Yes, as a pure function. |
| Second source of truth? | No. Zero new state. |
| Survives restart / concurrency? | It is derived from the checkpointed ledger and computed under the existing lock. |
| Official replay? | **Unchanged — all five scenarios identical.** |
| Honest demo? | Yes, entirely within official semantics. |
| Trivially reproducible by a competitor? | The *fix* is easy once you know. **Finding it is not** — the natural implementation is backward-looking and passes every ordinary test. |
| Complexity? | One pure function; no new state, endpoints or dependencies. |

**The one that survived is not a feature. It is a correctness property that the
official specification's own requirements induce a violation of.**

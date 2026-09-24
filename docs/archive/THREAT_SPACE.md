# Threat space map

One row per boundary the delegation crosses. The last column is what this map exists
for: **where the cell is empty, there is either a real gap or a reason it cannot be
filled.**

| boundary | attacker capability | authoritative source | observable facts | uncertainty | our control | residual risk |
| --- | --- | --- | --- | --- | --- | --- |
| **customer intent → words** | none (the customer writes it) | the customer | the instruction text | the customer may be vague or self-contradictory | `open_questions` shown before confirmation | an instruction can be ambiguous and we fail toward silence rather than guessing |
| **words → policy** | none | the deterministic compiler | `hard_rules`, `uncertainty_policy` | phrases we cannot map | every unmapped phrase becomes a visible question, never a guessed rule | a rule the customer *meant* but never said is not enforced |
| **policy → mandate** | none | the mandate record | status, rules | — | tighten-only by construction; frozen rules, append-only | — |
| **mandate → agent** | the agent reads it | platform | mandate snapshot | — | the agent cannot write it | the agent knows the rules, so it knows the edges |
| **agent → proposal** | **total** — which purchases, how many, in what order, all free text | none; this is the attack surface | amount, currency, merchant, basket, item text | everything here is a claim | every claim is either verified or narrowed | **the agent chooses the decomposition of a job into permitted purchases** |
| **merchant → item facts** | **total** — `item_details` is free text | none | derived size, return window, final sale | the merchant may simply lie | three narrow extractors; NFKC-normalised; each can only narrow | **`order.return_window_days` and `item.size` have NO input other than merchant text** |
| **platform → status** | none | platform | `authority_status`, `card_status_at_attempt`, `mandate.status`, `card_id`, `timestamp` | — | honoured as hard fails | read from the run snapshot, not the live event, for `mandate.status` |
| **arithmetic** | can misstate | the published FX table + the event's own parts | `amount`, `currency`, `billing_amount_chf`, `items_subtotal`, `delivery_fee` | none — it is checkable | recomputed both ways, always-on | — |
| **proposal → decision** | none | the engine | rule outcomes + their authority | unknown facts | `fail > unknown > pass`; uncertainty escalates, never approves | — |
| **decision → ledger** | none | `RunState._decisions` | write-once per id | — | idempotent replay; basket fingerprint detects a changed re-delivery | — |
| **ledger → execution** | can retry, race, crash | the ledger | merchant, amount, lifecycle | — | one enforcement point, atomic compare-and-set | single-use is **process-local** |
| **sequence of decisions** | can compose permitted purchases | the ledger | rolling spend, duplicate window, job fulfilment | how many performances the customer meant | rolling caps enforced; **job counting derived but NOT in the decision path** | **individually-permitted purchases composing into an unintended outcome** |
| **time** | can wait | nothing the customer can set | simulated purchase time | — | rolling windows | **no horizon is expressible**; a rate is not a total |
| **account** | — | `accounts.csv` | `monthly_limit_chf` | window semantics unstated | **none** | real bound, **not enforceable** — no account-scoped counter in the API |
| **human step-up** | can choose *what* gets asked | the customer's answer | the recorded resolution | — | one purchase only; conflicting second answer refused; revocation wins | **unauthenticated; no `resolved_by` recorded** |
| **explanation → agent** | **reads every reason we give** | — | reason codes, evidence | — | **none today** | **← the empty cell this pass is about** |

## The empty cell

Every other row has a control. The last one has none, and it is not obviously a
threat — which is why it stays empty in most designs.

The wallet tells the agent *why* it refused. Those reasons are computed from the same
rules the agent is trying to satisfy. The more precisely we explain, the more precisely
we describe the boundary the agent is probing.

This is well understood in machine learning — counterfactual explanations enable
model-extraction and evasion-path optimisation — and, as far as this research found, is
not treated as a design constraint in agentic-payment work. It becomes concrete here
because two of our rule fields rest on nothing but merchant free text: telling the agent
*"a return window of 14 days or more would satisfy this"* is telling it exactly what
sentence to put in `item_details`.

That is the white space §5 of the audit examines.

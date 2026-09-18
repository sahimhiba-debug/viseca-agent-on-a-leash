# Official schema — security audit

**Generated from `data/official/schemas/authorization_event.schema.json`.** Regenerate rather than edit.

This audit exists because the two largest vulnerabilities in this project were
*dead authoritative fields*: the schema declared them, the platform always sent
them, and the decision path never read them.

- **V1** — `authority_status` / `card_status_at_attempt`: a revoked authority, an
  expired authority and a blocked card all returned ALLOW and charged.
- **V12** — `mandate.status`: a revoked mandate still authorized. Missed by the V1
  audit because that audit walked only TOP-LEVEL `authorization` properties and
  never descended into `mandate`, `context`, `runtime`, `merchant` or `items[]`.

So this version walks every nested object, and every unread field carries a written
reason. "Probably fine" is how V12 survived four passes.

## Every field

| Field | Enum / type | Engine | Pay | If unread, why |
| --- | --- | :-: | :-: | --- |
| `authorization.amount` | `number` | yes | — |  |
| `authorization.authority_status` | `active, revoked, expired` | yes | — |  |
| `authorization.authorization_id` | `string` | yes | — |  |
| `authorization.billing_amount_chf` | `number` | yes | — |  |
| `authorization.card_id` | `string` | yes | — |  |
| `authorization.card_status_at_attempt` | `active, blocked` | yes | — |  |
| `authorization.channel` | `ecommerce, in_store, mobile_wallet, recurring, atm` | yes | — |  |
| `authorization.currency` | `CHF, EUR, GBP, USD` | yes | — |  |
| `authorization.customer_device_id` | `string` | yes | — |  |
| `authorization.delivery_by` | `['string', 'null']` | NO | — | *informational* — a delivery date; no rule reads it and none could gate authorization on it |
| `authorization.delivery_fee` | `number` | yes | — |  |
| `authorization.fulfillment_method` | `string` | NO | — | *informational* — `order_returnable` already carries the security-relevant consequence |
| `authorization.initiator_type` | `None` | NO | — | *conservative default* — everything is treated as agent-initiated, the strictest reading; trusting a "customer" claim here would be an escalation channel |
| `authorization.items` | `array` | yes | — |  |
| `authorization.items_subtotal` | `number` | yes | — |  |
| `authorization.mandate_id` | `string` | yes | — |  |
| `authorization.merchant` | `None` | yes | — |  |
| `authorization.order_cancellable` | `true, false, unknown, not_applicable` | yes | — |  |
| `authorization.order_returnable` | `true, false, unknown, not_applicable` | yes | — |  |
| `authorization.profile_id` | `string` | NO | — | *routing* — identity is bound on card_id + mandate_id, the two that gate history and rules |
| `authorization.purchase_description` | `string` | NO | — | *UNTRUSTED TEXT* — deliberately never read -- it is the field AU0020 uses to call a cycling helmet a "Running shoes order". The basket is read instead |
| `authorization.recent_attempt_count_10m` | `integer` | yes | — |  |
| `authorization.related_authorization_id` | `['string', 'null']` | yes | — |  |
| `authorization.related_authorization_status` | `pending, approved, declined, cancelled, None` | yes | — |  |
| `authorization.replay_order` | `integer` | NO | — | *deliberate* — reading it would be scenario-shaped logic; the no-hardcoding rule forbids it |
| `authorization.scenario_id` | `string` | NO | — | *deliberate* — same -- never branch on scenario identity |
| `authorization.source_authorization_id` | `string` | yes | — |  |
| `authorization.spend_in_period_before_chf` | `['number', 'null']` | NO | — | *deliberate* — platform-computed spend; we compute our own from decisions actually taken, so a wrong or stale value cannot widen a limit |
| `authorization.timestamp` | `string` | yes | — |  |
| `mandate.card_id` | `string` | yes | — |  |
| `mandate.customer_id` | `string` | NO | — | *carried* — present on the snapshot; identity is bound on card and mandate id |
| `mandate.hard_rules` | `array` | yes | — |  |
| `mandate.instruction` | `string` | NO | — | *carried* — the text the rules were compiled from; the compiled rules are what is evaluated |
| `mandate.mandate_id` | `string` | yes | — |  |
| `mandate.profile_id` | `string` | NO | — | *routing* — as above |
| `mandate.status` | `active, superseded, revoked, expired` | yes | — |  |
| `mandate.uncertainty_policy` | `ask, decline, approve` | yes | — |  |
| `context.approved_spend_in_period_chf` | `['number', 'null']` | NO | — | *deliberate* — same reason; available as a cross-check, not a decision input |
| `context.recent_authorizations` | `array` | NO | — | *evidence only* — we keep our own recent-attempt ledger; a supplied list could be curated |
| `runtime.context_basis` | `None` | NO | — | *informational* — describes how the platform computed context we do not use |
| `runtime.history_window_minutes` | `integer` | NO | — | *informational* — our duplicate window is our own constant |
| `runtime.received_at` | `string` | NO | — | *informational* — transport timestamp; deadlines use the real clock |

## Result

- Fields in schema: **42**
- Read by the decision path: **26**
- Unread, with a stated reason: **16**
- Unread with NO stated reason: **0** (none)

Every field carrying an authorization-relevant enum — `authority_status`,
`card_status_at_attempt`, `mandate.status`, `order_returnable`, `currency`,
`related_authorization_status` — is now read and enforced.

## The rule this audit encodes

> A field the platform is authoritative for, and that can say "no", must be read.
> If it is not read, the reason is written here — and "informational" means
> someone checked that it cannot say no.

`purchase_description` is the one field deliberately unread for a *security*
reason rather than an informational one: it is merchant-controlled narrative, and
the official data itself ships AU0020 describing a cycling helmet as a "Running
shoes order".

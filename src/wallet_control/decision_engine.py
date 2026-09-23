"""The deterministic wallet-control decision engine.

This is where "the agent proposes, the control layer decides" is actually
enforced. Given one authorization event, the confirmed mandate snapshot bound to
this run, and the run's accumulated state, it returns exactly one of ALLOW /
REVIEW / BLOCK, with the evidence and rule outcomes that produced it.

No language model sits in this path. Every input here is either a platform-
supplied structured field, a customer-authored hard rule, or a signal this
engine derived itself from trustworthy history/state -- never merchant-supplied
text (see `facts.py` for where that boundary is actually drawn).

Decision priority (matches the three-way distinction technical_details.md and
challenge.md ask for):

  1. Any hard rule clearly FAILS  -> BLOCK. A clear violation is never softened
     by an uncertain fact elsewhere.
  2. No failure, but something is UNKNOWN -> apply the mandate's own
     `uncertainty_policy` (ask/decline/approve). This is the customer's explicit
     choice about how to handle insufficient information, not the engine's.
  3. Every hard rule PASSES -> ALLOW.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from .drift import AuthorizationDrift, compute_drift
from .facts import (
    PurchaseFacts,
    build_purchase_facts,
    extract_return_window_days,
    extract_stated_size,
    mentions_final_sale,
)
from .intervention import InterventionKind, classify_intervention
from .mandate import HardRule, MandateSnapshot, MandateStatus, UncertaintyPolicy, mandate_policy_version
from .money import to_chf, to_decimal
from .rules import RuleContext, RuleEvaluation, evaluate_rule
from .state import DUPLICATE_WINDOW, BasketKey, PaymentAuthority, RunState
from .viseca_mapping import Decision

_DUPLICATE_RULE = HardRule(field="order.duplicate_suspected", operator="=", value="false")
# WHAT THE AGENT SAYS IT IS BUYING, against what the catalogue says that thing IS.
#
# `item.category` is the rule doing the most work across all five official scenarios,
# and the category arrives IN THE EVENT, supplied for each line. Through
# `/api/agent/propose` it is supplied by the agent -- the party being judged. Nothing
# checked it, and `data/official/items.csv` was already loaded in the same process:
#
#     a gift card labelled `gift_card`   ->  BLOCK on a grocery mandate
#     the same gift card labelled
#     `groceries`                        ->  ALLOW, "matches the rules you set"
#     a hotel room labelled `groceries`  ->  ALLOW
#     an item id that does not exist     ->  ALLOW
#
# CHF 100 of stored value, on a mandate that says groceries, by writing a different
# word. This is not the silence channel -- that one withholds a fact and is routed to
# `uncertainty_policy`. This one MISSTATES a fact, and misstatement is not absence:
# the event names an id and then contradicts what that id is. A contradiction is a
# FAIL, which is what keeps `approve when unsure` from waving it through.
_CATALOGUE_RULE = HardRule(field="item.matches_the_catalogue", operator="=", value="true")
_MERCHANT_RECORD_RULE = HardRule(field="merchant.matches_the_record", operator="=", value="true")

# Rules whose truth depends on what KIND of thing is in the basket. An id the
# catalogue cannot identify only matters to a customer who constrained the kind --
# see `_catalogue_agreement` for why the escalation is scoped rather than global.
_CATEGORY_DEPENDENT = frozenset({"item.category", "item.unrequested_present"})
_NO_RULES_RULE = HardRule(field="mandate.has_no_rules", operator="=", value="false")
_AMOUNT_INTEGRITY_RULE = HardRule(field="authorization.amount_integrity", operator="=", value="true")
_EVENT_READABLE_RULE = HardRule(field="authorization.event_readable", operator="=", value="true")

# The fields this engine dereferences without first asking whether they are there,
# and the item-line fields it dereferences per line. Missing any of them used to be
# an exception rather than a decision -- see `_unreadable_event`.
_REQUIRED_AUTH_FIELDS = (
    "authorization_id", "source_authorization_id", "merchant", "timestamp", "amount", "currency",
    "billing_amount_chf", "items_subtotal", "delivery_fee", "channel",
    "customer_device_id", "recent_attempt_count_10m", "order_returnable",
    "order_cancellable", "items",
)
# ONLY WHAT THE ENGINE DOES ARITHMETIC ON. `item_id`, `item_name` and
# `item_category` are deliberately NOT here: a line that carries none of them is
# already handled further down, proportionally and per-mandate -- the catalogue makes
# an unidentifiable item `unknown` where the customer constrained what may be bought,
# and says nothing where they did not. Requiring them here would block a purchase on
# a mandate that only set a price cap, which is the over-blocking the challenge warns
# about, and would undo that scoping from the other direction.
#
# It is also where the official schema stops: `items` carries `minItems: 1` and NO
# item schema at all -- no properties, no required list. The envelope, which the
# platform writes, is specified to the field; the line, which the proposer writes, is
# not specified at all.
_REQUIRED_ITEM_FIELDS = ("quantity", "unit_price", "currency")
_REQUIRED_MERCHANT_FIELDS = ("merchant_id", "merchant_name", "merchant_category")


def _unreadable_event(event: dict[str, Any]) -> list[str]:
    """Which parts of this event cannot be read at all.

    THE OFFICIAL WORKER OUTLINE MAKES THIS OURS: "Read the envelope's run ID and
    VALIDATE ITS DATA EVENT" (technical_details.md, step 7). Nothing in this service
    validated events against `authorization_event.schema.json`, and every field in
    that schema is required -- so any missing one was dereferenced straight into a
    `KeyError` or a `TypeError`, inside the decision path, before any decision
    existed. Measured by `research/erasure.py` over the 45 official events: 1,916 of
    8,124 single-field erasures made the engine RAISE instead of answering.

    A raise is not one of the three answers the wallet owes inside eight seconds, and
    we have NOT measured what the platform does with a missing answer -- so this is
    fixed rather than reasoned about.

    WHY A NAMED REFUSAL AND NOT A BLANKET `except`. Wrapping the decision path in
    `except Exception: return block` would turn every genuine engine defect into a
    silent refusal, and this repository has already been bitten once by a mutation
    probe that made the engine quietly wrong. This lists what the engine actually
    dereferences, so an unreadable event is REFUSED with a reason and anything else
    still crashes loudly in the tests.

    BLOCK, not `unknown`: a wallet that cannot read the purchase cannot authorise it,
    and this is an integrity failure rather than a fact we happen to be unsure of.
    Being the least permissive answer, it also cannot become a bypass.
    """
    missing: list[str] = []
    auth = event.get("authorization")
    if not isinstance(auth, dict):
        return ["authorization"]
    for field in _REQUIRED_AUTH_FIELDS:
        if auth.get(field) is None:
            missing.append(f"authorization.{field}")
    merchant = auth.get("merchant")
    if isinstance(merchant, dict):
        missing.extend(f"authorization.merchant.{f}" for f in _REQUIRED_MERCHANT_FIELDS
                       if merchant.get(f) is None)
    items = auth.get("items")
    if isinstance(items, list):
        for index, line in enumerate(items):
            if not isinstance(line, dict):
                missing.append(f"authorization.items[{index}]")
                continue
            missing.extend(f"authorization.items[{index}].{f}" for f in _REQUIRED_ITEM_FIELDS
                           if line.get(f) is None)
    return missing
# A seller writing to the machine that holds the card. Never a FAIL: the text is
# ineffective against this engine by construction, so it is not evidence that the
# purchase is bad -- it is evidence about the counterparty, and only the customer can
# weigh that. UNKNOWN routes it through their own `uncertainty_policy`, exactly as the
# session signal does.
_MERCHANT_TEXT_RULE = HardRule(field="merchant.text_addresses_the_machine", operator="=", value="false")
_BASKET_PRESENT_RULE = HardRule(field="authorization.basket_present", operator="=", value="true")
_AMOUNT_INTEGRITY_TOLERANCE_CHF = Decimal("0.02")  # allows for independent double-rounding, nothing more

_AUTHORITY_STATUS_RULE = HardRule(field="authorization.authority_status", operator="=", value="active")
_CARD_STATUS_RULE = HardRule(field="authorization.card_status_at_attempt", operator="=", value="active")
_CARD_BINDING_RULE = HardRule(field="authorization.card_id_binding", operator="=", value="true")
_MANDATE_BINDING_RULE = HardRule(field="authorization.mandate_id_binding", operator="=", value="true")
_MANDATE_STATUS_RULE = HardRule(field="mandate.mandate_status", operator="=", value="active")
_AUTHORIZATION_ID_RULE = HardRule(field="authorization.authorization_id_wellformed", operator="=", value="true")

# The exact enums from data/official/schemas/authorization_event.schema.json. A
# value outside these sets is not assumed benign -- it is treated as unknown.
_KNOWN_DEAD_AUTHORITY_STATUSES = frozenset({"revoked", "expired"})
_KNOWN_DEAD_CARD_STATUSES = frozenset({"blocked"})


def _platform_status_evaluations(auth: dict[str, Any]) -> list[RuleEvaluation]:
    """Evaluate the platform's authority/card status fields (see the call site for
    why these are hard failures rather than uncertainty when recognised)."""
    out: list[RuleEvaluation] = []
    for raw, rule, dead, label in (
        (auth.get("authority_status"), _AUTHORITY_STATUS_RULE, _KNOWN_DEAD_AUTHORITY_STATUSES, "authority_status"),
        (auth.get("card_status_at_attempt"), _CARD_STATUS_RULE, _KNOWN_DEAD_CARD_STATUSES, "card_status_at_attempt"),
    ):
        if raw == "active":
            out.append(RuleEvaluation(rule=rule, outcome="pass", detail=f"{label}=active", source="safety"))
        elif raw in dead:
            out.append(
                RuleEvaluation(
                    rule=rule,
                    outcome="fail",
                    detail=f"the platform reports {label}={raw!r}; this purchase is not authorized to proceed",
                    source="safety",
                )
            )
        else:
            out.append(
                RuleEvaluation(
                    rule=rule,
                    outcome="unknown",
                    detail=f"{label}={raw!r} is not a status this engine version recognizes",
                    source="safety",
                )
            )
    return out


_MANDATE_STATUS_ABSENT = "<not reported>"


def _reported_mandate_status(event: dict[str, Any]) -> Any:
    """The mandate status the platform reports on THIS event, or
    `_MANDATE_STATUS_ABSENT` when the event does not carry one.

    `mandate` and `mandate.status` are both REQUIRED by
    authorization_event.schema.json, and nothing in this service validates an
    incoming event against that schema. So absence is a MALFORMED event, not an
    event politely declining to comment -- and it must not be the quiet way to
    switch a status check off. Returning None here (the previous behaviour of an
    inline `(event.get("mandate") or {}).get("status")`) made the live-status
    branch below skip itself: drop the block and a revoked mandate was ALLOWed.

    The two sibling status fields already got this right -- `authority_status` and
    `card_status_at_attempt` both route an unrecognised value, None included, to
    `unknown`. Three platform status fields, and this was the one that read a
    missing required field as consent.
    """
    block = event.get("mandate")
    if not isinstance(block, dict):
        return _MANDATE_STATUS_ABSENT
    return block.get("status", _MANDATE_STATUS_ABSENT)


def _run_binding_failures(
    auth: dict[str, Any], mandate: MandateSnapshot, state: RunState,
    reported_mandate_status: Any,
) -> list[RuleEvaluation]:
    """Whether this event belongs to the run evaluating it.

    `card_id` is what the merchant-familiarity lookup is keyed on, so an event
    carrying a different card's identity would borrow that card's purchase history
    and could make an unfamiliar merchant look familiar. `mandate_id` decides whose
    rules are being applied. Both were previously taken from the event and never
    checked, which let the event answer "whose authority is this?" itself.

    Compared exactly: a case variant, a padded value, or one carrying an invisible
    character is a different identity, not a near-enough one.
    """
    failures: list[RuleEvaluation] = []

    # The live authorization_id is this purchase's IDENTITY and the key of the decision
    # ledger. The schema requires a string of minLength 1, and the API addresses the
    # purchase BY it -- `POST /v1/authorizations/{authorization_id}/decision` -- so a
    # null, empty or non-string id is not a purchase we could answer for even if we
    # wanted to. Accepting one meant recording a decision under a degenerate key that a
    # second purchase could collide with.
    raw_id = auth.get("authorization_id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        failures.append(
            RuleEvaluation(
                rule=_AUTHORIZATION_ID_RULE,
                outcome="fail",
                detail=f"authorization_id={raw_id!r} is not a usable identifier",
                source="safety",
            )
        )

    # Is the mandate behind this purchase still in force at all? `mandate.status`
    # is a required field of the official schema with enum
    # ["active","superseded","revoked","expired"] -- it is the platform reporting
    # the result of the customer's DELETE /v1/mandates, and the engine did not read
    # it. A revoked mandate produced ALLOW, minted an authority and charged.
    #
    # This is the twin of the authority_status hole: that field answers "is this
    # authorization still authorized?", this one answers "is the authority behind
    # it still in force?". Enforcing only the first meant revocation worked when it
    # came through our own demo endpoint and silently did not when the platform
    # told us about it. Anything other than ACTIVE is a hard failure -- draft,
    # superseded, revoked and expired are all "not a mandate you may spend under".
    if mandate.status is not MandateStatus.ACTIVE:
        failures.append(
            RuleEvaluation(
                rule=_MANDATE_STATUS_RULE,
                outcome="fail",
                detail=f"the mandate is {mandate.status.value!r}, not active; it cannot authorize a purchase",
                source="safety",
            )
        )

    # The status the platform reports on THIS event, which is not the same thing as
    # the status on the run's snapshot.
    #
    # `technical_details.md` says an existing run keeps its original snapshot, and
    # that is right for the RULES -- a mid-run tightening must not apply retroactively.
    # It is wrong for the STATUS. `live_worker` builds the snapshot from a run's FIRST
    # event and reuses it, so `mandate.status` above could never change, while
    # `authority_status` and `card_status_at_attempt` were read live from every event.
    # Three platform status fields, two live and one frozen: the check existed and was
    # wired to a source that could not move.
    #
    # The platform is documented to reject revoked or expired mandates before queueing
    # a request, so this may never fire. That is an argument for it being cheap, not
    # for leaving one of three status checks inert.
    if reported_mandate_status != mandate.status.value:
        if reported_mandate_status == MandateStatus.ACTIVE.value:
            pass                      # the snapshot is already checked above
        # list, not set: an event may carry an unhashable value here (the schema is
        # not enforced), and `[] in {...}` raises rather than answering False.
        elif reported_mandate_status in [s.value for s in MandateStatus]:
            failures.append(
                RuleEvaluation(
                    rule=_MANDATE_STATUS_RULE,
                    outcome="fail",
                    detail=f"the platform now reports this mandate as {reported_mandate_status!r}, "
                           f"not active; it cannot authorize a purchase",
                    source="safety",
                )
            )
        else:
            failures.append(
                RuleEvaluation(
                    rule=_MANDATE_STATUS_RULE,
                    outcome="unknown",
                    detail=(
                        "the platform did not report a mandate status on this event, "
                        "and the schema requires one"
                        if reported_mandate_status is _MANDATE_STATUS_ABSENT
                        else f"the platform reports mandate status {reported_mandate_status!r}, "
                             f"which this engine version does not recognize"
                    ),
                    source="safety",
                )
            )

    # The customer revoked this run's mandate through our own endpoint. The event's
    # `mandate.status` may still say "active" -- the platform has its own view and may
    # not have caught up, and in the offline/demo path there is no platform to tell.
    # Either way a purchase arriving after the brake was pulled must not be approved.
    #
    # Found by the stateful model immediately after run-level revocation was added:
    # a NEW purchase after revocation used to reach `issue_authority` and raise,
    # crashing the engine rather than declining the purchase. Blocking is both the
    # safe answer and the one the customer asked for.
    if state.is_revoked:
        failures.append(
            RuleEvaluation(
                rule=_MANDATE_STATUS_RULE,
                outcome="fail",
                detail="the customer revoked this mandate; no further purchase may be authorized under it",
                source="safety",
            )
        )

    if auth.get("card_id") != state.card_id:
        failures.append(
            RuleEvaluation(
                rule=_CARD_BINDING_RULE,
                outcome="fail",
                detail=f"event card_id={auth.get('card_id')!r} is not this run's card {state.card_id!r}",
                source="safety",
            )
        )
    if auth.get("mandate_id") != mandate.mandate_id:
        failures.append(
            RuleEvaluation(
                rule=_MANDATE_BINDING_RULE,
                outcome="fail",
                detail=f"event mandate_id={auth.get('mandate_id')!r} is not this run's mandate {mandate.mandate_id!r}",
                source="safety",
            )
        )
    return failures


@dataclass(frozen=True)
class EngineDecision:
    authorization_id: str
    decision: Decision
    reason_codes: tuple[str, ...]
    customer_message: str
    evidence: tuple[str, ...]
    rule_evaluations: tuple[RuleEvaluation, ...]
    intervention: InterventionKind
    facts: PurchaseFacts | None
    idempotent_replay: bool = False
    # True if this authorization_id was re-delivered with DIFFERENT purchase facts
    # (merchant/basket/amount) than the first time. The returned `decision` is the
    # ORIGINAL stored one (never re-evaluated from the mutated facts, and never
    # re-submitted -- see `evaluate_authorization`); this flag tells the caller the
    # event is suspect and should be investigated, not treated as routine.
    authorization_id_conflict: bool = False
    # When a rolling-window rule is what refused this, the simulated time at which
    # the SAME purchase would first fit again. CUSTOMER-FACING ONLY -- a retry time
    # beside an amount is the window's length and remaining balance, which is the
    # policy the agent is never told. `agent_view` does not carry it, and
    # `test_agent_explanation_boundary` fails on any digit that reaches the agent.
    earliest_retry_at: datetime | None = None
    # The same prose `customer_message` is built from, one entry per reason, so a
    # surface that wants a LIST instead of a sentence does not need its own copy of
    # the wording. `ui/index.html` kept one and it drifted three ways in a single
    # afternoon: stale text for two rules whose meaning had changed, and a raw dotted
    # field name on screen for a third that had only just been added.
    plain_reasons: tuple[str, ...] = ()
    # R&D Track E (docs/RND_POLICY_SECURITY_SPLIT.md): the SAME evaluations, scoped
    # to source=="customer" and source=="safety" respectively, decided by the SAME
    # `_decide()` function. Purely explanatory -- `decision` above is computed
    # exactly as before (over the full, unscoped list) and is provably at least as
    # strict as either sub-verdict (see the module docstring's monotonicity note).
    policy_verdict: Decision | None = None
    security_verdict: Decision | None = None
    # R&D Track D (docs/RND_AUTHORIZATION_DRIFT.md): a structured diff against a
    # related/conflicting prior authorization, if one exists. Never gates the
    # decision itself -- `rules.py` already does that; this only explains what
    # changed relative to a reference point.
    drift: AuthorizationDrift | None = None
    # R&D Track A (docs/RND_CAPABILITY_AUTHORITY.md): issued only when decision is
    # "allow" (here or via a later `resolve_authorization` to "allow").
    payment_authority: PaymentAuthority | None = None


_TERMINAL_INTERVENTION: dict[Decision, InterventionKind] = {"allow": "allow", "block": "never", "review": "ask_this_time"}


def _basket_key(items: list[dict[str, Any]]) -> BasketKey:
    """Fingerprint of what was actually in the basket, used to tell a harmless
    repeated delivery from the same authorization_id arriving with a DIFFERENT
    purchase (`authorization_id_conflict`).

    `item_name` is included alongside `item_id` and `quantity` because the name is
    what every `item.*` rule actually reads and what the customer is shown: a
    re-delivery that keeps the same item_id but renames the line from "Monitor" to
    "Gold bar" is a semantically different purchase, and without the name in the
    fingerprint it inherited the original ALLOW unexamined (fourth-pass finding;
    see docs/FINAL_ARCHITECTURE_ATTACK.md).

    `unit_price` is deliberately NOT included: the security-relevant money figure
    is `billing_amount_chf`, which is compared separately, and no rule in the
    official vocabulary reads a per-line price (per-item ceilings are a documented
    non-feature). Re-allocating the same total across lines therefore changes no
    decision, and folding it in would only add fingerprint churn.

    The last three elements are the facts DERIVED from `item_details`, never the
    raw text. This is load-bearing in both directions:

      * A re-delivery that keeps the money and the basket identical but rewrites
        the merchant's text so that a derived fact moves -- "size 43" becoming
        "size 38", or a returnable order becoming FINAL SALE -- is a different
        purchase in every way a rule can see, and previously inherited the
        original ALLOW without ever being re-evaluated (fourth-pass finding).
      * Fingerprinting the raw string instead would fail the opposite way: every
        cosmetic edit, re-encoding or whitespace change by the merchant would
        fork an ordinary network retry into a false conflict. The extractors
        already NFKC-normalize and strip invisible characters, so obfuscation
        noise that moves no fact moves no fingerprint either.

    `order_returnable` also feeds the effective return window but is a
    PLATFORM-supplied field rather than merchant text, so it sits in a different
    trust tier and is not fingerprinted here; see docs/FINAL_ARCHITECTURE_ATTACK.md
    for that residual and why it was scoped out rather than silently folded in.
    """
    fingerprints = [
        (
            # `.get`, because `_unreadable_event` deliberately does NOT require these:
            # an item nobody can identify is handled proportionally further down
            # rather than refused outright. A fingerprint over None is fine -- the
            # sort key below is total -- and two lines that are both anonymous really
            # are indistinguishable to everything that reads this.
            line.get("item_id"),
            line.get("item_name"),
            line["quantity"],
            extract_return_window_days(line.get("item_details", "")),
            mentions_final_sale(line.get("item_details", "")),
            extract_stated_size(line.get("item_details", "")),
        )
        for line in items
    ]
    # SORTING THIS RAISED TypeError, AND THE DECISION PATH HAD NO ANSWER.
    # Three of the six fields are `X | None`, None meaning "the seller stated
    # nothing". Python compares tuples element by element and stops at the first
    # difference, so the None fields were only ever reached when two lines agreed on
    # item_id, item_name AND quantity -- and then it compared None with an int:
    #
    #     two lines of the same product, one "Returns accepted within 30 days",
    #     the other silent  ->  TypeError  ->  HTTP 500 from /api/agent/propose
    #
    # That basket is legal, ordinary, and composed by the untrusted party. The wallet
    # returned no decision at all, which is not one of the three answers it owes.
    #
    # The sort key below is TOTAL: absence sorts as its own thing (`v is None` first)
    # instead of being compared against a value it has no order against. The
    # fingerprint tuples themselves are unchanged, so what counts as the same basket
    # is exactly what it was -- only the ordering is repaired.
    def _total_order(fingerprint: tuple) -> tuple:
        return tuple((v is None, "" if v is None else v) for v in fingerprint)

    return tuple(sorted(fingerprints, key=_total_order))


def _requested_categories(mandate: MandateSnapshot) -> frozenset[str] | None:
    """Which item categories the customer asked for, from any `item.category in ...`
    rule.

    `frozenset(rule.value)` was wrong for a value the rule format explicitly allows:
    `value` may be "a number, a string, or a list containing only strings", so
    `item.category in 20` is schema-legal and raised a TypeError here -- BEFORE any
    rule was evaluated, so `rules.evaluate_rule`'s guard never saw it. A number is
    one value, not an iterable of them, and this now reads it the way `rules.py`
    reads every other list-or-scalar rule."""
    for rule in mandate.hard_rules:
        if rule.field == "item.category" and rule.operator == "in":
            values = rule.value if isinstance(rule.value, list) else [rule.value]
            return frozenset(str(v) for v in values)
    return None


def _projected_period_spend(mandate: MandateSnapshot, state: RunState, as_of: datetime, this_amount: Decimal) -> dict[int, Decimal]:
    projected: dict[int, Decimal] = {}
    for rule in mandate.hard_rules:
        if rule.field == "authorization.billing_amount_chf" and rule.scope == "period" and rule.period_days:
            if not state.has_observed(as_of, timedelta(days=rule.period_days)):
                # The ledger is thin because this run's state was LOST, not because
                # nothing was spent -- and this particular window reaches back past
                # the moment this state started watching. Leaving the entry out makes
                # `rules.py` answer `unknown`. Filling it with the visible total would
                # understate the customer's allowance by exactly the amount nobody can
                # see. Once the state has been watching for `period_days`, the window
                # is fully observed and this stops firing on its own.
                continue
            # The peak of every window CONTAINING this purchase, not the window
            # ending at it -- see `RunState.peak_window_spend_chf`. For a run whose
            # decisions arrive in chronological order with nothing deferred the two
            # agree exactly, which is why the official replay is unchanged.
            projected[rule.period_days] = state.peak_window_spend_chf(
                as_of, this_amount, rule.period_days
            )
    return projected


def _decide(evaluations: list[RuleEvaluation], uncertainty_policy: UncertaintyPolicy) -> tuple[Decision, tuple[str, ...]]:
    failures = [e for e in evaluations if e.outcome == "fail"]
    if failures:
        return "block", tuple(f"hard_rule_failed:{e.rule.field}" for e in failures)

    unknowns = [e for e in evaluations if e.outcome == "unknown"]
    if unknowns:
        reason_codes = tuple(f"uncertain:{e.rule.field}" for e in unknowns)
        if uncertainty_policy == UncertaintyPolicy.DECLINE:
            return "block", reason_codes
        if uncertainty_policy == UncertaintyPolicy.APPROVE:
            return "allow", reason_codes
        return "review", reason_codes

    return "allow", ("all_hard_rules_satisfied",)


def _scoped_verdict(evaluations: list[RuleEvaluation], source: str, uncertainty_policy: UncertaintyPolicy) -> Decision:
    """R&D Track E: the same `_decide()` restricted to one evidence source. This is
    provably at least as permissive as the full-list verdict never -- i.e. never
    MORE permissive -- because the full list is a superset of each scoped list: any
    failure or unknown present in a subset is also present in the full set, so
    `_decide(full)` can only be equally or more restrictive than `_decide(subset)`.
    Verified directly by test_capability_and_drift.py's monotonicity property test."""
    decision, _ = _decide([e for e in evaluations if e.source == source], uncertainty_policy)
    return decision


# Plain sentences for the fields a customer can act on. This is the SAME wording the
# UI shows (`RULE_TEXT` / `UNSURE_TEXT` in ui/index.html); the two are kept in step by
# `test_plain_language_is_consistent_between_the_engine_and_the_ui`.
_PLAIN_FAIL = {
    "authorization.billing_amount_chf": "the amount is above the limit you set",
    "item.name_contains": "this is not the item you asked for",
    "item.category": "this is a kind of item you did not ask for",
    "item.unrequested_present": "the basket contains something you did not ask for",
    "merchant.familiar": "you have never paid this seller before",
    "merchant.category": "this is not the kind of shop you allowed",
    "order.return_window_days": "the return window is shorter than you asked for",
    "item.size": "the size is not the one you asked for",
    "merchant.text_addresses_the_machine": "this seller's product description is written at your wallet, not at you",
    "item.matches_the_catalogue": "this is not the kind of thing the seller's own "
                                  "catalogue says it is",
    "session.integrity_risk": "something about this session looks wrong",
    "order.duplicate_suspected": "this looks like the same order again",
    "authorization.amount_integrity": "the stated CHF amount does not match the currency conversion",
    "authorization.authority_status": "the authority behind this purchase is no longer active",
    "authorization.card_status_at_attempt": "the card is blocked",
    "authorization.mandate_status": "this mandate is no longer active",
    "authorization.basket_present": "this purchase lists no items to check",
}
_PLAIN_UNKNOWN = {
    "order.duplicate_suspected": "this looks like an order you already placed, and the wallet cannot tell whether you meant to order it twice",
    "order.return_window_days": "the seller did not say whether this can be returned",
    "item.size": "the seller did not state the size",
    "merchant.familiar": "the wallet has no purchase history to check this seller against",
    # Concrete and actionable: the customer can answer "yes, that was me on my
    # laptop" in a second. "Something could not be verified" makes them guess, and a
    # question nobody can answer is a question they learn to click through. The AGENT
    # still sees only the class `session` -- `agent_view` never carries this string.
    # Reachable, and each was rendering as a raw dotted field name until the
    # anti-rot check in `test_one_wording_not_two` went looking. An amount rule the
    # engine cannot apply, a basket with no lines, and a mandate that never said what
    # was being asked for -- all three reach a customer.
    "authorization.billing_amount_chf": "the wallet could not work out how this "
                                        "amount compares with the limit you set",
    "item.category": "this purchase lists nothing, so there is nothing to check "
                     "against what you asked for",
    "item.unrequested_present": "your instruction did not say what you were asking "
                                "for, so the wallet cannot tell what is extra",
    "item.matches_the_catalogue": "the wallet has no catalogue entry for one of "
                                  "these items, so it cannot check what it is",
    "merchant.text_addresses_the_machine": "this seller's product description "
                                           "contains instructions aimed at an "
                                           "automated buyer, not at you",
    "session.integrity_risk": "this purchase came from a device that has not been "
                              "used earlier in this session",
    "authorization.basket_present": "this purchase lists no items to check",
}


def _plain_reason(evaluation: RuleEvaluation) -> str:
    rule = evaluation.rule
    # A per-order breach and a rolling-window breach are the SAME field and mean
    # entirely different things to a person: "this order is too big" versus "you have
    # spent too much this week". Collapsing them to one sentence blames the wrong
    # boundary -- the customer would look at the order rather than at the week.
    if rule.field == "authorization.billing_amount_chf" and rule.scope == "period" and evaluation.outcome == "fail":
        window = f"{rule.period_days}-day" if rule.period_days else "rolling"
        # `float(rule.value)` assumed a number, and the rule format does not promise
        # one: `value` may be "a number, a string, or a list containing only strings",
        # so a period rule with a list value raised a TypeError HERE -- after the
        # decision had been computed correctly, while rendering the sentence for the
        # customer. The engine knew the answer and threw it away trying to say it in
        # English. Say it without the figure rather than not at all.
        try:
            return (f"it would take you over the CHF {float(rule.value):g} you allowed "
                    f"across any {window} period")
        except (TypeError, ValueError):
            return f"it would take you over what you allowed across any {window} period"
    # A rolling rule that cannot be COMPUTED is a different sentence again, and the
    # cause matters more here than anywhere else: the customer is being asked about
    # their own ceiling because the wallet lost sight of it, not because this purchase
    # is suspicious. Saying "could not work out how this compares" invites them to
    # re-read the order, which is the wrong place to look.
    if (rule.field == "authorization.billing_amount_chf" and rule.scope == "period"
            and evaluation.outcome == "unknown" and "restarted" in evaluation.detail):
        window = f"{rule.period_days}-day" if rule.period_days else "rolling"
        return (f"this wallet restarted and cannot see what has already been spent in "
                f"this {window} period, so it cannot tell whether this would take you "
                f"over the limit you set")
    # `merchant.familiar` has two unknowns -- no history at all, and history that is
    # the AGENT'S rather than the customer's -- and one entry in the table below. It
    # said "the wallet has no purchase history to check this seller against" while
    # the evidence line beside it said "your agent has paid this seller before, but
    # you have not". A record that is right and a rendering that is wrong is the
    # defect this whole file keeps finding; the basis is already prose, so use it.
    if rule.field == "merchant.familiar" and evaluation.outcome == "unknown" and evaluation.detail:
        return evaluation.detail
    table = _PLAIN_UNKNOWN if evaluation.outcome == "unknown" else _PLAIN_FAIL
    fallback = rule.field.replace(".", " ").replace("_", " ")
    return table.get(rule.field) or f"a check on {fallback} did not pass"


# The constraint CLASSES an agent is allowed to learn about. A class names the KIND of
# thing that failed, never its value: "amount" and not "CHF 120", "window" and not
# "CHF 300 across 7 days, CHF 287 already spent".
_AGENT_CONSTRAINT_CLASS = {
    "authorization.billing_amount_chf": "amount",
    "merchant.familiar": "merchant",
    "merchant.category": "merchant",
    "item.category": "item",
    "item.name_contains": "item",
    "item.size": "item",
    "item.unrequested_present": "basket",
    "order.return_window_days": "order_terms",
    # The agent is told `merchant`, which is both true and the useful direction: an
    # honest planner answers it by shopping somewhere else, which is exactly right.
    # `item` is both true and the useful direction: an honest planner answers it by
    # proposing something else. It never learns WHAT the catalogue says.
    "item.matches_the_catalogue": "item",
    "merchant.text_addresses_the_machine": "merchant",
    "session.integrity_risk": "session",
    "order.duplicate_suspected": "duplicate",
}


def _agent_constraint_class(rule: "HardRule") -> str:
    """Which CLASS of constraint refused, from the rule's field and its scope.

    Scope matters here and nowhere else in this table: the same field means two
    different problems depending on whether it bounds one purchase or a window.
    """
    if (rule.field == "authorization.billing_amount_chf" and rule.scope == "period"):
        return "budget_window"
    return _AGENT_CONSTRAINT_CLASS.get(rule.field, "other")


def agent_view(decision: "EngineDecision") -> dict[str, Any]:
    """What the SHOPPING AGENT may be told about a decision. Deliberately not what the
    customer is told.

    The wallet is an oracle: any decision system is. Measured on this engine, an agent
    that sees only ALLOW/BLOCK recovers a secret CHF 137 ceiling to within CHF 0.24 in
    twelve probes -- and spends CHF 531 of the customer's money doing it, because every
    ALLOW probe is a real purchase. That cost is the only thing making the oracle
    tolerable.

    The customer's payload would collapse that to ZERO probes: it carries the rule's
    numeric `value` and twenty evidence strings reading "projected 7-day spend=287.50
    CHF". That is right for the customer, who owns the policy. Handing the same object
    to the agent would be handing it the policy.

    So this projection carries the decision and the CLASS of constraint that failed,
    and nothing numeric. `test_agent_view_leaks_no_policy_values` fails if a number, a
    rule field name, or an evidence string ever reaches it.

    Naming the class adds no bits the agent could not already get: varying one
    dimension at a time costs exactly one probe per dimension either way.

    A PERIOD BREACH AND AN OVER-LIMIT ORDER USED TO READ THE SAME. Both were
    "amount", on the reasoning that the agent should learn to propose less and not
    how much less. That is still true of the magnitude -- and it made the agent
    answer two economically different situations identically. "This one order is too
    large" is fixed by a cheaper basket of any size. "The rolling allowance is used
    up" is fixed by fitting what remains, or by waiting, and cannot be fixed by
    shopping at all once the remainder is smaller than anything on sale.

    So a period breach now reads `budget_window`. By the docstring's own argument
    this costs nothing: an agent could already separate the two in one probe by
    re-proposing an identical basket and seeing it refused the second time. What it
    still cannot learn from either class is the cap, the remainder, or the window
    length -- and `test_agent_view_leaks_no_policy_values` keeps it that way.
    """
    classes = sorted({
        _agent_constraint_class(e.rule)
        for e in decision.rule_evaluations
        if e.outcome in ("fail", "unknown")
    })
    return {
        "authorization_id": decision.authorization_id,
        "decision": decision.decision,
        "blocked_by": classes,
        # Whether a human could unblock this, so the agent knows to wait rather than
        # retry. Not a policy fact.
        "awaiting_customer": decision.decision == "review",
    }


def _window_retry(evaluations: list[RuleEvaluation], state: "RunState",
                  facts: PurchaseFacts) -> datetime | None:
    """When a rolling-window refusal stops applying.

    "It would take you over the CHF 300 you allowed across any 7-day period" tells a
    customer the week is full. It does not tell them when it stops being full, and
    the engine knows: it holds every approved purchase's simulated timestamp. Making
    someone guess about their own money is a choice, and this is the other one.

    A card cannot answer this at all. It has no notion of the customer's window --
    only of its own month.

    ONLY WHEN THE WINDOW IS THE SOLE REASON. Two of the five refusals in the official
    household-budget scenario fail on the window AND on something else -- an item
    category the customer never asked for, a per-order ceiling. Telling either of
    those customers "you could order this again on Tuesday" would be false: Tuesday
    will not make a jar of something they did not ask for into something they did. A
    retry time attached to a refusal that waiting cannot cure is a worse answer than
    no retry time, because the customer will act on it."""
    failures = [e for e in evaluations if e.outcome == "fail"]
    if len(failures) != 1:
        return None
    for evaluation in failures:
        rule = evaluation.rule
        if (evaluation.outcome != "fail" or rule.scope != "period"
                or rule.field != "authorization.billing_amount_chf" or not rule.period_days):
            continue
        try:
            cap = Decimal(str(rule.value))
        except (ArithmeticError, TypeError, ValueError):
            continue          # a cap the engine cannot read bounds nothing to wait for
        return state.earliest_window_retry(facts.timestamp, facts.billing_amount_chf,
                                           rule.period_days, cap)
    return None


def _catalogue_agreement(items: list[dict[str, Any]]) -> tuple[str | None, str]:
    """Does each line agree with the official catalogue about what it is?

    CATEGORY ONLY, and the narrowness is the point. The catalogue also carries each
    item's NAME and a plausible PRICE BAND, and on the official pack all three agree
    perfectly -- 56/56 names exact, 52/52 prices inside band. Checking all three
    would look stronger here and be worse in the world: a marketplace listing's
    display name varies legitimately, and prices move. Neither would catch anything
    the amount rules do not already bound, so neither is checked. Recorded as a
    decision rather than left as a silent omission.

        id known, category agrees                    pass
        id known, category CONTRADICTS the catalogue fail
        id not in the catalogue                      UNKNOWN

    THE CATALOGUE CAN REFUTE A CLAIM. IT CAN NEVER CONFIRM ONE. An id it has never
    heard of is neither a refutation nor a confirmation, and the third value is what
    that is called here.

    THE LAST LINE USED TO BE `SILENT`, AND SILENCE WAS THE BUG. Measured through this
    engine, on a mandate reading `item.category in ['groceries']`:

        real gift card, labelled gift_card          block
        real gift card, RELABELLED groceries        block   <- refuted
        INVENTED id, labelled groceries             ALLOW
        NO id at all, labelled groceries            ALLOW

    An agent got a better outcome by saying LESS. Naming the item honestly was
    punished and withholding it was rewarded, so the check only ever caught an
    attacker careless enough to supply a real id -- and the Delegate tab meanwhile
    told the customer the catalogue could refuse this rule, which put the choice of
    whether that was true in the attacker's hands.

    WHAT THE OLD ARGUMENT GOT RIGHT, AND WHERE IT IS ANSWERED. The official pack is a
    closed world of 66 items; a real wallet sees goods it has no entry for constantly,
    and the challenge is explicit that "blocking ordinary shopping unnecessarily is
    also a failure". Escalating every unrecognised item would indeed make the control
    useless. So the escalation is PROPORTIONAL: the caller raises it only when the
    mandate actually contains a rule that reads a category (`_CATEGORY_DEPENDENT`).
    A customer who never constrained what may be bought pays nothing for a catalogue
    that has not heard of their shopping; a customer who did constrain it, and whose
    agent presents goods nobody can identify, is told that the rule they wrote could
    not be checked. It is `unknown`, never `fail` -- no evidence the purchase is bad --
    so their own `uncertainty_policy` decides, exactly like every other unknown.

    On the official pack this costs nothing measurable: 56 of 56 item lines carry an
    id the catalogue knows and 56 of 56 stated categories match it exactly.

    Reference data is read-only and never a rule: this compares two claims and
    reports which, it does not compile anything.
    """
    from .csv_data import load_items

    catalogue = load_items()
    contradicted, unknown = [], []
    for line in items:
        item_id = line.get("item_id")
        claimed = line.get("item_category")
        if not item_id or item_id not in catalogue:
            unknown.append(str(item_id) if item_id else "an item line with no id")
            continue      # unrefuted, NOT confirmed. See the docstring.
        actual = catalogue[item_id]["item_category"]
        if claimed != actual:
            contradicted.append(f"{item_id} is described as {claimed!r} but the "
                                f"catalogue lists it as {actual!r} "
                                f"({catalogue[item_id]['item_name']})")
    if contradicted:
        return "fail", "; ".join(contradicted)
    if unknown:
        return "unknown", ("the catalogue has no entry for " + ", ".join(unknown)
                           + ", so what kind of thing it is rests on the seller's "
                             "own description")
    return None, ""


def _merchant_record_agreement(auth: dict[str, Any]) -> tuple[str | None, str]:
    """Does the shop's stated KIND agree with the shop's own record?

    THE SAME HOLE AS `_catalogue_agreement`, ON THE OTHER SIDE OF THE EVENT, and it
    survived a full provenance audit because the audit and the code shared a
    misunderstanding. `provenance.py` declared `merchant.category` BOUND, "loaded
    from reference data, never from the proposal". The event BUILDERS do load it from
    `merchants.csv` -- but this engine never did. It read whatever the event said:

        mandate: merchant.category in ['groceries']
        RailNest, stated as `transport` (its real record)   block
        RailNest, stated as `groceries`                     ALLOW

    ...with `merchants.csv` loaded in the same process, saying `transport`.

    AND THE PROBE MISSED IT FOR THE SAME REASON. `research/forgeable_facts.py`
    attacked this fact by swapping the merchant ID, which changes the shop and
    therefore the purchase, so it measured BOUND and agreed with the declaration.
    It never relabelled the category of the SAME shop. A test written from the same
    misunderstanding as the code confirms the code.

    Scoped exactly like the item catalogue, for the same reasons:

        id known, category agrees                    pass
        id known, category CONTRADICTS the record    fail
        id not in the reference data                 UNKNOWN

    REFUTES, NEVER CONFIRMS. And the unknown is raised by the caller only when the
    mandate actually constrains the merchant's kind, so a customer who never asked
    about it pays nothing for a shop the reference data has not heard of.

    On the official pack this moves nothing: all 45 events are built from
    `merchants.csv`, so every stated category already equals its record.
    """
    from .csv_data import load_merchants

    merchant = auth.get("merchant") or {}
    merchant_id = merchant.get("merchant_id")
    stated = merchant.get("merchant_category")
    record = load_merchants().get(merchant_id) if merchant_id else None
    if record is None:
        return "unknown", (f"there is no merchant record for {merchant_id!r}, so what "
                           f"kind of shop this is rests on the purchase's own claim")
    actual = record["merchant_category"]
    if stated != actual:
        return "fail", (f"this purchase describes {merchant_id} as {stated!r}, but the "
                        f"merchant record lists it as {actual!r} "
                        f"({record['merchant_name']})")
    return None, ""


def _customer_message(decision: Decision, evaluations: list[RuleEvaluation], facts: PurchaseFacts,
                      retry_at: datetime | None = None) -> str:
    """Prose for a person. The technical detail goes in `evidence`, not here.

    `technical_details.md` shows this field carrying sentences -- "Please review this
    purchase." -- and says to "show the reason and purchase details to the real
    customer". This used to emit the engine's internal evaluation dump instead:

        Declined: CHF 62.0 at Alpine Basket -- authorization.billing_amount_chf
        (fail): projected 7-day spend=361.5 CHF (including this purchase);
        item.category (fail): item_categories=['cosmetics', 'groceries'], outside
        requested set: ['cosmetics']

    Internal field names, the engine's own `(fail)` vocabulary, and a Python list
    repr -- submitted to the platform in a field called `customer_message`. The demo
    UI was never affected, because it renders `reason_codes` through its own
    plain-language table and hides the raw evidence behind a disclosure. The OFFICIAL
    path had no such layer, so the polished explanation existed only where we happened
    to look. The same facts still reach the platform, in `evidence`, which the spec
    describes as "facts supporting the result".
    """
    amount = f"CHF {facts.billing_amount_chf}"
    problems = [e for e in evaluations if e.outcome in ("fail", "unknown")]
    if decision == "allow":
        # AN APPROVAL ON EVIDENCE AND AN APPROVAL ON THE ABSENCE OF EVIDENCE ARE NOT
        # THE SAME EVENT, and this sentence used to render them identically.
        #
        # With `uncertainty_policy = approve`, a rule the wallet COULD NOT CHECK is
        # allowed through by the customer's own fallback. The engine knows: its
        # `reason_codes` read `uncertain:order.return_window_days` rather than
        # `all_hard_rules_satisfied`. But the one field a person actually reads said
        # "matches the rules you set" -- of a purchase whose return terms were never
        # established. The customer asked for a 14-day return window and was told
        # their rule had matched, about a seller who said nothing at all.
        #
        # That is worse than unhelpful. It is the only sentence that could have told
        # them their fallback, not their rule, is what approved this; and a customer
        # who cannot see when uncertainty is being spent cannot decide to stop
        # spending it. Same defect class as I39: a representation that is correct in
        # the record and false in the rendering.
        unknowns = [e for e in evaluations if e.outcome == "unknown"]
        if unknowns:
            reasons = "; ".join(dict.fromkeys(_plain_reason(e) for e in unknowns))
            return (f"Approved: {amount} at {facts.merchant_name}. Not because the rules "
                    f"were met -- {reasons}. You told the wallet to go ahead when it "
                    f"cannot be sure.")
        return f"Approved: {amount} at {facts.merchant_name} matches the rules you set."
    reasons = list(dict.fromkeys(_plain_reason(e) for e in problems))
    detail = "; ".join(reasons) if reasons else "a check did not pass"
    if decision == "block":
        when = ""
        if retry_at is not None:
            # Their own local reading of a simulated clock; the day name is what makes
            # it answerable without arithmetic.
            when = f" You could order this again on {retry_at.strftime('%A %-d %B at %H:%M')}."
        return f"Declined: {amount} at {facts.merchant_name}. Reason: {detail}.{when}"
    return (
        f"Please review this purchase: {amount} at {facts.merchant_name}. "
        f"The wallet could not decide on its own because {detail}."
    )


def evaluate_authorization(event: dict[str, Any], mandate: MandateSnapshot, state: RunState) -> EngineDecision:
    """Evaluate one `authorization.request` event against `mandate` using `state`.

    Idempotent: calling this twice with the same `authorization_id` returns the
    original recorded decision the second time, without re-evaluating rules or
    double-counting spend (technical_details.md step 6 and step 8) -- PROVIDED the
    re-delivered event describes the same purchase. If a repeated `authorization_id`
    shows a different merchant, basket, or amount than the first delivery, that is
    not a legitimate retry; see the `authorization_id_conflict` branch below.
    """
    # One run, one decision at a time. The window check and the record it is based
    # on must not be separated by another thread's decision -- see RunState's lock.
    with state.decision_guard():
        unreadable = _unreadable_event(event)
        if unreadable:
            shown = ", ".join(unreadable[:6]) + ("..." if len(unreadable) > 6 else "")
            evaluation = RuleEvaluation(
                rule=_EVENT_READABLE_RULE, outcome="fail",
                detail=f"the event does not carry: {shown}", source="safety")
            return EngineDecision(
                authorization_id=str((event.get("authorization") or {}).get("authorization_id")
                                     or "<unreadable>"),
                decision="block",
                reason_codes=("hard_rule_failed:authorization.event_readable",),
                customer_message=("This purchase could not be authorized: the wallet "
                                  "could not read what was being bought. Nothing was "
                                  "approved."),
                evidence=(f"{evaluation.rule.field} [fail]: {evaluation.detail}",),
                rule_evaluations=(evaluation,),
                intervention=_TERMINAL_INTERVENTION["block"],
                facts=None,
                security_verdict="block",
            )

        auth = event["authorization"]
        authorization_id = auth["authorization_id"]
        merchant_id = auth["merchant"]["merchant_id"]
        basket_key = _basket_key(auth["items"])
        billing_amount_chf = to_decimal(auth["billing_amount_chf"])

        # "Is this event even ours?" is answered BEFORE "have we seen this purchase?".
        # Ordering matters: the repeat-delivery fingerprint covers merchant, basket and
        # amount but not identity, so a re-delivery carrying a different card_id or
        # mandate_id would otherwise match the fingerprint and be answered with the
        # stored decision -- returning a real answer to an event that was never ours to
        # answer. See docs/DEEP_SECURITY_RESEARCH.md (V5).
        binding_failures = _run_binding_failures(
            auth, mandate, state,
            reported_mandate_status=_reported_mandate_status(event),
        )
        if binding_failures:
            return EngineDecision(
                authorization_id=authorization_id,
                decision="block",
                reason_codes=tuple(f"hard_rule_failed:{e.rule.field}" for e in binding_failures),
                customer_message=(
                    "This purchase could not be authorized: it does not belong to this wallet session, "
                    "or the mandate behind it is no longer in force. Nothing was approved."
                ),
                evidence=tuple(f"{e.rule.field} [{e.outcome}]: {e.detail}" for e in binding_failures),
                rule_evaluations=tuple(binding_failures),
                intervention=_TERMINAL_INTERVENTION["block"],
                facts=None,
                security_verdict="block",
            )

        # The platform's status fields are read BEFORE the repeat-delivery branch, and
        # a dead status revokes this run's outstanding authority even when the delivery
        # is a routine replay.
        #
        # The two halves of that are deliberately different, because the correct answer
        # differs. The DECISION must still be the stored one: the platform already has
        # our answer for this authorization_id and re-sending a different one is not
        # something the official contract permits (technical_details.md step 6). But
        # money that has not moved yet is ours to stop, and a platform telling us the
        # authority is revoked or the card is blocked is the most authoritative reason
        # there is to stop it. Found by the mutation fuzzer in
        # tests/security/test_authority_mutation_fuzzer.py, which is exactly the kind
        # of composition (status change + replay) a per-field test does not reach.
        platform_status = _platform_status_evaluations(auth)
        if any(e.outcome == "fail" for e in platform_status):
            state.revoke_authority(authorization_id)

        stored = state.get_stored_decision(authorization_id)
        if stored is not None:
            if not state.check_repeat_fingerprint(
            authorization_id,
            merchant_id=merchant_id,
            basket_key=basket_key,
            billing_amount_chf=billing_amount_chf,
            # Parsed here rather than reusing the later local: the fingerprint check
            # runs BEFORE `timestamp` is bound at the top of the evaluation proper.
            timestamp=datetime.fromisoformat(auth["timestamp"].replace("Z", "+00:00")),
        ):
                # Same authorization_id, different purchase. Neither trust the old
                # decision (it was made on different facts) nor silently re-evaluate
                # and re-submit a new one (the platform already has a decision for this
                # ID). Fail closed and flag it loudly; the ORIGINAL stored decision is
                # left untouched, so the payment boundary still enforces the amount
                # that was actually approved, not whatever this mutated event claims.
                conflict_drift = compute_drift(
                    reference_authorization_id=authorization_id,
                    prior_merchant_id=stored.merchant_id,
                    prior_basket_key=stored.basket_key,
                    prior_amount_chf=stored.billing_amount_chf,
                    current_merchant_id=merchant_id,
                    current_basket_key=basket_key,
                    current_amount_chf=billing_amount_chf,
                )
                return EngineDecision(
                    authorization_id=authorization_id,
                    decision="block",
                    reason_codes=("authorization_id_conflict",),
                    customer_message=(
                        "This purchase could not be verified: the same authorization was received twice "
                        "with different details. The original decision was left unchanged."
                    ),
                    evidence=(
                        f"original: merchant={stored.merchant_id} amount={stored.billing_amount_chf} basket={stored.basket_key}",
                        f"received: merchant={merchant_id} amount={billing_amount_chf} basket={basket_key}",
                    ),
                    rule_evaluations=(),
                    intervention=_TERMINAL_INTERVENTION["block"],
                    facts=None,
                    idempotent_replay=False,
                    authorization_id_conflict=True,
                    drift=conflict_drift,
                )
            return EngineDecision(
                authorization_id=authorization_id,
                decision=stored.decision,
                reason_codes=("repeated_delivery",),
                customer_message="This purchase was already decided; returning the recorded result unchanged.",
                evidence=(f"original decision recorded at {stored.timestamp.isoformat()} for CHF {stored.billing_amount_chf}",),
                rule_evaluations=(),
                intervention=_TERMINAL_INTERVENTION[stored.decision],
                facts=None,
                idempotent_replay=True,
            )

        card_id = auth["card_id"]
        device_id = auth["customer_device_id"]
        timestamp = datetime.fromisoformat(auth["timestamp"].replace("Z", "+00:00"))

        merchant_familiar = state.history.is_familiar(card_id, merchant_id)
        # The event's own velocity claim, cross-checked against what this run has
        # actually seen. An event that under-reports its neighbours suppresses the
        # session-integrity rule entirely: four attempts inside one minute with a
        # device change, every event reporting 0, turned two BLOCKs into ALLOWs while
        # our own log held all four. `max` rather than a replacement, because the
        # platform legitimately sees attempts we cannot (measured on the official
        # corpus: reported exceeds observed once, observed NEVER exceeds reported, so
        # this cannot move the replay) -- and because it is monotone, it can only ever
        # raise risk, never lower it.
        reported_attempts = auth["recent_attempt_count_10m"]
        observed_attempts = state.observed_attempts_within(timestamp)
        session_risk, session_reasons = state.session_signals(
            device_id, max(reported_attempts, observed_attempts), merchant_familiar
        )
        if observed_attempts > reported_attempts:
            session_reasons = (
                *session_reasons,
                f"this purchase reports {reported_attempts} other recent attempts; "
                f"this session has seen {observed_attempts}",
            )
        duplicate = state.find_similar_recent(
            authorization_id=authorization_id,
            merchant_id=merchant_id,
            basket_key=basket_key,
            billing_amount_chf=billing_amount_chf,
            timestamp=timestamp,
        )
        duplicate_of, duplicate_reason = duplicate if duplicate else (None, None)

        facts = build_purchase_facts(
            event,
            merchant_familiar=merchant_familiar,
            merchant_familiar_basis=state.history.familiarity_basis(card_id, merchant_id),
            session_integrity_risk=session_risk,
            session_integrity_reasons=session_reasons,
            duplicate_of=duplicate_of,
            duplicate_reason=duplicate_reason,
        )

        # START THE HORIZON CLOCK. A state resumed part-way through knows nothing
        # about the run before this moment, and everything from it onwards. Recorded
        # in the SIMULATED purchase clock, because that is the clock the windows it
        # gates are measured in.
        state.note_observation(facts.timestamp)

        ctx = RuleContext(
            requested_item_categories=_requested_categories(mandate),
            projected_period_spend_chf=_projected_period_spend(mandate, state, facts.timestamp, facts.billing_amount_chf),
            unobserved_periods=frozenset(
                r.period_days for r in mandate.hard_rules
                if r.field == "authorization.billing_amount_chf" and r.scope == "period"
                and r.period_days
                and not state.has_observed(facts.timestamp, timedelta(days=r.period_days))),
        )
        evaluations = [evaluate_rule(rule, facts, ctx) for rule in mandate.hard_rules]

        # Always-on safety checks, independent of what the customer's mandate says --
        # these are control-layer integrity concerns, not policy the customer opted into.
        # The official schema requires amount/billing_amount_chf > 0 (exclusiveMinimum
        # 0), but a malformed or tampered event must not be trusted to have honored
        # that -- a non-positive amount is rejected here regardless of schema validation
        # upstream.
        merchant_verdict, merchant_detail = _merchant_record_agreement(auth)
        if merchant_verdict == "unknown" and not any(
                r.field == "merchant.category" for r in mandate.hard_rules):
            # Nothing was delegated that depends on the KIND of shop, so a shop the
            # reference data cannot identify is not this customer's problem. A
            # refutation is still raised: that is an integrity concern either way.
            merchant_verdict = None
        if merchant_verdict is not None:
            evaluations.append(RuleEvaluation(rule=_MERCHANT_RECORD_RULE,
                                              outcome=merchant_verdict,
                                              detail=merchant_detail, source="safety"))

        catalogue_verdict, catalogue_detail = _catalogue_agreement(auth["items"])
        if catalogue_verdict == "unknown" and not any(
                r.field in _CATEGORY_DEPENDENT for r in mandate.hard_rules):
            # Nothing was delegated that depends on the kind of thing being bought,
            # so an unidentifiable item is not this customer's problem. A refutation
            # ("fail") is still raised -- that is an integrity concern either way.
            catalogue_verdict = None
        if catalogue_verdict is not None:
            evaluations.append(RuleEvaluation(rule=_CATALOGUE_RULE, outcome=catalogue_verdict,
                                              detail=catalogue_detail, source="safety"))
        if facts.merchant_text_addresses_the_machine:
            evaluations.append(RuleEvaluation(
                rule=_MERCHANT_TEXT_RULE, outcome="unknown",
                detail=("this listing speaks to an automated purchasing system about "
                        "your authorization: "
                        + "; ".join(facts.merchant_text_addresses_the_machine)),
                source="safety"))
        if billing_amount_chf <= 0:
            evaluations.append(
                RuleEvaluation(rule=_AMOUNT_INTEGRITY_RULE, outcome="fail", detail=f"billing_amount_chf={billing_amount_chf} is not positive", source="safety")
            )
        # A purchase with NO line items passes every item rule vacuously. `item.category
        # in [electronics]` is satisfied because no item is outside the set;
        # `item.name_contains` because no name fails to match;
        # `item.unrequested_present=false` because there is nothing unrequested. Measured
        # before this check existed: a CHF 400 purchase with an empty basket was ALLOWED
        # against a mandate carrying four item restrictions -- under EVERY uncertainty
        # policy, `decline` included. The strictest setting the customer can choose was
        # not stricter, which is the tell that this is structural rather than uncertain.
        #
        # This is the same class as the `mandate.status` omission: a check switched off by
        # deleting what it guards, needing no forgery. There the attacker removed a field;
        # here they empty an array.
        #
        # `minItems: 1` in authorization_event.schema.json makes an empty basket malformed,
        # and all 45 official events carry items, so this cannot move the replay. It is a
        # hard failure rather than an unknown because `uncertainty_policy` governs
        # uncertainty about a real purchase's facts -- not whether a purchase has any
        # contents at all.
        if not facts.items:
            evaluations.append(
                RuleEvaluation(
                    rule=_BASKET_PRESENT_RULE,
                    outcome="fail",
                    detail="this purchase lists no items, so none of the customer's item rules can be checked against it",
                    source="safety",
                )
            )
        # `amount` is documented as the total INCLUDING delivery, with `items_subtotal`
        # and `delivery_fee` as its components. Nothing checked that they agreed, so an
        # event could claim a CHF 100 total whose parts summed to CHF 600 and be approved
        # against a CHF 400 ceiling. All 45 official rows agree exactly, so a mismatch is
        # an internally inconsistent event, not a rounding artefact.
        #
        # This is the same guard as the FX check below, on the other half of the same
        # arithmetic -- not a new mechanism.
        parts = to_decimal(auth["items_subtotal"]) + to_decimal(auth["delivery_fee"])
        if abs(parts - to_decimal(auth["amount"])) > _AMOUNT_INTEGRITY_TOLERANCE_CHF:
            evaluations.append(
                RuleEvaluation(
                    rule=_AMOUNT_INTEGRITY_RULE,
                    outcome="fail",
                    detail=f"items_subtotal + delivery_fee = {parts} does not match amount={auth['amount']}",
                    source="safety",
                )
            )
        expected_chf = to_chf(to_decimal(auth["amount"]), auth["currency"])
        if abs(expected_chf - billing_amount_chf) > _AMOUNT_INTEGRITY_TOLERANCE_CHF:
            evaluations.append(
                RuleEvaluation(
                    rule=_AMOUNT_INTEGRITY_RULE,
                    outcome="fail",
                    detail=f"billing_amount_chf={billing_amount_chf} does not match amount*fx_rate={expected_chf}",
                    source="safety",
                )
            )
        # The platform's own statement about whether this purchase may proceed at all.
        # `authority_status` and `card_status_at_attempt` are REQUIRED fields of the
        # official event schema and are the most authoritative signals in the whole
        # event: they are the platform saying the authority behind this purchase has
        # been revoked or has expired, or that the card is blocked. Ignoring them --
        # which this engine did until the deep-security pass -- meant a revoked
        # authority still produced ALLOW and still charged. All 45 official rows carry
        # "active"/"active", which is exactly why no fixture ever exercised it.
        #
        # A recognised negative is a hard failure, NOT uncertainty: the customer
        # revoking their authority is not a question to put back to the customer, and
        # an `approve`-on-uncertainty policy must not be able to soften it. Anything
        # unrecognised (a new enum value, an empty string, a case variant, a missing
        # field) is genuinely missing information and goes through uncertainty_policy.
        evaluations.extend(platform_status)

        if duplicate_of is not None:
            evaluations.append(RuleEvaluation(rule=_DUPLICATE_RULE, outcome="unknown", detail=duplicate_reason or "", source="safety"))
        elif not state.has_observed(facts.timestamp, DUPLICATE_WINDOW):
            # "NO SIMILAR RECENT PURCHASE" IS A CLAIM ABOUT THE LAST HOUR, and this
            # state has not been watching for an hour -- it was resumed part-way
            # through, so an order placed before it started is exactly what it cannot
            # see. Measured before this branch existed: the same basket at the same
            # shop five minutes later, with a fresh authorization_id, went `review`
            # with the ledger intact and ALLOW after a restart. One real order,
            # charged twice, and nothing had to be forged.
            #
            # Not `fail`: there may well be no earlier order. It is `unknown`, so the
            # customer's own uncertainty_policy decides, and it stops firing by itself
            # once this state has watched a full hour.
            evaluations.append(RuleEvaluation(
                rule=_DUPLICATE_RULE, outcome="unknown",
                detail=("this wallet restarted less than an hour ago and cannot see "
                        "whether you already placed this order"),
                source="safety"))
        if not mandate.hard_rules:
            # A confirmed mandate with zero executable rules has nothing to check a
            # purchase against. Treating that as "everything passes" would make an
            # empty or unparseable customer instruction into unlimited spending
            # authority -- exactly the "blank cheque" the challenge exists to prevent.
            # Route it through uncertainty_policy like any other missing information
            # instead (ASK by default: every purchase needs the customer; DECLINE:
            # nothing is spent; APPROVE: only if the customer explicitly, visibly chose
            # that -- see the compiler's own open_question for this exact condition).
            evaluations.append(
                RuleEvaluation(rule=_NO_RULES_RULE, outcome="unknown", detail="this mandate has no spending controls to check against", source="safety")
            )

        decision, reason_codes = _decide(evaluations, mandate.uncertainty_policy)

        state.remember_attempt(
            authorization_id=authorization_id,
            merchant_id=merchant_id,
            basket_key=basket_key,
            billing_amount_chf=billing_amount_chf,
            timestamp=timestamp,
        )
        state.record_decision(
            authorization_id, decision, facts.billing_amount_chf, facts.timestamp,
            merchant_id=merchant_id, basket_key=basket_key, reason_codes=reason_codes,
        )

        # R&D Track D: if this purchase names a related prior authorization this run
        # already decided (e.g. a re-quote after a decline), compute what actually
        # changed between them -- purely explanatory evidence, never a gate; `rules.py`
        # already decided this purchase on its own facts above.
        related_drift: AuthorizationDrift | None = None
        related_id = facts.related_authorization_id
        if related_id is not None:
            related_stored = state.get_stored_decision(related_id)
            if related_stored is not None:
                related_drift = compute_drift(
                    reference_authorization_id=related_id,
                    prior_merchant_id=related_stored.merchant_id,
                    prior_basket_key=related_stored.basket_key,
                    prior_amount_chf=related_stored.billing_amount_chf,
                    current_merchant_id=merchant_id,
                    current_basket_key=basket_key,
                    current_amount_chf=billing_amount_chf,
                )

        # R&D Track E: the same evaluations, scoped to what the customer's own policy
        # says vs. what the wallet's own safety checks say -- see `_scoped_verdict`.
        policy_verdict = _scoped_verdict(evaluations, "customer", mandate.uncertainty_policy)
        security_verdict = _scoped_verdict(evaluations, "safety", mandate.uncertainty_policy)

        # R&D Track A: ALLOW issues a narrow, expiring, inspectable payment authority --
        # never constructed anywhere else in this codebase.
        payment_authority: PaymentAuthority | None = None
        if decision == "allow":
            payment_authority = state.issue_authority(
                authorization_id, mandate_id=mandate.mandate_id, policy_version=mandate_policy_version(mandate)
            )

        evidence = tuple(f"{e.rule.field} [{e.outcome}]: {e.detail}" for e in evaluations)
        retry_at = _window_retry(evaluations, state, facts) if decision == "block" else None
        plain_reasons = tuple(dict.fromkeys(
            _plain_reason(e) for e in evaluations if e.outcome in ("fail", "unknown")))
        return EngineDecision(
            authorization_id=authorization_id,
            decision=decision,
            reason_codes=reason_codes,
            customer_message=_customer_message(decision, evaluations, facts, retry_at),
            earliest_retry_at=retry_at,
            plain_reasons=plain_reasons,
            evidence=evidence,
            rule_evaluations=tuple(evaluations),
            intervention=classify_intervention(decision, tuple(evaluations)),
            facts=facts,
            idempotent_replay=False,
            policy_verdict=policy_verdict,
            security_verdict=security_verdict,
            drift=related_drift,
            payment_authority=payment_authority,
        )


def _period_rules_breached_now(
    mandate: MandateSnapshot | None, state: RunState, authorization_id: str
) -> str | None:
    """Would approving this pending purchase now break a rolling-period ceiling?

    Re-derived from live state at the moment of resolution rather than trusted from
    the evaluation that raised the step-up. Returns the breached rule's description,
    or None.
    """
    if mandate is None:
        return None
    pending = state.get_stored_decision(authorization_id)
    if pending is None:
        return None
    for rule in mandate.hard_rules:
        if rule.field != "authorization.billing_amount_chf" or rule.scope != "period" or not rule.period_days:
            continue
        # Same correction as the evaluation path, and this is where it matters most:
        # a resolution is BY DEFINITION out of order. The purchase was paused at its
        # simulated time and the customer answers later, behind decisions already
        # taken. A backward-looking window from the paused purchase cannot see them,
        # which is how the first version of this check passed CHF 480 against a
        # CHF 300 cap.
        peak = state.peak_window_spend_chf(
            pending.timestamp, pending.billing_amount_chf, rule.period_days
        )
        if peak > to_decimal(rule.value):
            return (
                f"approving it would put CHF {peak} into a {rule.period_days}-day window "
                f"against a CHF {rule.value} ceiling"
            )
    return None


def resolve_authorization(
    authorization_id: str, human_decision: Decision, state: RunState, *, resolved_at: datetime, mandate: MandateSnapshot | None = None
) -> EngineDecision:
    """Apply a real customer's answer to a `review`ed authorization.

    Scoped to exactly this authorization_id -- see `state.RunState.record_resolution`
    -- and never touches the mandate. "A yes is this authorization. It is not a new
    wallet." Deliberately takes no amount: the amount that matters is whatever the
    customer was actually shown when the purchase was flagged for review, sourced
    from `state`'s own record, never from a value the caller could supply.

    `mandate` is optional (backward-compatible: existing callers that don't pass it
    keep working exactly as before) -- when given, an approve resolution issues a
    `PaymentAuthority` the same way an automatic ALLOW does (R&D Track A), so a
    step-up-then-approved purchase is just as payable, under the same bounded
    authority model, as an automatically-approved one.
    """
    # Same span as evaluate_authorization: a late human answer is re-checked
    # against the window and then recorded, and nothing may land between.
    with state.decision_guard():
        if human_decision == "review":
            raise ValueError("a human resolution must be 'allow' or 'block', not 'review'")

        # Two things can have changed between the wallet asking and the customer
        # answering, and BOTH used to be ignored. An independent security audit named the
        # shape exactly: this function was the one unguarded escape hatch, checking a
        # single flag set minutes or hours earlier and re-deriving nothing from
        # authoritative state.
        #
        # A customer's "yes" is an answer to a question, not an override of their own
        # later instructions, so where the two conflict the safe one wins and we record
        # WHY rather than silently downgrading.
        override_reason: str | None = None

        # Only a purchase still WAITING for an answer may be overridden. Once it has been
        # resolved, `record_resolution` owns the outcome: an identical re-submission is an
        # idempotent success and a conflicting one is refused.
        #
        # Skipping this guard was a real defect. The period re-check below adds the
        # purchase's own amount to `_approved_spend` -- which, after a first resolution,
        # already contains it. A CHF 200 purchase under a CHF 300 cap therefore scored
        # 200 + 200 = 400, the re-check decided to record a block, and `record_resolution`
        # raised a conflict against the 'allow' it had just recorded. A double-clicked
        # button crashed. Found by the temporal-consistency audit; the existing idempotence
        # test missed it because its mandate had no period rule.
        pending = state.get_stored_decision(authorization_id)
        already_resolved = pending is not None and pending.decision != "review"

        if human_decision == "allow" and not already_resolved:
            # (1) The customer revoked the mandate while this purchase was waiting. The
            # revocation is the later and stronger instruction.
            if state.is_revoked:
                override_reason = "mandate_revoked_before_resolution"
            else:
                # (2) A rolling-period ceiling that was satisfied when we asked may not be
                # satisfied now -- and a compromised agent chooses what gets asked, so it
                # could force purchases into the queue and have them approved one at a
                # time, each individually reasonable, together far over the customer's own
                # weekly cap. Measured at CHF 2,400 against a CHF 500 / 7-day cap before
                # this check existed.
                breached = _period_rules_breached_now(mandate, state, authorization_id)
                if breached is not None:
                    override_reason = f"period_limit_exceeded:{breached}"

        if override_reason is not None:
            stored = state.record_resolution(authorization_id, "block", resolved_at)
            return EngineDecision(
                authorization_id=authorization_id,
                decision=stored.decision,
                reason_codes=("customer_resolution", override_reason),
                customer_message=(
                    "Your approval arrived after you revoked this mandate, so the purchase was declined."
                    if override_reason.startswith("mandate_revoked")
                    else "Approving this purchase would now exceed the spending limit you set, so it was declined."
                ),
                evidence=(f"resolved by the customer at {resolved_at.isoformat()}", override_reason),
                rule_evaluations=(),
                intervention=_TERMINAL_INTERVENTION[stored.decision],
                facts=None,
                idempotent_replay=False,
                payment_authority=None,
            )

        stored = state.record_resolution(authorization_id, human_decision, resolved_at)
        payment_authority: PaymentAuthority | None = None
        if stored.decision == "allow" and mandate is not None:
            payment_authority = state.issue_authority(
                authorization_id, mandate_id=mandate.mandate_id, policy_version=mandate_policy_version(mandate), now=resolved_at
            )
        return EngineDecision(
            authorization_id=authorization_id,
            decision=stored.decision,
            reason_codes=("customer_resolution",),
            customer_message="The customer's answer has been recorded for this purchase only.",
            evidence=(f"resolved by the customer at {resolved_at.isoformat()}",),
            rule_evaluations=(),
            intervention=_TERMINAL_INTERVENTION[stored.decision],
            facts=None,
            idempotent_replay=False,
            payment_authority=payment_authority,
        )

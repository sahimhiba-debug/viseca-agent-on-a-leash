"""Competing models of the FUNDAMENTAL SECURITY OBJECT of agentic payment delegation.

This module exists to be falsified. It implements seven candidate answers to the
question "what is the thing that, if protected, makes this delegation safe?", as
pure functions over the same authoritative inputs, so they can be attacked
independently and measured against each other on the official corpus.

It is research apparatus. It is imported by no production path -- not by
`decision_engine`, `rules` or `facts` -- and it changes no decision.

The candidates
--------------
M1 TRANSACTION     the individual authorization. "Is this purchase permitted?"
                   What a conventional wallet protects, and what every competent
                   team will build.
M2 LEDGER          the persisted record of decisions. "Is the record intact?"
                   THIS PROJECT'S CURRENT CLAIM.
M3 MANDATE         the customer's rule set. "Has authority been widened?"
M4C CAPABILITY_CHF a consumable authority denominated in francs.
M5 JOB             the objective the customer described. "Is it already done?"
                   Also the capability denominated in PERFORMANCES: a separate
                   M4N was built for that and deleted, because a 4,000-run
                   randomized differential found zero inputs on which the two
                   disagree. "Job" and "capability whose unit is a performance"
                   are not two objects. The unit IS the job.
M6 CONSENT         the set of purchases the customer personally agreed to.
M7 IRREVERSIBILITY the portion of the commitment the customer cannot undo.
M8 ACCOUNT         the account's own per-transaction and monthly limits.

Each answers one common question -- "if this purchase proceeds, is the delegation
still intact?" -- so that disagreement between them is meaningful rather than a
difference of subject.

Verdicts are `within`, `outside` or `unknown`. No model here ever blocks anything;
`outside` means "this has left what the customer delegated", whose only sound
response is to ask them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from wallet_control.csv_data import account_limits_for_card
from wallet_control.mandate import MandateSnapshot, MandateStatus
from wallet_control.state import RunState, StoredDecision

Standing = Literal["within", "outside", "unknown"]

# A basket line is (item_id, item_name, quantity, return_window_days, final_sale,
# stated_size). The two reversibility facts are positions 3 and 4, derived from the
# merchant's text at decision time and persisted with the decision.
_RETURN_WINDOW, _FINAL_SALE = 3, 4


@dataclass(frozen=True)
class ModelVerdict:
    model: str
    standing: Standing
    detail: str

    @property
    def would_ask(self) -> bool:
        return self.standing == "outside"


# --- M1  the transaction ----------------------------------------------------------


def m1_transaction(mandate: MandateSnapshot, state: RunState, assessing: str) -> ModelVerdict:
    """The object is this one authorization, and the question is whether it passes
    the customer's rules. The engine has already answered; this model adds nothing
    to it, which is precisely the point of including it as a baseline."""
    stored = state.get_stored_decision(assessing)
    if stored is None:
        return ModelVerdict("M1_TRANSACTION", "unknown", "no decision on record")
    if stored.decision == "allow":
        return ModelVerdict("M1_TRANSACTION", "within", "every hard rule passed")
    if stored.decision == "review":
        return ModelVerdict("M1_TRANSACTION", "unknown", "a fact could not be established")
    return ModelVerdict("M1_TRANSACTION", "outside", "a hard rule failed")


# --- M2  the decision ledger  (this project's current claim) ----------------------


def m2_ledger(mandate: MandateSnapshot, state: RunState, assessing: str) -> ModelVerdict:
    """The object is the run's persisted decision ledger: write-once per
    authorization_id, carrying the money, the merchant and the basket fingerprint,
    with the execution lifecycle riding on it.

    What it protects is REAL and was established by attack: replay, re-pointing an
    approval, double execution, revocation evasion and post-restart resurrection all
    become impossible when this object is intact. The question this pass asks is not
    whether it is a security object -- it is -- but whether it is the security object
    of DELEGATION."""
    stored = state.get_stored_decision(assessing)
    if stored is None:
        return ModelVerdict("M2_LEDGER", "unknown", "no decision on record")
    if stored.decision != "allow":
        return ModelVerdict("M2_LEDGER", "outside", f"the record says {stored.decision}")
    if stored.revoked:
        return ModelVerdict("M2_LEDGER", "outside", "the authority on this record was revoked")
    if stored.consumed_at is not None:
        return ModelVerdict("M2_LEDGER", "outside", "this authorization was already executed")
    return ModelVerdict("M2_LEDGER", "within", "the record is intact, unrevoked and unconsumed")


# --- M3  the mandate --------------------------------------------------------------


def m3_mandate(mandate: MandateSnapshot, state: RunState, assessing: str) -> ModelVerdict:
    """The object is the customer's rule set, and the property is that authority can
    only ever narrow. Enforced in `mandate.py` by construction: `HardRule` is frozen
    and `tighten_hard_rules` only appends."""
    if mandate.status is not MandateStatus.ACTIVE:
        return ModelVerdict("M3_MANDATE", "outside", f"the mandate is {mandate.status.value}")
    if not mandate.hard_rules:
        return ModelVerdict("M3_MANDATE", "unknown", "this mandate states no rules at all")
    return ModelVerdict("M3_MANDATE", "within", f"{len(mandate.hard_rules)} rules, never widened")


# --- M4  a consumable capability --------------------------------------------------


def _stated_total_chf(mandate: MandateSnapshot) -> Decimal | None:
    """The franc quantity the customer delegated in total.

    Returns None for every mandate expressible in the official vocabulary, because
    `scope` is "purchase" or "period" and technical_details.md closes the set. This
    function returning None is not a gap in the implementation; it is the measurement.
    """
    for rule in mandate.hard_rules:
        if rule.scope == "total":  # no such scope exists; kept to make the absence explicit
            return Decimal(str(rule.value))
    return None


def m4c_capability_chf(mandate: MandateSnapshot, state: RunState, assessing: str) -> ModelVerdict:
    """The object is an authority denominated in francs, spent down by purchases.

    This is the model a reader reaches for first, and the one the previous pass was
    told not to build as a mechanism. It is implemented here honestly so its failure
    is measured rather than asserted."""
    total = _stated_total_chf(mandate)
    if total is None:
        return ModelVerdict(
            "M4C_CAPABILITY_CHF", "unknown",
            "the customer stated no total; there is nothing to spend down",
        )
    spent = sum((d.billing_amount_chf for d in state.approved_decisions()
                 if d.authorization_id != assessing), Decimal(0))
    stored = state.get_stored_decision(assessing)
    now = stored.billing_amount_chf if stored else Decimal(0)
    if spent + now > total:
        return ModelVerdict("M4C_CAPABILITY_CHF", "outside", f"CHF {spent + now} exceeds CHF {total}")
    return ModelVerdict("M4C_CAPABILITY_CHF", "within", f"CHF {spent + now} of CHF {total}")


# --- M5  the job ------------------------------------------------------------------


def m5_job(mandate: MandateSnapshot, state: RunState, assessing: str) -> ModelVerdict:
    """The object is the objective the customer described. Delegated to the module
    that already derives it from the ledger."""
    from .fulfillment import fulfilment_state

    verdict = fulfilment_state(mandate, state, assessing=assessing)
    standing: Standing = (
        "outside" if verdict.would_ask_customer
        else "unknown" if verdict.verdict == "not_applicable"
        else "within"
    )
    return ModelVerdict("M5_JOB", standing, verdict.detail)


# --- M6  the consent surface ------------------------------------------------------


def m6_consent(mandate: MandateSnapshot, state: RunState, assessing: str) -> ModelVerdict:
    """The object is the set of purchases the customer personally agreed to.

    The strictest possible reading of delegation: nothing counts as authorized
    unless a human said so about THIS purchase. Included to establish the degenerate
    bound -- it is trivially safe and trivially useless, and measuring how useless
    is the point."""
    stored = state.get_stored_decision(assessing)
    if stored is None:
        return ModelVerdict("M6_CONSENT", "unknown", "no decision on record")
    if stored.was_reviewed and stored.decision == "allow":
        return ModelVerdict("M6_CONSENT", "within", "the customer approved this purchase personally")
    return ModelVerdict("M6_CONSENT", "outside", "the customer was never asked about this purchase")


# --- M7  the irreversible commitment ----------------------------------------------


def _is_irreversible(decision: StoredDecision) -> bool | None:
    """Was this purchase unrecoverable? Read from the PERSISTED basket fingerprint,
    which carries the return window and the final-sale flag as facts derived at
    decision time -- never from merchant text re-read later.

    None means the merchant did not say, which is not the same as reversible and
    must not be silently treated as it."""
    if not decision.basket_key:
        return None
    if any(bool(line[_FINAL_SALE]) for line in decision.basket_key):
        return True
    windows = [line[_RETURN_WINDOW] for line in decision.basket_key]
    if any(w is None for w in windows):
        return None
    return all(int(w) <= 0 for w in windows)


def m7_irreversibility(mandate: MandateSnapshot, state: RunState, assessing: str) -> ModelVerdict:
    """The object is the portion of the commitment the customer CANNOT UNDO.

    The reasoning: 8,616 returnable purchases are an afternoon of administration;
    8,616 final-sale purchases are a loss. Every other model here treats those two
    sequences as identical, because francs, performances and ledger entries do not
    distinguish them. The customer does.

    So the delegated quantity is not money and not purchases -- it is UNRECOVERABLE
    COMMITMENT, and the claim under test is that a customer delegating a job
    delegates at most one job's worth of it.
    """
    stored = state.get_stored_decision(assessing)
    if stored is None:
        return ModelVerdict("M7_IRREVERSIBILITY", "unknown", "no decision on record")

    here = _is_irreversible(stored)
    prior = [d for d in state.approved_decisions() if d.authorization_id != assessing]
    committed = [d for d in prior if _is_irreversible(d) is True]
    unclear = [d for d in prior if _is_irreversible(d) is None]

    if here is False:
        return ModelVerdict("M7_IRREVERSIBILITY", "within",
                            "this purchase can be returned, so it commits the customer to nothing")
    if here is None:
        return ModelVerdict("M7_IRREVERSIBILITY", "unknown",
                            "the merchant did not state a return window, so recoverability is unknown")
    if committed:
        return ModelVerdict(
            "M7_IRREVERSIBILITY", "outside",
            f"an unrecoverable commitment was already made ({committed[0].authorization_id}); "
            f"this adds a second the customer cannot undo",
        )
    if unclear:
        return ModelVerdict(
            "M7_IRREVERSIBILITY", "unknown",
            f"{len(unclear)} earlier purchase(s) did not state recoverability",
        )
    return ModelVerdict("M7_IRREVERSIBILITY", "within", "the first unrecoverable commitment")


# --- M8  the account envelope -----------------------------------------------------


def m8_account(mandate: MandateSnapshot, state: RunState, assessing: str) -> ModelVerdict:
    """The object is the account's own limits: `per_transaction_limit_chf` and
    `monthly_limit_chf`, carried in `accounts.csv`.

    This candidate was found late, by reading the official data rather than the
    official prose. It matters for two reasons.

    First, it falsifies a claim this project committed one pass earlier -- that
    "neither this wallet nor the official schema models a credit limit". The WALLET
    does not. The SCHEMA does, on the account, and every scenario card resolves to
    one: CHF 3,200-5,000 a month. The unbounded franc figures that pass reported are
    what the wallet would approve, not what could actually be drawn.

    Second, it is the only candidate here that bounds a STANDING mandate. It does so
    without consulting the customer's words at all -- which is exactly why it is not
    an object of DELEGATION. It bounds the loss; it says nothing about intent. A
    customer who delegated one CHF 400 monitor is "protected" by it at CHF 3,200 a
    month, a number they never chose and were never shown.
    """
    limits = account_limits_for_card(mandate.card_id or "")
    if limits is None:
        return ModelVerdict("M8_ACCOUNT", "unknown", "no account on record for this card")
    monthly = Decimal(limits["monthly_limit_chf"])
    per_txn = Decimal(limits["per_transaction_limit_chf"])
    stored = state.get_stored_decision(assessing)
    now = stored.billing_amount_chf if stored else Decimal(0)
    if now > per_txn:
        return ModelVerdict("M8_ACCOUNT", "outside", f"CHF {now} exceeds the account's CHF {per_txn} per transaction")
    # The account's month, not the mandate's rolling window: a calendar-month bound
    # the customer did not choose and cannot tighten through the mandate.
    spent = sum((d.billing_amount_chf for d in state.approved_decisions()
                 if d.authorization_id != assessing
                 and stored is not None and d.timestamp.month == stored.timestamp.month
                 and d.timestamp.year == stored.timestamp.year), Decimal(0))
    if spent + now > monthly:
        return ModelVerdict("M8_ACCOUNT", "outside",
                            f"CHF {spent + now} this month exceeds the account's CHF {monthly}")
    return ModelVerdict("M8_ACCOUNT", "within", f"CHF {spent + now} of the account's CHF {monthly} this month")


MODELS = {
    "M1_TRANSACTION": m1_transaction,
    "M2_LEDGER": m2_ledger,
    "M3_MANDATE": m3_mandate,
    "M4C_CAPABILITY_CHF": m4c_capability_chf,
    "M5_JOB": m5_job,
    "M6_CONSENT": m6_consent,
    "M7_IRREVERSIBILITY": m7_irreversibility,
    "M8_ACCOUNT": m8_account,
}


def assess_all(mandate: MandateSnapshot, state: RunState, assessing: str) -> dict[str, ModelVerdict]:
    return {name: fn(mandate, state, assessing) for name, fn in MODELS.items()}

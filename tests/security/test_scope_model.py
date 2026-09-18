"""The scope model, and the one place it is not satisfied.

Thesis: a delegation is bounded only where an authoritative record exists at the
SAME SCOPE as the bound. These tests pin what the falsification pass established:
which scopes are real, which bounds we actually enforce, and the single invariant
we claim at mandate scope but only deliver at run scope.

Criteria were pre-registered in docs/FINAL_FALSIFICATION_PREREGISTRATION.md.
Reproduce with `python scripts/run_scope_falsification.py`.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.csv_data import DATA_DIR, load_accounts, load_cards
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.fulfillment import fulfilment_state
from wallet_control.mandate import HardRule
from wallet_control.offline_replay import (
    ALL_SCENARIO_IDS, build_event, compile_and_confirm_mandate_for_scenario,
    history_csv_path, scenario_rows,
)
from wallet_control.csv_data import load_merchants, load_purchase_attempt_items
from wallet_control.state import HistoryIndex, RunState

M, CARD = "ME_TEST_0001", "CA_TEST"
T0 = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


def _run():
    return RunState(history=HistoryIndex({CARD: frozenset({M})}, available=True), card_id=CARD)


def _one_shot_mandate():
    return make_mandate(instruction="Buy the 27-inch monitor I chose.", hard_rules=[
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=500,
                 currency="CHF", scope="purchase"),
        HardRule(field="item.name_contains", operator="=", value="27-inch")])


def _buy(md, s, aid, *, amt=399.0, hours=0):
    ev = make_event(mandate=md, authorization_id=aid, amount=amt, merchant_id=M,
                    timestamp=T0 + timedelta(hours=hours))
    ev["authorization"]["items"][0].update(item_name="27-inch monitor", item_category="electronics")
    return evaluate_authorization(ev, md, s)


# --- which scopes are real -------------------------------------------------------


def test_the_customer_scope_carries_no_bound_and_is_therefore_not_a_security_scope():
    """A scope needs a BOUND, not just an identity. `customers.csv` is persona text:
    home region, budget style, travel pattern. Nothing enforceable."""
    customers = list(csv.DictReader((DATA_DIR / "customers.csv").open()))
    assert customers
    assert not [k for k in customers[0] if "limit" in k.lower()]


def test_the_account_scope_carries_a_real_bound_that_fans_out_across_cards():
    """The account bound is real -- and it is scoped ABOVE the card, which is why no
    run-scoped or card-scoped record can enforce it."""
    accounts, cards = load_accounts(), load_cards()
    assert all(Decimal(a["monthly_limit_chf"]) > 0 for a in accounts.values())
    per_account: dict[str, int] = {}
    for card in cards.values():
        per_account[card["account_id"]] = per_account.get(card["account_id"], 0) + 1
    assert max(per_account.values()) > 1, "if no account fanned out, this scope would be untestable"


def test_the_official_pack_supplies_no_account_scoped_spend_counter():
    """`spend_in_period_before_chf` is the only field that could have carried prior
    spend into an event, and the pack states it is empty on every row. Without it,
    and with no account endpoint in the API surface, the account bound is not
    enforceable by this wallet. That is a documented limit, not a design choice."""
    rows = list(csv.DictReader((DATA_DIR / "purchase_attempts.csv").open()))
    assert rows
    assert all(r["spend_in_period_before_chf"] == "" for r in rows)


# --- the bounds we DO enforce, at the scope the platform defines ------------------


def test_our_period_counter_matches_the_platform_s_run_scoped_definition():
    """The pack defines the live counter as `context.approved_spend_in_period_chf`,
    "recomputed from the decisions actually taken in the run". Ours is derived from
    `RunState`. Both are run-scoped, and a stepped-up authorization must stay OUT of
    approved spend until it is resolved."""
    history = HistoryIndex.from_csv(history_csv_path())
    md = compile_and_confirm_mandate_for_scenario("SCEN0002").snapshot()
    merchants, items = load_merchants(), load_purchase_attempt_items()
    state = RunState(history=history, card_id=md.card_id)

    stepped_up = None
    for row in scenario_rows("SCEN0002"):
        ctx = {"approved_spend_in_period_chf": float(state.total_approved_spend_chf()),
               "recent_authorizations": state.recent_authorizations_context()}
        before = state.total_approved_spend_chf()
        d = evaluate_authorization(
            build_event(row, items[row["authorization_id"]], merchants[row["merchant_id"]], md, ctx),
            md, state)
        if d.decision == "review":
            assert state.total_approved_spend_chf() == before, "a paused purchase entered spend"
            stepped_up = d.authorization_id
            break

    assert stepped_up is not None
    before = state.total_approved_spend_chf()
    resolve_authorization(stepped_up, "allow", state,
                          resolved_at=datetime.now(timezone.utc), mandate=md)
    assert state.total_approved_spend_chf() > before, "resolution did not enter spend"


def test_a_misstated_fx_conversion_cannot_understate_the_chf_amount():
    """The pack publishes the formula -- `billing_amount_chf = amount x
    fx_rates[currency]` -- which makes the field checkable rather than trusted. An
    always-on safety check recomputes it, so a compromised agent cannot declare a
    CHF 9,499 purchase as CHF 100 to slip under the customer's cap."""
    md = make_mandate(instruction="Buy one monitor.", hard_rules=[
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=400,
                 currency="CHF", scope="purchase")])
    s = _run()
    ev = make_event(mandate=md, authorization_id="AU1", amount=9999.00, currency="EUR",
                    billing_amount_chf=100.00, merchant_id=M)
    d = evaluate_authorization(ev, md, s)
    assert d.decision == "block"
    assert any("amount_integrity" in c for c in d.reason_codes), d.reason_codes


def test_an_honest_foreign_currency_purchase_still_passes():
    """The other half: the check must not turn every non-CHF purchase into a block.
    Four official attempts are non-CHF and all four are exactly consistent."""
    md = make_mandate(instruction="Buy one monitor.", hard_rules=[
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=400,
                 currency="CHF", scope="purchase")])
    s = _run()
    ev = make_event(mandate=md, authorization_id="AU1", amount=450.00, currency="USD",
                    billing_amount_chf=391.50, merchant_id=M)   # 450 x 0.87
    assert evaluate_authorization(ev, md, s).decision == "allow"


# --- the invariant we do NOT deliver at the scope we claim it ---------------------


def test_the_one_shot_job_holds_within_a_run():
    md, s = _one_shot_mandate(), _run()
    _buy(md, s, "AU1", hours=0)
    _buy(md, s, "AU2", hours=5)
    assert fulfilment_state(md, s, assessing="AU2").would_ask_customer


def test_the_one_shot_job_does_NOT_hold_ACROSS_runs():
    """THE FALSIFIER of this pass, pinned rather than fixed.

    The job capability is MANDATE-scoped: "buy THE monitor I chose" is one job
    whatever run it happens in. Our authoritative record is RUN-scoped -- one
    `RunState`, one checkpoint per `run_id`. The official API contemplates reusing a
    mandate across runs (`PATCH /v1/mandates/{id}` "Preserves or tightens an active
    mandate FOR LATER RUNS"), so this is reachable, not theoretical.

    An earlier audit recorded this as "not reachable: one mandate per run". That was
    our own demo convention -- `api.py` compiles a fresh mandate per run -- not a
    guarantee of the challenge, and `live_worker.register_run` will happily accept
    the same mandate for two `run_id`s.

    Fixing it needs the ledger keyed by mandate rather than partitioned by run.
    This pass did not build that: it is a re-scoping of the authoritative record
    days before a freeze, and the scope model predicts the failure rather than being
    surprised by it. The claim is narrowed instead -- see FINAL_ARCHITECTURE_DECISION.md,
    "What we refuse to claim"."""
    md = _one_shot_mandate()
    verdicts = []
    for _ in range(2):
        s = _run()                      # a new run is a new ledger
        _buy(md, s, "AU1", hours=0)
        verdicts.append(fulfilment_state(md, s, assessing="AU1").verdict)
    assert verdicts == ["first_fulfilment", "first_fulfilment"], verdicts


# --- T1 sharpened -----------------------------------------------------------------


def test_the_scope_of_a_bound_is_set_by_its_authoritative_definition_not_its_author():
    """The rolling-period cap is written by the customer in the MANDATE, and we
    enforce it from RUN state. That looks like a scope violation and is not: the
    pack defines the period counter as run-scoped. The lesson is that the scope of a
    bound is decided by where its authoritative definition places it, not by where
    the customer happened to write it down."""
    md = make_mandate(instruction="Order groceries.", hard_rules=[
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=300,
                 currency="CHF", scope="period", period_days=7)])
    s = _run()
    _buy(md, s, "AU1", amt=200.0, hours=0)
    assert _buy(md, s, "AU2", amt=200.0, hours=24).decision != "allow"     # inside the window
    assert _buy(md, s, "AU3", amt=200.0, hours=24 * 8).decision == "allow"  # window re-opened

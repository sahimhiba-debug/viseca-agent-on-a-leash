"""The falsification pass: which candidate is the fundamental security object?

This project claimed ONE -- the run's persisted decision ledger. These tests pin
what the measurement actually found, including the two places the claim was too
strong and the one place a previous pass stated something false about the official
data.

The criteria were fixed before any model was built:

  F1 SUFFICIENCY    protect it perfectly -- is the unintended outcome bounded?
  F2 COMPUTABILITY  can it be computed from authoritative recorded facts at all?
  F3 NON-DEGENERACY does protecting it require escalating (almost) everything?
  F4 NECESSITY      is there an attack that ONLY this object catches?

`security_object.py` is research apparatus: it is imported by no production path
and changes no decision. `scripts/run_security_object_falsification.py` reproduces
every number quoted here.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.csv_data import account_limits_for_card, load_accounts
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.offline_replay import ALL_SCENARIO_IDS, compile_and_confirm_mandate_for_scenario
from wallet_control.payment import MockPSP, PaymentError
from research.security_object import MODELS, m2_ledger, m4c_capability_chf, m5_job, m8_account
from wallet_control.state import HistoryIndex, RunState

M, CARD = "ME_TEST_0001", "CA_TEST"
T0 = datetime(2026, 8, 12, 9, 0, 0, tzinfo=timezone.utc)


def _state(card=CARD):
    return RunState(history=HistoryIndex({card: frozenset({M})}, available=True), card_id=card)


def _mandate(instr="Buy the 27-inch monitor I chose.", anchor="27-inch", cap=500, card=CARD):
    rules = [HardRule(field="authorization.billing_amount_chf", operator="<=", value=cap,
                      currency="CHF", scope="purchase")]
    if anchor:
        rules.append(HardRule(field="item.name_contains", operator="=", value=anchor))
    return make_mandate(instruction=instr, hard_rules=rules, card_id=card)


def _buy(md, s, aid, *, name="27-inch monitor", qty=1, amt=300.0, hours=0):
    ev = make_event(mandate=md, authorization_id=aid, amount=amt, merchant_id=M,
                    card_id=md.card_id, timestamp=T0 + timedelta(hours=hours))
    ev["authorization"]["items"][0].update(item_name=name, quantity=qty, item_category="electronics")
    return evaluate_authorization(ev, md, s)


# --- F2: a model that cannot be computed cannot be protected ----------------------


@pytest.mark.parametrize("scenario_id", ALL_SCENARIO_IDS)
def test_a_franc_denominated_capability_is_uncomputable_on_every_official_mandate(scenario_id):
    """M4C asks "how much of the delegated total is left?" and no official mandate
    states a total, because `scope` is "purchase" or "period" and
    technical_details.md closes the set. 45 of 45 events return `unknown`.

    This is the cleanest falsification in the set: the model everyone reaches for
    first cannot be evaluated even once."""
    md = compile_and_confirm_mandate_for_scenario(scenario_id).snapshot()
    state = _state(md.card_id)
    assert m4c_capability_chf(md, state, "AU1").standing == "unknown"


# --- F3: a model that escalates everything has not secured anything ---------------


def test_requiring_personal_consent_for_every_purchase_is_degenerate():
    """M6 is trivially safe and trivially useless: it bounds the outcome at CHF 0 by
    questioning all 19 approved purchases in the official corpus. It is included in
    the model set precisely to fix that end of the scale."""
    from research.security_object import m6_consent

    md, s = _mandate(), _state()
    _buy(md, s, "AU1")
    assert m6_consent(md, s, "AU1").standing == "outside"


# --- F4: what each surviving object uniquely catches ------------------------------


def test_the_ledger_is_the_object_of_EXECUTION_and_is_silent_about_volume():
    """The claim under test, split in two by measurement.

    It HOLDS on execution: a second charge against one authorization is refused.
    It is SILENT on volume: a second purchase repeating a one-shot job is, to the
    ledger, simply a second intact record. Both halves matter -- the first is why
    the ledger is a real security object, the second is why it is not the security
    object of DELEGATION."""
    md, s = _mandate(), _state()
    _buy(md, s, "AU1", hours=0)
    psp = MockPSP(s)
    psp.charge(charge_id="C1", authorization_id="AU1", amount_chf=Decimal("300"), merchant_id=M)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="C2", authorization_id="AU1", amount_chf=Decimal("300"), merchant_id=M)

    _buy(md, s, "AU2", hours=5)
    assert m2_ledger(md, s, "AU2").standing == "within"     # the ledger sees nothing wrong
    assert m5_job(md, s, "AU2").standing == "outside"       # the delegation is spent


def test_the_job_capability_catches_volume_and_is_silent_about_execution():
    """The mirror image, and the reason both objects are kept: M5 has no opinion on
    whether money moves once. Neither object subsumes the other."""
    md, s = _mandate(), _state()
    _buy(md, s, "AU1", hours=0)
    s.revoke_outstanding_authorities()
    # revoked authority -- an execution fact. The job model does not look there.
    assert m5_job(md, s, "AU1").standing in ("within", "unknown")
    assert m2_ledger(md, s, "AU1").standing == "outside"


# --- the false claim a previous pass committed ------------------------------------


def test_the_official_schema_DOES_carry_a_total_spending_bound():
    """A previous pass of this project stated, in a committed document, that
    "neither this wallet nor the official schema models a credit limit". The wallet
    does not. THE SCHEMA DOES: `accounts.csv` carries `per_transaction_limit_chf`
    and `monthly_limit_chf` for all 31 accounts, and every scenario card resolves to
    one. The unbounded franc figures that pass reported are what the WALLET would
    approve, not what could be drawn."""
    accounts = load_accounts()
    assert len(accounts) == 31
    assert all("monthly_limit_chf" in a and "per_transaction_limit_chf" in a for a in accounts.values())

    for scenario_id in ALL_SCENARIO_IDS:
        md = compile_and_confirm_mandate_for_scenario(scenario_id).snapshot()
        limits = account_limits_for_card(md.card_id)
        assert limits is not None, scenario_id
        assert Decimal(limits["monthly_limit_chf"]) > 0


def test_the_account_per_transaction_limit_never_binds_on_an_official_mandate():
    """Half of the account envelope is dead weight: the customer's own per-purchase
    cap (CHF 20-400) is always below the account's (CHF 900-1,400), so only the
    MONTHLY limit ever does any work."""
    for scenario_id in ALL_SCENARIO_IDS:
        md = compile_and_confirm_mandate_for_scenario(scenario_id).snapshot()
        limits = account_limits_for_card(md.card_id)
        cap = next(r.value for r in md.hard_rules
                   if r.field == "authorization.billing_amount_chf" and r.scope == "purchase")
        assert Decimal(str(cap)) < Decimal(limits["per_transaction_limit_chf"]), scenario_id


def test_a_calendar_month_reading_of_the_account_limit_is_defeated_by_the_boundary():
    """Attack on the surviving model, pinned rather than fixed.

    A calendar month is not a rolling window: spend the limit on the 31st and again
    on the 1st and twice the monthly limit leaves in two days. The BOUND is real and
    authoritative; this READING of it is not, and a correct one needs account-scoped
    rolling state that `RunState` (per run, per card) cannot express."""
    md = _mandate(instr="Buy groceries.", anchor=None, card="CA0001")
    s = _state("CA0001")
    monthly = Decimal(account_limits_for_card("CA0001")["monthly_limit_chf"])

    drawn = Decimal(0)
    for label, day in (("jan", datetime(2026, 1, 31, tzinfo=timezone.utc)),
                       ("feb", datetime(2026, 2, 1, tzinfo=timezone.utc))):
        for i in range(20):
            aid = f"AU{label}{i}"
            ev = make_event(mandate=md, authorization_id=aid, amount=400.0, merchant_id=M,
                            card_id="CA0001", timestamp=day + timedelta(hours=2 * i))
            ev["authorization"]["items"][0].update(item_name=f"item {aid}")
            if evaluate_authorization(ev, md, s).decision != "allow":
                continue
            if m8_account(md, s, aid).standing == "outside":
                break
            drawn += Decimal("400")

    assert drawn > monthly, f"drew {drawn} against a monthly limit of {monthly}"


# --- the deletion this pass made --------------------------------------------------


def test_the_model_set_holds_no_duplicate_of_the_job_capability():
    """A separate "capability denominated in performances" (M4N) was built and then
    deleted: a 4,000-run randomized differential found zero inputs on which it and
    M5 disagree. "Job" and "capability whose unit is a performance" are one object,
    and the unit is the job."""
    assert "M4N_CAPABILITY_N" not in MODELS
    assert "M5_JOB" in MODELS


def test_the_research_module_is_absent_from_the_decision_path():
    """The whole comparison is apparatus. If it ever reached the engine it would
    change decisions, and the official replay would move off 19/2/24."""
    import inspect

    from wallet_control import decision_engine, facts, rules

    for module in (decision_engine, rules, facts):
        assert "security_object" not in inspect.getsource(module)

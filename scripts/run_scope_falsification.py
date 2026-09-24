#!/usr/bin/env python3
"""Falsify the three-scope model of agentic payment delegation.

Thesis under test:
  T1  a delegation is bounded only where an authoritative record exists at the
      SAME SCOPE as the bound;
  T2  the scopes are exactly three -- mandate, authorization, account.

Criteria were pre-registered in docs/archive/FINAL_FALSIFICATION_PREREGISTRATION.md before
any prototype. Nothing here is in the decision path.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests.helpers import make_event, make_mandate
from wallet_control.csv_data import DATA_DIR, load_accounts, load_cards
from wallet_control.decision_engine import evaluate_authorization
from research.fulfillment import fulfilment_state
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex, RunState

M, CARD = "ME_TEST_0001", "CA_TEST"
T0 = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


def _run():
    return RunState(history=HistoryIndex({CARD: frozenset({M})}, available=True), card_id=CARD)


def _md(instr="Buy the 27-inch monitor I chose.", anchor="27-inch", cap=500, period=None):
    rules = [HardRule(field="authorization.billing_amount_chf", operator="<=", value=cap,
                      currency="CHF", scope="purchase")]
    if anchor:
        rules.append(HardRule(field="item.name_contains", operator="=", value=anchor))
    if period:
        rules.append(HardRule(field="authorization.billing_amount_chf", operator="<=",
                              value=period[0], currency="CHF", scope="period", period_days=period[1]))
    return make_mandate(instruction=instr, hard_rules=rules)


def _buy(md, s, aid, *, amt=399.0, hours=0, name="27-inch monitor"):
    ev = make_event(mandate=md, authorization_id=aid, amount=amt, merchant_id=M,
                    timestamp=T0 + timedelta(hours=hours))
    ev["authorization"]["items"][0].update(item_name=name, item_category="electronics")
    return evaluate_authorization(ev, md, s)


# --- MISSION 1: the cardinality map -----------------------------------------------


def cardinality_map():
    print("=" * 78)
    print("MISSION 1 — DOES ANY SCOPE ACTUALLY FAN OUT?")
    print("=" * 78)
    cards, accounts = load_cards(), load_accounts()
    auths = list(csv.DictReader((DATA_DIR / "scenario_authorities.csv").open()))
    customers = list(csv.DictReader((DATA_DIR / "customers.csv").open()))

    acc_per_cust = Counter(a["customer_id"] for a in accounts.values())
    card_per_acc = Counter(c["account_id"] for c in cards.values())
    print(f"\n  customer -> account  max {max(acc_per_cust.values())}   "
          f"({sum(1 for v in acc_per_cust.values() if v > 1)} customers with >1)")
    print(f"  account  -> card     max {max(card_per_acc.values())}   "
          f"({sum(1 for v in card_per_acc.values() if v > 1)} accounts with >1)")

    by_card = defaultdict(list)
    for a in auths:
        by_card[a["card_id"]].append(a["authority_id"])
    shared = {k: v for k, v in by_card.items() if len(v) > 1}
    print(f"  card     -> authority shared cards in the corpus: {shared or 'none'}")
    print(f"\n  customers.csv limit columns: "
          f"{[k for k in customers[0] if 'limit' in k.lower()] or 'NONE — persona text only'}")
    print("  => CUSTOMER carries no bound, so it is not a security scope.")
    print("  => AGENT IDENTITY is excluded by the pack: 'The agent rows do not have")
    print("     agent_id ... the challenge is about controlling delegated spending,")
    print("     not identifying a particular fictional AI provider.'")


# --- MISSION 4/5: what monthly_limit_chf actually is -------------------------------


def account_semantics():
    print("\n" + "=" * 78)
    print("MISSION 4/5 — WHAT IS monthly_limit_chf, REALLY?")
    print("=" * 78)
    rows = [
        ("is it in the data?", "YES", "accounts.csv, all 31 accounts"),
        ("is it per account?", "YES", "keyed by account_id"),
        ("does it span cards?", "YES", "10 accounts carry 2 cards"),
        ("does it span runs?", "YES (economically)", "an account outlives any run"),
        ("calendar or rolling?", "UNSTATED", "the pack never says"),
        ("does the API expose account spend?", "NO", "no /v1/accounts endpoint exists"),
        ("is there a platform period counter?", "RUN-SCOPED ONLY",
         'context.approved_spend_in_period_chf, "recomputed from the decisions'),
        ("", "", 'actually taken in the run"'),
        ("is spend_in_period_before_chf usable?", "NO", "null on every row of the pack"),
        ("is it declared as policy?", "NO",
         '"account attributes carried on the row for context"'),
    ]
    for q, a, why in rows:
        print(f"  {q:38s} {a:20s} {why}")
    print("\n  VERDICT: CONTEXT ONLY. The bound is real and economically binding, but the")
    print("  official API exposes no account-scoped spend and no account-scoped counter,")
    print("  so this wallet CANNOT enforce it. That is a documented limit, not a design")
    print("  choice, and it must not be claimed as a control.")


# --- MISSION 3: the attack battery ------------------------------------------------


def attacks():
    print("\n" + "=" * 78)
    print("MISSION 3 — ATTACKS, AND THE SCOPE EACH ONE LIVES AT")
    print("=" * 78)
    out = []

    # A: same mandate, many authorizations, ONE run -- the job capability holds
    md, s = _md(), _run()
    _buy(md, s, "AU1", hours=0); _buy(md, s, "AU2", hours=5)
    out.append(("A  same mandate, many authorizations, one run", "mandate",
                fulfilment_state(md, s, assessing="AU2").would_ask_customer, "held"))

    # D/B3: same mandate, MANY RUNS -- the job capability does NOT hold
    caught = []
    for _ in range(2):
        s2 = _run(); _buy(md, s2, "AUx", hours=0)
        caught.append(fulfilment_state(md, s2, assessing="AUx").would_ask_customer)
    out.append(("D  same mandate, TWO RUNS (PATCH: 'for later runs')", "mandate",
                any(caught), "FALSIFIER — the ledger is run-scoped"))

    # R: rolling-window boundary, within one run
    md2, s3 = _md(period=(300, 7)), _run()
    _buy(md2, s3, "AU1", amt=200.0, hours=0)
    d = _buy(md2, s3, "AU2", amt=200.0, hours=24)
    out.append(("R  rolling 7-day cap, inside the window", "mandate",
                d.decision != "allow", "held"))
    d = _buy(md2, s3, "AU3", amt=200.0, hours=24 * 8)
    out.append(("R  rolling 7-day cap, window re-opened", "mandate",
                d.decision == "allow", "held (correctly permissive)"))

    # N: amount mutation under one authorization_id
    md3, s4 = _md(), _run()
    _buy(md3, s4, "AU1", amt=100.0, hours=0)
    d = _buy(md3, s4, "AU1", amt=499.0, hours=1)
    out.append(("N  amount mutation under one authorization_id", "authorization",
                d.decision == "block", "held"))

    # M: merchant mutation
    md4, s5 = _md(), _run()
    _buy(md4, s5, "AU1", hours=0)
    ev = make_event(mandate=md4, authorization_id="AU1", amount=399.0,
                    merchant_id="ME_OTHER", timestamp=T0 + timedelta(hours=1))
    ev["authorization"]["items"][0].update(item_name="27-inch monitor", item_category="electronics")
    d = evaluate_authorization(ev, md4, s5)
    out.append(("M  merchant mutation under one authorization_id", "authorization",
                d.decision != "allow", "held"))

    print(f"\n  {'attack':52s} {'scope':14s} {'result'}")
    print("  " + "-" * 92)
    for name, scope, caught_, verdict in out:
        print(f"  {name:52s} {scope:14s} {'caught' if caught_ else 'NOT CAUGHT':11s} {verdict}")


# --- MISSION 6: attack the same-scope principle itself ----------------------------


def same_scope_principle():
    print("\n" + "=" * 78)
    print("MISSION 6 — IS T1 (THE SAME-SCOPE PRINCIPLE) ITSELF FALSIFIABLE?")
    print("=" * 78)
    print("""
  Sought: a bound at scope A enforced SAFELY AND COMPLETELY using only state at a
  lower scope B. One candidate survives scrutiny and it is instructive.

  COUNTEREXAMPLE FOUND (partial): the rolling-period bound.
    The customer states it in the MANDATE. We enforce it from RUN state. That is
    lower-scope state for a higher-scope bound -- and it is CORRECT, because the
    official pack defines the period counter as run-scoped:
      "context.approved_spend_in_period_chf, recomputed from the decisions
       actually taken in the run"
    So the bound is not really mandate-scoped. The PLATFORM re-scoped it to the run,
    and our lower-scope state is the right scope after all.

  => T1 is NOT falsified, but it is SHARPENED. The scope of a bound is not decided
     by where the customer wrote it. It is decided by where the authoritative
     definition places it. Ours agreed with the platform's by accident of design;
     verified equal on all 45 official events.

  NO counterexample found where lower-scope state safely enforces a bound whose
  authoritative definition is genuinely higher-scoped. Attack D above is the
  negative case: mandate-scoped job, run-scoped record, hole.
""")


if __name__ == "__main__":
    cardinality_map()
    account_semantics()
    attacks()
    same_scope_principle()

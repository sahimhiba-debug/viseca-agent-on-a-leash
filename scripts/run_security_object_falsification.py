#!/usr/bin/env python3
"""Falsify the candidate security objects of agentic payment delegation.

This project claimed ONE fundamental security object: the run's persisted decision
ledger. This script is the experiment that tests that claim against seven rivals,
using criteria fixed BEFORE any of them was built:

  F1 SUFFICIENCY   protect it perfectly -- is the unintended economic outcome bounded?
  F2 COMPUTABILITY can it be computed from authoritative recorded facts at all?
  F3 NON-DEGENERACY does protecting it require escalating (almost) everything?
  F4 NECESSITY     is there an attack that ONLY this object catches?

Nothing here is in the decision path. The official replay stays 19/2/24.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import make_event, make_mandate
from wallet_control.csv_data import (
    account_limits_for_card, load_merchants, load_purchase_attempt_items,
)
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.mandate import HardRule
from wallet_control.offline_replay import (
    ALL_SCENARIO_IDS, build_event, compile_and_confirm_mandate_for_scenario,
    history_csv_path, replay_scenario, scenario_rows,
)
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.security_object import MODELS, assess_all
from wallet_control.state import HistoryIndex, RunState

HORIZON, SPACING, CAP = 365, timedelta(minutes=61), 400
M, CARD = "ME_TEST_0001", "CA_TEST"
T0 = datetime(2026, 8, 12, 9, 0, 0, tzinfo=timezone.utc)
RET, FIN = "returns accepted within 30 days", "clearance line, sold as final sale"


def _syn_state():
    return RunState(history=HistoryIndex({CARD: frozenset({M})}, available=True), card_id=CARD)


def _syn_mandate(instr="Buy the 27-inch monitor I chose.", anchor="27-inch", cap=500, extra=None):
    rules = [HardRule(field="authorization.billing_amount_chf", operator="<=", value=cap,
                      currency="CHF", scope="purchase")]
    if anchor:
        rules.append(HardRule(field="item.name_contains", operator="=", value=anchor))
    rules += extra or []
    return make_mandate(instruction=instr, hard_rules=rules)


def _buy(md, s, aid, *, name="27-inch monitor", qty=1, amt=300.0, details=None, hours=0):
    ev = make_event(mandate=md, authorization_id=aid, amount=amt, merchant_id=M,
                    timestamp=T0 + timedelta(hours=hours))
    ev["authorization"]["items"][0].update(item_name=name, quantity=qty, item_category="electronics")
    if details is not None:
        ev["authorization"]["order_returnable"] = "true"
        ev["authorization"]["items"][0]["item_details"] = details
    return evaluate_authorization(ev, md, s)


# --- the official corpus ----------------------------------------------------------


def official_corpus():
    from collections import Counter
    tally = {m: Counter() for m in MODELS}
    asked = {m: [] for m in MODELS}
    engine = Counter()
    for sid in ALL_SCENARIO_IDS:
        history = HistoryIndex.from_csv(history_csv_path())
        md = compile_and_confirm_mandate_for_scenario(sid).snapshot()
        merchants, items = load_merchants(), load_purchase_attempt_items()
        state = RunState(history=history, card_id=md.card_id)
        for row in scenario_rows(sid):
            ctx = {"approved_spend_in_period_chf": float(state.total_approved_spend_chf()),
                   "recent_authorizations": state.recent_authorizations_context()}
            ev = build_event(row, items[row["authorization_id"]], merchants[row["merchant_id"]], md, ctx)
            d = evaluate_authorization(ev, md, state)
            engine[d.decision] += 1
            for name, v in assess_all(md, state, row["authorization_id"]).items():
                tally[name][v.standing] += 1
                if v.standing == "outside" and d.decision == "allow":
                    asked[name].append(Decimal(row["billing_amount_chf"]))
    print("=== OFFICIAL CORPUS — 45 events ===  engine:", dict(engine), "\n")
    print(f"{'model':22s} {'within':>7s} {'outside':>8s} {'unknown':>8s} {'questions an ALLOW':>20s} {'CHF':>10s}")
    print("-" * 80)
    for m in MODELS:
        t, q = tally[m], asked[m]
        print(f"{m:22s} {t['within']:>7d} {t['outside']:>8d} {t['unknown']:>8d} "
              f"{len(q):>20d} {sum(q):>10,.2f}")


# --- F1 ---------------------------------------------------------------------------


def f1():
    def run(sid, model):
        history = HistoryIndex.from_csv(history_csv_path())
        md = compile_and_confirm_mandate_for_scenario(sid).snapshot()
        merchants, items = load_merchants(), load_purchase_attempt_items()
        rep = {d.authorization_id: d for d in replay_scenario(sid, history).decisions}
        t = max((r for r in scenario_rows(sid) if rep[r["authorization_id"]].decision == "allow"),
                key=lambda r: float(r["billing_amount_chf"]))
        unit = Decimal(t["billing_amount_chf"])
        start = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
        state = RunState(history=history, card_id=md.card_id)
        total, n = Decimal(0), 0
        for slot in range(int(timedelta(days=HORIZON) / SPACING)):
            row = dict(t); row["authorization_id"] = f"AUX{slot:06d}"
            row["timestamp"] = (start + SPACING * slot).isoformat().replace("+00:00", "Z")
            ctx = {"approved_spend_in_period_chf": float(state.total_approved_spend_chf()),
                   "recent_authorizations": state.recent_authorizations_context()}
            ev = build_event(row, items[t["authorization_id"]], merchants[t["merchant_id"]], md, ctx)
            if evaluate_authorization(ev, md, state).decision != "allow":
                continue
            if MODELS[model](md, state, row["authorization_id"]).standing == "outside":
                return total, True
            total += unit; n += 1
            if n >= CAP:
                return total, False
        return total, True

    print(f"\n\n=== F1 SUFFICIENCY === CHF extracted in {HORIZON} simulated days if the object")
    print(f"were protected perfectly. UNBOUNDED = still spending after {CAP} purchases.\n")
    hdr = f"{'model':22s}" + "".join(f"{s[-4:]:>12s}" for s in ALL_SCENARIO_IDS)
    print(hdr); print("-" * len(hdr))
    for m in MODELS:
        cells = []
        for sid in ALL_SCENARIO_IDS:
            chf, stopped = run(sid, m)
            cells.append(f"{chf:,.0f}" if stopped else "UNBOUNDED")
        print(f"{m:22s}" + "".join(f"{c:>12s}" for c in cells))


# --- attacks ----------------------------------------------------------------------


def attacks():
    res = {}

    def authz(name, fn):
        md, s, aid = fn()
        assert s.get_stored_decision(aid) is not None, name
        res[name] = {m: v.standing == "outside" for m, v in assess_all(md, s, aid).items()}

    def a1():
        md = _syn_mandate(); s = _syn_state(); _buy(md, s, "AU1", hours=0); _buy(md, s, "AUX", hours=5)
        return md, s, "AUX"

    def a2():
        md = _syn_mandate(); s = _syn_state(); _buy(md, s, "AUX", qty=2, amt=398.0)
        return md, s, "AUX"

    def a3():
        md = _syn_mandate(extra=[HardRule(field="order.return_window_days", operator=">=", value=14)])
        s = _syn_state()
        assert _buy(md, s, "AU1", hours=0).decision == "review"
        resolve_authorization("AU1", "allow", s, resolved_at=datetime.now(timezone.utc), mandate=md)
        _buy(md, s, "AUX", details=RET, hours=5)
        return md, s, "AUX"

    def a8():
        md = _syn_mandate(anchor=None, instr="Buy running shoes."); s = _syn_state()
        _buy(md, s, "AU1", name="shoe", details=FIN, hours=0)
        _buy(md, s, "AUX", name="shoe", details=FIN, hours=5)
        return md, s, "AUX"

    def a9():
        md = _syn_mandate(anchor=None, instr="Buy running shoes."); s = _syn_state()
        _buy(md, s, "AU1", name="shoe", details=RET, hours=0)
        _buy(md, s, "AUX", name="shoe", details=RET, hours=5)
        return md, s, "AUX"

    def a10():
        md = _syn_mandate(anchor=None, instr="The agent may buy clothing for me whenever needed.")
        s = _syn_state()
        _buy(md, s, "AU1", name="coat", details=FIN, hours=0)
        _buy(md, s, "AUX", name="coat", details=FIN, hours=5)
        return md, s, "AUX"

    def a11():
        md = _syn_mandate(anchor=None, instr="Buy running shoes."); s = _syn_state()
        _buy(md, s, "AUX", name="shoe", details=FIN, hours=0)
        return md, s, "AUX"

    for n, f in [("A1  repeat a one-shot job", a1), ("A2  batch qty=2 under the cap", a2),
                 ("A3  repeat after a human step-up", a3), ("A8  second FINAL-SALE purchase", a8),
                 ("A9  second RETURNABLE purchase (control)", a9),
                 ("A10 repeated FINAL-SALE, STANDING mandate", a10),
                 ("A11 first FINAL-SALE purchase (control)", a11)]:
        authz(n, f)

    names = list(MODELS)
    print("\n\n=== AUTHORIZATION ATTACKS === YES = the model calls it outside the delegation\n")
    print(f"{'attack':44s} " + " ".join(f"{n.split('_')[0]:>4s}" for n in names))
    print("-" * 44 + "-" + "-" * (5 * len(names)))
    for a, r in res.items():
        print(f"{a:44s} " + " ".join(f"{'YES' if r[n] else '  .':>4s}" for n in names))

    print("\n\n=== EXECUTION ATTACKS === the ledger's own domain\n")

    def probe(name, fn):
        try:
            moved = fn()
        except PaymentError:
            moved = False
        print(f"  {name:50s} {'MONEY MOVED -- HOLE' if moved else 'held'}")

    def mand2(cap=500):
        return make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf",
                            operator="<=", value=cap, currency="CHF", scope="purchase")])

    def e1():
        md = mand2(); s = _syn_state(); _buy(md, s, "AU1", name="x")
        p = MockPSP(s)
        p.charge(charge_id="C1", authorization_id="AU1", amount_chf=Decimal("300"), merchant_id=M)
        p.charge(charge_id="C2", authorization_id="AU1", amount_chf=Decimal("300"), merchant_id=M)
        return True

    def e2():
        md = mand2(); s = _syn_state(); _buy(md, s, "AU1", name="x"); s.revoke_outstanding_authorities()
        MockPSP(s).charge(charge_id="C1", authorization_id="AU1", amount_chf=Decimal("300"), merchant_id=M)
        return True

    def e3():
        md = mand2(); s = _syn_state(); _buy(md, s, "AU1", name="x"); s.revoke_outstanding_authorities()
        r = RunState.from_snapshot(json.loads(json.dumps(s.to_snapshot())), s.history)
        MockPSP(r).charge(charge_id="C1", authorization_id="AU1", amount_chf=Decimal("300"), merchant_id=M)
        return True

    def e4():
        md = mand2(); s = _syn_state(); _buy(md, s, "AU1", name="x")
        MockPSP(s).charge(charge_id="C1", authorization_id="AU1", amount_chf=Decimal("300"), merchant_id="ME_OTHER")
        return True

    def e5():
        md = mand2(); s = _syn_state(); _buy(md, s, "AU1", name="x")
        MockPSP(s).charge(charge_id="C1", authorization_id="AU1", amount_chf=Decimal("5000"), merchant_id=M)
        return True

    for n, f in [("E1 charge the same authorization twice", e1),
                 ("E2 charge after revocation", e2),
                 ("E3 revoke, crash, restart, charge", e3),
                 ("E4 redirect the charge to another merchant", e4),
                 ("E5 charge above the approved amount", e5)]:
        probe(n, f)
    print("\n  M5, M7 and M8 assess a PROPOSED PURCHASE and have no opinion on any of these.")
    print("  That is not a weakness. It is a different domain -- which is the whole result.")


def account_envelope():
    print("\n\n=== THE BOUND THAT ALREADY EXISTS, AND THAT THE WALLET NEVER READS ===\n")
    print(f"{'SCEN':9s} {'card':8s} {'per-txn':>9s} {'monthly':>9s} {'x12':>10s}  binding constraint")
    print("-" * 72)
    for sid in ALL_SCENARIO_IDS:
        md = compile_and_confirm_mandate_for_scenario(sid).snapshot()
        lim = account_limits_for_card(md.card_id)
        cap = next((r.value for r in md.hard_rules
                    if r.field == "authorization.billing_amount_chf" and r.scope == "purchase"), None)
        per = float(lim["per_transaction_limit_chf"]); mon = float(lim["monthly_limit_chf"])
        binding = "the mandate cap" if cap and cap < per else "THE ACCOUNT"
        print(f"{sid:9s} {md.card_id:8s} {per:>9,.0f} {mon:>9,.0f} {mon*12:>10,.0f}  {binding}")
    print("\n  data_dictionary.md: these are \"account attributes carried on the row for")
    print("  context\", and it tells the control layer to aggregate its own windows.")
    print("  The per-transaction limit is never the binding constraint on any official")
    print("  mandate -- the customer's own cap is always lower. Only the monthly one bites.")


if __name__ == "__main__":
    official_corpus()
    attacks()
    account_envelope()
    f1()

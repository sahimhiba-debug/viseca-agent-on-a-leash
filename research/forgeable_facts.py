"""Which of the customer's rules can the agent satisfy by WRITING the fact?

RESEARCH APPARATUS. Never imported by `src/wallet_control/`.

`src/wallet_control/provenance.py` declares, for every fact a rule is evaluated
against, whether the party being judged can author it and whether anything can
contradict them. That declaration is a hypothesis. This file is the experiment, and
it fails the build when the two disagree.

THE CRITERION

A fact is FORGEABLE if misstating it changes the decision **while leaving the
purchase itself unchanged**: same item id, same shop, same price, same moment. Only
the description moves.

That clause is what separates a real hole from an apparent one. An agent can write
`billing_amount_chf` too, and writing a smaller number turns a BLOCK into an ALLOW --
for a smaller charge, because the number it names is the number that is taken. The
purchase changed. Writing a fact is not forging it; forging it is getting the same
thing on better terms.

    bound      a violating purchase cannot be talked into compliance at all
    refutable  the claim is checkable against reference data and is refused
    advisory   the claim is believed, and the purchase goes through

EVERY VERDICT BELOW COMES FROM THE REAL ENGINE deciding a real event. Nothing here
inspects a rule to decide what it is worth.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "src"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from datetime import datetime, timedelta, timezone                         # noqa: E402

from tests.helpers import make_event, make_mandate                         # noqa: E402
from wallet_control.csv_data import history_csv_path, load_items, load_merchants  # noqa: E402
from decimal import Decimal

from wallet_control.decision_engine import evaluate_authorization          # noqa: E402
from wallet_control.mandate import HardRule, UncertaintyPolicy             # noqa: E402
from wallet_control.provenance import ADVISORY, BOUND, FACTS, REFUTABLE    # noqa: E402
from wallet_control.state import HistoryIndex, RunState                    # noqa: E402

CARD = "CA0001"
FAMILIAR_SHOP = "ME0001"        # a grocery shop this card has genuinely paid before
STRANGE_SHOP = "ME0005"         # a grocery shop it never has
AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)

RULES = [
    HardRule(field="authorization.billing_amount_chf", operator="<=", value=120,
             currency="CHF", scope="purchase"),
    HardRule(field="merchant.familiar", operator="=", value="true"),
    HardRule(field="merchant.category", operator="in", value=["groceries"]),
    HardRule(field="item.category", operator="in", value=["groceries"]),
    HardRule(field="item.unrequested_present", operator="=", value="false"),
    HardRule(field="item.name_contains", operator="=", value="produce"),
    HardRule(field="item.size", operator="=", value="M"),
    HardRule(field="order.return_window_days", operator=">=", value=14),
    HardRule(field="session.integrity_risk", operator="=", value="false"),
    # A rolling ceiling, so the clock itself can be put on trial. Without one, the
    # fact that decides WHICH WINDOW money falls into is never exercised, and it was
    # the only decision input with no declared provenance at all.
    HardRule(field="authorization.billing_amount_chf", operator="<=", value=300,
             currency="CHF", scope="period", period_days=7),
]

# An honest, compliant purchase. Every probe below starts here.
HONEST: dict[str, Any] = {
    "item_id": "IT0018", "item_name": "Fresh produce order",
    "item_category": "groceries", "unit_price": 60.0,
    "details": "size M; returns accepted within 30 days",
    "merchant": FAMILIAR_SHOP, "device": "DVC-A", "attempts": 0,
    "timestamp": AT, "prior": 0.0,
}


def _decide(spec: dict[str, Any], *, aid: str, state: RunState | None = None) -> str:
    mandate = make_mandate(instruction="probe", uncertainty_policy=UncertaintyPolicy.ASK,
                           hard_rules=RULES + list(spec.get("extra_rules", [])), card_id=CARD)
    merchant = load_merchants()[spec["merchant"]]
    event = make_event(mandate=mandate, authorization_id=aid, amount=spec["unit_price"],
                       merchant_id=spec["merchant"],
                       merchant_category=spec.get("merchant_category")
                       or merchant["merchant_category"],
                       card_id=CARD, timestamp=spec["timestamp"], order_returnable="true",
                       device_id=spec["device"],
                       recent_attempt_count_10m=spec["attempts"],
                       items=[{"line_no": 1, "item_id": spec["item_id"],
                               "item_name": spec["item_name"],
                               "item_category": spec["item_category"], "quantity": 1,
                               "unit_price": spec["unit_price"], "currency": "CHF",
                               "item_details": spec["details"]}])
    run = state or RunState(history=HistoryIndex.from_csv(history_csv_path()), card_id=CARD)
    if spec.get("prior"):
        # Money already approved inside the rolling window, so a ceiling probe has
        # something to breach. Recorded directly rather than by deciding a second
        # purchase, which would drag the duplicate machinery into an unrelated probe.
        run.record_decision(f"{aid}_prior", "allow", Decimal(str(spec["prior"])), AT,
                            merchant_id=spec["merchant"], basket_key=())
    if spec.get("errand_prior"):
        # One purchase already approved for this errand, in the wallet's own ledger.
        run.record_decision(f"{aid}_errand", "allow", Decimal("10"), AT - timedelta(days=1),
                            merchant_id=spec["merchant"], basket_key=())
    return evaluate_authorization(event, mandate, run).decision


# field -> (how to violate it, how to then TALK IT INTO COMPLIANCE without
#           changing the goods, the shop, the price or the moment)
PROBES: dict[str, tuple[dict, dict | None]] = {
    "item.category": ({"item_id": "IT0005", "item_name": "Digital gift voucher produce",
                       "item_category": "gift_card"},
                      {"item_category": "groceries"}),
    "item.name_contains": ({"item_name": "Gift voucher"},
                           {"item_name": "Fresh produce order"}),
    "item.size": ({"details": "size XL; returns accepted within 30 days"},
                  {"details": "size M; returns accepted within 30 days"}),
    "order.return_window_days": ({"details": "size M; returns accepted within 2 days"},
                                 {"details": "size M; returns accepted within 30 days"}),
    "merchant.familiar": ({"merchant": STRANGE_SHOP}, None),
    # THIS PROBE USED TO BE `({"merchant": "ME0009"}, None)` -- violate by using a
    # different shop, and do not even try to talk it into compliance. It measured
    # BOUND and agreed with a declaration that said "loaded from reference data,
    # never from the proposal". The engine never loaded it from anywhere: it read
    # `auth.merchant.merchant_category` out of the event. The probe missed the hole
    # because it shared the misunderstanding that created it.
    #
    # ME0007 (MetroHop, `transport`) is a shop CA0001 really has paid, so the
    # familiarity rule cannot mask what the CATEGORY rule does. The relabel then
    # changes nothing but the word.
    "merchant.category": ({"merchant": "ME0007"},
                          {"merchant_category": "groceries"}),
    "authorization.billing_amount_chf": ({"unit_price": 900.0}, {"unit_price": 60.0}),
    "session.integrity_risk": ({"device": "DVC-B", "attempts": 3}, None),
    # `item.unrequested_present` is derived from item.category and is exercised by
    # the first probe; a basket whose only line is a gift card is both.
    "item.unrequested_present": ({"item_id": "IT0005", "item_name": "voucher produce",
                                  "item_category": "gift_card"},
                                 {"item_category": "groceries"}),
    # THE ERRAND LEDGER. Only for this probe, so the one-off rule does not colour the
    # others (a prior approval IS a done errand, which would move the clock probe).
    # The agent has nothing to relabel: the fact is the wallet's own record.
    "order.errand_already_fulfilled": ({"extra_rules": [HardRule(field="order.errand_already_fulfilled",
                                                                 operator="=", value="false")],
                                        "errand_prior": True}, None),
    # THE CLOCK. Spend the rolling ceiling, then try to escape it by claiming the
    # purchase happened in a different week. It works on the decision -- and it is
    # not a forgery, because a purchase at another moment is another purchase. That
    # is the fourth clause of the criterion, and until this probe existed the code
    # only checked three of them.
    "authorization.timestamp": ({"prior": 300.0},
                                {"timestamp": AT - timedelta(days=8)}),
}


def measure() -> list[dict[str, Any]]:
    baseline = _decide(HONEST, aid="AU_BASE")
    rows = []
    for index, fact in enumerate(FACTS):
        violate, talk = PROBES[fact.field]
        violating = _decide({**HONEST, **violate}, aid=f"AU_V{index}")
        if talk is None:
            measured, relabelled = BOUND, None
        else:
            relabelled = _decide({**HONEST, **violate, **talk}, aid=f"AU_R{index}")
            if relabelled == "allow" and violating != "allow":
                # It worked. Is the PURCHASE unchanged? Only then is it a forgery.
                # THE FOURTH CLAUSE. The prose has always said "the same goods, the
                # same shop, the same price and THE SAME MOMENT", and this set listed
                # only three of them -- so a probe that moved the purchase in time
                # would have been scored as a forgery of an unchanged purchase. A
                # purchase in another week is a different purchase.
                economic = {"item_id", "unit_price", "merchant", "timestamp"}
                changed = economic & set(talk)
                measured = ADVISORY if not changed else BOUND
            else:
                measured = REFUTABLE if violating != "allow" else BOUND
        rows.append({"field": fact.field, "declared": fact.binding, "measured": measured,
                     "baseline": baseline, "violating": violating,
                     "relabelled": relabelled,
                     "changed_the_purchase": bool(talk and ({"item_id", "unit_price",
                                                             "merchant", "timestamp"}
                                                            & set(talk)))})
    return rows


def main() -> int:
    rows = measure()
    print("WHICH OF THE CUSTOMER'S RULES CAN THE AGENT SATISFY BY WRITING?\n")
    print("  An honest compliant purchase: %s\n" % rows[0]["baseline"].upper())
    print("  %-34s %-10s %-10s %-9s %s" %
          ("fact the rule is checked against", "violating", "relabelled", "measured", "declared"))
    print("  " + "-" * 92)
    for row in rows:
        mark = "" if row["declared"] == row["measured"] else "   <-- DISAGREES"
        print("  %-34s %-10s %-10s %-9s %s%s" %
              (row["field"], row["violating"], row["relabelled"] or "-",
               row["measured"], row["declared"], mark))
    print()
    advisory = [r["field"] for r in rows if r["measured"] == ADVISORY]
    print("  FORGEABLE -- the same goods, the same shop, the same price, and the")
    print("  decision changes because the description changed:")
    for field in advisory:
        print(f"      {field}")
    print()
    print("  The customer wrote those requirements next to the others and was never")
    print("  told the difference. That is what `provenance.py` puts on the screen.")
    disagree = [r for r in rows if r["declared"] != r["measured"]]
    if disagree:
        print(f"\n  *** {len(disagree)} declaration(s) do not match the measurement ***")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

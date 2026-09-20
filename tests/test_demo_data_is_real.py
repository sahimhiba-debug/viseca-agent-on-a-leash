"""Everything the demo shows must be the official data, or be labelled as not.

Written after an audit found the demo page selling `IT0012` -- a **hotel room** in
`data/official/items.csv` -- as "Pantry restock, groceries, CHF 35". `IT0010` and
`IT0011` are waterproof jackets and were being sold as milk and produce. Real item
ids, fabricated names, categories and prices. A judge who greps the CSV finds a
hotel room in a grocery basket, and every other number on the screen becomes
suspect at that moment.

The rule this file enforces: if the demo names an official id, it must tell the
truth about it. Names and categories must match exactly, prices must sit inside
that item's own published band, and merchants must be real merchants of the right
category.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "index.html"
DATA = ROOT / "data" / "official"


def _rows(name):
    with (DATA / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


ITEMS = {r["item_id"]: r for r in _rows("items.csv")}
MERCHANTS = {r["merchant_id"]: r for r in _rows("merchants.csv")}


def demo_offers():
    text = PAGE.read_text()
    block = text[text.index("const AG_OFFERS=["):text.index("];", text.index("const AG_OFFERS=["))]
    rows = re.findall(
        r"\{item_id:'([^']+)',name:'([^']+)',category:'([^']+)',"
        r"unit_price:([\d.]+),merchant:'([^']+)',mname:'([^']+)',ret:(\d+|null)\}", block)
    assert rows, "could not read the demo page's offer list"
    return rows


@pytest.mark.parametrize("offer", demo_offers(), ids=lambda o: f"{o[0]}@{o[4]}")
def test_every_demo_offer_tells_the_truth_about_the_official_item(offer):
    item_id, name, category, price, merchant, merchant_name, _ret = offer

    assert item_id in ITEMS, f"{item_id} is not in the official catalogue"
    official = ITEMS[item_id]
    assert name == official["item_name"], (
        f"{item_id} is {official['item_name']!r} officially, shown as {name!r}")
    assert category == official["item_category"], (
        f"{item_id} is {official['item_category']!r} officially, shown as {category!r}")

    low = float(official["unit_price_min_chf"])
    high = float(official["unit_price_max_chf"])
    assert low <= float(price) <= high, (
        f"{item_id} shown at CHF {price}, outside its official band {low}-{high}")

    assert merchant in MERCHANTS, f"{merchant} is not a real merchant"
    assert MERCHANTS[merchant]["merchant_category"] == "groceries", (
        f"{merchant} is a {MERCHANTS[merchant]['merchant_category']} merchant")
    assert merchant_name == MERCHANTS[merchant]["merchant_name"], (
        f"{merchant} is {MERCHANTS[merchant]['merchant_name']!r} officially, "
        f"shown to the jury as {merchant_name!r}")


def test_the_demo_relies_on_real_purchase_history_for_familiarity():
    """The whole first refusal rests on one shop being unfamiliar to this card. If
    that came from a fixture rather than the official history, the most striking
    moment in the demo would be staged."""
    from wallet_control.csv_data import history_csv_path
    from wallet_control.state import HistoryIndex

    history = HistoryIndex.from_csv(history_csv_path())
    shops = {o[4] for o in demo_offers()}
    familiar = {s for s in shops if history.is_familiar("CA0001", s)}
    unfamiliar = shops - familiar

    assert familiar and unfamiliar, (
        f"the demo needs one familiar and one unfamiliar shop; got {shops} "
        f"with familiar={familiar}")


def test_the_demo_still_produces_two_non_price_refusals():
    """The narrative promises a merchant refusal and a return-terms refusal. If a
    price edit ever makes the agent succeed immediately, or makes it fail on
    `amount` instead, the script is telling the jury something that is not
    happening."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed, so the page's own planner cannot be run here")

    text = PAGE.read_text()
    js = text[text.index("const AG_OFFERS=["):text.index("async function runAgent(){")]
    script = js + """
const b={ruledOut:new Set(),ceiling:null,returnsMatter:false,tried:new Set()};
const out=[];
for (const blocked of [['merchant'],['order_terms'],[]]) {
  const s=agBest(b); if(!s) break;
  out.push({merchant:s.merchant, total:s.lines.reduce((a,o)=>a+o.unit_price,0),
            items:s.lines.map(o=>o.item_id)});
  if(!blocked.length) break;
  agLearn(b,s.lines,s.merchant,blocked);
}
console.log(JSON.stringify(out));
"""
    trace = json.loads(subprocess.run([node, "-e", script], capture_output=True,
                                      text=True, timeout=30).stdout)
    assert len(trace) == 3, f"the demo no longer takes three attempts: {trace}"
    assert trace[0]["merchant"] != trace[1]["merchant"], "the agent never changes shop"
    assert trace[1]["merchant"] == trace[2]["merchant"], "the second change should be goods, not shop"
    assert set(trace[1]["items"]) != set(trace[2]["items"]), "the agent never changes the goods"
    assert trace[2]["total"] >= trace[1]["total"], (
        "the approved basket is CHEAPER than the refused one, so the demo no longer "
        "shows that the agent solved a non-price problem without spending less")

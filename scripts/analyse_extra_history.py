#!/usr/bin/env python3
"""Measure the wallet's signals against the organisers' extended history pack.

Usage:
    python scripts/analyse_extra_history.py <path/to/additional-data-history>

The pack (144,674 authorizations, 500 customers, 2025-09 to 2026-07) was sent to
teams separately and is not vendored: it is 48 MB and none of its customers appear
in the five scenarios, so it changes no decision this repository makes. What it can
do is test the signals those decisions rest on, at thirty times the official
history: how often an ordinary customer buys from a new shop, changes device, or
repeats an order -- and what the issuer did when they did.

`status` is an issuer outcome, not a fraud label (the pack's own README), so the
decline rates here describe the issuer, never whether a purchase was wanted.
"""
import csv
import sys
import time
import tracemalloc
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
D = sys.argv[1]
H = f"{D}/authorization_history.csv"

from wallet_control.state import HistoryIndex  # noqa: E402

# 1. scale: the runtime index on 30x the official history
tracemalloc.start(); t = time.perf_counter()
idx = HistoryIndex.from_csv(Path(H))
el = time.perf_counter() - t; cur, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
print(f"[scale] HistoryIndex.from_csv on 144,674 rows: {el:.2f}s, peak {peak/1e6:.0f} MB")
t = time.perf_counter()
for _ in range(100000): idx.is_familiar("CA1001", "ME0001")
print(f"[scale] is_familiar: {(time.perf_counter()-t)/100000*1e6:.2f} us/call")

rows = list(csv.DictReader(open(H)))
for r in rows: r["ts"] = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
rows.sort(key=lambda r: r["ts"])
cards = {r["card_id"]: r for r in csv.DictReader(open(f"{D}/cards.csv"))}
purch = [r for r in rows if r["transaction_type"] == "purchase"]

def pct(a, b): return f"{a}/{b} = {100*a/max(b,1):.1f}%"

# 2. merchant novelty, by card and by customer, in time order (approved history only counts)
seen_card, seen_cust, seen_card_human, seen_cust_human = defaultdict(set), defaultdict(set), defaultdict(set), defaultdict(set)
new_card = Counter(); new_cust = Counter(); tot = Counter()
repl_new_card = repl_new_cust = repl_tot = 0
for r in purch:
    who = r["initiator_type"]; c, u, m = r["card_id"], r["customer_id"], r["merchant_id"]
    tot[who] += 1
    nc = m not in seen_card_human[c]; nu = m not in seen_cust_human[u]
    new_card[who] += nc; new_cust[who] += nu
    if c.startswith("CA9") and who == "agent":
        repl_tot += 1; repl_new_card += nc; repl_new_cust += nu
    if r["status"] == "approved" and who != "agent":
        seen_card_human[c].add(m); seen_cust_human[u].add(m)
print("\n[familiarity] purchase at a merchant never used before (by the customer, not the agent)")
for who in ("human", "agent"):
    print(f"  {who:6s} per CARD {pct(new_card[who], tot[who])}   per CUSTOMER {pct(new_cust[who], tot[who])}")
print(f"  agent purchases on replacement cards (CA9xxx): new per card {pct(repl_new_card, repl_tot)}, new per customer {pct(repl_new_cust, repl_tot)}")

# 3. what the issuer did with those
dec = Counter(); cnt = Counter()
seen = defaultdict(set)
for r in purch:
    if r["initiator_type"] != "agent": 
        if r["status"] == "approved": seen[r["card_id"]].add(r["merchant_id"])
        continue
    k = "new merchant" if r["merchant_id"] not in seen[r["card_id"]] else "known merchant"
    cnt[k] += 1; dec[k] += r["status"] == "declined"
print("\n[issuer outcome, agent purchases]")
for k in cnt: print(f"  {k:15s} declined {pct(dec[k], cnt[k])}")

# 4. device changes: same customer, two purchases within 30 min, different device
last = {}; close = changed = 0; ch_dec = Counter(); ch_cnt = Counter()
for r in purch:
    u = r["customer_id"]; p = last.get(u)
    if p and r["ts"] - p["ts"] <= timedelta(minutes=30) and r["channel"] == "ecommerce" and p["channel"] == "ecommerce":
        close += 1; d = r["customer_device_id"] != p["customer_device_id"]; changed += d
        k = "device changed" if d else "same device"; ch_cnt[k] += 1; ch_dec[k] += r["status"] == "declined"
    last[u] = r
print("\n[device] consecutive online purchases by one customer within 30 min")
print(f"  device changed: {pct(changed, close)}")
for k in ch_cnt: print(f"  {k:15s} declined {pct(ch_dec[k], ch_cnt[k])}")
first_dev = Counter(); tot_dev = 0
for r in purch:
    if r["channel"] == "ecommerce":
        tot_dev += 1; first_dev[r["approved_device_transaction_count_before"] == "0"] += 1
print(f"  online purchase from a device with no prior approved use: {pct(first_dev[True], tot_dev)}")

# 5. duplicates: same card, merchant, amount within 10 min
lastk = {}; dup = 0; dup_dec = 0
for r in purch:
    k = (r["card_id"], r["merchant_id"], r["billing_amount_chf"])
    p = lastk.get(k)
    if p and r["ts"] - p["ts"] <= timedelta(minutes=10):
        dup += 1; dup_dec += r["status"] == "declined"
    lastk[k] = r
print(f"\n[duplicates] same card+merchant+amount within 10 min: {dup} rows, declined {pct(dup_dec, dup)}")

# 6. agent vs human overall
for who in ("human", "agent", "merchant"):
    rs = [r for r in rows if r["initiator_type"] == who]
    print(f"[outcome] {who:8s} {len(rs):6d} rows, declined {pct(sum(r['status']=='declined' for r in rs), len(rs))}")
# 7. hard causes the issuer applies
hard = Counter()
for r in purch:
    if r["status"] != "declined": continue
    if r["card_status"] != "active": hard["card not active"] += 1
    elif float(r["billing_amount_chf"]) > float(r["per_transaction_limit_chf"] or 1e18): hard["over per-transaction limit"] += 1
    elif r["merchant_country"] != "CH" and r["international_enabled"] == "false": hard["international disabled"] += 1
    else: hard["no visible cause"] += 1
print("\n[declined purchases by visible cause]", dict(hard))

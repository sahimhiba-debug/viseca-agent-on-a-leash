"""Read-only loaders for the official synthetic data pack (data/official/*.csv).

These files are the official challenge fixtures (see the top-level `reference/`
clone of https://github.com/Swiss-ai-Weeks/viseca-2026 that this copy is taken
from). Nothing in this module writes to them; it only parses rows into plain
dicts for `offline_replay.py` and `state.HistoryIndex` to consume.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "official"


def _read_csv(name: str) -> list[dict[str, str]]:
    path = DATA_DIR / name
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def load_scenario_catalogue() -> dict[str, dict[str, str]]:
    return {row["scenario_id"]: row for row in _read_csv("scenario_catalogue.csv")}


@lru_cache(maxsize=1)
def load_scenario_authorities() -> dict[str, dict[str, str]]:
    return {row["authority_id"]: row for row in _read_csv("scenario_authorities.csv")}


@lru_cache(maxsize=1)
def load_merchants() -> dict[str, dict[str, str]]:
    return {row["merchant_id"]: row for row in _read_csv("merchants.csv")}


@lru_cache(maxsize=1)
def load_purchase_attempts() -> list[dict[str, str]]:
    return _read_csv("purchase_attempts.csv")


@lru_cache(maxsize=1)
def load_purchase_attempt_items() -> dict[str, list[dict[str, str]]]:
    by_auth: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv("purchase_attempt_items.csv"):
        by_auth[row["authorization_id"]].append(row)
    for lines in by_auth.values():
        lines.sort(key=lambda r: int(r["line_no"]))
    return by_auth


def scenario_rows(scenario_id: str) -> list[dict[str, str]]:
    rows = [r for r in load_purchase_attempts() if r["scenario_id"] == scenario_id]
    rows.sort(key=lambda r: int(r["replay_order"]))
    return rows


def history_csv_path() -> Path:
    return DATA_DIR / "authorization_history.csv"

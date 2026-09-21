"""Read-only loaders for the official synthetic data pack (data/official/*.csv).

These files are the official challenge fixtures (see the top-level `reference/`
clone of https://github.com/Swiss-ai-Weeks/viseca-2026 that this copy is taken
from). Nothing in this module writes to them; it only parses rows into plain
dicts for `offline_replay.py` and `state.HistoryIndex` to consume.
"""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from functools import lru_cache
from pathlib import Path


def _data_dir() -> Path:
    """Where the official CSV pack lives.

    Source checkouts find it two levels up from this file. An INSTALLED copy does
    not: `pip install .` puts the package in site-packages, and `parents[2]` then
    points at a directory inside the virtualenv that contains no data at all. That
    made the first Docker image broken on import -- caught by installing into a
    throwaway venv before claiming the image worked, rather than after.

    `WALLET_DATA_DIR` takes precedence so a container can say where it put the pack
    without the package having to guess.
    """
    override = os.environ.get("WALLET_DATA_DIR")
    if override:
        return Path(override)

    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "data" / "official",     # a source checkout: src/wallet_control/..
        Path.cwd() / "data" / "official",          # an installed copy run from the app root
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    # Nothing found: return the source-checkout path so the eventual error names the
    # place a developer expects, rather than a site-packages path nobody recognises.
    return candidates[0]


DATA_DIR = _data_dir()


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


@lru_cache(maxsize=1)
def load_cards() -> dict[str, dict[str, str]]:
    return {row["card_id"]: row for row in _read_csv("cards.csv")}


@lru_cache(maxsize=1)
def load_accounts() -> dict[str, dict[str, str]]:
    """Accounts carry `per_transaction_limit_chf` and `monthly_limit_chf`.

    These are the only TOTAL spending bounds anywhere in the official data. They are
    platform-supplied and the agent cannot forge them -- and the wallet has never
    read them. See docs/SECURITY_OBJECT_FALSIFICATION.md; an earlier pass of this
    project stated that no credit limit existed in the official schema, which was
    wrong: it exists here, at the account level, not on the mandate.
    """
    return {row["account_id"]: row for row in _read_csv("accounts.csv")}


def account_limits_for_card(card_id: str) -> dict[str, str] | None:
    """Resolve a card to the limits of the account it belongs to."""
    card = load_cards().get(card_id)
    if card is None:
        return None
    return load_accounts().get(card["account_id"])

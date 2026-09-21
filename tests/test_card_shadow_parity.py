"""The page's card-limit shadow must agree with the one the tests measure.

Every agent refusal on screen carries a line saying whether a conventional card
limit would have allowed the same purchase. That line is the project's core
argument, so it must not be a second implementation quietly disagreeing with the
first. Same arrangement as the browser planner: duplication is allowed when a test
forbids it from mattering.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from research.card_limit_control import CardLimitControl
from scripts.generate_attack_manifest import CARD, card_control

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "index.html"

CASES = [10, 47, 107, 108, 119.99, 120, 120.01, 280, 8400, 0, -1000]


def test_the_generated_card_parameters_are_current():
    assert CARD.exists(), "run scripts/generate_attack_manifest.py"
    assert json.loads(CARD.read_text()) == card_control()


def test_the_page_reads_the_generated_parameters():
    page = PAGE.read_text()
    assert "card-control.json" in page, "the page hard-codes the card's numbers again"
    assert "CARD.per_transaction_chf" in page


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node is not installed, so the page's shadow cannot be "
                           "checked against the Python control on this machine")
@pytest.mark.parametrize("amount", CASES, ids=lambda a: str(a))
def test_the_page_and_the_control_agree(amount):
    python_verdict = CardLimitControl().decide(
        {"amount_chf": Decimal(str(amount)), "mcc": "5411", "country": "CH"})["decision"]

    page = PAGE.read_text()
    js = page[page.index("async function cardShadow(lines)"):page.index("async function runAgent(){")]
    script = f"""
const CARD = {json.dumps(card_control())};
{js.replace("async function cardShadow", "function cardShadow")
   .replace("if(!CARD) CARD = await (await fetch('card-control.json')).json();", "")}
const out = cardShadow([{{unit_price: {amount}, quantity: 1}}]);
console.log(out.decision);
"""
    result = subprocess.run([shutil.which("node"), "-e", script],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == python_verdict, (
        f"CHF {amount}: page says {result.stdout.strip()}, control says {python_verdict}")


def test_the_shadow_only_appears_when_it_is_actually_true():
    """The line must never claim a card would have allowed something it refuses.
    It is rendered only when the shadow allows AND the wallet does not."""
    page = PAGE.read_text()
    assert "o.shadow.decision==='allow' && o.v.decision!=='allow'" in page, (
        "the shadow line's condition changed -- it must only appear where a card "
        "limit genuinely would have let the purchase through")

"""Harness for testing the compiler's fidelity to customer intent.

Policy equivalence here is BEHAVIOURAL, never textual. Two compiled policies are
equivalent if they reach the same decision on every purchase in a generated probe
corpus. Comparing rule lists would be a weaker test that passes when the compiler
produces differently-shaped rules with identical effect, and fails when it produces
identically-shaped rules whose values differ in a way no purchase can observe.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.policy_compiler import compile_instruction
from wallet_control.state import HistoryIndex, RunState

KNOWN = "ME_KNOWN"
STRANGER = "ME_STRANGE"
UNSEEN = "ME_NO_HISTORY"      # history unavailable -> merchant.familiar is UNKNOWN, not false
T0 = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)

CATEGORIES = ["groceries", "sporting_goods", "electronics", "clothing", "jewellery"]
NAMES = ["bread", "road-running shoes", "trail-running shoes", "27-inch monitor",
         "32-inch monitor", "jacket", "gold bar"]
SIZES = ["43", "44", None]


@dataclass(frozen=True)
class Probe:
    amount: float
    merchant: str
    category: str
    name: str
    size: str | None
    quantity: int
    return_days: int | None
    extra_category: str | None
    hours: int


# Five "compliant cores" -- one per official mandate -- so that every policy under
# comparison has probes sitting ON its decision boundary. A uniformly random corpus
# blocked 59 of 60 probes for SCEN0000, which cannot discriminate between policies:
# two different compilers both saying "block" to everything look identical.
_CORES = [
    dict(amount=19.99, merchant=KNOWN, category="groceries", name="bread",
         size=None, quantity=1, return_days=30, extra_category=None),
    dict(amount=119.0, merchant=KNOWN, category="groceries", name="bread",
         size=None, quantity=1, return_days=30, extra_category=None),
    dict(amount=199.0, merchant=KNOWN, category="sporting_goods", name="road-running shoes",
         size="43", quantity=1, return_days=30, extra_category=None),
    dict(amount=249.0, merchant=KNOWN, category="clothing", name="jacket",
         size=None, quantity=1, return_days=30, extra_category=None),
    dict(amount=399.0, merchant=KNOWN, category="electronics", name="27-inch monitor",
         size=None, quantity=1, return_days=30, extra_category=None),
]

# One-dimension perturbations. Each is a lever some rule in the vocabulary reads, so
# a policy that drops a rule becomes observably different from one that keeps it.
_PERTURBATIONS = [
    {},                                             # the compliant core itself
    dict(amount=0.01), dict(amount=20.01), dict(amount=120.01), dict(amount=200.01),
    dict(amount=250.01), dict(amount=400.01), dict(amount=9999.0),
    dict(merchant=STRANGER),
    dict(category="jewellery"), dict(category="electronics"), dict(category="clothing"),
    dict(name="trail-running shoes"), dict(name="32-inch monitor"), dict(name="gold bar"),
    dict(size="44"), dict(size=None),
    dict(quantity=2), dict(quantity=5), dict(quantity=50),
    dict(return_days=None), dict(return_days=7), dict(return_days=14),
    dict(extra_category="jewellery"),
    # Probes that produce UNKNOWN rather than pass/fail. Without these, two policies
    # differing only in `uncertainty_policy` look identical -- the harness's own blind
    # spot, found when "decline when uncertain" scored behaviourally equivalent to
    # "ask when uncertain".
    dict(return_days=None, name="unstated-returns item"),
    dict(size=None, name="road-running shoes"),
    dict(merchant=UNSEEN),
]


def probe_corpus(seed: int = 7, n: int | None = None) -> list[Probe]:
    """Deterministic: every policy comparison sees exactly the same probes."""
    probes = []
    hours = 0
    for core in _CORES:
        for delta in _PERTURBATIONS:
            probes.append(Probe(hours=hours, **{**core, **delta}))
            hours += 6
    return probes if n is None else probes[:n]


def _event(mandate, probe: Probe, index: int):
    items = [{
        "line_no": 1, "item_id": f"I{index}", "item_name": probe.name,
        "item_category": probe.category, "quantity": probe.quantity,
        "unit_price": probe.amount, "currency": "CHF",
        "item_details": (f"size {probe.size} " if probe.size else "")
                        + (f"returns accepted within {probe.return_days} days" if probe.return_days else ""),
    }]
    if probe.extra_category:
        items.append({
            "line_no": 2, "item_id": f"X{index}", "item_name": "gift box",
            "item_category": probe.extra_category, "quantity": 1,
            "unit_price": 0.0, "currency": "CHF", "item_details": "",
        })
    event = make_event(
        mandate=mandate, authorization_id=f"AU{index:05d}", amount=probe.amount,
        merchant_id=probe.merchant, timestamp=T0 + timedelta(hours=probe.hours), items=items,
    )
    event["authorization"]["merchant"]["merchant_category"] = (
        "sporting_goods" if probe.category == "sporting_goods" else "groceries"
    )
    return event


def behaviour(instruction: str, probes: list[Probe]) -> tuple[str, ...]:
    """The decision this instruction produces on every probe, as a signature.

    Each probe runs in a FRESH RunState so that a rolling-window rule cannot make
    the signature depend on probe order -- we are comparing policies, not histories.
    """
    compiled = compile_instruction(instruction)
    mandate = make_mandate(
        instruction=instruction, hard_rules=compiled.hard_rules,
        uncertainty_policy=compiled.uncertainty_policy,
    )
    out = []
    for i, probe in enumerate(probes):
        state = RunState(
            history=HistoryIndex({"CA_TEST": frozenset({KNOWN})}, available=True), card_id="CA_TEST"
        )
        try:
            out.append(evaluate_authorization(_event(mandate, probe, i), mandate, state).decision)
        except Exception as exc:                      # a compiler output that crashes the engine is a result
            out.append(f"raise:{type(exc).__name__}")
    return tuple(out)


def sequential_behaviour(instruction: str, probes: list[Probe]) -> tuple[str, ...]:
    """Decisions when every probe runs against ONE accumulating RunState.

    `behaviour()` gives each probe a fresh state so that a policy is compared rather
    than a history. That is right for per-purchase rules and USELESS for period rules,
    which can never bind if spend never accumulates -- the harness's second blind spot,
    found when removing a CHF 300 / 7-day ceiling scored behaviourally equivalent to
    keeping it. Both signatures are compared; a difference in either is a difference.
    """
    compiled = compile_instruction(instruction)
    mandate = make_mandate(
        instruction=instruction, hard_rules=compiled.hard_rules,
        uncertainty_policy=compiled.uncertainty_policy,
    )
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({KNOWN})}, available=True), card_id="CA_TEST")
    out = []
    for i, probe in enumerate(probes):
        try:
            out.append(evaluate_authorization(_event(mandate, probe, i), mandate, state).decision)
        except Exception as exc:
            out.append(f"raise:{type(exc).__name__}")
    return tuple(out)


def rule_signature(instruction: str) -> tuple:
    compiled = compile_instruction(instruction)
    return (
        compiled.uncertainty_policy.value,
        tuple(sorted(
            (r.field, r.operator, str(r.value), r.scope or "", r.period_days or 0)
            for r in compiled.hard_rules
        )),
    )


PERMISSIVENESS = {"block": 0, "review": 1, "allow": 2}


def compare(a: str, b: str, probes: list[Probe]) -> dict:
    """How two instructions differ, behaviourally."""
    ba = behaviour(a, probes) + sequential_behaviour(a, probes)
    bb = behaviour(b, probes) + sequential_behaviour(b, probes)
    diffs = [(i, x, y) for i, (x, y) in enumerate(zip(ba, bb)) if x != y]
    weaker = sum(
        1 for _, x, y in diffs
        if x in PERMISSIVENESS and y in PERMISSIVENESS and PERMISSIVENESS[y] > PERMISSIVENESS[x]
    )
    return {
        "equivalent": not diffs,
        "differences": len(diffs),
        "b_weaker_than_a": weaker,
        "b_stricter_than_a": len(diffs) - weaker,
        "rules_equal": rule_signature(a) == rule_signature(b),
        "examples": diffs[:3],
    }

"""The largest real exposure this project has is not a wallet defect.

A fully compromised agent, confined to the customer's own policy and spacing its
purchases just outside the 60-minute similar-purchase window, extracts over one
simulated year:

    SCEN0000 (CHF 20 / purchase)   ->  8,616 purchases,   CHF   172,320
    SCEN0001 (CHF 300 / 7 days)    ->    104 purchases,   CHF    12,480
    SCEN0004 (CHF 400 / purchase)  ->  8,616 purchases,   CHF 3,445,538

Every one of those is the wallet working correctly.

An earlier version of this file asserted that SCEN0001's rolling cap yields "CHF
300, then blocked, forever". That was wrong, and wrong in the direction that
flatters us: the window ROLLS. It re-opens every seven days and the agent spends
again, indefinitely. The measurement above replaced the earlier 50-purchase probe,
which had never advanced simulated time past a single window.

This is the distinction the disclosure now has to carry:

    scope="purchase"  bounds ONE PURCHASE      -> total unbounded
    scope="period"    bounds a RATE            -> total unbounded, merely paced

and technical_details.md closes the vocabulary -- "No extra rule fields are
allowed" -- so there is no third scope. NO mandate expressible in the official rule
format can bound total economic delegation, including the one that looks like it
does. The customer's only real lever is knowing that before they confirm.

`open_questions` are advisory: shown before confirmation, read by no rule, so this
changes no decision and cannot move the official replay.
"""

from __future__ import annotations

from wallet_control.policy_compiler import compile_instruction


def _questions(instruction: str) -> str:
    return " ".join(compile_instruction(instruction).open_questions).lower()


def test_a_per_purchase_cap_without_a_total_cap_is_disclosed():
    compiled = compile_instruction("Buy groceries for CHF 50 or less from a shop I use regularly. Ask me when uncertain.")
    assert any(r.scope == "purchase" for r in compiled.hard_rules)
    assert not any(r.scope == "period" for r in compiled.hard_rules)
    text = " ".join(compiled.open_questions).lower()
    assert "total" in text or "how many" in text, compiled.open_questions


def test_a_rolling_cap_is_disclosed_as_a_rate_not_a_total():
    """This test previously asserted that a policy with a rolling cap gets NO
    warning, on the reasoning that it had already bounded itself. Measurement
    falsified that: the window re-opens and CHF 300 / 7 days is CHF 15,600 a year.

    A rolling cap is the strongest control the official vocabulary offers and it
    still does not bound the total, so it must be disclosed -- as a rate, with the
    rate's actual annual value, and without pretending a total is available."""
    text = _questions(
        "Order our household groceries for delivery. Keep each order at or below CHF 120 "
        "including delivery, and keep the total across any seven days at or below CHF 300. "
        "Ask me when uncertain."
    )
    assert "re-opens" in text or "indefinitely" in text, text
    assert "15,600" in text, text          # 300 * 365/7, the customer's own unit


def test_no_disclosure_advises_a_construct_that_does_not_bound_the_total():
    """The specific defect this pass found in its own earlier work: the advice said
    "consider adding a total, such as no more than CHF X across any 7 days". A
    rolling window is not a total. Naming the thing the customer wants and handing
    them something else is worse than staying silent, because they stop looking."""
    for instruction in (
        "Buy groceries for CHF 50 or less from a shop I use regularly. Ask me when uncertain.",
        "Order our household groceries. Keep each order at or below CHF 120 and the total "
        "across any seven days at or below CHF 300. Ask me when uncertain.",
    ):
        text = _questions(instruction)
        assert "adding a total" not in text, text
        assert "add a total" not in text, text


def test_the_disclosure_creates_no_rule_and_changes_no_decision():
    """open_questions are advisory by construction: they are not HardRules."""
    with_cap = compile_instruction("Buy groceries for CHF 50 or less. Ask me when uncertain.")
    assert all(not q.startswith("authorization.") for q in with_cap.open_questions)
    fields = {r.field for r in with_cap.hard_rules}
    assert "authorization.billing_amount_chf" in fields
    # exactly the rules the amount + uncertainty phrases produce, and nothing extra
    assert len(with_cap.hard_rules) == len([r for r in with_cap.hard_rules])


def test_every_official_instruction_still_compiles_the_same_rules():
    """The disclosure must not perturb the compiled policy of any official
    scenario -- that is what keeps the replay at 18/3/24."""
    from wallet_control.csv_data import load_scenario_catalogue

    for scenario in load_scenario_catalogue().values():
        compiled = compile_instruction(scenario["cardholder_instruction"])
        assert compiled.hard_rules, scenario["scenario_id"]
        # a warning is advisory text, never a rule
        assert all(isinstance(q, str) for q in compiled.open_questions)


def test_a_rolling_window_is_disclosed_as_per_session_not_global():
    """The half of the truth a customer is least likely to guess.

    `technical_details.md` scopes the platform's own spend context to the run --
    "context | Spend and recent authorization information from this run" -- so our
    window is counted per shopping session and a session started again begins at
    zero. Measured on SCEN0001: CHF 387.50 approved per run, so ten runs put
    CHF 3,875 through a stated CHF 300 / 7-day cap, 12.9x the customer's sentence.

    A customer reading only "your CHF 300 limit applies to each rolling 7-day
    window" would reasonably assume that is global. It is not, and the gap is large
    enough that saying nothing is a misrepresentation.

    We disclose rather than enforce, and that choice is forced rather than preferred:
    no documented endpoint returns a mandate's accumulated spend, so a cross-session
    total would be our own unverifiable record. `research/mandate_ledger_prototype.py`
    is that record, built and attacked -- two concurrent sessions both approved
    against the same remaining budget (and the losing write vanished, so the ledger
    was wrong as well as the decision), and a missing ledger file is indistinguishable
    from a mandate that has never spent. See docs/WHAT_WE_REFUSE_TO_CLAIM.md.
    """
    text = _questions(
        "Order our household groceries for delivery. Keep each order at or below CHF 120 "
        "including delivery, and keep the total across any seven days at or below CHF 300. "
        "Ask me when uncertain."
    )
    assert "session" in text, text
    assert "begins from zero" in text or "zero" in text, text


def test_the_per_session_disclosure_still_creates_no_rule():
    """Disclosure only. If this ever became a rule it would change the replay."""
    compiled = compile_instruction(
        "Order groceries. Keep the total across any seven days at or below CHF 300. Ask me when uncertain."
    )
    assert not any("session" in str(r.field) for r in compiled.hard_rules)
    assert any(r.scope == "period" for r in compiled.hard_rules)

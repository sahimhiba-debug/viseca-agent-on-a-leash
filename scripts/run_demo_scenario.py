#!/usr/bin/env python3
"""Runs and narrates the new, clearly-synthetic R&D demo scenario
(`wallet_control.demo_scenario`) -- kept entirely separate from the official
45-event replay data. See the module docstring for the full story this walks
through: prompt injection -> compromised re-quote -> drift-detected REVIEW ->
customer decline -> legitimate continuation -> narrow payment authority ->
final execution boundary check.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from wallet_control.demo_scenario import run_demo_scenario  # noqa: E402


def main() -> int:
    result = run_demo_scenario()
    print("R&D demo scenario: DEMO_RND_0001 -- 'The redirected re-quote'")
    print(f'  customer instruction: "{result.mandate.instruction}"')
    print(f"  hard_rules: {[r.as_dict() for r in result.mandate.hard_rules]}")
    print(f"  uncertainty_policy: {result.mandate.uncertainty_policy.value}")
    print()

    for i, step in enumerate(result.steps, 1):
        auth = step.event["authorization"]
        r = step.result
        print(f"--- Step {i}: {step.label} ---")
        print(f"  authorization_id={auth['authorization_id']}  merchant={auth['merchant']['merchant_name']} ({auth['merchant']['merchant_id']})  amount=CHF {auth['billing_amount_chf']}")
        if auth["related_authorization_id"]:
            print(f"  related_authorization_id={auth['related_authorization_id']} (status at submission: {auth['related_authorization_status']})")
        print(f"  DECISION: {r.decision.upper()}  intervention={r.intervention}  reason_codes={list(r.reason_codes)}")
        print("  policy checks (customer's own mandate):")
        for e in r.rule_evaluations:
            if e.source == "customer":
                print(f"    [{e.outcome:7s}] {e.rule.field}: {e.detail}")
        print("  wallet safety checks:")
        for e in r.rule_evaluations:
            if e.source == "safety":
                print(f"    [{e.outcome:7s}] {e.rule.field}: {e.detail}")
        if r.drift is not None:
            print(f"  DRIFT vs {r.drift.reference_authorization_id}: classification={r.drift.classification}")
            for f in r.drift.changed_fields:
                print(f"    {f.field}: {f.before!r} -> {f.after!r}")
        if r.policy_verdict is not None or r.security_verdict is not None:
            print(f"  policy_verdict={r.policy_verdict}  security_verdict={r.security_verdict}")
        if r.payment_authority is not None:
            pa = r.payment_authority
            print(f"  PAYMENT AUTHORITY issued: ceiling=CHF {pa.amount_ceiling_chf}  merchant={pa.merchant_id}  expires_at={pa.expires_at.isoformat()}")
        print()

    if result.resolution is not None:
        print("--- Human resolution ---")
        print(f"  AU_DEMO_0002 resolved by customer -> {result.resolution.decision.upper()}")
        print()

    if result.legitimate_charge is not None:
        print("--- Final execution boundary check ---")
        print(f"  Legitimate charge for CHF {result.legitimate_charge.amount_chf} against the narrow authority: EXECUTED ({result.legitimate_charge.charge_id})")
        if result.tampered_charge_error:
            print(f"  Tampered attempt to charge CHF 999 against the SAME authority: REFUSED")
            print(f"    reason: {result.tampered_charge_error}")
        else:
            print("  WARNING: tampered charge attempt was not refused -- this would be a real finding")
            return 1

    print()
    print("Demonstrated: the shopping agent was redirected by a merchant-supplied prompt")
    print("injection to an unfamiliar storefront; the wallet's drift analysis flagged the")
    print("re-quote as an unrelated-merchant change (not a price correction) and routed it")
    print("to the customer, who declined it; the legitimate purchase then proceeded under a")
    print("narrow, single-use payment authority that refused a subsequent, larger charge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

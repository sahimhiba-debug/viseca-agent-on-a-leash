"""Phases 17-18: a stateful model that generates adversarial OPERATION SEQUENCES
and asserts every security invariant after every single operation.

The motivation is empirical, not stylistic. Of the twelve vulnerabilities found
across the last three passes, almost none were reachable by exercising one field
in isolation -- they needed an ordering: approve then revoke, charge then crash,
revoke then re-deliver, resolve then mutate. Single-request tests cannot reach
those, and neither can a corpus of fixed cases once the interesting sequence is
longer than the cases someone thought to write down.

Hypothesis drives the operations and shrinks any counterexample to a minimal
sequence, so a failure arrives as the shortest reproduction rather than a
thousand-step log.

The invariants are checked after EVERY step, so a violation is attributed to the
operation that caused it rather than discovered at the end.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule
from hypothesis import strategies as st

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.mandate import HardRule
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, ResolutionError, RunState

MERCHANT = "ME_TEST_0001"
OTHER_MERCHANT = "ME_TEST_0002"
CEILING = Decimal("500")


class WalletSecurityModel(RuleBasedStateMachine):
    """Drives the real engine, state and payment boundary through random sequences."""

    @initialize()
    def setup(self) -> None:
        self.mandate = make_mandate(hard_rules=[
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=int(CEILING), currency="CHF", scope="purchase")
        ])
        self.state = RunState(
            history=HistoryIndex({"CA_TEST": frozenset({MERCHANT, OTHER_MERCHANT})}, available=True),
            card_id="CA_TEST",
        )
        self.clock = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        # Modelled faithfully after live_worker: a checkpoint is written after each
        # decision/resolution, and the payment boundary is given a persist hook so
        # consumption becomes durable before money is treated as moved. Restoring
        # uses THIS checkpoint, never a fresh in-memory snapshot taken at the
        # convenient moment -- that shortcut is exactly what hid V10.
        self.checkpoint = json.dumps(self.state.to_snapshot())
        self.psp = self._make_psp()
        self.operations = 0
        self.next_id = 0
        self.seen: list[str] = []
        # Shadow ledger kept by the MODEL, independent of the implementation.
        self.charged: dict[str, Decimal] = {}
        self.ever_consumed: set[str] = set()
        self.ever_revoked: set[str] = set()

    def _make_psp(self) -> MockPSP:
        return MockPSP(self.state, clock=lambda: self.clock, persist=self._save_checkpoint)

    def _save_checkpoint(self) -> None:
        self.checkpoint = json.dumps(self.state.to_snapshot())

    def _new_id(self) -> str:
        self.next_id += 1
        return f"AU{self.next_id}"

    def _event(self, authorization_id: str, amount: float, merchant: str):
        event = make_event(mandate=self.mandate, authorization_id=authorization_id, amount=amount, merchant_id=merchant)
        event["authorization"]["timestamp"] = self.clock.isoformat().replace("+00:00", "Z")
        return event

    # ---- operations --------------------------------------------------------------

    @rule(amount=st.floats(min_value=1.0, max_value=900.0, allow_nan=False, allow_infinity=False),
          merchant=st.sampled_from([MERCHANT, OTHER_MERCHANT]))
    def authorize(self, amount: float, merchant: str) -> None:
        authorization_id = self._new_id()
        evaluate_authorization(self._event(authorization_id, round(amount, 2), merchant), self.mandate, self.state)
        self._save_checkpoint()
        self.seen.append(authorization_id)
        self.operations += 1

    @precondition(lambda self: bool(self.seen))
    @rule(which=st.integers(min_value=0, max_value=50),
          amount=st.floats(min_value=1.0, max_value=900.0, allow_nan=False, allow_infinity=False),
          merchant=st.sampled_from([MERCHANT, OTHER_MERCHANT]))
    def redeliver_possibly_mutated(self, which: int, amount: float, merchant: str) -> None:
        """A re-delivery of an id we have seen, sometimes with mutated facts."""
        authorization_id = self.seen[which % len(self.seen)]
        evaluate_authorization(self._event(authorization_id, round(amount, 2), merchant), self.mandate, self.state)
        self._save_checkpoint()
        self.operations += 1

    @precondition(lambda self: bool(self.seen))
    @rule(which=st.integers(min_value=0, max_value=50), answer=st.sampled_from(["allow", "block"]))
    def human_resolves(self, which: int, answer: str) -> None:
        authorization_id = self.seen[which % len(self.seen)]
        try:
            resolve_authorization(authorization_id, answer, self.state, resolved_at=self.clock, mandate=self.mandate)
            self._save_checkpoint()
        except ResolutionError:
            pass  # refusing is a legitimate outcome; the invariants still must hold
        self.operations += 1

    @rule()
    def customer_revokes(self) -> None:
        for authorization_id in self.state.revoke_outstanding_authorities():
            self.ever_revoked.add(authorization_id)
        self._save_checkpoint()
        self.operations += 1

    @precondition(lambda self: bool(self.seen))
    @rule(which=st.integers(min_value=0, max_value=50),
          amount=st.floats(min_value=0.5, max_value=900.0, allow_nan=False, allow_infinity=False),
          merchant=st.sampled_from([MERCHANT, OTHER_MERCHANT]))
    def agent_attempts_charge(self, which: int, amount: float, merchant: str) -> None:
        authorization_id = self.seen[which % len(self.seen)]
        requested = Decimal(str(round(amount, 2)))
        try:
            record = self.psp.charge(
                charge_id=f"CH{len(self.charged)}-{authorization_id}",
                authorization_id=authorization_id,
                amount_chf=requested,
                merchant_id=merchant,
            )
        except PaymentError:
            return
        self.charged[authorization_id] = self.charged.get(authorization_id, Decimal("0")) + record.amount_chf
        self.ever_consumed.add(authorization_id)
        self.operations += 1

    @rule(minutes=st.integers(min_value=1, max_value=60))
    def time_passes(self, minutes: int) -> None:
        self.clock += timedelta(minutes=minutes)

    @rule()
    def crash_and_restart(self) -> None:
        """Round-trip the run through its checkpoint, as a restart would."""
        self.state = RunState.from_snapshot(json.loads(self.checkpoint), self.state.history)
        self.psp = self._make_psp()
        self.operations += 1

    # ---- invariants, checked after every operation --------------------------------

    @invariant()
    def no_authorization_is_charged_twice(self) -> None:
        for authorization_id, total in self.charged.items():
            stored = self.state.get_stored_decision(authorization_id)
            assert stored is not None, f"{authorization_id} charged with no stored decision"
            assert total <= stored.billing_amount_chf, (
                f"{authorization_id}: charged CHF {total} against an approved CHF {stored.billing_amount_chf}"
            )

    @invariant()
    def only_approved_authorizations_are_charged(self) -> None:
        for authorization_id in self.charged:
            stored = self.state.get_stored_decision(authorization_id)
            assert stored.decision == "allow", f"{authorization_id} charged while {stored.decision}"

    @invariant()
    def consumption_is_monotonic(self) -> None:
        """Once executed, an authority never returns to unexecuted -- including
        across a restart, which is exactly where this broke before (V8/V10)."""
        for authorization_id in self.ever_consumed:
            authority = self.state.get_authority(authorization_id)
            if authority is not None:
                assert authority.consumed_at is not None, f"{authorization_id} un-consumed itself"

    @invariant()
    def revocation_is_monotonic(self) -> None:
        for authorization_id in self.ever_revoked:
            authority = self.state.get_authority(authorization_id)
            if authority is not None:
                assert authority.revoked, f"{authorization_id} un-revoked itself"

    @invariant()
    def a_revoked_or_consumed_authority_is_never_chargeable(self) -> None:
        for authorization_id, authority in list(self.state._authorities.items()):
            if not (authority.revoked or authority.consumed_at is not None):
                continue
            probe = MockPSP(self.state, clock=lambda: self.clock)
            try:
                probe.charge(
                    charge_id=f"PROBE-{authorization_id}",
                    authorization_id=authorization_id,
                    amount_chf=Decimal("0.01"),
                    merchant_id=authority.merchant_id,
                )
            except PaymentError:
                continue
            raise AssertionError(f"{authorization_id} was chargeable while revoked/consumed")

    @invariant()
    def an_authority_only_ever_exists_for_an_allow(self) -> None:
        for authorization_id, authority in list(self.state._authorities.items()):
            stored = self.state.get_stored_decision(authorization_id)
            assert stored is not None and stored.decision == "allow", (
                f"authority exists for {authorization_id} whose decision is "
                f"{None if stored is None else stored.decision}"
            )

    @invariant()
    def approved_spend_never_exceeds_the_sum_of_approvals(self) -> None:
        expected = sum(
            (d.billing_amount_chf for d in self.state._decisions.values() if d.decision == "allow" and d.counted_in_spend),
            Decimal("0"),
        )
        assert self.state.total_approved_spend_chf() == expected

    @invariant()
    def every_charge_went_to_the_approved_merchant(self) -> None:
        for charge_id, record in list(self.psp._charges.items()):
            stored = self.state.get_stored_decision(record.authorization_id)
            if stored is not None:
                assert record.merchant_id == stored.merchant_id, (
                    f"{charge_id} paid {record.merchant_id} for an authorization approved at {stored.merchant_id}"
                )


TestWalletSecurityModel = WalletSecurityModel.TestCase
TestWalletSecurityModel.settings = settings(max_examples=300, stateful_step_count=30, deadline=None)

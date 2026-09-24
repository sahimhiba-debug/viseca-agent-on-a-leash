"""The brain is replaceable; the authority is not (research/brains.py).

The two real-model brains need network keys and are recorded in
docs/REAL_MODEL_PLANNER.md. The offline brains run here, on every commit.
"""

from __future__ import annotations

from research import brains


def test_no_brain_gets_a_purchase_approved_that_breaks_the_customers_sentence():
    for name, make in (("deterministic", lambda ep: (brains.sa.DETERMINISTIC, None)),
                       ("adversarial", brains._adversarial)):
        tally = brains.run_brain(name, make, brains.Tally(name))
        assert tally.unauthorized == [], (name, tally.unauthorized)
        assert tally.wallet_allowed > 0          # it did buy things: not a wallet that refuses all


def test_the_referee_is_not_blind():
    """Negative control: the same adversarial proposals, recorded as if a wallet had
    approved every one, must show violations. A referee stuck at zero proves nothing."""
    control = brains.run_brain("control", brains._adversarial, brains.Tally("control"), yes_wallet=True)
    assert len(control.unauthorized) >= 10


def test_the_referee_reads_the_sentence_not_the_compiler():
    """It must not import the compiler or the engine: agreeing with them would be circular."""
    import inspect
    source = inspect.getsource(brains.referee)
    assert "compile_instruction" not in source and "evaluate_authorization" not in source
    assert set(brains.SENTENCE) == {e.key for e in brains.B.episodes()}

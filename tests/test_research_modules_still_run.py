"""Every research module must still run, because every one of them is a CLAIM.

WHY THIS EXISTS. `research/lost_state.py` -- the module that reproduces the CHF 900
rolling-window finding -- sat broken for part of a session after a field it used was
renamed. Nothing noticed. The gate that was supposed to notice ran it and piped the
output through `tail`, which shows the last few lines whether or not the process
died, so a traceback on stderr and a clean run looked identical.

That is a tooling failure, not a code failure, and it is the more dangerous of the
two: these modules are where this repository's numbers come from. A number whose
generator no longer runs is worse than no number, because it still appears in the
documents. "Every important numerical claim must be reproducible" is only true if
something checks that it still reproduces.

So: run them all, in a subprocess, and require a zero exit. ~5 seconds for the whole
set. They are analysis rather than enforcement, so a non-zero exit here is not a
security failure -- it means a claim has gone stale and a document may now be lying.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"

MODULES = sorted(
    path.stem for path in RESEARCH.glob("*.py")
    if path.stem != "__init__"
)


def test_there_are_research_modules_to_check():
    """If the glob ever finds nothing, every test below would pass vacuously."""
    assert len(MODULES) >= 20, MODULES


@pytest.mark.parametrize("module", MODULES)
def test_the_module_runs_to_completion(module):
    result = subprocess.run(
        [sys.executable, "-m", f"research.{module}"],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"research/{module}.py exits {result.returncode}; the claims it produces are "
        f"no longer reproducible.\n\n{result.stderr[-2000:]}")

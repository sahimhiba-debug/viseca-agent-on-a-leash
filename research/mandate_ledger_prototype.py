"""PROTOTYPE, not runtime. A mandate-scoped approved-spend ledger.

Research question: the customer writes "keep the total across any seven days at or
below CHF 300". Our wallet enforces that per RUN, because `technical_details.md`
scopes the platform's own spend context to the run ("context | Spend and recent
authorization information from this run"). Two runs under one mandate therefore get
CHF 300 each.

Measured exposure: SCEN0001 approves CHF 387.50 per run against a stated CHF 300 /
7 days. Ten runs is CHF 3,875 -- 12.9x the customer's sentence.

This prototype asks whether binding the window to the MANDATE instead of the RUN
is (a) effective, (b) safe, and (c) affordable. It is deliberately outside
`src/wallet_control/` so that nothing in the runtime can import it until that
question is answered.

It is append-only and monotone, like `RunState._approved_spend`, because the
architecture decision that rejected a "single global security ledger" rejected a
shared MUTABLE record -- six vulnerabilities in this project came from those.
Append-only is a different object.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path


@dataclass
class MandateLedger:
    """Approved spend for one mandate, across every run it has ever authorized."""

    mandate_id: str
    path: Path | None = None
    _spend: list[tuple[datetime, Decimal]] = field(default_factory=list)

    @classmethod
    def load(cls, mandate_id: str, directory: Path) -> "MandateLedger":
        path = directory / f"{mandate_id}.json"
        ledger = cls(mandate_id=mandate_id, path=path)
        if path.exists():
            raw = json.loads(path.read_text())
            if raw.get("mandate_id") != mandate_id:
                raise ValueError(f"ledger at {path} belongs to {raw.get('mandate_id')!r}, not {mandate_id!r}")
            ledger._spend = [(datetime.fromisoformat(t), Decimal(a)) for t, a in raw["spend"]]
        return ledger

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"mandate_id": self.mandate_id,
                   "spend": [[t.isoformat(), str(a)] for t, a in self._spend]}
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent))
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(payload))
        os.replace(tmp, self.path)          # atomic; never a half-written ledger

    def record_approval(self, when: datetime, amount: Decimal) -> None:
        self._spend.append((when, amount))
        self._persist()

    def peak_window_spend_chf(self, as_of: datetime, amount: Decimal, period_days: int) -> Decimal:
        """Identical arithmetic to `RunState.peak_window_spend_chf`, over a wider set.

        Every window CONTAINING the candidate, not the one ending at it -- the same
        containment invariant, since purchases still arrive out of chronological order.
        """
        trial = [*self._spend, (as_of, amount)]
        window = timedelta(days=period_days)
        return max(
            sum((a for ts, a in trial if end - window < ts <= end), Decimal("0"))
            for end, _ in trial
        )

    def total(self) -> Decimal:
        return sum((a for _, a in self._spend), Decimal("0"))

    def __len__(self) -> int:
        return len(self._spend)

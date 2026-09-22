"""Does the read-back measure the COMPILER, or does it just know English?

RESEARCH APPARATUS. Never imported by `src/wallet_control/`.

THE OBJECTION WORTH TAKING SERIOUSLY

The read-back reports which of a customer's words changed the compiled policy. A
fair reviewer asks: is that a property of the MECHANISM, or did it quietly encode
what our particular regex compiler happens to know? And, behind that, the real
question for a product:

    "A serious version of this would compile with a language model. Would any of
     this survive that?"

THE TEST

Point the same read-back at three compilers with deliberately different vocabularies
and see whether it reports three different things. If it measures the compiler, the
struck-through words must move when the compiler moves. If it reports the same
sentence the same way regardless, it is measuring English and is worthless.

    NARROW   understands only "CHF N" -- nothing else at all
    SHIPPED  the real `policy_compiler`
    WIDER    the shipped one, plus "send back within N days", which is exactly the
             phrase the shipped one loses silently

WHY THIS ALSO ANSWERS THE MODEL QUESTION

The probe is one deletion per word and a re-compile. It never inspects the
compiler's internals, so a model-based compiler works the same way at the cost of
one call per word -- ~40 calls for a real mandate, paid once at drafting time,
parallelisable. Nothing here is regex-specific; WIDER is a different compiler and
the mechanism is unchanged. That is a demonstration of the mechanism's independence,
not evidence about any model: no model was called, and none is claimed.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "src"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from wallet_control.mandate import HardRule, UncertaintyPolicy      # noqa: E402
from wallet_control.policy_compiler import compile_instruction      # noqa: E402
from wallet_control.unconsumed import marks                         # noqa: E402

SENTENCE = ("Order our household groceries at or below CHF 120, and only buy things "
            "I can send back within 14 days.")


@dataclass
class TinyCompiled:
    """The smallest shape `unconsumed._signature` reads. Anything with these five
    attributes is a compiler as far as the read-back is concerned."""

    hard_rules: list[HardRule] = field(default_factory=list)
    uncertainty_policy: UncertaintyPolicy = UncertaintyPolicy.ASK
    guidance: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    unsupported_restrictions: list[str] = field(default_factory=list)


_AMOUNT = re.compile(r"CHF\s*([\d.]+)", re.IGNORECASE)
_SEND_BACK = re.compile(r"send\s+(?:it\s+)?back\s+(?:with)?in\s+(\d+)\s*days?", re.IGNORECASE)


def narrow_compiler(instruction: str) -> TinyCompiled:
    """Understands one thing: a CHF figure is a per-order ceiling. Nothing else."""
    match = _AMOUNT.search(instruction)
    if not match:
        return TinyCompiled()
    return TinyCompiled(hard_rules=[HardRule(
        field="authorization.billing_amount_chf", operator="<=",
        value=float(match.group(1)), currency="CHF", scope="purchase")])


def wider_compiler(instruction: str) -> Any:
    """The shipped compiler plus ONE phrase it loses silently. Nothing else changes,
    so any difference in the read-back is attributable to that phrase alone."""
    compiled = compile_instruction(instruction)
    match = _SEND_BACK.search(instruction)
    if not match:
        return compiled
    already = any(r.field == "order.return_window_days" for r in compiled.hard_rules)
    if already:
        return compiled
    return TinyCompiled(
        hard_rules=list(compiled.hard_rules) + [HardRule(
            field="order.return_window_days", operator=">=", value=int(match.group(1)))],
        uncertainty_policy=compiled.uncertainty_policy,
        guidance=list(compiled.guidance),
        open_questions=list(compiled.open_questions),
        unsupported_restrictions=list(compiled.unsupported_restrictions),
    )


COMPILERS = {
    "NARROW  (CHF only)": narrow_compiler,
    "SHIPPED (policy_compiler)": compile_instruction,
    "WIDER   (+ 'send back within N days')": wider_compiler,
}


def read(instruction: str = SENTENCE) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for label, compiler in COMPILERS.items():
        found = marks(instruction, compiler)
        out[label] = {
            "consumed": [m.word for m in found if m.kind == "consumed"],
            "inert": [m.word for m in found if m.kind == "inert"],
            "obstructive": [m.word for m in found if m.kind == "obstructive"],
        }
    return out


def main() -> int:
    print("DOES THE READ-BACK MEASURE THE COMPILER, OR JUST KNOW ENGLISH?\n")
    print(f'  One sentence: "{SENTENCE}"\n')
    print("  Three compilers with deliberately different vocabularies. If the")
    print("  mechanism measures the compiler, the struck-through words must move.\n")
    result = read()
    for label, marked in result.items():
        rendered = " ".join(
            w if w in marked["consumed"] else (f"<{w}>" if w in marked["obstructive"] else f"~{w}~")
            for w in SENTENCE.split())
        print(f"  {label}")
        print(f"      {rendered}")
        print(f"      read {len(marked['consumed'])} word(s), ignored {len(marked['inert'])}\n")

    signatures = {label: tuple(m["consumed"]) for label, m in result.items()}
    distinct = len(set(signatures.values()))
    print(f"  {distinct} distinct read-backs from {len(signatures)} compilers.")
    if distinct == len(signatures):
        print("  The mechanism measures the compiler, not the sentence. A model-based")
        print("  compiler is another entry in this table, at one call per word.")
    else:
        print("  TWO COMPILERS READ THE SAME -- the mechanism is not discriminating,")
        print("  and the claim in unconsumed.py is wrong.")
    print("\n  legend: plain = changed a rule   ~word~ = changed nothing   "
          "<word> = removing it creates one")
    print("\n  No model was called. WIDER is a hand-written compiler; this shows the")
    print("  mechanism is independent of the compiler, and claims nothing about LLMs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""When a sentence has two defensible readings, find the purchase that separates them.

THE PROBLEM WITH TELLING SOMEONE THEIR SENTENCE IS AMBIGUOUS

The compiler already detects ambiguity and explains it in prose: "the instruction
mentions more than one per-order amount; the smallest was used defensively".
That is honest and it is nearly useless, because it asks the customer to imagine a
consequence. People do not audit prose about hypothetical purchases. They agree to
it.

THE IDEA

Do not describe the ambiguity. **Find the purchase it changes.**

Compile the sentence twice -- once as the compiler read it, once as the other
defensible reading -- then search the real catalogue, through the real engine, for
a basket the two policies judge DIFFERENTLY. That basket is a *witness*: concrete
proof that the sentence is underdetermined, and the only question a customer can
actually answer.

    "Order groceries, under CHF 120."

    reading A (as compiled)   each order must be strictly under CHF 120
    reading B (also defensible) CHF 120 itself is fine

    WITNESS: a basket costing exactly CHF 120.00
             A refuses it. B allows it. Which did you mean?

A policy is a HYPOTHESIS about what someone meant. This is the experiment that
distinguishes two hypotheses -- and the customer is the only instrument that can
read the result.

WHAT THIS IS NOT
    Not a confidence score. Not an LLM asked to rate its own certainty. The
    witness is found by running both policies against real purchases in the real
    engine; if no purchase separates them, the ambiguity is immaterial and the
    customer is not bothered with it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# The mechanism lives in the RUNTIME, not here. It began in this file, and the
# runtime-boundary test refused to let `api.py` import it -- correctly, even as a
# guarded local import. That refusal was the right answer to the wrong question:
# this is not apparatus, it is a product feature shown to the customer before they
# confirm. It moved to `wallet_control/ambiguity.py` and this file is now the
# corpus and the CLI over it, so there is one implementation rather than two that
# agree today.
from wallet_control.ambiguity import READINGS, find_witness, witnesses  # noqa: E402,F401

CORPUS = [
    "Order our household groceries, under CHF 120.",
    "Order our household groceries, at or below CHF 120.",
    "Order our household groceries, up to CHF 250 per week.",
    "Order our household groceries, at or below CHF 120, from a shop I have used before.",
    "Buy the 27-inch monitor I chose, for CHF 400 or less.",
]


def main() -> int:
    print("WHERE DOES A SENTENCE STOP DETERMINING THE ANSWER?\n")
    print("  Two defensible readings, and the purchase that separates them.\n")
    found = 0
    for instruction in CORPUS:
        print(f"  \u201c{instruction}\u201d")
        hits = witnesses(instruction)
        for witness in hits:
            found += 1
            label_a, label_b = witness["labels"]
            repeats = witness["repeats"]
            what = (f"a basket of CHF {witness['amount']:.2f}" if repeats == 1
                    else f"{repeats} purchases of CHF {witness['amount']:.2f}")
            print(f"      {witness['reading'].question}")
            print(f"        {witness['count']} of {witness['universe']} purchases are "
                  f"decided differently. The cheapest:")
            print(f"        WITNESS: {what}")
            print(f"          read as \u201c{label_a}\u201d  \u2192  {witness['verdict_a'].upper()}")
            print(f"          read as \u201c{label_b}\u201d  \u2192  {witness['verdict_b'].upper()}")
        if not hits:
            print("      no reading changes any purchase we can construct \u2014 unambiguous "
                  "where it matters")
        print()
    print(f"  {found} witness(es) found across {len(CORPUS)} sentences. The silence on the")
    print("  others is the point: a disambiguator that fires on clear language teaches")
    print("  people to click through it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

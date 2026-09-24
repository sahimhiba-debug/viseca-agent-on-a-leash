"""A generated corpus aimed at SILENT SEMANTIC LOSS in the policy compiler.

RESEARCH APPARATUS. Never imported by `src/wallet_control/`.

The question is not "how many instructions compile". It is: when a customer states
a restriction, does the wallet either ENFORCE it or SAY that it cannot? Losing it
without a word is the failure; everything else is survivable.

WHERE THE EXPECTED MEANING COMES FROM. Not from the model. `sample_specs()` draws each
instruction's meaning in code, before any model sees it: the ceiling and its
notation, the period, the shop familiarity, the return terms, one-off or recurring,
the language. The model (OpenAI) is asked only to PHRASE that spec as a customer
would. So the model is a paraphraser, never an oracle, and a model that drops a
constraint while phrasing shows up as a disagreement to inspect, never as a pass.
Every text is stored with its spec, so grading is offline and reproducible:

    python3 research/generated_corpus.py            # grade the committed corpus
    OPENAI_API_KEY=... python3 research/generated_corpus.py --generate 240
    python3 research/generated_corpus.py --holdout  # the held-out corpus

The generator is not independent of our framing: it only produces the kinds of
restriction this file thought to ask for. See docs/GENERATED_CORPUS.md.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wallet_control.policy_compiler import compile_instruction  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "corpora" / "generated_instructions.json"
# HELD OUT: generated AFTER the compiler was fixed against CORPUS, with another seed
# and another voice, and graded without any further change to the compiler. Its
# numbers are the honest ones; CORPUS's are what the fixes were fitted to.
HOLDOUT = Path(__file__).resolve().parent / "corpora" / "generated_instructions_holdout.json"
# BLIND: generated after BOTH rounds of fixes, graded once, and reported as found.
BLIND = Path(__file__).resolve().parent / "corpora" / "generated_instructions_blind.json"
# FINAL: generated after the third round of fixes and reported as found; nothing in the
# compiler was changed in response to it.
FINAL = Path(__file__).resolve().parent / "corpora" / "generated_instructions_final.json"
STYLES = {
    "tuning": "Vary the wording naturally; do not copy the fact list verbatim.",
    "holdout": ("Write it the way a busy person types a quick note or text message to an assistant: "
                "terse, informal, possibly out of order, with abbreviations if natural."),
    "blind": ("Write it as a chatty, slightly rambling message with some irrelevant context (who it is "
              "for, why), the way a real customer might explain it to a new assistant."),
    "final": ("Write it as a short, polite, formal email to a personal assistant, with a greeting and "
              "a sign-off; facts may appear in any order and may be split across sentences."),
}
GENERATOR_MODEL = "gpt-4.1"
PROMPT_VERSION = 1

NOTATIONS = ["CHF {n}", "{n} CHF", "{n}.-", "Fr. {n}", "{n} francs", "{n} Swiss francs", "{n}"]
LIMIT_WORDS = {"no more than": "<=", "max": "<=", "at most": "<=", "up to": "<=", "capped at": "<=",
               "limited to": "<=", "not exceeding": "<=", "no higher than": "<=", "nothing over": "<=",
               "under": "<", "below": "<"}
SCOPES = {"per order": None, "per week": 7, "across any seven days": 7, "per month": 30, "in total": "total"}
RETURNS = [None, "returnable within 14 days", "returnable for at least 30 days", "no final-sale items",
           "must be refundable"]
PURPOSES = ["one-off", "recurring", "neutral"]
CATEGORIES = {"groceries": "household groceries", "electronics": "a 27-inch monitor",
              "clothing": "a winter jacket", "sporting_goods": "road-running shoes"}
LANGUAGES = ["English"] * 6 + ["French", "German", "Italian", "mixed English and French"]
POLICIES = {"ask": "ask me when unsure", "decline": "decline when unsure", "approve": "approve when unsure"}


@dataclass
class Spec:
    id: str
    amount: int
    notation: str
    limit_word: str
    scope: str
    familiar: bool
    returns: str | None
    purpose: str
    category: str
    language: str
    policy: str

    def english(self) -> str:
        """The spec as plain English facts for the paraphraser, not as a template sentence."""
        amount = self.notation.format(n=f"{self.amount:,}".replace(",", "'"))
        facts = [f"buy {CATEGORIES[self.category]}",
                 f"spending limit: {self.limit_word} {amount} {self.scope}"]
        if self.familiar:
            facts.append("only from a shop the customer has bought from before")
        if self.returns:
            facts.append(self.returns)
        facts.append({"one-off": "this is a one-time purchase of a single item the customer already chose",
                      "recurring": "this is a recurring order, placed every week",
                      "neutral": "say nothing about how often"}[self.purpose])
        facts.append(POLICIES[self.policy])
        return "; ".join(facts)


def sample_specs(n: int, seed: int = 20260924) -> list[Spec]:
    rng = random.Random(seed)
    specs = []
    for i in range(n):
        category = rng.choice(list(CATEGORIES))
        specs.append(Spec(
            id=f"G{i:04d}", amount=rng.choice([40, 120, 150, 400, 1200]),
            notation=rng.choice(NOTATIONS), limit_word=rng.choice(list(LIMIT_WORDS)),
            scope=rng.choice(list(SCOPES)), familiar=rng.random() < 0.5,
            returns=rng.choice(RETURNS),
            purpose="recurring" if category == "groceries" and rng.random() < 0.6 else rng.choice(PURPOSES),
            category=category, language=rng.choice(LANGUAGES), policy=rng.choice(list(POLICIES))))
    return specs


PROMPT = """You write test data for a payment wallet. Phrase the facts below as ONE instruction a
customer would type to their shopping agent, in {language}. Keep EVERY fact, including the
exact amount and its notation "{notation_example}". Do not add restrictions that are not listed.
{style}

Facts: {facts}

Reply with the instruction only."""


def generate(n: int, *, path: Path = CORPUS, seed: int = 20260924, style: str = "tuning") -> None:
    from research.model_planner import openai_completer
    complete = openai_completer(model=GENERATOR_MODEL, max_tokens=160, temperature=0.9)
    existing = {e["spec"]["id"]: e for e in load(path)}
    for spec in sample_specs(n, seed=seed):
        if spec.id in existing:
            continue
        text = complete(PROMPT.format(language=spec.language, facts=spec.english(), style=STYLES[style],
                                      notation_example=spec.notation.format(n=spec.amount))).strip().strip('"')
        existing[spec.id] = {"spec": asdict(spec), "text": text}
        print(spec.id, text[:110], flush=True)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"generator": GENERATOR_MODEL, "prompt_version": PROMPT_VERSION, "seed": seed,
                                "style": STYLES[style], "prompt": PROMPT, "entries": list(existing.values())},
                                 ensure_ascii=False, indent=1))


def load(path: Path = CORPUS) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text())["entries"]


# ---------------------------------------------------------------- grading
# Per constraint: ENFORCED, ENFORCED_LOOSER (weakened), DISCLOSED, or SILENT_LOSS.
# Separately: STRENGTHENED, a rule the spec did not ask for, or a stricter value.

# Read by a person: the paraphraser changed the meaning, and the compiler read the TEXT
# correctly. Listed rather than silently dropped, so the drift itself stays visible.
PARAPHRASE_DRIFT = {
    "G0203": "spec: at most 400.- per week; the text says 'each purchase does not exceed 400.-'",
}
PARAPHRASE_DRIFT_FINAL = {
    "G0067": "spec: no more than 40.- per week; the text says 'each order does not exceed 40.-'",
}


RELEVANT = {   # phrases of the compiler's own warnings, per kind of restriction
    "amount": ("no spending ceiling", "OVERALL TOTAL", "period of time", "You wrote a TOTAL"),
    "familiar": ("shop you have used before",),
    "returns": ("returns", "return-window", "returnability"),
    "one_off": ("specific number of items", "one-off errand", "one-off purchase"),
}


def grade(entry: dict) -> dict:
    s = Spec(**entry["spec"])
    c = compile_instruction(entry["text"])
    rules = {r.field: r for r in c.hard_rules}
    warnings = " ".join(c.unsupported_restrictions)
    foreign = "not appear to be in English" in warnings
    out: dict[str, str] = {}
    kind = {"value": ""}

    def verdict(ok: bool, looser: bool = False) -> str:
        """STRICT: a warning counts only if it is about THIS kind of restriction (or says
        the text was not read at all). An unrelated warning does not excuse a loss."""
        if ok:
            return "ENFORCED"
        relevant = foreign or "no spending rules at all" in warnings or any(
            w in warnings for w in RELEVANT[kind["value"]])
        if looser:
            return "DISCLOSED" if relevant else "ENFORCED_LOOSER"
        return "DISCLOSED" if relevant else "SILENT_LOSS"

    # the amount
    kind["value"] = "amount"
    amount_rules = [r for r in c.hard_rules if r.field == "authorization.billing_amount_chf"]
    want_days = SCOPES[s.scope]
    if want_days == "total" and s.purpose == "one-off" and "order.errand_already_fulfilled" in rules:
        # One chosen item, bought once: the order total IS the total, and a second
        # purchase is put to the customer by the errand rule.
        out["amount"] = verdict(any(r.scope == "purchase" and float(r.value) <= s.amount for r in amount_rules))
    elif want_days == "total":
        out["amount"] = verdict(False)
    else:
        scope = "purchase" if want_days is None else "period"
        match = [r for r in amount_rules if r.scope == scope
                 and (scope == "purchase" or r.period_days == want_days)]
        ok = any(float(r.value) <= s.amount for r in match)
        looser = any(float(r.value) > s.amount for r in match) or (
            not match and any(r.scope == "purchase" for r in amount_rules) and scope == "period")
        out["amount"] = verdict(ok, looser)
    if any(r.scope == "purchase" and float(r.value) < s.amount for r in amount_rules):
        out["amount_stricter"] = "STRENGTHENED"
    # familiarity
    kind["value"] = "familiar"
    if s.familiar:
        out["familiar"] = verdict("merchant.familiar" in rules)
    elif "merchant.familiar" in rules:
        out["familiar"] = "STRENGTHENED"
    # returns
    kind["value"] = "returns"
    if s.returns:
        want = 30 if "30" in s.returns else 14 if "14" in s.returns else None
        r = rules.get("order.return_window_days")
        if want is None:            # final sale / refundable: any positive window is the reading
            out["returns"] = verdict(r is not None or "order.returnable" in rules)
        else:
            out["returns"] = verdict(r is not None and int(r.value) >= want,
                                     looser=r is not None and int(r.value) < want)
    # one-off vs recurring
    kind["value"] = "one_off"
    errand = "order.errand_already_fulfilled" in rules
    if s.purpose == "one-off":
        out["one_off"] = verdict(errand)
    elif s.purpose == "recurring" and errand:
        out["one_off"] = "STRENGTHENED"
    # language: a non-English instruction must be disclosed even if parts were read
    if s.language != "English":
        out["language"] = "DISCLOSED" if any("not appear to be in English" in u
                                             for u in c.unsupported_restrictions) else "SILENT_LOSS"
    drift = PARAPHRASE_DRIFT_FINAL if entry.get("_corpus") == "final" else PARAPHRASE_DRIFT
    if s.id in drift:
        out = {k: ("PARAPHRASE_DRIFT" if v in ("SILENT_LOSS", "ENFORCED_LOOSER") else v) for k, v in out.items()}
    # NOISE: an English instruction whose every restriction is enforced, and which the
    # customer is nonetheless warned about. Not a safety failure; a usability cost.
    noisy = (s.language == "English" and out and all(v == "ENFORCED" for v in out.values())
             and bool(c.unsupported_restrictions))
    return {"id": s.id, "text": entry["text"], "language": s.language, "grades": out, "noisy": noisy,
            "warnings": list(c.unsupported_restrictions)}


def main(argv: list[str]) -> int:
    path = (HOLDOUT if "--holdout" in argv else BLIND if "--blind" in argv
            else FINAL if "--final" in argv else CORPUS)
    if "--generate" in argv:
        n = int(argv[argv.index("--generate") + 1])
        if path == HOLDOUT:
            generate(n, path=HOLDOUT, seed=777, style="holdout")
        elif path == BLIND:
            generate(n, path=BLIND, seed=4242, style="blind")
        elif path == FINAL:
            generate(n, path=FINAL, seed=9001, style="final")
        else:
            generate(n)
    graded = [grade(dict(e, _corpus="final" if path == FINAL else "")) for e in load(path)]
    from collections import Counter
    tally = Counter(v for g in graded for v in g["grades"].values())
    by_kind = Counter((k, v) for g in graded for k, v in g["grades"].items())
    print(f"{len(graded)} instructions graded: {dict(tally)}")
    english_clean = [g for g in graded if g["language"] == "English"
                     and g["grades"] and all(v == "ENFORCED" for v in g["grades"].values())]
    print(f"noise: {sum(g['noisy'] for g in graded)} of {len(english_clean)} fully-enforced English "
          f"instructions still carry a warning")
    for (k, v), n in sorted(by_kind.items()):
        print(f"  {k:16s} {v:16s} {n}")
    for g in graded:
        bad = {k: v for k, v in g["grades"].items() if v in ("SILENT_LOSS", "ENFORCED_LOOSER", "STRENGTHENED")}
        if bad:
            print(f"{g['id']} {bad}  | {g['text'][:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""Turn a customer's natural-language instruction into executable hard rules.

This is the "frontend" half of the challenge (challenge.md, Objective #1): translate
free text into clear, executable permissions, while making any uncertainty visible
so the customer can review it before confirming.

Design stance
--------------
This is a small, auditable, *rule-based* compiler -- not an LLM in the money path.
The reasons are architectural, not a shortcut:

  * technical_details.md explicitly asks for a solution that "must still give a
    predictable response when the model or another external service is
    unavailable" -- a regex/lexicon compiler has no such failure mode.
  * challenge.md's technical preference is for the decision engine to stay
    deterministic and low-latency; policy *compilation* happens once, at mandate
    creation time, off the hot path, but keeping it deterministic too means the
    customer sees the exact same permissions on every retry.
  * It must not silently invent authority: every phrase this compiler cannot map
    to a rule becomes a visible `open_question`, never a guess baked into
    `hard_rules`.

Field vocabulary
-----------------
The API storage format is `{field, operator, value, currency?, scope?, period_days?}`
and explicitly says the field name is "a convention for your engine to interpret,
not a formula the API runs" (technical_details.md, step 2). This compiler defines a
small vocabulary of such fields; `rules.py` is the one place that evaluates them
against purchase facts:

  authorization.billing_amount_chf   <=  N   (scope=purchase)              per-order ceiling
  authorization.billing_amount_chf   <=  N   (scope=period, period_days=D) rolling-window ceiling
  merchant.category                  in  [..]                              retailer-type requirement
  merchant.familiar                  =   "true"                            previously-used merchant required
  item.category                      in  [..]                              requested item category
  item.unrequested_present           =   "false"                           no items beyond what was asked for
  order.return_window_days           >=  N                                 minimum return window
  session.integrity_risk             =   "false"                           no active session/device anomaly

Every one of these is a *hard* rule: it can only ever narrow what is allowed,
never widen it (see `mandate.Mandate.tighten_hard_rules`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .money import annual_exposure
from .mandate import HardRule, UncertaintyPolicy

# A small, explicit lexicon mapping everyday nouns to the shared category
# vocabulary used across merchants.csv / items.csv (see data_dictionary.md,
# "Category vocabulary"). This is intentionally short and reviewable -- if the
# customer names something outside it, the compiler raises an open_question
# instead of guessing.
_ITEM_CATEGORY_LEXICON: dict[str, str] = {
    "grocery": "groceries",
    "groceries": "groceries",
    "food": "groceries",
    "running shoe": "sporting_goods",
    "running shoes": "sporting_goods",
    "shoe": "sporting_goods",
    "shoes": "sporting_goods",
    "sports": "sporting_goods",
    "sporting": "sporting_goods",
    "monitor": "electronics",
    "electronics": "electronics",
    "clothing": "clothing",
    "clothes": "clothing",
    "jacket": "clothing",
    "coat": "clothing",
}

_RETAILER_TYPE_LEXICON: dict[str, str] = {
    "sports retailer": "sporting_goods",
    "sporting goods retailer": "sporting_goods",
    "sports shop": "sporting_goods",
    "electronics retailer": "electronics",
    "electronics seller": "electronics",
    "grocery shop": "groceries",
    "grocer": "groceries",
    "supermarket": "groceries",
    "clothing retailer": "clothing",
    "clothes shop": "clothing",
}

_AMOUNT_RE = re.compile(
    r"""
    (?:
        (?:no\ more\ than|not\ more\ than|never\ more\ than|never\ (?:spend|pay)\ more\ than|
           up\ to|at\ most|pay\ no\ more\ than|
           under|below|less\ than|a\ maximum\ of|maximum\ of|max\ of|max|
           capped\ at|limited\ to|no\ higher\ than|nothing\ over|nothing\ above|
           (?:do\ not|don't|doesn't|does\ not)\ (?:exceed|go\ over|go\ above)|
           not\ exceeding|within|up\ to\ a\ limit\ of|budget(?:\ of)?|
           # Added after an INDEPENDENT corpus -- phrases written from a taxonomy of
           # what a person might say, not from this file -- found four amount
           # restrictions the compiler did not recognise. Each is unambiguously a
           # maximum; none invents a semantics the customer did not state. They were
           # already SAFE (no rule, and the customer was told before confirming), so
           # this buys recognition rather than safety.
           #
           # "Don't let any single order exceed CHF 120"  -- negation, then words, then exceed
           (?:do\ not|don't|does\ not|doesn't|must\ not|mustn't)\ (?:\w+\ ){0,4}?(?:exceed|go\ over|go\ above)|
           # "I don't want to pay more than CHF 120 at a time"
           (?:do\ not|don't)\ want\ to\ (?:pay|spend)\ more\ than|
           # "Cap each order at CHF 120"
           cap\ (?:\w+\ ){0,3}?at|
           # "No order above CHF 120"
           no\ \w+\ above)\s*
        CHF\s*(?P<v1>[\d.,]+)
        | CHF\s*(?P<v2>[\d.,]+)\s*(?:or\ less|or\ below|maximum|max\b|cap\b|ceiling|limit)
        | at\ or\ below\s*CHF\s*(?P<v3>[\d.,]+)
        | CHF\s*(?P<v4>[\d.,]+)\s+is\ the\ (?:real\ |actual\ |true\ )?limit
        | the\ limit\ is\ CHF\s*(?P<v5>[\d.,]+)
        | a\ CHF\s*(?P<v6>[\d.,]+)\ (?:cap|ceiling|limit)
        | with\ a\ CHF\s*(?P<v7>[\d.,]+)\ (?:cap|ceiling|limit)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_ROLLING_RE = re.compile(
    r"""
    (?:across|over|within)\s+any\s+(?P<days>\d+|seven|thirty|fourteen)\s*
    day s? .{0,40}? CHF\s*(?P<amount>[\d.,]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# The other direction: an amount stated FIRST and qualified by a period AFTER it --
# "up to CHF 250 per week", "no more than CHF 100 a week", "CHF 300 in any 7 days".
#
# This was the most damaging defect the intent-fidelity audit found, and it was an
# INVERSION rather than a loss. "CHF 250 per week" compiled to
# `billing_amount_chf <= 250 scope=purchase`: a weekly budget silently became a
# per-order ceiling, so the agent could spend CHF 250 every order, forever, against a
# customer who had written a weekly cap. Worse, the guidance then told the customer
# "Each order must total CHF 250 or less" -- asserting a scope they never wrote -- and
# the open question advised them to "consider adding a rolling weekly limit", which is
# the thing they had just written. 2,400 generated instructions hit this.
#
# The mapping is not a guess: week/fortnight/month/year have one ordinary meaning in
# days. Where the customer writes an explicit day count we use theirs.
_PERIOD_WORD_DAYS = {"day": 1, "week": 7, "fortnight": 14, "month": 30, "year": 365}

# "at or below CHF 120" means <=, and it contains the word "below". A first version of
# this pattern did not exclude it and silently flipped the household scenario's per-order rule from
# <= to <. The official replay did not move, because no official purchase is exactly
# CHF 120.00 -- so the only thing that caught it was reading the compiled rules. The
# test that was supposed to guard this compared value and scope but not the OPERATOR.
_STRICT_LIMIT_RE = re.compile(
    r"(?<!at\ or\ )\b(?:under|below|less\s+than)\s*CHF\s*[\d.,]+",
    re.IGNORECASE | re.VERBOSE,
)

# The period word can also come FIRST -- "weekly spending must not exceed CHF 300".
#
# Added after widening the amount vocabulary re-created the inversion this file
# already warns about at length: "must not exceed" newly matched, so a WEEKLY cap
# compiled to `scope=purchase` and the agent could spend CHF 300 every order against
# a customer who had written CHF 300 a week. Found by attacking the change rather
# than by the suite, which had no phrase of this shape.
#
# Deliberately tight: the period word must attach to a SPEND noun. "Order groceries
# weekly, each order under CHF 120" must stay a per-order ceiling, and it does,
# because "weekly" there qualifies the ordering and not a total.
_PERIOD_THEN_AMOUNT_RE = re.compile(
    r"""
    (?P<word>weekly|monthly|daily|yearly|fortnightly)\s+
    (?:spend|spending|total|budget|limit|outlay)
    .{0,40}?
    CHF\s*(?P<amount>[\d.,]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_PERIOD_ADJECTIVE_DAYS = {"daily": 1, "weekly": 7, "fortnightly": 14,
                          "monthly": 30, "yearly": 365}

_TOTAL_AMOUNT_RE = re.compile(
    r"CHF\s*(?P<amount>[\d.,]+)\s*(?:in\s+total|total|overall|altogether|in\s+all)\b",
    re.IGNORECASE,
)

_AMOUNT_THEN_PERIOD_RE = re.compile(
    r"""
    # `\d[\d.,]*\d|\d` rather than `[\d.,]+`: the loose class swallowed TRAILING
    # punctuation, so "CHF 120, and keep..." matched the amount as "120," and the
    # clause-boundary guard below never saw the comma at all. The guard was correct
    # and unreachable -- a fix defeated by the thing it was protecting.
    CHF\s*(?P<amount>\d[\d.,]*\d|\d)
    # Same clause only -- never across a full stop, AND never across another amount.
    # Without the CHF guard the lazy skip jumped over one: in "at or below CHF 120
    # per order, and CHF 300 across any 7 days" it paired CHF 120 with "7 days",
    # producing a CHF 120 WEEKLY budget and dropping the CHF 300 the customer had
    # actually written. Two constraints in, one wrong constraint out. Found by
    # asking whether the text the customer CONFIRMS compiles back to the policy the
    # wallet ENFORCES -- it did not.
    # ...AND NEVER ACROSS A CLAUSE BOUNDARY. The guards above stop the lazy skip at a
    # full stop, a semicolon and another CHF amount, and a comma followed by a
    # conjunction slipped through all three:
    #
    #   "Keep each order at or below CHF 120, and keep the total across any seven
    #    days at or below CHF 300."
    #
    # paired CHF 120 with "seven days", producing a CHF 120 WEEKLY budget, a spurious
    # CHF 300 PER-ORDER ceiling, and nothing at all resembling what was written. The
    # official S1 wording escapes it only by accident: "including delivery" sits
    # between the amount and the comma and pushes the skip past its 30-character
    # budget. So this compiled the benchmark correctly and a two-word paraphrase of
    # it incorrectly, which is the definition of fitting the benchmark.
    #
    # The boundary is the CONJUNCTION, not the comma. Excluding commas outright was
    # the first attempt and it broke "No more than CHF 50, each week" -- a comma that
    # joins nothing. "and"/"but" start a second instruction; a bare comma does not.
    # "or" is deliberately NOT excluded: "CHF 50 or less each week" is ordinary.
    (?:(?!CHF|\band\b|\bbut\b)[^.;]){0,30}?
    \b(?:per|a|each|every|in\ any|over\ any|across\ any|within\ any|in|over)\s+
    (?:(?P<days>\d+)\s*days?
       |(?P<daywords>seven|fourteen|thirty|ten|twenty|sixty|ninety)\s*days?
       |(?P<word>day|week|fortnight|month|year)s?)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_WORDS_TO_NUM = {"seven": 7, "ten": 10, "fourteen": 14, "twenty": 20,
                 "thirty": 30, "sixty": 60, "ninety": 90}

_FAMILIARITY_RE = re.compile(
    r"""
    (?:shop|shops|seller|sellers|merchant|merchants|retailer)\s+
    (?:i\s+(?:use|have\ used|'ve\ used|have\ bought\ from|'ve\ bought\ from)|
       i\ use\ regularly|i\ have\ used\ before|i've\ used\ before|
       i\ have\ bought\ from\ before|i've\ bought\ from\ before|
       (?:that\ )?is\ one\ i\ have\ used|(?:that\ )?is\ one\ i've\ used)
    (?:\s+(?:regularly|before))?
    """,
    re.IGNORECASE | re.VERBOSE,
)

# "a familiar shop" states the same requirement without naming the customer.
_FAMILIARITY_PLAIN_RE = re.compile(
    r"\b(?:familiar|previously[- ]used|known)\s+(?:shop|shops|seller|sellers|merchant|merchants|retailer)\b",
    re.IGNORECASE,
)

_RETAILER_TYPE_RE = re.compile(
    r"(?:only\s+from|from)\s+a\s+(specialist\s+)?([a-z ]+?)(?:\s*,|\s+only|\s+that|\.|$)",
    re.IGNORECASE,
)

# "return it within 14 days" produced NO rule and only an open question, because
# the day count had to follow the return word almost immediately. The near-miss was
# found by `unconsumed.py`, which reported the pronoun "it" as OBSTRUCTIVE -- delete
# that one word and a rule appears -- so the defect named itself rather than waiting
# for someone to think of the phrasing.
#
# Widened by a BOUNDED run of intervening characters, with three guards, because the
# last time an amount pattern was widened here it created a scope inversion:
#   * `[^.;]` cannot cross a sentence or clause boundary;
#   * `(?!CHF)` cannot swallow a money phrase and pair the wrong number;
#   * the preposition is REQUIRED, so only "... within/in/for N days" pairs -- an
#     unanchored `\d+ days` would match "keep the total across any seven days".
_RETURN_WINDOW_RE = re.compile(
    r"return(?:ed|able|s)?\b"
    r"(?:(?!CHF)[^.;]){0,24}?"
    r"\b(?:within|in|for|up\ to|of)\s+"
    # Only MINIMUM-flavoured quantifiers. "returnable for at least 14 days" is a
    # 14-day floor and compiles to `>= 14`; "at most 14 days" is a CEILING on the
    # window and would compile to the opposite of what it says. An unmatched phrase
    # is caught by `unconsumed.py` and shown to the customer, so the safe direction
    # is to decline the pairing rather than to guess it.
    r"(?:at\ least\s+|at\ minimum\s+|a\ minimum\ of\s+|no\ less\ than\s+|minimum\s+)?"
    r"(?P<days>\d+)\s*days?\s*(?P<or_more>or\ more)?",
    re.IGNORECASE | re.VERBOSE,
)

# Five of eight ordinary paraphrases of this one requirement produced NO rule before
# the audit -- including "Only add things I asked for" and "Buy only requested items",
# which are the brief's own examples. Each addition below is an exact synonym of the
# original, verified by reading, not a broadening of what the requirement means.
_NO_ADDONS_RE = re.compile(
    r"(?:do\s+not\s+add|don't\s+add|never\s+add|do\s+not\s+buy\s+unrequested|"
    r"nothing\s+(?:i|you)\s+did\s+not\s+ask\s+for|"
    r"no\s+unrequested|only\s+what\s+i\s+asked\s+for|"
    r"only\s+add\s+(?:things|items)\s+i\s+asked\s+for|"
    r"(?:buy|order)\s+only\s+requested\s+items|"
    r"no\s+extras|nothing\s+else)",
    re.IGNORECASE,
)

_SESSION_INTEGRITY_RE = re.compile(
    r"(?:pause|stop|halt).{0,60}?(?:someone\ other\ than\ me|not\ me|session|device)",
    re.IGNORECASE,
)

_ITEM_MENTION_RE = re.compile(
    r"\b(" + "|".join(sorted(_ITEM_CATEGORY_LEXICON, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# A hyphenated compound adjective immediately modifying a product noun ("road-running
# shoes", "27-inch monitor") is a common, generic way English names a product
# *variant* -- exactly the distinction a same-category substitution (trail-running
# shoes for road-running shoes) or a wrong-but-plausible item (a cycling helmet from
# the same sports retailer) would fail to satisfy. This is a general phrase pattern,
# not a per-scenario special case: it fires on hyphenated modifiers anywhere they
# appear next to a recognized item noun.
#
# The gap between modifier and noun is deliberately capped at one filler word
# ("27-inch [ ] monitor" / "road-running shoes" both fit) rather than left open --
# an unbounded gap would also match a benign, unrelated hyphenated adjective several
# words before the noun ("a well-made pair of running shoes"), turning ordinary
# descriptive language into an unsatisfiable product-variant lock.
_ITEM_MODIFIER_RE = re.compile(
    r"\b([a-z0-9]+-[a-z0-9]+)\b(?:\s+\w+){0,1}?\s+\b(?:"
    + "|".join(sorted(_ITEM_CATEGORY_LEXICON, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)

# "size 43", "in size M" -- a specific, generic size requirement. Restricted to
# plausible size tokens (see facts.py's identical rationale) so "an appropriate
# size for everyone" cannot be misread as a requirement for size "for".
_SIZE_RE = re.compile(r"\bsize\s+([0-9]{1,3}(?:\.[0-9])?|XXXL|XXL|XL|S|M|L)\b", re.IGNORECASE)

# "when"/"if" and "uncertain"/"not sure"/"unsure" are used interchangeably in
# ordinary English and must not be treated as different concepts -- a compiler
# that only recognizes "when uncertain" but not "if you're not sure" would fail to
# understand an explicit, unambiguous customer preference and silently fall back
# to the ASK default instead (found by the fuzz corpus, tests/test_compiler_fuzz_corpus.py).
_UNCERTAIN_TRIGGER = r"(?:when|if)\s+(?:you'?re\s+|it'?s\s+)?(?:not\s+sure|uncertain|unsure)"
_UNCERTAINTY_ASK_RE = re.compile(rf"ask\s+me\s+{_UNCERTAIN_TRIGGER}", re.IGNORECASE)
_UNCERTAINTY_DECLINE_RE = re.compile(rf"(?:decline|reject)(?:\s+it)?\s+{_UNCERTAIN_TRIGGER}", re.IGNORECASE)
_UNCERTAINTY_APPROVE_RE = re.compile(rf"(?:approve|allow)(?:\s+(?:it|anything))?\s+{_UNCERTAIN_TRIGGER}", re.IGNORECASE)


# A ONE-OFF errand: a single thing, bought once. Narrow on purpose -- a missed
# errand is disclosed by the quantity marker below, a false one would turn a
# customer's second legitimate order into a question.
_ERRAND_RE = re.compile(
    r"\b(?:buy|order|purchase|get)\s+(?:exactly\s+|at\s+most\s+|only\s+)?(?:one|a\s+single)\b"
    r"|\bthe\s+[\w\-' ]{1,40}?\s(?:I|we)\s+(?:have\s+)?(?:chose|chosen|picked|selected|saved|liked|want|wanted)\b"
    r"|\breplace\s+(?:my|our)\b",
    re.IGNORECASE)
_RECURRING_RE = re.compile(
    r"\b(?:every|each\s+(?:day|week|month|time)|weekly|daily|monthly|whenever|recurring|"
    r"subscription|regular\s+(?:order|delivery|deliveries)|(?:per|a|an)\s+(?:day|week|month|year))\b",
    re.IGNORECASE)


# --- intent coverage: what the customer wrote that no rule represents ---------------
#
# This module's docstring has always claimed that it "never treats absence of a
# recognizable phrase as silent permission -- unparsed intent becomes an
# `open_question`". The intent-fidelity audit found that claim was FALSE, three ways:
# a quantity word ("buy ONE grocery item") produced nothing at all, five of eight
# ordinary paraphrases of the no-add-ons requirement produced nothing, and two of
# eight familiarity paraphrases produced nothing -- none of them mentioned to the
# customer. An optimiser over generated instructions found 4,032 silent quantity
# losses, 2,400 temporal, 960 familiarity.
#
# Broadening the patterns fixes the paraphrases we happened to think of, and nothing
# else; there are indefinitely many ways to write a restriction. So the patterns
# below are not another attempt to UNDERSTAND the phrase. They detect that the
# customer used restrictive language of a given KIND, and then check whether any rule
# of that kind exists. If not, the phrase is named back to the customer before they
# confirm. The check never creates a rule and never changes a decision -- it converts
# a silent loss into a visible question, which is the weakest honest thing to do and
# the only one that does not require guessing what they meant.
_COVERAGE_MARKERS: tuple[tuple[str, "re.Pattern[str]", str, str], ...] = (
    (
        "quantity",
        # Anchored on the VERB, not on a list of nouns. An earlier version matched a
        # quantity word followed by one of a dozen product nouns, and so missed
        # "Buy one groceries" -- 2,112 generated instructions -- while a bare \bone\b
        # would fire on "a shop that is one I have used before". Anchoring on
        # "buy/order/purchase/get + quantifier" is narrow enough to avoid that and
        # general enough not to need a noun vocabulary.
        re.compile(r"\b(?:buy|order|purchase|get)\s+"
                   r"(?:exactly\s+|at\ most\s+|up\ to\s+|a\ single\s+|no\ more\ than\s+)?"
                   r"(?:one|two|three|four|five|ten|twenty|a\ single|\d+)\b",
                   re.IGNORECASE | re.VERBOSE),
        # ONE is expressible (see _ERRAND_RE below); any other count is not.
        "order.errand_already_fulfilled",
        "You asked for a specific number of items. This wallet enforces a one-off errand (one "
        "unit, then it asks you before buying again) but not larger counts, so this part of your "
        "instruction is NOT enforced. Revoke the mandate once you have what you asked for.",
    ),
    (
        "familiarity",
        re.compile(r"\b(?:familiar|used\ before|use\ regularly|bought\ from\ before|"
                   r"previously[- ]used|known\ (?:shop|seller|merchant))\b", re.IGNORECASE | re.VERBOSE),
        "merchant.familiar",
        "You appear to require a shop you have used before, but that was not recognised as a rule. "
        "It is NOT enforced. Please rephrase it, for example \"from a shop I have used before\".",
    ),
    (
        "no add-ons",
        re.compile(r"(?:do\ not\ add|don't\ add|never\ add|no\ extras|nothing\ else|"
                   r"only\ .{0,20}?(?:asked\ for|requested)|unrequested)", re.IGNORECASE | re.VERBOSE),
        "item.unrequested_present",
        "You appear to be forbidding unrequested items, but that was not recognised as a rule. It is "
        "NOT enforced. Please rephrase it, for example \"do not add anything I did not ask for\".",
    ),
    (
        "per-order ceiling",
        # A currency amount, OR a limit word followed by a bare number ("spend no more
        # than 400"): the customer stated a ceiling even without naming the currency.
        re.compile(r"CHF\s*[\d.,]+|\b(?:no\ more\ than|not\ more\ than|max(?:imum)?|at\ most|up\ to|"
                   r"under|below|less\ than|budget|limit|cap(?:ped)?\ at|exceed(?:ing)?)"
                   r"\s*(?:of\s+)?\d", re.IGNORECASE | re.VERBOSE),
        "authorization.billing_amount_chf",
        "You named an amount, but no spending ceiling was recognised from the way it is "
        "worded, so purchases are NOT limited by amount. Rephrase it, for example "
        "\"for CHF 40 or less\" or \"no more than CHF 40 per order\".",
    ),
    (
        "overall total",
        re.compile(r"CHF\s*[\d.,]+\s*(?:in\s+total|total|overall|altogether|in\s+all)\b", re.IGNORECASE),
        "",
        "You set an OVERALL TOTAL. The rule format cannot express one -- it has only a per-order "
        "ceiling and a rolling-window ceiling -- so that total is NOT enforced. The closest available "
        "control is a rolling limit, which paces spending without capping it. Revoke the mandate when "
        "the job is done.",
    ),
    (
        "end date",
        re.compile(r"\b(?:stop|end|finish|expire|until|after|by)\s+"
                   r"(?:on\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
                   r"tomorrow|tonight|today|next\s+\w+|the\s+\d{1,2}(?:st|nd|rd|th)?)\b",
                   re.IGNORECASE | re.VERBOSE),
        "",
        "You set an end date or deadline. The rule format has no way to express one, so the mandate "
        "does NOT expire on its own. Revoke it yourself when that time comes.",
    ),
    (
        "return window",
        re.compile(r"\breturn(?:ed|able|s)?\b", re.IGNORECASE),
        "order.return_window_days",
        "You mention returns, but no return-window rule was created, so returnability is NOT checked. "
        "Please state a number of days, for example \"returnable within 14 days or more\".",
    ),
    (
        "session integrity",
        re.compile(r"(?:someone\ other\ than\ me|not\ me|hijack|taken\ over|"
                   r"driving\ the\ session)", re.IGNORECASE | re.VERBOSE),
        "session.integrity_risk",
        "You appear to be asking us to pause when the session looks like it is not you, but that was "
        "not recognised as a rule. It is NOT enforced.",
    ),
)


def _coverage_questions(text: str, rules: list[HardRule]) -> list[str]:
    """Restrictive language the customer wrote that no rule of that kind represents.

    Every item here is UNSUPPORTED RESTRICTIVE INTENT by construction: the marker
    fired, so the customer used narrowing language of a kind we recognise, and no rule
    of that kind exists. That is precisely the set that must block auto-confirmation.
    """
    present = {r.field for r in rules}
    out: list[str] = []
    for _kind, pattern, required_field, message in _COVERAGE_MARKERS:
        if not pattern.search(text):
            continue
        # An empty `required_field` means no rule of that kind CAN exist -- quantity is
        # not expressible in this vocabulary at all -- so the question always fires.
        if required_field and required_field in present:
            continue
        out.append(message)
    if _looks_non_english(text):
        out.append(_NON_ENGLISH_MESSAGE)
    return out


# Every pattern in this file is English, and every marker above is English, so an
# instruction in French, German or Italian -- this is a Swiss card -- loses whatever
# the patterns cannot read and the markers cannot see. Measured: "chez un vendeur où
# j'ai déjà acheté ... N'ajoute rien que je n'ai pas demandé" compiled to a ceiling
# alone, with the familiarity and no-add-ons requirements gone and NOTHING said;
# "CHF 80 max chaque semaine" became CHF 80 per order with the weekly cap gone.
#
# Translating is out of scope for a deterministic compiler, and a list of foreign
# restriction phrases would be the paraphrase chase again, in three more languages.
# Detection is enough: function words that do not occur in English instructions, two
# DISTINCT ones so a single borrowed word ("chez", "café") does not trip it. It never
# creates a rule; it turns a silent loss into a question before confirmation.
_NON_ENGLISH_WORDS = frozenset("""
    je j tu que qui pas rien seulement chez où déjà achète acheter achat demande moi
    les des une sur chaque semaine mois jour ne suis sûr sûre vendeur magasin connu
    ich nicht nur und bei wenn du den der das mit für höchstens maximal kauf kaufe kaufen frag
    woche monat geschäft geschäften schon habe mich mir unsicher eingekauft
    che compra comprare massimo ho il della chiedi settimana negozio già sono
""".split())


def _looks_non_english(text: str) -> bool:
    words = set(re.findall(r"[^\W\d_]+", text.lower()))
    return len(words & _NON_ENGLISH_WORDS) >= 2


_NON_ENGLISH_MESSAGE = (
    "Part of your instruction does not appear to be in English. This wallet reads English only, "
    "so anything written in another language was NOT read and is NOT enforced. Please write the "
    "whole instruction in English and check the rules listed before you confirm."
)


# Every amount pattern above is written "CHF 400", and a Swiss customer writes
# "400 CHF", "400 francs", "Fr. 400", "SFr 400", "400.-" and "1'000" at least as
# often. None of those produced a ceiling, and the coverage marker below only looked
# for "CHF 400", so "Buy the monitor I chose, max 400 francs" compiled with no amount
# rule and NOTHING told the customer: the most basic limit a person can state, lost
# silently. Same remedy as the whitespace collapse: normalise the spelling of an
# amount once, for matching only, rather than teaching every pattern every spelling.
_SWISS_THOUSANDS_RE = re.compile(r"(?<=\d)[’'](?=\d{3}\b)")
_AMOUNT_TOKEN = r"\d[\d.,]*\d|\d"
_CURRENCY_AFTER_RE = re.compile(
    rf"(?<![\w.])(?:CHF\s*)?(?P<n>{_AMOUNT_TOKEN})(?:\.[-–])?\s*"
    r"(?:CHF\b|Swiss\s+francs?\b|francs?\b|Franken\b|franchi\b|SFr\.?|Fr\.)", re.IGNORECASE)
_CURRENCY_BEFORE_RE = re.compile(rf"(?<!\w)(?:SFr\.?|Fr\.)\s*(?P<n>{_AMOUNT_TOKEN})(?:\.[-–])?", re.IGNORECASE)
_SWISS_DASH_RE = re.compile(rf"(?<![\w.])(?:CHF\s*)?(?P<n>{_AMOUNT_TOKEN})\.[-–]")


def _normalise_currency(text: str) -> str:
    text = _SWISS_THOUSANDS_RE.sub("", text)
    for pattern in (_CURRENCY_AFTER_RE, _CURRENCY_BEFORE_RE, _SWISS_DASH_RE):
        text = pattern.sub(lambda m: f"CHF {m.group('n')}", text)
    return text


def _parse_amount(raw: str) -> float:
    return float(raw.replace(",", ""))


@dataclass
class CompiledPolicy:
    """The four categories this compiler distinguishes, stated once, precisely.

    SUPPORTED RESTRICTION -- a phrase mapped to a `HardRule`. Enforced.

    UNSUPPORTED RESTRICTIVE INTENT -- the text carries a restrictive marker of a kind
        this compiler recognises, and no rule of that kind was produced. The customer
        asked for something narrowing and did not get it. Goes in
        `unsupported_restrictions` and BLOCKS automatic confirmation.

    AMBIGUOUS INTENT -- a restriction of a supported kind stated more than once with
        conflicting values ("CHF 100, actually CHF 50"). The compiler resolves it
        DEFENSIVELY (the smaller figure) and names the resolution. Advisory, not
        blocking: a rule exists, it is the stricter reading, and the customer can see
        which one was used.

    HARMLESS UNKNOWN LANGUAGE -- text with no restrictive marker at all ("Order our
        household groceries for delivery", "Thanks very much"). Produces nothing and
        blocks nothing. Treating it as a restriction would make every mandate
        unconfirmable, which is why the blocking set is keyed on MARKERS rather than
        on "text we did not consume".
    """

    hard_rules: list[HardRule] = field(default_factory=list)
    uncertainty_policy: UncertaintyPolicy = UncertaintyPolicy.ASK
    guidance: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    # Restrictive intent this compiler could not represent. Non-empty means the
    # mandate must not be confirmed without the customer explicitly seeing these.
    unsupported_restrictions: list[str] = field(default_factory=list)


def compile_instruction(instruction: str) -> CompiledPolicy:
    """Compile one customer instruction into hard rules the decision engine can run.

    Never invents a rule the text does not support, and never treats absence of a
    recognizable phrase as silent permission -- unparsed intent becomes an
    `open_question` shown to the customer before they confirm the mandate.
    """
    # Whitespace is not semantic here, but every pattern below is written with literal
    # spaces, so it WAS: doubling the spaces in the five official instructions lost the
    # per-order ceiling in all five, the merchant-familiarity rule in two, the
    # session-integrity rule in one, and flipped the household scenario's operator from <= to <
    # (because "at or  below" no longer matched the negative lookbehind). A customer
    # typing into a text box produces double spaces, tabs and newlines constantly.
    #
    # Collapsing runs of whitespace before matching is the fix that does not require
    # touching a dozen patterns individually, and it cannot change meaning. Only the
    # matching text is normalised; nothing the customer wrote is rewritten for them.
    text = re.sub(r"\s+", " ", instruction).strip()
    text = _normalise_currency(text)
    rules: list[HardRule] = []
    # Intent that was RECOGNISED but cannot be turned into an enforceable rule, as
    # opposed to intent `_coverage_questions` failed to recognise at all. Merged into
    # `unsupported_restrictions` below; the two are different failures and the
    # customer is owed the difference.
    unenforceable: list[str] = []
    guidance: list[str] = []
    open_questions: list[str] = []

    # --- per-order amount ceiling -------------------------------------------------
    # If the instruction mentions more than one per-order amount (a correction, a
    # typo followed by a fix, or genuinely contradictory phrasing -- "up to CHF 100,
    # actually CHF 50 max"), taking only the FIRST match found would silently
    # ignore a later, possibly-corrective figure. The safe default when an
    # instruction is ambiguous about its own ceiling is the MORE restrictive
    # figure, and the ambiguity itself is surfaced so the customer can clarify.
    # Amounts the customer qualified with a PERIOD ("CHF 250 per week") are budgets,
    # not per-order ceilings, and must not be counted as either the per-order figure
    # or part of the "more than one per-order amount" ambiguity check below.
    period_amounts: list[tuple[float, int]] = []
    for m in _AMOUNT_THEN_PERIOD_RE.finditer(text):
        if m.group("days"):
            days = int(m.group("days"))
        elif m.group("daywords"):
            days = _WORDS_TO_NUM[m.group("daywords").lower()]
        else:
            days = _PERIOD_WORD_DAYS[m.group("word").lower()]
        period_amounts.append((_parse_amount(m.group("amount")), days))
    for m in _PERIOD_THEN_AMOUNT_RE.finditer(text):
        period_amounts.append((_parse_amount(m.group("amount")),
                               _PERIOD_ADJECTIVE_DAYS[m.group("word").lower()]))
    period_amount_values = {a for a, _ in period_amounts}

    # "no more than CHF 50 IN TOTAL" is the same inversion as "per week", pointing at
    # the one scope this vocabulary has no way to express at all. Reading it as a
    # per-order ceiling told the customer "your CHF 50 limit applies to each individual
    # purchase" -- contradicting the word they wrote -- and then explained that a total
    # cannot be set. The honest handling is to create NO amount rule from that phrase
    # and say so, rather than to quietly substitute a weaker scope for the one they asked for.
    total_amounts = {
        _parse_amount(m.group("amount"))
        for m in _TOTAL_AMOUNT_RE.finditer(text)
    }

    amount_matches = [
        v for v in (
            _parse_amount(m.group("v1") or m.group("v2") or m.group("v3") or m.group("v4")
                          or m.group("v5") or m.group("v6") or m.group("v7"))
            for m in _AMOUNT_RE.finditer(text)
        )
        if v not in period_amount_values and v not in total_amounts
    ]
    per_order_amount: float | None = min(amount_matches) if amount_matches else None
    # "under CHF 50" and "below CHF 50" exclude 50; "CHF 50 or less" includes it. The
    # compiler emitted `<=` for all of them, so a customer who wrote "under CHF 50" had
    # an order of exactly CHF 50.00 approved. One rappen of over-permissiveness, but it
    # is the customer's word being overridden, which is the whole subject of this audit.
    per_order_operator = "<" if _STRICT_LIMIT_RE.search(text) else "<="
    if len(amount_matches) > 1 and len(set(amount_matches)) > 1:
        open_questions.append(
            f"The instruction mentions more than one per-order amount ({sorted(set(amount_matches))}); "
            f"the smallest (CHF {per_order_amount:g}) was used defensively. Please confirm the intended limit."
        )

    # --- rolling-window ceiling ("across any N days ... CHF X") --------------------
    rolling_amount: float | None = None
    rolling_days: int | None = None
    rm = _ROLLING_RE.search(text)
    if rm:
        days_raw = rm.group("days").lower()
        rolling_days = _WORDS_TO_NUM.get(days_raw, None)
        if rolling_days is None:
            rolling_days = int(days_raw)
        rolling_amount = _parse_amount(rm.group("amount"))

    if per_order_amount is not None:
        rules.append(
            HardRule(
                field="authorization.billing_amount_chf",
                operator=per_order_operator,
                value=per_order_amount,
                currency="CHF",
                scope="purchase",
            )
        )
        # The wording has to match the OPERATOR, not just the number. "under CHF
        # 120" compiles to `< 120`, and this line said "CHF 120 or less" -- which
        # describes `<= 120`. The customer confirmed text one rappen more permissive
        # than the rule being enforced, so an order of exactly CHF 120.00 was refused
        # by a wallet whose own confirmation screen said it was allowed.
        guidance.append(
            f"Each order must total less than CHF {per_order_amount:g}, including delivery."
            if per_order_operator == "<"
            else f"Each order must total CHF {per_order_amount:g} or less, including delivery."
        )
    else:
        open_questions.append(
            "No per-order spending ceiling was recognized in the instruction. "
            "Purchases will not be limited by amount unless a rolling limit below applies."
        )

    # A period stated after the amount ("CHF 250 per week"). Emitted in addition to
    # any "across any N days" form, deduplicated on (amount, days).
    emitted_periods: set[tuple[float, int]] = set()
    if rolling_amount is not None and rolling_days is not None:
        emitted_periods.add((rolling_amount, rolling_days))
    for amount, days in period_amounts:
        if (amount, days) in emitted_periods:
            continue
        emitted_periods.add((amount, days))
        rules.append(
            HardRule(
                field="authorization.billing_amount_chf",
                operator="<=",
                value=amount,
                currency="CHF",
                scope="period",
                period_days=days,
            )
        )
        guidance.append(
            f"The total across any rolling {days}-day window must stay at or below CHF {amount:g}."
        )

    if rolling_amount is not None and rolling_days is not None:
        rules.append(
            HardRule(
                field="authorization.billing_amount_chf",
                operator="<=",
                value=rolling_amount,
                currency="CHF",
                scope="period",
                period_days=rolling_days,
            )
        )
        guidance.append(
            f"The total across any rolling {rolling_days}-day window must stay at or below CHF {rolling_amount:g}."
        )

    # --- merchant familiarity -------------------------------------------------------
    if _FAMILIARITY_RE.search(text) or _FAMILIARITY_PLAIN_RE.search(text):
        rules.append(HardRule(field="merchant.familiar", operator="=", value="true"))
        guidance.append(
            "The seller must be one this card has purchased from before "
            "(judged from the supplied authorization history)."
        )

    # --- retailer type (merchant category) -------------------------------------------
    retailer_category: str | None = None
    for phrase, category in _RETAILER_TYPE_LEXICON.items():
        if re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE):
            retailer_category = category
            break
    if retailer_category is None:
        rt_match = _RETAILER_TYPE_RE.search(text)
        # Ignore matches that are really a familiarity phrase in disguise ("from a
        # shop I use regularly") -- those name no category at all, and are handled
        # separately by _FAMILIARITY_RE below.
        if rt_match and not re.search(r"\bi\b|\bi've\b|\bi have\b", rt_match.group(2), re.IGNORECASE):
            open_questions.append(
                f"The instruction names a retailer type ({rt_match.group(2).strip()!r}) "
                "that is not in the known category lexicon; it was not turned into a rule."
            )
    if retailer_category is not None:
        rules.append(HardRule(field="merchant.category", operator="in", value=[retailer_category]))
        guidance.append(f"The seller's own category must be {retailer_category!r} (a specialist retailer of that kind).")

    # --- requested item category -----------------------------------------------------
    item_categories = sorted({_ITEM_CATEGORY_LEXICON[m.group(1).lower()] for m in _ITEM_MENTION_RE.finditer(text)})
    if item_categories:
        rules.append(HardRule(field="item.category", operator="in", value=item_categories))
        guidance.append(f"Purchases must be for the requested kind of item ({', '.join(item_categories)}).")

    # --- specific product variant (hyphenated modifier next to an item noun) --------
    modifier_match = _ITEM_MODIFIER_RE.search(text)
    if modifier_match:
        modifier = modifier_match.group(1)
        rules.append(HardRule(field="item.name_contains", operator="=", value=modifier))
        guidance.append(f"The purchased item's name must match the requested variant ({modifier!r}), not just its category.")

    # --- specific size --------------------------------------------------------------
    size_match = _SIZE_RE.search(text)
    if size_match:
        size_value = size_match.group(1)
        rules.append(HardRule(field="item.size", operator="=", value=size_value))
        guidance.append(f"The item must be in the requested size ({size_value}).")

    # --- return window ------------------------------------------------------------
    rw = _RETURN_WINDOW_RE.search(text)
    if rw:
        days = int(rw.group("days"))
        op = ">=" if rw.group("or_more") else ">="
        rules.append(HardRule(field="order.return_window_days", operator=op, value=days))
        guidance.append(f"The order must be returnable within at least {days} days.")
    elif re.search(r"\breturn", text, re.IGNORECASE):
        # The instruction clearly discusses returns but not in a form this compiler
        # recognizes (e.g. a word-form number like "returnable within a month") --
        # surfaced rather than silently dropped, matching the amount ceiling's own
        # "flag what couldn't be understood" behavior above.
        open_questions.append(
            "The instruction mentions returns, but no specific day count was recognized; "
            "no return-window rule was created."
        )

    # --- no unrequested add-ons -----------------------------------------------------
    if _NO_ADDONS_RE.search(text):
        # "UNREQUESTED" IS MEANINGLESS WITHOUT "REQUESTED". This rule is evaluated
        # against the categories the mandate's own `item.category` rules name, so on
        # its own it has nothing to compare a basket to -- it answers `unknown` for
        # every purchase, which under `approve` waves everything through and under
        # `ask` questions everything. "Do not add anything I did not ask for." on its
        # own compiled to exactly that, while the sibling phrasing "Only buy what I
        # asked for" was already being flagged unsupported.
        #
        # IT ALSO BROKE THE TIGHTEN-ONLY CONTRACT the brief requires, because the
        # missing fact could arrive later:
        #
        #     "nothing unrequested"                        review  (unknown)
        #     "nothing unrequested" + "groceries only"     ALLOW   (pass)
        #
        # Appending a rule -- the canonical tightening -- made the wallet MORE
        # permissive, because the second rule supplied the fact the first one needed.
        # Refusing to emit an unenforceable rule removes the non-monotonicity at its
        # source rather than policing it at the PATCH boundary.
        if any(r.field == "item.category" for r in rules):
            rules.append(HardRule(field="item.unrequested_present", operator="=", value="false"))
            guidance.append("The basket must not contain items beyond what was requested.")
        else:
            unenforceable.append(
                "You asked for nothing beyond what you requested, but the instruction "
                "never says WHAT you requested -- so there is nothing to compare a "
                "basket against, and this part is NOT enforced. Name the kind of thing "
                "you are buying (for example \"groceries\") and it becomes a rule.")

    # --- a one-off errand ------------------------------------------------------------
    # "Buy the monitor I chose", "Replace my worn shoes", "Buy one grocery item" name
    # ONE thing to buy once. Nothing represented that, so the official manipulated-
    # agent run approved four monitors (CHF 1,430.40) and the running-shoes run three
    # pairs. The rule format lets a solution name its own facts ("a nonempty string
    # naming the fact to check"; only extra rule KEYS are forbidden), so this one is
    # the wallet's own ledger: more than one unit in the order is refused, and a
    # further order after one was approved is put to the customer, because whether
    # the first was delivered, cancelled or returned is not something it can see.
    # A recurring phrasing ("every week", "weekly") is never read as an errand.
    if _ERRAND_RE.search(text) and not _RECURRING_RE.search(text):
        rules.append(HardRule(field="order.errand_already_fulfilled", operator="=", value="false"))
        guidance.append("This is a one-off errand: one unit, and after one approved purchase the "
                        "wallet asks you before any further purchase.")

    # --- session integrity ----------------------------------------------------------
    if _SESSION_INTEGRITY_RE.search(text):
        rules.append(HardRule(field="session.integrity_risk", operator="=", value="false"))
        guidance.append("Purchases are paused if the session shows signs of not being driven by the customer.")

    # --- uncertainty policy -----------------------------------------------------------
    if _UNCERTAINTY_DECLINE_RE.search(text):
        uncertainty_policy = UncertaintyPolicy.DECLINE
    elif _UNCERTAINTY_APPROVE_RE.search(text):
        uncertainty_policy = UncertaintyPolicy.APPROVE
    elif _UNCERTAINTY_ASK_RE.search(text):
        uncertainty_policy = UncertaintyPolicy.ASK
    else:
        uncertainty_policy = UncertaintyPolicy.ASK
        open_questions.append(
            "No explicit uncertainty preference was found; defaulting to 'ask the customer' "
            "when the engine cannot be confident."
        )

    if not rules:
        # A mandate with zero executable rules has nothing to check any purchase
        # against; decision_engine.py treats this as maximal uncertainty (routed
        # through uncertainty_policy) rather than "everything passes" specifically
        # so this case can never become unlimited spending authority by accident --
        # but the customer should still see, in plain language, that this
        # instruction produced no spending controls at all before they confirm it.
        open_questions.append(
            "This instruction did not produce any spending rules at all. Every purchase will need your "
            "confirmation (or will be declined, or approved automatically) purely based on the uncertainty "
            "setting below, since there is nothing else to check it against."
        )

    # Total economic exposure, disclosed before the customer confirms.
    #
    # The rule vocabulary has exactly two scopes -- "purchase" and "period" -- and
    # technical_details.md closes the set: "No extra rule fields are allowed." So a
    # customer can state a ceiling PER PURCHASE and a ceiling PER ROLLING WINDOW, and
    # there is no way to state either a total or a date on which the delegation ends.
    #
    # That has a consequence worth being precise about, because an earlier version of
    # this disclosure got it wrong in both directions:
    #
    #   * It claimed a rolling cap leaves the agent "blocked and stays blocked". It
    #     does not. The window rolls and re-opens: measured on the household scenario, a
    #     policy-compliant agent draws CHF 240 every 7 days without interruption,
    #     CHF 12,480 in a simulated year. A rolling cap is a RATE, not a total.
    #   * It then advised the customer to "add a total, such as no more than CHF X
    #     across any 7 days" -- which is that same rate. The advice named the thing
    #     the customer wanted and handed them a construct that does not provide it.
    #
    # So neither branch below promises a bound the vocabulary cannot deliver. Both
    # state the exposure in the customer's own unit and leave the judgement to them.
    # This is disclosure only: it creates no rule and is read by no evaluation, so it
    # cannot change a decision.
    per_purchase = next(
        (r for r in rules if r.field == "authorization.billing_amount_chf" and r.scope == "purchase"), None
    )
    period_rule = next((r for r in rules if r.scope == "period"), None)

    if period_rule is not None and period_rule.period_days:
        # One computation, three readers -- see `money.annual_exposure`.
        _exact, annual = annual_exposure(period_rule.value, period_rule.period_days)
        open_questions.append(
            f"Your CHF {float(period_rule.value):g} limit applies to each rolling "
            f"{period_rule.period_days}-day window, so it paces spending rather than capping it: the "
            f"window re-opens and the agent may spend up to that amount again, indefinitely. At that "
            f"rate the delegation is worth about CHF {annual:,.0f} a year. There is no way to set an "
            f"overall total or an end date, so if that figure is more than you intend to delegate, "
            f"revoke or tighten this mandate when the job is done."
        )
        # The second half of the truth, and the half a customer is least likely to
        # guess. `technical_details.md` scopes the platform's own spend context to
        # the run -- "context | Spend and recent authorization information from this
        # run" -- so the window is counted per shopping session, and a session
        # started again begins at zero. Measured on the household scenario: CHF 387.50 per run, so
        # ten runs put CHF 3,875 through a stated CHF 300 / 7-day cap.
        #
        # We do NOT enforce this across sessions, and the reason is a protocol
        # limit rather than a preference: no documented endpoint returns a mandate's
        # accumulated spend, so any cross-session total would be our own unverifiable
        # record. A prototype of one was built and attacked (research/
        # mandate_ledger_prototype.py): two concurrent sessions both approved against
        # the same remaining budget and the losing write vanished, and a ledger file
        # that goes missing is indistinguishable from a mandate that has never spent.
        # Claiming a bound we cannot hold would be worse than naming the one we do.
        open_questions.append(
            f"That {period_rule.period_days}-day window is counted per shopping session. If the agent "
            f"is started again, it begins from zero, so several sessions in the same "
            f"{period_rule.period_days} days can each spend up to CHF {float(period_rule.value):g}. "
            f"Start a new session only when you mean to grant the limit again."
        )
    elif per_purchase is not None:
        open_questions.append(
            f"Your CHF {float(per_purchase.value):g} limit applies to each individual purchase, not to "
            f"the total. The agent may make any number of purchases at that limit, so this mandate "
            f"does not bound what you are delegating overall. Adding a rolling weekly limit would "
            f"slow that down but would still not set a total -- there is no way to state one. Revoke "
            f"the mandate when the job is done."
        )

    # Named back to the customer LAST, so it sees the final rule set rather than a
    # partially-built one.
    # Every CHF figure the customer wrote, against the ones that became a rule.
    #
    # The defensive `min()` above only ever saw amounts this compiler PARSED. When the
    # stricter of two bounds used a phrasing it did not recognise, that bound was
    # invisible: "at most CHF 200 but never over CHF 100" enforced CHF 200, and the
    # multi-amount ambiguity question did not fire either, because it needs two PARSED
    # figures. A stricter limit the customer wrote in plain English simply vanished.
    #
    # Advisory, never blocking. A figure mentioned in passing ("I spent CHF 40 last
    # week") is harmless unknown language, and making an ordinary sentence with a
    # number in it unconfirmable would break the category the confirmation gate
    # deliberately protects. Naming the specific figure keeps it actionable.
    # `\d[\d.,]*` and not `[\d.,]+`: the looser form matched the "chf." in
    # "max 200 chf." and captured the full stop alone, so `_parse_amount(".")` raised
    # ValueError and compiling an ordinary instruction CRASHED. Found by re-running the
    # semantic corpus against this very fix, minutes after writing it.
    stated = {
        _parse_amount(m.group(1).rstrip(".,"))
        for m in re.finditer(r"CHF\s*(\d[\d.,]*)", text, re.IGNORECASE)
    }
    used = {float(r.value) for r in rules if r.field == "authorization.billing_amount_chf"}
    used |= period_amount_values | total_amounts
    unused = sorted(stated - used)
    if unused and used:
        open_questions.append(
            "The instruction also mentions "
            + ", ".join(f"CHF {v:g}" for v in unused)
            + ", which was not turned into any rule. If one of those was meant to be a limit, "
            "it is NOT enforced -- please restate it, for example \"no more than CHF X per order\"."
        )

    unsupported = unenforceable + _coverage_questions(text, rules)
    if not rules:
        # No executable rule at all is the strongest form of unsupported intent: the
        # customer wrote an instruction and got a mandate that checks nothing.
        unsupported.append(
            "This instruction produced no spending rules at all, so nothing about a purchase "
            "is checked against it."
        )
    open_questions.extend(unsupported)

    return CompiledPolicy(
        unsupported_restrictions=unsupported,
        hard_rules=rules,
        uncertainty_policy=uncertainty_policy,
        guidance=guidance,
        open_questions=open_questions,
    )

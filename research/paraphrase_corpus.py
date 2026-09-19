"""Paraphrases of the five official mandates, and near-misses that change meaning.

Every entry declares the relation a REASONABLE HUMAN READER would expect between the
original and the variant, with the reason. That expectation is the thing under test;
the compiler's own output is never used to define it, or the test would be circular.

    EQUIVALENT  -- same constraints; the compiled policy should behave identically
    STRICTER    -- the variant forbids more; the policy must not be more permissive
    WEAKER      -- the variant permits more; the policy must not be more restrictive
    DIFFERENT   -- meanings differ in a way some purchase can observe; policies must differ

A variant marked EQUIVALENT that compiles differently is a FALSE DISTINCTION
(the compiler is sensitive to wording that does not matter). A variant marked
DIFFERENT that compiles identically is a FALSE EQUIVALENCE (the compiler is blind to
wording that does). False equivalence in the permissive direction is the dangerous one.
"""

from __future__ import annotations

EQUIVALENT, STRICTER, WEAKER, DIFFERENT = "EQUIVALENT", "STRICTER", "WEAKER", "DIFFERENT"

S0 = "Buy one ordinary grocery item for CHF 20 or less from a shop I use regularly. Ask me when uncertain."
S1 = ("Order our household groceries for delivery. Keep each order at or below CHF 120 including "
      "delivery, and keep the total across any seven days at or below CHF 300. Ask me when uncertain.")
S2 = ("Replace my worn road-running shoes in size 43. Buy only from a specialist sports retailer, "
      "only if the order can be returned within 14 days or more, and pay no more than CHF 200. "
      "Ask me when uncertain.")
S3 = ("The agent may buy clothing for me, up to CHF 250 per order, from shops I have used before. "
      "Pause anything that looks like someone other than me is driving the session. Ask me when uncertain.")
S4 = ("Buy the 27-inch monitor I chose, from a seller I have bought from before, for CHF 400 or less. "
      "Do not add anything I did not ask for. Ask me when uncertain.")

OFFICIAL = {"SCEN0000": S0, "SCEN0001": S1, "SCEN0002": S2, "SCEN0003": S3, "SCEN0004": S4}

# (base, variant, expected relation, why)
CASES: list[tuple[str, str, str, str]] = [
    # ---------------- SCEN0000 : amount, familiarity, category, quantity ----------
    (S0, "Buy one ordinary grocery item for CHF 20 or less from a shop I use regularly. Ask me if you're not sure.",
     EQUIVALENT, "'ask me if you're not sure' is the same uncertainty preference"),
    (S0, "Buy one ordinary grocery item for a maximum of CHF 20 from a shop I use regularly. Ask me when uncertain.",
     EQUIVALENT, "'a maximum of CHF 20' == 'CHF 20 or less'"),
    (S0, "Buy one ordinary grocery item for no more than CHF 20 from a shop I use regularly. Ask me when uncertain.",
     EQUIVALENT, "'no more than' == 'or less'"),
    (S0, "From a shop I use regularly, buy one ordinary grocery item for CHF 20 or less. Ask me when uncertain.",
     EQUIVALENT, "clause reordering does not change meaning"),
    (S0, "Buy one ordinary grocery item, for CHF 20 or less, from a shop I use regularly. Ask me when uncertain.",
     EQUIVALENT, "punctuation only"),
    (S0, "Buy one ordinary food item for CHF 20 or less from a shop I use regularly. Ask me when uncertain.",
     EQUIVALENT, "'food' and 'grocery' both map to the groceries category"),
    (S0, "Buy one ordinary grocery item for CHF 20 or less from a shop I have used before. Ask me when uncertain.",
     EQUIVALENT, "'use regularly' and 'have used before' both mean a familiar merchant"),
    (S0, "Buy one ordinary grocery item for CHF 20 or less from any shop. Ask me when uncertain.",
     WEAKER, "'any shop' drops the familiarity requirement"),
    (S0, "Buy one ordinary grocery item for CHF 200 or less from a shop I use regularly. Ask me when uncertain.",
     WEAKER, "a ten-times-higher ceiling"),
    (S0, "Buy one ordinary grocery item for CHF 2 or less from a shop I use regularly. Ask me when uncertain.",
     STRICTER, "a much lower ceiling"),
    (S0, "Buy one ordinary grocery item for CHF 20 or less from a shop I use regularly. Decline it when uncertain.",
     STRICTER, "decline-on-uncertainty forbids more than ask"),
    (S0, "Buy one ordinary grocery item for CHF 20 or less from a shop I use regularly. Approve it when uncertain.",
     WEAKER, "approve-on-uncertainty permits more than ask"),
    (S0, "Buy groceries for CHF 20 or less from a shop I use regularly. Ask me when uncertain.",
     WEAKER, "drops 'one' -- any number of purchases rather than a single item"),
    (S0, "Buy twenty ordinary grocery items for CHF 20 or less from a shop I use regularly. Ask me when uncertain.",
     WEAKER, "twenty items instead of one"),
    (S0, "Buy one ordinary grocery item for CHF 20 or less from a specialist sports retailer. Ask me when uncertain.",
     DIFFERENT, "a different merchant restriction entirely"),

    # ---------------- SCEN0001 : per-order vs rolling window ----------------------
    (S1, "Order our household groceries for delivery. Each order must be CHF 120 or less including delivery, "
         "and the total across any seven days must be CHF 300 or less. Ask me when uncertain.",
     EQUIVALENT, "'must be X or less' == 'keep at or below X'"),
    (S1, "Order our household groceries for delivery. Keep the total across any seven days at or below CHF 300, "
         "and keep each order at or below CHF 120 including delivery. Ask me when uncertain.",
     EQUIVALENT, "the two ceilings are stated in the other order"),
    (S1, "Order our household groceries for delivery. Keep each order at or below CHF 120 including delivery, "
         "and keep the total across any 7 days at or below CHF 300. Ask me when uncertain.",
     EQUIVALENT, "numeral instead of the word seven"),
    (S1, "Order our household groceries for delivery. Keep each order at or below CHF 120 including delivery, "
         "and keep the total across any seven days at or below CHF 3000. Ask me when uncertain.",
     WEAKER, "a ten-times-higher rolling ceiling"),
    (S1, "Order our household groceries for delivery. Keep each order at or below CHF 120 including delivery, "
         "and keep the total across any thirty days at or below CHF 300. Ask me when uncertain.",
     STRICTER, "CHF 300 per 30 days is a much lower rate than per 7 days"),
    (S1, "Order our household groceries for delivery. Keep each order at or below CHF 120 including delivery. "
         "Ask me when uncertain.",
     WEAKER, "the rolling ceiling is removed entirely"),
    (S1, "Order our household groceries for delivery. Keep each order at or below CHF 300 including delivery, "
         "and keep the total across any seven days at or below CHF 120. Ask me when uncertain.",
     DIFFERENT, "the two figures are swapped -- a stricter window and a looser order ceiling"),

    # ---------------- SCEN0002 : only / only if / variant / size -----------------
    (S2, "Replace my worn road-running shoes in size 43. Purchase exclusively from a specialist sports "
         "retailer, and only if the order can be returned within 14 days or more, and pay no more than "
         "CHF 200. Ask me when uncertain.",
     EQUIVALENT, "'exclusively from' == 'only from'"),
    (S2, "Replace my worn road-running shoes in size 43. Buy only from a specialist sports retailer, only if "
         "the order can be returned within 14 days or more, and pay CHF 200 or less. Ask me when uncertain.",
     EQUIVALENT, "'pay CHF 200 or less' == 'pay no more than CHF 200'"),
    (S2, "Replace my worn road-running shoes in size 43. Buy from a specialist sports retailer, if the order "
         "can be returned within 14 days or more, and pay no more than CHF 200. Ask me when uncertain.",
     EQUIVALENT, "dropping the word 'only' before a single named requirement does not add options"),
    (S2, "Replace my worn road-running shoes in size 44. Buy only from a specialist sports retailer, only if "
         "the order can be returned within 14 days or more, and pay no more than CHF 200. Ask me when uncertain.",
     DIFFERENT, "a different size is a different requirement"),
    (S2, "Replace my worn trail-running shoes in size 43. Buy only from a specialist sports retailer, only if "
         "the order can be returned within 14 days or more, and pay no more than CHF 200. Ask me when uncertain.",
     DIFFERENT, "a different product variant"),
    (S2, "Replace my worn road-running shoes in size 43. Buy only from a specialist sports retailer, only if "
         "the order can be returned within 30 days or more, and pay no more than CHF 200. Ask me when uncertain.",
     STRICTER, "a longer minimum return window forbids more orders"),
    (S2, "Replace my worn road-running shoes in size 43. Buy only from a specialist sports retailer and pay no "
         "more than CHF 200. Ask me when uncertain.",
     WEAKER, "the return-window requirement is removed"),
    (S2, "Replace my worn road-running shoes in size 43. Buy from any shop, only if the order can be returned "
         "within 14 days or more, and pay no more than CHF 200. Ask me when uncertain.",
     WEAKER, "the specialist-retailer requirement is removed"),

    # ---------------- SCEN0003 : per order, familiarity, session ------------------
    (S3, "The agent may buy clothing for me, up to CHF 250 per purchase, from shops I have used before. Pause "
         "anything that looks like someone other than me is driving the session. Ask me when uncertain.",
     EQUIVALENT, "'per purchase' == 'per order' in this vocabulary"),
    (S3, "The agent may buy clothes for me, up to CHF 250 per order, from shops I have used before. Pause "
         "anything that looks like someone other than me is driving the session. Ask me when uncertain.",
     EQUIVALENT, "'clothes' and 'clothing' are the same category"),
    (S3, "For each clothing order, spend no more than CHF 250 and use a shop I have used before. Pause anything "
         "that looks like someone other than me is driving the session. Ask me when uncertain.",
     EQUIVALENT, "the brief's own paraphrase: same three constraints, restructured"),
    (S3, "Clothing purchases are allowed only when the order is CHF 250 or less and the shop is one I have used "
         "before. Pause anything that looks like someone other than me is driving the session. Ask me when uncertain.",
     EQUIVALENT, "the brief's own paraphrase, conditional form"),
    (S3, "The agent may buy clothing for me, up to CHF 250 per week, from shops I have used before. Pause "
         "anything that looks like someone other than me is driving the session. Ask me when uncertain.",
     DIFFERENT, "per week is a rate, per order is a ceiling -- the brief names this as a MUST-differ case"),
    (S3, "The agent may buy clothing for me, up to CHF 250 per order, from shops I have used before. Ask me "
         "when uncertain.",
     WEAKER, "the session-integrity requirement is removed"),

    # ---------------- SCEN0004 : definite article, no add-ons ---------------------
    (S4, "Buy the 27-inch monitor I chose, from a seller I have bought from before, for no more than CHF 400. "
         "Do not add anything I did not ask for. Ask me when uncertain.",
     EQUIVALENT, "'no more than CHF 400' == 'for CHF 400 or less'"),
    (S4, "Buy the 27-inch monitor I chose, from a seller I have bought from before, for CHF 400 or less. Only "
         "add things I asked for. Ask me when uncertain.",
     EQUIVALENT, "'only add things I asked for' == 'do not add anything I did not ask for'"),
    (S4, "Buy the 27-inch monitor I chose, from a seller I have bought from before, for CHF 400 or less. Do not "
         "buy unrequested items. Ask me when uncertain.",
     EQUIVALENT, "another wording of the same no-add-ons requirement"),
    (S4, "Buy the 27-inch monitor I chose, from a seller I have bought from before, for CHF 400 or less. Never "
         "add extras. Ask me when uncertain.",
     EQUIVALENT, "'never add extras' is the same requirement again"),
    (S4, "Buy the 27-inch monitor I chose, from a seller I have bought from before, for CHF 400 or less. Ask me "
         "when uncertain.",
     WEAKER, "the no-add-ons requirement is removed"),
    (S4, "Buy the 32-inch monitor I chose, from a seller I have bought from before, for CHF 400 or less. Do not "
         "add anything I did not ask for. Ask me when uncertain.",
     DIFFERENT, "a different product variant"),
    (S4, "Buy monitors from a seller I have bought from before, for CHF 400 or less. Do not add anything I did "
         "not ask for. Ask me when uncertain.",
     WEAKER, "'the monitor I chose' (one, specific) becomes 'monitors' (any number, any model)"),
]

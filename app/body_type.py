"""Deterministic body-type classification.

The assistant must never offer a hatchback to someone who asked for a sedan. Rather than
trusting the language model to know every model name, body type is stored per vehicle and,
when an admin leaves it blank, suggested from this keyword table.
"""

from __future__ import annotations

import re

BODY_TYPES = ("sedan", "suv", "pickup", "hatchback", "coupe", "minivan")

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "pickup": ("f-150", "f150", "silverado", "ram 1500", "tacoma", "tundra", "ranger",
               "colorado", "frontier", "gladiator", "maverick", "ridgeline", "sierra"),
    "minivan": ("odyssey", "sienna", "pacifica", "carnival", "grand caravan"),
    "suv": ("cr-v", "crv", "rav4", "rav-4", "highlander", "4runner", "pilot", "hr-v", "passport",
            "explorer", "escape", "bronco", "edge", "expedition", "tahoe", "equinox", "traverse",
            "trax", "blazer", "tucson", "santa fe", "palisade", "kona", "sportage", "sorento",
            "telluride", "seltos", "rogue", "murano", "pathfinder", "kicks", "cx-5", "cx-30",
            "cx-50", "cx-90", "outback", "forester", "crosstrek", "ascent", "tiguan", "atlas",
            "taos", "wrangler", "grand cherokee", "compass", "cherokee", "model y", "x3", "x5",
            "q5", "q7", "rdx", "mdx", "nx", "rx"),
    "coupe": ("mustang", "camaro", "challenger", "brz", "gr86", "supra", "miata", "mx-5",
              "corvette", "370z", "400z"),
    "hatchback": ("civic hatchback", "golf", "gti", "fit", "yaris", "mazda3 hatchback",
                  "impreza", "veloster", "bolt", "leaf", "mini cooper", "prius", "versa note"),
    "sedan": ("civic", "accord", "corolla", "camry", "avalon", "altima", "sentra", "maxima",
              "versa", "malibu", "elantra", "sonata", "forte", "k5", "jetta", "passat",
              "mazda3", "mazda6", "legacy", "model 3", "3 series", "5 series", "a4", "a6",
              "c-class", "e-class", "es 350", "is 300", "tlx", "charger"),
}

# Longer phrases are checked first so "civic hatchback" beats "civic".
_ORDERED = sorted(
    ((kw, body) for body, kws in _KEYWORDS.items() for kw in kws),
    key=lambda item: len(item[0]),
    reverse=True,
)


def classify(make: str, model: str, trim: str = "") -> str | None:
    """Return a body type for a make/model/trim, or None when unknown."""
    haystack = f" {make} {model} {trim} ".lower()
    for keyword, body in _ORDERED:
        if f" {keyword} " in haystack:
            return body
    return None


# Words a shopper might use for each body type.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "sedan": ("sedan", "saloon", "four-door", "4 door"),
    "suv": ("suv", "crossover", "sport utility"),
    "pickup": ("pickup", "pick-up", "truck"),
    "hatchback": ("hatchback", "hatch", "compact"),
    "coupe": ("coupe", "sports car", "two-door", "2 door"),
    "minivan": ("minivan", "van", "family van"),
}


def detect_requested(text: str) -> str | None:
    """Find the body type a shopper is asking for in free text."""
    lowered = text.lower()
    for body, pattern in _SYNONYM_PATTERNS.items():
        if pattern.search(lowered):
            return body
    return None


_SYNONYM_PATTERNS = {
    body: re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")s?\b")
    for body, words in SYNONYMS.items()
}

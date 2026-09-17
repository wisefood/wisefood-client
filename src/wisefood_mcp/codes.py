"""Country and language as the catalog wants them: two-letter codes.

A proposal records what the assistant wrote — "Greece", "Greek" — because
that is what a curator reads and what the source says about itself. The
catalog takes ISO 3166-1 alpha-2 and ISO 639-1, and rejected both:
`body.region: String should have at most 2 characters`. Translating happens
here rather than asking the model to emit codes, which it does inconsistently
and cannot be corrected on.

`pycountry` carries the official lists and their common names, so this is a
lookup rather than a table somebody has to remember to extend.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

#: Names that are in daily use but are not what the ISO tables call a place.
#: Kept short on purpose: anything pycountry can resolve does not belong here.
COUNTRY_ALIASES = {
    "uk": "GB", "britain": "GB", "great britain": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "usa": "US", "america": "US", "united states of america": "US",
    "south korea": "KR", "north korea": "KP", "russia": "RU",
    "czechia": "CZ", "czech republic": "CZ", "turkey": "TR", "türkiye": "TR",
    "holland": "NL", "ivory coast": "CI", "cape verde": "CV",
    "eu": None, "europe": None, "international": None, "global": None,
}

#: Same idea for languages, where the endonym is often what a source uses.
LANGUAGE_ALIASES = {
    "greek": "el", "ellinika": "el", "ελληνικά": "el",
    "bulgarian": "bg", "български": "bg",
    "english": "en", "french": "fr", "german": "de", "spanish": "es",
    "italian": "it", "dutch": "nl", "portuguese": "pt", "romanian": "ro",
    "polish": "pl", "czech": "cs", "croatian": "hr", "serbian": "sr",
}


def country_code(value: Optional[str]) -> Optional[str]:
    """An ISO 3166-1 alpha-2 code, or None.

    None where no single country is meant — "EU", "international" — which is
    correct rather than a failure: the catalog's region is optional and a
    guide for the whole of Europe has no one country.
    """
    if not value or not str(value).strip():
        return None
    raw = str(value).strip()
    flat = raw.lower()
    # Aliases first: "UK" and "EU" are two letters and neither is an ISO
    # country code — GB is, and the EU is not a country at all.
    if flat in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[flat]
    try:
        import pycountry

        if re.fullmatch(r"[A-Za-z]{2}", raw):
            # Only if it is a real code. Passing an invented one through is
            # how "UK" reaches the catalog and is rejected there instead.
            exact = pycountry.countries.get(alpha_2=raw.upper())
            return exact.alpha_2 if exact else None

        found = pycountry.countries.get(name=raw) or pycountry.countries.get(
            common_name=raw) or pycountry.countries.get(official_name=raw)
        if found is None:
            matches = pycountry.countries.search_fuzzy(raw)
            found = matches[0] if matches else None
        return found.alpha_2 if found else None
    except Exception:  # noqa: BLE001 — an unknown place is not an error here
        logger.debug("codes: could not resolve country %r", raw)
        return None


def language_code(value: Optional[str]) -> Optional[str]:
    """An ISO 639-1 code, or None."""
    if not value or not str(value).strip():
        return None
    raw = str(value).strip()
    flat = raw.lower()
    if flat in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[flat]
    try:
        import pycountry

        if re.fullmatch(r"[A-Za-z]{2}", raw):
            exact = pycountry.languages.get(alpha_2=flat)
            return exact.alpha_2 if exact else None

        found = (pycountry.languages.get(name=raw)
                 or pycountry.languages.get(alpha_3=flat)
                 or pycountry.languages.get(alpha_2=flat))
        # Not every language has a two-letter code; the catalog takes 639-1
        # only, so one that does not is left undetermined.
        return getattr(found, "alpha_2", None) if found else None
    except Exception:  # noqa: BLE001
        logger.debug("codes: could not resolve language %r", raw)
        return None

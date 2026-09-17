"""The catalog's licence vocabulary, and how to get a value into it.

The catalog accepts a fixed enum. A licence is read off a web page by a
model, though, and what a page says is "CC BY-NC-SA 4.0" — with spaces,
which is not a member. That value was stored on the proposal exactly as
written and only found out at the end, when the create call was rejected and
an approved integration stopped with a validation error nobody could act on.

So normalising happens where the value is first recorded, and again where it
is sent. Neither place is allowed to invent a licence: anything that cannot
be recognised becomes `None`, which the catalog accepts and which means
undetermined, rather than a guess that reads as established.
"""
from __future__ import annotations

import re
from typing import Optional

#: Exactly the catalog's `LicenseId`. Anything not in here is refused by the
#: API, so it is refused here first, where the message can be useful.
CATALOG_LICENCES = {
    "MIT", "Apache-2.0", "GPL-3.0", "CC-BY-4.0", "CC-BY-SA-4.0", "Proprietary",
    "CCBYNCSA", "CCBYNC", "CCBYNCND", "CCBYSA", "CCBY", "CC0", "mit", "gpl",
    "publisher-specific-oa", "public-domain", "pd", "unspecified-oa",
    "other-oa", "implied-oa", "publisher-specific, author manuscript",
    "elsevier-specific: oa user license",
}

#: Ordered longest-first: `by-nc-sa` has to be tried before `by-nc`, or every
#: ShareAlike licence is recorded as merely NonCommercial.
_FORMS = (
    (r"^cc.?by.?nc.?nd", "CCBYNCND"),
    (r"^cc.?by.?nc.?sa", "CCBYNCSA"),
    (r"^cc.?by.?sa.?4", "CC-BY-SA-4.0"),
    (r"^cc.?by.?nc", "CCBYNC"),
    (r"^cc.?by.?sa", "CCBYSA"),
    (r"^cc.?by.?4", "CC-BY-4.0"),
    (r"^cc.?by", "CCBY"),
    (r"^cc.?zero|^cc0", "CC0"),
    (r"^public.?domain", "public-domain"),
    (r"^apache", "Apache-2.0"),
    (r"^gpl.?3", "GPL-3.0"),
    (r"^mit$", "MIT"),
    (r"^proprietary", "Proprietary"),
)

#: Phrases that can appear anywhere in the value rather than at its start.
#: `re.match` anchors, so "© 2024 Elsevier, all rights reserved" matched
#: nothing and came back undetermined — which is safe but less useful than
#: the truth, since Proprietary is exactly what it says.
_ANYWHERE = ((r"all-rights-reserved", "Proprietary"),)


def normalise_licence(value: Optional[str]) -> Optional[str]:
    """A catalog licence id, or None when it cannot be recognised.

    None is a real answer here and not a failure: the catalog takes it, the
    console shows the source as undetermined, and a curator is asked for a
    reason before anything is copied in. A wrong id would do none of that.
    """
    if not value or not str(value).strip():
        return None
    raw = str(value).strip()
    if raw in CATALOG_LICENCES:
        return raw

    # Punctuation and case carry no meaning here: "CC BY-NC-SA 4.0",
    # "cc_by_nc_sa_4.0" and "CCBYNCSA" are one licence written three ways.
    flat = re.sub(r"[\s_/]+", "-", raw.lower()).strip("-")
    for pattern, licence in _FORMS:
        if re.match(pattern, flat):
            return licence
    for pattern, licence in _ANYWHERE:
        if re.search(pattern, flat):
            return licence
    return None

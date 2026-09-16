"""Profiling a food composition table, rather than ingesting it.

Worth being clear about why this is not an extractor, because the plan
originally called for one. `FCTable` in this catalog is a **metadata entity**:
compiling institution, nutrient coverage, number of entries, completeness,
units. There is no row-level store behind it — no entries sub-resource, no
bulk endpoint, nothing in the gateway or the console. An FCT here is a
registered *reference to* a food composition table, not a copy of its data.

So building a table extractor would produce thousands of rows with nowhere to
put them. What is genuinely missing is the thing a curator otherwise does by
hand: opening a five-thousand-row spreadsheet to count its entries, list its
nutrient columns, and judge how complete it is. That is arithmetic, and it is
what this does.

Everything here is reported as *observed*, never as decided. A column named
`Energy (kcal)` is evidence that the table covers energy in kilocalories; it
is not a guarantee, and a curator reviewing the proposal can see the column
names it was read from.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class TableProfileError(RuntimeError):
    """The file could not be read as a table."""


#: Nutrient names as they actually appear in food composition tables, mapped
#: to the canonical name. Deliberately a lookup of substrings rather than a
#: clever matcher: these files are produced by dozens of institutes over
#: decades, and a rule general enough to catch them all catches everything.
NUTRIENT_PATTERNS: Tuple[Tuple[str, str], ...] = (
    # Ordered most specific first, because the first match wins and a column
    # named "Saturated fat (g)" contains "fat". Two-letter element symbols
    # (Mg, Fe, Na, K) are deliberately absent: they collide with the units the
    # same column names carry, and "Vitamin C (mg)" read as magnesium is worse
    # than "Fe" alone going unrecognised.
    (r"saturat", "saturated fat"),
    (r"monounsaturat", "monounsaturated fat"),
    (r"polyunsaturat", "polyunsaturated fat"),
    (r"trans[- ]?fat", "trans fat"),
    (r"cholesterol", "cholesterol"),
    (r"vitamin\s*b\s*12|cobalamin", "vitamin B12"),
    (r"vitamin\s*b\s*6|pyridoxin", "vitamin B6"),
    (r"vitamin\s*b\s*1\b|thiamin", "thiamin"),
    (r"vitamin\s*b\s*2\b|riboflavin", "riboflavin"),
    (r"vitamin\s*b\s*3\b|\bniacin\b", "niacin"),
    (r"vitamin\s*a\b|retinol", "vitamin A"),
    (r"vitamin\s*c\b|ascorb", "vitamin C"),
    (r"vitamin\s*d\b|calciferol", "vitamin D"),
    (r"vitamin\s*e\b|tocopherol", "vitamin E"),
    (r"vitamin\s*k\b|phylloquinone", "vitamin K"),
    (r"\bfolate\b|folic", "folate"),
    (r"\bsugar", "sugars"),
    (r"\bstarch", "starch"),
    (r"fibre|fiber", "fibre"),
    (r"carbohydrate|\bcarbs?\b", "carbohydrate"),
    (r"\benergy\b|\bkcal\b|\bkj\b|calorie", "energy"),
    (r"\bprotein", "protein"),
    (r"\bfat\b|\bfats\b|\blipid", "fat"),
    (r"\bwater\b|moisture", "water"),
    (r"\bash\b", "ash"),
    (r"\balcohol\b|ethanol", "alcohol"),
    (r"\bsalt\b", "salt"),
    (r"\bsodium\b", "sodium"),
    (r"\bpotassium\b", "potassium"),
    (r"\bcalcium\b", "calcium"),
    (r"\bmagnesium\b", "magnesium"),
    (r"\bphosphor", "phosphorus"),
    (r"\biron\b", "iron"),
    (r"\bzinc\b", "zinc"),
    (r"\bcopper\b", "copper"),
    (r"\bselenium\b", "selenium"),
    (r"\biodine\b", "iodine"),
    (r"\bmanganese\b", "manganese"),
)

#: Columns that name the food rather than measure it.
IDENTITY_PATTERNS = (
    r"food\s*(name|item|description)", r"\bdescription\b", r"\bfoodname\b",
    r"\bname\b", r"\bitem\b", r"\bfood\b", r"\bcode\b", r"\bid\b",
    r"group", r"category", r"scientific", r"\bsource\b", r"\blang",
)

UNIT_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"\bkcal\b", "kcal"), (r"\bkj\b", "kJ"),
    (r"\bmcg\b|\bµg\b|\bug\b", "µg"), (r"\bmg\b", "mg"), (r"\bg\b", "g"),
    (r"\biu\b", "IU"), (r"\bml\b", "ml"), (r"%", "%"),
)

#: Per how much — the reference portion a table reports against.
PORTION_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"per\s*100\s*g|/\s*100\s*g|100g", "per 100 g"),
    (r"per\s*100\s*ml|/\s*100\s*ml", "per 100 ml"),
    (r"per\s*serving|per\s*portion", "per serving"),
    (r"edible\s*portion|\bep\b", "edible portion"),
)


def _match(text: str, patterns) -> Optional[str]:
    lowered = text.lower()
    for pattern, name in patterns:
        if re.search(pattern, lowered):
            return name
    return None


def _read(path: Path):
    """The table, as a DataFrame. Whatever the institute happened to ship."""
    import pandas

    suffix = path.suffix.lower()
    try:
        if suffix in (".csv", ".tsv", ".txt"):
            # Separator sniffed rather than assumed: European tables are
            # routinely semicolon-separated because the decimal mark is a comma.
            return pandas.read_csv(path, sep=None, engine="python",
                                   dtype=str, nrows=100_000)
        if suffix in (".xlsx", ".xls", ".ods"):
            frame = pandas.read_excel(path, dtype=str)
            return frame
    except ImportError as exc:  # pragma: no cover - deployment shape
        raise TableProfileError(
            f"reading {suffix} files needs a library this deployment does not "
            f"have ({exc})") from exc
    except Exception as exc:  # noqa: BLE001
        raise TableProfileError(f"that file could not be read as a table: {exc}"[:300]) from exc
    raise TableProfileError(
        f"{suffix or 'that file'} is not a table this can read; CSV, TSV, XLSX, "
        f"XLS and ODS are")


def profile_table(path: str) -> Dict[str, Any]:
    """Read a food composition table and describe it.

    Returns the descriptive fields an `FCTable` carries, plus the column names
    the judgement was made from — so a curator can disagree with it.
    """
    frame = _read(Path(path))
    if frame is None or frame.empty:
        raise TableProfileError("that table has no rows")

    columns = [str(c).strip() for c in frame.columns]
    nutrients: List[str] = []
    nutrient_columns: List[str] = []
    identity_columns: List[str] = []
    units: List[str] = []
    portions: List[str] = []

    for column in columns:
        if _match(column, ((p, p) for p in IDENTITY_PATTERNS)):
            identity_columns.append(column)
            continue
        nutrient = _match(column, NUTRIENT_PATTERNS)
        if nutrient:
            nutrient_columns.append(column)
            if nutrient not in nutrients:
                nutrients.append(nutrient)
            unit = _match(column, UNIT_PATTERNS)
            if unit and unit not in units:
                units.append(unit)
        portion = _match(column, PORTION_PATTERNS)
        if portion and portion not in portions:
            portions.append(portion)

    entries = int(len(frame))
    filled_per_row: List[int] = []
    if nutrient_columns:
        subset = frame[nutrient_columns]
        counts = subset.notna().sum(axis=1)
        filled_per_row = [int(v) for v in counts.tolist()]

    total_cells = entries * len(nutrient_columns)
    filled = sum(filled_per_row)
    completeness = round(100.0 * filled / total_cells, 1) if total_cells else None

    return {
        "number_of_entries": entries,
        "nutrient_coverage": nutrients,
        "min_nutrients_per_item": min(filled_per_row) if filled_per_row else None,
        "max_nutrients_per_item": max(filled_per_row) if filled_per_row else None,
        "completeness_percent": completeness,
        "completeness_description": (
            f"{filled:,} of {total_cells:,} nutrient cells carry a value across "
            f"{entries:,} entries and {len(nutrient_columns)} nutrient columns"
            if total_cells else "no nutrient columns were recognised"),
        "measurement_units": units,
        "reference_portions": portions,
        # The evidence, so the profile can be argued with rather than trusted.
        "columns": columns[:200],
        "nutrient_columns": nutrient_columns[:200],
        "identity_columns": identity_columns[:50],
    }

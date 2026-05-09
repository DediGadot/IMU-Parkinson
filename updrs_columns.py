"""Helpers for resolving MDS-UPDRS-III item columns across naming variants."""
from __future__ import annotations

import re


_SIDE_ALIASES = {
    "a": ["a", "r", "right"],
    "b": ["b", "l", "left"],
    "c": ["c"],
    "d": ["d"],
    "e": ["e"],
}

_ITEM_SPECIFIC_ALIASES = {
    3: {
        "a": ["neck"],
        "b": ["rue", "rightupper"],
        "c": ["lue", "leftupper"],
        "d": ["rle", "rightlower"],
        "e": ["lle", "leftlower"],
    },
    17: {
        "a": ["rue", "rightupper"],
        "b": ["lue", "leftupper"],
        "c": ["rle", "rightlower"],
        "d": ["lle", "leftlower"],
        "e": ["lipjaw", "lip", "jaw"],
    },
}

UPDRS_PART3_ITEM_TOTAL_MAX = {
    1: 4,
    2: 4,
    3: 20,
    4: 8,
    5: 8,
    6: 8,
    7: 8,
    8: 8,
    9: 4,
    10: 4,
    11: 4,
    12: 4,
    13: 4,
    14: 4,
    15: 8,
    16: 8,
    17: 20,
    18: 4,
}


def normalize_updrs_column(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def candidate_updrs_columns(item_num: int, suffix: str | None = None) -> list[str]:
    base = f"MDSUPDRS_3-{item_num}"
    if suffix is None:
        return [base]

    suffix = str(suffix).lower()
    suffix_tokens = {suffix}
    suffix_tokens.update(_SIDE_ALIASES.get(suffix, []))
    suffix_tokens.update(_ITEM_SPECIFIC_ALIASES.get(item_num, {}).get(suffix, []))

    candidates = []
    for token in sorted(suffix_tokens):
        candidates.extend(
            [
                f"{base}{token}",
                f"{base}-{token}",
                f"{base}_{token}",
                f"{base} {token}",
            ]
        )
    return candidates


def valid_updrs_item_total(item_num: int, value):
    """Return a valid Part III item total, or None for invalid/missing values."""
    try:
        import pandas as pd  # local import to keep this helper lightweight

        numeric = pd.to_numeric(value, errors="coerce")
    except Exception:
        numeric = value
    if numeric is None or numeric != numeric:
        return None
    numeric = float(numeric)
    max_value = UPDRS_PART3_ITEM_TOTAL_MAX.get(int(item_num))
    if max_value is None:
        return numeric
    if numeric < 0.0 or numeric > float(max_value):
        return None
    return numeric


def find_updrs_value(row, columns, item_num: int, suffix: str | None = None):
    lookup = {normalize_updrs_column(col): col for col in columns}
    for candidate in candidate_updrs_columns(item_num, suffix):
        resolved = lookup.get(normalize_updrs_column(candidate))
        if resolved is None:
            continue
        value = row.get(resolved)
        try:
            import pandas as pd  # local import to keep this helper lightweight

            numeric = pd.to_numeric(value, errors="coerce")
        except Exception:
            numeric = value
        if numeric is not None and numeric == numeric:
            numeric = float(numeric)
            # Raw MDS-UPDRS Part III subitem scores are coded 0-4. Combined
            # item totals have item-specific maxima. The dataset contains at
            # least one `9` missing/untestable code; do not treat it as severity.
            if suffix is not None:
                if numeric < 0.0 or numeric > 4.0:
                    return None
            elif valid_updrs_item_total(item_num, numeric) is None:
                return None
            return numeric
    return None

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
            return float(numeric)
    return None

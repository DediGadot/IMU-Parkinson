"""Audit T1 iter34 auxiliary-chain labels for invalid MDS-UPDRS item totals.

The iter34 T1 candidate reports T1 = items 9-14, but its RegressorChain also
uses auxiliary item targets 15 and 18. The iter47 T3 audit found NLS036 has raw
item-15 subparts coded 9/9, which per_item_scores.json had summed to item15=18.
This script checks whether that stale auxiliary label affects the iter34 cohort.

This is an audit only. It does not fit a model or create a new T1 headline.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import PER_ITEM_CACHE, T1_ITEMS, V2_FEATURES, is_pd
from run_t1_iter33b_8item_chain import AUX_ITEMS, T1_SUM_ITEMS
from updrs_columns import UPDRS_PART3_ITEM_TOTAL_MAX, valid_updrs_item_total


ITEM_TOTAL_MAX = UPDRS_PART3_ITEM_TOTAL_MAX


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _valid_total(item: int, value: Any) -> float:
    valid_value = valid_updrs_item_total(item, value)
    if valid_value is None:
        return float("nan")
    return float(valid_value)


def _load_raw_per_item() -> dict[str, dict[str, Any]]:
    with open(PER_ITEM_CACHE, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_validated_per_item() -> dict[str, dict[int, float]]:
    raw = _load_raw_per_item()
    out: dict[str, dict[int, float]] = {}
    for sid, scores in raw.items():
        per_item: dict[int, float] = {}
        for key, value in scores.items():
            if str(key).startswith("("):
                continue
            try:
                item = int(key)
            except ValueError:
                continue
            if item in ITEM_TOTAL_MAX:
                per_item[item] = _valid_total(item, value)
        out[str(sid)] = per_item
    return out


def _invalid_top_level_rows(pd_sids: set[str]) -> list[dict[str, Any]]:
    raw = _load_raw_per_item()
    rows: list[dict[str, Any]] = []
    for sid in sorted(pd_sids):
        scores = raw.get(sid, {})
        for item, max_value in ITEM_TOTAL_MAX.items():
            if str(item) not in scores:
                continue
            value = _as_float(scores[str(item)])
            if np.isfinite(value) and (value < 0.0 or value > max_value):
                rows.append(
                    {
                        "sid": sid,
                        "item": item,
                        "value": value,
                        "valid_min": 0.0,
                        "valid_max": float(max_value),
                    }
                )
    return rows


def _subpart_context(sid: str, item: int) -> dict[str, Any]:
    scores = _load_raw_per_item().get(sid, {})
    prefix = f"({item},"
    return {key: value for key, value in scores.items() if str(key).startswith(prefix)}


def _stale_t1_and_chain_cohorts() -> dict[str, Any]:
    """Reconstruct the historical unvalidated loader used by iter34 artifacts."""
    df = pd.read_csv(V2_FEATURES)
    raw = _load_raw_per_item()

    t1_sids: list[str] = []
    chain_sids: list[str] = []
    for _, row in df.iterrows():
        sid = str(row["sid"])
        if not is_pd(sid):
            continue
        scores = raw.get(sid)
        if not scores:
            continue
        if not all(str(item) in scores and np.isfinite(_as_float(scores[str(item)])) for item in T1_ITEMS):
            continue
        t1_sids.append(sid)
        if all(str(item) in scores and np.isfinite(_as_float(scores[str(item)])) for item in AUX_ITEMS):
            chain_sids.append(sid)

    return {
        "current_t1_sids": sorted(t1_sids),
        "current_chain_sids": sorted(chain_sids),
    }


def _validated_t1_and_chain_cohorts() -> dict[str, Any]:
    df = pd.read_csv(V2_FEATURES)
    raw_valid = _load_validated_per_item()

    t1_sids: list[str] = []
    chain_sids: list[str] = []
    sid_items: dict[str, dict[int, float]] = {}
    for _, row in df.iterrows():
        sid = str(row["sid"])
        if not is_pd(sid):
            continue
        item_values = raw_valid.get(sid)
        if not item_values:
            continue
        if not all(np.isfinite(item_values.get(item, float("nan"))) for item in T1_ITEMS):
            continue
        t1_sids.append(sid)
        sid_items[sid] = item_values
        if all(np.isfinite(item_values.get(item, float("nan"))) for item in AUX_ITEMS):
            chain_sids.append(sid)

    return {
        "validated_t1_sids": sorted(t1_sids),
        "validated_chain_sids": sorted(chain_sids),
        "sid_items": sid_items,
    }


def main() -> None:
    ensure_dir(RESULTS_DIR)
    df = pd.read_csv(V2_FEATURES)
    pd_sids = {str(sid) for sid in df["sid"] if is_pd(str(sid))}
    invalid_rows = _invalid_top_level_rows(pd_sids)
    current = _stale_t1_and_chain_cohorts()
    validated = _validated_t1_and_chain_cohorts()

    current_chain = set(current["current_chain_sids"])
    valid_chain = set(validated["validated_chain_sids"])
    current_t1 = set(current["current_t1_sids"])
    valid_t1 = set(validated["validated_t1_sids"])

    invalid_by_sid_item = {(row["sid"], int(row["item"])): row for row in invalid_rows}
    affected_chain_invalid = []
    for sid in sorted(current_chain):
        for item in AUX_ITEMS:
            row = invalid_by_sid_item.get((sid, item))
            if row is not None:
                affected_chain_invalid.append({**row, "subparts": _subpart_context(sid, item)})

    invalid_t1_target_items = [
        row for row in invalid_rows if row["sid"] in current_t1 and int(row["item"]) in T1_SUM_ITEMS
    ]

    payload = {
        "audit": "t1_iter48_aux_validrange",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_cache": str(PER_ITEM_CACHE),
        "item_total_valid_ranges": ITEM_TOTAL_MAX,
        "current_loader": {
            "t1_n": len(current_t1),
            "chain_n": len(current_chain),
            "chain_filter": "historical non-missing items 9-14 plus auxiliary items 15 and 18 using unvalidated per_item_scores.json totals",
        },
        "validated_loader": {
            "t1_n": len(valid_t1),
            "chain_n": len(valid_chain),
            "chain_filter": "same, but top-level item totals outside valid item range are treated as missing",
        },
        "cohort_deltas": {
            "current_chain_minus_validated_chain": sorted(current_chain - valid_chain),
            "validated_chain_minus_current_chain": sorted(valid_chain - current_chain),
            "current_t1_minus_validated_t1": sorted(current_t1 - valid_t1),
            "validated_t1_minus_current_t1": sorted(valid_t1 - current_t1),
        },
        "invalid_top_level_item_totals_among_pd_sids": invalid_rows,
        "invalid_t1_target_items_in_current_t1_cohort": invalid_t1_target_items,
        "invalid_auxiliary_items_in_current_chain_cohort": affected_chain_invalid,
        "interpretation": {
            "primary_t1_target_valid": len(invalid_t1_target_items) == 0,
            "iter34_auxiliary_chain_uses_invalid_label": len(affected_chain_invalid) > 0,
            "recommended_status": "document_only_no_posthoc_rerun_future_loader_fail_closed",
            "consult_decision": (
                "Primary T1 target items are clean, and the invalid code affects only an "
                "auxiliary chain label in a non-canonical candidate. Do not run a post-hoc "
                "N=92 lockbox; document the caveat and make future loaders fail closed."
            ),
        },
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"t1_iter48_aux_validrange_audit_{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    stable_out = RESULTS_DIR / "t1_iter48_aux_validrange_audit.json"
    with open(stable_out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"Wrote {out}")
    print(f"Wrote {stable_out}")
    print(
        "current_chain_n={current} validated_chain_n={validated} affected={affected}".format(
            current=len(current_chain),
            validated=len(valid_chain),
            affected=payload["cohort_deltas"]["current_chain_minus_validated_chain"],
        )
    )


if __name__ == "__main__":
    main()

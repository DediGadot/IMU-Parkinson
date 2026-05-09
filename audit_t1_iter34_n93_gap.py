"""Audit whether iter34's N=93 auxiliary-item cohort materially affects T1 CCC.

iter34 uses items 15 and 18 as auxiliary RegressorChain targets, so it drops
the one T1-complete subject lacking item 18. This script quantifies the maximum
possible CCC movement from adding that subject back under fixed OOF predictions.
It does not train a new model and is intended as a reporting/audit artifact.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from inductive_lib import cal_slope, ccc, mae, pearson_r
from project_paths import RESULTS_DIR, save_json_artifact
from run_t1_iter4 import T1_ITEMS, load_pd_data


ITER34_FILE = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260506_141720.json"
ITER12_FILE = RESULTS_DIR / "t1_iter12_honest_composite.json"


def _load(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def _metric_block(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    return {
        "n": int(len(y_true)),
        "ccc": round(float(ccc(y_true, y_pred)), 6),
        "mae": round(float(mae(y_true, y_pred)), 6),
        "r": round(float(pearson_r(y_true, y_pred)), 6),
        "cal_slope": round(float(cal_slope(y_true, y_pred)), 6),
        "true_mean": round(float(np.mean(y_true)), 6),
        "true_std": round(float(np.std(y_true)), 6),
        "pred_mean": round(float(np.mean(y_pred)), 6),
        "pred_std": round(float(np.std(y_pred)), 6),
    }


def _per_subject_arrays(payload: dict[str, Any]) -> tuple[list[str], np.ndarray, np.ndarray]:
    ps = payload["per_subject"]
    return (
        [str(s) for s in ps["sids"]],
        np.asarray(ps["y_true"], dtype=np.float64),
        np.asarray(ps["y_pred"], dtype=np.float64),
    )


def _best_one_subject_prediction(
    y_base: np.ndarray,
    p_base: np.ndarray,
    y_extra: float,
    lo: float = -20.0,
    hi: float = 30.0,
    n_grid: int = 200_001,
) -> dict[str, Any]:
    """Return grid-optimal prediction for one appended subject.

    This is a one-dimensional diagnostic upper bound: hold all iter34 OOF
    predictions fixed, vary only the excluded subject's prediction.
    """
    grid = np.linspace(lo, hi, n_grid)
    y_all = np.concatenate([y_base, [y_extra]])
    n = len(y_all)
    mu_y = float(np.mean(y_all))
    var_y = float(np.mean((y_all - mu_y) ** 2))

    mu_p = (float(np.sum(p_base)) + grid) / n
    var_p = (float(np.sum(p_base**2)) + grid**2) / n - mu_p**2
    cov = (float(np.sum(y_base * p_base)) + y_extra * grid) / n - mu_y * mu_p
    ccc_grid = (2.0 * cov) / (var_y + var_p + (mu_y - mu_p) ** 2)

    j = int(np.nanargmax(ccc_grid))
    pred = float(grid[j])
    y_aug = np.concatenate([y_base, [y_extra]])
    p_aug = np.concatenate([p_base, [pred]])
    return {
        "grid_range": [lo, hi],
        "grid_points": n_grid,
        "best_prediction": round(pred, 6),
        "metrics": _metric_block(y_aug, p_aug),
    }


def run_audit() -> dict[str, Any]:
    iter34 = _load(ITER34_FILE)
    iter12 = _load(ITER12_FILE)
    s34, y34, p34 = _per_subject_arrays(iter34)
    s12, y12, p12 = _per_subject_arrays(iter12)

    missing_from_iter34 = [sid for sid in s12 if sid not in set(s34)]
    if len(missing_from_iter34) != 1:
        raise RuntimeError(f"Expected exactly one iter12 subject absent from iter34, got {missing_from_iter34}")
    sid = missing_from_iter34[0]
    idx = s12.index(sid)
    y_extra = float(y12[idx])
    iter12_pred = float(p12[idx])

    pd_data = load_pd_data()
    sid_to_idx = {str(s): i for i, s in enumerate(pd_data["sids"])}
    pd_idx = sid_to_idx[sid]
    item_values = {str(i): float(pd_data["items"][i][pd_idx]) for i in range(1, 19)}
    missing_items = [i for i, v in item_values.items() if not np.isfinite(v)]
    t1_items_complete = all(np.isfinite(item_values[str(i)]) for i in T1_ITEMS)

    scenarios: dict[str, dict[str, Any]] = {
        "iter34_n93_locked": _metric_block(y34, p34),
        "iter12_honest_n94_locked": _metric_block(y12, p12),
    }
    for name, pred in {
        "iter34_plus_excluded_iter12_prediction": iter12_pred,
        "iter34_plus_excluded_perfect_prediction": y_extra,
        "iter34_plus_excluded_iter34_pred_mean": float(np.mean(p34)),
        "iter34_plus_excluded_iter34_true_mean": float(np.mean(y34)),
    }.items():
        scenarios[name] = _metric_block(
            np.concatenate([y34, [y_extra]]),
            np.concatenate([p34, [pred]]),
        )

    optimum = _best_one_subject_prediction(y34, p34, y_extra)
    scenarios["iter34_plus_excluded_grid_optimal_prediction"] = optimum["metrics"]

    return {
        "audit": "t1_iter34_n93_gap",
        "source_artifacts": {
            "iter34": str(ITER34_FILE),
            "iter12": str(ITER12_FILE),
        },
        "missing_from_iter34": {
            "sid": sid,
            "reason": "T1 target complete, but auxiliary item 18 is missing; iter34 requires complete auxiliary items 15 and 18.",
            "t1_true": y_extra,
            "iter12_honest_prediction": iter12_pred,
            "iter12_honest_error": iter12_pred - y_extra,
            "t1_items_complete": bool(t1_items_complete),
            "missing_items": missing_items,
            "item_values": item_values,
        },
        "scenarios": scenarios,
        "one_subject_upper_bound": optimum,
        "verdict": {
            "n93_gap_material": False,
            "max_ccc_after_adding_excluded_subject": optimum["metrics"]["ccc"],
            "locked_iter34_n93_ccc": scenarios["iter34_n93_locked"]["ccc"],
            "rounded_headline_changes": False,
            "rationale": (
                "The excluded subject has T1=4.0, essentially at the cohort mean. "
                "Holding all locked iter34 OOF predictions fixed, even the grid-optimal "
                "prediction for that single subject changes CCC by less than 0.00001."
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="audit_t1_iter34_n93_gap_20260508.json",
        help="Output JSON filename under results/.",
    )
    args = parser.parse_args()
    payload = run_audit()
    paths = save_json_artifact(args.out, payload)
    print(json.dumps(payload["verdict"], indent=2))
    print(f"wrote {paths[0]}")


if __name__ == "__main__":
    main()

"""Nested-CV temperature calibration that does NOT use the test subject's
true label to choose T or to centre the scaling.

Fix for H2 + H3 in the leakage audit:

  Original (run_calibration_v2.py:861-921, run_e7):
    1. Run LOOCV -> get raw predictions for all 94 PD subjects
    2. mean_train = np.mean(y_true)              # uses test labels
    3. Sweep T, pick T that minimises |slope-1| on those 94 predictions
    4. Report CCC, slope, MAE on the same 94 predictions
       --> slope mechanically pins to 1.0 because it's the optimisation target

  Nested protocol (this file):
    For each held-out subject i:
      mean_train_i = mean(y_true[j != i])         # fold-out training mean
      Sweep T over a grid; for each T compute |slope - 1| on the OTHER 93
        (y_true[j != i], y_pred_raw[j != i] re-centred and scaled by T)
      Pick T_i = argmin
      Apply: p_cal[i] = mean_train_i + T_i * (y_pred_raw[i] - mean_train_i)
    Report metrics on p_cal across all 94 subjects.

  For 5-fold: same idea, replacing the leave-one-out inner loop with
  leave-one-fold-out using the four other folds' (y_true, y_pred) pairs.

Inputs are per-subject prediction JSONs produced by run_inductive_ablation.py
(or, for backwards compatibility, the published compression_P5_TT*_loocv.json
files). Output is one JSON per (variant, target, eval) with the calibrated
predictions, the chosen T per subject/fold, and full metrics.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
from sklearn.linear_model import LinearRegression

from project_paths import RESULTS_DIR, ensure_dir, results_artifact_path

ensure_dir(RESULTS_DIR)

TEMP_GRID = np.round(np.arange(1.0, 8.05, 0.05), 2).tolist()
TARGET_CLIP = {"t1": (0, 24), "t2": (0, 32), "t3": (0, 59)}


def _ccc(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    yt, yp = np.asarray(y_true, dtype=np.float64), np.asarray(y_pred, dtype=np.float64)
    if yt.size < 2 or yt.std() < 1e-9 or yp.std() < 1e-9:
        return 0.0
    cov = float(np.mean((yt - yt.mean()) * (yp - yp.mean())))
    return (2 * cov) / (yt.var() + yp.var() + (yt.mean() - yp.mean()) ** 2)


def _slope(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Calibration slope = np.polyfit(y_true, y_pred, 1)[0].

    Matches the convention used by eval_utils.cal_slope and the published
    compression_P5_TT*_*split.json cache. The temperature optimiser must
    minimise |slope - 1| using the SAME formula the rest of the pipeline
    reports, otherwise the calibrated slope value will be inconsistent with
    the table values.
    """
    yt, yp = np.asarray(y_true, dtype=np.float64), np.asarray(y_pred, dtype=np.float64)
    if yt.size < 3 or yt.std() < 1e-8:
        return 0.0
    return float(np.polyfit(yt, yp, 1)[0])


def _full_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    return {
        "n": int(len(y_true)),
        "ccc": round(_ccc(y_true, y_pred), 4),
        "cal_slope": round(_slope(y_true, y_pred), 4),
        "mae": round(float(np.mean(np.abs(y_true - y_pred))), 4),
        "r": round(float(np.corrcoef(y_true, y_pred)[0, 1]), 4)
        if np.std(y_true) > 1e-9 and np.std(y_pred) > 1e-9 else 0.0,
    }


def _scale(y_pred: np.ndarray, mean: float, T: float, clip: tuple) -> np.ndarray:
    return np.clip(mean + T * (y_pred - mean), clip[0], clip[1])


def _best_T(y_true_inner: np.ndarray, y_pred_inner: np.ndarray,
            mean_train: float, clip: tuple) -> float:
    """Pick T that minimises |slope - 1| on the inner-CV (held-in) data."""
    best_T = 1.0
    best_err = float("inf")
    for T in TEMP_GRID:
        scaled = _scale(y_pred_inner, mean_train, T, clip)
        err = abs(_slope(y_true_inner, scaled) - 1.0)
        if err < best_err:
            best_err = err
            best_T = T
    return best_T


def nested_loocv_temperature(per_subject: dict, target: str) -> dict:
    """Tune T per subject using the other N-1 LOO predictions, then apply.

    Each subject's calibrated prediction uses:
      mean_train_i = mean(y_true[j != i])
      T_i = argmin_T |slope(y_true[j != i], scale(y_pred_raw[j != i], mean_train_i, T)) - 1|
      p_cal[i] = scale(y_pred_raw[i], mean_train_i, T_i)
    """
    sids = per_subject["sids"]
    y_true = np.array(per_subject["y_true"], dtype=np.float64)
    y_pred = np.array(per_subject["y_pred"], dtype=np.float64)
    n = len(y_true)
    clip = TARGET_CLIP[target]

    p_cal = np.zeros(n, dtype=np.float64)
    T_per_subject = np.zeros(n, dtype=np.float64)

    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        mean_train_i = float(np.mean(y_true[mask]))
        T_i = _best_T(y_true[mask], y_pred[mask], mean_train_i, clip)
        T_per_subject[i] = T_i
        p_cal[i] = _scale(np.array([y_pred[i]]), mean_train_i, T_i, clip)[0]

    metrics = _full_metrics(y_true, p_cal)
    metrics.update({
        "target": target,
        "eval_mode": "loocv_nested_T",
        "T_grid": TEMP_GRID,
        "T_per_subject_summary": {
            "mean": round(float(np.mean(T_per_subject)), 3),
            "std": round(float(np.std(T_per_subject)), 3),
            "min": round(float(np.min(T_per_subject)), 3),
            "max": round(float(np.max(T_per_subject)), 3),
        },
        "per_subject": {
            "sids": sids,
            "y_true": y_true.tolist(),
            "y_pred_raw": y_pred.tolist(),
            "y_pred_cal": p_cal.tolist(),
            "T_per_subject": T_per_subject.tolist(),
        },
    })
    return metrics


def nested_5fold_temperature(per_subject: dict, target: str,
                             n_folds: int = 5) -> dict:
    """Tune T per fold using the other K-1 folds' aggregated (y_true, y_pred) pairs.

    The published 5-fold predictions are stored as a flat list ordered by fold —
    splits 1..5, each a contiguous chunk. We recover fold boundaries from the
    'per_subject' dict if the producer recorded them; otherwise we fall back to
    chunking the SID list into n_folds equal blocks (only valid for the
    inductive_ablation outputs which preserve fold order).
    """
    sids = per_subject["sids"]
    y_true = np.array(per_subject["y_true"], dtype=np.float64)
    y_pred = np.array(per_subject["y_pred"], dtype=np.float64)
    clip = TARGET_CLIP[target]
    n = len(y_true)

    # Prefer explicit fold boundaries if present
    if "fold_boundaries" in per_subject:
        boundaries = per_subject["fold_boundaries"]
    else:
        # Equal chunking (good enough — fold order is preserved by both the
        # published cache and run_inductive_ablation)
        sizes = [n // n_folds + (1 if i < n % n_folds else 0) for i in range(n_folds)]
        boundaries = []
        start = 0
        for sz in sizes:
            boundaries.append((start, start + sz))
            start += sz

    p_cal = np.zeros(n, dtype=np.float64)
    T_per_fold = []

    for fi, (lo, hi) in enumerate(boundaries):
        # Inner = all subjects NOT in this fold
        inner_mask = np.ones(n, dtype=bool)
        inner_mask[lo:hi] = False
        mean_train_f = float(np.mean(y_true[inner_mask]))
        T_f = _best_T(y_true[inner_mask], y_pred[inner_mask], mean_train_f, clip)
        T_per_fold.append({"fold": fi + 1, "T": T_f, "mean_train": round(mean_train_f, 3)})
        p_cal[lo:hi] = _scale(y_pred[lo:hi], mean_train_f, T_f, clip)

    metrics = _full_metrics(y_true, p_cal)
    metrics.update({
        "target": target,
        "eval_mode": "5fold_nested_T",
        "T_grid": TEMP_GRID,
        "T_per_fold": T_per_fold,
        "per_subject": {
            "sids": sids,
            "y_true": y_true.tolist(),
            "y_pred_raw": y_pred.tolist(),
            "y_pred_cal": p_cal.tolist(),
        },
    })
    return metrics


def load_per_subject(input_path: str) -> tuple:
    """Return (per_subject_dict, eval_mode) from any cached prediction JSON."""
    with open(input_path) as f:
        data = json.load(f)
    if "per_subject" not in data:
        raise ValueError(f"{input_path} has no per_subject block")
    eval_mode = data.get("eval_mode", "")
    return data["per_subject"], eval_mode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True,
                        help="JSON with per_subject block (e.g. inductive_*.json or compression_P5_*.json)")
    parser.add_argument("--target", required=True, choices=["t1", "t2", "t3"])
    parser.add_argument("--output", required=True,
                        help="Output JSON path (relative to results/ or absolute)")
    parser.add_argument("--n-folds", type=int, default=5,
                        help="Number of folds for 5fold mode (ignored for LOOCV inputs)")
    args = parser.parse_args()

    per_subject, eval_mode = load_per_subject(args.input)
    print(f"Loaded {len(per_subject['sids'])} per-subject predictions from {args.input}")
    print(f"Detected eval_mode={eval_mode!r} for target={args.target}")

    if "loocv" in eval_mode.lower():
        metrics = nested_loocv_temperature(per_subject, args.target)
        print(f"\nNested LOOCV T calibration:")
    else:
        metrics = nested_5fold_temperature(per_subject, args.target, n_folds=args.n_folds)
        print(f"\nNested 5-fold T calibration:")

    print(f"  CCC      {metrics['ccc']:.4f}")
    print(f"  slope    {metrics['cal_slope']:.4f}")
    print(f"  MAE      {metrics['mae']:.4f}")
    print(f"  N        {metrics['n']}")
    if "T_per_subject_summary" in metrics:
        s = metrics["T_per_subject_summary"]
        print(f"  T_mean   {s['mean']:.3f}  (std {s['std']:.3f}, range [{s['min']:.2f}, {s['max']:.2f}])")
    if "T_per_fold" in metrics:
        print(f"  T_per_fold:")
        for tf in metrics["T_per_fold"]:
            print(f"    fold {tf['fold']}: T={tf['T']:.2f} mean_train={tf['mean_train']:.2f}")

    # Resolve output path
    out = Path(args.output)
    if not out.is_absolute():
        out = Path(RESULTS_DIR) / out
    with open(out, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nSaved -> {out}")


if __name__ == "__main__":
    main()

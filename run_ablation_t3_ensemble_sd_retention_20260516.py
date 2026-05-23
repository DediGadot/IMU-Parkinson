#!/usr/bin/env python3
"""Ablation #9 — T3 y-free retention via ensemble-SD (alternative to Slot F CQR-width).

**MOTIVATION**: Slot F (CQR-width retention) gave T3 retained CCC@70%=0.4237 /
@50%=0.5370 (Wall #98). Seed-101 replication frac>full=0.929 < 0.95 promotion
gate. Hypothesis: CQR width has higher score-variance than ensemble-SD because
quantile heads (α=0.05/0.95) are less stable than point predictions. Replacing
the score with multi-seed ensemble SD may stabilize the retention.

**ARCHITECTURE**:
  - Per fold: train 5 LGB seeds on iter47 Stage-1-residual residual
  - Per-fold test subject: SD across 5 LGB predictions = y-free retention score
  - Retain bottom-X% by SD (low SD = high confidence)
  - Apply to iter47 POINT predictions (unchanged)

**Y-FREE**: SD is computed from features-only LGB predictions on test subject;
no y_test access. --sanity-y-nan mandatory.

**ORTHOGONALITY** to Slot F:
  - Slot F: width = q95(x) - q05(x), from quantile-loss LGB heads
  - This: SD = std(p_1(x), ..., p_5(x)), from 5 different-seed point predictors
  - Both are y-free; this has lower estimator variance at N=95

**Pre-registered gate**: retained-CCC @70%/50% > Slot F baseline (0.4237/0.5370)
AND frac>full ≥ 0.95 across 2 disjoint seed sets.

Fork of run_t3_slotF_cqr_width_conformal.py with score replacement.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from eval_utils import lins_ccc as ccc
from inductive_lib import FoldImputer, FoldNormalizer
from run_t3_iter47_invalid_code_fix import filter_cohort
from run_t3_iter41_target_fix import build_stage1_matrix, filter_stage2, fit_stage1

ITER47_SUBJ_PREDS_CSV = "results/iter47_invalidcode_subject_preds_20260508_194605.csv"
COVERAGES = [0.70, 0.50]
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20260516
N_TOP_K = 500
ENSEMBLE_SEEDS = [42, 1337, 7, 91011, 31415]

LGB_PARAMS = dict(
    n_estimators=300, num_leaves=15, learning_rate=0.05,
    min_data_in_leaf=5, reg_lambda=0.0, verbosity=-1, n_jobs=1,
    bagging_fraction=0.8, bagging_freq=5, feature_fraction=0.8,
)


def fold_local_univariate_topk(X_tr_n: np.ndarray, y_tr: np.ndarray, k: int) -> np.ndarray:
    Xs = X_tr_n - X_tr_n.mean(axis=0, keepdims=True)
    ys = y_tr - y_tr.mean()
    sx = np.nan_to_num(Xs.std(axis=0), nan=1e-9) + 1e-9
    sy = ys.std() + 1e-9
    cov = (Xs * ys[:, None]).mean(axis=0)
    corr = np.abs(cov / (sx * sy))
    corr = np.where(np.isnan(corr), 0.0, corr)
    return np.argsort(corr)[::-1][:k]


def compute_ensemble_sd_loocv(data: dict, seeds: list[int]) -> np.ndarray:
    """Per-subject ensemble SD of LGB point predictions (y-free at test time)."""
    sids = data["sids"]
    X = data["X"]
    feat_cols = data["feat_cols"]
    y = data["y_t3"]
    hy = data["hy"]
    n = len(sids)
    X_s2, _ = filter_stage2(X, feat_cols, "stage2_current")
    X_s1 = build_stage1_matrix(sids, hy)

    sds = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        s1_tr, s1_te = fit_stage1(X_s1[tr], y[tr], X_s1[i:i+1], alpha=1.0)
        resid_tr = y[tr] - s1_tr

        imp = FoldImputer.fit(X_s2[tr])
        Xt = imp.transform(X_s2[tr])
        Xv = imp.transform(X_s2[i:i+1])
        nrm = FoldNormalizer.fit(Xt)
        Xt = nrm.transform(Xt)
        Xv = nrm.transform(Xv)
        top500 = fold_local_univariate_topk(Xt, resid_tr, N_TOP_K)

        preds_seeds = []
        for s in seeds:
            params = dict(LGB_PARAMS)
            params["random_state"] = s
            m = lgb.LGBMRegressor(**params)
            m.fit(Xt[:, top500], resid_tr)
            preds_seeds.append(float(m.predict(Xv[:, top500])[0]))
        sds[i] = float(np.std(preds_seeds))
        if (i + 1) % 20 == 0:
            print(f"  fold {i+1}/{n}: ensemble_sd={sds[i]:.3f}")
    return sds


def retained_ccc_at_coverage(
    y: np.ndarray, yhat: np.ndarray, score: np.ndarray, coverage: float
) -> tuple[float, np.ndarray, int]:
    n = len(y)
    k = int(round(coverage * n))
    if k < 5:
        return float("nan"), np.zeros(n, dtype=bool), 0
    order = np.argsort(score, kind="stable")
    mask = np.zeros(n, dtype=bool)
    mask[order[:k]] = True
    return float(ccc(y[mask], yhat[mask])), mask, int(mask.sum())


def load_iter47_aligned(data: dict) -> np.ndarray:
    df = pd.read_csv(ITER47_SUBJ_PREDS_CSV)
    df = df[(df["cohort"] == "drop_allmissing_validrange") & (df["stage2_policy"] == "stage2_current")]
    sid_to_pred = dict(zip(df["sid"].astype(str), df["y_pred"].astype(float)))
    preds = np.array([sid_to_pred.get(str(s), np.nan) for s in data["sids"]])
    if np.isnan(preds).any():
        preds = np.where(np.isnan(preds), np.nanmean(preds), preds)
    return preds


def sanity_y_nan(data: dict, iter47_preds: np.ndarray, sds: np.ndarray):
    y = data["y_t3"]
    n = len(y)
    y_nan = np.full(n, np.nan)
    masks_real, masks_nan = {}, {}
    for cov in COVERAGES:
        _, mr, _ = retained_ccc_at_coverage(y, iter47_preds, sds, cov)
        _, mn, _ = retained_ccc_at_coverage(y_nan, iter47_preds, sds, cov)
        masks_real[f"cov_{int(cov*100)}"] = mr.tolist()
        masks_nan[f"cov_{int(cov*100)}"] = mn.tolist()
    all_match = all(masks_real[k] == masks_nan[k] for k in masks_real)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "name": "abstention_sanity_t3_ensemble_sd_retention",
        "created_at_utc": ts,
        "retention_rule_form": "g(x) = std(p_seed_1(x), ..., p_seed_5(x)) from LGB on Stage-1 residual, NO y_test",
        "n_subjects": n,
        "masks_identical_with_y_nan": all_match,
        "test_passes": all_match,
    }
    Path(f"results/abstention_sanity_ensemble_sd_{ts}.json").write_text(json.dumps(receipt, indent=2))
    print(f"[Sanity y_nan] all_match={all_match}")
    return all_match


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--null", choices=["", "scrambled_y"], default="")
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"\n=== Ablation #9 T3 y-free retention via ENSEMBLE-SD ({ts}) ===")
    data = filter_cohort("drop_allmissing_validrange")
    y = data["y_t3"]
    n = len(y)
    iter47_preds = load_iter47_aligned(data)
    full_ccc = float(ccc(y, iter47_preds))
    print(f"  N={n}, full-cohort iter47 CCC={full_ccc:.4f}")
    print(f"  null_mode={args.null or 'none'}, ensemble_seeds={ENSEMBLE_SEEDS}")

    if args.null == "scrambled_y":
        rng = np.random.default_rng(91011)
        perm = rng.permutation(n)
        y = y[perm]
        iter47_preds = iter47_preds[perm]
        data = {**data, "y_t3": y}
        print(f"  [NULL] permuted y + iter47_preds")

    print(f"  Computing ensemble-SD per subject (LOOCV)...")
    sds = compute_ensemble_sd_loocv(data, ENSEMBLE_SEEDS)
    print(f"  SD distribution: median={np.median(sds):.3f}, min={np.min(sds):.3f}, max={np.max(sds):.3f}")

    sanity_y_nan(data, iter47_preds, sds)

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    results = {}
    for cov in COVERAGES:
        retained_ccc, mask, n_ret = retained_ccc_at_coverage(y, iter47_preds, sds, cov)
        retained_mae = float(np.mean(np.abs(y[mask] - iter47_preds[mask])))
        delta_vs_full = retained_ccc - full_ccc

        retained_idx = np.where(mask)[0]
        boots = np.empty(N_BOOTSTRAP)
        for b in range(N_BOOTSTRAP):
            idx_resampled = rng.choice(retained_idx, size=len(retained_idx), replace=True)
            boots[b] = float(ccc(y[idx_resampled], iter47_preds[idx_resampled]))
        ci = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))
        frac_above_full = float((boots > full_ccc).mean())

        results[f"cov_{int(cov*100)}"] = {
            "coverage": cov,
            "n_retained": n_ret,
            "iter47_full_cohort_ccc": round(full_ccc, 4),
            "retained_ccc": round(retained_ccc, 4),
            "delta_retained_vs_full": round(delta_vs_full, 4),
            "retained_mae": round(retained_mae, 4),
            "bootstrap_retained_ccc_ci95": [round(ci[0], 4), round(ci[1], 4)],
            "frac_retained_above_full": round(frac_above_full, 4),
            "passes_uncorrected_gate": frac_above_full >= 0.95,
        }
        print(f"  coverage={int(cov*100)}%, n_retained={n_ret}: "
              f"retained CCC={retained_ccc:.4f}, Δ vs full={delta_vs_full:+.4f}, "
              f"frac>full={frac_above_full:.3f}")

    out = {
        "experiment": "ablation_t3_ensemble_sd_retention",
        "created_at_utc": ts,
        "n_subjects": n,
        "ensemble_seeds": ENSEMBLE_SEEDS,
        "null_mode": args.null or "none",
        "iter47_full_cohort_ccc": full_ccc,
        "results_per_coverage": results,
        "comparator_slot_F_canonical": {"cov_70": 0.4237, "cov_50": 0.5370},
        "vs_slot_F": {
            "cov_70_delta": round(results["cov_70"]["retained_ccc"] - 0.4237, 4),
            "cov_50_delta": round(results["cov_50"]["retained_ccc"] - 0.5370, 4),
        },
        "promotion_gate": {
            "rule": "retained CCC > Slot F baseline at both coverages AND frac>full ≥ 0.95",
            "passes_cov70_uncorrected": results["cov_70"]["frac_retained_above_full"] >= 0.95,
            "passes_cov50_uncorrected": results["cov_50"]["frac_retained_above_full"] >= 0.95,
        },
    }
    out_path = Path(f"results/lockbox_ablation_t3_ensemble_sd_retention_{ts}.json")
    out_path.write_text(json.dumps(out, indent=2, default=str) + "\n")
    print(f"\n  Wrote {out_path}")
    print(f"\n=== SUMMARY ===")
    print(f"  Cov70: retained CCC={results['cov_70']['retained_ccc']:.4f} (Slot F 0.4237, Δ={out['vs_slot_F']['cov_70_delta']:+.4f}, frac>full={results['cov_70']['frac_retained_above_full']:.3f})")
    print(f"  Cov50: retained CCC={results['cov_50']['retained_ccc']:.4f} (Slot F 0.5370, Δ={out['vs_slot_F']['cov_50_delta']:+.4f}, frac>full={results['cov_50']['frac_retained_above_full']:.3f})")


if __name__ == "__main__":
    main()

"""Demographics-First Residual Modeling (Phase 2.1, codex IMPROVE #4).

Hypothesis: demographics-only ridge already explains a non-trivial chunk of
T3 variance (B4 baseline). Train the IMU model only on the *residual* signal
demographics can't explain. Recombine with a small monotone-constrained
meta-learner.

Inductive firewall: per-fold ridge is fit on training PD only, residual
target = y_train - y_demo_train, IMU model fits on residuals, final
recombination via Ridge stacker on training out-of-fold predictions only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from sklearn.linear_model import Ridge

from inductive_lib import FoldImputer, full_metrics, gen_5fold_split
from project_paths import RESULTS_DIR, ensure_dir, results_artifact_path
from run_baselines import _demo_features
from run_inductive_ablation import (
    SEEDS,
    TARGET_CLIP,
    feature_select,
    load_features_and_targets,
    train_lgb,
)

ensure_dir(RESULTS_DIR)


def predict_demo_residual(
    Xd_demo: np.ndarray, Xd_imu: np.ndarray, yd: np.ndarray,
    Xt_demo: np.ndarray, Xt_imu: np.ndarray,
    variant: str, target_key: str, k: int = 500,
) -> np.ndarray:
    """variant ∈ {'base', 'demo_first', 'demo_stacked'}.

    base: IMU-only LGB ensemble (control = drops the demo channel entirely).
    demo_first: ridge-on-demo predicts y_demo, IMU LGB fits on residual r=y-y_demo,
                final = y_demo_test + lgb_test.
    demo_stacked: ridge-on-demo and IMU LGB are independent base learners; a
                  ridge meta-learner combines their predictions on train OOF.
    """
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    # Inductive imputation for demographics
    imp = FoldImputer.fit(Xd_demo)
    Xd_demo_i = imp.transform(Xd_demo)
    Xt_demo_i = imp.transform(Xt_demo)

    if variant == "base":
        sel_idx, _ = feature_select(
            Xd_imu, yd, list(range(Xd_imu.shape[1])), k=min(k, Xd_imu.shape[1]),
        )
        Xd_sel, Xt_sel = Xd_imu[:, sel_idx], Xt_imu[:, sel_idx]
        preds = []
        for s in SEEDS:
            preds.append(np.clip(train_lgb(Xd_sel, yd, Xt_sel, s), clip_lo, clip_hi))
        return np.mean(preds, axis=0)

    if variant == "demo_first":
        ridge = Ridge(alpha=1.0, random_state=42).fit(Xd_demo_i, yd)
        y_demo_train = ridge.predict(Xd_demo_i)
        residual = yd - y_demo_train
        sel_idx, _ = feature_select(
            Xd_imu, residual, list(range(Xd_imu.shape[1])), k=min(k, Xd_imu.shape[1]),
        )
        Xd_sel, Xt_sel = Xd_imu[:, sel_idx], Xt_imu[:, sel_idx]
        preds = []
        for s in SEEDS:
            preds.append(train_lgb(Xd_sel, residual, Xt_sel, s))
        residual_pred = np.mean(preds, axis=0)
        y_demo_test = ridge.predict(Xt_demo_i)
        return np.clip(y_demo_test + residual_pred, clip_lo, clip_hi)

    if variant == "demo_stacked":
        # OOF for stacker
        from sklearn.model_selection import KFold
        kf = KFold(n_splits=5, shuffle=True, random_state=42)
        n = len(yd)
        oof_demo = np.zeros(n)
        oof_imu = np.zeros(n)
        for tr_idx, va_idx in kf.split(np.arange(n)):
            r = Ridge(alpha=1.0, random_state=42).fit(Xd_demo_i[tr_idx], yd[tr_idx])
            oof_demo[va_idx] = r.predict(Xd_demo_i[va_idx])
            sel_idx, _ = feature_select(
                Xd_imu[tr_idx], yd[tr_idx],
                list(range(Xd_imu.shape[1])), k=min(k, Xd_imu.shape[1]),
            )
            preds_inner = []
            for s in SEEDS[:3]:
                preds_inner.append(train_lgb(
                    Xd_imu[tr_idx][:, sel_idx], yd[tr_idx],
                    Xd_imu[va_idx][:, sel_idx], s,
                ))
            oof_imu[va_idx] = np.mean(preds_inner, axis=0)
        # Train stacker on OOF
        meta_X = np.column_stack([oof_demo, oof_imu])
        meta = Ridge(alpha=0.1, random_state=42).fit(meta_X, yd)

        # Final test predictions: train base learners on all train, predict test
        ridge_full = Ridge(alpha=1.0, random_state=42).fit(Xd_demo_i, yd)
        y_demo_test = ridge_full.predict(Xt_demo_i)
        sel_idx, _ = feature_select(
            Xd_imu, yd, list(range(Xd_imu.shape[1])), k=min(k, Xd_imu.shape[1]),
        )
        Xd_sel, Xt_sel = Xd_imu[:, sel_idx], Xt_imu[:, sel_idx]
        preds = []
        for s in SEEDS:
            preds.append(train_lgb(Xd_sel, yd, Xt_sel, s))
        y_imu_test = np.mean(preds, axis=0)
        meta_X_test = np.column_stack([y_demo_test, y_imu_test])
        return np.clip(meta.predict(meta_X_test), clip_lo, clip_hi)

    raise ValueError(f"Unknown variant: {variant}")


def run_5fold(pd_merged, feature_cols, target_key, variant) -> dict:
    target_col = f"{target_key}_target"
    X_imu_full = pd_merged[feature_cols].values.astype(np.float32)
    X_demo_full, demo_names = _demo_features(pd_merged)
    y_full = pd_merged[target_col].values.astype(np.float32)

    all_true, all_pred, all_sids_out = [], [], []
    t0 = time.time()
    for split_i, train_sids, test_sids in gen_5fold_split(pd_merged, target_key):
        dm = pd_merged["sid"].isin(train_sids).values
        tm = pd_merged["sid"].isin(test_sids).values
        ep = predict_demo_residual(
            X_demo_full[dm], X_imu_full[dm], y_full[dm],
            X_demo_full[tm], X_imu_full[tm],
            variant=variant, target_key=target_key,
        )
        all_true.extend(y_full[tm].tolist())
        all_pred.extend(np.asarray(ep).tolist())
        all_sids_out.extend(pd_merged.loc[dm.nonzero()[0][:0].tolist() + tm.nonzero()[0].tolist(), "sid"].tolist())
        print(f"  split {split_i}/5 [{variant} {target_key}]: "
              f"CCC={full_metrics(y_full[tm], ep)['ccc']:.3f} ({len(test_sids)} test subjects)")

    metrics = full_metrics(all_true, all_pred, label=variant)
    metrics.update({
        "target": target_key, "variant": variant, "eval_mode": "5split",
        "demo_features": demo_names, "runtime_s": round(time.time() - t0, 1),
        "per_subject": {"sids": all_sids_out, "y_true": all_true,
                        "y_pred": [float(p) for p in all_pred]},
    })
    return metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="all",
                    choices=["all", "base", "demo_first", "demo_stacked"])
    ap.add_argument("--target", default="all", choices=["t1", "t2", "t3", "all"])
    args = ap.parse_args()

    variants = ["base", "demo_first", "demo_stacked"] if args.variant == "all" else [args.variant]
    targets = ["t1", "t2", "t3"] if args.target == "all" else [args.target]

    pd_merged, all_merged, feature_cols = load_features_and_targets()
    summary = []
    for v in variants:
        for t in targets:
            print(f"\n{'='*70}\nRunning {v} | {t} | 5split\n{'='*70}")
            try:
                m = run_5fold(pd_merged, feature_cols, t, v)
                fname = f"demo_residual_{v}_{t}_5split.json"
                with open(results_artifact_path(fname), "w") as f:
                    json.dump(m, f, indent=2)
                print(f"  -> CCC={m['ccc']:.3f} slope={m['cal_slope']:.3f} MAE={m['mae']:.3f}")
                summary.append({"variant": v, "target": t,
                                "ccc": m["ccc"], "mae": m["mae"], "runtime_s": m["runtime_s"]})
            except Exception as e:
                print(f"  FAILED: {type(e).__name__}: {e}")
                summary.append({"variant": v, "target": t, "error": str(e)})

    print("\n" + "=" * 60)
    for r in summary:
        if "error" in r:
            print(f"  {r['variant']:<14} {r['target']} ERROR")
        else:
            print(f"  {r['variant']:<14} {r['target']} CCC={r['ccc']:.3f} MAE={r['mae']:.3f}")

    with open(results_artifact_path("demo_residual_summary.json"), "w") as f:
        json.dump({"summary": summary}, f, indent=2)


if __name__ == "__main__":
    main()

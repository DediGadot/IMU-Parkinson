"""Audit corrected-target T3 dependence on clinical Stage-1 information.

This is a framing audit, not a candidate search. The corrected T3 headline
comes from iter41 with Stage 1 = H&Y + cv_yrs + cv_sex + cv_dbs. This script
keeps the Stage-2 feature pool clinical-clean (drops all `cv_*` columns) and
re-runs LOOCV under four Stage-1 policies:

  - a3_hy_cv: H&Y + cv_yrs + cv_sex + cv_dbs
  - hy_only: H&Y only
  - cv_only: cv_yrs + cv_sex + cv_dbs, no H&Y
  - intercept_only: no clinical information in Stage 1

The goal is to quantify how much of corrected-target T3 performance is clinical
staging / intake covariates versus deployable IMU residual signal.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.model_selection import LeaveOneOut

os.environ.setdefault("PD_IMU_N_CORES", "1")

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter3 import get_hy_features
from run_t3_iter41_target_fix import (
    SEEDS,
    STAGE1_A3_COLS,
    V2_FEATURES,
    filter_cohort,
    filter_stage2,
)
from run_t3_iter5_clinical import fit_stage1


STAGE1_POLICIES = ["a3_hy_cv", "hy_only", "cv_only", "intercept_only"]
COHORT = "drop_allmissing"
STAGE2_POLICY = "stage2_no_cv"


def _load_v2_column(sids: np.ndarray, col: str) -> np.ndarray:
    import pandas as pd

    v2 = pd.read_csv(V2_FEATURES).set_index("sid")
    return np.array([v2.loc[s, col] for s in sids], dtype=np.float64)


def build_stage1_matrix(sids: np.ndarray, hy: np.ndarray, policy: str) -> tuple[np.ndarray, list[str]]:
    parts: list[np.ndarray] = []
    names: list[str] = []
    if policy in {"a3_hy_cv", "hy_only"}:
        hy_feat = get_hy_features(hy)
        parts.append(hy_feat)
        names.extend([f"hy_{i}" for i in range(hy_feat.shape[1])])
    if policy in {"a3_hy_cv", "cv_only"}:
        for col in STAGE1_A3_COLS:
            parts.append(_load_v2_column(sids, col).reshape(-1, 1))
            names.append(col)
    if policy == "intercept_only":
        parts.append(np.zeros((len(sids), 1), dtype=np.float64))
        names.append("intercept_only_zero_feature")
    if not parts:
        raise ValueError(f"Unknown Stage-1 policy: {policy}")
    return np.column_stack(parts), names


def loocv_preds(data: dict[str, Any], stage1_policy: str, seed: int) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    sids = data["sids"]
    y = data["y_t3"]
    X_s1, stage1_names = build_stage1_matrix(sids, data["hy"], stage1_policy)
    X_s2, feat_cols_s2 = filter_stage2(data["X"], data["feat_cols"], STAGE2_POLICY)
    preds = np.zeros(len(sids), dtype=np.float64)
    stage1_oof = np.zeros(len(sids), dtype=np.float64)
    t0 = time.time()

    for fold_idx, (tr, te) in enumerate(LeaveOneOut().split(np.arange(len(sids)))):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y[tr], X_s1[te], alpha=1.0)
        residual_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X_s2[tr], X_s2[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        preds[te] = s1_te + train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        stage1_oof[te] = s1_te
        if (fold_idx + 1) % 25 == 0:
            print(
                f"    policy={stage1_policy} seed={seed}: "
                f"fold {fold_idx+1}/{len(sids)} elapsed={time.time()-t0:.1f}s",
                flush=True,
            )
    meta = {
        "stage1_feature_names": stage1_names,
        "stage2_policy": STAGE2_POLICY,
        "stage2_n_features": len(feat_cols_s2),
    }
    return preds, stage1_oof, meta


def _bootstrap_delta(
    y: np.ndarray,
    pred_a: np.ndarray,
    pred_b: np.ndarray,
    *,
    seed: int,
    n_boot: int,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    n = len(y)
    deltas = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        deltas[b] = ccc_fn(y[idx], pred_a[idx]) - ccc_fn(y[idx], pred_b[idx])
    return {
        "n_boot": int(n_boot),
        "delta_mean": float(np.mean(deltas)),
        "ci_low": float(np.quantile(deltas, 0.025)),
        "ci_high": float(np.quantile(deltas, 0.975)),
        "frac_above_zero": float(np.mean(deltas > 0)),
    }


def run_audit(n_boot: int) -> dict[str, Any]:
    data = filter_cohort(COHORT)
    y = data["y_t3"]
    policy_rows = []
    subject_rows = []
    mean_preds_by_policy: dict[str, np.ndarray] = {}
    mean_stage1_by_policy: dict[str, np.ndarray] = {}
    meta_by_policy: dict[str, Any] = {}

    for policy in STAGE1_POLICIES:
        seed_preds = []
        seed_stage1 = []
        seed_metrics = []
        seed_stage1_metrics = []
        for seed in SEEDS:
            print(f"\n=== corrected T3 clinical-dependency policy={policy} seed={seed} ===", flush=True)
            pred, s1, meta = loocv_preds(data, policy, seed)
            seed_preds.append(pred)
            seed_stage1.append(s1)
            seed_metrics.append(full_metrics(y, pred, label=f"{policy}_seed{seed}"))
            seed_stage1_metrics.append(full_metrics(y, s1, label=f"{policy}_stage1_seed{seed}"))
            meta_by_policy[policy] = meta
        mean_pred = np.mean(np.column_stack(seed_preds), axis=1)
        mean_s1 = np.mean(np.column_stack(seed_stage1), axis=1)
        mean_preds_by_policy[policy] = mean_pred
        mean_stage1_by_policy[policy] = mean_s1
        row = {
            "stage1_policy": policy,
            "n": int(len(y)),
            "mean_prediction_metrics": full_metrics(y, mean_pred, label=policy),
            "mean_stage1_only_metrics": full_metrics(y, mean_s1, label=f"{policy}_stage1_only"),
            "per_seed_metrics": seed_metrics,
            "per_seed_stage1_only_metrics": seed_stage1_metrics,
            "meta": meta_by_policy[policy],
        }
        policy_rows.append(row)
        for sid, yt, yp, ys1 in zip(data["sids"], y, mean_pred, mean_s1):
            subject_rows.append(
                {
                    "stage1_policy": policy,
                    "sid": str(sid),
                    "y_true": float(yt),
                    "y_pred": float(yp),
                    "stage1_pred": float(ys1),
                }
            )

    reference = mean_preds_by_policy["a3_hy_cv"]
    comparisons = {}
    for policy in STAGE1_POLICIES:
        if policy == "a3_hy_cv":
            continue
        comparisons[f"a3_hy_cv_minus_{policy}"] = _bootstrap_delta(
            y,
            reference,
            mean_preds_by_policy[policy],
            seed=20260508 + len(policy),
            n_boot=n_boot,
        )

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "audit": "t3_corrected_target_clinical_dependency",
        "cohort": COHORT,
        "stage2_policy": STAGE2_POLICY,
        "n": int(len(y)),
        "seeds": [int(s) for s in SEEDS],
        "stage1_policies": STAGE1_POLICIES,
        "interpretation": (
            "This is a framing audit. It estimates corrected-target T3 dependence "
            "on H&Y/clinical Stage-1 information while keeping Stage 2 free of "
            "hidden cv_* columns."
        ),
        "policy_rows": policy_rows,
        "comparisons_vs_a3_hy_cv": comparisons,
        "subject_rows": subject_rows,
        "verdict": {
            "canonical_t3_changed": False,
            "best_policy_by_ccc": max(
                policy_rows,
                key=lambda r: r["mean_prediction_metrics"]["ccc"],
            )["stage1_policy"],
            "a3_hy_cv_ccc": next(
                r["mean_prediction_metrics"]["ccc"]
                for r in policy_rows
                if r["stage1_policy"] == "a3_hy_cv"
            ),
            "intercept_only_ccc": next(
                r["mean_prediction_metrics"]["ccc"]
                for r in policy_rows
                if r["stage1_policy"] == "intercept_only"
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n_boot", type=int, default=5000)
    parser.add_argument("--out", default="t3_clinical_dependency_20260508.json")
    args = parser.parse_args()

    payload = run_audit(args.n_boot)
    out = RESULTS_DIR / args.out
    rows_out = RESULTS_DIR / args.out.replace(".json", "_subject_rows.csv")
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    import pandas as pd

    pd.DataFrame(payload["subject_rows"]).to_csv(rows_out, index=False)
    print("\n=== T3 CLINICAL DEPENDENCY VERDICT ===", flush=True)
    print(json.dumps(payload["verdict"], indent=2), flush=True)
    for row in payload["policy_rows"]:
        print(row["stage1_policy"], row["mean_prediction_metrics"], flush=True)
    print(f"Wrote {out}", flush=True)
    print(f"Wrote {rows_out}", flush=True)


if __name__ == "__main__":
    main()

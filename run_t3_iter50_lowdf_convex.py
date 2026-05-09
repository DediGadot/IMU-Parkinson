#!/usr/bin/env python3
"""T3 iter50 — low-degree nested convex mix screen.

F56 killed the 19-feature T3 meta-stack at N≈98. The one remaining statistical
escape hatch from that failure mode is a very low-degree mixer: no high-K item
stack, no post-hoc OOF blending, and no LOOCV unless a fixed 5-fold gate clears.

This screen uses the corrected iter47 valid-range target (N=95) and compares:

  - baseline_seq_current: iter47-style A3 clinical Stage 1 -> current V2 residual LGB
  - clinical_only: A3 clinical Ridge only
  - imu_only_no_cv: direct LGB on V2 with cv_* columns removed
  - nested_convex: alpha * clinical_only + (1-alpha) * imu_only_no_cv

The convex alpha is selected only inside each outer training fold from inner OOF
predictions. This is a screen-only diagnostic unless it clears the strict T3 gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import fit_stage1
from run_t3_iter41_target_fix import (
    SEEDS,
    build_stage1_matrix,
    filter_stage2,
    paired_boot_delta,
    _git_sha,
    _jsonable,
)
from run_t3_iter47_invalid_code_fix import filter_cohort


ensure_dir(RESULTS_DIR)

COHORT = "drop_allmissing_validrange"
BASELINE_STAGE2_POLICY = "stage2_current"
IMU_STAGE2_POLICY = "stage2_no_cv"
ALPHA_GRID = np.round(np.linspace(0.0, 1.0, 101), 2)
INNER_SPLITS = 4
N_BOOT = 5000


def _formula_sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _kfold(n: int, seed: int, n_splits: int = 5) -> list[tuple[np.ndarray, np.ndarray]]:
    return list(KFold(n_splits=n_splits, shuffle=True, random_state=seed).split(np.arange(n)))


def _inner_kfold(n: int, seed: int) -> list[tuple[np.ndarray, np.ndarray]]:
    return list(KFold(n_splits=INNER_SPLITS, shuffle=True, random_state=seed).split(np.arange(n)))


def _stage1_predict(
    X_s1: np.ndarray,
    y: np.ndarray,
    tr: np.ndarray,
    te: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    return fit_stage1(X_s1[tr], y[tr], X_s1[te], alpha=1.0)


def _imu_direct_predict(
    X_s2: np.ndarray,
    y: np.ndarray,
    tr: np.ndarray,
    te: np.ndarray,
    seed: int,
) -> np.ndarray:
    Xtr, Xte = impute_fold(X_s2[tr], X_s2[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
    return train_lgb(Xtr_sel, y[tr], Xte_sel, seed)


def _seq_residual_predict(
    X_s1: np.ndarray,
    X_s2: np.ndarray,
    y: np.ndarray,
    tr: np.ndarray,
    te: np.ndarray,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    s1_tr, s1_te = _stage1_predict(X_s1, y, tr, te)
    residual_tr = y[tr] - s1_tr
    Xtr, Xte = impute_fold(X_s2[tr], X_s2[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
    return s1_te + train_lgb(Xtr_sel, residual_tr, Xte_sel, seed), s1_te


def _choose_alpha_inner(
    X_s1: np.ndarray,
    X_imu: np.ndarray,
    y: np.ndarray,
    outer_tr: np.ndarray,
    seed: int,
) -> dict[str, Any]:
    train_n = len(outer_tr)
    clinical_oof = np.zeros(train_n, dtype=np.float64)
    imu_oof = np.zeros(train_n, dtype=np.float64)
    inner_rows = []
    for inner_fold, (inner_tr_rel, inner_va_rel) in enumerate(_inner_kfold(train_n, seed + 1009), start=1):
        inner_tr = outer_tr[inner_tr_rel]
        inner_va = outer_tr[inner_va_rel]
        _, clinical_va = _stage1_predict(X_s1, y, inner_tr, inner_va)
        imu_va = _imu_direct_predict(X_imu, y, inner_tr, inner_va, seed + inner_fold)
        clinical_oof[inner_va_rel] = clinical_va
        imu_oof[inner_va_rel] = imu_va
        inner_rows.append(
            {
                "inner_fold": inner_fold,
                "n_train": int(len(inner_tr)),
                "n_valid": int(len(inner_va)),
                "clinical_ccc": float(ccc_fn(y[inner_va], clinical_va)),
                "imu_ccc": float(ccc_fn(y[inner_va], imu_va)),
            }
        )

    y_train = y[outer_tr]
    alpha_scores = []
    for alpha in ALPHA_GRID:
        pred = alpha * clinical_oof + (1.0 - alpha) * imu_oof
        alpha_scores.append(float(ccc_fn(y_train, pred)))
    best_idx = int(np.argmax(alpha_scores))
    best_alpha = float(ALPHA_GRID[best_idx])
    return {
        "alpha": best_alpha,
        "inner_oof_ccc": float(alpha_scores[best_idx]),
        "clinical_inner_oof_ccc": float(ccc_fn(y_train, clinical_oof)),
        "imu_inner_oof_ccc": float(ccc_fn(y_train, imu_oof)),
        "alpha_scores": [
            {"alpha": float(a), "ccc": float(s)}
            for a, s in zip(ALPHA_GRID, alpha_scores)
        ],
        "inner_rows": inner_rows,
    }


def run_seed(data: dict[str, Any], seed: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sids = data["sids"]
    y = data["y_t3"]
    X_s1 = build_stage1_matrix(sids, data["hy"])
    X_baseline, baseline_cols = filter_stage2(data["X"], data["feat_cols"], BASELINE_STAGE2_POLICY)
    X_imu, imu_cols = filter_stage2(data["X"], data["feat_cols"], IMU_STAGE2_POLICY)
    n = len(y)
    preds = {
        "baseline_seq_current": np.zeros(n, dtype=np.float64),
        "clinical_only": np.zeros(n, dtype=np.float64),
        "imu_only_no_cv": np.zeros(n, dtype=np.float64),
        "nested_convex": np.zeros(n, dtype=np.float64),
    }
    fold_rows = []
    t0 = time.time()

    for fold, (tr, te) in enumerate(_kfold(n, seed), start=1):
        alpha_info = _choose_alpha_inner(X_s1, X_imu, y, tr, seed + fold * 17)
        baseline_te, clinical_te_from_baseline = _seq_residual_predict(
            X_s1, X_baseline, y, tr, te, seed
        )
        _, clinical_te = _stage1_predict(X_s1, y, tr, te)
        if not np.allclose(clinical_te, clinical_te_from_baseline):
            raise RuntimeError("Stage-1 predictions disagree between baseline and clinical-only path")
        imu_te = _imu_direct_predict(X_imu, y, tr, te, seed + 500 + fold)
        alpha = float(alpha_info["alpha"])
        convex_te = alpha * clinical_te + (1.0 - alpha) * imu_te

        preds["baseline_seq_current"][te] = baseline_te
        preds["clinical_only"][te] = clinical_te
        preds["imu_only_no_cv"][te] = imu_te
        preds["nested_convex"][te] = convex_te

        fold_rows.append(
            {
                "seed": int(seed),
                "outer_fold": int(fold),
                "n_train": int(len(tr)),
                "n_test": int(len(te)),
                "alpha": alpha,
                "inner_oof_ccc": alpha_info["inner_oof_ccc"],
                "clinical_inner_oof_ccc": alpha_info["clinical_inner_oof_ccc"],
                "imu_inner_oof_ccc": alpha_info["imu_inner_oof_ccc"],
                "test_sids": [str(sids[i]) for i in te],
                "inner_rows": alpha_info["inner_rows"],
            }
        )
        print(
            f"  seed={seed} fold={fold}/5 alpha={alpha:.2f} "
            f"innerCCC={alpha_info['inner_oof_ccc']:+.4f} elapsed={time.time()-t0:.1f}s",
            flush=True,
        )

    seed_result = {
        "seed": int(seed),
        "n": int(n),
        "stage2_columns": {
            "baseline_policy": BASELINE_STAGE2_POLICY,
            "baseline_n_features": int(len(baseline_cols)),
            "imu_policy": IMU_STAGE2_POLICY,
            "imu_n_features": int(len(imu_cols)),
        },
        "metrics": {
            name: full_metrics(y, pred, label=f"iter50_{name}_seed{seed}")
            for name, pred in preds.items()
        },
        "alpha_values": [row["alpha"] for row in fold_rows],
        "alpha_mean": float(np.mean([row["alpha"] for row in fold_rows])),
        "alpha_std": float(np.std([row["alpha"] for row in fold_rows])),
        "predictions": preds,
        "fold_rows": fold_rows,
    }
    return seed_result, fold_rows


def _stack_mean(seed_results: list[dict[str, Any]], name: str) -> np.ndarray:
    return np.mean(np.column_stack([row["predictions"][name] for row in seed_results]), axis=1)


def _screen_gate(
    y: np.ndarray,
    convex_seed_cccs: list[float],
    baseline_seed_cccs: list[float],
    convex_mean: np.ndarray,
    baseline_mean: np.ndarray,
) -> dict[str, Any]:
    delta_seed_mean_predictions = float(ccc_fn(y, convex_mean) - ccc_fn(y, baseline_mean))
    mean_seed_delta = float(np.mean(np.array(convex_seed_cccs) - np.array(baseline_seed_cccs)))
    seed_delta_std = float(np.std(np.array(convex_seed_cccs) - np.array(baseline_seed_cccs), ddof=1))
    return {
        "strict_t3_gate_pass": bool(delta_seed_mean_predictions >= 0.05 and seed_delta_std < 0.02),
        "delta_seed_mean_predictions": delta_seed_mean_predictions,
        "mean_seed_delta": mean_seed_delta,
        "seed_delta_std": seed_delta_std,
        "required_delta": 0.05,
        "required_seed_delta_std_lt": 0.02,
    }


def run_screen() -> dict[str, Any]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg_payload = {
        "experiment": "T3 iter50 low-degree nested convex mix screen",
        "cohort": COHORT,
        "target": "iter47 valid-range corrected T3; exclude all-missing Part III rows and treat raw subitem values outside 0-4 as missing",
        "base_predictors": {
            "clinical_only": "A3 Ridge on H&Y + cv_yrs + cv_sex + cv_dbs",
            "imu_only_no_cv": "direct LGB on V2 features with cv_* columns removed",
        },
        "baseline": "iter47-style A3 clinical Stage 1 -> current V2 residual LGB",
        "mixing_rule": "For each outer fold, learn alpha in [0,1] step 0.01 on inner 4-fold OOF predictions from the outer training subjects; predict outer test as alpha*clinical + (1-alpha)*imu.",
        "seeds": SEEDS,
        "outer_cv": "5-fold KFold(shuffle=True, random_state=seed)",
        "inner_cv": f"{INNER_SPLITS}-fold KFold inside each outer-train fold",
        "promotion_gate": "5-fold seed-mean delta >= +0.05 vs baseline and seed delta std < 0.02 before any LOOCV lockbox",
        "no_loocv_in_this_script": True,
    }
    prereg = {
        **prereg_payload,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha(prereg_payload),
    }
    prereg_path = RESULTS_DIR / f"preregistration_t3_iter50_lowdfconvex_screen_{ts}.json"
    prereg_path.write_text(json.dumps(_jsonable(prereg), indent=2) + "\n", encoding="utf-8")
    print(f"Screen declaration written before computation: {prereg_path}", flush=True)

    data = filter_cohort(COHORT)
    y = data["y_t3"]
    seed_results = []
    fold_rows = []
    for seed in SEEDS:
        print(f"\n=== iter50 low-degree convex screen seed={seed} n={len(y)} ===", flush=True)
        seed_result, seed_fold_rows = run_seed(data, seed)
        seed_results.append(seed_result)
        fold_rows.extend(seed_fold_rows)
        for name, metrics in seed_result["metrics"].items():
            print(
                f"  {name:22s} CCC={metrics['ccc']:+.4f} MAE={metrics['mae']:.3f} "
                f"r={metrics['r']:+.4f}",
                flush=True,
            )

    mean_predictions = {
        name: _stack_mean(seed_results, name)
        for name in ["baseline_seq_current", "clinical_only", "imu_only_no_cv", "nested_convex"]
    }
    mean_metrics = {
        name: full_metrics(y, pred, label=f"iter50_{name}_mean3")
        for name, pred in mean_predictions.items()
    }
    convex_seed_cccs = [float(row["metrics"]["nested_convex"]["ccc"]) for row in seed_results]
    baseline_seed_cccs = [float(row["metrics"]["baseline_seq_current"]["ccc"]) for row in seed_results]
    gate = _screen_gate(
        y,
        convex_seed_cccs,
        baseline_seed_cccs,
        mean_predictions["nested_convex"],
        mean_predictions["baseline_seq_current"],
    )
    bootstrap = paired_boot_delta(
        y,
        mean_predictions["nested_convex"],
        mean_predictions["baseline_seq_current"],
        n_boot=N_BOOT,
    )
    alpha_values = [
        alpha
        for row in seed_results
        for alpha in row["alpha_values"]
    ]
    subject_rows = []
    for i, sid in enumerate(data["sids"]):
        subject_rows.append(
            {
                "sid": str(sid),
                "y_true": float(y[i]),
                **{name: float(pred[i]) for name, pred in mean_predictions.items()},
            }
        )

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "run_t3_iter50_lowdf_convex.py",
        "preregistration_file": str(prereg_path),
        "formula_sha256": prereg["formula_sha256"],
        "cohort": {
            "name": COHORT,
            "n": int(len(y)),
            "excluded_sids": data["excluded_sids"],
            "target_change_subjects": [
                {
                    "sid": str(sid),
                    "old_target": float(old),
                    "validrange_target": float(new),
                    "delta_old_minus_validrange": float(delta),
                }
                for sid, old, new, delta in zip(
                    data["sids"],
                    data["y_t3_original"],
                    data["y_t3"],
                    data["target_delta_original_minus_validrange"],
                )
                if abs(float(delta)) > 1e-9
            ],
        },
        "seeds": [int(seed) for seed in SEEDS],
        "mean_metrics": mean_metrics,
        "per_seed_metrics": [
            {
                "seed": int(row["seed"]),
                "metrics": row["metrics"],
                "alpha_values": row["alpha_values"],
                "alpha_mean": row["alpha_mean"],
                "alpha_std": row["alpha_std"],
            }
            for row in seed_results
        ],
        "alpha_summary": {
            "values": [float(a) for a in alpha_values],
            "mean": float(np.mean(alpha_values)),
            "std": float(np.std(alpha_values, ddof=1)),
            "min": float(np.min(alpha_values)),
            "max": float(np.max(alpha_values)),
        },
        "gate": gate,
        "bootstrap_nested_convex_minus_baseline": bootstrap,
        "decision": (
            "screen_pass_write_prereg_for_one_loocv_lockbox"
            if gate["strict_t3_gate_pass"]
            else "screen_fail_no_loocv_no_canonical_change"
        ),
        "fold_rows": fold_rows,
    }

    out_json = RESULTS_DIR / f"iter50_lowdf_convex_screen_{ts}.json"
    rows_csv = RESULTS_DIR / f"iter50_lowdf_convex_screen_rows_{ts}.csv"
    subject_csv = RESULTS_DIR / f"iter50_lowdf_convex_subject_preds_{ts}.csv"
    out_json.write_text(json.dumps(_jsonable(result), indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(
        [
            {
                "seed": row["seed"],
                "outer_fold": row["outer_fold"],
                "n_train": row["n_train"],
                "n_test": row["n_test"],
                "alpha": row["alpha"],
                "inner_oof_ccc": row["inner_oof_ccc"],
                "clinical_inner_oof_ccc": row["clinical_inner_oof_ccc"],
                "imu_inner_oof_ccc": row["imu_inner_oof_ccc"],
                "test_sids": ",".join(row["test_sids"]),
            }
            for row in fold_rows
        ]
    ).to_csv(rows_csv, index=False)
    pd.DataFrame(subject_rows).to_csv(subject_csv, index=False)
    print("\n=== iter50 low-degree convex screen verdict ===", flush=True)
    print(json.dumps(_jsonable({"mean_metrics": mean_metrics, "gate": gate, "decision": result["decision"]}), indent=2), flush=True)
    print(f"Wrote {out_json}", flush=True)
    print(f"Wrote {rows_csv}", flush=True)
    print(f"Wrote {subject_csv}", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["screen"], default="screen")
    args = parser.parse_args()
    if args.mode == "screen":
        run_screen()


if __name__ == "__main__":
    main()

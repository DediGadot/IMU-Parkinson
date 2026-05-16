"""T3 iter40 wildcard: local-similarity residual Stage 2.

This is a deliberately high-risk but fold-clean architecture probe. It keeps
the canonical iter5 Stage 1 unchanged:

    Ridge: T3 ~ H&Y + cv_yrs + cv_sex + cv_dbs

Then it compares two Stage 2 residual maps on identical 5-fold splits:

    baseline: canonical iter5 LGB residual model
    wildcard: fold-local feature selection -> train-only normalization -> PCA
              -> inverse-distance kNN residual smoother

Rationale: many failed T3 attempts show regression-to-the-mean tail shrinkage
under global tree models. A local residual smoother is a different bias class:
it predicts residuals from nearby training subjects rather than global leaf
averages. This script is screen-only. It writes no pre-registration and does
not change canonical numbers unless the strict gate is cleared.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldNormalizer, ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import (
    FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    kfold_split,
    load_clinical_dict,
    load_full_pd_data,
)


ensure_dir(RESULTS_DIR)
DEFAULT_SEEDS = (42, 1337, 7)
CANONICAL_FEATURE_SET = "A3_tier1"

LOCAL_CONFIG = {
    "stage1": "iter5 A3_tier1 Ridge alpha=1.0",
    "stage2_baseline": "iter5 LGB residual on V2 selected K=500",
    "stage2_wildcard": "selected K=500 -> FoldNormalizer -> PCA -> inverse_distance_kNN residual",
    "feature_select_k": 500,
    "pca_components": 24,
    "n_neighbors": 12,
    "distance_eps": 1e-3,
    "pca_random_state": 0,
}


def formula_sha256() -> str:
    payload = json.dumps(LOCAL_CONFIG, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def pca_knn_residual_predict(
    X_tr: np.ndarray,
    residual_tr: np.ndarray,
    X_te: np.ndarray,
    *,
    n_components: int,
    n_neighbors: int,
    distance_eps: float,
) -> np.ndarray:
    """Predict residuals by inverse-distance averaging in train-only PCA space."""
    nrm = FoldNormalizer.fit(X_tr)
    Xtr_s = np.nan_to_num(nrm.transform(X_tr), nan=0.0, posinf=0.0, neginf=0.0)
    Xte_s = np.nan_to_num(nrm.transform(X_te), nan=0.0, posinf=0.0, neginf=0.0)

    max_components = min(n_components, Xtr_s.shape[0] - 1, Xtr_s.shape[1])
    if max_components >= 1:
        pca = PCA(n_components=max_components, svd_solver="full", random_state=LOCAL_CONFIG["pca_random_state"])
        Z_tr = pca.fit_transform(Xtr_s)
        Z_te = pca.transform(Xte_s)
    else:
        Z_tr = Xtr_s
        Z_te = Xte_s

    d2 = np.sum((Z_te[:, None, :] - Z_tr[None, :, :]) ** 2, axis=2)
    d = np.sqrt(np.maximum(d2, 0.0))
    k = min(n_neighbors, len(residual_tr))
    nn_idx = np.argpartition(d, kth=k - 1, axis=1)[:, :k]
    nn_d = np.take_along_axis(d, nn_idx, axis=1)
    nn_y = residual_tr[nn_idx]
    w = 1.0 / (nn_d + distance_eps)
    return np.sum(w * nn_y, axis=1) / np.sum(w, axis=1)


def run_seed(seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (sids, y_t3, baseline_preds, wildcard_preds) for one 5-fold seed."""
    sids, X, _fc, y_t3, hy, _obs = load_full_pd_data()
    clinical = load_clinical_dict(sids)
    X_s1, _names = build_stage1_features(hy, clinical, FEATURE_SETS[CANONICAL_FEATURE_SET])
    baseline_preds = np.zeros(len(y_t3), dtype=np.float64)
    wildcard_preds = np.zeros(len(y_t3), dtype=np.float64)

    splits = kfold_split(len(y_t3), n_splits=5, seed=seed)
    for fold_idx, (tr, te) in enumerate(splits, start=1):
        s1_pred_tr, s1_pred_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=1.0)
        residual_tr = y_t3[tr] - s1_pred_tr

        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _idx = feature_select_fold(
            Xtr,
            residual_tr,
            Xte,
            k=LOCAL_CONFIG["feature_select_k"],
            seed=seed,
        )

        baseline_resid = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        wildcard_resid = pca_knn_residual_predict(
            Xtr_sel,
            residual_tr,
            Xte_sel,
            n_components=LOCAL_CONFIG["pca_components"],
            n_neighbors=LOCAL_CONFIG["n_neighbors"],
            distance_eps=LOCAL_CONFIG["distance_eps"],
        )
        baseline_preds[te] = s1_pred_te + baseline_resid
        wildcard_preds[te] = s1_pred_te + wildcard_resid
        print(f"  seed={seed} fold={fold_idx}/5 complete", flush=True)

    return sids, y_t3, baseline_preds, wildcard_preds


def bootstrap_delta(
    y: np.ndarray,
    baseline_pred: np.ndarray,
    wildcard_pred: np.ndarray,
    *,
    n_boot: int,
    seed: int = 20260508,
) -> dict:
    rng = np.random.default_rng(seed)
    deltas = []
    n = len(y)
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        deltas.append(ccc_fn(y[idx], wildcard_pred[idx]) - ccc_fn(y[idx], baseline_pred[idx]))
    arr = np.asarray(deltas, dtype=np.float64)
    return {
        "n_boot": int(n_boot),
        "delta_mean": round(float(arr.mean()), 4),
        "delta_ci_low": round(float(np.percentile(arr, 2.5)), 4),
        "delta_ci_high": round(float(np.percentile(arr, 97.5)), 4),
        "frac_positive": round(float((arr > 0).mean()), 4),
        "frac_above_0p025": round(float((arr > 0.025).mean()), 4),
        "frac_above_0p05": round(float((arr > 0.05).mean()), 4),
    }


def run_screen(seeds: tuple[int, ...], n_boot: int) -> dict:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("=== T3 iter40 local-residual wildcard screen ===", flush=True)
    print(json.dumps(LOCAL_CONFIG, indent=2), flush=True)
    print(f"formula_sha256={formula_sha256()}", flush=True)

    rows: list[dict] = []
    baseline_all = []
    wildcard_all = []
    sids_ref = None
    y_ref = None
    t0 = time.time()

    for seed in seeds:
        sids, y_t3, baseline_preds, wildcard_preds = run_seed(seed)
        if sids_ref is None:
            sids_ref = sids
            y_ref = y_t3
        else:
            assert np.array_equal(sids_ref, sids)
            assert np.array_equal(y_ref, y_t3)

        baseline_all.append(baseline_preds)
        wildcard_all.append(wildcard_preds)
        base_ccc = ccc_fn(y_t3, baseline_preds)
        wild_ccc = ccc_fn(y_t3, wildcard_preds)
        row = {
            "seed": int(seed),
            "baseline_ccc": round(float(base_ccc), 4),
            "wildcard_ccc": round(float(wild_ccc), 4),
            "delta_ccc": round(float(wild_ccc - base_ccc), 4),
            "baseline_mae": full_metrics(y_t3, baseline_preds)["mae"],
            "wildcard_mae": full_metrics(y_t3, wildcard_preds)["mae"],
        }
        rows.append(row)
        print(
            f"seed {seed}: baseline CCC={base_ccc:.4f}, "
            f"wildcard CCC={wild_ccc:.4f}, delta={wild_ccc - base_ccc:+.4f}",
            flush=True,
        )

    baseline_mean = np.mean(np.column_stack(baseline_all), axis=1)
    wildcard_mean = np.mean(np.column_stack(wildcard_all), axis=1)
    baseline_metrics = full_metrics(y_ref, baseline_mean, label="iter40_same_fold_iter5_baseline")
    wildcard_metrics = full_metrics(y_ref, wildcard_mean, label="iter40_local_residual_wildcard")
    seed_deltas = np.array([r["delta_ccc"] for r in rows], dtype=np.float64)
    boot = bootstrap_delta(y_ref, baseline_mean, wildcard_mean, n_boot=n_boot)

    mean_pred_delta = float(wildcard_metrics["ccc"] - baseline_metrics["ccc"])
    strict_gate = bool(mean_pred_delta >= 0.05 and seed_deltas.mean() >= 0.05 and seed_deltas.std() < 0.02)
    relaxed_gate = bool(mean_pred_delta >= 0.025 and seed_deltas.mean() >= 0.025 and seed_deltas.std() < 0.02)

    out = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "script": Path(__file__).name,
        "mode": "screen_only",
        "n_subjects": int(len(y_ref)),
        "seeds": [int(s) for s in seeds],
        "config": LOCAL_CONFIG,
        "formula_sha256": formula_sha256(),
        "baseline_metrics_seed_mean": baseline_metrics,
        "wildcard_metrics_seed_mean": wildcard_metrics,
        "seed_mean_delta_ccc": round(mean_pred_delta, 4),
        "per_seed_rows": rows,
        "per_seed_delta_mean": round(float(seed_deltas.mean()), 4),
        "per_seed_delta_std": round(float(seed_deltas.std()), 4),
        "bootstrap_delta": boot,
        "promotion_gate": {
            "strict_t3_gate_pass": strict_gate,
            "strict_rule": "mean-pred delta >= +0.05, per-seed mean delta >= +0.05, seed delta std < 0.02",
            "relaxed_gate_pass": relaxed_gate,
            "relaxed_rule": "mean-pred delta >= +0.025, per-seed mean delta >= +0.025, seed delta std < 0.02",
            "decision": "eligible_for_prereg_and_loocv" if strict_gate else "fail_screen_no_lockbox",
        },
        "per_subject": {
            "sids": sids_ref.tolist(),
            "y_true": y_ref.tolist(),
            "baseline_pred": baseline_mean.tolist(),
            "wildcard_pred": wildcard_mean.tolist(),
        },
        "wall_time_s": round(time.time() - t0, 1),
    }

    out_json = RESULTS_DIR / f"iter40_local_residual_screen_{ts}.json"
    out_rows = RESULTS_DIR / f"iter40_local_residual_screen_rows_{ts}.csv"
    with open(out_json, "w") as f:
        json.dump(out, f, indent=2, default=str)
    pd.DataFrame(rows).to_csv(out_rows, index=False)

    print("\n=== iter40 screen result ===", flush=True)
    print(
        f"baseline mean CCC={baseline_metrics['ccc']:.4f}; "
        f"wildcard mean CCC={wildcard_metrics['ccc']:.4f}; "
        f"delta={mean_pred_delta:+.4f}",
        flush=True,
    )
    print(
        f"per-seed delta mean={seed_deltas.mean():+.4f}, std={seed_deltas.std():.4f}; "
        f"strict_gate_pass={strict_gate}",
        flush=True,
    )
    print(f"Wrote {out_json}", flush=True)
    print(f"Wrote {out_rows}", flush=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["screen"], default="screen")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    parser.add_argument("--n_boot", type=int, default=2000)
    args = parser.parse_args()
    run_screen(tuple(args.seeds), n_boot=args.n_boot)


if __name__ == "__main__":
    main()

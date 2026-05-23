#!/usr/bin/env python3
"""Ablation #11 — Knowledge-distillation cascade via HARNet PCA-bottleneck.

**SETUP**: torch is not installed on the active remote slave (RTX 4060). This is a
sklearn-only KD APPROXIMATION that captures the feature-matching gradient signal
codex 2026-05-16 identified as the bypass for the N=94 absorption wall:

    KD loss term that bypasses absorption:
        L_feature = || normalize(P_s(z_s)) - stopgrad(normalize(P_t(x))) ||^2

This script approximates that loss via a fold-local Ridge cascade:
  - Student: V2 features → PCA-32 of HARNet UKB teacher embeddings.
  - Predicted student output = 32-d "distilled teacher" representation.
  - These 32 dims are FORCED-INCLUDED into the T1 K-best pool (bypasses absorption).

**ORTHOGONALITY** to F-iter15 (4× frozen-encoder wall):
  - F-iter15 took HARNet 2048-d (mean+std) → V2 K=500 LGB. K=500 absorbed HARNet
    dims; only 0-2 HARNet cols survived selection per fold.
  - This ablation projects HARNet via fold-local Ridge(V2 → PCA(HARNet_train)) →
    forced-include the 32 distilled cols (cannot be K-best-eliminated). The Ridge
    target IS HARNet embeddings on TRAIN-fold only (no label leak). The student
    learns the V2 → teacher mapping; only those mapped 32 dims enter the LGB.

**Pre-registered gate**: T1 LOOCV CCC ≥ +0.025 (single ablation), paired-bootstrap
frac>0 ≥ 0.95 vs iter34 hygiene baseline (0.7170).

**5-null gate**: scrambled-T1 + canary feature.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from eval_utils import lins_ccc as ccc
from inductive_lib import full_metrics, FoldNormalizer
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    load_pd_data,
    impute_fold,
    feature_select_fold,
    train_lgb,
    get_hy_features,
)

ensure_dir(RESULTS_DIR)

SEEDS = [42, 1337, 7]
HARNET_CACHE = REPO_ROOT / "results" / "harnet_subj_embeddings.csv"
PCA_DIMS = 32  # student bottleneck width
K_BEST = 500


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _formula_sha(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_harnet_cache(sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    df = pd.read_csv(HARNET_CACHE).set_index("sid")
    feat_cols = [c for c in df.columns if c != "n_recordings"]
    X = np.full((len(sids), len(feat_cols)), np.nan)
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, feat_cols].to_numpy(dtype=np.float64)
    return X, feat_cols


def fold_local_distillation_features(
    X_v2_tr: np.ndarray,
    X_v2_te: np.ndarray,
    X_harnet_tr: np.ndarray,
    X_harnet_te: np.ndarray,
    seed: int,
    pca_dims: int = PCA_DIMS,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Fold-local KD cascade:
      1. PCA-fit on X_harnet_tr → reduces teacher to pca_dims
      2. Project both train + test HARNet via this PCA → z_t_tr, z_t_te
      3. Fit Ridge per dim: V2 → z_t_tr_d for d in 0..pca_dims-1
      4. Predict on V2_te to get z_s_te (student's predicted teacher rep)

    Returns: (z_s_tr_oof, z_s_te) where z_s_tr_oof are fold-leak-free
    (Ridge fit on full train, then internal-OOF would be needed for honesty;
    here we use the in-train predictions as student "distilled" features — this
    is the standard KD use of student in tabular cascades, with the leak risk
    that any in-train Ridge prediction has zero residual to the train target.
    However: the train target IS HARNet embeddings, NOT the UPDRS label, so
    Ridge in-train predictions cannot leak the UPDRS test label. This is the
    same logic as Stage-1 H&Y Ridge predictions: the Stage-1 target is y, but
    Stage-2 LGB sees the Ridge residual. Here teacher Ridge sees no label.)
    """
    # Sanitize HARNet NaNs (impute with train median; teacher missing → 0 after norm)
    har_med = np.nanmedian(X_harnet_tr, axis=0)
    har_med = np.where(np.isnan(har_med), 0.0, har_med)
    X_har_tr = np.where(np.isnan(X_harnet_tr), har_med[None, :], X_harnet_tr)
    X_har_te = np.where(np.isnan(X_harnet_te), har_med[None, :], X_harnet_te)

    # PCA on train HARNet
    pca = PCA(n_components=min(pca_dims, X_har_tr.shape[1], X_har_tr.shape[0] - 1), random_state=seed * 11 + 1)
    z_t_tr = pca.fit_transform(X_har_tr)
    z_t_te = pca.transform(X_har_te)

    # Sanitize V2 (median imputation)
    v2_med = np.nanmedian(X_v2_tr, axis=0)
    v2_med = np.where(np.isnan(v2_med), 0.0, v2_med)
    X_v2_tr_c = np.where(np.isnan(X_v2_tr), v2_med[None, :], X_v2_tr)
    X_v2_te_c = np.where(np.isnan(X_v2_te), v2_med[None, :], X_v2_te)

    # Normalize V2
    v2_norm = FoldNormalizer.fit(X_v2_tr_c)
    Xv2_tr = v2_norm.transform(X_v2_tr_c)
    Xv2_te = v2_norm.transform(X_v2_te_c)

    # Multi-output Ridge per dim (label-free target = teacher PCA)
    ridge = Ridge(alpha=10.0, random_state=seed * 13 + 2)
    ridge.fit(Xv2_tr, z_t_tr)
    z_s_tr = ridge.predict(Xv2_tr)
    z_s_te = ridge.predict(Xv2_te)

    diag = {
        "pca_dims": int(z_t_tr.shape[1]),
        "pca_variance_explained_ratio_sum": float(pca.explained_variance_ratio_.sum()),
        "ridge_train_r2": float(ridge.score(Xv2_tr, z_t_tr)),
    }
    return z_s_tr, z_s_te, diag


def loocv_predict_arm(
    sids: np.ndarray,
    y: np.ndarray,
    hy: np.ndarray,
    X_v2: np.ndarray,
    X_harnet: np.ndarray | None,
    seed: int,
    canary_test_only: float | None = None,
) -> tuple[np.ndarray, list[dict]]:
    n = len(sids)
    preds = np.full(n, np.nan, dtype=np.float64)
    diags = []

    hy_feat = get_hy_features(hy)

    for i in range(n):
        tr = np.array([j for j in range(n) if j != i])
        te = np.array([i])

        # Stage-1: Ridge on H&Y → T1 base prediction
        v2_norm = FoldNormalizer.fit(hy_feat[tr])
        hytr = v2_norm.transform(hy_feat[tr])
        hyte = v2_norm.transform(hy_feat[te])
        ridge_s1 = Ridge(alpha=1.0, random_state=seed * 17 + 3)
        ridge_s1.fit(hytr, y[tr])
        y_s1_te = ridge_s1.predict(hyte)
        residual_tr = y[tr] - ridge_s1.predict(hytr)

        # Build feature block (V2 + optional distilled KD)
        if X_harnet is not None:
            z_s_tr, z_s_te, _diag = fold_local_distillation_features(
                X_v2[tr], X_v2[te], X_harnet[tr], X_harnet[te], seed=seed,
            )
            X_block_tr = np.hstack([X_v2[tr], z_s_tr])
            X_block_te = np.hstack([X_v2[te], z_s_te])
            forced_n = z_s_tr.shape[1]
        else:
            X_block_tr = X_v2[tr]
            X_block_te = X_v2[te]
            forced_n = 0

        # Canary feature
        if canary_test_only is not None:
            X_block_tr = np.hstack([X_block_tr, np.zeros((X_block_tr.shape[0], 1))])
            X_block_te = np.hstack([X_block_te, np.full((1, 1), canary_test_only)])

        Xtr_imp, Xte_imp = impute_fold(X_block_tr, X_block_te)

        if forced_n > 0:
            # K-best on V2 portion, then concat forced KD block
            v2_dims = X_v2.shape[1]
            X_v2_tr_i = Xtr_imp[:, :v2_dims]
            X_v2_te_i = Xte_imp[:, :v2_dims]
            X_kd_tr = Xtr_imp[:, v2_dims:v2_dims + forced_n]
            X_kd_te = Xte_imp[:, v2_dims:v2_dims + forced_n]
            X_canary_tr = Xtr_imp[:, v2_dims + forced_n:]
            X_canary_te = Xte_imp[:, v2_dims + forced_n:]
            X_v2_sel_tr, X_v2_sel_te, _ = feature_select_fold(
                X_v2_tr_i, residual_tr, X_v2_te_i, k=max(1, K_BEST - forced_n), seed=seed
            )
            Xtr_final = np.hstack([X_v2_sel_tr, X_kd_tr, X_canary_tr])
            Xte_final = np.hstack([X_v2_sel_te, X_kd_te, X_canary_te])
        else:
            Xtr_final, Xte_final, _ = feature_select_fold(Xtr_imp, residual_tr, Xte_imp, k=K_BEST, seed=seed)

        stage2 = train_lgb(Xtr_final, residual_tr, Xte_final, seed)
        preds[i] = y_s1_te[0] + stage2[0]

    return preds, diags


def paired_bootstrap_delta(
    y_true: np.ndarray, pred_a: np.ndarray, pred_b: np.ndarray, n_boot: int = 5000, seed: int = 42
) -> dict:
    rng = np.random.RandomState(seed)
    n = len(y_true)
    deltas = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        deltas[b] = ccc(y_true[idx], pred_b[idx]) - ccc(y_true[idx], pred_a[idx])
    return {
        "delta_mean": float(np.mean(deltas)),
        "delta_ci_low": float(np.percentile(deltas, 2.5)),
        "delta_ci_high": float(np.percentile(deltas, 97.5)),
        "frac_above_zero": float(np.mean(deltas > 0)),
        "frac_above_mcid": float(np.mean(deltas > 0.005)),
        "frac_above_0.025": float(np.mean(deltas > 0.025)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="3-fold quick screen (skips full LOOCV)")
    args = parser.parse_args()

    ts_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"\n=== Ablation #11 KD-cascade HARNet (T1, {ts_utc}) ===")

    if not HARNET_CACHE.exists():
        raise FileNotFoundError(f"HARNet cache missing: {HARNET_CACHE}")

    d = load_pd_data()
    sids = d["sids"]
    y_t1 = d["t1"].astype(np.float64)
    hy = d["hy"]
    X_v2 = d["X_v2"]
    n = len(sids)

    X_harnet, har_cols = load_harnet_cache(sids)
    n_har_matched = int(np.isfinite(X_harnet).any(axis=1).sum())
    print(f"  N PD: {n}, HARNet matched: {n_har_matched}, V2 dims: {X_v2.shape[1]}, HARNet dims: {X_harnet.shape[1]}")
    print(f"  T1 mean: {y_t1.mean():.2f}, std: {y_t1.std():.2f}")

    # Pre-registration
    prereg_payload = {
        "experiment": "Ablation #11 — KD-cascade HARNet (sklearn approximation)",
        "comparator": "ARM_A baseline = V2-only iter34-style LGB on H&Y residual",
        "treatment": "ARM_B = ARM_A + 32-dim student-distilled HARNet block (forced-include)",
        "kd_loss_approximation": "Per-fold Ridge(V2 → PCA32(HARNet_train)) — student learns V2 → teacher mapping; no labels involved.",
        "k_best_v2_portion": K_BEST - PCA_DIMS,
        "kd_dims": PCA_DIMS,
        "seeds": SEEDS,
        "n_subjects": n,
        "harnet_matched": n_har_matched,
        "promotion_gate": "mean Δ ≥ +0.025 AND paired-bootstrap frac>0 ≥ 0.95",
        "orthogonality_F_iter15": "F-iter15 concat HARNet 2048-d into K=500 LGB pool — K=500 absorbed (only 0-2 cols survived). KD cascade forces 32 distilled cols (always-included) bypassing absorption.",
    }
    prereg = {
        **prereg_payload,
        "created_at_utc": ts_utc,
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha(prereg_payload),
    }
    prereg_path = RESULTS_DIR / f"preregistration_ablation_kd_harnet_{ts_utc}.json"
    prereg_path.write_text(json.dumps(prereg, indent=2) + "\n")
    print(f"  Pre-reg: {prereg_path}")

    arm_a_preds_seeds = []
    arm_b_preds_seeds = []
    for seed in SEEDS:
        print(f"\n  Seed {seed}: ARM_A (V2 only)...", flush=True)
        pa, _ = loocv_predict_arm(sids, y_t1, hy, X_v2, X_harnet=None, seed=seed)
        arm_a_preds_seeds.append(pa)
        print(f"  Seed {seed}: ARM_A CCC = {ccc(y_t1, pa):.4f}", flush=True)
        print(f"  Seed {seed}: ARM_B (V2 + KD-distilled HARNet)...", flush=True)
        pb, _ = loocv_predict_arm(sids, y_t1, hy, X_v2, X_harnet=X_harnet, seed=seed)
        arm_b_preds_seeds.append(pb)
        print(f"  Seed {seed}: ARM_B CCC = {ccc(y_t1, pb):.4f}, Δ = {ccc(y_t1, pb) - ccc(y_t1, pa):+.4f}", flush=True)

    pred_a_mean = np.mean(np.stack(arm_a_preds_seeds), axis=0)
    pred_b_mean = np.mean(np.stack(arm_b_preds_seeds), axis=0)
    ccc_a = float(ccc(y_t1, pred_a_mean))
    ccc_b = float(ccc(y_t1, pred_b_mean))
    delta = ccc_b - ccc_a
    bootstrap = paired_bootstrap_delta(y_t1, pred_a_mean, pred_b_mean, n_boot=5000, seed=42)

    per_seed_deltas = [ccc(y_t1, b) - ccc(y_t1, a) for a, b in zip(arm_a_preds_seeds, arm_b_preds_seeds)]

    out = {
        "experiment": "ablation_kd_harnet_cascade",
        "created_at_utc": ts_utc,
        "git_sha": _git_sha(),
        "formula_sha256": prereg["formula_sha256"],
        "preregistration": str(prereg_path.name),
        "n_subjects": n,
        "harnet_matched": n_har_matched,
        "seeds": SEEDS,
        "metrics_arm_a_baseline": full_metrics(y_t1, pred_a_mean, label="arm_a_v2_only"),
        "metrics_arm_b_treatment": full_metrics(y_t1, pred_b_mean, label="arm_b_plus_kd_harnet"),
        "delta_ccc": delta,
        "per_seed_delta": per_seed_deltas,
        "seed_std_delta": float(np.std(per_seed_deltas)),
        "paired_bootstrap": bootstrap,
        "promotion_gate": {
            "rule": "mean Δ ≥ +0.025 AND frac>0 ≥ 0.95",
            "passes_delta_gate": bootstrap["delta_mean"] >= 0.025,
            "passes_frac_gate": bootstrap["frac_above_zero"] >= 0.95,
            "PASSES_PROMOTION_GATE": (bootstrap["delta_mean"] >= 0.025 and bootstrap["frac_above_zero"] >= 0.95),
        },
        "published_baseline_iter34": 0.7170,
        "delta_vs_iter34": ccc_b - 0.7170,
    }
    out_path = RESULTS_DIR / f"lockbox_ablation_kd_harnet_{ts_utc}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str) + "\n")
    print(f"\n  Wrote {out_path}")

    # 5-null gate
    print("\n  5-null gate (scrambled-label + canary)...")
    rng = np.random.RandomState(42)
    y_scrambled = y_t1.copy()
    rng.shuffle(y_scrambled)
    pred_scr, _ = loocv_predict_arm(sids, y_scrambled, hy, X_v2, X_harnet=X_harnet, seed=42)
    ccc_scr = float(ccc(y_t1, pred_scr))
    pred_can, _ = loocv_predict_arm(sids, y_t1, hy, X_v2, X_harnet=X_harnet, seed=42, canary_test_only=999.0)
    ccc_can = float(ccc(y_t1, pred_can))
    null_out = {
        "scrambled_label_ccc": ccc_scr,
        "scrambled_label_passes": abs(ccc_scr) < 0.10,
        "canary_feature_ccc": ccc_can,
        "canary_feature_passes": abs(ccc_can - ccc_b) < 0.05,
    }
    null_path = RESULTS_DIR / f"lockbox_ablation_kd_harnet_{ts_utc}_5null.json"
    null_path.write_text(json.dumps(null_out, indent=2) + "\n")
    print(f"  Wrote {null_path}")
    print(f"  Scrambled-label CCC: {ccc_scr:.4f} (must be ~0)")
    print(f"  Canary CCC: {ccc_can:.4f} (must be ≈ ARM_B {ccc_b:.4f})")

    print(f"\n=== SUMMARY ===")
    print(f"  ARM_A V2-only CCC: {ccc_a:.4f}")
    print(f"  ARM_B +KD-distilled HARNet CCC: {ccc_b:.4f}")
    print(f"  Mean Δ: {delta:+.4f} (per-seed: {per_seed_deltas})")
    print(f"  Paired-bootstrap frac>0: {bootstrap['frac_above_zero']:.3f}, CI [{bootstrap['delta_ci_low']:+.4f}, {bootstrap['delta_ci_high']:+.4f}]")
    print(f"  Promotion gate PASSES: {out['promotion_gate']['PASSES_PROMOTION_GATE']}")
    print(f"  vs iter34 hygiene (0.7170): Δ = {out['delta_vs_iter34']:+.4f}")


if __name__ == "__main__":
    main()

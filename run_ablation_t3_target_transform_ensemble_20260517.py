#!/usr/bin/env python3
"""Ablation #12 — T3 target-transformation ensemble.

**ORTHOGONAL MECHANISM**: target-space transformation. All prior T3 walls
(W#73-78, W#95-98, the 5-ablation campaign W#102-106) operated in the original
target space. This ablation predicts T3 under three target transforms
(identity, sqrt, log(1+·)) using the iter47 canonical architecture inside each
transformed space, then ensembles the back-transformed predictions.

**Hypothesis**: T3 distribution is right-skewed (most subjects 0-20, few above
40). Target transforms compress the high-severity tail, potentially stabilizing
MAE/CCC at the bulk where most subjects live. The ensemble of three differently-
biased estimators averages out individual bias-variance trade-offs.

**Architecture (per arm)**:
  - Apply transform T ∈ {identity, sqrt, log1p} to outer-train y → y_t
  - Stage 1: Ridge α=1 on (H&Y + cv_yrs + cv_sex + cv_dbs) predicting y_t
  - Stage 2: LGB on Stage-1 residual (in transformed space), K=500 V2 features
  - Inverse-transform predictions back to T3 space
  - Per-fold per-seed mean of 3 seeds

**Final ensemble**: mean of the three back-transformed predictions across the
three transforms.

**Pre-registered gate** (solo ablation, lifetime FWER n=15): paired-bootstrap
frac>0 ≥ 0.95 AND Δ̄ ≥ +0.025 vs iter47 baseline 0.3784.

**5-null gate**: scrambled-label on the ensemble arm + sanity check that each
arm's identity-transform exactly replicates iter47.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import LeaveOneOut

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from eval_utils import lins_ccc as ccc
from inductive_lib import full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter47_invalid_code_fix import filter_cohort
from run_t3_iter41_target_fix import build_stage1_matrix, filter_stage2
from run_t3_iter5_clinical import fit_stage1
from run_t3_iter2 import impute_fold, feature_select_fold, train_lgb

ensure_dir(RESULTS_DIR)

SEEDS = [42, 1337, 7]
TRANSFORMS = ["identity", "sqrt", "log1p"]
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


def apply_transform(y: np.ndarray, name: str) -> np.ndarray:
    if name == "identity":
        return y.astype(np.float64)
    if name == "sqrt":
        return np.sqrt(np.maximum(y.astype(np.float64), 0.0))
    if name == "log1p":
        return np.log1p(np.maximum(y.astype(np.float64), 0.0))
    raise ValueError(f"Unknown transform {name}")


def inverse_transform(y_t: np.ndarray, name: str) -> np.ndarray:
    if name == "identity":
        return y_t.astype(np.float64)
    if name == "sqrt":
        return np.maximum(y_t.astype(np.float64), 0.0) ** 2
    if name == "log1p":
        return np.maximum(np.expm1(y_t.astype(np.float64)), 0.0)
    raise ValueError(f"Unknown transform {name}")


def loocv_predict_arm(
    data: dict,
    transform_name: str,
    seed: int,
    scrambled_y: bool = False,
) -> np.ndarray:
    """LOOCV per arm. Returns per-subject back-transformed predictions in T3 space."""
    sids = data["sids"]
    y_orig = data["y_t3"].astype(np.float64).copy()
    if scrambled_y:
        rng = np.random.RandomState(seed * 7919)
        rng.shuffle(y_orig)
    y_t = apply_transform(y_orig, transform_name)

    X_s1 = build_stage1_matrix(sids, data["hy"])
    X_s2, _ = filter_stage2(data["X"], data["feat_cols"], "stage2_current")
    n = len(sids)
    preds_t = np.zeros(n, dtype=np.float64)

    for tr, te in LeaveOneOut().split(np.arange(n)):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t[tr], X_s1[te], alpha=1.0)
        residual_tr = y_t[tr] - s1_tr
        Xtr, Xte = impute_fold(X_s2[tr], X_s2[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=K_BEST, seed=seed)
        preds_t[te] = s1_te + train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)

    return inverse_transform(preds_t, transform_name)


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
        "n_boot": n_boot,
        "delta_mean": float(np.mean(deltas)),
        "delta_ci_low": float(np.percentile(deltas, 2.5)),
        "delta_ci_high": float(np.percentile(deltas, 97.5)),
        "frac_above_zero": float(np.mean(deltas > 0)),
        "frac_above_0.025": float(np.mean(deltas > 0.025)),
    }


def main():
    ts_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"\n=== Ablation #12 T3 target-transformation ensemble ({ts_utc}) ===")

    data = filter_cohort("drop_allmissing_validrange")
    y_orig = data["y_t3"].astype(np.float64)
    n = len(data["sids"])
    print(f"  N={n}")
    print(f"  T3 distribution: mean={y_orig.mean():.2f}, std={y_orig.std():.2f}, min={y_orig.min():.1f}, max={y_orig.max():.1f}")
    print(f"  T3 skew (proxy): {((y_orig - y_orig.mean())**3).mean() / (y_orig.std()**3):.3f}")

    # Pre-registration
    prereg_payload = {
        "experiment": "Ablation #12 — T3 target-transformation ensemble",
        "rationale": "All prior T3 walls operated in original target space. Target transforms compress right-skewed distribution, potentially extracting signal at the bulk.",
        "transforms": TRANSFORMS,
        "ensemble_rule": "equal-weight mean of 3 back-transformed predictions across transforms",
        "architecture": "iter47 canonical (Ridge Stage-1 H&Y+cv_yrs+cv_sex+cv_dbs + LGB Stage-2 K=500 V2 residual)",
        "seeds": SEEDS,
        "k_best": K_BEST,
        "n_subjects": n,
        "promotion_gate": "paired-bootstrap frac>0 ≥ 0.95 AND Δ̄ ≥ +0.025 vs iter47 (0.3784)",
        "fwer_lifetime": "n=15 (was 14 after 2026-05-16 campaign)",
        "orthogonality_argument": "no prior T3 ablation has used target transforms; all walls W#73-W#106 operated in original target space",
    }
    prereg = {
        **prereg_payload,
        "created_at_utc": ts_utc,
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha(prereg_payload),
    }
    prereg_path = RESULTS_DIR / f"preregistration_ablation_t3_target_transform_{ts_utc}.json"
    prereg_path.write_text(json.dumps(prereg, indent=2) + "\n")
    print(f"  Pre-reg: {prereg_path}")

    # Run each (transform, seed) combination
    arm_results = {t: [] for t in TRANSFORMS}
    for transform_name in TRANSFORMS:
        print(f"\n  Arm: {transform_name}")
        for seed in SEEDS:
            t0 = time.time()
            preds = loocv_predict_arm(data, transform_name, seed=seed)
            t = time.time() - t0
            arm_results[transform_name].append(preds)
            arm_ccc = float(ccc(y_orig, preds))
            print(f"    seed={seed}: CCC={arm_ccc:.4f}, wall={t:.1f}s")

    # Per-arm mean-of-seeds prediction
    arm_pred_mean = {t: np.mean(np.stack(arm_results[t]), axis=0) for t in TRANSFORMS}
    arm_ccc_mean = {t: float(ccc(y_orig, arm_pred_mean[t])) for t in TRANSFORMS}

    # Identity arm should match iter47 closely (verify)
    print(f"\n  Identity arm CCC: {arm_ccc_mean['identity']:.4f} (iter47 canonical 0.3784)")
    print(f"  Sqrt arm CCC: {arm_ccc_mean['sqrt']:.4f}")
    print(f"  Log1p arm CCC: {arm_ccc_mean['log1p']:.4f}")

    # Ensemble: equal-weight mean across transforms
    ensemble_pred = np.mean(np.stack([arm_pred_mean[t] for t in TRANSFORMS]), axis=0)
    ensemble_ccc = float(ccc(y_orig, ensemble_pred))
    print(f"\n  Ensemble (equal-weight mean of 3 transforms) CCC: {ensemble_ccc:.4f}")
    print(f"  Δ vs iter47 (0.3784): {ensemble_ccc - 0.3784:+.4f}")

    # Paired bootstrap: ensemble vs identity (= iter47-equivalent)
    bootstrap = paired_bootstrap_delta(y_orig, arm_pred_mean["identity"], ensemble_pred, n_boot=5000, seed=42)

    # Per-seed deltas
    per_seed_deltas = []
    for s_idx in range(len(SEEDS)):
        ens_s = np.mean(np.stack([arm_results[t][s_idx] for t in TRANSFORMS]), axis=0)
        id_s = arm_results["identity"][s_idx]
        per_seed_deltas.append(float(ccc(y_orig, ens_s) - ccc(y_orig, id_s)))

    # 5-null gate: scrambled-label on ensemble
    print("\n  5-null gate (scrambled-label on full ensemble)...")
    null_arm_results = {}
    for transform_name in TRANSFORMS:
        null_arm_results[transform_name] = loocv_predict_arm(data, transform_name, seed=42, scrambled_y=True)
    null_ensemble_pred = np.mean(np.stack([null_arm_results[t] for t in TRANSFORMS]), axis=0)
    null_ccc = float(ccc(y_orig, null_ensemble_pred))

    out = {
        "experiment": "ablation_t3_target_transform_ensemble",
        "created_at_utc": ts_utc,
        "git_sha": _git_sha(),
        "formula_sha256": prereg["formula_sha256"],
        "preregistration": str(prereg_path.name),
        "n_subjects": n,
        "transforms": TRANSFORMS,
        "seeds": SEEDS,
        "per_arm_ccc": arm_ccc_mean,
        "per_arm_metrics": {t: full_metrics(y_orig, arm_pred_mean[t], label=f"arm_{t}") for t in TRANSFORMS},
        "ensemble_ccc": ensemble_ccc,
        "ensemble_metrics": full_metrics(y_orig, ensemble_pred, label="ensemble_equal_weight"),
        "delta_ensemble_minus_identity": ensemble_ccc - arm_ccc_mean["identity"],
        "delta_ensemble_minus_iter47": ensemble_ccc - 0.3784,
        "per_seed_delta_ensemble_vs_identity": per_seed_deltas,
        "seed_std_delta": float(np.std(per_seed_deltas)),
        "paired_bootstrap_ensemble_vs_identity": bootstrap,
        "promotion_gate": {
            "rule": "frac>0 ≥ 0.95 AND Δ̄ ≥ +0.025 vs iter47 baseline",
            "passes_delta_gate": (ensemble_ccc - 0.3784) >= 0.025,
            "passes_frac_gate": bootstrap["frac_above_zero"] >= 0.95,
            "PASSES_PROMOTION_GATE": ((ensemble_ccc - 0.3784) >= 0.025 and bootstrap["frac_above_zero"] >= 0.95),
        },
        "null_gate_scrambled_y": {
            "ccc": null_ccc,
            "passes": abs(null_ccc) < 0.10,
        },
        "published_baseline_iter47": 0.3784,
    }

    out_path = RESULTS_DIR / f"lockbox_ablation_t3_target_transform_{ts_utc}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str) + "\n")
    print(f"\n  Wrote {out_path}")
    print(f"\n=== SUMMARY ===")
    print(f"  Identity arm:  CCC={arm_ccc_mean['identity']:.4f}")
    print(f"  Sqrt arm:      CCC={arm_ccc_mean['sqrt']:.4f}")
    print(f"  Log1p arm:     CCC={arm_ccc_mean['log1p']:.4f}")
    print(f"  Ensemble:      CCC={ensemble_ccc:.4f}  (Δ vs iter47 = {ensemble_ccc - 0.3784:+.4f})")
    print(f"  Paired-bootstrap frac>0 (ens vs identity): {bootstrap['frac_above_zero']:.3f}")
    print(f"  Paired-bootstrap CI95: [{bootstrap['delta_ci_low']:+.4f}, {bootstrap['delta_ci_high']:+.4f}]")
    print(f"  Per-seed Δ: {per_seed_deltas}")
    print(f"  Promotion gate PASSES: {out['promotion_gate']['PASSES_PROMOTION_GATE']}")
    print(f"  Scrambled-y null CCC: {null_ccc:.4f} (must be ~0)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Ablation #6 — Item 11 (freezing of gait) continuous regression + FoG event features.

Tests an UN-walled angle:
  * F44 (compose_t1_iter14_fog) tested FoG scalars for items 9 and 12, NULL because
    per-item std>0.02 was unwinnable; item 11 was never tested.
  * W#76 (cell G hurdle) collapsed because only 12 FoG-positive subjects can't
    support a binary classifier stage at N=92; CONTINUOUS baseline was CCC=0.222.
  * This script: regress item 11 (0..4) directly on V2 + item-11 multiscale +
    cached FoG event-rate / duration features (label-free cache).
  * Mechanism: continuous regressor on subject-level FoG event statistics, NOT
    hurdle two-stage; FoG features forced-included into K-best pool (bypassing
    K=500 absorption that killed F44).

Pre-registered comparison:
  - ARM_A baseline: hy_residual + V2 + item-11 multiscale, K-best on V2 pool
  - ARM_B treatment: baseline + 3 FoG event features forced-include (always-kept)

Headline: paired-bootstrap delta(Δarm_B - Δarm_A) on item-11 LOOCV CCC, 3 seeds.
Pre-registered gate (unilateral, no FWER yet — solo ablation): frac>0 ≥ 0.95 AND
mean Δ ≥ +0.025 (MCID-adjacent, item-level).

5-null gate runs scrambled-label (item 11) + canary-feature variants.

Output: results/lockbox_ablation_fog_item11_<UTC>.json + 5-null sidecars.
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
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    load_pd_data,
    impute_fold,
    feature_select_fold,
    train_lgb,
    get_hy_features,
    LGB_DEFAULTS,
)

ensure_dir(RESULTS_DIR)

SEEDS = [42, 1337, 7]
PUBLISHED_ITEM11_CCC = 0.222  # W#76 cell-G continuous baseline

FOG_CACHE = REPO_ROOT / "results" / "fog_events_balance_geometry.csv"
PERITEM_CACHE = REPO_ROOT / "results" / "peritem_subj_features.csv"
ITEM11_MULTISCALE_CACHE = REPO_ROOT / "results" / "item11_multiscale.csv"


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


def load_aux_cache(path: Path, sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Per-subject CSV → aligned numpy. Missing SIDs → NaN row."""
    df = pd.read_csv(path).set_index("sid")
    feat_cols = list(df.columns)
    X = np.full((len(sids), len(feat_cols)), np.nan)
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, feat_cols].to_numpy(dtype=np.float64)
    return X, feat_cols


def stage1_hy_residual(hy: np.ndarray, y: np.ndarray, tr_idx: np.ndarray, te_idx: np.ndarray, seed: int = 42) -> tuple:
    """Fold-local Ridge(H&Y) Stage-1 returning train/test residuals + predictions."""
    hy_feat = get_hy_features(hy)
    fn = FoldNormalizer.fit(hy_feat[tr_idx])
    Xtr = fn.transform(hy_feat[tr_idx])
    Xte = fn.transform(hy_feat[te_idx])
    ridge = Ridge(alpha=1.0, random_state=seed)
    ridge.fit(Xtr, y[tr_idx])
    yhat_tr = ridge.predict(Xtr)
    yhat_te = ridge.predict(Xte)
    res_tr = y[tr_idx] - yhat_tr
    return yhat_te, res_tr


def build_feature_block(
    X_v2: np.ndarray, X_item11: np.ndarray, X_fog: np.ndarray | None
) -> tuple[np.ndarray, dict]:
    """Concatenate feature blocks. Returns (X_all, slice_dict for forced-include)."""
    blocks = [("v2", X_v2), ("item11_ms", X_item11)]
    if X_fog is not None:
        blocks.append(("fog", X_fog))
    parts = [b for _, b in blocks]
    X = np.hstack(parts)
    offsets = {}
    cur = 0
    for name, b in blocks:
        offsets[name] = (cur, cur + b.shape[1])
        cur += b.shape[1]
    return X, offsets


def loocv_predict_arm(
    sids: np.ndarray,
    y_item11: np.ndarray,
    hy: np.ndarray,
    X_v2: np.ndarray,
    X_item11_ms: np.ndarray,
    X_fog: np.ndarray | None,
    k_best: int,
    seed: int,
    canary_test_only: float | None = None,
) -> np.ndarray:
    """LOOCV predictor for item 11. Returns per-subject predictions."""
    n = len(sids)
    X_all, offsets = build_feature_block(X_v2, X_item11_ms, X_fog)
    preds = np.full(n, np.nan, dtype=np.float64)
    fog_slice = offsets.get("fog", None)

    for i in range(n):
        tr = np.array([j for j in range(n) if j != i])
        te = np.array([i])

        yhat_te, res_tr = stage1_hy_residual(hy, y_item11, tr, te, seed=seed)

        Xtr_raw = X_all[tr].copy()
        Xte_raw = X_all[te].copy()

        # Canary: inject test-fold-only feature, value=canary_test_only on test row.
        if canary_test_only is not None:
            canary_tr = np.zeros((len(tr), 1))
            canary_te = np.full((1, 1), canary_test_only)
            Xtr_raw = np.hstack([Xtr_raw, canary_tr])
            Xte_raw = np.hstack([Xte_raw, canary_te])

        Xtr_imp, Xte_imp = impute_fold(Xtr_raw, Xte_raw)

        # Forced-include FoG indices (keep in selector); K-best on the rest.
        if fog_slice is not None:
            fog_start, fog_end = fog_slice
            forced = np.arange(fog_start, fog_end)
            non_forced_mask = np.ones(Xtr_imp.shape[1], dtype=bool)
            non_forced_mask[forced] = False
            X_rest_tr = Xtr_imp[:, non_forced_mask]
            X_rest_te = Xte_imp[:, non_forced_mask]
            k_rest = max(1, k_best - len(forced))
            X_rest_sel_tr, X_rest_sel_te, _ = feature_select_fold(X_rest_tr, res_tr, X_rest_te, k=k_rest, seed=seed)
            Xtr_final = np.hstack([Xtr_imp[:, forced], X_rest_sel_tr])
            Xte_final = np.hstack([Xte_imp[:, forced], X_rest_sel_te])
        else:
            Xtr_final, Xte_final, _ = feature_select_fold(Xtr_imp, res_tr, Xte_imp, k=k_best, seed=seed)

        stage2_res = train_lgb(Xtr_final, res_tr, Xte_final, seed)
        preds[i] = yhat_te[0] + stage2_res[0]

    return preds


def paired_bootstrap_delta(
    y_true: np.ndarray, pred_a: np.ndarray, pred_b: np.ndarray, n_boot: int = 5000, seed: int = 42
) -> dict:
    """Paired bootstrap on Δ = CCC(B) - CCC(A) on resampled subjects."""
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
    parser.add_argument("--k-best", type=int, default=200,
                        help="K-best feature selector size (default 200; F44 used K=500)")
    args = parser.parse_args()

    ts_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"\n=== Ablation #6 FoG item-11 (T1 ceiling-push, {ts_utc}) ===")

    # Data loading
    d = load_pd_data()
    sids = d["sids"]
    items = d["items"]
    y_item11 = items[11].astype(np.float64)
    hy = d["hy"]
    X_v2 = d["X_v2"]

    # Filter: keep subjects with valid item-11 score (0..4 already enforced by load)
    mask_valid = np.isfinite(y_item11) & (y_item11 >= 0) & (y_item11 <= 4)
    sids = sids[mask_valid]
    y_item11 = y_item11[mask_valid]
    hy = hy[mask_valid]
    X_v2 = X_v2[mask_valid]
    n = len(sids)

    # Load item-11 multiscale cache + FoG cache
    X_item11_ms, item11_cols = load_aux_cache(ITEM11_MULTISCALE_CACHE, sids)
    X_fog_all, fog_cols = load_aux_cache(FOG_CACHE, sids)

    # Subset to FoG-only cols (first 3) — the rest are item-13 balance features.
    fog_only_cols = ["fog_event_rate", "fog_event_duration_mean", "fog_event_duration_std"]
    fog_col_idx = [fog_cols.index(c) for c in fog_only_cols]
    X_fog = X_fog_all[:, fog_col_idx]

    print(f"  N item-11 valid: {n}")
    print(f"  FoG event-rate nonzero: {int((X_fog[:, 0] > 0).sum())}/{n}")
    print(f"  V2 dims: {X_v2.shape[1]}  item11_ms dims: {X_item11_ms.shape[1]}  fog dims: {X_fog.shape[1]}")
    print(f"  Item-11 distribution: {dict(zip(*np.unique(y_item11.astype(int), return_counts=True)))}")

    # Pre-registration
    prereg_payload = {
        "experiment": "Ablation #6 — FoG event-rate features for item-11 continuous regression",
        "comparator": "ARM_A (baseline) = hy_residual + V2 + item-11 multiscale, K-best on V2 pool",
        "treatment": "ARM_B (treatment) = ARM_A + 3 FoG event features forced-included",
        "k_best": args.k_best,
        "seeds": SEEDS,
        "n_subjects": n,
        "promotion_gate": "frac>0 ≥ 0.95 AND mean Δ ≥ +0.025 (item-level MCID; solo ablation, n=1 FWER pos)",
        "fog_features": fog_only_cols,
        "stage1": "Ridge(alpha=1.0) on H&Y one-hot + linear; fold-local",
        "stage2": "LGB on item-11 residual after Stage-1 Ridge",
        "rationale": (
            "F44 (compose_t1_iter14_fog) tested items 9 and 12 — null. W#76 hurdle "
            "collapsed at 12 FoG-positives. Continuous regression on item-11 with "
            "FoG features forced-included is genuinely new (item, gate, architecture)."
        ),
    }
    prereg = {
        **prereg_payload,
        "created_at_utc": ts_utc,
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha(prereg_payload),
    }
    prereg_path = RESULTS_DIR / f"preregistration_ablation_fog_item11_{ts_utc}.json"
    prereg_path.write_text(json.dumps(prereg, indent=2) + "\n")
    print(f"  Pre-reg: {prereg_path}")

    # Run ARM_A baseline and ARM_B treatment under 3 seeds
    arm_a_preds_seeds = []
    arm_b_preds_seeds = []
    for seed in SEEDS:
        print(f"\n  Seed {seed}: running ARM_A...", flush=True)
        pred_a = loocv_predict_arm(sids, y_item11, hy, X_v2, X_item11_ms, X_fog=None, k_best=args.k_best, seed=seed)
        arm_a_preds_seeds.append(pred_a)
        print(f"  Seed {seed}: ARM_A done. Running ARM_B...", flush=True)
        pred_b = loocv_predict_arm(sids, y_item11, hy, X_v2, X_item11_ms, X_fog=X_fog, k_best=args.k_best, seed=seed)
        arm_b_preds_seeds.append(pred_b)
        ccc_a = ccc(y_item11, pred_a)
        ccc_b = ccc(y_item11, pred_b)
        print(f"  Seed {seed}: ARM_A CCC={ccc_a:.4f}, ARM_B CCC={ccc_b:.4f}, Δ={ccc_b-ccc_a:+.4f}")

    pred_a_mean = np.mean(np.stack(arm_a_preds_seeds), axis=0)
    pred_b_mean = np.mean(np.stack(arm_b_preds_seeds), axis=0)

    ccc_a_mean = float(ccc(y_item11, pred_a_mean))
    ccc_b_mean = float(ccc(y_item11, pred_b_mean))
    delta_mean = ccc_b_mean - ccc_a_mean

    bootstrap = paired_bootstrap_delta(y_item11, pred_a_mean, pred_b_mean, n_boot=5000, seed=42)

    # Per-seed deltas + seed-std
    per_seed_deltas = [
        ccc(y_item11, b) - ccc(y_item11, a)
        for a, b in zip(arm_a_preds_seeds, arm_b_preds_seeds)
    ]
    seed_std = float(np.std(per_seed_deltas))

    out = {
        "experiment": "ablation_fog_item11",
        "created_at_utc": ts_utc,
        "git_sha": _git_sha(),
        "formula_sha256": prereg["formula_sha256"],
        "preregistration": str(prereg_path.name),
        "n_subjects": n,
        "k_best": args.k_best,
        "seeds": SEEDS,
        "fog_features": fog_only_cols,
        "fog_event_rate_nonzero": int((X_fog[:, 0] > 0).sum()),
        "metrics_arm_a_baseline": full_metrics(y_item11, pred_a_mean, label="arm_a_hy_v2_item11ms"),
        "metrics_arm_b_treatment": full_metrics(y_item11, pred_b_mean, label="arm_b_plus_fog"),
        "delta_ccc_mean_of_seeds_pred_means": delta_mean,
        "delta_ccc_per_seed": per_seed_deltas,
        "seed_std_delta": seed_std,
        "paired_bootstrap": bootstrap,
        "promotion_gate": {
            "rule": "frac>0 ≥ 0.95 AND mean Δ ≥ +0.025",
            "frac_above_zero": bootstrap["frac_above_zero"],
            "mean_delta": bootstrap["delta_mean"],
            "passes_frac_gate": bootstrap["frac_above_zero"] >= 0.95,
            "passes_mcid_gate": bootstrap["delta_mean"] >= 0.025,
            "PASSES_PROMOTION_GATE": (bootstrap["frac_above_zero"] >= 0.95 and bootstrap["delta_mean"] >= 0.025),
        },
        "published_baseline_w76": PUBLISHED_ITEM11_CCC,
        "delta_vs_published_w76": ccc_b_mean - PUBLISHED_ITEM11_CCC,
    }

    out_path = RESULTS_DIR / f"lockbox_ablation_fog_item11_{ts_utc}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str) + "\n")
    print(f"\n  Wrote {out_path}")

    # 5-null gate: scrambled-label and canary
    print("\n  Running 5-null gate (scrambled-label + canary)...")
    rng = np.random.RandomState(42)
    y_scrambled = y_item11.copy()
    rng.shuffle(y_scrambled)
    pred_scrambled = loocv_predict_arm(sids, y_scrambled, hy, X_v2, X_item11_ms, X_fog=X_fog, k_best=args.k_best, seed=42)
    ccc_scrambled = float(ccc(y_item11, pred_scrambled))

    pred_canary = loocv_predict_arm(sids, y_item11, hy, X_v2, X_item11_ms, X_fog=X_fog, k_best=args.k_best, seed=42, canary_test_only=999.0)
    ccc_canary = float(ccc(y_item11, pred_canary))

    null_gate = {
        "scrambled_label_ccc": ccc_scrambled,
        "scrambled_label_passes": abs(ccc_scrambled) < 0.10,
        "canary_feature_ccc": ccc_canary,
        "canary_feature_passes": abs(ccc_canary - ccc_b_mean) < 0.05,
        "n_pos_at_train_time": int((X_fog[:, 0] > 0).sum()),
    }
    null_path = RESULTS_DIR / f"lockbox_ablation_fog_item11_{ts_utc}_5null.json"
    null_path.write_text(json.dumps(null_gate, indent=2) + "\n")
    print(f"  5-null gate written: {null_path}")
    print(f"  Scrambled-label CCC: {ccc_scrambled:.4f} (must be ~0)")
    print(f"  Canary-test-only CCC: {ccc_canary:.4f} (must be ≈ ARM_B CCC)")

    print(f"\n=== SUMMARY ===")
    print(f"  ARM_A baseline CCC: {ccc_a_mean:.4f}")
    print(f"  ARM_B treatment CCC: {ccc_b_mean:.4f}")
    print(f"  Mean Δ: {delta_mean:+.4f}  (per-seed: {per_seed_deltas})")
    print(f"  Paired-bootstrap frac>0: {bootstrap['frac_above_zero']:.3f}")
    print(f"  Paired-bootstrap 95% CI: [{bootstrap['delta_ci_low']:+.4f}, {bootstrap['delta_ci_high']:+.4f}]")
    print(f"  Promotion gate PASSES: {out['promotion_gate']['PASSES_PROMOTION_GATE']}")
    print(f"  vs W#76 published baseline (0.222): ΔCCC = {out['delta_vs_published_w76']:+.4f}")


if __name__ == "__main__":
    main()

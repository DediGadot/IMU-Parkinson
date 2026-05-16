"""T3-A: 5-fold screen ONLY — V3-GSP injection into T3 Stage-2 LGB.

Pre-registered as a FALSIFY-FAST kill-the-experiment-early probe.
4-CLI consensus prior on clearing +0.025 MCID: mean 9% (range 3-15%).
Tri-CLI kill criteria:
  - 5-fold Δ < +0.010 OR
  - Seed-std > 0.025 OR
  - Top-K=500 LGB importance picks ≤ 2 GSP features.

If kill criteria triggered, NO LOOCV is run (per master pre-reg).

Architecture:
  Cohort: drop_allmissing_validrange, N=95.
  Stage-1: Ridge on H&Y + cv_yrs + cv_sex + cv_dbs (iter47 architecture).
  Stage-2 baseline: LGB on K=500 V2 (univariate-corr K-best on residual).
  Stage-2 augmented: LGB on K=500 from V2+GSP unified feature pool (univariate-corr).
  5-fold subject-level CV. 3 seeds. Compare delta Δ_CCC mean and std.

Output: results/lockbox_t3_a_gsp_screen_<TS>.json with verdict.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldImputer, FoldNormalizer, full_metrics
from eval_utils import lins_ccc as ccc
from project_paths import RESULTS_DIR
from run_t3_iter47_invalid_code_fix import filter_cohort

K_BEST = 500
SEEDS = (42, 1337, 7)
N_FOLDS = 5
KILL_DELTA = 0.010
KILL_SEED_STD = 0.025
KILL_GSP_TOP_FEATURES = 2  # if fewer than this many GSP features in top-50, kill


def _univariate_kselect(X: np.ndarray, y: np.ndarray, k: int) -> np.ndarray:
    if X.shape[1] <= k:
        return np.arange(X.shape[1])
    y_c = y - y.mean()
    X_c = X - X.mean(axis=0)
    X_std = X.std(axis=0) + 1e-9
    y_std = y.std() + 1e-9
    corr = (X_c * y_c[:, None]).sum(axis=0) / ((X_std * y_std) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]


def _stage1_ridge(X_clinical: np.ndarray, y: np.ndarray, alpha: float = 1.0):
    from sklearn.linear_model import Ridge

    m = Ridge(alpha=alpha)
    m.fit(X_clinical, y)
    return m


def _fit_lgb(X_train: np.ndarray, y_train: np.ndarray, seed: int):
    try:
        from lightgbm import LGBMRegressor

        return LGBMRegressor(
            n_estimators=500,
            learning_rate=0.05,
            num_leaves=15,
            min_data_in_leaf=10,
            feature_fraction=0.8,
            bagging_fraction=0.8,
            bagging_freq=3,
            verbose=-1,
            random_state=seed,
        ).fit(X_train, y_train)
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingRegressor

        return HistGradientBoostingRegressor(
            random_state=seed,
            max_iter=500,
            learning_rate=0.05,
            max_leaf_nodes=15,
            min_samples_leaf=10,
        ).fit(X_train, y_train)


def run_5fold(
    X_v2: np.ndarray,
    X_aug: np.ndarray,
    feat_cols_v2: list[str],
    feat_cols_aug: list[str],
    sids: np.ndarray,
    y: np.ndarray,
    X_clinical: np.ndarray,
    seed: int,
) -> dict:
    """Run a single seed of 5-fold CV. Return baseline and augmented CCC per fold."""
    kf = KFold(n_splits=N_FOLDS, shuffle=True, random_state=seed)
    base_preds = np.zeros_like(y)
    aug_preds = np.zeros_like(y)
    gsp_top_feature_counts = []
    for fold_idx, (tr, te) in enumerate(kf.split(sids)):
        # Stage 1 (clinical Ridge)
        m1 = _stage1_ridge(X_clinical[tr], y[tr])
        s1_tr = m1.predict(X_clinical[tr])
        s1_te = m1.predict(X_clinical[te])
        resid_tr = y[tr] - s1_tr

        # Stage 2 baseline (V2 only)
        X_v2_tr, X_v2_te = X_v2[tr], X_v2[te]
        imp = FoldImputer.fit(X_v2_tr)
        X_v2_tr_imp = imp.transform(X_v2_tr)
        X_v2_te_imp = imp.transform(X_v2_te)
        sel_base = _univariate_kselect(X_v2_tr_imp, resid_tr, K_BEST)
        base_m = _fit_lgb(X_v2_tr_imp[:, sel_base], resid_tr, seed)
        base_preds[te] = s1_te + base_m.predict(X_v2_te_imp[:, sel_base])

        # Stage 2 augmented (V2+GSP)
        X_aug_tr, X_aug_te = X_aug[tr], X_aug[te]
        imp2 = FoldImputer.fit(X_aug_tr)
        X_aug_tr_imp = imp2.transform(X_aug_tr)
        X_aug_te_imp = imp2.transform(X_aug_te)
        sel_aug = _univariate_kselect(X_aug_tr_imp, resid_tr, K_BEST)
        aug_m = _fit_lgb(X_aug_tr_imp[:, sel_aug], resid_tr, seed)
        aug_preds[te] = s1_te + aug_m.predict(X_aug_te_imp[:, sel_aug])

        # Count GSP features in top-50 importance
        try:
            importance = aug_m.feature_importances_
        except AttributeError:
            importance = np.ones(len(sel_aug))
        order = np.argsort(-importance)[:50]
        top50_global_idx = sel_aug[order]
        n_gsp_top50 = sum(1 for i in top50_global_idx if feat_cols_aug[i].startswith("gsp_"))
        gsp_top_feature_counts.append(n_gsp_top50)

    m_base = full_metrics(y, base_preds, label=f"baseline_seed{seed}")
    m_aug = full_metrics(y, aug_preds, label=f"augmented_seed{seed}")
    return {
        "seed": seed,
        "base_ccc": m_base["ccc"],
        "aug_ccc": m_aug["ccc"],
        "delta_ccc": round(m_aug["ccc"] - m_base["ccc"], 4),
        "gsp_top50_counts_per_fold": gsp_top_feature_counts,
        "mean_gsp_top50": float(np.mean(gsp_top_feature_counts)),
        "base_pred_mean": float(base_preds.mean()),
        "aug_pred_mean": float(aug_preds.mean()),
        "y_true_mean": float(y.mean()),
        "y_true_std": float(y.std()),
    }


def main():
    print("=" * 72)
    print("T3-A 5-fold screen: V3-GSP injection into iter47 Stage-2")
    print("=" * 72)
    print(f"  4-CLI prior P(clear +0.025) = 9% mean; kill criteria pre-registered.")

    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    feat_cols_v2 = data["feat_cols"]
    y = data["y_t3"]
    print(f"  N={len(sids)}, V2 feat dim={X_v2.shape[1]}")

    # Clinical features (Stage 1) — find cv_* columns
    clin_cols = [
        i for i, c in enumerate(feat_cols_v2)
        if c.startswith("cv_") or c == "hy"
    ]
    if "hy" not in feat_cols_v2:
        # H&Y is separate column
        X_clinical = np.column_stack([data["hy"], X_v2[:, clin_cols]]) if len(clin_cols) > 0 else data["hy"].reshape(-1, 1)
    else:
        X_clinical = X_v2[:, clin_cols]
    print(f"  Stage-1 clinical feats: {X_clinical.shape[1]} cols (cv_* + hy)")

    # Load GSP cache
    gsp_df = pd.read_csv(REPO_ROOT / "results" / "v3_gsp_features.csv")
    gsp_lookup = {str(s): i for i, s in enumerate(gsp_df["sid"].astype(str))}
    missing = [s for s in sids if s not in gsp_lookup]
    if missing:
        print(f"  WARNING: GSP cache missing {len(missing)} SIDs: {missing[:3]}...")
        # Impute missing rows with NaN — FoldImputer will handle
        gsp_cols = [c for c in gsp_df.columns if c != "sid"]
        X_gsp_aligned = np.full((len(sids), len(gsp_cols)), np.nan)
        for i, s in enumerate(sids):
            if s in gsp_lookup:
                X_gsp_aligned[i] = gsp_df.iloc[gsp_lookup[s]][gsp_cols].to_numpy()
    else:
        gsp_cols = [c for c in gsp_df.columns if c != "sid"]
        aligned_idx = np.array([gsp_lookup[s] for s in sids])
        X_gsp_aligned = gsp_df.iloc[aligned_idx][gsp_cols].to_numpy()

    # Rename GSP cols with "gsp_" prefix if not already
    gsp_cols_prefixed = [c if c.startswith("gsp_") else f"gsp_{c}" for c in gsp_cols]
    print(f"  GSP aligned dim={X_gsp_aligned.shape}")

    # Augmented feature matrix = V2 ⊕ GSP
    X_aug = np.column_stack([X_v2, X_gsp_aligned])
    feat_cols_aug = feat_cols_v2 + gsp_cols_prefixed
    print(f"  Augmented dim={X_aug.shape}")

    # Run 5-fold per seed
    results = []
    t0 = time.time()
    for seed in SEEDS:
        print(f"\n  === seed={seed} ===", flush=True)
        r = run_5fold(X_v2, X_aug, feat_cols_v2, feat_cols_aug, sids, y, X_clinical, seed)
        print(
            f"  seed={seed} base={r['base_ccc']:.4f} aug={r['aug_ccc']:.4f} "
            f"Δ={r['delta_ccc']:+.4f} GSP_top50={r['mean_gsp_top50']:.1f}",
            flush=True,
        )
        results.append(r)

    deltas = [r["delta_ccc"] for r in results]
    delta_mean = float(np.mean(deltas))
    delta_std = float(np.std(deltas))
    mean_gsp_top = float(np.mean([r["mean_gsp_top50"] for r in results]))

    # Kill criteria
    killed_by_delta = delta_mean < KILL_DELTA
    killed_by_std = delta_std > KILL_SEED_STD
    killed_by_gsp = mean_gsp_top < KILL_GSP_TOP_FEATURES
    verdict = (
        "KILL" if (killed_by_delta or killed_by_std or killed_by_gsp)
        else "CLEAR_TO_LOOCV"
    )

    formula_sha = hashlib.sha256(
        json.dumps(
            {
                "cohort": "drop_allmissing_validrange",
                "k_best": K_BEST,
                "seeds": list(SEEDS),
                "n_folds": N_FOLDS,
                "stage1": "ridge_clinical",
                "stage2": "lgb_v2_vs_v2_gsp_kbest",
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    summary = {
        "name": "t3_a_gsp_screen",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formula_sha256": formula_sha,
        "mode": "5fold_screen_only",
        "n_subjects": int(len(sids)),
        "cohort": "drop_allmissing_validrange",
        "per_seed_results": results,
        "delta_mean": round(delta_mean, 4),
        "delta_std": round(delta_std, 4),
        "mean_gsp_in_top50": round(mean_gsp_top, 2),
        "kill_criteria": {
            "delta_min": KILL_DELTA,
            "seed_std_max": KILL_SEED_STD,
            "gsp_top_min": KILL_GSP_TOP_FEATURES,
            "killed_by_delta": killed_by_delta,
            "killed_by_std": killed_by_std,
            "killed_by_gsp": killed_by_gsp,
        },
        "verdict": verdict,
        "ccc_baseline_seed_42_iter47_canonical": 0.3784,
        "tri_cli_prior_clearing_+0.025": "9% mean (3-15% range)",
        "decision": "If KILL: no LOOCV. If CLEAR: promote to LOOCV.",
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t3_a_gsp_screen_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\n  Δ mean={delta_mean:+.4f} std={delta_std:.4f}")
    print(f"  GSP in top-50: {mean_gsp_top:.1f} per fold")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out_path}")
    print(f"  Wall: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

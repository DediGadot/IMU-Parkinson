"""T3-A LOOCV — V3-GSP injection into iter47 Stage-2 (post 5-fold-CLEAR promotion).

5-fold screen (2026-05-12T21:20Z, run_t3_a_gsp_screen.py) cleared kill criteria:
  Δ mean=+0.0337, seed_std=0.0082, GSP_top50=3.7. Verdict CLEAR_TO_LOOCV.

This script runs the canonical LOOCV at N=95 with REAL LightGBM (not the
sklearn HistGradientBoosting fallback the 5-fold screen used locally).

Architecture (matches iter47 exactly except for the augmented K=500 pool):
  Stage-1: Ridge alpha=1.0 on cv_yrs + cv_sex + cv_dbs + H&Y (clinical).
  Stage-2: LGB with K=500 univariate-corr K-best on V2+GSP unified pool.
  Cohort: drop_allmissing_validrange, N=95.
  Seeds: (42, 1337, 7). Mean of 3 seed preds.

Pre-registered gates (vs iter47 stage2_current N=95 baseline CCC=0.3784):
  Primary: LOOCV CCC delta ≥ +0.025.
  Bonferroni n=3 (T3 family vs iter47): paired-bootstrap frac>0 ≥ 0.9833.
  Sign-flip permutation p ≤ 0.0167.

Output: results/lockbox_t3_a_gsp_loocv_<TS>.json + .oof.npy
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
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldImputer, full_metrics
from eval_utils import lins_ccc as ccc
from run_t3_iter47_invalid_code_fix import filter_cohort

K_BEST = 500
SEEDS = (42, 1337, 7)
ITER47_BASELINE_CCC = 0.3784
MCID = 0.025
BONFERRONI_FRAC_GT = 0.9833  # n=3 FWER


def _univariate_kselect(X: np.ndarray, y: np.ndarray, k: int) -> np.ndarray:
    if X.shape[1] <= k:
        return np.arange(X.shape[1])
    y_c = y - y.mean()
    X_c = X - X.mean(axis=0)
    X_std = X.std(axis=0) + 1e-9
    y_std = y.std() + 1e-9
    corr = (X_c * y_c[:, None]).sum(axis=0) / ((X_std * y_std) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]


def _fit_lgb(X_train: np.ndarray, y_train: np.ndarray, seed: int):
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


def loocv_iter47_aug(
    X_v2: np.ndarray,
    X_gsp: np.ndarray,
    feat_cols_v2: list[str],
    feat_cols_gsp: list[str],
    X_clinical: np.ndarray,
    y: np.ndarray,
    seed: int,
    augmented: bool,
) -> np.ndarray:
    n = len(y)
    preds = np.zeros(n)
    if augmented:
        X = np.column_stack([X_v2, X_gsp])
        feat_cols = feat_cols_v2 + feat_cols_gsp
    else:
        X = X_v2
        feat_cols = feat_cols_v2

    loo = LeaveOneOut()
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(loo.split(X)):
        # Stage 1
        m1 = Ridge(alpha=1.0)
        m1.fit(X_clinical[tr], y[tr])
        s1_tr = m1.predict(X_clinical[tr])
        s1_te = m1.predict(X_clinical[te])
        resid_tr = y[tr] - s1_tr

        # Stage 2
        imp = FoldImputer.fit(X[tr])
        X_tr_imp = imp.transform(X[tr])
        X_te_imp = imp.transform(X[te])
        sel = _univariate_kselect(X_tr_imp, resid_tr, K_BEST)
        m2 = _fit_lgb(X_tr_imp[:, sel], resid_tr, seed)
        preds[te[0]] = float(s1_te[0] + m2.predict(X_te_imp[:, sel])[0])

        if (fold_idx + 1) % 10 == 0:
            print(
                f"  seed={seed} aug={augmented} fold {fold_idx+1}/{n} "
                f"elapsed={time.time()-t0:.1f}s",
                flush=True,
            )
    return preds


def paired_bootstrap(y, pa, pb, n_boot=5000, seed=42):
    rng = np.random.RandomState(seed)
    n = len(y)
    deltas = np.zeros(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, n)
        deltas[i] = ccc(y[idx], pb[idx]) - ccc(y[idx], pa[idx])
    return (
        float(deltas.mean()),
        float(np.percentile(deltas, 2.5)),
        float(np.percentile(deltas, 97.5)),
        float((deltas > 0).mean()),
    )


def sign_flip_p(y, pa, pb, n_perms=10000, seed=42):
    rng = np.random.RandomState(seed)
    se_a = (y - pa) ** 2
    se_b = (y - pb) ** 2
    diffs = se_b - se_a
    obs = -diffs.mean()
    n = len(diffs)
    perm = np.empty(n_perms)
    for i in range(n_perms):
        flips = rng.choice([-1.0, 1.0], size=n)
        perm[i] = -(diffs * flips).mean()
    return float(obs), float((perm >= obs).mean())


def main():
    print("=" * 72)
    print("T3-A LOOCV: V3-GSP injection into iter47 Stage-2 (REAL LGB)")
    print("=" * 72)

    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    feat_cols_v2 = data["feat_cols"]
    y = data["y_t3"]
    print(f"  N={len(sids)}, V2 dim={X_v2.shape[1]}")

    # Build clinical matrix (cv_yrs + cv_sex + cv_dbs + hy)
    clin_cols = [i for i, c in enumerate(feat_cols_v2) if c.startswith("cv_")]
    X_clinical_cv = X_v2[:, clin_cols] if clin_cols else np.zeros((len(sids), 0))
    X_clinical = np.column_stack([data["hy"], X_clinical_cv])
    print(f"  Stage-1 clinical dim={X_clinical.shape[1]}")

    # GSP cache
    gsp_df = pd.read_csv(REPO_ROOT / "results" / "v3_gsp_features.csv")
    gsp_lookup = {str(s): i for i, s in enumerate(gsp_df["sid"].astype(str))}
    gsp_cols = [c for c in gsp_df.columns if c != "sid"]
    X_gsp_aligned = np.full((len(sids), len(gsp_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in gsp_lookup:
            X_gsp_aligned[i] = gsp_df.iloc[gsp_lookup[s]][gsp_cols].to_numpy()
    feat_cols_gsp = [f"gsp_{c}" if not c.startswith("gsp_") else c for c in gsp_cols]
    print(f"  GSP dim={X_gsp_aligned.shape[1]}; missing rows = {np.isnan(X_gsp_aligned).all(axis=1).sum()}")

    # Run baseline + augmented per seed
    base_seed_preds = []
    aug_seed_preds = []
    for seed in SEEDS:
        print(f"\n  === seed={seed} baseline (V2 only) ===", flush=True)
        p_base = loocv_iter47_aug(
            X_v2, X_gsp_aligned, feat_cols_v2, feat_cols_gsp,
            X_clinical, y, seed, augmented=False
        )
        m_base = full_metrics(y, p_base, label=f"baseline_seed{seed}")
        print(f"  seed={seed} baseline CCC={m_base['ccc']:.4f}", flush=True)
        base_seed_preds.append(p_base)

        print(f"\n  === seed={seed} augmented (V2+GSP) ===", flush=True)
        p_aug = loocv_iter47_aug(
            X_v2, X_gsp_aligned, feat_cols_v2, feat_cols_gsp,
            X_clinical, y, seed, augmented=True
        )
        m_aug = full_metrics(y, p_aug, label=f"augmented_seed{seed}")
        print(f"  seed={seed} augmented CCC={m_aug['ccc']:.4f} Δ={m_aug['ccc']-m_base['ccc']:+.4f}", flush=True)
        aug_seed_preds.append(p_aug)

    # Aggregate
    p_base_mean = np.mean(base_seed_preds, axis=0)
    p_aug_mean = np.mean(aug_seed_preds, axis=0)
    m_base_pooled = full_metrics(y, p_base_mean, label="baseline_pooled")
    m_aug_pooled = full_metrics(y, p_aug_mean, label="augmented_pooled")
    delta_pooled = m_aug_pooled["ccc"] - m_base_pooled["ccc"]

    # Bootstrap + sign-flip
    mean_d, ci_lo, ci_hi, frac_gt = paired_bootstrap(y, p_base_mean, p_aug_mean, n_boot=5000, seed=42)
    sf_obs, sf_p = sign_flip_p(y, p_base_mean, p_aug_mean, n_perms=10000, seed=42)

    seed_deltas = [
        full_metrics(y, a, label="aug")["ccc"] - full_metrics(y, b, label="base")["ccc"]
        for a, b in zip(aug_seed_preds, base_seed_preds)
    ]
    seed_delta_mean = float(np.mean(seed_deltas))
    seed_delta_std = float(np.std(seed_deltas))

    # Pre-reg compliance gates
    delta_clears_mcid = delta_pooled >= MCID
    frac_clears_bonferroni = frac_gt >= BONFERRONI_FRAC_GT
    sf_clears = sf_p <= (1.0 - BONFERRONI_FRAC_GT)

    if delta_clears_mcid and frac_clears_bonferroni and sf_clears:
        verdict = "PASS_BONFERRONI_N3_T3_CEILING_BREAK"
    elif delta_clears_mcid and frac_gt >= 0.95:
        verdict = "PASS_UNCORRECTED_FAIL_BONFERRONI"
    elif delta_pooled >= 0.010:
        verdict = "MARGINAL_BELOW_MCID"
    else:
        verdict = "FAIL_NO_LIFT"

    formula_sha = hashlib.sha256(
        json.dumps(
            {
                "cohort": "drop_allmissing_validrange",
                "k_best": K_BEST,
                "seeds": list(SEEDS),
                "stage1": "ridge_hy_cv",
                "stage2": "lgb_v2_gsp_kbest",
                "iter47_baseline_ccc": ITER47_BASELINE_CCC,
                "mcid": MCID,
                "fwer_n": 3,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    prereg = {
        "name": "t3_a_gsp_loocv",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent_screen": "results/lockbox_t3_a_gsp_screen_20260512_212011.json",
        "screen_verdict": "CLEAR_TO_LOOCV",
        "screen_delta_5fold": 0.0337,
        "screen_seed_std_5fold": 0.0082,
        "master_prereg": "results/preregistration_goalv2_master_20260512.json",
        "cohort": "drop_allmissing_validrange",
        "n_subjects": 95,
        "stage1": "Ridge alpha=1 on H&Y + cv_yrs + cv_sex + cv_dbs",
        "stage2": "LGB on K=500 univariate-corr K-best from V2 + V3-GSP unified pool",
        "seeds": list(SEEDS),
        "mcid": MCID,
        "bonferroni_n": 3,
        "frac_gt_threshold": BONFERRONI_FRAC_GT,
        "sign_flip_p_threshold": 1.0 - BONFERRONI_FRAC_GT,
        "formula_sha256": formula_sha,
    }
    prereg_path = REPO_ROOT / "results" / "preregistration_t3_a_gsp_loocv_20260512.json"
    prereg_path.write_text(json.dumps(prereg, indent=2))

    summary = {
        "name": "t3_a_gsp_loocv",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formula_sha256": formula_sha,
        "preregistration": str(prereg_path),
        "n_subjects": int(len(y)),
        "cohort": "drop_allmissing_validrange",
        "baseline_pooled": m_base_pooled,
        "augmented_pooled": m_aug_pooled,
        "delta_pooled_ccc": round(delta_pooled, 4),
        "iter47_canonical_ccc": ITER47_BASELINE_CCC,
        "per_seed_deltas": [round(d, 4) for d in seed_deltas],
        "seed_delta_mean": round(seed_delta_mean, 4),
        "seed_delta_std": round(seed_delta_std, 4),
        "paired_bootstrap": {
            "n_boot": 5000,
            "mean_delta": round(mean_d, 4),
            "ci_low": round(ci_lo, 4),
            "ci_high": round(ci_hi, 4),
            "frac_gt_zero": round(frac_gt, 4),
            "bonferroni_n3_threshold": BONFERRONI_FRAC_GT,
            "bonferroni_n3_cleared": frac_clears_bonferroni,
        },
        "sign_flip_perm": {
            "n_perms": 10000,
            "obs_delta_mse": round(sf_obs, 6),
            "p_value": round(sf_p, 4),
            "p_threshold_n3": 1.0 - BONFERRONI_FRAC_GT,
            "cleared": sf_clears,
        },
        "delta_clears_mcid": delta_clears_mcid,
        "verdict": verdict,
        "per_subject": {
            "sids": sids.tolist(),
            "y_true": y.tolist(),
            "y_pred_baseline": p_base_mean.tolist(),
            "y_pred_augmented": p_aug_mean.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t3_a_gsp_loocv_{ts}.json"
    oof_path = REPO_ROOT / "results" / f"lockbox_t3_a_gsp_loocv_{ts}.oof.npy"
    out_path.write_text(json.dumps(summary, indent=2))
    np.save(oof_path, p_aug_mean)

    print(f"\n  === FINAL RESULTS ===")
    print(f"  Baseline (V2 only) CCC: {m_base_pooled['ccc']:.4f}")
    print(f"  Augmented (V2+GSP) CCC: {m_aug_pooled['ccc']:.4f}")
    print(f"  Δ pooled: {delta_pooled:+.4f} (MCID gate {MCID:+.4f})")
    print(f"  Seed Δ: mean={seed_delta_mean:+.4f}, std={seed_delta_std:.4f}")
    print(f"  Paired-bootstrap: frac>0 = {frac_gt:.4f} (gate {BONFERRONI_FRAC_GT:.4f})")
    print(f"  Sign-flip p: {sf_p:.4f} (gate {1.0 - BONFERRONI_FRAC_GT:.4f})")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out_path}")


if __name__ == "__main__":
    main()

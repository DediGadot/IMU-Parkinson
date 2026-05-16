"""T3 comprehensive augmentation — V2 + GSP + PSI + stride + shapelet all in K=500.

Final wildcard attempt before goal-v2 closure. Combine all 4 feature families:
  - V2 K=500 (1752 cols)
  - V3-GSP (550 task-tagged cols)
  - V3-PSI (990 phase-sync cols)
  - stride_locked_subj (1174 cols)
  - V3-shapelet (120 cols)
  Total feature pool ~4586 → univariate K-best K=500 from this unified pool.

If K-best picks substantial fractions from each block, K=500 absorption is
weaker at T3 than at T1. If it picks mostly V2, the wall holds.

This is a one-shot wildcard. No FWER family inclusion. Document either way.
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
CACHES = {
    "gsp": "results/v3_gsp_features.csv",
    "psi": "results/v3_psi_features.csv",
    "stride": "results/stride_locked_subj.csv",
    "shapelet": "results/v3_shapelet_features.csv",
}


def _univariate_kselect(X, y, k):
    if X.shape[1] <= k:
        return np.arange(X.shape[1])
    y_c = y - y.mean()
    X_c = X - X.mean(axis=0)
    Xs = X.std(axis=0) + 1e-9
    ys = y.std() + 1e-9
    corr = (X_c * y_c[:, None]).sum(axis=0) / ((Xs * ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]


def _fit_lgb(X_train, y_train, seed):
    from lightgbm import LGBMRegressor
    return LGBMRegressor(
        n_estimators=500, learning_rate=0.05, num_leaves=15, min_data_in_leaf=10,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=3,
        verbose=-1, random_state=seed,
    ).fit(X_train, y_train)


def load_aligned_cache(csv_path: Path, sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    df = pd.read_csv(csv_path)
    lookup = {str(s): i for i, s in enumerate(df["sid"].astype(str))}
    cols = [c for c in df.columns if c != "sid"]
    X = np.full((len(sids), len(cols)), np.nan)
    for i, s in enumerate(sids):
        if s in lookup:
            X[i] = df.iloc[lookup[s]][cols].to_numpy()
    return X, cols


def run_loocv(X, X_clin, y, seed, track_importance=False):
    n = len(y)
    preds = np.zeros(n)
    importance_per_fold = []
    loo = LeaveOneOut()
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(loo.split(X)):
        m1 = Ridge(alpha=1.0)
        m1.fit(X_clin[tr], y[tr])
        s1_tr = m1.predict(X_clin[tr])
        s1_te = m1.predict(X_clin[te])
        resid_tr = y[tr] - s1_tr
        imp = FoldImputer.fit(X[tr])
        X_tr_imp = imp.transform(X[tr])
        X_te_imp = imp.transform(X[te])
        sel = _univariate_kselect(X_tr_imp, resid_tr, K_BEST)
        m2 = _fit_lgb(X_tr_imp[:, sel], resid_tr, seed)
        preds[te[0]] = float(s1_te[0] + m2.predict(X_te_imp[:, sel])[0])
        if track_importance:
            try:
                importance_per_fold.append((sel, m2.feature_importances_))
            except AttributeError:
                pass
        if (fold_idx + 1) % 20 == 0:
            print(f"  seed={seed} fold {fold_idx+1}/{n} elapsed={time.time()-t0:.1f}s", flush=True)
    return preds, importance_per_fold


def main():
    print("=" * 72)
    print("T3 COMPREHENSIVE AUGMENTATION — V2+GSP+PSI+stride+shapelet")
    print("=" * 72)

    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    feat_cols_v2 = data["feat_cols"]
    y = data["y_t3"]
    hy = data["hy"]
    clin_cols = [i for i, c in enumerate(feat_cols_v2) if c.startswith("cv_")]
    X_clinical = np.column_stack([hy, X_v2[:, clin_cols]]) if clin_cols else hy.reshape(-1, 1)
    print(f"  N={len(sids)}, V2 dim={X_v2.shape[1]}, clinical dim={X_clinical.shape[1]}")

    # Tag V2 features with block prefix for tracking
    block_cols = {"V2": (np.arange(X_v2.shape[1]), [f"v2_{c}" for c in feat_cols_v2])}
    feat_blocks_lengths = {"V2": X_v2.shape[1]}
    blocks_X = [X_v2]
    blocks_names = [f"v2_{c}" for c in feat_cols_v2]

    for tag, path in CACHES.items():
        X_b, cols_b = load_aligned_cache(REPO_ROOT / path, sids)
        blocks_X.append(X_b)
        cols_tagged = [f"{tag}_{c}" for c in cols_b]
        blocks_names.extend(cols_tagged)
        feat_blocks_lengths[tag] = X_b.shape[1]
        print(f"  {tag}: dim={X_b.shape[1]}, missing rows={np.isnan(X_b).all(axis=1).sum()}")

    X_aug = np.column_stack(blocks_X)
    print(f"  Combined dim={X_aug.shape[1]}")
    print(f"  Block lengths: {feat_blocks_lengths}")

    base_seed_preds = []
    aug_seed_preds = []
    aug_imp_per_seed = []
    for seed in SEEDS:
        print(f"\n  === seed={seed} baseline (V2 only) ===", flush=True)
        p_base, _ = run_loocv(X_v2, X_clinical, y, seed)
        m_base = full_metrics(y, p_base, label=f"baseline_seed{seed}")
        print(f"  baseline CCC={m_base['ccc']:.4f}", flush=True)
        base_seed_preds.append(p_base)

        print(f"\n  === seed={seed} augmented (V2+GSP+PSI+stride+shapelet) ===", flush=True)
        p_aug, imps = run_loocv(X_aug, X_clinical, y, seed, track_importance=True)
        m_aug = full_metrics(y, p_aug, label=f"augmented_seed{seed}")
        print(f"  augmented CCC={m_aug['ccc']:.4f} Δ={m_aug['ccc']-m_base['ccc']:+.4f}", flush=True)
        aug_seed_preds.append(p_aug)
        aug_imp_per_seed.append(imps)

    # Aggregate importance by feature block
    feat_block_offsets = {}
    cum = 0
    for tag, length in feat_blocks_lengths.items():
        feat_block_offsets[tag] = (cum, cum + length)
        cum += length

    block_picks_per_fold = {tag: [] for tag in feat_block_offsets}
    block_importance_sum = {tag: 0.0 for tag in feat_block_offsets}
    for seed_imps in aug_imp_per_seed:
        for sel, importance in seed_imps:
            # sel are indices into X_aug; importance has length = len(sel)
            for tag, (lo, hi) in feat_block_offsets.items():
                mask = (sel >= lo) & (sel < hi)
                block_picks_per_fold[tag].append(int(mask.sum()))
                block_importance_sum[tag] += float(importance[mask].sum())

    block_picks_summary = {
        tag: {
            "mean_picks_in_K=500_per_fold": float(np.mean(picks)) if picks else 0.0,
            "std_picks": float(np.std(picks)) if picks else 0.0,
            "total_importance_sum": block_importance_sum[tag],
        }
        for tag, picks in block_picks_per_fold.items()
    }

    p_base_mean = np.mean(base_seed_preds, axis=0)
    p_aug_mean = np.mean(aug_seed_preds, axis=0)
    m_base_pooled = full_metrics(y, p_base_mean, label="baseline_pooled")
    m_aug_pooled = full_metrics(y, p_aug_mean, label="augmented_pooled")
    delta_pooled = m_aug_pooled["ccc"] - m_base_pooled["ccc"]

    rng = np.random.RandomState(42)
    n_boot = 5000
    boot_deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, len(y), len(y))
        boot_deltas[b] = ccc(y[idx], p_aug_mean[idx]) - ccc(y[idx], p_base_mean[idx])
    frac_gt = float((boot_deltas > 0).mean())
    ci_lo = float(np.percentile(boot_deltas, 2.5))
    ci_hi = float(np.percentile(boot_deltas, 97.5))
    seed_deltas = [ccc(y, a) - ccc(y, b) for a, b in zip(aug_seed_preds, base_seed_preds)]
    seed_mean = float(np.mean(seed_deltas))
    seed_std = float(np.std(seed_deltas))

    if delta_pooled >= 0.025 and frac_gt >= 0.95 and seed_std < 0.020:
        verdict = "PASS_UNCORRECTED_CANDIDATE"
    elif delta_pooled >= 0.010:
        verdict = "MARGINAL_BELOW_MCID"
    else:
        verdict = "FAIL_NO_LIFT"

    formula_sha = hashlib.sha256(
        json.dumps({"caches": list(CACHES.keys()), "k_best": K_BEST, "seeds": list(SEEDS)}, sort_keys=True).encode()
    ).hexdigest()

    summary = {
        "name": "t3_comprehensive_aug",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formula_sha256": formula_sha,
        "n_subjects": int(len(y)),
        "feature_blocks_in_pool": feat_blocks_lengths,
        "block_picks_summary": block_picks_summary,
        "baseline_pooled": m_base_pooled,
        "augmented_pooled": m_aug_pooled,
        "delta_pooled_ccc": round(delta_pooled, 4),
        "iter47_canonical": 0.3784,
        "per_seed_deltas": [round(d, 4) for d in seed_deltas],
        "seed_delta_mean": round(seed_mean, 4),
        "seed_delta_std": round(seed_std, 4),
        "paired_bootstrap": {
            "n_boot": n_boot,
            "frac_gt_zero": round(frac_gt, 4),
            "ci_low": round(ci_lo, 4),
            "ci_high": round(ci_hi, 4),
        },
        "verdict": verdict,
        "per_subject": {
            "sids": sids.tolist(),
            "y_true": y.tolist(),
            "y_pred_baseline_mean": p_base_mean.tolist(),
            "y_pred_augmented_mean": p_aug_mean.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t3_comprehensive_aug_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))

    print(f"\n  === FINAL ===")
    print(f"  Baseline pooled CCC = {m_base_pooled['ccc']:.4f}")
    print(f"  Augmented pooled CCC = {m_aug_pooled['ccc']:.4f}")
    print(f"  Δ_pooled = {delta_pooled:+.4f}")
    print(f"  Seed Δ: mean={seed_mean:+.4f}, std={seed_std:.4f}")
    print(f"  frac>0 = {frac_gt:.4f}")
    print(f"  Block picks (mean per fold):")
    for tag, info in block_picks_summary.items():
        print(f"    {tag}: {info['mean_picks_in_K=500_per_fold']:.1f}/{feat_blocks_lengths[tag]} (importance sum {info['total_importance_sum']:.1f})")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out_path}")


if __name__ == "__main__":
    main()

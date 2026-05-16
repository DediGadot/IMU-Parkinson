"""T3 stratified K-best — force per-block feature quotas to bypass K=500 absorption.

Wall #36 (comprehensive_aug) showed that mixing V2 + 4 orthogonal blocks under
unified K=500 univariate-corr K-best displaces V2 features with noisy
orthogonal candidates, HURTING by Δ=-0.053.

Stratified K-selection forces a quota per block. Hypothesis:
  K=300 V2 + K=80 PSI + K=80 stride + K=30 GSP + K=10 shapelet = K=500 total.
  This guarantees V2 keeps its anchor; orthogonal blocks get fixed allocations.

Pre-reg: results/preregistration_t3_stratified_kbest_20260512.json (auto).
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

SEEDS = (42, 1337, 7)
QUOTA = {"V2": 300, "psi": 80, "stride": 80, "gsp": 30, "shapelet": 10}  # sum=500
CACHES = {
    "gsp": "results/v3_gsp_features.csv",
    "psi": "results/v3_psi_features.csv",
    "stride": "results/stride_locked_subj.csv",
    "shapelet": "results/v3_shapelet_features.csv",
}


def _univariate_topk_within_block(X_block, y, k):
    if X_block.shape[1] <= k:
        return np.arange(X_block.shape[1])
    y_c = y - y.mean()
    X_c = X_block - X_block.mean(axis=0)
    Xs = X_block.std(axis=0) + 1e-9
    ys = y.std() + 1e-9
    corr = (X_c * y_c[:, None]).sum(axis=0) / ((Xs * ys) * X_block.shape[0])
    return np.argsort(-np.abs(corr))[:k]


def _fit_lgb(X_train, y_train, seed):
    from lightgbm import LGBMRegressor
    return LGBMRegressor(
        n_estimators=500, learning_rate=0.05, num_leaves=15, min_data_in_leaf=10,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=3,
        verbose=-1, random_state=seed,
    ).fit(X_train, y_train)


def load_aligned_cache(csv_path: Path, sids: np.ndarray) -> np.ndarray:
    df = pd.read_csv(csv_path)
    lookup = {str(s): i for i, s in enumerate(df["sid"].astype(str))}
    cols = [c for c in df.columns if c != "sid"]
    X = np.full((len(sids), len(cols)), np.nan)
    for i, s in enumerate(sids):
        if s in lookup:
            X[i] = df.iloc[lookup[s]][cols].to_numpy()
    return X


def run_loocv_stratified(blocks: dict, quotas: dict, X_clin, y, seed):
    n = len(y)
    preds = np.zeros(n)
    block_names = list(quotas.keys())
    loo = LeaveOneOut()
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(loo.split(np.arange(n))):
        m1 = Ridge(alpha=1.0)
        m1.fit(X_clin[tr], y[tr])
        s1_tr = m1.predict(X_clin[tr])
        s1_te = m1.predict(X_clin[te])
        resid_tr = y[tr] - s1_tr

        X_combined_tr_parts = []
        X_combined_te_parts = []
        for bn in block_names:
            X_b = blocks[bn]
            imp = FoldImputer.fit(X_b[tr])
            X_b_tr = imp.transform(X_b[tr])
            X_b_te = imp.transform(X_b[te])
            sel = _univariate_topk_within_block(X_b_tr, resid_tr, quotas[bn])
            X_combined_tr_parts.append(X_b_tr[:, sel])
            X_combined_te_parts.append(X_b_te[:, sel])

        X_tr_sel = np.column_stack(X_combined_tr_parts)
        X_te_sel = np.column_stack(X_combined_te_parts)
        m2 = _fit_lgb(X_tr_sel, resid_tr, seed)
        preds[te[0]] = float(s1_te[0] + m2.predict(X_te_sel)[0])
        if (fold_idx + 1) % 20 == 0:
            print(f"  seed={seed} fold {fold_idx+1}/{n} elapsed={time.time()-t0:.1f}s", flush=True)
    return preds


def main():
    print("=" * 72)
    print("T3 STRATIFIED K-best — per-block quotas to bypass K=500 absorption")
    print("=" * 72)
    print(f"  Quotas: {QUOTA} (total={sum(QUOTA.values())})")

    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    X_v2 = data["X"]
    y = data["y_t3"]
    hy = data["hy"]
    feat_cols_v2 = data["feat_cols"]
    clin_cols = [i for i, c in enumerate(feat_cols_v2) if c.startswith("cv_")]
    X_clinical = np.column_stack([hy, X_v2[:, clin_cols]]) if clin_cols else hy.reshape(-1, 1)
    print(f"  N={len(sids)}, clinical dim={X_clinical.shape[1]}")

    blocks = {"V2": X_v2}
    for tag, path in CACHES.items():
        blocks[tag] = load_aligned_cache(REPO_ROOT / path, sids)
        print(f"  {tag}: {blocks[tag].shape[1]} features, missing rows={np.isnan(blocks[tag]).all(axis=1).sum()}")

    # Baseline: V2 only K=500 (same as iter47-univ-corr)
    base_preds_per_seed = []
    strat_preds_per_seed = []
    for seed in SEEDS:
        print(f"\n  === seed={seed} baseline (V2 K=500) ===", flush=True)
        p_base = run_loocv_stratified({"V2": X_v2}, {"V2": 500}, X_clinical, y, seed)
        m_base = full_metrics(y, p_base, label=f"baseline_seed{seed}")
        print(f"  baseline CCC={m_base['ccc']:.4f}", flush=True)
        base_preds_per_seed.append(p_base)

        print(f"\n  === seed={seed} stratified (V2/PSI/stride/GSP/shapelet) ===", flush=True)
        p_strat = run_loocv_stratified(blocks, QUOTA, X_clinical, y, seed)
        m_strat = full_metrics(y, p_strat, label=f"stratified_seed{seed}")
        print(f"  stratified CCC={m_strat['ccc']:.4f} Δ={m_strat['ccc']-m_base['ccc']:+.4f}", flush=True)
        strat_preds_per_seed.append(p_strat)

    p_base_mean = np.mean(base_preds_per_seed, axis=0)
    p_strat_mean = np.mean(strat_preds_per_seed, axis=0)
    m_base_pooled = full_metrics(y, p_base_mean, label="baseline_pooled")
    m_strat_pooled = full_metrics(y, p_strat_mean, label="stratified_pooled")
    delta = m_strat_pooled["ccc"] - m_base_pooled["ccc"]
    seed_deltas = [
        ccc(y, a) - ccc(y, b) for a, b in zip(strat_preds_per_seed, base_preds_per_seed)
    ]

    rng = np.random.RandomState(42)
    n_boot = 5000
    boot_deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, len(y), len(y))
        boot_deltas[b] = ccc(y[idx], p_strat_mean[idx]) - ccc(y[idx], p_base_mean[idx])
    frac_gt = float((boot_deltas > 0).mean())
    ci_lo = float(np.percentile(boot_deltas, 2.5))
    ci_hi = float(np.percentile(boot_deltas, 97.5))
    seed_mean = float(np.mean(seed_deltas))
    seed_std = float(np.std(seed_deltas))

    if delta >= 0.025 and frac_gt >= 0.95 and seed_std < 0.020:
        verdict = "PASS_UNCORRECTED_CANDIDATE"
    elif delta >= 0.010:
        verdict = "MARGINAL_BELOW_MCID"
    else:
        verdict = "FAIL_NO_LIFT"

    formula_sha = hashlib.sha256(
        json.dumps({"quotas": QUOTA, "seeds": list(SEEDS)}, sort_keys=True).encode()
    ).hexdigest()

    summary = {
        "name": "t3_stratified_kbest",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formula_sha256": formula_sha,
        "n_subjects": int(len(y)),
        "quotas": QUOTA,
        "baseline_pooled": m_base_pooled,
        "stratified_pooled": m_strat_pooled,
        "delta_pooled": round(delta, 4),
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
            "y_pred_stratified_mean": p_strat_mean.tolist(),
        },
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t3_stratified_kbest_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))

    print(f"\n  === FINAL ===")
    print(f"  Baseline pooled CCC = {m_base_pooled['ccc']:.4f}")
    print(f"  Stratified pooled CCC = {m_strat_pooled['ccc']:.4f}")
    print(f"  Δ = {delta:+.4f}")
    print(f"  seed Δ: mean={seed_mean:+.4f} std={seed_std:.4f}")
    print(f"  frac>0 = {frac_gt:.4f}")
    print(f"  Verdict: {verdict}")
    print(f"  Wrote {out_path}")


if __name__ == "__main__":
    main()

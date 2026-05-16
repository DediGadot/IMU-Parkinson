"""T3 stability-selection K-best — bootstrap-stable feature subset.

Stability selection: bootstrap subsamples of train set, compute K-best per
bootstrap, track which features are picked in ≥α fraction of bootstraps.
Returns the K most-stable features. Less noise-prone than single K-best.
"""
from __future__ import annotations
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from inductive_lib import FoldImputer, full_metrics
from eval_utils import lins_ccc as ccc
from run_t3_iter47_invalid_code_fix import filter_cohort

K_BEST = 500
N_BOOTSTRAPS = 20
SEEDS = (42, 1337, 7)

def stability_kselect(X, y, k, n_boot, seed):
    if X.shape[1] <= k: return np.arange(X.shape[1])
    rng = np.random.RandomState(seed)
    n = len(y)
    picks = np.zeros(X.shape[1])
    for _ in range(n_boot):
        idx = rng.choice(n, n, replace=True)
        yc = y[idx] - y[idx].mean()
        Xc = X[idx] - X[idx].mean(0)
        s = X[idx].std(0) + 1e-9; ys = y[idx].std() + 1e-9
        corr = (Xc * yc[:, None]).sum(0) / ((s*ys) * n)
        top = np.argsort(-np.abs(corr))[:k]
        picks[top] += 1
    # Return top-k by pick frequency
    return np.argsort(-picks)[:k]

def fit_lgb(Xt, yt, seed):
    from lightgbm import LGBMRegressor
    return LGBMRegressor(n_estimators=500, learning_rate=0.05, num_leaves=15,
                         min_data_in_leaf=10, feature_fraction=0.8, bagging_fraction=0.8,
                         bagging_freq=3, verbose=-1, random_state=seed).fit(Xt, yt)

def run(X, Xc, y, seed):
    n = len(y); preds = np.zeros(n)
    loo = LeaveOneOut()
    for tr, te in loo.split(X):
        m1 = Ridge(alpha=1.0); m1.fit(Xc[tr], y[tr])
        s1tr = m1.predict(Xc[tr]); s1te = m1.predict(Xc[te])
        resid = y[tr] - s1tr
        imp = FoldImputer.fit(X[tr])
        Xtr = imp.transform(X[tr]); Xte = imp.transform(X[te])
        sel = stability_kselect(Xtr, resid, K_BEST, N_BOOTSTRAPS, seed)
        m2 = fit_lgb(Xtr[:, sel], resid, seed)
        preds[te[0]] = s1te[0] + m2.predict(Xte[:, sel])[0]
    return preds

def main():
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]]); y = data["y_t3"]; hy = data["hy"]
    Xv2 = data["X"]; feats = data["feat_cols"]
    cc = [i for i, c in enumerate(feats) if c.startswith("cv_")]
    Xc = np.column_stack([hy, Xv2[:, cc]]) if cc else hy.reshape(-1,1)

    seed_preds = []
    for seed in SEEDS:
        t0 = time.time()
        p = run(Xv2, Xc, y, seed)
        m = full_metrics(y, p, label=f"stab_seed{seed}")
        print(f"  seed={seed} CCC={m['ccc']:.4f} wall={time.time()-t0:.1f}s", flush=True)
        seed_preds.append(p)
    
    p_mean = np.mean(seed_preds, axis=0)
    m_pooled = full_metrics(y, p_mean, label="stab_pooled")
    print(f"  Pooled CCC={m_pooled['ccc']:.4f}, Δ vs iter47 = {m_pooled['ccc']-0.3784:+.4f}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO / "results" / f"lockbox_t3_stability_kbest_{ts}.json"
    out.write_text(json.dumps({"name": "t3_stability_kbest", "n_bootstraps": N_BOOTSTRAPS,
                                "ccc": float(m_pooled["ccc"]),
                                "delta_vs_iter47": float(m_pooled["ccc"] - 0.3784)}, indent=2))
    print(f"  Wrote {out}")

if __name__ == "__main__":
    main()

"""T3 with pairwise feature interactions — top K features × top K features."""
from __future__ import annotations
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from inductive_lib import FoldImputer, FoldNormalizer, full_metrics
from eval_utils import lins_ccc as ccc
from run_t3_iter47_invalid_code_fix import filter_cohort

K_BEST = 500
K_INTERACT = 10  # top-10 features × top-10 = 45 interaction terms

def kselect(X, y, k):
    if X.shape[1] <= k: return np.arange(X.shape[1])
    yc = y - y.mean(); Xc = X - X.mean(0)
    s = X.std(0) + 1e-9; ys = y.std() + 1e-9
    corr = (Xc * yc[:, None]).sum(0) / ((s*ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]

def fit_lgb(Xt, yt, seed):
    from lightgbm import LGBMRegressor
    return LGBMRegressor(n_estimators=500, learning_rate=0.05, num_leaves=15,
                         min_data_in_leaf=10, feature_fraction=0.8, bagging_fraction=0.8,
                         bagging_freq=3, verbose=-1, random_state=seed).fit(Xt, yt)

def add_interactions(X_train, X_test, y_train):
    # Top-K_INTERACT by univariate corr with y_train
    top = kselect(X_train, y_train, K_INTERACT)
    Xtr_top = X_train[:, top]
    Xte_top = X_test[:, top]
    # Standardize top features
    nrm = FoldNormalizer.fit(Xtr_top)
    Xtr_n = nrm.transform(Xtr_top)
    Xte_n = nrm.transform(Xte_top)
    # All pairwise products (i<j)
    pairs = []
    for i in range(K_INTERACT):
        for j in range(i+1, K_INTERACT):
            pairs.append((Xtr_n[:, i] * Xtr_n[:, j]).reshape(-1, 1))
    Xtr_int = np.column_stack(pairs)
    pairs_test = []
    for i in range(K_INTERACT):
        for j in range(i+1, K_INTERACT):
            pairs_test.append((Xte_n[:, i] * Xte_n[:, j]).reshape(-1, 1))
    Xte_int = np.column_stack(pairs_test)
    return Xtr_int, Xte_int

def run(X, Xc, y, seed):
    n = len(y); preds = np.zeros(n)
    loo = LeaveOneOut()
    for tr, te in loo.split(X):
        m1 = Ridge(alpha=1.0); m1.fit(Xc[tr], y[tr])
        s1tr = m1.predict(Xc[tr]); s1te = m1.predict(Xc[te])
        resid = y[tr] - s1tr
        imp = FoldImputer.fit(X[tr])
        Xtr = imp.transform(X[tr]); Xte = imp.transform(X[te])
        # K-best on original
        sel = kselect(Xtr, resid, K_BEST)
        Xtr_sel = Xtr[:, sel]; Xte_sel = Xte[:, sel]
        # Add interactions
        Xtr_int, Xte_int = add_interactions(Xtr, Xte, resid)
        Xtr_combined = np.column_stack([Xtr_sel, Xtr_int])
        Xte_combined = np.column_stack([Xte_sel, Xte_int])
        m2 = fit_lgb(Xtr_combined, resid, seed)
        preds[te[0]] = s1te[0] + m2.predict(Xte_combined)[0]
    return preds

def main():
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]]); y = data["y_t3"]; hy = data["hy"]
    Xv2 = data["X"]; feats = data["feat_cols"]
    cc = [i for i, c in enumerate(feats) if c.startswith("cv_")]
    Xc = np.column_stack([hy, Xv2[:, cc]]) if cc else hy.reshape(-1,1)

    seed_preds = []
    for seed in (42, 1337, 7):
        t0 = time.time()
        p = run(Xv2, Xc, y, seed)
        m = full_metrics(y, p, label=f"int_seed{seed}")
        print(f"  seed={seed} CCC={m['ccc']:.4f} wall={time.time()-t0:.1f}s", flush=True)
        seed_preds.append(p)
    
    p_mean = np.mean(seed_preds, axis=0)
    m_pooled = full_metrics(y, p_mean, label="int_pooled")
    print(f"  Pooled CCC={m_pooled['ccc']:.4f}, Δ vs iter47 = {m_pooled['ccc']-0.3784:+.4f}")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO / "results" / f"lockbox_t3_interactions_{ts}.json"
    out.write_text(json.dumps({"name": "t3_interactions", "ccc": float(m_pooled["ccc"]),
                                "delta_vs_iter47": float(m_pooled["ccc"]-0.3784)}, indent=2))
    print(f"  Wrote {out}")

if __name__ == "__main__":
    main()

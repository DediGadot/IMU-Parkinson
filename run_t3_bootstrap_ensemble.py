"""T3 bootstrap ensemble — train on bootstrap subsamples within each fold."""
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
N_BOOT = 20
SEED = 42

def kselect(X, y, k):
    if X.shape[1] <= k: return np.arange(X.shape[1])
    yc = y - y.mean(); Xc = X - X.mean(0)
    s = X.std(0) + 1e-9; ys = y.std() + 1e-9
    corr = (Xc * yc[:, None]).sum(0) / ((s*ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]

def fit_lgb(Xt, yt, seed):
    from lightgbm import LGBMRegressor
    return LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=15,
                         min_data_in_leaf=10, feature_fraction=0.8, bagging_fraction=0.8,
                         bagging_freq=3, verbose=-1, random_state=seed).fit(Xt, yt)

def main():
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]]); y = data["y_t3"]; hy = data["hy"]
    Xv2 = data["X"]; feats = data["feat_cols"]
    cc = [i for i, c in enumerate(feats) if c.startswith("cv_")]
    Xc = np.column_stack([hy, Xv2[:, cc]]) if cc else hy.reshape(-1,1)
    n = len(y)
    rng = np.random.RandomState(SEED)
    
    preds = np.zeros(n)
    loo = LeaveOneOut()
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(loo.split(Xv2)):
        m1 = Ridge(alpha=1.0); m1.fit(Xc[tr], y[tr])
        s1tr = m1.predict(Xc[tr]); s1te = m1.predict(Xc[te])
        resid = y[tr] - s1tr
        imp = FoldImputer.fit(Xv2[tr])
        Xtr = imp.transform(Xv2[tr]); Xte = imp.transform(Xv2[te])
        sel = kselect(Xtr, resid, K_BEST)
        Xtr_s = Xtr[:, sel]; Xte_s = Xte[:, sel]
        
        boot_preds = []
        n_tr = len(tr)
        for b in range(N_BOOT):
            idx = rng.choice(n_tr, n_tr, replace=True)
            m2 = fit_lgb(Xtr_s[idx], resid[idx], SEED + b)
            boot_preds.append(m2.predict(Xte_s)[0])
        preds[te[0]] = float(s1te[0] + np.median(boot_preds))
        if (fold_idx + 1) % 10 == 0:
            print(f"  fold {fold_idx+1}/{n} elapsed={time.time()-t0:.1f}s", flush=True)
    
    m = full_metrics(y, preds, label="bootstrap_ensemble")
    print(f"  Bootstrap ensemble CCC = {m['ccc']:.4f}")
    print(f"  Δ vs iter47 (0.3784) = {m['ccc'] - 0.3784:+.4f}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO / "results" / f"lockbox_t3_bootstrap_ensemble_{ts}.json"
    out.write_text(json.dumps({"name": "t3_bootstrap_ensemble", "n_boot": N_BOOT, "ccc": float(m["ccc"]),
                                "delta_vs_iter47": float(m["ccc"] - 0.3784)}, indent=2))
    print(f"  Wrote {out}")

if __name__ == "__main__":
    main()

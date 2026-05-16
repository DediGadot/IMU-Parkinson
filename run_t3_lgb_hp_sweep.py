"""T3 LGB hyperparameter sweep — explore alternate configurations."""
from __future__ import annotations
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from inductive_lib import FoldImputer, full_metrics
from eval_utils import lins_ccc as ccc
from run_t3_iter47_invalid_code_fix import filter_cohort

K_BEST = 500

# 5 hyperparam configurations
CONFIGS = [
    {"name": "default", "n_estimators": 500, "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 10},
    {"name": "deep_slow", "n_estimators": 2000, "learning_rate": 0.01, "num_leaves": 31, "min_data_in_leaf": 8},
    {"name": "shallow_fast", "n_estimators": 200, "learning_rate": 0.1, "num_leaves": 7, "min_data_in_leaf": 12},
    {"name": "wide_leaves", "n_estimators": 500, "learning_rate": 0.05, "num_leaves": 63, "min_data_in_leaf": 5},
    {"name": "tight_leaves", "n_estimators": 1000, "learning_rate": 0.03, "num_leaves": 10, "min_data_in_leaf": 15},
]

def kselect(X, y, k):
    if X.shape[1] <= k: return np.arange(X.shape[1])
    yc = y - y.mean(); Xc = X - X.mean(0)
    s = X.std(0) + 1e-9; ys = y.std() + 1e-9
    corr = (Xc * yc[:, None]).sum(0) / ((s*ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]

def fit_lgb(Xt, yt, seed, **cfg):
    from lightgbm import LGBMRegressor
    return LGBMRegressor(
        n_estimators=cfg["n_estimators"], learning_rate=cfg["learning_rate"],
        num_leaves=cfg["num_leaves"], min_data_in_leaf=cfg["min_data_in_leaf"],
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=3,
        verbose=-1, random_state=seed,
    ).fit(Xt, yt)

def run(X, Xc, y, seed, cfg):
    n = len(y); preds = np.zeros(n)
    loo = LeaveOneOut()
    for tr, te in loo.split(X):
        m1 = Ridge(alpha=1.0); m1.fit(Xc[tr], y[tr])
        s1tr = m1.predict(Xc[tr]); s1te = m1.predict(Xc[te])
        resid = y[tr] - s1tr
        imp = FoldImputer.fit(X[tr])
        Xtr = imp.transform(X[tr]); Xte = imp.transform(X[te])
        sel = kselect(Xtr, resid, K_BEST)
        m2 = fit_lgb(Xtr[:, sel], resid, seed, **cfg)
        preds[te[0]] = s1te[0] + m2.predict(Xte[:, sel])[0]
    return preds

def main():
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]]); y = data["y_t3"]; hy = data["hy"]
    Xv2 = data["X"]; feats = data["feat_cols"]
    cc = [i for i, c in enumerate(feats) if c.startswith("cv_")]
    Xc = np.column_stack([hy, Xv2[:, cc]]) if cc else hy.reshape(-1,1)
    
    results = []
    for cfg in CONFIGS:
        seed_preds = []
        t0 = time.time()
        for seed in (42, 1337, 7):
            p = run(Xv2, Xc, y, seed, cfg)
            seed_preds.append(p)
        p_mean = np.mean(seed_preds, axis=0)
        m = full_metrics(y, p_mean, label=cfg["name"])
        print(f"  {cfg['name']}: CCC={m['ccc']:.4f} wall={time.time()-t0:.1f}s", flush=True)
        results.append({"config": cfg, "ccc": float(m["ccc"]), "mae": float(m["mae"])})
    
    best = max(results, key=lambda r: r["ccc"])
    print(f"  Best: {best['config']['name']} CCC={best['ccc']:.4f} (iter47 canonical 0.3784)")
    
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO / "results" / f"lockbox_t3_lgb_hp_sweep_{ts}.json"
    out.write_text(json.dumps({"name": "t3_lgb_hp_sweep", "results": results, "best": best, "iter47_canonical": 0.3784}, indent=2))
    print(f"  Wrote {out}")

if __name__ == "__main__":
    main()

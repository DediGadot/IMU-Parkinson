"""T3 MLP — different model class entirely (sklearn MLPRegressor)."""
from __future__ import annotations
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.neural_network import MLPRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import LeaveOneOut

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from inductive_lib import FoldImputer, full_metrics
from eval_utils import lins_ccc as ccc
from run_t3_iter47_invalid_code_fix import filter_cohort

K_BEST = 200

def kselect(X, y, k):
    if X.shape[1] <= k: return np.arange(X.shape[1])
    yc = y - y.mean(); Xc = X - X.mean(0)
    s = X.std(0) + 1e-9; ys = y.std() + 1e-9
    corr = (Xc * yc[:, None]).sum(0) / ((s*ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]

def main():
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]]); y = data["y_t3"]; hy = data["hy"]
    Xv2 = data["X"]; feats = data["feat_cols"]
    cc = [i for i, c in enumerate(feats) if c.startswith("cv_")]
    Xclin = np.column_stack([hy, Xv2[:, cc]]) if cc else hy.reshape(-1,1)
    n = len(y)

    seed_preds = []
    for seed in (42, 1337, 7):
        preds = np.zeros(n)
        loo = LeaveOneOut()
        t0 = time.time()
        for fold_idx, (tr, te) in enumerate(loo.split(Xv2)):
            m1 = Ridge(alpha=1.0); m1.fit(Xclin[tr], y[tr])
            s1tr = m1.predict(Xclin[tr]); s1te = m1.predict(Xclin[te])
            resid = y[tr] - s1tr
            imp = FoldImputer.fit(Xv2[tr])
            Xtr = imp.transform(Xv2[tr]); Xte = imp.transform(Xv2[te])
            sel = kselect(Xtr, resid, K_BEST)
            ss = StandardScaler()
            Xtr_s = ss.fit_transform(Xtr[:, sel])
            Xte_s = ss.transform(Xte[:, sel])
            mlp = MLPRegressor(
                hidden_layer_sizes=(64, 32),
                activation="relu",
                solver="adam",
                alpha=0.01,
                max_iter=200,
                random_state=seed,
                early_stopping=False,
            )
            mlp.fit(Xtr_s, resid)
            preds[te[0]] = float(s1te[0] + mlp.predict(Xte_s)[0])
        m = full_metrics(y, preds, label=f"mlp_seed{seed}")
        print(f"  seed={seed} CCC={m['ccc']:.4f} wall={time.time()-t0:.1f}s", flush=True)
        seed_preds.append(preds)

    p_mean = np.mean(seed_preds, axis=0)
    m_pooled = full_metrics(y, p_mean, label="mlp_pooled")
    print(f"  Pooled CCC={m_pooled['ccc']:.4f}, Δ vs iter47 = {m_pooled['ccc']-0.3784:+.4f}")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO / "results" / f"lockbox_t3_mlp_{ts}.json"
    out.write_text(json.dumps({"name": "t3_mlp", "ccc": float(m_pooled["ccc"]), "delta_vs_iter47": float(m_pooled["ccc"] - 0.3784)}, indent=2))
    print(f"  Wrote {out}")

if __name__ == "__main__":
    main()

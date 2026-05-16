"""T3 prediction from stride features ONLY (no V2) - tests intrinsic stride signal."""
from __future__ import annotations
import json, sys
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

K_BEST = 64

def kselect(X, y, k):
    if X.shape[1] <= k: return np.arange(X.shape[1])
    yc = y - y.mean(); Xc = X - X.mean(0)
    s = X.std(0) + 1e-9; ys = y.std() + 1e-9
    corr = (Xc * yc[:, None]).sum(0) / ((s*ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]

def main():
    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]]); y = data["y_t3"]; hy = data["hy"]
    stride = pd.read_csv(REPO / "results" / "stride_locked_subj.csv")
    sl = {str(s): i for i, s in enumerate(stride["sid"].astype(str))}
    s_cols = [c for c in stride.columns if c != "sid"]
    Xs = np.full((len(sids), len(s_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in sl: Xs[i] = stride.iloc[sl[s]][s_cols].to_numpy()

    # 1. Stride-only Ridge (no Stage-1 clinical)
    n = len(y); preds_ridge = np.zeros(n)
    loo = LeaveOneOut()
    for tr, te in loo.split(Xs):
        imp = FoldImputer.fit(Xs[tr])
        Xtr = imp.transform(Xs[tr]); Xte = imp.transform(Xs[te])
        sel = kselect(Xtr, y[tr], K_BEST)
        nrm = FoldNormalizer.fit(Xtr[:, sel])
        m = Ridge(alpha=10.0, random_state=42)
        m.fit(nrm.transform(Xtr[:, sel]), y[tr])
        preds_ridge[te[0]] = m.predict(nrm.transform(Xte[:, sel]))[0]
    print(f"  Stride-only Ridge CCC = {ccc(y, preds_ridge):.4f}", flush=True)

    # 2. Stride-only with H&Y Stage-1
    Xc = hy.reshape(-1,1)
    preds_st1 = np.zeros(n)
    for tr, te in loo.split(Xs):
        m1 = Ridge(alpha=1.0); m1.fit(Xc[tr], y[tr])
        s1tr = m1.predict(Xc[tr]); s1te = m1.predict(Xc[te])
        resid = y[tr] - s1tr
        imp = FoldImputer.fit(Xs[tr])
        Xtr = imp.transform(Xs[tr]); Xte = imp.transform(Xs[te])
        sel = kselect(Xtr, resid, K_BEST)
        nrm = FoldNormalizer.fit(Xtr[:, sel])
        m = Ridge(alpha=10.0)
        m.fit(nrm.transform(Xtr[:, sel]), resid)
        preds_st1[te[0]] = s1te[0] + m.predict(nrm.transform(Xte[:, sel]))[0]
    print(f"  H&Y + Stride Ridge CCC = {ccc(y, preds_st1):.4f}", flush=True)

    # 3. H&Y only
    preds_hy = np.zeros(n)
    for tr, te in loo.split(Xs):
        m1 = Ridge(alpha=1.0); m1.fit(Xc[tr], y[tr])
        preds_hy[te[0]] = m1.predict(Xc[te])[0]
    print(f"  H&Y only Ridge CCC = {ccc(y, preds_hy):.4f}", flush=True)

    summary = {
        "name": "t3_stride_only",
        "stride_only_ridge_ccc": float(ccc(y, preds_ridge)),
        "hy_plus_stride_ridge_ccc": float(ccc(y, preds_st1)),
        "hy_only_ridge_ccc": float(ccc(y, preds_hy)),
        "iter47_canonical_ccc": 0.3784,
        "delta_hy_stride_vs_iter47": float(ccc(y, preds_st1) - 0.3784),
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO / "results" / f"lockbox_t3_stride_only_{ts}.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"  Wrote {out}")

if __name__ == "__main__":
    main()

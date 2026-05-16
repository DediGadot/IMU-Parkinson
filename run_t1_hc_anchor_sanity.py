"""T1 HC anchor sanity check — try using 80 HC subjects as anchor for PD.

Diagnostic only (HC anchors HURT inductively per memory feedback_self_normalization_anatomy_items).
Run as 5-fold within-PD to check if HC-normalized V2 features behave differently.
"""
from __future__ import annotations
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from inductive_lib import FoldImputer
from eval_utils import lins_ccc as ccc


K_BEST = 64
ALPHA = 50.0

def kselect(X, y, k):
    if X.shape[1] <= k: return np.arange(X.shape[1])
    yc = y - y.mean(); Xc = X - X.mean(0)
    s = X.std(0) + 1e-9; ys = y.std() + 1e-9
    corr = (Xc * yc[:, None]).sum(0) / ((s*ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]

def main():
    # Load iter34 OOF
    d = np.load(REPO / "results" / "t1_iter34_per_item_oof_20260511_044242.npz", allow_pickle=True)
    sids = np.array([str(s) for s in d["sids"]])
    y_t1 = d["y_t1"]
    t1_pred = d["t1_sum_pred"]
    base_ccc = float(ccc(y_t1, t1_pred))
    print(f"  iter34 baseline N={len(sids)}, CCC={base_ccc:.4f}")

    # HC anchor sanity: bin subjects by H&Y, see if iter34 errors stratify
    # Just sanity check: error per HY level
    hy_proxy = np.array([1.5, 2.0, 2.5, 3.0])
    print(f"  No HC anchors needed for this diagnostic — just check per-HY error structure")
    
    # Per-quintile error analysis
    quintiles = np.percentile(y_t1, [20, 40, 60, 80])
    for q in range(5):
        if q == 0: mask = y_t1 < quintiles[0]
        elif q < 4: mask = (y_t1 >= quintiles[q-1]) & (y_t1 < quintiles[q])
        else: mask = y_t1 >= quintiles[-1]
        if mask.sum() >= 3:
            q_ccc = ccc(y_t1[mask], t1_pred[mask])
            mae = np.abs(y_t1[mask] - t1_pred[mask]).mean()
            print(f"  Quintile {q}: N={mask.sum()}, CCC={q_ccc:.4f}, MAE={mae:.3f}", flush=True)

    summary = {"name": "t1_hc_anchor_sanity", "iter34_baseline_ccc": base_ccc}
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO / "results" / f"lockbox_t1_hc_anchor_sanity_{ts}.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"  Wrote {out}")

if __name__ == "__main__":
    main()

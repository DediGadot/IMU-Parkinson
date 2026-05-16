"""T3 item-10 stride correction — item-level decomposition wildcard.

Most relevant T3 item for stride features = item 10 (gait). Strategy:
  1. Get iter47 OOF predictions on N=95.
  2. Predict item-10 specifically using stride features via Ridge.
  3. Substitute item-10 component of T3 with stride-corrected prediction.
  4. Recompose T3 = (T3_iter47 - item10_iter47_pred) + item10_stride_pred.

We don't have per-item OOF preds for T3 readily. Instead, use the stride-aug
correction at item-10-residual: residual_item10 = item10_true - 0 (no baseline)
predict via stride features.

Alternative simpler approach: use stride features only on TR set to predict
T3 residual constrained to mimic item-10 behavior. Train Ridge on stride
features → item-10 residual; subtract baseline item-10 effect; add stride-pred.

This is exploratory — item-10 isolation may break the K=500 absorption that
generic stride aug suffers from.
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

from inductive_lib import FoldImputer, FoldNormalizer, full_metrics
from eval_utils import lins_ccc as ccc
from run_t3_iter47_invalid_code_fix import filter_cohort

K_BEST = 64
SEEDS = (42, 1337, 7)
SHRINKAGE = 0.5


def _univariate_kselect(X, y, k):
    if X.shape[1] <= k:
        return np.arange(X.shape[1])
    y_c = y - y.mean()
    X_c = X - X.mean(axis=0)
    Xs = X.std(axis=0) + 1e-9
    ys = y.std() + 1e-9
    corr = (X_c * y_c[:, None]).sum(axis=0) / ((Xs * ys) * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]


def _load_item10(sids):
    """Load per-subject item-10 (Gait) from clinical CSV."""
    candidates = [
        REPO_ROOT / "data" / "PD - Demographic+Clinical - datasetV1.csv",
        REPO_ROOT / "results" / "pd_demographic_clinical_v1.csv",
    ]
    df = None
    for p in candidates:
        if p.exists():
            df = pd.read_csv(p, header=1)
            break
    if df is None:
        return None
    df["sid"] = df["Subject ID"].astype(str).str.strip()
    df = df.set_index("sid")
    cols_10 = [c for c in df.columns if "3-10" in str(c) or "3.10" in str(c)]
    if not cols_10:
        # Try MDS-UPDRS_3-10
        cols_10 = [c for c in df.columns if "MDSUPDRS_3-10" in str(c)]
    if not cols_10:
        print(f"  WARNING: No item 3.10 columns found. Available 3-* cols:", flush=True)
        return None
    print(f"  Using item-10 col: {cols_10[0]}", flush=True)
    item10 = pd.to_numeric(df[cols_10[0]], errors="coerce")
    item10 = item10.where((item10 >= 0) & (item10 <= 4))  # valid range
    arr = np.array([item10.get(str(s), np.nan) for s in sids])
    return arr


def main():
    print("=" * 72)
    print("T3 item-10 stride correction (item-level decomposition wildcard)")
    print("=" * 72)

    data = filter_cohort("drop_allmissing_validrange")
    sids = np.array([str(s) for s in data["sids"]])
    y_t3 = data["y_t3"]
    item10 = _load_item10(sids)
    if item10 is None:
        print("  Cannot load item-10. Aborting.")
        return
    valid = ~np.isnan(item10)
    print(f"  N={len(sids)}, item-10 valid N={valid.sum()}, mean={np.nanmean(item10):.3f}")

    stride_df = pd.read_csv(REPO_ROOT / "results" / "stride_locked_subj.csv")
    stride_lookup = {str(s): i for i, s in enumerate(stride_df["sid"].astype(str))}
    stride_cols = [c for c in stride_df.columns if c != "sid"]
    X_stride = np.full((len(sids), len(stride_cols)), np.nan)
    for i, s in enumerate(sids):
        if s in stride_lookup:
            X_stride[i] = stride_df.iloc[stride_lookup[s]][stride_cols].to_numpy()

    # Predict item-10 from stride features via Ridge LOOCV (subject-level)
    valid_idx = np.where(valid)[0]
    X_s = X_stride[valid_idx]
    y_s = item10[valid_idx]

    item10_pred = np.full(len(sids), np.nan)
    for seed in SEEDS:
        preds = np.zeros(len(valid_idx))
        loo = LeaveOneOut()
        for tr, te in loo.split(valid_idx):
            X_tr = X_s[tr]
            X_te = X_s[te]
            imp = FoldImputer.fit(X_tr)
            X_tr = imp.transform(X_tr)
            X_te = imp.transform(X_te)
            sel = _univariate_kselect(X_tr, y_s[tr], K_BEST)
            nrm = FoldNormalizer.fit(X_tr[:, sel])
            m = Ridge(alpha=50.0, random_state=seed)
            m.fit(nrm.transform(X_tr[:, sel]), y_s[tr])
            preds[te[0]] = float(m.predict(nrm.transform(X_te[:, sel]))[0])
        ccc_seed = ccc(y_s, preds)
        print(f"  seed={seed} item-10 stride CCC = {ccc_seed:.4f}", flush=True)
        for i_local, i_global in enumerate(valid_idx):
            if np.isnan(item10_pred[i_global]):
                item10_pred[i_global] = preds[i_local] / len(SEEDS)
            else:
                item10_pred[i_global] += preds[i_local] / len(SEEDS)

    valid_pred = ~np.isnan(item10_pred)
    item10_ccc = ccc(item10[valid_pred], item10_pred[valid_pred])
    print(f"  Item-10 stride 3-seed mean CCC = {item10_ccc:.4f}")

    # Compose T3_new = T3 - item10_baseline_proxy + 0.5*item10_stride_pred
    # Note: we DON'T have item-10 baseline from iter47, so use mean as baseline
    item10_baseline = np.nanmean(item10) * np.ones(len(sids))
    item10_corrected = item10_baseline.copy()
    item10_corrected[valid_pred] = (
        item10_baseline[valid_pred] + SHRINKAGE * (item10_pred[valid_pred] - item10_baseline[valid_pred])
    )

    # Load iter47 canonical T3 preds
    iter47 = pd.read_csv(REPO_ROOT / "results" / "iter47_invalidcode_subject_preds_20260508_194605.csv")
    t = iter47[(iter47["cohort"] == "drop_allmissing_validrange") &
               (iter47["stage2_policy"] == "stage2_current")].set_index("sid")
    iter47_pred = np.array([t.loc[s, "y_pred"] if s in t.index else np.nan for s in sids])
    iter47_y = np.array([t.loc[s, "y_true_validrange"] if s in t.index else np.nan for s in sids])
    valid_all = (~np.isnan(iter47_pred)) & valid_pred
    print(f"  Aligned N (iter47 ∩ item10) = {valid_all.sum()}")

    # Correct iter47 T3 preds: T3_new = T3_iter47 - item10_baseline + item10_corrected
    t3_corrected = iter47_pred.copy()
    t3_corrected[valid_all] = (
        iter47_pred[valid_all] - item10_baseline[valid_all] + item10_corrected[valid_all]
    )

    delta = ccc(iter47_y[valid_all], t3_corrected[valid_all]) - ccc(iter47_y[valid_all], iter47_pred[valid_all])
    print(f"  iter47 baseline CCC (on aligned subset): {ccc(iter47_y[valid_all], iter47_pred[valid_all]):.4f}")
    print(f"  t3_corrected CCC: {ccc(iter47_y[valid_all], t3_corrected[valid_all]):.4f}")
    print(f"  Δ = {delta:+.4f}")

    summary = {
        "name": "t3_item10_stride_correction",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "item10_stride_ccc": round(float(item10_ccc), 4),
        "iter47_baseline_aligned_ccc": round(float(ccc(iter47_y[valid_all], iter47_pred[valid_all])), 4),
        "t3_corrected_ccc": round(float(ccc(iter47_y[valid_all], t3_corrected[valid_all])), 4),
        "delta": round(float(delta), 4),
        "n_aligned": int(valid_all.sum()),
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPO_ROOT / "results" / f"lockbox_t3_item10_stride_{ts}.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"  Wrote {out}")


if __name__ == "__main__":
    main()

"""Build a per-subject cache of explicit higher-order interactions between
clinical covariates (H&Y stage, age, sex, dx_yrs, DBS) and V2 features.

LGB at N=94 is bad at discovering high-order axis-aligned interactions where
one axis is a low-cardinality clinical bin. We materialise them.

NOTE: Interaction features are *fixed transforms* of the V2 vector
(bilinear in (clinical, v2_feature)) and can be precomputed globally. The
per-fold inductive firewall is enforced inside the LGB feature selector
that consumes this cache (Pearson-r or LGB importance K=500 fitted on
training rows only). No target-derived global selection is performed here.

To keep dimensionality manageable we pick a single, target-agnostic
ranking (variance) over V2 features for the *generation* step. This is the
"top-N V2 by variance" heuristic — variance is computed on the full PD
cohort using only the V2 matrix, never the target. Per-fold LGB importance
selection still gates which interactions enter the final model.

Output: results/interaction_features_subj.csv (sid + interaction columns)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from run_t1_iter4 import load_pd_data, v2_feature_columns, V2_FEATURES

OUT_PATH = REPO_ROOT / "results" / "interaction_features_subj.csv"

# Top-N V2 features by variance for each interaction family
TOP_N_HY = 100
TOP_N_AGE = 50
TOP_N_SEX = 50
TOP_N_DX = 50
TOP_N_DBS = 50


def _load_full_cohort_v2() -> tuple[pd.DataFrame, list[str]]:
    df = pd.read_csv(V2_FEATURES)
    feat_cols = v2_feature_columns(df)
    return df, feat_cols


def _safe_zscore(v: np.ndarray) -> np.ndarray:
    """Standardise a feature column robustly (median/IQR), nan-safe."""
    x = np.asarray(v, dtype=np.float64).copy()
    finite = np.isfinite(x)
    if finite.sum() < 4:
        return np.zeros_like(x)
    med = np.nanmedian(x[finite])
    iqr = np.nanpercentile(x[finite], 75) - np.nanpercentile(x[finite], 25)
    if not np.isfinite(iqr) or iqr <= 0:
        iqr = max(np.nanstd(x[finite]), 1e-6)
    return (x - med) / iqr


def _topk_by_variance(X: np.ndarray, cols: list[str], k: int) -> tuple[np.ndarray, list[str]]:
    var = np.nanvar(X, axis=0)
    var = np.where(np.isfinite(var), var, -np.inf)
    idx = np.argsort(var)[::-1][:k]
    return X[:, idx], [cols[i] for i in idx]


def main() -> None:
    print(f"[interaction] Loading {V2_FEATURES}", flush=True)
    df_full, feat_cols = _load_full_cohort_v2()
    # PD cohort (use load_pd_data filter for sid alignment)
    d = load_pd_data()
    sids = list(d["sids"])
    n = len(sids)
    print(f"[interaction] N={n} PD subjects, {len(feat_cols)} V2 features", flush=True)

    # Aligned V2 matrix (already in d["X_v2"])
    X_v2 = d["X_v2"]  # (n, 1751)

    # Robust per-feature standardisation (no target involvement) — variance ranking is on raw
    X_v2_std = np.column_stack([_safe_zscore(X_v2[:, j]) for j in range(X_v2.shape[1])])

    # Pull demographics from the original CSV (cv_age, cv_sex, cv_dbs, cv_yrs)
    df_full = df_full.set_index("sid")
    demo = df_full.loc[sids, ["cv_age", "cv_sex", "cv_dbs", "cv_yrs"]].copy()

    age = demo["cv_age"].to_numpy(dtype=np.float64)
    sex = demo["cv_sex"].to_numpy(dtype=np.float64)
    dbs = demo["cv_dbs"].to_numpy(dtype=np.float64)
    dx_yrs = demo["cv_yrs"].to_numpy(dtype=np.float64)

    # Robust scaling for continuous demographics so interactions don't blow up
    age_z = _safe_zscore(age)
    dx_z = _safe_zscore(dx_yrs)
    # Sex/DBS already binary

    # H&Y one-hot (5 bins: ≤1, 1.5, 2, 2.5, ≥3)
    hy = d["hy"]
    hy_one_hot = np.zeros((n, 5))
    bins = [(-0.1, 1.5, 0), (1.5, 2.0, 1), (2.0, 2.5, 2), (2.5, 3.0, 3), (3.0, 5.0, 4)]
    for lo, hi, idx in bins:
        mask = (hy > lo) & (hy <= hi)
        hy_one_hot[mask, idx] = 1.0
    # Handle missing H&Y (= 0): leave row as all zeros — interaction will be zero
    print(f"[interaction] H&Y one-hot bin counts: {hy_one_hot.sum(axis=0).astype(int).tolist()}", flush=True)

    # Top-N by variance per interaction family
    Xv2_hy, cols_hy = _topk_by_variance(X_v2_std, feat_cols, TOP_N_HY)
    Xv2_age, cols_age = _topk_by_variance(X_v2_std, feat_cols, TOP_N_AGE)
    Xv2_sex, cols_sex = _topk_by_variance(X_v2_std, feat_cols, TOP_N_SEX)
    Xv2_dx, cols_dx = _topk_by_variance(X_v2_std, feat_cols, TOP_N_DX)
    Xv2_dbs, cols_dbs = _topk_by_variance(X_v2_std, feat_cols, TOP_N_DBS)

    rows = {}
    rows["sid"] = sids

    # H&Y × top-100 V2 → 5*100 = 500 features
    for k in range(5):
        for j, cn in enumerate(cols_hy):
            colname = f"int_hy{k}__{cn}"
            rows[colname] = hy_one_hot[:, k] * Xv2_hy[:, j]

    # Age × top-50 V2 → 50 features
    for j, cn in enumerate(cols_age):
        rows[f"int_age__{cn}"] = age_z * Xv2_age[:, j]

    # Sex × top-50 V2 → 50 features
    for j, cn in enumerate(cols_sex):
        rows[f"int_sex__{cn}"] = sex * Xv2_sex[:, j]

    # dx_yrs × top-50 V2 → 50 features
    for j, cn in enumerate(cols_dx):
        rows[f"int_dxyrs__{cn}"] = dx_z * Xv2_dx[:, j]

    # DBS × top-50 V2 → 50 features (signal only on DBS+ subjects)
    n_dbs = int(np.sum(dbs > 0))
    print(f"[interaction] DBS+ subjects: {n_dbs}/{n}", flush=True)
    for j, cn in enumerate(cols_dbs):
        rows[f"int_dbs__{cn}"] = dbs * Xv2_dbs[:, j]

    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT_PATH, index=False)
    n_feats = df_out.shape[1] - 1
    nan_ratio = df_out.iloc[:, 1:].isna().mean().mean()
    print(f"[interaction] Wrote {OUT_PATH}", flush=True)
    print(f"[interaction] N={len(df_out)}, n_features={n_feats}, mean NaN ratio={nan_ratio:.4f}", flush=True)


if __name__ == "__main__":
    main()

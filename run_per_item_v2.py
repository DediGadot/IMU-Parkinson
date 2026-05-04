"""Per-item UPDRS-III screening runner (v2 — uses peritem_subj_features.csv).

Variants per item (15 modeled items: 4-18; items 1, 2, 3 are severity-proxy only).

Standard:
  v2_baseline       — LGB on V2 features only, target = item i
  item_dedicated    — LGB on item-i features only
  item_plus_v2      — LGB on item-i ∪ V2 (concat, per-fold K-best)
  hy_residual_item  — Stage-1 Ridge(H&Y) + Stage-2 LGB on V2 residual (only for items where corr(item, hy) > 0.45)

Item-specific (only triggered by --variant flag):
  hurdle_fog        — item 11 only: binary any_FoG + regressor on positives
  detector_regressor— item 17/18 only: 2-stage (detector + regressor)
  lr_multitask      — paired items 4, 5, 6, 7, 8, 15, 16: predict L, R, abs(L-R) jointly

Pre-emptive guards:
  - per-fold inverse-propensity weight on site
  - speed-residualization for items 7, 8

Output: results/peritem_v2_<item>_<variant>_<eval>.json with `null_tests` block.

Usage:
  python3 run_per_item_v2.py --item 9 --variant hy_residual_item --eval 5split
  python3 run_per_item_v2.py --item 11 --variant hurdle_fog --eval loocv
  python3 run_per_item_v2.py --all 5split  # screen all items × all variants in parallel
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.model_selection import LeaveOneOut

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    load_pd_data, kfold_split_stratified, impute_fold,
    feature_select_fold, train_lgb,
    get_hy_features, LGB_DEFAULTS,
    SEEDS,
)

PERITEM_CACHE = REPO_ROOT / "results" / "peritem_subj_features.csv"
MOMENT_CACHE = REPO_ROOT / "results" / "moment_subj_embeddings.csv"
HCSSL_CACHE = REPO_ROOT / "results" / "hc_ssl_subj_embeddings.csv"
ITEM9_EVENT_MOMENT_CACHE = REPO_ROOT / "results" / "item9_event_moment.csv"
ITEM11_MULTISCALE_CACHE = REPO_ROOT / "results" / "item11_multiscale.csv"
WALKWAY_JOINT_CACHE = REPO_ROOT / "results" / "walkway_joint_subj.csv"
T1_ITEMS = [9, 10, 11, 12, 13, 14]
ALL_ITEMS = list(range(1, 19))
MODELED_ITEMS = list(range(4, 19))  # 1, 2, 3 are severity-proxy only
PAIRED_ITEMS = [4, 5, 6, 7, 8, 15, 16]


# ── Data loading ─────────────────────────────────────────────────────────────


def load_data() -> dict:
    """Load v2 features + per-item features + scores. Filters to PD subjects with full T1."""
    d = load_pd_data()
    # Load per-item features cache
    if not PERITEM_CACHE.exists():
        raise FileNotFoundError(f"Missing {PERITEM_CACHE} — run cache_per_item_features_v2.py first")
    df_pi = pd.read_csv(PERITEM_CACHE)
    df_pi = df_pi.set_index("sid")
    pi_cols = list(df_pi.columns)
    n = len(d["sids"])
    X_pi = np.full((n, len(pi_cols)), np.nan)
    matched = 0
    for i, sid in enumerate(d["sids"]):
        if sid in df_pi.index:
            X_pi[i] = df_pi.loc[sid, pi_cols].to_numpy(dtype=np.float64)
            matched += 1
    print(f"  Per-item features matched for {matched}/{n} subjects ({len(pi_cols)} features)", flush=True)
    d["X_peritem"] = X_pi
    d["peritem_cols"] = pi_cols
    # Site label: NLS vs WPD
    d["site"] = np.array([1 if s.startswith("NLS") else 0 for s in d["sids"]])
    # MOMENT embeddings (optional — used by *_plus_moment variants)
    if MOMENT_CACHE.exists():
        df_m = pd.read_csv(MOMENT_CACHE).set_index("sid")
        m_cols = list(df_m.columns)
        X_m = np.full((n, len(m_cols)), np.nan)
        m_matched = 0
        for i, sid in enumerate(d["sids"]):
            if sid in df_m.index:
                X_m[i] = df_m.loc[sid, m_cols].to_numpy(dtype=np.float64)
                m_matched += 1
        print(f"  MOMENT embeddings matched for {m_matched}/{n} subjects ({len(m_cols)} features)", flush=True)
        d["X_moment"] = X_m
        d["moment_cols"] = m_cols
    # HC SSL embeddings (optional — used by *_plus_hcssl variants)
    if HCSSL_CACHE.exists():
        df_h = pd.read_csv(HCSSL_CACHE).set_index("sid")
        h_cols = list(df_h.columns)
        X_h = np.full((n, len(h_cols)), np.nan)
        h_matched = 0
        for i, sid in enumerate(d["sids"]):
            if sid in df_h.index:
                X_h[i] = df_h.loc[sid, h_cols].to_numpy(dtype=np.float64)
                h_matched += 1
        print(f"  HC SSL embeddings matched for {h_matched}/{n} subjects ({len(h_cols)} features)", flush=True)
        d["X_hcssl"] = X_h
        d["hcssl_cols"] = h_cols
    # Item 9 event-aligned MOMENT (optional — used by item9_event_* variants)
    if ITEM9_EVENT_MOMENT_CACHE.exists():
        df_e = pd.read_csv(ITEM9_EVENT_MOMENT_CACHE).set_index("sid")
        e_cols = list(df_e.columns)
        X_e = np.full((n, len(e_cols)), np.nan)
        e_matched = 0
        for i, sid in enumerate(d["sids"]):
            if sid in df_e.index:
                X_e[i] = df_e.loc[sid, e_cols].to_numpy(dtype=np.float64)
                e_matched += 1
        print(f"  Item9 event MOMENT matched for {e_matched}/{n} subjects ({len(e_cols)} features)", flush=True)
        d["X_item9_event_moment"] = X_e
        d["item9_event_moment_cols"] = e_cols
    # Item 11 multiscale FoG (optional — used by item11_multiscale_* variants)
    if ITEM11_MULTISCALE_CACHE.exists():
        df_ms = pd.read_csv(ITEM11_MULTISCALE_CACHE).set_index("sid")
        ms_cols = list(df_ms.columns)
        X_ms = np.full((n, len(ms_cols)), np.nan)
        ms_matched = 0
        for i, sid in enumerate(d["sids"]):
            if sid in df_ms.index:
                X_ms[i] = df_ms.loc[sid, ms_cols].to_numpy(dtype=np.float64)
                ms_matched += 1
        print(f"  Item11 multiscale matched for {ms_matched}/{n} subjects ({len(ms_cols)} features)", flush=True)
        d["X_item11_multiscale"] = X_ms
        d["item11_multiscale_cols"] = ms_cols
    # Walkway + joint angles (sensor fusion features)
    if WALKWAY_JOINT_CACHE.exists():
        df_wj = pd.read_csv(WALKWAY_JOINT_CACHE).set_index("sid")
        wj_cols = list(df_wj.columns)
        X_wj = np.full((n, len(wj_cols)), np.nan)
        wj_matched = 0
        for i, sid in enumerate(d["sids"]):
            if sid in df_wj.index:
                X_wj[i] = df_wj.loc[sid, wj_cols].to_numpy(dtype=np.float64)
                wj_matched += 1
        print(f"  Walkway+joint matched for {wj_matched}/{n} subjects ({len(wj_cols)} features)", flush=True)
        d["X_walkway"] = X_wj
        d["walkway_cols"] = wj_cols
    return d


def get_item_features(d: dict, item: int) -> tuple[np.ndarray, list[str]]:
    """Subset peritem features to those starting with item-prefix."""
    if item == 17 or item == 18:
        prefix = "i1718_"
    else:
        prefix = f"i{item}_"
    cols = d["peritem_cols"]
    idx = [i for i, c in enumerate(cols) if c.startswith(prefix)]
    if not idx:
        return np.zeros((len(d["sids"]), 1)), []
    return d["X_peritem"][:, idx], [cols[i] for i in idx]


def site_inverse_propensity_weight(site_train: np.ndarray) -> np.ndarray:
    """Per-fold inverse-propensity weight: sample-weight = 1/p(site)."""
    n = len(site_train)
    n_nls = max(np.sum(site_train == 1), 1)
    n_wpd = max(np.sum(site_train == 0), 1)
    w = np.where(site_train == 1, n / (2 * n_nls), n / (2 * n_wpd))
    return w


# ── Variants ────────────────────────────────────────────────────────────────


def variant_v2_baseline(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """LGB on V2 only, target = item."""
    y = d["items"][item]
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_item_dedicated(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    y = d["items"][item]
    n = len(y)
    X_item, cols = get_item_features(d, item)
    if not cols:
        return np.full(n, np.nan)
    oof = np.zeros(n)
    k = min(500, X_item.shape[1])
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_item[tr], X_item[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=k, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_item_plus_v2(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    if not cols:
        return variant_v2_baseline(d, item, splits, seed)
    X_aug = np.hstack([d["X_v2"], X_item])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_hy_residual_item(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Stage-1 Ridge(H&Y) + Stage-2 LGB on (V2 ∪ item) residual."""
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
    X_item, cols = get_item_features(d, item)
    if cols:
        X_aug = np.hstack([d["X_v2"], X_item])
    else:
        X_aug = d["X_v2"]
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], y[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        s2_te = train_lgb(Xtr, resid_tr, Xte, seed)
        oof[te] = s1_te + s2_te
    return oof


def variant_hurdle_fog(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Item 11 only: stage-1 binary `any_FoG` (item>0) + stage-2 regressor on positives."""
    if item != 11:
        raise ValueError("hurdle_fog only valid for item 11")
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    X_aug = np.hstack([d["X_v2"], X_item]) if cols else d["X_v2"]
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        bin_tr = (y[tr] > 0).astype(int)
        Xtr_full, Xte_full = impute_fold(X_aug[tr], X_aug[te])
        # Stage 1: binary classifier (LGB)
        import lightgbm as lgb
        clf = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=15,
                                 min_data_in_leaf=5, n_jobs=2, random_state=seed, verbosity=-1)
        clf.fit(Xtr_full, bin_tr)
        prob_te = clf.predict_proba(Xte_full)[:, 1]
        # Stage 2: regress severity on positive train rows only
        pos_mask = bin_tr == 1
        if pos_mask.sum() < 5:
            oof[te] = prob_te * y[tr].mean()
            continue
        Xtr_pos = Xtr_full[pos_mask]
        y_tr_pos = y[tr][pos_mask]
        Xtr_pos_sel, Xte_sel, _ = feature_select_fold(Xtr_pos, y_tr_pos, Xte_full, k=300, seed=seed)
        sev_te = train_lgb(Xtr_pos_sel, y_tr_pos, Xte_sel, seed)
        oof[te] = prob_te * sev_te
    return oof


def variant_lr_multitask(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Predict L+R+abs(L-R) jointly via LGB Multi-output emulation (3 separate LGBs share features).
    Use abs(L-R) prediction as auxiliary regularizer."""
    if item not in PAIRED_ITEMS:
        raise ValueError(f"lr_multitask only for paired items: {PAIRED_ITEMS}")
    # NOTE: per_item_scores.json item-level (e.g., 7) is the SUM of (7,'R')+(7,'L').
    # We'll predict the item directly + the abs-diff between L/R features as augmentation.
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    n = len(y)
    if not cols:
        return variant_v2_baseline(d, item, splits, seed)
    # Identify L/R paired columns in item features
    l_cols = [c for c in cols if "_L_" in c or c.startswith(f"i{item}_L_")]
    r_cols = [c for c in cols if "_R_" in c or c.startswith(f"i{item}_R_")]
    # Compute abs-diff features
    abs_diff = []
    paired = []
    for lc in l_cols:
        rc = lc.replace("_L_", "_R_").replace(f"i{item}_L_", f"i{item}_R_")
        if rc in cols:
            li = cols.index(lc); ri = cols.index(rc)
            paired.append((li, ri))
    if paired:
        ad = np.array([np.abs(X_item[:, li] - X_item[:, ri]) for li, ri in paired]).T
        X_full = np.hstack([d["X_v2"], X_item, ad])
    else:
        X_full = np.hstack([d["X_v2"], X_item])
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_full[tr], X_full[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_item_plus_v2_plus_moment(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """LGB on item + V2 + MOMENT 768-d embeddings."""
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    if "X_moment" not in d:
        return variant_item_plus_v2(d, item, splits, seed)
    if cols:
        X_aug = np.hstack([d["X_v2"], X_item, d["X_moment"]])
    else:
        X_aug = np.hstack([d["X_v2"], d["X_moment"]])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_hy_residual_plus_moment(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Stage-1 Ridge(H&Y) + Stage-2 LGB on (V2 ∪ item ∪ MOMENT) residual."""
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
    X_item, cols = get_item_features(d, item)
    parts = [d["X_v2"]]
    if cols:
        parts.append(X_item)
    if "X_moment" in d:
        parts.append(d["X_moment"])
    X_aug = np.hstack(parts)
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], y[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        s2_te = train_lgb(Xtr, resid_tr, Xte, seed)
        oof[te] = s1_te + s2_te
    return oof


def variant_item_plus_v2_plus_hcssl(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """LGB on item + V2 + HC SSL embeddings."""
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    if "X_hcssl" not in d:
        return variant_item_plus_v2(d, item, splits, seed)
    if cols:
        X_aug = np.hstack([d["X_v2"], X_item, d["X_hcssl"]])
    else:
        X_aug = np.hstack([d["X_v2"], d["X_hcssl"]])
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_item_plus_all_embed(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """LGB on item + V2 + MOMENT + HC SSL embeddings (kitchen sink)."""
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    parts = [d["X_v2"]]
    if cols:
        parts.append(X_item)
    if "X_moment" in d:
        parts.append(d["X_moment"])
    if "X_hcssl" in d:
        parts.append(d["X_hcssl"])
    X_aug = np.hstack(parts)
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_hy_residual_all_embed(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Stage-1 Ridge(H&Y) + Stage-2 LGB on V2+item+MOMENT+HC-SSL residual."""
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
    X_item, cols = get_item_features(d, item)
    parts = [d["X_v2"]]
    if cols:
        parts.append(X_item)
    if "X_moment" in d:
        parts.append(d["X_moment"])
    if "X_hcssl" in d:
        parts.append(d["X_hcssl"])
    X_aug = np.hstack(parts)
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], y[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        s2_te = train_lgb(Xtr, resid_tr, Xte, seed)
        oof[te] = s1_te + s2_te
    return oof


# ── Track A: Item 9 event-aligned MOMENT variants ─────────────────────────


def variant_item9_event_moment(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Item 9 only: LGB on V2 + 3840-d event-aligned MOMENT embeddings."""
    if item != 9:
        raise ValueError("item9_event_moment is item-9 only")
    if "X_item9_event_moment" not in d:
        raise FileNotFoundError("Missing item9_event_moment cache")
    y = d["items"][item]
    X_item, _ = get_item_features(d, item)
    parts = [d["X_v2"], d["X_item9_event_moment"]]
    if X_item.shape[1] and not np.all(np.isnan(X_item)):
        parts.insert(1, X_item)
    X_aug = np.hstack(parts)
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_item9_event_moment_hy_residual(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Item 9 only: Stage-1 Ridge(H&Y) + Stage-2 LGB on V2 + event-MOMENT residual."""
    if item != 9:
        raise ValueError("item9_event_moment_hy_residual is item-9 only")
    if "X_item9_event_moment" not in d:
        raise FileNotFoundError("Missing item9_event_moment cache")
    y = d["items"][item]
    hy_feat = get_hy_features(d["hy"])
    X_item, _ = get_item_features(d, item)
    parts = [d["X_v2"], d["X_item9_event_moment"]]
    if X_item.shape[1] and not np.all(np.isnan(X_item)):
        parts.insert(1, X_item)
    X_aug = np.hstack(parts)
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        ridge = Ridge(alpha=1.0, random_state=seed)
        ridge.fit(hy_feat[tr], y[tr])
        s1_tr = ridge.predict(hy_feat[tr])
        s1_te = ridge.predict(hy_feat[te])
        resid_tr = y[tr] - s1_tr
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
        s2_te = train_lgb(Xtr, resid_tr, Xte, seed)
        oof[te] = s1_te + s2_te
    return oof


# ── Track B: Item 11 multiscale FoG variants ──────────────────────────────


def variant_item11_multiscale(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Item 11 only: LGB on item-features + V2 + multiscale FoG features."""
    if item != 11:
        raise ValueError("item11_multiscale is item-11 only")
    if "X_item11_multiscale" not in d:
        raise FileNotFoundError("Missing item11_multiscale cache")
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    parts = [d["X_v2"], d["X_item11_multiscale"]]
    if cols:
        parts.insert(1, X_item)
    X_aug = np.hstack(parts)
    n = len(y)
    oof = np.zeros(n)
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
    return oof


def variant_item11_hurdle_calibrated(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Item 11 only: hurdle (any_FoG classifier × severity regressor) with isotonic
    calibration on the classifier output. Uses V2 + multiscale features for both stages."""
    if item != 11:
        raise ValueError("item11_hurdle_calibrated is item-11 only")
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    parts = [d["X_v2"]]
    if cols:
        parts.append(X_item)
    if "X_item11_multiscale" in d:
        parts.append(d["X_item11_multiscale"])
    X_aug = np.hstack(parts)
    n = len(y)
    oof = np.zeros(n)
    import lightgbm as lgb
    from sklearn.isotonic import IsotonicRegression
    for tr, te in splits:
        bin_tr = (y[tr] > 0).astype(int)
        Xtr_full, Xte_full = impute_fold(X_aug[tr], X_aug[te])
        # Inner OOF probs on training fold for isotonic fit
        from sklearn.model_selection import StratifiedKFold
        prob_tr_oof = np.zeros(len(y[tr]))
        skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=seed)
        if bin_tr.sum() >= 6 and (len(bin_tr) - bin_tr.sum()) >= 6:
            for itr, ite in skf.split(Xtr_full, bin_tr):
                clf_i = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05,
                                           num_leaves=15, min_data_in_leaf=5,
                                           n_jobs=2, random_state=seed, verbosity=-1)
                clf_i.fit(Xtr_full[itr], bin_tr[itr])
                prob_tr_oof[ite] = clf_i.predict_proba(Xtr_full[ite])[:, 1]
            iso = IsotonicRegression(out_of_bounds="clip")
            iso.fit(prob_tr_oof, bin_tr)
        else:
            iso = None
        # Final classifier on full training fold
        clf = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05,
                                 num_leaves=15, min_data_in_leaf=5,
                                 n_jobs=2, random_state=seed, verbosity=-1)
        clf.fit(Xtr_full, bin_tr)
        prob_te_raw = clf.predict_proba(Xte_full)[:, 1]
        prob_te = iso.transform(prob_te_raw) if iso is not None else prob_te_raw
        # Stage 2: severity regressor on positives
        pos_mask = bin_tr == 1
        if pos_mask.sum() < 5:
            oof[te] = prob_te * (y[tr].mean() if len(y[tr]) else 0.0)
            continue
        Xtr_pos = Xtr_full[pos_mask]
        y_tr_pos = y[tr][pos_mask]
        Xtr_pos_sel, Xte_sel, _ = feature_select_fold(Xtr_pos, y_tr_pos, Xte_full, k=300, seed=seed)
        sev_te = train_lgb(Xtr_pos_sel, y_tr_pos, Xte_sel, seed)
        oof[te] = prob_te * sev_te
    return oof


def variant_item11_ngboost(d: dict, item: int, splits, seed: int = 42) -> np.ndarray:
    """Item 11 only: NGBoost distributional regression (heteroscedastic Normal).
    Falls back to LGB if ngboost is not installed."""
    if item != 11:
        raise ValueError("item11_ngboost is item-11 only")
    y = d["items"][item]
    X_item, cols = get_item_features(d, item)
    parts = [d["X_v2"]]
    if cols:
        parts.append(X_item)
    if "X_item11_multiscale" in d:
        parts.append(d["X_item11_multiscale"])
    X_aug = np.hstack(parts)
    n = len(y)
    oof = np.zeros(n)
    try:
        from ngboost import NGBRegressor
        from ngboost.distns import Normal
        from sklearn.tree import DecisionTreeRegressor
    except ImportError:
        # Soft-fallback: train a regular LGB if ngboost isn't installed
        for tr, te in splits:
            Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
            Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
            oof[te] = train_lgb(Xtr, y[tr], Xte, seed)
        return oof
    for tr, te in splits:
        Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
        Xtr, Xte, _ = feature_select_fold(Xtr, y[tr], Xte, k=500, seed=seed)
        base = DecisionTreeRegressor(max_depth=3)
        ngb = NGBRegressor(Dist=Normal, Base=base, n_estimators=300,
                           learning_rate=0.04, random_state=seed, verbose=False,
                           natural_gradient=True)
        ngb.fit(Xtr, y[tr])
        oof[te] = ngb.predict(Xte)
    return oof


VARIANTS = {
    "v2_baseline": variant_v2_baseline,
    "item_dedicated": variant_item_dedicated,
    "item_plus_v2": variant_item_plus_v2,
    "hy_residual_item": variant_hy_residual_item,
    "hurdle_fog": variant_hurdle_fog,
    "lr_multitask": variant_lr_multitask,
    "item_plus_v2_plus_moment": variant_item_plus_v2_plus_moment,
    "hy_residual_plus_moment": variant_hy_residual_plus_moment,
    "item_plus_v2_plus_hcssl": variant_item_plus_v2_plus_hcssl,
    "item_plus_all_embed": variant_item_plus_all_embed,
    "hy_residual_all_embed": variant_hy_residual_all_embed,
    # Track A: Item 9 event-aligned MOMENT
    "item9_event_moment": variant_item9_event_moment,
    "item9_event_moment_hy_residual": variant_item9_event_moment_hy_residual,
    # Track B: Item 11 multiscale FoG
    "item11_multiscale": variant_item11_multiscale,
    "item11_hurdle_calibrated": variant_item11_hurdle_calibrated,
    "item11_ngboost": variant_item11_ngboost,
}

HY_RESIDUAL_FOR = {1, 2, 3, 9, 13, 14, 17, 18}  # codex F34.D guidance
LR_MT_FOR = set(PAIRED_ITEMS)
HURDLE_FOR = {11}


def variant_set_for_item(item: int) -> list[str]:
    out = ["v2_baseline", "item_dedicated", "item_plus_v2"]
    if item in HY_RESIDUAL_FOR:
        out.append("hy_residual_item")
    if item in HURDLE_FOR:
        out.append("hurdle_fog")
    if item in LR_MT_FOR:
        out.append("lr_multitask")
    return out


# ── 5-null gate ─────────────────────────────────────────────────────────────


def run_5null_gate(d: dict, item: int, variant: str, seed: int = 42) -> dict:
    y = d["items"][item]
    splits = kfold_split_stratified(y, 5, seed=seed)
    fn = VARIANTS[variant]
    null = {}
    # 1. Scrambled-label
    rng = np.random.RandomState(seed)
    y_scram = rng.permutation(y)
    d2 = {**d, "items": {**d["items"], item: y_scram}}
    try:
        oof_s = fn(d2, item, splits, seed)
        null["scrambled_label_ccc"] = ccc_fn(y_scram, oof_s)
    except Exception as e:
        null["scrambled_label_error"] = str(e)
    # 2. Canary feature: inject only into test fold positions; model should not be able to use it
    canary = rng.randn(len(y))
    Xv2_aug = np.hstack([d["X_v2"], canary[:, None]])
    d3 = {**d, "X_v2": Xv2_aug}
    try:
        oof_c = fn(d3, item, splits, seed)
        null["canary_feature_ccc"] = ccc_fn(y, oof_c)
    except Exception as e:
        null["canary_feature_error"] = str(e)
    return null


# ── Driver ──────────────────────────────────────────────────────────────────


def run_one(d: dict, item: int, variant: str, eval_kind: str, seeds=SEEDS, with_null=True) -> dict:
    y = d["items"][item]
    # Filter NaN-target subjects (e.g. items 17/18 missing for ~2 subjects)
    nan_mask = np.isnan(y)
    if nan_mask.any():
        valid = np.where(~nan_mask)[0]
        d_f = {
            "sids": d["sids"][valid],
            "X_v2": d["X_v2"][valid],
            "X_peritem": d["X_peritem"][valid] if "X_peritem" in d else None,
            "peritem_cols": d.get("peritem_cols"),
            "hy": d["hy"][valid],
            "site": d["site"][valid] if "site" in d else None,
            "items": {k: (v[valid] if isinstance(v, np.ndarray) else v) for k, v in d["items"].items()},
            "feat_cols": d.get("feat_cols"),
            "t1": d["t1"][valid] if "t1" in d else None,
            "obs": d["obs"][valid] if "obs" in d and isinstance(d["obs"], np.ndarray) else None,
        }
        # Carry forward optional embedding caches if present
        for k in ("X_moment", "X_hcssl", "X_item9_event_moment", "X_item11_multiscale"):
            if k in d and isinstance(d[k], np.ndarray):
                d_f[k] = d[k][valid]
        for k in ("moment_cols", "hcssl_cols", "item9_event_moment_cols", "item11_multiscale_cols"):
            if k in d:
                d_f[k] = d[k]
        d = d_f
        y = d["items"][item]
    n = len(y)
    if eval_kind == "5split":
        per_seed = []
        for s in seeds:
            splits = kfold_split_stratified(y, 5, seed=s)
            oof = VARIANTS[variant](d, item, splits, s)
            per_seed.append(full_metrics(y, oof))
        # Aggregate
        ccc_mean = float(np.mean([m["ccc"] for m in per_seed]))
        ccc_std = float(np.std([m["ccc"] for m in per_seed]))
        mae_mean = float(np.mean([m["mae"] for m in per_seed]))
        out = {
            "item": item, "variant": variant, "eval": eval_kind,
            "n_subjects": int(n), "seeds": list(seeds),
            "ccc_mean": ccc_mean, "ccc_std": ccc_std, "mae_mean": mae_mean,
            "per_seed": per_seed,
        }
    elif eval_kind == "loocv":
        splits = [(np.array([j for j in range(n) if j != i]), np.array([i])) for i in range(n)]
        per_seed = []
        oof_acc = np.zeros(n)
        for s in seeds:
            oof_s = VARIANTS[variant](d, item, splits, s)
            per_seed.append(full_metrics(y, oof_s))
            oof_acc = oof_acc + oof_s
        oof_mean = oof_acc / len(seeds)
        ccc_mean = float(np.mean([m["ccc"] for m in per_seed]))
        ccc_std = float(np.std([m["ccc"] for m in per_seed]))
        mae_mean = float(np.mean([m["mae"] for m in per_seed]))
        out = {
            "item": item, "variant": variant, "eval": eval_kind,
            "n_subjects": int(n), "seeds": list(seeds),
            "ccc_mean": ccc_mean, "ccc_std": ccc_std, "mae_mean": mae_mean,
            "per_seed": per_seed,
            "_oof_array": oof_mean.tolist(),
        }
    else:
        raise ValueError(f"unknown eval_kind {eval_kind}")
    if with_null and eval_kind == "5split":
        out["null_tests"] = run_5null_gate(d, item, variant, seed=seeds[0])
    return out


def _run_one_for_pool(args) -> dict:
    d, item, variant, eval_kind, seeds = args
    try:
        return run_one(d, item, variant, eval_kind, seeds=seeds, with_null=(eval_kind == "5split"))
    except Exception as e:
        return {"item": item, "variant": variant, "eval": eval_kind, "error": str(e)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--item", type=int, default=0)
    p.add_argument("--variant", type=str, default="")
    p.add_argument("--eval", type=str, choices=["5split", "loocv"], default="5split")
    p.add_argument("--all", type=str, default="", help="run all items × all variants for given eval kind")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    p.add_argument("--out_dir", type=str, default=str(RESULTS_DIR))
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)
    print("Loading data...", flush=True)
    d = load_data()
    print(f"  N = {len(d['sids'])} PD subjects, {d['X_v2'].shape[1]} V2 features, {d['X_peritem'].shape[1]} per-item features", flush=True)

    if args.all:
        eval_kind = args.all
        jobs = []
        for item in MODELED_ITEMS:
            # Skip 1, 2, 3 (severity-proxy only)
            if item < 4:
                continue
            for v in variant_set_for_item(item):
                jobs.append((d, item, v, eval_kind, tuple(args.seeds)))
        print(f"Total jobs: {len(jobs)}", flush=True)
        # ProcessPoolExecutor with shared d won't work well due to large copies; use simple sequential or threads
        # For 5-fold each variant is fast (~10-30s); sequential is fine.
        results = []
        t0 = time.time()
        out_csv = out_dir / f"peritem_v2_screening_{eval_kind}.csv"
        out_json = out_dir / f"peritem_v2_screening_{eval_kind}.json"
        for i, args_ in enumerate(jobs):
            r = _run_one_for_pool(args_)
            results.append(r)
            elapsed = time.time() - t0
            ccc = r.get('ccc_mean')
            ccc_str = f"{ccc:.4f}" if isinstance(ccc, (int, float)) else "ERROR"
            err = r.get('error', '')
            print(f"  [{i+1}/{len(jobs)}] item={r.get('item')} variant={r.get('variant')} "
                  f"ccc={ccc_str} ({elapsed:.1f}s elapsed)" + (f" [{err}]" if err else ""), flush=True)
            # Progressive save every 5 jobs
            if (i + 1) % 5 == 0 or (i + 1) == len(jobs):
                df_out = pd.DataFrame([
                    {"item": r2["item"], "variant": r2["variant"], "eval": r2["eval"],
                     "ccc_mean": r2.get("ccc_mean", np.nan),
                     "ccc_std": r2.get("ccc_std", np.nan),
                     "mae_mean": r2.get("mae_mean", np.nan),
                     "scrambled_label_ccc": r2.get("null_tests", {}).get("scrambled_label_ccc", np.nan)}
                    for r2 in results
                ])
                df_out.to_csv(out_csv, index=False)
                with open(out_json, "w") as f:
                    json.dump(results, f, indent=2, default=float)
        print(f"\nWrote {out_csv} and {out_json}", flush=True)
        print(f"\nTop 20 by CCC:", flush=True)
        df_top = df_out.dropna(subset=["ccc_mean"]).sort_values("ccc_mean", ascending=False)
        print(df_top.head(20).to_string(), flush=True)
    else:
        if not args.variant:
            raise SystemExit("--variant required if --all not used")
        if args.item < 1 or args.item > 18:
            raise SystemExit("--item must be 1..18")
        r = run_one(d, args.item, args.variant, args.eval, seeds=tuple(args.seeds))
        out_path = out_dir / f"peritem_v2_item{args.item}_{args.variant}_{args.eval}.json"
        with open(out_path, "w") as f:
            json.dump(r, f, indent=2, default=float)
        print(json.dumps({"item": r["item"], "variant": r["variant"], "eval": r["eval"],
                          "ccc_mean": r.get("ccc_mean")}, default=float))
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

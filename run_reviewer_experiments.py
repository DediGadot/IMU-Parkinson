#!/usr/bin/env python3
"""run_reviewer_experiments.py — Experiments for reviewer response.

4 subcommands addressing reviewer comments C1-C3, C11:
  --age-sensitivity   : C2 — age-matched HC + age-stratified within-PD + partial correlation
  --hc-ablation       : C3 — P5 SSL without HC (PD-only ranker) vs with HC
  --single-sensor     : C11 — single wrist and lower back sensor ablation
  --obs-5fold         : C1 — 3-level observability decomposition under 5-fold

All experiments use 5-fold CV as primary evaluation.

Usage:
    python3 -u run_reviewer_experiments.py --age-sensitivity
    python3 -u run_reviewer_experiments.py --hc-ablation
    python3 -u run_reviewer_experiments.py --single-sensor
    python3 -u run_reviewer_experiments.py --obs-5fold
    python3 -u run_reviewer_experiments.py --all
"""
import argparse
import json
import os
import sys
import time
import warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from scipy.linalg import lstsq
from sklearn.model_selection import StratifiedShuffleSplit

warnings.filterwarnings("ignore")


# ── Auto-install ─────────────────────────────────────────────────────
def _ensure_deps():
    missing = []
    for pkg, imp in [("lightgbm", "lightgbm"), ("xgboost", "xgboost")]:
        try:
            __import__(imp)
        except ImportError:
            missing.append(pkg)
    if missing:
        import subprocess
        print(f"Installing: {' '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q"] + missing)

_ensure_deps()

import lightgbm as lgb
from xgboost import XGBRegressor, XGBRanker

from project_paths import REPO_ROOT, RESULTS_DIR, ensure_dir, results_artifact_path
sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, DATA_DIR, SENSORS

ensure_dir(RESULTS_DIR)

# ── Constants ────────────────────────────────────────────────────────
V2_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
FM_CACHE = str(results_artifact_path("fm_embeddings.npz"))
RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))
PER_ITEM_CACHE = str(results_artifact_path("per_item_scores.json"))
N_CORES = min(os.cpu_count() or 4, 11)
SEEDS = [42, 123, 456, 789, 2024]

T1_ITEMS = [9, 10, 11, 12, 13, 14]
T2_ITEMS = [7, 8, 9, 10, 11, 12, 13, 14]
T2_LR_ITEMS = {7, 8}
T3_ITEMS = list(range(1, 19))

TARGET_CLIP = {"t1": (0, 24), "t2": (0, 32), "t3": (0, 59)}

# Observability tiers for items
OBS_DIRECT_ITEMS = [9, 10, 11, 12, 13, 14]
OBS_PARTIAL_ITEMS = [5, 6, 7, 8, 15, 16, 17]
OBS_UNOBS_ITEMS = [1, 2, 3, 4, 18]

DEFAULT_LGB_PARAMS = {
    "n_estimators": 2000,
    "learning_rate": 0.03,
    "max_depth": 6,
    "num_leaves": 31,
    "reg_lambda": 0.3,
    "min_data_in_leaf": 8,
    "colsample_bytree": 0.5,
    "subsample": 1.0,
    "objective": "mse",
    "val_frac": 0.15,
    "early_stopping_rounds": 100,
}


# ═══════════════════════════════════════════════════════════════════════
# METRICS
# ═══════════════════════════════════════════════════════════════════════

from eval_utils import lins_ccc, cal_slope


def full_metrics(y_true, y_pred, label=""):
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    r = float(sp_stats.pearsonr(y_true, y_pred)[0]) if len(y_true) > 2 else 0.0
    ccc = lins_ccc(y_true, y_pred)
    slope = cal_slope(y_true, y_pred)
    return {
        "label": label,
        "mae": round(mae, 3), "rmse": round(rmse, 3), "r": round(r, 3),
        "ccc": round(ccc, 3), "cal_slope": round(float(slope), 3),
        "n": len(y_true),
    }


# ═══════════════════════════════════════════════════════════════════════
# DATA LOADING (reused from run_compression_ablation.py)
# ═══════════════════════════════════════════════════════════════════════

def extract_demographics():
    """Extract demographic covariates for all subjects.
    Returns dict sid -> {age, sex, years_dx, height_cm, weight_kg, hy, group, updrs3}.
    """
    demos = {}
    for filename, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(str(DATA_DIR), filename)
        assert os.path.exists(path), f"Clinical CSV not found: {path}"
        df = pd.read_csv(path, header=1)
        u3cols = [c for c in df.columns if c.startswith("MDSUPDRS_3-")]
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            updrs3 = pd.to_numeric(row[u3cols], errors="coerce").sum()
            if np.isnan(updrs3):
                continue
            age = pd.to_numeric(row.get("Age (years)", row.get("Age", np.nan)), errors="coerce")
            sex_raw = str(row.get("Sex", row.get("Gender", ""))).strip().upper()
            sex = 1 if sex_raw.startswith("M") else 0
            yrs = pd.to_numeric(row.get("Years since PD diagnosis",
                                        row.get("Years Since Diagnosis", np.nan)), errors="coerce")
            height_in = pd.to_numeric(row.get("Height (in)", row.get("Height (cm)", np.nan)), errors="coerce")
            height_cm = float(height_in * 2.54) if pd.notna(height_in) and height_in > 50 else (
                float(height_in) if pd.notna(height_in) else None)
            weight = pd.to_numeric(row.get("Weight (kg)", row.get("Weight", np.nan)), errors="coerce")
            hy = pd.to_numeric(
                row.get("Modified Hoehn & Yahr Score",
                         row.get("H&Y", row.get("Hoehn & Yahr", np.nan))),
                errors="coerce"
            )
            demos[sid] = {
                "age": float(age) if pd.notna(age) else None,
                "sex": sex,
                "years_dx": float(yrs) if pd.notna(yrs) else None,
                "height_cm": height_cm,
                "weight_kg": float(weight) if pd.notna(weight) else None,
                "hy": float(hy) if pd.notna(hy) else None,
                "group": group,
                "updrs3": float(updrs3),
            }
    return demos


SUBITEMS_MAP = {
    1: None, 2: None,
    3: ["a", "b", "c", "d", "e"],
    4: ["a", "b"], 5: ["a", "b"], 6: ["a", "b"],
    7: ["a", "b"], 8: ["a", "b"],
    9: None, 10: None, 11: None, 12: None, 13: None, 14: None,
    15: ["a", "b"], 16: ["a", "b"],
    17: ["a", "b", "c", "d", "e"],
    18: None,
}

from updrs_columns import find_updrs_value


def parse_per_item_scores():
    if os.path.exists(PER_ITEM_CACHE):
        with open(PER_ITEM_CACHE) as f:
            raw = json.load(f)
        result = {}
        for sid, scores in raw.items():
            result[sid] = {}
            for k, v in scores.items():
                if k.startswith("("):
                    result[sid][k] = v
                else:
                    result[sid][int(k)] = v
        return result

    print("Parsing per-item scores from clinical CSVs...")
    item_scores = {}
    for fn, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(str(DATA_DIR), fn)
        assert os.path.exists(path), f"Clinical CSV not found: {path}"
        df = pd.read_csv(path, header=1)
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            scores = {}
            for item_num in range(1, 19):
                sub = SUBITEMS_MAP[item_num]
                if sub is None:
                    val = find_updrs_value(row, df.columns, item_num)
                    if val is not None:
                        scores[item_num] = val
                    elif group == "HC":
                        scores[item_num] = 0.0
                else:
                    vals = []
                    subpart_scores = {}
                    for s in sub:
                        v = find_updrs_value(row, df.columns, item_num, s)
                        if v is not None:
                            vals.append(v)
                            subpart_scores[s] = v
                    if len(vals) == len(sub):
                        if item_num in T2_LR_ITEMS:
                            r_val = subpart_scores.get("a", 0.0)
                            l_val = subpart_scores.get("b", 0.0)
                            scores[f"({item_num}, 'R')"] = r_val
                            scores[f"({item_num}, 'L')"] = l_val
                            scores[item_num] = max(r_val, l_val)
                        else:
                            scores[item_num] = float(sum(vals))
                        for s, v in subpart_scores.items():
                            scores[f"({item_num}, '{s}')"] = v
                    elif len(vals) == 0 and group == "HC":
                        scores[item_num] = 0.0
                        if item_num in T2_LR_ITEMS:
                            scores[f"({item_num}, 'R')"] = 0.0
                            scores[f"({item_num}, 'L')"] = 0.0
                        for s in sub:
                            scores[f"({item_num}, '{s}')"] = 0.0
            if scores:
                item_scores[sid] = scores

    cache_obj = {}
    for sid, scores in item_scores.items():
        cache_obj[sid] = {str(k): v for k, v in scores.items()}
    with open(PER_ITEM_CACHE, "w") as f:
        json.dump(cache_obj, f, indent=2)
    print(f"Cached per-item scores to {PER_ITEM_CACHE} ({len(item_scores)} subjects)")
    return item_scores


def compute_target(item_scores, sid, target_key):
    if sid not in item_scores:
        return None
    scores = item_scores[sid]
    if target_key == "t1":
        items = T1_ITEMS
    elif target_key == "t2":
        items = T2_ITEMS
    else:
        raise ValueError(f"compute_target not used for T3. Got: {target_key}")
    total = 0.0
    for item in items:
        if item not in scores:
            return None
        total += scores[item]
    return total


def compute_obs_tier_scores(item_scores, sid):
    """Compute 3-level observability tier scores for a subject.
    Returns (direct, partial, unobs) or None if items missing.
    """
    if sid not in item_scores:
        return None
    scores = item_scores[sid]

    direct = 0.0
    for item in OBS_DIRECT_ITEMS:
        if item not in scores:
            return None
        direct += scores[item]

    partial = 0.0
    for item in OBS_PARTIAL_ITEMS:
        if item not in scores:
            return None
        partial += scores[item]

    unobs = 0.0
    for item in OBS_UNOBS_ITEMS:
        if item not in scores:
            return None
        unobs += scores[item]

    return (direct, partial, unobs)


def load_features_and_targets():
    """Load v2+FM features and all 3 targets. Returns merged dataframes."""
    assert os.path.exists(V2_CACHE), f"V2 cache not found: {V2_CACHE}"
    assert os.path.exists(FM_CACHE), f"FM cache not found: {FM_CACHE}"
    assert os.path.exists(RECORDING_CACHE), f"Recording cache not found: {RECORDING_CACHE}"

    v2_df = pd.read_csv(V2_CACHE)
    fm_embeddings = np.load(FM_CACHE)["embeddings"]
    rec_sids = np.load(RECORDING_CACHE)["sids"].tolist()

    d_model = fm_embeddings.shape[1]
    fm_df = pd.DataFrame(fm_embeddings, columns=[f"fm_{i}" for i in range(d_model)])
    fm_df["sid"] = rec_sids
    fm_agg = fm_df.groupby("sid").mean().reset_index()
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]

    EXCLUDED_COLS = {"sid", "updrs3", "obs_subscore", "hy"}
    EXTRA_PREFIXES = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")
    v2_feat_cols = [c for c in v2_df.columns
                    if c not in EXCLUDED_COLS
                    and not any(c.startswith(p) for p in EXTRA_PREFIXES)]

    merged = v2_df[["sid", "updrs3"] + v2_feat_cols].merge(fm_agg, on="sid", how="left").fillna(0.0)
    feature_cols = v2_feat_cols + fm_cols

    item_scores = parse_per_item_scores()
    subjects = parse_clinical()

    merged["t1_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t1"))
    merged["t2_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t2"))
    merged["t3_target"] = merged["updrs3"].astype(float)

    pd_sids = {sid for sid, info in subjects.items() if info.get("group") == "PD"}
    all_sids = {sid for sid, info in subjects.items()}

    pd_mask = merged["sid"].isin(pd_sids)
    pd_valid = pd_mask & merged["t1_target"].notna() & merged["t2_target"].notna()
    pd_merged = merged[pd_valid].copy()
    pd_merged["t1_target"] = pd_merged["t1_target"].astype(np.float32)
    pd_merged["t2_target"] = pd_merged["t2_target"].astype(np.float32)
    pd_merged["t3_target"] = pd_merged["t3_target"].astype(np.float32)

    all_valid = merged["t1_target"].notna() & merged["t2_target"].notna()
    all_merged = merged[all_valid].copy()
    all_merged["t1_target"] = all_merged["t1_target"].astype(np.float32)
    all_merged["t2_target"] = all_merged["t2_target"].astype(np.float32)
    all_merged["t3_target"] = all_merged["t3_target"].astype(np.float32)
    all_merged["is_pd"] = all_merged["sid"].isin(pd_sids).astype(int)

    print(f"\nData loaded:")
    print(f"  PD subjects: {len(pd_merged)}")
    print(f"  All subjects (PD+HC): {len(all_merged)}")
    print(f"  Features: {len(feature_cols)} (v2: {len(v2_feat_cols)}, FM: {len(fm_cols)})")
    for tk in ["t1", "t2", "t3"]:
        col = f"{tk}_target"
        vals = pd_merged[col]
        print(f"  {tk.upper()}: range [{vals.min():.0f}, {vals.max():.0f}], "
              f"mean={vals.mean():.1f}, std={vals.std():.1f}")

    return pd_merged, all_merged, feature_cols, subjects, item_scores


# ═══════════════════════════════════════════════════════════════════════
# SHARED TRAINING
# ═══════════════════════════════════════════════════════════════════════

def feature_select(X, y, names, k=500):
    k = min(k, X.shape[1])
    sel = XGBRegressor(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
        objective="reg:absoluteerror",
    )
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def train_lgb(Xd, yd, Xt, seed, params=None):
    p = dict(DEFAULT_LGB_PARAMS)
    if params:
        p.update(params)
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * p.get("val_frac", 0.15)))
    m = lgb.LGBMRegressor(
        n_estimators=p["n_estimators"],
        learning_rate=p["learning_rate"],
        max_depth=p["max_depth"],
        num_leaves=p["num_leaves"],
        reg_lambda=p["reg_lambda"],
        min_data_in_leaf=p["min_data_in_leaf"],
        colsample_bytree=p["colsample_bytree"],
        subsample=p["subsample"],
        random_state=seed,
        n_jobs=N_CORES,
        objective=p["objective"],
        verbose=-1,
    )
    m.fit(
        X=Xd[idx[nv:]],
        y=yd[idx[nv:]],
        eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
        callbacks=[lgb.early_stopping(p["early_stopping_rounds"], verbose=False)],
    )
    return m.predict(Xt)


def _target_bin(score, target_key):
    clip_lo, clip_hi = TARGET_CLIP[target_key]
    rng = clip_hi - clip_lo
    if score < clip_lo + rng * 0.25:
        return 0
    elif score < clip_lo + rng * 0.5:
        return 1
    elif score < clip_lo + rng * 0.75:
        return 2
    else:
        return 3


def gen_split(pd_merged, seed, target_key):
    sids = pd_merged["sid"].values
    target_col = f"{target_key}_target"
    bins = pd_merged[target_col].apply(lambda x: _target_bin(x, target_key)).values
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    di, ti = next(sss.split(sids, bins))
    return sids[di].tolist(), sids[ti].tolist()


# ═══════════════════════════════════════════════════════════════════════
# SSL PIPELINE (P5 core, supports HC subset argument)
# ═══════════════════════════════════════════════════════════════════════

def run_ssl_5fold(pd_merged, all_merged, feature_cols, target_key, hc_sids_subset=None):
    """Run P5 SSL with 5-fold CV. Optionally restrict HC to a subset.

    Args:
        hc_sids_subset: if provided, only use these HC SIDs in the ranker (for age matching / ablation)
                        if None, use all HC. If empty list, PD-only ranking (no HC).
    """
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    # Determine which subjects go into the ranker
    if hc_sids_subset is not None:
        # Filter all_merged to only include PD + specified HC
        pd_sids_set = set(pd_merged["sid"].values)
        hc_set = set(hc_sids_subset)
        ranker_merged = all_merged[
            all_merged["sid"].isin(pd_sids_set | hc_set)
        ].copy()
        n_hc_used = int((ranker_merged["is_pd"] == 0).sum())
        print(f"  Ranker uses {n_hc_used} HC (subset) + {len(pd_sids_set)} PD")
    else:
        ranker_merged = all_merged
        n_hc_used = int((ranker_merged["is_pd"] == 0).sum())
        print(f"  Ranker uses {n_hc_used} HC (all) + {int((ranker_merged['is_pd'] == 1).sum())} PD")

    # Pre-compute ranking labels for ranker subjects
    ranker_sids = ranker_merged["sid"].values
    ranker_targets = ranker_merged[target_col].values.astype(np.float32)
    ranker_is_pd = ranker_merged["is_pd"].values
    X_ranker = ranker_merged[feature_cols].values.astype(np.float32)

    rank_labels = np.zeros(len(ranker_sids), dtype=np.int32)
    pd_indices = np.where(ranker_is_pd == 1)[0]
    pd_order = np.argsort(ranker_targets[pd_indices])
    for rank, idx in enumerate(pd_order):
        rank_labels[pd_indices[idx]] = rank + 1

    sid_to_ranker_idx = {s: i for i, s in enumerate(ranker_sids)}

    # 5-fold CV
    n_splits = 5
    all_true = []
    all_pred = []
    all_sids_out = []
    t0 = time.time()

    for split_i in range(1, n_splits + 1):
        dev_s, test_s = gen_split(pd_merged, split_i, target_key)
        dm = pd_merged["sid"].isin(dev_s)
        tm = pd_merged["sid"].isin(test_s)
        Xd = pd_merged.loc[dm, feature_cols].values.astype(np.float32)
        yd = pd_merged.loc[dm, target_col].values.astype(np.float32)
        Xt = pd_merged.loc[tm, feature_cols].values.astype(np.float32)
        yt = pd_merged.loc[tm, target_col].values.astype(np.float32)
        sids_train = pd_merged.loc[dm, "sid"].values.tolist()
        sids_test = pd_merged.loc[tm, "sid"].values.tolist()

        # Feature selection inside fold
        sel_idx, sel_names = feature_select(Xd, yd, list(feature_cols), k=500)
        Xd_sel = Xd[:, sel_idx]
        Xt_sel = Xt[:, sel_idx]

        # Stage 1: Train XGBRanker on ranker subjects using selected features
        X_ranker_sel = X_ranker[:, sel_idx]
        group_sizes = np.array([len(X_ranker_sel)])

        all_leaf_features = []
        for seed in SEEDS[:3]:
            ranker = XGBRanker(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
                objective="rank:pairwise",
            )
            ranker.fit(X_ranker_sel, rank_labels, group=group_sizes)

            # Extract leaf indices for train and test PD subjects
            train_ranker_indices = [sid_to_ranker_idx[s] for s in sids_train if s in sid_to_ranker_idx]
            test_ranker_indices = [sid_to_ranker_idx[s] for s in sids_test if s in sid_to_ranker_idx]

            train_leaves = ranker.apply(X_ranker_sel[train_ranker_indices])
            test_leaves = ranker.apply(X_ranker_sel[test_ranker_indices])
            all_leaf_features.append((train_leaves, test_leaves))

        train_leaf_cat = np.hstack([lf[0] for lf in all_leaf_features]).astype(np.float32)
        test_leaf_cat = np.hstack([lf[1] for lf in all_leaf_features]).astype(np.float32)

        # Stage 2: Combine original + leaf features, train LGB
        Xd_combined = np.hstack([Xd_sel, train_leaf_cat])
        Xt_combined = np.hstack([Xt_sel, test_leaf_cat])

        preds = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd, Xt_combined, s)
            preds.append(np.clip(p, clip_lo, clip_hi))
        ep = np.mean(preds, axis=0)

        ccc = lins_ccc(yt, ep)
        mae = float(np.mean(np.abs(yt - ep)))
        slope = cal_slope(yt, ep)
        print(f"  Split {split_i}/{n_splits}: CCC={ccc:.3f} slope={slope:.3f} MAE={mae:.3f}")

        all_true.extend(yt.tolist())
        all_pred.extend(ep.tolist())
        all_sids_out.extend(sids_test)

    metrics = full_metrics(np.array(all_true), np.array(all_pred))
    metrics["eval_mode"] = "5split"
    metrics["runtime_s"] = round(time.time() - t0, 1)
    metrics["n_hc_used"] = n_hc_used
    metrics["per_subject"] = {
        "sids": all_sids_out,
        "y_true": all_true,
        "y_pred": [float(p) for p in all_pred],
    }
    return metrics


# ═══════════════════════════════════════════════════════════════════════
# C2: AGE-CONFOUND SENSITIVITY ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def run_age_sensitivity():
    """C2: Age-matched HC subset SSL + age-stratified within-PD + partial correlation."""
    print("\n" + "=" * 70)
    print("C2: AGE-CONFOUND SENSITIVITY ANALYSIS")
    print("=" * 70)

    t0 = time.time()
    pd_merged, all_merged, feature_cols, subjects, item_scores = load_features_and_targets()
    demos = extract_demographics()

    pd_sids = pd_merged["sid"].values.tolist()
    hc_sids = all_merged[all_merged["is_pd"] == 0]["sid"].values.tolist()

    pd_ages = np.array([demos.get(s, {}).get("age", np.nan) for s in pd_sids])
    hc_ages = np.array([demos.get(s, {}).get("age", np.nan) for s in hc_sids])

    pd_mean_age = np.nanmean(pd_ages)
    hc_mean_age = np.nanmean(hc_ages)
    print(f"\nPD mean age: {pd_mean_age:.1f} (N={len(pd_sids)})")
    print(f"HC mean age: {hc_mean_age:.1f} (N={len(hc_sids)})")

    # --- Analysis 1: Age-matched HC subset ---
    # Remove oldest HC to match PD age distribution
    # Strategy: keep HC whose age <= PD 75th percentile + 5y margin
    pd_age_p75 = np.nanpercentile(pd_ages, 75)
    age_threshold = pd_age_p75 + 5.0
    age_matched_hc = [s for s, a in zip(hc_sids, hc_ages)
                      if not np.isnan(a) and a <= age_threshold]

    matched_hc_ages = np.array([demos[s]["age"] for s in age_matched_hc])
    print(f"\nAge matching: HC threshold = {age_threshold:.1f}y (PD p75={pd_age_p75:.1f} + 5)")
    print(f"  HC retained: {len(age_matched_hc)}/{len(hc_sids)} "
          f"(mean age: {np.mean(matched_hc_ages):.1f})")

    # Statistical test for age balance
    u_stat_full, p_full = sp_stats.mannwhitneyu(
        pd_ages[~np.isnan(pd_ages)], hc_ages[~np.isnan(hc_ages)], alternative="two-sided")
    u_stat_matched, p_matched = sp_stats.mannwhitneyu(
        pd_ages[~np.isnan(pd_ages)], matched_hc_ages, alternative="two-sided")
    print(f"  Age difference (full): U={u_stat_full:.0f}, p={p_full:.4f}")
    print(f"  Age difference (matched): U={u_stat_matched:.0f}, p={p_matched:.4f}")

    results = {
        "phase": "age_sensitivity",
        "pd_mean_age": round(float(pd_mean_age), 1),
        "hc_mean_age_full": round(float(hc_mean_age), 1),
        "hc_mean_age_matched": round(float(np.mean(matched_hc_ages)), 1),
        "age_threshold": round(age_threshold, 1),
        "n_hc_full": len(hc_sids),
        "n_hc_matched": len(age_matched_hc),
        "age_test_full_p": round(float(p_full), 4),
        "age_test_matched_p": round(float(p_matched), 4),
    }

    # Run SSL with full HC and age-matched HC for T1 (primary outcome)
    print("\n--- SSL with FULL HC (reference) ---")
    ssl_full = run_ssl_5fold(pd_merged, all_merged, feature_cols, "t1", hc_sids_subset=None)
    results["ssl_full_hc_t1"] = ssl_full

    print("\n--- SSL with AGE-MATCHED HC ---")
    ssl_matched = run_ssl_5fold(pd_merged, all_merged, feature_cols, "t1",
                                hc_sids_subset=age_matched_hc)
    results["ssl_age_matched_t1"] = ssl_matched

    # Also run T3 for both
    print("\n--- SSL with FULL HC, T3 (reference) ---")
    ssl_full_t3 = run_ssl_5fold(pd_merged, all_merged, feature_cols, "t3", hc_sids_subset=None)
    results["ssl_full_hc_t3"] = ssl_full_t3

    print("\n--- SSL with AGE-MATCHED HC, T3 ---")
    ssl_matched_t3 = run_ssl_5fold(pd_merged, all_merged, feature_cols, "t3",
                                    hc_sids_subset=age_matched_hc)
    results["ssl_age_matched_t3"] = ssl_matched_t3

    # --- Analysis 2: Partial correlation of SSL predictions controlling for age ---
    print("\n--- Partial correlation (controlling age + disease duration) ---")
    ps = ssl_full["per_subject"]
    pred_sids = ps["sids"]
    y_true = np.array(ps["y_true"])
    y_pred = np.array(ps["y_pred"])

    ages_for_partial = np.array([float(demos.get(s, {}).get("age") or np.nan) for s in pred_sids], dtype=np.float64)
    yrs_dx = np.array([float(demos.get(s, {}).get("years_dx") or np.nan) for s in pred_sids], dtype=np.float64)

    # Impute NaN with median
    for arr in [ages_for_partial, yrs_dx]:
        mask = np.isnan(arr)
        if mask.any() and not mask.all():
            arr[mask] = np.nanmedian(arr)

    confounds = np.column_stack([ages_for_partial, np.ones(len(ages_for_partial))])
    beta_true, _, _, _ = lstsq(confounds, y_true)
    resid_true = y_true - confounds @ beta_true
    beta_pred, _, _, _ = lstsq(confounds, y_pred)
    resid_pred = y_pred - confounds @ beta_pred
    partial_r_age, partial_p_age = sp_stats.pearsonr(resid_true, resid_pred)
    print(f"  Partial r (controlling age only): {partial_r_age:.3f}, p={partial_p_age:.6f}")

    confounds2 = np.column_stack([ages_for_partial, yrs_dx, np.ones(len(ages_for_partial))])
    beta_true2, _, _, _ = lstsq(confounds2, y_true)
    resid_true2 = y_true - confounds2 @ beta_true2
    beta_pred2, _, _, _ = lstsq(confounds2, y_pred)
    resid_pred2 = y_pred - confounds2 @ beta_pred2
    partial_r_both, partial_p_both = sp_stats.pearsonr(resid_true2, resid_pred2)
    print(f"  Partial r (controlling age + dx_years): {partial_r_both:.3f}, p={partial_p_both:.6f}")

    results["partial_correlation"] = {
        "age_only": {"r": round(float(partial_r_age), 3),
                     "p": round(float(partial_p_age), 6)},
        "age_and_dx_years": {"r": round(float(partial_r_both), 3),
                              "p": round(float(partial_p_both), 6)},
    }

    # --- Analysis 3: Age-stratified within-PD evaluation ---
    print("\n--- Age-stratified within-PD evaluation ---")
    age_terciles = np.nanpercentile(ages_for_partial, [33.3, 66.7])
    strata = {
        f"young (<{age_terciles[0]:.0f}y)": ages_for_partial < age_terciles[0],
        f"middle ({age_terciles[0]:.0f}-{age_terciles[1]:.0f}y)":
            (ages_for_partial >= age_terciles[0]) & (ages_for_partial < age_terciles[1]),
        f"older (>={age_terciles[1]:.0f}y)": ages_for_partial >= age_terciles[1],
    }

    strata_results = {}
    for name, mask in strata.items():
        n_stratum = int(mask.sum())
        if n_stratum < 5:
            print(f"  {name}: N={n_stratum} — too few, skipping")
            continue
        yt_s = y_true[mask]
        yp_s = y_pred[mask]
        m = full_metrics(yt_s, yp_s, label=name)
        strata_results[name] = m
        print(f"  {name}: N={n_stratum}, CCC={m['ccc']:.3f}, MAE={m['mae']:.3f}, r={m['r']:.3f}")

    results["age_strata"] = strata_results
    results["age_tercile_bounds"] = [round(float(t), 1) for t in age_terciles]
    results["runtime_s"] = round(time.time() - t0, 1)

    # Summary table
    print(f"\n{'='*70}")
    print("SUMMARY: Age Sensitivity")
    print(f"{'='*70}")
    print(f"{'Condition':<30} {'CCC':>7} {'MAE':>7} {'r':>7} {'slope':>7}")
    print(f"{'-'*70}")
    for label, data in [("Full HC", ssl_full), ("Age-matched HC", ssl_matched)]:
        print(f"{label + ' (T1)':<30} {data['ccc']:>7.3f} {data['mae']:>7.3f} "
              f"{data['r']:>7.3f} {data['cal_slope']:>7.3f}")
    for label, data in [("Full HC", ssl_full_t3), ("Age-matched HC", ssl_matched_t3)]:
        print(f"{label + ' (T3)':<30} {data['ccc']:>7.3f} {data['mae']:>7.3f} "
              f"{data['r']:>7.3f} {data['cal_slope']:>7.3f}")
    print(f"\nPartial r (age only): {partial_r_age:.3f} (p={partial_p_age:.6f})")
    print(f"Partial r (age+dx):  {partial_r_both:.3f} (p={partial_p_both:.6f})")
    print(f"{'='*70}")

    out_path = str(results_artifact_path("reviewer_age_sensitivity.json"))
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {out_path}")
    return results


# ═══════════════════════════════════════════════════════════════════════
# C3: HC ABLATION — SSL WITH AND WITHOUT HC
# ═══════════════════════════════════════════════════════════════════════

def run_hc_ablation():
    """C3: Compare P5 SSL with HC vs without HC (PD-only ranker)."""
    print("\n" + "=" * 70)
    print("C3: HC ABLATION — SSL WITH vs WITHOUT HC")
    print("=" * 70)

    t0 = time.time()
    pd_merged, all_merged, feature_cols, subjects, item_scores = load_features_and_targets()

    results = {"phase": "hc_ablation"}

    for target_key in ["t1", "t3"]:
        print(f"\n{'='*50}")
        print(f"Target: {target_key.upper()}")
        print(f"{'='*50}")

        # P0: Baseline (no ranking at all) — standard LGB 5-fold
        print("\n--- P0: Baseline (no ranking) ---")
        target_col = f"{target_key}_target"
        clip_lo, clip_hi = TARGET_CLIP[target_key]

        all_true_p0, all_pred_p0 = [], []
        for split_i in range(1, 6):
            dev_s, test_s = gen_split(pd_merged, split_i, target_key)
            dm = pd_merged["sid"].isin(dev_s)
            tm = pd_merged["sid"].isin(test_s)
            Xd = pd_merged.loc[dm, feature_cols].values.astype(np.float32)
            yd = pd_merged.loc[dm, target_col].values.astype(np.float32)
            Xt = pd_merged.loc[tm, feature_cols].values.astype(np.float32)
            yt = pd_merged.loc[tm, target_col].values.astype(np.float32)

            sel_idx, _ = feature_select(Xd, yd, list(feature_cols), k=500)
            Xd_sel = Xd[:, sel_idx]
            Xt_sel = Xt[:, sel_idx]

            preds = []
            for s in SEEDS:
                p = train_lgb(Xd_sel, yd, Xt_sel, s)
                preds.append(np.clip(p, clip_lo, clip_hi))
            ep = np.mean(preds, axis=0)

            ccc = lins_ccc(yt, ep)
            print(f"  Split {split_i}/5: CCC={ccc:.3f}")
            all_true_p0.extend(yt.tolist())
            all_pred_p0.extend(ep.tolist())

        p0_metrics = full_metrics(np.array(all_true_p0), np.array(all_pred_p0),
                                  label="P0_baseline")
        results[f"p0_baseline_{target_key}"] = p0_metrics
        print(f"  P0 baseline: CCC={p0_metrics['ccc']:.3f} MAE={p0_metrics['mae']:.3f}")

        # P5-no-HC: SSL with PD-only ranking (no HC anchors)
        print("\n--- P5-no-HC: SSL with PD-only ranking (no HC) ---")
        ssl_no_hc = run_ssl_5fold(pd_merged, all_merged, feature_cols, target_key,
                                   hc_sids_subset=[])  # empty = no HC
        results[f"p5_no_hc_{target_key}"] = ssl_no_hc
        print(f"  P5-no-HC: CCC={ssl_no_hc['ccc']:.3f} MAE={ssl_no_hc['mae']:.3f}")

        # P5-with-HC: SSL with full HC (reference)
        print("\n--- P5-with-HC: SSL with full HC ---")
        ssl_with_hc = run_ssl_5fold(pd_merged, all_merged, feature_cols, target_key,
                                     hc_sids_subset=None)
        results[f"p5_with_hc_{target_key}"] = ssl_with_hc
        print(f"  P5-with-HC: CCC={ssl_with_hc['ccc']:.3f} MAE={ssl_with_hc['mae']:.3f}")

    results["runtime_s"] = round(time.time() - t0, 1)

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY: HC Ablation")
    print(f"{'='*70}")
    print(f"{'Method':<25} {'T1 CCC':>8} {'T1 MAE':>8} {'T3 CCC':>8} {'T3 MAE':>8}")
    print(f"{'-'*70}")
    for label, key in [("P0 Baseline", "p0_baseline"),
                       ("P5 SSL (no HC)", "p5_no_hc"),
                       ("P5 SSL (with HC)", "p5_with_hc")]:
        t1 = results.get(f"{key}_t1", {})
        t3 = results.get(f"{key}_t3", {})
        print(f"{label:<25} {t1.get('ccc', 0):>8.3f} {t1.get('mae', 0):>8.3f} "
              f"{t3.get('ccc', 0):>8.3f} {t3.get('mae', 0):>8.3f}")
    print(f"{'='*70}")

    out_path = str(results_artifact_path("reviewer_hc_ablation.json"))
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {out_path}")
    return results


# ═══════════════════════════════════════════════════════════════════════
# C11: SINGLE-SENSOR SENSITIVITY
# ═══════════════════════════════════════════════════════════════════════

def run_single_sensor():
    """C11: Single wrist and single lower back sensor ablation.
    Uses the same v2+FM pipeline as run_sensor_ablation.py but with
    the SSL pipeline for T1 (observable subscore).
    """
    print("\n" + "=" * 70)
    print("C11: SINGLE-SENSOR SENSITIVITY ANALYSIS")
    print("=" * 70)

    t0 = time.time()
    pd_merged, all_merged, feature_cols, subjects, item_scores = load_features_and_targets()

    # Get all v2 feature column names (before FM merge)
    v2_df = pd.read_csv(V2_CACHE)
    EXCLUDED_COLS = {"sid", "updrs3", "obs_subscore", "hy"}
    EXTRA_PREFIXES = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")
    all_v2_cols = [c for c in v2_df.columns
                   if c not in EXCLUDED_COLS
                   and not any(c.startswith(p) for p in EXTRA_PREFIXES)]

    configs = {
        "R_Wrist_1": ["R_Wrist"],
        "L_Wrist_1": ["L_Wrist"],
        "LowerBack_1": ["LowerBack"],
        "wrists_2": ["R_Wrist", "L_Wrist"],
        "all_13": SENSORS,
    }

    results = {"phase": "single_sensor_sensitivity", "configs": {}}

    for cfg_name, sensor_list in configs.items():
        print(f"\n{'='*50}")
        print(f"Config: {cfg_name} — sensors: {sensor_list}")
        print(f"{'='*50}")

        # Filter v2 features for this sensor set
        sensor_set = set(sensor_list)
        keep_v2 = []
        for col in all_v2_cols:
            # Direct sensor-prefixed features
            matched_sensor = None
            for s in SENSORS:
                if col.startswith(s + "_"):
                    matched_sensor = s
                    break
            if matched_sensor is not None:
                if matched_sensor in sensor_set:
                    keep_v2.append(col)
                continue
            # Asymmetry features
            if col.startswith("asy_"):
                parts = col.split("_")
                if len(parts) >= 2:
                    pair_name = parts[1]
                    if f"R_{pair_name}" in sensor_set and f"L_{pair_name}" in sensor_set:
                        keep_v2.append(col)
                continue
            # Event/turn/balance/STS: derived from LowerBack
            if col.startswith(("ev_", "trn_", "sts_", "bal_")):
                if "LowerBack" in sensor_set:
                    keep_v2.append(col)
                continue
            # Foot contact
            if col.startswith("fc_"):
                foot_sensors = {"R_DorsalFoot", "L_DorsalFoot", "R_Ankle", "L_Ankle"}
                if sensor_set & foot_sensors:
                    keep_v2.append(col)
                continue
            # Covariates: always keep
            if col.startswith(("cv_", "n_")) or col in ("duration_s",):
                keep_v2.append(col)
                continue
            # Distribution/contrast features
            if col.startswith(("dv_", "d_", "r_")):
                found = any(s in col for s in sensor_set)
                if found or not any(s in col for s in SENSORS):
                    keep_v2.append(col)
                continue
            # Distilled walkway — skip for clean sensor ablation
            if col.startswith("dst_"):
                continue
            # Unknown column — keep
            keep_v2.append(col)

        # FM features: keep all (FM was extracted from all sensors, per the original protocol)
        # For sensor ablation, we'd ideally re-extract FM per config, but that requires
        # per-config FM caches. For single-sensor, we use v2-only to be conservative.
        sensor_feature_cols = keep_v2  # v2-only for sensor ablation (no FM leakage)
        print(f"  Features available: {len(sensor_feature_cols)} / {len(all_v2_cols)}")

        if len(sensor_feature_cols) < 10:
            print(f"  SKIP: too few features ({len(sensor_feature_cols)})")
            results["configs"][cfg_name] = {"skipped": True, "n_features": len(sensor_feature_cols)}
            continue

        # Filter pd_merged and all_merged to only these features
        valid_cols = [c for c in sensor_feature_cols if c in pd_merged.columns]
        if len(valid_cols) < 10:
            print(f"  SKIP: only {len(valid_cols)} valid columns in merged data")
            results["configs"][cfg_name] = {"skipped": True, "n_features": len(valid_cols)}
            continue

        # Run SSL 5-fold with these features for T1
        ssl_result = run_ssl_5fold(pd_merged, all_merged, valid_cols, "t1",
                                    hc_sids_subset=None)
        ssl_result["n_sensors"] = len(sensor_list)
        ssl_result["sensors"] = sensor_list
        ssl_result["n_features_available"] = len(valid_cols)
        results["configs"][cfg_name] = ssl_result
        print(f"  SSL T1: CCC={ssl_result['ccc']:.3f} MAE={ssl_result['mae']:.3f} "
              f"r={ssl_result['r']:.3f}")

    results["runtime_s"] = round(time.time() - t0, 1)

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY: Single-Sensor Sensitivity (SSL, T1)")
    print(f"{'='*70}")
    print(f"{'Config':<15} {'Sensors':>3} {'Features':>8} {'CCC':>7} {'MAE':>7} {'r':>7}")
    print(f"{'-'*70}")
    for cfg_name, data in results["configs"].items():
        if data.get("skipped"):
            print(f"{cfg_name:<15} {'?':>3} {data.get('n_features', 0):>8} {'SKIP':>7}")
        else:
            print(f"{cfg_name:<15} {data['n_sensors']:>3} {data['n_features_available']:>8} "
                  f"{data['ccc']:>7.3f} {data['mae']:>7.3f} {data['r']:>7.3f}")
    print(f"{'='*70}")

    out_path = str(results_artifact_path("reviewer_single_sensor.json"))
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {out_path}")
    return results


# ═══════════════════════════════════════════════════════════════════════
# C1: 3-LEVEL OBSERVABILITY UNDER 5-FOLD CV
# ═══════════════════════════════════════════════════════════════════════

def run_obs_5fold():
    """C1: 3-level observability decomposition under 5-fold CV.
    Trains separate models for direct, partial, and unobservable subscores.
    """
    print("\n" + "=" * 70)
    print("C1: 3-LEVEL OBSERVABILITY DECOMPOSITION (5-FOLD CV)")
    print("=" * 70)

    t0 = time.time()
    pd_merged, all_merged, feature_cols, subjects, item_scores = load_features_and_targets()

    # Compute observability tier targets for PD subjects
    pd_sids = pd_merged["sid"].values.tolist()
    obs_scores = {}
    for sid in pd_sids:
        tiers = compute_obs_tier_scores(item_scores, sid)
        if tiers is not None:
            obs_scores[sid] = {"direct": tiers[0], "partial": tiers[1], "unobs": tiers[2]}

    print(f"Observability scores available for {len(obs_scores)}/{len(pd_sids)} PD subjects")

    # Add tier targets to pd_merged
    pd_merged = pd_merged[pd_merged["sid"].isin(obs_scores)].copy()
    pd_merged["obs_direct_target"] = pd_merged["sid"].apply(lambda s: obs_scores[s]["direct"]).astype(np.float32)
    pd_merged["obs_partial_target"] = pd_merged["sid"].apply(lambda s: obs_scores[s]["partial"]).astype(np.float32)
    pd_merged["obs_unobs_target"] = pd_merged["sid"].apply(lambda s: obs_scores[s]["unobs"]).astype(np.float32)

    # Also update all_merged
    all_merged_sids = set(all_merged["sid"].values)
    for sid in all_merged_sids:
        if sid not in obs_scores:
            # HC subjects: set observability scores to 0
            obs_scores[sid] = {"direct": 0.0, "partial": 0.0, "unobs": 0.0}
    all_merged["obs_direct_target"] = all_merged["sid"].apply(
        lambda s: obs_scores.get(s, {}).get("direct", 0.0)).astype(np.float32)
    all_merged["obs_partial_target"] = all_merged["sid"].apply(
        lambda s: obs_scores.get(s, {}).get("partial", 0.0)).astype(np.float32)
    all_merged["obs_unobs_target"] = all_merged["sid"].apply(
        lambda s: obs_scores.get(s, {}).get("unobs", 0.0)).astype(np.float32)

    results = {"phase": "obs_5fold_decomposition", "n_pd": len(pd_merged)}

    # For each tier, use the SSL pipeline with the tier-specific target
    tiers = [
        ("direct", "obs_direct_target", (0, 24)),
        ("partial", "obs_partial_target", (0, 60)),  # rough upper bound
        ("unobs", "obs_unobs_target", (0, 40)),
    ]

    for tier_name, target_col, (clip_lo, clip_hi) in tiers:
        print(f"\n{'='*50}")
        print(f"Tier: {tier_name} (target: {target_col})")
        print(f"{'='*50}")

        # Run P5 SSL 5-fold for this tier
        # We need a custom target, so we temporarily rename the column
        tk_fake = "t1"  # reuse t1 splitting logic
        pd_merged_tier = pd_merged.copy()
        pd_merged_tier["t1_target"] = pd_merged_tier[target_col]

        all_merged_tier = all_merged.copy()
        all_merged_tier["t1_target"] = all_merged_tier[target_col]

        # Run SSL 5-fold
        ssl_result = run_ssl_5fold(pd_merged_tier, all_merged_tier, feature_cols, tk_fake,
                                    hc_sids_subset=None)

        # Also run baseline (no SSL) for comparison
        print(f"\n  Baseline (no SSL) for {tier_name}:")
        all_true_bl, all_pred_bl = [], []
        for split_i in range(1, 6):
            dev_s, test_s = gen_split(pd_merged_tier, split_i, tk_fake)
            dm = pd_merged_tier["sid"].isin(dev_s)
            tm = pd_merged_tier["sid"].isin(test_s)
            Xd = pd_merged_tier.loc[dm, feature_cols].values.astype(np.float32)
            yd = pd_merged_tier.loc[dm, "t1_target"].values.astype(np.float32)
            Xt = pd_merged_tier.loc[tm, feature_cols].values.astype(np.float32)
            yt = pd_merged_tier.loc[tm, "t1_target"].values.astype(np.float32)

            sel_idx, _ = feature_select(Xd, yd, list(feature_cols), k=500)
            preds = []
            for s in SEEDS:
                p = train_lgb(Xd[:, sel_idx], yd, Xt[:, sel_idx], s)
                preds.append(np.clip(p, clip_lo, clip_hi))
            ep = np.mean(preds, axis=0)
            all_true_bl.extend(yt.tolist())
            all_pred_bl.extend(ep.tolist())

        baseline_metrics = full_metrics(np.array(all_true_bl), np.array(all_pred_bl),
                                        label=f"{tier_name}_baseline")

        results[f"{tier_name}_ssl"] = ssl_result
        results[f"{tier_name}_baseline"] = baseline_metrics

        print(f"\n  {tier_name} SSL:      CCC={ssl_result['ccc']:.3f} MAE={ssl_result['mae']:.3f} "
              f"r={ssl_result['r']:.3f}")
        print(f"  {tier_name} baseline: CCC={baseline_metrics['ccc']:.3f} "
              f"MAE={baseline_metrics['mae']:.3f} r={baseline_metrics['r']:.3f}")

    results["runtime_s"] = round(time.time() - t0, 1)

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY: 3-Level Observability (5-fold CV)")
    print(f"{'='*70}")
    print(f"{'Tier':<12} {'Method':<12} {'CCC':>7} {'MAE':>7} {'r':>7} {'slope':>7}")
    print(f"{'-'*70}")
    for tier_name in ["direct", "partial", "unobs"]:
        for method, key in [("SSL", f"{tier_name}_ssl"), ("Baseline", f"{tier_name}_baseline")]:
            d = results.get(key, {})
            print(f"{tier_name:<12} {method:<12} {d.get('ccc', 0):>7.3f} "
                  f"{d.get('mae', 0):>7.3f} {d.get('r', 0):>7.3f} "
                  f"{d.get('cal_slope', 0):>7.3f}")
    print(f"{'='*70}")

    out_path = str(results_artifact_path("reviewer_obs_5fold.json"))
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {out_path}")
    return results


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Reviewer experiments for PD-IMU paper")
    parser.add_argument("--age-sensitivity", action="store_true",
                        help="C2: Age-confound sensitivity analysis")
    parser.add_argument("--hc-ablation", action="store_true",
                        help="C3: HC ablation (SSL with/without HC)")
    parser.add_argument("--single-sensor", action="store_true",
                        help="C11: Single sensor ablation")
    parser.add_argument("--obs-5fold", action="store_true",
                        help="C1: 3-level observability under 5-fold")
    parser.add_argument("--all", action="store_true",
                        help="Run all experiments")
    args = parser.parse_args()

    if not any([args.age_sensitivity, args.hc_ablation, args.single_sensor,
                args.obs_5fold, args.all]):
        parser.print_help()
        sys.exit(1)

    t0 = time.time()

    if args.age_sensitivity or args.all:
        run_age_sensitivity()

    if args.hc_ablation or args.all:
        run_hc_ablation()

    if args.single_sensor or args.all:
        run_single_sensor()

    if args.obs_5fold or args.all:
        run_obs_5fold()

    total_time = time.time() - t0
    print(f"\n\nTotal runtime: {total_time:.0f}s ({total_time / 60:.1f}m)")


if __name__ == "__main__":
    main()

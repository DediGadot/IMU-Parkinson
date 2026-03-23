#!/usr/bin/env python3
"""autoresearch_ccc_eval.py — Fixed evaluation harness for CCC optimization.

Targets the OBSERVABLE SUBSCORE (items 3.9-3.14, range 0-24) on PD-only subjects.
Primary metric: CCC (Lin's concordance correlation coefficient).
Secondary: cal_slope, MAE, r.

DO NOT MODIFY THIS FILE. The AI agent only modifies autoresearch_config.py.

Usage:
    python3 -u autoresearch_ccc_eval.py              # run experiment
    python3 -u autoresearch_ccc_eval.py --baseline    # compute + save baseline
    python3 -u autoresearch_ccc_eval.py --full        # force 10-split validation
    python3 -u autoresearch_ccc_eval.py --loocv       # LOOCV validation (slow)
"""
import argparse
import json
import os
import sys
import time
import traceback
import warnings

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.linear_model import Ridge

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
from xgboost import XGBRegressor

from project_paths import RESULTS_DIR, results_artifact_path, ensure_dir
from data_split import parse_clinical, _get_valid_sids


# ── Constants ────────────────────────────────────────────────────────
V2_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
FM_CACHE = str(results_artifact_path("fm_embeddings.npz"))
RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))
VELINC_CACHE = str(results_artifact_path("velinc_features.csv"))
VELINC_GATED_CACHE = str(results_artifact_path("velinc_gated_features.csv"))
WALKWAY_CACHE = str(results_artifact_path("walkway_features.csv"))
OBS_DIRECT_CACHE = str(results_artifact_path("obs_direct_subscores.json"))
BASELINE_FILE = str(results_artifact_path("autoresearch_ccc_baseline.json"))
N_CORES = min(os.cpu_count() or 4, 11)
CLIP_MAX = 24  # observable subscore range 0-24 (items 3.9-3.14, 6 items × 4)
ensure_dir(RESULTS_DIR)


# ═══════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════

def load_data():
    """Load ALL feature caches + strict obs_direct subscore (items 3.9-3.14). PD-only.

    Returns a dict of feature groups so the config can select which to use:
      - v2_core: standard handcrafted (1480)
      - v2_extra: normally-excluded groups (nl_, sv_, fq_, ix_, ext_, pa_, hr_)
      - fm: MOMENT-1 embeddings (768)
      - velinc: VelocityIncrement features (if cached)
      - velinc_gated: phase-gated VelInc Walk/Turn (if cached)
      - walkway: raw walkway metrics (if cached)
      Plus per-prefix groups: dv_, d_, fc_, ev_, trn_, asy_, k_, cv_, dst_
    """
    assert os.path.exists(V2_CACHE), f"V2 cache not found: {V2_CACHE}"
    assert os.path.exists(FM_CACHE), f"FM cache not found: {FM_CACHE}"
    assert os.path.exists(RECORDING_CACHE), f"Recording cache not found: {RECORDING_CACHE}"
    assert os.path.exists(OBS_DIRECT_CACHE), (
        f"Obs direct subscore cache not found: {OBS_DIRECT_CACHE}\n"
        "Generate it by running the obs_direct computation script first.")

    v2_df = pd.read_csv(V2_CACHE)
    fm_embeddings = np.load(FM_CACHE)["embeddings"]
    rec_sids = np.load(RECORDING_CACHE)["sids"].tolist()

    # Load strict obs_direct subscores (items 3.9-3.14 only, max=24)
    import json as _json
    with open(OBS_DIRECT_CACHE) as f:
        obs_raw = _json.load(f)
    obs_direct = {sid: info["obs_direct"] for sid, info in obs_raw.items()}

    # Aggregate FM embeddings per subject
    d_model = fm_embeddings.shape[1]
    fm_df = pd.DataFrame(fm_embeddings, columns=[f"fm_{i}" for i in range(d_model)])
    fm_df["sid"] = rec_sids
    fm_agg = fm_df.groupby("sid").mean().reset_index()
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]

    # Categorize ALL v2 columns into groups
    EXCLUDED_COLS = {"sid", "updrs3", "obs_subscore", "hy"}
    EXTRA_PREFIXES = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")
    NAMED_PREFIXES = {
        "dv_": "dv", "d_": "delta", "fc_": "fc", "ev_": "ev",
        "trn_": "turn", "asy_": "asym", "k_": "kinematic",
        "cv_": "covariate", "dst_": "distilled",
    }

    feature_groups = {
        "fm": fm_cols,
        "v2_extra_nl": [], "v2_extra_sv": [], "v2_extra_fq": [],
        "v2_extra_ix": [], "v2_extra_ext": [], "v2_extra_pa": [], "v2_extra_hr": [],
    }
    v2_core_cols = []
    v2_all_cols = []  # everything from v2 cache (excl targets)

    for c in v2_df.columns:
        if c in EXCLUDED_COLS:
            continue
        v2_all_cols.append(c)

        # Check named prefix groups
        matched = False
        for pfx, grp in NAMED_PREFIXES.items():
            if c.startswith(pfx):
                feature_groups.setdefault(f"v2_{grp}", []).append(c)
                matched = True
                break

        if not matched:
            # Check extra prefixes
            for ep in EXTRA_PREFIXES:
                if c.startswith(ep):
                    feature_groups[f"v2_extra_{ep.rstrip('_')}"].append(c)
                    matched = True
                    break

        if not matched:
            v2_core_cols.append(c)

    feature_groups["v2_core"] = v2_core_cols

    # Start with v2 all columns + FM
    merged = v2_df[["sid"] + v2_all_cols].merge(fm_agg, on="sid", how="left").fillna(0.0)

    # Load optional caches
    velinc_cols, velinc_gated_cols, walkway_cols = [], [], []

    if os.path.exists(VELINC_CACHE):
        vi_df = pd.read_csv(VELINC_CACHE)
        velinc_cols = [c for c in vi_df.columns if c != "sid"]
        merged = merged.merge(vi_df, on="sid", how="left").fillna(0.0)
        feature_groups["velinc"] = velinc_cols
        print(f"  VelInc loaded: {len(velinc_cols)} features")

    if os.path.exists(VELINC_GATED_CACHE):
        vig_df = pd.read_csv(VELINC_GATED_CACHE)
        velinc_gated_cols = [c for c in vig_df.columns if c != "sid"]
        merged = merged.merge(vig_df, on="sid", how="left").fillna(0.0)
        feature_groups["velinc_gated"] = velinc_gated_cols
        print(f"  VelInc gated loaded: {len(velinc_gated_cols)} features")

    if os.path.exists(WALKWAY_CACHE):
        wk_df = pd.read_csv(WALKWAY_CACHE)
        walkway_cols = [c for c in wk_df.columns if c != "sid"]
        merged = merged.merge(wk_df, on="sid", how="left").fillna(0.0)
        feature_groups["walkway"] = walkway_cols
        print(f"  Walkway loaded: {len(walkway_cols)} features")

    # Add strict obs_direct target
    merged["obs_target"] = merged["sid"].map(obs_direct)

    # Filter to PD subjects with valid obs_direct subscore
    subjects = parse_clinical()
    pd_sids = {sid for sid, info in subjects.items() if info.get("group") == "PD"}
    pd_merged = merged[merged["sid"].isin(pd_sids) & merged["obs_target"].notna()].copy()
    pd_merged["obs_target"] = pd_merged["obs_target"].astype(np.float32)

    # Print feature group summary
    print(f"\nData: {len(pd_merged)} PD subjects")
    print(f"Obs DIRECT (items 3.9-3.14): range [{pd_merged['obs_target'].min():.0f}, "
          f"{pd_merged['obs_target'].max():.0f}], mean={pd_merged['obs_target'].mean():.1f}")
    print(f"Feature groups:")
    total_feats = 0
    for grp, cols in sorted(feature_groups.items()):
        if cols:
            print(f"  {grp:20s}: {len(cols):5d}")
            total_feats += len(cols)
    print(f"  {'TOTAL':20s}: {total_feats:5d}")

    return pd_merged, feature_groups, subjects


# ═══════════════════════════════════════════════════════════════════════
# SPLITTING (PD-only)
# ═══════════════════════════════════════════════════════════════════════

def _obs_bin(score):
    """Bin obs direct subscore for stratification. Range [0,14], 3 bins."""
    if score < 3:
        return 0
    elif score < 6:
        return 1
    else:
        return 2

def gen_pd_split(pd_merged, seed):
    """Deterministic stratified 80/20 split on PD-only subjects."""
    sids = pd_merged["sid"].values
    bins = pd_merged["obs_target"].apply(_obs_bin).values
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    di, ti = next(sss.split(sids, bins))
    return sids[di].tolist(), sids[ti].tolist()


# ═══════════════════════════════════════════════════════════════════════
# FEATURE SELECTION
# ═══════════════════════════════════════════════════════════════════════

def feature_select(X, y, names, k=150, fs_params=None):
    """XGB importance-based feature selection targeting obs_subscore."""
    k = min(k, X.shape[1])
    params = {
        "n_estimators": 300, "max_depth": 4, "learning_rate": 0.05,
        "reg_lambda": 2.0, "random_state": 42, "n_jobs": N_CORES,
        "objective": "reg:absoluteerror",
    }
    if fs_params:
        params.update(fs_params)
    sel = XGBRegressor(**params)
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


# ═══════════════════════════════════════════════════════════════════════
# MODEL TRAINING (CPU only — GPU is slower for N<200)
# ═══════════════════════════════════════════════════════════════════════

def train_lgb(Xd, yd, Xt, seed, params):
    """Train single LightGBM on CPU, return predictions on Xt."""
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * params.get("val_frac", 0.15)))
    m = lgb.LGBMRegressor(
        n_estimators=params.get("n_estimators", 2000),
        learning_rate=params.get("learning_rate", 0.03),
        max_depth=params.get("max_depth", 6),
        num_leaves=params.get("num_leaves", 31),
        reg_lambda=params.get("reg_lambda", 3.0),
        min_data_in_leaf=params.get("min_data_in_leaf", 20),
        colsample_bytree=params.get("colsample_bytree", 1.0),
        subsample=params.get("subsample", 1.0),
        random_state=seed,
        n_jobs=N_CORES,
        objective=params.get("objective", "mse"),
        verbose=-1,
    )
    m.fit(
        Xd[idx[nv:]], yd[idx[nv:]],
        eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
        callbacks=[lgb.early_stopping(params.get("early_stopping_rounds", 100), verbose=False)],
    )
    return m.predict(Xt)


def train_xgb(Xd, yd, Xt, seed, params):
    """Train single XGBoost on CPU, return predictions on Xt."""
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * params.get("val_frac", 0.15)))
    m = XGBRegressor(
        n_estimators=params.get("n_estimators", 2000),
        learning_rate=params.get("learning_rate", 0.03),
        max_depth=params.get("max_depth", 6),
        reg_lambda=params.get("reg_lambda", 3.0),
        colsample_bytree=params.get("colsample_bytree", 1.0),
        subsample=params.get("subsample", 1.0),
        random_state=seed,
        n_jobs=N_CORES,
        early_stopping_rounds=params.get("early_stopping_rounds", 100),
        objective=params.get("objective", "reg:absoluteerror"),
    )
    m.fit(
        Xd[idx[nv:]], yd[idx[nv:]],
        eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
        verbose=False,
    )
    return m.predict(Xt)


# ═══════════════════════════════════════════════════════════════════════
# METRICS
# ═══════════════════════════════════════════════════════════════════════

def lins_ccc(y_true, y_pred):
    """Lin's concordance correlation coefficient."""
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    mu_t, mu_p = np.mean(y_true), np.mean(y_pred)
    var_t, var_p = np.var(y_true), np.var(y_pred)
    cov = np.mean((y_true - mu_t) * (y_pred - mu_p))
    denom = var_t + var_p + (mu_t - mu_p) ** 2
    return float(2 * cov / denom) if denom > 1e-12 else 0.0


def cal_slope(y_true, y_pred):
    """Calibration slope (linear regression of pred on true)."""
    if np.std(y_true) < 1e-8:
        return 0.0
    return float(np.polyfit(y_true, y_pred, 1)[0])


# ═══════════════════════════════════════════════════════════════════════
# ENSEMBLE RUNNERS
# ═══════════════════════════════════════════════════════════════════════

def run_lgb_ensemble(Xds, yd, Xts, seeds, lgb_params):
    preds = [np.clip(train_lgb(Xds, yd, Xts, s, lgb_params), 0, CLIP_MAX) for s in seeds]
    return np.mean(preds, axis=0)


def run_xgb_ensemble(Xds, yd, Xts, seeds, xgb_params):
    preds = [np.clip(train_xgb(Xds, yd, Xts, s, xgb_params), 0, CLIP_MAX) for s in seeds]
    return np.mean(preds, axis=0)


def run_average_ensemble(Xds, yd, Xts, seeds, lgb_params, xgb_params):
    preds = []
    for s in seeds:
        p_l = train_lgb(Xds, yd, Xts, s, lgb_params)
        p_x = train_xgb(Xds, yd, Xts, s, xgb_params)
        preds.append(np.clip((p_l + p_x) / 2, 0, CLIP_MAX))
    return np.mean(preds, axis=0)


def run_stack_ensemble(Xds, yd, Xts, seeds, lgb_params, xgb_params, meta_alpha):
    from sklearn.model_selection import KFold
    preds = []
    for s in seeds:
        kf = KFold(n_splits=5, shuffle=True, random_state=s)
        oof_l, oof_x = np.zeros(len(Xds)), np.zeros(len(Xds))
        tp_l, tp_x = np.zeros(len(Xts)), np.zeros(len(Xts))
        for tr_i, val_i in kf.split(Xds):
            oof_l[val_i] = train_lgb(Xds[tr_i], yd[tr_i], Xds[val_i], s, lgb_params)
            tp_l += train_lgb(Xds[tr_i], yd[tr_i], Xts, s, lgb_params) / 5
            oof_x[val_i] = train_xgb(Xds[tr_i], yd[tr_i], Xds[val_i], s, xgb_params)
            tp_x += train_xgb(Xds[tr_i], yd[tr_i], Xts, s, xgb_params) / 5
        L0tr = np.column_stack([oof_l, oof_x])
        L0te = np.column_stack([tp_l, tp_x])
        meta = Ridge(alpha=meta_alpha)
        meta.fit(L0tr, yd)
        preds.append(np.clip(meta.predict(L0te), 0, CLIP_MAX))
    return np.mean(preds, axis=0)


# ═══════════════════════════════════════════════════════════════════════
# EXPERIMENT RUNNER
# ═══════════════════════════════════════════════════════════════════════

def resolve_feature_cols(config, feature_groups, pd_merged):
    """Resolve config's use_groups list into actual column names.

    Config knob 'use_groups' is a list of feature group names to include.
    Available groups (from load_data):
      v2_core, v2_dv, v2_delta, v2_fc, v2_ev, v2_turn, v2_asym,
      v2_kinematic, v2_covariate, v2_distilled,
      v2_extra_nl, v2_extra_sv, v2_extra_fq, v2_extra_ix, v2_extra_ext,
      v2_extra_pa, v2_extra_hr,
      fm, velinc, velinc_gated, walkway

    Shortcuts:
      "v2" = v2_core + all v2_* subgroups (excl extra_*)
      "v2+extras" = v2 + all v2_extra_* groups
      "v2+fm" = v2 + fm
      "all" = everything available
    """
    use_groups = config.get("use_groups", None)

    # Legacy: if use_groups not set, fall back to use_cols
    if use_groups is None:
        use_cols = config.get("use_cols", "v2+fm")
        if use_cols == "v2":
            use_groups = ["v2"]
        elif use_cols == "fm":
            use_groups = ["fm"]
        elif use_cols == "v2+fm":
            use_groups = ["v2", "fm"]
        elif use_cols == "v2+fm+velinc":
            use_groups = ["v2", "fm", "velinc"]
        elif use_cols == "all_raw":
            use_groups = ["all"]
        else:
            use_groups = ["v2", "fm"]

    # Expand shortcuts
    V2_SUBGROUPS = [k for k in feature_groups if k.startswith("v2_") and not k.startswith("v2_extra")]
    V2_EXTRA_GROUPS = [k for k in feature_groups if k.startswith("v2_extra")]
    expanded = []
    for g in use_groups:
        if g == "v2":
            expanded.extend(V2_SUBGROUPS)
        elif g == "v2+extras":
            expanded.extend(V2_SUBGROUPS + V2_EXTRA_GROUPS)
        elif g == "all":
            expanded.extend(feature_groups.keys())
        else:
            expanded.append(g)

    # Collect columns from requested groups
    cols = []
    used_groups = []
    for g in expanded:
        if g in feature_groups and feature_groups[g]:
            cols.extend(feature_groups[g])
            used_groups.append(g)

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for c in cols:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    cols = deduped

    # Verify all columns exist in dataframe
    available = set(pd_merged.columns)
    cols = [c for c in cols if c in available]

    n_groups = len(used_groups)
    print(f"  Features: {len(cols)} from {n_groups} groups: {', '.join(used_groups)}")
    return cols


def run_experiment(config, pd_merged, feature_groups):
    """Run CV experiment targeting obs_subscore. Returns result dict."""
    t0 = time.time()
    n_splits = config.get("n_splits", 5)
    seeds = config.get("seeds", [42, 123, 456, 789, 2024])
    feature_k = config.get("feature_k", 300)
    ensemble = config.get("ensemble", "lgb_only")
    lgb_params = config.get("lgb_params", {})
    xgb_params = config.get("xgb_params", {})
    fs_params = config.get("fs_params", None)
    custom_transform = config.get("custom_transform", None)
    meta_alpha = config.get("meta_alpha", 1.0)

    cols = resolve_feature_cols(config, feature_groups, pd_merged)

    split_cccs, split_maes, split_slopes, split_rs = [], [], [], []

    for split_i in range(1, n_splits + 1):
        dev_s, test_s = gen_pd_split(pd_merged, split_i)
        dm = pd_merged["sid"].isin(dev_s)
        tm = pd_merged["sid"].isin(test_s)
        Xd = pd_merged.loc[dm, cols].values.astype(np.float32)
        yd = pd_merged.loc[dm, "obs_target"].values.astype(np.float32)
        Xt = pd_merged.loc[tm, cols].values.astype(np.float32)
        yt = pd_merged.loc[tm, "obs_target"].values.astype(np.float32)

        # Custom transform (optional)
        col_names = list(cols)
        if custom_transform is not None:
            Xd, Xt, col_names = custom_transform(Xd, yd, Xt, col_names)

        # Feature selection (on dev only, targeting obs_subscore)
        sel_idx, _ = feature_select(Xd, yd, col_names, k=feature_k, fs_params=fs_params)
        Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

        # Ensemble prediction
        if ensemble == "lgb_only":
            ep = run_lgb_ensemble(Xds, yd, Xts, seeds, lgb_params)
        elif ensemble == "xgb_only":
            ep = run_xgb_ensemble(Xds, yd, Xts, seeds, xgb_params)
        elif ensemble == "average":
            ep = run_average_ensemble(Xds, yd, Xts, seeds, lgb_params, xgb_params)
        elif ensemble == "stack":
            ep = run_stack_ensemble(Xds, yd, Xts, seeds, lgb_params, xgb_params, meta_alpha)
        else:
            raise ValueError(f"Unknown ensemble type: {ensemble}")

        mae = float(mean_absolute_error(yt, ep))
        r_val = float(sp_stats.pearsonr(yt, ep)[0]) if len(yt) > 2 else 0.0
        ccc = lins_ccc(yt, ep)
        slope = cal_slope(yt, ep)

        split_cccs.append(ccc)
        split_maes.append(mae)
        split_slopes.append(slope)
        split_rs.append(r_val)
        print(f"  Split {split_i}/{n_splits}: CCC={ccc:.3f} slope={slope:.3f} "
              f"MAE={mae:.3f} r={r_val:.3f}")

    # Serialize config (skip non-serializable fields)
    serializable_config = {k: v for k, v in config.items() if k != "custom_transform"}

    return {
        "name": config.get("name", "unnamed"),
        "description": config.get("description", ""),
        "n_splits": n_splits,
        "ensemble": ensemble,
        "feature_k": feature_k,
        "use_groups": config.get("use_groups", config.get("use_cols", "v2+fm")),
        "n_features": len(cols),
        "ccc_mean": round(float(np.mean(split_cccs)), 4),
        "ccc_std": round(float(np.std(split_cccs)), 4),
        "slope_mean": round(float(np.mean(split_slopes)), 4),
        "mae_mean": round(float(np.mean(split_maes)), 4),
        "mae_std": round(float(np.std(split_maes)), 4),
        "r_mean": round(float(np.mean(split_rs)), 4),
        "split_cccs": [round(c, 4) for c in split_cccs],
        "split_maes": [round(m, 4) for m in split_maes],
        "split_slopes": [round(s, 4) for s in split_slopes],
        "runtime_s": round(time.time() - t0, 1),
        "config": serializable_config,
    }


# ═══════════════════════════════════════════════════════════════════════
# LOOCV RUNNER (for validation only)
# ═══════════════════════════════════════════════════════════════════════

def run_loocv(config, pd_merged, feature_groups):
    """Run PD-only LOOCV. Slow but definitive."""
    t0 = time.time()
    seeds = config.get("seeds", [42, 123, 456, 789, 2024])
    feature_k = config.get("feature_k", 300)
    lgb_params = config.get("lgb_params", {})
    fs_params = config.get("fs_params", None)
    custom_transform = config.get("custom_transform", None)

    cols = resolve_feature_cols(config, feature_groups, pd_merged)

    sids = pd_merged["sid"].values
    n = len(sids)
    y_true_all = pd_merged["obs_target"].values.astype(np.float32)
    X_all = pd_merged[cols].values.astype(np.float32)
    y_pred_all = np.zeros(n, dtype=np.float64)

    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        Xd, yd = X_all[mask], y_true_all[mask]
        Xt = X_all[i:i+1]

        col_names = list(cols)
        if custom_transform is not None:
            Xd, Xt, col_names = custom_transform(Xd, yd, Xt, col_names)

        sel_idx, _ = feature_select(Xd, yd, col_names, k=feature_k, fs_params=fs_params)
        Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

        preds = [np.clip(train_lgb(Xds, yd, Xts, s, lgb_params), 0, CLIP_MAX)[0] for s in seeds]
        y_pred_all[i] = float(np.mean(preds))

        if (i + 1) % 10 == 0:
            running_mae = float(np.mean(np.abs(y_true_all[:i+1] - y_pred_all[:i+1])))
            running_ccc = lins_ccc(y_true_all[:i+1], y_pred_all[:i+1])
            elapsed = time.time() - t0
            remaining = elapsed / (i + 1) * (n - i - 1)
            print(f"    [{i+1}/{n}] CCC={running_ccc:.3f} MAE={running_mae:.3f} "
                  f"({elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining)")

    ccc = lins_ccc(y_true_all, y_pred_all)
    mae = float(np.mean(np.abs(y_true_all - y_pred_all)))
    r_val = float(sp_stats.pearsonr(y_true_all, y_pred_all)[0])
    slope = cal_slope(y_true_all, y_pred_all)

    print(f"\n  LOOCV DONE in {time.time()-t0:.0f}s: CCC={ccc:.3f} slope={slope:.3f} "
          f"MAE={mae:.3f} r={r_val:.3f}")

    serializable_config = {k: v for k, v in config.items() if k != "custom_transform"}
    return {
        "name": config.get("name", "unnamed") + "_loocv",
        "description": config.get("description", "") + " [LOOCV validation]",
        "eval_mode": "loocv",
        "n": n,
        "ccc": round(ccc, 4),
        "slope": round(slope, 4),
        "mae": round(mae, 4),
        "r": round(r_val, 4),
        "runtime_s": round(time.time() - t0, 1),
        "config": serializable_config,
    }


# ═══════════════════════════════════════════════════════════════════════
# BASELINE MANAGEMENT (CCC-based)
# ═══════════════════════════════════════════════════════════════════════

def load_baseline():
    if os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE) as f:
            return json.load(f)
    return None


def save_baseline(result):
    with open(BASELINE_FILE, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Baseline saved: CCC={result['ccc_mean']:.4f} slope={result['slope_mean']:.4f} "
          f"-> {BASELINE_FILE}")


def compare_to_baseline(result, baseline):
    """Compare experiment to baseline using CCC as primary metric."""
    if baseline is None:
        return {"has_baseline": False}

    if result["n_splits"] != baseline["n_splits"]:
        return {
            "has_baseline": True, "comparable": False,
            "reason": f"Split mismatch: experiment={result['n_splits']}, baseline={baseline['n_splits']}",
        }

    exp_cccs = result["split_cccs"]
    base_cccs = baseline["split_cccs"]
    improvement = result["ccc_mean"] - baseline["ccc_mean"]

    try:
        _, p = sp_stats.wilcoxon(exp_cccs, base_cccs)
        wilcoxon_p = round(float(p), 6)
    except Exception:
        wilcoxon_p = 1.0

    # KEEP if: CCC improvement > 0.01 AND p < 0.20
    # (more lenient p-threshold because CCC has higher variance on small splits)
    keep = improvement > 0.01 and wilcoxon_p < 0.20

    return {
        "has_baseline": True, "comparable": True,
        "baseline_ccc": baseline["ccc_mean"],
        "experiment_ccc": result["ccc_mean"],
        "improvement": round(improvement, 4),
        "wilcoxon_p": wilcoxon_p,
        "keep": keep,
        "reason": f"{'KEEP' if keep else 'DISCARD'}: ΔCCC={improvement:+.4f}, p={wilcoxon_p:.4f}",
    }


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Autoresearch CCC evaluation harness")
    parser.add_argument("--baseline", action="store_true", help="Compute + save baseline")
    parser.add_argument("--full", action="store_true", help="Force 10-split evaluation")
    parser.add_argument("--loocv", action="store_true", help="Run LOOCV validation (slow)")
    args = parser.parse_args()

    print("=" * 60)
    print("AUTORESEARCH CCC HARNESS — Observable Subscore (items 3.9-3.14)")
    print("Target: PD-only, CCC optimization, clip [0, 24]")
    print("=" * 60)
    pd_merged, feature_groups, subjects = load_data()

    # Import config
    try:
        from autoresearch_config import get_config
        config = get_config()
    except Exception as e:
        print(f"\nFATAL: Failed to import autoresearch_config: {e}")
        traceback.print_exc()
        crash = {"status": "CRASH", "error": str(e), "traceback": traceback.format_exc()}
        print("\n<<<AUTORESEARCH_RESULT>>>")
        print(json.dumps(crash))
        print("<<<END_RESULT>>>")
        sys.exit(1)

    if args.full:
        config["n_splits"] = 10

    print(f"\nExperiment: {config.get('name', 'unnamed')}")
    print(f"Description: {config.get('description', '')}")
    print(f"Config: ensemble={config.get('ensemble')}, K={config.get('feature_k')}, "
          f"splits={config.get('n_splits')}, cols={config.get('use_cols')}")

    # Run experiment
    try:
        if args.loocv:
            result = run_loocv(config, pd_merged, feature_groups)
            result["status"] = "OK"
            print("\n<<<AUTORESEARCH_RESULT>>>")
            print(json.dumps(result))
            print("<<<END_RESULT>>>")
            return

        result = run_experiment(config, pd_merged, feature_groups)
        result["status"] = "OK"
    except Exception as e:
        print(f"\nCRASH: {e}")
        traceback.print_exc()
        crash = {"status": "CRASH", "error": str(e), "traceback": traceback.format_exc(),
                 "name": config.get("name", "unnamed")}
        print("\n<<<AUTORESEARCH_RESULT>>>")
        print(json.dumps(crash))
        print("<<<END_RESULT>>>")
        sys.exit(1)

    if args.baseline:
        result["is_baseline"] = True
        save_baseline(result)
        print(f"\nBASELINE ESTABLISHED: CCC = {result['ccc_mean']:.4f} ± {result['ccc_std']:.4f}")
        print(f"                     slope = {result['slope_mean']:.4f}")
        print(f"                     MAE   = {result['mae_mean']:.4f}")
        print("\n<<<AUTORESEARCH_RESULT>>>")
        print(json.dumps(result))
        print("<<<END_RESULT>>>")
        return

    # Compare to baseline
    baseline = load_baseline()
    comparison = compare_to_baseline(result, baseline)
    result["comparison"] = comparison

    # Auto-update baseline on KEEP
    if comparison.get("keep"):
        save_baseline(result)

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"RESULT: CCC   = {result['ccc_mean']:.4f} ± {result['ccc_std']:.4f}")
    print(f"        slope = {result['slope_mean']:.4f}")
    print(f"        MAE   = {result['mae_mean']:.4f} ± {result['mae_std']:.4f}")
    print(f"        r     = {result['r_mean']:.4f}")
    print(f"        Runtime: {result['runtime_s']:.1f}s")
    if comparison.get("comparable"):
        print(f"\nBASELINE: CCC = {comparison['baseline_ccc']:.4f}")
        print(f"DELTA:    {comparison['improvement']:+.4f} (Wilcoxon p={comparison['wilcoxon_p']:.4f})")
        print(f"VERDICT:  {comparison['reason']}")
    elif comparison.get("has_baseline") and not comparison.get("comparable"):
        print(f"\nCANNOT COMPARE: {comparison['reason']}")
    else:
        print("\nNO BASELINE — run with --baseline first")
    print("=" * 60)

    # Output JSON for agent parsing
    print("\n<<<AUTORESEARCH_RESULT>>>")
    print(json.dumps(result))
    print("<<<END_RESULT>>>")


if __name__ == "__main__":
    main()

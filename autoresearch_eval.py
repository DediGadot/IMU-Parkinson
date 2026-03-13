#!/usr/bin/env python3
"""autoresearch_eval.py — Fixed evaluation harness for autonomous research.

DO NOT MODIFY THIS FILE. The AI agent only modifies autoresearch_config.py.

Loads cached v2+FM features, runs experiment config, compares to baseline,
outputs structured JSON result block for the agent to parse.

Usage:
    python3 -u autoresearch_eval.py              # run experiment
    python3 -u autoresearch_eval.py --baseline    # compute + save baseline
    python3 -u autoresearch_eval.py --full        # force 10-split validation
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
from sklearn.model_selection import KFold, StratifiedShuffleSplit
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
from data_split import parse_clinical, _updrs_bin, _get_valid_sids


# ── Constants ────────────────────────────────────────────────────────
V2_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
FM_CACHE = str(results_artifact_path("fm_embeddings.npz"))
RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))
BASELINE_FILE = str(results_artifact_path("autoresearch_baseline.json"))
N_CORES = min(os.cpu_count() or 4, 11)
CLIP_MAX = 132
ensure_dir(RESULTS_DIR)


# ═══════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════

def load_data():
    """Load cached features. Fail fast if caches missing."""
    assert os.path.exists(V2_CACHE), (
        f"V2 cache not found: {V2_CACHE}\nRun run_ablation_v3.py first.")
    assert os.path.exists(FM_CACHE), (
        f"FM cache not found: {FM_CACHE}\nRun run_rocket_ablation.py --phase 2 first.")
    assert os.path.exists(RECORDING_CACHE), (
        f"Recording cache not found: {RECORDING_CACHE}\nRun run_rocket_ablation.py --phase 0 first.")

    v2_df = pd.read_csv(V2_CACHE)
    fm_embeddings = np.load(FM_CACHE)["embeddings"]
    rec_sids = np.load(RECORDING_CACHE)["sids"].tolist()

    # Aggregate FM embeddings per subject
    d_model = fm_embeddings.shape[1]
    fm_df = pd.DataFrame(fm_embeddings, columns=[f"fm_{i}" for i in range(d_model)])
    fm_df["sid"] = rec_sids
    fm_agg = fm_df.groupby("sid").mean().reset_index()
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]

    # Standard v2 feature filter
    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_", "obs_subscore"))
               and c != "hy"]

    # Merge v2 + FM
    merged = v2_df[["sid", "updrs3"] + v2_cols].merge(fm_agg, on="sid", how="left").fillna(0.0)
    all_cols = v2_cols + fm_cols

    subjects = parse_clinical()
    print(f"Data: {len(merged)} subjects, {len(v2_cols)} v2 + {len(fm_cols)} FM = {len(all_cols)} features")
    return merged, all_cols, v2_cols, fm_cols, subjects


# ═══════════════════════════════════════════════════════════════════════
# SPLITTING
# ═══════════════════════════════════════════════════════════════════════

def gen_split(subjects, seed):
    """Deterministic stratified 80/20 split."""
    valid = _get_valid_sids(subjects)
    sids = np.array(valid)
    bins = np.array([_updrs_bin(subjects[s]["updrs3"]) for s in sids])
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    di, ti = next(sss.split(sids, bins))
    return sids[di].tolist(), sids[ti].tolist()


# ═══════════════════════════════════════════════════════════════════════
# FEATURE SELECTION
# ═══════════════════════════════════════════════════════════════════════

def feature_select(X, y, names, k=150, fs_params=None):
    """XGB importance-based feature selection."""
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
# MODEL TRAINING
# ═══════════════════════════════════════════════════════════════════════

def train_lgb(Xd, yd, Xt, seed, params):
    """Train single LightGBM, return predictions on Xt."""
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
        objective=params.get("objective", "mae"),
        verbose=-1,
        device="gpu",
    )
    m.fit(
        Xd[idx[nv:]], yd[idx[nv:]],
        eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
        callbacks=[lgb.early_stopping(params.get("early_stopping_rounds", 100), verbose=False)],
    )
    return m.predict(Xt)


def train_xgb(Xd, yd, Xt, seed, params):
    """Train single XGBoost, return predictions on Xt."""
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
        device="cuda",
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

def run_experiment(config, merged, all_cols, v2_cols, fm_cols, subjects):
    """Run CV experiment with given config. Returns result dict."""
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

    # Select feature columns
    use_cols = config.get("use_cols", "v2+fm")
    if use_cols == "v2":
        cols = list(v2_cols)
    elif use_cols == "fm":
        cols = list(fm_cols)
    elif use_cols == "all_raw":
        cols = [c for c in merged.columns if c not in ("sid", "updrs3")]
    else:
        cols = list(all_cols)

    # Include extra prefixes if specified
    extra_prefixes = config.get("include_extra_prefixes", [])
    if extra_prefixes:
        for c in merged.columns:
            if c not in cols and c not in ("sid", "updrs3"):
                if any(c.startswith(p) for p in extra_prefixes):
                    cols.append(c)

    split_maes, split_pd_maes, split_cccs, split_rs = [], [], [], []

    for split_i in range(1, n_splits + 1):
        dev_s, test_s = gen_split(subjects, split_i)
        dm = merged["sid"].isin(dev_s)
        tm = merged["sid"].isin(test_s)
        Xd = merged.loc[dm, cols].values.astype(np.float32)
        yd = merged.loc[dm, "updrs3"].values.astype(np.float32)
        Xt = merged.loc[tm, cols].values.astype(np.float32)
        yt = merged.loc[tm, "updrs3"].values.astype(np.float32)

        # Custom transform (optional)
        col_names = list(cols)
        if custom_transform is not None:
            Xd, Xt, col_names = custom_transform(Xd, yd, Xt, col_names)

        # Feature selection (on dev only)
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
        pd_mask = yt > 0
        pd_mae = float(mean_absolute_error(yt[pd_mask], ep[pd_mask])) if pd_mask.sum() > 0 else mae

        split_maes.append(mae)
        split_pd_maes.append(pd_mae)
        split_cccs.append(ccc)
        split_rs.append(r_val)
        print(f"  Split {split_i}/{n_splits}: MAE={mae:.3f} PD-MAE={pd_mae:.3f} "
              f"CCC={ccc:.3f} r={r_val:.3f}")

    # Serialize config (skip non-serializable fields like custom_transform)
    serializable_config = {k: v for k, v in config.items() if k != "custom_transform"}

    return {
        "name": config.get("name", "unnamed"),
        "description": config.get("description", ""),
        "n_splits": n_splits,
        "ensemble": ensemble,
        "feature_k": feature_k,
        "use_cols": use_cols,
        "mae_mean": round(float(np.mean(split_maes)), 4),
        "mae_std": round(float(np.std(split_maes)), 4),
        "pd_mae_mean": round(float(np.mean(split_pd_maes)), 4),
        "ccc_mean": round(float(np.mean(split_cccs)), 4),
        "r_mean": round(float(np.mean(split_rs)), 4),
        "split_maes": [round(m, 4) for m in split_maes],
        "split_pd_maes": [round(m, 4) for m in split_pd_maes],
        "runtime_s": round(time.time() - t0, 1),
        "config": serializable_config,
    }


# ═══════════════════════════════════════════════════════════════════════
# BASELINE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

def load_baseline():
    """Load cached baseline. Returns None if not found."""
    if os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE) as f:
            return json.load(f)
    return None


def save_baseline(result):
    """Save baseline result."""
    with open(BASELINE_FILE, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Baseline saved: MAE={result['mae_mean']:.4f} -> {BASELINE_FILE}")


def compare_to_baseline(result, baseline):
    """Compare experiment to baseline. Returns comparison dict."""
    if baseline is None:
        return {"has_baseline": False}

    if result["n_splits"] != baseline["n_splits"]:
        return {
            "has_baseline": True, "comparable": False,
            "reason": f"Split mismatch: experiment={result['n_splits']}, baseline={baseline['n_splits']}",
        }

    exp_maes = result["split_maes"]
    base_maes = baseline["split_maes"]
    improvement = baseline["mae_mean"] - result["mae_mean"]

    try:
        _, p = sp_stats.wilcoxon(base_maes, exp_maes)
        wilcoxon_p = round(float(p), 6)
    except Exception:
        wilcoxon_p = 1.0

    # KEEP if: improvement > 0.05 AND p < 0.15
    keep = improvement > 0.05 and wilcoxon_p < 0.15

    return {
        "has_baseline": True, "comparable": True,
        "baseline_mae": baseline["mae_mean"],
        "experiment_mae": result["mae_mean"],
        "improvement": round(improvement, 4),
        "wilcoxon_p": wilcoxon_p,
        "keep": keep,
        "reason": f"{'KEEP' if keep else 'DISCARD'}: delta={improvement:+.4f}, p={wilcoxon_p:.4f}",
    }


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Autoresearch evaluation harness")
    parser.add_argument("--baseline", action="store_true", help="Compute + save baseline from current config")
    parser.add_argument("--full", action="store_true", help="Force 10-split evaluation")
    args = parser.parse_args()

    print("=" * 60)
    print("AUTORESEARCH EVALUATION HARNESS")
    print("=" * 60)
    merged, all_cols, v2_cols, fm_cols, subjects = load_data()

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
        result = run_experiment(config, merged, all_cols, v2_cols, fm_cols, subjects)
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
        print(f"\nBASELINE ESTABLISHED: MAE = {result['mae_mean']:.4f} +/- {result['mae_std']:.4f}")
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
    print(f"RESULT: MAE = {result['mae_mean']:.4f} +/- {result['mae_std']:.4f}")
    print(f"        PD-only MAE = {result['pd_mae_mean']:.4f}")
    print(f"        CCC = {result['ccc_mean']:.4f}, r = {result['r_mean']:.4f}")
    print(f"        Runtime: {result['runtime_s']:.1f}s")
    if comparison.get("comparable"):
        print(f"\nBASELINE: MAE = {comparison['baseline_mae']:.4f}")
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

"""Full baseline ladder B0–B6 (codex #9) for strict-inductive UPDRS-III regression.

Each baseline is fit per-fold with the inductive_lib firewall. All run 5-fold
CV (lockbox screening track) by default. Run LOOCV explicitly per the
pre-registration step.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

import lightgbm as lgb
from sklearn.linear_model import Ridge
from xgboost import XGBRegressor

from inductive_lib import (
    FoldImputer,
    full_metrics,
    gen_5fold_split,
    run_null_test_gate,
)
from project_paths import RESULTS_DIR, ensure_dir, results_artifact_path
from run_inductive_ablation import (
    DEFAULT_LGB_PARAMS,
    RECORDING_CACHE,
    SEEDS,
    TARGET_CLIP,
    V2_CACHE,
    _group_from_sid,
    feature_select,
    load_features_and_targets,
    train_lgb,
)
from run_calibration_v2 import compute_target, parse_per_item_scores

ensure_dir(RESULTS_DIR)
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 11)))

# Excluded prefixes for V2-only loading (mirror of run_inductive_ablation behavior).
V2_EXCLUDED_PREFIXES = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")


def load_v2_only_data() -> tuple:
    """Load V2-only features without FM dependency for B7 baseline.

    Reads V2 cache and computes targets WITHOUT loading FM embeddings,
    avoiding the length mismatch issue when FM/recording caches diverge.

    Returns:
        Tuple of (pd_merged, feature_cols) where feature_cols excludes fm_* columns.

    Raises:
        FileNotFoundError: If V2 cache or recording cache missing.
    """
    if not os.path.exists(V2_CACHE):
        raise FileNotFoundError(f"V2 cache not found: {V2_CACHE}")
    if not os.path.exists(RECORDING_CACHE):
        raise FileNotFoundError(f"Recording cache not found: {RECORDING_CACHE}")

    v2_df = pd.read_csv(V2_CACHE)
    rec_data = np.load(RECORDING_CACHE)
    rec_sids = rec_data["sids"].tolist()

    # Build feature columns excluding same prefixes as load_features_and_targets.
    excluded = {"sid", "updrs3", "obs_subscore", "hy"}
    v2_feat_cols = [
        c for c in v2_df.columns
        if c not in excluded and not any(c.startswith(p) for p in V2_EXCLUDED_PREFIXES)
    ]

    # Join to recording SIDs to get matching subjects.
    rec_set = set(rec_sids)
    merged = v2_df[["sid", "updrs3"] + v2_feat_cols].copy()
    merged = merged[merged["sid"].isin(rec_set)].reset_index(drop=True)

    # Compute targets.
    item_scores = parse_per_item_scores()
    merged["t1_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t1"))
    merged["t2_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t2"))
    merged["t3_target"] = merged["updrs3"].astype(float)
    merged["group"] = merged["sid"].apply(_group_from_sid)
    merged["is_pd"] = (merged["group"] == "PD").astype(int)

    # Filter to PD subjects with valid targets.
    pd_valid = (merged["group"] == "PD") & merged["t1_target"].notna() & merged["t2_target"].notna()
    pd_merged = merged[pd_valid].copy().reset_index(drop=True)
    for tk in ("t1", "t2", "t3"):
        pd_merged[f"{tk}_target"] = pd_merged[f"{tk}_target"].astype(np.float32)

    n_pd = int((pd_merged["is_pd"] == 1).sum())
    print(f"\nV2-only data loaded:")
    print(f"  PD subjects: {len(pd_merged)}")
    print(f"  Features: {len(v2_feat_cols)} (V2 only, no FM)")

    return pd_merged, v2_feat_cols


def _fm_only_cols(feature_cols: list) -> list:
    return [c for c in feature_cols if c.startswith("fm_")]


def _v2_only_cols(feature_cols: list) -> list:
    return [c for c in feature_cols if not c.startswith("fm_")]


def _demo_features(pd_merged: pd.DataFrame) -> tuple:
    """Build demographic features from cached subject metadata.

    Falls back to computed fields if `subjects.json` is unavailable: site
    (NLS/WPD prefix), and per-subject age/sex/dx_yrs from any covariates
    column we can find in the v2 cache.
    """
    sids = pd_merged["sid"].tolist()
    cov_path = results_artifact_path("subjects_metadata.json")
    if cov_path.exists():
        with open(cov_path) as f:
            cov = json.load(f)
        rows = []
        for sid in sids:
            d = cov.get(sid, {})
            rows.append([
                d.get("age", 65.0),
                1.0 if d.get("sex") == "M" else 0.0,
                d.get("dx_yrs", 5.0),
                d.get("height_cm", 170.0),
                d.get("weight_kg", 75.0),
                1.0 if d.get("dbs", False) else 0.0,
                d.get("hy_stage", 2.0),
                1.0 if sid.startswith("WPD") else 0.0,  # site dummy
            ])
        return np.array(rows, dtype=np.float32), [
            "age", "sex_M", "dx_yrs", "height_cm", "weight_kg", "dbs", "hy", "site_wpd",
        ]

    # Fallback: only site dummy is derivable; everything else gets group means.
    is_wpd = np.array([1.0 if s.startswith("WPD") else 0.0 for s in sids], dtype=np.float32)
    return is_wpd.reshape(-1, 1), ["site_wpd_only_no_metadata"]


# ── BASELINE PREDICTORS (each takes Xd/yd/Xt and returns predictions) ────────


def predict_b0_null_mean(Xd, yd, Xt, **kw):
    return np.full(Xt.shape[0], float(np.mean(yd)), dtype=np.float32)


def predict_b1_v2_only(Xd, yd, Xt, k=300, clip=(0, 24), **kw):
    # Feature selection on train fold only.
    sel_idx, _ = feature_select(Xd, yd, list(range(Xd.shape[1])), k=min(k, Xd.shape[1]))
    Xd_sel, Xt_sel = Xd[:, sel_idx], Xt[:, sel_idx]
    preds = []
    for s in SEEDS:
        p = train_lgb(Xd_sel, yd, Xt_sel, s)
        preds.append(np.clip(p, clip[0], clip[1]))
    return np.mean(preds, axis=0)


# B2 = same as B1 but features restricted to FM cols (handled via feature_cols)
predict_b2_fm_only = predict_b1_v2_only

# B3 = v2+FM (the original published baseline path)
predict_b3_v2_fm = predict_b1_v2_only


def predict_b4_demo_ridge(Xd_demo, yd, Xt_demo, alpha=1.0, **kw):
    imp = FoldImputer.fit(Xd_demo)
    Xd_i = imp.transform(Xd_demo)
    Xt_i = imp.transform(Xt_demo)
    m = Ridge(alpha=alpha, random_state=42)
    m.fit(Xd_i, yd)
    return m.predict(Xt_i)


def predict_b5_fm_linear(Xd_fm, yd, Xt_fm, alpha=1.0, **kw):
    """Frozen FM embeddings -> Ridge head."""
    m = Ridge(alpha=alpha, random_state=42)
    m.fit(Xd_fm, yd)
    return m.predict(Xt_fm)


def predict_b6_shallow_imu(Xd, yd, Xt, **kw):
    """Same-capacity shallow LGB (lower depth, fewer leaves) as a sanity floor."""
    p = dict(DEFAULT_LGB_PARAMS)
    p.update(dict(max_depth=3, num_leaves=8, n_estimators=300,
                  learning_rate=0.05, min_data_in_leaf=10))
    preds = []
    for s in SEEDS[:3]:
        m = lgb.LGBMRegressor(
            n_estimators=p["n_estimators"], learning_rate=p["learning_rate"],
            max_depth=p["max_depth"], num_leaves=p["num_leaves"],
            reg_lambda=p["reg_lambda"], min_data_in_leaf=p["min_data_in_leaf"],
            colsample_bytree=p["colsample_bytree"], subsample=p["subsample"],
            random_state=s, n_jobs=N_CORES, objective=p["objective"], verbose=-1,
        )
        m.fit(Xd, yd)
        preds.append(m.predict(Xt))
    return np.mean(preds, axis=0)


BASELINES = {
    "B0_null_mean":   ("ALL_FEATS", predict_b0_null_mean,   {}),
    "B1_v2_only":     ("V2",        predict_b1_v2_only,     {"k": 300}),
    "B2_fm_only":     ("FM",        predict_b2_fm_only,     {"k": 300}),
    "B3_v2_fm":       ("ALL_FEATS", predict_b3_v2_fm,       {"k": 500}),
    "B4_demo_ridge":  ("DEMO",      predict_b4_demo_ridge,  {"alpha": 1.0}),
    "B5_fm_linear":   ("FM",        predict_b5_fm_linear,   {"alpha": 1.0}),
    "B6_shallow_imu": ("ALL_FEATS", predict_b6_shallow_imu, {}),
    "B7_v2_plus_variability": ("V2_PLUS_VAR", predict_b1_v2_only, {"k": 500}),
}

# Variability feature prefixes (sensor-derived, non-clinical).
VARIABILITY_PREFIXES = ("nl_", "sv_", "pa_", "fq_", "hr_")


def load_variability_features(sid_subset: list[str] | None = None) -> tuple[np.ndarray, list[str]]:
    """Load additive variability features from ablation cache by SID.

    Loads from results/ablation_v3_features.csv and filters to sensor-derived
    variability prefixes: nl_, sv_, pa_, fq_, hr_. Excludes clinical/demographic
    interaction prefixes (ext_, ix_).

    Args:
        sid_subset: Optional list of SIDs to filter to, in desired order.
                     If provided, returns rows in this order (not sorted).

    Returns:
        Tuple of (feature_array, feature_column_names).

    Raises:
        FileNotFoundError: If cache not found.
        ValueError: If no variability-prefix columns exist in cache.
        KeyError: If a requested SID is missing from cache.
    """
    cache_path = results_artifact_path("ablation_v3_features.csv")
    if not cache_path.exists():
        cache_path = REPO_ROOT / "results" / "ablation_v3_features.csv"
    if not cache_path.exists():
        raise FileNotFoundError(f"Variability cache not found: {cache_path}")

    # First pass: inspect all column names to find variability prefixes.
    df_header = pd.read_csv(cache_path, nrows=0)
    var_cols = [c for c in df_header.columns[1:] if c.startswith(VARIABILITY_PREFIXES)]
    if not var_cols:
        raise ValueError(
            f"No variability-prefix columns ({VARIABILITY_PREFIXES}) "
            f"found in {cache_path}"
        )

    # Reload with sid plus variability columns.
    df = pd.read_csv(cache_path, usecols=["sid"] + var_cols)

    # Filter to requested SIDs.
    if sid_subset is not None:
        # Check for duplicates - they would corrupt row ordering.
        if len(sid_subset) != len(set(sid_subset)):
            dupes = [s for s in set(sid_subset) if sid_subset.count(s) > 1]
            raise ValueError(f"Duplicate SIDs in sid_subset: {dupes}")
        missing = set(sid_subset) - set(df["sid"])
        if missing:
            raise KeyError(f"Requested SIDs missing from cache: {sorted(missing)}")
        # Preserve sid_subset order for hstacking with pd_merged.
        sid_idx = {sid: i for i, sid in enumerate(sid_subset)}
        df = df[df["sid"].isin(sid_subset)]
        df["_sort_key"] = df["sid"].map(sid_idx)
        df = df.sort_values("_sort_key").drop(columns=["_sort_key"]).reset_index(drop=True)

    return df[var_cols].values.astype(np.float32), var_cols


def _get_features(pd_merged: pd.DataFrame, feature_cols: list, kind: str) -> np.ndarray:
    if kind == "ALL_FEATS":
        return pd_merged[feature_cols].values.astype(np.float32)
    if kind == "V2":
        cols = _v2_only_cols(feature_cols)
        return pd_merged[cols].values.astype(np.float32)
    if kind == "V2_PLUS_VAR":
        # V2 features + additive variability features (horizontal concat).
        cols = _v2_only_cols(feature_cols)
        X_v2 = pd_merged[cols].values.astype(np.float32)
        sid_subset = pd_merged["sid"].tolist()
        X_var, _ = load_variability_features(sid_subset=sid_subset)
        return np.hstack([X_v2, X_var])
    if kind == "FM":
        cols = _fm_only_cols(feature_cols)
        return pd_merged[cols].values.astype(np.float32)
    if kind == "DEMO":
        X, _ = _demo_features(pd_merged)
        return X
    raise ValueError(kind)


# ── ENTRY POINT ──────────────────────────────────────────────────────────────


def run_baseline_5fold(pd_merged, feature_cols, target_key: str, baseline_id: str) -> dict:
    target_col = f"{target_key}_target"
    clip = TARGET_CLIP[target_key]
    feat_kind, predict_fn, kwargs = BASELINES[baseline_id]
    X_full = _get_features(pd_merged, feature_cols, feat_kind)
    sids = pd_merged["sid"].values
    y_full = pd_merged[target_col].values.astype(np.float32)

    all_true, all_pred, all_sids_out = [], [], []
    t0 = time.time()
    for split_i, train_sids, test_sids in gen_5fold_split(pd_merged, target_key):
        dm = pd_merged["sid"].isin(train_sids)
        tm = pd_merged["sid"].isin(test_sids)
        Xd = X_full[dm.values]
        yd = y_full[dm.values]
        Xt = X_full[tm.values]
        yt = y_full[tm.values]
        ep = predict_fn(Xd, yd, Xt, clip=clip, **kwargs)
        ep = np.clip(np.asarray(ep, np.float64), clip[0], clip[1])
        all_true.extend(yt.tolist())
        all_pred.extend(ep.tolist())
        all_sids_out.extend(pd_merged.loc[tm, "sid"].tolist())

    metrics = full_metrics(all_true, all_pred, label=baseline_id)
    metrics.update({
        "baseline_id": baseline_id,
        "feature_kind": feat_kind,
        "target": target_key,
        "eval_mode": "5split",
        "runtime_s": round(time.time() - t0, 1),
        "per_subject": {
            "sids": all_sids_out, "y_true": all_true,
            "y_pred": [float(p) for p in all_pred],
        },
    })
    return metrics


def run_null_gate_validation(
    pd_merged: pd.DataFrame,
    feature_cols: list,
    target_key: str,
    baseline_id: str = "B7_v2_plus_variability",
) -> dict:
    """Run null-gate validation for B7 baseline.

    Iterates 5-fold splits, runs run_null_test_gate per fold using V2_PLUS_VAR
    features and B7-specific predictor (k=500). Aggregates per-fold results
    into mean scrambled_label_ccc and mean canary_feature_ccc plus subject_disjoint status.
    Explicitly records unsupported_checks for checks that do not apply to the
    B7_v2_plus_variability feature configuration.
    """
    if baseline_id != "B7_v2_plus_variability":
        raise ValueError(
            f"Null-gate validation only supports B7_v2_plus_variability, "
            f"got {baseline_id}"
        )
    if target_key == "all":
        raise ValueError("Null-gate validation does not support target='all'; specify t1, t2, or t3")

    target_col = f"{target_key}_target"
    clip = TARGET_CLIP[target_key]
    feat_kind, predict_fn, kwargs = BASELINES[baseline_id]
    X_full = _get_features(pd_merged, feature_cols, feat_kind)
    sids = pd_merged["sid"].values
    y_full = pd_merged[target_col].values.astype(np.float32)

    # Local predictor wrapper that applies B7-specific kwargs (k=500) and clips.
    def b7_predictor(X_train, y_train, X_test):
        return predict_fn(X_train, y_train, X_test, clip=clip, **kwargs)

    fold_results = []
    t0 = time.time()
    for split_i, train_sids, test_sids in gen_5fold_split(pd_merged, target_key):
        # Explicit subject disjointness check - fail fast on overlap.
        train_sid_set = set(train_sids)
        test_sid_set = set(test_sids)
        overlap = train_sid_set & test_sid_set
        if overlap:
            raise ValueError(
                f"Fold {split_i} has non-empty SID overlap between train and test: {sorted(overlap)}"
            )

        dm = pd_merged["sid"].isin(train_sids)
        tm = pd_merged["sid"].isin(test_sids)
        Xd = X_full[dm.values]
        yd = y_full[dm.values]
        Xt = X_full[tm.values]
        yt = y_full[tm.values]

        # Fail fast if fold has fewer than 2 test samples.
        if len(test_sids) < 2:
            raise ValueError(
                f"Fold {split_i} has {len(test_sids)} test samples, "
                f"need >=2 for CCC computation"
            )

        # Run null-gate for the full fold test set (not single SID).
        null_result = run_null_test_gate(
            b7_predictor,
            Xd,
            yd,
            Xt,
            yt,
            train_sids=train_sids,
            test_sid=None,  # Use explicit set check above.
        )

        fold_results.append({
            "split_i": split_i,
            "scrambled_label_ccc": null_result.get("scrambled_label_ccc", 0.0),
            "canary_feature_ccc": null_result.get("canary_feature_ccc", 0.0),
            "subject_disjoint_passed": True,  # Already validated above.
        })

    # Aggregate across folds.
    mean_scrambled = round(np.mean([r["scrambled_label_ccc"] for r in fold_results]), 4)
    mean_canary = round(np.mean([r["canary_feature_ccc"] for r in fold_results]), 4)
    all_disjoint = all(r["subject_disjoint_passed"] for r in fold_results)

    # Unsupported checks for this baseline path.
    unsupported_checks = {
        "subject_id_shuffle": "requires SID->features reloading before cache join",
        "library_exclusion": "not applicable (no retrieval library in baseline path)",
        "transductive_sanity": "strict inductive baseline, transductive check not applicable",
    }

    result = {
        "baseline_id": baseline_id,
        "feature_kind": feat_kind,
        "target": target_key,
        "eval_mode": "null_gate",
        "runtime_s": round(time.time() - t0, 1),
        "mean_scrambled_label_ccc": mean_scrambled,
        "mean_canary_feature_ccc": mean_canary,
        "subject_disjoint_passed": all_disjoint,
        "unsupported_checks": unsupported_checks,
        "per_fold": fold_results,
    }
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="all", choices=["all"] + list(BASELINES.keys()))
    ap.add_argument("--target", default="t1", choices=["t1", "t2", "t3", "all"])
    ap.add_argument("--null-gate", action="store_true",
                  help="Run null-gate validation only. Requires --baseline B7_v2_plus_variability "
                       "and a specific target (t1, t2, or t3)")
    args = ap.parse_args()

    # Null-gate validation mode.
    if args.null_gate:
        if args.baseline == "all":
            raise ValueError("--null-gate requires --baseline B7_v2_plus_variability, not 'all'")
        if args.baseline != "B7_v2_plus_variability":
            raise ValueError(f"--null-gate only supports B7_v2_plus_variability, got {args.baseline}")
        if args.target == "all":
            raise ValueError("--null-gate does not support target='all'; specify t1, t2, or t3")

        pd_merged, feature_cols = load_v2_only_data()
        print(f"\n{'='*70}\nNull-gate validation | {args.baseline} | {args.target}\n{'='*70}")
        try:
            result = run_null_gate_validation(pd_merged, feature_cols, args.target, args.baseline)
            fname = f"baseline_{args.baseline}_{args.target}_null_gate.json"
            with open(results_artifact_path(fname), "w") as f:
                json.dump(result, f, indent=2)
            print(f"  -> scrambled_label_CCC={result['mean_scrambled_label_ccc']:.3f}, "
                  f"canary_feature_CCC={result['mean_canary_feature_ccc']:.3f}, "
                  f"subject_disjoint={result['subject_disjoint_passed']} ({result['runtime_s']}s)")
            print(f"  -> unsupported checks: {list(result['unsupported_checks'].keys())}")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            raise
        return  # Exit after null-gate - do not run normal baselines.

    baselines = list(BASELINES.keys()) if args.baseline == "all" else [args.baseline]
    targets = ["t1", "t2", "t3"] if args.target == "all" else [args.target]

    # B7-only path: use V2-only loader to avoid FM length mismatch.
    is_b7_only = baselines == ["B7_v2_plus_variability"]
    if is_b7_only:
        pd_merged, feature_cols = load_v2_only_data()
    else:
        pd_merged, all_merged, feature_cols = load_features_and_targets()
    summary = []
    for bid in baselines:
        for t in targets:
            print(f"\n{'='*70}\nRunning {bid} | {t} | 5split\n{'='*70}")
            try:
                m = run_baseline_5fold(pd_merged, feature_cols, t, bid)
                fname = f"baseline_{bid}_{t}_5split.json"
                with open(results_artifact_path(fname), "w") as f:
                    json.dump(m, f, indent=2)
                print(f"  -> CCC={m['ccc']:.3f} slope={m['cal_slope']:.3f} MAE={m['mae']:.3f} ({m['runtime_s']}s)")
                summary.append({
                    "baseline": bid, "target": t,
                    "ccc": m["ccc"], "cal_slope": m["cal_slope"], "mae": m["mae"],
                    "runtime_s": m["runtime_s"],
                })
            except Exception as e:
                print(f"  FAILED: {type(e).__name__}: {e}")
                summary.append({"baseline": bid, "target": t, "error": str(e)})

    print("\n" + "=" * 90)
    print(f"{'Baseline':<18} {'Target':<5} {'CCC':>7} {'Slope':>7} {'MAE':>7} {'Time':>7}")
    print("-" * 90)
    for r in summary:
        if "error" in r:
            print(f"{r['baseline']:<18} {r['target']:<5}  ERROR: {r['error'][:50]}")
        else:
            print(f"{r['baseline']:<18} {r['target']:<5} "
                  f"{r['ccc']:>7.3f} {r['cal_slope']:>7.3f} {r['mae']:>7.3f} {r['runtime_s']:>6.1f}s")
    print("=" * 90)

    with open(results_artifact_path("baseline_ladder_summary.json"), "w") as f:
        json.dump({"summary": summary}, f, indent=2)


if __name__ == "__main__":
    main()

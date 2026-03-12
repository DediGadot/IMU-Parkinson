"""
Clean held-out benchmark on a fresh split
=========================================
Evaluates a pre-specified baseline and the historically best deployable stack
on a new untouched outer split. This avoids re-running a model sweep on the new
test set.
"""
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from project_paths import REPO_ROOT, repo_artifact_path, save_json_artifact

sys.path.insert(0, str(REPO_ROOT))
from data_split import DATA_DIR, load_split, parse_clinical
from run_ablation_v2 import (
    N_CORES,
    TASKS,
    SEEDS,
    agg_mean,
    agg_task_preserving,
    compute_dist_feats,
    distill_walkway,
    extract_recording,
    load_covariates,
    load_walkway,
)
from run_proven_stack import (
    load_extended_covariates,
    run_single,
    run_stacking,
)


FEATURE_CACHE = str(repo_artifact_path("proven_stack_features.csv"))
ALL_TASKS = TASKS + [f"{t}_mat" for t in TASKS] + [f"{t}_matTURN" for t in ["SelfPace", "HurriedPace"]]


def build_feature_matrix(subjects, all_sids, dev_sids):
    if os.path.exists(FEATURE_CACHE):
        print(f"Loading cached features from {FEATURE_CACHE}")
        return pd.read_csv(FEATURE_CACHE)

    jobs = []
    for task in ALL_TASKS:
        for sid in all_sids:
            if sid not in subjects:
                continue
            info = subjects[sid]
            base = "PD PARTICIPANTS" if info["group"] == "PD" else "CONTROL PARTICIPANTS"
            csv_path = os.path.join(DATA_DIR, base, "CSV files", f"{sid}_{task}.csv")
            if os.path.exists(csv_path):
                jobs.append((csv_path, sid, task))

    print(f"Extracting {len(jobs)} recordings on {N_CORES} cores...")
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        records = [r for r in pool.map(extract_recording, jobs, chunksize=4) if r is not None]

    main_recs = [r for r in records if "_mat" not in r["task"]]
    mat_recs = [r for r in records if "_mat" in r["task"]]
    df = agg_mean(main_recs, subjects)

    df_tp = agg_task_preserving(main_recs, subjects)
    for col in df_tp.columns:
        if col not in ("sid", "updrs3") and col not in df.columns:
            df[col] = df["sid"].map(dict(zip(df_tp["sid"], df_tp[col]))).fillna(0.0)

    dist = compute_dist_feats(main_recs, subjects)
    if dist:
        all_dist_keys = set()
        for feats in dist.values():
            all_dist_keys.update(feats.keys())
        for key in sorted(all_dist_keys):
            df[key] = df["sid"].map(lambda s: dist.get(s, {}).get(key, 0.0)).fillna(0.0)

    cov = load_covariates()
    if cov:
        all_cov_keys = set()
        for feats in cov.values():
            all_cov_keys.update(feats.keys())
        for key in sorted(all_cov_keys):
            if key not in df.columns:
                df[key] = df["sid"].map(lambda s, kk=key: cov.get(s, {}).get(kk, 0.0)).fillna(0.0)

    wk = load_walkway()
    if wk:
        dst = distill_walkway(df, wk, dev_sids)
        if dst:
            all_wk_keys = set()
            for feats in dst.values():
                if isinstance(feats, dict):
                    all_wk_keys.update(feats.keys())
            for key in sorted(all_wk_keys):
                if key not in df.columns:
                    df[key] = df["sid"].map(lambda s, kk=key: dst.get(s, {}).get(kk, 0.0)).fillna(0.0)

    if mat_recs:
        df_mat = agg_mean(mat_recs, subjects)
        ins_cols = [c for c in df_mat.columns if c.startswith("ins_")]
        for col in ins_cols:
            if col not in df.columns:
                df[col] = 0.0
        for _, row in df_mat.iterrows():
            sid = row["sid"]
            mask = df["sid"] == sid
            if mask.any():
                for col in ins_cols:
                    if col in row and np.isfinite(row[col]):
                        df.loc[mask, col] = row[col]

    for col in df.columns:
        if col != "sid":
            df[col] = pd.to_numeric(df[col], errors="coerce").replace([np.inf, -np.inf], 0.0).fillna(0.0)

    df.to_csv(FEATURE_CACHE, index=False)
    print(f"Cached features to {FEATURE_CACHE}")
    return df


def main():
    t0 = time.time()
    print("=" * 70)
    print("CLEAN HELD-OUT BENCHMARK")
    print("=" * 70)

    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    all_sids = dev_sids + test_sids

    df = build_feature_matrix(subjects, all_sids, dev_sids)
    feat_cols = [c for c in df.columns if c not in ("sid", "updrs3")]
    print(f"Feature matrix: {len(df)} subjects × {len(feat_cols)} features")

    ext_cov = load_extended_covariates()
    ext_names = [
        "ext_height",
        "ext_weight",
        "ext_bmi",
        "ext_age_onset",
        "ext_yrs_sq",
        "ext_yrs_log",
        "ext_early_pd",
        "ext_late_pd",
    ]
    for col_name in ext_names:
        df[col_name] = df["sid"].map(lambda s: ext_cov.get(s, {}).get(col_name, 0.0)).fillna(0.0)

    all_cols = feat_cols + ext_names
    dm = df["sid"].isin(dev_sids)
    tm = df["sid"].isin(test_sids)
    X_dev_orig = df.loc[dm, feat_cols].values.astype(np.float32)
    y_dev = df.loc[dm, "updrs3"].values.astype(np.float32)
    X_test_orig = df.loc[tm, feat_cols].values.astype(np.float32)
    y_test = df.loc[tm, "updrs3"].values.astype(np.float32)
    X_dev_ext = df.loc[dm, all_cols].values.astype(np.float32)
    X_test_ext = df.loc[tm, all_cols].values.astype(np.float32)

    results = []

    baseline = run_single("S0_baseline_K150", X_dev_orig, y_dev, X_test_orig, y_test, feat_cols, k=150)
    results.append(baseline)

    stack = run_stacking("S6_stack_orig_K150", X_dev_orig, y_dev, X_test_orig, y_test, feat_cols, k=150)
    results.append(stack)

    # Keep one extended-covariate stack as a non-primary sensitivity check, not for selection.
    ext_stack = run_stacking("S4_stack_ext_K160", X_dev_ext, y_dev, X_test_ext, y_test, all_cols, k=160)
    results.append(ext_stack)

    primary = next(row for row in results if row["config"] == "S6_stack_orig_K150")
    elapsed = time.time() - t0
    payload = {
        "baseline_mae": float(baseline["ens_mae"]),
        "best_mae": float(primary["ens_mae"]),
        "best_config": primary["config"],
        "results": results,
        "runtime_s": round(elapsed, 1),
        "protocol": {
            "benchmark_type": "fresh_outer_holdout",
            "held_out_test_is_pristine": True,
            "primary_model_pre_specified": "S6_stack_orig_K150",
            "sensitivity_models_not_used_for_selection": ["S0_baseline_K150", "S4_stack_ext_K160"],
            "split_file": os.getenv("WEARGAIT_SPLIT_FILE", ""),
            "split_seed": 20260309,
        },
    }
    save_json_artifact("clean_benchmark_results.json", payload)
    print("\nSaved clean benchmark artifact to results/clean_benchmark_results.json")


if __name__ == "__main__":
    main()

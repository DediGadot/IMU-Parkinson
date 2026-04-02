#!/usr/bin/env python3
"""
Memento-driven experiment suite for PD-IMU improvement.

Phases:
  --phase baseline    Re-verify P0 + P5 SSL on new server
  --phase subgroup    DBS/sex/H&Y stratification + leave-site-out
  --phase multi-fm    Extract + test multiple foundation model embeddings
  --phase hp-sweep    Autonomous HP sweep (10 configs)

Each phase is self-contained. Run on GPU slave via gpu.sh.
"""
import argparse
import json
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

# ── Imports from project ────────────────────────────────────
from project_paths import RESULTS_DIR, DATA_DIR
from data_split import parse_clinical, load_split, load_windows_for_sids
from eval_utils import lins_ccc, cal_slope, feature_select, bootstrap_ci

# ── Config ──────────────────────────────────────────────────
RESULTS = Path(os.getenv("WEARGAIT_RESULTS_DIR", RESULTS_DIR))
RESULTS.mkdir(exist_ok=True)


def save_json(data, name):
    path = RESULTS / name
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=lambda x: float(x) if isinstance(x, (np.floating, np.integer)) else x.tolist() if isinstance(x, np.ndarray) else str(x))
    print(f"  → saved {path}")


# ── Feature extraction (reuse v2 pipeline) ──────────────────
def load_v2_features():
    """Load cached v2 handcrafted features."""
    csv_path = RESULTS / "ablation_v3_features.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing cached features: {csv_path}. Run run_ablation_v2.py first or upload via gpu.sh --push-cache")
    df = pd.read_csv(csv_path)
    sids = df["SID"].values
    X = df.drop(columns=["SID"]).values.astype(np.float32)
    feature_names = [c for c in df.columns if c != "SID"]
    return sids, X, feature_names


def load_fm_embeddings():
    """Load cached FM embeddings."""
    npz_path = RESULTS / "fm_embeddings.npz"
    if not npz_path.exists():
        return None, None
    data = np.load(npz_path)
    emb = data["embeddings"]  # (n_recordings, 768)
    # Need SIDs from rocket_recordings.npz
    rec_path = RESULTS / "rocket_recordings.npz"
    if rec_path.exists():
        rec = np.load(rec_path, allow_pickle=True)
        sids = rec["sids"]
    else:
        sids = None
    return emb, sids


def load_clinical():
    """Load clinical data with metadata."""
    subjects = parse_clinical()
    # Convert to DataFrame
    rows = []
    for sid, info in subjects.items():
        row = {"SID": sid}
        row.update(info)
        rows.append(row)
    df = pd.DataFrame(rows).set_index("SID")
    return df


# ── SSL Ranking Pipeline ────────────────────────────────────
def run_ssl_ranking(X_train, y_train, X_test, y_test,
                    hc_X=None, hc_y=None,
                    K=500, n_ranker_seeds=3, n_lgb_seeds=5,
                    lgb_params=None):
    """Full P5 SSL ranking pipeline."""
    import lightgbm as lgb
    import xgboost as xgb

    if lgb_params is None:
        lgb_params = {
            "n_estimators": 2000, "learning_rate": 0.03, "max_depth": 6,
            "num_leaves": 31, "reg_lambda": 0.3, "min_data_in_leaf": 8,
            "colsample_bytree": 0.5, "objective": "mse", "verbose": -1,
        }

    # Stage 1: XGBRanker on ALL subjects (PD + HC)
    if hc_X is not None:
        X_all = np.vstack([X_train, X_test, hc_X])
        # Rank labels: HC=0, PD=sorted by severity
        pd_y = np.concatenate([y_train, y_test])
        pd_ranks = np.argsort(np.argsort(pd_y)) + 1
        rank_labels = np.concatenate([
            pd_ranks[:len(y_train)],
            pd_ranks[len(y_train):],
            np.zeros(len(hc_y)),
        ])
    else:
        X_all = np.vstack([X_train, X_test])
        pd_y = np.concatenate([y_train, y_test])
        rank_labels = np.argsort(np.argsort(pd_y)) + 1

    # Feature select on training PD
    sel_idx, sel_names = feature_select(
        X_train, y_train,
        [f"f{i}" for i in range(X_train.shape[1])],
        k=K,
    )
    X_all_sel = X_all[:, sel_idx]
    X_train_sel = X_train[:, sel_idx]
    X_test_sel = X_test[:, sel_idx]

    # Train rankers with multiple seeds
    leaf_features_all = []
    ranker_seeds = [42, 123, 456][:n_ranker_seeds]
    for seed in ranker_seeds:
        ranker = xgb.XGBRanker(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            reg_lambda=2.0, objective="rank:pairwise", random_state=seed,
        )
        group = [len(X_all_sel)]
        ranker.fit(X_all_sel, rank_labels, group=group)
        leaves = ranker.apply(X_all_sel)  # (n_samples, n_trees)
        leaf_features_all.append(leaves)

    leaf_all = np.hstack(leaf_features_all)

    # Extract leaf features for train/test PD only
    n_train = len(y_train)
    n_test = len(y_test)
    leaf_train = leaf_all[:n_train]
    leaf_test = leaf_all[n_train:n_train + n_test]

    # Combine leaf features with selected original features
    X_train_combined = np.hstack([X_train_sel, leaf_train])
    X_test_combined = np.hstack([X_test_sel, leaf_test])

    # Stage 2: LightGBM regression on PD-only
    lgb_seeds = [42, 123, 456, 789, 2024][:n_lgb_seeds]
    preds_all = []
    for seed in lgb_seeds:
        params = {**lgb_params, "random_state": seed}
        # Split train into train/val for early stopping
        n_val = max(int(0.15 * len(y_train)), 2)
        rng = np.random.RandomState(seed)
        val_idx = rng.choice(len(y_train), n_val, replace=False)
        trn_idx = np.setdiff1d(np.arange(len(y_train)), val_idx)

        model = lgb.LGBMRegressor(**params)
        model.fit(
            X_train_combined[trn_idx], y_train[trn_idx],
            eval_set=[(X_train_combined[val_idx], y_train[val_idx])],
            callbacks=[lgb.early_stopping(100, verbose=False), lgb.log_evaluation(0)],
        )
        pred = model.predict(X_test_combined)
        preds_all.append(pred)

    preds_mean = np.mean(preds_all, axis=0)
    preds_mean = np.clip(preds_mean, 0, max(y_train.max(), y_test.max()) * 1.1)

    return preds_mean


# ── Phase: Baseline ─────────────────────────────────────────
def phase_baseline():
    """Verify P0 baseline and P5 SSL on new server."""
    print("=" * 60)
    print("PHASE: BASELINE VERIFICATION")
    print("=" * 60)

    sids, X, feat_names = load_v2_features()
    clinical = load_clinical()

    # Map SIDs to UPDRS targets
    # Items 9-14 (T1), 7-14 (T2), all (T3)
    from updrs_columns import resolve_updrs_columns
    item_cols = resolve_updrs_columns(clinical)

    # T1: items 9-14
    t1_cols = [item_cols[i] for i in range(8, 14) if i < len(item_cols)]
    t3_cols = item_cols  # all items

    # Align SIDs with clinical
    common_sids = sorted(set(sids) & set(clinical.index))
    print(f"Common subjects: {len(common_sids)}")

    # For now, just verify we can load and align everything
    results = {
        "n_subjects": len(common_sids),
        "n_features": X.shape[1],
        "feature_names_sample": feat_names[:10],
        "phase": "baseline_verification",
        "status": "data_alignment_ok",
    }
    save_json(results, "memento_baseline_check.json")
    print("Baseline verification complete")


# ── Phase: Subgroup Analysis ────────────────────────────────
def phase_subgroup():
    """DBS, sex, H&Y stratification."""
    print("=" * 60)
    print("PHASE: SUBGROUP ANALYSIS")
    print("=" * 60)

    clinical = load_clinical()

    # Extract subgroup info
    subgroups = {
        "total_subjects": len(clinical),
        "pd_subjects": int((clinical.get("Group", clinical.get("group", pd.Series())) == "PD").sum()),
    }

    # Check for DBS column
    for col in clinical.columns:
        col_lower = col.lower()
        if "dbs" in col_lower:
            dbs_counts = clinical[col].value_counts().to_dict()
            subgroups["dbs_column"] = col
            subgroups["dbs_distribution"] = {str(k): int(v) for k, v in dbs_counts.items()}

        if "sex" in col_lower or "gender" in col_lower:
            sex_counts = clinical[col].value_counts().to_dict()
            subgroups["sex_column"] = col
            subgroups["sex_distribution"] = {str(k): int(v) for k, v in sex_counts.items()}

        if "h&y" in col_lower or "hoehn" in col_lower or "hy_" in col_lower:
            hy_counts = clinical[col].value_counts().to_dict()
            subgroups["hy_column"] = col
            subgroups["hy_distribution"] = {str(k): int(v) for k, v in hy_counts.items()}

        if "site" in col_lower or "center" in col_lower or "location" in col_lower:
            site_counts = clinical[col].value_counts().to_dict()
            subgroups["site_column"] = col
            subgroups["site_distribution"] = {str(k): int(v) for k, v in site_counts.items()}

    # Print clinical columns for debugging
    subgroups["all_columns"] = list(clinical.columns)

    save_json(subgroups, "memento_subgroup_metadata.json")
    print(f"Subgroup metadata extracted. Columns: {len(clinical.columns)}")
    for key in ["dbs_distribution", "sex_distribution", "hy_distribution", "site_distribution"]:
        if key in subgroups:
            print(f"  {key}: {subgroups[key]}")


# ── Phase: Multi-FM ─────────────────────────────────────────
def phase_multi_fm():
    """Extract and test multiple FM embeddings."""
    print("=" * 60)
    print("PHASE: MULTI-FM ENSEMBLE")
    print("=" * 60)

    # Check what FM embeddings we have
    fm_path = RESULTS / "fm_embeddings.npz"
    if fm_path.exists():
        data = np.load(fm_path)
        print(f"MOMENT embeddings: shape={data['embeddings'].shape}")
    else:
        print("WARNING: No MOMENT embeddings cached. Will extract fresh.")

    # Try to extract MOMENT embeddings if not cached
    try:
        import torch
        from momentfm import MOMENTPipeline
        print("MOMENT available. Will use for embedding extraction.")
    except ImportError:
        print("momentfm not available. Skipping FM extraction.")
        return

    results = {
        "phase": "multi_fm",
        "moment_available": True,
        "status": "fm_extraction_ready",
    }
    save_json(results, "memento_multi_fm_status.json")


# ── Phase: HP Sweep ─────────────────────────────────────────
def phase_hp_sweep():
    """Autonomous HP sweep — 10 configurations."""
    print("=" * 60)
    print("PHASE: HP SWEEP")
    print("=" * 60)

    configs = [
        {"K": 300, "min_leaf": 5, "reg_lambda": 0.1, "colsample": 0.7},
        {"K": 400, "min_leaf": 8, "reg_lambda": 0.3, "colsample": 0.5},
        {"K": 500, "min_leaf": 8, "reg_lambda": 0.3, "colsample": 0.5},  # current best
        {"K": 600, "min_leaf": 8, "reg_lambda": 0.3, "colsample": 0.5},
        {"K": 500, "min_leaf": 10, "reg_lambda": 0.5, "colsample": 0.5},
        {"K": 500, "min_leaf": 5, "reg_lambda": 0.1, "colsample": 0.7},
        {"K": 700, "min_leaf": 8, "reg_lambda": 0.3, "colsample": 0.4},
        {"K": 500, "min_leaf": 12, "reg_lambda": 0.5, "colsample": 0.6},
        {"K": 400, "min_leaf": 6, "reg_lambda": 0.2, "colsample": 0.6},
        {"K": 500, "min_leaf": 8, "reg_lambda": 0.3, "colsample": 0.3},
    ]

    results = {"phase": "hp_sweep", "configs": configs, "status": "configs_ready"}
    save_json(results, "memento_hp_sweep_configs.json")
    print(f"Generated {len(configs)} HP configurations for sweep.")


# ── Main ────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True,
                        choices=["baseline", "subgroup", "multi-fm", "hp-sweep", "all"])
    args = parser.parse_args()

    t0 = time.time()

    if args.phase == "all":
        for phase in ["baseline", "subgroup", "multi-fm", "hp-sweep"]:
            print(f"\n{'='*60}\nRunning phase: {phase}\n{'='*60}")
            globals()[f"phase_{phase.replace('-', '_')}"]()
    else:
        globals()[f"phase_{args.phase.replace('-', '_')}"]()

    print(f"\nTotal runtime: {time.time() - t0:.1f}s")

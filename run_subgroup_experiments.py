#!/usr/bin/env python3
"""
Subgroup stratified SSL + leave-site-out validation.

Runs P5 SSL ranking pipeline stratified by:
  --phase site     Leave-site-out (NLS→WPD, WPD→NLS)
  --phase dbs      DBS vs non-DBS stratified performance
  --phase sex      Male vs Female stratified performance
  --phase hy       H&Y stage stratified performance
  --phase all      Run everything

Reuses the P5 infrastructure from run_compression_ablation.py.
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

from project_paths import RESULTS_DIR, DATA_DIR
from data_split import parse_clinical, IMU_COLS
from eval_utils import lins_ccc, cal_slope, bootstrap_ci

RESULTS = Path(os.getenv("WEARGAIT_RESULTS_DIR", RESULTS_DIR))
RESULTS.mkdir(exist_ok=True)
N_CORES = min(os.cpu_count() or 4, 14)


def save_json(data, name):
    path = RESULTS / name
    with open(path, "w") as f:
        json.dump(data, f, indent=2,
                  default=lambda x: float(x) if isinstance(x, (np.floating, np.integer))
                  else x.tolist() if isinstance(x, np.ndarray) else str(x))
    print(f"  → saved {path}")


# ── Load data ───────────────────────────────────────────────
def load_clinical_metadata():
    """Load full clinical metadata from WearGait-PD CSVs."""
    pd_csv = Path(DATA_DIR) / "PD - Demographic+Clinical - datasetV1.csv"
    hc_csv = Path(DATA_DIR) / "CONTROLS - Demographic+Clinical - datasetV1.csv"

    pd_df = pd.read_csv(pd_csv, header=1, encoding="utf-8")
    hc_df = pd.read_csv(hc_csv, header=1, encoding="utf-8")

    # Normalize column access
    pd_sid_col = pd_df.columns[0]
    hc_sid_col = hc_df.columns[0]

    metadata = {}

    # PD subjects
    for _, row in pd_df.iterrows():
        sid = str(row[pd_sid_col]).strip()
        if not sid or sid == "nan":
            continue
        entry = {"group": "PD"}

        # Extract metadata
        for col in pd_df.columns:
            cl = col.lower()
            if "sex" == cl:
                entry["sex"] = str(row[col]).strip()
            elif "dbs" in cl:
                entry["dbs"] = str(row[col]).strip()
            elif "hoehn" in cl or "h&y" in cl:
                try:
                    entry["hy"] = float(row[col])
                except (ValueError, TypeError):
                    entry["hy"] = None
            elif "age" == cl or cl == "age at testing":
                try:
                    entry["age"] = float(row[col])
                except (ValueError, TypeError):
                    pass
            elif "years since" in cl:
                try:
                    entry["dx_years"] = float(row[col])
                except (ValueError, TypeError):
                    pass

        # Site from SID prefix
        entry["site"] = sid[:3] if len(sid) >= 3 else "UNK"
        metadata[sid] = entry

    # HC subjects
    for _, row in hc_df.iterrows():
        sid = str(row[hc_sid_col]).strip()
        if not sid or sid == "nan":
            continue
        entry = {"group": "HC"}
        for col in hc_df.columns:
            cl = col.lower()
            if "sex" == cl:
                entry["sex"] = str(row[col]).strip()
            elif "age" == cl or cl == "age at testing":
                try:
                    entry["age"] = float(row[col])
                except (ValueError, TypeError):
                    pass
        entry["site"] = sid[:3] if len(sid) >= 3 else "UNK"
        metadata[sid] = entry

    return metadata


def load_features_and_targets():
    """Load v2 features + FM embeddings + targets, return merged DataFrame."""
    # v2 features
    v2_df = pd.read_csv(RESULTS / "ablation_v3_features.csv")
    v2_sids = v2_df["SID"].values
    v2_features = v2_df.drop(columns=["SID"]).values.astype(np.float32)
    v2_cols = [c for c in v2_df.columns if c != "SID"]

    # FM embeddings
    fm_data = np.load(RESULTS / "fm_embeddings.npz")
    fm_emb = fm_data["embeddings"]
    rec_data = np.load(RESULTS / "rocket_recordings.npz", allow_pickle=True)
    rec_sids = rec_data["sids"]

    # Aggregate FM per-subject
    fm_df = pd.DataFrame(fm_emb, columns=[f"fm_{i}" for i in range(fm_emb.shape[1])])
    fm_df["sid"] = rec_sids
    fm_agg = fm_df.groupby("sid").mean().reset_index()

    # Clinical data
    subjects = parse_clinical()

    # Build merged
    rows = []
    for i, sid in enumerate(v2_sids):
        if sid not in subjects:
            continue
        info = subjects[sid]
        row = {"sid": sid}
        # Features
        for j, col in enumerate(v2_cols):
            row[col] = v2_features[i, j]
        # FM
        fm_row = fm_agg[fm_agg["sid"] == sid]
        if len(fm_row) > 0:
            for col in fm_agg.columns:
                if col != "sid":
                    row[col] = float(fm_row.iloc[0][col])
        # Targets
        row["t1_target"] = info.get("label", None)
        row["is_pd"] = 1 if info["group"] == "PD" else 0
        rows.append(row)

    merged = pd.DataFrame(rows)
    # Need to compute t1/t2/t3 targets from UPDRS items
    # For now, use the label as total UPDRS
    return merged, v2_cols


def load_prepared_data():
    """Load from run_compression_ablation.py's prepared data."""
    # The easiest way: run the data prep portion of run_compression_ablation.py
    # and return the dataframes. Let's import what we need.
    sys.path.insert(0, os.path.dirname(__file__))

    # Import the main script's data loading
    import importlib
    spec = importlib.util.spec_from_file_location(
        "compression", os.path.join(os.path.dirname(__file__), "run_compression_ablation.py"))
    mod = importlib.util.module_from_spec(spec)

    # We can't easily import the full module without running it.
    # Instead, replicate the data loading logic directly.
    from run_compression_ablation import load_features_and_targets as comp_load
    return comp_load()


# ── SSL ranking core (simplified from run_compression_ablation.py) ──
def run_ssl_for_subset(pd_sids_train, pd_sids_test, all_merged, feature_cols,
                       target_key, K=500):
    """Run P5 SSL ranking for a specific train/test split.

    Returns dict with CCC, MAE, slope, r, per_subject predictions.
    """
    import lightgbm as lgb
    from xgboost import XGBRanker

    target_col = f"{target_key}_target"
    SEEDS = [42, 123, 456, 789, 2024]

    # Prepare data
    pd_data = all_merged[all_merged["is_pd"] == 1]
    train_mask = pd_data["sid"].isin(pd_sids_train)
    test_mask = pd_data["sid"].isin(pd_sids_test)

    Xd = pd_data.loc[train_mask, feature_cols].values.astype(np.float32)
    yd = pd_data.loc[train_mask, target_col].values.astype(np.float32)
    Xt = pd_data.loc[test_mask, feature_cols].values.astype(np.float32)
    yt = pd_data.loc[test_mask, target_col].values.astype(np.float32)

    if len(yd) < 5 or len(yt) < 2:
        return {"error": f"Too few subjects: train={len(yd)}, test={len(yt)}"}

    # Feature selection
    from eval_utils import feature_select
    sel_idx, sel_names = feature_select(Xd, yd, list(feature_cols), k=min(K, Xd.shape[1]))
    Xd_sel = Xd[:, sel_idx]
    Xt_sel = Xt[:, sel_idx]

    # Stage 1: XGBRanker on ALL subjects
    X_all = all_merged[feature_cols].values.astype(np.float32)[:, sel_idx]
    all_targets = all_merged[target_col].values.astype(np.float32)
    is_pd = all_merged["is_pd"].values
    rank_labels = np.zeros(len(is_pd), dtype=np.int32)
    pd_idx = np.where(is_pd == 1)[0]
    pd_order = np.argsort(all_targets[pd_idx])
    for rank, idx in enumerate(pd_order):
        rank_labels[pd_idx[idx]] = rank + 1

    all_sids = all_merged["sid"].values
    sid_to_idx = {s: i for i, s in enumerate(all_sids)}

    train_all_idx = [sid_to_idx[s] for s in pd_sids_train if s in sid_to_idx]
    test_all_idx = [sid_to_idx[s] for s in pd_sids_test if s in sid_to_idx]

    leaf_features = []
    for seed in SEEDS[:3]:
        ranker = XGBRanker(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
            objective="rank:pairwise",
        )
        ranker.fit(X_all, rank_labels, group=np.array([len(X_all)]))
        train_leaves = ranker.apply(X_all[train_all_idx])
        test_leaves = ranker.apply(X_all[test_all_idx])
        leaf_features.append((train_leaves, test_leaves))

    train_leaf = np.hstack([lf[0] for lf in leaf_features]).astype(np.float32)
    test_leaf = np.hstack([lf[1] for lf in leaf_features]).astype(np.float32)

    Xd_combined = np.hstack([Xd_sel, train_leaf])
    Xt_combined = np.hstack([Xt_sel, test_leaf])

    # Stage 2: LGB ensemble
    preds_all = []
    for seed in SEEDS:
        n_val = max(int(0.15 * len(yd)), 2)
        rng = np.random.RandomState(seed)
        val_idx = rng.choice(len(yd), n_val, replace=False)
        trn_idx = np.setdiff1d(np.arange(len(yd)), val_idx)

        model = lgb.LGBMRegressor(
            n_estimators=2000, learning_rate=0.03, max_depth=6,
            num_leaves=31, reg_lambda=0.3, min_data_in_leaf=8,
            colsample_bytree=0.5, verbose=-1, random_state=seed,
            n_jobs=N_CORES,
        )
        model.fit(
            Xd_combined[trn_idx], yd[trn_idx],
            eval_set=[(Xd_combined[val_idx], yd[val_idx])],
            callbacks=[lgb.early_stopping(100, verbose=False), lgb.log_evaluation(0)],
        )
        pred = model.predict(Xt_combined)
        preds_all.append(np.clip(pred, 0, max(yd.max(), yt.max()) * 1.2))

    y_pred = np.mean(preds_all, axis=0)

    ccc = lins_ccc(yt, y_pred)
    mae = float(np.mean(np.abs(yt - y_pred)))
    slope = cal_slope(yt, y_pred)
    r = float(np.corrcoef(yt, y_pred)[0, 1]) if np.std(yt) > 0 and np.std(y_pred) > 0 else 0.0

    test_sids = pd_data.loc[test_mask, "sid"].values
    per_subject = {"y_true": yt.tolist(), "y_pred": y_pred.tolist(), "sids": test_sids.tolist()}

    return {
        "ccc": ccc, "mae": mae, "cal_slope": slope, "r": r,
        "n_train": len(yd), "n_test": len(yt),
        "per_subject": per_subject,
    }


# ── Phase: Leave-site-out ───────────────────────────────────
def phase_site(all_merged, feature_cols, metadata):
    """Leave-site-out validation: NLS→WPD and WPD→NLS."""
    print("=" * 60)
    print("PHASE: LEAVE-SITE-OUT VALIDATION")
    print("=" * 60)

    pd_data = all_merged[all_merged["is_pd"] == 1]
    pd_sids = pd_data["sid"].values

    # Assign sites
    sid_sites = {sid: metadata.get(sid, {}).get("site", "UNK") for sid in pd_sids}
    sites = sorted(set(sid_sites.values()) - {"UNK"})
    print(f"Sites: {sites}")
    for site in sites:
        n = sum(1 for s in pd_sids if sid_sites.get(s) == site)
        print(f"  {site}: {n} PD subjects")

    results = []
    for target_key in ["t1", "t3"]:
        for test_site in sites:
            train_sids = [s for s in pd_sids if sid_sites.get(s) != test_site]
            test_sids = [s for s in pd_sids if sid_sites.get(s) == test_site]

            print(f"\n  {target_key.upper()} — Train: {len(train_sids)} (excl {test_site}), Test: {len(test_sids)} ({test_site})")
            r = run_ssl_for_subset(train_sids, test_sids, all_merged, feature_cols, target_key)
            r["target"] = target_key
            r["test_site"] = test_site
            r["train_sites"] = [s for s in sites if s != test_site]
            results.append(r)
            if "error" not in r:
                print(f"    CCC={r['ccc']:.3f}  MAE={r['mae']:.3f}  slope={r['cal_slope']:.3f}  r={r['r']:.3f}")

    save_json({"phase": "leave_site_out", "results": results}, "memento_site_validation.json")
    return results


# ── Phase: DBS stratification ───────────────────────────────
def phase_dbs(all_merged, feature_cols, metadata):
    """DBS vs non-DBS stratified performance."""
    print("\n" + "=" * 60)
    print("PHASE: DBS STRATIFICATION")
    print("=" * 60)

    pd_data = all_merged[all_merged["is_pd"] == 1]
    pd_sids = pd_data["sid"].values

    dbs_yes = [s for s in pd_sids if metadata.get(s, {}).get("dbs") == "Yes"]
    dbs_no = [s for s in pd_sids if metadata.get(s, {}).get("dbs") == "No"]
    print(f"DBS Yes: {len(dbs_yes)}, DBS No: {len(dbs_no)}")

    results = []
    for target_key in ["t1", "t3"]:
        # Full model, stratified evaluation
        # 5-fold on all PD, then evaluate separately for DBS/non-DBS
        from sklearn.model_selection import StratifiedKFold

        target_col = f"{target_key}_target"
        yt_all = pd_data[target_col].values
        sids_all = pd_data["sid"].values

        # Binary for stratification
        dbs_labels = np.array([1 if metadata.get(s, {}).get("dbs") == "Yes" else 0 for s in sids_all])

        all_true = {g: [] for g in ["dbs_yes", "dbs_no"]}
        all_pred = {g: [] for g in ["dbs_yes", "dbs_no"]}

        kf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        # Stratify on quartiles of target for balanced folds
        target_bins = pd.qcut(yt_all, q=4, labels=False, duplicates="drop")

        for fold_i, (train_idx, test_idx) in enumerate(kf.split(sids_all, target_bins)):
            train_sids = sids_all[train_idx]
            test_sids = sids_all[test_idx]

            r = run_ssl_for_subset(train_sids, test_sids, all_merged, feature_cols, target_key)
            if "error" in r:
                print(f"  Fold {fold_i}: ERROR — {r['error']}")
                continue

            # Stratify predictions by DBS status
            ps = r["per_subject"]
            for i, sid in enumerate(ps["sids"]):
                dbs = metadata.get(sid, {}).get("dbs")
                if dbs == "Yes":
                    all_true["dbs_yes"].append(ps["y_true"][i])
                    all_pred["dbs_yes"].append(ps["y_pred"][i])
                elif dbs == "No":
                    all_true["dbs_no"].append(ps["y_true"][i])
                    all_pred["dbs_no"].append(ps["y_pred"][i])

        # Compute metrics per group
        for group in ["dbs_yes", "dbs_no"]:
            yt = np.array(all_true[group])
            yp = np.array(all_pred[group])
            if len(yt) < 3:
                results.append({"target": target_key, "group": group, "error": f"N={len(yt)} too small"})
                continue
            ccc = lins_ccc(yt, yp)
            mae = float(np.mean(np.abs(yt - yp)))
            slope = cal_slope(yt, yp)
            r_val = float(np.corrcoef(yt, yp)[0, 1]) if np.std(yt) > 0 and np.std(yp) > 0 else 0.0
            results.append({
                "target": target_key, "group": group,
                "n": len(yt), "ccc": ccc, "mae": mae, "cal_slope": slope, "r": r_val,
            })
            print(f"  {target_key.upper()} {group} (N={len(yt)}): CCC={ccc:.3f}  MAE={mae:.3f}  slope={slope:.3f}")

    save_json({"phase": "dbs_stratification", "results": results}, "memento_dbs_results.json")
    return results


# ── Phase: Sex stratification ───────────────────────────────
def phase_sex(all_merged, feature_cols, metadata):
    """Male vs Female stratified performance."""
    print("\n" + "=" * 60)
    print("PHASE: SEX STRATIFICATION")
    print("=" * 60)

    pd_data = all_merged[all_merged["is_pd"] == 1]
    sids_all = pd_data["sid"].values
    target_col = "t1_target"

    results = []
    for target_key in ["t1", "t3"]:
        target_col = f"{target_key}_target"
        yt_all = pd_data[target_col].values

        all_true = {"Male": [], "Female": []}
        all_pred = {"Male": [], "Female": []}

        from sklearn.model_selection import StratifiedKFold
        target_bins = pd.qcut(yt_all, q=4, labels=False, duplicates="drop")
        kf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

        for fold_i, (train_idx, test_idx) in enumerate(kf.split(sids_all, target_bins)):
            r = run_ssl_for_subset(sids_all[train_idx], sids_all[test_idx],
                                   all_merged, feature_cols, target_key)
            if "error" in r:
                continue
            ps = r["per_subject"]
            for i, sid in enumerate(ps["sids"]):
                sex = metadata.get(sid, {}).get("sex", "Unknown")
                if sex in all_true:
                    all_true[sex].append(ps["y_true"][i])
                    all_pred[sex].append(ps["y_pred"][i])

        for group in ["Male", "Female"]:
            yt = np.array(all_true[group])
            yp = np.array(all_pred[group])
            if len(yt) < 3:
                results.append({"target": target_key, "group": group, "error": f"N={len(yt)}"})
                continue
            ccc = lins_ccc(yt, yp)
            mae = float(np.mean(np.abs(yt - yp)))
            slope = cal_slope(yt, yp)
            r_val = float(np.corrcoef(yt, yp)[0, 1]) if np.std(yt) > 0 and np.std(yp) > 0 else 0.0
            results.append({
                "target": target_key, "group": group,
                "n": len(yt), "ccc": ccc, "mae": mae, "cal_slope": slope, "r": r_val,
            })
            print(f"  {target_key.upper()} {group} (N={len(yt)}): CCC={ccc:.3f}  MAE={mae:.3f}  slope={slope:.3f}")

    save_json({"phase": "sex_stratification", "results": results}, "memento_sex_results.json")
    return results


# ── Phase: H&Y stratification ──────────────────────────────
def phase_hy(all_merged, feature_cols, metadata):
    """H&Y stage stratified performance."""
    print("\n" + "=" * 60)
    print("PHASE: H&Y STRATIFICATION")
    print("=" * 60)

    pd_data = all_merged[all_merged["is_pd"] == 1]
    sids_all = pd_data["sid"].values

    # Group H&Y: 1-1.5 (mild), 2-2.5 (moderate), 3-4 (severe)
    hy_groups = {}
    for sid in sids_all:
        hy = metadata.get(sid, {}).get("hy")
        if hy is not None:
            if hy <= 1.5:
                hy_groups.setdefault("HY_1-1.5", []).append(sid)
            elif hy <= 2.5:
                hy_groups.setdefault("HY_2-2.5", []).append(sid)
            else:
                hy_groups.setdefault("HY_3-4", []).append(sid)
        else:
            hy_groups.setdefault("HY_unknown", []).append(sid)

    for g, sids in hy_groups.items():
        print(f"  {g}: {len(sids)} PD subjects")

    results = []
    for target_key in ["t1", "t3"]:
        target_col = f"{target_key}_target"
        yt_all = pd_data[target_col].values

        group_preds = {g: {"true": [], "pred": []} for g in hy_groups}

        from sklearn.model_selection import StratifiedKFold
        target_bins = pd.qcut(yt_all, q=4, labels=False, duplicates="drop")
        kf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

        for fold_i, (train_idx, test_idx) in enumerate(kf.split(sids_all, target_bins)):
            r = run_ssl_for_subset(sids_all[train_idx], sids_all[test_idx],
                                   all_merged, feature_cols, target_key)
            if "error" in r:
                continue
            ps = r["per_subject"]
            for i, sid in enumerate(ps["sids"]):
                for g, g_sids in hy_groups.items():
                    if sid in g_sids:
                        group_preds[g]["true"].append(ps["y_true"][i])
                        group_preds[g]["pred"].append(ps["y_pred"][i])
                        break

        for group, preds in group_preds.items():
            yt = np.array(preds["true"])
            yp = np.array(preds["pred"])
            if len(yt) < 3:
                results.append({"target": target_key, "group": group, "error": f"N={len(yt)}"})
                continue
            ccc = lins_ccc(yt, yp)
            mae = float(np.mean(np.abs(yt - yp)))
            slope = cal_slope(yt, yp)
            r_val = float(np.corrcoef(yt, yp)[0, 1]) if np.std(yt) > 0 and np.std(yp) > 0 else 0.0
            results.append({
                "target": target_key, "group": group,
                "n": len(yt), "ccc": ccc, "mae": mae, "cal_slope": slope, "r": r_val,
            })
            print(f"  {target_key.upper()} {group} (N={len(yt)}): CCC={ccc:.3f}  MAE={mae:.3f}  slope={slope:.3f}")

    save_json({"phase": "hy_stratification", "results": results}, "memento_hy_results.json")
    return results


# ── Main ────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True,
                        choices=["site", "dbs", "sex", "hy", "all"])
    args = parser.parse_args()

    t0 = time.time()
    print("Loading clinical metadata...")
    metadata = load_clinical_metadata()
    print(f"  {len(metadata)} subjects with metadata")

    print("Loading features and targets...")
    # Import load from compression script
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from run_compression_ablation import load_features_and_targets as _load_data
    pd_merged, all_merged, feature_cols, subjects, item_scores = _load_data()
    print(f"  PD: {len(pd_merged)}, All: {len(all_merged)}, Features: {len(feature_cols)}")

    phases = [args.phase] if args.phase != "all" else ["site", "dbs", "sex", "hy"]
    all_results = {}
    for phase in phases:
        fn = globals()[f"phase_{phase}"]
        all_results[phase] = fn(all_merged, feature_cols, metadata)

    save_json(all_results, "memento_subgroup_all_results.json")
    print(f"\nTotal runtime: {time.time() - t0:.0f}s")

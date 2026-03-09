"""
Cross-Dataset Transfer & Generalization Study
==============================================
Since no external dataset has BOTH IMU gait data AND UPDRS-III scores,
we run three types of transfer experiments:

1. SENSOR REDUCTION: How does MAE degrade with fewer sensors?
   (Simulates deployment with 1-4 sensors vs full 13)
2. PADS CLASSIFICATION TRANSFER: Do WearGait-PD features transfer to
   smartwatch PD/HC classification?
3. TASK GENERALIZATION: Train on subset of tasks, test with all tasks

These directly address reviewer questions about:
- "What if I only have a wrist sensor?" → Sensor reduction
- "Do these features generalize to other datasets?" → PADS transfer
- "Does the model require all 5 gait tasks?" → Task generalization
"""
import os, sys, json, time, warnings, signal as _signal

# Handle broken pipe gracefully (SSH disconnect)
_signal.signal(_signal.SIGPIPE, _signal.SIG_DFL)
import numpy as np
import pandas as pd
from scipy import signal, stats as sp_stats
from sklearn.metrics import mean_absolute_error, balanced_accuracy_score, roc_auc_score
from concurrent.futures import ProcessPoolExecutor
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS

from run_ablation_v2 import (extract_recording, agg_task_preserving, compute_dist_feats,
                              load_covariates, load_walkway, distill_walkway,
                              agg_mean, TASKS, N_CORES, SEEDS, td_feats, fd_feats, gait_reg)

RESULTS_FILE = "/root/pd-imu/transfer_results.json"

# Sensor groups for reduction study
SENSOR_CONFIGS = {
    "full_13": SENSORS,
    "lower_body_7": ["LowerBack", "R_LatShank", "L_LatShank",
                     "R_DorsalFoot", "L_DorsalFoot", "R_Ankle", "L_Ankle"],
    "minimal_clinical_4": ["LowerBack", "R_Wrist", "R_Ankle", "L_Ankle"],
    "wrist_pair_2": ["R_Wrist", "L_Wrist"],
    "ankle_pair_2": ["R_Ankle", "L_Ankle"],
    "lower_back_1": ["LowerBack"],
    "single_wrist_1": ["R_Wrist"],
    "single_ankle_1": ["R_Ankle"],
}

# Task configs for generalization study
TASK_CONFIGS = {
    "all_5": TASKS,
    "gait_only_2": ["SelfPace", "HurriedPace"],
    "selfpace_only_1": ["SelfPace"],
    "tug_only_1": ["TUG"],
    "no_balance_4": ["SelfPace", "HurriedPace", "TUG", "TandemGait"],
    "no_tandem_4": ["SelfPace", "HurriedPace", "TUG", "Balance"],
}


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def train_lgb(Xtr, ytr, Xva, yva, seed):
    import lightgbm as lgb
    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                          reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                          objective="mae", verbosity=-1)
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)],
          callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    return m


def feature_select(X, y, n_feats, feat_names):
    from xgboost import XGBRegressor
    rng = np.random.RandomState(42)
    idx = np.arange(len(X))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    m = XGBRegressor(n_estimators=500, learning_rate=0.05, max_depth=6,
                     reg_lambda=3.0, random_state=42, n_jobs=N_CORES,
                     early_stopping_rounds=50, objective="reg:absoluteerror")
    m.fit(X[idx[nv:]], y[idx[nv:]], eval_set=[(X[idx[:nv]], y[idx[:nv]])], verbose=False)
    top = np.argsort(m.feature_importances_)[::-1][:n_feats]
    return top, [feat_names[i] for i in top]


def eval_config(df, dev_sids, test_sids, n_feats=150, label=""):
    """Train LightGBM 5-seed ensemble, return ensemble MAE and r."""
    feat_cols = [c for c in df.columns if c not in ("sid", "updrs3")]
    if len(feat_cols) == 0:
        return {"ens_mae": 999, "ens_r": 0, "n_feats_avail": 0}

    dev = df[df["sid"].isin(dev_sids)].copy()
    test = df[df["sid"].isin(test_sids)].copy()
    for c in feat_cols:
        dev[c] = dev[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        test[c] = test[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)

    Xd = dev[feat_cols].values.astype(np.float32)
    yd = dev["updrs3"].values.astype(np.float32)
    Xt = test[feat_cols].values.astype(np.float32)
    yt = test["updrs3"].values.astype(np.float32)

    nf = min(n_feats, len(feat_cols))
    if nf < len(feat_cols):
        top_idx, _ = feature_select(Xd, yd, nf, feat_cols)
        Xd = Xd[:, top_idx]
        Xt = Xt[:, top_idx]

    preds = []
    seed_maes = []
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(Xd))
        rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        m = train_lgb(Xd[idx[nv:]], yd[idx[nv:]],
                      Xd[idx[:nv]], yd[idx[:nv]], seed)
        p = m.predict(Xt)
        preds.append(p)
        seed_maes.append(mean_absolute_error(yt, p))

    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep)
    er, _ = sp_stats.pearsonr(yt, ep)

    return {
        "ens_mae": round(float(em), 3),
        "ens_r": round(float(er), 3),
        "mean_mae": round(float(np.mean(seed_maes)), 3),
        "std_mae": round(float(np.std(seed_maes)), 3),
        "n_feats_avail": len(feat_cols),
        "n_feats_selected": nf,
        "n_dev": len(dev),
        "n_test": len(test),
    }


# ═══════════════════════════════════════════════════════════════════
# EXPERIMENT 1: SENSOR REDUCTION STUDY
# ═══════════════════════════════════════════════════════════════════

META_KEYS = {"sid", "task", "n_samples", "duration_s"}

def extract_for_sensors(jobs):
    """Extract features from all recordings."""
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        all_recs = [r for r in pool.map(extract_recording, jobs) if r is not None]
    return all_recs


def run_sensor_reduction(subjects, dev_sids, test_sids):
    """Test model performance with different sensor configurations."""
    print("\n" + "=" * 70)
    print("EXPERIMENT 1: SENSOR REDUCTION STUDY")
    print("=" * 70)

    all_sids = dev_sids + test_sids
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")

    jobs = []
    all_tasks = TASKS + [f"{t}_mat" for t in TASKS] + \
                [f"{t}_matTURN" for t in ["SelfPace", "HurriedPace"]]
    for task in all_tasks:
        for sid in all_sids:
            if sid not in subjects:
                continue
            d = pd_dir if subjects[sid]["group"] == "PD" else hc_dir
            p = os.path.join(d, f"{sid}_{task}.csv")
            if os.path.exists(p):
                jobs.append((p, sid, task))

    # Extract all features once
    all_recs = extract_for_sensors(jobs)
    main_recs = [r for r in all_recs if "_mat" not in r["task"]]
    mat_recs = [r for r in all_recs if "_mat" in r["task"]]
    covs = load_covariates()
    wk = load_walkway()

    results = {}

    for config_name, sensor_subset in SENSOR_CONFIGS.items():
        print(f"\n  Config: {config_name} ({len(sensor_subset)} sensors)")

        # Filter features: keep only those from allowed sensors
        filtered_recs = []
        for rec in main_recs:
            new_rec = {}
            for k, v in rec.items():
                if k in META_KEYS:
                    new_rec[k] = v
                    continue
                # Feature key: check if it belongs to an allowed sensor
                keep = False
                for s in sensor_subset:
                    if k.startswith(f"{s}_"):
                        keep = True
                        break
                if k.startswith("bilat_"):
                    keep = True
                if k.startswith("trunk_") and any(s in ["LowerBack", "Xiphoid"] for s in sensor_subset):
                    keep = True
                if k.startswith("fog_") and "LowerBack" in sensor_subset:
                    keep = True
                # Keep foot-contact features if ankle/foot sensors present
                if k.startswith("fc_") and any(s.startswith(("R_Ankle", "L_Ankle", "R_Dorsal", "L_Dorsal"))
                                                for s in sensor_subset):
                    keep = True
                # Keep balance features if LowerBack present
                if k.startswith("bal_") and "LowerBack" in sensor_subset:
                    keep = True
                # Keep turn features if LowerBack present
                if k.startswith("turn_") and "LowerBack" in sensor_subset:
                    keep = True
                # Keep task contrast/distribution features for matching sensors
                if k.startswith(("d_", "r_", "dv_")):
                    for s in sensor_subset:
                        if s in k:
                            keep = True
                            break
                if keep:
                    new_rec[k] = v
            filtered_recs.append(new_rec)

        # Build feature DataFrame
        df = agg_task_preserving(filtered_recs, subjects)

        # Add covariates (always available regardless of sensors)
        for cn in ["cv_age", "cv_sex", "cv_ht", "cv_wt", "cv_yrs", "cv_dbs"]:
            df[cn] = 0.0
        for sid, cv in covs.items():
            mask = df["sid"] == sid
            if mask.any():
                for k, v in cv.items():
                    df.loc[mask, k] = v

        # Walkway distillation (using available sensors only)
        if wk:
            dst = distill_walkway(df, wk, dev_sids)
            if dst:
                for dc in sorted(set().union(*[set(v.keys()) for v in dst.values()])):
                    df[dc] = 0.0
                for sid, dm in dst.items():
                    mask = df["sid"] == sid
                    if mask.any():
                        for k, v in dm.items():
                            df.loc[mask, k] = v

        n_feats = len([c for c in df.columns if c not in ("sid", "updrs3")])
        print(f"    {n_feats} features extracted")

        res = eval_config(df, dev_sids, test_sids, n_feats=min(150, n_feats))
        res["sensors"] = sensor_subset
        res["n_sensors"] = len(sensor_subset)
        results[config_name] = res
        print(f"    MAE={res['ens_mae']:.2f}, r={res['ens_r']:.3f}")

    return results


# ═══════════════════════════════════════════════════════════════════
# EXPERIMENT 2: PADS CLASSIFICATION TRANSFER
# ═══════════════════════════════════════════════════════════════════

def extract_pads_features():
    """Extract wrist-based features from PADS smartwatch data."""
    pads_dir = "/root/pd-imu/data/raw/pads/physionet.org/files/parkinsons-disease-smartwatch/1.0.0"
    patient_dir = os.path.join(pads_dir, "patients")
    movement_dir = os.path.join(pads_dir, "movement")
    file_list = os.path.join(pads_dir, "preprocessed", "file_list.csv")

    # Load patient metadata
    patients = {}
    flist = pd.read_csv(file_list)
    for _, row in flist.iterrows():
        pid = str(row["id"]).zfill(3)
        condition = row.get("condition", "")
        label = int(row.get("label", -1))
        patients[pid] = {
            "condition": condition,
            "label": label,  # 0=healthy, 1=PD, 2=other
            "age": row.get("age", 0),
            "gender": row.get("gender", ""),
        }

    # Load movement observations
    obs_files = sorted([f for f in os.listdir(movement_dir)
                       if f.startswith("observation_") and f.endswith(".json")])

    all_feats = []
    for obs_file in obs_files:
        with open(os.path.join(movement_dir, obs_file)) as f:
            obs = json.load(f)
        pid = obs.get("subject_id", "").zfill(3)
        if pid not in patients:
            continue
        if patients[pid]["label"] not in (0, 1):  # only HC and PD
            continue

        sr = obs.get("sampling_rate", 100)
        endian = obs.get("endianness", "little")
        bits = obs.get("bits", 32)
        dtype = np.float32 if bits == 32 else np.float64

        sessions = obs.get("session", [])
        for session in sessions:
            record_name = session.get("record_name", "")
            rows = session.get("rows", 0)
            if rows < 200:
                continue

            records = session.get("records", [])
            acc_data = None
            for rec in records:
                channels = rec.get("channels", [])
                if "Accelerometer_X" in channels and "Accelerometer_Y" in channels:
                    # Load binary data
                    bin_file = rec.get("data_file", "")
                    if not bin_file:
                        continue
                    bin_path = os.path.join(movement_dir, bin_file)
                    if not os.path.exists(bin_path):
                        continue
                    data = np.fromfile(bin_path, dtype=dtype)
                    n_ch = len(channels) - 1  # exclude Time
                    if len(data) < rows * (n_ch + 1):
                        continue
                    data = data[:rows * (n_ch + 1)].reshape(rows, n_ch + 1)
                    # Get acc columns (skip Time)
                    ch_idx = {c: i for i, c in enumerate(channels)}
                    ax = data[:, ch_idx.get("Accelerometer_X", 1)]
                    ay = data[:, ch_idx.get("Accelerometer_Y", 2)]
                    az = data[:, ch_idx.get("Accelerometer_Z", 3)]
                    acc_data = np.stack([ax, ay, az], axis=1)
                    break

            if acc_data is None or len(acc_data) < 200:
                continue

            # Extract same feature types as WearGait-PD wrist features
            feats = {"pid": pid, "session": record_name, "label": patients[pid]["label"]}
            am = np.sqrt(acc_data[:, 0]**2 + acc_data[:, 1]**2 + acc_data[:, 2]**2)

            for i, axis in enumerate(["ax", "ay", "az"]):
                feats.update(td_feats(acc_data[:, i], f"wrist_{axis}"))
                feats.update(fd_feats(acc_data[:, i], f"wrist_{axis}"))
            feats.update(td_feats(am, "wrist_am"))
            feats.update(fd_feats(am, "wrist_am"))
            feats.update(gait_reg(am, "wrist_g"))

            all_feats.append(feats)

    if not all_feats:
        return None, None

    df = pd.DataFrame(all_feats)
    # Aggregate per subject
    feat_cols = [c for c in df.columns if c not in ("pid", "session", "label")]
    agg = df.groupby("pid")[feat_cols].mean().reset_index()
    labels = df.groupby("pid")["label"].first().reset_index()
    agg = agg.merge(labels, on="pid")

    return agg, feat_cols


def run_pads_transfer(subjects, dev_sids):
    """Test WearGait-PD wrist features on PADS classification."""
    print("\n" + "=" * 70)
    print("EXPERIMENT 2: PADS CLASSIFICATION TRANSFER")
    print("=" * 70)

    pads_df, pads_feats = extract_pads_features()
    if pads_df is None:
        print("  PADS data not loadable — skipping")
        return {"status": "skipped", "reason": "PADS data not loadable"}

    n_pd = (pads_df["label"] == 1).sum()
    n_hc = (pads_df["label"] == 0).sum()
    print(f"  PADS subjects: {n_pd} PD + {n_hc} HC = {len(pads_df)} total")
    print(f"  PADS features: {len(pads_feats)}")

    if len(pads_df) < 10:
        print("  Too few subjects — skipping")
        return {"status": "skipped", "reason": f"only {len(pads_df)} subjects"}

    # Extract matching wrist features from WearGait-PD
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")

    wg_feats = []
    for sid in dev_sids + list(set(subjects.keys()) - set(dev_sids)):
        if sid not in subjects:
            continue
        info = subjects[sid]
        d = pd_dir if info["group"] == "PD" else hc_dir

        sess_feats = []
        for task in TASKS:
            p = os.path.join(d, f"{sid}_{task}.csv")
            if not os.path.exists(p):
                continue
            try:
                df = pd.read_csv(p)
            except Exception:
                continue

            feats = {"sid": sid, "label": info["label"]}
            for wrist in ["R_Wrist"]:  # Use right wrist to match PADS left wrist
                for axis_name, col_suffix in [("ax", "Acc_X"), ("ay", "Acc_Y"), ("az", "Acc_Z")]:
                    col = f"{wrist}_{col_suffix}"
                    if col not in df.columns:
                        continue
                    x = df[col].values.astype(np.float32)
                    x = np.nan_to_num(x, nan=0.0)
                    feats.update(td_feats(x, f"wrist_{axis_name}"))
                    feats.update(fd_feats(x, f"wrist_{axis_name}"))

                # Magnitude
                acc_cols = [f"{wrist}_Acc_{a}" for a in "XYZ"]
                if all(c in df.columns for c in acc_cols):
                    acc = df[acc_cols].values.astype(np.float32)
                    acc = np.nan_to_num(acc, nan=0.0)
                    am = np.sqrt((acc**2).sum(axis=1))
                    feats.update(td_feats(am, "wrist_am"))
                    feats.update(fd_feats(am, "wrist_am"))
                    feats.update(gait_reg(am, "wrist_g"))
            sess_feats.append(feats)

        if sess_feats:
            # Average across tasks
            avg = {"sid": sid, "label": info["label"]}
            keys = [k for k in sess_feats[0].keys() if k not in ("sid", "label")]
            for k in keys:
                vals = [f[k] for f in sess_feats if k in f and isinstance(f[k], (int, float))]
                avg[k] = np.mean(vals) if vals else 0.0
            wg_feats.append(avg)

    wg_df = pd.DataFrame(wg_feats)
    print(f"  WearGait-PD wrist features: {len(wg_df)} subjects")

    # Find common features
    common_feats = sorted(set(pads_feats) & set([c for c in wg_df.columns if c not in ("sid", "label")]))
    print(f"  Common features: {len(common_feats)}")

    if len(common_feats) < 5:
        print("  Too few common features — skipping")
        return {"status": "skipped", "reason": f"only {len(common_feats)} common features"}

    # Experiment A: Train on WearGait-PD, test on PADS (zero-shot transfer)
    from sklearn.ensemble import GradientBoostingClassifier

    X_wg = wg_df[common_feats].values.astype(np.float32)
    y_wg = wg_df["label"].values
    X_pads = pads_df[common_feats].values.astype(np.float32)
    y_pads = pads_df["label"].values

    # Clean
    X_wg = np.nan_to_num(X_wg, nan=0.0, posinf=0.0, neginf=0.0)
    X_pads = np.nan_to_num(X_pads, nan=0.0, posinf=0.0, neginf=0.0)

    # Normalize using WG statistics
    mu = X_wg.mean(axis=0)
    sd = X_wg.std(axis=0) + 1e-8
    X_wg_n = (X_wg - mu) / sd
    X_pads_n = (X_pads - mu) / sd

    accs_zs = []
    for seed in SEEDS:
        clf = GradientBoostingClassifier(n_estimators=200, max_depth=4,
                                         learning_rate=0.05, random_state=seed)
        clf.fit(X_wg_n, y_wg)
        pred = clf.predict(X_pads_n)
        ba = balanced_accuracy_score(y_pads, pred)
        accs_zs.append(ba)
        print(f"    Zero-shot seed={seed}: bal_acc={ba:.3f}")

    # Experiment B: 5-fold CV within PADS alone (baseline)
    from sklearn.model_selection import StratifiedKFold
    accs_pads = []
    skf = StratifiedKFold(n_splits=min(5, n_pd, n_hc), shuffle=True, random_state=42)
    for tr_idx, te_idx in skf.split(X_pads, y_pads):
        mu_p = X_pads[tr_idx].mean(axis=0)
        sd_p = X_pads[tr_idx].std(axis=0) + 1e-8
        Xtr = (X_pads[tr_idx] - mu_p) / sd_p
        Xte = (X_pads[te_idx] - mu_p) / sd_p
        clf = GradientBoostingClassifier(n_estimators=200, max_depth=4,
                                         learning_rate=0.05, random_state=42)
        clf.fit(Xtr, y_pads[tr_idx])
        pred = clf.predict(Xte)
        accs_pads.append(balanced_accuracy_score(y_pads[te_idx], pred))

    print(f"  Zero-shot transfer: {np.mean(accs_zs):.3f} ± {np.std(accs_zs):.3f}")
    print(f"  PADS-only 5-fold:   {np.mean(accs_pads):.3f} ± {np.std(accs_pads):.3f}")

    return {
        "n_pads_pd": int(n_pd),
        "n_pads_hc": int(n_hc),
        "n_common_features": len(common_feats),
        "zero_shot_bal_acc": round(float(np.mean(accs_zs)), 3),
        "zero_shot_std": round(float(np.std(accs_zs)), 3),
        "pads_only_bal_acc": round(float(np.mean(accs_pads)), 3),
        "pads_only_std": round(float(np.std(accs_pads)), 3),
    }


# ═══════════════════════════════════════════════════════════════════
# EXPERIMENT 3: TASK GENERALIZATION
# ═══════════════════════════════════════════════════════════════════

def run_task_generalization(subjects, dev_sids, test_sids):
    """Test model performance when trained on subset of gait tasks."""
    print("\n" + "=" * 70)
    print("EXPERIMENT 3: TASK GENERALIZATION")
    print("=" * 70)

    all_sids = dev_sids + test_sids
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    covs = load_covariates()

    results = {}

    for config_name, task_subset in TASK_CONFIGS.items():
        print(f"\n  Config: {config_name} (tasks: {', '.join(task_subset)})")

        jobs = []
        for task in task_subset:
            for sid in all_sids:
                if sid not in subjects:
                    continue
                d = pd_dir if subjects[sid]["group"] == "PD" else hc_dir
                p = os.path.join(d, f"{sid}_{task}.csv")
                if os.path.exists(p):
                    jobs.append((p, sid, task))

        with ProcessPoolExecutor(max_workers=N_CORES) as pool:
            recs = [r for r in pool.map(extract_recording, jobs) if r is not None]
        print(f"    {len(recs)} recordings extracted")

        df = agg_task_preserving(recs, subjects)

        # Add covariates
        for cn in ["cv_age", "cv_sex", "cv_ht", "cv_wt", "cv_yrs", "cv_dbs"]:
            df[cn] = 0.0
        for sid, cv in covs.items():
            mask = df["sid"] == sid
            if mask.any():
                for k, v in cv.items():
                    df.loc[mask, k] = v

        n_feats = len([c for c in df.columns if c not in ("sid", "updrs3")])
        print(f"    {n_feats} features")

        res = eval_config(df, dev_sids, test_sids, n_feats=min(150, n_feats))
        res["tasks"] = task_subset
        res["n_tasks"] = len(task_subset)
        results[config_name] = res
        print(f"    MAE={res['ens_mae']:.2f}, r={res['ens_r']:.3f}")

    return results


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    print("=" * 70)
    print("CROSS-DATASET TRANSFER & GENERALIZATION STUDY")
    print("=" * 70)

    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]

    # Experiment 1: Sensor Reduction
    sensor_results = run_sensor_reduction(subjects, dev_sids, test_sids)

    # Experiment 2: PADS Transfer
    pads_results = run_pads_transfer(subjects, dev_sids)

    # Experiment 3: Task Generalization
    task_results = run_task_generalization(subjects, dev_sids, test_sids)

    # === Summary ===
    all_results = {
        "sensor_reduction": sensor_results,
        "pads_transfer": pads_results,
        "task_generalization": task_results,
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    elapsed = time.time() - t0

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print("\nSENSOR REDUCTION:")
    print(f"  {'Config':<25} {'Sensors':<5} {'MAE':<8} {'r':<8} {'N_feats':<8}")
    print("  " + "-" * 55)
    for name in ["full_13", "lower_body_7", "minimal_clinical_4",
                  "wrist_pair_2", "ankle_pair_2", "lower_back_1",
                  "single_wrist_1", "single_ankle_1"]:
        if name in sensor_results:
            r = sensor_results[name]
            print(f"  {name:<25} {r['n_sensors']:<5} {r['ens_mae']:<8.2f} {r['ens_r']:<8.3f} {r['n_feats_avail']}")

    print("\nPADS TRANSFER:")
    if isinstance(pads_results, dict) and "zero_shot_bal_acc" in pads_results:
        print(f"  Zero-shot: {pads_results['zero_shot_bal_acc']:.3f} ± {pads_results['zero_shot_std']:.3f}")
        print(f"  PADS-only: {pads_results['pads_only_bal_acc']:.3f} ± {pads_results['pads_only_std']:.3f}")
    else:
        print(f"  {pads_results}")

    print("\nTASK GENERALIZATION:")
    print(f"  {'Config':<25} {'Tasks':<5} {'MAE':<8} {'r':<8}")
    print("  " + "-" * 45)
    for name in ["all_5", "gait_only_2", "selfpace_only_1", "tug_only_1",
                  "no_balance_4", "no_tandem_4"]:
        if name in task_results:
            r = task_results[name]
            print(f"  {name:<25} {r['n_tasks']:<5} {r['ens_mae']:<8.2f} {r['ens_r']:<8.3f}")

    print(f"\nTotal time: {elapsed/60:.1f} min")
    print(f"Results: {RESULTS_FILE}")


if __name__ == "__main__":
    main()

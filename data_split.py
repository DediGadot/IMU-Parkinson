"""
Shared data loading and splitting for WearGait-PD experiments.
==============================================================
Provides:
1. Deterministic stratified held-out test set (20% of subjects)
2. Per-fold train/val split within CV (val for early stopping only)
3. Consistent data loading across all experiments

Usage:
    from data_split import load_split, load_windows_for_subjects
    split = load_split()  # returns {"dev_sids", "test_sids", "subjects"}
"""
import os
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedShuffleSplit, GroupKFold
from project_paths import DATA_DIR, SPLIT_FILE, ensure_parent

DATA_DIR = str(DATA_DIR)
SPLIT_FILE = str(SPLIT_FILE)

FS = 100
WINDOW_LEN = 1000
STRIDE_LEN = 500

SENSORS = [
    "LowerBack", "R_Wrist", "L_Wrist",
    "R_MidLatThigh", "L_MidLatThigh",
    "R_LatShank", "L_LatShank",
    "R_DorsalFoot", "L_DorsalFoot",
    "R_Ankle", "L_Ankle",
    "Xiphoid", "Forehead",
]
IMU_COLS = []
for s in SENSORS:
    IMU_COLS.extend([f"{s}_Acc_X", f"{s}_Acc_Y", f"{s}_Acc_Z",
                     f"{s}_Gyr_X", f"{s}_Gyr_Y", f"{s}_Gyr_Z"])
N_CH = len(IMU_COLS)  # 78


def parse_clinical():
    """Parse clinical data, return subjects with valid UPDRS-III.

    Uses sum of available UPDRS-III subitems (skipna=True). Subjects with
    partially missing subitems (e.g. 32/33) get the sum of present items.
    Only subjects where ALL subitems are NaN are excluded.
    """
    subjects = {}
    for filename, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        df = pd.read_csv(os.path.join(DATA_DIR, filename), header=1)
        u3cols = [c for c in df.columns if c.startswith("MDSUPDRS_3-")]
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            u3_values = pd.to_numeric(row[u3cols], errors="coerce")
            u3_values = u3_values.mask((u3_values < 0) | (u3_values > 4))
            if int(u3_values.notna().sum()) == 0:
                continue
            u3 = u3_values.sum()
            if np.isnan(u3):
                continue
            subjects[sid] = {
                "group": group,
                "label": 1 if group == "PD" else 0,
                "updrs3": float(u3),
            }
    return subjects


def _updrs_bin(score):
    """Bin UPDRS-III score for stratification.
    Bins: 0 (HC-like), 1-10 (mild), 11-20 (moderate), 21-35 (moderate-severe), 36+ (severe)
    """
    if score <= 0:
        return 0
    elif score <= 10:
        return 1
    elif score <= 20:
        return 2
    elif score <= 35:
        return 3
    else:
        return 4


def _get_valid_sids(subjects, tasks=("SelfPace", "HurriedPace")):
    """Return subject IDs that have at least one valid CSV with all sensors."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    valid = set()
    for task in tasks:
        for sid, info in subjects.items():
            csv_dir = pd_dir if info["group"] == "PD" else hc_dir
            csv_path = os.path.join(csv_dir, f"{sid}_{task}.csv")
            if not os.path.exists(csv_path):
                continue
            try:
                df = pd.read_csv(csv_path, nrows=5)
            except Exception:
                continue
            missing = [c for c in IMU_COLS if c not in df.columns]
            if not missing:
                valid.add(sid)
    return sorted(valid)


def create_split(seed=42):
    """Create and save deterministic train/test split."""
    subjects = parse_clinical()
    valid_sids = _get_valid_sids(subjects)

    sids = np.array(valid_sids)
    scores = np.array([subjects[s]["updrs3"] for s in sids])
    bins = np.array([_updrs_bin(s) for s in scores])

    # Stratified 80/20 split
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    dev_idx, test_idx = next(sss.split(sids, bins))

    dev_sids = sids[dev_idx].tolist()
    test_sids = sids[test_idx].tolist()

    # Verify distribution match
    dev_bins = bins[dev_idx]
    test_bins = bins[test_idx]

    split_info = {
        "seed": seed,
        "dev_sids": dev_sids,
        "test_sids": test_sids,
        "n_dev": len(dev_sids),
        "n_test": len(test_sids),
    }

    split_path = Path(SPLIT_FILE)
    ensure_parent(split_path)
    split_path.write_text(json.dumps(split_info, indent=2) + "\n")

    print(f"Split created: {len(dev_sids)} dev + {len(test_sids)} test subjects")
    print(f"  Dev  UPDRS bins: {np.bincount(dev_bins, minlength=5).tolist()}")
    print(f"  Test UPDRS bins: {np.bincount(test_bins, minlength=5).tolist()}")
    dev_scores = scores[dev_idx]
    test_scores = scores[test_idx]
    print(f"  Dev  UPDRS: mean={dev_scores.mean():.1f}, std={dev_scores.std():.1f}, "
          f"range=[{dev_scores.min():.0f}, {dev_scores.max():.0f}]")
    print(f"  Test UPDRS: mean={test_scores.mean():.1f}, std={test_scores.std():.1f}, "
          f"range=[{test_scores.min():.0f}, {test_scores.max():.0f}]")
    return split_info


def load_split():
    """Load existing split or create new one."""
    if os.path.exists(SPLIT_FILE):
        with open(SPLIT_FILE) as f:
            split = json.load(f)
        print(f"Loaded split: {split['n_dev']} dev + {split['n_test']} test subjects")
        return split
    return create_split()


def load_windows_for_sids(subjects, sid_list, tasks=("SelfPace", "HurriedPace")):
    """Load windows for a specific list of subject IDs."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    all_X, all_y, all_sids = [], [], []

    for task in tasks:
        for sid in sid_list:
            if sid not in subjects:
                continue
            info = subjects[sid]
            csv_dir = pd_dir if info["group"] == "PD" else hc_dir
            csv_path = os.path.join(csv_dir, f"{sid}_{task}.csv")
            if not os.path.exists(csv_path):
                continue
            try:
                df = pd.read_csv(csv_path)
            except Exception:
                continue
            missing = [c for c in IMU_COLS if c not in df.columns]
            if missing:
                continue
            data = df[IMU_COLS].values.astype(np.float32)
            data = np.nan_to_num(data, nan=0.0)
            if len(data) < WINDOW_LEN:
                continue
            mean = data.mean(axis=0, keepdims=True)
            std = data.std(axis=0, keepdims=True) + 1e-8
            data = (data - mean) / std
            for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
                all_X.append(data[start:start + WINDOW_LEN])
                all_y.append(info["updrs3"])
                all_sids.append(sid)

    if not all_X:
        return np.array([]), np.array([]), np.array([])

    X = np.stack(all_X)
    y = np.array(all_y, dtype=np.float32)
    sids = np.array(all_sids)
    return X, y, sids


def load_unlabeled_for_sids(subjects, sid_list, tasks):
    """Load windows without labels (for pretraining). Uses all subjects including those without UPDRS."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    all_X = []

    for task in tasks:
        for sid in sid_list:
            if sid not in subjects:
                continue
            info = subjects[sid]
            csv_dir = pd_dir if info["group"] == "PD" else hc_dir
            csv_path = os.path.join(csv_dir, f"{sid}_{task}.csv")
            if not os.path.exists(csv_path):
                continue
            try:
                df = pd.read_csv(csv_path)
            except Exception:
                continue
            missing = [c for c in IMU_COLS if c not in df.columns]
            if missing:
                continue
            data = df[IMU_COLS].values.astype(np.float32)
            data = np.nan_to_num(data, nan=0.0)
            if len(data) < WINDOW_LEN:
                continue
            mean = data.mean(axis=0, keepdims=True)
            std = data.std(axis=0, keepdims=True) + 1e-8
            data = (data - mean) / std
            for start in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
                all_X.append(data[start:start + WINDOW_LEN])

    if not all_X:
        return np.array([])
    return np.stack(all_X)


def cv_split_with_val(X, y, sids, n_splits=5, val_frac=0.1, seed=42):
    """Generator yielding (train_idx, val_idx, test_idx) per fold.

    Within each GroupKFold test fold:
    - test_idx: the fold's test subjects (untouched, for metrics)
    - val_idx: 10% of training subjects (for early stopping only)
    - train_idx: remaining training subjects
    """
    gkf = GroupKFold(n_splits=n_splits)
    rng = np.random.RandomState(seed)

    for fold_train_idx, test_idx in gkf.split(X, y, sids):
        # Split fold_train into actual train + val by subject
        train_sids_unique = np.unique(sids[fold_train_idx])
        rng.shuffle(train_sids_unique)
        n_val_subj = max(1, int(len(train_sids_unique) * val_frac))
        val_subjects = set(train_sids_unique[:n_val_subj])

        val_idx = np.array([i for i in fold_train_idx if sids[i] in val_subjects])
        train_idx = np.array([i for i in fold_train_idx if sids[i] not in val_subjects])

        yield train_idx, val_idx, test_idx


if __name__ == "__main__":
    split = create_split()
    subjects = parse_clinical()
    print(f"\nLoading dev windows...")
    X_dev, y_dev, sids_dev = load_windows_for_sids(
        subjects, split["dev_sids"], tasks=("SelfPace", "HurriedPace"))
    print(f"Dev: {len(X_dev)} windows, {len(np.unique(sids_dev))} subjects")

    print(f"\nLoading test windows...")
    X_test, y_test, sids_test = load_windows_for_sids(
        subjects, split["test_sids"], tasks=("SelfPace", "HurriedPace"))
    print(f"Test: {len(X_test)} windows, {len(np.unique(sids_test))} subjects")

    print(f"\nCV split check (dev set):")
    for fold, (tr, va, te) in enumerate(cv_split_with_val(X_dev, y_dev, sids_dev)):
        print(f"  Fold {fold+1}: train={len(tr)} val={len(va)} test={len(te)} windows "
              f"({len(np.unique(sids_dev[tr]))}/"
              f"{len(np.unique(sids_dev[va]))}/"
              f"{len(np.unique(sids_dev[te]))} subjects)")

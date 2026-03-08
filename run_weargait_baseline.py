"""
WearGait-PD Baseline Experiment
================================
1. Parse clinical CSVs → subject-level UPDRS + H&Y labels
2. Load wrist IMU from SelfPace CSVs → extract gait features
3. Run XGBoost/RF baselines with LOSO CV for:
   - UPDRS-III total score regression
   - H&Y stage classification
   - PD vs HC classification
"""
import os
import glob
import numpy as np
import pandas as pd
from scipy import signal, stats
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import (
    accuracy_score, f1_score, roc_auc_score, mean_absolute_error,
    mean_squared_error, classification_report, confusion_matrix
)
from sklearn.preprocessing import LabelEncoder
import warnings
warnings.filterwarnings("ignore")

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
    print("xgboost not available, using RF only")

DATA_DIR = "/root/pd-imu/data/raw/weargait-pd"


# ── 1. Parse Clinical Data ──────────────────────────────────────────────

def parse_clinical_data():
    """Parse PD and Control clinical CSVs, extract UPDRS and H&Y scores."""
    pd_csv = os.path.join(DATA_DIR, "PD - Demographic+Clinical - datasetV1.csv")
    hc_csv = os.path.join(DATA_DIR, "CONTROLS - Demographic+Clinical - datasetV1.csv")

    # PD clinical (row 0 = category headers, row 1 = column names)
    pd_df = pd.read_csv(pd_csv, header=1)
    print(f"PD clinical CSV: {pd_df.shape[0]} rows, {pd_df.shape[1]} cols")
    print(f"PD columns (first 30): {list(pd_df.columns[:30])}")

    # HC clinical
    hc_df = pd.read_csv(hc_csv, header=1)
    print(f"HC clinical CSV: {hc_df.shape[0]} rows, {hc_df.shape[1]} cols")

    subjects = {}

    # Parse PD subjects
    for _, row in pd_df.iterrows():
        sid = str(row.get("Subject ID", "")).strip()
        if not sid or sid == "nan":
            continue

        # UPDRS Part III total: sum of MDSUPDRS_3-* columns
        updrs3_cols = [c for c in pd_df.columns if c.startswith("MDSUPDRS_3-")]
        updrs3_vals = pd.to_numeric(row[updrs3_cols], errors="coerce")
        updrs3_total = updrs3_vals.sum() if updrs3_vals.notna().sum() > 0 else np.nan

        # UPDRS Part II total
        updrs2_cols = [c for c in pd_df.columns if c.startswith("MDSUPDRS_2-")]
        updrs2_vals = pd.to_numeric(row[updrs2_cols], errors="coerce")
        updrs2_total = updrs2_vals.sum() if updrs2_vals.notna().sum() > 0 else np.nan

        # H&Y
        hy_raw = row.get("Modified Hoehn & Yahr Score", np.nan)
        hy = pd.to_numeric(hy_raw, errors="coerce")

        # Demographics
        age = pd.to_numeric(row.get("Age (years)", np.nan), errors="coerce")
        gender = str(row.get("Gender", "")).strip()
        years_dx = pd.to_numeric(row.get("Years since PD diagnosis", np.nan), errors="coerce")

        subjects[sid] = {
            "group": "PD",
            "updrs3_total": updrs3_total,
            "updrs2_total": updrs2_total,
            "hy": hy,
            "age": age,
            "gender": gender,
            "years_since_dx": years_dx,
        }

    # Parse HC subjects
    for _, row in hc_df.iterrows():
        sid = str(row.get("Subject ID", "")).strip()
        if not sid or sid == "nan":
            continue

        updrs3_cols = [c for c in hc_df.columns if c.startswith("MDSUPDRS_3-")]
        updrs3_vals = pd.to_numeric(row[updrs3_cols], errors="coerce")
        updrs3_total = updrs3_vals.sum() if updrs3_vals.notna().sum() > 0 else np.nan

        hy_raw = row.get("Modified Hoehn & Yahr Score", np.nan)
        hy = pd.to_numeric(hy_raw, errors="coerce")

        age = pd.to_numeric(row.get("Age", np.nan), errors="coerce")
        gender = str(row.get("Gender", "")).strip()

        subjects[sid] = {
            "group": "HC",
            "updrs3_total": updrs3_total,
            "updrs2_total": np.nan,
            "hy": hy,
            "age": age,
            "gender": gender,
            "years_since_dx": 0.0,
        }

    print(f"\nTotal subjects with clinical data: {len(subjects)}")
    pd_count = sum(1 for s in subjects.values() if s["group"] == "PD")
    hc_count = sum(1 for s in subjects.values() if s["group"] == "HC")
    print(f"  PD: {pd_count}, HC: {hc_count}")

    # UPDRS-III stats
    updrs3_vals = [s["updrs3_total"] for s in subjects.values() if not np.isnan(s["updrs3_total"])]
    print(f"  UPDRS-III available: {len(updrs3_vals)}, range: [{min(updrs3_vals):.0f}, {max(updrs3_vals):.0f}], mean: {np.mean(updrs3_vals):.1f}")

    # H&Y stats
    hy_vals = [s["hy"] for s in subjects.values() if not np.isnan(s["hy"])]
    print(f"  H&Y available: {len(hy_vals)}, values: {sorted(set(hy_vals))}")

    return subjects


# ── 2. Extract IMU Features ─────────────────────────────────────────────

WRIST_ACC_COLS = ["R_Wrist_Acc_X", "R_Wrist_Acc_Y", "R_Wrist_Acc_Z"]
WRIST_GYR_COLS = ["R_Wrist_Gyr_X", "R_Wrist_Gyr_Y", "R_Wrist_Gyr_Z"]
LBACK_ACC_COLS = ["LowerBack_Acc_X", "LowerBack_Acc_Y", "LowerBack_Acc_Z"]
LBACK_GYR_COLS = ["LowerBack_Gyr_X", "LowerBack_Gyr_Y", "LowerBack_Gyr_Z"]
FS = 100  # Hz


def compute_features_from_imu(acc, gyro, prefix=""):
    """Extract gait features from 3-axis acc + 3-axis gyro arrays.

    Args:
        acc: (N, 3) accelerometer data
        gyro: (N, 3) gyroscope data
        prefix: string prefix for feature names

    Returns:
        dict of feature_name -> value
    """
    feats = {}
    if acc.shape[0] < 200:  # need at least 2 seconds
        return feats

    # Remove NaN rows
    valid = ~(np.isnan(acc).any(axis=1) | np.isnan(gyro).any(axis=1))
    acc = acc[valid]
    gyro = gyro[valid]
    if acc.shape[0] < 200:
        return feats

    # Acc magnitude
    acc_mag = np.sqrt(np.sum(acc**2, axis=1))

    # ── Statistical features ──
    for i, axis in enumerate(["x", "y", "z"]):
        feats[f"{prefix}acc_{axis}_mean"] = np.mean(acc[:, i])
        feats[f"{prefix}acc_{axis}_std"] = np.std(acc[:, i])
        feats[f"{prefix}acc_{axis}_range"] = np.ptp(acc[:, i])
        feats[f"{prefix}gyr_{axis}_mean"] = np.mean(gyro[:, i])
        feats[f"{prefix}gyr_{axis}_std"] = np.std(gyro[:, i])
        feats[f"{prefix}gyr_{axis}_range"] = np.ptp(gyro[:, i])

    feats[f"{prefix}acc_mag_mean"] = np.mean(acc_mag)
    feats[f"{prefix}acc_mag_std"] = np.std(acc_mag)

    # ── Jerk (derivative of acc) ──
    jerk = np.diff(acc, axis=0) * FS
    jerk_mag = np.sqrt(np.sum(jerk**2, axis=1))
    feats[f"{prefix}jerk_rms"] = np.sqrt(np.mean(jerk_mag**2))
    feats[f"{prefix}jerk_mean"] = np.mean(jerk_mag)

    # ── Tremor power (4-6 Hz band from acc magnitude) ──
    try:
        freqs, psd = signal.welch(acc_mag, fs=FS, nperseg=min(256, len(acc_mag)))
        tremor_mask = (freqs >= 4) & (freqs <= 6)
        total_mask = freqs > 0.5
        tremor_power = np.trapz(psd[tremor_mask], freqs[tremor_mask]) if tremor_mask.sum() > 1 else 0
        total_power = np.trapz(psd[total_mask], freqs[total_mask]) if total_mask.sum() > 1 else 1
        feats[f"{prefix}tremor_power"] = tremor_power
        feats[f"{prefix}tremor_ratio"] = tremor_power / max(total_power, 1e-10)

        # Dominant frequency
        feats[f"{prefix}dominant_freq"] = freqs[np.argmax(psd[freqs > 0.5]) + np.searchsorted(freqs, 0.5)]

        # Spectral entropy
        psd_norm = psd[total_mask] / (np.sum(psd[total_mask]) + 1e-10)
        psd_norm = psd_norm[psd_norm > 0]
        feats[f"{prefix}spectral_entropy"] = -np.sum(psd_norm * np.log2(psd_norm + 1e-10))
    except Exception:
        pass

    # ── Stride regularity (autocorrelation) ──
    try:
        acc_detrend = acc_mag - np.mean(acc_mag)
        autocorr = np.correlate(acc_detrend, acc_detrend, mode="full")
        autocorr = autocorr[len(autocorr) // 2:]
        autocorr = autocorr / (autocorr[0] + 1e-10)

        # Find peaks in autocorrelation (stride period ~0.8-2.0 sec)
        min_lag = int(0.8 * FS)
        max_lag = min(int(2.0 * FS), len(autocorr) - 1)
        if max_lag > min_lag:
            peaks, props = signal.find_peaks(autocorr[min_lag:max_lag], height=0.1)
            if len(peaks) > 0:
                best_peak = peaks[np.argmax(props["peak_heights"])]
                stride_period = (best_peak + min_lag) / FS
                stride_regularity = props["peak_heights"][np.argmax(props["peak_heights"])]
                feats[f"{prefix}stride_period"] = stride_period
                feats[f"{prefix}stride_regularity"] = stride_regularity
                feats[f"{prefix}cadence"] = 60.0 / stride_period  # steps/min (approx)
    except Exception:
        pass

    # ── Sample entropy (complexity) ──
    try:
        # Simplified sample entropy on downsampled signal
        ds = acc_mag[::10][:100]  # 100 points max
        if len(ds) > 20:
            m = 2
            r = 0.2 * np.std(ds)
            N = len(ds)
            count_m = 0
            count_m1 = 0
            for i in range(N - m):
                for j in range(i + 1, N - m):
                    if np.max(np.abs(ds[i:i+m] - ds[j:j+m])) < r:
                        count_m += 1
                        if np.abs(ds[i+m] - ds[j+m]) < r:
                            count_m1 += 1
            if count_m > 0 and count_m1 > 0:
                feats[f"{prefix}sample_entropy"] = -np.log(count_m1 / count_m)
    except Exception:
        pass

    # ── Gyroscope features ──
    gyro_mag = np.sqrt(np.sum(gyro**2, axis=1))
    feats[f"{prefix}gyro_mag_mean"] = np.mean(gyro_mag)
    feats[f"{prefix}gyro_mag_std"] = np.std(gyro_mag)
    feats[f"{prefix}gyro_mag_max"] = np.max(gyro_mag)

    # ── Arm swing asymmetry (peak-to-peak of acc in swing direction) ──
    feats[f"{prefix}acc_swing_p2p"] = np.ptp(acc[:, 1])  # Y-axis typically swing

    return feats


def load_and_extract_features(subjects, task="SelfPace"):
    """Load sensor CSVs and extract features for each subject.

    Args:
        subjects: dict from parse_clinical_data()
        task: which task to load (SelfPace, HurriedPace, Balance, TUG, TandemGait)

    Returns:
        features_df: DataFrame with one row per subject
        labels: dict of subject_id -> label dict
    """
    pd_csv_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_csv_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")

    all_features = []
    valid_subjects = []

    for sid, info in subjects.items():
        # Find CSV file
        if info["group"] == "PD":
            csv_path = os.path.join(pd_csv_dir, f"{sid}_{task}.csv")
        else:
            csv_path = os.path.join(hc_csv_dir, f"{sid}_{task}.csv")

        if not os.path.exists(csv_path):
            continue

        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            print(f"  Error reading {sid}: {e}")
            continue

        # Check required columns exist
        wrist_cols = WRIST_ACC_COLS + WRIST_GYR_COLS
        lback_cols = LBACK_ACC_COLS + LBACK_GYR_COLS
        has_wrist = all(c in df.columns for c in wrist_cols)
        has_lback = all(c in df.columns for c in lback_cols)

        if not has_wrist:
            continue

        # Extract wrist features
        wrist_acc = df[WRIST_ACC_COLS].values
        wrist_gyro = df[WRIST_GYR_COLS].values
        wrist_feats = compute_features_from_imu(wrist_acc, wrist_gyro, prefix="wrist_")

        if not wrist_feats:
            continue

        # Extract lower back features if available
        if has_lback:
            lback_acc = df[LBACK_ACC_COLS].values
            lback_gyro = df[LBACK_GYR_COLS].values
            lback_feats = compute_features_from_imu(lback_acc, lback_gyro, prefix="lback_")
            wrist_feats.update(lback_feats)

        wrist_feats["subject_id"] = sid
        wrist_feats["duration_sec"] = len(df) / FS
        all_features.append(wrist_feats)
        valid_subjects.append(sid)

    features_df = pd.DataFrame(all_features)
    print(f"\nExtracted features for {len(features_df)} subjects ({task} task)")
    print(f"  Feature columns: {len(features_df.columns) - 2}")
    return features_df, valid_subjects


# ── 3. Run Baselines ────────────────────────────────────────────────────

def run_pd_vs_hc(features_df, subjects):
    """PD vs HC classification with LOSO CV."""
    print("\n" + "="*60)
    print("TASK 1: PD vs HC Classification (LOSO)")
    print("="*60)

    sids = features_df["subject_id"].values
    labels = np.array([1 if subjects[s]["group"] == "PD" else 0 for s in sids])

    feat_cols = [c for c in features_df.columns if c not in ("subject_id", "duration_sec")]
    X = features_df[feat_cols].fillna(0).values

    logo = LeaveOneGroupOut()
    groups = sids

    results = {}

    for name, clf in [
        ("RandomForest", RandomForestClassifier(n_estimators=200, max_depth=10, random_state=42)),
    ] + ([("XGBoost", xgb.XGBClassifier(
        n_estimators=200, max_depth=6, learning_rate=0.1,
        eval_metric="logloss", random_state=42
    ))] if HAS_XGB else []):

        y_true_all, y_pred_all, y_prob_all = [], [], []

        for train_idx, test_idx in logo.split(X, labels, groups):
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = labels[train_idx], labels[test_idx]

            clf.fit(X_train, y_train)
            y_pred = clf.predict(X_test)
            y_prob = clf.predict_proba(X_test)[:, 1] if hasattr(clf, "predict_proba") else y_pred

            y_true_all.extend(y_test)
            y_pred_all.extend(y_pred)
            y_prob_all.extend(y_prob)

        y_true_all = np.array(y_true_all)
        y_pred_all = np.array(y_pred_all)
        y_prob_all = np.array(y_prob_all)

        acc = accuracy_score(y_true_all, y_pred_all)
        f1 = f1_score(y_true_all, y_pred_all, average="macro")
        try:
            auc = roc_auc_score(y_true_all, y_prob_all)
        except ValueError:
            auc = 0.0

        results[name] = {"accuracy": acc, "f1_macro": f1, "auc": auc}
        print(f"\n{name}: Acc={acc:.3f}, F1={f1:.3f}, AUC={auc:.3f}")
        print(classification_report(y_true_all, y_pred_all, target_names=["HC", "PD"]))

        # Feature importance
        if hasattr(clf, "feature_importances_"):
            imp = clf.feature_importances_
            top_idx = np.argsort(imp)[::-1][:10]
            print(f"Top 10 features ({name}):")
            for i in top_idx:
                print(f"  {feat_cols[i]}: {imp[i]:.4f}")

    return results


def run_updrs3_regression(features_df, subjects):
    """UPDRS-III total score regression with LOSO CV."""
    print("\n" + "="*60)
    print("TASK 2: UPDRS-III Total Score Regression (LOSO)")
    print("="*60)

    # Filter to subjects with valid UPDRS-III
    valid_mask = []
    updrs_labels = []
    for sid in features_df["subject_id"]:
        val = subjects[sid]["updrs3_total"]
        if not np.isnan(val):
            valid_mask.append(True)
            updrs_labels.append(val)
        else:
            valid_mask.append(False)

    valid_mask = np.array(valid_mask)
    if valid_mask.sum() < 10:
        print(f"Only {valid_mask.sum()} subjects with UPDRS-III scores. Skipping.")
        return {}

    sub_df = features_df[valid_mask].reset_index(drop=True)
    y = np.array(updrs_labels)
    sids = sub_df["subject_id"].values

    feat_cols = [c for c in sub_df.columns if c not in ("subject_id", "duration_sec")]
    X = sub_df[feat_cols].fillna(0).values

    print(f"Subjects with UPDRS-III: {len(y)}")
    print(f"UPDRS-III range: [{y.min():.0f}, {y.max():.0f}], mean: {y.mean():.1f}, std: {y.std():.1f}")

    logo = LeaveOneGroupOut()
    results = {}

    for name, reg in [
        ("RandomForest", RandomForestRegressor(n_estimators=200, max_depth=10, random_state=42)),
    ] + ([("XGBoost", xgb.XGBRegressor(
        n_estimators=200, max_depth=6, learning_rate=0.1, random_state=42
    ))] if HAS_XGB else []):

        y_true_all, y_pred_all = [], []

        for train_idx, test_idx in logo.split(X, y, sids):
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]

            reg.fit(X_train, y_train)
            y_pred = reg.predict(X_test)

            y_true_all.extend(y_test)
            y_pred_all.extend(y_pred)

        y_true_all = np.array(y_true_all)
        y_pred_all = np.array(y_pred_all)

        mae = mean_absolute_error(y_true_all, y_pred_all)
        rmse = np.sqrt(mean_squared_error(y_true_all, y_pred_all))
        r, p = stats.pearsonr(y_true_all, y_pred_all)

        results[name] = {"mae": mae, "rmse": rmse, "pearson_r": r, "p_value": p}
        print(f"\n{name}: MAE={mae:.2f}, RMSE={rmse:.2f}, Pearson r={r:.3f} (p={p:.4f})")

        # Feature importance
        if hasattr(reg, "feature_importances_"):
            imp = reg.feature_importances_
            top_idx = np.argsort(imp)[::-1][:10]
            print(f"Top 10 features ({name}):")
            for i in top_idx:
                print(f"  {feat_cols[i]}: {imp[i]:.4f}")

    return results


def run_hy_classification(features_df, subjects):
    """H&Y stage classification with LOSO CV."""
    print("\n" + "="*60)
    print("TASK 3: H&Y Stage Classification (LOSO)")
    print("="*60)

    # Filter to subjects with valid H&Y (PD only, HC is typically 0)
    valid_mask = []
    hy_labels = []
    for sid in features_df["subject_id"]:
        val = subjects[sid]["hy"]
        group = subjects[sid]["group"]
        if not np.isnan(val) and group == "PD":
            valid_mask.append(True)
            hy_labels.append(val)
        else:
            valid_mask.append(False)

    valid_mask = np.array(valid_mask)
    if valid_mask.sum() < 10:
        print(f"Only {valid_mask.sum()} PD subjects with H&Y scores. Skipping.")
        return {}

    sub_df = features_df[valid_mask].reset_index(drop=True)
    y = np.array(hy_labels)
    sids = sub_df["subject_id"].values

    feat_cols = [c for c in sub_df.columns if c not in ("subject_id", "duration_sec")]
    X = sub_df[feat_cols].fillna(0).values

    # Bin H&Y for classification (group 0.5 increments)
    unique_hy = sorted(set(y))
    print(f"PD subjects with H&Y: {len(y)}")
    print(f"H&Y distribution: {dict(zip(*np.unique(y, return_counts=True)))}")

    # If too few classes or samples, bin into mild/moderate/severe
    if len(unique_hy) > 3:
        # Bin: 1-2 = mild, 2.5-3 = moderate, 3.5+ = severe
        y_binned = np.where(y <= 2, 0, np.where(y <= 3, 1, 2))
        class_names = ["Mild (1-2)", "Moderate (2.5-3)", "Severe (3.5+)"]
    else:
        y_binned = LabelEncoder().fit_transform(y)
        class_names = [str(v) for v in unique_hy]

    # Check we have enough samples per class
    unique_bins, counts = np.unique(y_binned, return_counts=True)
    print(f"Binned distribution: {dict(zip(class_names, counts))}")

    if len(unique_bins) < 2:
        print("Only one class present. Skipping.")
        return {}

    logo = LeaveOneGroupOut()
    results = {}

    clf = RandomForestClassifier(n_estimators=200, max_depth=10, random_state=42)
    y_true_all, y_pred_all = [], []

    for train_idx, test_idx in logo.split(X, y_binned, sids):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y_binned[train_idx], y_binned[test_idx]

        # Skip if train has <2 classes
        if len(np.unique(y_train)) < 2:
            continue

        clf.fit(X_train, y_train)
        y_pred = clf.predict(X_test)

        y_true_all.extend(y_test)
        y_pred_all.extend(y_pred)

    if len(y_true_all) == 0:
        print("No valid folds. Skipping.")
        return {}

    y_true_all = np.array(y_true_all)
    y_pred_all = np.array(y_pred_all)

    acc = accuracy_score(y_true_all, y_pred_all)
    f1 = f1_score(y_true_all, y_pred_all, average="macro")

    results["RandomForest"] = {"accuracy": acc, "f1_macro": f1}
    print(f"\nRandomForest: Acc={acc:.3f}, F1 Macro={f1:.3f}")

    present_classes = sorted(set(y_true_all) | set(y_pred_all))
    present_names = [class_names[i] for i in present_classes if i < len(class_names)]
    print(classification_report(y_true_all, y_pred_all, target_names=present_names))

    return results


# ── 4. Main ─────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("WearGait-PD Baseline Experiment")
    print("=" * 60)

    # Step 1: Parse clinical data
    subjects = parse_clinical_data()

    # Step 2: Extract features from SelfPace task
    features_df, valid_sids = load_and_extract_features(subjects, task="SelfPace")

    if len(features_df) < 10:
        print("Not enough subjects with valid sensor data. Aborting.")
        return

    # Step 3: Run baselines
    clf_results = run_pd_vs_hc(features_df, subjects)
    reg_results = run_updrs3_regression(features_df, subjects)
    hy_results = run_hy_classification(features_df, subjects)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Subjects processed: {len(features_df)} (of {len(subjects)} with clinical data)")
    print(f"Task: SelfPace (self-paced walking)")
    print(f"Sensor: Right wrist + Lower back IMU (acc + gyro)")

    print("\n--- PD vs HC ---")
    for name, r in clf_results.items():
        print(f"  {name}: Acc={r['accuracy']:.3f}, F1={r['f1_macro']:.3f}, AUC={r['auc']:.3f}")

    print("\n--- UPDRS-III Regression ---")
    for name, r in reg_results.items():
        print(f"  {name}: MAE={r['mae']:.2f}, RMSE={r['rmse']:.2f}, r={r['pearson_r']:.3f}")

    print("\n--- H&Y Classification ---")
    for name, r in hy_results.items():
        print(f"  {name}: Acc={r['accuracy']:.3f}, F1={r['f1_macro']:.3f}")


if __name__ == "__main__":
    main()

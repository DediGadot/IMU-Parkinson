#!/usr/bin/env python3
"""
Baseline experiment on PhysioNet Gait-PD dataset.
Extracts gait features from vertical ground reaction force,
runs XGBoost/RF for PD vs Control classification.
"""
import sys
sys.path.insert(0, "/root/pd-imu")

import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict
from sklearn.metrics import accuracy_score, f1_score, classification_report, roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import xgboost as xgb
from scipy import signal
from scipy.stats import entropy
import warnings
warnings.filterwarnings("ignore")


DATA_DIR = Path("/root/pd-imu/data/raw/gait-pd/physionet.org/files/gaitpdb/1.0.0")


def load_gaitpd_txt(data_dir: Path) -> list[dict]:
    """Load all .txt files from gaitpdb.

    Format: tab-separated, 19 columns
    Col 0: time (s), Cols 1-8: left foot sensors, Cols 9-16: right foot sensors,
    Col 17: total left, Col 18: total right
    OR: Col 17: total force, Col 18: unused

    Filename convention:
    - Ga/Ju/Si = study (Garcia/Juutalainen/Silvestri)
    - Co = control, Pt = patient (PD)
    - Number = subject ID
    - _01/_02 = trial number
    """
    txt_files = sorted(data_dir.glob("*.txt"))
    records = []

    for f in txt_files:
        name = f.stem
        # Parse filename
        study = name[:2]  # Ga, Ju, Si
        group_code = name[2:4]  # Co or Pt

        if group_code not in ("Co", "Pt"):
            continue

        is_pd = group_code == "Pt"

        # Extract subject number
        rest = name[4:]
        parts = rest.split("_")
        subject_num = parts[0]
        trial = parts[1] if len(parts) > 1 else "01"

        subject_id = f"{study}_{group_code}{subject_num}"

        try:
            data = np.loadtxt(str(f), delimiter="\t")
        except Exception:
            try:
                data = pd.read_csv(str(f), sep="\t", header=None).values
            except Exception as e:
                print(f"  Skipping {name}: {e}")
                continue

        if data.ndim != 2 or data.shape[1] < 19:
            continue

        time_col = data[:, 0]
        left_sensors = data[:, 1:9]    # 8 left foot sensors
        right_sensors = data[:, 9:17]  # 8 right foot sensors
        total_left = data[:, 17]
        total_right = data[:, 18]

        # Sampling rate from time column
        dt = np.median(np.diff(time_col))
        fs = 1.0 / dt if dt > 0 else 100.0

        records.append({
            "subject_id": subject_id,
            "trial": trial,
            "study": study,
            "is_pd": is_pd,
            "time": time_col,
            "left_sensors": left_sensors,
            "right_sensors": right_sensors,
            "total_left": total_left,
            "total_right": total_right,
            "total_force": total_left + total_right,
            "fs": fs,
        })

    return records


def extract_gait_features(record: dict) -> dict:
    """Extract gait features from a single walking trial."""
    total = record["total_force"]
    left = record["total_left"]
    right = record["total_right"]
    fs = record["fs"]
    n = len(total)

    if n < int(2 * fs):  # need at least 2 seconds
        return None

    features = {}

    # 1. Stride detection from total force
    nyq = fs / 2
    low = max(0.5 / nyq, 0.01)
    high = min(3.0 / nyq, 0.99)
    b, a = signal.butter(4, [low, high], btype="band")
    filtered = signal.filtfilt(b, a, total)

    # Autocorrelation for stride period
    ac = np.correlate(filtered, filtered, mode="full")
    ac = ac[len(ac)//2:]
    ac = ac / (ac[0] + 1e-10)

    min_s = int(0.4 * fs)
    max_s = int(2.5 * fs)
    search = ac[min_s:max_s] if max_s < len(ac) else ac[min_s:]

    if len(search) > 0:
        peaks, _ = signal.find_peaks(search, height=0.2, distance=int(0.2 * fs))
        stride_period = (peaks[0] + min_s) / fs if len(peaks) > 0 else 1.0
    else:
        stride_period = 1.0

    # Find heel strikes
    hs, _ = signal.find_peaks(filtered, distance=int(stride_period * fs * 0.6))
    stride_times = np.diff(hs) / fs if len(hs) > 1 else np.array([stride_period])

    # 2. Temporal features
    features["stride_time_mean"] = np.mean(stride_times)
    features["stride_time_std"] = np.std(stride_times)
    features["stride_time_cv"] = np.std(stride_times) / (np.mean(stride_times) + 1e-10)

    # Step time (half-stride from alternating feet)
    step_times = stride_times / 2
    features["step_time_mean"] = np.mean(step_times)

    # 3. Step asymmetry
    if len(stride_times) >= 2:
        even = stride_times[0::2]
        odd = stride_times[1::2]
        min_len = min(len(even), len(odd))
        features["step_asymmetry"] = np.mean(np.abs(even[:min_len] - odd[:min_len]))
    else:
        features["step_asymmetry"] = 0.0

    # 4. Force features
    features["force_mean"] = np.mean(total)
    features["force_std"] = np.std(total)
    features["force_peak"] = np.max(total)
    features["force_rms"] = np.sqrt(np.mean(total**2))

    # 5. Left-right asymmetry
    left_power = np.mean(left**2)
    right_power = np.mean(right**2)
    features["lr_asymmetry"] = abs(left_power - right_power) / (left_power + right_power + 1e-10)

    # 6. Frequency domain
    freqs, psd = signal.welch(total, fs=fs, nperseg=min(256, n))
    features["dominant_freq"] = freqs[np.argmax(psd)]
    total_power = np.trapz(psd, freqs)

    # Spectral entropy
    psd_norm = psd / (np.sum(psd) + 1e-10)
    features["spectral_entropy"] = entropy(psd_norm + 1e-10)

    # 7. Regularity
    if stride_period > 0 and int(stride_period * fs) < len(ac):
        features["stride_regularity"] = ac[int(stride_period * fs)]
    else:
        features["stride_regularity"] = 0.0

    half_stride = int(stride_period * fs / 2)
    if half_stride < len(ac):
        features["step_regularity"] = ac[half_stride]
    else:
        features["step_regularity"] = 0.0

    # 8. Jerk (smoothness)
    jerk = np.diff(total) * fs
    features["jerk_rms"] = np.sqrt(np.mean(jerk**2))

    # 9. Harmonic ratio
    stride_freq = 1.0 / stride_period if stride_period > 0 else 1.0
    fft_vals = np.abs(np.fft.rfft(total))
    fft_freqs = np.fft.rfftfreq(n, 1.0 / fs)
    even_sum, odd_sum = 0.0, 0.0
    for h in range(1, 11):
        freq = h * stride_freq
        idx = np.argmin(np.abs(fft_freqs - freq))
        if h % 2 == 0:
            even_sum += fft_vals[idx]
        else:
            odd_sum += fft_vals[idx]
    features["harmonic_ratio"] = even_sum / (odd_sum + 1e-10)

    return features


def run_baseline():
    """Main baseline experiment."""
    print("=" * 60)
    print("GAIT-PD BASELINE EXPERIMENT")
    print("=" * 60)

    # Load data
    print("\nLoading Gait-PD dataset...")
    records = load_gaitpd_txt(DATA_DIR)
    print(f"  Loaded {len(records)} trials")

    pd_count = sum(1 for r in records if r["is_pd"])
    hc_count = sum(1 for r in records if not r["is_pd"])
    print(f"  PD: {pd_count} trials, HC: {hc_count} trials")

    subjects = set(r["subject_id"] for r in records)
    pd_subjects = set(r["subject_id"] for r in records if r["is_pd"])
    hc_subjects = set(r["subject_id"] for r in records if not r["is_pd"])
    print(f"  Unique subjects: {len(subjects)} ({len(pd_subjects)} PD, {len(hc_subjects)} HC)")

    # Extract features
    print("\nExtracting gait features...")
    feature_list = []
    labels = []
    group_ids = []

    for rec in records:
        feats = extract_gait_features(rec)
        if feats is None:
            continue
        feature_list.append(feats)
        labels.append(1 if rec["is_pd"] else 0)
        group_ids.append(rec["subject_id"])

    feature_names = list(feature_list[0].keys())
    X = np.array([[f[k] for k in feature_names] for f in feature_list])
    y = np.array(labels)
    groups = np.array(group_ids)

    print(f"  Features: {X.shape[1]} ({', '.join(feature_names[:5])}...)")
    print(f"  Samples: {X.shape[0]} ({sum(y==1)} PD, {sum(y==0)} HC)")

    # Handle NaN/Inf
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    # Model 1: XGBoost with LOSO CV
    print("\n--- XGBoost (Leave-One-Subject-Out CV) ---")
    logo = LeaveOneGroupOut()
    xgb_pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("xgb", xgb.XGBClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.1,
            subsample=0.8, colsample_bytree=0.8,
            eval_metric="logloss", random_state=42,
        )),
    ])

    xgb_preds = cross_val_predict(xgb_pipe, X, y, groups=groups, cv=logo)
    xgb_proba = cross_val_predict(xgb_pipe, X, y, groups=groups, cv=logo, method="predict_proba")[:, 1]

    xgb_acc = accuracy_score(y, xgb_preds)
    xgb_f1 = f1_score(y, xgb_preds, average="macro")
    xgb_auc = roc_auc_score(y, xgb_proba)

    print(f"  Accuracy: {xgb_acc:.4f}")
    print(f"  F1 Macro: {xgb_f1:.4f}")
    print(f"  AUC:      {xgb_auc:.4f}")
    print(classification_report(y, xgb_preds, target_names=["HC", "PD"]))

    # Model 2: Random Forest with LOSO CV
    print("--- Random Forest (Leave-One-Subject-Out CV) ---")
    rf_pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("rf", RandomForestClassifier(
            n_estimators=200, max_depth=10, random_state=42, n_jobs=-1,
        )),
    ])

    rf_preds = cross_val_predict(rf_pipe, X, y, groups=groups, cv=logo)
    rf_proba = cross_val_predict(rf_pipe, X, y, groups=groups, cv=logo, method="predict_proba")[:, 1]

    rf_acc = accuracy_score(y, rf_preds)
    rf_f1 = f1_score(y, rf_preds, average="macro")
    rf_auc = roc_auc_score(y, rf_proba)

    print(f"  Accuracy: {rf_acc:.4f}")
    print(f"  F1 Macro: {rf_f1:.4f}")
    print(f"  AUC:      {rf_auc:.4f}")
    print(classification_report(y, rf_preds, target_names=["HC", "PD"]))

    # Feature importance
    print("--- Feature Importance (XGBoost, full dataset) ---")
    xgb_pipe.fit(X, y)
    importances = xgb_pipe.named_steps["xgb"].feature_importances_
    sorted_idx = np.argsort(importances)[::-1]
    for i in sorted_idx[:10]:
        print(f"  {feature_names[i]:25s} {importances[i]:.4f}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Dataset: PhysioNet Gait-PD ({len(subjects)} subjects, {X.shape[0]} trials)")
    print(f"Features: {X.shape[1]} handcrafted gait features from VGRF")
    print(f"CV: Leave-One-Subject-Out ({len(set(groups))} folds)")
    print(f"XGBoost:       Acc={xgb_acc:.3f}  F1={xgb_f1:.3f}  AUC={xgb_auc:.3f}")
    print(f"Random Forest: Acc={rf_acc:.3f}  F1={rf_f1:.3f}  AUC={rf_auc:.3f}")
    print(f"\nLit SOTA on this dataset: 95-98% accuracy (but often without LOSO CV)")
    print(f"Our LOSO CV is more rigorous — expect lower numbers.")


if __name__ == "__main__":
    run_baseline()

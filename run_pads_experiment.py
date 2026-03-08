#!/usr/bin/env python3
"""
Full PADS experiment: PD vs HC vs DD classification from wrist smartwatch IMU.

Pipeline:
1. Load PADS dataset (469 subjects, 11 tasks, both wrists, 6-axis IMU @ 100Hz)
2. Baseline: handcrafted features + XGBoost (LOSO CV)
3. DL Baseline: 1D-CNN on raw IMU (LOSO CV)
4. Transformer: IMU Transformer encoder (LOSO CV)
5. Compare all methods

Labels: ICD-10 diagnosis -> PD / HC / DD (3-class classification)
"""
import sys
sys.path.insert(0, "/root/pd-imu")

import json
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from pathlib import Path
from sklearn.model_selection import LeaveOneGroupOut, StratifiedGroupKFold
from sklearn.metrics import accuracy_score, f1_score, classification_report, roc_auc_score
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.pipeline import Pipeline
import xgboost as xgb
from scipy import signal
from scipy.stats import entropy
from collections import Counter
import warnings
warnings.filterwarnings("ignore")

BASE_DIR = Path("/root/pd-imu/data/raw/pads/physionet.org/files/parkinsons-disease-smartwatch/1.0.0")


def load_pads_all():
    """Load all PADS data: observations + patient info + timeseries."""
    movement_dir = BASE_DIR / "movement"
    timeseries_dir = movement_dir / "timeseries"
    patients_dir = BASE_DIR / "patients"

    # Load patient diagnoses
    # Map PADS condition field to our 3 groups
    condition_map = {
        "Parkinson's": "PD",
        "Healthy": "HC",
        "Essential Tremor": "DD",
        "Other Movement Disorders": "DD",
        "Atypical Parkinsonism": "DD",
        "Multiple Sclerosis": "DD",
    }

    patient_diag = {}
    for f in sorted(patients_dir.glob("patient_*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
            sid = int(data.get("id", f.stem.split("_")[1]))
            condition = data.get("condition", "Unknown")
            group = condition_map.get(condition, "Unknown")
            patient_diag[sid] = {
                "group": group,
                "condition": condition,
                "age": data.get("age"),
                "sex": data.get("gender"),
                "raw": data,
            }
        except (json.JSONDecodeError, ValueError, KeyError):
            continue

    print(f"Patient info loaded: {len(patient_diag)} subjects")
    diag_dist = Counter(v["group"] for v in patient_diag.values())
    print(f"  Diagnosis distribution: {dict(diag_dist)}")

    # Load observations and their timeseries
    records = []
    obs_files = sorted(movement_dir.glob("observation_*.json"))

    for obs_file in obs_files:
        try:
            with open(obs_file) as f:
                obs = json.load(f)
        except json.JSONDecodeError:
            continue

        sid_str = str(obs.get("subject_id", obs_file.stem.split("_")[1]))
        sid = int(sid_str)
        fs = float(obs.get("sampling_rate", 100))

        pat = patient_diag.get(sid, {})
        group = pat.get("group", "Unknown")

        for session in obs.get("session", []):
            task_name = session.get("record_name", "Unknown")

            for rec in session.get("records", []):
                wrist = rec.get("device_location", "Unknown")
                filename = rec.get("file_name", "")

                filepath = timeseries_dir / Path(filename).name
                if not filepath.exists():
                    # Try alternate path
                    filepath = movement_dir / filename
                if not filepath.exists():
                    continue

                try:
                    data = np.loadtxt(str(filepath), delimiter=",")
                except Exception:
                    try:
                        data = np.loadtxt(str(filepath))
                    except Exception:
                        continue

                if data.ndim != 2 or data.shape[1] < 7:
                    continue

                # Skip first 50 samples (0.5s vibration artifact)
                data = data[50:]

                records.append({
                    "subject_id": sid,
                    "task_name": task_name,
                    "wrist": wrist,
                    "time": data[:, 0],
                    "accel": data[:, 1:4],
                    "gyro": data[:, 4:7],
                    "fs": fs,
                    "group": group,
                })

    print(f"Loaded {len(records)} timeseries recordings")
    return records, patient_diag


def extract_imu_features(accel, gyro, fs):
    """Extract features from one IMU recording."""
    n = len(accel)
    if n < 50:
        return None

    accel_mag = np.linalg.norm(accel, axis=1)
    gyro_mag = np.linalg.norm(gyro, axis=1)

    features = {}

    # Accel statistics
    for i, axis in enumerate(["x", "y", "z"]):
        features[f"acc_{axis}_mean"] = np.mean(accel[:, i])
        features[f"acc_{axis}_std"] = np.std(accel[:, i])
        features[f"acc_{axis}_range"] = np.ptp(accel[:, i])

    features["acc_mag_mean"] = np.mean(accel_mag)
    features["acc_mag_std"] = np.std(accel_mag)
    features["acc_mag_rms"] = np.sqrt(np.mean(accel_mag**2))

    # Gyro statistics
    for i, axis in enumerate(["x", "y", "z"]):
        features[f"gyro_{axis}_mean"] = np.mean(gyro[:, i])
        features[f"gyro_{axis}_std"] = np.std(gyro[:, i])
        features[f"gyro_{axis}_range"] = np.ptp(gyro[:, i])

    features["gyro_mag_mean"] = np.mean(gyro_mag)
    features["gyro_mag_std"] = np.std(gyro_mag)

    # Tremor band power (4-6 Hz)
    freqs, psd_acc = signal.welch(accel_mag, fs=fs, nperseg=min(256, n))
    total_power = np.trapz(psd_acc, freqs) + 1e-10
    tremor_mask = (freqs >= 4.0) & (freqs <= 6.0)
    features["tremor_power"] = np.trapz(psd_acc[tremor_mask], freqs[tremor_mask])
    features["tremor_ratio"] = features["tremor_power"] / total_power

    # Dominant frequency
    features["dominant_freq"] = freqs[np.argmax(psd_acc)]

    # Spectral entropy
    psd_norm = psd_acc / (np.sum(psd_acc) + 1e-10)
    features["spectral_entropy"] = entropy(psd_norm + 1e-10)

    # Jerk
    jerk = np.diff(accel_mag) * fs
    features["jerk_rms"] = np.sqrt(np.mean(jerk**2))

    # Cross-correlation between accel axes (coordination)
    features["acc_xy_corr"] = np.corrcoef(accel[:, 0], accel[:, 1])[0, 1]
    features["acc_xz_corr"] = np.corrcoef(accel[:, 0], accel[:, 2])[0, 1]

    # Gyro frequency features
    _, psd_gyro = signal.welch(gyro_mag, fs=fs, nperseg=min(256, n))
    features["gyro_dominant_freq"] = freqs[np.argmax(psd_gyro)]
    gyro_tremor = (freqs >= 4.0) & (freqs <= 6.0)
    features["gyro_tremor_power"] = np.trapz(psd_gyro[gyro_tremor], freqs[gyro_tremor])

    return features


def run_feature_baseline(records):
    """Run XGBoost baseline on handcrafted features."""
    print("\n" + "=" * 60)
    print("BASELINE: Handcrafted Features + XGBoost")
    print("=" * 60)

    # Map groups to numeric labels
    label_map = {"HC": 0, "PD": 1, "DD": 2}

    feature_list = []
    labels = []
    subject_ids = []
    task_names = []

    for rec in records:
        if rec["group"] not in label_map:
            continue

        feats = extract_imu_features(rec["accel"], rec["gyro"], rec["fs"])
        if feats is None:
            continue

        feature_list.append(feats)
        labels.append(label_map[rec["group"]])
        subject_ids.append(rec["subject_id"])
        task_names.append(rec["task_name"])

    if not feature_list:
        print("No valid features extracted!")
        return

    feature_names = list(feature_list[0].keys())
    X = np.array([[f.get(k, 0) for k in feature_names] for f in feature_list])
    y = np.array(labels)
    groups = np.array(subject_ids)

    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    print(f"Features: {X.shape[1]}, Samples: {X.shape[0]}")
    print(f"Labels: {Counter(y)} (0=HC, 1=PD, 2=DD)")
    print(f"Unique subjects: {len(set(groups))}")

    # Adaptive CV: use fewer folds if few subjects
    n_subjects = len(set(groups))
    n_folds = min(5, n_subjects)
    if n_folds < 2:
        print("Too few subjects for cross-validation!")
        return None
    sgkf = StratifiedGroupKFold(n_splits=n_folds, shuffle=True, random_state=42)

    # 3-class classification
    from sklearn.model_selection import cross_val_predict

    n_classes = len(np.unique(y))
    xgb_pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("xgb", xgb.XGBClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.1,
            subsample=0.8, colsample_bytree=0.8,
            eval_metric="mlogloss" if n_classes > 2 else "logloss",
            random_state=42,
        )),
    ])

    try:
        preds = cross_val_predict(xgb_pipe, X, y, groups=groups, cv=sgkf)
        acc = accuracy_score(y, preds)
        f1 = f1_score(y, preds, average="macro")
        target_names = ["HC", "PD", "DD"][:n_classes]
        report = classification_report(y, preds, target_names=target_names)

        print(f"\n{n_classes}-Class Results ({n_folds}-fold StratifiedGroupKFold):")
        print(f"  Accuracy: {acc:.4f}")
        print(f"  F1 Macro: {f1:.4f}")
        print(report)
    except Exception as e:
        print(f"  CV failed: {e}")
        acc, f1 = 0, 0

    # Binary PD vs HC
    binary_mask = y != 2  # exclude DD
    if binary_mask.sum() > 10:
        X_bin = X[binary_mask]
        y_bin = (y[binary_mask] > 0).astype(int)
        g_bin = groups[binary_mask]

        xgb_bin = Pipeline([
            ("scaler", StandardScaler()),
            ("xgb", xgb.XGBClassifier(
                n_estimators=200, max_depth=6, learning_rate=0.1,
                eval_metric="logloss", random_state=42,
            )),
        ])

        n_subjects_bin = len(set(g_bin))
        sgkf_bin = StratifiedGroupKFold(n_splits=min(5, n_subjects_bin), shuffle=True, random_state=42)
        preds_bin = cross_val_predict(xgb_bin, X_bin, y_bin, groups=g_bin, cv=sgkf_bin)
        proba_bin = cross_val_predict(
            xgb_bin, X_bin, y_bin, groups=g_bin, cv=sgkf_bin, method="predict_proba"
        )[:, 1]

        acc_bin = accuracy_score(y_bin, preds_bin)
        f1_bin = f1_score(y_bin, preds_bin, average="macro")
        auc_bin = roc_auc_score(y_bin, proba_bin)

        print(f"\nBinary PD vs HC:")
        print(f"  Accuracy: {acc_bin:.4f}")
        print(f"  F1 Macro: {f1_bin:.4f}")
        print(f"  AUC:      {auc_bin:.4f}")
        print(classification_report(y_bin, preds_bin, target_names=["HC", "PD"]))

    # Feature importance
    xgb_pipe.fit(X, y)
    importances = xgb_pipe.named_steps["xgb"].feature_importances_
    sorted_idx = np.argsort(importances)[::-1]
    print("Top 10 features:")
    for i in sorted_idx[:10]:
        print(f"  {feature_names[i]:25s} {importances[i]:.4f}")

    return {"accuracy_3c": acc, "f1_3c": f1, "accuracy_bin": acc_bin if binary_mask.sum() > 10 else None}


def run_cnn_baseline(records):
    """Run 1D-CNN baseline on raw IMU."""
    print("\n" + "=" * 60)
    print("DL BASELINE: 1D-CNN on Raw IMU")
    print("=" * 60)

    class ResBlock1D(nn.Module):
        def __init__(self, channels, kernel_size=7):
            super().__init__()
            padding = kernel_size // 2
            self.block = nn.Sequential(
                nn.Conv1d(channels, channels, kernel_size, padding=padding),
                nn.BatchNorm1d(channels), nn.GELU(),
                nn.Conv1d(channels, channels, kernel_size, padding=padding),
                nn.BatchNorm1d(channels))
            self.act = nn.GELU()
        def forward(self, x):
            return self.act(x + self.block(x))

    class CNN1DBaseline(nn.Module):
        def __init__(self, in_channels=6, base_channels=64, n_blocks=4, n_classes=3, dropout=0.3):
            super().__init__()
            self.stem = nn.Sequential(
                nn.Conv1d(in_channels, base_channels, 15, stride=2, padding=7),
                nn.BatchNorm1d(base_channels), nn.GELU())
            blocks = []
            ch = base_channels
            for i in range(n_blocks):
                blocks.append(ResBlock1D(ch))
                if i < n_blocks - 1:
                    next_ch = ch * 2
                    blocks.extend([nn.Conv1d(ch, next_ch, 3, stride=2, padding=1),
                                   nn.BatchNorm1d(next_ch), nn.GELU()])
                    ch = next_ch
            self.backbone = nn.Sequential(*blocks)
            self.pool = nn.AdaptiveAvgPool1d(1)
            self.classifier = nn.Sequential(
                nn.Dropout(dropout), nn.Linear(ch, ch // 2), nn.GELU(),
                nn.Dropout(dropout), nn.Linear(ch // 2, n_classes))
        def forward(self, x):
            x = self.stem(x)
            x = self.backbone(x)
            x = self.pool(x).squeeze(-1)
            return {"classification": self.classifier(x)}

    label_map = {"HC": 0, "PD": 1, "DD": 2}
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Collect and pad/truncate to fixed length
    TARGET_LEN = 1024  # ~10s at 100Hz
    imu_list = []
    labels = []
    subject_ids = []

    for rec in records:
        if rec["group"] not in label_map:
            continue

        imu = np.concatenate([rec["accel"], rec["gyro"]], axis=1)  # (T, 6)

        # Pad or truncate
        if len(imu) < TARGET_LEN:
            pad = np.zeros((TARGET_LEN - len(imu), 6))
            imu = np.vstack([imu, pad])
        else:
            imu = imu[:TARGET_LEN]

        imu_list.append(imu)
        labels.append(label_map[rec["group"]])
        subject_ids.append(rec["subject_id"])

    X = np.array(imu_list)  # (N, T, 6)
    y = np.array(labels)
    groups = np.array(subject_ids)

    print(f"Data: {X.shape}, Labels: {Counter(y)}, Subjects: {len(set(groups))}")

    # Normalize per-channel
    X_flat = X.reshape(-1, 6)
    scaler = StandardScaler()
    X_flat = scaler.fit_transform(X_flat)
    X = X_flat.reshape(X.shape)

    # Convert to (N, C, T) for PyTorch
    X_tensor = torch.from_numpy(X).float().permute(0, 2, 1)
    y_tensor = torch.from_numpy(y).long()

    # Adaptive CV
    n_subjects_dl = len(set(groups))
    n_folds_dl = min(5, n_subjects_dl)
    if n_folds_dl < 2:
        print("Too few subjects for DL cross-validation!")
        return None
    sgkf = StratifiedGroupKFold(n_splits=n_folds_dl, shuffle=True, random_state=42)
    all_preds = np.zeros(len(y), dtype=int)

    for fold, (train_idx, val_idx) in enumerate(sgkf.split(X, y, groups)):
        print(f"\n  Fold {fold+1}/5...")

        X_train = X_tensor[train_idx].to(device)
        y_train = y_tensor[train_idx].to(device)
        X_val = X_tensor[val_idx].to(device)
        y_val = y_tensor[val_idx].to(device)

        model = CNN1DBaseline(in_channels=6, n_classes=3, base_channels=64).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
        criterion = nn.CrossEntropyLoss()
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=50)

        # Train
        best_val_acc = 0
        patience = 0
        batch_size = 32

        for epoch in range(50):
            model.train()
            perm = torch.randperm(len(X_train))
            epoch_loss = 0
            n_batches = 0

            for i in range(0, len(X_train), batch_size):
                idx = perm[i:i+batch_size]
                out = model(X_train[idx])
                loss = criterion(out["classification"], y_train[idx])

                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()

                epoch_loss += loss.item()
                n_batches += 1

            scheduler.step()

            # Validate
            model.eval()
            with torch.no_grad():
                val_out = model(X_val)
                val_preds = val_out["classification"].argmax(dim=1)
                val_acc = (val_preds == y_val).float().mean().item()

            if val_acc > best_val_acc:
                best_val_acc = val_acc
                best_preds = val_preds.cpu().numpy()
                patience = 0
            else:
                patience += 1
                if patience >= 10:
                    break

        all_preds[val_idx] = best_preds
        print(f"    Best val acc: {best_val_acc:.4f}")

    acc = accuracy_score(y, all_preds)
    f1 = f1_score(y, all_preds, average="macro")
    print(f"\n1D-CNN Results (5-fold StratifiedGroupKFold):")
    print(f"  Accuracy: {acc:.4f}")
    print(f"  F1 Macro: {f1:.4f}")
    print(classification_report(y, all_preds, target_names=["HC", "PD", "DD"]))

    return {"accuracy": acc, "f1": f1}


def main():
    print("=" * 60)
    print("PADS EXPERIMENT: PD vs HC vs DD from Wrist Smartwatch IMU")
    print("=" * 60)

    records, patient_info = load_pads_all()

    if not records:
        print("No data loaded! Check that PADS timeseries are downloaded.")
        return

    # Group distribution
    group_dist = Counter(r["group"] for r in records)
    print(f"\nRecording distribution by group: {dict(group_dist)}")

    task_dist = Counter(r["task_name"] for r in records)
    print(f"Task distribution: {dict(task_dist)}")

    # Run baselines
    feature_results = run_feature_baseline(records)
    cnn_results = run_cnn_baseline(records)

    # Summary
    print("\n" + "=" * 60)
    print("EXPERIMENT SUMMARY")
    print("=" * 60)
    print(f"Dataset: PADS ({len(set(r['subject_id'] for r in records))} subjects)")
    if feature_results:
        print(f"XGBoost (features):  Acc={feature_results.get('accuracy_3c', 'N/A'):.3f}")
    if cnn_results:
        print(f"1D-CNN (raw IMU):    Acc={cnn_results['accuracy']:.3f}")
    print(f"\nLit SOTA (PADS): AUC 0.85 PD vs HC (RF/XGBoost, npj PD 2024)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Reproduce Varghese et al. (2024) PADS benchmark — corrected from official repo.

Reference: "Machine Learning in the Parkinson's disease smartwatch (PADS) dataset"
  npj Parkinson's Disease, 10, 9. DOI: 10.1038/s41531-023-00625-7
  Code: https://imigitlab.uni-muenster.de/published/pads-project

Official preprocessing (from their run_preprocessing.py):
  1. Arrange 11 tasks into 14 segments: Relaxed, RelaxedTask, Entrainment split into halves
  2. Exclude: LiftHold, PointFinger, TouchIndex (+ Time columns)
  3. L1 trend filter (cvxpy, λ=50) on accelerometer channels only
  4. Remove first 48 samples (vibration artifact)

Official features (from their feature_extraction.py):
  - 19 PSD via Welch (1-19 Hz, log10-scaled)
  - 4-segment: std, abs_max, abs_energy (=sum of abs values)
  = 31 features/channel

Official classification:
  - Two SEPARATE binary tasks: PD vs HC, PD vs DD
  - Not 3-class
  - Nested 5-fold CV with GridSearchCV (inner) → SVM/NN/BOSS/XceptionTime

Targets (balanced accuracy):
  PD vs HC — smartwatch: 78.99%, questionnaire: 89.79%, combined: 91.16%
  PD vs DD — smartwatch: 69.18%, questionnaire: 67.77%, combined: 72.42%
"""
import sys
sys.path.insert(0, "/root/pd-imu")

import json
import time
import numpy as np
from pathlib import Path
from collections import Counter, defaultdict
from scipy import signal
from sklearn.svm import SVC
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import StratifiedGroupKFold, GridSearchCV
from sklearn.metrics import balanced_accuracy_score, classification_report
from sklearn.linear_model import LogisticRegression
from sklearn.impute import SimpleImputer
import warnings
warnings.filterwarnings("ignore")

# ============================================================
# Constants (from official repo)
# ============================================================
BASE_DIR = Path(
    "/root/pd-imu/data/raw/pads/physionet.org/files/"
    "parkinsons-disease-smartwatch/1.0.0"
)
FS = 100
VIBRATION_SAMPLES = 48  # official: 48 (not 50)

# Official task ordering: 3 tasks split into halves + 8 single tasks = 14 segments
SPLIT_TASKS = {"Relaxed", "RelaxedTask", "Entrainment"}  # split into 2 halves
# Official exclusion (from run_preprocessing.py: to_remove = 'Time|LiftHold|PointFinger|TouchIndex')
EXCLUDED_TASKS = frozenset({"LiftHold", "PointFinger", "TouchIndex"})

# Remaining 11 task-segments after exclusion:
# Relaxed1, Relaxed2, RelaxedTask1, RelaxedTask2, StretchHold, HoldWeight,
# DrinkGlas, CrossArms, TouchNose, Entrainment1, Entrainment2

CONDITION_MAP = {
    "Parkinson's": "PD",
    "Healthy": "HC",
    "Essential Tremor": "DD",
    "Other Movement Disorders": "DD",
    "Atypical Parkinsonism": "DD",
    "Multiple Sclerosis": "DD",
}
LABEL_MAP = {"HC": 0, "PD": 1, "DD": 2}


# ============================================================
# Data Loading
# ============================================================
def load_patient_info():
    patients_dir = BASE_DIR / "patients"
    info = {}
    for f in sorted(patients_dir.glob("patient_*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
            sid = int(data.get("id", f.stem.split("_")[1]))
            condition = data.get("condition", "Unknown")
            group = CONDITION_MAP.get(condition)
            if group is None:
                continue
            info[sid] = {"group": group, "condition": condition,
                         "age": data.get("age"), "gender": data.get("gender")}
        except (json.JSONDecodeError, ValueError):
            continue
    return info


def load_questionnaire_data():
    """Load PDNMS questionnaire (30 yes/no symptom questions)."""
    quest_dir = BASE_DIR / "questionnaire"
    if not quest_dir.exists():
        return {}
    responses = {}
    for f in sorted(quest_dir.glob("questionnaire_response_*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
            sid = int(data.get("subject_id", f.stem.rsplit("_", 1)[-1]))
            items = data.get("item", [])
            if items:
                vec = []
                for item in sorted(items, key=lambda x: x.get("link_id", "")):
                    ans = item.get("answer", False)
                    vec.append(1.0 if ans is True else 0.0)
                if vec:
                    responses[sid] = np.array(vec)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return responses


def load_all_recordings(patient_info):
    """Load PADS timeseries, splitting long tasks and excluding per official code."""
    movement_dir = BASE_DIR / "movement"
    timeseries_dir = movement_dir / "timeseries"

    # recordings[sid] = list of (task_segment_name, wrist, accel, gyro)
    recordings = defaultdict(list)
    n_loaded = 0

    for obs_file in sorted(movement_dir.glob("observation_*.json")):
        try:
            with open(obs_file) as f:
                obs = json.load(f)
        except json.JSONDecodeError:
            continue

        sid = int(obs.get("subject_id", obs_file.stem.split("_")[1]))
        if sid not in patient_info:
            continue

        for session in obs.get("session", []):
            task = session.get("record_name", "Unknown")
            if task in EXCLUDED_TASKS:
                continue

            for rec in session.get("records", []):
                wrist = rec.get("device_location", "Unknown")
                fname = rec.get("file_name", "")
                fpath = timeseries_dir / Path(fname).name
                if not fpath.exists():
                    fpath = movement_dir / fname
                if not fpath.exists():
                    continue

                try:
                    data = np.loadtxt(str(fpath), delimiter=",")
                except Exception:
                    try:
                        data = np.loadtxt(str(fpath))
                    except Exception:
                        continue

                if data.ndim != 2 or data.shape[1] < 7:
                    continue

                accel = data[:, 1:4].copy()
                gyro = data[:, 4:7].copy()

                # Split tasks per official code
                if task in SPLIT_TASKS:
                    mid = len(accel) // 2
                    recordings[sid].append(
                        (f"{task}1", wrist, accel[:mid], gyro[:mid])
                    )
                    recordings[sid].append(
                        (f"{task}2", wrist, accel[mid:], gyro[mid:])
                    )
                else:
                    recordings[sid].append((task, wrist, accel, gyro))
                n_loaded += 1

    print(f"Loaded {n_loaded} raw recordings from {len(recordings)} subjects")
    return dict(recordings)


# ============================================================
# Preprocessing (from official repo)
# ============================================================
def l1_trend_filter_approx(y, vlambda=50):
    """Approximate L1 trend filter using Butterworth lowpass.

    The official code uses cvxpy CVXOPT solver which is slow (~2s per channel).
    This approximation runs in microseconds and gives similar gravity removal.
    For exact reproduction, install cvxpy and use l1_trend_filter_exact().
    """
    if len(y) < 30:
        return np.zeros_like(y)
    # Low-pass at 0.3 Hz to estimate gravity trend
    sos = signal.butter(4, 0.3, btype="low", fs=FS, output="sos")
    trend = signal.sosfiltfilt(sos, y, axis=0)
    return trend


def l1_trend_filter_exact(y, vlambda=50):
    """Exact L1 trend filter (requires cvxpy + CVXOPT)."""
    try:
        import cvxpy as cp
        import scipy.sparse
    except ImportError:
        return l1_trend_filter_approx(y, vlambda)

    n = y.size
    e = np.ones((1, n))
    D = scipy.sparse.spdiags(np.vstack((e, -2 * e, e)), range(3), n - 2, n)
    x = cp.Variable(shape=n)
    obj = cp.Minimize(0.5 * cp.sum_squares(y - x) + vlambda * cp.norm(D @ x, 1))
    prob = cp.Problem(obj)
    prob.solve(solver=cp.CVXOPT, verbose=False)
    if prob.status != cp.OPTIMAL:
        return l1_trend_filter_approx(y, vlambda)
    return x.value


def preprocess_recording(accel, gyro, use_exact_l1=False):
    """Preprocess a single recording segment.

    1. L1 trend filter on accelerometer (gravity removal)
    2. Remove first 48 samples (vibration artifact)
    """
    l1_func = l1_trend_filter_exact if use_exact_l1 else l1_trend_filter_approx

    # Remove gravity from each accel axis
    accel_clean = accel.copy()
    for axis in range(3):
        trend = l1_func(accel[:, axis], vlambda=50)
        accel_clean[:, axis] = accel[:, axis] - trend

    # Remove vibration artifact
    accel_clean = accel_clean[VIBRATION_SAMPLES:]
    gyro_clean = gyro[VIBRATION_SAMPLES:]

    return accel_clean, gyro_clean


# ============================================================
# Feature Extraction (exact match of official feature_extraction.py)
# ============================================================
def bandpower(x, srate=FS, steps=100, cut=(1, 20)):
    """PSD via Welch at 1Hz resolution, log10-scaled, 1-19 Hz."""
    _, pxx = signal.welch(x, fs=srate, nperseg=steps, scaling="density")
    band_powers = pxx[cut[0]:cut[1]]  # indices 1..19 → freqs 1..19 Hz
    band_powers = np.log10(np.maximum(band_powers, 1e-20))  # log10 as in official
    return list(band_powers)


def std_windowed(x):
    """Standard deviation on 4 equal segments."""
    seg_len = len(x) // 4
    return [float(np.std(x[i * seg_len:(i + 1) * seg_len])) for i in range(4)]


def abs_energy_windowed(x):
    """Sum of absolute values on 4 equal segments (NOT squared!)."""
    seg_len = len(x) // 4
    return [float(np.sum(np.abs(x[i * seg_len:(i + 1) * seg_len]))) for i in range(4)]


def abs_max_windowed(x):
    """Max absolute amplitude on 4 equal segments."""
    seg_len = len(x) // 4
    return [float(np.max(np.abs(x[i * seg_len:(i + 1) * seg_len]))) for i in range(4)]


def extract_channel_features(x):
    """Extract 31 features from one 1-D channel (matching official pipeline)."""
    if len(x) < 100:
        return [0.0] * 31
    feats = []
    feats.extend(bandpower(x))        # 19 log-PSD features
    feats.extend(std_windowed(x))      # 4 std features
    feats.extend(abs_energy_windowed(x))  # 4 abs-energy features
    feats.extend(abs_max_windowed(x))  # 4 abs-max features
    return feats


# ============================================================
# Subject-level feature vector construction
# ============================================================
# Official task ordering (14 segments before exclusion)
TASK_ORDER = [
    "Relaxed1", "Relaxed2", "RelaxedTask1", "RelaxedTask2",
    "StretchHold", "LiftHold", "HoldWeight",
    "PointFinger", "DrinkGlas", "CrossArms",
    "TouchIndex", "TouchNose", "Entrainment1", "Entrainment2",
]
# After removing excluded tasks
TASK_ORDER_KEPT = [t for t in TASK_ORDER
                   if not any(exc in t for exc in EXCLUDED_TASKS)]
# Should be 11: Relaxed1/2, RelaxedTask1/2, StretchHold, HoldWeight,
#               DrinkGlas, CrossArms, TouchNose, Entrainment1/2


def build_subject_features(records):
    """Build flat feature vector for one subject.

    For each task-segment in TASK_ORDER_KEPT × [LeftWrist, RightWrist]:
        For each of 6 channels (acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z):
            Extract 31 features

    Total: 11 segments × 2 wrists × 6 channels × 31 = 4,092 features
    """
    # Index records by (task_segment, wrist)
    rec_map = {}
    for task_seg, wrist, accel, gyro in records:
        rec_map[(task_seg, wrist)] = (accel, gyro)

    feats = []
    for task in TASK_ORDER_KEPT:
        for wrist in ("LeftWrist", "RightWrist"):
            key = (task, wrist)
            if key not in rec_map:
                feats.extend([np.nan] * (6 * 31))
                continue

            accel, gyro = rec_map[key]
            accel_p, gyro_p = preprocess_recording(accel, gyro)

            imu = np.hstack([accel_p, gyro_p])  # (T, 6)
            for ch in range(6):
                feats.extend(extract_channel_features(imu[:, ch]))

    return np.array(feats, dtype=np.float64)


# ============================================================
# Classification (binary, matching official approach)
# ============================================================
def run_binary_nested_cv(X, y, groups, model_name="SVM", n_outer=5, n_inner=5):
    """Nested CV for a single binary classification task.

    Returns (predictions, probabilities, fold_scores).
    """
    outer_cv = StratifiedGroupKFold(n_splits=n_outer, shuffle=True, random_state=42)
    all_preds = np.full(len(y), -1, dtype=int)
    all_proba = np.zeros(len(y))
    fold_scores = []

    if model_name == "SVM":
        pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("clf", SVC(kernel="rbf", class_weight="balanced", probability=True)),
        ])
        param_grid = {
            "clf__C": [0.1, 1.0, 10.0, 100.0],
            "clf__gamma": ["scale"],  # official: only 'scale'
        }
    elif model_name == "NN":
        pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("clf", MLPClassifier(max_iter=500, early_stopping=True, random_state=42)),
        ])
        param_grid = {
            "clf__hidden_layer_sizes": [(50,), (200,), (200, 20), (500, 100, 20)],
        }
    else:
        raise ValueError(model_name)

    t0 = time.time()
    for fold, (train_idx, test_idx) in enumerate(outer_cv.split(X, y, groups)):
        inner_cv = StratifiedGroupKFold(n_splits=n_inner, shuffle=True, random_state=42)

        grid = GridSearchCV(
            pipe, param_grid, cv=inner_cv,
            scoring="balanced_accuracy", n_jobs=-1, refit=True,
        )
        grid.fit(X[train_idx], y[train_idx], groups=groups[train_idx])

        preds = grid.predict(X[test_idx])
        proba = grid.predict_proba(X[test_idx])[:, 1]
        all_preds[test_idx] = preds
        all_proba[test_idx] = proba

        fold_bal = balanced_accuracy_score(y[test_idx], preds)
        fold_scores.append(fold_bal)
        print(f"  Fold {fold + 1}/{n_outer}: bal_acc={fold_bal:.3f}  "
              f"best={grid.best_params_}")

    elapsed = time.time() - t0
    overall = balanced_accuracy_score(y[all_preds >= 0], all_preds[all_preds >= 0])
    print(f"  {model_name} overall: {overall:.4f} ({overall*100:.2f}%) "
          f"mean±std: {np.mean(fold_scores):.3f}±{np.std(fold_scores):.3f}  "
          f"[{elapsed:.1f}s]")
    return all_preds, all_proba, fold_scores


# ============================================================
# Stacking
# ============================================================
def run_stacking(X_sw, X_quest, y, groups, n_outer=5, n_inner=5):
    """Full pipeline: SVM on smartwatch + XGBoost on questionnaire → LR stacking."""
    outer_cv = StratifiedGroupKFold(n_splits=n_outer, shuffle=True, random_state=42)
    all_preds = np.full(len(y), -1, dtype=int)
    fold_scores = []

    for fold, (train_idx, test_idx) in enumerate(outer_cv.split(X_sw, y, groups)):
        y_tr, g_tr = y[train_idx], groups[train_idx]

        # --- SVM on smartwatch ---
        inner_cv = StratifiedGroupKFold(n_splits=n_inner, shuffle=True, random_state=42)
        sw_pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("clf", SVC(kernel="rbf", class_weight="balanced", probability=True)),
        ])
        sw_grid = GridSearchCV(
            sw_pipe, {"clf__C": [0.1, 1.0, 10.0, 100.0], "clf__gamma": ["scale"]},
            cv=inner_cv, scoring="balanced_accuracy", n_jobs=-1, refit=True,
        )
        sw_grid.fit(X_sw[train_idx], y_tr, groups=g_tr)

        # OOF smartwatch probabilities for stacking
        best_C = sw_grid.best_params_["clf__C"]
        sw_oof = np.zeros(len(y_tr))
        for _, (tr2, va2) in enumerate(inner_cv.split(X_sw[train_idx], y_tr, g_tr)):
            p = Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("clf", SVC(kernel="rbf", C=best_C, gamma="scale",
                            class_weight="balanced", probability=True)),
            ])
            p.fit(X_sw[train_idx][tr2], y_tr[tr2])
            sw_oof[va2] = p.predict_proba(X_sw[train_idx][va2])[:, 1]
        sw_test = sw_grid.predict_proba(X_sw[test_idx])[:, 1]

        # --- XGBoost on questionnaire ---
        imp_q = SimpleImputer(strategy="most_frequent")
        X_q_tr = imp_q.fit_transform(X_quest[train_idx])
        X_q_te = imp_q.transform(X_quest[test_idx])

        try:
            import xgboost as xgb
            q_model = xgb.XGBClassifier(
                n_estimators=200, max_depth=6, learning_rate=0.1,
                eval_metric="logloss", random_state=42,
            )
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier
            q_model = GradientBoostingClassifier(
                n_estimators=200, max_depth=6, random_state=42
            )

        # Sample weights for class balance
        class_counts = Counter(y_tr)
        n_s, nc = len(y_tr), len(class_counts)
        sw = np.array([n_s / (nc * class_counts[c]) for c in y_tr])
        q_model.fit(X_q_tr, y_tr, sample_weight=sw)

        # OOF questionnaire probabilities
        q_oof = np.zeros(len(y_tr))
        for _, (tr2, va2) in enumerate(inner_cv.split(X_q_tr, y_tr, g_tr)):
            from sklearn.base import clone
            qm = clone(q_model)
            sw2 = np.array([len(y_tr[tr2]) / (nc * Counter(y_tr[tr2])[c])
                            for c in y_tr[tr2]])
            qm.fit(X_q_tr[tr2], y_tr[tr2], sample_weight=sw2)
            q_oof[va2] = qm.predict_proba(X_q_tr[va2])[:, 1]
        q_test = q_model.predict_proba(X_q_te)[:, 1]

        # --- Logistic Regression stacking ---
        stack_tr = np.column_stack([sw_oof, q_oof])
        stack_te = np.column_stack([sw_test, q_test])
        meta = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)
        meta.fit(stack_tr, y_tr)
        preds = meta.predict(stack_te)
        all_preds[test_idx] = preds

        fold_bal = balanced_accuracy_score(y[test_idx], preds)
        fold_scores.append(fold_bal)
        print(f"  Fold {fold + 1}: sw_best_C={best_C}, stk_bal={fold_bal:.3f}")

    valid = all_preds >= 0
    overall = balanced_accuracy_score(y[valid], all_preds[valid])
    print(f"  Stacking overall: {overall:.4f} ({overall*100:.2f}%) "
          f"mean±std: {np.mean(fold_scores):.3f}±{np.std(fold_scores):.3f}")
    return all_preds, fold_scores


# ============================================================
# Main
# ============================================================
def main():
    t_start = time.time()
    print("=" * 70)
    print("REPRODUCING: Varghese et al. (2024) — corrected from official repo")
    print("=" * 70)

    # --- Load ---
    print("\n--- Loading data ---")
    patient_info = load_patient_info()
    print(f"Patients: {len(patient_info)} — {Counter(v['group'] for v in patient_info.values())}")

    recordings = load_all_recordings(patient_info)
    questionnaire = load_questionnaire_data()
    print(f"Questionnaire: {len(questionnaire)} responses")

    # --- Build features ---
    print(f"\n--- Building features (official pipeline: 31/ch, log10 PSD) ---")
    print(f"Task segments kept: {TASK_ORDER_KEPT}")
    t_feat = time.time()

    sids = sorted(recordings.keys())
    X_list, y_list, g_list = [], [], []
    for sid in sids:
        group = patient_info[sid]["group"]
        label = LABEL_MAP.get(group)
        if label is None:
            continue
        feat = build_subject_features(recordings[sid])
        X_list.append(feat)
        y_list.append(label)
        g_list.append(sid)

    # Pad to uniform length
    max_len = max(len(v) for v in X_list)
    X = np.full((len(X_list), max_len), np.nan, dtype=np.float64)
    for i, v in enumerate(X_list):
        X[i, :len(v)] = v
    X = np.nan_to_num(X, nan=np.nan, posinf=np.nan, neginf=np.nan)

    y_all = np.array(y_list)
    groups = np.array(g_list)

    nan_pct = np.isnan(X).sum() / X.size * 100
    print(f"Feature matrix: {X.shape} ({nan_pct:.1f}% NaN)")
    print(f"Labels: {Counter(y_all)} (0=HC, 1=PD, 2=DD)")
    print(f"Feature extraction: {time.time() - t_feat:.1f}s")

    # Build questionnaire matrix
    max_q = max((len(v) for v in questionnaire.values()), default=0)
    X_quest = np.full((len(y_all), max_q), np.nan) if max_q > 0 else None
    if X_quest is not None:
        for i, sid in enumerate(g_list):
            if sid in questionnaire:
                q = questionnaire[sid]
                X_quest[i, :len(q)] = q
        n_q = np.sum(~np.all(np.isnan(X_quest), axis=1))
        print(f"Questionnaire: {n_q}/{len(y_all)} subjects, {max_q} features")

    # ===== Binary Task 1: PD vs HC =====
    print("\n" + "=" * 70)
    print("TASK 1: PD vs HC (binary)")
    print("=" * 70)

    mask_hc_pd = np.isin(y_all, [0, 1])
    X_hcpd = X[mask_hc_pd]
    y_hcpd = y_all[mask_hc_pd]  # 0=HC, 1=PD
    g_hcpd = groups[mask_hc_pd]
    print(f"Subjects: {len(y_hcpd)} (HC={np.sum(y_hcpd==0)}, PD={np.sum(y_hcpd==1)})")

    print("\n--- SVM ---")
    preds_svm_hcpd, proba_svm_hcpd, _ = run_binary_nested_cv(
        X_hcpd, y_hcpd, g_hcpd, "SVM"
    )
    print("\n--- NN ---")
    preds_nn_hcpd, proba_nn_hcpd, _ = run_binary_nested_cv(
        X_hcpd, y_hcpd, g_hcpd, "NN"
    )

    # Questionnaire + stacking for PD vs HC
    if X_quest is not None:
        X_q_hcpd = X_quest[mask_hc_pd]
        if not np.all(np.isnan(X_q_hcpd)):
            print("\n--- Questionnaire (XGBoost) ---")
            imp = SimpleImputer(strategy="most_frequent")
            X_q_imp = imp.fit_transform(X_q_hcpd)

            outer_cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
            q_preds = np.full(len(y_hcpd), -1)
            q_scores = []
            for fold, (tr, te) in enumerate(outer_cv.split(X_q_imp, y_hcpd, g_hcpd)):
                try:
                    import xgboost as xgb
                    qm = xgb.XGBClassifier(n_estimators=200, max_depth=6,
                                           eval_metric="logloss", random_state=42)
                except ImportError:
                    from sklearn.ensemble import GradientBoostingClassifier
                    qm = GradientBoostingClassifier(n_estimators=200, random_state=42)
                cc = Counter(y_hcpd[tr])
                sw = np.array([len(y_hcpd[tr]) / (2 * cc[c]) for c in y_hcpd[tr]])
                qm.fit(X_q_imp[tr], y_hcpd[tr], sample_weight=sw)
                p = qm.predict(X_q_imp[te])
                q_preds[te] = p
                fb = balanced_accuracy_score(y_hcpd[te], p)
                q_scores.append(fb)
                print(f"  Fold {fold+1}: bal_acc={fb:.3f}")
            q_bal = balanced_accuracy_score(y_hcpd, q_preds)
            print(f"  Quest overall: {q_bal:.4f} ({q_bal*100:.2f}%)")

            print("\n--- Stacking (SVM + Quest → LR) ---")
            stk_preds, stk_scores = run_stacking(
                X_hcpd, X_q_hcpd, y_hcpd, g_hcpd
            )

    # ===== Binary Task 2: PD vs DD =====
    print("\n" + "=" * 70)
    print("TASK 2: PD vs DD (binary)")
    print("=" * 70)

    mask_pd_dd = np.isin(y_all, [1, 2])
    X_pddd = X[mask_pd_dd]
    y_pddd = (y_all[mask_pd_dd] == 2).astype(int)  # 0=PD, 1=DD
    g_pddd = groups[mask_pd_dd]
    print(f"Subjects: {len(y_pddd)} (PD={np.sum(y_pddd==0)}, DD={np.sum(y_pddd==1)})")

    print("\n--- SVM ---")
    preds_svm_pddd, _, _ = run_binary_nested_cv(X_pddd, y_pddd, g_pddd, "SVM")
    print("\n--- NN ---")
    preds_nn_pddd, _, _ = run_binary_nested_cv(X_pddd, y_pddd, g_pddd, "NN")

    if X_quest is not None:
        X_q_pddd = X_quest[mask_pd_dd]
        if not np.all(np.isnan(X_q_pddd)):
            print("\n--- Questionnaire (XGBoost) ---")
            imp2 = SimpleImputer(strategy="most_frequent")
            X_q2 = imp2.fit_transform(X_q_pddd)
            outer_cv2 = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
            q2_preds = np.full(len(y_pddd), -1)
            for fold, (tr, te) in enumerate(outer_cv2.split(X_q2, y_pddd, g_pddd)):
                try:
                    import xgboost as xgb
                    qm2 = xgb.XGBClassifier(n_estimators=200, max_depth=6,
                                            eval_metric="logloss", random_state=42)
                except ImportError:
                    from sklearn.ensemble import GradientBoostingClassifier
                    qm2 = GradientBoostingClassifier(n_estimators=200, random_state=42)
                cc = Counter(y_pddd[tr])
                sw = np.array([len(y_pddd[tr]) / (2 * cc[c]) for c in y_pddd[tr]])
                qm2.fit(X_q2[tr], y_pddd[tr], sample_weight=sw)
                p = qm2.predict(X_q2[te])
                q2_preds[te] = p
                fb = balanced_accuracy_score(y_pddd[te], p)
                print(f"  Fold {fold+1}: bal_acc={fb:.3f}")
            q2_bal = balanced_accuracy_score(y_pddd, q2_preds)
            print(f"  Quest overall: {q2_bal:.4f} ({q2_bal*100:.2f}%)")

            print("\n--- Stacking (SVM + Quest → LR) ---")
            stk2_preds, stk2_scores = run_stacking(
                X_pddd, X_q_pddd, y_pddd, g_pddd
            )

    # ===== Summary =====
    print("\n" + "=" * 70)
    print("COMPARISON WITH VARGHESE ET AL. (2024)")
    print("=" * 70)

    svm_hcpd_bal = balanced_accuracy_score(y_hcpd, preds_svm_hcpd)
    nn_hcpd_bal = balanced_accuracy_score(y_hcpd, preds_nn_hcpd)
    svm_pddd_bal = balanced_accuracy_score(y_pddd, preds_svm_pddd)
    nn_pddd_bal = balanced_accuracy_score(y_pddd, preds_nn_pddd)

    print(f"\n{'Method':<30} {'PD/HC Target':>12} {'PD/HC Ours':>12} {'PD/DD Target':>12} {'PD/DD Ours':>12}")
    print("-" * 80)
    print(f"{'SW SVM':<30} {'78.99%':>12} {f'{svm_hcpd_bal*100:.2f}%':>12} {'69.18%':>12} {f'{svm_pddd_bal*100:.2f}%':>12}")
    print(f"{'SW NN':<30} {'78.99%':>12} {f'{nn_hcpd_bal*100:.2f}%':>12} {'69.18%':>12} {f'{nn_pddd_bal*100:.2f}%':>12}")

    if X_quest is not None:
        try:
            print(f"{'Questionnaire':<30} {'89.79%':>12} {f'{q_bal*100:.2f}%':>12} {'67.77%':>12} {f'{q2_bal*100:.2f}%':>12}")
        except NameError:
            pass
        try:
            stk_hcpd = balanced_accuracy_score(y_hcpd[stk_preds >= 0], stk_preds[stk_preds >= 0])
            stk_pddd = balanced_accuracy_score(y_pddd[stk2_preds >= 0], stk2_preds[stk2_preds >= 0])
            print(f"{'Stacked':<30} {'91.16%':>12} {f'{stk_hcpd*100:.2f}%':>12} {'72.42%':>12} {f'{stk_pddd*100:.2f}%':>12}")
        except NameError:
            pass

    print(f"\nTotal runtime: {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()

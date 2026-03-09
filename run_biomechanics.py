"""
Phase 4.2: Biomechanical Feature Extraction + CatBoost
======================================================
CPU-bound (~1-2h on 11 cores). Run simultaneously with run_recipe_fix.py (GPU).

Extracts ~150 clinical gait features per subject per task:
- Time-domain stats (RMS, range, jerk, zero-crossings)
- Frequency-domain (PSD bands: locomotor, tremor, freeze)
- Gait-specific (cadence, stride regularity, symmetry, arm swing)
- Cross-sensor (L/R asymmetry, trunk stability)
- Clinical covariates (age, sex, years since dx, medication, DBS)

Then trains CatBoost with proper subject-level split.
"""
import os, sys, json, time, warnings
import numpy as np
import pandas as pd
from scipy import signal, stats as sp_stats
from scipy.fft import rfft, rfftfreq
from sklearn.metrics import mean_absolute_error
from concurrent.futures import ProcessPoolExecutor
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS

TASKS = ["SelfPace", "HurriedPace", "TUG", "Balance", "TandemGait"]
N_CORES = 11  # server has 11 cores

# Channels to use per sensor
ACC_COLS = ["Acc_X", "Acc_Y", "Acc_Z"]
GYR_COLS = ["Gyr_X", "Gyr_Y", "Gyr_Z"]
FREEACC_COLS = ["FreeAcc_E", "FreeAcc_N", "FreeAcc_U"]
EULER_COLS = ["Roll", "Pitch", "Yaw"]

# Sensor groups for cross-sensor features
PAIRED_SENSORS = [
    ("R_Wrist", "L_Wrist"),
    ("R_Ankle", "L_Ankle"),
    ("R_DorsalFoot", "L_DorsalFoot"),
    ("R_LatShank", "L_LatShank"),
    ("R_MidLatThigh", "L_MidLatThigh"),
]
TRUNK_SENSORS = ["LowerBack", "Xiphoid"]


# ── Feature extraction functions ─────────────────────────────────────

def safe_stat(func, data, default=0.0):
    try:
        v = func(data)
        return float(v) if np.isfinite(v) else default
    except Exception:
        return default


def load_subject_covariates():
    """Parse clinical covariates with fallbacks for column-name variants."""
    covariates = {}
    for fn in [
        "PD - Demographic+Clinical - datasetV1.csv",
        "CONTROLS - Demographic+Clinical - datasetV1.csv",
    ]:
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, header=1)
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            age = pd.to_numeric(row.get("Age (years)", row.get("Age", np.nan)), errors="coerce")
            sex = 1.0 if str(row.get("Sex", "")).strip().upper().startswith("M") else 0.0
            yrs = pd.to_numeric(
                row.get("Years since PD diagnosis", row.get("Years Since Diagnosis", 0)),
                errors="coerce",
            )
            med_raw = str(
                row.get("Medication State", row.get("Medication status", row.get("Med State", "")))
            ).strip().upper()
            dbs_raw = str(row.get("DBS?", row.get("DBS", ""))).strip().upper()
            covariates[sid] = np.array([
                float(age) if pd.notna(age) else 65.0,
                sex,
                float(yrs) if pd.notna(yrs) else 0.0,
                1.0 if med_raw == "ON" else 0.0,
                1.0 if dbs_raw in ("YES", "Y", "1") else 0.0,
            ], dtype=np.float32)
    return covariates


def time_domain_features(x, prefix=""):
    """Time-domain features for a single axis signal."""
    feats = {}
    feats[f"{prefix}_rms"] = safe_stat(lambda d: np.sqrt(np.mean(d**2)), x)
    feats[f"{prefix}_mean"] = safe_stat(np.mean, x)
    feats[f"{prefix}_std"] = safe_stat(np.std, x)
    feats[f"{prefix}_range"] = safe_stat(lambda d: np.ptp(d), x)
    feats[f"{prefix}_iqr"] = safe_stat(lambda d: np.percentile(d, 75) - np.percentile(d, 25), x)
    feats[f"{prefix}_skew"] = safe_stat(lambda d: float(sp_stats.skew(d)), x)
    feats[f"{prefix}_kurt"] = safe_stat(lambda d: float(sp_stats.kurtosis(d)), x)
    feats[f"{prefix}_p5"] = safe_stat(lambda d: np.percentile(d, 5), x)
    feats[f"{prefix}_p95"] = safe_stat(lambda d: np.percentile(d, 95), x)

    # Jerk (derivative)
    jerk = np.diff(x) * FS
    feats[f"{prefix}_jerk_rms"] = safe_stat(lambda d: np.sqrt(np.mean(d**2)), jerk)
    feats[f"{prefix}_jerk_mean"] = safe_stat(np.mean, np.abs(jerk))

    # Zero crossing rate
    zc = np.sum(np.diff(np.sign(x - np.mean(x))) != 0)
    feats[f"{prefix}_zcr"] = float(zc) / max(len(x), 1)

    return feats


def freq_domain_features(x, prefix=""):
    """Frequency-domain features using Welch PSD."""
    feats = {}
    try:
        freqs, psd = signal.welch(x, fs=FS, nperseg=min(256, len(x)),
                                   noverlap=min(128, len(x) // 2))
        psd = psd + 1e-12  # avoid log(0)

        # Band powers
        bands = {
            "locomotor": (0.5, 3.0),
            "tremor": (3.0, 8.0),
            "freeze": (3.0, 8.0),  # freeze band overlaps tremor
            "high": (8.0, 20.0),
        }
        total_power = np.trapz(psd, freqs) + 1e-12
        for bname, (lo, hi) in bands.items():
            mask = (freqs >= lo) & (freqs <= hi)
            bp = np.trapz(psd[mask], freqs[mask]) if mask.sum() > 1 else 0.0
            feats[f"{prefix}_psd_{bname}"] = float(np.log10(bp + 1e-12))
            feats[f"{prefix}_psd_{bname}_rel"] = float(bp / total_power)

        # Dominant frequency
        feats[f"{prefix}_dom_freq"] = float(freqs[np.argmax(psd)])
        feats[f"{prefix}_psd_total"] = float(np.log10(total_power))

        # Spectral entropy
        psd_norm = psd / psd.sum()
        se = -np.sum(psd_norm * np.log2(psd_norm + 1e-12))
        feats[f"{prefix}_spectral_entropy"] = float(se)

    except Exception:
        for k in ["locomotor", "tremor", "freeze", "high"]:
            feats[f"{prefix}_psd_{k}"] = 0.0
            feats[f"{prefix}_psd_{k}_rel"] = 0.0
        feats[f"{prefix}_dom_freq"] = 0.0
        feats[f"{prefix}_psd_total"] = 0.0
        feats[f"{prefix}_spectral_entropy"] = 0.0

    return feats


def gait_regularity_features(acc_vert, prefix=""):
    """Auto-correlation based gait regularity (Moe-Nilssen 2004)."""
    feats = {}
    try:
        x = acc_vert - np.mean(acc_vert)
        ac = np.correlate(x, x, mode="full")
        ac = ac[len(ac)//2:]
        ac = ac / (ac[0] + 1e-12)

        # Find peaks (step and stride)
        peaks, props = signal.find_peaks(ac, distance=30, height=0.1)
        if len(peaks) >= 2:
            step_lag = peaks[0]
            stride_lag = peaks[1] if len(peaks) > 1 else peaks[0] * 2
            feats[f"{prefix}_step_time"] = float(step_lag / FS)
            feats[f"{prefix}_stride_time"] = float(stride_lag / FS)
            feats[f"{prefix}_cadence"] = float(60.0 * FS / step_lag) if step_lag > 0 else 0.0
            feats[f"{prefix}_step_regularity"] = float(ac[step_lag])
            feats[f"{prefix}_stride_regularity"] = float(ac[stride_lag]) if stride_lag < len(ac) else 0.0
            feats[f"{prefix}_step_symmetry"] = abs(float(ac[step_lag]) - float(ac[stride_lag])) if stride_lag < len(ac) else 0.0
        else:
            for k in ["step_time", "stride_time", "cadence", "step_regularity",
                       "stride_regularity", "step_symmetry"]:
                feats[f"{prefix}_{k}"] = 0.0
    except Exception:
        for k in ["step_time", "stride_time", "cadence", "step_regularity",
                   "stride_regularity", "step_symmetry"]:
            feats[f"{prefix}_{k}"] = 0.0
    return feats


def freeze_index(acc_vert, prefix=""):
    """Freeze of gait index: power(3-8Hz) / power(0.5-3Hz)."""
    feats = {}
    try:
        freqs, psd = signal.welch(acc_vert, fs=FS, nperseg=min(256, len(acc_vert)))
        loco = np.trapz(psd[(freqs >= 0.5) & (freqs <= 3.0)],
                        freqs[(freqs >= 0.5) & (freqs <= 3.0)]) + 1e-12
        freeze = np.trapz(psd[(freqs >= 3.0) & (freqs <= 8.0)],
                          freqs[(freqs >= 3.0) & (freqs <= 8.0)])
        feats[f"{prefix}_freeze_idx"] = float(freeze / loco)
    except Exception:
        feats[f"{prefix}_freeze_idx"] = 0.0
    return feats


def asymmetry_features(left_data, right_data, prefix=""):
    """L/R asymmetry features."""
    feats = {}
    try:
        l_rms = np.sqrt(np.mean(left_data**2, axis=0))
        r_rms = np.sqrt(np.mean(right_data**2, axis=0))
        asym = np.abs(l_rms - r_rms) / (l_rms + r_rms + 1e-8)
        feats[f"{prefix}_asym_mean"] = float(np.mean(asym))
        feats[f"{prefix}_asym_max"] = float(np.max(asym))

        # Cross-correlation for phase lag
        for ax in range(min(3, left_data.shape[1])):
            cc = np.correlate(left_data[:, ax] - left_data[:, ax].mean(),
                             right_data[:, ax] - right_data[:, ax].mean(), mode="full")
            lag = np.argmax(cc) - len(left_data[:, ax])
            feats[f"{prefix}_phase_lag_ax{ax}"] = float(lag / FS)
    except Exception:
        feats[f"{prefix}_asym_mean"] = 0.0
        feats[f"{prefix}_asym_max"] = 0.0
        for ax in range(3):
            feats[f"{prefix}_phase_lag_ax{ax}"] = 0.0
    return feats


# ── Per-subject feature extraction ───────────────────────────────────

def extract_features_for_recording(args):
    """Extract all features from one CSV file. Runs in worker process."""
    csv_path, sid, task = args
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None

    feats = {"sid": sid, "task": task}

    # Per-sensor features
    for sensor in SENSORS:
        # Try FreeAcc first, fall back to Acc
        acc_cols_full = [f"{sensor}_{c}" for c in FREEACC_COLS]
        if not all(c in df.columns for c in acc_cols_full):
            acc_cols_full = [f"{sensor}_{c}" for c in ACC_COLS]
        gyr_cols_full = [f"{sensor}_{c}" for c in GYR_COLS]
        euler_cols_full = [f"{sensor}_{c}" for c in EULER_COLS]

        has_acc = all(c in df.columns for c in acc_cols_full)
        has_gyr = all(c in df.columns for c in gyr_cols_full)
        has_euler = all(c in df.columns for c in euler_cols_full)

        if has_acc:
            acc = df[acc_cols_full].values.astype(np.float32)
            acc = np.nan_to_num(acc, nan=0.0)
            acc_mag = np.sqrt(np.sum(acc**2, axis=1))

            for i, ax in enumerate(["x", "y", "z"]):
                feats.update(time_domain_features(acc[:, i], f"{sensor}_acc_{ax}"))
                feats.update(freq_domain_features(acc[:, i], f"{sensor}_acc_{ax}"))
            feats.update(time_domain_features(acc_mag, f"{sensor}_acc_mag"))
            feats.update(freq_domain_features(acc_mag, f"{sensor}_acc_mag"))

            # Gait regularity from vertical acc (Z axis typically)
            if sensor in ["LowerBack", "R_Ankle", "L_Ankle", "R_DorsalFoot", "L_DorsalFoot"]:
                feats.update(gait_regularity_features(acc[:, 2], f"{sensor}_gait"))
                feats.update(freeze_index(acc[:, 2], f"{sensor}"))

        if has_gyr:
            gyr = df[gyr_cols_full].values.astype(np.float32)
            gyr = np.nan_to_num(gyr, nan=0.0)
            gyr_mag = np.sqrt(np.sum(gyr**2, axis=1))
            feats.update(time_domain_features(gyr_mag, f"{sensor}_gyr_mag"))
            feats.update(freq_domain_features(gyr_mag, f"{sensor}_gyr_mag"))

        if has_euler:
            euler = df[euler_cols_full].values.astype(np.float32)
            euler = np.nan_to_num(euler, nan=0.0)
            for i, ax in enumerate(["roll", "pitch", "yaw"]):
                feats.update(time_domain_features(euler[:, i], f"{sensor}_{ax}"))
                feats[f"{sensor}_{ax}_range_total"] = float(np.ptp(euler[:, i]))

    # Cross-sensor asymmetry
    for l_sensor, r_sensor in PAIRED_SENSORS:
        l_cols = [f"{l_sensor}_{c}" for c in ACC_COLS]
        r_cols = [f"{r_sensor}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in l_cols + r_cols):
            ld = df[l_cols].values.astype(np.float32)
            rd = df[r_cols].values.astype(np.float32)
            pair_name = l_sensor.replace("L_", "").replace("R_", "")
            feats.update(asymmetry_features(ld, rd, f"asym_{pair_name}"))

    # Trunk stability (RMS of lower back)
    for ts in TRUNK_SENSORS:
        acc_cols_t = [f"{ts}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in acc_cols_t):
            trunk = df[acc_cols_t].values.astype(np.float32)
            trunk = np.nan_to_num(trunk, nan=0.0)
            feats[f"{ts}_trunk_sway"] = float(np.sqrt(np.mean(trunk[:, :2]**2)))

    feats["n_samples"] = len(df)
    feats["duration_s"] = len(df) / FS

    return feats


def extract_all_features(subjects, sid_list, tasks):
    """Extract features for all subjects across all tasks using multiprocessing."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")

    jobs = []
    for task in tasks:
        for sid in sid_list:
            if sid not in subjects:
                continue
            info = subjects[sid]
            csv_dir = pd_dir if info["group"] == "PD" else hc_dir
            csv_path = os.path.join(csv_dir, f"{sid}_{task}.csv")
            if os.path.exists(csv_path):
                jobs.append((csv_path, sid, task))

    print(f"  Extracting features from {len(jobs)} recordings using {N_CORES} cores...")
    t0 = time.time()

    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        results = list(pool.map(extract_features_for_recording, jobs))

    results = [r for r in results if r is not None]
    elapsed = time.time() - t0
    print(f"  Done: {len(results)} recordings in {elapsed:.0f}s")
    return results


def aggregate_subject_features(feature_records, subjects):
    """Aggregate per-task features to per-subject (mean across tasks)."""
    from collections import defaultdict

    by_subject = defaultdict(list)
    for rec in feature_records:
        by_subject[rec["sid"]].append(rec)

    rows = []
    for sid, recs in by_subject.items():
        if sid not in subjects:
            continue
        info = subjects[sid]
        agg = {"sid": sid, "updrs3": info["updrs3"]}

        # Get all numeric feature keys
        feat_keys = set()
        for r in recs:
            for k, v in r.items():
                if k not in ("sid", "task") and isinstance(v, (int, float)):
                    feat_keys.add(k)

        # Aggregate: mean across tasks
        for k in sorted(feat_keys):
            vals = [r[k] for r in recs if k in r and np.isfinite(r[k])]
            agg[k] = float(np.mean(vals)) if vals else 0.0

        # Add clinical covariates
        cov_names = ["age", "sex", "years_since_dx", "medication", "dbs"]
        if "covariates" not in info:
            # Re-parse to get covariates
            agg["n_tasks"] = len(recs)
            rows.append(agg)
            continue

        for i, cn in enumerate(cov_names):
            agg[cn] = float(info.get("covariates", np.zeros(5))[i]) if hasattr(info.get("covariates", None), "__getitem__") else 0.0

        agg["n_tasks"] = len(recs)
        rows.append(agg)

    return pd.DataFrame(rows)


# ── CatBoost training ────────────────────────────────────────────────

def train_catboost(X_train, y_train, X_val, y_val, X_test, y_test, seed=42):
    """Train CatBoost regressor."""
    try:
        from catboost import CatBoostRegressor
    except ImportError:
        print("  CatBoost not installed, trying XGBoost...")
        return train_xgboost(X_train, y_train, X_val, y_val, X_test, y_test)

    model = CatBoostRegressor(
        iterations=2000,
        learning_rate=0.03,
        depth=6,
        l2_leaf_reg=3.0,
        random_seed=seed,
        verbose=100,
        early_stopping_rounds=100,
        task_type="CPU",
        thread_count=N_CORES,
        loss_function="MAE",
    )
    model.fit(X_train, y_train, eval_set=(X_val, y_val), verbose=100)

    pred_test = model.predict(X_test)
    pred_val = model.predict(X_val)
    return model, pred_test, pred_val


def train_xgboost(X_train, y_train, X_val, y_val, X_test, y_test, seed=42):
    """Fallback: XGBoost regressor."""
    from xgboost import XGBRegressor

    model = XGBRegressor(
        n_estimators=2000, learning_rate=0.03, max_depth=6,
        reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
        early_stopping_rounds=100, objective="reg:absoluteerror",
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=100)

    pred_test = model.predict(X_test)
    pred_val = model.predict(X_val)
    return model, pred_test, pred_val


def train_lightgbm(X_train, y_train, X_val, y_val, X_test, y_test, seed=42):
    """Alternative: LightGBM regressor."""
    try:
        import lightgbm as lgb
    except ImportError:
        return train_xgboost(X_train, y_train, X_val, y_val, X_test, y_test)

    model = lgb.LGBMRegressor(
        n_estimators=2000, learning_rate=0.03, max_depth=6,
        reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
        objective="mae",
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)],
              callbacks=[lgb.early_stopping(100), lgb.log_evaluation(100)])

    pred_test = model.predict(X_test)
    pred_val = model.predict(X_val)
    return model, pred_test, pred_val


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("PHASE 4.2: BIOMECHANICAL FEATURES + GRADIENT BOOSTING")
    print("=" * 70)

    subjects = parse_clinical()
    for sid, covariates in load_subject_covariates().items():
        if sid in subjects:
            subjects[sid]["covariates"] = covariates

    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]

    # ── Extract features ─────────────────────────────────────────────
    print("\n--- Feature extraction (all tasks, all sensors) ---")
    all_records = extract_all_features(subjects, dev_sids + test_sids, TASKS)

    # Aggregate to subject level
    df_features = aggregate_subject_features(all_records, subjects)
    print(f"Feature matrix: {df_features.shape[0]} subjects × {df_features.shape[1]} columns")

    # Save feature matrix
    feat_path = "/root/pd-imu/biomechanical_features.csv"
    df_features.to_csv(feat_path, index=False)
    print(f"Saved to {feat_path}")

    # ── Prepare train/val/test ───────────────────────────────────────
    feat_cols = [c for c in df_features.columns if c not in ("sid", "updrs3")]
    print(f"Feature columns: {len(feat_cols)}")

    dev_mask = df_features["sid"].isin(dev_sids)
    test_mask = df_features["sid"].isin(test_sids)

    df_dev = df_features[dev_mask].copy()
    df_test = df_features[test_mask].copy()
    print(f"Dev: {len(df_dev)}, Test: {len(df_test)}")

    # Replace inf/nan
    for c in feat_cols:
        df_dev[c] = df_dev[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        df_test[c] = df_test[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)

    X_dev = df_dev[feat_cols].values.astype(np.float32)
    y_dev = df_dev["updrs3"].values.astype(np.float32)
    X_test = df_test[feat_cols].values.astype(np.float32)
    y_test = df_test["updrs3"].values.astype(np.float32)

    all_results = []

    # ── Multi-seed CatBoost ──────────────────────────────────────────
    SEEDS = [42, 123, 456, 789, 2024]
    boosters = ["catboost", "xgboost", "lightgbm"]

    for booster_name in boosters:
        print(f"\n{'='*60}")
        print(f"GRADIENT BOOSTING: {booster_name}")
        print(f"{'='*60}")

        train_fn = {"catboost": train_catboost, "xgboost": train_xgboost,
                     "lightgbm": train_lightgbm}[booster_name]

        seed_maes, seed_rs, seed_preds = [], [], []
        for seed in SEEDS:
            np.random.seed(seed)
            rng = np.random.RandomState(seed)

            # Subject-level val split
            dev_unique_idx = np.arange(len(df_dev))
            rng.shuffle(dev_unique_idx)
            n_val = max(1, int(len(dev_unique_idx) * 0.15))
            val_idx = dev_unique_idx[:n_val]
            tr_idx = dev_unique_idx[n_val:]

            X_tr, y_tr = X_dev[tr_idx], y_dev[tr_idx]
            X_va, y_va = X_dev[val_idx], y_dev[val_idx]

            try:
                model, pred_test, pred_val = train_fn(
                    X_tr, y_tr, X_va, y_va, X_test, y_test, seed=seed
                )
                mae = mean_absolute_error(y_test, pred_test)
                r, p = sp_stats.pearsonr(y_test, pred_test)
                print(f"  Seed {seed}: MAE={mae:.2f}, r={r:.3f}")
                seed_maes.append(mae)
                seed_rs.append(r)
                seed_preds.append(pred_test.tolist())
            except Exception as e:
                print(f"  Seed {seed}: FAILED - {e}")
                continue

        if seed_maes:
            mean_mae = np.mean(seed_maes)
            std_mae = np.std(seed_maes)
            ens_pred = np.mean([np.array(p) for p in seed_preds], axis=0)
            ens_mae = mean_absolute_error(y_test, ens_pred)
            ens_r, _ = sp_stats.pearsonr(y_test, ens_pred)
            print(f"  MEAN: MAE={mean_mae:.2f}+/-{std_mae:.2f} r={np.mean(seed_rs):.3f}")
            print(f"  ENS:  MAE={ens_mae:.2f} r={ens_r:.3f}")

            all_results.append({
                "name": booster_name,
                "mean_mae": round(mean_mae, 3), "std_mae": round(std_mae, 3),
                "mean_r": round(np.mean(seed_rs), 3),
                "ens_mae": round(ens_mae, 3), "ens_r": round(ens_r, 3),
                "individual_mae": seed_maes, "individual_r": seed_rs,
                "test_true": y_test.tolist(),
            })

    # ── Feature importance (from best model) ─────────────────────────
    print(f"\n{'='*60}")
    print("TOP 30 FEATURES (CatBoost)")
    print(f"{'='*60}")
    try:
        from catboost import CatBoostRegressor
        # Train final model on all dev
        n_va = max(1, int(len(X_dev) * 0.1))
        final_model = CatBoostRegressor(
            iterations=2000, learning_rate=0.03, depth=6,
            l2_leaf_reg=3.0, random_seed=42, verbose=0,
            early_stopping_rounds=100, task_type="CPU",
            thread_count=N_CORES, loss_function="MAE",
        )
        final_model.fit(X_dev[n_va:], y_dev[n_va:],
                        eval_set=(X_dev[:n_va], y_dev[:n_va]), verbose=0)
        importances = final_model.get_feature_importance()
        top_idx = np.argsort(importances)[::-1][:30]
        for rank, i in enumerate(top_idx):
            print(f"  {rank+1:2d}. {feat_cols[i]:<50s} {importances[i]:.2f}")

        # Save importances
        imp_df = pd.DataFrame({
            "feature": [feat_cols[i] for i in np.argsort(importances)[::-1]],
            "importance": sorted(importances, reverse=True),
        })
        imp_df.to_csv("/root/pd-imu/feature_importances.csv", index=False)
    except Exception as e:
        print(f"  Feature importance failed: {e}")

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("FINAL SUMMARY")
    print(f"{'='*70}")
    print(f"  {'Method':<20} {'Mean MAE':>10} {'Ens MAE':>9} {'Ens r':>7}")
    print(f"  {'-'*50}")
    for r in sorted(all_results, key=lambda x: x["ens_mae"]):
        print(f"  {r['name']:<20} {r['mean_mae']:>6.2f}+/-{r['std_mae']:.2f} "
              f"{r['ens_mae']:>7.2f}  {r['ens_r']:>6.3f}")

    # Save
    with open("/root/pd-imu/biomechanics_results.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nSaved to /root/pd-imu/biomechanics_results.json")


if __name__ == "__main__":
    main()

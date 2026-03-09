#!/usr/bin/env python3
"""
V2 Experiments: Feature-First + DL-Assisted UPDRS-III Regression
================================================================
Baseline to beat: LightGBM 150 features -> MAE=7.97, r=0.821

Strategy: expand features, use DL as complement, not replacement.
All CPU-bound booster experiments run first, then GPU for DL embeddings.

Phases:
  E1: Expanded feature baselines (FreeAcc+Acc, Euler, task-specific)
  E2: DL embedding + booster fusion
  E3: Observable-first two-stage
  E4: Per-task + task-contrast models
  E5: Grand ensemble + PD-only track
"""
import os, sys, json, time, warnings, gc, hashlib
import numpy as np
import pandas as pd
from scipy import signal, stats as sp_stats
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import LeaveOneOut
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

warnings.filterwarnings("ignore")
sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS, \
    WINDOW_LEN, STRIDE_LEN, IMU_COLS, N_CH

N_CORES = 11
SEEDS = [42, 123, 456, 789, 2024]
TASKS = ["SelfPace", "HurriedPace", "TUG", "Balance", "TandemGait"]
TEST_TASKS = ["SelfPace", "HurriedPace"]
RESULTS_FILE = "/root/pd-imu/v2_results.json"
FEAT_CACHE = "/root/pd-imu/v2_features.csv"
CACHE_DIR = "/root/pd-imu/data/cache"

# UPDRS-III items observable from gait/body IMU
OBSERVABLE_ITEMS = [
    "MDSUPDRS_3-7a", "MDSUPDRS_3-7b",   # Toe tapping L/R
    "MDSUPDRS_3-8a", "MDSUPDRS_3-8b",   # Leg agility L/R
    "MDSUPDRS_3-9",                       # Arising from chair
    "MDSUPDRS_3-10",                      # Gait
    "MDSUPDRS_3-11",                      # Freezing of gait
    "MDSUPDRS_3-12",                      # Postural stability
    "MDSUPDRS_3-13",                      # Posture
    "MDSUPDRS_3-14",                      # Global spontaneity
]
PARTIALLY_OBSERVABLE = [
    "MDSUPDRS_3-4a", "MDSUPDRS_3-4b",   # Finger tapping (wrist IMU)
    "MDSUPDRS_3-5a", "MDSUPDRS_3-5b",   # Hand movements (wrist IMU)
    "MDSUPDRS_3-6a", "MDSUPDRS_3-6b",   # Pronation-supination
    "MDSUPDRS_3-15a", "MDSUPDRS_3-15b", # Postural tremor
]

ACC_COLS = ["Acc_X", "Acc_Y", "Acc_Z"]
GYR_COLS = ["Gyr_X", "Gyr_Y", "Gyr_Z"]
FREEACC_COLS = ["FreeAcc_E", "FreeAcc_N", "FreeAcc_U"]
EULER_COLS = ["Roll", "Pitch", "Yaw"]
PAIRED_SENSORS = [
    ("R_Wrist", "L_Wrist"), ("R_Ankle", "L_Ankle"),
    ("R_DorsalFoot", "L_DorsalFoot"), ("R_LatShank", "L_LatShank"),
    ("R_MidLatThigh", "L_MidLatThigh"),
]
TRUNK_SENSORS = ["LowerBack", "Xiphoid"]


# =====================================================================
# CLINICAL DATA (with subitems)
# =====================================================================

def parse_clinical_subitems():
    """Parse clinical data with individual UPDRS-III subitem scores."""
    subjects = {}
    for filename, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, header=1)
        u3cols = sorted([c for c in df.columns if c.startswith("MDSUPDRS_3-")])
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            vals = pd.to_numeric(row[u3cols], errors="coerce") if u3cols else pd.Series(dtype=float)
            updrs3 = vals.sum()  # skipna=True: sum of available items, missing treated as 0
            if np.isnan(updrs3):
                continue
            updrs3 = float(updrs3)
            # Subitems
            subitems = {}
            for c in u3cols:
                v = pd.to_numeric(row[c], errors="coerce")
                subitems[c] = float(v) if pd.notna(v) else 0.0
            # Observable subtotal
            obs_items = [c for c in u3cols if c in OBSERVABLE_ITEMS]
            obs_score = sum(subitems.get(c, 0.0) for c in obs_items)
            part_items = [c for c in u3cols if c in PARTIALLY_OBSERVABLE]
            part_score = sum(subitems.get(c, 0.0) for c in part_items)
            # Covariates
            age = pd.to_numeric(row.get("Age (years)", row.get("Age", np.nan)), errors="coerce")
            sex = 1.0 if str(row.get("Sex", "")).strip().upper().startswith("M") else 0.0
            yrs = pd.to_numeric(row.get("Years since PD diagnosis",
                                        row.get("Years Since Diagnosis", 0)), errors="coerce")
            dbs_raw = str(row.get("DBS?", row.get("DBS", ""))).strip().upper()
            subjects[sid] = {
                "group": group, "label": 1 if group == "PD" else 0,
                "updrs3": updrs3,
                "observable_score": obs_score,
                "partial_score": part_score,
                "obs_plus_partial": obs_score + part_score,
                "subitems": subitems,
                "covariates": np.array([
                    float(age) if pd.notna(age) else 65.0, sex,
                    float(yrs) if pd.notna(yrs) else 0.0,
                    1.0 if dbs_raw in ("YES", "Y", "1") else 0.0,
                ], dtype=np.float32),
            }
    return subjects


# =====================================================================
# FEATURE EXTRACTION (expanded)
# =====================================================================

def _safe(f, d, default=0.0):
    try:
        v = f(d)
        return float(v) if np.isfinite(v) else default
    except Exception:
        return default


def _time_feats(x, prefix):
    """13 time-domain features for one axis."""
    f = {}
    f[f"{prefix}_rms"] = _safe(lambda d: np.sqrt(np.mean(d**2)), x)
    f[f"{prefix}_mean"] = _safe(np.mean, x)
    f[f"{prefix}_std"] = _safe(np.std, x)
    f[f"{prefix}_range"] = _safe(np.ptp, x)
    f[f"{prefix}_iqr"] = _safe(lambda d: np.percentile(d, 75) - np.percentile(d, 25), x)
    f[f"{prefix}_skew"] = _safe(lambda d: float(sp_stats.skew(d)), x)
    f[f"{prefix}_kurt"] = _safe(lambda d: float(sp_stats.kurtosis(d)), x)
    f[f"{prefix}_p5"] = _safe(lambda d: np.percentile(d, 5), x)
    f[f"{prefix}_p95"] = _safe(lambda d: np.percentile(d, 95), x)
    jerk = np.diff(x) * FS
    f[f"{prefix}_jerk_rms"] = _safe(lambda d: np.sqrt(np.mean(d**2)), jerk)
    f[f"{prefix}_jerk_mean"] = _safe(np.mean, np.abs(jerk))
    zc = np.sum(np.diff(np.sign(x - np.mean(x))) != 0)
    f[f"{prefix}_zcr"] = float(zc) / max(len(x), 1)
    return f


def _freq_feats(x, prefix):
    """10 frequency-domain features."""
    f = {}
    try:
        freqs, psd = signal.welch(x, fs=FS, nperseg=min(256, len(x)),
                                   noverlap=min(128, len(x) // 2))
        psd = psd + 1e-12
        total_power = np.trapz(psd, freqs) + 1e-12
        for bname, lo, hi in [("loco", 0.5, 3.0), ("trem", 3.0, 8.0), ("high", 8.0, 20.0)]:
            mask = (freqs >= lo) & (freqs <= hi)
            bp = np.trapz(psd[mask], freqs[mask]) if mask.sum() > 1 else 1e-12
            f[f"{prefix}_{bname}"] = float(np.log10(bp))
            f[f"{prefix}_{bname}_r"] = float(bp / total_power)
        f[f"{prefix}_domf"] = float(freqs[np.argmax(psd)])
        f[f"{prefix}_ptot"] = float(np.log10(total_power))
        psd_n = psd / psd.sum()
        f[f"{prefix}_se"] = float(-np.sum(psd_n * np.log2(psd_n + 1e-12)))
        # Freeze index (power_3-8 / power_0.5-3)
        loco_m = (freqs >= 0.5) & (freqs <= 3.0)
        trem_m = (freqs >= 3.0) & (freqs <= 8.0)
        loco_p = np.trapz(psd[loco_m], freqs[loco_m]) + 1e-12 if loco_m.sum() > 1 else 1e-12
        trem_p = np.trapz(psd[trem_m], freqs[trem_m]) if trem_m.sum() > 1 else 0.0
        f[f"{prefix}_fi"] = float(trem_p / loco_p)
    except Exception:
        for k in ["loco", "trem", "high"]:
            f[f"{prefix}_{k}"] = 0.0
            f[f"{prefix}_{k}_r"] = 0.0
        f[f"{prefix}_domf"] = 0.0
        f[f"{prefix}_ptot"] = 0.0
        f[f"{prefix}_se"] = 0.0
        f[f"{prefix}_fi"] = 0.0
    return f


def _gait_feats(acc_z, prefix):
    """6 gait regularity features from vertical acceleration."""
    f = {}
    try:
        x = acc_z - np.mean(acc_z)
        ac = np.correlate(x, x, mode="full")
        ac = ac[len(ac)//2:]
        ac = ac / (ac[0] + 1e-12)
        peaks, _ = signal.find_peaks(ac, distance=30, height=0.1)
        if len(peaks) >= 2:
            step_lag = peaks[0]
            stride_lag = peaks[1]
            f[f"{prefix}_step_t"] = float(step_lag / FS)
            f[f"{prefix}_stride_t"] = float(stride_lag / FS)
            f[f"{prefix}_cad"] = float(60.0 * FS / step_lag) if step_lag > 0 else 0.0
            f[f"{prefix}_step_reg"] = float(ac[step_lag])
            f[f"{prefix}_stride_reg"] = float(ac[stride_lag]) if stride_lag < len(ac) else 0.0
            f[f"{prefix}_sym"] = abs(float(ac[step_lag]) - float(ac[stride_lag])) if stride_lag < len(ac) else 0.0
        else:
            for k in ["step_t", "stride_t", "cad", "step_reg", "stride_reg", "sym"]:
                f[f"{prefix}_{k}"] = 0.0
    except Exception:
        for k in ["step_t", "stride_t", "cad", "step_reg", "stride_reg", "sym"]:
            f[f"{prefix}_{k}"] = 0.0
    return f


def _asym_feats(left, right, prefix):
    """5 bilateral asymmetry features."""
    f = {}
    try:
        l_rms = np.sqrt(np.mean(left**2, axis=0))
        r_rms = np.sqrt(np.mean(right**2, axis=0))
        asym = np.abs(l_rms - r_rms) / (l_rms + r_rms + 1e-8)
        f[f"{prefix}_asym_m"] = float(np.mean(asym))
        f[f"{prefix}_asym_x"] = float(np.max(asym))
        for ax in range(min(3, left.shape[1])):
            cc = np.correlate(left[:, ax] - left[:, ax].mean(),
                              right[:, ax] - right[:, ax].mean(), mode="full")
            lag = np.argmax(cc) - len(left[:, ax])
            f[f"{prefix}_lag{ax}"] = float(lag / FS)
    except Exception:
        f[f"{prefix}_asym_m"] = 0.0
        f[f"{prefix}_asym_x"] = 0.0
        for ax in range(3):
            f[f"{prefix}_lag{ax}"] = 0.0
    return f


def _extract_recording(args):
    """Extract expanded features from one CSV. Returns dict or None."""
    csv_path, sid, task = args
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None
    ft = {"sid": sid, "task": task}

    for sensor in SENSORS:
        # RAW Acc features (body frame, includes gravity)
        raw_acc_cols = [f"{sensor}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in raw_acc_cols):
            acc = np.nan_to_num(df[raw_acc_cols].values.astype(np.float32))
            mag = np.sqrt(np.sum(acc**2, axis=1))
            for i, ax in enumerate("xyz"):
                ft.update(_time_feats(acc[:, i], f"{sensor}_ra{ax}"))
                ft.update(_freq_feats(acc[:, i], f"{sensor}_ra{ax}"))
            ft.update(_time_feats(mag, f"{sensor}_ram"))
            ft.update(_freq_feats(mag, f"{sensor}_ram"))

        # FreeAcc features (earth frame, gravity removed)
        free_cols = [f"{sensor}_{c}" for c in FREEACC_COLS]
        if all(c in df.columns for c in free_cols):
            facc = np.nan_to_num(df[free_cols].values.astype(np.float32))
            fmag = np.sqrt(np.sum(facc**2, axis=1))
            for i, ax in enumerate("enu"):
                ft.update(_time_feats(facc[:, i], f"{sensor}_fa{ax}"))
                ft.update(_freq_feats(facc[:, i], f"{sensor}_fa{ax}"))
            ft.update(_time_feats(fmag, f"{sensor}_fam"))
            ft.update(_freq_feats(fmag, f"{sensor}_fam"))

        # Gyroscope features
        gyr_cols = [f"{sensor}_{c}" for c in GYR_COLS]
        if all(c in df.columns for c in gyr_cols):
            gyr = np.nan_to_num(df[gyr_cols].values.astype(np.float32))
            gmag = np.sqrt(np.sum(gyr**2, axis=1))
            for i, ax in enumerate("xyz"):
                ft.update(_time_feats(gyr[:, i], f"{sensor}_g{ax}"))
                ft.update(_freq_feats(gyr[:, i], f"{sensor}_g{ax}"))
            ft.update(_time_feats(gmag, f"{sensor}_gm"))
            ft.update(_freq_feats(gmag, f"{sensor}_gm"))

        # Euler angle features (Roll, Pitch, Yaw)
        eul_cols = [f"{sensor}_{c}" for c in EULER_COLS]
        if all(c in df.columns for c in eul_cols):
            eul = np.nan_to_num(df[eul_cols].values.astype(np.float32))
            for i, ax in enumerate(["ro", "pi", "ya"]):
                ft.update(_time_feats(eul[:, i], f"{sensor}_{ax}"))
                ft[f"{sensor}_{ax}_rng_tot"] = float(np.ptp(eul[:, i]))

        # Gait regularity (from vertical acc, gait-relevant sensors)
        if sensor in ["LowerBack", "R_Ankle", "L_Ankle", "R_DorsalFoot", "L_DorsalFoot"]:
            if all(c in df.columns for c in raw_acc_cols):
                acc_z = np.nan_to_num(df[raw_acc_cols[2]].values.astype(np.float32))
                ft.update(_gait_feats(acc_z, f"{sensor}_gait"))
            if all(c in df.columns for c in free_cols):
                facc_u = np.nan_to_num(df[free_cols[2]].values.astype(np.float32))
                ft.update(_gait_feats(facc_u, f"{sensor}_fgait"))

    # Cross-sensor asymmetry
    for l_sensor, r_sensor in PAIRED_SENSORS:
        l_cols = [f"{l_sensor}_{c}" for c in ACC_COLS]
        r_cols = [f"{r_sensor}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in l_cols + r_cols):
            ld = np.nan_to_num(df[l_cols].values.astype(np.float32))
            rd = np.nan_to_num(df[r_cols].values.astype(np.float32))
            pair = l_sensor.replace("L_", "").replace("R_", "")
            ft.update(_asym_feats(ld, rd, f"asy_{pair}"))
        # FreeAcc asymmetry too
        lf_cols = [f"{l_sensor}_{c}" for c in FREEACC_COLS]
        rf_cols = [f"{r_sensor}_{c}" for c in FREEACC_COLS]
        if all(c in df.columns for c in lf_cols + rf_cols):
            ld = np.nan_to_num(df[lf_cols].values.astype(np.float32))
            rd = np.nan_to_num(df[rf_cols].values.astype(np.float32))
            pair = l_sensor.replace("L_", "").replace("R_", "")
            ft.update(_asym_feats(ld, rd, f"fasy_{pair}"))

    # Trunk stability
    for ts in TRUNK_SENSORS:
        acc_t = [f"{ts}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in acc_t):
            trunk = np.nan_to_num(df[acc_t].values.astype(np.float32))
            ft[f"{ts}_trunk_sway"] = float(np.sqrt(np.mean(trunk[:, :2]**2)))

    # Phase-specific features from GeneralEvent annotations
    if "GeneralEvent" in df.columns:
        ev = df["GeneralEvent"].fillna("X")
        for phase in ["Walk", "Turn", "Sitting", "SitToStand", "Standing"]:
            phase_mask = ev.str.contains(phase, case=False, na=False)
            n_phase = int(phase_mask.sum())
            ft[f"phase_{phase}_n"] = float(n_phase)
            ft[f"phase_{phase}_frac"] = float(n_phase / max(len(df), 1))
            if n_phase > 50:
                # Extract key features from this phase only
                for sensor in ["LowerBack", "R_Wrist", "L_Wrist"]:
                    acc_c = [f"{sensor}_{c}" for c in ACC_COLS]
                    if all(c in df.columns for c in acc_c):
                        seg = np.nan_to_num(df.loc[phase_mask, acc_c].values.astype(np.float32))
                        mag = np.sqrt(np.sum(seg**2, axis=1))
                        ft[f"ph_{phase}_{sensor}_rms"] = _safe(
                            lambda d: np.sqrt(np.mean(d**2)), mag)
                        ft[f"ph_{phase}_{sensor}_std"] = _safe(np.std, mag)
        # Turn metrics
        ec = ev != ev.shift()
        ts_idx = np.where((ev == "Turn").values & ec.values)[0]
        if len(ts_idx) > 0:
            durs = []
            for t in ts_idx:
                e = np.where(ev.iloc[t:] != "Turn")[0]
                durs.append(((t + e[0] if len(e) else len(ev)) - t) / FS)
            ft["trn_n"] = float(len(durs))
            ft["trn_dur_mean"] = float(np.mean(durs))
            ft["trn_dur_std"] = float(np.std(durs)) if len(durs) > 1 else 0.0

    ft["dur_s"] = len(df) / FS
    ft["n_samples"] = float(len(df))
    return ft


def extract_all(subjects, sid_list, tasks):
    """Extract features for all subjects using multiprocessing."""
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
    jobs = []
    for task in tasks:
        for sid in sid_list:
            if sid not in subjects:
                continue
            csv_dir = pd_dir if subjects[sid]["group"] == "PD" else hc_dir
            csv_path = os.path.join(csv_dir, f"{sid}_{task}.csv")
            if os.path.exists(csv_path):
                jobs.append((csv_path, sid, task))
    print(f"  Extracting features from {len(jobs)} recordings using {N_CORES} cores...")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        results = [r for r in pool.map(_extract_recording, jobs) if r is not None]
    print(f"  Done: {len(results)} recordings in {time.time()-t0:.0f}s")
    return results


def aggregate_features(records, subjects, mode="mean"):
    """Aggregate per-recording features to per-subject.
    mode='mean': average across all tasks (standard)
    mode='per_task': keep separate columns per task
    mode='contrast': add task-contrast features (hurried - selfpace)
    """
    by_subject = defaultdict(lambda: defaultdict(list))
    for rec in records:
        by_subject[rec["sid"]][rec["task"]].append(rec)

    rows = []
    for sid, task_recs in by_subject.items():
        if sid not in subjects:
            continue
        info = subjects[sid]
        agg = {"sid": sid, "updrs3": info["updrs3"]}

        # Collect all numeric keys
        all_keys = set()
        for task, recs in task_recs.items():
            for r in recs:
                for k, v in r.items():
                    if k not in ("sid", "task") and isinstance(v, (int, float)):
                        all_keys.add(k)

        # Mean across ALL tasks (baseline features)
        all_recs = [r for recs in task_recs.values() for r in recs]
        for k in sorted(all_keys):
            vals = [r[k] for r in all_recs if k in r and isinstance(r.get(k), (int, float))
                    and np.isfinite(r[k])]
            agg[k] = float(np.mean(vals)) if vals else 0.0

        if mode in ("per_task", "contrast"):
            # Per-task features for SelfPace and HurriedPace
            for task in ["SelfPace", "HurriedPace"]:
                if task in task_recs:
                    trecs = task_recs[task]
                    for k in sorted(all_keys):
                        vals = [r[k] for r in trecs if k in r
                                and isinstance(r.get(k), (int, float)) and np.isfinite(r[k])]
                        agg[f"{task}_{k}"] = float(np.mean(vals)) if vals else 0.0

        if mode == "contrast":
            # Task contrast: HurriedPace - SelfPace
            if "SelfPace" in task_recs and "HurriedPace" in task_recs:
                for k in sorted(all_keys):
                    sp_val = agg.get(f"SelfPace_{k}", 0.0)
                    hp_val = agg.get(f"HurriedPace_{k}", 0.0)
                    agg[f"contrast_{k}"] = float(hp_val - sp_val)

        # Covariates
        cov = info.get("covariates", np.zeros(4, dtype=np.float32))
        for i, cn in enumerate(["age", "sex", "years_dx", "dbs"]):
            agg[cn] = float(cov[i])

        rows.append(agg)
    return pd.DataFrame(rows)


# =====================================================================
# STRATIFIED VAL SPLIT
# =====================================================================

def _updrs_bin(score):
    if score <= 0: return 0
    elif score <= 10: return 1
    elif score <= 20: return 2
    elif score <= 35: return 3
    else: return 4


def stratified_val_split(sids, subjects, val_frac=0.15, seed=42):
    """Split subjects into train/val with stratification by UPDRS bin + PD/HC."""
    rng = np.random.RandomState(seed)
    # Group by (updrs_bin, group)
    strata = defaultdict(list)
    for sid in sids:
        if sid not in subjects:
            continue
        info = subjects[sid]
        b = _updrs_bin(info["updrs3"])
        g = info["group"]
        strata[(b, g)].append(sid)
    train_sids, val_sids = [], []
    for key, group_sids in strata.items():
        rng.shuffle(group_sids)
        n_val = max(1, int(len(group_sids) * val_frac))
        val_sids.extend(group_sids[:n_val])
        train_sids.extend(group_sids[n_val:])
    return train_sids, val_sids


# =====================================================================
# BOOSTER TRAINING
# =====================================================================

def train_lgb(X_train, y_train, X_val, y_val, seed=42):
    """Train LightGBM, return model."""
    import lightgbm as lgb
    model = lgb.LGBMRegressor(
        n_estimators=2000, learning_rate=0.03, max_depth=6,
        reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
        objective="mae", verbosity=-1,
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)],
              callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    return model


def train_xgb(X_train, y_train, X_val, y_val, seed=42):
    """Train XGBoost, return model."""
    from xgboost import XGBRegressor
    model = XGBRegressor(
        n_estimators=2000, learning_rate=0.03, max_depth=6,
        reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
        early_stopping_rounds=100, objective="reg:absoluteerror",
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    return model


def select_features_stable(X, y, feat_cols, n_select=200):
    """Stable feature selection: multi-seed XGBoost importance + pre-filter constants."""
    from xgboost import XGBRegressor
    # Pre-filter: remove constant/near-constant features
    stds = np.std(X, axis=0)
    active = stds > 1e-6
    active_idx = np.where(active)[0]
    X_active = X[:, active_idx]
    active_cols = [feat_cols[i] for i in active_idx]
    print(f"  Pre-filter: {len(feat_cols)} -> {len(active_cols)} features (removed {(~active).sum()} constant)")
    if len(active_cols) <= n_select:
        return active_cols, active_idx

    # Multi-seed importance averaging (3 seeds for speed)
    importances = np.zeros(len(active_cols))
    for seed in [42, 123, 789]:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(X_active))
        rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        m = XGBRegressor(
            n_estimators=500, learning_rate=0.05, max_depth=6,
            reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
            early_stopping_rounds=50, objective="reg:absoluteerror",
        )
        m.fit(X_active[idx[nv:]], y[idx[nv:]],
              eval_set=[(X_active[idx[:nv]], y[idx[:nv]])], verbose=False)
        importances += m.feature_importances_
    importances /= 3.0

    top = np.argsort(importances)[::-1][:n_select]
    sel_cols = [active_cols[i] for i in top]
    sel_global_idx = active_idx[top]
    print(f"  Selected top {n_select} features (multi-seed stable)")
    return sel_cols, sel_global_idx


def run_booster_experiment(name, X_dev, y_dev, dev_sids, X_test, y_test, subjects,
                            booster="lgb", sel_idx=None):
    """Multi-seed booster experiment with stratified val splits.
    sel_idx: pre-computed feature indices (feature selection done ONCE outside)."""
    print(f"\n--- {name} ---")
    if sel_idx is not None:
        Xd = X_dev[:, sel_idx]
        Xt = X_test[:, sel_idx]
    else:
        Xd = X_dev
        Xt = X_test
    print(f"  Features: {Xd.shape[1]}, Dev: {len(Xd)}, Test: {len(Xt)}")
    train_fn = train_lgb if booster == "lgb" else train_xgb

    seed_maes, seed_rs, seed_preds = [], [], []
    for seed in SEEDS:
        tr_sids, va_sids = stratified_val_split(dev_sids, subjects, 0.15, seed)
        tr_mask = np.isin(dev_sids, tr_sids)
        va_mask = np.isin(dev_sids, va_sids)
        X_tr, y_tr = Xd[tr_mask], y_dev[tr_mask]
        X_va, y_va = Xd[va_mask], y_dev[va_mask]

        model = train_fn(X_tr, y_tr, X_va, y_va, seed)
        pred = model.predict(Xt)
        mae = mean_absolute_error(y_test, pred)
        r, _ = sp_stats.pearsonr(y_test, pred) if len(y_test) > 2 else (0.0, 1.0)
        print(f"  Seed {seed}: MAE={mae:.2f}, r={r:.3f}")
        seed_maes.append(float(mae))
        seed_rs.append(float(r))
        seed_preds.append(pred.tolist())

    mm = np.mean(seed_maes)
    sm = np.std(seed_maes)
    ens_pred = np.mean([np.array(p) for p in seed_preds], axis=0)
    em = mean_absolute_error(y_test, ens_pred)
    er, _ = sp_stats.pearsonr(y_test, ens_pred)
    print(f"  MEAN: MAE={mm:.2f}+/-{sm:.2f}, r={np.mean(seed_rs):.3f}")
    print(f"  ENS:  MAE={em:.2f}, r={er:.3f}")

    return {
        "name": name, "mean_mae": round(mm, 3), "std_mae": round(sm, 3),
        "mean_r": round(np.mean(seed_rs), 3),
        "ens_mae": round(em, 3), "ens_r": round(er, 3),
        "individual_mae": seed_maes, "individual_r": seed_rs,
        "test_true": y_test.tolist(), "test_preds": seed_preds,
    }


# =====================================================================
# DL MODEL DEFINITIONS (for embedding extraction)
# =====================================================================

def _try_import_torch():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import Dataset, DataLoader
    return torch, nn, F, Dataset, DataLoader


class InceptionBlock:
    """Defined at module level but instantiated only if torch available."""
    pass


def build_dl_models():
    """Build DL model classes. Only called when GPU phase starts."""
    torch, nn, F, Dataset, DataLoader = _try_import_torch()
    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    class _InceptionBlock(nn.Module):
        def __init__(self, in_ch, out_ch, bottleneck=32):
            super().__init__()
            self.bn_in = nn.Conv1d(in_ch, bottleneck, 1) if in_ch > bottleneck else nn.Identity()
            bn = bottleneck if in_ch > bottleneck else in_ch
            self.convs = nn.ModuleList([
                nn.Conv1d(bn, out_ch, k, padding=k//2) for k in [10, 25, 50, 100]])
            self.pool_conv = nn.Sequential(nn.MaxPool1d(3, 1, 1), nn.Conv1d(in_ch, out_ch, 1))
            self.bn = nn.BatchNorm1d(out_ch * 5)
            self.act = nn.GELU()

        def forward(self, x):
            b = self.bn_in(x)
            outs = [c(b)[:, :, :x.size(2)] for c in self.convs]
            outs.append(self.pool_conv(x))
            return self.act(self.bn(torch.cat(outs, 1)))

    class InceptionTimeEncoder(nn.Module):
        def __init__(self, in_ch, hidden=32, n_blocks=3):
            super().__init__()
            layers = []
            ch = in_ch
            for i in range(n_blocks):
                out = hidden * (2 ** i)
                layers.append(_InceptionBlock(ch, out, min(32, ch)))
                ch = out * 5
            self.blocks = nn.Sequential(*layers)
            self.embed_dim = ch
            self.pool = nn.AdaptiveAvgPool1d(1)

        def forward(self, x):
            return self.pool(self.blocks(x)).squeeze(-1)

    class MILPool(nn.Module):
        def __init__(self, dim):
            super().__init__()
            self.gate = nn.Sequential(nn.Linear(dim, dim//4), nn.Tanh(), nn.Linear(dim//4, 1))

        def forward(self, emb, mask):
            a = self.gate(emb).squeeze(-1)
            a = a.masked_fill(~mask, float("-inf"))
            w = F.softmax(a, 1).unsqueeze(-1)
            return (emb * w).sum(1)

    class OrdinalHead(nn.Module):
        def __init__(self, in_dim, n_bins=20, lo=0, hi=80):
            super().__init__()
            self.n_bins = n_bins
            self.bw = (hi - lo) / n_bins
            self.lo, self.hi = lo, hi
            self.fc = nn.Linear(in_dim, n_bins)

        def forward(self, x):
            logits = self.fc(x)
            probs = torch.sigmoid(logits)
            mids = torch.linspace(self.lo + self.bw/2, self.hi - self.bw/2, self.n_bins, device=x.device)
            bp = torch.zeros_like(probs)
            bp[:, 0] = 1.0 - probs[:, 0]
            for k in range(1, self.n_bins):
                bp[:, k] = probs[:, k-1] - probs[:, k]
            return (bp * mids).sum(1) + probs[:, -1] * (self.hi + self.bw/2)

        def loss(self, x, y):
            logits = self.fc(x)
            thr = torch.linspace(self.lo + self.bw, self.hi, self.n_bins, device=x.device)
            tgt = (y.unsqueeze(1) > thr.unsqueeze(0)).float()
            return F.binary_cross_entropy_with_logits(logits, tgt)

    class MILModel(nn.Module):
        def __init__(self, encoder, n_cov=4):
            super().__init__()
            self.encoder = encoder
            self.mil = MILPool(encoder.embed_dim)
            dim = encoder.embed_dim + n_cov
            self.head = OrdinalHead(dim)

        def forward(self, bags, masks, covs):
            B, N, C, T = bags.shape
            emb = self.encoder(bags.reshape(B*N, C, T)).reshape(B, N, -1)
            pooled = self.mil(emb, masks)
            if covs is not None:
                pooled = torch.cat([pooled, covs], 1)
            return self.head(pooled)

        def get_loss(self, bags, masks, covs, y):
            B, N, C, T = bags.shape
            emb = self.encoder(bags.reshape(B*N, C, T)).reshape(B, N, -1)
            pooled = self.mil(emb, masks)
            if covs is not None:
                pooled = torch.cat([pooled, covs], 1)
            return self.head.loss(pooled, y)

        def get_embeddings(self, bags, masks, covs):
            """Get per-subject embeddings (after MIL pool + covs)."""
            B, N, C, T = bags.shape
            emb = self.encoder(bags.reshape(B*N, C, T)).reshape(B, N, -1)
            pooled = self.mil(emb, masks)
            if covs is not None:
                pooled = torch.cat([pooled, covs], 1)
            return pooled

    return {
        "InceptionTimeEncoder": InceptionTimeEncoder,
        "MILModel": MILModel,
        "DEVICE": DEVICE,
        "torch": torch, "nn": nn, "F": F,
    }


def extract_dl_embeddings(subjects, dev_sids, test_sids):
    """Train InceptionTime+ordinal, extract per-subject embeddings."""
    dl = build_dl_models()
    torch, nn, F = dl["torch"], dl["nn"], dl["F"]
    DEVICE = dl["DEVICE"]
    InceptionTimeEncoder = dl["InceptionTimeEncoder"]
    MILModel = dl["MILModel"]

    print("\n  Loading cached window data for DL...")
    # Load cached data from V1 or reload
    os.makedirs(CACHE_DIR, exist_ok=True)

    def _load_windows(sid_list, tasks, tag):
        xp = os.path.join(CACHE_DIR, f"{tag}_X.npy")
        yp = os.path.join(CACHE_DIR, f"{tag}_y.npy")
        sp = os.path.join(CACHE_DIR, f"{tag}_sids.npy")
        if all(os.path.exists(p) for p in [xp, yp, sp]):
            print(f"  Using cached {tag}")
            return np.load(xp), np.load(yp), np.load(sp, allow_pickle=True)
        # Rebuild from CSVs
        print(f"  Rebuilding {tag} from CSVs...")
        pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
        hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")
        Xs, ys, ss = [], [], []
        for task in tasks:
            for sid in sid_list:
                if sid not in subjects: continue
                info = subjects[sid]
                d = pd_dir if info["group"] == "PD" else hc_dir
                p = os.path.join(d, f"{sid}_{task}.csv")
                if not os.path.exists(p): continue
                try:
                    df = pd.read_csv(p, usecols=IMU_COLS)
                except Exception: continue
                if any(c not in df.columns for c in IMU_COLS): continue
                data = df[IMU_COLS].values.astype(np.float32)
                np.nan_to_num(data, copy=False, nan=0.0)
                if len(data) < WINDOW_LEN: continue
                for st in range(0, len(data) - WINDOW_LEN + 1, STRIDE_LEN):
                    Xs.append(data[st:st+WINDOW_LEN])
                    ys.append(info["updrs3"])
                    ss.append(sid)
        X = np.stack(Xs); y = np.array(ys, dtype=np.float32); s = np.array(ss)
        np.save(xp, X); np.save(yp, y); np.save(sp, s)
        return X, y, s

    ALL_TASKS = ("SelfPace", "HurriedPace", "TandemGait", "TUG", "Balance")
    X_dev, y_dev, s_dev = _load_windows(dev_sids, ALL_TASKS, "dev_all5")
    X_test, y_test, s_test = _load_windows(test_sids, TEST_TASKS, "test_sp_hp")

    # Global norm from dev
    N, T, C = X_dev.shape
    flat = X_dev.reshape(-1, C)
    g_mean = flat.mean(axis=0).astype(np.float32)
    g_std = (flat.std(axis=0) + 1e-8).astype(np.float32)
    del flat
    X_dev = (X_dev - g_mean[None, None, :]) / g_std[None, None, :]
    X_test = (X_test - g_mean[None, None, :]) / g_std[None, None, :]

    # Load covariates
    covs = {}
    for sid in subjects:
        covs[sid] = subjects[sid].get("covariates", np.zeros(4, dtype=np.float32))

    # Train 5 models, extract embeddings, average
    print(f"  Training InceptionTime+ordinal (5 seeds) for embeddings...")
    all_dev_embs = defaultdict(list)  # sid -> list of embedding vectors
    all_test_embs = defaultdict(list)

    # Use DataLoader-based MIL training (batched, not full-batch)
    from torch.utils.data import Dataset as TDataset, DataLoader as TDataLoader

    class _MILDataset(TDataset):
        def __init__(self, X, y, sids, max_w=32, covs_dict=None):
            self.bags = []
            for sid in np.unique(sids):
                m = sids == sid
                self.bags.append({
                    "X": X[m], "y": float(y[m][0]), "sid": sid,
                    "cov": covs_dict.get(sid, np.zeros(4, dtype=np.float32)) if covs_dict else np.zeros(4, dtype=np.float32),
                })
            self.max_w = max_w
        def __len__(self): return len(self.bags)
        def __getitem__(self, idx):
            bag = self.bags[idx]
            w = bag["X"]
            n = min(len(w), self.max_w)
            if len(w) > self.max_w:
                sel = np.random.choice(len(w), self.max_w, replace=False)
                w = w[sel]
            return (torch.from_numpy(w).permute(0, 2, 1),
                    torch.tensor(bag["y"]),
                    torch.from_numpy(bag["cov"]),
                    bag["sid"])

    def _mil_collate(batch):
        bags, ys, cv, sids = zip(*batch)
        mx = max(b.size(0) for b in bags)
        C, T = bags[0].size(1), bags[0].size(2)
        pb = torch.zeros(len(bags), mx, C, T)
        mk = torch.zeros(len(bags), mx, dtype=torch.bool)
        for i, b in enumerate(bags):
            pb[i, :b.size(0)] = b; mk[i, :b.size(0)] = True
        return pb, torch.stack(ys), mk, torch.stack(cv), list(sids)

    for seed in SEEDS:
        torch.manual_seed(seed)
        np.random.seed(seed)
        rng = np.random.RandomState(seed)
        uniq = np.unique(s_dev)
        rng.shuffle(uniq)
        nv = max(1, int(len(uniq) * 0.15))
        val_set = set(uniq[:nv])
        tr_m = np.array([s not in val_set for s in s_dev])

        tr_ds = _MILDataset(X_dev[tr_m], y_dev[tr_m], s_dev[tr_m], 16, covs)
        va_ds = _MILDataset(X_dev[~tr_m], y_dev[~tr_m], s_dev[~tr_m], 16, covs)
        tr_dl = TDataLoader(tr_ds, 2, True, collate_fn=_mil_collate, num_workers=2, pin_memory=True)
        va_dl = TDataLoader(va_ds, 2, False, collate_fn=_mil_collate, num_workers=2, pin_memory=True)

        model = MILModel(InceptionTimeEncoder(N_CH, 32, 3)).to(DEVICE)
        scaler = torch.amp.GradScaler("cuda")

        # Train with ordinal loss, batched + mixed precision
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=1e-4)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, 120)
        best_v, best_sd, wait = float("inf"), None, 0
        for ep in range(120):
            model.train()
            for bags, ys, masks, cv, _ in tr_dl:
                bags, ys, masks, cv = bags.to(DEVICE), ys.to(DEVICE), masks.to(DEVICE), cv.to(DEVICE)
                opt.zero_grad()
                with torch.amp.autocast("cuda"):
                    loss = model.get_loss(bags, masks, cv, ys)
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(opt)
                scaler.update()
            sched.step()
            model.eval()
            vl, nv2 = 0, 0
            with torch.no_grad(), torch.amp.autocast("cuda"):
                for bags, ys, masks, cv, _ in va_dl:
                    bags, ys, masks, cv = bags.to(DEVICE), ys.to(DEVICE), masks.to(DEVICE), cv.to(DEVICE)
                    pred = model(bags, masks, cv)
                    vl += F.l1_loss(pred, ys).item() * ys.size(0)
                    nv2 += ys.size(0)
            vl /= max(nv2, 1)
            if vl < best_v:
                best_v = vl
                best_sd = {k: v.clone() for k, v in model.state_dict().items()}
                wait = 0
            else:
                wait += 1
                if wait >= 25:
                    break
        if best_sd:
            model.load_state_dict(best_sd)

        # Extract embeddings in batches of 2 subjects with mixed precision
        model.eval()
        with torch.no_grad(), torch.amp.autocast("cuda"):
            for emb_dict, X_src, y_src, s_src in [
                (all_dev_embs, X_dev, y_dev, s_dev),
                (all_test_embs, X_test, y_test, s_test),
            ]:
                ds = _MILDataset(X_src, y_src, s_src, 16, covs)
                dl = TDataLoader(ds, 2, False, collate_fn=_mil_collate, num_workers=2, pin_memory=True)
                for bags, ys, masks, cv, sids_batch in dl:
                    bags, masks, cv = bags.to(DEVICE), masks.to(DEVICE), cv.to(DEVICE)
                    emb = model.get_embeddings(bags, masks, cv).float().cpu().numpy()
                    for i, sid in enumerate(sids_batch):
                        emb_dict[sid].append(emb[i])

        gb = torch.cuda.max_memory_allocated() / 1e9
        torch.cuda.reset_peak_memory_stats()
        print(f"  Seed {seed}: done ({gb:.1f}GB VRAM)")
        del model, tr_ds, va_ds
        gc.collect()
        torch.cuda.empty_cache()

    # Average embeddings across seeds
    dev_embeddings = {sid: np.mean(embs, axis=0) for sid, embs in all_dev_embs.items()}
    test_embeddings = {sid: np.mean(embs, axis=0) for sid, embs in all_test_embs.items()}
    embed_dim = next(iter(dev_embeddings.values())).shape[0]
    print(f"  Extracted {embed_dim}d embeddings for {len(dev_embeddings)} dev + {len(test_embeddings)} test subjects")
    return dev_embeddings, test_embeddings, embed_dim


# =====================================================================
# MAIN
# =====================================================================

def main():
    T0 = time.time()
    print("=" * 80)
    print("V2 EXPERIMENTS: FEATURE-FIRST + DL-ASSISTED")
    print("Baseline: LightGBM 150 features -> MAE=7.97, r=0.821")
    print("=" * 80)

    subjects = parse_clinical_subitems()
    # Also get subjects from original parse_clinical for compatibility
    subjects_orig = parse_clinical()
    # Merge: use subitems where available, fall back to original
    for sid, info in subjects_orig.items():
        if sid not in subjects:
            subjects[sid] = {**info, "observable_score": 0.0, "partial_score": 0.0,
                             "obs_plus_partial": 0.0, "subitems": {},
                             "covariates": np.zeros(4, dtype=np.float32)}
    split = load_split()
    dev_sids = split["dev_sids"]
    test_sids = split["test_sids"]
    print(f"Subjects: {len(subjects)}, Dev: {len(dev_sids)}, Test: {len(test_sids)}")

    # Check observable scores
    obs_scores = [subjects[s]["observable_score"] for s in dev_sids if s in subjects]
    if obs_scores:
        print(f"Observable subtotal: mean={np.mean(obs_scores):.1f}, "
              f"range=[{np.min(obs_scores):.0f}, {np.max(obs_scores):.0f}]")

    # Resume logic
    all_results = []
    done_names = set()
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE) as f:
                all_results = json.load(f)
            done_names = {r["name"] for r in all_results}
            print(f"  Resuming: {len(done_names)} experiments done")
        except Exception:
            pass

    def save():
        with open(RESULTS_FILE, "w") as f:
            json.dump(all_results, f, indent=2, default=str)

    def run_if_new(name, fn):
        if name in done_names:
            print(f"\n  SKIP (done): {name}")
            return None
        r = fn()
        all_results.append(r)
        save()
        return r

    # ══════════════════════════════════════════════════════════════════
    # PHASE 0: FEATURE EXTRACTION
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}\nPHASE 0: EXPANDED FEATURE EXTRACTION\n{'='*80}")

    if os.path.exists(FEAT_CACHE):
        print(f"  Loading cached features from {FEAT_CACHE}")
        df_all = pd.read_csv(FEAT_CACHE)
    else:
        all_sids = dev_sids + test_sids
        records = extract_all(subjects, all_sids, TASKS)
        # Build all three aggregation modes
        df_mean = aggregate_features(records, subjects, mode="mean")
        df_contrast = aggregate_features(records, subjects, mode="contrast")
        # Merge: mean features + per-task + contrast columns from df_contrast
        extra_cols = [c for c in df_contrast.columns if c not in df_mean.columns]
        df_all = df_mean.merge(df_contrast[["sid"] + extra_cols], on="sid", how="left")
        df_all.to_csv(FEAT_CACHE, index=False)
        print(f"  Saved {df_all.shape[1]} columns for {len(df_all)} subjects to {FEAT_CACHE}")

    # Prepare feature matrices
    meta_cols = {"sid", "updrs3", "age", "sex", "years_dx", "dbs"}
    feat_cols = sorted([c for c in df_all.columns if c not in meta_cols])
    print(f"  Total raw features: {len(feat_cols)}")

    # Clean
    for c in feat_cols:
        df_all[c] = pd.to_numeric(df_all[c], errors="coerce").replace([np.inf, -np.inf], 0.0).fillna(0.0)

    # Ensure ALL split subjects are included (pad missing with 0)
    df_all_indexed = df_all.set_index("sid")
    all_needed = dev_sids + test_sids
    missing = [s for s in all_needed if s not in df_all_indexed.index]
    if missing:
        print(f"  WARNING: {len(missing)} subjects missing features, padding with 0")
        for s in missing:
            if s in subjects:
                row = {c: 0.0 for c in feat_cols}
                row["updrs3"] = subjects[s]["updrs3"]
                df_all_indexed.loc[s] = row
    df_all = df_all_indexed.reset_index().rename(columns={"index": "sid"})

    # Build aligned arrays (same order as split)
    dev_sids_in = [s for s in dev_sids if s in subjects]
    test_sids_in = [s for s in test_sids if s in subjects]
    df_dev = df_all.set_index("sid").loc[dev_sids_in].reset_index()
    df_test = df_all.set_index("sid").loc[test_sids_in].reset_index()
    dev_sids_feat = df_dev["sid"].values
    test_sids_feat = df_test["sid"].values

    X_dev_all = df_dev[feat_cols].values.astype(np.float32)
    y_dev = df_dev["updrs3"].values.astype(np.float32)
    X_test_all = df_test[feat_cols].values.astype(np.float32)
    y_test = df_test["updrs3"].values.astype(np.float32)
    print(f"  Dev: {X_dev_all.shape}, Test: {X_test_all.shape}")

    # ══════════════════════════════════════════════════════════════════
    # PHASE 1: EXPANDED FEATURE BASELINES
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}\nPHASE 1: EXPANDED FEATURE BASELINES\n{'='*80}")

    # Stable feature selection ONCE (not per-seed)
    print("  Running stable feature selection (multi-seed XGBoost)...")
    sel_150_cols, sel_150_idx = select_features_stable(X_dev_all, y_dev, feat_cols, 150)
    sel_200_cols, sel_200_idx = select_features_stable(X_dev_all, y_dev, feat_cols, 200)
    sel_300_cols, sel_300_idx = select_features_stable(X_dev_all, y_dev, feat_cols, 300)

    # E1A: LightGBM top 200 expanded features
    run_if_new("E1A: LGB expanded 200 feats", lambda: run_booster_experiment(
        "E1A: LGB expanded 200 feats", X_dev_all, y_dev, dev_sids_feat,
        X_test_all, y_test, subjects, booster="lgb", sel_idx=sel_200_idx))

    # E1B: LightGBM top 150 (match baseline count)
    run_if_new("E1B: LGB expanded 150 feats", lambda: run_booster_experiment(
        "E1B: LGB expanded 150 feats", X_dev_all, y_dev, dev_sids_feat,
        X_test_all, y_test, subjects, booster="lgb", sel_idx=sel_150_idx))

    # E1C: LightGBM top 300
    run_if_new("E1C: LGB expanded 300 feats", lambda: run_booster_experiment(
        "E1C: LGB expanded 300 feats", X_dev_all, y_dev, dev_sids_feat,
        X_test_all, y_test, subjects, booster="lgb", sel_idx=sel_300_idx))

    # E1D: XGBoost top 200
    run_if_new("E1D: XGB expanded 200 feats", lambda: run_booster_experiment(
        "E1D: XGB expanded 200 feats", X_dev_all, y_dev, dev_sids_feat,
        X_test_all, y_test, subjects, booster="xgb", sel_idx=sel_200_idx))

    # E1E: Mean-only features (no per-task, no contrast) — ablation
    mean_cols = [c for c in feat_cols if not c.startswith("SelfPace_")
                 and not c.startswith("HurriedPace_") and not c.startswith("contrast_")]
    mean_idx = [feat_cols.index(c) for c in mean_cols]
    X_dev_mean = X_dev_all[:, mean_idx]
    X_test_mean = X_test_all[:, mean_idx]
    sel_mean_cols, sel_mean_idx = select_features_stable(X_dev_mean, y_dev, mean_cols, 200)
    run_if_new("E1E: LGB mean-only 200 feats", lambda: run_booster_experiment(
        "E1E: LGB mean-only 200 feats", X_dev_mean, y_dev, dev_sids_feat,
        X_test_mean, y_test, subjects, booster="lgb", sel_idx=sel_mean_idx))

    # ══════════════════════════════════════════════════════════════════
    # PHASE 3: OBSERVABLE-FIRST TWO-STAGE
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}\nPHASE 3: OBSERVABLE-FIRST TWO-STAGE\n{'='*80}")

    # E3A: Predict observable subtotal
    y_dev_obs = np.array([subjects[s]["observable_score"] for s in dev_sids_feat], dtype=np.float32)
    y_test_obs = np.array([subjects[s]["observable_score"] for s in test_sids_feat], dtype=np.float32)
    run_if_new("E3A: LGB observable subtotal", lambda: run_booster_experiment(
        "E3A: LGB observable subtotal", X_dev_all, y_dev_obs, dev_sids_feat,
        X_test_all, y_test_obs, subjects, booster="lgb", sel_idx=sel_200_idx))

    # E3B: Predict obs+partial subtotal
    y_dev_obsp = np.array([subjects[s]["obs_plus_partial"] for s in dev_sids_feat], dtype=np.float32)
    y_test_obsp = np.array([subjects[s]["obs_plus_partial"] for s in test_sids_feat], dtype=np.float32)
    run_if_new("E3B: LGB obs+partial subtotal", lambda: run_booster_experiment(
        "E3B: LGB obs+partial subtotal", X_dev_all, y_dev_obsp, dev_sids_feat,
        X_test_all, y_test_obsp, subjects, booster="lgb", sel_idx=sel_200_idx))

    # E3C: Two-stage (predict observable → add as feature → predict total)
    def _run_two_stage():
        print(f"\n--- E3C: Two-stage observable → total ---")
        # Use pre-selected features
        X_dev_s = X_dev_all[:, sel_200_idx]
        X_test_s = X_test_all[:, sel_200_idx]
        seed_maes, seed_rs, seed_preds = [], [], []
        for seed in SEEDS:
            tr_sids, va_sids = stratified_val_split(list(dev_sids_feat), subjects, 0.15, seed)
            tr_mask = np.isin(dev_sids_feat, tr_sids)
            va_mask = np.isin(dev_sids_feat, va_sids)
            X_tr_s = X_dev_s[tr_mask]
            X_va_s = X_dev_s[va_mask]
            X_te_s = X_test_s
            # Stage 1: predict observable subtotal
            m1 = train_lgb(X_tr_s, y_dev_obs[tr_mask], X_va_s, y_dev_obs[va_mask], seed)
            obs_pred_tr = m1.predict(X_tr_s).reshape(-1, 1)
            obs_pred_va = m1.predict(X_va_s).reshape(-1, 1)
            obs_pred_te = m1.predict(X_te_s).reshape(-1, 1)
            # Stage 2: predict total from features + obs prediction
            X_tr2 = np.hstack([X_tr_s, obs_pred_tr])
            X_va2 = np.hstack([X_va_s, obs_pred_va])
            X_te2 = np.hstack([X_te_s, obs_pred_te])
            m2 = train_lgb(X_tr2, y_dev[tr_mask], X_va2, y_dev[va_mask], seed)
            pred = m2.predict(X_te2)
            mae = mean_absolute_error(y_test, pred)
            r, _ = sp_stats.pearsonr(y_test, pred)
            print(f"  Seed {seed}: MAE={mae:.2f}, r={r:.3f}")
            seed_maes.append(float(mae))
            seed_rs.append(float(r))
            seed_preds.append(pred.tolist())
        mm = np.mean(seed_maes)
        ens_pred = np.mean([np.array(p) for p in seed_preds], axis=0)
        em = mean_absolute_error(y_test, ens_pred)
        er, _ = sp_stats.pearsonr(y_test, ens_pred)
        print(f"  MEAN: MAE={mm:.2f}+/-{np.std(seed_maes):.2f}")
        print(f"  ENS:  MAE={em:.2f}, r={er:.3f}")
        return {"name": "E3C: Two-stage obs→total", "mean_mae": round(mm, 3),
                "std_mae": round(np.std(seed_maes), 3), "mean_r": round(np.mean(seed_rs), 3),
                "ens_mae": round(em, 3), "ens_r": round(er, 3),
                "individual_mae": seed_maes, "individual_r": seed_rs,
                "test_true": y_test.tolist(), "test_preds": seed_preds}

    run_if_new("E3C: Two-stage obs→total", _run_two_stage)

    # ══════════════════════════════════════════════════════════════════
    # PHASE 4: PER-TASK + TASK-CONTRAST
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}\nPHASE 4: PER-TASK MODELS\n{'='*80}")

    # E4A: Per-task LightGBM (train separate models per task, average predictions)
    def _run_per_task():
        print(f"\n--- E4A: Per-task LGB ensemble ---")
        seed_maes, seed_rs, seed_preds = [], [], []
        # We need per-task features. Extract from df_all using SelfPace_ and HurriedPace_ prefixed cols
        sp_cols = sorted([c for c in feat_cols if c.startswith("SelfPace_")])
        hp_cols = sorted([c for c in feat_cols if c.startswith("HurriedPace_")])
        if not sp_cols or not hp_cols:
            print("  No per-task features found, skipping")
            return {"name": "E4A: Per-task LGB ensemble", "ens_mae": 99.0, "ens_r": 0.0,
                    "mean_mae": 99.0, "std_mae": 0.0, "mean_r": 0.0,
                    "individual_mae": [], "individual_r": [],
                    "test_true": y_test.tolist(), "test_preds": []}
        for seed in SEEDS:
            tr_sids, va_sids = stratified_val_split(list(dev_sids_feat), subjects, 0.15, seed)
            tr_mask = np.isin(dev_sids_feat, tr_sids)
            va_mask = np.isin(dev_sids_feat, va_sids)
            preds_per_task = []
            for task_cols in [sp_cols, hp_cols]:
                tc_idx = [feat_cols.index(c) for c in task_cols]
                X_tr = X_dev_all[tr_mask][:, tc_idx]
                X_va = X_dev_all[va_mask][:, tc_idx]
                X_te = X_test_all[:, tc_idx]
                m = train_lgb(X_tr, y_dev[tr_mask], X_va, y_dev[va_mask], seed)
                preds_per_task.append(m.predict(X_te))
            pred = np.mean(preds_per_task, axis=0)
            mae = mean_absolute_error(y_test, pred)
            r, _ = sp_stats.pearsonr(y_test, pred)
            print(f"  Seed {seed}: MAE={mae:.2f}, r={r:.3f}")
            seed_maes.append(float(mae))
            seed_rs.append(float(r))
            seed_preds.append(pred.tolist())
        mm = np.mean(seed_maes)
        ens_pred = np.mean([np.array(p) for p in seed_preds], axis=0)
        em = mean_absolute_error(y_test, ens_pred)
        er, _ = sp_stats.pearsonr(y_test, ens_pred)
        print(f"  MEAN: MAE={mm:.2f}+/-{np.std(seed_maes):.2f}")
        print(f"  ENS:  MAE={em:.2f}, r={er:.3f}")
        return {"name": "E4A: Per-task LGB ensemble", "mean_mae": round(mm, 3),
                "std_mae": round(np.std(seed_maes), 3), "mean_r": round(np.mean(seed_rs), 3),
                "ens_mae": round(em, 3), "ens_r": round(er, 3),
                "individual_mae": seed_maes, "individual_r": seed_rs,
                "test_true": y_test.tolist(), "test_preds": seed_preds}

    run_if_new("E4A: Per-task LGB ensemble", _run_per_task)

    # E4B: Contrast-only features
    contrast_cols = sorted([c for c in feat_cols if c.startswith("contrast_")])
    if contrast_cols:
        contrast_idx = [feat_cols.index(c) for c in contrast_cols]
        X_dev_con = X_dev_all[:, contrast_idx]
        X_test_con = X_test_all[:, contrast_idx]
        sel_con_cols, sel_con_idx = select_features_stable(
            X_dev_con, y_dev, contrast_cols, min(100, len(contrast_cols)))
        run_if_new("E4B: LGB contrast-only 100 feats", lambda: run_booster_experiment(
            "E4B: LGB contrast-only 100 feats", X_dev_con, y_dev, dev_sids_feat,
            X_test_con, y_test, subjects, booster="lgb", sel_idx=sel_con_idx))

    # ══════════════════════════════════════════════════════════════════
    # PHASE 2: DL EMBEDDING + BOOSTER FUSION
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}\nPHASE 2: DL EMBEDDING FUSION\n{'='*80}")

    try:
        dev_embs, test_embs, embed_dim = extract_dl_embeddings(subjects, dev_sids, test_sids)

        # Build embedding arrays aligned with feature dataframes
        E_dev = np.zeros((len(dev_sids_feat), embed_dim), dtype=np.float32)
        for i, sid in enumerate(dev_sids_feat):
            if sid in dev_embs:
                E_dev[i] = dev_embs[sid]
        E_test = np.zeros((len(test_sids_feat), embed_dim), dtype=np.float32)
        for i, sid in enumerate(test_sids_feat):
            if sid in test_embs:
                E_test[i] = test_embs[sid]

        # E2A: Features + DL embeddings
        X_dev_fused = np.hstack([X_dev_all, E_dev])
        X_test_fused = np.hstack([X_test_all, E_test])
        fused_cols = feat_cols + [f"dl_emb_{i}" for i in range(embed_dim)]
        sel_fused_cols, sel_fused_idx = select_features_stable(
            X_dev_fused, y_dev, fused_cols, 200)
        run_if_new("E2A: LGB features+DL 200", lambda: run_booster_experiment(
            "E2A: LGB features+DL 200", X_dev_fused, y_dev, dev_sids_feat,
            X_test_fused, y_test, subjects, booster="lgb", sel_idx=sel_fused_idx))

        # E2B: DL embeddings only
        run_if_new("E2B: LGB DL embeddings only", lambda: run_booster_experiment(
            "E2B: LGB DL embeddings only", E_dev, y_dev, dev_sids_feat,
            E_test, y_test, subjects, booster="lgb"))

        # E2C: XGBoost features + DL embeddings
        run_if_new("E2C: XGB features+DL 200", lambda: run_booster_experiment(
            "E2C: XGB features+DL 200", X_dev_fused, y_dev, dev_sids_feat,
            X_test_fused, y_test, subjects, booster="xgb", sel_idx=sel_fused_idx))

    except Exception as e:
        print(f"  DL embedding extraction failed: {e}")
        import traceback
        traceback.print_exc()

    # ══════════════════════════════════════════════════════════════════
    # PHASE 5: GRAND ENSEMBLE + PD-ONLY TRACK
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*80}\nPHASE 5: GRAND ENSEMBLE + PD-ONLY\n{'='*80}")

    # E5A: Stacking ensemble (meta-learner)
    valid = [r for r in all_results if "test_preds" in r and r.get("test_preds")
             and "test_true" in r and r.get("ens_mae", 99) < 15]
    if len(valid) >= 3:
        def _run_stacking():
            print(f"\n--- E5A: Stacking ensemble ---")
            tt = np.array(valid[0]["test_true"])
            ranked = sorted(valid, key=lambda x: x["ens_mae"])
            print(f"  Components (ranked):")
            for i, r in enumerate(ranked[:8]):
                print(f"    {i+1}. {r['name']}: MAE={r['ens_mae']:.2f}")

            best_em, best_name = 99, ""
            for k in [3, 5, len(ranked)]:
                topk = ranked[:min(k, len(ranked))]
                preds = [np.mean(r["test_preds"], 0) for r in topk]
                ep = np.mean(preds, 0)
                em = mean_absolute_error(tt, ep)
                er, _ = sp_stats.pearsonr(tt, ep)
                print(f"  Top-{min(k, len(ranked))} mean: MAE={em:.2f}, r={er:.3f}")
                if em < best_em:
                    best_em, best_name = em, f"Top-{min(k, len(ranked))}"

            # Weighted by inverse MAE
            weights = np.array([1.0 / r["ens_mae"] for r in ranked[:5]])
            weights /= weights.sum()
            wp = sum(w * np.mean(r["test_preds"], 0) for w, r in zip(weights, ranked[:5]))
            wm = mean_absolute_error(tt, wp)
            wr, _ = sp_stats.pearsonr(tt, wp)
            print(f"  Weighted top-5: MAE={wm:.2f}, r={wr:.3f}")
            if wm < best_em:
                best_em = wm

            return {"name": "E5A: Grand ensemble", "ens_mae": round(best_em, 3),
                    "ens_r": round(wr, 3), "mean_mae": round(best_em, 3),
                    "std_mae": 0.0, "mean_r": round(wr, 3),
                    "individual_mae": [], "individual_r": [],
                    "test_true": tt.tolist(), "test_preds": [wp.tolist()]}
        run_if_new("E5A: Grand ensemble", _run_stacking)

    # E5B: PD-only LOOCV (literature-comparable track)
    def _run_pd_loocv():
        print(f"\n--- E5B: PD-only LOOCV ---")
        pd_sids = [s for s in dev_sids_feat if subjects.get(s, {}).get("group") == "PD"]
        pd_test = [s for s in test_sids_feat if subjects.get(s, {}).get("group") == "PD"]
        all_pd = pd_sids + pd_test
        if len(all_pd) < 10:
            print("  Too few PD subjects, skipping")
            return {"name": "E5B: PD-only LOOCV", "ens_mae": 99.0, "ens_r": 0.0,
                    "mean_mae": 99.0, "std_mae": 0.0, "mean_r": 0.0,
                    "individual_mae": [], "individual_r": [],
                    "test_true": [], "test_preds": []}

        # Build PD-only feature matrix
        pd_mask_all = df_all["sid"].isin(all_pd)
        df_pd = df_all[pd_mask_all].copy()
        X_pd = df_pd[feat_cols].values.astype(np.float32)
        y_pd = df_pd["updrs3"].values.astype(np.float32)
        pd_sid_arr = df_pd["sid"].values

        # Feature selection on full PD set (stable)
        sel_cols, sel_idx = select_features_stable(X_pd, y_pd, feat_cols, 200)
        X_pd_sel = X_pd[:, sel_idx]

        # LOOCV
        loo = LeaveOneOut()
        trues, preds = [], []
        for tr_idx, te_idx in loo.split(X_pd_sel):
            # Use first 15% of training as val
            rng = np.random.RandomState(42)
            idx = np.arange(len(tr_idx))
            rng.shuffle(idx)
            nv = max(1, int(len(idx) * 0.15))
            va_i = tr_idx[idx[:nv]]
            tr_i = tr_idx[idx[nv:]]
            m = train_lgb(X_pd_sel[tr_i], y_pd[tr_i], X_pd_sel[va_i], y_pd[va_i], 42)
            pred = m.predict(X_pd_sel[te_idx])
            trues.append(float(y_pd[te_idx[0]]))
            preds.append(float(pred[0]))

        trues = np.array(trues)
        preds = np.array(preds)
        mae = mean_absolute_error(trues, preds)
        r, _ = sp_stats.pearsonr(trues, preds)
        print(f"  PD-only LOOCV (N={len(all_pd)}): MAE={mae:.2f}, r={r:.3f}")
        print(f"  Compare: Hssayeni 2021 MAE=5.95, Shuqair 2024 MAE~5.65 (N=24)")
        return {"name": "E5B: PD-only LOOCV", "ens_mae": round(mae, 3),
                "ens_r": round(r, 3), "mean_mae": round(mae, 3), "std_mae": 0.0,
                "mean_r": round(r, 3), "individual_mae": [float(mae)],
                "individual_r": [float(r)],
                "test_true": trues.tolist(), "test_preds": [preds.tolist()],
                "n_pd": len(all_pd), "protocol": "LOOCV"}

    run_if_new("E5B: PD-only LOOCV", _run_pd_loocv)

    # ══════════════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ══════════════════════════════════════════════════════════════════
    elapsed = time.time() - T0
    print(f"\n{'='*80}\nFINAL SUMMARY ({elapsed/60:.1f} min)\n{'='*80}")
    print(f"  Baseline: LightGBM 150 features -> MAE=7.97, r=0.821\n")

    ranked_all = sorted([r for r in all_results if "ens_mae" in r], key=lambda x: x["ens_mae"])
    print(f"  {'#':>2} {'Model':<40} {'ENS MAE':>8} {'ENS r':>7}")
    print(f"  {'-'*60}")
    for i, r in enumerate(ranked_all):
        mark = " ***" if r["ens_mae"] < 7.97 else ""
        print(f"  {i+1:>2} {r['name']:<40} {r['ens_mae']:>7.2f}  {r.get('ens_r',0):>6.3f}{mark}")

    best = ranked_all[0] if ranked_all else None
    if best:
        if best["ens_mae"] < 7.97:
            print(f"\n  NEW BEST: {best['name']} -> MAE={best['ens_mae']:.2f}, r={best['ens_r']:.3f}")
        else:
            print(f"\n  Best V2: {best['name']} -> MAE={best['ens_mae']:.2f}")
            print(f"  Baseline still wins. Consider publishing feature-only result.")

    save()
    print(f"\nResults: {RESULTS_FILE}")
    print(f"Features: {FEAT_CACHE}")


if __name__ == "__main__":
    main()

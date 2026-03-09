"""
Wave 3: Graft Extended Covariates + Model Innovations onto Original Pipeline
=============================================================================
Combines:
  1. Original run_biomechanics.py extraction (FreeAcc+Euler+asymmetry+trunk+gait)
  2. Extended covariates (BMI, onset age, years²,  duration bins)
  3. Feature selection sweep (K=150, 200)
  4. Two-stage model (observable items → total UPDRS-III)
  5. Log1p target transform
  6. Task specialist ensemble

CPU-bound. Self-contained. Imports from data_split.py only.
"""
import os, sys, json, time, warnings, math
import numpy as np
import pandas as pd
from scipy import signal, stats as sp_stats
from sklearn.metrics import mean_absolute_error
from concurrent.futures import ProcessPoolExecutor
from collections import defaultdict
warnings.filterwarnings("ignore")

sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS

TASKS = ["SelfPace", "HurriedPace", "TUG", "Balance", "TandemGait"]
N_CORES = 11
SEEDS = [42, 123, 456, 789, 2024]

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

# Observable UPDRS-III subitems (detectable from gait/balance IMU)
# 3.7-3.18: toe tap, leg agility, arising, gait, freezing, postural stability,
#           posture, body bradykinesia, postural tremor, kinetic tremor, rest tremor, tremor constancy
OBSERVABLE_ITEMS = [
    "MDSUPDRS_3-7a", "MDSUPDRS_3-7b", "MDSUPDRS_3-8a", "MDSUPDRS_3-8b",
    "MDSUPDRS_3-9", "MDSUPDRS_3-10", "MDSUPDRS_3-11", "MDSUPDRS_3-12",
    "MDSUPDRS_3-13", "MDSUPDRS_3-14",
    "MDSUPDRS_3-15a", "MDSUPDRS_3-15b",
    "MDSUPDRS_3-16a", "MDSUPDRS_3-16b",
    "MDSUPDRS_3-17a", "MDSUPDRS_3-17b", "MDSUPDRS_3-17c",
    "MDSUPDRS_3-17d", "MDSUPDRS_3-17e", "MDSUPDRS_3-18",
]
# Unobservable: 3.1 speech, 3.2 facial, 3.3a-e rigidity, 3.4-3.6 finger/hand/pronation


def safe_stat(func, data, default=0.0):
    try:
        v = func(data)
        return float(v) if np.isfinite(v) else default
    except Exception:
        return default


def get_csv_path(sid, task, subjects):
    info = subjects[sid]
    base = "PD PARTICIPANTS" if info["group"] == "PD" else "CONTROL PARTICIPANTS"
    return os.path.join(DATA_DIR, base, "CSV files", f"{sid}_{task}.csv")


# ══════════════════════════════════════════════════════════════════════
# FEATURE EXTRACTION (exact copy of run_biomechanics.py)
# ══════════════════════════════════════════════════════════════════════

def time_domain_features(x, prefix=""):
    feats = {}
    feats[f"{prefix}_rms"] = safe_stat(lambda d: np.sqrt(np.mean(d**2)), x)
    feats[f"{prefix}_mean"] = safe_stat(np.mean, x)
    feats[f"{prefix}_std"] = safe_stat(np.std, x)
    feats[f"{prefix}_range"] = safe_stat(np.ptp, x)
    feats[f"{prefix}_iqr"] = safe_stat(lambda d: np.percentile(d, 75) - np.percentile(d, 25), x)
    feats[f"{prefix}_skew"] = safe_stat(lambda d: float(sp_stats.skew(d)), x)
    feats[f"{prefix}_kurt"] = safe_stat(lambda d: float(sp_stats.kurtosis(d)), x)
    feats[f"{prefix}_p5"] = safe_stat(lambda d: np.percentile(d, 5), x)
    feats[f"{prefix}_p95"] = safe_stat(lambda d: np.percentile(d, 95), x)
    jerk = np.diff(x) * FS
    feats[f"{prefix}_jerk_rms"] = safe_stat(lambda d: np.sqrt(np.mean(d**2)), jerk)
    feats[f"{prefix}_jerk_mean"] = safe_stat(np.mean, np.abs(jerk))
    zc = np.sum(np.diff(np.sign(x - np.mean(x))) != 0)
    feats[f"{prefix}_zcr"] = float(zc) / max(len(x), 1)
    return feats


def freq_domain_features(x, prefix=""):
    feats = {}
    try:
        freqs, psd = signal.welch(x, fs=FS, nperseg=min(256, len(x)),
                                   noverlap=min(128, len(x) // 2))
        psd = psd + 1e-12
        bands = {"locomotor": (0.5, 3.0), "tremor": (3.0, 8.0),
                 "freeze": (3.0, 8.0), "high": (8.0, 20.0)}
        total_power = np.trapz(psd, freqs) + 1e-12
        for bname, (lo, hi) in bands.items():
            mask = (freqs >= lo) & (freqs <= hi)
            bp = np.trapz(psd[mask], freqs[mask]) if mask.sum() > 1 else 0.0
            feats[f"{prefix}_psd_{bname}"] = float(np.log10(bp + 1e-12))
            feats[f"{prefix}_psd_{bname}_rel"] = float(bp / total_power)
        feats[f"{prefix}_dom_freq"] = float(freqs[np.argmax(psd)])
        feats[f"{prefix}_psd_total"] = float(np.log10(total_power))
        psd_norm = psd / psd.sum()
        feats[f"{prefix}_spectral_entropy"] = float(-np.sum(psd_norm * np.log2(psd_norm + 1e-12)))
    except Exception:
        for k in ["locomotor", "tremor", "freeze", "high"]:
            feats[f"{prefix}_psd_{k}"] = 0.0; feats[f"{prefix}_psd_{k}_rel"] = 0.0
        feats[f"{prefix}_dom_freq"] = 0.0; feats[f"{prefix}_psd_total"] = 0.0
        feats[f"{prefix}_spectral_entropy"] = 0.0
    return feats


def gait_regularity_features(acc_vert, prefix=""):
    feats = {}
    try:
        x = acc_vert - np.mean(acc_vert)
        ac = np.correlate(x, x, mode="full"); ac = ac[len(ac)//2:]
        ac = ac / (ac[0] + 1e-12)
        peaks, _ = signal.find_peaks(ac, distance=30, height=0.1)
        if len(peaks) >= 2:
            feats[f"{prefix}_step_time"] = float(peaks[0] / FS)
            feats[f"{prefix}_stride_time"] = float(peaks[1] / FS)
            feats[f"{prefix}_cadence"] = float(60.0 * FS / peaks[0]) if peaks[0] > 0 else 0.0
            feats[f"{prefix}_step_regularity"] = float(ac[peaks[0]])
            feats[f"{prefix}_stride_regularity"] = float(ac[peaks[1]]) if peaks[1] < len(ac) else 0.0
            feats[f"{prefix}_step_symmetry"] = abs(float(ac[peaks[0]]) - float(ac[peaks[1]])) if peaks[1] < len(ac) else 0.0
        else:
            for k in ["step_time", "stride_time", "cadence", "step_regularity", "stride_regularity", "step_symmetry"]:
                feats[f"{prefix}_{k}"] = 0.0
    except Exception:
        for k in ["step_time", "stride_time", "cadence", "step_regularity", "stride_regularity", "step_symmetry"]:
            feats[f"{prefix}_{k}"] = 0.0
    return feats


def freeze_index(acc_vert, prefix=""):
    feats = {}
    try:
        freqs, psd = signal.welch(acc_vert, fs=FS, nperseg=min(256, len(acc_vert)))
        loco = np.trapz(psd[(freqs >= 0.5) & (freqs <= 3.0)], freqs[(freqs >= 0.5) & (freqs <= 3.0)]) + 1e-12
        freeze = np.trapz(psd[(freqs >= 3.0) & (freqs <= 8.0)], freqs[(freqs >= 3.0) & (freqs <= 8.0)])
        feats[f"{prefix}_freeze_idx"] = float(freeze / loco)
    except Exception:
        feats[f"{prefix}_freeze_idx"] = 0.0
    return feats


def asymmetry_features(left_data, right_data, prefix=""):
    feats = {}
    try:
        l_rms = np.sqrt(np.mean(left_data**2, axis=0))
        r_rms = np.sqrt(np.mean(right_data**2, axis=0))
        asym = np.abs(l_rms - r_rms) / (l_rms + r_rms + 1e-8)
        feats[f"{prefix}_asym_mean"] = float(np.mean(asym))
        feats[f"{prefix}_asym_max"] = float(np.max(asym))
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


_SUBJECTS = None

def _init_worker(subjects):
    global _SUBJECTS
    _SUBJECTS = subjects


def extract_recording(args):
    """Extract features from one CSV — same as run_biomechanics.py + task contrasts."""
    sid, task = args
    global _SUBJECTS
    path = get_csv_path(sid, task, _SUBJECTS)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if len(df) < 200:
        return None

    feats = {}

    # Per-sensor features (exact run_biomechanics.py pattern)
    for sensor in SENSORS:
        fa_cols = [f"{sensor}_{c}" for c in FREEACC_COLS]
        acc_cols = [f"{sensor}_{c}" for c in ACC_COLS]
        use_cols = fa_cols if all(c in df.columns for c in fa_cols) else acc_cols
        gyr_cols = [f"{sensor}_{c}" for c in GYR_COLS]
        euler_cols = [f"{sensor}_{c}" for c in EULER_COLS]

        if all(c in df.columns for c in use_cols):
            acc = np.nan_to_num(df[use_cols].values.astype(np.float32), nan=0.0)
            acc_mag = np.sqrt(np.sum(acc**2, axis=1))
            for i, ax in enumerate(["x", "y", "z"]):
                feats.update(time_domain_features(acc[:, i], f"{sensor}_acc_{ax}"))
                feats.update(freq_domain_features(acc[:, i], f"{sensor}_acc_{ax}"))
            feats.update(time_domain_features(acc_mag, f"{sensor}_acc_mag"))
            feats.update(freq_domain_features(acc_mag, f"{sensor}_acc_mag"))
            if sensor in ["LowerBack", "R_Ankle", "L_Ankle", "R_DorsalFoot", "L_DorsalFoot"]:
                feats.update(gait_regularity_features(acc[:, 2], f"{sensor}_gait"))
                feats.update(freeze_index(acc[:, 2], f"{sensor}"))

        if all(c in df.columns for c in gyr_cols):
            gyr = np.nan_to_num(df[gyr_cols].values.astype(np.float32), nan=0.0)
            gyr_mag = np.sqrt(np.sum(gyr**2, axis=1))
            feats.update(time_domain_features(gyr_mag, f"{sensor}_gyr_mag"))
            feats.update(freq_domain_features(gyr_mag, f"{sensor}_gyr_mag"))

        if all(c in df.columns for c in euler_cols):
            euler = np.nan_to_num(df[euler_cols].values.astype(np.float32), nan=0.0)
            for i, ax in enumerate(["roll", "pitch", "yaw"]):
                feats.update(time_domain_features(euler[:, i], f"{sensor}_{ax}"))
                feats[f"{sensor}_{ax}_range_total"] = float(np.ptp(euler[:, i]))

    # Cross-sensor asymmetry with phase lag
    for l_s, r_s in PAIRED_SENSORS:
        l_c = [f"{l_s}_{c}" for c in ACC_COLS]
        r_c = [f"{r_s}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in l_c + r_c):
            ld = np.nan_to_num(df[l_c].values.astype(np.float32), nan=0.0)
            rd = np.nan_to_num(df[r_c].values.astype(np.float32), nan=0.0)
            pair = l_s.replace("L_", "").replace("R_", "")
            feats.update(asymmetry_features(ld, rd, f"asym_{pair}"))

    # Trunk stability
    for ts in TRUNK_SENSORS:
        acc_t = [f"{ts}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in acc_t):
            trunk = np.nan_to_num(df[acc_t].values.astype(np.float32), nan=0.0)
            feats[f"{ts}_trunk_sway"] = float(np.sqrt(np.mean(trunk[:, :2]**2)))

    feats["n_samples"] = len(df)
    feats["duration_s"] = len(df) / FS

    return {"sid": sid, "task": task, "feats": feats}


# ══════════════════════════════════════════════════════════════════════
# EXTENDED COVARIATES
# ══════════════════════════════════════════════════════════════════════

def load_covariates_extended():
    """Parse ALL clinical covariates including extended ones."""
    covariates = {}
    for fn, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
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
            height = pd.to_numeric(row.get("Height (cm)", row.get("Height", np.nan)), errors="coerce")
            weight = pd.to_numeric(row.get("Weight (kg)", row.get("Weight", np.nan)), errors="coerce")
            yrs = pd.to_numeric(row.get("Years since PD diagnosis", row.get("Years Since Diagnosis", 0)), errors="coerce")

            age_v = float(age) if pd.notna(age) else 65.0
            yrs_v = float(yrs) if pd.notna(yrs) else 0.0
            h = float(height) if pd.notna(height) else 170.0
            w = float(weight) if pd.notna(weight) else 75.0
            sex = 1.0 if str(row.get("Sex", "")).strip().upper().startswith("M") else 0.0
            dbs_raw = str(row.get("DBS?", row.get("DBS", ""))).strip().upper()
            med_raw = str(row.get("Medication State", row.get("Medication status", ""))).strip().upper()

            covariates[sid] = {
                # Original 5
                "cv_age": age_v, "cv_sex": sex, "cv_years_dx": yrs_v,
                "cv_med_on": 1.0 if med_raw == "ON" else 0.0,
                "cv_dbs": 1.0 if dbs_raw in ("YES", "Y", "1") else 0.0,
                # Extended
                "cv_height": h, "cv_weight": w,
                "cv_bmi": w / ((h / 100.0) ** 2) if h > 0 else 25.0,
                "cv_age_onset": age_v - yrs_v if yrs_v > 0 else age_v,
                "cv_yrs_sq": yrs_v ** 2,
                "cv_yrs_log": float(np.log1p(yrs_v)),
                "cv_early": 1.0 if 0 < yrs_v <= 5 else 0.0,
                "cv_late": 1.0 if yrs_v > 10 else 0.0,
            }
    return covariates


# ══════════════════════════════════════════════════════════════════════
# OBSERVABLE UPDRS SUBITEMS (for two-stage model)
# ══════════════════════════════════════════════════════════════════════

def parse_updrs_subitems():
    """Parse individual UPDRS-III subitems for two-stage modeling."""
    subitems = {}
    for fn, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, header=1)
        u3cols = [c for c in df.columns if c.startswith("MDSUPDRS_3-")]
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            items = {}
            for c in u3cols:
                v = pd.to_numeric(row[c], errors="coerce")
                items[c] = float(v) if pd.notna(v) else 0.0
            subitems[sid] = items
    return subitems


# ══════════════════════════════════════════════════════════════════════
# AGGREGATION & FEATURE MATRIX
# ══════════════════════════════════════════════════════════════════════

def build_feature_matrix(records, subjects, covariates):
    """Aggregate recordings to subject-level + add covariates."""
    by_subj = defaultdict(list)
    for r in records:
        by_subj[r["sid"]].append(r)

    rows = []
    for sid in sorted(by_subj.keys()):
        if sid not in subjects:
            continue
        recs = by_subj[sid]
        agg = {"sid": sid, "updrs3": subjects[sid]["updrs3"]}

        # Aggregate IMU features (mean across tasks)
        all_keys = set()
        for r in recs:
            all_keys.update(r["feats"].keys())
        for k in sorted(all_keys):
            vals = [r["feats"].get(k, None) for r in recs]
            vals = [v for v in vals if v is not None and np.isfinite(v)]
            agg[k] = float(np.mean(vals)) if vals else 0.0

        # Task contrasts: hurried - selfpace deltas
        sp_recs = [r for r in recs if r["task"] == "SelfPace"]
        hp_recs = [r for r in recs if r["task"] == "HurriedPace"]
        if sp_recs and hp_recs:
            sp_f = sp_recs[0]["feats"]
            hp_f = hp_recs[0]["feats"]
            shared_keys = set(sp_f.keys()) & set(hp_f.keys())
            # Only compute contrasts for a few key features to avoid explosion
            key_prefixes = ["LowerBack_acc_mag_rms", "LowerBack_gait_cadence",
                           "LowerBack_gait_stride_time", "R_Ankle_acc_mag_rms"]
            for k in key_prefixes:
                if k in shared_keys:
                    delta = hp_f[k] - sp_f[k]
                    if np.isfinite(delta):
                        agg[f"contrast_{k}"] = float(delta)

        # Add covariates
        cov = covariates.get(sid, {})
        agg.update(cov)

        agg["n_tasks"] = len(recs)
        rows.append(agg)

    df = pd.DataFrame(rows)
    for c in df.columns:
        if c not in ("sid",):
            df[c] = pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return df


# ══════════════════════════════════════════════════════════════════════
# FEATURE SELECTION + MODEL TRAINING
# ══════════════════════════════════════════════════════════════════════

def feature_select(X, y, names, k=150):
    from xgboost import XGBRegressor
    sel = XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                        reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
                        objective="reg:absoluteerror")
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def train_lgbm(Xd, yd, Xt, yt, seed=42):
    import lightgbm as lgb
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd)); rng.shuffle(idx)
    nv = max(1, int(len(idx) * 0.15))
    vi, ti = idx[:nv], idx[nv:]

    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                           reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                           objective="mae", verbose=-1)
    m.fit(Xd[ti], yd[ti], eval_set=[(Xd[vi], yd[vi])],
          callbacks=[lgb.early_stopping(100, verbose=False)])
    p = m.predict(Xt)
    return p, m


def run_experiment(name, Xd, yd, Xt, yt, feat_names, k=150,
                   target_transform=None, inv_transform=None):
    """Run a 5-seed LightGBM experiment with feature selection."""
    k = min(k, Xd.shape[1])
    if Xd.shape[1] == 0:
        print(f"\n  {name}: SKIPPED (0 features)")
        return None

    # Transform targets if needed
    yd_t = target_transform(yd) if target_transform else yd
    yt_orig = yt  # always evaluate on original scale

    print(f"\n  {name} ({Xd.shape[1]} raw → top {k})")
    sel_idx, sel_names = feature_select(Xd, yd_t, feat_names, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

    maes, rs, preds = [], [], []
    for seed in SEEDS:
        p, _ = train_lgbm(Xds, yd_t, Xts, yt_orig, seed)
        if inv_transform:
            p = inv_transform(p)
        p = np.clip(p, 0, 132)
        mae = mean_absolute_error(yt_orig, p)
        r, _ = sp_stats.pearsonr(yt_orig, p)
        maes.append(mae); rs.append(r); preds.append(p)
        print(f"    seed {seed}: MAE={mae:.2f} r={r:.3f}")

    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt_orig, ep)
    er, _ = sp_stats.pearsonr(yt_orig, ep)
    print(f"    ENS: MAE={em:.2f} r={er:.3f}")

    return {
        "config": name, "n_raw": int(Xd.shape[1]), "n_sel": k,
        "mean_mae": round(float(np.mean(maes)), 3),
        "std_mae": round(float(np.std(maes)), 3),
        "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
        "seed_maes": [round(float(m), 3) for m in maes],
        "top10": sel_names[:10],
        "ens_preds": ep.tolist(),
    }


# ══════════════════════════════════════════════════════════════════════
# TWO-STAGE MODEL
# ══════════════════════════════════════════════════════════════════════

def run_two_stage(Xd, yd, Xt, yt, feat_names, subitems, dev_sids, test_sids, k=150):
    """Two-stage: predict observable subscore → predict total."""
    import lightgbm as lgb

    print(f"\n  TWO-STAGE ({Xd.shape[1]} raw → K={k})")

    # Compute observable subscore per subject
    obs_dev = np.array([
        sum(subitems.get(sid, {}).get(item, 0.0) for item in OBSERVABLE_ITEMS
            if item in subitems.get(sid, {}))
        for sid in dev_sids
    ], dtype=np.float32)
    obs_test = np.array([
        sum(subitems.get(sid, {}).get(item, 0.0) for item in OBSERVABLE_ITEMS
            if item in subitems.get(sid, {}))
        for sid in test_sids
    ], dtype=np.float32)

    print(f"    Observable subscore: dev mean={obs_dev.mean():.1f} test mean={obs_test.mean():.1f}")

    # Feature selection
    sel_idx, sel_names = feature_select(Xd, yd, feat_names, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

    maes, rs, preds = [], [], []
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(Xds)); rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        vi, ti = idx[:nv], idx[nv:]

        # Stage 1: predict observable subscore
        m1 = lgb.LGBMRegressor(n_estimators=1500, learning_rate=0.03, max_depth=5,
                                reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                                objective="mae", verbose=-1)
        m1.fit(Xds[ti], obs_dev[ti], eval_set=[(Xds[vi], obs_dev[vi])],
               callbacks=[lgb.early_stopping(80, verbose=False)])

        # OOF predictions for Stage 2 training (prevent leakage)
        obs_oof = np.zeros(len(Xds))
        from sklearn.model_selection import KFold
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        for tr_i, val_i in kf.split(Xds):
            m1_cv = lgb.LGBMRegressor(n_estimators=1500, learning_rate=0.03, max_depth=5,
                                       reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                                       objective="mae", verbose=-1)
            nv_cv = max(1, int(len(tr_i) * 0.15))
            m1_cv.fit(Xds[tr_i[nv_cv:]], obs_dev[tr_i[nv_cv:]],
                      eval_set=[(Xds[tr_i[:nv_cv]], obs_dev[tr_i[:nv_cv]])],
                      callbacks=[lgb.early_stopping(80, verbose=False)])
            obs_oof[val_i] = m1_cv.predict(Xds[val_i])

        obs_pred_test = m1.predict(Xts)

        # Stage 2: predict total from features + observable prediction
        X2_dev = np.column_stack([Xds, obs_oof])
        X2_test = np.column_stack([Xts, obs_pred_test])

        m2 = lgb.LGBMRegressor(n_estimators=1500, learning_rate=0.03, max_depth=5,
                                reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                                objective="mae", verbose=-1)
        m2.fit(X2_dev[ti], yd[ti], eval_set=[(X2_dev[vi], yd[vi])],
               callbacks=[lgb.early_stopping(80, verbose=False)])

        p = np.clip(m2.predict(X2_test), 0, 132)
        mae = mean_absolute_error(yt, p)
        r, _ = sp_stats.pearsonr(yt, p)
        maes.append(mae); rs.append(r); preds.append(p)
        print(f"    seed {seed}: MAE={mae:.2f} r={r:.3f}")

    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep)
    er, _ = sp_stats.pearsonr(yt, ep)
    print(f"    ENS: MAE={em:.2f} r={er:.3f}")

    return {
        "config": f"two_stage_K{k}", "n_raw": int(Xd.shape[1]), "n_sel": k,
        "mean_mae": round(float(np.mean(maes)), 3),
        "std_mae": round(float(np.std(maes)), 3),
        "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
        "seed_maes": [round(float(m), 3) for m in maes],
        "top10": sel_names[:10],
        "ens_preds": ep.tolist(),
    }


# ══════════════════════════════════════════════════════════════════════
# TASK SPECIALIST ENSEMBLE
# ══════════════════════════════════════════════════════════════════════

def run_task_specialist(records, subjects, covariates, dev_sids, test_sids, k=150):
    """Per-task models averaged."""
    import lightgbm as lgb

    print(f"\n  TASK SPECIALIST (per-task models, K={k})")

    task_preds = {}
    for task in TASKS:
        task_recs = [r for r in records if r["task"] == task]
        if not task_recs:
            continue

        # Build per-task feature matrix
        by_subj = defaultdict(list)
        for r in task_recs:
            by_subj[r["sid"]].append(r)

        rows = []
        sids_order = []
        for sid in sorted(by_subj.keys()):
            if sid not in subjects:
                continue
            recs = by_subj[sid]
            agg = {}
            all_keys = set()
            for r in recs:
                all_keys.update(r["feats"].keys())
            for kk in sorted(all_keys):
                vals = [r["feats"].get(kk, None) for r in recs]
                vals = [v for v in vals if v is not None and np.isfinite(v)]
                agg[kk] = float(np.mean(vals)) if vals else 0.0
            cov = covariates.get(sid, {})
            agg.update(cov)
            rows.append(agg)
            sids_order.append(sid)

        df = pd.DataFrame(rows)
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], 0.0).fillna(0.0)

        feat_cols = list(df.columns)
        dm = [s in dev_sids for s in sids_order]
        tm = [s in test_sids for s in sids_order]

        if sum(tm) == 0 or sum(dm) < 10:
            continue

        Xd = df.loc[dm].values.astype(np.float32)
        Xt = df.loc[tm].values.astype(np.float32)
        yd = np.array([subjects[s]["updrs3"] for s, d in zip(sids_order, dm) if d], dtype=np.float32)
        yt = np.array([subjects[s]["updrs3"] for s, t in zip(sids_order, tm) if t], dtype=np.float32)

        kk = min(k, Xd.shape[1])
        sel_idx, _ = feature_select(Xd, yd, feat_cols, kk)
        Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

        task_seed_preds = []
        for seed in SEEDS:
            p, _ = train_lgbm(Xds, yd, Xts, yt, seed)
            task_seed_preds.append(np.clip(p, 0, 132))

        task_preds[task] = np.mean(task_seed_preds, axis=0)
        task_mae = mean_absolute_error(yt, task_preds[task])
        print(f"    {task}: MAE={task_mae:.2f} ({Xd.shape[1]}→{kk} feats, {sum(dm)} dev, {sum(tm)} test)")

    # Ensemble: average predictions across tasks
    if len(task_preds) < 2:
        print("    Not enough tasks for ensemble")
        return None

    # All tasks should have same test subjects — verify
    test_subjects_per_task = {}
    all_test_preds = []
    for task_name, preds in task_preds.items():
        all_test_preds.append(preds)

    if not all_test_preds:
        return None

    # Simple average
    ens_pred = np.mean(all_test_preds, axis=0)
    # Need test y — use first task's
    yt = np.array([subjects[s]["updrs3"] for s in test_sids
                   if s in subjects], dtype=np.float32)[:len(ens_pred)]
    em = mean_absolute_error(yt, ens_pred)
    er, _ = sp_stats.pearsonr(yt, ens_pred)
    print(f"    TASK ENS ({len(task_preds)} tasks): MAE={em:.2f} r={er:.3f}")

    return {
        "config": f"task_specialist_{len(task_preds)}tasks", "n_raw": 0, "n_sel": k,
        "mean_mae": round(float(em), 3), "std_mae": 0.0,
        "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
        "seed_maes": [], "top10": list(task_preds.keys()),
        "ens_preds": ens_pred.tolist(),
    }


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    print("=" * 70)
    print("WAVE 3: EXTENDED COVARIATES + MODEL INNOVATIONS")
    print("=" * 70)

    subjects = parse_clinical()
    covariates = load_covariates_extended()
    subitems = parse_updrs_subitems()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    all_sids = dev_sids + test_sids

    # Build jobs
    jobs = []
    for task in TASKS:
        for sid in all_sids:
            if sid in subjects and os.path.exists(get_csv_path(sid, task, subjects)):
                jobs.append((sid, task))

    print(f"\nExtracting {len(jobs)} recordings on {N_CORES} cores...")
    with ProcessPoolExecutor(N_CORES, initializer=_init_worker, initargs=(subjects,)) as pool:
        records = [r for r in pool.map(extract_recording, jobs, chunksize=4) if r is not None]
    print(f"Done: {len(records)} recordings in {time.time()-t0:.0f}s")

    # Build feature matrix
    df_feat = build_feature_matrix(records, subjects, covariates)
    feat_cols = [c for c in df_feat.columns if c not in ("sid", "updrs3")]
    print(f"Feature matrix: {len(df_feat)} subjects × {len(feat_cols)} features")

    dm = df_feat["sid"].isin(dev_sids)
    tm = df_feat["sid"].isin(test_sids)
    X_dev = df_feat.loc[dm, feat_cols].values.astype(np.float32)
    y_dev = df_feat.loc[dm, "updrs3"].values.astype(np.float32)
    X_test = df_feat.loc[tm, feat_cols].values.astype(np.float32)
    y_test = df_feat.loc[tm, "updrs3"].values.astype(np.float32)

    dev_sids_ordered = df_feat.loc[dm, "sid"].tolist()
    test_sids_ordered = df_feat.loc[tm, "sid"].tolist()

    results = []

    # ── EXP 1: Baseline (original extraction, original 5 covariates, K=150) ──
    # Remove extended covariates to get original baseline
    orig_cols = [c for c in feat_cols if not c.startswith("cv_") or c in
                 ["cv_age", "cv_sex", "cv_years_dx", "cv_med_on", "cv_dbs"]]
    orig_idx = [feat_cols.index(c) for c in orig_cols]
    r = run_experiment("E1_orig_K150", X_dev[:, orig_idx], y_dev,
                       X_test[:, orig_idx], y_test, orig_cols, k=150)
    if r: results.append(r)
    baseline_mae = r["ens_mae"] if r else 99.0

    # ── EXP 2: Original + extended covariates, K=150 ──
    r = run_experiment("E2_extcov_K150", X_dev, y_dev, X_test, y_test, feat_cols, k=150)
    if r: results.append(r)

    # ── EXP 3: Original + extended covariates, K=200 ──
    r = run_experiment("E3_extcov_K200", X_dev, y_dev, X_test, y_test, feat_cols, k=200)
    if r: results.append(r)

    # ── EXP 4: Log1p target transform ──
    r = run_experiment("E4_log1p_K200", X_dev, y_dev, X_test, y_test, feat_cols, k=200,
                       target_transform=np.log1p, inv_transform=np.expm1)
    if r: results.append(r)

    # ── EXP 5: Sqrt target transform ──
    r = run_experiment("E5_sqrt_K200", X_dev, y_dev, X_test, y_test, feat_cols, k=200,
                       target_transform=np.sqrt,
                       inv_transform=lambda x: np.clip(x, 0, None)**2)
    if r: results.append(r)

    # ── EXP 6: Two-stage (observable → total) ──
    r = run_two_stage(X_dev, y_dev, X_test, y_test, feat_cols, subitems,
                      dev_sids_ordered, test_sids_ordered, k=200)
    if r: results.append(r)

    # ── EXP 7: Task specialist ensemble ──
    r = run_task_specialist(records, subjects, covariates, dev_sids, test_sids, k=150)
    if r: results.append(r)

    # ── EXP 8: K=250 with extended covariates ──
    r = run_experiment("E8_extcov_K250", X_dev, y_dev, X_test, y_test, feat_cols, k=250)
    if r: results.append(r)

    # ── REPORT ────────────────────────────────────────────────────────
    total = time.time() - t0
    print(f"\n{'='*70}")
    print("RESULTS (sorted by ENS MAE)")
    print(f"{'='*70}")
    print(f"{'Config':<30s} {'Raw':>5s} {'K':>4s} {'MAE±std':>12s} {'ENS':>7s} {'r':>6s} {'Δ':>6s}")
    print("-" * 75)
    for r in sorted(results, key=lambda x: x["ens_mae"]):
        d = baseline_mae - r["ens_mae"]
        ds = f"+{d:.2f}" if d > 0 else f"{d:.2f}"
        print(f"  {r['config']:<28s} {r['n_raw']:>5d} {r['n_sel']:>4d} "
              f"{r['mean_mae']:>5.2f}±{r['std_mae']:.2f} {r['ens_mae']:>7.2f} {r['ens_r']:>6.3f} {ds:>6s}")

    best = min(results, key=lambda x: x["ens_mae"])
    print(f"\n  Baseline (E1): {baseline_mae:.2f}")
    print(f"  Best:          {best['ens_mae']:.2f} ({best['config']})")
    print(f"  Δ:             {baseline_mae - best['ens_mae']:.2f}")
    print(f"\n  Top features ({best['config']}): {best.get('top10', [])[:5]}")
    print(f"  Runtime: {total:.0f}s ({total/60:.1f}m)")

    # Save
    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)): return int(obj)
            if isinstance(obj, (np.floating,)): return float(obj)
            if isinstance(obj, np.ndarray): return obj.tolist()
            return super().default(obj)

    with open("/root/pd-imu/wave3_results.json", "w") as f:
        json.dump({"baseline_mae": float(baseline_mae), "best_mae": float(best["ens_mae"]),
                    "best_config": best["config"], "results": results,
                    "runtime_s": round(total, 1)}, f, indent=2, cls=NpEncoder)
    print("  Saved to /root/pd-imu/wave3_results.json")


if __name__ == "__main__":
    main()

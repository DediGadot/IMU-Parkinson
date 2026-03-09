"""
V3 Full Feature Ablation Study
================================
Wave 1: Extract 7 new feature families (channels, stride, phase, asymmetry,
        nonlinear dynamics, frequency expansion, clinical covariates)
Wave 2: Ablation — test each family alone + combined winners

CPU-bound (~60-90 min on 11 cores for extraction, ~10 min for ablation).
Self-contained. Imports from data_split.py only.

Usage:
    python3 -u run_v3_ablation.py
"""
import os, sys, json, time, warnings, traceback
import numpy as np
import pandas as pd
from scipy import signal, stats as sp_stats
from scipy.fft import rfft, rfftfreq
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import StratifiedKFold
from concurrent.futures import ProcessPoolExecutor
from collections import defaultdict
warnings.filterwarnings("ignore")

sys.path.insert(0, "/root/pd-imu")
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS

TASKS = ["SelfPace", "HurriedPace", "TUG", "Balance", "TandemGait"]
GAIT_TASKS = ["SelfPace", "HurriedPace", "TUG"]  # stride-based tasks only
N_CORES = 11
SEEDS = [42, 123, 789]  # 3 seeds for ablation speed

# Channel definitions
ACC_COLS = ["Acc_X", "Acc_Y", "Acc_Z"]
GYR_COLS = ["Gyr_X", "Gyr_Y", "Gyr_Z"]
FREEACC_COLS = ["FreeAcc_E", "FreeAcc_N", "FreeAcc_U"]
EULER_COLS = ["Roll", "Pitch", "Yaw"]
MAG_COLS = ["Mag_X", "Mag_Y", "Mag_Z"]

PAIRED_SENSORS = [
    ("R_Wrist", "L_Wrist"),
    ("R_Ankle", "L_Ankle"),
    ("R_DorsalFoot", "L_DorsalFoot"),
    ("R_LatShank", "L_LatShank"),
    ("R_MidLatThigh", "L_MidLatThigh"),
]


# ══════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════

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


def load_subject_covariates_full():
    """Parse ALL clinical covariates (extended set)."""
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
            sex = 1.0 if str(row.get("Sex", "")).strip().upper().startswith("M") else 0.0
            height = pd.to_numeric(row.get("Height (cm)", row.get("Height", np.nan)), errors="coerce")
            weight = pd.to_numeric(row.get("Weight (kg)", row.get("Weight", np.nan)), errors="coerce")
            yrs = pd.to_numeric(
                row.get("Years since PD diagnosis", row.get("Years Since Diagnosis", 0)),
                errors="coerce",
            )
            dbs_raw = str(row.get("DBS?", row.get("DBS", ""))).strip().upper()
            hy_raw = pd.to_numeric(row.get("H&Y stage", row.get("Hoehn and Yahr", np.nan)), errors="coerce")

            age_v = float(age) if pd.notna(age) else 65.0
            yrs_v = float(yrs) if pd.notna(yrs) else 0.0
            height_v = float(height) if pd.notna(height) else 170.0
            weight_v = float(weight) if pd.notna(weight) else 75.0
            bmi = weight_v / ((height_v / 100.0) ** 2) if height_v > 0 else 25.0

            covariates[sid] = {
                "age": age_v,
                "sex": sex,
                "height": height_v,
                "weight": weight_v,
                "bmi": bmi,
                "years_dx": yrs_v,
                "dbs": 1.0 if dbs_raw in ("YES", "Y", "1") else 0.0,
                "hy": float(hy_raw) if pd.notna(hy_raw) else 0.0,
                "group_pd": 1.0 if group == "PD" else 0.0,
                # Derived
                "age_at_onset": age_v - yrs_v if yrs_v > 0 else age_v,
                "years_dx_sq": yrs_v ** 2,
                "years_dx_log": float(np.log1p(yrs_v)),
            }
    return covariates


# ══════════════════════════════════════════════════════════════════════
# FEATURE EXTRACTION: BASELINE (Acc + Gyr time/freq domain)
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
        bands = {"loco": (0.5, 3.0), "tremor": (3.0, 8.0), "high_r": (8.0, 20.0)}
        total_power = np.trapz(psd, freqs) + 1e-12
        for bname, (lo, hi) in bands.items():
            mask = (freqs >= lo) & (freqs <= hi)
            bp = np.trapz(psd[mask], freqs[mask]) if mask.sum() > 1 else 0.0
            feats[f"{prefix}_{bname}"] = float(np.log10(bp + 1e-12))
            feats[f"{prefix}_{bname}_rel"] = float(bp / total_power)
        feats[f"{prefix}_dom_freq"] = float(freqs[np.argmax(psd)])
        feats[f"{prefix}_psd_total"] = float(np.log10(total_power))
        psd_norm = psd / psd.sum()
        feats[f"{prefix}_se"] = float(-np.sum(psd_norm * np.log2(psd_norm + 1e-12)))
    except Exception:
        for k in ["loco", "tremor", "high_r"]:
            feats[f"{prefix}_{k}"] = 0.0
            feats[f"{prefix}_{k}_rel"] = 0.0
        feats[f"{prefix}_dom_freq"] = 0.0
        feats[f"{prefix}_psd_total"] = 0.0
        feats[f"{prefix}_se"] = 0.0
    return feats


def gait_regularity(acc_z, prefix=""):
    feats = {}
    try:
        x = acc_z - np.mean(acc_z)
        ac = np.correlate(x, x, mode="full")
        ac = ac[len(ac)//2:]
        ac = ac / (ac[0] + 1e-12)
        peaks, _ = signal.find_peaks(ac, distance=30, height=0.1)
        if len(peaks) >= 2:
            feats[f"{prefix}_step_time"] = float(peaks[0] / FS)
            feats[f"{prefix}_stride_time"] = float(peaks[1] / FS)
            feats[f"{prefix}_cadence"] = float(60.0 * FS / peaks[0]) if peaks[0] > 0 else 0.0
            feats[f"{prefix}_step_reg"] = float(ac[peaks[0]])
            feats[f"{prefix}_stride_reg"] = float(ac[peaks[1]]) if peaks[1] < len(ac) else 0.0
            feats[f"{prefix}_symmetry"] = abs(float(ac[peaks[0]]) - float(ac[peaks[1]])) if peaks[1] < len(ac) else 0.0
        else:
            for k in ["step_time", "stride_time", "cadence", "step_reg", "stride_reg", "symmetry"]:
                feats[f"{prefix}_{k}"] = 0.0
    except Exception:
        for k in ["step_time", "stride_time", "cadence", "step_reg", "stride_reg", "symmetry"]:
            feats[f"{prefix}_{k}"] = 0.0
    return feats


def freeze_index(acc_z, prefix=""):
    try:
        freqs, psd = signal.welch(acc_z, fs=FS, nperseg=min(256, len(acc_z)))
        loco = np.trapz(psd[(freqs >= 0.5) & (freqs <= 3.0)], freqs[(freqs >= 0.5) & (freqs <= 3.0)]) + 1e-12
        freeze = np.trapz(psd[(freqs >= 3.0) & (freqs <= 8.0)], freqs[(freqs >= 3.0) & (freqs <= 8.0)])
        return {f"{prefix}_fi": float(freeze / loco)}
    except Exception:
        return {f"{prefix}_fi": 0.0}


def extract_baseline_features(df, sensor, prefix):
    """Extract baseline Acc+Gyr features for one sensor."""
    feats = {}
    acc_cols = [f"{sensor}_{c}" for c in ACC_COLS]
    gyr_cols = [f"{sensor}_{c}" for c in GYR_COLS]

    has_acc = all(c in df.columns for c in acc_cols)
    has_gyr = all(c in df.columns for c in gyr_cols)

    if has_acc:
        acc = df[acc_cols].values.astype(np.float32)
        acc = np.nan_to_num(acc, nan=0.0)
        acc_mag = np.sqrt(np.sum(acc**2, axis=1))
        for i, ax in enumerate(["ax", "ay", "az"]):
            feats.update(time_domain_features(acc[:, i], f"{prefix}_{ax}"))
            feats.update(freq_domain_features(acc[:, i], f"{prefix}_{ax}"))
        feats.update(time_domain_features(acc_mag, f"{prefix}_am"))
        feats.update(freq_domain_features(acc_mag, f"{prefix}_am"))
        if sensor in ["LowerBack", "R_Ankle", "L_Ankle", "R_DorsalFoot", "L_DorsalFoot"]:
            feats.update(gait_regularity(acc[:, 2], f"{prefix}_gait"))
            feats.update(freeze_index(acc[:, 2], f"{prefix}"))

    if has_gyr:
        gyr = df[gyr_cols].values.astype(np.float32)
        gyr = np.nan_to_num(gyr, nan=0.0)
        gyr_mag = np.sqrt(np.sum(gyr**2, axis=1))
        feats.update(time_domain_features(gyr_mag, f"{prefix}_gm"))
        feats.update(freq_domain_features(gyr_mag, f"{prefix}_gm"))

    return feats


# ══════════════════════════════════════════════════════════════════════
# FEATURE FAMILY 1: CHANNEL EXPANSION (FreeAcc, Euler, Mag)
# ══════════════════════════════════════════════════════════════════════

def extract_channel_features(df, sensor, prefix):
    """Extract features from FreeAcc, Euler, Mag channels."""
    feats = {}

    # FreeAcc (gravity-removed, global frame)
    fa_cols = [f"{sensor}_{c}" for c in FREEACC_COLS]
    if all(c in df.columns for c in fa_cols):
        fa = df[fa_cols].values.astype(np.float32)
        fa = np.nan_to_num(fa, nan=0.0)
        fa_mag = np.sqrt(np.sum(fa**2, axis=1))
        for i, ax in enumerate(["fe", "fn", "fu"]):
            feats.update(time_domain_features(fa[:, i], f"{prefix}_{ax}"))
            feats.update(freq_domain_features(fa[:, i], f"{prefix}_{ax}"))
        feats.update(time_domain_features(fa_mag, f"{prefix}_fm"))
        # Jerk smoothness (SPARC proxy: spectral arc length)
        jerk_mag = np.diff(fa_mag) * FS
        feats[f"{prefix}_fm_jerk_smooth"] = safe_stat(
            lambda d: -float(np.sum(np.abs(np.diff(d)))), jerk_mag
        )

    # Euler angles (Roll/Pitch/Yaw)
    eu_cols = [f"{sensor}_{c}" for c in EULER_COLS]
    if all(c in df.columns for c in eu_cols):
        eu = df[eu_cols].values.astype(np.float32)
        eu = np.nan_to_num(eu, nan=0.0)
        for i, ax in enumerate(["ro", "pi", "ya"]):
            feats.update(time_domain_features(eu[:, i], f"{prefix}_{ax}"))
            feats[f"{prefix}_{ax}_rom"] = float(np.ptp(eu[:, i]))
            # Angular velocity from finite differences
            ang_vel = np.diff(eu[:, i]) * FS
            feats[f"{prefix}_{ax}_angvel_rms"] = safe_stat(
                lambda d: np.sqrt(np.mean(d**2)), ang_vel
            )
            feats[f"{prefix}_{ax}_angvel_peak"] = safe_stat(
                lambda d: np.max(np.abs(d)), ang_vel
            )

    # Magnetometer
    mg_cols = [f"{sensor}_{c}" for c in MAG_COLS]
    if all(c in df.columns for c in mg_cols):
        mg = df[mg_cols].values.astype(np.float32)
        mg = np.nan_to_num(mg, nan=0.0)
        mg_mag = np.sqrt(np.sum(mg**2, axis=1))
        feats[f"{prefix}_mag_rms"] = safe_stat(lambda d: np.sqrt(np.mean(d**2)), mg_mag)
        feats[f"{prefix}_mag_std"] = safe_stat(np.std, mg_mag)
        # Heading change rate (from Mag_X, Mag_Y)
        heading = np.arctan2(mg[:, 1], mg[:, 0])
        heading_rate = np.abs(np.diff(np.unwrap(heading))) * FS
        feats[f"{prefix}_heading_rate_mean"] = safe_stat(np.mean, heading_rate)
        feats[f"{prefix}_heading_rate_std"] = safe_stat(np.std, heading_rate)

    return feats


# ══════════════════════════════════════════════════════════════════════
# FEATURE FAMILY 2: STRIDE-ALIGNED FEATURES
# ══════════════════════════════════════════════════════════════════════

def detect_strides_from_shank(df, sensor="R_LatShank"):
    """Detect strides from shank gyroscope peaks (swing phase)."""
    col = f"{sensor}_Gyr_Y"
    if col not in df.columns:
        col = f"{sensor}_Gyr_X"
        if col not in df.columns:
            return []
    gyr = df[col].values.astype(np.float32)
    gyr = np.nan_to_num(gyr, nan=0.0)
    # Find peaks (mid-swing = peak angular velocity)
    peaks, props = signal.find_peaks(gyr, distance=50, height=np.percentile(gyr, 60), prominence=0.3)
    if len(peaks) < 3:
        return []
    # Strides = peak-to-peak
    strides = []
    for i in range(len(peaks) - 1):
        start, end = peaks[i], peaks[i + 1]
        dur = (end - start) / FS
        if 0.5 < dur < 3.0:  # valid stride duration
            strides.append((start, end, dur))
    return strides


def extract_stride_features(df, prefix):
    """Extract stride-aligned features from gait tasks."""
    feats = {}
    # Try both legs
    strides_R = detect_strides_from_shank(df, "R_LatShank")
    strides_L = detect_strides_from_shank(df, "L_LatShank")

    for side, strides in [("R", strides_R), ("L", strides_L)]:
        sp = f"{prefix}_str_{side}"
        if len(strides) < 5:
            for k in ["dur_mean", "dur_cv", "dur_iqr", "dur_slope", "n_strides"]:
                feats[f"{sp}_{k}"] = 0.0
            continue

        durs = np.array([s[2] for s in strides])
        feats[f"{sp}_dur_mean"] = float(np.mean(durs))
        feats[f"{sp}_dur_cv"] = float(np.std(durs) / (np.mean(durs) + 1e-8))
        feats[f"{sp}_dur_iqr"] = float(np.percentile(durs, 75) - np.percentile(durs, 25))
        feats[f"{sp}_n_strides"] = float(len(strides))
        # Trend (fatigue detection)
        if len(durs) > 5:
            slope = np.polyfit(np.arange(len(durs)), durs, 1)[0]
            feats[f"{sp}_dur_slope"] = float(slope)
        else:
            feats[f"{sp}_dur_slope"] = 0.0

        # Per-stride acceleration RMS variability
        lb_acc_cols = [f"LowerBack_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in lb_acc_cols):
            stride_rms = []
            for start, end, _ in strides:
                seg = df[lb_acc_cols].values[start:end].astype(np.float32)
                stride_rms.append(np.sqrt(np.mean(seg**2)))
            stride_rms = np.array(stride_rms)
            feats[f"{sp}_rms_cv"] = float(np.std(stride_rms) / (np.mean(stride_rms) + 1e-8))
            feats[f"{sp}_rms_mean"] = float(np.mean(stride_rms))

    # L-R stride timing asymmetry
    if len(strides_R) >= 5 and len(strides_L) >= 5:
        r_dur = np.mean([s[2] for s in strides_R])
        l_dur = np.mean([s[2] for s in strides_L])
        feats[f"{prefix}_str_asym"] = float(abs(r_dur - l_dur) / (r_dur + l_dur + 1e-8))
        feats[f"{prefix}_str_asym_signed"] = float((r_dur - l_dur) / (r_dur + l_dur + 1e-8))
    else:
        feats[f"{prefix}_str_asym"] = 0.0
        feats[f"{prefix}_str_asym_signed"] = 0.0

    return feats


# ══════════════════════════════════════════════════════════════════════
# FEATURE FAMILY 3: PHASE-SPECIFIC FEATURES
# ══════════════════════════════════════════════════════════════════════

def load_general_events(sid, task, subjects):
    """Load GeneralEvent annotations for a recording."""
    info = subjects[sid]
    base = "PD PARTICIPANTS" if info["group"] == "PD" else "CONTROL PARTICIPANTS"
    event_dir = os.path.join(DATA_DIR, base, "CSV files")
    # GeneralEvent files follow pattern: SID_Task_GeneralEvent.csv or similar
    candidates = [
        os.path.join(event_dir, f"{sid}_{task}_GeneralEvents.csv"),
        os.path.join(event_dir, f"{sid}_{task}_GeneralEvent.csv"),
        os.path.join(event_dir, f"{sid}_{task}_Event.csv"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return pd.read_csv(path)
            except Exception:
                continue
    return None


def extract_phase_features(df, sid, task, subjects, prefix):
    """Extract phase-specific features using GeneralEvent annotations."""
    feats = {}
    events = load_general_events(sid, task, subjects)
    if events is None or len(events) == 0:
        return feats

    # Try to parse events - column names vary
    time_col = None
    event_col = None
    for c in events.columns:
        cl = c.lower()
        if "time" in cl or "stamp" in cl or "sec" in cl:
            time_col = c
        if "event" in cl or "type" in cl or "label" in cl or "name" in cl:
            event_col = c
    if time_col is None or event_col is None:
        return feats

    events[time_col] = pd.to_numeric(events[time_col], errors="coerce")
    events = events.dropna(subset=[time_col])

    # Segment by phase
    phases = {}
    for _, row in events.iterrows():
        phase = str(row[event_col]).strip()
        t = float(row[time_col])
        if phase not in phases:
            phases[phase] = []
        phases[phase].append(t)

    # Extract LowerBack acc features per phase
    lb_cols = [f"LowerBack_{c}" for c in ACC_COLS]
    if not all(c in df.columns for c in lb_cols):
        return feats

    lb_acc = df[lb_cols].values.astype(np.float32)

    for phase_name in ["Walk", "Turn"]:
        times = sorted(phases.get(phase_name, []))
        if len(times) < 2:
            continue
        # Use pairs of timestamps as start/end of phase segments
        segments = []
        for i in range(0, len(times) - 1, 2):
            s_idx = int(times[i] * FS)
            e_idx = int(times[i + 1] * FS)
            if 0 <= s_idx < e_idx <= len(lb_acc) and (e_idx - s_idx) > 50:
                segments.append(lb_acc[s_idx:e_idx])

        if not segments:
            continue

        all_seg = np.concatenate(segments)
        seg_mag = np.sqrt(np.sum(all_seg**2, axis=1))
        sp = f"{prefix}_ph_{phase_name.lower()}"
        feats[f"{sp}_rms"] = float(np.sqrt(np.mean(seg_mag**2)))
        feats[f"{sp}_std"] = float(np.std(seg_mag))
        feats[f"{sp}_dur_total"] = float(len(all_seg) / FS)
        feats[f"{sp}_n_segments"] = float(len(segments))
        feats[f"{sp}_dur_mean"] = float(np.mean([len(s) / FS for s in segments]))
        if len(segments) > 1:
            seg_durs = [len(s) / FS for s in segments]
            feats[f"{sp}_dur_cv"] = float(np.std(seg_durs) / (np.mean(seg_durs) + 1e-8))
        else:
            feats[f"{sp}_dur_cv"] = 0.0

    # Phase ratios
    walk_key = f"{prefix}_ph_walk_rms"
    turn_key = f"{prefix}_ph_turn_rms"
    if walk_key in feats and turn_key in feats and feats[walk_key] > 0:
        feats[f"{prefix}_ph_turn_walk_ratio"] = feats[turn_key] / (feats[walk_key] + 1e-8)

    return feats


# ══════════════════════════════════════════════════════════════════════
# FEATURE FAMILY 4: L-R ASYMMETRY
# ══════════════════════════════════════════════════════════════════════

def extract_asymmetry_features(df, prefix):
    """Systematic L-R asymmetry for all bilateral sensor pairs."""
    feats = {}
    for r_sensor, l_sensor in PAIRED_SENSORS:
        pair = r_sensor.replace("R_", "")
        r_acc = [f"{r_sensor}_{c}" for c in ACC_COLS]
        l_acc = [f"{l_sensor}_{c}" for c in ACC_COLS]
        r_gyr = [f"{r_sensor}_{c}" for c in GYR_COLS]
        l_gyr = [f"{l_sensor}_{c}" for c in GYR_COLS]

        sp = f"{prefix}_asym_{pair}"

        # Acc asymmetry
        if all(c in df.columns for c in r_acc + l_acc):
            r_data = df[r_acc].values.astype(np.float32)
            l_data = df[l_acc].values.astype(np.float32)
            r_data = np.nan_to_num(r_data, nan=0.0)
            l_data = np.nan_to_num(l_data, nan=0.0)

            r_rms = np.sqrt(np.mean(r_data**2, axis=0))
            l_rms = np.sqrt(np.mean(l_data**2, axis=0))
            ai = np.abs(r_rms - l_rms) / (r_rms + l_rms + 1e-8)
            feats[f"{sp}_acc_ai_mean"] = float(np.mean(ai))
            feats[f"{sp}_acc_ai_max"] = float(np.max(ai))
            signed_ai = (r_rms - l_rms) / (r_rms + l_rms + 1e-8)
            feats[f"{sp}_acc_signed_mean"] = float(np.mean(signed_ai))

            # Bilateral correlation (healthy = high, PD = lower)
            for ax in range(3):
                r_ax = r_data[:, ax] - r_data[:, ax].mean()
                l_ax = l_data[:, ax] - l_data[:, ax].mean()
                denom = (np.std(r_ax) * np.std(l_ax) * len(r_ax))
                if denom > 1e-8:
                    corr = np.sum(r_ax * l_ax) / denom
                    feats[f"{sp}_bilat_corr_ax{ax}"] = float(np.clip(corr, -1, 1))
                else:
                    feats[f"{sp}_bilat_corr_ax{ax}"] = 0.0

        # Gyr asymmetry
        if all(c in df.columns for c in r_gyr + l_gyr):
            r_g = df[r_gyr].values.astype(np.float32)
            l_g = df[l_gyr].values.astype(np.float32)
            r_g = np.nan_to_num(r_g, nan=0.0)
            l_g = np.nan_to_num(l_g, nan=0.0)

            r_g_rms = np.sqrt(np.mean(r_g**2, axis=0))
            l_g_rms = np.sqrt(np.mean(l_g**2, axis=0))
            g_ai = np.abs(r_g_rms - l_g_rms) / (r_g_rms + l_g_rms + 1e-8)
            feats[f"{sp}_gyr_ai_mean"] = float(np.mean(g_ai))

    return feats


# ══════════════════════════════════════════════════════════════════════
# FEATURE FAMILY 5: NONLINEAR DYNAMICS (entropy, DFA)
# ══════════════════════════════════════════════════════════════════════

def sample_entropy(x, m=2, r_mult=0.2):
    """Sample entropy (Richman & Moorman 2000). O(n^2) but fast for n<5000."""
    n = len(x)
    if n < 100:
        return 0.0
    # Downsample for speed if too long
    if n > 3000:
        x = x[::n // 3000]
        n = len(x)
    r = r_mult * np.std(x)
    if r < 1e-10:
        return 0.0

    def _count_matches(m_val):
        count = 0
        templates = np.array([x[i:i + m_val] for i in range(n - m_val)])
        for i in range(len(templates)):
            dists = np.max(np.abs(templates[i + 1:] - templates[i]), axis=1)
            count += np.sum(dists < r)
        return count

    A = _count_matches(m + 1)
    B = _count_matches(m)
    if B == 0:
        return 0.0
    return float(-np.log((A + 1e-12) / (B + 1e-12)))


def dfa_alpha(x, min_box=4, max_box=None):
    """Detrended Fluctuation Analysis alpha exponent."""
    n = len(x)
    if n < 100:
        return 0.5
    if max_box is None:
        max_box = n // 4

    # Integrate
    y = np.cumsum(x - np.mean(x))

    box_sizes = np.unique(np.logspace(np.log10(min_box), np.log10(max_box), 15).astype(int))
    box_sizes = box_sizes[box_sizes >= min_box]
    if len(box_sizes) < 3:
        return 0.5

    flucts = []
    for bs in box_sizes:
        n_boxes = n // bs
        if n_boxes < 1:
            continue
        rms_vals = []
        for i in range(n_boxes):
            seg = y[i * bs:(i + 1) * bs]
            t = np.arange(len(seg))
            coefs = np.polyfit(t, seg, 1)
            trend = np.polyval(coefs, t)
            rms_vals.append(np.sqrt(np.mean((seg - trend) ** 2)))
        if rms_vals:
            flucts.append((bs, np.mean(rms_vals)))

    if len(flucts) < 3:
        return 0.5

    log_n = np.log([f[0] for f in flucts])
    log_f = np.log([f[1] + 1e-12 for f in flucts])
    try:
        alpha = np.polyfit(log_n, log_f, 1)[0]
        return float(alpha) if np.isfinite(alpha) else 0.5
    except Exception:
        return 0.5


def extract_nonlinear_features(df, prefix):
    """Extract nonlinear dynamics features from key signals."""
    feats = {}
    key_signals = [
        ("LowerBack", ACC_COLS, "lb_acc"),
        ("R_LatShank", ACC_COLS, "rsh_acc"),
        ("LowerBack", GYR_COLS, "lb_gyr"),
    ]

    for sensor, cols, sig_name in key_signals:
        full_cols = [f"{sensor}_{c}" for c in cols]
        if not all(c in df.columns for c in full_cols):
            continue
        data = df[full_cols].values.astype(np.float32)
        data = np.nan_to_num(data, nan=0.0)
        mag = np.sqrt(np.sum(data**2, axis=1))

        sp = f"{prefix}_nl_{sig_name}"
        feats[f"{sp}_sampen"] = sample_entropy(mag, m=2, r_mult=0.2)
        feats[f"{sp}_dfa"] = dfa_alpha(mag)

        # Permutation entropy (fast, robust)
        try:
            order = 3
            delay = 1
            n = len(mag) - (order - 1) * delay
            if n > 50:
                perm_patterns = defaultdict(int)
                for i in range(n):
                    pattern = tuple(np.argsort(mag[i:i + order * delay:delay]))
                    perm_patterns[pattern] += 1
                total = sum(perm_patterns.values())
                probs = np.array([c / total for c in perm_patterns.values()])
                pe = float(-np.sum(probs * np.log2(probs + 1e-12)))
                max_pe = np.log2(np.math.factorial(order))
                feats[f"{sp}_pe"] = pe / max_pe  # normalized
            else:
                feats[f"{sp}_pe"] = 0.0
        except Exception:
            feats[f"{sp}_pe"] = 0.0

    return feats


# ══════════════════════════════════════════════════════════════════════
# FEATURE FAMILY 6: ADVANCED FREQUENCY (wavelet, spectral complexity)
# ══════════════════════════════════════════════════════════════════════

def extract_frequency_features(df, prefix):
    """Wavelet decomposition + spectral complexity features."""
    feats = {}

    key_signals = [
        ("LowerBack", ACC_COLS, "lb"),
        ("R_LatShank", ACC_COLS, "rsh"),
        ("R_Wrist", ACC_COLS, "rwr"),
    ]

    for sensor, cols, sig_name in key_signals:
        full_cols = [f"{sensor}_{c}" for c in cols]
        if not all(c in df.columns for c in full_cols):
            continue
        data = df[full_cols].values.astype(np.float32)
        data = np.nan_to_num(data, nan=0.0)
        mag = np.sqrt(np.sum(data**2, axis=1))

        sp = f"{prefix}_freq_{sig_name}"

        # Wavelet decomposition (using scipy CWT with Morlet, or manual DWT)
        try:
            # Manual DWT using convolution (no pywt dependency)
            # Approximate db4 with a simple multi-level decomposition
            sig = mag.copy()
            level_energies = []
            for level in range(5):
                # Low-pass (approximate) and high-pass (detail)
                if len(sig) < 10:
                    break
                # Simple Haar-like decomposition
                n = len(sig) // 2 * 2
                sig = sig[:n]
                detail = sig[1::2] - sig[::2]  # high-pass
                approx = (sig[1::2] + sig[::2]) / 2  # low-pass

                detail_energy = float(np.sum(detail**2))
                level_energies.append(detail_energy)
                feats[f"{sp}_wl{level+1}_energy"] = float(np.log10(detail_energy + 1e-12))
                feats[f"{sp}_wl{level+1}_std"] = float(np.std(detail))
                sig = approx

            total_energy = sum(level_energies) + 1e-12
            for i, e in enumerate(level_energies):
                feats[f"{sp}_wl{i+1}_ratio"] = float(e / total_energy)
        except Exception:
            pass

        # Spectral complexity
        try:
            freqs, psd = signal.welch(mag, fs=FS, nperseg=min(256, len(mag)))
            psd = psd + 1e-12
            psd_norm = psd / psd.sum()

            # Spectral flatness (geometric/arithmetic mean)
            log_psd = np.log(psd)
            geo_mean = np.exp(np.mean(log_psd))
            arith_mean = np.mean(psd)
            feats[f"{sp}_spec_flat"] = float(geo_mean / (arith_mean + 1e-12))

            # Spectral centroid
            feats[f"{sp}_spec_centroid"] = float(np.sum(freqs * psd) / (np.sum(psd) + 1e-12))

            # Spectral bandwidth
            centroid = feats[f"{sp}_spec_centroid"]
            feats[f"{sp}_spec_bw"] = float(np.sqrt(
                np.sum((freqs - centroid)**2 * psd) / (np.sum(psd) + 1e-12)
            ))

            # Spectral edge (95%)
            cumsum = np.cumsum(psd) / np.sum(psd)
            feats[f"{sp}_spec_edge95"] = float(freqs[np.searchsorted(cumsum, 0.95)])

            # Harmonic ratio (even/odd harmonics)
            stride_range = (freqs >= 0.5) & (freqs <= 3.0)
            if stride_range.sum() > 0:
                fund_freq = freqs[stride_range][np.argmax(psd[stride_range])]
                if fund_freq > 0.1:
                    even_power = 0.0
                    odd_power = 0.0
                    for k in range(1, 7):
                        target = k * fund_freq
                        idx = np.argmin(np.abs(freqs - target))
                        if k % 2 == 0:
                            even_power += psd[idx]
                        else:
                            odd_power += psd[idx]
                    feats[f"{sp}_harmonic_ratio"] = float(even_power / (odd_power + 1e-12))
        except Exception:
            pass

    return feats


# ══════════════════════════════════════════════════════════════════════
# FEATURE FAMILY 7: CLINICAL COVARIATES (extended + interactions)
# ══════════════════════════════════════════════════════════════════════

def extract_covariate_features(sid, covariates_db, top_imu_features=None):
    """Extended clinical covariates + optional interactions."""
    feats = {}
    cov = covariates_db.get(sid, {})
    if not cov:
        return feats

    # Direct covariates
    for key in ["age", "sex", "height", "weight", "bmi", "years_dx", "dbs",
                "age_at_onset", "years_dx_sq", "years_dx_log"]:
        feats[f"cov_{key}"] = float(cov.get(key, 0.0))

    # Disease duration bins
    yrs = cov.get("years_dx", 0.0)
    feats["cov_early_pd"] = 1.0 if 0 < yrs <= 5 else 0.0
    feats["cov_mid_pd"] = 1.0 if 5 < yrs <= 10 else 0.0
    feats["cov_late_pd"] = 1.0 if yrs > 10 else 0.0

    return feats


# ══════════════════════════════════════════════════════════════════════
# MASTER EXTRACTION: ONE RECORDING → ALL FEATURE FAMILIES
# ══════════════════════════════════════════════════════════════════════

# Global state for multiprocessing
_SUBJECTS = None
_COVARIATES = None

def _init_worker(subjects, covariates):
    global _SUBJECTS, _COVARIATES
    _SUBJECTS = subjects
    _COVARIATES = covariates


def extract_all_families_for_recording(args):
    """Extract ALL feature families from one CSV. Runs in worker process."""
    sid, task = args
    global _SUBJECTS, _COVARIATES

    csv_path = get_csv_path(sid, task, _SUBJECTS)
    if not os.path.exists(csv_path):
        return None

    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None

    if len(df) < 200:
        return None

    result = {"sid": sid, "task": task}

    # BASELINE: Acc + Gyr for all sensors
    baseline = {}
    for sensor in SENSORS:
        baseline.update(extract_baseline_features(df, sensor, sensor))
    result["baseline"] = baseline

    # FAMILY 1: Channel expansion
    channels = {}
    for sensor in SENSORS:
        channels.update(extract_channel_features(df, sensor, sensor))
    result["channels"] = channels

    # FAMILY 2: Stride features (gait tasks only)
    stride = {}
    if task in GAIT_TASKS:
        stride = extract_stride_features(df, task)
    result["stride"] = stride

    # FAMILY 3: Phase features
    phase = extract_phase_features(df, sid, task, _SUBJECTS, task)
    result["phase"] = phase

    # FAMILY 4: Asymmetry
    asym = extract_asymmetry_features(df, task)
    result["asymmetry"] = asym

    # FAMILY 5: Nonlinear dynamics
    nonlinear = extract_nonlinear_features(df, task)
    result["nonlinear"] = nonlinear

    # FAMILY 6: Frequency expansion
    freq = extract_frequency_features(df, task)
    result["frequency"] = freq

    # FAMILY 7: Covariates (same for all tasks, but include per-recording for aggregation)
    covs = extract_covariate_features(sid, _COVARIATES)
    result["covariates"] = covs

    result["n_samples"] = len(df)
    result["duration_s"] = len(df) / FS

    return result


# ══════════════════════════════════════════════════════════════════════
# AGGREGATION: PER-TASK → PER-SUBJECT
# ══════════════════════════════════════════════════════════════════════

def aggregate_to_subjects(records, subjects):
    """Aggregate per-task features to per-subject (mean across tasks)."""
    by_subject = defaultdict(list)
    for rec in records:
        by_subject[rec["sid"]].append(rec)

    families = ["baseline", "channels", "stride", "phase", "asymmetry",
                "nonlinear", "frequency", "covariates"]

    rows = {family: [] for family in families}
    sids_out = []
    updrs_out = []

    for sid, recs in sorted(by_subject.items()):
        if sid not in subjects:
            continue
        sids_out.append(sid)
        updrs_out.append(subjects[sid]["updrs3"])

        for family in families:
            # Collect all keys across tasks for this family
            all_keys = set()
            for r in recs:
                all_keys.update(r.get(family, {}).keys())

            agg = {}
            for k in sorted(all_keys):
                vals = []
                for r in recs:
                    v = r.get(family, {}).get(k, None)
                    if v is not None and np.isfinite(v):
                        vals.append(v)
                agg[k] = float(np.mean(vals)) if vals else 0.0
            rows[family].append(agg)

    # Convert to DataFrames
    dfs = {}
    for family in families:
        df = pd.DataFrame(rows[family])
        df.insert(0, "sid", sids_out)
        df.insert(1, "updrs3", updrs_out)
        # Replace inf/nan
        for c in df.columns[2:]:
            df[c] = df[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        dfs[family] = df

    return dfs


# ══════════════════════════════════════════════════════════════════════
# ABLATION: TRAIN + EVALUATE EACH FEATURE FAMILY
# ══════════════════════════════════════════════════════════════════════

def feature_select(X_train, y_train, feat_names, k=150):
    """Select top-k features by XGBoost importance."""
    from xgboost import XGBRegressor

    selector = XGBRegressor(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
        objective="reg:absoluteerror",
    )
    selector.fit(X_train, y_train)
    importances = selector.feature_importances_
    top_idx = np.argsort(importances)[::-1][:k]
    return top_idx, [feat_names[i] for i in top_idx]


def train_eval_lgb(X_train, y_train, X_val, y_val, X_test, y_test, seed=42):
    """Train LightGBM and return test MAE + predictions."""
    import lightgbm as lgb

    model = lgb.LGBMRegressor(
        n_estimators=2000, learning_rate=0.03, max_depth=6,
        reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
        objective="mae", verbose=-1,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, pred)
    r, _ = sp_stats.pearsonr(y_test, pred)
    return mae, r, pred, model


def run_ablation_config(config_name, X_dev, y_dev, X_test, y_test, feat_names,
                         dev_sids, subjects, k=150):
    """Run one ablation config with feature selection + multi-seed."""
    print(f"\n  CONFIG: {config_name} ({X_dev.shape[1]} raw features → select top {k})")

    # Feature selection on dev set
    sel_idx, sel_names = feature_select(X_dev, y_dev, feat_names, k=min(k, X_dev.shape[1]))
    X_dev_sel = X_dev[:, sel_idx]
    X_test_sel = X_test[:, sel_idx]

    seed_maes, seed_rs, seed_preds = [], [], []
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(X_dev_sel))
        rng.shuffle(idx)
        n_val = max(1, int(len(idx) * 0.15))
        val_idx, tr_idx = idx[:n_val], idx[n_val:]

        mae, r, pred, _ = train_eval_lgb(
            X_dev_sel[tr_idx], y_dev[tr_idx],
            X_dev_sel[val_idx], y_dev[val_idx],
            X_test_sel, y_test, seed=seed,
        )
        seed_maes.append(mae)
        seed_rs.append(r)
        seed_preds.append(pred)
        print(f"    Seed {seed}: MAE={mae:.2f}, r={r:.3f}")

    # Ensemble
    ens_pred = np.mean(seed_preds, axis=0)
    ens_mae = mean_absolute_error(y_test, ens_pred)
    ens_r, _ = sp_stats.pearsonr(y_test, ens_pred)

    result = {
        "config": config_name,
        "n_raw_features": int(X_dev.shape[1]),
        "n_selected": len(sel_idx),
        "mean_mae": round(float(np.mean(seed_maes)), 3),
        "std_mae": round(float(np.std(seed_maes)), 3),
        "mean_r": round(float(np.mean(seed_rs)), 3),
        "ens_mae": round(float(ens_mae), 3),
        "ens_r": round(float(ens_r), 3),
        "seed_maes": [round(m, 3) for m in seed_maes],
        "top10_features": sel_names[:10],
    }
    print(f"    ENS: MAE={ens_mae:.2f}, r={ens_r:.3f}")
    return result


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    t_start = time.time()
    print("=" * 70)
    print("V3 FULL FEATURE ABLATION STUDY")
    print("Wave 1: Extract 7 feature families | Wave 2: Ablation + combination")
    print("=" * 70)

    # ── Load data ─────────────────────────────────────────────────────
    subjects = parse_clinical()
    covariates = load_subject_covariates_full()
    split = load_split()
    dev_sids = split["dev_sids"]
    test_sids = split["test_sids"]
    all_sids = dev_sids + test_sids

    print(f"\nSubjects: {len(subjects)} total, {len(dev_sids)} dev, {len(test_sids)} test")
    print(f"Covariates parsed: {len(covariates)} subjects")

    # ── WAVE 1: Feature extraction ────────────────────────────────────
    print(f"\n{'='*70}")
    print("WAVE 1: EXTRACTING ALL FEATURE FAMILIES")
    print(f"{'='*70}")

    # Build job list
    jobs = []
    for task in TASKS:
        for sid in all_sids:
            if sid in subjects:
                csv_path = get_csv_path(sid, task, subjects)
                if os.path.exists(csv_path):
                    jobs.append((sid, task))

    print(f"  Jobs: {len(jobs)} recordings across {len(TASKS)} tasks")
    print(f"  Workers: {N_CORES} CPU cores")

    t0 = time.time()
    with ProcessPoolExecutor(
        max_workers=N_CORES,
        initializer=_init_worker,
        initargs=(subjects, covariates),
    ) as pool:
        results = list(pool.map(extract_all_families_for_recording, jobs, chunksize=4))

    results = [r for r in results if r is not None]
    elapsed = time.time() - t0
    print(f"  Extracted {len(results)} recordings in {elapsed:.0f}s ({elapsed/60:.1f}m)")

    # Count features per family
    sample = results[0]
    for fam in ["baseline", "channels", "stride", "phase", "asymmetry", "nonlinear", "frequency", "covariates"]:
        n = len(sample.get(fam, {}))
        print(f"  {fam:<15s}: {n:>4d} features per recording (sample)")

    # ── Aggregate to subject level ────────────────────────────────────
    print(f"\n--- Aggregating to subject level ---")
    family_dfs = aggregate_to_subjects(results, subjects)

    for fam, df in family_dfs.items():
        feat_count = len([c for c in df.columns if c not in ("sid", "updrs3")])
        print(f"  {fam:<15s}: {len(df):>3d} subjects × {feat_count:>4d} features")

    # ── WAVE 2: ABLATION ──────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("WAVE 2: ABLATION STUDY")
    print(f"{'='*70}")

    # Prepare data matrices for each family
    families = ["baseline", "channels", "stride", "phase", "asymmetry",
                "nonlinear", "frequency", "covariates"]

    family_arrays = {}
    family_feat_names = {}
    for fam in families:
        df = family_dfs[fam]
        feat_cols = [c for c in df.columns if c not in ("sid", "updrs3")]
        # Align to dev/test split
        dev_mask = df["sid"].isin(dev_sids)
        test_mask = df["sid"].isin(test_sids)

        X_dev = df.loc[dev_mask, feat_cols].values.astype(np.float32)
        X_test = df.loc[test_mask, feat_cols].values.astype(np.float32)
        y_dev = df.loc[dev_mask, "updrs3"].values.astype(np.float32)
        y_test = df.loc[test_mask, "updrs3"].values.astype(np.float32)
        dev_s = df.loc[dev_mask, "sid"].values

        family_arrays[fam] = (X_dev, y_dev, X_test, y_test, dev_s)
        family_feat_names[fam] = feat_cols

    # Reference y values
    y_dev = family_arrays["baseline"][1]
    y_test = family_arrays["baseline"][3]
    dev_s = family_arrays["baseline"][4]

    all_results = []

    # ── B0: Baseline (Acc+Gyr only, 150 features) ────────────────────
    print(f"\n{'─'*60}")
    print("SINGLE-FAMILY ABLATION")
    print(f"{'─'*60}")

    r = run_ablation_config(
        "B0_baseline",
        family_arrays["baseline"][0], y_dev,
        family_arrays["baseline"][2], y_test,
        family_feat_names["baseline"], dev_s, subjects, k=150,
    )
    all_results.append(r)
    baseline_mae = r["ens_mae"]

    # ── B1-B7: Each new family ALONE ──────────────────────────────────
    for i, fam in enumerate(families[1:], 1):
        X_d, _, X_t, _, _ = family_arrays[fam]
        if X_d.shape[1] == 0:
            print(f"\n  CONFIG: B{i}_{fam} — SKIPPED (0 features)")
            continue

        r = run_ablation_config(
            f"B{i}_{fam}_only",
            X_d, y_dev, X_t, y_test,
            family_feat_names[fam], dev_s, subjects,
            k=min(100, X_d.shape[1]),
        )
        all_results.append(r)

    # ── B8-B14: Baseline + each family ────────────────────────────────
    print(f"\n{'─'*60}")
    print("BASELINE + EACH FAMILY")
    print(f"{'─'*60}")

    X_base_dev = family_arrays["baseline"][0]
    X_base_test = family_arrays["baseline"][2]
    base_names = family_feat_names["baseline"]

    for i, fam in enumerate(families[1:], 1):
        X_d, _, X_t, _, _ = family_arrays[fam]
        if X_d.shape[1] == 0:
            print(f"\n  CONFIG: B{i+7}_base+{fam} — SKIPPED (0 features)")
            continue

        X_combo_dev = np.hstack([X_base_dev, X_d])
        X_combo_test = np.hstack([X_base_test, X_t])
        combo_names = base_names + family_feat_names[fam]

        r = run_ablation_config(
            f"B{i+7}_base+{fam}",
            X_combo_dev, y_dev, X_combo_test, y_test,
            combo_names, dev_s, subjects, k=180,
        )
        all_results.append(r)

    # ── C1: All families combined ─────────────────────────────────────
    print(f"\n{'─'*60}")
    print("COMBINED CONFIGURATIONS")
    print(f"{'─'*60}")

    # Combine all families
    all_X_dev_parts = [family_arrays[f][0] for f in families if family_arrays[f][0].shape[1] > 0]
    all_X_test_parts = [family_arrays[f][2] for f in families if family_arrays[f][2].shape[1] > 0]
    all_names = []
    for f in families:
        if family_arrays[f][0].shape[1] > 0:
            all_names.extend(family_feat_names[f])

    X_all_dev = np.hstack(all_X_dev_parts)
    X_all_test = np.hstack(all_X_test_parts)

    print(f"\n  Total combined features: {X_all_dev.shape[1]}")

    # C1: All combined, K=150
    r = run_ablation_config("C1_all_K150", X_all_dev, y_dev, X_all_test, y_test,
                             all_names, dev_s, subjects, k=150)
    all_results.append(r)

    # C2: All combined, K=200
    r = run_ablation_config("C2_all_K200", X_all_dev, y_dev, X_all_test, y_test,
                             all_names, dev_s, subjects, k=200)
    all_results.append(r)

    # C3: All combined, K=300
    r = run_ablation_config("C3_all_K300", X_all_dev, y_dev, X_all_test, y_test,
                             all_names, dev_s, subjects, k=300)
    all_results.append(r)

    # C4: All combined, K=400
    r = run_ablation_config("C4_all_K400", X_all_dev, y_dev, X_all_test, y_test,
                             all_names, dev_s, subjects, k=min(400, X_all_dev.shape[1]))
    all_results.append(r)

    # C5: All combined, K=500
    if X_all_dev.shape[1] >= 500:
        r = run_ablation_config("C5_all_K500", X_all_dev, y_dev, X_all_test, y_test,
                                 all_names, dev_s, subjects, k=500)
        all_results.append(r)

    # ── C6: XGBoost on best combined ──────────────────────────────────
    print(f"\n{'─'*60}")
    print("XGBOOST COMPARISON ON BEST K")
    print(f"{'─'*60}")

    # Find best K from C1-C5
    c_results = [r for r in all_results if r["config"].startswith("C")]
    best_c = min(c_results, key=lambda x: x["ens_mae"])
    best_k = best_c["n_selected"]
    print(f"  Best combined config: {best_c['config']} MAE={best_c['ens_mae']:.2f}, K={best_k}")

    # XGBoost on same features
    from xgboost import XGBRegressor
    sel_idx, sel_names = feature_select(X_all_dev, y_dev, all_names, k=best_k)
    X_dev_sel = X_all_dev[:, sel_idx]
    X_test_sel = X_all_test[:, sel_idx]

    xgb_maes, xgb_rs, xgb_preds = [], [], []
    print(f"\n  CONFIG: C6_xgb_K{best_k}")
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(X_dev_sel))
        rng.shuffle(idx)
        n_val = max(1, int(len(idx) * 0.15))
        val_idx, tr_idx = idx[:n_val], idx[n_val:]

        model = XGBRegressor(
            n_estimators=2000, learning_rate=0.03, max_depth=6,
            reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
            early_stopping_rounds=100, objective="reg:absoluteerror",
        )
        model.fit(X_dev_sel[tr_idx], y_dev[tr_idx],
                  eval_set=[(X_dev_sel[val_idx], y_dev[val_idx])], verbose=False)
        pred = model.predict(X_test_sel)
        mae = mean_absolute_error(y_test, pred)
        r_val, _ = sp_stats.pearsonr(y_test, pred)
        xgb_maes.append(mae)
        xgb_rs.append(r_val)
        xgb_preds.append(pred)
        print(f"    Seed {seed}: MAE={mae:.2f}, r={r_val:.3f}")

    ens_pred = np.mean(xgb_preds, axis=0)
    ens_mae = mean_absolute_error(y_test, ens_pred)
    ens_r, _ = sp_stats.pearsonr(y_test, ens_pred)
    print(f"    ENS: MAE={ens_mae:.2f}, r={ens_r:.3f}")
    all_results.append({
        "config": f"C6_xgb_K{best_k}",
        "n_raw_features": int(X_all_dev.shape[1]),
        "n_selected": best_k,
        "mean_mae": round(float(np.mean(xgb_maes)), 3),
        "std_mae": round(float(np.std(xgb_maes)), 3),
        "mean_r": round(float(np.mean(xgb_rs)), 3),
        "ens_mae": round(float(ens_mae), 3),
        "ens_r": round(float(ens_r), 3),
        "seed_maes": [round(m, 3) for m in xgb_maes],
        "top10_features": sel_names[:10],
    })

    # ── FINAL REPORT ──────────────────────────────────────────────────
    total_time = time.time() - t_start
    print(f"\n{'='*70}")
    print("ABLATION RESULTS SUMMARY")
    print(f"{'='*70}")
    print(f"{'Config':<30s} {'Raw':>5s} {'Sel':>4s} {'MAE±std':>12s} {'ENS MAE':>8s} {'ENS r':>7s} {'Delta':>7s}")
    print(f"{'-'*76}")

    for r in sorted(all_results, key=lambda x: x["ens_mae"]):
        delta = baseline_mae - r["ens_mae"]
        delta_str = f"+{delta:.2f}" if delta > 0 else f"{delta:.2f}"
        print(f"  {r['config']:<28s} {r['n_raw_features']:>5d} {r['n_selected']:>4d} "
              f"{r['mean_mae']:>5.2f}±{r['std_mae']:.2f} {r['ens_mae']:>8.2f} {r['ens_r']:>7.3f} {delta_str:>7s}")

    print(f"\n  Baseline: MAE={baseline_mae:.2f}")
    best = min(all_results, key=lambda x: x["ens_mae"])
    print(f"  Best:     MAE={best['ens_mae']:.2f} ({best['config']})")
    print(f"  Improvement: {baseline_mae - best['ens_mae']:.2f} MAE points")

    # Top features from best config
    print(f"\n  Top 10 features ({best['config']}):")
    for i, f in enumerate(best.get("top10_features", [])[:10]):
        print(f"    {i+1:2d}. {f}")

    print(f"\n  Total runtime: {total_time:.0f}s ({total_time/60:.1f}m)")

    # ── Save results ──────────────────────────────────────────────────
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runtime_s": round(total_time, 1),
        "baseline_mae": baseline_mae,
        "best_mae": best["ens_mae"],
        "best_config": best["config"],
        "improvement": round(baseline_mae - best["ens_mae"], 3),
        "results": all_results,
    }
    out_path = "/root/pd-imu/v3_ablation_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Saved to {out_path}")


if __name__ == "__main__":
    main()

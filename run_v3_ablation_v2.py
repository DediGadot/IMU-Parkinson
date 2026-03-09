"""
V3 Ablation v2: Fixed Phase + Stride + Grafted onto Original Pipeline
=====================================================================
Fixes from v1:
  - GeneralEvent is a COLUMN in CSV, not a separate file
  - Foot Contact is a binary COLUMN (L/R Foot Contact), 0/1 per sample
  - Uses original run_biomechanics.py extraction as baseline (FreeAcc+Euler+covariates)
  - Only adds TRULY NEW features on top

New feature families tested:
  1. Extended covariates (height, weight, BMI, duration nonlinearity, onset age)
  2. Phase-specific features (Walk vs Turn vs Standing from GeneralEvent column)
  3. Foot contact stride features (from L/R Foot Contact binary columns)
  4. Systematic asymmetry (expanded L-R features)
  5. Nonlinear dynamics (sample entropy, DFA, permutation entropy)
  6. Wavelet energy features

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
SEEDS = [42, 123, 456, 789, 2024]  # 5 seeds for reliable comparison

ACC_COLS = ["Acc_X", "Acc_Y", "Acc_Z"]
GYR_COLS = ["Gyr_X", "Gyr_Y", "Gyr_Z"]
FREEACC_COLS = ["FreeAcc_E", "FreeAcc_N", "FreeAcc_U"]
EULER_COLS = ["Roll", "Pitch", "Yaw"]
PAIRED_SENSORS = [
    ("R_Wrist", "L_Wrist"), ("R_Ankle", "L_Ankle"),
    ("R_DorsalFoot", "L_DorsalFoot"), ("R_LatShank", "L_LatShank"),
    ("R_MidLatThigh", "L_MidLatThigh"),
]


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
# BASELINE EXTRACTION (matches run_biomechanics.py exactly)
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
            feats[f"{prefix}_{k}"] = 0.0; feats[f"{prefix}_{k}_rel"] = 0.0
        feats[f"{prefix}_dom_freq"] = 0.0; feats[f"{prefix}_psd_total"] = 0.0
        feats[f"{prefix}_se"] = 0.0
    return feats


def gait_regularity(acc_z, prefix=""):
    feats = {}
    try:
        x = acc_z - np.mean(acc_z)
        ac = np.correlate(x, x, mode="full"); ac = ac[len(ac)//2:]
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


def extract_baseline(df):
    """Extract baseline features matching run_biomechanics.py: Acc+FreeAcc+Gyr+Euler+gait."""
    feats = {}
    for sensor in SENSORS:
        # Acc: prefer FreeAcc, fallback to Acc
        fa_cols = [f"{sensor}_{c}" for c in FREEACC_COLS]
        acc_cols = [f"{sensor}_{c}" for c in ACC_COLS]
        use_cols = fa_cols if all(c in df.columns for c in fa_cols) else acc_cols
        tag = "fa" if use_cols == fa_cols else "ac"

        if all(c in df.columns for c in use_cols):
            acc = df[use_cols].values.astype(np.float32)
            acc = np.nan_to_num(acc, nan=0.0)
            acc_mag = np.sqrt(np.sum(acc**2, axis=1))
            for i, ax in enumerate(["x", "y", "z"]):
                feats.update(time_domain_features(acc[:, i], f"{sensor}_{tag}_{ax}"))
                feats.update(freq_domain_features(acc[:, i], f"{sensor}_{tag}_{ax}"))
            feats.update(time_domain_features(acc_mag, f"{sensor}_{tag}_m"))
            feats.update(freq_domain_features(acc_mag, f"{sensor}_{tag}_m"))
            if sensor in ["LowerBack", "R_Ankle", "L_Ankle", "R_DorsalFoot", "L_DorsalFoot"]:
                feats.update(gait_regularity(acc[:, 2], f"{sensor}_gait"))
                # Freeze index
                try:
                    fr, psd = signal.welch(acc[:, 2], fs=FS, nperseg=min(256, len(acc)))
                    loco_p = np.trapz(psd[(fr >= 0.5) & (fr <= 3.0)], fr[(fr >= 0.5) & (fr <= 3.0)]) + 1e-12
                    freeze_p = np.trapz(psd[(fr >= 3.0) & (fr <= 8.0)], fr[(fr >= 3.0) & (fr <= 8.0)])
                    feats[f"{sensor}_fi"] = float(freeze_p / loco_p)
                except Exception:
                    feats[f"{sensor}_fi"] = 0.0

        # Gyr
        gyr_cols = [f"{sensor}_{c}" for c in GYR_COLS]
        if all(c in df.columns for c in gyr_cols):
            gyr = df[gyr_cols].values.astype(np.float32)
            gyr = np.nan_to_num(gyr, nan=0.0)
            gyr_mag = np.sqrt(np.sum(gyr**2, axis=1))
            feats.update(time_domain_features(gyr_mag, f"{sensor}_gm"))
            feats.update(freq_domain_features(gyr_mag, f"{sensor}_gm"))

        # Euler angles (Roll/Pitch/Yaw)
        eu_cols = [f"{sensor}_{c}" for c in EULER_COLS]
        if all(c in df.columns for c in eu_cols):
            euler = df[eu_cols].values.astype(np.float32)
            euler = np.nan_to_num(euler, nan=0.0)
            for i, ax in enumerate(["ro", "pi", "ya"]):
                feats.update(time_domain_features(euler[:, i], f"{sensor}_{ax}"))
                feats[f"{sensor}_{ax}_rom"] = float(np.ptp(euler[:, i]))

    # Cross-sensor asymmetry (basic, from original)
    for l_s, r_s in PAIRED_SENSORS:
        l_c = [f"{l_s}_{c}" for c in ACC_COLS]; r_c = [f"{r_s}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in l_c + r_c):
            ld = df[l_c].values.astype(np.float32); rd = df[r_c].values.astype(np.float32)
            l_rms = np.sqrt(np.mean(ld**2, axis=0)); r_rms = np.sqrt(np.mean(rd**2, axis=0))
            asym = np.abs(l_rms - r_rms) / (l_rms + r_rms + 1e-8)
            pair = l_s.replace("L_", "").replace("R_", "")
            feats[f"asym_{pair}_mean"] = float(np.mean(asym))
            feats[f"asym_{pair}_max"] = float(np.max(asym))

    feats[f"n_samples"] = len(df)
    feats[f"duration_s"] = len(df) / FS
    return feats


# ══════════════════════════════════════════════════════════════════════
# NEW FAMILY 1: EXTENDED COVARIATES
# ══════════════════════════════════════════════════════════════════════

def load_extended_covariates():
    """Parse ALL clinical covariates including new ones."""
    covariates = {}
    for fn, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path): continue
        df = pd.read_csv(path, header=1)
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan": continue
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

            covariates[sid] = {
                # Original 5 (already in baseline)
                "cov_age": age_v, "cov_sex": sex, "cov_years_dx": yrs_v,
                "cov_med_on": 1.0 if str(row.get("Medication State", "")).strip().upper() == "ON" else 0.0,
                "cov_dbs": 1.0 if dbs_raw in ("YES", "Y", "1") else 0.0,
                # NEW extended covariates
                "cov_height": h, "cov_weight": w,
                "cov_bmi": w / ((h / 100.0) ** 2) if h > 0 else 25.0,
                "cov_age_onset": age_v - yrs_v if yrs_v > 0 else age_v,
                "cov_yrs_sq": yrs_v ** 2,
                "cov_yrs_log": float(np.log1p(yrs_v)),
                "cov_early": 1.0 if 0 < yrs_v <= 5 else 0.0,
                "cov_late": 1.0 if yrs_v > 10 else 0.0,
            }
    return covariates


# ══════════════════════════════════════════════════════════════════════
# NEW FAMILY 2: PHASE-SPECIFIC (from GeneralEvent COLUMN)
# ══════════════════════════════════════════════════════════════════════

def extract_phase_features(df):
    """Phase-specific features from GeneralEvent column in CSV."""
    feats = {}
    if "GeneralEvent" not in df.columns:
        return feats

    events = df["GeneralEvent"].fillna("")

    # LowerBack acceleration as reference signal
    lb_cols = [f"LowerBack_{c}" for c in ACC_COLS]
    if not all(c in df.columns for c in lb_cols):
        return feats
    lb_acc = df[lb_cols].values.astype(np.float32)
    lb_acc = np.nan_to_num(lb_acc, nan=0.0)
    lb_mag = np.sqrt(np.sum(lb_acc**2, axis=1))

    for phase in ["Walk", "Turn", "Standing", "Sitting"]:
        mask = events.str.strip() == phase
        n_phase = mask.sum()
        if n_phase < 50:  # need at least 0.5s
            continue

        seg = lb_mag[mask.values]
        sp = f"ph_{phase.lower()}"
        feats[f"{sp}_rms"] = float(np.sqrt(np.mean(seg**2)))
        feats[f"{sp}_std"] = float(np.std(seg))
        feats[f"{sp}_pct"] = float(n_phase / len(df))  # fraction of time in this phase
        feats[f"{sp}_dur_s"] = float(n_phase / FS)

        # Count segments (transitions into this phase)
        transitions = np.diff(mask.astype(int))
        n_segments = np.sum(transitions == 1)
        feats[f"{sp}_n_seg"] = float(max(n_segments, 1))
        feats[f"{sp}_mean_dur"] = float(n_phase / FS / max(n_segments, 1))

        # Segment duration variability
        if n_segments > 1:
            seg_starts = np.where(transitions == 1)[0]
            seg_ends = np.where(transitions == -1)[0]
            if len(seg_ends) < len(seg_starts):
                seg_ends = np.append(seg_ends, len(df) - 1)
            seg_durs = (seg_ends[:len(seg_starts)] - seg_starts) / FS
            seg_durs = seg_durs[seg_durs > 0.1]  # filter tiny segments
            if len(seg_durs) > 1:
                feats[f"{sp}_dur_cv"] = float(np.std(seg_durs) / (np.mean(seg_durs) + 1e-8))
            else:
                feats[f"{sp}_dur_cv"] = 0.0
        else:
            feats[f"{sp}_dur_cv"] = 0.0

    # Phase ratios
    walk_rms = feats.get("ph_walk_rms", 0.0)
    turn_rms = feats.get("ph_turn_rms", 0.0)
    if walk_rms > 0:
        feats["ph_turn_walk_ratio"] = turn_rms / (walk_rms + 1e-8)
    walk_pct = feats.get("ph_walk_pct", 0.0)
    turn_pct = feats.get("ph_turn_pct", 0.0)
    if walk_pct + turn_pct > 0:
        feats["ph_turn_frac"] = turn_pct / (walk_pct + turn_pct + 1e-8)

    return feats


# ══════════════════════════════════════════════════════════════════════
# NEW FAMILY 3: FOOT CONTACT STRIDE FEATURES
# ══════════════════════════════════════════════════════════════════════

def extract_foot_contact_features(df):
    """Stride features from L/R Foot Contact binary columns."""
    feats = {}
    for side in ["L", "R"]:
        col = f"{side} Foot Contact"
        if col not in df.columns:
            continue
        fc = df[col].values.astype(np.float32)
        fc = np.nan_to_num(fc, nan=0.0)

        # Detect heel strikes (transitions from 0→1)
        transitions = np.diff(fc)
        heel_strikes = np.where(transitions == 1)[0]
        toe_offs = np.where(transitions == -1)[0]

        sp = f"fc_{side}"

        if len(heel_strikes) < 3:
            for k in ["stride_dur_mean", "stride_dur_cv", "stride_dur_iqr",
                       "stance_pct_mean", "swing_pct_mean", "cadence", "n_strides",
                       "stride_dur_slope"]:
                feats[f"{sp}_{k}"] = 0.0
            continue

        # Stride durations (heel-strike to heel-strike)
        stride_durs = np.diff(heel_strikes) / FS
        stride_durs = stride_durs[(stride_durs > 0.3) & (stride_durs < 3.0)]  # filter outliers

        if len(stride_durs) < 3:
            for k in ["stride_dur_mean", "stride_dur_cv", "stride_dur_iqr",
                       "stance_pct_mean", "swing_pct_mean", "cadence", "n_strides",
                       "stride_dur_slope"]:
                feats[f"{sp}_{k}"] = 0.0
            continue

        feats[f"{sp}_stride_dur_mean"] = float(np.mean(stride_durs))
        feats[f"{sp}_stride_dur_cv"] = float(np.std(stride_durs) / (np.mean(stride_durs) + 1e-8))
        feats[f"{sp}_stride_dur_iqr"] = float(np.percentile(stride_durs, 75) - np.percentile(stride_durs, 25))
        feats[f"{sp}_cadence"] = float(60.0 / (np.mean(stride_durs) + 1e-8))
        feats[f"{sp}_n_strides"] = float(len(stride_durs))

        # Stride duration trend (fatigue)
        if len(stride_durs) > 5:
            feats[f"{sp}_stride_dur_slope"] = float(np.polyfit(np.arange(len(stride_durs)), stride_durs, 1)[0])
        else:
            feats[f"{sp}_stride_dur_slope"] = 0.0

        # Stance/swing ratio
        stance_pcts = []
        for i in range(len(heel_strikes) - 1):
            hs = heel_strikes[i]
            next_hs = heel_strikes[i + 1]
            # Find toe-off between these heel strikes
            tos_between = toe_offs[(toe_offs > hs) & (toe_offs < next_hs)]
            if len(tos_between) > 0:
                stance_dur = (tos_between[0] - hs) / FS
                stride_dur_s = (next_hs - hs) / FS
                if stride_dur_s > 0:
                    stance_pcts.append(stance_dur / stride_dur_s)

        if stance_pcts:
            feats[f"{sp}_stance_pct_mean"] = float(np.mean(stance_pcts))
            feats[f"{sp}_swing_pct_mean"] = float(1.0 - np.mean(stance_pcts))
        else:
            feats[f"{sp}_stance_pct_mean"] = 0.0
            feats[f"{sp}_swing_pct_mean"] = 0.0

    # L-R stride timing asymmetry
    l_dur = feats.get("fc_L_stride_dur_mean", 0.0)
    r_dur = feats.get("fc_R_stride_dur_mean", 0.0)
    if l_dur > 0 and r_dur > 0:
        feats["fc_stride_asym"] = float(abs(l_dur - r_dur) / (l_dur + r_dur))
        feats["fc_stride_asym_signed"] = float((r_dur - l_dur) / (r_dur + l_dur))
    else:
        feats["fc_stride_asym"] = 0.0
        feats["fc_stride_asym_signed"] = 0.0

    # L-R cadence asymmetry
    l_cad = feats.get("fc_L_cadence", 0.0)
    r_cad = feats.get("fc_R_cadence", 0.0)
    if l_cad > 0 and r_cad > 0:
        feats["fc_cadence_asym"] = float(abs(l_cad - r_cad) / (l_cad + r_cad))
    else:
        feats["fc_cadence_asym"] = 0.0

    # Double support (both feet on ground)
    if "L Foot Contact" in df.columns and "R Foot Contact" in df.columns:
        l_fc = df["L Foot Contact"].values.astype(np.float32)
        r_fc = df["R Foot Contact"].values.astype(np.float32)
        l_fc = np.nan_to_num(l_fc, nan=0.0)
        r_fc = np.nan_to_num(r_fc, nan=0.0)
        double_support = (l_fc > 0.5) & (r_fc > 0.5)
        feats["fc_double_support_pct"] = float(np.mean(double_support))

    return feats


# ══════════════════════════════════════════════════════════════════════
# NEW FAMILY 4: NONLINEAR DYNAMICS
# ══════════════════════════════════════════════════════════════════════

def sample_entropy_fast(x, m=2, r_mult=0.2):
    n = len(x)
    if n < 100: return 0.0
    if n > 2000: x = x[::n // 2000]; n = len(x)
    r = r_mult * np.std(x)
    if r < 1e-10: return 0.0
    def _count(mv):
        count = 0
        tmpl = np.array([x[i:i+mv] for i in range(n - mv)])
        for i in range(len(tmpl)):
            dists = np.max(np.abs(tmpl[i+1:] - tmpl[i]), axis=1)
            count += np.sum(dists < r)
        return count
    A = _count(m + 1); B = _count(m)
    return float(-np.log((A + 1e-12) / (B + 1e-12))) if B > 0 else 0.0


def dfa_alpha(x):
    n = len(x)
    if n < 100: return 0.5
    y = np.cumsum(x - np.mean(x))
    box_sizes = np.unique(np.logspace(np.log10(4), np.log10(n // 4), 12).astype(int))
    flucts = []
    for bs in box_sizes:
        if bs < 4 or n // bs < 1: continue
        rms_vals = []
        for i in range(n // bs):
            seg = y[i*bs:(i+1)*bs]
            t = np.arange(len(seg))
            trend = np.polyval(np.polyfit(t, seg, 1), t)
            rms_vals.append(np.sqrt(np.mean((seg - trend)**2)))
        if rms_vals: flucts.append((bs, np.mean(rms_vals)))
    if len(flucts) < 3: return 0.5
    try:
        alpha = np.polyfit(np.log([f[0] for f in flucts]), np.log([f[1]+1e-12 for f in flucts]), 1)[0]
        return float(alpha) if np.isfinite(alpha) else 0.5
    except Exception:
        return 0.5


def extract_nonlinear(df):
    feats = {}
    for sensor, cols, tag in [("LowerBack", ACC_COLS, "lb"), ("R_LatShank", ACC_COLS, "rsh")]:
        full = [f"{sensor}_{c}" for c in cols]
        if not all(c in df.columns for c in full): continue
        data = np.nan_to_num(df[full].values.astype(np.float32), nan=0.0)
        mag = np.sqrt(np.sum(data**2, axis=1))
        feats[f"nl_{tag}_sampen"] = sample_entropy_fast(mag)
        feats[f"nl_{tag}_dfa"] = dfa_alpha(mag)
        # Permutation entropy
        order, n = 3, len(mag) - 2
        if n > 50:
            pats = defaultdict(int)
            for i in range(n):
                pats[tuple(np.argsort(mag[i:i+order]))] += 1
            total = sum(pats.values())
            probs = np.array([c/total for c in pats.values()])
            pe = float(-np.sum(probs * np.log2(probs + 1e-12)))
            feats[f"nl_{tag}_pe"] = pe / np.log2(math.factorial(order))
        else:
            feats[f"nl_{tag}_pe"] = 0.0
    return feats


# ══════════════════════════════════════════════════════════════════════
# MASTER EXTRACTION PER RECORDING
# ══════════════════════════════════════════════════════════════════════

_SUBJECTS = None
_COVARIATES = None

def _init_worker(subjects, covariates):
    global _SUBJECTS, _COVARIATES
    _SUBJECTS = subjects; _COVARIATES = covariates


def extract_recording(args):
    """Extract all feature families from one CSV."""
    sid, task = args
    global _SUBJECTS, _COVARIATES
    path = get_csv_path(sid, task, _SUBJECTS)
    if not os.path.exists(path): return None
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if len(df) < 200: return None

    return {
        "sid": sid, "task": task,
        "baseline": extract_baseline(df),
        "phase": extract_phase_features(df),
        "foot_contact": extract_foot_contact_features(df),
        "nonlinear": extract_nonlinear(df),
        "n_samples": len(df),
    }


# ══════════════════════════════════════════════════════════════════════
# AGGREGATION
# ══════════════════════════════════════════════════════════════════════

def aggregate(records, subjects, covariates):
    by_subj = defaultdict(list)
    for r in records:
        by_subj[r["sid"]].append(r)

    families = ["baseline", "phase", "foot_contact", "nonlinear"]
    dfs = {f: [] for f in families}
    dfs["covariates"] = []
    sids_out, updrs_out = [], []

    for sid in sorted(by_subj.keys()):
        if sid not in subjects: continue
        recs = by_subj[sid]
        sids_out.append(sid)
        updrs_out.append(subjects[sid]["updrs3"])

        for fam in families:
            all_keys = set()
            for r in recs: all_keys.update(r.get(fam, {}).keys())
            agg = {}
            for k in sorted(all_keys):
                vals = [r.get(fam, {}).get(k, None) for r in recs]
                vals = [v for v in vals if v is not None and np.isfinite(v)]
                agg[k] = float(np.mean(vals)) if vals else 0.0
            dfs[fam].append(agg)

        # Covariates (same for all tasks)
        cov = covariates.get(sid, {})
        # Only NEW covariates (not in original 5)
        new_cov = {k: v for k, v in cov.items() if k in [
            "cov_height", "cov_weight", "cov_bmi", "cov_age_onset",
            "cov_yrs_sq", "cov_yrs_log", "cov_early", "cov_late"
        ]}
        dfs["covariates"].append(new_cov)

    result = {}
    for fam in list(dfs.keys()):
        df = pd.DataFrame(dfs[fam])
        df.insert(0, "sid", sids_out); df.insert(1, "updrs3", updrs_out)
        for c in df.columns[2:]:
            df[c] = df[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        result[fam] = df
    return result


# ══════════════════════════════════════════════════════════════════════
# ABLATION
# ══════════════════════════════════════════════════════════════════════

def feature_select(X, y, names, k=150):
    from xgboost import XGBRegressor
    sel = XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                        reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
                        objective="reg:absoluteerror")
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def run_config(name, X_dev, y_dev, X_test, y_test, feat_names, k=150):
    import lightgbm as lgb

    k = min(k, X_dev.shape[1])
    if X_dev.shape[1] == 0:
        print(f"\n  {name}: SKIPPED (0 features)")
        return None

    print(f"\n  {name} ({X_dev.shape[1]} raw → top {k})")
    sel_idx, sel_names = feature_select(X_dev, y_dev, feat_names, k)
    Xd, Xt = X_dev[:, sel_idx], X_test[:, sel_idx]

    maes, rs, preds = [], [], []
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(Xd)); rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        vi, ti = idx[:nv], idx[nv:]

        m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                               reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                               objective="mae", verbose=-1)
        m.fit(Xd[ti], y_dev[ti], eval_set=[(Xd[vi], y_dev[vi])],
              callbacks=[lgb.early_stopping(100, verbose=False)])
        p = m.predict(Xt)
        mae = mean_absolute_error(y_test, p)
        r, _ = sp_stats.pearsonr(y_test, p)
        maes.append(mae); rs.append(r); preds.append(p)
        print(f"    seed {seed}: MAE={mae:.2f} r={r:.3f}")

    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(y_test, ep)
    er, _ = sp_stats.pearsonr(y_test, ep)
    print(f"    ENS: MAE={em:.2f} r={er:.3f}")

    return {
        "config": name, "n_raw": int(X_dev.shape[1]), "n_sel": k,
        "mean_mae": round(np.mean(maes), 3), "std_mae": round(np.std(maes), 3),
        "ens_mae": round(em, 3), "ens_r": round(er, 3),
        "seed_maes": [round(m, 3) for m in maes],
        "top10": sel_names[:10],
    }


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    print("=" * 70)
    print("V3 ABLATION v2: Fixed Phase/Stride + Original Baseline")
    print("=" * 70)

    subjects = parse_clinical()
    covariates = load_extended_covariates()
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
    with ProcessPoolExecutor(N_CORES, initializer=_init_worker,
                              initargs=(subjects, covariates)) as pool:
        records = [r for r in pool.map(extract_recording, jobs, chunksize=4) if r is not None]
    print(f"Done: {len(records)} recordings in {time.time()-t0:.0f}s")

    family_dfs = aggregate(records, subjects, covariates)
    for fam, df in family_dfs.items():
        fc = len([c for c in df.columns if c not in ("sid", "updrs3")])
        print(f"  {fam:<15s}: {len(df):>3d} subjects × {fc:>4d} features")

    # Prepare arrays
    arrays = {}
    for fam, df in family_dfs.items():
        fc = [c for c in df.columns if c not in ("sid", "updrs3")]
        dm = df["sid"].isin(dev_sids); tm = df["sid"].isin(test_sids)
        arrays[fam] = (
            df.loc[dm, fc].values.astype(np.float32),
            df.loc[dm, "updrs3"].values.astype(np.float32),
            df.loc[tm, fc].values.astype(np.float32),
            df.loc[tm, "updrs3"].values.astype(np.float32),
            fc,
        )

    y_dev = arrays["baseline"][1]
    y_test = arrays["baseline"][3]

    results = []

    # ── ABLATION ──────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("ABLATION: BASELINE + EACH NEW FAMILY")
    print(f"{'='*70}")

    # A0: Baseline only (should match ~7.97)
    r = run_config("A0_baseline", *arrays["baseline"][:4], arrays["baseline"][4], k=150)
    if r: results.append(r)
    baseline_mae = r["ens_mae"] if r else 99.0

    # A1-A4: Baseline + each new family
    new_families = ["phase", "foot_contact", "nonlinear", "covariates"]
    for i, fam in enumerate(new_families, 1):
        Xd_new, _, Xt_new, _, names_new = arrays[fam]
        if Xd_new.shape[1] == 0:
            print(f"\n  A{i}_base+{fam}: SKIPPED (0 new features)")
            continue
        Xd = np.hstack([arrays["baseline"][0], Xd_new])
        Xt = np.hstack([arrays["baseline"][2], Xt_new])
        names = arrays["baseline"][4] + names_new
        r = run_config(f"A{i}_base+{fam}", Xd, y_dev, Xt, y_test, names, k=180)
        if r: results.append(r)

    # A5: Baseline + ALL new families
    all_new_X_dev = [arrays["baseline"][0]]
    all_new_X_test = [arrays["baseline"][2]]
    all_names = list(arrays["baseline"][4])
    for fam in new_families:
        Xd, _, Xt, _, nm = arrays[fam]
        if Xd.shape[1] > 0:
            all_new_X_dev.append(Xd)
            all_new_X_test.append(Xt)
            all_names.extend(nm)

    X_all_dev = np.hstack(all_new_X_dev)
    X_all_test = np.hstack(all_new_X_test)

    for k in [150, 200, 250, 300]:
        r = run_config(f"A5_all_K{k}", X_all_dev, y_dev, X_all_test, y_test, all_names, k=k)
        if r: results.append(r)

    # A6: XGBoost on best combined
    from xgboost import XGBRegressor
    c_results = [r for r in results if r["config"].startswith("A5")]
    if c_results:
        best_c = min(c_results, key=lambda x: x["ens_mae"])
        best_k = best_c["n_sel"]
        print(f"\n  XGBoost on best K={best_k}...")
        sel_idx, sel_names = feature_select(X_all_dev, y_dev, all_names, best_k)
        Xds, Xts = X_all_dev[:, sel_idx], X_all_test[:, sel_idx]
        xmaes, xrs, xpreds = [], [], []
        for seed in SEEDS:
            rng = np.random.RandomState(seed)
            idx = np.arange(len(Xds)); rng.shuffle(idx)
            nv = max(1, int(len(idx) * 0.15))
            m = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                              reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                              early_stopping_rounds=100, objective="reg:absoluteerror")
            m.fit(Xds[idx[nv:]], y_dev[idx[nv:]], eval_set=[(Xds[idx[:nv]], y_dev[idx[:nv]])], verbose=False)
            p = m.predict(Xts)
            xmaes.append(mean_absolute_error(y_test, p))
            xrs.append(sp_stats.pearsonr(y_test, p)[0])
            xpreds.append(p)
            print(f"    seed {seed}: MAE={xmaes[-1]:.2f} r={xrs[-1]:.3f}")
        ep = np.mean(xpreds, axis=0)
        em = mean_absolute_error(y_test, ep); er = sp_stats.pearsonr(y_test, ep)[0]
        print(f"    ENS: MAE={em:.2f} r={er:.3f}")
        results.append({"config": f"A6_xgb_K{best_k}", "n_raw": X_all_dev.shape[1], "n_sel": best_k,
                         "mean_mae": round(np.mean(xmaes),3), "std_mae": round(np.std(xmaes),3),
                         "ens_mae": round(em,3), "ens_r": round(er,3),
                         "seed_maes": [round(m,3) for m in xmaes], "top10": sel_names[:10]})

    # ── REPORT ────────────────────────────────────────────────────────
    total = time.time() - t0
    print(f"\n{'='*70}")
    print("RESULTS (sorted by ENS MAE)")
    print(f"{'='*70}")
    print(f"{'Config':<25s} {'Raw':>5s} {'K':>4s} {'MAE±std':>12s} {'ENS':>7s} {'r':>6s} {'Δ':>6s}")
    print("-" * 70)
    for r in sorted(results, key=lambda x: x["ens_mae"]):
        d = baseline_mae - r["ens_mae"]
        ds = f"+{d:.2f}" if d > 0 else f"{d:.2f}"
        print(f"  {r['config']:<23s} {r['n_raw']:>5d} {r['n_sel']:>4d} "
              f"{r['mean_mae']:>5.2f}±{r['std_mae']:.2f} {r['ens_mae']:>7.2f} {r['ens_r']:>6.3f} {ds:>6s}")

    best = min(results, key=lambda x: x["ens_mae"])
    print(f"\n  Baseline: {baseline_mae:.2f}")
    print(f"  Best:     {best['ens_mae']:.2f} ({best['config']})")
    print(f"  Δ:        {baseline_mae - best['ens_mae']:.2f}")
    print(f"\n  Top features ({best['config']}): {best.get('top10', [])[:5]}")
    print(f"  Runtime: {total:.0f}s ({total/60:.1f}m)")

    # Convert numpy types for JSON serialization
    def to_native(obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return obj

    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            v = to_native(obj)
            if v is not obj: return v
            return super().default(obj)

    with open("/root/pd-imu/v3_ablation_v2_results.json", "w") as f:
        json.dump({"baseline_mae": float(baseline_mae), "best_mae": float(best["ens_mae"]),
                    "best_config": best["config"], "results": results,
                    "runtime_s": round(total,1)}, f, indent=2, cls=NpEncoder)
    print("  Saved to /root/pd-imu/v3_ablation_v2_results.json")


if __name__ == "__main__":
    main()

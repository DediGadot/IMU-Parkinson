#!/usr/bin/env python3
"""run_pd_only_experiments.py — PD-only prediction power experiments.

Phase 1: PD-only 10-split (B1: PD-train, B2: HC-augmented, demographic baseline)
Phase 2: FM LOOCV enhanced stats + demographic baseline
Phase 3: 3-level observability decomposition (direct/partial/unobservable)
Phase 4: Severity-stratified error + confound analysis
Phase 5: Locked held-out test (paper3_split.json)
Phase 6: Sensor ablation with FM re-extraction per config
Phase 7: Consolidated report + Holm-Bonferroni correction

Usage:
    python3 -u run_pd_only_experiments.py --phase 1
    python3 -u run_pd_only_experiments.py --phase 2
    python3 -u run_pd_only_experiments.py --phase all
"""
import argparse, os, sys, json, time, warnings
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold, StratifiedShuffleSplit
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
warnings.filterwarnings("ignore")

# ── Auto-install ─────────────────────────────────────────────────────
def _ensure_deps():
    missing = []
    for pkg, imp in [("aeon","aeon"),("lightgbm","lightgbm"),("xgboost","xgboost")]:
        try: __import__(imp)
        except ImportError: missing.append(pkg)
    if missing:
        import subprocess
        print(f"Installing: {' '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q"] + missing)
_ensure_deps()

import lightgbm as lgb
from xgboost import XGBRegressor

from project_paths import REPO_ROOT, RESULTS_DIR, ensure_dir, save_json_artifact, results_artifact_path, load_json_artifact
sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, DATA_DIR, SENSORS, FS, _updrs_bin, _get_valid_sids
from updrs_columns import find_updrs_value

# ── Constants ────────────────────────────────────────────────────────
ACC_COLS = ["Acc_X", "Acc_Y", "Acc_Z"]
GYR_COLS = ["Gyr_X", "Gyr_Y", "Gyr_Z"]
TASKS = ["SelfPace", "HurriedPace", "TUG", "TandemGait", "Balance"]
ALL_TASKS = TASKS + [f"{t}_mat" for t in TASKS] + [f"{t}_matTURN" for t in ["SelfPace", "HurriedPace"]]
SEQ_LEN = 1000   # 10s at 100Hz
N_CORES = min(os.cpu_count() or 4, 11)
SEEDS = [42, 123, 456, 789, 2024]

FM_MODEL = "AutonLab/MOMENT-1-base"
FM_SEQ_LEN = 512
FM_BATCH_SIZE = 32

RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))
V2_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
FM_CACHE = str(results_artifact_path("fm_embeddings.npz"))

SUBITEMS_MAP = {
    1: None, 2: None,
    3: ["a", "b", "c", "d", "e"],
    4: ["a", "b"], 5: ["a", "b"], 6: ["a", "b"],
    7: ["a", "b"], 8: ["a", "b"],
    9: None, 10: None, 11: None, 12: None, 13: None, 14: None,
    15: ["a", "b"], 16: ["a", "b"],
    17: ["a", "b", "c", "d", "e"],
    18: None,
}

# 3-level observability taxonomy
DIRECT_ITEMS = {9, 10, 11, 12, 13, 14}    # max 24
PARTIAL_ITEMS = {5, 6, 7, 8, 15, 16, 17}  # max 68
UNOBS_ITEMS = {1, 2, 3, 4, 18}            # max 40
OBSERVABLE_ITEMS = [7, 8, 9, 10, 11, 12, 13, 14]  # binary split backward compat

# Sensor ablation configs
SENSOR_CONFIGS = {
    "all_13": SENSORS,
    "wrists_2": ["R_Wrist", "L_Wrist"],
    "lower_back_1": ["LowerBack"],
    "wrists_back_3": ["R_Wrist", "L_Wrist", "LowerBack"],
    "minimal_5": ["LowerBack", "R_Wrist", "L_Wrist", "R_Ankle", "L_Ankle"],
}

ensure_dir(RESULTS_DIR)


# ═══════════════════════════════════════════════════════════════════════
# STATISTICAL UTILITIES
# ═══════════════════════════════════════════════════════════════════════

def lins_ccc(y_true, y_pred):
    """Lin's concordance correlation coefficient."""
    y_true, y_pred = np.asarray(y_true, dtype=np.float64), np.asarray(y_pred, dtype=np.float64)
    mu_t, mu_p = np.mean(y_true), np.mean(y_pred)
    var_t, var_p = np.var(y_true), np.var(y_pred)
    cov = np.mean((y_true - mu_t) * (y_pred - mu_p))
    denom = var_t + var_p + (mu_t - mu_p)**2
    if denom < 1e-12:
        return 0.0
    return float(2 * cov / denom)


def calibration_slope_intercept(y_true, y_pred):
    """Calibration: regress predicted on true. Ideal: slope=1, intercept=0."""
    if len(y_true) < 3:
        return 1.0, 0.0
    slope, intercept, _, _, _ = sp_stats.linregress(y_true, y_pred)
    return float(slope), float(intercept)


def subject_paired_bootstrap(errors_a, errors_b, n_boot=10000, seed=42):
    """Subject-level paired bootstrap for MAE difference.
    Returns: mean_diff, ci_lo, ci_hi, p_value (two-sided)."""
    errors_a, errors_b = np.asarray(errors_a), np.asarray(errors_b)
    rng = np.random.RandomState(seed)
    n = len(errors_a)
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.choice(n, n, replace=True)
        diffs[b] = np.mean(errors_a[idx]) - np.mean(errors_b[idx])
    mean_diff = float(np.mean(diffs))
    ci_lo, ci_hi = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
    if mean_diff < 0:
        p_val = float(np.mean(diffs >= 0))
    else:
        p_val = float(np.mean(diffs <= 0))
    p_val = min(2 * p_val, 1.0)
    return mean_diff, ci_lo, ci_hi, p_val


def cohens_d(errors_a, errors_b):
    """Cohen's d effect size for paired samples."""
    diff = np.asarray(errors_a) - np.asarray(errors_b)
    return float(np.mean(diff) / (np.std(diff, ddof=1) + 1e-12))


def compute_full_metrics(y_true, y_pred):
    """Compute MAE, RMSE, R2, CCC, Pearson r, Spearman rho, MAE/SD, NRMSE, calibration."""
    y_true, y_pred = np.asarray(y_true, dtype=np.float64), np.asarray(y_pred, dtype=np.float64)
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(np.mean((y_true - y_pred)**2)))
    r2 = float(r2_score(y_true, y_pred)) if len(y_true) > 2 else 0.0
    ccc = lins_ccc(y_true, y_pred)
    r_val = float(sp_stats.pearsonr(y_true, y_pred)[0]) if len(y_true) > 2 else 0.0
    rho, rho_p = sp_stats.spearmanr(y_true, y_pred) if len(y_true) > 2 else (0.0, 1.0)
    sd_y = float(np.std(y_true))
    mae_sd = mae / sd_y if sd_y > 1e-8 else float('inf')
    y_range = float(np.max(y_true) - np.min(y_true))
    nrmse = rmse / y_range if y_range > 1e-8 else float('inf')
    cal_slope, cal_intercept = calibration_slope_intercept(y_true, y_pred)
    return {
        "mae": round(mae, 3), "rmse": round(rmse, 3), "r2": round(r2, 3),
        "ccc": round(ccc, 3), "r": round(r_val, 3),
        "spearman_rho": round(float(rho), 3), "spearman_p": round(float(rho_p), 4),
        "mae_sd": round(mae_sd, 3), "nrmse": round(nrmse, 3),
        "cal_slope": round(cal_slope, 3), "cal_intercept": round(cal_intercept, 3),
    }


def holm_bonferroni(p_values):
    """Holm-Bonferroni correction. Input: list of (label, p). Output: list of (label, p_raw, p_adj)."""
    n = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1][1])
    adjusted = [None] * n
    max_p = 0.0
    for rank, (orig_idx, (label, p_raw)) in enumerate(indexed):
        p_adj = min(p_raw * (n - rank), 1.0)
        p_adj = max(p_adj, max_p)
        max_p = p_adj
        adjusted[orig_idx] = (label, round(p_raw, 6), round(p_adj, 6))
    return adjusted


# ═══════════════════════════════════════════════════════════════════════
# DATA LOADING (reuse patterns from run_rocket_ablation.py)
# ═══════════════════════════════════════════════════════════════════════

def _get_csv_path(sid, task, subjects):
    grp = subjects[sid]["group"]
    base = "PD PARTICIPANTS" if grp == "PD" else "CONTROL PARTICIPANTS"
    return os.path.join(DATA_DIR, base, "CSV files", f"{sid}_{task}.csv")


def _load_one_recording(args):
    """Load a single recording as acc+gyro magnitude per sensor.
    Returns: (26, SEQ_LEN) array with 13 acc_mag + 13 gyr_mag channels.
    """
    csv_path, sid, task = args
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None

    channels = []
    for sen in SENSORS:
        ac = [f"{sen}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in ac):
            vals = np.nan_to_num(df[ac].values.astype(np.float32))
            channels.append(np.sqrt(np.sum(vals**2, axis=1)))
        else:
            channels.append(np.zeros(len(df), dtype=np.float32))
        gc = [f"{sen}_{c}" for c in GYR_COLS]
        if all(c in df.columns for c in gc):
            vals = np.nan_to_num(df[gc].values.astype(np.float32))
            channels.append(np.sqrt(np.sum(vals**2, axis=1)))
        else:
            channels.append(np.zeros(len(df), dtype=np.float32))

    data = np.column_stack(channels)  # (T, 26)
    T = len(data)
    if T > SEQ_LEN:
        data = data[:SEQ_LEN]
    elif T < SEQ_LEN:
        pad = np.zeros((SEQ_LEN - T, data.shape[1]), dtype=np.float32)
        data = np.vstack([data, pad])
    return {"sid": sid, "task": task, "data": data.T}  # (26, SEQ_LEN)


def load_all_recordings(subjects, all_sids):
    """Load raw recordings into 3D array. Cached."""
    if os.path.exists(RECORDING_CACHE):
        print(f"[cache] Loading recordings from {RECORDING_CACHE}")
        data = np.load(RECORDING_CACHE)
        rec_array = data["recordings"]
        rec_sids = data["sids"].tolist()
        rec_tasks = data["tasks"].tolist()
        print(f"  {len(rec_sids)} recordings")
        return rec_array, rec_sids, rec_tasks

    jobs = []
    for task in ALL_TASKS:
        for sid in all_sids:
            if sid not in subjects:
                continue
            p = _get_csv_path(sid, task, subjects)
            if os.path.exists(p):
                jobs.append((p, sid, task))
    print(f"Loading {len(jobs)} recordings with {N_CORES} cores...")
    t0 = time.time()

    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        rec_results = list(pool.map(_load_one_recording, jobs, chunksize=8))
    valid_recs = [r for r in rec_results if r is not None]
    rec_array = np.stack([r["data"] for r in valid_recs])
    rec_sids = [r["sid"] for r in valid_recs]
    rec_tasks = [r["task"] for r in valid_recs]
    print(f"  Recordings: {rec_array.shape} in {time.time()-t0:.0f}s")

    np.savez_compressed(RECORDING_CACHE,
                        recordings=rec_array,
                        sids=np.array(rec_sids),
                        tasks=np.array(rec_tasks))
    print(f"  Cached to {RECORDING_CACHE}")
    return rec_array, rec_sids, rec_tasks


# ═══════════════════════════════════════════════════════════════════════
# FM EXTRACTION
# ═══════════════════════════════════════════════════════════════════════

def extract_fm_embeddings(rec_array, cache_path=None):
    """Extract frozen MOMENT-1-base embeddings for all recordings.
    Input: rec_array shape (N, C, T) — raw IMU recordings (C channels)
    Output: (N, d_model) embedding matrix — 768 for MOMENT-1-base
    """
    if cache_path is None:
        cache_path = FM_CACHE
    if os.path.exists(cache_path):
        print(f"[cache] Loading FM embeddings from {cache_path}")
        data = np.load(cache_path)
        return data["embeddings"]

    try:
        import torch
    except ImportError:
        raise RuntimeError("PyTorch required for FM extraction")
    try:
        from momentfm import MOMENTPipeline
    except ImportError:
        import subprocess
        print("Installing momentfm...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "momentfm"])
        from momentfm import MOMENTPipeline

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading {FM_MODEL} on {device}...")
    t0 = time.time()

    model = MOMENTPipeline.from_pretrained(
        FM_MODEL,
        model_kwargs={"task_name": "embedding"}
    )
    model.init()
    model = model.to(device)
    model.eval()
    print(f"  Model loaded in {time.time()-t0:.1f}s")

    trunc_len = min(FM_SEQ_LEN, rec_array.shape[2])
    data = rec_array[:, :, :trunc_len].copy().astype(np.float32)

    # Per-channel z-normalize
    for ch in range(data.shape[1]):
        ch_data = data[:, ch, :].ravel()
        mu = float(np.mean(ch_data))
        std = float(np.std(ch_data)) + 1e-8
        data[:, ch, :] = (data[:, ch, :] - mu) / std

    # Pad to FM_SEQ_LEN if needed
    if trunc_len < FM_SEQ_LEN:
        pad_width = FM_SEQ_LEN - trunc_len
        data = np.pad(data, ((0, 0), (0, 0), (0, pad_width)), mode='constant', constant_values=0)

    print(f"  Input: {data.shape} (truncated to {trunc_len}, z-normalized)")

    embeddings = []
    n = len(data)
    t1 = time.time()

    with torch.no_grad():
        for i in range(0, n, FM_BATCH_SIZE):
            batch = data[i:i+FM_BATCH_SIZE]
            x = torch.from_numpy(batch).float().to(device)

            raw_batch = rec_array[i:i+FM_BATCH_SIZE, :, :trunc_len]
            mask_arr = (np.abs(raw_batch).sum(axis=1) > 1e-6).astype(np.float32)
            if trunc_len < FM_SEQ_LEN:
                mask_arr = np.pad(mask_arr, ((0, 0), (0, FM_SEQ_LEN - trunc_len)),
                                  mode='constant', constant_values=0)
            mask_t = torch.from_numpy(mask_arr).to(device)

            output = model(x_enc=x, input_mask=mask_t)
            emb = output.embeddings
            if emb.dim() == 3:
                emb = emb.mean(dim=1)
            embeddings.append(emb.cpu().numpy())

            done = min(i + FM_BATCH_SIZE, n)
            if done % (FM_BATCH_SIZE * 10) == 0 or done == n:
                elapsed = time.time() - t1
                rate = done / max(elapsed, 0.1)
                eta = (n - done) / max(rate, 0.1) / 60
                print(f"  FM: {done}/{n} ({elapsed:.0f}s, {rate:.1f} rec/s, ETA={eta:.1f}m)")

    embeddings = np.vstack(embeddings)
    embeddings = np.nan_to_num(embeddings, nan=0.0, posinf=0.0, neginf=0.0)

    np.savez_compressed(cache_path, embeddings=embeddings)
    print(f"  FM embeddings: {embeddings.shape}, cached to {cache_path}")
    print(f"  Extraction time: {(time.time()-t0)/60:.1f}m")
    return embeddings


def fm_features_for_subjects(embeddings, rec_sids):
    """Aggregate FM embeddings per subject (mean across recordings)."""
    d_model = embeddings.shape[1]
    fm_df = pd.DataFrame(embeddings, columns=[f"fm_{i}" for i in range(d_model)])
    fm_df["sid"] = rec_sids
    agg = fm_df.groupby("sid").mean().reset_index()
    return agg


# ═══════════════════════════════════════════════════════════════════════
# TRAINING / EVALUATION MACHINERY (from run_rocket_ablation.py)
# ═══════════════════════════════════════════════════════════════════════

def get_v2_cols(v2_df):
    """Standard v2 feature column filter."""
    return [c for c in v2_df.columns if c not in ("sid", "updrs3")
            and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_", "obs_subscore"))
            and c != "hy"]


def feature_select(X, y, names, k=150):
    k = min(k, X.shape[1])
    sel = XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                       reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
                       objective="reg:absoluteerror")
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def train_lgb(Xd, yd, Xt, seed=42):
    rng = np.random.RandomState(seed); idx = np.arange(len(Xd)); rng.shuffle(idx)
    nv = max(1, int(len(idx)*0.15))
    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                           reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                           objective="mae", verbose=-1, device="gpu")
    m.fit(Xd[idx[nv:]], yd[idx[nv:]], eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
          callbacks=[lgb.early_stopping(100, verbose=False)])
    return m.predict(Xt), m


def train_xgb(Xd, yd, Xt, seed=42):
    rng = np.random.RandomState(seed); idx = np.arange(len(Xd)); rng.shuffle(idx)
    nv = max(1, int(len(idx)*0.15))
    m = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6, reg_lambda=3.0,
                     random_state=seed, n_jobs=N_CORES, early_stopping_rounds=100,
                     objective="reg:absoluteerror", device="cuda")
    m.fit(Xd[idx[nv:]], yd[idx[nv:]], eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])], verbose=False)
    return m.predict(Xt), m


def prep_arrays(df, dev_sids, test_sids, cols, target_col="updrs3"):
    dm = df["sid"].isin(dev_sids); tm = df["sid"].isin(test_sids)
    Xd = df.loc[dm, cols].values.astype(np.float32)
    yd = df.loc[dm, target_col].values.astype(np.float32)
    Xt = df.loc[tm, cols].values.astype(np.float32)
    yt = df.loc[tm, target_col].values.astype(np.float32)
    return Xd, yd, Xt, yt


def run_lgb_ensemble(Xd, yd, Xt, clip_max=132):
    """5-seed LGB ensemble prediction."""
    preds = []
    for seed in SEEDS:
        p, _ = train_lgb(Xd, yd, Xt, seed)
        preds.append(np.clip(p, 0, clip_max))
    return np.mean(preds, axis=0)


def run_stack(Xd, yd, Xt, clip_max=132):
    """5-seed LGB+XGB stacking with Ridge meta-learner."""
    preds = []
    for seed in SEEDS:
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        oof_lgb = np.zeros(len(Xd))
        oof_xgb = np.zeros(len(Xd))
        tp_lgb = np.zeros(len(Xt))
        tp_xgb = np.zeros(len(Xt))
        for tr_i, val_i in kf.split(Xd):
            rng = np.random.RandomState(seed + len(tr_i))
            shuf = tr_i.copy(); rng.shuffle(shuf)
            nv = max(1, int(len(shuf)*0.15))
            Xtr, ytr = Xd[shuf[nv:]], yd[shuf[nv:]]
            Xval, yval = Xd[shuf[:nv]], yd[shuf[:nv]]
            m1 = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                                    reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                                    objective="mae", verbose=-1, device="gpu")
            m1.fit(Xtr, ytr, eval_set=[(Xval, yval)], callbacks=[lgb.early_stopping(100, verbose=False)])
            oof_lgb[val_i] = m1.predict(Xd[val_i])
            tp_lgb += m1.predict(Xt) / 5
            m2 = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6, reg_lambda=3.0,
                               random_state=seed, n_jobs=N_CORES, early_stopping_rounds=100,
                               objective="reg:absoluteerror", device="cuda")
            m2.fit(Xtr, ytr, eval_set=[(Xval, yval)], verbose=False)
            oof_xgb[val_i] = m2.predict(Xd[val_i])
            tp_xgb += m2.predict(Xt) / 5
        L0tr = np.column_stack([oof_lgb, oof_xgb])
        L0te = np.column_stack([tp_lgb, tp_xgb])
        meta = Ridge(alpha=1.0); meta.fit(L0tr, yd)
        preds.append(np.clip(meta.predict(L0te), 0, clip_max))
    return np.mean(preds, axis=0)


# ═══════════════════════════════════════════════════════════════════════
# CLINICAL DATA HELPERS
# ═══════════════════════════════════════════════════════════════════════

def parse_item_scores():
    """Parse per-item UPDRS-III scores from clinical CSVs."""
    item_scores = {}
    for fn, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Clinical CSV not found: {path}")
        df = pd.read_csv(path, header=1)
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            scores = {}
            for item_num in range(1, 19):
                sub = SUBITEMS_MAP[item_num]
                if sub is None:
                    val = find_updrs_value(row, df.columns, item_num)
                    if val is not None:
                        scores[item_num] = val
                    elif group == "HC":
                        scores[item_num] = 0.0
                else:
                    vals = []
                    for s in sub:
                        v = find_updrs_value(row, df.columns, item_num, s)
                        if v is not None:
                            vals.append(v)
                    if len(vals) == len(sub):
                        scores[item_num] = float(sum(vals))
                    elif len(vals) == 0 and group == "HC":
                        scores[item_num] = 0.0
            if scores:
                item_scores[sid] = scores
    return item_scores


def compute_subscore(item_scores_dict, sid, item_set):
    """Sum of items in item_set for a subject. Returns None if any item missing."""
    if sid not in item_scores_dict:
        return None
    total = 0.0
    for item in item_set:
        if item not in item_scores_dict[sid]:
            return None
        total += item_scores_dict[sid][item]
    return total


def extract_demographics_for_sids(target_sids=None):
    """Extract demographic covariates for all subjects with clinical data.
    Returns dict sid -> {age, sex, years_dx, height_cm, weight_kg, hy, group, updrs3}.
    """
    demos = {}
    for filename, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Clinical CSV not found: {path}")
        df = pd.read_csv(path, header=1)
        u3cols = [c for c in df.columns if c.startswith("MDSUPDRS_3-")]
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if not sid or sid == "nan":
                continue
            if target_sids is not None and sid not in target_sids:
                continue

            updrs3 = pd.to_numeric(row[u3cols], errors="coerce").sum()
            if np.isnan(updrs3):
                continue

            age = pd.to_numeric(row.get("Age (years)", row.get("Age", np.nan)), errors="coerce")
            sex_raw = str(row.get("Sex", row.get("Gender", ""))).strip().upper()
            sex = 1 if sex_raw.startswith("M") else 0
            yrs = pd.to_numeric(row.get("Years since PD diagnosis",
                                        row.get("Years Since Diagnosis", np.nan)), errors="coerce")
            height_in = pd.to_numeric(row.get("Height (in)", row.get("Height (cm)", np.nan)), errors="coerce")
            height_cm = float(height_in * 2.54) if pd.notna(height_in) and height_in > 50 else (
                float(height_in) if pd.notna(height_in) else None)
            weight = pd.to_numeric(row.get("Weight (kg)", row.get("Weight", np.nan)), errors="coerce")
            hy = pd.to_numeric(
                row.get("Modified Hoehn & Yahr Score",
                         row.get("H&Y", row.get("Hoehn & Yahr", np.nan))),
                errors="coerce"
            )

            demos[sid] = {
                "age": float(age) if pd.notna(age) else None,
                "sex": sex,
                "years_dx": float(yrs) if pd.notna(yrs) else None,
                "height_cm": height_cm,
                "weight_kg": float(weight) if pd.notna(weight) else None,
                "hy": float(hy) if pd.notna(hy) else None,
                "group": group,
                "updrs3": float(updrs3),
            }
    return demos


def build_demo_matrix(sids, demos):
    """Build demographic feature matrix [age, sex, years_dx, height_cm, weight_kg].
    NaN-imputed with median. Returns X array and feature names."""
    feat_names = ["age", "sex", "years_dx", "height_cm", "weight_kg"]
    rows = []
    for sid in sids:
        d = demos.get(sid, {})
        rows.append([d.get(f) for f in feat_names])
    X = np.array(rows, dtype=np.float64)
    # Median imputation per column
    for j in range(X.shape[1]):
        col = X[:, j]
        mask = np.isnan(col)
        if mask.all():
            X[:, j] = 0.0
        elif mask.any():
            X[mask, j] = np.nanmedian(col)
    return X.astype(np.float32), feat_names


def gen_pd_split(pd_sids, subjects, demos, seed):
    """StratifiedShuffleSplit on PD subjects using UPDRS bins x age terciles."""
    sids = np.array(pd_sids)
    scores = np.array([subjects[s]["updrs3"] for s in sids])
    ages = np.array([demos.get(s, {}).get("age", 65.0) or 65.0 for s in sids])

    # UPDRS bins
    updrs_bins = np.array([_updrs_bin(s) for s in scores])
    # Age terciles
    age_t = np.digitize(ages, np.percentile(ages[~np.isnan(ages)], [33.3, 66.7]))
    # Joint label for multi-label stratification
    joint = updrs_bins * 10 + age_t
    # Collapse rare bins (< 2 samples)
    counts = pd.Series(joint).value_counts()
    rare = set(counts[counts < 2].index)
    if rare:
        joint = np.array([j if j not in rare else -1 for j in joint])

    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    di, ti = next(sss.split(sids, joint))
    return sids[di].tolist(), sids[ti].tolist()


def filter_features_for_sensors(all_cols, sensor_set):
    """Return columns available if only sensor_set sensors are worn."""
    sensor_set = set(sensor_set)
    keep = []
    for col in all_cols:
        matched_sensor = None
        for s in SENSORS:
            if col.startswith(s + "_"):
                matched_sensor = s
                break
        if matched_sensor is not None:
            if matched_sensor in sensor_set:
                keep.append(col)
            continue
        if col.startswith("asy_"):
            parts = col.split("_")
            if len(parts) >= 2:
                pair_name = parts[1]
                if f"R_{pair_name}" in sensor_set and f"L_{pair_name}" in sensor_set:
                    keep.append(col)
            continue
        if col.startswith(("ev_", "trn_", "sts_", "bal_")):
            if "LowerBack" in sensor_set:
                keep.append(col)
            continue
        if col.startswith("fc_"):
            foot_sensors = {"R_DorsalFoot", "L_DorsalFoot", "R_Ankle", "L_Ankle"}
            if sensor_set & foot_sensors:
                keep.append(col)
            continue
        if col.startswith("k_"):
            side = col[2] if len(col) > 2 else ""
            ankle = f"{side}_Ankle"
            shank = f"{side}_LatShank"
            if ankle in sensor_set or shank in sensor_set:
                keep.append(col)
            continue
        if col.startswith(("dv_", "d_", "r_")):
            found = any(s in col for s in sensor_set)
            if found or not any(s in col for s in SENSORS):
                keep.append(col)
            continue
        if col.startswith(("cv_", "ext_", "n_")) or col in ("duration_s",):
            keep.append(col)
            continue
        if col.startswith("dst_"):
            continue
        keep.append(col)
    return keep


# ═══════════════════════════════════════════════════════════════════════
# PHASE 1: PD-ONLY 10-SPLIT
# ═══════════════════════════════════════════════════════════════════════

def phase1(v2_df, fm_agg, fm_cols, subjects, all_sids):
    """PD-only 10-split: B1 (PD-train), B2 (HC-augmented), demographic baseline."""
    print("\n" + "="*70)
    print("PHASE 1: PD-only 10-split (B1 + B2 + demographic baseline)")
    print("="*70)
    t0 = time.time()

    pd_sids = [s for s in all_sids if subjects[s]["group"] == "PD"]
    hc_sids = [s for s in all_sids if subjects[s]["group"] == "HC"]
    print(f"PD subjects: {len(pd_sids)}, HC subjects: {len(hc_sids)}")

    demos = extract_demographics_for_sids(set(all_sids))
    v2_cols = get_v2_cols(v2_df)

    # Merge v2 + FM once
    merged = v2_df[["sid", "updrs3"] + v2_cols].merge(fm_agg, on="sid", how="left").fillna(0.0)
    all_feat_cols = v2_cols + fm_cols

    results = {"phase": "1_pd_only_10split", "splits": [],
               "n_pd": len(pd_sids), "n_hc": len(hc_sids)}

    for si, seed in enumerate(range(1, 11)):
        print(f"\n--- Split {si+1}/10 (seed={seed}) ---")
        dev_pd, test_pd = gen_pd_split(pd_sids, subjects, demos, seed)
        print(f"  PD dev: {len(dev_pd)}, PD test: {len(test_pd)}")

        split_result = {"seed": seed, "n_dev_pd": len(dev_pd), "n_test_pd": len(test_pd)}

        # ── Demographic baseline ──────────────────────────────────────
        Xd_demo, _ = build_demo_matrix(dev_pd, demos)
        Xt_demo, _ = build_demo_matrix(test_pd, demos)
        yd_demo = np.array([subjects[s]["updrs3"] for s in dev_pd], dtype=np.float32)
        yt = np.array([subjects[s]["updrs3"] for s in test_pd], dtype=np.float32)
        ridge_demo = Ridge(alpha=1.0)
        ridge_demo.fit(Xd_demo, yd_demo)
        pred_demo = np.clip(ridge_demo.predict(Xt_demo), 0, 132)
        split_result["demographic"] = compute_full_metrics(yt, pred_demo)
        print(f"  Demographic: MAE={split_result['demographic']['mae']}")

        # ── B1: PD-only train ─────────────────────────────────────────
        # v2 only
        Xd_v2, yd, Xt_v2, _ = prep_arrays(merged, dev_pd, test_pd, v2_cols)
        k_v2 = min(150, Xd_v2.shape[1])
        sel_idx_v2, sel_names_v2 = feature_select(Xd_v2, yd, v2_cols, k_v2)
        Xds_v2, Xts_v2 = Xd_v2[:, sel_idx_v2], Xt_v2[:, sel_idx_v2]
        pred_b1_v2 = run_lgb_ensemble(Xds_v2, yd, Xts_v2)
        split_result["b1_v2"] = compute_full_metrics(yt, pred_b1_v2)
        print(f"  B1 v2: MAE={split_result['b1_v2']['mae']}")

        # v2+FM LGB
        Xd_all, _, Xt_all, _ = prep_arrays(merged, dev_pd, test_pd, all_feat_cols)
        k_fm = min(300, Xd_all.shape[1])
        sel_idx_fm, sel_names_fm = feature_select(Xd_all, yd, all_feat_cols, k_fm)
        Xds_fm, Xts_fm = Xd_all[:, sel_idx_fm], Xt_all[:, sel_idx_fm]
        pred_b1_fm_lgb = run_lgb_ensemble(Xds_fm, yd, Xts_fm)
        split_result["b1_fm_lgb"] = compute_full_metrics(yt, pred_b1_fm_lgb)
        print(f"  B1 v2+FM LGB: MAE={split_result['b1_fm_lgb']['mae']}")

        # v2+FM stack
        pred_b1_fm_stk = run_stack(Xds_fm, yd, Xts_fm)
        split_result["b1_fm_stk"] = compute_full_metrics(yt, pred_b1_fm_stk)
        print(f"  B1 v2+FM stack: MAE={split_result['b1_fm_stk']['mae']}")

        # ── B2: HC-augmented train ────────────────────────────────────
        dev_b2 = dev_pd + hc_sids
        Xd_v2_b2, yd_b2, Xt_v2_b2, _ = prep_arrays(merged, dev_b2, test_pd, v2_cols)
        k_v2_b2 = min(150, Xd_v2_b2.shape[1])
        sel_idx_v2_b2, _ = feature_select(Xd_v2_b2, yd_b2, v2_cols, k_v2_b2)
        pred_b2_v2 = run_lgb_ensemble(Xd_v2_b2[:, sel_idx_v2_b2], yd_b2, Xt_v2_b2[:, sel_idx_v2_b2])
        split_result["b2_v2"] = compute_full_metrics(yt, pred_b2_v2)
        print(f"  B2 v2: MAE={split_result['b2_v2']['mae']}")

        Xd_all_b2, _, Xt_all_b2, _ = prep_arrays(merged, dev_b2, test_pd, all_feat_cols)
        k_fm_b2 = min(300, Xd_all_b2.shape[1])
        sel_idx_fm_b2, _ = feature_select(Xd_all_b2, yd_b2, all_feat_cols, k_fm_b2)
        pred_b2_fm_stk = run_stack(Xd_all_b2[:, sel_idx_fm_b2], yd_b2, Xt_all_b2[:, sel_idx_fm_b2])
        split_result["b2_fm_stk"] = compute_full_metrics(yt, pred_b2_fm_stk)
        print(f"  B2 v2+FM stack: MAE={split_result['b2_fm_stk']['mae']}")

        # ── Subject-level paired bootstrap ────────────────────────────
        err_demo = np.abs(yt - pred_demo)
        err_b1_v2 = np.abs(yt - pred_b1_v2)
        err_b1_fm = np.abs(yt - pred_b1_fm_stk)
        err_b2_fm = np.abs(yt - pred_b2_fm_stk)

        _, _, _, p_fm_vs_v2 = subject_paired_bootstrap(err_b1_v2, err_b1_fm)
        _, _, _, p_fm_vs_demo = subject_paired_bootstrap(err_demo, err_b1_fm)
        _, _, _, p_b1_vs_b2 = subject_paired_bootstrap(err_b1_fm, err_b2_fm)

        split_result["bootstrap_fm_vs_v2_p"] = round(p_fm_vs_v2, 4)
        split_result["bootstrap_fm_vs_demo_p"] = round(p_fm_vs_demo, 4)
        split_result["bootstrap_b1_vs_b2_p"] = round(p_b1_vs_b2, 4)
        split_result["cohens_d_fm_vs_v2"] = round(cohens_d(err_b1_v2, err_b1_fm), 3)
        split_result["cohens_d_fm_vs_demo"] = round(cohens_d(err_demo, err_b1_fm), 3)

        # Store raw predictions for later aggregation
        split_result["test_sids"] = test_pd
        split_result["y_true"] = yt.tolist()
        split_result["pred_b1_fm_stk"] = pred_b1_fm_stk.tolist()
        split_result["pred_demo"] = pred_demo.tolist()

        results["splits"].append(split_result)

    # ── Aggregate summaries ───────────────────────────────────────────
    for tag in ["demographic", "b1_v2", "b1_fm_lgb", "b1_fm_stk", "b2_v2", "b2_fm_stk"]:
        maes = [s[tag]["mae"] for s in results["splits"]]
        cccs = [s[tag]["ccc"] for s in results["splits"]]
        results[f"summary_{tag}"] = {
            "mae_mean": round(np.mean(maes), 3), "mae_std": round(np.std(maes), 3),
            "ccc_mean": round(np.mean(cccs), 3), "ccc_std": round(np.std(cccs), 3),
        }
        print(f"\n10-split {tag}: MAE={np.mean(maes):.3f}+/-{np.std(maes):.3f}  "
              f"CCC={np.mean(cccs):.3f}+/-{np.std(cccs):.3f}")

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("pd_only_phase1.json", results)
    print(f"\nPhase 1 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 2: FM LOOCV ENHANCED STATS
# ═══════════════════════════════════════════════════════════════════════

def phase2(subjects, all_sids):
    """Enhanced stats on cached FM LOOCV predictions + demographic baseline."""
    print("\n" + "="*70)
    print("PHASE 2: FM LOOCV Enhanced Statistics + Demographic Baseline")
    print("="*70)
    t0 = time.time()

    # Load cached FM LOOCV predictions
    loocv_data, loocv_path = load_json_artifact("rocket_phase8_fm_loocv.json")
    preds = loocv_data["predictions"]
    print(f"Loaded {len(preds)} FM LOOCV predictions from {loocv_path}")

    sids = [p["sid"] for p in preds]
    y_true = np.array([p["true"] for p in preds], dtype=np.float64)
    y_pred_fm = np.array([p["pred_fm"] for p in preds], dtype=np.float64)

    pd_sids = [s for s in all_sids if subjects[s]["group"] == "PD"]
    demos = extract_demographics_for_sids(set(all_sids))

    results = {"phase": "2_fm_loocv_stats", "n_pd": len(sids)}

    # ── Core metrics ──────────────────────────────────────────────────
    results["fm_metrics"] = compute_full_metrics(y_true, y_pred_fm)
    print(f"FM LOOCV: {results['fm_metrics']}")

    # ── Demographic LOO baseline ──────────────────────────────────────
    print("Running demographic LOO baseline...")
    y_pred_demo = np.zeros_like(y_true)
    for i, loo_sid in enumerate(sids):
        dev_sids_loo = [s for s in pd_sids if s != loo_sid]
        Xd_demo, _ = build_demo_matrix(dev_sids_loo, demos)
        yd_demo = np.array([subjects[s]["updrs3"] for s in dev_sids_loo], dtype=np.float32)
        Xt_demo, _ = build_demo_matrix([loo_sid], demos)
        ridge = Ridge(alpha=1.0)
        ridge.fit(Xd_demo, yd_demo)
        y_pred_demo[i] = np.clip(ridge.predict(Xt_demo)[0], 0, 132)
    results["demo_metrics"] = compute_full_metrics(y_true, y_pred_demo)
    print(f"Demo LOO: {results['demo_metrics']}")

    # ── Paired bootstrap: FM vs demo ──────────────────────────────────
    err_fm = np.abs(y_true - y_pred_fm)
    err_demo = np.abs(y_true - y_pred_demo)
    diff, ci_lo, ci_hi, p_val = subject_paired_bootstrap(err_demo, err_fm)
    results["bootstrap_fm_vs_demo"] = {
        "mean_diff": round(diff, 3), "ci_lo": round(ci_lo, 3),
        "ci_hi": round(ci_hi, 3), "p": round(p_val, 4),
    }
    results["cohens_d_fm_vs_demo"] = round(cohens_d(err_demo, err_fm), 3)
    print(f"FM vs Demo bootstrap: diff={diff:.3f} [{ci_lo:.3f}, {ci_hi:.3f}] p={p_val:.4f}")

    # ── Permutation test (H0: FM >= mean predictor) ───────────────────
    mean_pred = np.full_like(y_true, np.mean(y_true))
    fm_mae = float(mean_absolute_error(y_true, y_pred_fm))
    rng = np.random.RandomState(42)
    n_perm = 10000
    n_better = 0
    for _ in range(n_perm):
        perm_idx = rng.permutation(len(y_true))
        perm_mae = float(mean_absolute_error(y_true, y_pred_fm[perm_idx]))
        if perm_mae <= fm_mae:
            n_better += 1
    perm_p = (n_better + 1) / (n_perm + 1)
    results["permutation_test"] = {"n_perm": n_perm, "p": round(perm_p, 6),
                                   "fm_mae": round(fm_mae, 3),
                                   "mean_mae": round(float(mean_absolute_error(y_true, mean_pred)), 3)}
    print(f"Permutation test: p={perm_p:.6f}")

    # ── Bland-Altman ──────────────────────────────────────────────────
    ba_mean = (y_true + y_pred_fm) / 2
    ba_diff = y_pred_fm - y_true
    bias = float(np.mean(ba_diff))
    loa_lo = bias - 1.96 * float(np.std(ba_diff))
    loa_hi = bias + 1.96 * float(np.std(ba_diff))
    # Proportional bias
    prop_slope, prop_intercept, prop_r, prop_p, _ = sp_stats.linregress(ba_mean, ba_diff)
    results["bland_altman"] = {
        "bias": round(bias, 3), "loa_lo": round(loa_lo, 3), "loa_hi": round(loa_hi, 3),
        "prop_bias_slope": round(float(prop_slope), 4),
        "prop_bias_r": round(float(prop_r), 3),
        "prop_bias_p": round(float(prop_p), 4),
    }
    print(f"Bland-Altman: bias={bias:.3f}, LOA=[{loa_lo:.2f}, {loa_hi:.2f}]")

    # ── Partial correlation controlling age + disease duration ─────────
    ages = np.array([demos.get(s, {}).get("age") or np.nan for s in sids])
    yrs_dx = np.array([demos.get(s, {}).get("years_dx") or np.nan for s in sids])
    # Impute NaN with median
    for arr in [ages, yrs_dx]:
        mask = np.isnan(arr)
        if mask.any() and not mask.all():
            arr[mask] = np.nanmedian(arr)
        elif mask.all():
            arr[:] = 0.0

    # Partial correlation: residualize both true and pred on confounds
    confounds = np.column_stack([ages, yrs_dx])
    from numpy.linalg import lstsq
    # Residualize y_true
    beta_true, _, _, _ = lstsq(np.column_stack([confounds, np.ones(len(confounds))]),
                                y_true, rcond=None)
    resid_true = y_true - confounds @ beta_true[:2] - beta_true[2]
    # Residualize y_pred
    beta_pred, _, _, _ = lstsq(np.column_stack([confounds, np.ones(len(confounds))]),
                                y_pred_fm, rcond=None)
    resid_pred = y_pred_fm - confounds @ beta_pred[:2] - beta_pred[2]

    partial_r, partial_p = sp_stats.pearsonr(resid_true, resid_pred)
    results["partial_correlation"] = {
        "r": round(float(partial_r), 3), "p": round(float(partial_p), 4),
        "controlling": ["age", "years_dx"],
    }
    print(f"Partial correlation (controlling age+yrs_dx): r={partial_r:.3f} p={partial_p:.4f}")

    # ── Clinical significance (contextual) ────────────────────────────
    abs_errors = np.abs(y_true - y_pred_fm)
    within_mcid = float(np.mean(abs_errors <= 3.25)) * 100
    within_5 = float(np.mean(abs_errors <= 5.0)) * 100
    within_10 = float(np.mean(abs_errors <= 10.0)) * 100
    results["clinical_significance"] = {
        "pct_within_mcid_3.25": round(within_mcid, 1),
        "pct_within_5": round(within_5, 1),
        "pct_within_10": round(within_10, 1),
    }
    print(f"Clinical significance: <=3.25: {within_mcid:.1f}%, <=5: {within_5:.1f}%, <=10: {within_10:.1f}%")

    # ── Severity quartile stratification ──────────────────────────────
    quartile_results = []
    bins = [(0, 12, "Q1(<12)"), (12, 20, "Q2(12-20)"), (20, 35, "Q3(20-35)"), (35, 200, "Q4(>35)")]
    for lo, hi, label in bins:
        mask = (y_true >= lo) & (y_true < hi)
        n_q = int(mask.sum())
        if n_q < 2:
            quartile_results.append({"label": label, "n": n_q, "mae": None})
            continue
        q_metrics = compute_full_metrics(y_true[mask], y_pred_fm[mask])
        q_metrics["n"] = n_q
        q_metrics["label"] = label
        q_metrics["mean_true"] = round(float(np.mean(y_true[mask])), 1)
        q_metrics["mean_pred"] = round(float(np.mean(y_pred_fm[mask])), 1)
        q_metrics["bias"] = round(float(np.mean(y_pred_fm[mask] - y_true[mask])), 2)
        quartile_results.append(q_metrics)
        print(f"  {label} (n={n_q}): MAE={q_metrics['mae']}, bias={q_metrics['bias']}")
    results["severity_quartiles"] = quartile_results

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("pd_only_phase2.json", results)
    print(f"\nPhase 2 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 3: 3-LEVEL OBSERVABILITY DECOMPOSITION
# ═══════════════════════════════════════════════════════════════════════

def phase3(v2_df, fm_agg, fm_cols, subjects, all_sids, rec_array, rec_sids):
    """3-level observability: direct/partial/unobservable + binary compat."""
    print("\n" + "="*70)
    print("PHASE 3: Observable vs Partially-Observable vs Unobservable")
    print("="*70)
    t0 = time.time()

    item_scores = parse_item_scores()
    demos = extract_demographics_for_sids(set(all_sids))
    v2_cols = get_v2_cols(v2_df)

    pd_sids = [s for s in all_sids if subjects[s]["group"] == "PD"]
    hc_sids = [s for s in all_sids if subjects[s]["group"] == "HC"]

    # Compute subscores for all subjects
    subscore_defs = [
        ("direct", DIRECT_ITEMS, 24),
        ("partial", PARTIAL_ITEMS, 68),
        ("unobs", UNOBS_ITEMS, 40),
        ("binary_obs", set(OBSERVABLE_ITEMS), 40),  # backward compat (items 7-14)
    ]

    subscores = {}
    for name, items, max_score in subscore_defs:
        subscores[name] = {}
        for sid in all_sids:
            val = compute_subscore(item_scores, sid, items)
            if val is not None:
                subscores[name][sid] = val

    for name, _, _ in subscore_defs:
        n_pd = sum(1 for s in pd_sids if s in subscores[name])
        n_hc = sum(1 for s in hc_sids if s in subscores[name])
        print(f"  {name}: {n_pd} PD + {n_hc} HC = {n_pd + n_hc} total")

    # Merge v2 + FM
    merged = v2_df[["sid", "updrs3"] + v2_cols].merge(fm_agg, on="sid", how="left").fillna(0.0)
    all_feat_cols = v2_cols + fm_cols

    results = {"phase": "3_observability", "subscores": {}}

    # ── 3a: PD-only LOOCV per subscore ────────────────────────────────
    for name, items, max_score in subscore_defs:
        print(f"\n--- LOOCV for {name} (items {sorted(items)}, max={max_score}) ---")
        valid_pd = [s for s in pd_sids if s in subscores[name]]
        if len(valid_pd) < 10:
            print(f"  SKIP: only {len(valid_pd)} valid PD subjects")
            results["subscores"][name] = {"loocv": None, "n_pd": len(valid_pd)}
            continue

        # Add subscore column
        merged_sub = merged.copy()
        merged_sub["sub_target"] = merged_sub["sid"].map(subscores[name])
        merged_sub_valid = merged_sub.dropna(subset=["sub_target"])

        y_true_loo, y_pred_loo = [], []
        for i, loo_sid in enumerate(valid_pd):
            dev_sids_loo = [s for s in all_sids if s != loo_sid and s in subscores[name]]
            Xd, yd, Xt, yt = prep_arrays(merged_sub_valid, dev_sids_loo, [loo_sid],
                                          all_feat_cols, target_col="sub_target")
            if len(Xt) == 0 or len(yt) == 0:
                continue

            k = min(300, Xd.shape[1])
            sel_idx, _ = feature_select(Xd, yd, all_feat_cols, k)
            Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]
            pred = run_lgb_ensemble(Xds, yd, Xts, clip_max=max_score)
            y_true_loo.append(float(yt[0]))
            y_pred_loo.append(float(pred[0]))

            if (i+1) % 20 == 0:
                running_mae = float(np.mean(np.abs(np.array(y_true_loo) - np.array(y_pred_loo))))
                print(f"  [{i+1}/{len(valid_pd)}] running MAE={running_mae:.3f}")

        y_true_loo = np.array(y_true_loo)
        y_pred_loo = np.array(y_pred_loo)
        loocv_metrics = compute_full_metrics(y_true_loo, y_pred_loo)
        loocv_metrics["n"] = len(y_true_loo)
        print(f"  {name} LOOCV: MAE={loocv_metrics['mae']}, CCC={loocv_metrics['ccc']}, "
              f"r={loocv_metrics['r']}, MAE/SD={loocv_metrics['mae_sd']}")

        results["subscores"][name] = {
            "loocv": loocv_metrics,
            "max_score": max_score,
            "items": sorted(items),
            "n_pd": len(valid_pd),
        }

    # ── 3b: PD-only 10-split per subscore (B1 track) ─────────────────
    for name, items, max_score in subscore_defs[:3]:  # direct, partial, unobs
        print(f"\n--- 10-split B1 for {name} ---")
        valid_pd = [s for s in pd_sids if s in subscores[name]]
        if len(valid_pd) < 10:
            continue

        merged_sub = merged.copy()
        merged_sub["sub_target"] = merged_sub["sid"].map(subscores[name])
        merged_sub_valid = merged_sub.dropna(subset=["sub_target"])

        split_maes = []
        for si, seed in enumerate(range(1, 11)):
            dev_pd_sub, test_pd_sub = gen_pd_split(valid_pd, subjects, demos, seed)
            Xd, yd, Xt, yt = prep_arrays(merged_sub_valid, dev_pd_sub, test_pd_sub,
                                          all_feat_cols, target_col="sub_target")
            if len(Xt) < 2:
                continue
            k = min(300, Xd.shape[1])
            sel_idx, _ = feature_select(Xd, yd, all_feat_cols, k)
            pred = run_lgb_ensemble(Xd[:, sel_idx], yd, Xt[:, sel_idx], clip_max=max_score)
            mae_val = float(mean_absolute_error(yt, pred))
            split_maes.append(mae_val)

        if split_maes:
            results["subscores"][name]["ten_split_b1"] = {
                "mae_mean": round(np.mean(split_maes), 3),
                "mae_std": round(np.std(split_maes), 3),
            }
            print(f"  {name} 10-split: MAE={np.mean(split_maes):.3f}+/-{np.std(split_maes):.3f}")

    # ── 3c: Permutation test: r_direct > r_partial > r_unobs ──────────
    print("\n--- Permutation test: prediction quality ordering ---")
    r_vals = {}
    for name in ["direct", "partial", "unobs"]:
        loocv = results["subscores"].get(name, {}).get("loocv")
        if loocv and loocv.get("r") is not None:
            r_vals[name] = loocv["r"]

    if len(r_vals) == 3:
        observed_order = (r_vals["direct"] > r_vals["partial"] > r_vals["unobs"])
        # Bootstrap permutation
        rng = np.random.RandomState(42)
        n_perm = 10000
        n_correct = 0
        r_array = [r_vals["direct"], r_vals["partial"], r_vals["unobs"]]
        for _ in range(n_perm):
            perm = rng.permutation(r_array)
            if perm[0] > perm[1] > perm[2]:
                n_correct += 1
        perm_p = (n_correct + 1) / (n_perm + 1)
        results["ordering_test"] = {
            "r_direct": r_vals["direct"], "r_partial": r_vals["partial"],
            "r_unobs": r_vals["unobs"],
            "observed_monotonic": bool(observed_order),
            "permutation_p": round(perm_p, 4),
        }
        print(f"  r_direct={r_vals['direct']:.3f} > r_partial={r_vals['partial']:.3f} > "
              f"r_unobs={r_vals['unobs']:.3f} -> monotonic={observed_order}, p={perm_p:.4f}")

    # ── 3d: Residualization test ──────────────────────────────────────
    print("\n--- Residualization: predict subscore after removing total-severity variance ---")
    residual_results = {}
    for name in ["direct", "partial", "unobs"]:
        valid_pd = [s for s in pd_sids if s in subscores[name]]
        if len(valid_pd) < 10:
            continue
        sub_vals = np.array([subscores[name][s] for s in valid_pd])
        total_vals = np.array([subjects[s]["updrs3"] for s in valid_pd])
        # Regress subscore on total
        slope, intercept, _, _, _ = sp_stats.linregress(total_vals, sub_vals)
        residuals = sub_vals - (slope * total_vals + intercept)
        residual_results[name] = {
            "residual_sd": round(float(np.std(residuals)), 3),
            "residual_range": round(float(np.max(residuals) - np.min(residuals)), 3),
            "r_sub_total": round(float(sp_stats.pearsonr(total_vals, sub_vals)[0]), 3),
        }
        print(f"  {name}: r(sub,total)={residual_results[name]['r_sub_total']:.3f}, "
              f"residual SD={residual_results[name]['residual_sd']:.3f}")
    results["residualization"] = residual_results

    # ── 3e: Feature importance x sensor alignment ─────────────────────
    print("\n--- Feature importance x sensor alignment ---")
    fi_results = {}
    for name, items, max_score in subscore_defs[:3]:
        valid_pd = [s for s in pd_sids if s in subscores[name]]
        if len(valid_pd) < 10:
            continue
        merged_sub = merged.copy()
        merged_sub["sub_target"] = merged_sub["sid"].map(subscores[name])
        merged_sub_valid = merged_sub.dropna(subset=["sub_target"])

        Xd = merged_sub_valid[all_feat_cols].values.astype(np.float32)
        yd = merged_sub_valid["sub_target"].values.astype(np.float32)

        sel = XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                           reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
                           objective="reg:absoluteerror")
        sel.fit(Xd, yd)
        top_idx = np.argsort(sel.feature_importances_)[::-1][:20]
        top_feats = [all_feat_cols[i] for i in top_idx]

        # Map features to sensors
        sensor_counts = {s: 0 for s in SENSORS}
        for f in top_feats:
            for s in SENSORS:
                if f.startswith(s + "_") or s.lower() in f.lower():
                    sensor_counts[s] += 1
                    break

        fi_results[name] = {
            "top20_features": top_feats,
            "sensor_alignment": {k: v for k, v in sensor_counts.items() if v > 0},
        }
        top_sensors = sorted(sensor_counts.items(), key=lambda x: -x[1])[:5]
        print(f"  {name}: top sensors = {top_sensors}")
    results["feature_importance_alignment"] = fi_results

    # ── 3f: Decomposition analysis ────────────────────────────────────
    common_pd = [s for s in pd_sids
                 if s in subscores["direct"] and s in subscores["partial"] and s in subscores["unobs"]]
    if len(common_pd) > 0:
        sum_sub = np.array([subscores["direct"][s] + subscores["partial"][s] + subscores["unobs"][s]
                            for s in common_pd])
        total = np.array([subjects[s]["updrs3"] for s in common_pd])
        recon_error = float(np.mean(np.abs(sum_sub - total)))
        results["decomposition"] = {
            "n": len(common_pd),
            "mean_reconstruction_error": round(recon_error, 3),
            "r_sum_vs_total": round(float(sp_stats.pearsonr(sum_sub, total)[0]), 3),
        }
        print(f"\nDecomposition: recon error={recon_error:.3f}, "
              f"r(sum,total)={results['decomposition']['r_sum_vs_total']:.3f}")

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("pd_only_phase3.json", results)
    print(f"\nPhase 3 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 4: SEVERITY + CONFOUNDS
# ═══════════════════════════════════════════════════════════════════════

def phase4(subjects, all_sids):
    """Severity-stratified error + confound analysis using LOOCV predictions."""
    print("\n" + "="*70)
    print("PHASE 4: Severity-Stratified Error + Confound Analysis")
    print("="*70)
    t0 = time.time()

    # Load FM LOOCV predictions
    loocv_data, _ = load_json_artifact("rocket_phase8_fm_loocv.json")
    preds = loocv_data["predictions"]
    sids = [p["sid"] for p in preds]
    y_true = np.array([p["true"] for p in preds], dtype=np.float64)
    y_pred = np.array([p["pred_fm"] for p in preds], dtype=np.float64)

    demos = extract_demographics_for_sids(set(all_sids))
    item_scores = parse_item_scores()

    results = {"phase": "4_severity_confounds", "n": len(sids)}

    # ── Severity quartile stratification ──────────────────────────────
    print("\n--- Severity quartile stratification ---")
    bins = [(0, 12, "Q1(<12)"), (12, 20, "Q2(12-20)"), (20, 35, "Q3(20-35)"), (35, 200, "Q4(>35)")]
    quartile_results = []
    for lo, hi, label in bins:
        mask = (y_true >= lo) & (y_true < hi)
        n_q = int(mask.sum())
        if n_q < 2:
            quartile_results.append({"label": label, "n": n_q})
            continue
        q_metrics = compute_full_metrics(y_true[mask], y_pred[mask])
        q_metrics["n"] = n_q
        q_metrics["label"] = label
        q_metrics["mean_true"] = round(float(np.mean(y_true[mask])), 1)
        q_metrics["mean_pred"] = round(float(np.mean(y_pred[mask])), 1)
        q_metrics["bias"] = round(float(np.mean(y_pred[mask] - y_true[mask])), 2)
        quartile_results.append(q_metrics)
        print(f"  {label} (n={n_q}): MAE={q_metrics['mae']}, CCC={q_metrics['ccc']}, bias={q_metrics['bias']}")
    results["severity_quartiles"] = quartile_results

    # ── Spearman rank correlation ─────────────────────────────────────
    rho, rho_p = sp_stats.spearmanr(y_true, y_pred)
    results["spearman"] = {"rho": round(float(rho), 3), "p": round(float(rho_p), 6)}
    print(f"\nSpearman: rho={rho:.3f}, p={rho_p:.6f}")

    # ── Weighted kappa at severity bins ───────────────────────────────
    from sklearn.metrics import cohen_kappa_score
    bin_edges = [0, 12, 20, 35, 200]
    true_bins = np.digitize(y_true, bin_edges) - 1
    pred_bins = np.digitize(y_pred, bin_edges) - 1
    pred_bins = np.clip(pred_bins, 0, 3)
    wk = cohen_kappa_score(true_bins, pred_bins, weights="quadratic")
    results["weighted_kappa"] = round(float(wk), 3)
    print(f"Weighted kappa (quadratic): {wk:.3f}")

    # ── Proportional bias ─────────────────────────────────────────────
    abs_errors = np.abs(y_true - y_pred)
    prop_slope, prop_intercept, prop_r, prop_p, _ = sp_stats.linregress(y_true, abs_errors)
    results["proportional_bias"] = {
        "slope": round(float(prop_slope), 4),
        "intercept": round(float(prop_intercept), 3),
        "r": round(float(prop_r), 3),
        "p": round(float(prop_p), 4),
    }
    print(f"Proportional bias: slope={prop_slope:.4f}, r={prop_r:.3f}, p={prop_p:.4f}")

    # ── Partial correlation controlling age + disease duration ─────────
    ages = np.array([demos.get(s, {}).get("age") or np.nan for s in sids])
    yrs_dx = np.array([demos.get(s, {}).get("years_dx") or np.nan for s in sids])
    for arr in [ages, yrs_dx]:
        mask = np.isnan(arr)
        if mask.any() and not mask.all():
            arr[mask] = np.nanmedian(arr)
        elif mask.all():
            arr[:] = 0.0

    confounds = np.column_stack([ages, yrs_dx])
    from numpy.linalg import lstsq
    beta_true, _, _, _ = lstsq(np.column_stack([confounds, np.ones(len(confounds))]), y_true, rcond=None)
    resid_true = y_true - confounds @ beta_true[:2] - beta_true[2]
    beta_pred, _, _, _ = lstsq(np.column_stack([confounds, np.ones(len(confounds))]), y_pred, rcond=None)
    resid_pred = y_pred - confounds @ beta_pred[:2] - beta_pred[2]
    partial_r, partial_p = sp_stats.pearsonr(resid_true, resid_pred)
    results["partial_correlation"] = {
        "r": round(float(partial_r), 3), "p": round(float(partial_p), 4),
    }
    print(f"Partial correlation (age+yrs_dx): r={partial_r:.3f}, p={partial_p:.4f}")

    # ── Error correlation with demographics ───────────────────────────
    print("\n--- Error correlation with demographics ---")
    errors = y_pred - y_true
    demo_fields = ["age", "sex", "years_dx", "height_cm", "weight_kg"]
    error_correlations = {}
    for field in demo_fields:
        vals = np.array([demos.get(s, {}).get(field) or np.nan for s in sids])
        valid = ~np.isnan(vals)
        if valid.sum() < 5:
            continue
        r_val, p_val = sp_stats.pearsonr(vals[valid], errors[valid])
        error_correlations[field] = {"r": round(float(r_val), 3), "p": round(float(p_val), 4)}
        flag = " *** FLAGGED" if abs(r_val) > 0.3 else ""
        print(f"  error ~ {field}: r={r_val:.3f}, p={p_val:.4f}{flag}")
    results["error_correlations"] = error_correlations

    # ── Missing-data sensitivity ──────────────────────────────────────
    print("\n--- Missing-data sensitivity ---")
    complete_sids = []
    for sid in sids:
        if sid not in item_scores:
            continue
        all_present = all(item_num in item_scores[sid] for item_num in range(1, 19))
        if all_present:
            complete_sids.append(sid)
    complete_mask = np.array([s in set(complete_sids) for s in sids])
    n_complete = int(complete_mask.sum())
    n_partial = len(sids) - n_complete
    print(f"  Complete items: {n_complete}, Partial items: {n_partial}")

    if n_complete >= 5 and n_partial >= 5:
        mae_complete = float(mean_absolute_error(y_true[complete_mask], y_pred[complete_mask]))
        mae_partial = float(mean_absolute_error(y_true[~complete_mask], y_pred[~complete_mask]))
        results["missing_data"] = {
            "n_complete": n_complete, "n_partial": n_partial,
            "mae_complete": round(mae_complete, 3), "mae_partial": round(mae_partial, 3),
        }
        print(f"  MAE(complete)={mae_complete:.3f}, MAE(partial)={mae_partial:.3f}")
    elif n_complete >= 5:
        mae_complete = float(mean_absolute_error(y_true[complete_mask], y_pred[complete_mask]))
        results["missing_data"] = {
            "n_complete": n_complete, "n_partial": n_partial,
            "mae_complete": round(mae_complete, 3), "mae_partial": None,
        }
        print(f"  MAE(complete)={mae_complete:.3f}, too few partial for comparison")
    else:
        results["missing_data"] = {"n_complete": n_complete, "n_partial": n_partial}

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("pd_only_phase4.json", results)
    print(f"\nPhase 4 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 5: LOCKED HELD-OUT TEST
# ═══════════════════════════════════════════════════════════════════════

def phase5(v2_df, fm_agg, fm_cols, subjects, all_sids):
    """Locked held-out test from paper3_split.json."""
    print("\n" + "="*70)
    print("PHASE 5: Locked Held-Out Test (paper3_split.json)")
    print("="*70)
    t0 = time.time()

    # Load clean split
    split_path = str(results_artifact_path("paper3_split.json"))
    if not os.path.exists(split_path):
        raise FileNotFoundError(f"Clean split not found: {split_path}")
    with open(split_path) as f:
        split_info = json.load(f)
    dev_sids = split_info["dev_sids"]
    test_sids = split_info["test_sids"]
    print(f"Split: {len(dev_sids)} dev + {len(test_sids)} test")

    demos = extract_demographics_for_sids(set(all_sids))
    item_scores = parse_item_scores()
    v2_cols = get_v2_cols(v2_df)

    # Merge v2 + FM
    merged = v2_df[["sid", "updrs3"] + v2_cols].merge(fm_agg, on="sid", how="left").fillna(0.0)
    all_feat_cols = v2_cols + fm_cols

    results = {"phase": "5_locked_held_out", "split_seed": split_info.get("seed"),
               "n_dev": len(dev_sids), "n_test": len(test_sids)}

    # ── Full test (all subjects in test set) ──────────────────────────
    print("\n--- Full test (all subjects) ---")
    Xd, yd, Xt, yt = prep_arrays(merged, dev_sids, test_sids, all_feat_cols)
    k = min(300, Xd.shape[1])
    sel_idx, sel_names = feature_select(Xd, yd, all_feat_cols, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]

    pred_full = run_stack(Xds, yd, Xts)
    results["full_test"] = compute_full_metrics(yt, pred_full)
    print(f"Full test: {results['full_test']}")

    # ── PD-subset (test PD subjects) ──────────────────────────────────
    test_pd_sids = [s for s in test_sids if subjects.get(s, {}).get("group") == "PD"]
    print(f"\n--- PD-subset test (N={len(test_pd_sids)}) ---")
    if len(test_pd_sids) >= 3:
        test_df = merged[merged["sid"].isin(test_sids)].reset_index(drop=True)
        pd_test_mask = test_df["sid"].isin(test_pd_sids)
        yt_pd = test_df.loc[pd_test_mask, "updrs3"].values.astype(np.float32)
        Xt_pd = test_df.loc[pd_test_mask, [all_feat_cols[i] for i in sel_idx]].values.astype(np.float32)
        pred_pd = run_stack(Xds, yd, Xt_pd)
        results["pd_subset_test"] = compute_full_metrics(yt_pd, pred_pd)
        results["pd_subset_test"]["n"] = len(test_pd_sids)
        results["pd_subset_test"]["caveat"] = "N too small for primary PD claim"
        print(f"PD-subset: {results['pd_subset_test']}")

    # ── Demographic baseline on same test ─────────────────────────────
    print("\n--- Demographic baseline on test ---")
    valid_dev = [s for s in dev_sids if s in subjects]
    valid_test = [s for s in test_sids if s in subjects]
    Xd_demo, _ = build_demo_matrix(valid_dev, demos)
    yd_demo = np.array([subjects[s]["updrs3"] for s in valid_dev], dtype=np.float32)
    Xt_demo, _ = build_demo_matrix(valid_test, demos)
    yt_demo = np.array([subjects[s]["updrs3"] for s in valid_test], dtype=np.float32)
    ridge_demo = Ridge(alpha=1.0)
    ridge_demo.fit(Xd_demo, yd_demo)
    pred_demo = np.clip(ridge_demo.predict(Xt_demo), 0, 132)
    results["demo_baseline"] = compute_full_metrics(yt_demo, pred_demo)
    print(f"Demographic baseline: {results['demo_baseline']}")

    # ── Observable subscore on test PD ─────────────────────────────────
    print("\n--- Observable subscore on test PD ---")
    if len(test_pd_sids) >= 3:
        obs_targets_test = {}
        for sid in test_pd_sids:
            obs = compute_subscore(item_scores, sid, set(OBSERVABLE_ITEMS))
            if obs is not None:
                obs_targets_test[sid] = obs

        if len(obs_targets_test) >= 3:
            obs_targets_dev = {}
            for sid in dev_sids:
                obs = compute_subscore(item_scores, sid, set(OBSERVABLE_ITEMS))
                if obs is not None:
                    obs_targets_dev[sid] = obs

            merged_obs = merged.copy()
            merged_obs["obs_target"] = merged_obs["sid"].map({**obs_targets_dev, **obs_targets_test})
            merged_obs_valid = merged_obs.dropna(subset=["obs_target"])

            valid_dev_obs = [s for s in dev_sids if s in obs_targets_dev]
            valid_test_obs = [s for s in test_pd_sids if s in obs_targets_test]

            Xd_obs, yd_obs, Xt_obs, yt_obs = prep_arrays(
                merged_obs_valid, valid_dev_obs, valid_test_obs,
                all_feat_cols, target_col="obs_target")
            k_obs = min(300, Xd_obs.shape[1])
            sel_idx_obs, _ = feature_select(Xd_obs, yd_obs, all_feat_cols, k_obs)
            pred_obs = run_lgb_ensemble(Xd_obs[:, sel_idx_obs], yd_obs,
                                        Xt_obs[:, sel_idx_obs], clip_max=40)
            results["obs_subscore_test"] = compute_full_metrics(yt_obs, pred_obs)
            results["obs_subscore_test"]["n"] = len(valid_test_obs)
            print(f"Observable subscore on test PD: {results['obs_subscore_test']}")

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("pd_only_phase5.json", results)
    print(f"\nPhase 5 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 6: SENSOR ABLATION WITH FM RE-EXTRACTION
# ═══════════════════════════════════════════════════════════════════════

def phase6(v2_df, rec_array, rec_sids, subjects, all_sids):
    """Sensor ablation with FM re-extraction per config."""
    print("\n" + "="*70)
    print("PHASE 6: PD-Only Sensor Ablation (FM re-extracted per config)")
    print("="*70)
    t0 = time.time()

    pd_sids = [s for s in all_sids if subjects[s]["group"] == "PD"]
    demos = extract_demographics_for_sids(set(all_sids))
    v2_cols = get_v2_cols(v2_df)

    results = {"phase": "6_sensor_ablation", "configs": {}}

    # Sensor index mapping: for sensor i, acc_mag = 2*i, gyr_mag = 2*i+1
    sensor_to_channels = {}
    for i, sen in enumerate(SENSORS):
        sensor_to_channels[sen] = [2*i, 2*i+1]

    for config_name, sensor_list in SENSOR_CONFIGS.items():
        print(f"\n--- Config: {config_name} ({len(sensor_list)} sensors) ---")

        # Select channels for this config
        channels = []
        for sen in sensor_list:
            channels.extend(sensor_to_channels[sen])
        channels = sorted(channels)
        print(f"  Channels: {len(channels)} ({channels[:6]}...)")

        # Subset rec_array to these channels
        rec_sub = rec_array[:, channels, :]  # (N, C_sub, SEQ_LEN)
        print(f"  rec_sub shape: {rec_sub.shape}")

        # Re-extract FM embeddings for this config
        fm_cache_config = str(results_artifact_path(f"fm_embeddings_{config_name}.npz"))
        fm_emb = extract_fm_embeddings(rec_sub, cache_path=fm_cache_config)
        fm_agg_config = fm_features_for_subjects(fm_emb, rec_sids)
        fm_cols_config = [c for c in fm_agg_config.columns if c.startswith("fm_")]

        # Filter v2 features for this sensor config
        v2_cols_filtered = filter_features_for_sensors(v2_cols, set(sensor_list))
        print(f"  v2 features: {len(v2_cols_filtered)}/{len(v2_cols)}, FM features: {len(fm_cols_config)}")

        if v2_cols_filtered:
            merged = v2_df[["sid", "updrs3"] + v2_cols_filtered].merge(
                fm_agg_config, on="sid", how="left").fillna(0.0)
            feat_cols = v2_cols_filtered + fm_cols_config
        else:
            merged = v2_df[["sid", "updrs3"]].merge(fm_agg_config, on="sid", how="left").fillna(0.0)
            feat_cols = fm_cols_config

        # 10-split PD-only (B1 track)
        split_maes, split_cccs = [], []
        for si, seed in enumerate(range(1, 11)):
            dev_pd, test_pd = gen_pd_split(pd_sids, subjects, demos, seed)
            Xd, yd, Xt, yt = prep_arrays(merged, dev_pd, test_pd, feat_cols)
            if len(Xt) < 2:
                continue
            k = min(300, Xd.shape[1])
            sel_idx, _ = feature_select(Xd, yd, feat_cols, k)
            pred = run_lgb_ensemble(Xd[:, sel_idx], yd, Xt[:, sel_idx])
            mae_val = float(mean_absolute_error(yt, pred))
            ccc_val = lins_ccc(yt, pred)
            split_maes.append(mae_val)
            split_cccs.append(ccc_val)

        config_result = {
            "n_sensors": len(sensor_list),
            "sensors": sensor_list,
            "n_v2_features": len(v2_cols_filtered),
            "n_fm_features": len(fm_cols_config),
            "mae_mean": round(np.mean(split_maes), 3),
            "mae_std": round(np.std(split_maes), 3),
            "ccc_mean": round(np.mean(split_cccs), 3),
            "ccc_std": round(np.std(split_cccs), 3),
            "split_maes": [round(m, 3) for m in split_maes],
        }
        results["configs"][config_name] = config_result
        print(f"  {config_name}: MAE={np.mean(split_maes):.3f}+/-{np.std(split_maes):.3f}, "
              f"CCC={np.mean(split_cccs):.3f}")

    # ── Paired bootstrap: each config vs all_13 ──────────────────────
    print("\n--- Paired bootstrap: config vs all_13 ---")
    if "all_13" in results["configs"]:
        baseline_maes = np.array(results["configs"]["all_13"]["split_maes"])
        for config_name, config_result in results["configs"].items():
            if config_name == "all_13":
                continue
            config_maes = np.array(config_result["split_maes"])
            if len(config_maes) != len(baseline_maes):
                continue
            diff, ci_lo, ci_hi, p_val = subject_paired_bootstrap(config_maes, baseline_maes,
                                                                  n_boot=5000)
            results["configs"][config_name]["vs_all_13"] = {
                "mean_diff": round(diff, 3), "ci_lo": round(ci_lo, 3),
                "ci_hi": round(ci_hi, 3), "p": round(p_val, 4),
            }
            print(f"  {config_name} vs all_13: diff={diff:.3f} [{ci_lo:.3f}, {ci_hi:.3f}] p={p_val:.4f}")

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("pd_only_phase6.json", results)
    print(f"\nPhase 6 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 7: CONSOLIDATED REPORT
# ═══════════════════════════════════════════════════════════════════════

def phase7(subjects, all_sids):
    """Consolidated report: load all phases, demographics, Holm-Bonferroni."""
    print("\n" + "="*70)
    print("PHASE 7: Consolidated Report")
    print("="*70)
    t0 = time.time()

    demos = extract_demographics_for_sids(set(all_sids))
    pd_sids = [s for s in all_sids if subjects[s]["group"] == "PD"]
    hc_sids = [s for s in all_sids if subjects[s]["group"] == "HC"]

    results = {"phase": "7_consolidated"}

    # ── Table 1: Demographics ─────────────────────────────────────────
    print("\n--- Table 1: Demographics ---")
    demo_table = {}
    for group_name, group_sids in [("PD", pd_sids), ("HC", hc_sids), ("All", all_sids)]:
        group_demos = [demos[s] for s in group_sids if s in demos]
        ages = [d["age"] for d in group_demos if d["age"] is not None]
        yrs = [d["years_dx"] for d in group_demos if d["years_dx"] is not None]
        heights = [d["height_cm"] for d in group_demos if d["height_cm"] is not None]
        weights = [d["weight_kg"] for d in group_demos if d["weight_kg"] is not None]
        hys = [d["hy"] for d in group_demos if d["hy"] is not None]
        updrs = [d["updrs3"] for d in group_demos]
        n_male = sum(1 for d in group_demos if d["sex"] == 1)

        demo_table[group_name] = {
            "n": len(group_demos),
            "age_mean": round(np.mean(ages), 1) if ages else None,
            "age_std": round(np.std(ages), 1) if ages else None,
            "pct_male": round(100 * n_male / len(group_demos), 1) if group_demos else None,
            "years_dx_mean": round(np.mean(yrs), 1) if yrs else None,
            "years_dx_std": round(np.std(yrs), 1) if yrs else None,
            "height_cm_mean": round(np.mean(heights), 1) if heights else None,
            "weight_kg_mean": round(np.mean(weights), 1) if weights else None,
            "hy_median": round(float(np.median(hys)), 1) if hys else None,
            "updrs3_mean": round(np.mean(updrs), 1) if updrs else None,
            "updrs3_std": round(np.std(updrs), 1) if updrs else None,
            "updrs3_range": [round(min(updrs), 0), round(max(updrs), 0)] if updrs else None,
        }
        print(f"  {group_name}: N={demo_table[group_name]['n']}, "
              f"Age={demo_table[group_name]['age_mean']}+/-{demo_table[group_name]['age_std']}, "
              f"UPDRS={demo_table[group_name]['updrs3_mean']}+/-{demo_table[group_name]['updrs3_std']}")
    results["demographics"] = demo_table

    # ── Load phase results ────────────────────────────────────────────
    phase_files = {
        "phase1": "pd_only_phase1.json",
        "phase2": "pd_only_phase2.json",
        "phase3": "pd_only_phase3.json",
        "phase4": "pd_only_phase4.json",
        "phase5": "pd_only_phase5.json",
        "phase6": "pd_only_phase6.json",
    }
    loaded = {}
    for key, fname in phase_files.items():
        try:
            data, path = load_json_artifact(fname)
            loaded[key] = data
            print(f"  Loaded {fname}")
        except FileNotFoundError:
            print(f"  MISSING {fname} -- skipping")

    # ── Master results table ──────────────────────────────────────────
    print("\n--- Master results table ---")
    master = {}

    if "phase1" in loaded:
        p1 = loaded["phase1"]
        for tag in ["b1_v2", "b1_fm_stk", "b2_fm_stk", "demographic"]:
            skey = f"summary_{tag}"
            if skey in p1:
                master[f"10split_{tag}"] = p1[skey]

    if "phase2" in loaded:
        p2 = loaded["phase2"]
        master["loocv_fm"] = p2.get("fm_metrics")
        master["loocv_demo"] = p2.get("demo_metrics")

    if "phase3" in loaded:
        p3 = loaded["phase3"]
        for name in ["direct", "partial", "unobs", "binary_obs"]:
            sub = p3.get("subscores", {}).get(name, {})
            loocv = sub.get("loocv")
            if loocv:
                master[f"obs_{name}_loocv"] = {
                    "mae": loocv.get("mae"), "ccc": loocv.get("ccc"),
                    "r": loocv.get("r"), "mae_sd": loocv.get("mae_sd"),
                }

    if "phase5" in loaded:
        p5 = loaded["phase5"]
        master["held_out_full"] = p5.get("full_test")
        master["held_out_pd_subset"] = p5.get("pd_subset_test")
        master["held_out_demo"] = p5.get("demo_baseline")

    if "phase6" in loaded:
        p6 = loaded["phase6"]
        for config_name, config_data in p6.get("configs", {}).items():
            master[f"sensor_{config_name}"] = {
                "mae_mean": config_data.get("mae_mean"),
                "ccc_mean": config_data.get("ccc_mean"),
                "n_sensors": config_data.get("n_sensors"),
            }

    results["master_table"] = master

    for key, val in master.items():
        if val:
            mae_str = str(val.get("mae") or val.get("mae_mean", "?"))
            ccc_str = str(val.get("ccc") or val.get("ccc_mean", "?"))
            print(f"  {key}: MAE={mae_str}, CCC={ccc_str}")

    # ── Collect all p-values for Holm-Bonferroni ──────────────────────
    print("\n--- Holm-Bonferroni correction ---")
    all_p_values = []

    if "phase1" in loaded:
        p1 = loaded["phase1"]
        fm_vs_v2_ps = [s.get("bootstrap_fm_vs_v2_p") for s in p1.get("splits", [])
                       if s.get("bootstrap_fm_vs_v2_p") is not None]
        fm_vs_demo_ps = [s.get("bootstrap_fm_vs_demo_p") for s in p1.get("splits", [])
                         if s.get("bootstrap_fm_vs_demo_p") is not None]
        if fm_vs_v2_ps:
            all_p_values.append(("P1_fm_vs_v2_median", float(np.median(fm_vs_v2_ps))))
        if fm_vs_demo_ps:
            all_p_values.append(("P1_fm_vs_demo_median", float(np.median(fm_vs_demo_ps))))

    if "phase2" in loaded:
        p2 = loaded["phase2"]
        perm = p2.get("permutation_test", {}).get("p")
        if perm is not None:
            all_p_values.append(("P2_permutation", perm))
        boot = p2.get("bootstrap_fm_vs_demo", {}).get("p")
        if boot is not None:
            all_p_values.append(("P2_fm_vs_demo_bootstrap", boot))
        partial = p2.get("partial_correlation", {}).get("p")
        if partial is not None:
            all_p_values.append(("P2_partial_corr", partial))

    if "phase3" in loaded:
        p3 = loaded["phase3"]
        ordering = p3.get("ordering_test", {}).get("permutation_p")
        if ordering is not None:
            all_p_values.append(("P3_ordering_test", ordering))

    if "phase4" in loaded:
        p4 = loaded["phase4"]
        spearman = p4.get("spearman", {}).get("p")
        if spearman is not None:
            all_p_values.append(("P4_spearman", spearman))
        partial = p4.get("partial_correlation", {}).get("p")
        if partial is not None:
            all_p_values.append(("P4_partial_corr", partial))

    if all_p_values:
        adjusted = holm_bonferroni(all_p_values)
        results["holm_bonferroni"] = [
            {"label": label, "p_raw": p_raw, "p_adj": p_adj}
            for label, p_raw, p_adj in adjusted
        ]
        for label, p_raw, p_adj in adjusted:
            sig = "***" if p_adj < 0.001 else ("**" if p_adj < 0.01 else ("*" if p_adj < 0.05 else "ns"))
            print(f"  {label}: p_raw={p_raw:.6f} -> p_adj={p_adj:.6f} {sig}")

    # ── Effect sizes ──────────────────────────────────────────────────
    if "phase2" in loaded:
        results["effect_sizes"] = {
            "cohens_d_fm_vs_demo": loaded["phase2"].get("cohens_d_fm_vs_demo"),
        }
    if "phase1" in loaded:
        ds = [s.get("cohens_d_fm_vs_v2") for s in loaded["phase1"].get("splits", [])
              if s.get("cohens_d_fm_vs_v2") is not None]
        if ds:
            results.setdefault("effect_sizes", {})["cohens_d_fm_vs_v2_median"] = round(float(np.median(ds)), 3)

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("pd_only_experiments.json", results)
    save_json_artifact("pd_only_phase7.json", results)
    print(f"\nPhase 7 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="PD-only prediction power experiments")
    parser.add_argument("--phase", default="all", help="1|2|3|4|5|6|7|all")
    args = parser.parse_args()

    t_start = time.time()
    print(f"PD-ONLY EXPERIMENTS -- phase={args.phase}")
    print(f"N_CORES={N_CORES}")

    # Load subjects
    subjects = parse_clinical()
    all_sids = sorted(_get_valid_sids(subjects))
    n_pd = sum(1 for s in all_sids if subjects[s]["group"] == "PD")
    n_hc = sum(1 for s in all_sids if subjects[s]["group"] == "HC")
    print(f"Subjects: {len(all_sids)} ({n_pd} PD, {n_hc} HC)")

    # Load v2 feature cache
    if not os.path.exists(V2_CACHE):
        raise FileNotFoundError(f"V2 feature cache not found: {V2_CACHE}\n"
                                f"Run: python3 run_ablation_v3.py --phase 0 first")
    v2_df = pd.read_csv(V2_CACHE)
    print(f"V2 cache: {v2_df.shape}")

    phases = args.phase.split(",") if "," in args.phase else [args.phase]

    # Determine what data is needed
    need_recordings = any(p in ("1", "3", "5", "6", "all") for p in phases)
    need_fm = any(p in ("1", "3", "5", "6", "all") for p in phases)

    rec_array, rec_sids, rec_tasks = None, None, None
    fm_agg, fm_cols = None, None

    if need_recordings:
        rec_array, rec_sids, rec_tasks = load_all_recordings(subjects, all_sids)

    if need_fm and rec_array is not None:
        fm_embeddings = extract_fm_embeddings(rec_array)
        fm_agg = fm_features_for_subjects(fm_embeddings, rec_sids)
        fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]
        print(f"FM features per subject: {len(fm_cols)}")

    all_results = {}

    for phase in phases:
        phase = phase.strip()
        if phase in ("1", "all"):
            assert fm_agg is not None and fm_cols is not None, "FM embeddings required for Phase 1"
            all_results["phase1"] = phase1(v2_df, fm_agg, fm_cols, subjects, all_sids)
        if phase in ("2", "all"):
            all_results["phase2"] = phase2(subjects, all_sids)
        if phase in ("3", "all"):
            assert fm_agg is not None and fm_cols is not None, "FM embeddings required for Phase 3"
            assert rec_array is not None, "Recordings required for Phase 3"
            all_results["phase3"] = phase3(v2_df, fm_agg, fm_cols, subjects, all_sids,
                                           rec_array, rec_sids)
        if phase in ("4", "all"):
            all_results["phase4"] = phase4(subjects, all_sids)
        if phase in ("5", "all"):
            assert fm_agg is not None and fm_cols is not None, "FM embeddings required for Phase 5"
            all_results["phase5"] = phase5(v2_df, fm_agg, fm_cols, subjects, all_sids)
        if phase in ("6", "all"):
            assert rec_array is not None, "Recordings required for Phase 6"
            all_results["phase6"] = phase6(v2_df, rec_array, rec_sids, subjects, all_sids)
        if phase in ("7", "all"):
            all_results["phase7"] = phase7(subjects, all_sids)

    print(f"\n{'='*70}")
    print(f"TOTAL RUNTIME: {(time.time()-t_start)/60:.1f} minutes")
    print(f"Results saved to results/pd_only_*.json")


if __name__ == "__main__":
    main()

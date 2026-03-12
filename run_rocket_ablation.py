#!/usr/bin/env python3
"""run_rocket_ablation.py — ROCKET + FM + Coordination ablation.

Phase 0: MiniROCKET temporal motif features from raw IMU recordings
Phase 1: Cross-sensor coordination features (PLV, coherence, eigenvalues)
Phase 2: Foundation model embeddings (frozen MOMENT-1-base encoder)
Phase 4: Grand integration — combine ROCKET + coordination + v2 handcrafted
Phase 5: PD-only LOOCV with ROCKET
Phase 6: Observable subdomain with ROCKET

Usage:
    python3 -u run_rocket_ablation.py --phase 0     # ROCKET extraction + eval
    python3 -u run_rocket_ablation.py --phase 1     # Coordination extraction + eval
    python3 -u run_rocket_ablation.py --phase 2     # FM embeddings + eval
    python3 -u run_rocket_ablation.py --phase 4     # Grand integration + 10-split
    python3 -u run_rocket_ablation.py --phase 5     # PD-only LOOCV
    python3 -u run_rocket_ablation.py --phase 6     # Observable subdomain
    python3 -u run_rocket_ablation.py --phase all    # Everything
"""
import argparse, os, sys, json, time, warnings
import numpy as np
import pandas as pd
from scipy import signal, stats as sp_stats
from sklearn.metrics import mean_absolute_error
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

from aeon.transformations.collection.convolution_based import MiniRocket
import lightgbm as lgb
from xgboost import XGBRegressor

from project_paths import REPO_ROOT, RESULTS_DIR, ensure_dir, save_json_artifact, results_artifact_path
sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS, _updrs_bin, _get_valid_sids
from updrs_columns import find_updrs_value

# ── Constants ────────────────────────────────────────────────────────
ACC_COLS = ["Acc_X", "Acc_Y", "Acc_Z"]
GYR_COLS = ["Gyr_X", "Gyr_Y", "Gyr_Z"]
TASKS = ["SelfPace", "HurriedPace", "TUG", "TandemGait", "Balance"]
ALL_TASKS = TASKS + [f"{t}_mat" for t in TASKS] + [f"{t}_matTURN" for t in ["SelfPace", "HurriedPace"]]
SEQ_LEN = 1000   # 10s at 100Hz
N_CORES = min(os.cpu_count() or 4, 11)
SEEDS = [42, 123, 456, 789, 2024]
N_ROCKET_KERNELS = 5000

BILATERAL_PAIRS = [
    ("R_Wrist", "L_Wrist"), ("R_Ankle", "L_Ankle"),
    ("R_DorsalFoot", "L_DorsalFoot"), ("R_LatShank", "L_LatShank"),
    ("R_MidLatThigh", "L_MidLatThigh"),
]
TRUNK_LIMB_PAIRS = [
    ("LowerBack", "R_Wrist"), ("LowerBack", "L_Wrist"),
    ("LowerBack", "R_Ankle"), ("LowerBack", "L_Ankle"),
    ("Xiphoid", "R_Wrist"), ("Xiphoid", "L_Wrist"),
]

RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))
COORD_CACHE = str(results_artifact_path("coordination_features.csv"))
V2_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
FM_CACHE = str(results_artifact_path("fm_embeddings.npz"))
FM_MODEL = "AutonLab/MOMENT-1-base"
FM_SEQ_LEN = 512     # MOMENT's native sequence length (512/8=64 patches)
FM_BATCH_SIZE = 32    # GPU batch size for inference
ensure_dir(RESULTS_DIR)


# ═══════════════════════════════════════════════════════════════════════
# RAW RECORDING LOADING
# ═══════════════════════════════════════════════════════════════════════

def _get_csv_path(sid, task, subjects):
    grp = subjects[sid]["group"]
    base = "PD PARTICIPANTS" if grp == "PD" else "CONTROL PARTICIPANTS"
    return os.path.join(DATA_DIR, base, "CSV files", f"{sid}_{task}.csv")


def _load_one_recording(args):
    """Load a single recording as acc+gyro magnitude per sensor.
    Returns: (n_channels, SEQ_LEN) array with 26 channels (13 acc_mag + 13 gyr_mag).
    """
    csv_path, sid, task = args
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None

    channels = []
    for sen in SENSORS:
        # Acc magnitude
        ac = [f"{sen}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in ac):
            vals = np.nan_to_num(df[ac].values.astype(np.float32))
            channels.append(np.sqrt(np.sum(vals**2, axis=1)))
        else:
            channels.append(np.zeros(len(df), dtype=np.float32))
        # Gyr magnitude
        gc = [f"{sen}_{c}" for c in GYR_COLS]
        if all(c in df.columns for c in gc):
            vals = np.nan_to_num(df[gc].values.astype(np.float32))
            channels.append(np.sqrt(np.sum(vals**2, axis=1)))
        else:
            channels.append(np.zeros(len(df), dtype=np.float32))

    # Stack and pad/truncate to SEQ_LEN
    data = np.column_stack(channels)  # (T, 26)
    T = len(data)
    if T > SEQ_LEN:
        data = data[:SEQ_LEN]
    elif T < SEQ_LEN:
        pad = np.zeros((SEQ_LEN - T, data.shape[1]), dtype=np.float32)
        data = np.vstack([data, pad])

    return {"sid": sid, "task": task, "data": data.T}  # (26, SEQ_LEN)


def _extract_coord_one(args):
    """Extract cross-sensor coordination features from one recording."""
    csv_path, sid, task = args
    feats = {"sid": sid, "task": task}
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return feats

    def _sensor_mag(sen, col_group):
        cols = [f"{sen}_{c}" for c in col_group]
        if all(c in df.columns for c in cols):
            return np.sqrt(np.sum(np.nan_to_num(df[cols].values.astype(np.float32))**2, axis=1))
        return None

    # ── 1. PLV + Coherence between bilateral pairs ───────────────────
    for r_sen, l_sen in BILATERAL_PAIRS:
        r_mag = _sensor_mag(r_sen, ACC_COLS)
        l_mag = _sensor_mag(l_sen, ACC_COLS)
        if r_mag is None or l_mag is None or len(r_mag) < 200:
            continue
        n = min(len(r_mag), len(l_mag), 5000)
        r_mag, l_mag = r_mag[:n], l_mag[:n]
        pair = r_sen.replace("R_", "")[:5]

        # Bandpass to locomotion band (0.5-3 Hz), compute PLV
        try:
            b, a = signal.butter(4, [0.5, 3.0], btype='band', fs=FS)
            rf = signal.filtfilt(b, a, r_mag)
            lf = signal.filtfilt(b, a, l_mag)
            rp = np.angle(signal.hilbert(rf))
            lp = np.angle(signal.hilbert(lf))
            plv = float(np.abs(np.mean(np.exp(1j * (rp - lp)))))
            feats[f"crd_plv_{pair}"] = plv
        except Exception:
            pass

        # Coherence in locomotion band
        try:
            f, Cxy = signal.coherence(r_mag, l_mag, fs=FS, nperseg=min(512, n))
            loco = (f >= 0.5) & (f <= 3.0)
            trem = (f >= 3.0) & (f <= 8.0)
            if loco.sum() > 0:
                feats[f"crd_coh_loco_{pair}"] = float(np.max(Cxy[loco]))
            if trem.sum() > 0:
                feats[f"crd_coh_trem_{pair}"] = float(np.max(Cxy[trem]))
        except Exception:
            pass

    # ── 2. Trunk-limb coupling ───────────────────────────────────────
    for trunk, limb in TRUNK_LIMB_PAIRS:
        t_mag = _sensor_mag(trunk, ACC_COLS)
        l_mag = _sensor_mag(limb, ACC_COLS)
        if t_mag is None or l_mag is None or len(t_mag) < 200:
            continue
        n = min(len(t_mag), len(l_mag), 5000)
        t_mag, l_mag = t_mag[:n], l_mag[:n]
        ln = f"{trunk[:4]}_{limb.replace('R_','').replace('L_','')[:5]}"

        try:
            f, Cxy = signal.coherence(t_mag, l_mag, fs=FS, nperseg=min(512, n))
            loco = (f >= 0.5) & (f <= 3.0)
            if loco.sum() > 0:
                feats[f"crd_tl_{ln}"] = float(np.max(Cxy[loco]))
        except Exception:
            pass

    # ── 3. Global coordination: cross-correlation eigenvalues ────────
    sensor_mags = []
    for sen in SENSORS:
        m = _sensor_mag(sen, ACC_COLS)
        if m is not None:
            sensor_mags.append(m[:min(len(m), 3000)])
    if len(sensor_mags) >= 5:
        min_len = min(len(m) for m in sensor_mags)
        M = np.column_stack([m[:min_len] for m in sensor_mags])
        try:
            C = np.corrcoef(M.T)
            C = np.nan_to_num(C, nan=0.0)
            eigvals = np.sort(np.linalg.eigvalsh(C))[::-1]
            eigvals = np.maximum(eigvals, 0)
            total_eig = np.sum(eigvals) + 1e-12
            feats["crd_eig1"] = float(eigvals[0])
            feats["crd_eig_ratio"] = float(eigvals[0] / total_eig)
            feats["crd_eig2"] = float(eigvals[1]) if len(eigvals) > 1 else 0.0
            normed = eigvals / total_eig
            feats["crd_eig_entropy"] = float(-np.sum(normed * np.log(normed + 1e-12)))
            # Effective dimensionality (exponential of entropy)
            feats["crd_eig_effrank"] = float(np.exp(feats["crd_eig_entropy"]))
        except Exception:
            pass

    # ── 4. Gyro coordination (captures rotational coupling) ──────────
    gyro_mags = []
    for sen in SENSORS:
        m = _sensor_mag(sen, GYR_COLS)
        if m is not None:
            gyro_mags.append(m[:min(len(m), 3000)])
    if len(gyro_mags) >= 5:
        min_len = min(len(m) for m in gyro_mags)
        M = np.column_stack([m[:min_len] for m in gyro_mags])
        try:
            C = np.corrcoef(M.T)
            C = np.nan_to_num(C, nan=0.0)
            eigvals = np.sort(np.linalg.eigvalsh(C))[::-1]
            eigvals = np.maximum(eigvals, 0)
            total_eig = np.sum(eigvals) + 1e-12
            feats["crd_g_eig1"] = float(eigvals[0])
            feats["crd_g_eig_ratio"] = float(eigvals[0] / total_eig)
            normed = eigvals / total_eig
            feats["crd_g_eig_entropy"] = float(-np.sum(normed * np.log(normed + 1e-12)))
        except Exception:
            pass

    return feats


def load_all_recordings(subjects, all_sids):
    """Load raw recordings into 3D array + coordination features. Cached."""
    # ── Check caches ─────────────────────────────────────────────────
    have_rec = os.path.exists(RECORDING_CACHE)
    have_coord = os.path.exists(COORD_CACHE)

    if have_rec and have_coord:
        print(f"[cache] Loading recordings from {RECORDING_CACHE}")
        data = np.load(RECORDING_CACHE)
        rec_array = data["recordings"]
        rec_sids = data["sids"].tolist()
        rec_tasks = data["tasks"].tolist()
        coord_df = pd.read_csv(COORD_CACHE)
        print(f"  {len(rec_sids)} recordings, {len(coord_df)} coord rows")
        return rec_array, rec_sids, rec_tasks, coord_df

    # ── Build job list ───────────────────────────────────────────────
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

    # ── Extract recordings (for ROCKET) ──────────────────────────────
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        rec_results = list(pool.map(_load_one_recording, jobs, chunksize=8))
    valid_recs = [r for r in rec_results if r is not None]
    rec_array = np.stack([r["data"] for r in valid_recs])  # (N, 26, SEQ_LEN)
    rec_sids = [r["sid"] for r in valid_recs]
    rec_tasks = [r["task"] for r in valid_recs]
    print(f"  Recordings: {rec_array.shape} in {time.time()-t0:.0f}s")

    # ── Extract coordination features ────────────────────────────────
    print(f"Extracting coordination features...")
    t1 = time.time()
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        coord_results = list(pool.map(_extract_coord_one, jobs, chunksize=8))
    coord_df = pd.DataFrame([r for r in coord_results if r is not None])
    print(f"  Coordination: {coord_df.shape} in {time.time()-t1:.0f}s")

    # ── Cache ────────────────────────────────────────────────────────
    np.savez_compressed(RECORDING_CACHE,
                        recordings=rec_array,
                        sids=np.array(rec_sids),
                        tasks=np.array(rec_tasks))
    coord_df.to_csv(COORD_CACHE, index=False)
    print(f"  Cached to {RECORDING_CACHE} and {COORD_CACHE}")
    print(f"Total loading: {time.time()-t0:.0f}s")

    return rec_array, rec_sids, rec_tasks, coord_df


# ═══════════════════════════════════════════════════════════════════════
# ROCKET FEATURE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════

def rocket_features_for_split(rec_array, rec_sids, dev_sids):
    """Fit MiniRocket on dev recordings, transform all, aggregate per subject."""
    dev_mask = np.array([s in set(dev_sids) for s in rec_sids])

    # Fit on dev only (proper protocol)
    X_dev = rec_array[dev_mask]
    mr = MiniRocket(n_kernels=N_ROCKET_KERNELS, random_state=42, n_jobs=N_CORES)
    mr.fit(X_dev)

    # Transform all
    X_all = mr.transform(rec_array).astype(np.float32)
    n_feat = X_all.shape[1]
    print(f"  ROCKET: {rec_array.shape[0]} recordings -> {n_feat} features")

    # Replace NaN/inf
    X_all = np.nan_to_num(X_all, nan=0.0, posinf=0.0, neginf=0.0)

    # Aggregate per subject (mean across recordings)
    rk_df = pd.DataFrame(X_all, columns=[f"rk_{i}" for i in range(n_feat)])
    rk_df["sid"] = rec_sids
    agg = rk_df.groupby("sid").mean().reset_index()
    return agg


def coord_features_for_subjects(coord_df):
    """Aggregate coordination features per subject."""
    feat_cols = [c for c in coord_df.columns if c.startswith("crd_")]
    if not feat_cols:
        return pd.DataFrame(columns=["sid"])
    agg = coord_df.groupby("sid")[feat_cols].mean().reset_index()
    # Replace NaN/inf
    for c in feat_cols:
        agg[c] = pd.to_numeric(agg[c], errors="coerce").replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return agg


# ═══════════════════════════════════════════════════════════════════════
# EVALUATION MACHINERY
# ═══════════════════════════════════════════════════════════════════════

def feature_select(X, y, names, k=150):
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


def run_eval(name, Xd, yd, Xt, yt, fnames, k=150):
    k = min(k, Xd.shape[1])
    sel_idx, sel_names = feature_select(Xd, yd, fnames, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]
    preds = []
    for seed in SEEDS:
        p, _ = train_lgb(Xds, yd, Xts, seed)
        preds.append(np.clip(p, 0, 132))
    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep)
    er = float(sp_stats.pearsonr(yt, ep)[0]) if len(yt) > 2 else 0.0
    pd_mask = yt > 0
    pd_mae = float(mean_absolute_error(yt[pd_mask], ep[pd_mask])) if pd_mask.sum() > 0 else em
    print(f"  {name}: MAE={em:.3f} r={er:.3f} PD-MAE={pd_mae:.3f} (K={k})")
    return {"config": name, "k": k, "mae": round(em, 3), "r": round(er, 3),
            "pd_mae": round(pd_mae, 3), "top10": sel_names[:10]}


def run_stack(name, Xd, yd, Xt, yt, fnames, k=150):
    k = min(k, Xd.shape[1])
    sel_idx, sel_names = feature_select(Xd, yd, fnames, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]
    preds = []
    for seed in SEEDS:
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        oof_lgb = np.zeros(len(Xds))
        oof_xgb = np.zeros(len(Xds))
        tp_lgb = np.zeros(len(Xts))
        tp_xgb = np.zeros(len(Xts))
        for tr_i, val_i in kf.split(Xds):
            rng = np.random.RandomState(seed + len(tr_i))
            shuf = tr_i.copy(); rng.shuffle(shuf)
            nv = max(1, int(len(shuf)*0.15))
            Xtr, ytr = Xds[shuf[nv:]], yd[shuf[nv:]]
            Xval, yval = Xds[shuf[:nv]], yd[shuf[:nv]]
            # LGB
            m1 = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                                    reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                                    objective="mae", verbose=-1, device="gpu")
            m1.fit(Xtr, ytr, eval_set=[(Xval, yval)], callbacks=[lgb.early_stopping(100, verbose=False)])
            oof_lgb[val_i] = m1.predict(Xds[val_i])
            tp_lgb += m1.predict(Xts) / 5
            # XGB
            m2 = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6, reg_lambda=3.0,
                               random_state=seed, n_jobs=N_CORES, early_stopping_rounds=100,
                               objective="reg:absoluteerror", device="cuda")
            m2.fit(Xtr, ytr, eval_set=[(Xval, yval)], verbose=False)
            oof_xgb[val_i] = m2.predict(Xds[val_i])
            tp_xgb += m2.predict(Xts) / 5
        L0tr = np.column_stack([oof_lgb, oof_xgb])
        L0te = np.column_stack([tp_lgb, tp_xgb])
        meta = Ridge(alpha=1.0); meta.fit(L0tr, yd)
        preds.append(np.clip(meta.predict(L0te), 0, 132))
    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep)
    er = float(sp_stats.pearsonr(yt, ep)[0]) if len(yt) > 2 else 0.0
    pd_mask = yt > 0
    pd_mae = float(mean_absolute_error(yt[pd_mask], ep[pd_mask])) if pd_mask.sum() > 0 else em
    print(f"  {name}: MAE={em:.3f} r={er:.3f} PD-MAE={pd_mae:.3f} (K={k}, stack)")
    return {"config": name, "k": k, "mae": round(em, 3), "r": round(er, 3),
            "pd_mae": round(pd_mae, 3), "top10": sel_names[:10]}


def gen_split(subjects, seed):
    valid = _get_valid_sids(subjects)
    sids = np.array(valid)
    bins = np.array([_updrs_bin(subjects[s]["updrs3"]) for s in sids])
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    di, ti = next(sss.split(sids, bins))
    return sids[di].tolist(), sids[ti].tolist()


def prep_arrays(df, dev_sids, test_sids, cols):
    dm = df["sid"].isin(dev_sids); tm = df["sid"].isin(test_sids)
    Xd = df.loc[dm, cols].values.astype(np.float32)
    yd = df.loc[dm, "updrs3"].values.astype(np.float32)
    Xt = df.loc[tm, cols].values.astype(np.float32)
    yt = df.loc[tm, "updrs3"].values.astype(np.float32)
    return Xd, yd, Xt, yt


# ═══════════════════════════════════════════════════════════════════════
# PHASE 0: MINIROCKET
# ═══════════════════════════════════════════════════════════════════════

def phase0(rec_array, rec_sids, rec_tasks, v2_df, subjects):
    print("\n" + "="*70)
    print("PHASE 0: MiniROCKET temporal motif features")
    print("="*70)
    t0 = time.time()

    # Load v2 feature columns (baseline)
    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_", "obs_subscore"))
               and c != "hy"]
    print(f"V2 baseline: {len(v2_cols)} features")

    results = {"phase": "0_rocket", "splits": [], "k_sweep": []}

    # ── 10-split evaluation ──────────────────────────────────────────
    print("\n--- 10-split validation ---")
    for si, seed in enumerate(range(1, 11)):
        dev_s, test_s = gen_split(subjects, seed)

        # Extract ROCKET features (fit on dev only)
        rk_agg = rocket_features_for_split(rec_array, rec_sids, dev_s)
        rk_cols = [c for c in rk_agg.columns if c.startswith("rk_")]

        # Merge ROCKET with v2
        merged = v2_df[["sid", "updrs3"] + v2_cols].merge(rk_agg, on="sid", how="left").fillna(0.0)
        all_cols = v2_cols + rk_cols

        # Evaluate: v2 only, ROCKET only, v2+ROCKET
        Xd_v2, yd, Xt_v2, yt = prep_arrays(merged, dev_s, test_s, v2_cols)
        Xd_rk, _, Xt_rk, _ = prep_arrays(merged, dev_s, test_s, rk_cols)
        Xd_all, _, Xt_all, _ = prep_arrays(merged, dev_s, test_s, all_cols)

        r_v2 = run_eval(f"s{seed}_v2", Xd_v2, yd, Xt_v2, yt, v2_cols, k=150)
        r_rk = run_eval(f"s{seed}_rocket", Xd_rk, yd, Xt_rk, yt, rk_cols, k=150)
        r_fused = run_eval(f"s{seed}_fused", Xd_all, yd, Xt_all, yt, all_cols, k=400)
        r_stk = run_stack(f"s{seed}_fused_stk", Xd_all, yd, Xt_all, yt, all_cols, k=400)

        split = {"seed": seed, "v2": r_v2, "rocket": r_rk, "fused": r_fused, "fused_stk": r_stk}
        results["splits"].append(split)
        print(f"  [{si+1}/10] v2={r_v2['mae']:.2f} rocket={r_rk['mae']:.2f} "
              f"fused={r_fused['mae']:.2f} stk={r_stk['mae']:.2f}")

    # ── Summary ──────────────────────────────────────────────────────
    for tag in ["v2", "rocket", "fused", "fused_stk"]:
        maes = [s[tag]["mae"] for s in results["splits"]]
        print(f"\n10-split {tag}: {np.mean(maes):.3f} +/- {np.std(maes):.3f}")
    results["summary"] = {}
    for tag in ["v2", "rocket", "fused", "fused_stk"]:
        maes = [s[tag]["mae"] for s in results["splits"]]
        results["summary"][tag] = {"mean": round(np.mean(maes), 3), "std": round(np.std(maes), 3)}

    # Wilcoxon: fused_stk vs v2
    v2_maes = [s["v2"]["mae"] for s in results["splits"]]
    stk_maes = [s["fused_stk"]["mae"] for s in results["splits"]]
    try:
        stat, p = sp_stats.wilcoxon(v2_maes, stk_maes)
        results["wilcoxon_fused_vs_v2"] = {"statistic": round(stat, 3), "p": round(p, 4)}
        print(f"\nWilcoxon fused_stk vs v2: p={p:.4f}")
    except Exception:
        pass

    # ── K sweep on primary split (seed=1) ────────────────────────────
    print("\n--- K sweep (primary split, seed=1) ---")
    dev_s, test_s = gen_split(subjects, 1)
    rk_agg = rocket_features_for_split(rec_array, rec_sids, dev_s)
    rk_cols = [c for c in rk_agg.columns if c.startswith("rk_")]
    merged = v2_df[["sid", "updrs3"] + v2_cols].merge(rk_agg, on="sid", how="left").fillna(0.0)
    all_cols = v2_cols + rk_cols
    Xd, yd, Xt, yt = prep_arrays(merged, dev_s, test_s, all_cols)

    for k in [150, 200, 250, 300, 400, 500, 700]:
        r = run_eval(f"K{k}", Xd, yd, Xt, yt, all_cols, k=k)
        results["k_sweep"].append(r)

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("rocket_phase0.json", results)
    print(f"\nPhase 0 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 1: COORDINATION FEATURES
# ═══════════════════════════════════════════════════════════════════════

def phase1(coord_df, v2_df, subjects):
    print("\n" + "="*70)
    print("PHASE 1: Cross-sensor coordination features")
    print("="*70)
    t0 = time.time()

    # Aggregate coordination per subject
    coord_agg = coord_features_for_subjects(coord_df)
    coord_cols = [c for c in coord_agg.columns if c.startswith("crd_")]
    print(f"Coordination features: {len(coord_cols)}")

    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_", "obs_subscore"))
               and c != "hy"]

    # Merge with v2
    merged = v2_df[["sid", "updrs3"] + v2_cols].merge(coord_agg, on="sid", how="left").fillna(0.0)
    all_cols = v2_cols + coord_cols

    results = {"phase": "1_coordination", "splits": [], "n_coord_features": len(coord_cols)}

    # 10-split validation
    print("\n--- 10-split validation ---")
    for si, seed in enumerate(range(1, 11)):
        dev_s, test_s = gen_split(subjects, seed)
        Xd_v2, yd, Xt_v2, yt = prep_arrays(merged, dev_s, test_s, v2_cols)
        Xd_all, _, Xt_all, _ = prep_arrays(merged, dev_s, test_s, all_cols)

        r_v2 = run_eval(f"s{seed}_v2", Xd_v2, yd, Xt_v2, yt, v2_cols, k=150)
        r_fused = run_eval(f"s{seed}_v2+coord", Xd_all, yd, Xt_all, yt, all_cols, k=175)
        r_stk = run_stack(f"s{seed}_v2+coord_stk", Xd_all, yd, Xt_all, yt, all_cols, k=175)

        results["splits"].append({"seed": seed, "v2": r_v2, "fused": r_fused, "stk": r_stk})
        print(f"  [{si+1}/10] v2={r_v2['mae']:.2f} +coord={r_fused['mae']:.2f} stk={r_stk['mae']:.2f}")

    for tag in ["v2", "fused", "stk"]:
        maes = [s[tag]["mae"] for s in results["splits"]]
        print(f"\n10-split {tag}: {np.mean(maes):.3f} +/- {np.std(maes):.3f}")
        results[f"summary_{tag}"] = {"mean": round(np.mean(maes), 3), "std": round(np.std(maes), 3)}

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("rocket_phase1.json", results)
    print(f"\nPhase 1 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 2: FOUNDATION MODEL EMBEDDINGS (FROZEN MOMENT-1)
# ═══════════════════════════════════════════════════════════════════════

def extract_fm_embeddings(rec_array):
    """Extract frozen MOMENT-1-base embeddings for all recordings.

    Input: rec_array shape (N, 26, 1000) — raw IMU recordings
    Output: (N, d_model) embedding matrix — 768 for MOMENT-1-base

    MOMENT is completely frozen — no training on our data.
    Embeddings are deterministic and cached across splits.
    """
    if os.path.exists(FM_CACHE):
        print(f"[cache] Loading FM embeddings from {FM_CACHE}")
        data = np.load(FM_CACHE)
        return data["embeddings"]

    # Lazy import — only needed for Phase 2
    try:
        import torch
    except ImportError:
        raise RuntimeError("PyTorch required for Phase 2")
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

    # Truncate to FM_SEQ_LEN (512) — MOMENT's native sequence length
    # 512 samples = 5.12s at 100Hz — covers ~2.5 gait cycles
    data = rec_array[:, :, :FM_SEQ_LEN].copy().astype(np.float32)

    # Per-channel z-normalize (critical: raw IMU ±70 crashes models expecting ±1)
    for ch in range(data.shape[1]):
        ch_data = data[:, ch, :].ravel()
        mu = float(np.mean(ch_data))
        std = float(np.std(ch_data)) + 1e-8
        data[:, ch, :] = (data[:, ch, :] - mu) / std

    print(f"  Input: {data.shape} (truncated to {FM_SEQ_LEN}, z-normalized)")

    embeddings = []
    n = len(data)
    t1 = time.time()

    with torch.no_grad():
        for i in range(0, n, FM_BATCH_SIZE):
            batch = data[i:i+FM_BATCH_SIZE]
            x = torch.from_numpy(batch).float().to(device)

            # Input mask: 1 = real data, 0 = zero-padding
            raw_batch = rec_array[i:i+FM_BATCH_SIZE, :, :FM_SEQ_LEN]
            mask = (np.abs(raw_batch).sum(axis=1) > 1e-6).astype(np.float32)
            mask_t = torch.from_numpy(mask).to(device)

            output = model(x_enc=x, input_mask=mask_t)

            emb = output.embeddings
            if emb.dim() == 3:
                emb = emb.mean(dim=1)  # (B, n_channels, d) -> (B, d)
            embeddings.append(emb.cpu().numpy())

            done = min(i + FM_BATCH_SIZE, n)
            if done % (FM_BATCH_SIZE * 10) == 0 or done == n:
                elapsed = time.time() - t1
                rate = done / max(elapsed, 0.1)
                eta = (n - done) / max(rate, 0.1) / 60
                print(f"  FM: {done}/{n} ({elapsed:.0f}s, {rate:.1f} rec/s, ETA={eta:.1f}m)")

    embeddings = np.vstack(embeddings)
    embeddings = np.nan_to_num(embeddings, nan=0.0, posinf=0.0, neginf=0.0)

    np.savez_compressed(FM_CACHE, embeddings=embeddings)
    print(f"  FM embeddings: {embeddings.shape}, cached to {FM_CACHE}")
    print(f"  Extraction time: {(time.time()-t0)/60:.1f}m")

    return embeddings


def fm_features_for_subjects(embeddings, rec_sids):
    """Aggregate FM embeddings per subject (mean across recordings)."""
    d_model = embeddings.shape[1]
    fm_df = pd.DataFrame(embeddings, columns=[f"fm_{i}" for i in range(d_model)])
    fm_df["sid"] = rec_sids
    agg = fm_df.groupby("sid").mean().reset_index()
    return agg


def phase2(rec_array, rec_sids, rec_tasks, v2_df, subjects):
    """Phase 2: Foundation Model Embeddings — frozen MOMENT-1-base encoder."""
    print("\n" + "="*70)
    print("PHASE 2: Foundation Model Embeddings (MOMENT-1-base, frozen)")
    print("="*70)
    t0 = time.time()

    # Extract embeddings (frozen encoder, only need once)
    embeddings = extract_fm_embeddings(rec_array)

    # Aggregate per subject
    fm_agg = fm_features_for_subjects(embeddings, rec_sids)
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]
    print(f"FM features per subject: {len(fm_cols)} (d_model={len(fm_cols)})")

    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_", "obs_subscore"))
               and c != "hy"]
    print(f"V2 baseline: {len(v2_cols)} features")

    results = {"phase": "2_foundation_model", "model": FM_MODEL,
               "d_model": len(fm_cols), "splits": [], "k_sweep": []}

    # ── 10-split validation ──────────────────────────────────────────
    print("\n--- 10-split validation ---")
    for si, seed in enumerate(range(1, 11)):
        dev_s, test_s = gen_split(subjects, seed)

        # Merge FM with v2
        merged = v2_df[["sid", "updrs3"] + v2_cols].merge(fm_agg, on="sid", how="left").fillna(0.0)
        all_cols = v2_cols + fm_cols

        Xd_v2, yd, Xt_v2, yt = prep_arrays(merged, dev_s, test_s, v2_cols)
        Xd_fm, _, Xt_fm, _ = prep_arrays(merged, dev_s, test_s, fm_cols)
        Xd_all, _, Xt_all, _ = prep_arrays(merged, dev_s, test_s, all_cols)

        r_v2 = run_eval(f"s{seed}_v2", Xd_v2, yd, Xt_v2, yt, v2_cols, k=150)
        r_fm = run_eval(f"s{seed}_fm_only", Xd_fm, yd, Xt_fm, yt, fm_cols, k=150)
        r_fused = run_eval(f"s{seed}_v2+fm", Xd_all, yd, Xt_all, yt, all_cols, k=300)
        r_stk = run_stack(f"s{seed}_v2+fm_stk", Xd_all, yd, Xt_all, yt, all_cols, k=300)

        split = {"seed": seed, "v2": r_v2, "fm_only": r_fm, "fused": r_fused, "fused_stk": r_stk}
        results["splits"].append(split)
        print(f"  [{si+1}/10] v2={r_v2['mae']:.2f} fm={r_fm['mae']:.2f} "
              f"fused={r_fused['mae']:.2f} stk={r_stk['mae']:.2f}")

    # ── Summary ──────────────────────────────────────────────────────
    for tag in ["v2", "fm_only", "fused", "fused_stk"]:
        maes = [s[tag]["mae"] for s in results["splits"]]
        results[f"summary_{tag}"] = {"mean": round(np.mean(maes), 3), "std": round(np.std(maes), 3)}
        print(f"\n10-split {tag}: {np.mean(maes):.3f} +/- {np.std(maes):.3f}")

    # Wilcoxon: fused_stk vs v2
    v2_maes = [s["v2"]["mae"] for s in results["splits"]]
    stk_maes = [s["fused_stk"]["mae"] for s in results["splits"]]
    try:
        stat, p = sp_stats.wilcoxon(v2_maes, stk_maes)
        results["wilcoxon_fused_vs_v2"] = {"statistic": round(stat, 3), "p": round(p, 4)}
        print(f"\nWilcoxon fused_stk vs v2: p={p:.4f}")
    except Exception:
        pass

    # ── K sweep on primary split (seed=1) ────────────────────────────
    print("\n--- K sweep (primary split, seed=1) ---")
    dev_s, test_s = gen_split(subjects, 1)
    merged = v2_df[["sid", "updrs3"] + v2_cols].merge(fm_agg, on="sid", how="left").fillna(0.0)
    all_cols = v2_cols + fm_cols
    Xd, yd, Xt, yt = prep_arrays(merged, dev_s, test_s, all_cols)

    for k in [100, 150, 200, 300, 400, 500]:
        r = run_eval(f"K{k}", Xd, yd, Xt, yt, all_cols, k=k)
        results["k_sweep"].append(r)

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("rocket_phase2_fm.json", results)
    print(f"\nPhase 2 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 4: GRAND INTEGRATION
# ═══════════════════════════════════════════════════════════════════════

def phase4(rec_array, rec_sids, rec_tasks, coord_df, v2_df, subjects):
    print("\n" + "="*70)
    print("PHASE 4: Grand integration — ROCKET + Coordination + v2")
    print("="*70)
    t0 = time.time()

    coord_agg = coord_features_for_subjects(coord_df)
    coord_cols = [c for c in coord_agg.columns if c.startswith("crd_")]

    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_", "obs_subscore"))
               and c != "hy"]

    results = {"phase": "4_grand", "splits": [], "k_sweep": []}

    print("\n--- 10-split validation ---")
    for si, seed in enumerate(range(1, 11)):
        dev_s, test_s = gen_split(subjects, seed)

        # ROCKET features (fit on dev only)
        rk_agg = rocket_features_for_split(rec_array, rec_sids, dev_s)
        rk_cols = [c for c in rk_agg.columns if c.startswith("rk_")]

        # Merge all
        merged = v2_df[["sid", "updrs3"] + v2_cols].copy()
        merged = merged.merge(rk_agg, on="sid", how="left").fillna(0.0)
        merged = merged.merge(coord_agg, on="sid", how="left").fillna(0.0)
        grand_cols = v2_cols + rk_cols + coord_cols

        Xd_v2, yd, Xt_v2, yt = prep_arrays(merged, dev_s, test_s, v2_cols)
        Xd_grand, _, Xt_grand, _ = prep_arrays(merged, dev_s, test_s, grand_cols)

        r_v2 = run_eval(f"s{seed}_v2", Xd_v2, yd, Xt_v2, yt, v2_cols, k=150)
        r_grand_lgb = run_eval(f"s{seed}_grand", Xd_grand, yd, Xt_grand, yt, grand_cols, k=250)
        r_grand_stk = run_stack(f"s{seed}_grand_stk", Xd_grand, yd, Xt_grand, yt, grand_cols, k=250)

        results["splits"].append({"seed": seed, "v2": r_v2, "grand": r_grand_lgb, "grand_stk": r_grand_stk})
        print(f"  [{si+1}/10] v2={r_v2['mae']:.2f} grand={r_grand_lgb['mae']:.2f} stk={r_grand_stk['mae']:.2f}")

    # Summary
    for tag in ["v2", "grand", "grand_stk"]:
        maes = [s[tag]["mae"] for s in results["splits"]]
        print(f"\n10-split {tag}: {np.mean(maes):.3f} +/- {np.std(maes):.3f}")
        results[f"summary_{tag}"] = {"mean": round(np.mean(maes), 3), "std": round(np.std(maes), 3)}

    # Wilcoxon
    v2_maes = [s["v2"]["mae"] for s in results["splits"]]
    stk_maes = [s["grand_stk"]["mae"] for s in results["splits"]]
    try:
        stat, p = sp_stats.wilcoxon(v2_maes, stk_maes)
        results["wilcoxon_grand_vs_v2"] = {"statistic": round(stat, 3), "p": round(p, 4)}
        print(f"\nWilcoxon grand_stk vs v2: p={p:.4f}")
    except Exception:
        pass

    # K sweep on primary split
    print("\n--- K sweep (primary split, seed=1) ---")
    dev_s, test_s = gen_split(subjects, 1)
    rk_agg = rocket_features_for_split(rec_array, rec_sids, dev_s)
    rk_cols = [c for c in rk_agg.columns if c.startswith("rk_")]
    merged = v2_df[["sid", "updrs3"] + v2_cols].copy()
    merged = merged.merge(rk_agg, on="sid", how="left").fillna(0.0)
    merged = merged.merge(coord_agg, on="sid", how="left").fillna(0.0)
    grand_cols = v2_cols + rk_cols + coord_cols
    Xd, yd, Xt, yt = prep_arrays(merged, dev_s, test_s, grand_cols)

    for k in [150, 200, 250, 300, 400, 500]:
        r_lgb = run_eval(f"K{k}_lgb", Xd, yd, Xt, yt, grand_cols, k=k)
        r_stk = run_stack(f"K{k}_stk", Xd, yd, Xt, yt, grand_cols, k=k)
        results["k_sweep"].append({"k": k, "lgb": r_lgb, "stk": r_stk})

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("rocket_phase4.json", results)
    print(f"\nPhase 4 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 5: PD-ONLY LOOCV WITH ROCKET
# ═══════════════════════════════════════════════════════════════════════

def phase5_loocv(rec_array, rec_sids, rec_tasks, v2_df, subjects):
    """PD-only LOOCV for direct comparison with Hssayeni (MAE=5.95, r=0.74)."""
    print("\n" + "="*70)
    print("PHASE 5: PD-only LOOCV with ROCKET features")
    print("="*70)
    t0 = time.time()

    # Get PD subjects only
    all_sids = sorted(_get_valid_sids(subjects))
    pd_sids = [s for s in all_sids if subjects[s]["group"] == "PD"]
    print(f"PD subjects: {len(pd_sids)}")

    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_", "obs_subscore"))
               and c != "hy"]

    rec_sids_set = set(rec_sids)
    rec_sids_arr = np.array(rec_sids)

    results = {"phase": "5_pd_loocv", "predictions": [], "k": 400}
    y_true, y_pred_v2, y_pred_fused = [], [], []

    for i, loo_sid in enumerate(pd_sids):
        t1 = time.time()
        dev_sids = [s for s in all_sids if s != loo_sid]

        # --- ROCKET features (fit on dev, transform all) ---
        dev_mask = np.array([s in set(dev_sids) for s in rec_sids])
        mr = MiniRocket(n_kernels=N_ROCKET_KERNELS, random_state=42, n_jobs=N_CORES)
        mr.fit(rec_array[dev_mask])
        X_all_rk = mr.transform(rec_array).astype(np.float32)
        X_all_rk = np.nan_to_num(X_all_rk, nan=0.0, posinf=0.0, neginf=0.0)
        n_feat = X_all_rk.shape[1]

        rk_df = pd.DataFrame(X_all_rk, columns=[f"rk_{j}" for j in range(n_feat)])
        rk_df["sid"] = rec_sids
        rk_agg = rk_df.groupby("sid").mean().reset_index()
        rk_cols = [c for c in rk_agg.columns if c.startswith("rk_")]

        # Merge with v2
        merged = v2_df[["sid", "updrs3"] + v2_cols].merge(rk_agg, on="sid", how="left").fillna(0.0)
        all_cols = v2_cols + rk_cols

        # Prep arrays
        Xd, yd, Xt, yt = prep_arrays(merged, dev_sids, [loo_sid], all_cols)
        Xd_v2, _, Xt_v2, _ = prep_arrays(merged, dev_sids, [loo_sid], v2_cols)

        if len(Xt) == 0 or len(yt) == 0:
            print(f"  [{i+1}/{len(pd_sids)}] {loo_sid}: SKIP (no data)")
            continue

        true_val = float(yt[0])

        # v2-only prediction (LGB ensemble)
        k_v2 = min(150, Xd_v2.shape[1])
        sel_idx_v2, _ = feature_select(Xd_v2, yd, v2_cols, k_v2)
        Xds_v2, Xts_v2 = Xd_v2[:, sel_idx_v2], Xt_v2[:, sel_idx_v2]
        preds_v2 = []
        for seed in SEEDS:
            p, _ = train_lgb(Xds_v2, yd, Xts_v2, seed)
            preds_v2.append(np.clip(p, 0, 132))
        pred_v2 = float(np.mean(preds_v2))

        # Fused stack prediction
        k_fused = min(400, Xd.shape[1])
        sel_idx, sel_names = feature_select(Xd, yd, all_cols, k_fused)
        Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]
        preds_stk = []
        for seed in SEEDS:
            kf = KFold(n_splits=5, shuffle=True, random_state=seed)
            oof_lgb = np.zeros(len(Xds))
            oof_xgb = np.zeros(len(Xds))
            tp_lgb = np.zeros(len(Xts))
            tp_xgb = np.zeros(len(Xts))
            for tr_i, val_i in kf.split(Xds):
                rng = np.random.RandomState(seed + len(tr_i))
                shuf = tr_i.copy(); rng.shuffle(shuf)
                nv = max(1, int(len(shuf)*0.15))
                Xtr, ytr = Xds[shuf[nv:]], yd[shuf[nv:]]
                Xval, yval = Xds[shuf[:nv]], yd[shuf[:nv]]
                m1 = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                                        reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                                        objective="mae", verbose=-1, device="gpu")
                m1.fit(Xtr, ytr, eval_set=[(Xval, yval)], callbacks=[lgb.early_stopping(100, verbose=False)])
                oof_lgb[val_i] = m1.predict(Xds[val_i])
                tp_lgb += m1.predict(Xts) / 5
                m2 = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6, reg_lambda=3.0,
                                   random_state=seed, n_jobs=N_CORES, early_stopping_rounds=100,
                                   objective="reg:absoluteerror", device="cuda")
                m2.fit(Xtr, ytr, eval_set=[(Xval, yval)], verbose=False)
                oof_xgb[val_i] = m2.predict(Xds[val_i])
                tp_xgb += m2.predict(Xts) / 5
            L0tr = np.column_stack([oof_lgb, oof_xgb])
            L0te = np.column_stack([tp_lgb, tp_xgb])
            meta = Ridge(alpha=1.0); meta.fit(L0tr, yd)
            preds_stk.append(float(np.clip(meta.predict(L0te), 0, 132)[0]))
        pred_fused = float(np.mean(preds_stk))

        y_true.append(true_val)
        y_pred_v2.append(pred_v2)
        y_pred_fused.append(pred_fused)
        results["predictions"].append({
            "sid": loo_sid, "true": true_val, "pred_v2": round(pred_v2, 2),
            "pred_fused": round(pred_fused, 2)
        })

        elapsed = time.time() - t1
        if (i+1) % 5 == 0 or i == 0:
            v2_mae_so_far = float(np.mean(np.abs(np.array(y_true) - np.array(y_pred_v2))))
            fused_mae_so_far = float(np.mean(np.abs(np.array(y_true) - np.array(y_pred_fused))))
            eta = elapsed * (len(pd_sids) - i - 1) / 60
            print(f"  [{i+1}/{len(pd_sids)}] {loo_sid}: true={true_val:.0f} v2={pred_v2:.1f} fused={pred_fused:.1f} "
                  f"({elapsed:.0f}s) running_v2_MAE={v2_mae_so_far:.2f} running_fused_MAE={fused_mae_so_far:.2f} ETA={eta:.0f}m")

    # Final metrics
    y_true, y_pred_v2, y_pred_fused = np.array(y_true), np.array(y_pred_v2), np.array(y_pred_fused)
    v2_mae = float(mean_absolute_error(y_true, y_pred_v2))
    v2_r = float(sp_stats.pearsonr(y_true, y_pred_v2)[0])
    fused_mae = float(mean_absolute_error(y_true, y_pred_fused))
    fused_r = float(sp_stats.pearsonr(y_true, y_pred_fused)[0])

    print(f"\n=== PD-only LOOCV Results (N={len(y_true)}) ===")
    print(f"v2-only:      MAE={v2_mae:.3f}  r={v2_r:.3f}")
    print(f"ROCKET-fused: MAE={fused_mae:.3f}  r={fused_r:.3f}")
    print(f"Hssayeni ref: MAE=5.95   r=0.74")

    results["v2"] = {"mae": round(v2_mae, 3), "r": round(v2_r, 3)}
    results["fused_stk"] = {"mae": round(fused_mae, 3), "r": round(fused_r, 3)}
    results["n_pd"] = len(y_true)
    results["runtime_s"] = round(time.time() - t0, 1)

    # Bootstrap CI
    n_boot = 2000
    boot_maes = []
    for _ in range(n_boot):
        idx = np.random.choice(len(y_true), len(y_true), replace=True)
        boot_maes.append(float(mean_absolute_error(y_true[idx], y_pred_fused[idx])))
    ci_lo, ci_hi = np.percentile(boot_maes, [2.5, 97.5])
    results["fused_stk"]["ci_95"] = [round(ci_lo, 2), round(ci_hi, 2)]
    print(f"Fused 95% CI: [{ci_lo:.2f}, {ci_hi:.2f}]")

    save_json_artifact("rocket_loocv.json", results)
    print(f"\nPhase 5 LOOCV done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 6: OBSERVABLE SUBDOMAIN WITH ROCKET
# ═══════════════════════════════════════════════════════════════════════

OBSERVABLE_ITEMS = [7, 8, 9, 10, 11, 12, 13, 14]
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


def observable_score(item_scores_dict, sid):
    """Sum of observable items 7-14 for a subject. Returns None if any missing."""
    if sid not in item_scores_dict:
        return None
    total = 0.0
    for item in OBSERVABLE_ITEMS:
        if item not in item_scores_dict[sid]:
            return None
        total += item_scores_dict[sid][item]
    return total


def phase6_observable(rec_array, rec_sids, rec_tasks, v2_df, subjects):
    """10-split validation of ROCKET features on observable subdomain (items 7-14)."""
    print("\n" + "="*70)
    print("PHASE 6: Observable subdomain (items 7-14) with ROCKET")
    print("="*70)
    t0 = time.time()

    item_scores = parse_item_scores()
    all_sids = sorted(_get_valid_sids(subjects))

    # Build observable target column
    obs_targets = {}
    for sid in all_sids:
        obs = observable_score(item_scores, sid)
        if obs is not None:
            obs_targets[sid] = obs
    print(f"Subjects with observable scores: {len(obs_targets)}/{len(all_sids)}")

    # v2 features
    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_", "obs_subscore"))
               and c != "hy"]

    # Add observable target to v2_df
    v2_obs = v2_df.copy()
    v2_obs["obs_target"] = v2_obs["sid"].map(obs_targets)
    v2_obs = v2_obs.dropna(subset=["obs_target"])
    obs_sids = set(v2_obs["sid"].values)
    print(f"Subjects with v2 features + observable target: {len(obs_sids)}")

    # Observable target range for K calibration (matches run_subdomain_v3 adaptive_k)
    obs_max = v2_obs["obs_target"].max()
    k_obs = 150  # range 0-40, adaptive_k(40)=150
    k_fused = 300  # allow more features from ROCKET pool
    print(f"Observable max: {obs_max:.0f}, v2 K={k_obs}, fused K={k_fused}")

    results = {"phase": "6_observable", "splits": [], "k_v2": k_obs, "k_fused": k_fused}

    # Filter subjects to those with observable scores
    obs_subjects = {s: subjects[s] for s in obs_sids if s in subjects}

    print("\n--- 10-split validation (observable target: items 7-14) ---")
    for si, seed in enumerate(range(1, 11)):
        dev_s, test_s = gen_split(obs_subjects, seed)

        # ROCKET features (fit on dev only)
        rk_agg = rocket_features_for_split(rec_array, rec_sids, dev_s)
        rk_cols = [c for c in rk_agg.columns if c.startswith("rk_")]

        # Merge
        merged = v2_obs[["sid", "obs_target"] + v2_cols].merge(rk_agg, on="sid", how="left").fillna(0.0)
        all_cols = v2_cols + rk_cols

        # Prep arrays with observable target
        dev_mask = merged["sid"].isin(dev_s)
        test_mask = merged["sid"].isin(test_s)
        Xd_v2 = merged.loc[dev_mask, v2_cols].values.astype(np.float32)
        Xt_v2 = merged.loc[test_mask, v2_cols].values.astype(np.float32)
        Xd_all = merged.loc[dev_mask, all_cols].values.astype(np.float32)
        Xt_all = merged.loc[test_mask, all_cols].values.astype(np.float32)
        yd = merged.loc[dev_mask, "obs_target"].values.astype(np.float32)
        yt = merged.loc[test_mask, "obs_target"].values.astype(np.float32)

        # v2-only LGB
        r_v2 = run_eval(f"obs_s{seed}_v2", Xd_v2, yd, Xt_v2, yt, v2_cols, k=k_obs)
        # v2+ROCKET LGB
        r_fused = run_eval(f"obs_s{seed}_fused", Xd_all, yd, Xt_all, yt, all_cols, k=k_fused)
        # v2+ROCKET Stack
        r_stk = run_stack(f"obs_s{seed}_fused_stk", Xd_all, yd, Xt_all, yt, all_cols, k=k_fused)

        results["splits"].append({"seed": seed, "v2": r_v2, "fused": r_fused, "stk": r_stk})
        print(f"  [{si+1}/10] v2={r_v2['mae']:.2f} fused={r_fused['mae']:.2f} stk={r_stk['mae']:.2f}")

    # Summary
    for tag in ["v2", "fused", "stk"]:
        maes = [s[tag]["mae"] for s in results["splits"]]
        results[f"summary_{tag}"] = {"mean": round(np.mean(maes), 3), "std": round(np.std(maes), 3)}
        print(f"\n10-split {tag}: {np.mean(maes):.3f} +/- {np.std(maes):.3f}")

    # Wilcoxon: stk vs v2
    v2_maes = [s["v2"]["mae"] for s in results["splits"]]
    stk_maes = [s["stk"]["mae"] for s in results["splits"]]
    _, p_val = sp_stats.wilcoxon(stk_maes, v2_maes, alternative="less")
    results["wilcoxon_stk_vs_v2"] = round(p_val, 4)
    print(f"\nWilcoxon stk vs v2: p={p_val:.4f}")

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("rocket_phase6_observable.json", results)
    print(f"\nPhase 6 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 7: ULTIMATE GRAND INTEGRATION (v2 + ROCKET + FM + COORD)
# ═══════════════════════════════════════════════════════════════════════

def phase7_ultimate(rec_array, rec_sids, rec_tasks, coord_df, v2_df, subjects):
    """Ultimate grand integration: v2 + ROCKET + FM embeddings + coordination."""
    print("\n" + "="*70)
    print("PHASE 7: Ultimate Grand — v2 + ROCKET + MOMENT + Coordination")
    print("="*70)
    t0 = time.time()

    # FM embeddings (frozen, cached)
    fm_embeddings = extract_fm_embeddings(rec_array)
    fm_agg = fm_features_for_subjects(fm_embeddings, rec_sids)
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]

    # Coordination features
    coord_agg = coord_features_for_subjects(coord_df)
    coord_cols = [c for c in coord_agg.columns if c.startswith("crd_")]

    # v2 handcrafted
    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_", "obs_subscore"))
               and c != "hy"]

    print(f"Feature groups: v2={len(v2_cols)}, FM={len(fm_cols)}, coord={len(coord_cols)}")
    print(f"ROCKET features extracted per split (fit on dev only)")

    results = {"phase": "7_ultimate", "splits": [], "k_sweep": []}

    # ── 10-split validation ──────────────────────────────────────────
    print("\n--- 10-split validation ---")
    for si, seed in enumerate(range(1, 11)):
        dev_s, test_s = gen_split(subjects, seed)

        # ROCKET features (fit on dev only)
        rk_agg = rocket_features_for_split(rec_array, rec_sids, dev_s)
        rk_cols = [c for c in rk_agg.columns if c.startswith("rk_")]

        # Merge all feature groups
        merged = v2_df[["sid", "updrs3"] + v2_cols].copy()
        merged = merged.merge(rk_agg, on="sid", how="left").fillna(0.0)
        merged = merged.merge(fm_agg, on="sid", how="left").fillna(0.0)
        merged = merged.merge(coord_agg, on="sid", how="left").fillna(0.0)

        # Feature sets for comparison
        ultimate_cols = v2_cols + rk_cols + fm_cols + coord_cols
        v2_fm_cols = v2_cols + fm_cols           # Phase 2 winner
        v2_rk_cols = v2_cols + rk_cols           # Phase 0 winner
        v2_rk_fm_cols = v2_cols + rk_cols + fm_cols  # Triple fusion (no coord)

        Xd_v2, yd, Xt_v2, yt = prep_arrays(merged, dev_s, test_s, v2_cols)
        Xd_fm, _, Xt_fm, _ = prep_arrays(merged, dev_s, test_s, v2_fm_cols)
        Xd_rk, _, Xt_rk, _ = prep_arrays(merged, dev_s, test_s, v2_rk_cols)
        Xd_triple, _, Xt_triple, _ = prep_arrays(merged, dev_s, test_s, v2_rk_fm_cols)
        Xd_ult, _, Xt_ult, _ = prep_arrays(merged, dev_s, test_s, ultimate_cols)

        r_v2 = run_eval(f"s{seed}_v2", Xd_v2, yd, Xt_v2, yt, v2_cols, k=150)
        r_fm_stk = run_stack(f"s{seed}_v2+fm", Xd_fm, yd, Xt_fm, yt, v2_fm_cols, k=300)
        r_rk_stk = run_stack(f"s{seed}_v2+rk", Xd_rk, yd, Xt_rk, yt, v2_rk_cols, k=400)
        r_triple = run_stack(f"s{seed}_triple", Xd_triple, yd, Xt_triple, yt, v2_rk_fm_cols, k=400)
        r_ult = run_stack(f"s{seed}_ultimate", Xd_ult, yd, Xt_ult, yt, ultimate_cols, k=400)

        split = {"seed": seed, "v2": r_v2, "v2_fm_stk": r_fm_stk, "v2_rk_stk": r_rk_stk,
                 "triple_stk": r_triple, "ultimate_stk": r_ult}
        results["splits"].append(split)
        print(f"  [{si+1}/10] v2={r_v2['mae']:.2f} fm={r_fm_stk['mae']:.2f} "
              f"rk={r_rk_stk['mae']:.2f} triple={r_triple['mae']:.2f} ult={r_ult['mae']:.2f}")

    # ── Summary ──────────────────────────────────────────────────────
    for tag in ["v2", "v2_fm_stk", "v2_rk_stk", "triple_stk", "ultimate_stk"]:
        maes = [s[tag]["mae"] for s in results["splits"]]
        results[f"summary_{tag}"] = {"mean": round(np.mean(maes), 3), "std": round(np.std(maes), 3)}
        print(f"\n10-split {tag}: {np.mean(maes):.3f} +/- {np.std(maes):.3f}")

    # Wilcoxon tests
    v2_maes = [s["v2"]["mae"] for s in results["splits"]]
    for tag, label in [("v2_fm_stk", "v2+FM"), ("triple_stk", "triple"), ("ultimate_stk", "ultimate")]:
        tag_maes = [s[tag]["mae"] for s in results["splits"]]
        try:
            stat, p = sp_stats.wilcoxon(v2_maes, tag_maes)
            results[f"wilcoxon_{tag}_vs_v2"] = {"statistic": round(stat, 3), "p": round(p, 4)}
            print(f"\nWilcoxon {label} vs v2: p={p:.4f}")
        except Exception:
            pass

    # Wilcoxon: triple vs FM-only
    fm_maes = [s["v2_fm_stk"]["mae"] for s in results["splits"]]
    triple_maes = [s["triple_stk"]["mae"] for s in results["splits"]]
    try:
        stat, p = sp_stats.wilcoxon(fm_maes, triple_maes)
        results["wilcoxon_triple_vs_fm"] = {"statistic": round(stat, 3), "p": round(p, 4)}
        print(f"\nWilcoxon triple vs FM-only: p={p:.4f}")
    except Exception:
        pass

    # ── K sweep on primary split (seed=1) ────────────────────────────
    print("\n--- K sweep (primary split, seed=1) ---")
    dev_s, test_s = gen_split(subjects, 1)
    rk_agg = rocket_features_for_split(rec_array, rec_sids, dev_s)
    rk_cols = [c for c in rk_agg.columns if c.startswith("rk_")]
    merged = v2_df[["sid", "updrs3"] + v2_cols].copy()
    merged = merged.merge(rk_agg, on="sid", how="left").fillna(0.0)
    merged = merged.merge(fm_agg, on="sid", how="left").fillna(0.0)
    merged = merged.merge(coord_agg, on="sid", how="left").fillna(0.0)

    triple_cols = v2_cols + rk_cols + fm_cols
    Xd, yd, Xt, yt = prep_arrays(merged, dev_s, test_s, triple_cols)
    for k in [200, 300, 400, 500, 600, 700]:
        r_lgb = run_eval(f"K{k}_lgb", Xd, yd, Xt, yt, triple_cols, k=k)
        r_stk = run_stack(f"K{k}_stk", Xd, yd, Xt, yt, triple_cols, k=k)
        results["k_sweep"].append({"k": k, "lgb": r_lgb, "stk": r_stk})

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("rocket_phase7_ultimate.json", results)
    print(f"\nPhase 7 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 8: PD-ONLY LOOCV WITH FM EMBEDDINGS
# ═══════════════════════════════════════════════════════════════════════

def phase8_fm_loocv(rec_array, rec_sids, rec_tasks, v2_df, subjects):
    """PD-only LOOCV with frozen FM embeddings for Hssayeni comparison."""
    print("\n" + "="*70)
    print("PHASE 8: PD-only LOOCV with FM embeddings (MOMENT-1-base)")
    print("="*70)
    t0 = time.time()

    # FM embeddings (frozen, pre-cached — no refit needed per LOO iteration)
    fm_embeddings = extract_fm_embeddings(rec_array)
    fm_agg = fm_features_for_subjects(fm_embeddings, rec_sids)
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]

    # Get PD subjects
    all_sids = sorted(_get_valid_sids(subjects))
    pd_sids = [s for s in all_sids if subjects[s]["group"] == "PD"]
    print(f"PD subjects: {len(pd_sids)}, FM features: {len(fm_cols)}")

    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_", "obs_subscore"))
               and c != "hy"]

    # Merge v2 + FM once (frozen embeddings don't change per split)
    merged = v2_df[["sid", "updrs3"] + v2_cols].merge(fm_agg, on="sid", how="left").fillna(0.0)
    all_cols = v2_cols + fm_cols

    results = {"phase": "8_fm_loocv", "predictions": [], "k_v2": 150, "k_fused": 300}
    y_true, y_pred_v2, y_pred_fused = [], [], []

    for i, loo_sid in enumerate(pd_sids):
        t1 = time.time()
        dev_sids = [s for s in all_sids if s != loo_sid]

        # Prep arrays
        Xd, yd, Xt, yt = prep_arrays(merged, dev_sids, [loo_sid], all_cols)
        Xd_v2, _, Xt_v2, _ = prep_arrays(merged, dev_sids, [loo_sid], v2_cols)

        if len(Xt) == 0 or len(yt) == 0:
            print(f"  [{i+1}/{len(pd_sids)}] {loo_sid}: SKIP (no data)")
            continue

        true_val = float(yt[0])

        # v2-only prediction (LGB ensemble)
        k_v2 = min(150, Xd_v2.shape[1])
        sel_idx_v2, _ = feature_select(Xd_v2, yd, v2_cols, k_v2)
        Xds_v2, Xts_v2 = Xd_v2[:, sel_idx_v2], Xt_v2[:, sel_idx_v2]
        preds_v2 = []
        for seed in SEEDS:
            p, _ = train_lgb(Xds_v2, yd, Xts_v2, seed)
            preds_v2.append(np.clip(p, 0, 132))
        pred_v2 = float(np.mean(preds_v2))

        # FM fused stack prediction
        k_fused = min(300, Xd.shape[1])
        sel_idx, _ = feature_select(Xd, yd, all_cols, k_fused)
        Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]
        preds_stk = []
        for seed in SEEDS:
            kf = KFold(n_splits=5, shuffle=True, random_state=seed)
            oof_lgb = np.zeros(len(Xds))
            oof_xgb = np.zeros(len(Xds))
            tp_lgb = np.zeros(len(Xts))
            tp_xgb = np.zeros(len(Xts))
            for tr_i, val_i in kf.split(Xds):
                rng = np.random.RandomState(seed + len(tr_i))
                shuf = tr_i.copy(); rng.shuffle(shuf)
                nv = max(1, int(len(shuf)*0.15))
                Xtr, ytr = Xds[shuf[nv:]], yd[shuf[nv:]]
                Xval, yval = Xds[shuf[:nv]], yd[shuf[:nv]]
                m1 = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                                        reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                                        objective="mae", verbose=-1, device="gpu")
                m1.fit(Xtr, ytr, eval_set=[(Xval, yval)], callbacks=[lgb.early_stopping(100, verbose=False)])
                oof_lgb[val_i] = m1.predict(Xds[val_i])
                tp_lgb += m1.predict(Xts) / 5
                m2 = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6, reg_lambda=3.0,
                                   random_state=seed, n_jobs=N_CORES, early_stopping_rounds=100,
                                   objective="reg:absoluteerror", device="cuda")
                m2.fit(Xtr, ytr, eval_set=[(Xval, yval)], verbose=False)
                oof_xgb[val_i] = m2.predict(Xds[val_i])
                tp_xgb += m2.predict(Xts) / 5
            L0tr = np.column_stack([oof_lgb, oof_xgb])
            L0te = np.column_stack([tp_lgb, tp_xgb])
            meta = Ridge(alpha=1.0); meta.fit(L0tr, yd)
            preds_stk.append(float(np.clip(meta.predict(L0te), 0, 132)[0]))
        pred_fused = float(np.mean(preds_stk))

        y_true.append(true_val)
        y_pred_v2.append(pred_v2)
        y_pred_fused.append(pred_fused)
        results["predictions"].append({
            "sid": loo_sid, "true": true_val, "pred_v2": round(pred_v2, 2),
            "pred_fm": round(pred_fused, 2)
        })

        elapsed = time.time() - t1
        if (i+1) % 5 == 0 or i == 0:
            v2_mae_so_far = float(np.mean(np.abs(np.array(y_true) - np.array(y_pred_v2))))
            fm_mae_so_far = float(np.mean(np.abs(np.array(y_true) - np.array(y_pred_fused))))
            eta = elapsed * (len(pd_sids) - i - 1) / 60
            print(f"  [{i+1}/{len(pd_sids)}] {loo_sid}: true={true_val:.0f} v2={pred_v2:.1f} fm={pred_fused:.1f} "
                  f"({elapsed:.0f}s) v2_MAE={v2_mae_so_far:.2f} fm_MAE={fm_mae_so_far:.2f} ETA={eta:.0f}m")

    # Final metrics
    y_true, y_pred_v2, y_pred_fused = np.array(y_true), np.array(y_pred_v2), np.array(y_pred_fused)
    v2_mae = float(mean_absolute_error(y_true, y_pred_v2))
    v2_r = float(sp_stats.pearsonr(y_true, y_pred_v2)[0])
    fm_mae = float(mean_absolute_error(y_true, y_pred_fused))
    fm_r = float(sp_stats.pearsonr(y_true, y_pred_fused)[0])

    print(f"\n=== PD-only LOOCV Results (N={len(y_true)}) ===")
    print(f"v2-only:  MAE={v2_mae:.3f}  r={v2_r:.3f}")
    print(f"FM-fused: MAE={fm_mae:.3f}  r={fm_r:.3f}")
    print(f"Hssayeni: MAE=5.95   r=0.74")
    print(f"ROCKET LOOCV ref: MAE=8.223  r=0.405")

    # Wilcoxon
    errors_v2 = np.abs(y_true - y_pred_v2)
    errors_fm = np.abs(y_true - y_pred_fused)
    stat, p = sp_stats.wilcoxon(errors_v2, errors_fm)
    wins = int(np.sum(errors_fm < errors_v2))
    print(f"Wilcoxon: p={p:.4f}, FM wins {wins}/{len(y_true)} subjects")

    results["v2"] = {"mae": round(v2_mae, 3), "r": round(v2_r, 3)}
    results["fm_stk"] = {"mae": round(fm_mae, 3), "r": round(fm_r, 3)}
    results["wilcoxon"] = {"statistic": round(stat, 3), "p": round(p, 4)}
    results["fm_wins"] = wins
    results["n_pd"] = len(y_true)

    # Bootstrap CI
    n_boot = 2000
    boot_maes = []
    for _ in range(n_boot):
        idx = np.random.choice(len(y_true), len(y_true), replace=True)
        boot_maes.append(float(mean_absolute_error(y_true[idx], y_pred_fused[idx])))
    ci_lo, ci_hi = np.percentile(boot_maes, [2.5, 97.5])
    results["fm_stk"]["ci_95"] = [round(ci_lo, 2), round(ci_hi, 2)]
    print(f"FM 95% CI: [{ci_lo:.2f}, {ci_hi:.2f}]")

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("rocket_phase8_fm_loocv.json", results)
    print(f"\nPhase 8 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# PHASE 9: OBSERVABLE SUBDOMAIN WITH FM EMBEDDINGS
# ═══════════════════════════════════════════════════════════════════════

def phase9_fm_observable(rec_array, rec_sids, rec_tasks, v2_df, subjects):
    """10-split validation of FM embeddings on observable subdomain (items 7-14)."""
    print("\n" + "="*70)
    print("PHASE 9: Observable subdomain (items 7-14) with FM embeddings")
    print("="*70)
    t0 = time.time()

    # FM embeddings (frozen, pre-cached)
    fm_embeddings = extract_fm_embeddings(rec_array)
    fm_agg = fm_features_for_subjects(fm_embeddings, rec_sids)
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]

    item_scores = parse_item_scores()
    all_sids = sorted(_get_valid_sids(subjects))

    # Build observable target
    obs_targets = {}
    for sid in all_sids:
        obs = observable_score(item_scores, sid)
        if obs is not None:
            obs_targets[sid] = obs
    print(f"Subjects with observable scores: {len(obs_targets)}/{len(all_sids)}")

    v2_cols = [c for c in v2_df.columns if c not in ("sid", "updrs3")
               and not c.startswith(("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_", "obs_subscore"))
               and c != "hy"]

    # Add observable target
    v2_obs = v2_df.copy()
    v2_obs["obs_target"] = v2_obs["sid"].map(obs_targets)
    v2_obs = v2_obs.dropna(subset=["obs_target"])
    obs_sids = set(v2_obs["sid"].values)
    print(f"Subjects with features + observable: {len(obs_sids)}")

    # Merge with FM
    v2_obs = v2_obs.merge(fm_agg, on="sid", how="left").fillna(0.0)
    all_cols = v2_cols + fm_cols

    k_obs = 150
    k_fused = 300
    print(f"v2 K={k_obs}, fused K={k_fused}, FM features={len(fm_cols)}")

    results = {"phase": "9_fm_observable", "splits": [], "k_v2": k_obs, "k_fused": k_fused}
    obs_subjects = {s: subjects[s] for s in obs_sids if s in subjects}

    print("\n--- 10-split validation (observable target: items 7-14) ---")
    for si, seed in enumerate(range(1, 11)):
        dev_s, test_s = gen_split(obs_subjects, seed)

        dev_mask = v2_obs["sid"].isin(dev_s)
        test_mask = v2_obs["sid"].isin(test_s)
        Xd_v2 = v2_obs.loc[dev_mask, v2_cols].values.astype(np.float32)
        Xt_v2 = v2_obs.loc[test_mask, v2_cols].values.astype(np.float32)
        Xd_all = v2_obs.loc[dev_mask, all_cols].values.astype(np.float32)
        Xt_all = v2_obs.loc[test_mask, all_cols].values.astype(np.float32)
        yd = v2_obs.loc[dev_mask, "obs_target"].values.astype(np.float32)
        yt = v2_obs.loc[test_mask, "obs_target"].values.astype(np.float32)

        r_v2 = run_eval(f"obs_s{seed}_v2", Xd_v2, yd, Xt_v2, yt, v2_cols, k=k_obs)
        r_fused = run_eval(f"obs_s{seed}_v2+fm", Xd_all, yd, Xt_all, yt, all_cols, k=k_fused)
        r_stk = run_stack(f"obs_s{seed}_v2+fm_stk", Xd_all, yd, Xt_all, yt, all_cols, k=k_fused)

        results["splits"].append({"seed": seed, "v2": r_v2, "fused": r_fused, "stk": r_stk})
        print(f"  [{si+1}/10] v2={r_v2['mae']:.2f} fused={r_fused['mae']:.2f} stk={r_stk['mae']:.2f}")

    # Summary
    for tag in ["v2", "fused", "stk"]:
        maes = [s[tag]["mae"] for s in results["splits"]]
        results[f"summary_{tag}"] = {"mean": round(np.mean(maes), 3), "std": round(np.std(maes), 3)}
        print(f"\n10-split {tag}: {np.mean(maes):.3f} +/- {np.std(maes):.3f}")

    # Wilcoxon: stk vs v2
    v2_maes = [s["v2"]["mae"] for s in results["splits"]]
    stk_maes = [s["stk"]["mae"] for s in results["splits"]]
    _, p_val = sp_stats.wilcoxon(stk_maes, v2_maes, alternative="less")
    results["wilcoxon_stk_vs_v2"] = round(p_val, 4)
    print(f"\nWilcoxon stk vs v2: p={p_val:.4f}")

    # Compare with ROCKET observable baseline
    print(f"\nROCKET obs baseline: 3.068 ± 0.463 (p=0.032)")

    results["runtime_s"] = round(time.time() - t0, 1)
    save_json_artifact("rocket_phase9_fm_observable.json", results)
    print(f"\nPhase 9 done in {(time.time()-t0)/60:.1f}m")
    return results


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="all", help="0|1|2|4|5|loocv|6|obs|7|ult|8|fmloocv|9|fmobs|all")
    args = parser.parse_args()

    t_start = time.time()
    print(f"ROCKET ABLATION — phase={args.phase}")
    print(f"N_CORES={N_CORES}, SEQ_LEN={SEQ_LEN}, N_ROCKET_KERNELS={N_ROCKET_KERNELS}")

    # Load subjects
    subjects = parse_clinical()
    all_sids = sorted(_get_valid_sids(subjects))
    print(f"Subjects: {len(all_sids)} ({sum(1 for s in all_sids if subjects[s]['group']=='PD')} PD)")

    # Load v2 feature cache
    if not os.path.exists(V2_CACHE):
        raise FileNotFoundError(f"V2 feature cache not found: {V2_CACHE}\n"
                                f"Run: python3 run_ablation_v3.py --phase 0 first")
    v2_df = pd.read_csv(V2_CACHE)
    print(f"V2 cache: {v2_df.shape}")

    # Load raw recordings + coordination features
    rec_array, rec_sids, rec_tasks, coord_df = load_all_recordings(subjects, all_sids)

    phases = args.phase.split(",") if "," in args.phase else [args.phase]

    all_results = {}

    for phase in phases:
        phase = phase.strip()
        if phase in ("0", "all"):
            all_results["phase0"] = phase0(rec_array, rec_sids, rec_tasks, v2_df, subjects)
        if phase in ("1", "all"):
            all_results["phase1"] = phase1(coord_df, v2_df, subjects)
        if phase in ("2", "all"):
            all_results["phase2"] = phase2(rec_array, rec_sids, rec_tasks, v2_df, subjects)
        if phase in ("4", "all"):
            all_results["phase4"] = phase4(rec_array, rec_sids, rec_tasks, coord_df, v2_df, subjects)
        if phase in ("5", "loocv"):
            all_results["phase5"] = phase5_loocv(rec_array, rec_sids, rec_tasks, v2_df, subjects)
        if phase in ("6", "obs", "all"):
            all_results["phase6"] = phase6_observable(rec_array, rec_sids, rec_tasks, v2_df, subjects)
        if phase in ("7", "ult", "all"):
            all_results["phase7"] = phase7_ultimate(rec_array, rec_sids, rec_tasks, coord_df, v2_df, subjects)
        if phase in ("8", "fmloocv"):
            all_results["phase8"] = phase8_fm_loocv(rec_array, rec_sids, rec_tasks, v2_df, subjects)
        if phase in ("9", "fmobs"):
            all_results["phase9"] = phase9_fm_observable(rec_array, rec_sids, rec_tasks, v2_df, subjects)

    # Save combined results
    save_json_artifact("rocket_ablation_results.json", all_results)
    print(f"\n{'='*70}")
    print(f"TOTAL RUNTIME: {(time.time()-t_start)/60:.1f} minutes")
    print(f"Results: results/rocket_ablation_results.json")


if __name__ == "__main__":
    main()

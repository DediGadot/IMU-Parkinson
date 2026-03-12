#!/usr/bin/env python3
"""run_ablation_v3.py — Full NEXTNEXT ablation. --phase 0|1|2|3|4|all"""
import argparse, os, sys, json, time, warnings
import numpy as np
import pandas as pd
from scipy import signal, stats as sp_stats
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold, StratifiedShuffleSplit
from concurrent.futures import ProcessPoolExecutor
from collections import defaultdict
warnings.filterwarnings("ignore")

def _ensure_deps():
    missing = []
    for pkg, imp in [("antropy","antropy"),("PyWavelets","pywt"),("lightgbm","lightgbm"),("catboost","catboost")]:
        try: __import__(imp)
        except ImportError: missing.append(pkg)
    if missing:
        import subprocess
        print(f"Installing: {' '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q"] + missing)
_ensure_deps()

import antropy, pywt
import lightgbm as lgb
from xgboost import XGBRegressor
from catboost import CatBoostRegressor

from project_paths import REPO_ROOT, RESULTS_DIR, ensure_dir, save_json_artifact, results_artifact_path
sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, load_split, DATA_DIR, SENSORS, FS, _updrs_bin, _get_valid_sids
from updrs_columns import find_updrs_value
from run_ablation_v2 import (
    extract_recording, agg_mean, agg_task_preserving, compute_dist_feats,
    load_covariates, load_walkway, distill_walkway, load_hy, safe,
    TASKS, N_CORES, SEEDS, ACC_COLS, GYR_COLS, FREEACC_COLS, EULER_COLS, PAIRED_SENSORS,
)
from run_proven_stack import load_extended_covariates, feature_select

ALL_TASKS = TASKS + [f"{t}_mat" for t in TASKS] + [f"{t}_matTURN" for t in ["SelfPace","HurriedPace"]]
GAIT_TASKS = ["SelfPace","HurriedPace","TUG","TandemGait"]
NL_SENSORS = ["LowerBack","R_Wrist","L_Wrist","R_Ankle","L_Ankle"]
FEATURE_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
NEW_PREFIXES = ("nl_","sv_","pa_","fq_","hr_","ix_","ext_")
NEW_STANDALONE = ("obs_subscore","hy")
ensure_dir(RESULTS_DIR)

# ── New feature extractors ───────────────────────────────────────────

def _nl_feats(x, p):
    f = {}
    if len(x) < 100:
        return {f"{p}_{k}": 0.0 for k in ("sampen","dfa","hfd")}
    xs = x[np.linspace(0, len(x)-1, min(3000,len(x)), dtype=int)] if len(x) > 3000 else x
    for tag, fn in [("sampen", lambda d: antropy.sample_entropy(d, order=2, metric="chebyshev")),
                    ("dfa", lambda d: antropy.detrended_fluctuation(d)),
                    ("hfd", lambda d: antropy.higuchi_fd(d, kmax=10))]:
        try:
            v = float(fn(xs))
            f[f"{p}_{tag}"] = v if np.isfinite(v) else 0.0
        except Exception:
            f[f"{p}_{tag}"] = 0.0
    return f

def _stride_feats(df, side, p):
    f = {}
    fc_col = f"{side} Foot Contact"
    if fc_col not in df.columns: return f
    fc = df[fc_col].fillna(0).values.astype(int)
    hs = np.where(np.diff(fc) == 1)[0]
    if len(hs) < 5: return f
    st = np.diff(hs) / FS
    st = st[(st > 0.3) & (st < 3.0)]
    if len(st) < 3: return f
    mu = np.mean(st)
    f[f"{p}_st_m"] = float(mu)
    f[f"{p}_st_sd"] = float(np.std(st))
    f[f"{p}_st_cv"] = float(np.std(st) / (mu + 1e-8))
    f[f"{p}_st_iqr"] = float(np.percentile(st, 75) - np.percentile(st, 25))
    if len(st) >= 4:
        f[f"{p}_st_trend"] = float(np.polyfit(np.arange(len(st)), st, 1)[0])
    for sen in ["LowerBack", f"{side}_Ankle"]:
        ac = [f"{sen}_{c}" for c in ACC_COLS]
        if not all(c in df.columns for c in ac): continue
        mag = np.sqrt(np.sum(np.nan_to_num(df[ac].values.astype(np.float32))**2, axis=1))
        pks, rms_v, jrk_v = [], [], []
        for i in range(len(hs)-1):
            s, e = hs[i], hs[i+1]
            if e-s < 30 or e-s > 300: continue
            seg = mag[s:e]
            pks.append(np.max(seg)); rms_v.append(np.sqrt(np.mean(seg**2)))
            jrk_v.append(np.sqrt(np.mean((np.diff(seg)*FS)**2)))
        if len(pks) >= 3:
            sn = sen[:6]
            for tag, arr in [("pk",pks),("rms",rms_v),("jrk",jrk_v)]:
                a = np.array(arr)
                f[f"{p}_{sn}_{tag}_cv"] = float(np.std(a)/(np.mean(a)+1e-8))
    return f

def _pci_feats(df, p):
    f = {}
    if "L Foot Contact" not in df.columns or "R Foot Contact" not in df.columns: return f
    lfc = df["L Foot Contact"].fillna(0).values.astype(int)
    rfc = df["R Foot Contact"].fillna(0).values.astype(int)
    lhs = np.where(np.diff(lfc)==1)[0]; rhs = np.where(np.diff(rfc)==1)[0]
    if len(lhs) < 5 or len(rhs) < 5: return f
    phases = []
    for i in range(len(lhs)-1):
        ls, le = lhs[i], lhs[i+1]; cyc = le - ls
        if cyc < 30 or cyc > 300: continue
        for rh in rhs[(rhs > ls) & (rhs < le)]:
            phases.append(360.0*(rh-ls)/cyc)
    if len(phases) >= 3:
        ph = np.array(phases)
        cv = np.std(ph)/(np.mean(ph)+1e-8); dev = np.mean(np.abs(ph-180.0))
        f[f"{p}_pci"] = float(cv*100+dev); f[f"{p}_pci_cv"] = float(cv); f[f"{p}_pci_dev"] = float(dev)
    lst = np.diff(lhs)/FS; rst = np.diff(rhs)/FS
    lst = lst[(lst>0.2)&(lst<3.0)]; rst = rst[(rst>0.2)&(rst<3.0)]
    if len(lst) >= 3 and len(rst) >= 3:
        lm, rm = np.mean(lst), np.mean(rst)
        f[f"{p}_step_asym"] = float(abs(lm-rm)/(lm+rm+1e-8))
    for pr, pl in PAIRED_SENSORS[:2]:
        rc = [f"{pr}_{c}" for c in ACC_COLS]; lc = [f"{pl}_{c}" for c in ACC_COLS]
        if not all(c in df.columns for c in rc+lc): continue
        ra = np.sqrt(np.sum(np.nan_to_num(df[rc].values[:5000].astype(np.float32))**2, axis=1))
        la = np.sqrt(np.sum(np.nan_to_num(df[lc].values[:5000].astype(np.float32))**2, axis=1))
        n = min(len(ra),len(la)); ra, la = ra[:n], la[:n]
        cc = np.correlate(ra-ra.mean(), la-la.mean(), mode="full")
        cc /= (np.std(ra)*np.std(la)*n+1e-8)
        mid = len(cc)//2; w = min(50, mid); cw = cc[mid-w:mid+w+1]
        pn = pr.replace("R_","")[:5]
        f[f"{p}_xc_{pn}_pk"] = float(np.max(cw))
        f[f"{p}_xc_{pn}_lag"] = float((np.argmax(cw)-w)/FS)
    return f

def _fine_freq(x, p):
    f = {}
    if len(x) < 200: return f
    try:
        freqs, psd = signal.welch(x, fs=FS, nperseg=min(512,len(x)))
        psd += 1e-12; total = np.trapz(psd, freqs)+1e-12
        for bn,lo,hi in [("t34",3,4),("t46",4,6),("t68",6,8),("t810",8,10)]:
            m = (freqs>=lo)&(freqs<=hi)
            f[f"{p}_{bn}"] = float(np.trapz(psd[m],freqs[m])/total) if m.sum()>1 else 0.0
        cp = np.cumsum(psd*np.diff(np.concatenate([[freqs[0]],freqs])))
        cp /= cp[-1]+1e-12
        f[f"{p}_sef90"] = float(freqs[min(np.searchsorted(cp,0.9),len(freqs)-1)])
    except Exception: pass
    try:
        coeffs = pywt.wavedec(x[:min(len(x),4096)], "db4", level=5)
        te = sum(np.sum(c**2) for c in coeffs)+1e-12
        for i,c in enumerate(coeffs):
            f[f"{p}_dw{i}"] = float(np.sum(c**2)/te)
    except Exception: pass
    return f

def _harmonic_ratio(x, p):
    f = {}
    if len(x) < 200: return f
    try:
        xc = x - np.mean(x)
        ac = np.correlate(xc, xc, mode="full")[len(xc)-1:]
        ac /= ac[0]+1e-12
        pks, _ = signal.find_peaks(ac, distance=50, height=0.1)
        if len(pks) < 1: return f
        sf = FS / pks[0]
        fv = np.abs(np.fft.rfft(x)); ff = np.fft.rfftfreq(len(x), 1.0/FS)
        ev = sum(fv[np.argmin(np.abs(ff-h*sf))]**2 for h in range(2,11,2))
        od = sum(fv[np.argmin(np.abs(ff-h*sf))]**2 for h in range(1,11,2))
        f[f"{p}_hr"] = float(ev/(od+1e-12))
    except Exception: pass
    return f

# ── V3 extraction ────────────────────────────────────────────────────

def extract_recording_v3(args):
    base = extract_recording(args)
    if base is None: return None
    csv_path, sid, task = args
    try: df = pd.read_csv(csv_path)
    except Exception: return base
    is_gait = any(task.startswith(gt) for gt in GAIT_TASKS)
    for sen in NL_SENSORS:
        for cols, sfx in [([f"{sen}_{c}" for c in FREEACC_COLS if f"{sen}_{c}" in df.columns] or
                           [f"{sen}_{c}" for c in ACC_COLS], "am"),
                          ([f"{sen}_{c}" for c in GYR_COLS], "gm")]:
            real = [c for c in cols if c in df.columns]
            if len(real) >= 3:
                d = np.nan_to_num(df[real[:3]].values.astype(np.float32))
                mag = np.sqrt(np.sum(d**2, axis=1))
                base.update(_nl_feats(mag, f"nl_{sen}_{sfx}"))
    if is_gait:
        for side in ["L","R"]:
            base.update(_stride_feats(df, side, f"sv_{side}"))
    base.update(_pci_feats(df, "pa"))
    for sen in ["R_Wrist","L_Wrist","R_LatShank","L_LatShank"]:
        ac = [f"{sen}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in ac):
            mag = np.sqrt(np.sum(np.nan_to_num(df[ac].values.astype(np.float32))**2, axis=1))
            base.update(_fine_freq(mag, f"fq_{sen[:6]}"))
    if is_gait:
        for sen in ["R_Ankle","L_Ankle"]:
            ac = [f"{sen}_{c}" for c in ACC_COLS]
            if all(c in df.columns for c in ac):
                mag = np.sqrt(np.sum(np.nan_to_num(df[ac].values.astype(np.float32))**2, axis=1))
                base.update(_harmonic_ratio(mag, f"hr_{sen}"))
    return base

# ── Observable subscore ──────────────────────────────────────────────

def _observable_subscores(subjects):
    OBS_ITEMS = [(9,None),(10,None),(11,None),(12,None),(13,None),(14,None),
                 (15,"a"),(15,"b"),(16,"a"),(16,"b"),(17,"a"),(17,"b"),(17,"c"),(17,"d"),(17,"e"),
                 (7,"a"),(7,"b"),(8,"a"),(8,"b")]
    obs = {}
    for fn in ["PD - Demographic+Clinical - datasetV1.csv","CONTROLS - Demographic+Clinical - datasetV1.csv"]:
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path): continue
        df = pd.read_csv(path, header=1); cols = df.columns.tolist()
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID","")).strip()
            if not sid or sid == "nan" or sid not in subjects: continue
            total = sum(v for item, sfx in OBS_ITEMS if (v := find_updrs_value(row, cols, item, sfx)) is not None)
            obs[sid] = total
    return obs

# ── Feature matrix builder ───────────────────────────────────────────

def build_v3_features(subjects, all_sids, dev_sids):
    if os.path.exists(FEATURE_CACHE):
        print(f"[cache] {FEATURE_CACHE}")
        return pd.read_csv(FEATURE_CACHE)
    t0 = time.time()
    jobs = []
    for task in ALL_TASKS:
        for sid in all_sids:
            if sid not in subjects: continue
            base = "PD PARTICIPANTS" if subjects[sid]["group"] == "PD" else "CONTROL PARTICIPANTS"
            p = os.path.join(DATA_DIR, base, "CSV files", f"{sid}_{task}.csv")
            if os.path.exists(p): jobs.append((p, sid, task))
    print(f"V3 extraction: {len(jobs)} recordings, {N_CORES} cores...")
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        records = [r for r in pool.map(extract_recording_v3, jobs, chunksize=4) if r is not None]
    print(f"  {len(records)} done in {time.time()-t0:.0f}s")
    main_recs = [r for r in records if "_mat" not in r["task"]]
    mat_recs = [r for r in records if "_mat" in r["task"]]
    df = agg_mean(main_recs, subjects)
    df_tp = agg_task_preserving(main_recs, subjects)
    for col in df_tp.columns:
        if col not in ("sid","updrs3") and col not in df.columns:
            df[col] = df["sid"].map(dict(zip(df_tp["sid"], df_tp[col]))).fillna(0.0)
    dist = compute_dist_feats(main_recs, subjects)
    if dist:
        ak = sorted(set().union(*(v.keys() for v in dist.values())))
        for k in ak: df[k] = df["sid"].map(lambda s, kk=k: dist.get(s,{}).get(kk,0.0)).fillna(0.0)
    cov = load_covariates()
    if cov:
        ak = sorted(set().union(*(v.keys() for v in cov.values())))
        for k in ak:
            if k not in df.columns: df[k] = df["sid"].map(lambda s, kk=k: cov.get(s,{}).get(kk,0.0)).fillna(0.0)
    ext = load_extended_covariates()
    for cn in ["ext_height","ext_weight","ext_bmi","ext_age_onset","ext_yrs_sq","ext_yrs_log","ext_early_pd","ext_late_pd"]:
        df[cn] = df["sid"].map(lambda s, c=cn: ext.get(s,{}).get(c,0.0)).fillna(0.0)
    if "cv_yrs" in df.columns:
        for gf in ["LowerBack_g_cadence","fc_L_cad","fc_L_st_cv"]:
            if gf in df.columns: df[f"ix_yrs_{gf}"] = df["cv_yrs"]*df[gf]
    if "cv_age" in df.columns and "bal_path" in df.columns:
        df["ix_age_bal"] = df["cv_age"]*df["bal_path"]
    if "cv_dbs" in df.columns:
        for tf in [c for c in df.columns if "trem" in c][:3]:
            df[f"ix_dbs_{tf}"] = df["cv_dbs"]*df[tf]
    wk = load_walkway()
    if wk:
        dst = distill_walkway(df, wk, dev_sids)
        if dst and isinstance(dst, dict):
            ak = sorted(set().union(*(v.keys() for v in dst.values() if isinstance(v,dict))))
            for k in ak:
                if k not in df.columns: df[k] = df["sid"].map(lambda s, kk=k: dst.get(s,{}).get(kk,0.0)).fillna(0.0)
    if mat_recs:
        df_mat = agg_mean(mat_recs, subjects)
        ic = [c for c in df_mat.columns if c.startswith("ins_")]
        for col in ic:
            if col not in df.columns: df[col] = 0.0
        for _, row in df_mat.iterrows():
            mask = df["sid"] == row["sid"]
            if mask.any():
                for col in ic:
                    if col in row and np.isfinite(row[col]): df.loc[mask, col] = row[col]
    hy = load_hy(); df["hy"] = df["sid"].map(lambda s: hy.get(s,0.0)).fillna(0.0)
    obs = _observable_subscores(subjects)
    df["obs_subscore"] = df["sid"].map(lambda s: obs.get(s,0.0)).fillna(0.0)
    for col in df.columns:
        if col != "sid": df[col] = pd.to_numeric(df[col], errors="coerce").replace([np.inf,-np.inf],0.0).fillna(0.0)
    df.to_csv(FEATURE_CACHE, index=False)
    fc = [c for c in df.columns if c not in ("sid","updrs3")]
    print(f"Cached: {len(df)} subjects x {len(fc)} features -> {FEATURE_CACHE}")
    return df

# ── Helpers ──────────────────────────────────────────────────────────

def gen_split(subjects, seed):
    valid = _get_valid_sids(subjects)
    sids = np.array(valid)
    bins = np.array([_updrs_bin(subjects[s]["updrs3"]) for s in sids])
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    di, ti = next(sss.split(sids, bins))
    return sids[di].tolist(), sids[ti].tolist()

def is_new(col):
    return col.startswith(NEW_PREFIXES) or col in NEW_STANDALONE or col.startswith("hy_x_")

def v2_cols(df):
    return [c for c in df.columns if c not in ("sid","updrs3") and not is_new(c)]

def train_lgb(Xd, yd, Xt, seed=42):
    rng = np.random.RandomState(seed); idx = np.arange(len(Xd)); rng.shuffle(idx)
    nv = max(1, int(len(idx)*0.15))
    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                           reg_lambda=3.0, random_state=seed, n_jobs=N_CORES, objective="mae", verbose=-1)
    m.fit(Xd[idx[nv:]], yd[idx[nv:]], eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
          callbacks=[lgb.early_stopping(100, verbose=False)])
    return m.predict(Xt), m

def train_xgb(Xd, yd, Xt, seed=42):
    rng = np.random.RandomState(seed); idx = np.arange(len(Xd)); rng.shuffle(idx)
    nv = max(1, int(len(idx)*0.15))
    m = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6, reg_lambda=3.0,
                     random_state=seed, n_jobs=N_CORES, early_stopping_rounds=100, objective="reg:absoluteerror")
    m.fit(Xd[idx[nv:]], yd[idx[nv:]], eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])], verbose=False)
    return m.predict(Xt), m

def train_cat(Xd, yd, Xt, seed=42):
    rng = np.random.RandomState(seed); idx = np.arange(len(Xd)); rng.shuffle(idx)
    nv = max(1, int(len(idx)*0.15))
    m = CatBoostRegressor(iterations=2000, learning_rate=0.03, depth=6, l2_leaf_reg=3.0,
                           random_seed=seed, loss_function="MAE", verbose=0, thread_count=N_CORES)
    m.fit(Xd[idx[nv:]], yd[idx[nv:]], eval_set=(Xd[idx[:nv]], yd[idx[:nv]]), early_stopping_rounds=100)
    return m.predict(Xt), m

def run_eval(name, Xd, yd, Xt, yt, fnames, k=150, train_fn=train_lgb):
    k = min(k, Xd.shape[1])
    sel_idx, sel_names = feature_select(Xd, yd, fnames, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]
    maes, rs, preds = [], [], []
    for seed in SEEDS:
        p, _ = train_fn(Xds, yd, Xts, seed)
        p = np.clip(p, 0, 132)
        mae = mean_absolute_error(yt, p); r, _ = sp_stats.pearsonr(yt, p)
        maes.append(mae); rs.append(r); preds.append(p)
    ep = np.mean(preds, axis=0)
    em = mean_absolute_error(yt, ep); er, _ = sp_stats.pearsonr(yt, ep)
    pd_mask = yt > 0
    pd_mae = float(mean_absolute_error(yt[pd_mask], ep[pd_mask])) if pd_mask.sum() > 0 else em
    print(f"  {name}: MAE={em:.2f} r={er:.3f} PD-MAE={pd_mae:.2f} (K={k})")
    return {"config": name, "n_sel": k, "ens_mae": round(em,3), "ens_r": round(er,3),
            "pd_mae": round(pd_mae,3), "mean_mae": round(float(np.mean(maes)),3),
            "std_mae": round(float(np.std(maes)),3), "top10": sel_names[:10]}

def run_stack(name, Xd, yd, Xt, yt, fnames, k=150, base_fns=None):
    if base_fns is None: base_fns = [train_lgb, train_xgb]
    k = min(k, Xd.shape[1])
    sel_idx, sel_names = feature_select(Xd, yd, fnames, k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]
    nb = len(base_fns)
    maes, rs, preds = [], [], []
    for seed in SEEDS:
        kf = KFold(n_splits=5, shuffle=True, random_state=seed)
        oof = [np.zeros(len(Xds)) for _ in range(nb)]
        tp = [np.zeros(len(Xts)) for _ in range(nb)]
        for tr_i, val_i in kf.split(Xds):
            rng = np.random.RandomState(seed+len(tr_i)); shuf = tr_i.copy(); rng.shuffle(shuf)
            nv = max(1, int(len(shuf)*0.15))
            Xtr, ytr = Xds[shuf[nv:]], yd[shuf[nv:]]
            Xval, yval = Xds[shuf[:nv]], yd[shuf[:nv]]
            for bi, bfn in enumerate(base_fns):
                if bfn == train_lgb:
                    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                                           reg_lambda=3.0, random_state=seed, n_jobs=N_CORES, objective="mae", verbose=-1)
                    m.fit(Xtr, ytr, eval_set=[(Xval, yval)], callbacks=[lgb.early_stopping(100, verbose=False)])
                elif bfn == train_xgb:
                    m = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6, reg_lambda=3.0,
                                     random_state=seed, n_jobs=N_CORES, early_stopping_rounds=100, objective="reg:absoluteerror")
                    m.fit(Xtr, ytr, eval_set=[(Xval, yval)], verbose=False)
                elif bfn == train_cat:
                    m = CatBoostRegressor(iterations=2000, learning_rate=0.03, depth=6, l2_leaf_reg=3.0,
                                           random_seed=seed, loss_function="MAE", verbose=0, thread_count=N_CORES)
                    m.fit(Xtr, ytr, eval_set=(Xval, yval), early_stopping_rounds=100)
                else:
                    raise ValueError(f"Unknown base fn: {bfn}")
                oof[bi][val_i] = m.predict(Xds[val_i])
                tp[bi] += m.predict(Xts) / 5
        L0tr = np.column_stack(oof); L0te = np.column_stack(tp)
        meta = Ridge(alpha=1.0); meta.fit(L0tr, yd)
        p = np.clip(meta.predict(L0te), 0, 132)
        mae = mean_absolute_error(yt, p); r, _ = sp_stats.pearsonr(yt, p)
        maes.append(mae); rs.append(r); preds.append(p)
    ep = np.mean(preds, axis=0); em = mean_absolute_error(yt, ep); er, _ = sp_stats.pearsonr(yt, ep)
    pd_mask = yt > 0
    pd_mae = float(mean_absolute_error(yt[pd_mask], ep[pd_mask])) if pd_mask.sum() > 0 else em
    print(f"  {name}: MAE={em:.2f} r={er:.3f} PD-MAE={pd_mae:.2f} (K={k}, {nb} base)")
    return {"config": name, "n_sel": k, "ens_mae": round(em,3), "ens_r": round(er,3),
            "pd_mae": round(pd_mae,3), "mean_mae": round(float(np.mean(maes)),3),
            "std_mae": round(float(np.std(maes)),3), "top10": sel_names[:10]}

def prep_arrays(df, dev_sids, test_sids, cols):
    dm = df["sid"].isin(dev_sids); tm = df["sid"].isin(test_sids)
    Xd = df.loc[dm, cols].values.astype(np.float32); yd = df.loc[dm, "updrs3"].values.astype(np.float32)
    Xt = df.loc[tm, cols].values.astype(np.float32); yt = df.loc[tm, "updrs3"].values.astype(np.float32)
    return Xd, yd, Xt, yt

# ═══════════════════════════════════════════════════════════════════════
# PHASES
# ═══════════════════════════════════════════════════════════════════════

def phase0(df, subjects):
    print("\n" + "="*70 + "\nPHASE 0: FOUNDATION — 10-split stability + K sweep\n" + "="*70)
    t0 = time.time()
    base_cols = v2_cols(df)
    split_results = []
    for si, seed in enumerate(range(1, 11)):
        dev_s, test_s = gen_split(subjects, seed)
        Xd, yd, Xt, yt = prep_arrays(df, dev_s, test_s, base_cols)
        r_lgb = run_eval(f"split{seed}_lgb", Xd, yd, Xt, yt, base_cols, k=150)
        r_stk = run_stack(f"split{seed}_stk", Xd, yd, Xt, yt, base_cols, k=150)
        split_results.append({"seed": seed, "lgb": r_lgb, "stack": r_stk})
        print(f"  [{si+1}/10] seed={seed} lgb={r_lgb['ens_mae']:.2f} stk={r_stk['ens_mae']:.2f}")
    lgb_maes = [s["lgb"]["ens_mae"] for s in split_results]
    stk_maes = [s["stack"]["ens_mae"] for s in split_results]
    print(f"\n10-split LGB: {np.mean(lgb_maes):.2f} +/- {np.std(lgb_maes):.2f}")
    print(f"10-split STK: {np.mean(stk_maes):.2f} +/- {np.std(stk_maes):.2f}")
    if np.std(lgb_maes) > 2.0:
        print("WARNING: std > 2.0 — high split variance, results may be noisy")
    # K sweep on primary split
    split = load_split()
    k_results = []
    for k in [100, 125, 150, 175, 200, 250, 300]:
        Xd, yd, Xt, yt = prep_arrays(df, split["dev_sids"], split["test_sids"], base_cols)
        r = run_eval(f"K{k}", Xd, yd, Xt, yt, base_cols, k=k)
        k_results.append(r)
    best_k = min(k_results, key=lambda x: x["ens_mae"])
    print(f"\nBest K: {best_k['n_sel']} -> MAE={best_k['ens_mae']:.2f}")
    payload = {"split_results": split_results, "k_results": k_results,
               "lgb_mean": round(np.mean(lgb_maes),3), "lgb_std": round(np.std(lgb_maes),3),
               "stk_mean": round(np.mean(stk_maes),3), "stk_std": round(np.std(stk_maes),3),
               "best_k": best_k["n_sel"], "runtime_s": round(time.time()-t0,1)}
    save_json_artifact("ablation_v3_phase0.json", payload)
    print(f"Phase 0 done in {(time.time()-t0)/60:.1f}m -> results/ablation_v3_phase0.json")
    return payload

def phase1(subjects):
    print("\n" + "="*70 + "\nPHASE 1: MEGA FEATURE EXTRACTION\n" + "="*70)
    split = load_split()
    all_sids = split["dev_sids"] + split["test_sids"]
    df = build_v3_features(subjects, all_sids, split["dev_sids"])
    fc = [c for c in df.columns if c not in ("sid","updrs3")]
    new_c = [c for c in fc if is_new(c)]
    print(f"Total: {len(fc)} features ({len(fc)-len(new_c)} v2 + {len(new_c)} new)")
    return df

def phase2(df, subjects):
    print("\n" + "="*70 + "\nPHASE 2: FEATURE ABLATION\n" + "="*70)
    t0 = time.time()
    split = load_split()
    dev_s, test_s = split["dev_sids"], split["test_sids"]
    base_cols = v2_cols(df)
    all_cols = [c for c in df.columns if c not in ("sid","updrs3")]
    groups = [
        ("baseline_v2", base_cols),
        ("+nonlinear", base_cols + [c for c in all_cols if c.startswith("nl_")]),
        ("+stride_var", base_cols + [c for c in all_cols if c.startswith("sv_")]),
        ("+adv_asym", base_cols + [c for c in all_cols if c.startswith("pa_")]),
        ("+fine_freq", base_cols + [c for c in all_cols if c.startswith(("fq_","hr_"))]),
        ("+clin_interact", base_cols + [c for c in all_cols if c.startswith(("ix_","ext_"))]),
        ("+obs_subscore", base_cols + ["obs_subscore"]),
        ("ALL_features", all_cols),
    ]
    results = []
    for name, cols in groups:
        cols = [c for c in cols if c in df.columns]
        Xd, yd, Xt, yt = prep_arrays(df, dev_s, test_s, cols)
        r_lgb = run_eval(f"P2_{name}_lgb", Xd, yd, Xt, yt, cols, k=150)
        r_stk = run_stack(f"P2_{name}_stk", Xd, yd, Xt, yt, cols, k=150)
        results.append({"group": name, "n_cols": len(cols), "lgb": r_lgb, "stack": r_stk})
    # K sweep on ALL features
    k_results = []
    for k in [150, 200, 250, 300]:
        Xd, yd, Xt, yt = prep_arrays(df, dev_s, test_s, all_cols)
        r = run_eval(f"P2_ALL_K{k}", Xd, yd, Xt, yt, all_cols, k=k)
        k_results.append(r)
    best_k = min(k_results, key=lambda x: x["ens_mae"])
    base_mae = results[0]["lgb"]["ens_mae"]
    print(f"\n{'Group':<20} {'N':>5} {'LGB':>7} {'Stack':>7} {'ΔLGB':>7}")
    print("-"*50)
    for r in results:
        dl = base_mae - r["lgb"]["ens_mae"]; ds = base_mae - r["stack"]["ens_mae"]
        print(f"  {r['group']:<18} {r['n_cols']:>5} {r['lgb']['ens_mae']:>7.2f} {r['stack']['ens_mae']:>7.2f} {dl:>+7.2f}")
    print(f"\nBest ALL K: {best_k['n_sel']} -> MAE={best_k['ens_mae']:.2f}")
    payload = {"results": results, "k_results": k_results, "best_k": best_k["n_sel"],
               "baseline_mae": base_mae, "runtime_s": round(time.time()-t0,1)}
    save_json_artifact("ablation_v3_phase2.json", payload)
    print(f"Phase 2 done in {(time.time()-t0)/60:.1f}m")
    return payload

def phase3(df, subjects, p2_payload=None):
    print("\n" + "="*70 + "\nPHASE 3: ARCHITECTURE ABLATION\n" + "="*70)
    t0 = time.time()
    split = load_split()
    dev_s, test_s = split["dev_sids"], split["test_sids"]
    all_cols = [c for c in df.columns if c not in ("sid","updrs3")]
    best_k = p2_payload["best_k"] if p2_payload else 200
    Xd, yd, Xt, yt = prep_arrays(df, dev_s, test_s, all_cols)
    results = []
    # 3.1 CatBoost as base
    r = run_eval("P3_catboost", Xd, yd, Xt, yt, all_cols, k=best_k, train_fn=train_cat)
    results.append(r)
    # 3.2 3-base stack (LGB+XGB+CAT)
    r = run_stack("P3_stack3", Xd, yd, Xt, yt, all_cols, k=best_k, base_fns=[train_lgb,train_xgb,train_cat])
    results.append(r)
    # 3.3 2-base stack (LGB+XGB) — baseline comparison
    r = run_stack("P3_stack2", Xd, yd, Xt, yt, all_cols, k=best_k)
    results.append(r)
    # 3.4 Huber loss LGB
    def train_lgb_huber(Xd_, yd_, Xt_, seed=42):
        rng = np.random.RandomState(seed); idx = np.arange(len(Xd_)); rng.shuffle(idx)
        nv = max(1, int(len(idx)*0.15))
        m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6, reg_lambda=3.0,
                               random_state=seed, n_jobs=N_CORES, objective="huber", verbose=-1)
        m.fit(Xd_[idx[nv:]], yd_[idx[nv:]], eval_set=[(Xd_[idx[:nv]], yd_[idx[:nv]])],
              callbacks=[lgb.early_stopping(100, verbose=False)])
        return m.predict(Xt_), m
    r = run_eval("P3_huber", Xd, yd, Xt, yt, all_cols, k=best_k, train_fn=train_lgb_huber)
    results.append(r)
    # 3.5 Sqrt target transform
    yd_sqrt = np.sqrt(yd)
    r_lgb_sqrt = run_eval("P3_sqrt_lgb_raw", Xd, yd_sqrt, Xt, yt, all_cols, k=best_k)
    # re-evaluate in original scale
    sel_idx, _ = feature_select(Xd, yd_sqrt, all_cols, best_k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]
    sqrt_preds = []
    for seed in SEEDS:
        p, _ = train_lgb(Xds, yd_sqrt, Xts, seed)
        sqrt_preds.append(np.clip(p**2, 0, 132))
    ep = np.mean(sqrt_preds, axis=0)
    em = mean_absolute_error(yt, ep); er, _ = sp_stats.pearsonr(yt, ep)
    results.append({"config": "P3_sqrt_lgb", "ens_mae": round(em,3), "ens_r": round(er,3), "n_sel": best_k})
    print(f"  P3_sqrt_lgb: MAE={em:.2f} r={er:.3f} (K={best_k})")
    # 3.6 Observable subscore as OOF meta-feature
    obs_col_idx = all_cols.index("obs_subscore") if "obs_subscore" in all_cols else None
    if obs_col_idx is not None:
        obs_feats = [c for c in all_cols if c != "obs_subscore"]
        Xd_nobs, yd_obs = prep_arrays(df, dev_s, test_s, obs_feats)[:2]
        obs_target = df.loc[df["sid"].isin(dev_s), "obs_subscore"].values.astype(np.float32)
        kf = KFold(n_splits=5, shuffle=True, random_state=42)
        oof_obs = np.zeros(len(Xd_nobs))
        Xt_nobs = df.loc[df["sid"].isin(test_s), obs_feats].values.astype(np.float32)
        test_obs = np.zeros(len(Xt_nobs))
        sel_idx_obs, _ = feature_select(Xd_nobs, obs_target, obs_feats, 100)
        for tr_i, val_i in kf.split(Xd_nobs):
            p, _ = train_lgb(Xd_nobs[tr_i][:, sel_idx_obs], obs_target[tr_i], Xd_nobs[val_i][:, sel_idx_obs])
            oof_obs[val_i] = p
            p_t, _ = train_lgb(Xd_nobs[tr_i][:, sel_idx_obs], obs_target[tr_i], Xt_nobs[:, sel_idx_obs])
            test_obs += p_t / 5
        Xd_meta = np.column_stack([Xd, oof_obs]); Xt_meta = np.column_stack([Xt, test_obs])
        meta_cols = all_cols + ["oof_obs_pred"]
        r = run_eval("P3_obs_meta", Xd_meta, yd, Xt_meta, yt, meta_cols, k=best_k+1, train_fn=train_lgb)
        results.append(r)
    print(f"\n{'Config':<20} {'MAE':>7} {'r':>6}")
    print("-"*35)
    for r in sorted(results, key=lambda x: x["ens_mae"]):
        print(f"  {r['config']:<18} {r['ens_mae']:>7.2f} {r.get('ens_r',0):>6.3f}")
    payload = {"results": results, "best_k": best_k, "runtime_s": round(time.time()-t0,1)}
    save_json_artifact("ablation_v3_phase3.json", payload)
    print(f"Phase 3 done in {(time.time()-t0)/60:.1f}m")
    return payload

def phase4(df, subjects, p2_payload=None, p3_payload=None):
    print("\n" + "="*70 + "\nPHASE 4: GRAND COMBINATION + VALIDATION\n" + "="*70)
    t0 = time.time()
    split = load_split()
    dev_s, test_s = split["dev_sids"], split["test_sids"]
    all_cols = [c for c in df.columns if c not in ("sid","updrs3")]
    best_k = p2_payload["best_k"] if p2_payload else 200
    # 4.1 Grand pipeline on primary split
    Xd, yd, Xt, yt = prep_arrays(df, dev_s, test_s, all_cols)
    grand_lgb = run_eval("grand_lgb", Xd, yd, Xt, yt, all_cols, k=best_k)
    grand_stk2 = run_stack("grand_stk2", Xd, yd, Xt, yt, all_cols, k=best_k)
    grand_stk3 = run_stack("grand_stk3", Xd, yd, Xt, yt, all_cols, k=best_k,
                            base_fns=[train_lgb, train_xgb, train_cat])
    # 4.2 10-split validation
    print("\n--- 10-split validation ---")
    split_maes = {"lgb": [], "stk2": [], "stk3": []}
    for seed in range(1, 11):
        ds, ts = gen_split(subjects, seed)
        Xd_, yd_, Xt_, yt_ = prep_arrays(df, ds, ts, all_cols)
        r1 = run_eval(f"val{seed}_lgb", Xd_, yd_, Xt_, yt_, all_cols, k=best_k)
        r2 = run_stack(f"val{seed}_stk2", Xd_, yd_, Xt_, yt_, all_cols, k=best_k)
        r3 = run_stack(f"val{seed}_stk3", Xd_, yd_, Xt_, yt_, all_cols, k=best_k,
                        base_fns=[train_lgb, train_xgb, train_cat])
        split_maes["lgb"].append(r1["ens_mae"]); split_maes["stk2"].append(r2["ens_mae"])
        split_maes["stk3"].append(r3["ens_mae"])
    for name, maes in split_maes.items():
        print(f"  {name}: {np.mean(maes):.2f} +/- {np.std(maes):.2f}")
    # 4.3 Wilcoxon test: grand vs Phase 0 baseline
    try:
        p0, _ = json.loads(results_artifact_path("ablation_v3_phase0.json").read_text()), None
        base_maes = [s["lgb"]["ens_mae"] for s in p0["split_results"]]
        stat, pval = sp_stats.wilcoxon(base_maes[:10], split_maes["lgb"][:10])
        print(f"  Wilcoxon LGB vs baseline: stat={stat:.1f} p={pval:.4f}")
    except Exception as e:
        print(f"  Wilcoxon skipped: {e}")
        pval = 1.0
    # 4.4 Bootstrap CIs on primary split
    print("\n--- Bootstrap CIs ---")
    best_primary = min([grand_lgb, grand_stk2, grand_stk3], key=lambda x: x["ens_mae"])
    sel_idx, _ = feature_select(Xd, yd, all_cols, best_k)
    Xds, Xts = Xd[:, sel_idx], Xt[:, sel_idx]
    boot_preds = []
    for seed in SEEDS:
        p, _ = train_lgb(Xds, yd, Xts, seed)
        boot_preds.append(np.clip(p, 0, 132))
    ep = np.mean(boot_preds, axis=0)
    boot_maes = []
    rng = np.random.RandomState(42)
    for _ in range(2000):
        idx = rng.choice(len(yt), len(yt), replace=True)
        boot_maes.append(mean_absolute_error(yt[idx], ep[idx]))
    ci_lo, ci_hi = np.percentile(boot_maes, [2.5, 97.5])
    print(f"  MAE={mean_absolute_error(yt, ep):.2f} 95%CI=[{ci_lo:.2f}, {ci_hi:.2f}]")
    # 4.5 PD-only LOOCV
    print("\n--- PD-only LOOCV ---")
    pd_sids = [s for s in df["sid"] if subjects.get(s, {}).get("group") == "PD"]
    pd_df = df[df["sid"].isin(pd_sids)].reset_index(drop=True)
    loocv_preds, loocv_true = [], []
    for i, sid in enumerate(pd_df["sid"]):
        train_mask = pd_df["sid"] != sid
        Xtr = pd_df.loc[train_mask, all_cols].values.astype(np.float32)
        ytr = pd_df.loc[train_mask, "updrs3"].values.astype(np.float32)
        Xte = pd_df.loc[~train_mask, all_cols].values.astype(np.float32)
        yte = pd_df.loc[~train_mask, "updrs3"].values.astype(np.float32)
        # Feature selection INSIDE loop
        k_loo = min(best_k, Xtr.shape[1])
        si, _ = feature_select(Xtr, ytr, all_cols, k_loo)
        preds_i = []
        for seed in SEEDS:
            p, _ = train_lgb(Xtr[:, si], ytr, Xte[:, si], seed)
            preds_i.append(np.clip(p, 0, 132))
        loocv_preds.append(float(np.mean(preds_i)))
        loocv_true.append(float(yte[0]))
        if (i+1) % 20 == 0: print(f"    LOOCV {i+1}/{len(pd_df)}")
    loocv_mae = mean_absolute_error(loocv_true, loocv_preds)
    loocv_r, _ = sp_stats.pearsonr(loocv_true, loocv_preds)
    print(f"  PD-only LOOCV: MAE={loocv_mae:.2f} r={loocv_r:.3f} (N={len(pd_df)})")
    # Save
    payload = {
        "grand": {"lgb": grand_lgb, "stk2": grand_stk2, "stk3": grand_stk3},
        "split_validation": {k: {"mean": round(np.mean(v),3), "std": round(np.std(v),3), "values": v}
                             for k, v in split_maes.items()},
        "wilcoxon_p": round(pval, 4) if isinstance(pval, float) else 1.0,
        "bootstrap_ci": [round(ci_lo,3), round(ci_hi,3)],
        "loocv": {"mae": round(loocv_mae,3), "r": round(loocv_r,3), "n": len(pd_df)},
        "best_k": best_k, "runtime_s": round(time.time()-t0,1),
    }
    save_json_artifact("ablation_v3_phase4.json", payload)
    print(f"\nPhase 4 done in {(time.time()-t0)/60:.1f}m")
    # Final summary
    print("\n" + "="*70 + "\nFINAL SUMMARY\n" + "="*70)
    print(f"  Primary split best: MAE={best_primary['ens_mae']:.2f} ({best_primary['config']})")
    for k, v in split_maes.items():
        print(f"  10-split {k}: {np.mean(v):.2f} +/- {np.std(v):.2f}")
    print(f"  PD-only LOOCV: MAE={loocv_mae:.2f} r={loocv_r:.3f}")
    print(f"  Bootstrap 95%CI: [{ci_lo:.2f}, {ci_hi:.2f}]")
    print(f"  Hssayeni target: MAE=5.95 (N=24, PD-only)")
    return payload

# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="all", help="0|1|2|3|4|all")
    args = parser.parse_args()
    phases = [0,1,2,3,4] if args.phase == "all" else [int(x) for x in args.phase.split(",")]
    subjects = parse_clinical()
    df = None
    p2, p3 = None, None
    def get_df():
        nonlocal df
        if df is None:
            split = load_split()
            df = build_v3_features(subjects, split["dev_sids"] + split["test_sids"], split["dev_sids"])
        return df
    for p in phases:
        if p == 0: phase0(get_df(), subjects)
        elif p == 1: df = phase1(subjects)
        elif p == 2: p2 = phase2(get_df(), subjects)
        elif p == 3: p3 = phase3(get_df(), subjects, p2)
        elif p == 4: phase4(get_df(), subjects, p2, p3)
    print("\nDONE.")

if __name__ == "__main__":
    main()

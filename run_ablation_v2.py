"""
Ablation Study v2: WearGait-PD UPDRS-III Regression
====================================================
13 experiments (E0-E13), each adds feature blocks progressively.
XGBoost with 5 seeds, results appended to JSON incrementally.
"""
import os, sys, json, time, warnings, traceback
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
RESULTS_FILE = "/root/pd-imu/ablation_v2_results.json"

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
GAIT_SENSORS = ["LowerBack", "R_Ankle", "L_Ankle", "R_DorsalFoot", "L_DorsalFoot"]


# ── Utility ──────────────────────────────────────────────────────────

def safe(func, data, default=0.0):
    try:
        v = func(data)
        return float(v) if np.isfinite(v) else default
    except Exception:
        return default


def td_feats(x, p):
    """8 time-domain features."""
    f = {}
    f[f"{p}_rms"] = safe(lambda d: np.sqrt(np.mean(d**2)), x)
    f[f"{p}_std"] = safe(np.std, x)
    f[f"{p}_range"] = safe(np.ptp, x)
    f[f"{p}_iqr"] = safe(lambda d: np.percentile(d, 75) - np.percentile(d, 25), x)
    f[f"{p}_skew"] = safe(lambda d: float(sp_stats.skew(d)), x)
    f[f"{p}_kurt"] = safe(lambda d: float(sp_stats.kurtosis(d)), x)
    jerk = np.diff(x) * FS
    f[f"{p}_jerk"] = safe(lambda d: np.sqrt(np.mean(d**2)), jerk)
    f[f"{p}_zcr"] = float(np.sum(np.diff(np.sign(x - np.mean(x))) != 0)) / max(len(x), 1)
    return f


def fd_feats(x, p):
    """8 frequency-domain features."""
    f = {}
    try:
        freqs, psd = signal.welch(x, fs=FS, nperseg=min(256, len(x)),
                                   noverlap=min(128, len(x) // 2))
        psd += 1e-12
        total = np.trapz(psd, freqs) + 1e-12
        for bn, lo, hi in [("loco", 0.5, 3.0), ("trem", 3.0, 8.0), ("high", 8.0, 20.0)]:
            mask = (freqs >= lo) & (freqs <= hi)
            bp = np.trapz(psd[mask], freqs[mask]) if mask.sum() > 1 else 1e-12
            f[f"{p}_{bn}"] = float(np.log10(bp))
            f[f"{p}_{bn}_r"] = float(bp / total)
        f[f"{p}_dom"] = float(freqs[np.argmax(psd)])
        pn = psd / psd.sum()
        f[f"{p}_se"] = float(-np.sum(pn * np.log2(pn + 1e-12)))
    except Exception:
        for bn in ["loco", "trem", "high"]:
            f[f"{p}_{bn}"] = 0.0
            f[f"{p}_{bn}_r"] = 0.0
        f[f"{p}_dom"] = 0.0
        f[f"{p}_se"] = 0.0
    return f


def gait_reg(acc_v, p):
    """5 autocorrelation gait regularity features."""
    f = {}
    try:
        x = acc_v - np.mean(acc_v)
        ac = np.correlate(x, x, mode="full")[len(x)-1:]
        ac /= (ac[0] + 1e-12)
        peaks, _ = signal.find_peaks(ac, distance=30, height=0.1)
        if len(peaks) >= 2:
            f[f"{p}_step_t"] = float(peaks[0] / FS)
            f[f"{p}_stride_t"] = float(peaks[1] / FS)
            f[f"{p}_cadence"] = float(60.0 * FS / peaks[0]) if peaks[0] > 0 else 0.0
            f[f"{p}_step_reg"] = float(ac[peaks[0]])
            f[f"{p}_stride_reg"] = float(ac[peaks[1]]) if peaks[1] < len(ac) else 0.0
        else:
            raise ValueError
    except Exception:
        for k in ["step_t", "stride_t", "cadence", "step_reg", "stride_reg"]:
            f[f"{p}_{k}"] = 0.0
    return f


def freeze_idx(acc_v, p):
    try:
        freqs, psd = signal.welch(acc_v, fs=FS, nperseg=min(256, len(acc_v)))
        loco = np.trapz(psd[(freqs >= 0.5) & (freqs <= 3.0)],
                         freqs[(freqs >= 0.5) & (freqs <= 3.0)]) + 1e-12
        frz = np.trapz(psd[(freqs >= 3.0) & (freqs <= 8.0)],
                        freqs[(freqs >= 3.0) & (freqs <= 8.0)])
        return {f"{p}_fi": float(frz / loco)}
    except Exception:
        return {f"{p}_fi": 0.0}


# ── Per-recording extraction ─────────────────────────────────────────

def extract_recording(args):
    """Extract ALL feature types from one CSV. Runs in worker process."""
    csv_path, sid, task = args
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None

    ft = {"sid": sid, "task": task, "n_samples": len(df), "duration_s": len(df) / FS}

    # === E0: Base sensor features ===
    for sen in SENSORS:
        acc_c = [f"{sen}_{c}" for c in FREEACC_COLS]
        if not all(c in df.columns for c in acc_c):
            acc_c = [f"{sen}_{c}" for c in ACC_COLS]
        gyr_c = [f"{sen}_{c}" for c in GYR_COLS]
        eul_c = [f"{sen}_{c}" for c in EULER_COLS]

        if all(c in df.columns for c in acc_c):
            acc = np.nan_to_num(df[acc_c].values.astype(np.float32))
            mag = np.sqrt(np.sum(acc**2, axis=1))
            for i, ax in enumerate("xyz"):
                ft.update(td_feats(acc[:, i], f"{sen}_a{ax}"))
                ft.update(fd_feats(acc[:, i], f"{sen}_a{ax}"))
            ft.update(td_feats(mag, f"{sen}_am"))
            ft.update(fd_feats(mag, f"{sen}_am"))
            if sen in GAIT_SENSORS:
                ft.update(gait_reg(acc[:, 2], f"{sen}_g"))
                ft.update(freeze_idx(acc[:, 2], sen))

        if all(c in df.columns for c in gyr_c):
            gyr = np.nan_to_num(df[gyr_c].values.astype(np.float32))
            gm = np.sqrt(np.sum(gyr**2, axis=1))
            ft.update(td_feats(gm, f"{sen}_gm"))
            ft.update(fd_feats(gm, f"{sen}_gm"))

        if all(c in df.columns for c in eul_c):
            eul = np.nan_to_num(df[eul_c].values.astype(np.float32))
            for i, ax in enumerate(["ro", "pi", "ya"]):
                ft.update(td_feats(eul[:, i], f"{sen}_{ax}"))

    # Asymmetry
    for ls, rs in PAIRED_SENSORS:
        lc = [f"{ls}_{c}" for c in ACC_COLS]
        rc = [f"{rs}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in lc + rc):
            ld = np.nan_to_num(df[lc].values.astype(np.float32))
            rd = np.nan_to_num(df[rc].values.astype(np.float32))
            pn = ls.replace("L_", "").replace("R_", "")
            lr = np.sqrt(np.mean(ld**2, axis=0))
            rr = np.sqrt(np.mean(rd**2, axis=0))
            a = np.abs(lr - rr) / (lr + rr + 1e-8)
            ft[f"asy_{pn}_m"] = float(np.mean(a))
            ft[f"asy_{pn}_x"] = float(np.max(a))

    # Trunk sway
    for ts in TRUNK_SENSORS:
        tc = [f"{ts}_{c}" for c in ACC_COLS]
        if all(c in df.columns for c in tc):
            t = np.nan_to_num(df[tc].values.astype(np.float32))
            ft[f"{ts}_sway"] = float(np.sqrt(np.mean(t[:, :2]**2)))

    # === E2: Event-conditioned ===
    if "GeneralEvent" in df.columns:
        events = df["GeneralEvent"].fillna("Unknown")
        ev_changes = events != events.shift()
        for ev in ["Walk", "Turn", "SitToStand", "TurnToSit"]:
            em = events == ev
            ec = em.sum()
            ft[f"ev_{ev}_n"] = float(ec)
            ft[f"ev_{ev}_s"] = float(ec / FS)
            ft[f"ev_{ev}_f"] = float(ec / max(len(df), 1))
            ft[f"ev_{ev}_bouts"] = float(((events == ev) & ev_changes).sum())
            if ec > 50:
                lb = [f"LowerBack_{c}" for c in FREEACC_COLS]
                if not all(c in df.columns for c in lb):
                    lb = [f"LowerBack_{c}" for c in ACC_COLS]
                if all(c in df.columns for c in lb):
                    ea = np.nan_to_num(df.loc[em, lb].values.astype(np.float32))
                    emag = np.sqrt(np.sum(ea**2, axis=1))
                    ft[f"ev_{ev}_rms"] = safe(lambda d: np.sqrt(np.mean(d**2)), emag)
                    ft[f"ev_{ev}_jrk"] = safe(lambda d: np.sqrt(np.mean((np.diff(d)*FS)**2)), emag)
                lg = [f"LowerBack_{c}" for c in GYR_COLS]
                if all(c in df.columns for c in lg):
                    eg = np.nan_to_num(df.loc[em, lg].values.astype(np.float32))
                    ft[f"ev_{ev}_grms"] = safe(lambda d: np.sqrt(np.mean(d**2)), np.sqrt(np.sum(eg**2, axis=1)))

    # === E3: Contact-derived spatiotemporal ===
    for side in ["L", "R"]:
        fc_col = f"{side} Foot Contact"
        if fc_col not in df.columns:
            continue
        fc = df[fc_col].fillna(0).values.astype(int)
        hs = np.where(np.diff(fc) == 1)[0]  # heel-strikes
        to = np.where(np.diff(fc) == -1)[0]  # toe-offs
        if len(hs) >= 3:
            st = np.diff(hs) / FS
            ft[f"fc_{side}_nhs"] = float(len(hs))
            ft[f"fc_{side}_st_m"] = float(np.mean(st))
            ft[f"fc_{side}_st_sd"] = float(np.std(st))
            ft[f"fc_{side}_st_cv"] = float(np.std(st) / (np.mean(st) + 1e-8))
            ft[f"fc_{side}_cad"] = float(60.0 / (np.mean(st) + 1e-8))
            if len(hs) >= 4:
                strd = (hs[2:] - hs[:-2]) / FS
                ft[f"fc_{side}_strd_m"] = float(np.mean(strd))
                ft[f"fc_{side}_strd_cv"] = float(np.std(strd) / (np.mean(strd) + 1e-8))
            # Stance/swing
            if len(to) >= 2:
                stance_d, swing_d = [], []
                for h in hs:
                    nto = to[to > h]
                    if len(nto) > 0:
                        stance_d.append((nto[0] - h) / FS)
                for t in to:
                    nhs = hs[hs > t]
                    if len(nhs) > 0:
                        swing_d.append((nhs[0] - t) / FS)
                if stance_d:
                    ft[f"fc_{side}_stance_m"] = float(np.mean(stance_d))
                    ft[f"fc_{side}_stance_pct"] = float(np.mean(stance_d) / (np.mean(st) + 1e-8) * 100)
                if swing_d:
                    ft[f"fc_{side}_swing_m"] = float(np.mean(swing_d))

    # Double support + L/R asymmetry
    if "L Foot Contact" in df.columns and "R Foot Contact" in df.columns:
        lfc = df["L Foot Contact"].fillna(0).values.astype(int)
        rfc = df["R Foot Contact"].fillna(0).values.astype(int)
        both = (lfc == 1) & (rfc == 1)
        either = (lfc == 1) | (rfc == 1)
        ft["fc_ds_pct"] = float(both.sum() / (either.sum() + 1e-8) * 100)
        lhs = np.where(np.diff(lfc) == 1)[0]
        rhs = np.where(np.diff(rfc) == 1)[0]
        if len(lhs) >= 3 and len(rhs) >= 3:
            ls = np.mean(np.diff(lhs) / FS)
            rs = np.mean(np.diff(rhs) / FS)
            ft["fc_asym"] = float(abs(ls - rs) / (ls + rs + 1e-8))

    # === E4: Contact-phase kinematics ===
    for side in ["L", "R"]:
        fc_col = f"{side} Foot Contact"
        ankle_pitch = f"{side}_Ankle_Pitch"
        if fc_col not in df.columns or ankle_pitch not in df.columns:
            continue
        fc = df[fc_col].fillna(0).values.astype(int)
        pitch = np.nan_to_num(df[ankle_pitch].values.astype(np.float32))
        hs = np.where(np.diff(fc) == 1)[0]
        to = np.where(np.diff(fc) == -1)[0]
        if len(hs) >= 3:
            ft[f"k_{side}_fsa_m"] = float(np.mean(pitch[hs]))
            ft[f"k_{side}_fsa_sd"] = float(np.std(pitch[hs]))
        if len(to) >= 3:
            ft[f"k_{side}_toa_m"] = float(np.mean(pitch[to]))
            ft[f"k_{side}_toa_sd"] = float(np.std(pitch[to]))
        # Foot clearance proxy
        if len(hs) >= 2 and len(to) >= 2:
            clr = []
            for t in to:
                nhs = hs[hs > t]
                if len(nhs) > 0 and nhs[0] - t > 10:
                    clr.append(np.min(pitch[t:nhs[0]]))
            if clr:
                ft[f"k_{side}_clr_m"] = float(np.mean(clr))
        # Shank angular velocity at IC/TO
        sgyr = f"{side}_LatShank_Gyr_Y"
        if sgyr in df.columns:
            sg = np.nan_to_num(df[sgyr].values.astype(np.float32))
            if len(hs) >= 3:
                ft[f"k_{side}_sg_ic"] = float(np.mean(np.abs(sg[hs])))
            if len(to) >= 3:
                ft[f"k_{side}_sg_to"] = float(np.mean(np.abs(sg[to])))

    # === E5: Turn features ===
    if "GeneralEvent" in df.columns:
        events = df["GeneralEvent"].fillna("Unknown")
        ev_ch = events != events.shift()
        turn_starts = np.where((events == "Turn").values & ev_ch.values)[0]
        if len(turn_starts) > 0:
            turn_durs = []
            turn_segs = []
            for ts in turn_starts:
                end = np.where(events.iloc[ts:] != "Turn")[0]
                te = ts + end[0] if len(end) > 0 else len(events)
                turn_durs.append((te - ts) / FS)
                turn_segs.append((ts, te))
            ft["trn_n"] = float(len(turn_durs))
            ft["trn_dur_m"] = float(np.mean(turn_durs))
            ft["trn_dur_sd"] = float(np.std(turn_durs)) if len(turn_durs) > 1 else 0.0
            yaw_col = "LowerBack_Gyr_Z"
            if yaw_col in df.columns:
                yaw = np.nan_to_num(df[yaw_col].values.astype(np.float32))
                pk, mn = [], []
                for s, e in turn_segs:
                    if e - s > 10:
                        seg = np.abs(yaw[s:e])
                        pk.append(np.max(seg))
                        mn.append(np.mean(seg))
                if pk:
                    ft["trn_pk_yaw"] = float(np.mean(pk))
                    ft["trn_mn_yaw"] = float(np.mean(mn))
            if "L Foot Contact" in df.columns:
                lfc = df["L Foot Contact"].fillna(0).values.astype(int)
                spt = [np.sum(np.diff(lfc[s:e]) == 1) for s, e in turn_segs]
                ft["trn_steps_m"] = float(np.mean(spt)) if spt else 0.0

    # === E6: Transition/balance ===
    if "GeneralEvent" in df.columns:
        events = df["GeneralEvent"].fillna("Unknown")
        sts = events == "SitToStand"
        if sts.sum() > 10:
            lb = [f"LowerBack_{c}" for c in FREEACC_COLS]
            if not all(c in df.columns for c in lb):
                lb = [f"LowerBack_{c}" for c in ACC_COLS]
            if all(c in df.columns for c in lb):
                sd = np.nan_to_num(df.loc[sts, lb].values.astype(np.float32))
                ft["sts_pk_sag"] = float(np.max(np.abs(sd[:, 1])))
                ft["sts_pk_ver"] = float(np.max(np.abs(sd[:, 2])))
                ft["sts_dur"] = float(sts.sum() / FS)
                ft["sts_jrk"] = safe(lambda d: np.sqrt(np.mean((np.diff(d)*FS)**2)),
                                     np.sqrt(np.sum(sd**2, axis=1)))
        for bev in ["Standing", "EO_FeetShoWidth"]:
            bm = events == bev
            if bm.sum() > 50:
                lb = [f"LowerBack_{c}" for c in FREEACC_COLS]
                if not all(c in df.columns for c in lb):
                    lb = [f"LowerBack_{c}" for c in ACC_COLS]
                if all(c in df.columns for c in lb):
                    bd = np.nan_to_num(df.loc[bm, lb].values.astype(np.float32))
                    ft[f"bal_ap_rms"] = float(np.sqrt(np.mean(bd[:, 0]**2)))
                    ft[f"bal_ml_rms"] = float(np.sqrt(np.mean(bd[:, 1]**2)))
                    ft[f"bal_path"] = float(np.sum(np.sqrt(np.sum(np.diff(bd[:, :2], axis=0)**2, axis=1))))
                    ft[f"bal_area"] = float(np.std(bd[:, 0]) * np.std(bd[:, 1]) * np.pi)
                break

    # === E11: Insole pressure ===
    lp = [f"LPressure{i}" for i in range(1, 17)]
    rp = [f"RPressure{i}" for i in range(1, 17)]
    for side, pcols in [("L", lp), ("R", rp)]:
        avail = [c for c in pcols if c in df.columns]
        if len(avail) >= 4:
            pd_arr = np.nan_to_num(df[avail].values.astype(np.float32))
            valid = np.any(pd_arr > 0, axis=1)
            if valid.sum() > 50:
                pd_arr = pd_arr[valid]
                tf = np.sum(pd_arr, axis=1)
                ft[f"ins_{side}_pk"] = float(np.max(tf))
                ft[f"ins_{side}_mn"] = float(np.mean(tf))
                wt = np.arange(len(avail), dtype=np.float32)
                cop = np.sum(pd_arr * wt[None, :], axis=1) / (tf + 1e-8)
                ft[f"ins_{side}_cop_r"] = float(np.ptp(cop))
                ft[f"ins_{side}_cop_v"] = float(np.mean(np.abs(np.diff(cop))) * FS)
                ns = len(avail)
                heel = np.mean(pd_arr[:, :ns//3], axis=1)
                toe = np.mean(pd_arr[:, -ns//3:], axis=1)
                ft[f"ins_{side}_ht"] = float(np.mean(heel) / (np.mean(toe) + 1e-8))

    return ft


# ── Aggregation ──────────────────────────────────────────────────────

def agg_mean(records, subjects):
    """E0: Mean across all tasks."""
    by_sid = defaultdict(list)
    for r in records:
        by_sid[r["sid"]].append(r)
    rows = []
    for sid, recs in by_sid.items():
        if sid not in subjects:
            continue
        agg = {"sid": sid, "updrs3": subjects[sid]["updrs3"]}
        fkeys = set()
        for r in recs:
            for k, v in r.items():
                if k not in ("sid", "task") and isinstance(v, (int, float)):
                    fkeys.add(k)
        for k in sorted(fkeys):
            vals = [r[k] for r in recs if k in r and isinstance(r.get(k), (int, float)) and np.isfinite(r[k])]
            agg[k] = float(np.mean(vals)) if vals else 0.0
        agg["n_tasks"] = len(recs)
        rows.append(agg)
    return pd.DataFrame(rows)


def agg_task_preserving(records, subjects):
    """E1: Mean-agg base + task contrasts."""
    by_sid = defaultdict(dict)
    for r in records:
        by_sid[r["sid"]][r["task"]] = r
    rows = []
    for sid, task_recs in by_sid.items():
        if sid not in subjects:
            continue
        agg = {"sid": sid, "updrs3": subjects[sid]["updrs3"]}
        all_recs = list(task_recs.values())
        fkeys = set()
        for r in all_recs:
            for k, v in r.items():
                if k not in ("sid", "task") and isinstance(v, (int, float)):
                    fkeys.add(k)
        for k in sorted(fkeys):
            vals = [r[k] for r in all_recs if k in r and isinstance(r.get(k), (int, float)) and np.isfinite(r[k])]
            agg[k] = float(np.mean(vals)) if vals else 0.0

        # Task contrasts: Hurried-SelfPace, TUG-SelfPace, Tandem-SelfPace
        sp = task_recs.get("SelfPace", {})
        contrast_pats = ["cadence", "step_t", "stride_t", "rms", "step_reg", "stride_reg",
                         "fi", "jerk", "sway", "cad", "st_m", "st_cv"]
        contrast_keys = [k for k in sp if isinstance(sp.get(k), (int, float))
                         and any(p in k for p in contrast_pats)][:25]
        for ct, cp in [("HurriedPace", "hp"), ("TUG", "tug"), ("TandemGait", "tg")]:
            cr = task_recs.get(ct, {})
            for k in contrast_keys:
                sv = sp.get(k, 0.0)
                cv = cr.get(k, 0.0)
                if isinstance(sv, (int, float)) and isinstance(cv, (int, float)):
                    agg[f"d_{cp}_{k}"] = float(cv) - float(sv)
                    if abs(float(sv)) > 1e-6:
                        agg[f"r_{cp}_{k}"] = float(cv) / float(sv)
        agg["n_tasks"] = len(task_recs)
        rows.append(agg)
    return pd.DataFrame(rows)


# ── Distribution features (E7) ──────────────────────────────────────

def compute_dist_feats(records, subjects):
    """Cross-task variability for key metrics."""
    by_sid = defaultdict(list)
    for r in records:
        by_sid[r["sid"]].append(r)
    out = {}
    pats = ["cadence", "step_t", "stride_t", "rms", "sway", "fi", "step_reg", "stride_reg", "cad"]
    for sid, recs in by_sid.items():
        if sid not in subjects or len(recs) < 2:
            continue
        feats = {}
        fkeys = set()
        for r in recs:
            for k, v in r.items():
                if k not in ("sid", "task") and isinstance(v, (int, float)) and any(p in k for p in pats):
                    fkeys.add(k)
        for k in sorted(fkeys)[:40]:
            vals = [r[k] for r in recs if k in r and isinstance(r[k], (int, float)) and np.isfinite(r[k])]
            if len(vals) >= 2:
                feats[f"dv_{k}_cv"] = float(np.std(vals) / (abs(np.mean(vals)) + 1e-8))
                feats[f"dv_{k}_rng"] = float(np.ptp(vals))
        out[sid] = feats
    return out


# ── Clinical covariates (E8) ────────────────────────────────────────

def load_covariates():
    covs = {}
    for fn in ["PD - Demographic+Clinical - datasetV1.csv",
               "CONTROLS - Demographic+Clinical - datasetV1.csv"]:
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
            ht = pd.to_numeric(row.get("Height (in)", row.get("Height", np.nan)), errors="coerce")
            wt = pd.to_numeric(row.get("Weight (kg)", row.get("Weight", np.nan)), errors="coerce")
            yrs = pd.to_numeric(row.get("Years since PD diagnosis",
                                        row.get("Years Since Diagnosis", 0)), errors="coerce")
            dbs = 1.0 if str(row.get("DBS?", row.get("DBS", ""))).strip().upper() in ("YES", "Y", "1") else 0.0
            covs[sid] = {
                "cv_age": float(age) if pd.notna(age) else 65.0,
                "cv_sex": sex,
                "cv_ht": float(ht) if pd.notna(ht) else 67.0,
                "cv_wt": float(wt) if pd.notna(wt) else 80.0,
                "cv_yrs": float(yrs) if pd.notna(yrs) else 0.0,
                "cv_dbs": dbs,
            }
    return covs


# ── Walkway metrics (E9) ────────────────────────────────────────────

def load_walkway():
    wk_path = os.path.join(DATA_DIR, "Walkway-derived metrics",
                           "PKMAS Walkway Gait Metrics - HP+SP.csv")
    if not os.path.exists(wk_path):
        print(f"  Walkway not found: {wk_path}")
        return {}
    df = pd.read_csv(wk_path)
    # Row 0 is sub-headers (#Samples, Mean, Mean-Ratio, etc.), data starts row 1
    sub_headers = df.iloc[0].values
    df = df.iloc[1:].reset_index(drop=True)
    # Find Mean columns (sub_header == "Mean")
    mean_idx = [i for i in range(len(sub_headers)) if str(sub_headers[i]).strip() == "Mean"]
    mean_col_names = [df.columns[i] for i in mean_idx]
    # Clean parameter names: "Step Length (cm.).1" → "step_length"
    clean_names = []
    for cn in mean_col_names:
        name = cn.split("(")[0].strip().replace(" ", "_").lower()
        name = name.rstrip(".")
        clean_names.append(f"wk_{name}")

    wk = {}
    for _, row in df.iterrows():
        sid = str(row.get("Participant ID", "")).strip()
        task = str(row.get("Task", "")).strip()
        if not sid or sid == "nan":
            continue
        feats = {}
        for mi, cn in zip(mean_idx, clean_names):
            val = pd.to_numeric(row.iloc[mi], errors="coerce")
            if pd.notna(val):
                feats[cn] = float(val)
        if feats:
            if sid in wk:
                for k, v in feats.items():
                    wk[sid][k] = (wk[sid].get(k, v) + v) / 2
            else:
                wk[sid] = feats
    print(f"  Walkway loaded: {len(wk)} subjects, {len(clean_names)} metrics")
    return wk


# ── H&Y stages (E13) ────────────────────────────────────────────────

def load_hy():
    hy = {}
    path = os.path.join(DATA_DIR, "PD - Demographic+Clinical - datasetV1.csv")
    if not os.path.exists(path):
        return hy
    df = pd.read_csv(path, header=1)
    for _, row in df.iterrows():
        sid = str(row.get("Subject ID", "")).strip()
        if not sid or sid == "nan":
            continue
        for col in df.columns:
            if "hoehn" in col.lower() or "h&y" in col.lower() or "h_y" in col.lower():
                val = pd.to_numeric(row[col], errors="coerce")
                if pd.notna(val):
                    hy[sid] = float(val)
                    break
    return hy


# ── Walkway distillation (E10) ──────────────────────────────────────

def distill_walkway(df_feats, wk_metrics, dev_sids):
    from xgboost import XGBRegressor
    feat_cols = [c for c in df_feats.columns if c not in ("sid", "updrs3")]
    common = [s for s in dev_sids if s in wk_metrics]
    if len(common) < 20:
        print(f"  Distillation: only {len(common)} subjects, skipping")
        return {}
    wk_cols = sorted(set().union(*[set(wk_metrics[s].keys()) for s in common]))
    predicted = {}
    for wc in wk_cols:
        train_s = [s for s in common if wc in wk_metrics[s]]
        if len(train_s) < 15:
            continue
        Xtr = np.nan_to_num(df_feats[df_feats["sid"].isin(train_s)][feat_cols].values.astype(np.float32))
        ytr = np.array([wk_metrics[s][wc] for s in train_s], dtype=np.float32)
        m = XGBRegressor(n_estimators=200, learning_rate=0.05, max_depth=4,
                         random_state=42, n_jobs=N_CORES)
        m.fit(Xtr, ytr, verbose=False)
        Xall = np.nan_to_num(df_feats[feat_cols].values.astype(np.float32))
        preds = m.predict(Xall)
        for i, sid in enumerate(df_feats["sid"].values):
            if sid not in predicted:
                predicted[sid] = {}
            predicted[sid][f"dst_{wc}"] = float(preds[i])
    print(f"  Distilled {len(wk_cols)} walkway cols for {len(predicted)} subjects")
    return predicted


# ── Training + evaluation ────────────────────────────────────────────

def run_experiment(df_feats, dev_sids, test_sids, name, max_feats=None):
    from xgboost import XGBRegressor
    feat_cols = [c for c in df_feats.columns if c not in ("sid", "updrs3")]
    dev = df_feats[df_feats["sid"].isin(dev_sids)].copy()
    test = df_feats[df_feats["sid"].isin(test_sids)].copy()
    if len(dev) == 0 or len(test) == 0:
        print(f"  ERROR: dev={len(dev)}, test={len(test)}")
        return None
    for c in feat_cols:
        dev[c] = dev[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        test[c] = test[c].replace([np.inf, -np.inf], 0.0).fillna(0.0)

    Xd = dev[feat_cols].values.astype(np.float32)
    yd = dev["updrs3"].values.astype(np.float32)
    Xt = test[feat_cols].values.astype(np.float32)
    yt = test["updrs3"].values.astype(np.float32)
    sel_cols = feat_cols

    # Feature selection if needed
    if max_feats and len(feat_cols) > max_feats:
        rng = np.random.RandomState(42)
        idx = np.arange(len(Xd))
        rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        sm = XGBRegressor(n_estimators=500, learning_rate=0.05, max_depth=6,
                          reg_lambda=3.0, random_state=42, n_jobs=N_CORES,
                          early_stopping_rounds=50, objective="reg:absoluteerror")
        sm.fit(Xd[idx[nv:]], yd[idx[nv:]], eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])], verbose=False)
        top = np.argsort(sm.feature_importances_)[::-1][:max_feats]
        sel_cols = [feat_cols[i] for i in top]
        Xd = dev[sel_cols].values.astype(np.float32)
        Xt = test[sel_cols].values.astype(np.float32)
        print(f"  Feature selection: {len(feat_cols)} -> {len(sel_cols)}")

    print(f"  {name}: {Xd.shape[0]} dev x {Xd.shape[1]} feats, {Xt.shape[0]} test")
    maes, rs, preds = [], [], []
    for seed in SEEDS:
        rng = np.random.RandomState(seed)
        idx = np.arange(len(Xd))
        rng.shuffle(idx)
        nv = max(1, int(len(idx) * 0.15))
        m = XGBRegressor(n_estimators=2000, learning_rate=0.03, max_depth=6,
                         reg_lambda=3.0, random_state=seed, n_jobs=N_CORES,
                         early_stopping_rounds=100, objective="reg:absoluteerror")
        m.fit(Xd[idx[nv:]], yd[idx[nv:]], eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])], verbose=False)
        p = m.predict(Xt)
        mae = mean_absolute_error(yt, p)
        r, _ = sp_stats.pearsonr(yt, p)
        maes.append(mae)
        rs.append(r)
        preds.append(p.tolist())
        print(f"    seed {seed}: MAE={mae:.2f} r={r:.3f}")

    ep = np.mean([np.array(p) for p in preds], axis=0)
    em = mean_absolute_error(yt, ep)
    er, _ = sp_stats.pearsonr(yt, ep)

    # Top features from last model
    tf = []
    if hasattr(m, 'feature_importances_'):
        imp = m.feature_importances_
        for i in np.argsort(imp)[::-1][:15]:
            tf.append((sel_cols[i], round(float(imp[i]), 4)))

    res = {
        "experiment": name, "n_features": len(sel_cols),
        "n_dev": int(Xd.shape[0]), "n_test": int(Xt.shape[0]),
        "mean_mae": round(float(np.mean(maes)), 3),
        "std_mae": round(float(np.std(maes)), 3),
        "ens_mae": round(float(em), 3), "ens_r": round(float(er), 3),
        "individual_mae": [round(m, 3) for m in maes],
        "individual_r": [round(r, 3) for r in rs],
        "top_features": tf,
    }
    print(f"  -> MEAN: MAE={res['mean_mae']:.2f}+/-{res['std_mae']:.2f}  "
          f"ENS: MAE={res['ens_mae']:.2f} r={res['ens_r']:.3f}")
    return res


# ── Column selectors ─────────────────────────────────────────────────

E0_EXCLUDE = ["ev_", "fc_", "k_", "trn_", "sts_", "bal_", "ins_", "d_", "r_",
              "dv_", "cv_", "wk_", "dst_", "hy_", "interact_"]


def cols_for(df, include_prefixes=None, exclude_prefixes=None):
    """Select feature columns by prefix inclusion/exclusion."""
    base = [c for c in df.columns if c not in ("sid", "updrs3")]
    if exclude_prefixes:
        base = [c for c in base if not any(c.startswith(p) for p in exclude_prefixes)]
    if include_prefixes:
        extra = [c for c in df.columns if c not in ("sid", "updrs3")
                 and any(c.startswith(p) for p in include_prefixes)]
        base = list(dict.fromkeys(base + extra))
    return base


# ── Main ─────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    print("=" * 70)
    print("ABLATION STUDY v2: WearGait-PD UPDRS-III Regression")
    print("=" * 70)

    subjects = parse_clinical()
    split = load_split()
    dev_sids, test_sids = split["dev_sids"], split["test_sids"]
    all_sids = dev_sids + test_sids

    # Phase 0: Extract all features
    print(f"\n{'='*70}\nPHASE 0: Feature extraction\n{'='*70}")
    pd_dir = os.path.join(DATA_DIR, "PD PARTICIPANTS", "CSV files")
    hc_dir = os.path.join(DATA_DIR, "CONTROL PARTICIPANTS", "CSV files")

    jobs = []
    all_tasks = TASKS + [f"{t}_mat" for t in TASKS] + \
                [f"{t}_matTURN" for t in ["SelfPace", "HurriedPace"]]
    for task in all_tasks:
        for sid in all_sids:
            if sid not in subjects:
                continue
            d = pd_dir if subjects[sid]["group"] == "PD" else hc_dir
            p = os.path.join(d, f"{sid}_{task}.csv")
            if os.path.exists(p):
                jobs.append((p, sid, task))

    print(f"  {len(jobs)} recordings, {N_CORES} cores...")
    t1 = time.time()
    with ProcessPoolExecutor(max_workers=N_CORES) as pool:
        all_recs = list(pool.map(extract_recording, jobs))
    all_recs = [r for r in all_recs if r is not None]
    print(f"  {len(all_recs)} done in {time.time()-t1:.0f}s")

    main_recs = [r for r in all_recs if "_mat" not in r["task"]]
    mat_recs = [r for r in all_recs if "_mat" in r["task"]]

    # Load supplementary data
    covs = load_covariates()
    wk = load_walkway()
    hy = load_hy()
    dist = compute_dist_feats(main_recs, subjects)
    print(f"  Covariates: {len(covs)}, Walkway: {len(wk)}, H&Y: {len(hy)}")

    results = []
    def save():
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2, default=str)

    # === E0: Baseline ===
    print(f"\n{'='*70}\nE0: BASELINE (mean-aggregated)\n{'='*70}")
    df_full = agg_mean(main_recs, subjects)
    e0_cols = ["sid", "updrs3"] + [c for c in df_full.columns
               if c not in ("sid", "updrs3") and not any(c.startswith(p) for p in E0_EXCLUDE)]
    df_e0 = df_full[e0_cols].copy()
    print(f"  {len(e0_cols)-2} features")
    r = run_experiment(df_e0, dev_sids, test_sids, "E0_baseline", max_feats=200)
    if r: results.append(r); save()

    # === E1: Task-preserving ===
    print(f"\n{'='*70}\nE1: TASK-PRESERVING\n{'='*70}")
    df_tp = agg_task_preserving(main_recs, subjects)
    e1_excl = [p for p in E0_EXCLUDE if p not in ("d_", "r_")]
    e1_cols = ["sid", "updrs3"] + [c for c in df_tp.columns
               if c not in ("sid", "updrs3") and not any(c.startswith(p) for p in e1_excl)]
    df_e1 = df_tp[e1_cols].copy()
    print(f"  {len(e1_cols)-2} features")
    r = run_experiment(df_e1, dev_sids, test_sids, "E1_task_preserving", max_feats=200)
    if r: results.append(r); save()

    # === E2: Event-conditioned ===
    print(f"\n{'='*70}\nE2: EVENT-CONDITIONED\n{'='*70}")
    ev_cols = [c for c in df_tp.columns if c.startswith("ev_")]
    e2_set = list(dict.fromkeys(e1_cols + ev_cols))
    df_e2 = df_tp[[c for c in e2_set if c in df_tp.columns]].copy()
    print(f"  {len(e2_set)-2} features (+{len(ev_cols)} event)")
    r = run_experiment(df_e2, dev_sids, test_sids, "E2_events", max_feats=200)
    if r: results.append(r); save()

    # === E3: Contact spatiotemporal ===
    print(f"\n{'='*70}\nE3: CONTACT SPATIOTEMPORAL\n{'='*70}")
    fc_cols = [c for c in df_tp.columns if c.startswith("fc_")]
    e3_set = list(dict.fromkeys(e2_set + fc_cols))
    df_e3 = df_tp[[c for c in e3_set if c in df_tp.columns]].copy()
    print(f"  {len(e3_set)-2} features (+{len(fc_cols)} contact)")
    r = run_experiment(df_e3, dev_sids, test_sids, "E3_contact", max_feats=200)
    if r: results.append(r); save()

    # === E4: Kinematics ===
    print(f"\n{'='*70}\nE4: KINEMATICS (FSA, TOA, clearance)\n{'='*70}")
    kin_cols = [c for c in df_tp.columns if c.startswith("k_")]
    e4_set = list(dict.fromkeys(e3_set + kin_cols))
    df_e4 = df_tp[[c for c in e4_set if c in df_tp.columns]].copy()
    print(f"  {len(e4_set)-2} features (+{len(kin_cols)} kinematic)")
    r = run_experiment(df_e4, dev_sids, test_sids, "E4_kinematics", max_feats=200)
    if r: results.append(r); save()

    # === E5: Turns ===
    print(f"\n{'='*70}\nE5: TURNS\n{'='*70}")
    trn_cols = [c for c in df_tp.columns if c.startswith("trn_")]
    e5_set = list(dict.fromkeys(e4_set + trn_cols))
    df_e5 = df_tp[[c for c in e5_set if c in df_tp.columns]].copy()
    print(f"  {len(e5_set)-2} features (+{len(trn_cols)} turn)")
    r = run_experiment(df_e5, dev_sids, test_sids, "E5_turns", max_feats=200)
    if r: results.append(r); save()

    # === E6: Transitions/Balance ===
    print(f"\n{'='*70}\nE6: TRANSITIONS/BALANCE\n{'='*70}")
    tb_cols = [c for c in df_tp.columns if c.startswith("sts_") or c.startswith("bal_")]
    e6_set = list(dict.fromkeys(e5_set + tb_cols))
    df_e6 = df_tp[[c for c in e6_set if c in df_tp.columns]].copy()
    print(f"  {len(e6_set)-2} features (+{len(tb_cols)} transition)")
    r = run_experiment(df_e6, dev_sids, test_sids, "E6_transitions", max_feats=200)
    if r: results.append(r); save()

    # === E7: Distribution features ===
    print(f"\n{'='*70}\nE7: DISTRIBUTIONS\n{'='*70}")
    df_e7 = df_e6.copy()
    for sid, df_dict in dist.items():
        mask = df_e7["sid"] == sid
        if mask.any():
            for k, v in df_dict.items():
                if k not in df_e7.columns:
                    df_e7[k] = 0.0
                df_e7.loc[mask, k] = v
    dv_cols = [c for c in df_e7.columns if c.startswith("dv_")]
    print(f"  {len([c for c in df_e7.columns if c not in ('sid','updrs3')])} features (+{len(dv_cols)} dist)")
    r = run_experiment(df_e7, dev_sids, test_sids, "E7_distributions", max_feats=200)
    if r: results.append(r); save()

    # === E8: Clinical covariates ===
    print(f"\n{'='*70}\nE8: CLINICAL COVARIATES\n{'='*70}")
    df_e8 = df_e7.copy()
    for cn in ["cv_age", "cv_sex", "cv_ht", "cv_wt", "cv_yrs", "cv_dbs"]:
        df_e8[cn] = 0.0
    for sid, cv in covs.items():
        mask = df_e8["sid"] == sid
        if mask.any():
            for k, v in cv.items():
                df_e8.loc[mask, k] = v
    print(f"  {len([c for c in df_e8.columns if c not in ('sid','updrs3')])} features (+6 cov)")
    r = run_experiment(df_e8, dev_sids, test_sids, "E8_clinical", max_feats=200)
    if r: results.append(r); save()

    # === E9: Walkway oracle ===
    print(f"\n{'='*70}\nE9: WALKWAY ORACLE\n{'='*70}")
    df_e9 = df_e8.copy()
    if wk:
        wk_all = sorted(set().union(*[set(v.keys()) for v in wk.values()]))
        for wc in wk_all:
            df_e9[wc] = 0.0
        df_e9["wk_miss"] = 1.0
        for sid, wm in wk.items():
            mask = df_e9["sid"] == sid
            if mask.any():
                for k, v in wm.items():
                    df_e9.loc[mask, k] = v
                df_e9.loc[mask, "wk_miss"] = 0.0
        n_wk = sum(1 for s in all_sids if s in wk)
        print(f"  Walkway: {n_wk}/{len(all_sids)} subjects")
    print(f"  {len([c for c in df_e9.columns if c not in ('sid','updrs3')])} features")
    r = run_experiment(df_e9, dev_sids, test_sids, "E9_walkway_oracle", max_feats=200)
    if r: results.append(r); save()

    # === E10: Walkway distillation ===
    print(f"\n{'='*70}\nE10: WALKWAY DISTILLATION\n{'='*70}")
    df_e10 = df_e8.copy()  # from E8, not E9
    if wk:
        dst = distill_walkway(df_e8, wk, dev_sids)
        if dst:
            dst_all = sorted(set().union(*[set(v.keys()) for v in dst.values()]))
            for dc in dst_all:
                df_e10[dc] = 0.0
            for sid, dm in dst.items():
                mask = df_e10["sid"] == sid
                if mask.any():
                    for k, v in dm.items():
                        df_e10.loc[mask, k] = v
    print(f"  {len([c for c in df_e10.columns if c not in ('sid','updrs3')])} features")
    r = run_experiment(df_e10, dev_sids, test_sids, "E10_distillation", max_feats=200)
    if r: results.append(r); save()

    # === E11: Insole pressure ===
    print(f"\n{'='*70}\nE11: INSOLE PRESSURE\n{'='*70}")
    df_e11 = df_e10.copy()
    if mat_recs:
        df_mat = agg_mean(mat_recs, subjects)
        ins_cols = [c for c in df_mat.columns if c.startswith("ins_")]
        print(f"  Insole cols: {len(ins_cols)}")
        for ic in ins_cols:
            df_e11[ic] = 0.0
        for _, row in df_mat.iterrows():
            sid = row["sid"]
            mask = df_e11["sid"] == sid
            if mask.any():
                for ic in ins_cols:
                    if ic in row and np.isfinite(row[ic]):
                        df_e11.loc[mask, ic] = row[ic]
    print(f"  {len([c for c in df_e11.columns if c not in ('sid','updrs3')])} features")
    r = run_experiment(df_e11, dev_sids, test_sids, "E11_insole", max_feats=200)
    if r: results.append(r); save()

    # === E12: Fused + interactions ===
    print(f"\n{'='*70}\nE12: FUSED + INTERACTIONS\n{'='*70}")
    df_e12 = df_e11.copy()
    best = min(results, key=lambda x: x["ens_mae"]) if results else None
    if best and best.get("top_features"):
        top_n = [f[0] for f in best["top_features"][:8]]
        for i in range(min(4, len(top_n))):
            for j in range(i+1, min(6, len(top_n))):
                n1, n2 = top_n[i], top_n[j]
                if n1 in df_e12.columns and n2 in df_e12.columns:
                    df_e12[f"ix_{i}_{j}"] = df_e12[n1] * df_e12[n2]
    print(f"  {len([c for c in df_e12.columns if c not in ('sid','updrs3')])} features")
    r = run_experiment(df_e12, dev_sids, test_sids, "E12_fused", max_feats=200)
    if r: results.append(r); save()

    # === E13: Ceiling + H&Y ===
    print(f"\n{'='*70}\nE13: CEILING (+ H&Y)\n{'='*70}")
    df_e13 = df_e12.copy()
    df_e13["hy"] = 0.0
    for sid, h in hy.items():
        mask = df_e13["sid"] == sid
        if mask.any():
            df_e13.loc[mask, "hy"] = h
    for col in ["cv_yrs", "fc_L_cad", "LowerBack_g_cadence"]:
        if col in df_e13.columns:
            df_e13[f"hy_x_{col}"] = df_e13["hy"] * df_e13[col]
    n_hy = sum(1 for s in all_sids if s in hy)
    print(f"  H&Y: {n_hy}/{len(all_sids)} subjects")
    print(f"  {len([c for c in df_e13.columns if c not in ('sid','updrs3')])} features")
    r = run_experiment(df_e13, dev_sids, test_sids, "E13_ceiling", max_feats=200)
    if r: results.append(r); save()

    # === Summary ===
    elapsed = time.time() - t0
    print(f"\n{'='*70}")
    print(f"ABLATION COMPLETE ({elapsed/60:.1f} min)")
    print(f"{'='*70}")
    print(f"  {'Experiment':<25} {'Feats':>6} {'Mean MAE':>10} {'Ens MAE':>9} {'Ens r':>7}")
    print(f"  {'-'*60}")
    for r in results:
        print(f"  {r['experiment']:<25} {r['n_features']:>5} "
              f"{r['mean_mae']:>6.2f}+/-{r['std_mae']:.2f} "
              f"{r['ens_mae']:>7.2f}  {r['ens_r']:>6.3f}")
    if len(results) >= 2:
        best = min(results, key=lambda x: x["ens_mae"])
        base = results[0]
        d = base["ens_mae"] - best["ens_mae"]
        print(f"\n  BEST: {best['experiment']} MAE={best['ens_mae']:.2f} r={best['ens_r']:.3f}")
        print(f"  IMPROVEMENT: {d:.2f} ({d/base['ens_mae']*100:.1f}%)")
    save()
    print(f"\nResults: {RESULTS_FILE}")


if __name__ == "__main__":
    main()

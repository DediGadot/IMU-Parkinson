#!/usr/bin/env python3
"""Cache extra feature sets for autoresearch CCC harness.

Creates:
  results/velinc_features.csv         — VelocityIncrement features (regular)
  results/velinc_gated_features.csv   — VelocityIncrement phase-gated (Walk vs Turn)
  results/walkway_features.csv        — Raw walkway gait metrics (196 params)

Usage: python3 -u cache_extra_features.py
"""
import os, sys, time, warnings
import numpy as np
import pandas as pd
from scipy import signal as sp_signal

warnings.filterwarnings("ignore")

from project_paths import RESULTS_DIR, results_artifact_path, ensure_dir
from data_split import parse_clinical, DATA_DIR, SENSORS, FS

ensure_dir(RESULTS_DIR)

ACC_COLS = ["Acc_X", "Acc_Y", "Acc_Z"]
GYR_COLS = ["Gyr_X", "Gyr_Y", "Gyr_Z"]
VELINC_COLS = ["VelInc_X", "VelInc_Y", "VelInc_Z"]
TASKS = ["SelfPace", "HurriedPace", "TUG", "TandemGait", "Balance",
         "SelfPace_mat", "HurriedPace_mat", "SelfPace_matTURN", "HurriedPace_matTURN",
         "TUG_mat", "TandemGait_mat", "Balance_mat"]


def td_feats(x, prefix):
    """Time-domain features for a 1D signal."""
    if len(x) < 10:
        return {f"{prefix}_{s}": 0.0 for s in
                ["rms", "std", "range", "iqr", "skew", "kurt", "jerk", "zcr"]}
    rms = float(np.sqrt(np.mean(x ** 2)))
    std = float(np.std(x))
    rng = float(np.ptp(x))
    iqr = float(np.percentile(x, 75) - np.percentile(x, 25))
    skw = float(pd.Series(x).skew()) if std > 1e-8 else 0.0
    krt = float(pd.Series(x).kurtosis()) if std > 1e-8 else 0.0
    jrk = float(np.sqrt(np.mean(np.diff(x) ** 2))) if len(x) > 1 else 0.0
    mean_val = np.mean(x)
    zcr = float(np.sum(np.diff(np.sign(x - mean_val)) != 0) / len(x))
    return {
        f"{prefix}_rms": rms, f"{prefix}_std": std, f"{prefix}_range": rng,
        f"{prefix}_iqr": iqr, f"{prefix}_skew": skw, f"{prefix}_kurt": krt,
        f"{prefix}_jerk": jrk, f"{prefix}_zcr": zcr,
    }


def fd_feats(x, prefix):
    """Frequency-domain features for a 1D signal."""
    if len(x) < 256:
        return {f"{prefix}_{s}": 0.0 for s in
                ["loco", "trem", "high", "loco_r", "high_r", "se"]}
    f, pxx = sp_signal.welch(x, fs=FS, nperseg=min(256, len(x)))
    total = np.sum(pxx) + 1e-12
    loco = float(np.sum(pxx[(f >= 0.5) & (f <= 3)]))
    trem = float(np.sum(pxx[(f >= 3) & (f <= 8)]))
    high = float(np.sum(pxx[(f >= 8) & (f <= 25)]))
    se = float(-np.sum((pxx / total) * np.log2(pxx / total + 1e-12)))
    return {
        f"{prefix}_loco": loco, f"{prefix}_trem": trem, f"{prefix}_high": high,
        f"{prefix}_loco_r": loco / total, f"{prefix}_high_r": high / total,
        f"{prefix}_se": se,
    }


def extract_velinc_recording(csv_path, sid, task, phase_gated=False):
    """Extract VelocityIncrement features from one recording."""
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None

    ft = {"sid": sid, "task": task}

    if phase_gated and "GeneralEvent" in df.columns:
        events = df["GeneralEvent"].fillna("Unknown")
        phases = {"walk": events == "Walk", "turn": events == "Turn"}
    else:
        phases = {"all": pd.Series(True, index=df.index)}

    for phase_name, phase_mask in phases.items():
        phase_df = df[phase_mask]
        if len(phase_df) < 50:
            continue

        for sen in SENSORS:
            vi_cols = [f"{sen}_{c}" for c in VELINC_COLS]
            if not all(c in phase_df.columns for c in vi_cols):
                continue
            vi = np.nan_to_num(phase_df[vi_cols].values.astype(np.float32))
            vi_mag = np.sqrt(np.sum(vi ** 2, axis=1))

            pfx = f"vi_{phase_name}_{sen}" if phase_gated else f"vi_{sen}"
            ft.update(td_feats(vi_mag, f"{pfx}_m"))
            ft.update(fd_feats(vi_mag, f"{pfx}_m"))
            for i, ax in enumerate(["x", "y", "z"]):
                ft.update(td_feats(vi[:, i], f"{pfx}_{ax}"))

    return ft


def aggregate_recordings(records):
    """Aggregate recording-level features to subject-level (mean)."""
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    feat_cols = [c for c in df.columns if c not in ("sid", "task")]
    agg = df.groupby("sid")[feat_cols].mean().reset_index()
    return agg


def cache_velinc(subjects, phase_gated=False):
    """Extract and cache VelocityIncrement features."""
    label = "phase-gated" if phase_gated else "regular"
    print(f"\n{'='*60}")
    print(f"Caching VelInc features ({label})")
    print(f"{'='*60}")
    t0 = time.time()

    records = []
    n_recs = 0
    for i, (sid, info) in enumerate(subjects.items()):
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(subjects)} subjects...")
        group = info.get("group", "PD")
        base = "PD PARTICIPANTS" if group == "PD" else "CONTROL PARTICIPANTS"
        csv_dir = os.path.join(DATA_DIR, base, "CSV files")

        for task in TASKS:
            csv_path = os.path.join(csv_dir, f"{sid}_{task}.csv")
            if not os.path.exists(csv_path):
                continue
            rec = extract_velinc_recording(csv_path, sid, task, phase_gated=phase_gated)
            if rec is not None:
                records.append(rec)
                n_recs += 1

    agg = aggregate_recordings(records)
    feat_cols = [c for c in agg.columns if c != "sid"]

    if phase_gated:
        out_path = str(results_artifact_path("velinc_gated_features.csv"))
    else:
        out_path = str(results_artifact_path("velinc_features.csv"))

    agg.to_csv(out_path, index=False)
    elapsed = time.time() - t0
    print(f"  Saved: {out_path}")
    print(f"  {len(agg)} subjects, {len(feat_cols)} features, {n_recs} recordings ({elapsed:.0f}s)")
    return agg


def cache_walkway():
    """Cache raw walkway gait metrics."""
    print(f"\n{'='*60}")
    print(f"Caching walkway features")
    print(f"{'='*60}")

    wk_path = os.path.join(DATA_DIR, "Walkway-derived metrics",
                           "PKMAS Walkway Gait Metrics - HP+SP.csv")
    assert os.path.exists(wk_path), f"Walkway CSV not found: {wk_path}"

    df = pd.read_csv(wk_path)
    # Row 0 is sub-header, data starts row 1
    sub_header = df.iloc[0]
    df = df.iloc[1:].reset_index(drop=True)

    # Build clean column names
    clean_names = []
    for col in df.columns:
        sh = str(sub_header.get(col, ""))
        if sh and sh != "nan" and col not in ("Subject ID", "Condition"):
            clean_names.append(f"wk_{col}_{sh}".replace(" ", "_").replace("/", "_")[:50])
        elif col not in ("Subject ID", "Condition"):
            clean_names.append(f"wk_{col}".replace(" ", "_").replace("/", "_")[:50])

    sid_col = "Subject ID"
    cond_col = "Condition"

    results = {}
    for _, row in df.iterrows():
        sid = str(row.get(sid_col, "")).strip()
        if not sid or sid == "nan":
            continue

        feats = {}
        for i, col in enumerate(df.columns):
            if col in (sid_col, cond_col):
                continue
            if i - 2 < len(clean_names):
                name = clean_names[i - 2]
            else:
                continue
            try:
                val = float(row[col])
                if np.isfinite(val):
                    feats[name] = val
            except (ValueError, TypeError):
                continue

        if feats:
            if sid not in results:
                results[sid] = feats
            else:
                # Average across conditions
                for k, v in feats.items():
                    results[sid][k] = (results[sid].get(k, v) + v) / 2

    rows = [{"sid": sid, **feats} for sid, feats in results.items()]
    out_df = pd.DataFrame(rows).fillna(0.0)
    feat_cols = [c for c in out_df.columns if c != "sid"]

    out_path = str(results_artifact_path("walkway_features.csv"))
    out_df.to_csv(out_path, index=False)
    print(f"  Saved: {out_path}")
    print(f"  {len(out_df)} subjects, {len(feat_cols)} features")
    return out_df


def main():
    subjects = parse_clinical()
    print(f"Subjects: {len(subjects)}")

    cache_velinc(subjects, phase_gated=False)
    cache_velinc(subjects, phase_gated=True)
    cache_walkway()

    print(f"\n{'='*60}")
    print("ALL CACHES COMPLETE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""run_sensor_span.py — Minimal sensor span study with SSL ranking.

Statistically robust sensor ablation under the P5 SSL ranking pipeline.
22 sensor configurations × 3 targets (T1/T2/T3) = 66 experiments.

Per-config FM re-extraction: MOMENT embeddings use ONLY channels from the
target sensor subset, preventing information leakage from absent sensors.

Evaluation: PD-only LOOCV (N~94).

Usage:
    python3 -u run_sensor_span.py --config all_13 --target t1
    python3 -u run_sensor_span.py --config all --target all
    python3 -u run_sensor_span.py --config all --target all --eval 5split
    python3 -u run_sensor_span.py --analyze          # run bootstrap analysis
"""
import argparse
import json
import os
import sys
import time
import warnings
from collections import OrderedDict

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")


# ── Dependency check ─────────────────────────────────────────────────
try:
    import lightgbm as lgb
    from xgboost import XGBRegressor, XGBRanker
    _HAS_ML = True
except ImportError:
    _HAS_ML = False

from project_paths import REPO_ROOT, RESULTS_DIR, ensure_dir, results_artifact_path
sys.path.insert(0, str(REPO_ROOT))
from data_split import parse_clinical, SENSORS
from updrs_columns import find_updrs_value
from eval_utils import lins_ccc, cal_slope, feature_select, N_CORES


# ── Constants ────────────────────────────────────────────────────────
V2_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
FM_CACHE = str(results_artifact_path("fm_embeddings.npz"))
RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))
PER_ITEM_CACHE = str(results_artifact_path("per_item_scores.json"))
SENSOR_FM_DIR = str(results_artifact_path("sensor_fm_cache"))
SEEDS = [42, 123, 456, 789, 2024]
LOOCV_PROGRESS_EVERY = 10
FM_SEQ_LEN = 512
FM_BATCH_SIZE = 32
ensure_dir(RESULTS_DIR)

TARGET_CLIP = {"t1": (0, 24), "t2": (0, 32), "t3": (0, 59)}

# Subitem map for parsing individual UPDRS items
SUBITEMS_MAP = {
    1: None, 2: None,
    3: ["a", "b", "c", "d", "e"],
    4: ["a", "b"],
    5: ["RA", "LA"],  6: ["RA", "LA"],
    7: ["RA", "LA"],  8: ["RL", "LL"],
    9: None, 10: None, 11: None, 12: None,
    13: None, 14: None,
    15: ["RA", "LA"],  16: ["RL", "LL"],
    17: ["RL", "RU", "LU", "LL", "LipJaw"],
    18: None,
}

DEFAULT_LGB_PARAMS = {
    "n_estimators": 2000,
    "learning_rate": 0.03,
    "max_depth": 6,
    "num_leaves": 31,
    "reg_lambda": 0.3,
    "min_data_in_leaf": 8,
    "colsample_bytree": 0.5,
    "subsample": 1.0,
    "objective": "mse",
    "val_frac": 0.15,
    "early_stopping_rounds": 100,
}


# ═══════════════════════════════════════════════════════════════════════
# SENSOR → CHANNEL MAPPING
# ═══════════════════════════════════════════════════════════════════════
# Recording cache: (N, 26, 1000) = 13 sensors × 2 (acc_mag, gyr_mag)
# Channel order follows SENSORS list: [LB_acc, LB_gyr, RW_acc, RW_gyr, ...]

SENSOR_TO_CHANNELS = {}
for _i, _s in enumerate(SENSORS):
    SENSOR_TO_CHANNELS[_s] = (_i * 2, _i * 2 + 1)  # (acc_mag_idx, gyr_mag_idx)


# ═══════════════════════════════════════════════════════════════════════
# SENSOR CONFIGURATIONS (22 total)
# ═══════════════════════════════════════════════════════════════════════

SENSOR_CONFIGS = OrderedDict([
    # ── Tier A: Reference ──
    ("all_13", SENSORS),

    # ── Tier B: Leave-one-location-out (8) ──
    ("no_LowerBack", [s for s in SENSORS if s != "LowerBack"]),
    ("no_Wrists", [s for s in SENSORS if "Wrist" not in s]),
    ("no_Feet", [s for s in SENSORS if "DorsalFoot" not in s]),
    ("no_Ankles", [s for s in SENSORS if "Ankle" not in s]),
    ("no_Shanks", [s for s in SENSORS if "LatShank" not in s]),
    ("no_Thighs", [s for s in SENSORS if "MidLatThigh" not in s]),
    ("no_Xiphoid", [s for s in SENSORS if s != "Xiphoid"]),
    ("no_Forehead", [s for s in SENSORS if s != "Forehead"]),

    # ── Tier C: Clinical deployment subsets (13) ──
    ("lower_back_1", ["LowerBack"]),
    ("wrists_2", ["R_Wrist", "L_Wrist"]),
    ("ankles_2", ["R_Ankle", "L_Ankle"]),
    ("back_wrists_3", ["LowerBack", "R_Wrist", "L_Wrist"]),
    ("back_ankles_3", ["LowerBack", "R_Ankle", "L_Ankle"]),
    ("wrists_ankles_4", ["R_Wrist", "L_Wrist", "R_Ankle", "L_Ankle"]),
    ("minimal_5", ["LowerBack", "R_Wrist", "L_Wrist", "R_Ankle", "L_Ankle"]),
    ("gait_7", ["LowerBack", "R_Ankle", "L_Ankle", "R_LatShank", "L_LatShank",
                "R_DorsalFoot", "L_DorsalFoot"]),
    ("lower_body_9", [s for s in SENSORS if s not in
                      ("R_Wrist", "L_Wrist", "Xiphoid", "Forehead")]),
    ("upper_body_4", ["R_Wrist", "L_Wrist", "Xiphoid", "Forehead"]),
    ("feet_ankles_4", ["R_DorsalFoot", "L_DorsalFoot", "R_Ankle", "L_Ankle"]),
    ("back_feet_3", ["LowerBack", "R_DorsalFoot", "L_DorsalFoot"]),
    ("extremity_6", ["R_Wrist", "L_Wrist", "R_Ankle", "L_Ankle",
                     "R_DorsalFoot", "L_DorsalFoot"]),
])


# ═══════════════════════════════════════════════════════════════════════
# FM EXTRACTION PER SENSOR CONFIG
# ═══════════════════════════════════════════════════════════════════════

def get_sensor_channels(sensor_list: list[str]) -> list[int]:
    """Return recording cache channel indices for a sensor subset."""
    channels = []
    for s in sensor_list:
        acc_idx, gyr_idx = SENSOR_TO_CHANNELS[s]
        channels.extend([acc_idx, gyr_idx])
    return sorted(channels)


def extract_fm_for_sensors(sensor_list: list[str], config_name: str) -> np.ndarray:
    """Extract MOMENT embeddings using only channels from sensor_list.

    Caches result to SENSOR_FM_DIR/<config_name>_fm.npz.
    Returns: (N_recordings, 768) embedding matrix.
    """
    os.makedirs(SENSOR_FM_DIR, exist_ok=True)
    cache_path = os.path.join(SENSOR_FM_DIR, f"{config_name}_fm.npz")

    if os.path.exists(cache_path):
        print(f"  [cache] Loading FM for {config_name} from {cache_path}")
        return np.load(cache_path)["embeddings"]

    # If all_13, use main FM cache ONLY if it matches recording count
    if set(sensor_list) == set(SENSORS) and os.path.exists(FM_CACHE):
        rec_count = np.load(RECORDING_CACHE)["recordings"].shape[0]
        main_fm = np.load(FM_CACHE)["embeddings"]
        if main_fm.shape[0] == rec_count:
            print(f"  [cache] Using main FM cache for all_13 ({rec_count} recordings)")
            np.savez_compressed(cache_path, embeddings=main_fm)
            return main_fm
        print(f"  [warn] Main FM cache has {main_fm.shape[0]} != {rec_count} recordings, re-extracting")

    try:
        import torch
    except ImportError:
        raise RuntimeError("PyTorch required for FM extraction. Run on GPU slave.")
    try:
        from momentfm import MOMENTPipeline
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "momentfm"])
        from momentfm import MOMENTPipeline

    assert os.path.exists(RECORDING_CACHE), f"Recording cache not found: {RECORDING_CACHE}"
    rec = np.load(RECORDING_CACHE)
    rec_array = rec["recordings"]  # (N, 26, 1000)

    # Select only channels for this sensor config
    ch_indices = get_sensor_channels(sensor_list)
    rec_subset = rec_array[:, ch_indices, :]  # (N, 2*n_sensors, 1000)
    n_ch_subset = len(ch_indices)

    print(f"  Extracting FM for {config_name}: {n_ch_subset} channels "
          f"(sensors: {sensor_list})")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  Loading MOMENT-1-base on {device}...")
    t0 = time.time()

    model = MOMENTPipeline.from_pretrained(
        "AutonLab/MOMENT-1-base",
        model_kwargs={"task_name": "embedding"}
    )
    model.init()
    model = model.to(device)
    model.eval()
    print(f"  Model loaded in {time.time()-t0:.1f}s")

    # Truncate to FM_SEQ_LEN
    trunc_len = min(FM_SEQ_LEN, rec_subset.shape[2])
    data = rec_subset[:, :, :trunc_len].copy().astype(np.float32)

    # Per-channel global z-normalize
    for ch in range(data.shape[1]):
        ch_data = data[:, ch, :].ravel()
        mu = float(np.mean(ch_data))
        std = float(np.std(ch_data)) + 1e-8
        data[:, ch, :] = (data[:, ch, :] - mu) / std

    # Pad to FM_SEQ_LEN if needed
    if trunc_len < FM_SEQ_LEN:
        pad_width = FM_SEQ_LEN - trunc_len
        data = np.pad(data, ((0, 0), (0, 0), (0, pad_width)),
                      mode='constant', constant_values=0)

    print(f"  Input: {data.shape}")

    embeddings = []
    n = len(data)
    t1 = time.time()

    with torch.no_grad():
        for i in range(0, n, FM_BATCH_SIZE):
            batch = data[i:i+FM_BATCH_SIZE]
            x = torch.from_numpy(batch).float().to(device)

            raw_batch = rec_subset[i:i+FM_BATCH_SIZE, :, :trunc_len]
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
                print(f"    FM: {done}/{n} ({elapsed:.0f}s, ETA={eta:.1f}m)")

    embeddings = np.vstack(embeddings)
    embeddings = np.nan_to_num(embeddings, nan=0.0, posinf=0.0, neginf=0.0)

    np.savez_compressed(cache_path, embeddings=embeddings)
    print(f"  FM embeddings: {embeddings.shape}, cached to {cache_path}")
    print(f"  Extraction time: {(time.time()-t0)/60:.1f}m")
    return embeddings


def preextract_all_fm():
    """Pre-extract FM embeddings for all 22 sensor configs."""
    print("=" * 70)
    print("PRE-EXTRACTING FM EMBEDDINGS FOR ALL SENSOR CONFIGS")
    print("=" * 70)
    t0 = time.time()
    for name, sensors in SENSOR_CONFIGS.items():
        extract_fm_for_sensors(sensors, name)
    print(f"\nAll FM caches built in {(time.time()-t0)/60:.1f}m")


# ═══════════════════════════════════════════════════════════════════════
# V2 FEATURE FILTERING BY SENSOR CONFIG
# ═══════════════════════════════════════════════════════════════════════

def filter_v2_features(all_v2_cols: list[str], sensor_list: list[str]) -> list[str]:
    """Return v2 feature columns available for a given sensor subset.

    Reuses the validated filtering logic from run_sensor_ablation.py.
    """
    sensor_set = set(sensor_list)
    keep = []

    for col in all_v2_cols:
        # Direct sensor-prefixed features
        matched_sensor = None
        for s in SENSORS:
            if col.startswith(s + "_"):
                matched_sensor = s
                break
        if matched_sensor is not None:
            if matched_sensor in sensor_set:
                keep.append(col)
            continue

        # Asymmetry: need both L and R
        if col.startswith("asy_"):
            parts = col.split("_")
            if len(parts) >= 2:
                pair_name = parts[1]
                if f"R_{pair_name}" in sensor_set and f"L_{pair_name}" in sensor_set:
                    keep.append(col)
            continue

        # Event/turn/balance/STS: derived from LowerBack
        if col.startswith(("ev_", "trn_", "sts_", "bal_")):
            if "LowerBack" in sensor_set:
                keep.append(col)
            continue

        # Foot contact
        if col.startswith("fc_"):
            foot_sensors = {"R_DorsalFoot", "L_DorsalFoot", "R_Ankle", "L_Ankle"}
            if sensor_set & foot_sensors:
                keep.append(col)
            continue

        # Kinematics
        if col.startswith("k_"):
            side = col[2] if len(col) > 2 else ""
            ankle = f"{side}_Ankle"
            shank = f"{side}_LatShank"
            if ankle in sensor_set or shank in sensor_set:
                keep.append(col)
            continue

        # Distribution/contrast
        if col.startswith(("dv_", "d_", "r_")):
            found = any(s in col for s in sensor_set)
            if found or not any(s in col for s in SENSORS):
                keep.append(col)
            continue

        # Covariates: always keep
        if col.startswith(("cv_", "n_")) or col in ("duration_s",):
            keep.append(col)
            continue

        # Distilled walkway: EXCLUDED (learned from full sensors)
        if col.startswith("dst_"):
            continue

        # Unknown — keep
        keep.append(col)

    return keep


# ═══════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════

def parse_per_item_scores():
    """Load per-item UPDRS scores for all subjects."""
    if os.path.exists(PER_ITEM_CACHE):
        with open(PER_ITEM_CACHE) as f:
            return json.load(f)

    subjects = parse_clinical()
    item_scores = {}
    for filename, group in [
        ("PD - Demographic+Clinical - datasetV1.csv", "PD"),
        ("CONTROLS - Demographic+Clinical - datasetV1.csv", "HC"),
    ]:
        from data_split import DATA_DIR
        path = os.path.join(str(DATA_DIR), filename)
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, header=1)
        for _, row in df.iterrows():
            sid = str(row.get("Subject ID", "")).strip()
            if sid in ("", "nan") or sid not in subjects:
                continue
            scores = {}
            for item_num in range(1, 19):
                val = find_updrs_value(row, item_num, SUBITEMS_MAP)
                if val is not None:
                    scores[str(item_num)] = val
            if scores:
                item_scores[sid] = scores

    with open(PER_ITEM_CACHE, "w") as f:
        json.dump(item_scores, f, indent=2)
    return item_scores


def compute_target(item_scores: dict, sid: str, target_key: str):
    """Compute target score for a subject."""
    if sid not in item_scores:
        return None
    scores = item_scores[sid]

    if target_key == "t1":
        # Items 9-14 (direct observable)
        items = [9, 10, 11, 12, 13, 14]
        vals = [scores.get(str(i)) for i in items]
        if any(v is None for v in vals):
            return None
        return float(sum(vals))

    elif target_key == "t2":
        # Items 7-14 (broad observable), items 7-8 use max(L,R)
        total = 0.0
        for i in [7, 8]:
            v = scores.get(str(i))
            if v is None:
                return None
            total += v  # Already max(L,R) from find_updrs_value
        for i in [9, 10, 11, 12, 13, 14]:
            v = scores.get(str(i))
            if v is None:
                return None
            total += v
        return total

    elif target_key == "t3":
        return None  # Handled from updrs3 column directly

    raise ValueError(f"Unknown target: {target_key}")


def load_features_for_config(config_name: str, sensor_list: list[str]):
    """Load v2 + per-config FM features, merge, and return dataframes.

    Returns: (pd_merged, all_merged, feature_cols, subjects, item_scores)
    """
    assert os.path.exists(V2_CACHE), f"V2 cache not found: {V2_CACHE}"
    assert os.path.exists(RECORDING_CACHE), f"Recording cache not found: {RECORDING_CACHE}"

    # ── V2 features ──
    v2_df = pd.read_csv(V2_CACHE)
    EXCLUDED_COLS = {"sid", "updrs3", "obs_subscore", "hy"}
    EXTRA_PREFIXES = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")
    all_v2_cols = [c for c in v2_df.columns
                   if c not in EXCLUDED_COLS
                   and not any(c.startswith(p) for p in EXTRA_PREFIXES)]

    # Filter v2 by sensor config
    sensor_v2_cols = filter_v2_features(all_v2_cols, sensor_list)

    # ── FM embeddings (per-config) ──
    fm_embeddings = extract_fm_for_sensors(sensor_list, config_name)
    rec_sids = np.load(RECORDING_CACHE)["sids"].tolist()

    d_model = fm_embeddings.shape[1]
    fm_df = pd.DataFrame(fm_embeddings, columns=[f"fm_{i}" for i in range(d_model)])
    fm_df["sid"] = rec_sids
    fm_agg = fm_df.groupby("sid").mean().reset_index()
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]

    # ── Merge ──
    merged = v2_df[["sid", "updrs3"] + sensor_v2_cols].merge(
        fm_agg, on="sid", how="left"
    ).fillna(0.0)
    feature_cols = sensor_v2_cols + fm_cols

    # ── Targets ──
    item_scores = parse_per_item_scores()
    subjects = parse_clinical()
    merged["t1_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t1"))
    merged["t2_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t2"))
    merged["t3_target"] = merged["updrs3"].astype(float)

    pd_sids = {sid for sid, info in subjects.items() if info.get("group") == "PD"}
    all_sids = set(subjects.keys())

    pd_mask = merged["sid"].isin(pd_sids)
    pd_valid = pd_mask & merged["t1_target"].notna() & merged["t2_target"].notna()
    pd_merged = merged[pd_valid].copy()
    for tk in ["t1", "t2", "t3"]:
        pd_merged[f"{tk}_target"] = pd_merged[f"{tk}_target"].astype(np.float32)

    all_valid = merged["t1_target"].notna() & merged["t2_target"].notna()
    all_merged = merged[all_valid].copy()
    for tk in ["t1", "t2", "t3"]:
        all_merged[f"{tk}_target"] = all_merged[f"{tk}_target"].astype(np.float32)
    all_merged["is_pd"] = all_merged["sid"].isin(pd_sids).astype(int)

    print(f"  Config {config_name}: {len(sensor_v2_cols)} v2 + {len(fm_cols)} FM = "
          f"{len(feature_cols)} features, {len(pd_merged)} PD, {len(all_merged)} all")

    return pd_merged, all_merged, feature_cols, subjects, item_scores


# ═══════════════════════════════════════════════════════════════════════
# TRAINING
# ═══════════════════════════════════════════════════════════════════════

def train_lgb(Xd, yd, Xt, seed, params=None):
    """Train LightGBM with early stopping, return test predictions."""
    assert _HAS_ML, "lightgbm/xgboost required. Run on GPU slave."
    p = dict(DEFAULT_LGB_PARAMS)
    if params:
        p.update(params)
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * p.get("val_frac", 0.15)))
    m = lgb.LGBMRegressor(
        n_estimators=p["n_estimators"],
        learning_rate=p["learning_rate"],
        max_depth=p["max_depth"],
        num_leaves=p["num_leaves"],
        reg_lambda=p["reg_lambda"],
        min_data_in_leaf=p["min_data_in_leaf"],
        colsample_bytree=p["colsample_bytree"],
        subsample=p["subsample"],
        random_state=seed,
        n_jobs=N_CORES,
        objective=p["objective"],
        verbose=-1,
    )
    m.fit(
        X=Xd[idx[nv:]],
        y=yd[idx[nv:]],
        eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
        callbacks=[lgb.early_stopping(p["early_stopping_rounds"], verbose=False)],
    )
    return m.predict(Xt)


# ═══════════════════════════════════════════════════════════════════════
# SSL RANKING LOOCV
# ═══════════════════════════════════════════════════════════════════════

def run_ssl_loocv(pd_merged, all_merged, feature_cols, target_key):
    """Run P5 SSL ranking with LOOCV evaluation.

    Stage 1: XGBRanker on all subjects (PD+HC) — learns severity ordering
    Stage 2: Extract leaf indices as features
    Stage 3: LGB on PD-only using original + leaf features
    Evaluation: PD-only LOOCV
    """
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    # Pre-compute ranking labels for ALL subjects
    ranker_sids = all_merged["sid"].values
    ranker_targets = all_merged[target_col].values.astype(np.float32)
    ranker_is_pd = all_merged["is_pd"].values
    X_ranker = all_merged[feature_cols].values.astype(np.float32)

    rank_labels = np.zeros(len(ranker_sids), dtype=np.int32)
    pd_indices = np.where(ranker_is_pd == 1)[0]
    pd_order = np.argsort(ranker_targets[pd_indices])
    for rank, idx in enumerate(pd_order):
        rank_labels[pd_indices[idx]] = rank + 1

    sid_to_ranker_idx = {s: i for i, s in enumerate(ranker_sids)}
    n_hc = int((ranker_is_pd == 0).sum())
    n_pd = int((ranker_is_pd == 1).sum())
    print(f"  Ranker: {n_hc} HC + {n_pd} PD = {len(ranker_sids)} total")

    # PD-only LOOCV
    sids = pd_merged["sid"].values
    n = len(sids)
    y_true_all = pd_merged[target_col].values.astype(np.float32)
    X_all = pd_merged[feature_cols].values.astype(np.float32)
    y_pred_all = np.zeros(n, dtype=np.float64)

    t0 = time.time()

    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        Xd, yd = X_all[mask], y_true_all[mask]
        Xt = X_all[i:i+1]
        sids_train = sids[mask].tolist()
        sids_test = [sids[i]]

        # Feature selection inside fold
        k = min(500, Xd.shape[1])
        sel_idx, sel_names = feature_select(Xd, yd, list(feature_cols), k=k)
        Xd_sel = Xd[:, sel_idx]
        Xt_sel = Xt[:, sel_idx]

        # Stage 1: Train XGBRanker on ALL subjects using selected features
        X_ranker_sel = X_ranker[:, sel_idx]
        group_sizes = np.array([len(X_ranker_sel)])

        all_leaf_features = []
        for seed in SEEDS[:3]:
            ranker = XGBRanker(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
                objective="rank:pairwise",
            )
            ranker.fit(X_ranker_sel, rank_labels, group=group_sizes)

            # Stage 2: Extract leaf indices
            train_ranker_indices = [sid_to_ranker_idx[s] for s in sids_train
                                    if s in sid_to_ranker_idx]
            test_ranker_indices = [sid_to_ranker_idx[s] for s in sids_test
                                   if s in sid_to_ranker_idx]

            train_leaves = ranker.apply(X_ranker_sel[train_ranker_indices])
            test_leaves = ranker.apply(X_ranker_sel[test_ranker_indices])
            all_leaf_features.append((train_leaves, test_leaves))

        train_leaf_cat = np.hstack([lf[0] for lf in all_leaf_features]).astype(np.float32)
        test_leaf_cat = np.hstack([lf[1] for lf in all_leaf_features]).astype(np.float32)

        # Stage 3: Original + leaf features → LGB
        Xd_combined = np.hstack([Xd_sel, train_leaf_cat])
        Xt_combined = np.hstack([Xt_sel, test_leaf_cat])

        preds = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd, Xt_combined, s)
            preds.append(np.clip(p, clip_lo, clip_hi))
        ep = np.mean(preds, axis=0)
        y_pred_all[i] = float(ep[0]) if hasattr(ep, '__len__') else float(ep)

        if (i + 1) % LOOCV_PROGRESS_EVERY == 0:
            running_mae = float(np.mean(np.abs(y_true_all[:i+1] - y_pred_all[:i+1])))
            running_ccc = lins_ccc(y_true_all[:i+1], y_pred_all[:i+1])
            elapsed = time.time() - t0
            remaining = elapsed / (i + 1) * (n - i - 1)
            print(f"    [{i+1}/{n}] CCC={running_ccc:.3f} MAE={running_mae:.3f} "
                  f"({elapsed:.0f}s, ~{remaining:.0f}s remaining)")

    metrics = full_metrics(y_true_all, y_pred_all, target_key)
    metrics["eval_mode"] = "loocv"
    metrics["runtime_s"] = round(time.time() - t0, 1)
    metrics["per_subject"] = {
        "sids": sids.tolist(),
        "y_true": y_true_all.tolist(),
        "y_pred": y_pred_all.tolist(),
    }
    return metrics


def run_ssl_5split(pd_merged, all_merged, feature_cols, target_key):
    """Run P5 SSL ranking with 5-fold CV (faster, for initial screening)."""
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    ranker_sids = all_merged["sid"].values
    ranker_targets = all_merged[target_col].values.astype(np.float32)
    ranker_is_pd = all_merged["is_pd"].values
    X_ranker = all_merged[feature_cols].values.astype(np.float32)

    rank_labels = np.zeros(len(ranker_sids), dtype=np.int32)
    pd_indices = np.where(ranker_is_pd == 1)[0]
    pd_order = np.argsort(ranker_targets[pd_indices])
    for rank, idx in enumerate(pd_order):
        rank_labels[pd_indices[idx]] = rank + 1

    sid_to_ranker_idx = {s: i for i, s in enumerate(ranker_sids)}

    n_splits = 5
    all_true, all_pred, all_sids_out = [], [], []
    t0 = time.time()

    for split_i in range(1, n_splits + 1):
        dev_s, test_s = _gen_split(pd_merged, split_i, target_key)
        dm = pd_merged["sid"].isin(dev_s)
        tm = pd_merged["sid"].isin(test_s)
        Xd = pd_merged.loc[dm, feature_cols].values.astype(np.float32)
        yd = pd_merged.loc[dm, target_col].values.astype(np.float32)
        Xt = pd_merged.loc[tm, feature_cols].values.astype(np.float32)
        yt = pd_merged.loc[tm, target_col].values.astype(np.float32)
        sids_train = pd_merged.loc[dm, "sid"].values.tolist()
        sids_test = pd_merged.loc[tm, "sid"].values.tolist()

        k = min(500, Xd.shape[1])
        sel_idx, _ = feature_select(Xd, yd, list(feature_cols), k=k)
        Xd_sel = Xd[:, sel_idx]
        Xt_sel = Xt[:, sel_idx]

        X_ranker_sel = X_ranker[:, sel_idx]
        group_sizes = np.array([len(X_ranker_sel)])

        all_leaf_features = []
        for seed in SEEDS[:3]:
            ranker = XGBRanker(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
                objective="rank:pairwise",
            )
            ranker.fit(X_ranker_sel, rank_labels, group=group_sizes)

            train_idx = [sid_to_ranker_idx[s] for s in sids_train if s in sid_to_ranker_idx]
            test_idx = [sid_to_ranker_idx[s] for s in sids_test if s in sid_to_ranker_idx]
            train_leaves = ranker.apply(X_ranker_sel[train_idx])
            test_leaves = ranker.apply(X_ranker_sel[test_idx])
            all_leaf_features.append((train_leaves, test_leaves))

        train_leaf_cat = np.hstack([lf[0] for lf in all_leaf_features]).astype(np.float32)
        test_leaf_cat = np.hstack([lf[1] for lf in all_leaf_features]).astype(np.float32)

        Xd_combined = np.hstack([Xd_sel, train_leaf_cat])
        Xt_combined = np.hstack([Xt_sel, test_leaf_cat])

        preds = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd, Xt_combined, s)
            preds.append(np.clip(p, clip_lo, clip_hi))
        ep = np.mean(preds, axis=0)

        ccc = lins_ccc(yt, ep)
        mae = float(np.mean(np.abs(yt - ep)))
        print(f"  Split {split_i}/{n_splits}: CCC={ccc:.3f} MAE={mae:.3f}")

        all_true.extend(yt.tolist())
        all_pred.extend(ep.tolist())
        all_sids_out.extend(sids_test)

    metrics = full_metrics(np.array(all_true), np.array(all_pred), target_key)
    metrics["eval_mode"] = "5split"
    metrics["runtime_s"] = round(time.time() - t0, 1)
    metrics["per_subject"] = {
        "sids": all_sids_out,
        "y_true": all_true,
        "y_pred": [float(p) for p in all_pred],
    }
    return metrics


def _target_bin(score, target_key):
    clip_lo, clip_hi = TARGET_CLIP[target_key]
    rng = clip_hi - clip_lo
    if score < clip_lo + rng * 0.25:
        return 0
    elif score < clip_lo + rng * 0.5:
        return 1
    elif score < clip_lo + rng * 0.75:
        return 2
    return 3


def _gen_split(pd_merged, seed, target_key):
    """Stratified 80/20 split."""
    from sklearn.model_selection import StratifiedShuffleSplit
    sids = pd_merged["sid"].values
    target_col = f"{target_key}_target"
    bins = pd_merged[target_col].apply(lambda x: _target_bin(x, target_key)).values
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    dev_i, test_i = next(sss.split(sids, bins))
    return sids[dev_i].tolist(), sids[test_i].tolist()


# ═══════════════════════════════════════════════════════════════════════
# METRICS
# ═══════════════════════════════════════════════════════════════════════

def full_metrics(y_true, y_pred, target_key):
    """Compute all metrics."""
    y_true = np.asarray(y_true, dtype=np.float64)
    y_pred = np.asarray(y_pred, dtype=np.float64)
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    r = float(sp_stats.pearsonr(y_true, y_pred)[0]) if len(y_true) > 2 else 0.0
    ccc = lins_ccc(y_true, y_pred)
    slope = cal_slope(y_true, y_pred)
    return {
        "mae": round(mae, 3),
        "rmse": round(rmse, 3),
        "r": round(r, 3),
        "ccc": round(ccc, 3),
        "cal_slope": round(slope, 3),
        "n": int(len(y_true)),
    }


# ═══════════════════════════════════════════════════════════════════════
# BOOTSTRAP ANALYSIS (Phase 4)
# ═══════════════════════════════════════════════════════════════════════

def bootstrap_ccc_ci(y_true, y_pred, n_boot=10000, alpha=0.05):
    """BCa bootstrap CI for CCC."""
    n = len(y_true)
    boot_cccs = np.zeros(n_boot)
    rng = np.random.RandomState(42)

    for b in range(n_boot):
        idx = rng.choice(n, n, replace=True)
        boot_cccs[b] = lins_ccc(y_true[idx], y_pred[idx])

    lo = np.percentile(boot_cccs, 100 * alpha / 2)
    hi = np.percentile(boot_cccs, 100 * (1 - alpha / 2))
    return float(lo), float(hi), boot_cccs


def paired_bootstrap_diff(y_true, y_pred_a, y_pred_b, n_boot=10000):
    """Paired bootstrap of CCC difference: CCC(A) - CCC(B).

    Returns: (mean_diff, ci_lo, ci_hi, p_value)
    """
    n = len(y_true)
    diffs = np.zeros(n_boot)
    rng = np.random.RandomState(42)

    for b in range(n_boot):
        idx = rng.choice(n, n, replace=True)
        ccc_a = lins_ccc(y_true[idx], y_pred_a[idx])
        ccc_b = lins_ccc(y_true[idx], y_pred_b[idx])
        diffs[b] = ccc_a - ccc_b

    mean_diff = float(np.mean(diffs))
    ci_lo = float(np.percentile(diffs, 2.5))
    ci_hi = float(np.percentile(diffs, 97.5))
    # Two-sided p-value: proportion of bootstrap samples where diff crosses 0
    p_value = float(2 * min(np.mean(diffs >= 0), np.mean(diffs <= 0)))
    return mean_diff, ci_lo, ci_hi, p_value


def tost_non_inferiority(y_true, y_pred_config, y_pred_ref,
                         delta=0.05, n_boot=10000):
    """TOST non-inferiority test for CCC.

    Tests H0: CCC_config - CCC_ref <= -delta (inferior)
    vs    H1: CCC_config - CCC_ref > -delta (non-inferior)

    Returns: (non_inferior: bool, ci_lo: float, p_value: float)
    """
    n = len(y_true)
    diffs = np.zeros(n_boot)
    rng = np.random.RandomState(42)

    for b in range(n_boot):
        idx = rng.choice(n, n, replace=True)
        ccc_config = lins_ccc(y_true[idx], y_pred_config[idx])
        ccc_ref = lins_ccc(y_true[idx], y_pred_ref[idx])
        diffs[b] = ccc_config - ccc_ref

    ci_lo = float(np.percentile(diffs, 5.0))  # One-sided 95% CI lower bound
    p_value = float(np.mean(diffs <= -delta))  # P(diff <= -delta)
    non_inferior = ci_lo > -delta
    return non_inferior, ci_lo, p_value


def run_analysis(results_dir=None):
    """Phase 4: Statistical analysis on all completed sensor span results.

    Loads all sensor_span_*.json files, runs TOST non-inferiority tests,
    generates summary tables.
    """
    if results_dir is None:
        results_dir = str(RESULTS_DIR)

    # Load all results
    import glob
    files = sorted(glob.glob(os.path.join(results_dir, "sensor_span_*.json")))
    if not files:
        print("ERROR: No sensor_span_*.json files found")
        sys.exit(1)

    results = {}
    for f in files:
        with open(f) as fh:
            data = json.load(fh)
        key = (data["config"], data["target"])
        results[key] = data

    targets = sorted(set(k[1] for k in results.keys()))
    configs = list(SENSOR_CONFIGS.keys())

    delta = 0.05  # Pre-specified non-inferiority margin

    print("\n" + "=" * 100)
    print("SENSOR SPAN STATISTICAL ANALYSIS")
    print(f"Non-inferiority margin: delta = {delta} CCC")
    print("=" * 100)

    analysis_results = {"delta": delta, "targets": {}}

    for target in targets:
        print(f"\n{'─' * 80}")
        print(f"Target: {target.upper()}")
        print(f"{'─' * 80}")

        ref_key = ("all_13", target)
        if ref_key not in results:
            print(f"  WARNING: No all_13 result for {target}")
            continue

        ref = results[ref_key]
        ref_true = np.array(ref["per_subject"]["y_true"])
        ref_pred = np.array(ref["per_subject"]["y_pred"])
        ref_ccc = ref["ccc"]

        _, ref_ci_lo, ref_ci_hi, _ = bootstrap_ccc_ci(ref_true, ref_pred)

        print(f"  Reference (all_13): CCC={ref_ccc:.3f} [{ref_ci_lo:.3f}, {ref_ci_hi:.3f}]")
        print()
        print(f"  {'Config':<20} {'#Sen':>4} {'CCC':>7} {'CI_lo':>7} {'CI_hi':>7} "
              f"{'ΔCCC':>7} {'NonInf':>7} {'p':>7}")
        print(f"  {'-'*80}")

        target_analysis = {"ref_ccc": ref_ccc, "ref_ci": [ref_ci_lo, ref_ci_hi], "configs": {}}

        pvalues = []
        config_names = []

        for cfg_name in configs:
            if cfg_name == "all_13":
                continue
            key = (cfg_name, target)
            if key not in results:
                continue

            data = results[key]
            cfg_true = np.array(data["per_subject"]["y_true"])
            cfg_pred = np.array(data["per_subject"]["y_pred"])

            # Bootstrap CI for this config
            _, cfg_ci_lo, cfg_ci_hi, _ = bootstrap_ccc_ci(cfg_true, cfg_pred)

            # TOST non-inferiority
            # Need aligned subjects — LOOCV should have same subjects
            assert len(cfg_true) == len(ref_true), (
                f"Subject count mismatch: {cfg_name}={len(cfg_true)} vs ref={len(ref_true)}")

            non_inf, tost_ci_lo, tost_p = tost_non_inferiority(
                ref_true, cfg_pred, ref_pred, delta=delta)

            dccc = data["ccc"] - ref_ccc
            marker = "YES" if non_inf else "no"

            n_sensors = len(SENSOR_CONFIGS.get(cfg_name, []))
            print(f"  {cfg_name:<20} {n_sensors:>4} {data['ccc']:>7.3f} "
                  f"{cfg_ci_lo:>7.3f} {cfg_ci_hi:>7.3f} "
                  f"{dccc:>+7.3f} {marker:>7} {tost_p:>7.3f}")

            target_analysis["configs"][cfg_name] = {
                "n_sensors": n_sensors,
                "ccc": data["ccc"],
                "mae": data["mae"],
                "ci": [cfg_ci_lo, cfg_ci_hi],
                "delta_ccc": round(dccc, 4),
                "non_inferior": non_inf,
                "tost_ci_lo": tost_ci_lo,
                "tost_p": round(tost_p, 4),
            }
            pvalues.append(tost_p)
            config_names.append(cfg_name)

        # Holm-Bonferroni correction
        if pvalues:
            sorted_indices = np.argsort(pvalues)
            m = len(pvalues)
            corrected = {}
            for rank, idx in enumerate(sorted_indices):
                corrected_p = min(1.0, pvalues[idx] * (m - rank))
                corrected[config_names[idx]] = corrected_p
                target_analysis["configs"][config_names[idx]]["holm_p"] = round(corrected_p, 4)
                target_analysis["configs"][config_names[idx]]["holm_non_inferior"] = corrected_p < 0.05

            print(f"\n  Holm-Bonferroni corrected non-inferiority (alpha=0.05):")
            for cfg_name in configs:
                if cfg_name in corrected:
                    verdict = "YES" if corrected[cfg_name] < 0.05 else "no"
                    print(f"    {cfg_name:<20} Holm p={corrected[cfg_name]:.4f} → {verdict}")

        analysis_results["targets"][target] = target_analysis

    # Save analysis
    out_path = str(results_artifact_path("sensor_span_analysis.json"))
    with open(out_path, "w") as f:
        json.dump(analysis_results, f, indent=2)
    print(f"\nAnalysis saved: {out_path}")


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def run_k_sweep():
    """4B.1: Sweep K for key configs to test if fixed K=500 is a confound."""
    KEY_CONFIGS = ["all_13", "lower_back_1", "minimal_5", "wrists_ankles_4"]
    K_VALUES = [100, 200, 300, 500, 800]
    TARGETS = ["t1", "t2", "t3"]

    print("=" * 80)
    print("K-SWEEP: Testing if fixed K=500 is a confound")
    print(f"Configs: {KEY_CONFIGS}")
    print(f"K values: {K_VALUES}")
    print("=" * 80)

    all_results = []
    t_global = time.time()

    for cfg_name in KEY_CONFIGS:
        sensor_list = SENSOR_CONFIGS[cfg_name]
        pd_merged, all_merged, feature_cols, _, _ = \
            load_features_for_config(cfg_name, sensor_list)

        for target_key in TARGETS:
            for k_val in K_VALUES:
                effective_k = min(k_val, len(feature_cols))
                if effective_k < 20:
                    continue

                print(f"\n  {cfg_name} × {target_key.upper()} × K={k_val} "
                      f"(effective={effective_k}/{len(feature_cols)})")

                # Run 5-split with custom K
                metrics = _run_k_sweep_5split(
                    pd_merged, all_merged, feature_cols,
                    target_key, effective_k)

                metrics["config"] = cfg_name
                metrics["target"] = target_key
                metrics["k_value"] = k_val
                metrics["effective_k"] = effective_k
                metrics["n_sensors"] = len(sensor_list)
                metrics["n_features"] = len(feature_cols)
                metrics["k_fraction"] = round(effective_k / len(feature_cols), 3)

                print(f"    CCC={metrics['ccc']:.3f} MAE={metrics['mae']:.3f} "
                      f"(K={effective_k}, {metrics['k_fraction']*100:.0f}% of features)")
                all_results.append(metrics)

    # Summary
    print(f"\n{'=' * 100}")
    print(f"{'Config':<20} {'Target':<6} {'K':>5} {'K%':>5} {'CCC':>7} {'MAE':>7}")
    print(f"{'─' * 100}")
    for r in all_results:
        print(f"{r['config']:<20} {r['target']:<6} {r['k_value']:>5} "
              f"{r['k_fraction']*100:>4.0f}% {r['ccc']:>7.3f} {r['mae']:>7.3f}")
    print(f"{'=' * 100}")
    print(f"Total: {(time.time() - t_global)/60:.1f}m")

    out_path = str(results_artifact_path("sensor_span_k_sweep.json"))
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"Saved: {out_path}")


def _run_k_sweep_5split(pd_merged, all_merged, feature_cols, target_key, k_val):
    """5-split SSL with custom K value."""
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    ranker_sids = all_merged["sid"].values
    ranker_targets = all_merged[target_col].values.astype(np.float32)
    ranker_is_pd = all_merged["is_pd"].values
    X_ranker = all_merged[feature_cols].values.astype(np.float32)

    rank_labels = np.zeros(len(ranker_sids), dtype=np.int32)
    pd_indices = np.where(ranker_is_pd == 1)[0]
    pd_order = np.argsort(ranker_targets[pd_indices])
    for rank, idx in enumerate(pd_order):
        rank_labels[pd_indices[idx]] = rank + 1

    sid_to_ranker_idx = {s: i for i, s in enumerate(ranker_sids)}

    all_true, all_pred = [], []
    t0 = time.time()

    for split_i in range(1, 6):
        dev_s, test_s = _gen_split(pd_merged, split_i, target_key)
        dm = pd_merged["sid"].isin(dev_s)
        tm = pd_merged["sid"].isin(test_s)
        Xd = pd_merged.loc[dm, feature_cols].values.astype(np.float32)
        yd = pd_merged.loc[dm, target_col].values.astype(np.float32)
        Xt = pd_merged.loc[tm, feature_cols].values.astype(np.float32)
        yt = pd_merged.loc[tm, target_col].values.astype(np.float32)
        sids_train = pd_merged.loc[dm, "sid"].values.tolist()
        sids_test = pd_merged.loc[tm, "sid"].values.tolist()

        sel_idx, _ = feature_select(Xd, yd, list(feature_cols), k=k_val)
        Xd_sel = Xd[:, sel_idx]
        Xt_sel = Xt[:, sel_idx]

        X_ranker_sel = X_ranker[:, sel_idx]
        group_sizes = np.array([len(X_ranker_sel)])

        all_leaf_features = []
        for seed in SEEDS[:3]:
            ranker = XGBRanker(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
                objective="rank:pairwise",
            )
            ranker.fit(X_ranker_sel, rank_labels, group=group_sizes)

            train_idx = [sid_to_ranker_idx[s] for s in sids_train if s in sid_to_ranker_idx]
            test_idx = [sid_to_ranker_idx[s] for s in sids_test if s in sid_to_ranker_idx]
            train_leaves = ranker.apply(X_ranker_sel[train_idx])
            test_leaves = ranker.apply(X_ranker_sel[test_idx])
            all_leaf_features.append((train_leaves, test_leaves))

        train_leaf_cat = np.hstack([lf[0] for lf in all_leaf_features]).astype(np.float32)
        test_leaf_cat = np.hstack([lf[1] for lf in all_leaf_features]).astype(np.float32)

        Xd_combined = np.hstack([Xd_sel, train_leaf_cat])
        Xt_combined = np.hstack([Xt_sel, test_leaf_cat])

        preds = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd, Xt_combined, s)
            preds.append(np.clip(p, clip_lo, clip_hi))
        ep = np.mean(preds, axis=0)

        all_true.extend(yt.tolist())
        all_pred.extend(ep.tolist())

    metrics = full_metrics(np.array(all_true), np.array(all_pred), target_key)
    metrics["eval_mode"] = "5split"
    metrics["runtime_s"] = round(time.time() - t0, 1)
    return metrics


def run_fm_decomposition():
    """4B.2: Run key configs with v2-only and FM-only to test FM confound."""
    KEY_CONFIGS = ["all_13", "lower_back_1", "minimal_5", "wrists_ankles_4"]
    TARGETS = ["t1", "t3"]

    print("=" * 80)
    print("FM DECOMPOSITION: v2-only vs FM-only vs combined")
    print("=" * 80)

    all_results = []
    t_global = time.time()

    for cfg_name in KEY_CONFIGS:
        sensor_list = SENSOR_CONFIGS[cfg_name]
        pd_merged, all_merged, feature_cols, _, _ = \
            load_features_for_config(cfg_name, sensor_list)

        v2_cols = [c for c in feature_cols if not c.startswith("fm_")]
        fm_cols = [c for c in feature_cols if c.startswith("fm_")]

        for target_key in TARGETS:
            for mode, cols in [("v2_only", v2_cols), ("fm_only", fm_cols), ("combined", feature_cols)]:
                if len(cols) < 10:
                    print(f"  SKIP {cfg_name} × {target_key} × {mode}: only {len(cols)} features")
                    continue

                print(f"\n  {cfg_name} × {target_key.upper()} × {mode} ({len(cols)} features)")

                metrics = _run_k_sweep_5split(
                    pd_merged, all_merged, cols, target_key, min(500, len(cols)))

                metrics["config"] = cfg_name
                metrics["target"] = target_key
                metrics["feature_mode"] = mode
                metrics["n_sensors"] = len(sensor_list)
                metrics["n_features"] = len(cols)

                print(f"    CCC={metrics['ccc']:.3f} MAE={metrics['mae']:.3f}")
                all_results.append(metrics)

    # Summary
    print(f"\n{'=' * 90}")
    print(f"{'Config':<20} {'Target':<6} {'Mode':<12} {'#Feat':>6} {'CCC':>7} {'MAE':>7}")
    print(f"{'─' * 90}")
    for r in all_results:
        print(f"{r['config']:<20} {r['target']:<6} {r['feature_mode']:<12} "
              f"{r['n_features']:>6} {r['ccc']:>7.3f} {r['mae']:>7.3f}")
    print(f"{'=' * 90}")
    print(f"Total: {(time.time() - t_global)/60:.1f}m")

    out_path = str(results_artifact_path("sensor_span_fm_decomposition.json"))
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"Saved: {out_path}")


def run_repeated_cv():
    """4B.4: 10×5-fold repeated nested CV for 4 key configs.

    Codex's highest-value recommendation: lock 4 configs, run repeated CV,
    compute paired bootstrap CIs with non-inferiority margins.
    """
    KEY_CONFIGS = ["all_13", "lower_back_1", "minimal_5", "wrists_ankles_4"]
    TARGETS = ["t1", "t2", "t3"]
    N_REPEATS = 10
    CV_SEEDS = list(range(1, N_REPEATS + 1))  # seeds 1-10

    print("=" * 80)
    print(f"REPEATED {N_REPEATS}×5-FOLD CV — 4 key configs × 3 targets")
    print("=" * 80)

    # Load features for each config once
    config_data = {}
    for cfg_name in KEY_CONFIGS:
        sensor_list = SENSOR_CONFIGS[cfg_name]
        pd_merged, all_merged, feature_cols, _, _ = \
            load_features_for_config(cfg_name, sensor_list)
        config_data[cfg_name] = (pd_merged, all_merged, feature_cols)

    all_results = {}  # {(config, target): [ccc_per_repeat]}
    per_subject_all = {}  # {(config, target, repeat): {sids, y_true, y_pred}}
    t_global = time.time()

    for cfg_name in KEY_CONFIGS:
        pd_merged, all_merged, feature_cols = config_data[cfg_name]

        for target_key in TARGETS:
            repeat_cccs = []
            repeat_maes = []

            for rep_i, seed in enumerate(CV_SEEDS):
                metrics = _run_repeated_5split(
                    pd_merged, all_merged, feature_cols,
                    target_key, base_seed=seed * 100)

                repeat_cccs.append(metrics["ccc"])
                repeat_maes.append(metrics["mae"])
                per_subject_all[(cfg_name, target_key, rep_i)] = metrics.get("per_subject", {})

                if (rep_i + 1) % 5 == 0 or rep_i == N_REPEATS - 1:
                    mean_ccc = float(np.mean(repeat_cccs))
                    std_ccc = float(np.std(repeat_cccs))
                    print(f"  {cfg_name} × {target_key.upper()}: rep {rep_i+1}/{N_REPEATS} "
                          f"mean CCC={mean_ccc:.3f}±{std_ccc:.3f}")

            all_results[(cfg_name, target_key)] = {
                "cccs": repeat_cccs,
                "maes": repeat_maes,
                "mean_ccc": round(float(np.mean(repeat_cccs)), 4),
                "std_ccc": round(float(np.std(repeat_cccs)), 4),
                "mean_mae": round(float(np.mean(repeat_maes)), 3),
                "std_mae": round(float(np.std(repeat_maes)), 3),
            }

    # Summary + paired comparisons
    print(f"\n{'=' * 90}")
    print(f"{'Config':<22} {'Target':<6} {'Mean CCC':>10} {'±Std':>7} {'Mean MAE':>10} {'±Std':>7}")
    print(f"{'─' * 90}")
    for cfg_name in KEY_CONFIGS:
        for target_key in TARGETS:
            r = all_results[(cfg_name, target_key)]
            print(f"  {cfg_name:<20} {target_key:<6} {r['mean_ccc']:>10.4f} "
                  f"±{r['std_ccc']:>5.4f} {r['mean_mae']:>10.3f} ±{r['std_mae']:>5.3f}")
        print()

    # Paired comparisons vs all_13
    print(f"\n{'=' * 90}")
    print("PAIRED COMPARISONS vs all_13 (Nadeau-Bengio corrected resampled t-test)")
    print(f"{'─' * 90}")
    delta = 0.05  # non-inferiority margin

    paired_results = {}
    for target_key in TARGETS:
        ref = all_results[("all_13", target_key)]
        print(f"\n  Target: {target_key.upper()} — all_13 mean CCC = {ref['mean_ccc']:.4f}")

        for cfg_name in KEY_CONFIGS:
            if cfg_name == "all_13":
                continue
            cfg = all_results[(cfg_name, target_key)]
            diffs = [c - r for c, r in zip(cfg["cccs"], ref["cccs"])]
            mean_diff = float(np.mean(diffs))
            std_diff = float(np.std(diffs, ddof=1))
            n = len(diffs)

            # Nadeau-Bengio corrected variance: accounts for train/test overlap
            # correction factor = 1/n + n_test/(n_train) ≈ 1/10 + 19/76 ≈ 0.35
            test_frac = 0.2
            correction = 1.0 / n + test_frac / (1.0 - test_frac)
            se_corrected = std_diff * np.sqrt(correction)

            # t-statistic for superiority (diff > 0)
            t_stat = mean_diff / max(se_corrected, 1e-10)
            from scipy.stats import t as t_dist
            p_sup = float(1 - t_dist.cdf(t_stat, df=n - 1))

            # Non-inferiority: test if diff > -delta
            t_ni = (mean_diff + delta) / max(se_corrected, 1e-10)
            p_ni = float(1 - t_dist.cdf(t_ni, df=n - 1))
            non_inf = p_ni < 0.05

            marker = "NON-INF" if non_inf else "---"
            print(f"    {cfg_name:<20} ΔCCC={mean_diff:+.4f}±{std_diff:.4f} "
                  f"t={t_stat:+.2f} p_sup={p_sup:.3f} p_ni={p_ni:.4f} → {marker}")

            paired_results[(cfg_name, target_key)] = {
                "mean_diff": round(mean_diff, 4),
                "std_diff": round(std_diff, 4),
                "t_stat": round(t_stat, 3),
                "p_superiority": round(p_sup, 4),
                "p_non_inferiority": round(p_ni, 4),
                "non_inferior": non_inf,
                "correction_factor": round(correction, 3),
            }

    print(f"\n{'=' * 90}")
    print(f"Total runtime: {(time.time() - t_global)/60:.1f}m")

    # Save
    save_data = {
        "n_repeats": N_REPEATS,
        "delta": delta,
        "configs": {f"{c}_{t}": all_results[(c, t)]
                    for c in KEY_CONFIGS for t in TARGETS},
        "paired": {f"{c}_{t}": paired_results[(c, t)]
                   for (c, t) in paired_results},
    }
    out_path = str(results_artifact_path("sensor_span_repeated_cv.json"))
    with open(out_path, "w") as f:
        json.dump(save_data, f, indent=2)
    print(f"Saved: {out_path}")


def _run_repeated_5split(pd_merged, all_merged, feature_cols, target_key, base_seed):
    """Single 5-fold SSL run with a given base seed for fold generation."""
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]

    ranker_sids = all_merged["sid"].values
    ranker_targets = all_merged[target_col].values.astype(np.float32)
    ranker_is_pd = all_merged["is_pd"].values
    X_ranker = all_merged[feature_cols].values.astype(np.float32)

    rank_labels = np.zeros(len(ranker_sids), dtype=np.int32)
    pd_indices = np.where(ranker_is_pd == 1)[0]
    pd_order = np.argsort(ranker_targets[pd_indices])
    for rank, idx in enumerate(pd_order):
        rank_labels[pd_indices[idx]] = rank + 1

    sid_to_ranker_idx = {s: i for i, s in enumerate(ranker_sids)}

    all_true, all_pred, all_sids_out = [], [], []

    for split_i in range(1, 6):
        dev_s, test_s = _gen_split(pd_merged, base_seed + split_i, target_key)
        dm = pd_merged["sid"].isin(dev_s)
        tm = pd_merged["sid"].isin(test_s)
        Xd = pd_merged.loc[dm, feature_cols].values.astype(np.float32)
        yd = pd_merged.loc[dm, target_col].values.astype(np.float32)
        Xt = pd_merged.loc[tm, feature_cols].values.astype(np.float32)
        yt = pd_merged.loc[tm, target_col].values.astype(np.float32)
        sids_train = pd_merged.loc[dm, "sid"].values.tolist()
        sids_test = pd_merged.loc[tm, "sid"].values.tolist()

        k = min(500, Xd.shape[1])
        sel_idx, _ = feature_select(Xd, yd, list(feature_cols), k=k)
        Xd_sel = Xd[:, sel_idx]
        Xt_sel = Xt[:, sel_idx]

        X_ranker_sel = X_ranker[:, sel_idx]
        group_sizes = np.array([len(X_ranker_sel)])

        all_leaf_features = []
        for seed in SEEDS[:3]:
            ranker = XGBRanker(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
                objective="rank:pairwise",
            )
            ranker.fit(X_ranker_sel, rank_labels, group=group_sizes)

            train_idx = [sid_to_ranker_idx[s] for s in sids_train if s in sid_to_ranker_idx]
            test_idx = [sid_to_ranker_idx[s] for s in sids_test if s in sid_to_ranker_idx]
            train_leaves = ranker.apply(X_ranker_sel[train_idx])
            test_leaves = ranker.apply(X_ranker_sel[test_idx])
            all_leaf_features.append((train_leaves, test_leaves))

        train_leaf_cat = np.hstack([lf[0] for lf in all_leaf_features]).astype(np.float32)
        test_leaf_cat = np.hstack([lf[1] for lf in all_leaf_features]).astype(np.float32)

        Xd_combined = np.hstack([Xd_sel, train_leaf_cat])
        Xt_combined = np.hstack([Xt_sel, test_leaf_cat])

        preds = []
        for s in SEEDS:
            p = train_lgb(Xd_combined, yd, Xt_combined, s)
            preds.append(np.clip(p, clip_lo, clip_hi))
        ep = np.mean(preds, axis=0)

        all_true.extend(yt.tolist())
        all_pred.extend(ep.tolist())
        all_sids_out.extend(sids_test)

    metrics = full_metrics(np.array(all_true), np.array(all_pred), target_key)
    metrics["per_subject"] = {
        "sids": all_sids_out,
        "y_true": all_true,
        "y_pred": [float(p) for p in all_pred],
    }
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Sensor span ablation with SSL ranking")
    parser.add_argument("--config", type=str, default="all",
                        help="Sensor config name or 'all'")
    parser.add_argument("--target", type=str, default="all",
                        choices=["t1", "t2", "t3", "all"],
                        help="Target (t1/t2/t3/all)")
    parser.add_argument("--eval", type=str, default="loocv",
                        choices=["loocv", "5split"],
                        help="Evaluation mode")
    parser.add_argument("--preextract-fm", action="store_true",
                        help="Pre-extract FM for all configs, then exit")
    parser.add_argument("--analyze", action="store_true",
                        help="Run bootstrap analysis on completed results")
    parser.add_argument("--k-sweep", action="store_true",
                        help="Run K sweep for key configs (confound test)")
    parser.add_argument("--fm-decomp", action="store_true",
                        help="Run FM decomposition (v2-only vs FM-only)")
    parser.add_argument("--repeated-cv", action="store_true",
                        help="Run 10x5-fold repeated CV for 4 key configs")
    args = parser.parse_args()

    if args.analyze:
        run_analysis()
        return

    if args.preextract_fm:
        preextract_all_fm()
        return

    if args.k_sweep:
        run_k_sweep()
        return

    if args.fm_decomp:
        run_fm_decomposition()
        return

    if args.repeated_cv:
        run_repeated_cv()
        return

    # Determine configs and targets
    if args.config == "all":
        config_list = list(SENSOR_CONFIGS.keys())
    else:
        assert args.config in SENSOR_CONFIGS, (
            f"Unknown config: {args.config}. Choose from: {list(SENSOR_CONFIGS.keys())}")
        config_list = [args.config]

    if args.target == "all":
        target_list = ["t1", "t2", "t3"]
    else:
        target_list = [args.target]

    print("=" * 70)
    print(f"SENSOR SPAN STUDY — SSL RANKING")
    print(f"Configs: {len(config_list)}, Targets: {len(target_list)}, "
          f"Eval: {args.eval}")
    print(f"Total experiments: {len(config_list) * len(target_list)}")
    print("=" * 70)

    all_results = []
    t_global = time.time()

    for cfg_name in config_list:
        sensor_list = SENSOR_CONFIGS[cfg_name]
        print(f"\n{'═' * 70}")
        print(f"Config: {cfg_name} ({len(sensor_list)} sensors)")
        print(f"Sensors: {sensor_list}")
        print(f"{'═' * 70}")

        pd_merged, all_merged, feature_cols, subjects, item_scores = \
            load_features_for_config(cfg_name, sensor_list)

        for target_key in target_list:
            print(f"\n  ── Target: {target_key.upper()} ──")

            if args.eval == "loocv":
                metrics = run_ssl_loocv(pd_merged, all_merged, feature_cols, target_key)
            else:
                metrics = run_ssl_5split(pd_merged, all_merged, feature_cols, target_key)

            metrics["config"] = cfg_name
            metrics["target"] = target_key
            metrics["n_sensors"] = len(sensor_list)
            metrics["sensors"] = sensor_list
            metrics["n_features"] = len(feature_cols)

            # Save individual result
            suffix = f"_{metrics['eval_mode']}"
            out_path = str(results_artifact_path(
                f"sensor_span_{cfg_name}_{target_key}{suffix}.json"))
            with open(out_path, "w") as f:
                json.dump(metrics, f, indent=2)
            print(f"  Saved: {out_path}")

            print(f"  {cfg_name} × {target_key.upper()}: CCC={metrics['ccc']:.3f} "
                  f"MAE={metrics['mae']:.3f} slope={metrics['cal_slope']:.3f} "
                  f"r={metrics['r']:.3f} ({metrics['runtime_s']:.0f}s)")

            all_results.append(metrics)

    # Summary table
    print(f"\n{'=' * 90}")
    print(f"{'Config':<20} {'Target':<6} {'#Sen':>4} {'#Feat':>6} {'CCC':>7} "
          f"{'Slope':>7} {'MAE':>7} {'r':>7} {'Time':>7}")
    print(f"{'─' * 90}")
    for r in all_results:
        print(f"{r['config']:<20} {r['target']:<6} {r['n_sensors']:>4} "
              f"{r['n_features']:>6} {r['ccc']:>7.3f} {r['cal_slope']:>7.3f} "
              f"{r['mae']:>7.3f} {r['r']:>7.3f} {r['runtime_s']:>6.0f}s")
    print(f"{'=' * 90}")
    print(f"Total runtime: {(time.time() - t_global)/60:.1f}m")


if __name__ == "__main__":
    main()

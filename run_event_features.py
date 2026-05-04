"""Phase 3 (compressed): shallow event-aware feature aggregation.

Codex's main insight: "stop treating each subject as one long time series and
start treating them as a bag of clinically meaningful micro-events." A full
DL Event-MIL takes 3-4 days — for the lockbox screening run we instead test
the *aggregation hypothesis* with cheap statistical operators applied to the
already-cached recording-level features. If aggregation matters, this should
move CCC; if it doesn't, full DL Event-MIL likely won't either.

Variants tested:
  - mean: baseline (current pipeline averages across recordings) — control
  - max: per-feature max across recordings (catches extreme moments)
  - topk_mean: per-feature mean of top-K=3 recordings (robust extreme)
  - mean_plus_max: concat mean and max features (2x feature dim)
  - mean_plus_std: mean + cross-recording std (subject-level variability)
  - mean_max_std: full triplet, ~3x feature dim

All aggregations are on the recording-level FM cache; the subject ↔ recording
mapping is fixed (cached in rocket_recordings.npz). No per-fold "fitting"
needed for aggregation itself — it's a deterministic function of train data.
The downstream LightGBM still trains per fold inside the inductive firewall.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, gen_5fold_split
from project_paths import RESULTS_DIR, ensure_dir, results_artifact_path
from run_inductive_ablation import (
    SEEDS,
    TARGET_CLIP,
    _group_from_sid,
    feature_select,
    load_features_and_targets,
    train_lgb,
)
from run_calibration_v2 import parse_per_item_scores, compute_target

ensure_dir(RESULTS_DIR)
N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 11)))

V2_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
_FM_PRIMARY = str(results_artifact_path("sensor_fm_cache/all_13_fm.npz"))
_FM_LEGACY = str(results_artifact_path("fm_embeddings.npz"))
FM_CACHE = _FM_PRIMARY if os.path.exists(_FM_PRIMARY) else _FM_LEGACY
RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))


def aggregate_fm(fm_emb: np.ndarray, sids: list, target_sids: list, mode: str) -> np.ndarray:
    """Aggregate recording-level FM embeddings to subject level.

    fm_emb: (n_recordings, d_model)
    sids:   (n_recordings,) subject IDs aligned with fm_emb rows
    target_sids: subjects to produce features for
    mode:   'mean' / 'max' / 'topk_mean' / 'mean_plus_max' / 'mean_plus_std' / 'mean_max_std'
    """
    sid_to_indices = {}
    for i, sid in enumerate(sids):
        sid_to_indices.setdefault(sid, []).append(i)

    rows = []
    for tsid in target_sids:
        idxs = sid_to_indices.get(tsid, [])
        if not idxs:
            rows.append(np.zeros(_out_dim(fm_emb.shape[1], mode), dtype=np.float32))
            continue
        block = fm_emb[idxs]  # (n_rec_for_subj, d)

        if mode == "mean":
            rows.append(block.mean(axis=0))
        elif mode == "max":
            rows.append(block.max(axis=0))
        elif mode == "topk_mean":
            k = min(3, len(idxs))
            top_idx = np.argsort(np.abs(block).max(axis=1))[-k:]  # rank by magnitude
            rows.append(block[top_idx].mean(axis=0))
        elif mode == "mean_plus_max":
            rows.append(np.concatenate([block.mean(axis=0), block.max(axis=0)]))
        elif mode == "mean_plus_std":
            std = block.std(axis=0) if len(idxs) > 1 else np.zeros(block.shape[1])
            rows.append(np.concatenate([block.mean(axis=0), std]))
        elif mode == "mean_max_std":
            std = block.std(axis=0) if len(idxs) > 1 else np.zeros(block.shape[1])
            rows.append(np.concatenate([block.mean(axis=0), block.max(axis=0), std]))
        else:
            raise ValueError(f"Unknown mode: {mode}")
    return np.array(rows, dtype=np.float32)


def _out_dim(d_model: int, mode: str) -> int:
    return {
        "mean": d_model, "max": d_model, "topk_mean": d_model,
        "mean_plus_max": 2 * d_model, "mean_plus_std": 2 * d_model,
        "mean_max_std": 3 * d_model,
    }[mode]


def load_subject_features(mode: str):
    """Load v2 subject features + recording-level FM aggregated by mode.

    Returns (pd_merged, feature_cols)
    """
    v2_df = pd.read_csv(V2_CACHE)
    fm_emb = np.load(FM_CACHE)["embeddings"]
    rec_sids = np.load(RECORDING_CACHE)["sids"].tolist()

    excluded = {"sid", "updrs3", "obs_subscore", "hy"}
    extra_pref = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")
    v2_cols = [c for c in v2_df.columns
               if c not in excluded and not any(c.startswith(p) for p in extra_pref)]
    v2_sub = v2_df[["sid", "updrs3"] + v2_cols].copy()

    fm_subject = aggregate_fm(fm_emb, rec_sids, v2_sub["sid"].tolist(), mode)
    fm_cols = [f"fm_{mode}_{i}" for i in range(fm_subject.shape[1])]
    fm_df = pd.DataFrame(fm_subject, columns=fm_cols)
    fm_df["sid"] = v2_sub["sid"].values
    merged = v2_sub.merge(fm_df, on="sid", how="left").fillna(0.0)

    # Item-level targets
    item_scores = parse_per_item_scores()
    merged["t1_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t1"))
    merged["t2_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t2"))
    merged["t3_target"] = merged["updrs3"].astype(float)
    merged["group"] = merged["sid"].apply(_group_from_sid)

    valid = (merged["group"] == "PD") & merged["t1_target"].notna() & merged["t2_target"].notna()
    pd_merged = merged[valid].copy().reset_index(drop=True)
    for tk in ("t1", "t2", "t3"):
        pd_merged[f"{tk}_target"] = pd_merged[f"{tk}_target"].astype(np.float32)

    feature_cols = v2_cols + fm_cols
    return pd_merged, feature_cols


def run_5fold(pd_merged, feature_cols, target_key, mode):
    target_col = f"{target_key}_target"
    clip = TARGET_CLIP[target_key]
    X_full = pd_merged[feature_cols].values.astype(np.float32)
    y_full = pd_merged[target_col].values.astype(np.float32)

    all_true, all_pred, all_sids_out = [], [], []
    t0 = time.time()
    for split_i, train_sids, test_sids in gen_5fold_split(pd_merged, target_key):
        dm = pd_merged["sid"].isin(train_sids).values
        tm = pd_merged["sid"].isin(test_sids).values
        Xd, yd = X_full[dm], y_full[dm]
        Xt, yt = X_full[tm], y_full[tm]
        sel_idx, _ = feature_select(Xd, yd, list(range(Xd.shape[1])), k=min(500, Xd.shape[1]))
        preds = []
        for s in SEEDS:
            preds.append(np.clip(train_lgb(Xd[:, sel_idx], yd, Xt[:, sel_idx], s), clip[0], clip[1]))
        ep = np.mean(preds, axis=0)
        all_true.extend(yt.tolist())
        all_pred.extend(ep.tolist())
        all_sids_out.extend(pd_merged.loc[tm, "sid"].tolist())
        print(f"  split {split_i}/5 [{mode} {target_key}]: CCC={full_metrics(yt, ep)['ccc']:.3f}")

    metrics = full_metrics(all_true, all_pred, label=mode)
    metrics.update({
        "target": target_key, "variant": mode, "eval_mode": "5split",
        "feature_dim": len(feature_cols), "runtime_s": round(time.time() - t0, 1),
        "per_subject": {"sids": all_sids_out, "y_true": all_true,
                        "y_pred": [float(p) for p in all_pred]},
    })
    return metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="all",
                    choices=["all", "mean", "max", "topk_mean",
                             "mean_plus_max", "mean_plus_std", "mean_max_std"])
    ap.add_argument("--target", default="all", choices=["t1", "t2", "t3", "all"])
    args = ap.parse_args()

    variants = (["mean", "max", "topk_mean", "mean_plus_max", "mean_plus_std", "mean_max_std"]
                if args.variant == "all" else [args.variant])
    targets = ["t1", "t2", "t3"] if args.target == "all" else [args.target]

    summary = []
    for v in variants:
        print(f"\nLoading subject features with mode={v}...")
        pd_merged, feature_cols = load_subject_features(v)
        for t in targets:
            print(f"\n{'='*70}\nRunning event-features {v} | {t} | 5split\n{'='*70}")
            try:
                m = run_5fold(pd_merged, feature_cols, t, v)
                fname = f"event_features_{v}_{t}_5split.json"
                with open(results_artifact_path(fname), "w") as f:
                    json.dump(m, f, indent=2)
                print(f"  -> CCC={m['ccc']:.3f} slope={m['cal_slope']:.3f} MAE={m['mae']:.3f}")
                summary.append({"variant": v, "target": t,
                                "ccc": m["ccc"], "mae": m["mae"]})
            except Exception as e:
                print(f"  FAILED: {type(e).__name__}: {e}")
                summary.append({"variant": v, "target": t, "error": str(e)})

    print("\n" + "=" * 60)
    for r in summary:
        if "error" in r:
            print(f"  {r['variant']:<16} {r['target']} ERROR")
        else:
            print(f"  {r['variant']:<16} {r['target']} CCC={r['ccc']:.3f}")

    with open(results_artifact_path("event_features_summary.json"), "w") as f:
        json.dump({"summary": summary}, f, indent=2)


if __name__ == "__main__":
    main()

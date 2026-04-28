"""Inductive Stage-1 ablation for the SSL ranking pipeline.

The published pipeline (run_calibration_v2.py:475-545, run_compression_ablation.py:1015-1106)
trains the XGBRanker on ALL N=178 subjects with target-derived rank labels, INCLUDING the
held-out fold's labels. This is the H1 leak identified in the audit. This script re-runs the
same pipeline but rebuilds the rank labels and refits the ranker per fold using ONLY
training-fold subjects (plus, optionally, all HC as anchors).

Three variants are produced:
  V0  Transductive baseline   - reproduces the published numbers (sanity check)
  V1  Inductive PD-only       - ranker sees only training-fold PD subjects
  V2  Inductive PD+HC         - ranker sees training-fold PD + all HC

For each variant, runs T1/T2/T3 under LOOCV and 5-fold CV. Outputs JSON per variant per
target. The CCC delta between V0 and V1/V2 quantifies the leakage that the original paper's
weak defences (HC ablation, LOOCV-vs-5fold) could not detect.

Self-contained: builds PD/HC group labels from the SID prefix (NLS/WPD = PD, HC/WHC = HC)
to bypass the data/ raw-CSV dependency. Equivalent to data_split.parse_clinical()'s
group field when only group membership is needed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

import lightgbm as lgb
from sklearn.linear_model import LinearRegression
from xgboost import XGBRanker, XGBRegressor

from project_paths import RESULTS_DIR, ensure_dir, results_artifact_path

# Reuse compute_target / parse_per_item_scores from the calibration v2 module.
# These do NOT depend on the raw dataset because per_item_scores.json is cached.
from run_calibration_v2 import (
    DEFAULT_LGB_PARAMS,
    SEEDS,
    SUBITEMS_MAP,
    T1_ITEMS,
    T2_ITEMS,
    TARGET_CLIP,
    compute_target,
    parse_per_item_scores,
)


N_CORES = int(os.getenv("PD_IMU_N_CORES", min(os.cpu_count() or 4, 11)))
LOOCV_PROGRESS_EVERY = 20
ensure_dir(RESULTS_DIR)

V2_CACHE = str(results_artifact_path("ablation_v3_features.csv"))
_FM_PRIMARY = str(results_artifact_path("sensor_fm_cache/all_13_fm.npz"))
_FM_LEGACY = str(results_artifact_path("fm_embeddings.npz"))
FM_CACHE = _FM_PRIMARY if os.path.exists(_FM_PRIMARY) else _FM_LEGACY
RECORDING_CACHE = str(results_artifact_path("rocket_recordings.npz"))


# ─── METRICS (duplicated from run_calibration_v2 to keep this file standalone) ─

def _ccc(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    yt, yp = np.asarray(y_true, dtype=np.float64), np.asarray(y_pred, dtype=np.float64)
    if yt.size < 2 or yt.std() < 1e-9 or yp.std() < 1e-9:
        return 0.0
    cov = float(np.mean((yt - yt.mean()) * (yp - yp.mean())))
    return (2 * cov) / (yt.var() + yp.var() + (yt.mean() - yp.mean()) ** 2)


def _slope(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Calibration slope: linear regression of predicted on true.

    MATCHES eval_utils.cal_slope (np.polyfit(y_true, y_pred, 1)[0]). Slope < 1
    indicates regression to the mean; slope > 1 indicates over-stretched
    predictions. The published cache (compression_P5_TT*_5split.json) uses this
    convention; fitting the inverse direction would silently make the inductive
    transductive baseline disagree with the cache.
    """
    yt, yp = np.asarray(y_true, dtype=np.float64), np.asarray(y_pred, dtype=np.float64)
    if yt.size < 3 or yt.std() < 1e-8:
        return 0.0
    return float(np.polyfit(yt, yp, 1)[0])


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(y_true) - np.asarray(y_pred))))


def _r(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if np.std(y_true) < 1e-9 or np.std(y_pred) < 1e-9:
        return 0.0
    return float(np.corrcoef(y_true, y_pred)[0, 1])


def _full_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    return {
        "n": int(len(y_true)),
        "ccc": round(_ccc(y_true, y_pred), 4),
        "cal_slope": round(_slope(y_true, y_pred), 4),
        "mae": round(_mae(y_true, y_pred), 4),
        "r": round(_r(y_true, y_pred), 4),
    }


# ─── DATA LOADING (no data_split dependency) ──────────────────────────────────

def _group_from_sid(sid: str) -> str:
    """SID prefix encodes the cohort. Verified against parse_clinical totals
    in MEMORY.md: NLS+WPD = 98 PD, HC+WHC = 80 HC."""
    if sid.startswith("HC") or sid.startswith("WHC"):
        return "HC"
    if sid.startswith("NLS") or sid.startswith("WPD"):
        return "PD"
    raise ValueError(f"Unknown SID prefix: {sid}")


def load_features_and_targets():
    """Mirror of run_calibration_v2.load_features_and_targets without the
    parse_clinical() dependency. Returns (pd_merged, all_merged, feature_cols)."""
    assert os.path.exists(V2_CACHE), f"V2 cache not found: {V2_CACHE}"
    assert os.path.exists(FM_CACHE), f"FM cache not found: {FM_CACHE}"
    assert os.path.exists(RECORDING_CACHE), f"Recording cache not found: {RECORDING_CACHE}"

    v2_df = pd.read_csv(V2_CACHE)
    fm_embeddings = np.load(FM_CACHE)["embeddings"]
    rec_sids = np.load(RECORDING_CACHE)["sids"].tolist()

    d_model = fm_embeddings.shape[1]
    fm_df = pd.DataFrame(fm_embeddings, columns=[f"fm_{i}" for i in range(d_model)])
    fm_df["sid"] = rec_sids
    fm_agg = fm_df.groupby("sid").mean().reset_index()
    fm_cols = [c for c in fm_agg.columns if c.startswith("fm_")]

    excluded = {"sid", "updrs3", "obs_subscore", "hy"}
    extra_prefixes = ("nl_", "sv_", "pa_", "fq_", "hr_", "ix_", "ext_")
    v2_feat_cols = [
        c for c in v2_df.columns
        if c not in excluded and not any(c.startswith(p) for p in extra_prefixes)
    ]

    merged = (
        v2_df[["sid", "updrs3"] + v2_feat_cols]
        .merge(fm_agg, on="sid", how="left")
        .fillna(0.0)
    )
    feature_cols = v2_feat_cols + fm_cols

    item_scores = parse_per_item_scores()
    merged["t1_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t1"))
    merged["t2_target"] = merged["sid"].apply(lambda s: compute_target(item_scores, s, "t2"))
    merged["t3_target"] = merged["updrs3"].astype(float)
    merged["group"] = merged["sid"].apply(_group_from_sid)
    merged["is_pd"] = (merged["group"] == "PD").astype(int)

    pd_valid = (merged["group"] == "PD") & merged["t1_target"].notna() & merged["t2_target"].notna()
    pd_merged = merged[pd_valid].copy().reset_index(drop=True)
    for tk in ("t1", "t2", "t3"):
        pd_merged[f"{tk}_target"] = pd_merged[f"{tk}_target"].astype(np.float32)

    all_valid = merged["t1_target"].notna() & merged["t2_target"].notna()
    all_merged = merged[all_valid].copy().reset_index(drop=True)
    for tk in ("t1", "t2", "t3"):
        all_merged[f"{tk}_target"] = all_merged[f"{tk}_target"].astype(np.float32)

    n_pd = int((all_merged["is_pd"] == 1).sum())
    n_hc = int((all_merged["is_pd"] == 0).sum())
    print(f"\nData loaded:")
    print(f"  PD subjects: {len(pd_merged)} ({n_pd} total in all_merged)")
    print(f"  HC subjects: {n_hc}")
    print(f"  All subjects: {len(all_merged)}")
    print(f"  Features: {len(feature_cols)} (v2: {len(v2_feat_cols)}, FM: {len(fm_cols)})")

    return pd_merged, all_merged, feature_cols


# ─── FEATURE SELECTION + LGB TRAINER (per-fold, no leakage) ───────────────────

def feature_select(X: np.ndarray, y: np.ndarray, names: list, k: int = 500):
    k = min(k, X.shape[1])
    sel = XGBRegressor(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        reg_lambda=2.0, random_state=42, n_jobs=N_CORES,
        objective="reg:absoluteerror",
    )
    sel.fit(X, y)
    idx = np.argsort(sel.feature_importances_)[::-1][:k]
    return idx, [names[i] for i in idx]


def train_lgb(Xd: np.ndarray, yd: np.ndarray, Xt: np.ndarray, seed: int) -> np.ndarray:
    p = dict(DEFAULT_LGB_PARAMS)
    rng = np.random.RandomState(seed)
    idx = np.arange(len(Xd))
    rng.shuffle(idx)
    nv = max(1, int(len(idx) * p["val_frac"]))
    m = lgb.LGBMRegressor(
        n_estimators=p["n_estimators"], learning_rate=p["learning_rate"],
        max_depth=p["max_depth"], num_leaves=p["num_leaves"],
        reg_lambda=p["reg_lambda"], min_data_in_leaf=p["min_data_in_leaf"],
        colsample_bytree=p["colsample_bytree"], subsample=p["subsample"],
        random_state=seed, n_jobs=N_CORES, objective=p["objective"], verbose=-1,
    )
    m.fit(
        X=Xd[idx[nv:]], y=yd[idx[nv:]],
        eval_set=[(Xd[idx[:nv]], yd[idx[:nv]])],
        callbacks=[lgb.early_stopping(p["early_stopping_rounds"], verbose=False)],
    )
    return m.predict(Xt)


# ─── INDUCTIVE STAGE-1 RANKER (the actual fix) ────────────────────────────────

def fit_inductive_ranker(
    X_rank: np.ndarray,
    rank_labels: np.ndarray,
) -> list:
    """Fit a 3-seed XGBRanker ensemble on the given (ranker subjects only)
    feature matrix and rank labels. Returns the trained models."""
    group_sizes = np.array([len(X_rank)])
    rankers = []
    for seed in SEEDS[:3]:
        r = XGBRanker(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            reg_lambda=2.0, random_state=seed, n_jobs=N_CORES,
            objective="rank:pairwise",
        )
        r.fit(X_rank, rank_labels, group=group_sizes)
        rankers.append(r)
    return rankers


def build_rank_labels_pd_only(
    pd_train_targets: np.ndarray,
) -> np.ndarray:
    """Inductive PD-only: rank labels assigned to training-fold PD subjects only.
    Sorted by target ascending, ranks 1..N_train (no anchor at 0)."""
    labels = np.zeros(len(pd_train_targets), dtype=np.int32)
    order = np.argsort(pd_train_targets)
    for rank, idx in enumerate(order):
        labels[idx] = rank + 1
    return labels


def build_rank_labels_pd_plus_hc(
    pd_train_targets: np.ndarray,
    n_hc: int,
) -> np.ndarray:
    """Inductive PD+HC: training-fold PD subjects ranked 1..N_train, all HC at rank 0."""
    labels = np.zeros(len(pd_train_targets) + n_hc, dtype=np.int32)
    # PD subjects come first (we control the row order), HC after
    order = np.argsort(pd_train_targets)
    for rank, idx in enumerate(order):
        labels[idx] = rank + 1
    # HC stay at 0 (already initialised)
    return labels


# ─── SSL LOOPS: TRANSDUCTIVE (V0) vs INDUCTIVE (V1/V2) ────────────────────────

def _seed_leaves(rankers: list, X: np.ndarray) -> np.ndarray:
    """Concatenate leaf assignments from a 3-seed ranker ensemble."""
    return np.hstack([r.apply(X) for r in rankers]).astype(np.float32)


def _ssl_predict_one_fold(
    Xd: np.ndarray, yd: np.ndarray, Xt: np.ndarray,
    feature_cols: list, sids_train: list, sids_test: list,
    all_merged: pd.DataFrame, target_col: str, variant: str,
    clip_lo: float, clip_hi: float,
) -> np.ndarray:
    """Run feature selection -> Stage-1 ranker -> Stage-2 LGB for one CV fold.

    variant:
      "transductive" : ranker trained on all N=178 with all PD ranks (LEAKY baseline)
      "inductive_pd" : ranker trained on training-fold PD only with their ranks
      "inductive_pd_hc" : ranker trained on training-fold PD + all HC
    """
    # Feature selection inside fold (training data only)
    sel_idx, _ = feature_select(Xd, yd, feature_cols, k=500)
    Xd_sel = Xd[:, sel_idx]
    Xt_sel = Xt[:, sel_idx]

    if variant == "transductive":
        # Leaky baseline: all subjects, all ranks (including held-out PD)
        all_X = all_merged[feature_cols].values.astype(np.float32)[:, sel_idx]
        all_targets = all_merged[target_col].values.astype(np.float32)
        is_pd = all_merged["is_pd"].values
        all_sids = all_merged["sid"].values

        labels = np.zeros(len(all_sids), dtype=np.int32)
        pd_idx = np.where(is_pd == 1)[0]
        order = np.argsort(all_targets[pd_idx])
        for rank, j in enumerate(order):
            labels[pd_idx[j]] = rank + 1

        rankers = fit_inductive_ranker(all_X, labels)
        sid_to_idx = {s: i for i, s in enumerate(all_sids)}
        train_idx = np.array([sid_to_idx[s] for s in sids_train])
        test_idx = np.array([sid_to_idx[s] for s in sids_test])
        train_leaves = _seed_leaves(rankers, all_X[train_idx])
        test_leaves = _seed_leaves(rankers, all_X[test_idx])

    elif variant == "inductive_pd":
        # Ranker sees only training-fold PD subjects with their ranks
        labels = build_rank_labels_pd_only(yd)
        rankers = fit_inductive_ranker(Xd_sel, labels)
        train_leaves = _seed_leaves(rankers, Xd_sel)
        test_leaves = _seed_leaves(rankers, Xt_sel)

    elif variant == "inductive_pd_hc":
        # Ranker sees training-fold PD + all HC subjects
        is_pd = all_merged["is_pd"].values
        hc_mask = is_pd == 0
        all_X = all_merged[feature_cols].values.astype(np.float32)[:, sel_idx]
        X_hc = all_X[hc_mask]

        # PD train rows first, then HC
        X_rank = np.vstack([Xd_sel, X_hc])
        labels = build_rank_labels_pd_plus_hc(yd, len(X_hc))
        rankers = fit_inductive_ranker(X_rank, labels)
        train_leaves = _seed_leaves(rankers, Xd_sel)
        test_leaves = _seed_leaves(rankers, Xt_sel)

    else:
        raise ValueError(f"Unknown variant: {variant}")

    Xd_combined = np.hstack([Xd_sel, train_leaves])
    Xt_combined = np.hstack([Xt_sel, test_leaves])

    preds = []
    for s in SEEDS:
        p = train_lgb(Xd_combined, yd, Xt_combined, s)
        preds.append(np.clip(p, clip_lo, clip_hi))
    return np.mean(preds, axis=0)


def run_loocv(
    pd_merged: pd.DataFrame, all_merged: pd.DataFrame,
    feature_cols: list, target_key: str, variant: str,
) -> dict:
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]
    sids = pd_merged["sid"].values
    n = len(sids)
    y_true = pd_merged[target_col].values.astype(np.float32)
    X = pd_merged[feature_cols].values.astype(np.float32)
    y_pred = np.zeros(n, dtype=np.float64)

    t0 = time.time()
    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        Xd, yd = X[mask], y_true[mask]
        Xt = X[i:i + 1]
        sids_train = sids[mask].tolist()
        sids_test = [sids[i]]

        ep = _ssl_predict_one_fold(
            Xd, yd, Xt, feature_cols, sids_train, sids_test,
            all_merged, target_col, variant, clip_lo, clip_hi,
        )
        y_pred[i] = float(ep[0])

        if (i + 1) % LOOCV_PROGRESS_EVERY == 0:
            elapsed = time.time() - t0
            running_ccc = _ccc(y_true[:i + 1], y_pred[:i + 1])
            print(f"    [{variant} {target_key} {i + 1}/{n}] CCC={running_ccc:.3f} "
                  f"({elapsed:.0f}s elapsed)")

    metrics = _full_metrics(y_true, y_pred)
    metrics.update({
        "eval_mode": "loocv",
        "target": target_key,
        "variant": variant,
        "runtime_s": round(time.time() - t0, 1),
        "per_subject": {
            "sids": sids.tolist(),
            "y_true": y_true.tolist(),
            "y_pred": y_pred.tolist(),
        },
    })
    return metrics


def gen_5fold_split(pd_merged: pd.DataFrame, target_key: str, n_splits: int = 5):
    """Stratified 5-fold by target quartile, mirroring run_compression_ablation.gen_split.

    Yields (split_i, train_sids, test_sids) for split_i in 1..n_splits.
    The published code seeds each split independently using gen_split(seed=split_i)
    via an 80/20 stratified shuffle. We replicate that here so 5-fold numbers stay
    comparable to the published cache.
    """
    from sklearn.model_selection import train_test_split

    target_col = f"{target_key}_target"
    y = pd_merged[target_col].values
    sids = pd_merged["sid"].values
    # Stratify by quartile (4 bins, robust at N=95)
    bins = np.digitize(y, np.percentile(y, [25, 50, 75]))

    for split_i in range(1, n_splits + 1):
        train_sids, test_sids = train_test_split(
            sids, test_size=0.2, random_state=split_i, stratify=bins,
        )
        yield split_i, train_sids.tolist(), test_sids.tolist()


def run_5fold(
    pd_merged: pd.DataFrame, all_merged: pd.DataFrame,
    feature_cols: list, target_key: str, variant: str,
) -> dict:
    target_col = f"{target_key}_target"
    clip_lo, clip_hi = TARGET_CLIP[target_key]
    all_true: list = []
    all_pred: list = []
    all_sids_out: list = []

    t0 = time.time()
    for split_i, train_sids, test_sids in gen_5fold_split(pd_merged, target_key):
        dm = pd_merged["sid"].isin(train_sids)
        tm = pd_merged["sid"].isin(test_sids)
        Xd = pd_merged.loc[dm, feature_cols].values.astype(np.float32)
        yd = pd_merged.loc[dm, target_col].values.astype(np.float32)
        Xt = pd_merged.loc[tm, feature_cols].values.astype(np.float32)
        yt = pd_merged.loc[tm, target_col].values.astype(np.float32)
        sids_train = pd_merged.loc[dm, "sid"].values.tolist()
        sids_test = pd_merged.loc[tm, "sid"].values.tolist()

        ep = _ssl_predict_one_fold(
            Xd, yd, Xt, feature_cols, sids_train, sids_test,
            all_merged, target_col, variant, clip_lo, clip_hi,
        )

        ccc = _ccc(yt, ep)
        slope = _slope(yt, ep)
        mae = _mae(yt, ep)
        print(f"  Split {split_i}/5 [{variant} {target_key}]: "
              f"CCC={ccc:.3f} slope={slope:.3f} MAE={mae:.3f}")

        all_true.extend(yt.tolist())
        all_pred.extend(ep.tolist())
        all_sids_out.extend(sids_test)

    yt_arr = np.array(all_true, dtype=np.float32)
    yp_arr = np.array(all_pred, dtype=np.float32)
    metrics = _full_metrics(yt_arr, yp_arr)
    metrics.update({
        "eval_mode": "5split",
        "target": target_key,
        "variant": variant,
        "runtime_s": round(time.time() - t0, 1),
        "per_subject": {
            "sids": all_sids_out,
            "y_true": all_true,
            "y_pred": [float(p) for p in all_pred],
        },
    })
    return metrics


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

def save_result(name: str, data: dict) -> None:
    path = results_artifact_path(name)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved -> {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant", required=True,
        choices=["transductive", "inductive_pd", "inductive_pd_hc", "all"],
    )
    parser.add_argument(
        "--target", default="t1", choices=["t1", "t2", "t3", "all"],
    )
    parser.add_argument(
        "--eval", default="loocv", choices=["loocv", "5split", "both"],
    )
    args = parser.parse_args()

    variants = (
        ["transductive", "inductive_pd", "inductive_pd_hc"]
        if args.variant == "all" else [args.variant]
    )
    targets = ["t1", "t2", "t3"] if args.target == "all" else [args.target]
    evals = ["loocv", "5split"] if args.eval == "both" else [args.eval]

    print(f"Variants: {variants}")
    print(f"Targets:  {targets}")
    print(f"Evals:    {evals}")

    pd_merged, all_merged, feature_cols = load_features_and_targets()

    summary = []
    for variant in variants:
        for target in targets:
            for ev in evals:
                print(f"\n{'=' * 70}")
                print(f"Running {variant} | {target} | {ev}")
                print('=' * 70)
                if ev == "loocv":
                    metrics = run_loocv(pd_merged, all_merged, feature_cols, target, variant)
                else:
                    metrics = run_5fold(pd_merged, all_merged, feature_cols, target, variant)

                fname = f"inductive_{variant}_{target}_{ev}.json"
                save_result(fname, metrics)
                summary.append({
                    "variant": variant, "target": target, "eval": ev,
                    "ccc": metrics["ccc"], "cal_slope": metrics["cal_slope"],
                    "mae": metrics["mae"], "n": metrics["n"],
                    "runtime_s": metrics["runtime_s"],
                })

    print("\n" + "=" * 90)
    print(f"{'Variant':<22} {'Target':<6} {'Eval':<8} {'N':>4} "
          f"{'CCC':>7} {'Slope':>7} {'MAE':>7} {'Time':>8}")
    print("-" * 90)
    for r in summary:
        print(f"{r['variant']:<22} {r['target']:<6} {r['eval']:<8} {r['n']:>4} "
              f"{r['ccc']:>7.3f} {r['cal_slope']:>7.3f} {r['mae']:>7.3f} {r['runtime_s']:>7.1f}s")
    print("=" * 90)

    save_result("inductive_summary.json", {"summary": summary})


if __name__ == "__main__":
    main()

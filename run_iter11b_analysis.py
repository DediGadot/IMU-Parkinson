"""Iter11B analysis: bootstrap CI + T3 composite candidate.

Track 3: Bootstrap CI on canonical hybrid_v5 T1 sum (subjects resampled with replacement,
         stratified by H&Y bin). 1000 reps. Compare 95% lower bound against prior canonical.

Track 4: T3 composite from new per-item heads vs canonical T3 hy_residual.
         Per-item heads:
           - items 1, 2, 3: severity-proxy Ridge on H&Y features (LOOCV)
           - items 4-8: iter8 best (lockbox_peritem_*_20260430_143044)
           - items 9, 11, 13, 14, 15, 16: iter8 best
           - item 10: iter11 self_norm_hy_residual (canonical T1 winner)
           - item 12: cccv2
           - items 17, 18: hy_residual_cccv2
           - item 13 also: inter v2_plus_self_norm (the v4 canonical swap)

Outputs:
  results/iter11b_bootstrap_ci.json       — T1 v5 bootstrap CI
  results/iter11b_t3_composite.json       — T3 composite candidate

Run:
  uv run python run_iter11b_analysis.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR
from run_per_item_v2 import load_data as load_peritem_data, T1_ITEMS
from run_t1_iter4 import get_hy_features

ITER6_TS = "20260430_182930"
ITER8_TS = "20260430_143044"


def _align_oof(oof: np.ndarray, n: int, valid_mask: np.ndarray) -> np.ndarray:
    if len(oof) == n:
        return oof
    full = np.full(n, np.nan)
    full[valid_mask] = oof
    full = np.where(np.isnan(full), np.nanmean(full), full)
    return full


def severity_proxy_ridge_loocv(d: dict, item: int) -> np.ndarray:
    """Item-level Ridge on H&Y features, LOOCV."""
    y = np.asarray(d["items"][item], dtype=float)
    hy = get_hy_features(d["hy"])
    n = len(y)
    valid = ~np.isnan(y)
    oof = np.full(n, np.nan)
    valid_idx = np.where(valid)[0]
    for i in valid_idx:
        tr = np.array([j for j in valid_idx if j != i])
        ridge = Ridge(alpha=1.0, random_state=42)
        ridge.fit(hy[tr], y[tr])
        oof[i] = ridge.predict(hy[i:i+1])[0]
    # Fill non-valid with mean
    oof[~valid] = np.nanmean(oof)
    return oof


def load_canonical_t1_v3_oofs(d: dict) -> dict[int, np.ndarray]:
    """Load canonical T1 hybrid v3 baseline per-item OOFs.
    Selections: iter6{10,14}, iter8{9,11,13}, cccv2{12}.
    """
    n = len(d["sids"])
    sids_cur = list(d["sids"])
    out: dict[int, np.ndarray] = {}

    # iter8 for items 9, 11, 13 — find the 13 OOF
    for it, fname in [
        (9, f"lockbox_peritem_9_hy_residual_item_{ITER8_TS}.oof.npy"),
        (11, f"lockbox_peritem_11_item_dedicated_{ITER8_TS}.oof.npy"),
        (13, f"lockbox_peritem_13_item_plus_v2_{ITER8_TS}.oof.npy"),
    ]:
        arr = np.load(RESULTS_DIR / fname)
        valid = ~np.isnan(np.asarray(d["items"][it], dtype=float))
        out[it] = _align_oof(arr, n, valid)

    # cccv2 for item 12
    arr = np.load(RESULTS_DIR / "lockbox_peritem_12_item_plus_v2_cccv2.oof.npy")
    valid = ~np.isnan(np.asarray(d["items"][12], dtype=float))
    out[12] = _align_oof(arr, n, valid)

    # iter6 for items 10, 14
    sids_iter6 = np.load(RESULTS_DIR / f"iter6_sids_{ITER6_TS}.npy", allow_pickle=True)
    sids_iter6 = np.array([str(s) for s in sids_iter6])
    align_idx = np.array([np.where(sids_iter6 == s)[0][0] if s in list(sids_iter6) else -1
                          for s in sids_cur])
    valid_iter6_mask = align_idx >= 0
    for it in [10, 14]:
        arr = np.load(RESULTS_DIR / f"iter6_item{it}_oof_{ITER6_TS}.npy")
        full = np.full(n, np.nan)
        full[valid_iter6_mask] = arr[align_idx[valid_iter6_mask]]
        out[it] = full

    return out


def load_canonical_t1_v5_oofs(d: dict) -> dict[int, np.ndarray]:
    """Load canonical T1 hybrid v5 per-item OOFs.

    Per peritem_composite_hybrid_v5_iter11.json swaps:
      9: iter8       (lockbox_peritem_9_hy_residual_item_20260430_143044)
      10: iter11     (lockbox_self_norm_cross_10_self_norm_hy_residual_20260501_064907)
      11: iter8      (lockbox_peritem_11_item_dedicated_20260430_143044)
      12: cccv2      (lockbox_peritem_12_item_plus_v2_cccv2)
      13: inter      (interaction_13_v2_plus_self_norm_loocv_loocv_winners)
      14: iter6      (iter6_item14_oof_20260430_182930)
    """
    n = len(d["sids"])
    sids_cur = list(d["sids"])
    out: dict[int, np.ndarray] = {}

    # Item 9 — iter8
    arr = np.load(RESULTS_DIR / f"lockbox_peritem_9_hy_residual_item_{ITER8_TS}.oof.npy")
    valid = ~np.isnan(np.asarray(d["items"][9], dtype=float))
    out[9] = _align_oof(arr, n, valid)

    # Item 10 — iter11 self_norm_hy_residual
    arr = np.load(RESULTS_DIR / "lockbox_self_norm_cross_10_self_norm_hy_residual_20260501_064907.oof.npy")
    valid = ~np.isnan(np.asarray(d["items"][10], dtype=float))
    out[10] = _align_oof(arr, n, valid)

    # Item 11 — iter8
    arr = np.load(RESULTS_DIR / f"lockbox_peritem_11_item_dedicated_{ITER8_TS}.oof.npy")
    valid = ~np.isnan(np.asarray(d["items"][11], dtype=float))
    out[11] = _align_oof(arr, n, valid)

    # Item 12 — cccv2
    arr = np.load(RESULTS_DIR / "lockbox_peritem_12_item_plus_v2_cccv2.oof.npy")
    valid = ~np.isnan(np.asarray(d["items"][12], dtype=float))
    out[12] = _align_oof(arr, n, valid)

    # Item 13 — inter v2_plus_self_norm
    arr = np.load(RESULTS_DIR / "interaction_13_v2_plus_self_norm_loocv_loocv_winners.oof.npy")
    valid = ~np.isnan(np.asarray(d["items"][13], dtype=float))
    out[13] = _align_oof(arr, n, valid)

    # Item 14 — iter6
    sids_iter6 = np.load(RESULTS_DIR / f"iter6_sids_{ITER6_TS}.npy", allow_pickle=True)
    sids_iter6 = np.array([str(s) for s in sids_iter6])
    align_idx = np.array([np.where(sids_iter6 == s)[0][0] if s in list(sids_iter6) else -1
                          for s in sids_cur])
    valid_iter6_mask = align_idx >= 0
    arr = np.load(RESULTS_DIR / f"iter6_item14_oof_{ITER6_TS}.npy")
    full = np.full(n, np.nan)
    full[valid_iter6_mask] = arr[align_idx[valid_iter6_mask]]
    out[14] = full

    return out


def stratified_bootstrap_ci(t1_oofs: dict[int, np.ndarray], y_t1: np.ndarray,
                            hy: np.ndarray, n_reps: int = 1000,
                            seed: int = 42,
                            t1_oofs_baseline: dict[int, np.ndarray] | None = None,
                            ) -> dict:
    """Bootstrap CI on T1 sum CCC, stratified by H&Y bin.

    Subjects are resampled (with replacement) within each H&Y bin to preserve severity distribution.
    Each bootstrap rep computes CCC of (sum of per-item OOFs) vs y_t1 on the resampled subjects.

    If t1_oofs_baseline is provided, also computes paired CCC differences (v5 - baseline)
    on the SAME bootstrap resamples, giving a paired Δ-CCC test (stronger than marginal CI).
    """
    rng = np.random.RandomState(seed)
    # H&Y bins (stratify by integer H&Y stage)
    hy_arr = np.asarray(hy, dtype=float)
    hy_bins = np.where(np.isnan(hy_arr), 0.0, hy_arr).astype(int)
    bin_idx: dict[int, np.ndarray] = {}
    for b in np.unique(hy_bins):
        bin_idx[int(b)] = np.where(hy_bins == b)[0]

    n = len(y_t1)
    t1_pred_full = sum(t1_oofs[it] for it in T1_ITEMS)
    t1_pred_baseline = sum(t1_oofs_baseline[it] for it in T1_ITEMS) if t1_oofs_baseline else None

    point_ccc = ccc_fn(y_t1, t1_pred_full)
    point_metrics = full_metrics(y_t1, t1_pred_full)
    point_baseline_ccc = ccc_fn(y_t1, t1_pred_baseline) if t1_pred_baseline is not None else float("nan")
    point_delta = point_ccc - point_baseline_ccc if t1_pred_baseline is not None else float("nan")

    bs_ccc = np.empty(n_reps, dtype=float)
    bs_baseline_ccc = np.empty(n_reps, dtype=float) if t1_pred_baseline is not None else None
    bs_delta = np.empty(n_reps, dtype=float) if t1_pred_baseline is not None else None

    for r in range(n_reps):
        idx = []
        for b, members in bin_idx.items():
            idx.append(rng.choice(members, size=len(members), replace=True))
        idx = np.concatenate(idx)
        y_b = y_t1[idx]
        p_b = t1_pred_full[idx]
        bs_ccc[r] = ccc_fn(y_b, p_b)
        if t1_pred_baseline is not None:
            p_base_b = t1_pred_baseline[idx]
            bs_baseline_ccc[r] = ccc_fn(y_b, p_base_b)
            bs_delta[r] = bs_ccc[r] - bs_baseline_ccc[r]

    out = {
        "n_reps": n_reps,
        "point_ccc": float(point_ccc),
        "point_metrics": point_metrics,
        "bs_ccc_mean": float(np.mean(bs_ccc)),
        "bs_ccc_std": float(np.std(bs_ccc)),
        "ci95_lower": float(np.percentile(bs_ccc, 2.5)),
        "ci95_upper": float(np.percentile(bs_ccc, 97.5)),
        "ci99_lower": float(np.percentile(bs_ccc, 0.5)),
        "ci99_upper": float(np.percentile(bs_ccc, 99.5)),
        "stratify_by": "hy_bin",
        "n_bins": len(bin_idx),
        "n_subjects": int(n),
    }
    if bs_delta is not None:
        out["paired_delta"] = {
            "point_baseline_ccc": float(point_baseline_ccc),
            "point_delta": float(point_delta),
            "bs_delta_mean": float(np.mean(bs_delta)),
            "bs_delta_std": float(np.std(bs_delta)),
            "ci95_delta_lower": float(np.percentile(bs_delta, 2.5)),
            "ci95_delta_upper": float(np.percentile(bs_delta, 97.5)),
            "p_one_sided_v5_gt_baseline": float(np.mean(bs_delta <= 0)),
            "n_reps_pos_delta": int(np.sum(bs_delta > 0)),
        }
    return out


def build_t3_composite(d: dict) -> dict:
    """Build T3 composite from per-item LOOCV heads + severity-proxy ridge.

    Per-item assignment:
      items 1, 2, 3: severity-proxy ridge on H&Y (no IMU heads available)
      items 4-8: iter8 (lockbox_peritem_*_20260430_143044)
      item 9: iter8 (hy_residual_item)
      item 10: iter11 self_norm_hy_residual
      item 11: iter8 (item_dedicated)
      item 12: cccv2 (item_plus_v2_cccv2)
      item 13: inter v2_plus_self_norm
      item 14: iter6
      item 15: iter8 (item_dedicated)
      item 16: iter8 (lr_multitask)
      item 17: iter8 (v2_baseline) — no cccv2 head exists
      item 18: cccv2 (hy_residual_cccv2)

    Sum all per-item preds → T3 candidate. Compare to canonical hy_residual T3 (CCC=0.4092).
    """
    n = len(d["sids"])
    # T3 = sum of items 1..18 (set to NaN if any item missing)
    items_mat = np.column_stack([np.asarray(d["items"][i], dtype=float) for i in range(1, 19)])
    t3 = np.where(np.isnan(items_mat).any(axis=1), np.nan, items_mat.sum(axis=1))
    # Compute per-item heads
    head_oofs: dict[int, np.ndarray] = {}
    head_names: dict[int, str] = {}

    # severity-proxy ridge for items 1, 2, 3
    for it in [1, 2, 3]:
        if it not in d["items"]:
            continue
        head_oofs[it] = severity_proxy_ridge_loocv(d, it)
        head_names[it] = "severity_proxy_ridge_hy"

    # iter8 best for items 4-8, 9, 11, 13, 14, 15, 16
    iter8_assignments = {
        4: ("v2_baseline", f"lockbox_peritem_4_v2_baseline_{ITER8_TS}.oof.npy"),
        5: ("v2_baseline", f"lockbox_peritem_5_v2_baseline_{ITER8_TS}.oof.npy"),
        6: ("lr_multitask", f"lockbox_peritem_6_lr_multitask_{ITER8_TS}.oof.npy"),
        7: ("item_plus_v2", f"lockbox_peritem_7_item_plus_v2_{ITER8_TS}.oof.npy"),
        8: ("item_plus_v2", f"lockbox_peritem_8_item_plus_v2_{ITER8_TS}.oof.npy"),
        9: ("hy_residual_item", f"lockbox_peritem_9_hy_residual_item_{ITER8_TS}.oof.npy"),
        11: ("item_dedicated", f"lockbox_peritem_11_item_dedicated_{ITER8_TS}.oof.npy"),
        14: ("item_plus_v2", f"lockbox_peritem_14_item_plus_v2_{ITER8_TS}.oof.npy"),
        15: ("item_dedicated", f"lockbox_peritem_15_item_dedicated_{ITER8_TS}.oof.npy"),
        16: ("lr_multitask", f"lockbox_peritem_16_lr_multitask_{ITER8_TS}.oof.npy"),
        17: ("v2_baseline", f"lockbox_peritem_17_v2_baseline_{ITER8_TS}.oof.npy"),
    }
    for it, (name, fname) in iter8_assignments.items():
        path = RESULTS_DIR / fname
        if not path.exists():
            print(f"WARN: missing OOF for item {it} ({fname})")
            continue
        arr = np.load(path)
        y = np.asarray(d["items"][it], dtype=float)
        valid = ~np.isnan(y)
        head_oofs[it] = _align_oof(arr, n, valid)
        head_names[it] = name

    # item 10: iter11 self_norm_hy_residual
    arr = np.load(RESULTS_DIR / "lockbox_self_norm_cross_10_self_norm_hy_residual_20260501_064907.oof.npy")
    y = np.asarray(d["items"][10], dtype=float)
    valid = ~np.isnan(y)
    head_oofs[10] = _align_oof(arr, n, valid)
    head_names[10] = "iter11_self_norm_hy_residual"

    # item 12: cccv2
    arr = np.load(RESULTS_DIR / "lockbox_peritem_12_item_plus_v2_cccv2.oof.npy")
    y = np.asarray(d["items"][12], dtype=float)
    valid = ~np.isnan(y)
    head_oofs[12] = _align_oof(arr, n, valid)
    head_names[12] = "cccv2_item_plus_v2"

    # item 13: inter v2_plus_self_norm
    arr = np.load(RESULTS_DIR / "interaction_13_v2_plus_self_norm_loocv_loocv_winners.oof.npy")
    y = np.asarray(d["items"][13], dtype=float)
    valid = ~np.isnan(y)
    head_oofs[13] = _align_oof(arr, n, valid)
    head_names[13] = "inter_v2_plus_self_norm"

    # item 14: iter6
    sids_iter6 = np.load(RESULTS_DIR / f"iter6_sids_{ITER6_TS}.npy", allow_pickle=True)
    sids_iter6 = np.array([str(s) for s in sids_iter6])
    sids_cur = list(d["sids"])
    align_idx = np.array([np.where(sids_iter6 == s)[0][0] if s in list(sids_iter6) else -1
                          for s in sids_cur])
    valid_iter6_mask = align_idx >= 0
    arr = np.load(RESULTS_DIR / f"iter6_item14_oof_{ITER6_TS}.npy")
    full = np.full(n, np.nan)
    full[valid_iter6_mask] = arr[align_idx[valid_iter6_mask]]
    head_oofs[14] = full
    head_names[14] = "iter6_item14"

    # item 18: hy_residual_cccv2
    arr = np.load(RESULTS_DIR / "lockbox_peritem_18_hy_residual_cccv2.oof.npy")
    y = np.asarray(d["items"][18], dtype=float)
    valid = ~np.isnan(y)
    head_oofs[18] = _align_oof(arr, n, valid)
    head_names[18] = "hy_residual_cccv2"

    # Per-item LOOCV CCCs (only on valid subjects for that item)
    per_item_ccc: dict[int, float] = {}
    for it in range(1, 19):
        if it not in head_oofs:
            continue
        y = np.asarray(d["items"][it], dtype=float)
        valid = ~np.isnan(y)
        # Also drop OOF NaN
        oof_v = head_oofs[it]
        valid = valid & np.isfinite(oof_v)
        if valid.sum() < 5:
            per_item_ccc[it] = float("nan")
            continue
        c = ccc_fn(y[valid], oof_v[valid])
        per_item_ccc[it] = float(c)

    # T3 composite sum
    items_present = sorted(head_oofs.keys())
    print(f"Items in T3 composite: {items_present}")
    t3_pred = sum(head_oofs[it] for it in items_present)
    # Filter to subjects with valid T3
    valid_t3 = ~np.isnan(t3)
    t3_metrics = full_metrics(t3[valid_t3], t3_pred[valid_t3])
    t3_metrics["n_valid"] = int(valid_t3.sum())
    t3_metrics["n_total"] = int(len(t3))

    return {
        "items_used": items_present,
        "head_names": head_names,
        "per_item_loocv_ccc": per_item_ccc,
        "t3_composite_metrics": t3_metrics,
        "canonical_t3_hy_residual": {"ccc": 0.4092, "mae": 8.07, "ref": "preregistration_t3_20260429_052015.json"},
    }


def evaluate_iter11b_swaps(d: dict, t1_v5_oofs: dict[int, np.ndarray]) -> dict:
    """Track 1 lockbox: compare iter11b LOOCV OOFs (item 11) against current v5.

    For each iter11b LOOCV OOF, compute per-item LOOCV CCC and the resulting T1
    composite CCC if we swap that item's head in v5.
    """
    n = len(d["sids"])
    out = {}
    # Item 11 LOOCV from iter11b
    p_item11 = RESULTS_DIR / "iter11b_11_self_norm_hy_residual_item_loocv_iter11b_lockbox_item11.oof.npy"
    if p_item11.exists():
        arr = np.load(p_item11)
        y = np.asarray(d["items"][11], dtype=float)
        valid = ~np.isnan(y)
        oof_aligned = _align_oof(arr, n, valid)
        c_new = ccc_fn(y, oof_aligned)
        c_old = ccc_fn(y, t1_v5_oofs[11])
        # Swap into v5
        v5_swapped = dict(t1_v5_oofs)
        v5_swapped[11] = oof_aligned
        t1_swapped = sum(v5_swapped[it] for it in T1_ITEMS)
        t1_v5 = sum(t1_v5_oofs[it] for it in T1_ITEMS)
        m_swap = full_metrics(d["t1"], t1_swapped)
        m_v5 = full_metrics(d["t1"], t1_v5)
        out["item11_self_norm_hy_residual_item"] = {
            "per_item_loocv_ccc_new": float(c_new),
            "per_item_loocv_ccc_v5": float(c_old),
            "delta_per_item": float(c_new - c_old),
            "t1_composite_ccc_with_swap": float(m_swap["ccc"]),
            "t1_composite_ccc_v5_baseline": float(m_v5["ccc"]),
            "delta_t1_composite": float(m_swap["ccc"] - m_v5["ccc"]),
            "swap_recommended": bool(c_new > c_old + 0.015),
        }
    return out


def main() -> None:
    print("Loading data...", flush=True)
    d = load_peritem_data()
    n = len(d["sids"])

    # ── Track 3: Bootstrap CI on T1 v5 (with paired Δ vs v3) ──
    print("\n=== Track 3: Bootstrap CI on hybrid_v5 T1 ===", flush=True)
    t1_oofs = load_canonical_t1_v5_oofs(d)
    t1_oofs_v3 = load_canonical_t1_v3_oofs(d)
    print(f"Loaded T1 v5 OOFs for items: {sorted(t1_oofs.keys())}")
    print(f"Loaded T1 v3 OOFs for items: {sorted(t1_oofs_v3.keys())}")

    bs = stratified_bootstrap_ci(t1_oofs, d["t1"], d["hy"], n_reps=1000, seed=42,
                                 t1_oofs_baseline=t1_oofs_v3)
    print(f"\n  v5 point CCC = {bs['point_ccc']:.4f}")
    print(f"  Bootstrap (n_reps={bs['n_reps']}, stratified by H&Y): "
          f"mean={bs['bs_ccc_mean']:.4f} ± {bs['bs_ccc_std']:.4f}")
    print(f"  v5 95% CI: [{bs['ci95_lower']:.4f}, {bs['ci95_upper']:.4f}]")
    print(f"  v5 99% CI: [{bs['ci99_lower']:.4f}, {bs['ci99_upper']:.4f}]")
    print(f"  Prior canonical (v3 baseline): 0.6908")
    print(f"  → 95% v5 lower bound > 0.6908? {'YES' if bs['ci95_lower'] > 0.6908 else 'NO'}")
    if "paired_delta" in bs:
        pd_ = bs["paired_delta"]
        print(f"\n  Paired Δ (v5 - v3, same bootstrap resamples):")
        print(f"    Point Δ = {pd_['point_delta']:+.4f}  (v3 = {pd_['point_baseline_ccc']:.4f}, v5 = {bs['point_ccc']:.4f})")
        print(f"    Bootstrap Δ mean = {pd_['bs_delta_mean']:+.4f} ± {pd_['bs_delta_std']:.4f}")
        print(f"    95% Δ CI: [{pd_['ci95_delta_lower']:+.4f}, {pd_['ci95_delta_upper']:+.4f}]")
        print(f"    P(Δ > 0): {1.0 - pd_['p_one_sided_v5_gt_baseline']:.4f} "
              f"(reps with Δ>0: {pd_['n_reps_pos_delta']}/{bs['n_reps']})")
        print(f"    → v5 better than v3 with 95% confidence (paired)? "
              f"{'YES' if pd_['ci95_delta_lower'] > 0 else 'NO'}")

    # ── Track 4: T3 composite ──
    print("\n=== Track 4: T3 composite candidate ===", flush=True)
    t3_res = build_t3_composite(d)
    m = t3_res["t3_composite_metrics"]
    canon = t3_res["canonical_t3_hy_residual"]
    print(f"\n  T3 composite CCC={m['ccc']:.4f}, MAE={m['mae']:.3f}, slope={m['cal_slope']:.3f}")
    print(f"  Canonical T3 hy_residual:    CCC={canon['ccc']:.4f}, MAE={canon['mae']:.2f}")
    print(f"  Δ: {m['ccc'] - canon['ccc']:+.4f}")
    print(f"\n  Per-item LOOCV CCCs:")
    for it in sorted(t3_res["per_item_loocv_ccc"]):
        nm = t3_res["head_names"][it]
        c = t3_res["per_item_loocv_ccc"][it]
        print(f"    item {it:>2} ({nm:>32s}): CCC={c:.4f}")

    # ── Track 1 swap eval ──
    print("\n=== Track 1: iter11b LOOCV swap evaluation ===", flush=True)
    swaps = evaluate_iter11b_swaps(d, t1_oofs)
    for variant, res in swaps.items():
        print(f"  {variant}:")
        for k, v in res.items():
            print(f"    {k}: {v}")

    # ── Save ──
    out = {
        "track1_iter11b_swaps": swaps,
        "track3_bootstrap_ci_t1_v5": bs,
        "track4_t3_composite": t3_res,
        "n_subjects": int(n),
    }
    out_path = RESULTS_DIR / "iter11b_analysis.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nWrote {out_path}", flush=True)


if __name__ == "__main__":
    main()

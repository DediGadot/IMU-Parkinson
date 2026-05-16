#!/usr/bin/env python3
"""Canonical frozen-OOF audit for iter13 T1 hybrid v5.

This script does not retrain models. It verifies the frozen final result from saved
OOF arrays, records source hashes/alignment, recomputes metrics and bootstrap CIs,
and runs OOF-level negative controls that should collapse if subject alignment is
broken or labels are permuted.

Output: results/iter13_final_T1_v5_full_audit.json
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from inductive_lib import ccc as ccc_fn, full_metrics
from run_per_item_v2 import load_data as load_per_item_data
from project_paths import RESULTS_DIR

ROOT = Path(__file__).resolve().parent
OUT = RESULTS_DIR / "iter13_final_T1_v5_full_audit.json"
T1_ITEMS = [9, 10, 11, 12, 13, 14]
ITER6_TS = "20260430_182930"

SOURCE_FILES = {
    9: "lockbox_peritem_9_hy_residual_item_20260430_143044.oof.npy",
    10: "lockbox_self_norm_cross_10_self_norm_hy_residual_20260501_064907.oof.npy",
    11: "lockbox_peritem_11_item_dedicated_20260430_143044.oof.npy",
    12: "lockbox_peritem_12_item_plus_v2_cccv2.oof.npy",
    13: "interaction_13_v2_plus_self_norm_loocv_loocv_winners.oof.npy",
    # item14 needs SID alignment from iter6 source order
    14: f"iter6_item14_oof_{ITER6_TS}.npy",
}
SOURCE_LABELS = {
    9: "iter8 hy_residual_item",
    10: "iter11 self_norm_hy_residual",
    11: "iter8 item_dedicated",
    12: "iter9 cccv2 item_plus_v2",
    13: "iter10 v2_plus_self_norm",
    14: "iter6 V2+TUG gated",
}
META_FILES = {
    9: "lockbox_peritem_9_hy_residual_item_20260430_143044.json",
    10: "lockbox_self_norm_cross_10_self_norm_hy_residual_20260501_064907.json",
    11: "lockbox_peritem_11_item_dedicated_20260430_143044.json",
    12: "lockbox_peritem_12_item_plus_v2_cccv2_cccv2.json",
    13: "interaction_13_v2_plus_self_norm_loocv_loocv_winners.json",
    14: f"lockbox_t1_iter6_loocv_{ITER6_TS}.json",
}
PREREG_FILES = {
    9: "preregistration_peritem_9_20260430_143044.json",
    10: "preregistration_self_norm_cross_10_self_norm_hy_residual_20260501_064907.json",
    11: "preregistration_peritem_11_20260430_143044.json",
    13: "preregistration_peritem_13_20260430_143044.json",
}


def sha256_path(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_array(a: np.ndarray) -> str:
    aa = np.ascontiguousarray(a)
    h = hashlib.sha256()
    h.update(str(aa.shape).encode())
    h.update(str(aa.dtype).encode())
    h.update(aa.tobytes())
    return h.hexdigest()


def read_json_if_exists(p: Path) -> Any | None:
    if not p.exists():
        return None
    with p.open() as f:
        return json.load(f)


def json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def hy_bins(hy: np.ndarray, n_bins: int = 5) -> np.ndarray:
    """Stable small-N bins for stratified bootstrap."""
    hy = np.asarray(hy, dtype=float)
    # Prefer exact H&Y value bins; merge sparse bins by rank quantiles only if needed.
    vals = np.unique(hy[~np.isnan(hy)])
    if len(vals) <= n_bins:
        mapping = {v: i for i, v in enumerate(vals)}
        return np.array([mapping.get(v, 0) for v in hy], dtype=int)
    order = np.argsort(hy, kind="mergesort")
    bins = np.zeros(len(hy), dtype=int)
    for b, idx in enumerate(np.array_split(order, n_bins)):
        bins[idx] = b
    return bins


def bootstrap_ccc(y: np.ndarray, pred: np.ndarray, hy: np.ndarray, *, seed: int, reps: int = 5000) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    bins = hy_bins(hy, 5)
    groups = [np.where(bins == b)[0] for b in sorted(set(bins.tolist()))]
    vals = []
    for _ in range(reps):
        idx = np.concatenate([rng.choice(g, size=len(g), replace=True) for g in groups if len(g)])
        vals.append(float(ccc_fn(y[idx], pred[idx])))
    arr = np.asarray(vals)
    return {
        "seed": seed,
        "reps": reps,
        "stratify_by": "exact_hy_bins_if_<=5_else_rank_bins",
        "hy_bin_counts": {str(int(b)): int((bins == b).sum()) for b in sorted(set(bins.tolist()))},
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)),
        "ci_2.5": float(np.quantile(arr, 0.025)),
        "ci_97.5": float(np.quantile(arr, 0.975)),
        "ci_0.5": float(np.quantile(arr, 0.005)),
        "ci_99.5": float(np.quantile(arr, 0.995)),
        "p_gt_0.69": float((arr > 0.69).mean()),
        "p_gt_0.70": float((arr > 0.70).mean()),
        "p_gt_0.72": float((arr > 0.72).mean()),
        "min": float(arr.min()),
        "max": float(arr.max()),
    }


def load_sources(d: dict[str, Any]) -> tuple[dict[int, np.ndarray], dict[str, Any]]:
    n = len(d["sids"])
    sids_cur = np.array([str(s) for s in d["sids"]])
    sid_info: dict[str, Any] = {
        "n_subjects": int(n),
        "current_sid_sha256": sha256_array(sids_cur.astype("U")),
    }
    arrays: dict[int, np.ndarray] = {}
    source_info: dict[int, dict[str, Any]] = {}

    # iter6 alignment for item 14
    sids_iter6_path = RESULTS_DIR / f"iter6_sids_{ITER6_TS}.npy"
    sids_iter6 = np.load(sids_iter6_path, allow_pickle=True)
    sids_iter6 = np.array([str(s) for s in sids_iter6])
    iter6_pos = {s: i for i, s in enumerate(sids_iter6)}
    align_idx = np.array([iter6_pos.get(s, -1) for s in sids_cur], dtype=int)
    valid6 = align_idx >= 0
    sid_info.update({
        "iter6_sids_file": str(sids_iter6_path.relative_to(ROOT)),
        "iter6_sids_sha256": sha256_path(sids_iter6_path),
        "iter6_sid_count": int(len(sids_iter6)),
        "iter6_matched_current_subjects": int(valid6.sum()),
        "iter6_missing_current_subjects": [str(s) for s, ok in zip(sids_cur, valid6) if not ok],
        "iter6_duplicate_sids": bool(len(set(sids_iter6.tolist())) != len(sids_iter6)),
        "current_duplicate_sids": bool(len(set(sids_cur.tolist())) != len(sids_cur)),
    })

    for item, fname in SOURCE_FILES.items():
        p = RESULTS_DIR / fname
        raw = np.load(p)
        arr = raw.astype(float)
        alignment = "native_current_order"
        if item == 14:
            full = np.full(n, np.nan, dtype=float)
            full[valid6] = arr[align_idx[valid6]]
            arr = full
            alignment = "aligned_from_iter6_sids_by_subject_id"
        arrays[item] = arr
        y_item = np.asarray(d["items"][item], dtype=float)
        meta = read_json_if_exists(RESULTS_DIR / META_FILES[item]) if item in META_FILES else None
        prereg = read_json_if_exists(RESULTS_DIR / PREREG_FILES[item]) if item in PREREG_FILES else None
        source_info[item] = {
            "label": SOURCE_LABELS[item],
            "file": str(p.relative_to(ROOT)),
            "file_sha256": sha256_path(p),
            "array_sha256": sha256_array(arr),
            "raw_shape": list(raw.shape),
            "final_shape": list(arr.shape),
            "alignment": alignment,
            "nan_count": int(np.isnan(arr).sum()),
            "finite_count": int(np.isfinite(arr).sum()),
            "metric_vs_item_target": full_metrics(y_item, arr),
            "meta_file": META_FILES.get(item),
            "meta_file_exists": bool((RESULTS_DIR / META_FILES[item]).exists()) if item in META_FILES else False,
            "meta_sha256": sha256_path(RESULTS_DIR / META_FILES[item]) if item in META_FILES and (RESULTS_DIR / META_FILES[item]).exists() else None,
            "prereg_file": PREREG_FILES.get(item),
            "prereg_file_exists": bool((RESULTS_DIR / PREREG_FILES[item]).exists()) if item in PREREG_FILES else False,
            "prereg_sha256": sha256_path(RESULTS_DIR / PREREG_FILES[item]) if item in PREREG_FILES and (RESULTS_DIR / PREREG_FILES[item]).exists() else None,
            "meta_summary_keys": sorted(meta.keys()) if isinstance(meta, dict) else None,
            "prereg_summary_keys": sorted(prereg.keys()) if isinstance(prereg, dict) else None,
        }
    return arrays, {"sid_alignment": sid_info, "sources": {str(k): v for k, v in source_info.items()}}


def oof_negative_controls(y: np.ndarray, pred: np.ndarray, arrays: dict[int, np.ndarray], *, seed: int = 20260501, reps: int = 2000) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    n = len(y)
    label_perm_ccc = []
    joint_sid_shuffle_ccc = []
    independent_component_shuffle_ccc = []
    circular_shift_ccc = []
    for _ in range(reps):
        perm = rng.permutation(n)
        label_perm_ccc.append(float(ccc_fn(y[perm], pred)))
        joint_sid_shuffle_ccc.append(float(ccc_fn(y, pred[perm])))
        comp = np.zeros(n)
        for item in T1_ITEMS:
            comp += arrays[item][rng.permutation(n)]
        independent_component_shuffle_ccc.append(float(ccc_fn(y, comp)))
        shift = int(rng.integers(1, n))
        circular_shift_ccc.append(float(ccc_fn(y, np.roll(pred, shift))))

    def summarize(vals: list[float]) -> dict[str, float]:
        a = np.asarray(vals)
        return {
            "mean": float(a.mean()),
            "std": float(a.std(ddof=1)),
            "min": float(a.min()),
            "max": float(a.max()),
            "q01": float(np.quantile(a, 0.01)),
            "q50": float(np.quantile(a, 0.50)),
            "q99": float(np.quantile(a, 0.99)),
            "p_abs_gt_0.20": float((np.abs(a) > 0.20).mean()),
            "p_gt_observed": float((a >= ccc_fn(y, pred)).mean()),
        }

    return {
        "description": "OOF-level controls only; they verify metric/alignment fragility, not retraining leakage.",
        "seed": seed,
        "reps": reps,
        "observed_ccc": float(ccc_fn(y, pred)),
        "label_permutation_y_vs_fixed_pred": summarize(label_perm_ccc),
        "joint_sid_shuffle_fixed_pred": summarize(joint_sid_shuffle_ccc),
        "independent_component_shuffle_then_sum": summarize(independent_component_shuffle_ccc),
        "circular_shift_fixed_pred": summarize(circular_shift_ccc),
    }


def main() -> None:
    d = load_per_item_data()
    y = np.asarray(d["t1"], dtype=float)
    arrays, provenance = load_sources(d)
    pred = np.zeros(len(y), dtype=float)
    for item in T1_ITEMS:
        pred += arrays[item]

    items_sum = np.zeros(len(y), dtype=float)
    for item in T1_ITEMS:
        items_sum += np.asarray(d["items"][item], dtype=float)

    comp_path = RESULTS_DIR / "peritem_composite_hybrid_v5_iter11.json"
    final_path = RESULTS_DIR / "iter13_final_T1_v5_verified.json"
    iter11b_path = RESULTS_DIR / "iter11b_analysis.json"

    composite_json = read_json_if_exists(comp_path)
    final_json = read_json_if_exists(final_path)
    iter11b_json = read_json_if_exists(iter11b_path)

    metrics = full_metrics(y, pred)
    out = {
        "audit_version": "2026-05-01_final_frozen_oof_audit_v1",
        "scope": "Frozen OOF reconstruction and metadata/null audit for iter13 T1 hybrid v5; no retraining except external tests.",
        "result_files": {
            "final_verified_json": str(final_path.relative_to(ROOT)),
            "final_verified_json_sha256": sha256_path(final_path) if final_path.exists() else None,
            "composite_json": str(comp_path.relative_to(ROOT)),
            "composite_json_sha256": sha256_path(comp_path) if comp_path.exists() else None,
            "iter11b_analysis_json": str(iter11b_path.relative_to(ROOT)),
            "iter11b_analysis_json_sha256": sha256_path(iter11b_path) if iter11b_path.exists() else None,
        },
        **provenance,
        "target_checks": {
            "t1_equals_sum_items_9_14": bool(np.allclose(y, items_sum, atol=0, rtol=0)),
            "maxabs_t1_minus_sum_items_9_14": float(np.max(np.abs(y - items_sum))),
            "target_sha256": sha256_array(y),
            "sum_items_target_sha256": sha256_array(items_sum),
        },
        "final_prediction": {
            "array_sha256": sha256_array(pred),
            "nan_count": int(np.isnan(pred).sum()),
            "finite_count": int(np.isfinite(pred).sum()),
            "min": float(np.min(pred)),
            "max": float(np.max(pred)),
            "metrics": metrics,
        },
        "bootstrap_canonical_stratified_hy_5000": bootstrap_ccc(y, pred, np.asarray(d["hy"], dtype=float), seed=20260501, reps=5000),
        "oof_level_negative_controls": oof_negative_controls(y, pred, arrays, seed=20260501, reps=2000),
        "comparison_to_existing_artifacts": {},
        "audit_conclusion_flags": {},
    }

    if isinstance(final_json, dict):
        out["comparison_to_existing_artifacts"]["iter13_final_T1_v5_verified"] = {
            "json_metrics": {k: final_json.get(k) for k in ["T1_LOOCV_CCC", "T1_MAE", "T1_slope", "T1_r"]},
            "metric_deltas_recomputed_minus_json": {
                "ccc": float(metrics["ccc"] - final_json.get("T1_LOOCV_CCC", np.nan)),
                "mae": float(metrics["mae"] - final_json.get("T1_MAE", np.nan)),
                "slope": float(metrics["cal_slope"] - final_json.get("T1_slope", np.nan)),
                "r": float(metrics["r"] - final_json.get("T1_r", np.nan)),
            },
            "bootstrap_in_json": final_json.get("bootstrap_1000reps_strat_hy"),
        }
    if isinstance(composite_json, dict):
        c = composite_json.get("composites", {}).get("T1_hybrid_v5_iter11", {})
        out["comparison_to_existing_artifacts"]["peritem_composite_hybrid_v5_iter11"] = {
            "json_metrics": {k: c.get(k) for k in ["ccc", "mae", "cal_slope", "r", "pred_mean", "pred_std", "true_mean", "true_std"]},
            "swaps": c.get("swaps"),
        }
    if isinstance(iter11b_json, dict):
        b = iter11b_json.get("track3_bootstrap_ci_t1_v5", {})
        out["comparison_to_existing_artifacts"]["iter11b_analysis_bootstrap"] = b

    flags = out["audit_conclusion_flags"]
    flags["metrics_match_final_json"] = bool(
        isinstance(final_json, dict)
        and abs(metrics["ccc"] - final_json.get("T1_LOOCV_CCC", np.nan)) < 5e-5
        and abs(metrics["mae"] - final_json.get("T1_MAE", np.nan)) < 5e-5
    )
    flags["no_nan_predictions"] = bool(np.isfinite(pred).all())
    flags["t1_target_coherent"] = bool(out["target_checks"]["t1_equals_sum_items_9_14"])
    flags["all_source_meta_exists"] = bool(all(v["meta_file_exists"] for v in out["sources"].values()))
    flags["all_source_prereg_exists"] = bool(all(v["prereg_file_exists"] for v in out["sources"].values()))
    # Publication-grade no-leakage certification requires retrain null gates; this script does not do that.
    flags["certifies_no_training_leakage"] = False
    flags["requires_retraining_null_audit"] = True

    with OUT.open("w") as f:
        json.dump(out, f, indent=2, default=json_default)
    print(json.dumps({
        "wrote": str(OUT),
        "metrics": metrics,
        "bootstrap": out["bootstrap_canonical_stratified_hy_5000"],
        "flags": flags,
    }, indent=2, default=json_default))


if __name__ == "__main__":
    main()

"""T1 iter46 — ExtraTrees-only robustification screen winner.

This is a single pre-registered follow-up to the iter34 base/item/P2
decomposition audit. It is not an adaptive replacement for iter34: the screen
allowed exactly one robustness candidate, ExtraTrees-only, because it preserved
the 5-fold iter34 signal within -0.010 CCC and cleared the P2 bootstrap
one-sided margin.

Protocol:
  * cohort and Stage 1 match iter34 (N=93; items 9-14 plus aux 15/18);
  * Stage 2 is the same 8-item RegressorChain, but base set = {ExtraTrees};
  * five seeds from the robustness audit: 42, 1337, 7, 2026, 9001;
  * one pre-registration, one LOOCV lockbox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("PD_IMU_N_CORES", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import numpy as np
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter5_clinical import FEATURE_SETS, build_stage1_features, load_clinical_dict
from run_t1_iter33b_8item_chain import AUX_ITEMS, T1_SUM_ITEMS, _load_t1_cohort_with_8items
from run_t1_iter34_hybrid_8item_multibase import (
    _fit_one_fold,
    _hybrid_loocv,
    _iter5_direct_loocv,
    _paired_bootstrap_ccc,
)


ensure_dir(RESULTS_DIR)

SEEDS_DEFAULT = (42, 1337, 7, 2026, 9001)
BASES = ("et",)
FEATURE_SET = "A3_tier1"
STAGE1_ALPHA = 1.0
K_FEATURES = 500
ITER34_LOCKBOX_CCC = 0.7366
ITER12_CANONICAL_CCC = 0.6550
SCREEN_ARTIFACT = "results/iter34_base_item_decomp_20260508.json"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _formula_payload() -> dict[str, Any]:
    screen_path = REPO_ROOT / SCREEN_ARTIFACT
    return {
        "experiment": "T1 iter46 ExtraTrees-only robustification of iter34",
        "purpose": (
            "Follow the single robustness candidate from "
            "audit_t1_iter34_base_item_decomp.py; try to retain iter34-like T1 "
            "performance while clearing P2 noisy-test-X bootstrap fragility."
        ),
        "screen_source": {
            "script": "audit_t1_iter34_base_item_decomp.py",
            "artifact": SCREEN_ARTIFACT,
            "artifact_sha256": _sha256_file(screen_path),
            "screen_summary": {
                "et_baseline_ccc_mean": 0.7056904677186848,
                "et_delta_vs_all_mean": -0.003122369748038678,
                "et_p2_delta_max": 0.008072720664122346,
                "et_p2_bootstrap_ci_high_max": 0.04421608888623165,
                "et_robustification_screen_pass": True,
                "ceiling_promotion_candidates": [],
            },
        },
        "cohort": {
            "target": "T1 = sum MDS-UPDRS Part III items 9-14",
            "filter": "PD subjects complete for items 9-14 plus auxiliary items 15 and 18",
            "expected_n": 93,
            "n93_caveat": "WPD002 excluded because auxiliary item 18 is missing; prior bound showed non-load-bearing.",
        },
        "stage1": {
            "model": "Ridge",
            "alpha": STAGE1_ALPHA,
            "feature_set": FEATURE_SET,
            "features": "H&Y one-hot + cv_yrs + cv_sex + cv_dbs",
        },
        "stage2": {
            "chain_targets": list(T1_SUM_ITEMS) + list(AUX_ITEMS),
            "summed_items": list(T1_SUM_ITEMS),
            "auxiliary_items": list(AUX_ITEMS),
            "base_learners": list(BASES),
            "base_model": "ExtraTreesRegressor(n_estimators=300, max_depth=10, min_samples_leaf=5)",
            "feature_selection": f"fold-local LGB importance top K={K_FEATURES}",
            "imputation": "fold-local median",
            "item_target_centering": "fold-local train mean per item",
        },
        "lockbox": {
            "cv": "LOOCV",
            "seeds": list(SEEDS_DEFAULT),
            "headline": "mean prediction over the five ET-only seed OOF vectors",
            "comparators": [
                "iter12 honest canonical floor on same SIDs when available",
                "iter34 all-base strongest candidate",
                "same-run iter5-direct T1 residual baseline",
            ],
            "decision_rule": (
                "If LOOCV <= iter12-on-same-SIDs or bootstrap frac>0 vs iter12 < 0.95, "
                "stop. If above iter12 but below iter34, report only as robust "
                "candidate, not ceiling break. If above iter34, require a separate "
                "null-gate audit before any canonical promotion."
            ),
        },
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git_sha": _git_sha(),
    }


def _formula_sha256(payload: dict[str, Any]) -> str:
    payload = dict(payload)
    payload.pop("created_at_utc", None)
    payload.pop("git_sha", None)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def write_preregistration() -> Path:
    payload = _formula_payload()
    sha = _formula_sha256(payload)
    prereg = {
        **payload,
        "formula_sha256": sha,
        "status": "PRE_REGISTERED_BEFORE_ITER46_LOOCV",
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"preregistration_t1_iter46_etrobust_{ts}.json"
    out.write_text(json.dumps(prereg, indent=2) + "\n", encoding="utf-8")
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"formula_sha256={sha}", flush=True)
    return out


def smoke_test(seed: int = 42) -> None:
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, FEATURE_SETS[FEATURE_SET])
    splits = list(LeaveOneOut().split(np.arange(len(sids))))
    fold_id, (tr, te) = 0, splits[0]
    print(
        f"=== iter46 smoke: one LOOCV fold, seed={seed}, bases={BASES}, "
        f"test_sid={sids[te[0]]} ===",
        flush=True,
    )
    t0 = time.time()
    te_idx, pred = _fit_one_fold(
        (fold_id, tr, te, X, y_t1, X_s1, items, item_order, seed, BASES)
    )
    print(
        f"smoke pred={float(pred[0]):.4f}, y={float(y_t1[te_idx[0]]):.4f}, "
        f"wall={time.time()-t0:.2f}s",
        flush=True,
    )


def _load_comparator_from_json_npy(json_name: str, npy_name: str, sids: np.ndarray) -> dict[str, Any]:
    json_path = RESULTS_DIR / json_name
    npy_path = RESULTS_DIR / npy_name
    if not json_path.exists() or not npy_path.exists():
        return {"error": f"missing comparator {json_path} / {npy_path}"}
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    comp_sids = [str(s) for s in meta.get("per_subject", {}).get("sids", [])]
    preds = np.load(npy_path)
    sid_to_pred = dict(zip(comp_sids, preds.tolist()))
    try:
        aligned = np.asarray([sid_to_pred[str(s)] for s in sids], dtype=np.float64)
    except KeyError as exc:
        return {"error": f"SID missing in comparator: {exc!r}"}
    return {
        "json": json_name,
        "npy": npy_name,
        "pred": aligned,
        "reported_ccc": meta.get("ccc"),
        "reported_mae": meta.get("mae"),
    }


def _comparator_block(y: np.ndarray, p_new: np.ndarray, comp: dict[str, Any], label: str) -> dict[str, Any]:
    if "pred" not in comp:
        return {"label": label, **comp}
    p_old = comp["pred"]
    boot = _paired_bootstrap_ccc(y, p_new, p_old)
    return {
        "label": label,
        "ccc_comparator_on_same_sids": float(ccc_fn(y, p_old)),
        "mae_comparator_on_same_sids": float(np.mean(np.abs(y - p_old))),
        "delta_new_minus_comparator": float(ccc_fn(y, p_new) - ccc_fn(y, p_old)),
        "bootstrap_delta": boot,
        "reported_ccc": comp.get("reported_ccc"),
        "reported_mae": comp.get("reported_mae"),
    }


def run_lockbox(prereg_file: Path, *, seeds: tuple[int, ...], n_workers: int) -> Path:
    prereg = json.loads(prereg_file.read_text(encoding="utf-8"))
    expected = _formula_sha256(_formula_payload())
    if prereg.get("formula_sha256") != expected:
        raise AssertionError(
            f"prereg formula_sha256 {prereg.get('formula_sha256')!r} != current {expected!r}"
        )

    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    if item_order != list(T1_SUM_ITEMS) + list(AUX_ITEMS):
        raise RuntimeError(f"unexpected item order: {item_order}")
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, FEATURE_SETS[FEATURE_SET])

    print(
        f"\n=== T1 iter46 ET-only robust LOOCV "
        f"(N={len(sids)}, seeds={list(seeds)}, bases={BASES}, workers={n_workers}) ===",
        flush=True,
    )

    all_preds: list[np.ndarray] = []
    all_i5: list[np.ndarray] = []
    per_seed = []
    t0 = time.time()
    for seed in seeds:
        seed_t0 = time.time()
        pred = _hybrid_loocv(seed, X, y_t1, X_s1, items, item_order, BASES, n_workers)
        pred_i5 = _iter5_direct_loocv(seed, X, y_t1, X_s1, n_workers)
        c_new = float(ccc_fn(y_t1, pred))
        c_i5 = float(ccc_fn(y_t1, pred_i5))
        per_seed.append(
            {
                "seed": int(seed),
                "ccc_iter46_et": c_new,
                "mae_iter46_et": float(np.mean(np.abs(y_t1 - pred))),
                "ccc_iter5_direct": c_i5,
                "delta_vs_iter5_direct": c_new - c_i5,
                "wall_time_s": float(time.time() - seed_t0),
            }
        )
        print(
            f"  seed={seed}: ET={c_new:.4f} | i5={c_i5:.4f} | "
            f"delta={c_new-c_i5:+.4f} | {time.time()-seed_t0:.0f}s",
            flush=True,
        )
        all_preds.append(pred)
        all_i5.append(pred_i5)

    mean_pred = np.mean(np.column_stack(all_preds), axis=1)
    mean_i5 = np.mean(np.column_stack(all_i5), axis=1)
    metrics = full_metrics(y_t1, mean_pred, label="t1_iter46_etrobust")
    c_i5_mean = float(ccc_fn(y_t1, mean_i5))
    boot_i5 = _paired_bootstrap_ccc(y_t1, mean_pred, mean_i5)

    iter12 = _load_comparator_from_json_npy(
        "t1_iter12_honest_composite.json",
        "t1_iter12_honest_composite.oof.npy",
        sids,
    )
    iter34 = _load_comparator_from_json_npy(
        "lockbox_t1_iter34_hybrid_20260506_141720.json",
        "lockbox_t1_iter34_hybrid_20260506_141720.oof.npy",
        sids,
    )
    cmp_iter12 = _comparator_block(y_t1, mean_pred, iter12, "iter12_honest_same_sids")
    cmp_iter34 = _comparator_block(y_t1, mean_pred, iter34, "iter34_all_base_same_sids")

    if "bootstrap_delta" in cmp_iter12:
        candidate_above_iter12 = (
            cmp_iter12["delta_new_minus_comparator"] > 0
            and cmp_iter12["bootstrap_delta"]["frac_above_zero"] >= 0.95
        )
    else:
        candidate_above_iter12 = False
    if "bootstrap_delta" in cmp_iter34:
        candidate_above_iter34 = (
            cmp_iter34["delta_new_minus_comparator"] > 0
            and cmp_iter34["bootstrap_delta"]["frac_above_zero"] >= 0.95
        )
    else:
        candidate_above_iter34 = False

    verdict = {
        "screen_source": SCREEN_ARTIFACT,
        "is_lockbox_headline": True,
        "is_canonical_update": bool(candidate_above_iter12 and candidate_above_iter34),
        "is_robust_candidate_above_iter12": bool(candidate_above_iter12),
        "breaks_iter34_ceiling": bool(candidate_above_iter34),
        "decision": (
            "ceiling_break_requires_followup_null_gate"
            if candidate_above_iter34
            else (
                "robust_candidate_not_ceiling_break"
                if candidate_above_iter12
                else "lockbox_negative_stop_branch"
            )
        ),
    }

    out = {
        **metrics,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "T1 iter46 ET-only robustification lockbox",
        "variant": "et_only_8item_chain",
        "n": int(len(sids)),
        "seeds": [int(s) for s in seeds],
        "bases": list(BASES),
        "item_order_chain": [int(i) for i in item_order],
        "auxiliary_items_used": [int(i) for i in available_aux],
        "preregistration_file": prereg_file.name,
        "formula_sha256": prereg.get("formula_sha256"),
        "per_seed": per_seed,
        "wall_time_total_s": float(time.time() - t0),
        "ccc_iter5_direct_loocv_baseline_same_run": c_i5_mean,
        "delta_vs_iter5_direct_same_run": float(metrics["ccc"] - c_i5_mean),
        "bootstrap_delta_vs_iter5_direct_same_run": boot_i5,
        "comparison_vs_iter12_honest": cmp_iter12,
        "comparison_vs_iter34_all_base": cmp_iter34,
        "verdict": verdict,
        "per_subject": {
            "sids": [str(s) for s in sids],
            "y_true": y_t1.tolist(),
            "y_pred": mean_pred.tolist(),
        },
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_iter46_etrobust_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t1_iter46_etrobust_{ts}.oof.npy"
    out_json.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    np.save(out_npy, mean_pred)

    print(
        f"\n=== iter46 ET HEADLINE: CCC={metrics['ccc']:.4f}, MAE={metrics['mae']:.3f}, "
        f"r={metrics['r']:.4f}, slope={metrics['cal_slope']:.3f} ===",
        flush=True,
    )
    print(f"  vs same-run i5: delta={out['delta_vs_iter5_direct_same_run']:+.4f}", flush=True)
    if "delta_new_minus_comparator" in cmp_iter12:
        print(
            f"  vs iter12 same SIDs: delta={cmp_iter12['delta_new_minus_comparator']:+.4f}, "
            f"frac>0={cmp_iter12['bootstrap_delta']['frac_above_zero']:.4f}",
            flush=True,
        )
    if "delta_new_minus_comparator" in cmp_iter34:
        print(
            f"  vs iter34 all-base: delta={cmp_iter34['delta_new_minus_comparator']:+.4f}, "
            f"frac>0={cmp_iter34['bootstrap_delta']['frac_above_zero']:.4f}",
            flush=True,
        )
    print(f"  verdict={verdict['decision']}", flush=True)
    print(f"Wrote {out_json}\n      {out_npy}", flush=True)
    return out_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["smoke", "write_prereg", "lockbox"], required=True)
    parser.add_argument("--preregistration_file", type=str, default=None)
    parser.add_argument("--seeds", nargs="+", type=int, default=list(SEEDS_DEFAULT))
    parser.add_argument("--n_workers", type=int, default=11)
    args = parser.parse_args()

    if args.mode == "smoke":
        smoke_test(seed=args.seeds[0])
    elif args.mode == "write_prereg":
        write_preregistration()
    else:
        if not args.preregistration_file:
            raise ValueError("--preregistration_file is required for lockbox mode")
        run_lockbox(
            RESULTS_DIR / args.preregistration_file,
            seeds=tuple(args.seeds),
            n_workers=args.n_workers,
        )


if __name__ == "__main__":
    main()

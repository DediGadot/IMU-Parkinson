"""T3 iter28-A — AutoGluon Stage-2 replacement of iter5 LightGBM.

Stage 1 BIT-IDENTICAL to iter5 (Ridge alpha=1.0 on H&Y + cv_yrs + cv_sex + cv_dbs).
Stage 2 = AutoGluon TabularPredictor (presets=best_quality, time_limit=180s)
on V2 residual after per-fold median imputation + K=500 LGB-importance selection.

Modes: --mode {screen,write_prereg,lockbox}; lockbox requires --preregistration_file.
Each AG fit runs in its own ProcessPool worker (num_cpus=1) with a fresh tmp dir.
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")
# AutoGluon prints lots of logs; quieten:
os.environ.setdefault("AUTOGLUON_LOG_LEVEL", "30")  # WARNING

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold, LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn
from inductive_lib import full_metrics, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold
from run_t3_iter3 import load_full_pd_data
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
PUBLISHED_ITER5_LOOCV_CCC = 0.5227
ITER5_LOCKBOX_OOF = RESULTS_DIR / "lockbox_t3_iter5_A3_tier1_20260502_171604.oof.npy"
ITER5_LOCKBOX_JSON = RESULTS_DIR / "lockbox_t3_iter5_A3_tier1_20260502_171604.json"
STAGE1_ALPHA = 1.0
K_FEATURES = 500


# ── Stage 2: AutoGluon ──────────────────────────────────────────────────────


def _ag_workdir(seed: int, fold_id: int) -> str:
    return f"/tmp/ag_iter28a_{seed}_{fold_id}_{int(time.time()*1000)}"


def stage2_autogluon(
    Xtr_sel: np.ndarray,
    residual_tr: np.ndarray,
    Xte_sel: np.ndarray,
    seed: int,
    fold_id: int,
    time_limit: int = 180,
) -> np.ndarray:
    """Fit AG on (Xtr_sel, residual_tr); predict Xte_sel. Tmp dir cleaned on exit."""
    from autogluon.tabular import TabularPredictor

    tr_df = pd.DataFrame(Xtr_sel)
    tr_df.columns = [f"f{i}" for i in range(tr_df.shape[1])]
    tr_df["__target__"] = residual_tr
    te_df = pd.DataFrame(Xte_sel)
    te_df.columns = [f"f{i}" for i in range(te_df.shape[1])]

    workdir = _ag_workdir(seed, fold_id)
    try:
        pred = TabularPredictor(
            label="__target__",
            problem_type="regression",
            eval_metric="mean_absolute_error",
            verbosity=1,
            path=workdir,
        ).fit(
            tr_df,
            time_limit=time_limit,
            presets="best_quality",
            ag_args_fit={"random_state": seed, "num_cpus": 1},
        )
        out = pred.predict(te_df).values.astype(np.float64)
        return out
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ── Worker (one fold of either 5-fold or LOOCV) ─────────────────────────────


def _fit_one_fold(
    seed: int, fold_id: int, tr_idx: np.ndarray, te_idx: np.ndarray,
    X: np.ndarray, y_t3: np.ndarray, X_s1: np.ndarray, time_limit: int,
) -> tuple[np.ndarray, np.ndarray]:
    """One fold: Stage 1 (iter5 bit-identical) + AG Stage 2. Returns (te_idx, te_preds)."""
    s1_pred_tr, s1_pred_te = fit_stage1(X_s1[tr_idx], y_t3[tr_idx], X_s1[te_idx], alpha=STAGE1_ALPHA)
    residual_tr = y_t3[tr_idx] - s1_pred_tr
    Xtr, Xte = impute_fold(X[tr_idx], X[te_idx])
    Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=K_FEATURES, seed=seed)
    s2_pred_te = stage2_autogluon(
        Xtr_sel, residual_tr, Xte_sel, seed=seed, fold_id=fold_id, time_limit=time_limit
    )
    return te_idx, s1_pred_te + s2_pred_te


def _splits(n: int, seed: int, eval_mode: str) -> list[tuple[np.ndarray, np.ndarray]]:
    if eval_mode == "5fold":
        return list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))
    if eval_mode == "loocv":
        return list(LeaveOneOut().split(np.arange(n)))
    raise ValueError(f"unknown eval_mode {eval_mode!r}")


def _run_seed(
    seed: int, feature_set: str, time_limit: int, eval_mode: str, n_workers: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Returns (sids, y_t3, preds, wall_time_s) for ONE seed."""
    sids, X, _, y_t3, hy, _ = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    splits = _splits(n, seed, eval_mode)
    preds = np.zeros(n)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futures = {
            ex.submit(_fit_one_fold, seed, fid, tr, te, X, y_t3, X_s1, time_limit): fid
            for fid, (tr, te) in enumerate(splits)
        }
        done = 0
        for fut in as_completed(futures):
            te_idx, te_preds = fut.result()
            preds[te_idx] = te_preds
            done += 1
            if eval_mode == "loocv" and done % 10 == 0:
                print(f"  [seed={seed}] {done}/{len(splits)} folds, elapsed {time.time()-t0:.1f}s", flush=True)
    return sids, y_t3, preds, time.time() - t0


def _quartile_residuals(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float]:
    """Mean residual on Q1/Q4 of y_true — diagnostic for tail-end ensemble shift."""
    q1 = float(np.percentile(y_true, 25))
    q4 = float(np.percentile(y_true, 75))
    res = y_pred - y_true
    q1_mask, q4_mask = y_true <= q1, y_true >= q4
    return (
        float(res[q1_mask].mean()) if q1_mask.any() else float("nan"),
        float(res[q4_mask].mean()) if q4_mask.any() else float("nan"),
    )


# ── Mode: screen ────────────────────────────────────────────────────────────


def run_screen(seeds: tuple[int, ...], feature_set: str, time_limit: int, n_workers: int) -> Path:
    print(
        f"\n=== T3 iter28-A SCREEN (5-fold, feature_set={feature_set}, "
        f"time_limit={time_limit}s, {len(seeds)} seeds, {n_workers} workers) ===",
        flush=True,
    )
    from run_t3_iter5_clinical import clinical_residual_kfold

    rows: list[dict[str, Any]] = []
    iter5_per_seed: list[float] = []
    for seed in seeds:
        sids, y_t3, preds_ag, elapsed = _run_seed(
            seed=seed, feature_set=feature_set, time_limit=time_limit,
            eval_mode="5fold", n_workers=n_workers,
        )
        iter5_preds = clinical_residual_kfold(seed=seed, feature_set=feature_set, alpha=STAGE1_ALPHA)
        iter5_ccc = float(ccc_fn(y_t3, iter5_preds))
        iter5_per_seed.append(iter5_ccc)
        c = float(ccc_fn(y_t3, preds_ag))
        m = float(mae_fn(y_t3, preds_ag))
        r = float(pearson_r(y_t3, preds_ag))
        slope = float(np.polyfit(preds_ag, y_t3, 1)[0]) if preds_ag.std() > 1e-9 else float("nan")
        q1_res, q4_res = _quartile_residuals(y_t3, preds_ag)
        rows.append({
            "seed": seed, "ccc": round(c, 4), "mae": round(m, 3), "r": round(r, 4),
            "slope": round(slope, 4), "q1_residual": round(q1_res, 3), "q4_residual": round(q4_res, 3),
            "wall_time_s": round(elapsed, 1), "iter5_5fold_ccc": round(iter5_ccc, 4),
            "delta_vs_iter5": round(c - iter5_ccc, 4),
        })
        print(
            f"  seed={seed}: AG CCC={c:.4f} | iter5 CCC={iter5_ccc:.4f} | "
            f"Δ={c-iter5_ccc:+.4f} | MAE={m:.3f} | r={r:.4f} | slope={slope:.3f} | "
            f"Q1res={q1_res:+.2f} Q4res={q4_res:+.2f} | {elapsed:.1f}s",
            flush=True,
        )

    df = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"iter28a_autogluon_5fold_{ts}.csv"
    df.to_csv(out, index=False)
    print(
        f"\nMean AG CCC = {df['ccc'].mean():.4f} ± {df['ccc'].std():.4f}; "
        f"Mean iter5 CCC = {np.mean(iter5_per_seed):.4f} ± {np.std(iter5_per_seed):.4f}; "
        f"Δ̄ = {df['delta_vs_iter5'].mean():+.4f}",
        flush=True,
    )
    print(f"Wrote {out}", flush=True)
    return out


# ── Mode: write_prereg ──────────────────────────────────────────────────────


def _formula_payload(time_limit: int, feature_set: str) -> dict[str, Any]:
    return {
        "experiment": "T3 iter28-A AutoGluon Stage-2 replacement",
        "stage1": {
            "model": "Ridge",
            "alpha": STAGE1_ALPHA,
            "fit_intercept": True,
            "feature_set_name": feature_set,
            "feature_set_extras": ITER5_FEATURE_SETS[feature_set],
            "stage1_total_features": 6 + len(ITER5_FEATURE_SETS[feature_set]),
            "per_fold_standardisation": True,
            "source_module": "run_t3_iter5_clinical:fit_stage1",
        },
        "stage2": {
            "model": "autogluon.tabular.TabularPredictor",
            "presets": "best_quality",
            "time_limit_s": time_limit,
            "eval_metric": "mean_absolute_error",
            "problem_type": "regression",
            "ag_args_fit": {"num_cpus": 1, "random_state_per_seed": True},
            "feature_select_k": K_FEATURES,
            "feature_select_method": "lgb_importance_top_k_per_fold",
            "imputation": "fold_local_median",
        },
        "eval": {
            "loocv_n": 98,
            "seeds": list(SEEDS_DEFAULT),
            "fold_construction_5fold": "KFold(shuffle=True, random_state=seed)",
            "headline_metric": "CCC of mean-of-3-seed predictions",
            "comparator_oof": ITER5_LOCKBOX_OOF.name,
            "comparator_ccc": PUBLISHED_ITER5_LOOCV_CCC,
        },
        "lockbox_rules": [
            "ONE config pre-registered. ONE LOOCV run.",
            "Stage 1 BIT-IDENTICAL to iter5 (Ridge alpha=1.0 on H&Y + A3_tier1).",
            "Stage 2 = AutoGluon best_quality, time_limit=180s, num_cpus=1.",
            "Per-fold imputation + K=500 LGB-importance selection (iter5 contract).",
            "Headline = CCC of mean-of-3-seed preds on N=98.",
            "Canonical update IFF paired-bootstrap (n=5000) frac>0 >= 0.95 AND ccc > 0.5227.",
        ],
    }


def _formula_sha256(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def write_preregistration(time_limit: int, feature_set: str) -> Path:
    payload = _formula_payload(time_limit=time_limit, feature_set=feature_set)
    sha = _formula_sha256(payload)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "experiment": "T3 iter28-A — AutoGluon Stage-2 replacement of iter5 LightGBM",
        "git_head": _git_head(),
        "formula_sha256": sha,
        "formula": payload,
        "n_subjects": 98,
        "eval_protocol": (
            "LOOCV (n=98), Stage-1 Ridge (alpha=1.0) on H&Y + cv_yrs + cv_sex + cv_dbs "
            "with per-fold standardisation. Stage-2 AutoGluon TabularPredictor "
            "(presets=best_quality, time_limit=180s, num_cpus=1) on V2 residual after "
            "per-fold median imputation and K=500 LGB-importance selection. "
            "3-seed mean preds = headline."
        ),
    }
    out = RESULTS_DIR / f"preregistration_t3_iter28a_autogluon_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


# ── Mode: lockbox ───────────────────────────────────────────────────────────


def _load_iter5_oof(sids_ref: np.ndarray, y_t3_ref: np.ndarray) -> np.ndarray:
    """Align iter5 lockbox OOF preds to current SID order; assert y_true matches."""
    if not ITER5_LOCKBOX_OOF.exists() or not ITER5_LOCKBOX_JSON.exists():
        raise FileNotFoundError(f"iter5 lockbox files missing: {ITER5_LOCKBOX_OOF}, {ITER5_LOCKBOX_JSON}")
    iter5_preds = np.load(ITER5_LOCKBOX_OOF)
    with open(ITER5_LOCKBOX_JSON) as f:
        meta = json.load(f)
    iter5_sids = list(meta["per_subject"]["sids"])
    iter5_y = np.array(meta["per_subject"]["y_true"], dtype=np.float64)
    sid_to_pred = dict(zip(iter5_sids, iter5_preds.tolist()))
    sid_to_y = dict(zip(iter5_sids, iter5_y.tolist()))
    aligned_pred = np.array([sid_to_pred[str(s)] for s in sids_ref], dtype=np.float64)
    aligned_y = np.array([sid_to_y[str(s)] for s in sids_ref], dtype=np.float64)
    if not np.allclose(aligned_y, y_t3_ref, atol=1e-6):
        raise AssertionError("iter5 y_true does not match current y_t3; SID alignment broken.")
    return aligned_pred


def run_lockbox(
    preregistration_file: Path, seeds: tuple[int, ...], feature_set: str,
    time_limit: int, n_workers: int,
) -> Path:
    if not preregistration_file.exists():
        raise FileNotFoundError(f"missing preregistration_file: {preregistration_file}")
    with open(preregistration_file) as f:
        prereg = json.load(f)
    expected_sha = _formula_sha256(_formula_payload(time_limit=time_limit, feature_set=feature_set))
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(
            f"prereg formula_sha256 {prereg.get('formula_sha256')!r} != current {expected_sha!r}"
        )

    print(
        f"\n=== T3 iter28-A LOCKBOX LOOCV (feature_set={feature_set}, "
        f"time_limit={time_limit}s, {len(seeds)} seeds, {n_workers} workers) ===",
        flush=True,
    )
    all_preds: list[tuple[int, np.ndarray]] = []
    sids_ref: np.ndarray | None = None
    y_t3_ref: np.ndarray | None = None
    per_seed_metrics: list[dict[str, float]] = []
    for seed in seeds:
        sids, y_t3, preds, elapsed = _run_seed(
            seed=seed, feature_set=feature_set, time_limit=time_limit,
            eval_mode="loocv", n_workers=n_workers,
        )
        c = float(ccc_fn(y_t3, preds))
        m = float(mae_fn(y_t3, preds))
        r = float(pearson_r(y_t3, preds))
        per_seed_metrics.append({"seed": seed, "ccc": c, "mae": m, "r": r, "wall_time_s": elapsed})
        print(f"  seed {seed}: CCC={c:.4f}, MAE={m:.3f}, r={r:.4f}, time={elapsed:.1f}s", flush=True)
        all_preds.append((seed, preds))
        sids_ref = sids
        y_t3_ref = y_t3

    assert sids_ref is not None and y_t3_ref is not None
    mean_preds = np.mean(np.column_stack([p for _, p in all_preds]), axis=1)
    headline = full_metrics(y_t3_ref, mean_preds, label="t3_iter28a_autogluon")

    iter5_aligned = _load_iter5_oof(sids_ref, y_t3_ref)
    iter5_ccc_on_ref = float(ccc_fn(y_t3_ref, iter5_aligned))

    rng = np.random.RandomState(42)
    n_boot = 5000
    n = len(y_t3_ref)
    deltas = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, size=n)
        deltas[i] = ccc_fn(y_t3_ref[idx], mean_preds[idx]) - ccc_fn(y_t3_ref[idx], iter5_aligned[idx])
    boot = {
        "n_boot": n_boot,
        "delta_mean": round(float(deltas.mean()), 4),
        "delta_ci_low": round(float(np.percentile(deltas, 2.5)), 4),
        "delta_ci_high": round(float(np.percentile(deltas, 97.5)), 4),
        "frac_above_zero": round(float((deltas > 0).mean()), 4),
        "frac_above_0p005": round(float((deltas > 0.005).mean()), 4),
    }
    is_canonical_update = bool(
        boot["frac_above_zero"] >= 0.95 and headline["ccc"] > PUBLISHED_ITER5_LOOCV_CCC
    )

    headline.update({
        "feature_set": feature_set, "time_limit_s": time_limit, "alpha": STAGE1_ALPHA,
        "eval_mode": "loocv_3seed_mean", "n_seeds": len(seeds), "per_seed": per_seed_metrics,
        "per_subject": {
            "sids": sids_ref.tolist(), "y_true": y_t3_ref.tolist(), "y_pred": mean_preds.tolist(),
        },
        "preregistration_file": preregistration_file.name, "is_lockbox_headline": True,
        "baseline_iter5_ccc_on_same_98": round(iter5_ccc_on_ref, 4),
        "baseline_published_iter5_ccc": PUBLISHED_ITER5_LOOCV_CCC,
        "delta_vs_iter5": round(float(headline["ccc"]) - iter5_ccc_on_ref, 4),
        "bootstrap_delta_vs_iter5": boot, "is_canonical_update": is_canonical_update,
    })

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"iter28a_lockbox_{ts}.json"
    out_npy = RESULTS_DIR / f"iter28a_lockbox_{ts}.oof.npy"
    out_sids = RESULTS_DIR / f"iter28a_lockbox_{ts}.sids.npy"
    np.save(out_npy, mean_preds)
    np.save(out_sids, sids_ref)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)

    print(
        f"\n=== HEADLINE (lockbox): CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f}, "
        f"r={headline['r']:.4f}, slope={headline['cal_slope']:.3f} ===",
        flush=True,
    )
    print(f"  iter5 CCC on same N=98: {iter5_ccc_on_ref:.4f}  |  Δ = {headline['delta_vs_iter5']:+.4f}", flush=True)
    print(
        f"  Bootstrap (n={n_boot}): mean Δ={boot['delta_mean']:+.4f}, "
        f"95% CI=[{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}], "
        f"frac>0={boot['frac_above_zero']}, frac>0.005={boot['frac_above_0p005']}",
        flush=True,
    )
    print(f"  is_canonical_update = {is_canonical_update}", flush=True)
    print(f"Wrote {out_json}\n      {out_npy}\n      {out_sids}", flush=True)
    return out_json


# ── main ────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["screen", "write_prereg", "lockbox"], required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--feature_set", default="A3_tier1")
    ap.add_argument("--time_limit", type=int, default=180, help="seconds per AutoGluon fit")
    ap.add_argument(
        "--n_workers", type=int, default=int(os.getenv("ITER28A_WORKERS", 5)),
        help="ProcessPool workers (each AG fit uses N_CORES=1 internally)",
    )
    ap.add_argument("--preregistration_file", type=str, default=None)
    args = ap.parse_args()

    if args.feature_set not in ITER5_FEATURE_SETS:
        raise ValueError(
            f"feature_set must be one of {list(ITER5_FEATURE_SETS)}; got {args.feature_set!r}"
        )

    seeds = tuple(args.seeds)
    if args.mode == "screen":
        run_screen(seeds=seeds, feature_set=args.feature_set,
                   time_limit=args.time_limit, n_workers=args.n_workers)
    elif args.mode == "write_prereg":
        write_preregistration(time_limit=args.time_limit, feature_set=args.feature_set)
    elif args.mode == "lockbox":
        if not args.preregistration_file:
            raise ValueError("--preregistration_file is required for --mode lockbox")
        run_lockbox(
            preregistration_file=Path(args.preregistration_file), seeds=seeds,
            feature_set=args.feature_set, time_limit=args.time_limit, n_workers=args.n_workers,
        )
    else:
        raise ValueError(f"unknown mode {args.mode!r}")


if __name__ == "__main__":
    main()

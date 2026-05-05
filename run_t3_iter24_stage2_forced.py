"""T3 iter24 — Stage-2 forced-inclusion of clinical extras (finalizing experiment).

Mission origin: iter23 (F59 prequel) ran a 5-fold ablation across 19 single-/pair-/
kitchen-sink Stage-1 widening variants over (LEDD, Part1 items, ON/OFF, race, etc.).
**Zero passers; every variant Δ ≤ 0** — partial-correlation collapse mechanism
(both codex and gemini confirmed). Diagnostic partial-r analysis (residualizing
against H&Y + cv_yrs + cv_sex + cv_dbs) showed that only THREE clinical extras
retain non-trivial partial signal:

  part1_cognitive          partial r = +0.232  (n=61, 37% NaN)
  assistive_device_yn      partial r = +0.156  (n=98)
  hours_since_last_dose    partial r = −0.158  (n=89)

This script is the **finalizing experiment** for the T3 push. It tests the only
remaining architectural lever explicitly allowed by AGENTS.md "dead-list rules":
**forced-inclusion of clinical extras at Stage-2 LGB**, bypassing the K=500
LGB-importance absorption that killed all prior small-feature additions
(F19/F44/F45/F48). The clinical extras are concatenated to V2 features; a custom
fold-local feature selector ALWAYS retains the M clinical-extra columns and
fills the remaining K−M slots from V2 by LGB-importance.

  Stage 1: bit-identical to iter5 — Ridge on (H&Y + cv_yrs + cv_sex + cv_dbs).
  Stage 2: LGB on (V2 residual ⊕ clinical_extras), K=500 with forced inclusion.

GATES (single-batch pre-reg, no cherry-picking):
  5-fold sum-level: hybrid CCC ≥ iter5 5-fold + 0.025 AND seed std < 0.020.
  LOOCV lockbox:    paired bootstrap CI vs iter5 LOOCV on identical N=98 SIDs;
                    canonical update requires frac>0 ≥ 95% AND ccc > 0.5227.

Usage:
  # Pre-register the immutable architecture
  python3 run_t3_iter24_stage2_forced.py --mode write_prereg --cv 5fold --seeds 42 1337 7
  # Execute (validates formula_sha256)
  python3 run_t3_iter24_stage2_forced.py --mode run --preregistration_file <path>
  # If 5-fold gate passes:
  python3 run_t3_iter24_stage2_forced.py --mode write_prereg --cv loocv --seeds 42 1337 7
  python3 run_t3_iter24_stage2_forced.py --mode run --preregistration_file <path>

Both consults predict Δ ∈ [−0.04, +0.015], P(gate) < 10-15%. If failure: 8th
N≈100 wall data point; paper pivots to rigor section (conformal intervals).
"""
from __future__ import annotations

import os
os.environ.setdefault("PD_IMU_N_CORES", "1")

import argparse
import hashlib
import json
import subprocess
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldImputer, FoldNormalizer, ccc as ccc_fn, mae as mae_fn, pearson_r, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter3 import load_full_pd_data, get_hy_features
from run_t3_iter2 import impute_fold, train_lgb
from run_t3_iter5_clinical import (
    build_stage1_features as iter5_build_s1,
    fit_stage1,
    load_clinical_dict,
    FEATURE_SETS as ITER5_FEATURE_SETS,
)

# ── Architecture (FROZEN before any composite is computed) ──────────────────


CLINICAL_EXTRAS_PATH = RESULTS_DIR / "clinical_extras.csv"
MANIFEST_PATH = RESULTS_DIR / "clinical_extras.csv.manifest.json"
ITER5_CANONICAL_LOCKBOX_OOF_GLOB = "lockbox_t3_iter5_A3_tier1_*.oof.npy"

# The 3 partial-r winners + a fall-back kitchen-sink for completeness.
FORCED_EXTRA_COLS = [
    "part1_cognitive",
    "assistive_device_yn",
    "hours_since_last_dose",
]
ITER5_FEATURE_SET = "A3_tier1"  # H&Y + cv_yrs + cv_sex + cv_dbs (Stage-1)
ITER5_ALPHA = 1.0
LGB_FEATURE_K = 500


def _validate_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Missing manifest: {MANIFEST_PATH}")
    with open(MANIFEST_PATH) as f:
        m = json.load(f)
    if m.get("labels_used") is True:
        raise RuntimeError(f"Manifest labels_used=True; cache is leaky.")
    if m.get("leakage_status") != "clean_by_construction":
        raise RuntimeError(f"Manifest leakage_status={m.get('leakage_status')!r}")
    return m


def load_clinical_extras_aligned(sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Returns (X_extras shape=(n, len(FORCED_EXTRA_COLS)), col_names). NaN-allowed."""
    _validate_manifest()
    df = pd.read_csv(CLINICAL_EXTRAS_PATH).set_index("sid")
    n = len(sids)
    X = np.full((n, len(FORCED_EXTRA_COLS)), np.nan, dtype=np.float64)
    for j, sid in enumerate(sids):
        if sid in df.index:
            for k, c in enumerate(FORCED_EXTRA_COLS):
                v = df.loc[sid, c]
                X[j, k] = float(v) if pd.notna(v) else np.nan
    return X, list(FORCED_EXTRA_COLS)


# ── Stage-2 LGB with FORCED INCLUSION of clinical extras ────────────────────


def _feature_select_fold_forced(
    X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray,
    n_forced_cols: int, k: int = LGB_FEATURE_K, seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """LGB-importance Top-K selector with the FIRST `n_forced_cols` always retained.

    Layout: X has shape (n, n_forced + n_v2). Returns (X_tr_sel, X_te_sel, sel_idx).
    Forced indices are 0..n_forced_cols-1. Remaining K-n_forced are picked from
    V2 columns (n_forced..end) by LGB importance trained on (X, y_tr).
    """
    n_total = X_tr.shape[1]
    if n_total <= k:
        return X_tr, X_te, np.arange(n_total)
    import lightgbm as lgb
    sel = lgb.LGBMRegressor(
        n_estimators=200, learning_rate=0.1, num_leaves=15,
        min_data_in_leaf=5, n_jobs=1, random_state=seed, verbosity=-1,
    )
    sel.fit(X_tr, y_tr)
    imp = sel.feature_importances_
    forced_idx = np.arange(n_forced_cols)
    v2_idx = np.arange(n_forced_cols, n_total)
    v2_imp = imp[v2_idx]
    n_v2_pick = max(0, k - n_forced_cols)
    top_v2 = v2_idx[np.argsort(v2_imp)[::-1][:n_v2_pick]]
    sel_idx = np.concatenate([forced_idx, top_v2])
    return X_tr[:, sel_idx], X_te[:, sel_idx], sel_idx


def stage2_residual_kfold_forced(
    seed: int, alpha: float = ITER5_ALPHA,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """5-fold OOF predictions for iter24: iter5 Stage-1 + Stage-2 LGB on (V2 ⊕ clinical_extras forced).

    Returns (sids, y_t3, oof).
    """
    sids, X_v2, _, y_t3, hy, _ = load_full_pd_data()
    n = len(sids)
    clinical_iter5 = load_clinical_dict(sids)
    extras_iter5 = ITER5_FEATURE_SETS[ITER5_FEATURE_SET]
    X_s1, _ = iter5_build_s1(hy, clinical_iter5, extras_iter5)
    X_extras, _ = load_clinical_extras_aligned(sids)

    splits = list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))
    oof = np.zeros(n, dtype=np.float64)
    for tr, te in splits:
        # Stage 1: Ridge on (H&Y + cv_yrs + cv_sex + cv_dbs) — bit-identical to iter5.
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=alpha)
        residual_tr = y_t3[tr] - s1_tr

        # Stage 2 inputs: clinical_extras ⊕ V2 (extras come FIRST so forced indices are 0..M-1).
        # Per-fold imputation: extras NaNs → train-fold median. V2 imputed via existing impute_fold (median).
        ex_imputer = FoldImputer.fit(X_extras[tr])
        ex_tr = ex_imputer.transform(X_extras[tr])
        ex_te = ex_imputer.transform(X_extras[te])
        v2_tr, v2_te = impute_fold(X_v2[tr], X_v2[te])
        Xtr_full = np.hstack([ex_tr, v2_tr])
        Xte_full = np.hstack([ex_te, v2_te])

        # K=500 selector with forced inclusion of the first len(FORCED_EXTRA_COLS) cols.
        Xtr_sel, Xte_sel, _ = _feature_select_fold_forced(
            Xtr_full, residual_tr, Xte_full,
            n_forced_cols=len(FORCED_EXTRA_COLS), k=LGB_FEATURE_K, seed=seed,
        )
        s2_te = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        oof[te] = s1_te + s2_te
    return sids, y_t3, oof


def stage2_residual_loocv_forced(
    seed: int, alpha: float = ITER5_ALPHA,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sids, X_v2, _, y_t3, hy, _ = load_full_pd_data()
    n = len(sids)
    clinical_iter5 = load_clinical_dict(sids)
    extras_iter5 = ITER5_FEATURE_SETS[ITER5_FEATURE_SET]
    X_s1, _ = iter5_build_s1(hy, clinical_iter5, extras_iter5)
    X_extras, _ = load_clinical_extras_aligned(sids)

    oof = np.zeros(n, dtype=np.float64)
    t0 = time.time()
    for fold_idx, te in enumerate(range(n)):
        tr = np.array([i for i in range(n) if i != te])
        te_arr = np.array([te])
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te_arr], alpha=alpha)
        residual_tr = y_t3[tr] - s1_tr
        ex_imputer = FoldImputer.fit(X_extras[tr])
        ex_tr = ex_imputer.transform(X_extras[tr])
        ex_te = ex_imputer.transform(X_extras[te_arr])
        v2_tr, v2_te = impute_fold(X_v2[tr], X_v2[te_arr])
        Xtr_full = np.hstack([ex_tr, v2_tr])
        Xte_full = np.hstack([ex_te, v2_te])
        Xtr_sel, Xte_sel, _ = _feature_select_fold_forced(
            Xtr_full, residual_tr, Xte_full,
            n_forced_cols=len(FORCED_EXTRA_COLS), k=LGB_FEATURE_K, seed=seed,
        )
        s2_te = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        oof[te] = (s1_te + s2_te)[0]
        if (fold_idx + 1) % 20 == 0:
            print(f"  [seed={seed}] LOOCV fold {fold_idx+1}/{n}, elapsed {time.time()-t0:.1f}s", flush=True)
    return sids, y_t3, oof


# ── Pre-reg + run modes ─────────────────────────────────────────────────────


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        return "unknown"


def _formula_sha256(payload: dict) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canon).hexdigest()


def make_prereg_payload(seeds: list[int], cv: str) -> dict:
    manifest = json.load(open(MANIFEST_PATH))
    return {
        "experiment": "T3 iter24 — Stage-2 forced-inclusion of clinical extras (finalizing experiment)",
        "origin": (
            "iter23 (F59 prequel) Stage-1 widening ablation = monotone negative across 19 sets. "
            "Partial-r residualization vs (H&Y + cv_yrs + cv_sex + cv_dbs) showed only 3 covariates "
            "retain non-trivial partial signal: part1_cognitive (+0.232), assistive_device_yn (+0.156), "
            "hours_since_last_dose (−0.158). iter24 tests the only remaining architectural lever — "
            "forced-inclusion at Stage-2 LGB (bypasses K=500 absorption that killed F19/F44/F45/F48)."
        ),
        "stage1": "Ridge alpha=1.0 on (H&Y(linear+1hot) + cv_yrs + cv_sex + cv_dbs) — bit-identical to iter5",
        "stage2": (
            "LGB on (clinical_extras ⊕ V2 residual). FORCED inclusion of the 3 clinical_extras columns; "
            "remaining K-3=497 V2 cols selected per-fold by LGB-importance."
        ),
        "forced_extra_cols": FORCED_EXTRA_COLS,
        "iter5_feature_set": ITER5_FEATURE_SET,
        "iter5_alpha": ITER5_ALPHA,
        "lgb_K": LGB_FEATURE_K,
        "cv": cv,
        "seeds": list(seeds),
        "n_subjects": "T3-native cohort N=98 (canonical updrs3 cohort).",
        "endpoint": "updrs3 (T3 canonical)",
        "clinical_extras_manifest_sha256": manifest["data_sha256"],
        "5null_inheritance": (
            "iter5 base bit-identical to canonical lockbox preregistration_t3_iter5_*.json. "
            "Clinical extras cache leakage_status='clean_by_construction' (verified at script start). "
            "Per-fold FoldImputer for extras-only NaNs; per-fold standardization in Stage-1; "
            "per-fold LGB-importance selector for Stage-2 V2 cols. Forced inclusion is a per-fold rule, "
            "not a global pick."
        ),
        "purpose": (
            "Final test of whether ANY clinical-extra signal is harvestable at Stage-2 with forced "
            "inclusion. Both codex and gemini priors: predicted Δ ∈ [−0.04, +0.015], P(gate) < 10-15%."
        ),
    }


def write_preregistration(seeds: list[int], cv: str) -> Path:
    payload = make_prereg_payload(seeds, cv)
    formula_sha = _formula_sha256(payload)
    git_sha = _git_sha()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        **payload,
        "formula_sha256": formula_sha,
        "git_sha": git_sha,
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "created_at_local": datetime.now().isoformat(),
        "timestamp": ts,
        "lockbox_rules": [
            "Architecture FROZEN before any composite is computed.",
            "ONE pre-reg JSON per cv mode. --mode run requires --preregistration_file.",
            "5-fold gate: hybrid 5-fold CCC ≥ iter5 5-fold + 0.025 AND seed std < 0.020 across 3 seeds.",
            "LOOCV lockbox: paired bootstrap CI vs iter5 LOOCV on identical N=98 SIDs; 5000 resamples; "
            "canonical update requires frac>0 ≥ 95% AND ccc > 0.5227.",
            "Wide-margin Δ < 0 → skip LOOCV; F59 negative.",
            "If gate passes: run LOOCV separately with a NEW pre-reg JSON.",
        ],
    }
    pre_path = RESULTS_DIR / f"preregistration_t3_iter24_stage2forced_{ts}.json"
    if pre_path.exists():
        raise RuntimeError(f"Pre-reg path exists (timestamp clash): {pre_path}")
    with open(pre_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nPre-registration: {pre_path.name}", flush=True)
    print(f"  formula_sha256 = {formula_sha[:16]}...", flush=True)
    print(f"  git_sha = {git_sha[:12]}", flush=True)
    print(f"  cv = {cv}, seeds = {seeds}, forced_cols = {FORCED_EXTRA_COLS}", flush=True)
    return pre_path


def load_and_validate_prereg(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing pre-reg: {path}")
    with open(path) as f:
        pre = json.load(f)
    expected = make_prereg_payload(pre["seeds"], pre["cv"])
    expected_sha = _formula_sha256(expected)
    if pre["formula_sha256"] != expected_sha:
        raise RuntimeError(
            f"formula_sha256 mismatch: pre-reg={pre['formula_sha256'][:16]} vs current={expected_sha[:16]}. "
            "Architecture changed since pre-registration."
        )
    return pre


def paired_bootstrap_ci(y, pred_a, pred_b, n_boot: int = 5000, seed: int = 42) -> dict:
    n = len(y)
    rng = np.random.RandomState(seed)
    diffs = []
    for _ in range(n_boot):
        idx = rng.randint(0, n, size=n)
        diffs.append(float(ccc_fn(y[idx], pred_a[idx]) - ccc_fn(y[idx], pred_b[idx])))
    diffs = np.array(diffs)
    return {
        "ccc_a": float(ccc_fn(y, pred_a)),
        "ccc_b": float(ccc_fn(y, pred_b)),
        "delta_point": float(ccc_fn(y, pred_a) - ccc_fn(y, pred_b)),
        "delta_mean_boot": float(diffs.mean()),
        "delta_ci_low": float(np.percentile(diffs, 2.5)),
        "delta_ci_high": float(np.percentile(diffs, 97.5)),
        "frac_above_zero": float((diffs > 0).mean()),
        "n_boot": int(n_boot),
    }


def _worker_5fold(args: tuple) -> dict:
    seed, alpha = args
    t0 = time.time()
    sids, y, oof = stage2_residual_kfold_forced(seed=seed, alpha=alpha)
    elapsed = time.time() - t0
    return {
        "seed": seed,
        "ccc": float(ccc_fn(y, oof)),
        "mae": float(mae_fn(y, oof)),
        "r": float(pearson_r(y, oof)),
        "wall_time_s": round(elapsed, 1),
        "oof": oof.tolist(),
        "sids": sids.tolist(),
        "y": y.tolist(),
    }


def _worker_loocv(args: tuple) -> dict:
    seed, alpha = args
    t0 = time.time()
    sids, y, oof = stage2_residual_loocv_forced(seed=seed, alpha=alpha)
    elapsed = time.time() - t0
    return {
        "seed": seed,
        "ccc": float(ccc_fn(y, oof)),
        "mae": float(mae_fn(y, oof)),
        "r": float(pearson_r(y, oof)),
        "wall_time_s": round(elapsed, 1),
        "oof": oof.tolist(),
        "sids": sids.tolist(),
        "y": y.tolist(),
    }


def run_mode(prereg_path: Path, n_workers: int) -> None:
    pre = load_and_validate_prereg(prereg_path)
    cv = pre["cv"]
    seeds = list(pre["seeds"])
    ts = pre["timestamp"]
    alpha = pre["iter5_alpha"]
    print(f"\nLoaded pre-reg {prereg_path.name}", flush=True)
    print(f"  cv={cv}, seeds={seeds}, forced_cols={FORCED_EXTRA_COLS}", flush=True)
    print(f"  formula_sha256 = {pre['formula_sha256'][:16]}...", flush=True)
    _validate_manifest()
    print(f"  Manifest: clinical_extras leakage_status=clean_by_construction ✓", flush=True)

    jobs = [(seed, alpha) for seed in seeds]
    worker = _worker_5fold if cv == "5fold" else _worker_loocv

    print(f"\n=== Running {len(jobs)} (seed) jobs, n_workers={min(n_workers, len(jobs))} ===", flush=True)
    t0 = time.time()
    results = {}
    if n_workers <= 1 or len(jobs) <= 1:
        for j in jobs:
            r = worker(j)
            results[r["seed"]] = r
            print(f"  seed={r['seed']} CCC={r['ccc']:+.4f} MAE={r['mae']:.3f} ({r['wall_time_s']}s)", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=min(n_workers, len(jobs))) as ex:
            futs = {ex.submit(worker, j): j for j in jobs}
            for fut in as_completed(futs):
                r = fut.result()
                results[r["seed"]] = r
                print(f"  seed={r['seed']} CCC={r['ccc']:+.4f} MAE={r['mae']:.3f} ({r['wall_time_s']}s)", flush=True)
    total_elapsed = time.time() - t0
    print(f"\nTotal {cv} elapsed: {total_elapsed:.1f}s", flush=True)

    # Aggregate
    cccs = [results[s]["ccc"] for s in seeds]
    maes = [results[s]["mae"] for s in seeds]
    iter24_mean_oof = np.mean(np.stack([np.asarray(results[s]["oof"]) for s in seeds], axis=0), axis=0)
    y = np.asarray(results[seeds[0]]["y"])
    sids_iter24 = np.asarray(results[seeds[0]]["sids"])

    if cv == "5fold":
        # Reproduce iter5 5-fold for apples-to-apples (use existing helper).
        from run_t3_iter5_clinical import clinical_residual_kfold
        iter5_cccs = []
        iter5_oofs = []
        for seed in seeds:
            t1 = time.time()
            it5_oof = clinical_residual_kfold(seed=seed, feature_set=ITER5_FEATURE_SET, alpha=ITER5_ALPHA)
            iter5_oofs.append(it5_oof)
            iter5_cccs.append(float(ccc_fn(y, it5_oof)))
            print(f"  iter5 5-fold seed={seed} CCC={iter5_cccs[-1]:+.4f}  ({time.time()-t1:.1f}s)", flush=True)
        iter5_mean_oof = np.mean(np.stack(iter5_oofs, axis=0), axis=0)
        iter5_mean_ccc = float(np.mean(iter5_cccs))
        iter5_std = float(np.std(iter5_cccs))
        iter24_mean = float(np.mean(cccs))
        iter24_std = float(np.std(cccs))
        delta = iter24_mean - iter5_mean_ccc
        gate_delta = delta >= 0.025
        gate_std = iter24_std < 0.020
        gate_pass = gate_delta and gate_std

        print(f"\n=== iter24 5-fold GATE ===", flush=True)
        print(f"  iter24 5-fold CCC = {iter24_mean:+.4f} ± {iter24_std:.4f}  (per-seed: {[round(c,4) for c in cccs]})", flush=True)
        print(f"  iter5  5-fold CCC = {iter5_mean_ccc:+.4f} ± {iter5_std:.4f}  (per-seed: {[round(c,4) for c in iter5_cccs]})", flush=True)
        print(f"  Δ = {delta:+.4f}", flush=True)
        if delta < 0:
            verdict = "FAIL (Δ < 0; F59 negative)"
        elif 0 <= delta < 0.025:
            verdict = "BORDERLINE (Δ ∈ (0, +0.025); diagnostic only)"
        elif gate_pass:
            verdict = "PASS — proceed to LOOCV lockbox"
        else:
            verdict = f"STD-FAIL (Δ ≥ +0.025 but std={iter24_std:.4f} ≥ 0.020)"
        print(f"  GATE: {verdict}", flush=True)

        boot = paired_bootstrap_ci(y, iter24_mean_oof, iter5_mean_oof, n_boot=2000, seed=42)
        print(f"  Bootstrap (n=2000, 3-seed-mean): Δ={boot['delta_point']:+.4f}, "
              f"95% CI [{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}], "
              f"frac>0={boot['frac_above_zero']:.3f}", flush=True)

        out = {
            "mode": "5fold_gate", "preregistration": prereg_path.name, "ts": ts,
            "n_subjects": int(len(y)), "seeds": seeds,
            "iter24_ccc_mean": iter24_mean, "iter24_ccc_std": iter24_std, "iter24_per_seed_ccc": cccs,
            "iter5_ccc_mean": iter5_mean_ccc, "iter5_ccc_std": iter5_std, "iter5_per_seed_ccc": iter5_cccs,
            "delta": delta, "gate_pass": bool(gate_pass), "gate_message": verdict,
            "iter24_3seed_ccc": float(ccc_fn(y, iter24_mean_oof)),
            "iter5_3seed_ccc": float(ccc_fn(y, iter5_mean_oof)),
            "iter24_3seed_mae": float(mae_fn(y, iter24_mean_oof)),
            "iter5_3seed_mae": float(mae_fn(y, iter5_mean_oof)),
            "bootstrap": boot, "forced_extra_cols": FORCED_EXTRA_COLS,
            "total_elapsed_s": round(total_elapsed, 1),
        }
        out_path = RESULTS_DIR / f"iter24_5fold_gate_{ts}.json"
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2, default=float)
        np.save(RESULTS_DIR / f"iter24_5fold_gate_{ts}.iter24_oof.npy", iter24_mean_oof)
        np.save(RESULTS_DIR / f"iter24_5fold_gate_{ts}.iter5_oof.npy", iter5_mean_oof)
        np.save(RESULTS_DIR / f"iter24_5fold_gate_{ts}.sids.npy", sids_iter24)
        print(f"\nWrote {out_path.name}", flush=True)
        return

    if cv == "loocv":
        # Compare against canonical iter5 LOOCV OOF.
        canonical_iter5 = sorted(RESULTS_DIR.glob(ITER5_CANONICAL_LOCKBOX_OOF_GLOB))
        if not canonical_iter5:
            raise FileNotFoundError("Missing canonical iter5 LOOCV OOF .npy")
        iter5_oof_can = np.load(canonical_iter5[-1])
        canonical_json = canonical_iter5[-1].with_suffix("").with_suffix(".json")
        with open(canonical_json) as f:
            cj = json.load(f)
        sids_can = list(cj["per_subject"]["sids"])
        sids_now = list(sids_iter24)
        if sids_can != sids_now:
            sid_to_pred = dict(zip(sids_can, iter5_oof_can))
            iter5_oof_can = np.array([sid_to_pred[s] for s in sids_now])
        boot = paired_bootstrap_ci(y, iter24_mean_oof, iter5_oof_can, n_boot=5000, seed=42)
        canonical_update = (boot["frac_above_zero"] >= 0.95) and (boot["ccc_a"] > 0.5227)
        print(f"\n=== iter24 LOOCV LOCKBOX ===", flush=True)
        print(f"  iter24 LOOCV CCC (3-seed mean) = {boot['ccc_a']:+.4f}", flush=True)
        print(f"  iter5  LOOCV CCC (canonical)   = {boot['ccc_b']:+.4f}", flush=True)
        print(f"  Δ point = {boot['delta_point']:+.4f}", flush=True)
        print(f"  95% CI  = [{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}]", flush=True)
        print(f"  frac>0  = {boot['frac_above_zero']:.3f}", flush=True)
        print(f"  CANONICAL UPDATE: {'YES' if canonical_update else 'NO'}", flush=True)
        out = {
            "mode": "loocv_lockbox", "preregistration": prereg_path.name, "ts": ts,
            "n_subjects": int(len(y)), "seeds": seeds,
            "iter24_ccc_3seed": boot["ccc_a"], "iter5_ccc_canonical": boot["ccc_b"],
            "iter24_per_seed_ccc": cccs, "iter24_per_seed_mae": maes,
            "iter24_3seed_mae": float(mae_fn(y, iter24_mean_oof)),
            "bootstrap": boot, "is_canonical_update": bool(canonical_update),
            "forced_extra_cols": FORCED_EXTRA_COLS,
            "total_elapsed_s": round(total_elapsed, 1),
        }
        out_path = RESULTS_DIR / f"iter24_loocv_lockbox_{ts}.json"
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2, default=float)
        np.save(RESULTS_DIR / f"iter24_loocv_lockbox_{ts}.iter24_oof.npy", iter24_mean_oof)
        np.save(RESULTS_DIR / f"iter24_loocv_lockbox_{ts}.sids.npy", sids_iter24)
        print(f"\nWrote {out_path.name}", flush=True)
        return

    raise ValueError(f"unknown cv: {cv!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["write_prereg", "run"], required=True)
    ap.add_argument("--cv", choices=["5fold", "loocv"], default=None)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 1337, 7])
    ap.add_argument("--preregistration_file", type=str, default=None)
    ap.add_argument("--n_workers", type=int, default=int(os.getenv("ITER24_WORKERS", 3)))
    args = ap.parse_args()
    ensure_dir(RESULTS_DIR)
    if args.mode == "write_prereg":
        if args.cv is None:
            raise ValueError("--cv required for write_prereg")
        write_preregistration(seeds=list(args.seeds), cv=args.cv)
        return
    if args.mode == "run":
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required for run")
        prereg_path = Path(args.preregistration_file)
        if not prereg_path.is_absolute():
            prereg_path = (REPO_ROOT / args.preregistration_file).resolve()
        run_mode(prereg_path, n_workers=args.n_workers)
        return


if __name__ == "__main__":
    main()

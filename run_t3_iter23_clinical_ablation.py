"""T3 iter23 — Clinical-extras ablation runner over the iter5 architecture.

iter5 canonical (LOOCV CCC=0.5227): Stage-1 Ridge on H&Y(6) + cv_yrs/sex/dbs;
Stage-2 LGB on V2 residual with per-fold K=500 feature selection. iter23 tests
whether ADDITIONAL intake clinical covariates from results/clinical_extras.csv
(parallel-built) lift Stage-1.

Stage-1 per fold: FoldImputer (median, extras-only NaNs) → FoldNormalizer →
Ridge(α=1.0). Stage-2: BIT-IDENTICAL to iter5 (impute_fold + feature_select_fold
K=500 + train_lgb).

Modes:
  --mode ablate_5fold          : ProcessPool over (set, seed); writes CSV + gate verdict.
  --mode write_prereg --feature_set <name> : writes pre-reg JSON with formula_sha256.
  --mode lockbox --preregistration_file <path> : validates SHA, runs LOOCV 3-seed mean,
                                paired-bootstrap vs iter5 lockbox OOF; writes JSON+oof+sids.

Leakage rules: FoldImputer/FoldNormalizer fold-local; K=500 inside CV; refuses to start
if manifest reports labels_used=True or leakage_status != clean_by_construction.
"""
from __future__ import annotations

import os
# Default LGB threads to 1 so we can saturate cores via ProcessPoolExecutor without
# thread oversubscription. Set PD_IMU_N_CORES explicitly to override.
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
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold, LeaveOneOut

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import (
    FoldImputer,
    FoldNormalizer,
    ccc as ccc_fn,
    full_metrics,
    mae as mae_fn,
    pearson_r,
)
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter5_clinical import (
    CLINICAL_COLS_BINARY,
    CLINICAL_COLS_CONTINUOUS,
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features as iter5_build_s1,
    clinical_residual_kfold,
    fit_stage1,
    load_clinical_dict,
)
from run_t3_iter3 import get_hy_features, load_full_pd_data
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb

ensure_dir(RESULTS_DIR)

CLINICAL_EXTRAS_CSV = RESULTS_DIR / "clinical_extras.csv"
CLINICAL_EXTRAS_MANIFEST = RESULTS_DIR / "clinical_extras.csv.manifest.json"
ITER5_LOCKBOX_GLOB = "lockbox_t3_iter5_A3_tier1_*.json"

# Ablation knobs (Stage-2 untouched — bit-identical to iter5)
ITER5_BASELINE_EXTRAS: list[str] = ITER5_FEATURE_SETS["A3_tier1"]  # cv_yrs, cv_sex, cv_dbs
ITER5_ALPHA_DEFAULT = 1.0
LGB_FEATURE_K = 500
PUBLISHED_ITER5_LOOCV_CCC = 0.5227

# Schema of clinical_extras.csv (parallel agent ensures these exist).
CLINICAL_EXTRAS_SCHEMA: list[str] = [
    "ledd_total",
    "ledd_levodopa",
    "ledd_dopamine_agonist",
    "ledd_other",
    "ledd_on_levodopa",
    "ledd_on_agonist",
    "hours_since_last_dose",
    "assistive_device_yn",
    "pt_ot_status_yn",
    "race_white",
    "days_since_part3",
    "part1_sum",
    "part1_cognitive",
    "part1_hallucinations",
    "part1_sleep",
    "part1_daytime_sleepiness",
]


# Ablation sets (each list = clinical extras ADDED on top of iter5 A3_tier1 baseline)
ABLATION_SETS: dict[str, list[str]] = {
    # Baseline reproductions
    "B0_iter5_canonical":           [],
    "B0_check_no_extras":           [],   # sanity duplicate

    # Single-signal lifts over iter5 A3_tier1
    "B1_plus_ledd_total":           ["ledd_total"],
    "B2_plus_ledd_split":           ["ledd_levodopa", "ledd_dopamine_agonist"],
    "B3_plus_ledd_other":           ["ledd_other"],
    "B4_plus_part1_sum":            ["part1_sum"],
    "B5_plus_part1_cognitive":      ["part1_cognitive"],
    "B6_plus_part1_hallucinations": ["part1_hallucinations"],
    "B7_plus_onoff":                ["hours_since_last_dose"],
    "B8_plus_assistive":            ["assistive_device_yn"],
    "B9_plus_ptot":                 ["pt_ot_status_yn"],
    "B10_plus_race":                ["race_white"],
    "B11_plus_days_p3":             ["days_since_part3"],

    # Pairs (most-promising signals together)
    "C1_ledd_plus_part1":           ["ledd_total", "part1_sum"],
    "C2_ledd_plus_onoff":           ["ledd_total", "hours_since_last_dose"],
    "C3_part1_plus_onoff":          ["part1_sum", "hours_since_last_dose"],
    "C4_ledd_plus_assistive":       ["ledd_total", "assistive_device_yn"],

    # Kitchen-sink (all promising)
    "D1_ledd_part1_onoff":          ["ledd_total", "part1_sum", "hours_since_last_dose"],
    "D2_ledd_part1_onoff_assist":   ["ledd_total", "part1_sum", "hours_since_last_dose",
                                     "assistive_device_yn"],
}


# ── manifest validation ──────────────────────────────────────────────────────


def _validate_manifest() -> dict:
    """Refuse to start if cache or manifest is missing/unsafe."""
    if not CLINICAL_EXTRAS_CSV.exists():
        raise FileNotFoundError(
            f"Missing clinical extras cache: {CLINICAL_EXTRAS_CSV}. The parallel agent must "
            "build this via cache_clinical_extras.py before iter23 can run."
        )
    if not CLINICAL_EXTRAS_MANIFEST.exists():
        raise FileNotFoundError(
            f"Missing clinical extras manifest: {CLINICAL_EXTRAS_MANIFEST}. "
            "Cannot verify leakage status; refusing to compute."
        )
    with open(CLINICAL_EXTRAS_MANIFEST) as f:
        mani = json.load(f)
    if mani.get("labels_used", True):
        raise RuntimeError(
            f"Manifest reports labels_used=True; clinical extras may be derived from UPDRS-III "
            f"ratings. Refusing to use as Stage-1 covariates. Manifest: {CLINICAL_EXTRAS_MANIFEST}"
        )
    if mani.get("leakage_status") != "clean_by_construction":
        raise RuntimeError(
            f"Manifest leakage_status={mani.get('leakage_status')!r}, expected "
            f"'clean_by_construction'. Refusing. Manifest: {CLINICAL_EXTRAS_MANIFEST}"
        )
    return mani


def _manifest_sha256() -> str:
    """Hash of manifest content (locked into pre-reg formula_sha256 for tamper detection)."""
    if not CLINICAL_EXTRAS_MANIFEST.exists():
        return "missing_manifest"
    with open(CLINICAL_EXTRAS_MANIFEST, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ── extras loader ────────────────────────────────────────────────────────────


def load_clinical_extras(sids: np.ndarray) -> dict[str, np.ndarray]:
    """Return {col: array(n)} aligned to ``sids`` (NaN where SID missing).

    Validates the manifest before reading; raises if labels_used or wrong leakage_status.
    """
    _validate_manifest()
    df = pd.read_csv(CLINICAL_EXTRAS_CSV)
    if "sid" not in df.columns:
        raise ValueError(f"{CLINICAL_EXTRAS_CSV} missing required 'sid' column")
    df = df.set_index("sid")
    out: dict[str, np.ndarray] = {}
    for col in CLINICAL_EXTRAS_SCHEMA:
        if col not in df.columns:
            raise KeyError(
                f"Required clinical extras column missing: {col!r}. "
                f"Cache schema: {sorted(df.columns)}"
            )
        vals = np.full(len(sids), np.nan, dtype=np.float64)
        for i, sid in enumerate(sids):
            if sid in df.index:
                v = df.loc[sid, col]
                # Pandas may return Series for duplicated indices — flag explicitly
                if isinstance(v, pd.Series):
                    raise ValueError(
                        f"Duplicate SID {sid!r} in {CLINICAL_EXTRAS_CSV}; cache must be unique by sid"
                    )
                vals[i] = float(v) if pd.notna(v) else np.nan
        out[col] = vals
    return out


# ── Stage-1 feature builder ──────────────────────────────────────────────────


def build_stage1_features_extended(
    hy_arr: np.ndarray,
    clinical_iter5: dict[str, np.ndarray],
    clinical_extras: dict[str, np.ndarray],
    extra_cols: Sequence[str],
) -> tuple[np.ndarray, list[str]]:
    """Stage-1 X matrix: H&Y(6) + iter5 A3_tier1 covariates(3) + extra clinical extras.

    Output shape: (N, 9 + len(extra_cols)). May contain NaN in the extras tail; the
    per-fold imputer in clinical_residual_kfold_v2 handles those.
    """
    hy_feat = get_hy_features(hy_arr)  # (N, 6)
    parts: list[np.ndarray] = [hy_feat]
    names: list[str] = [f"hy_{i}" for i in range(hy_feat.shape[1])]
    # Always-included iter5 baseline extras (no NaN expected)
    for col in ITER5_BASELINE_EXTRAS:
        if col not in clinical_iter5:
            raise KeyError(f"iter5 clinical column {col!r} missing")
        parts.append(clinical_iter5[col].reshape(-1, 1))
        names.append(col)
    # Iter23 ablation extras (may contain NaN)
    for col in extra_cols:
        if col not in clinical_extras:
            raise KeyError(f"clinical_extras column {col!r} missing")
        parts.append(clinical_extras[col].reshape(-1, 1))
        names.append(col)
    X = np.column_stack(parts)
    return X, names


# ── per-fold helpers ─────────────────────────────────────────────────────────


def _fit_stage1_with_imputation(
    X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray, alpha: float = 1.0
) -> tuple[np.ndarray, np.ndarray]:
    """Fold-local: median-impute NaN columns (extras tail) on TRAIN, transform train+test,
    standardize all cols, fit Ridge. NEVER fits on test data.

    The HY+A3_tier1 cols (first 9) have no NaN; the imputer is a no-op on those columns.
    """
    imp = FoldImputer.fit(X_tr)
    Xtr_i = imp.transform(X_tr)
    Xte_i = imp.transform(X_te)
    return fit_stage1(Xtr_i, y_tr, Xte_i, alpha=alpha)


def clinical_residual_kfold_v2(
    seed: int, extra_cols: Sequence[str], alpha: float = ITER5_ALPHA_DEFAULT
) -> np.ndarray:
    """5-fold variant of iter5 hy_residual with iter23 Stage-1 extras on top of A3_tier1.
    Returns OOF preds aligned to load_full_pd_data() sid order.
    """
    sids, X, _, y_t3, hy, _ = load_full_pd_data()
    n = len(sids)
    clinical_iter5 = load_clinical_dict(sids)
    clinical_extras = load_clinical_extras(sids) if extra_cols else {c: np.zeros(n) for c in []}
    X_s1, _ = build_stage1_features_extended(hy, clinical_iter5, clinical_extras, extra_cols)
    preds = np.zeros(n)
    splits = list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))
    for tr, te in splits:
        s1_tr, s1_te = _fit_stage1_with_imputation(X_s1[tr], y_t3[tr], X_s1[te], alpha=alpha)
        residual_tr = y_t3[tr] - s1_tr
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=LGB_FEATURE_K, seed=seed)
        s2_te = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        preds[te] = s1_te + s2_te
    return preds


def clinical_residual_loocv_v2(
    seed: int, extra_cols: Sequence[str], alpha: float = ITER5_ALPHA_DEFAULT
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """LOOCV variant. Returns (sids, y_t3, preds)."""
    sids, X, _, y_t3, hy, _ = load_full_pd_data()
    n = len(sids)
    clinical_iter5 = load_clinical_dict(sids)
    clinical_extras = load_clinical_extras(sids) if extra_cols else {c: np.zeros(n) for c in []}
    X_s1, _ = build_stage1_features_extended(hy, clinical_iter5, clinical_extras, extra_cols)
    preds = np.zeros(n)
    loo = LeaveOneOut()
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(loo.split(np.arange(n))):
        s1_tr, s1_te = _fit_stage1_with_imputation(X_s1[tr], y_t3[tr], X_s1[te], alpha=alpha)
        residual_tr = y_t3[tr] - s1_tr
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=LGB_FEATURE_K, seed=seed)
        s2_te = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        preds[te] = s1_te + s2_te
        if (fold_idx + 1) % 10 == 0:
            print(
                f"  [seed={seed}] fold {fold_idx + 1}/{n}, elapsed {time.time() - t0:.1f}s",
                flush=True,
            )
    return sids, y_t3, preds


# ── ProcessPool worker (top-level for picklability) ──────────────────────────


def _worker_5fold(args: tuple) -> dict:
    feature_set_name, extra_cols, seed, alpha = args
    t0 = time.time()
    preds = clinical_residual_kfold_v2(seed=seed, extra_cols=list(extra_cols), alpha=alpha)
    sids, _, _, y_t3, _, _ = load_full_pd_data()
    elapsed = time.time() - t0
    return {
        "feature_set": feature_set_name,
        "extras": "+".join(extra_cols) if extra_cols else "(no extras)",
        "n_extras": len(extra_cols),
        "seed": seed,
        "ccc": float(ccc_fn(y_t3, preds)),
        "mae": float(mae_fn(y_t3, preds)),
        "r": float(pearson_r(y_t3, preds)),
        "wall_time_s": round(elapsed, 1),
    }


# ── ablate_5fold mode ────────────────────────────────────────────────────────


def run_ablate_5fold(
    seeds: Sequence[int], n_workers: int, alpha: float = ITER5_ALPHA_DEFAULT
) -> pd.DataFrame:
    _validate_manifest()  # fail-fast before spawning workers
    print(
        f"\n=== T3 iter23 5-FOLD ABLATION (alpha={alpha}, {len(seeds)} seeds × "
        f"{len(ABLATION_SETS)} feature sets, n_workers={n_workers}) ===",
        flush=True,
    )
    print(f"Iter5 A3_tier1 LOOCV baseline = {PUBLISHED_ITER5_LOOCV_CCC} (apples-to-apples 5-fold ≈ same).",
          flush=True)
    jobs: list[tuple] = []
    for fs_name, extra_cols in ABLATION_SETS.items():
        for seed in seeds:
            jobs.append((fs_name, tuple(extra_cols), seed, alpha))
    print(f"Total jobs: {len(jobs)}", flush=True)

    rows: list[dict] = []
    t_start = time.time()
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        future_to_job = {pool.submit(_worker_5fold, j): j for j in jobs}
        completed = 0
        for fut in as_completed(future_to_job):
            job = future_to_job[fut]
            try:
                row = fut.result()
            except Exception as exc:
                print(f"  FAILED {job}: {exc}", flush=True)
                raise
            rows.append(row)
            completed += 1
            print(
                f"  [{completed:>3}/{len(jobs)}] {row['feature_set']:32s} seed={row['seed']:>4}  "
                f"CCC={row['ccc']:+.4f}  MAE={row['mae']:.3f}  r={row['r']:+.4f}  "
                f"({row['wall_time_s']:.1f}s)",
                flush=True,
            )
    total_wall = time.time() - t_start
    print(f"\nAll jobs done in {total_wall:.1f}s wall.", flush=True)

    df = pd.DataFrame(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = RESULTS_DIR / f"iter23_clinical_ablation_5fold_{ts}.csv"
    df.to_csv(out_csv, index=False)
    print(f"Wrote {out_csv}", flush=True)

    # Summary: per-set mean ± std, sorted descending by mean CCC
    grp = df.groupby("feature_set")["ccc"].agg(["mean", "std", "count"]).sort_values(
        "mean", ascending=False
    )
    baseline_mean = float(grp.loc["B0_iter5_canonical", "mean"]) if "B0_iter5_canonical" in grp.index else float("nan")

    print("\n=== Per-set 5-fold CCC summary (sorted by mean, descending) ===", flush=True)
    print(f"  Baseline (B0_iter5_canonical) mean = {baseline_mean:.4f}", flush=True)
    print(f"  {'feature_set':32s}  {'mean':>8}  {'std':>8}  {'Δ_vs_B0':>9}  {'gate':>6}", flush=True)
    print(f"  {'-' * 32}  {'-' * 8}  {'-' * 8}  {'-' * 9}  {'-' * 6}", flush=True)
    for fs, row in grp.iterrows():
        delta = float(row["mean"]) - baseline_mean
        std = float(row["std"]) if row["count"] > 1 else float("nan")
        gate_pass = (delta >= 0.025) and (std < 0.020)
        gate_tag = "PASS" if gate_pass else "----"
        print(
            f"  {fs:32s}  {row['mean']:+.4f}  {std:.4f}  {delta:+.4f}    {gate_tag}",
            flush=True,
        )

    # Gate verdict
    passers = []
    for fs, row in grp.iterrows():
        if fs == "B0_iter5_canonical":
            continue
        delta = float(row["mean"]) - baseline_mean
        std = float(row["std"]) if row["count"] > 1 else float("inf")
        if delta >= 0.025 and std < 0.020:
            passers.append((fs, delta, std))
    print("\n=== Gate verdict (5-fold Δ ≥ +0.025 AND seed std < 0.020) ===", flush=True)
    if passers:
        print(f"  {len(passers)} set(s) pass:", flush=True)
        for fs, delta, std in passers:
            print(f"    {fs}: Δ={delta:+.4f}, std={std:.4f}", flush=True)
    else:
        print("  No set passes the strict 5-fold gate. iter5 A3_tier1 stays canonical.", flush=True)

    return df


# ── pre-registration discipline ──────────────────────────────────────────────


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT
        ).decode().strip()
    except Exception:
        return "unknown"


def _formula_sha256(payload: dict) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canon).hexdigest()


def _make_prereg_payload(feature_set: str, alpha: float, seeds: Sequence[int]) -> dict:
    if feature_set not in ABLATION_SETS:
        raise ValueError(f"Unknown feature_set {feature_set!r}; choose from {list(ABLATION_SETS)}")
    extras = list(ABLATION_SETS[feature_set])
    return {
        "experiment": "T3 iter23 — Clinical-extras ablation (Stage-1 widening over iter5 A3_tier1)",
        "feature_set": feature_set,
        "stage1_iter5_baseline_extras": list(ITER5_BASELINE_EXTRAS),
        "stage1_iter23_extras": extras,
        "stage1_total_features": 9 + len(extras),  # 6 H&Y + 3 A3_tier1 + iter23 extras
        "iter5_alpha": float(alpha),
        "meta_alpha": "N/A (no meta-learner; Stage-1 Ridge → Stage-2 LGB residual)",
        "lgb_feature_K": LGB_FEATURE_K,
        "stage2_pipeline": "impute_fold + feature_select_fold(K=500) + train_lgb (bit-identical to iter5)",
        "n_subjects": 98,
        "endpoint": "updrs3 (T3 canonical)",
        "seeds": list(seeds),
        "clinical_extras_manifest_sha256": _manifest_sha256(),
        "5null_inheritance": (
            "iter5 base (Stage-1 H&Y+A3_tier1, Stage-2 LGB on V2 residual) is pre-registered "
            "and canonical. iter23 extends Stage-1 only with intake clinical covariates whose "
            "manifest is verified labels_used=False / leakage_status=clean_by_construction."
        ),
        "covariate_safety_argument": (
            "All Stage-1 extras are intake / pre-session clinical covariates (LEDD breakdown, "
            "PD Part-1 sums, hours_since_last_dose, assistive_device_yn, pt_ot_status_yn, "
            "race_white, days_since_part3). None derived from the rated UPDRS-III; cache "
            "manifest enforced clean_by_construction at load time."
        ),
    }


def _write_preregistration(feature_set: str, alpha: float, seeds: Sequence[int]) -> Path:
    _validate_manifest()
    payload = _make_prereg_payload(feature_set, alpha, seeds)
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
            "Stage-1 extras list, alpha=1.0, K=500 LGB feature select, and bit-identical iter5 "
            "Stage-2 pipeline are LOCKED before any LOOCV CCC is computed.",
            "ONE pre-reg JSON per (feature_set) execution. --mode lockbox requires --preregistration_file.",
            "Apples-to-apples comparator: iter5 A3_tier1 lockbox OOF (CCC=0.5227) on identical N=98.",
            "Canonical update requires paired-bootstrap frac_above_zero ≥ 0.95 AND ccc > 0.5227.",
            "If gate fails: report as null result; iter5 A3_tier1 stays canonical.",
            "Manifest SHA is locked into formula_sha256 — any change to clinical_extras.csv "
            "(rebuild, schema change) invalidates this pre-reg by construction.",
        ],
    }
    pre_path = RESULTS_DIR / f"preregistration_t3_iter23_{feature_set}_{ts}.json"
    if pre_path.exists():
        raise RuntimeError(f"Pre-reg path already exists (timestamp clash): {pre_path}")
    with open(pre_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nPre-registration written: {pre_path}", flush=True)
    print(f"  formula_sha256 = {formula_sha[:16]}...", flush=True)
    print(f"  git_sha        = {git_sha[:12]}", flush=True)
    print(f"  feature_set    = {feature_set}, extras = {ABLATION_SETS[feature_set]}", flush=True)
    print(f"  alpha          = {alpha}, seeds = {list(seeds)}", flush=True)
    print(f"\nNext: --mode lockbox --preregistration_file={pre_path}", flush=True)
    return pre_path


def _load_and_validate_prereg(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing pre-registration: {path}")
    with open(path) as f:
        pre = json.load(f)
    expected = _make_prereg_payload(pre["feature_set"], pre["iter5_alpha"], pre["seeds"])
    expected_sha = _formula_sha256(expected)
    if pre["formula_sha256"] != expected_sha:
        raise RuntimeError(
            f"Pre-reg formula_sha256 mismatch: stored={pre['formula_sha256'][:16]}... "
            f"expected={expected_sha[:16]}... — code, schema, or manifest changed since pre-reg."
        )
    return pre


# ── lockbox LOOCV ────────────────────────────────────────────────────────────


def _find_iter5_comparator() -> Path:
    """Latest iter5 A3_tier1 lockbox JSON in RESULTS_DIR."""
    candidates = sorted(RESULTS_DIR.glob(ITER5_LOCKBOX_GLOB))
    if not candidates:
        raise FileNotFoundError(
            f"No iter5 A3_tier1 lockbox JSON found matching {ITER5_LOCKBOX_GLOB} in {RESULTS_DIR}"
        )
    return candidates[-1]


def _load_iter5_comparator(sids_ref: np.ndarray) -> tuple[np.ndarray, str]:
    """Load iter5 A3_tier1 lockbox OOF aligned to sids_ref. Verifies sid alignment."""
    path = _find_iter5_comparator()
    with open(path) as f:
        d = json.load(f)
    if d.get("feature_set") != "A3_tier1":
        raise RuntimeError(f"Comparator {path} is not A3_tier1 (got {d.get('feature_set')})")
    if d.get("eval_mode") not in ("loocv_3seed_mean", "loocv"):
        raise RuntimeError(f"Comparator {path} eval_mode={d.get('eval_mode')!r} — expected LOOCV")
    iter5_sids = d["per_subject"]["sids"]
    iter5_preds = d["per_subject"]["y_pred"]
    sid_to_pred = dict(zip(iter5_sids, iter5_preds))
    missing = [s for s in sids_ref if s not in sid_to_pred]
    if missing:
        raise RuntimeError(f"Comparator missing {len(missing)} SIDs: {missing[:5]}...")
    aligned = np.array([sid_to_pred[s] for s in sids_ref], dtype=np.float64)
    return aligned, str(path.name)


def _paired_bootstrap_delta(
    y_true: np.ndarray, y_iter23: np.ndarray, y_iter5: np.ndarray, n_boot: int = 5000, seed: int = 42
) -> dict:
    rng = np.random.RandomState(seed)
    deltas = np.zeros(n_boot)
    n = len(y_true)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        deltas[b] = ccc_fn(y_true[idx], y_iter23[idx]) - ccc_fn(y_true[idx], y_iter5[idx])
    return {
        "n_boot": n_boot,
        "delta_mean": round(float(deltas.mean()), 4),
        "delta_ci_low": round(float(np.percentile(deltas, 2.5)), 4),
        "delta_ci_high": round(float(np.percentile(deltas, 97.5)), 4),
        "frac_above_zero": round(float((deltas > 0).mean()), 3),
        "frac_above_0p01": round(float((deltas > 0.01).mean()), 3),
    }


def run_lockbox(prereg_path: Path) -> dict:
    pre = _load_and_validate_prereg(prereg_path)
    feature_set = pre["feature_set"]
    extras = ABLATION_SETS[feature_set]
    alpha = float(pre["iter5_alpha"])
    seeds = list(pre["seeds"])
    print(
        f"\n=== T3 iter23 LOCKBOX LOOCV ===\n"
        f"  feature_set   = {feature_set}\n"
        f"  extras        = {extras}\n"
        f"  alpha         = {alpha}, seeds = {seeds}\n"
        f"  pre-reg path  = {prereg_path}\n"
        f"  formula_sha256 = {pre['formula_sha256'][:16]}...",
        flush=True,
    )

    all_preds: list[tuple[int, np.ndarray]] = []
    sids_ref: np.ndarray | None = None
    y_t3_ref: np.ndarray | None = None
    for seed in seeds:
        t0 = time.time()
        sids, y_t3, preds = clinical_residual_loocv_v2(seed=seed, extra_cols=extras, alpha=alpha)
        elapsed = time.time() - t0
        c = ccc_fn(y_t3, preds)
        m = mae_fn(y_t3, preds)
        r = pearson_r(y_t3, preds)
        print(f"  seed {seed}: CCC={c:+.4f}, MAE={m:.3f}, r={r:+.4f}, time={elapsed:.1f}s", flush=True)
        all_preds.append((seed, preds))
        sids_ref = sids
        y_t3_ref = y_t3
    assert sids_ref is not None and y_t3_ref is not None

    mean_preds = np.mean(np.column_stack([p for _, p in all_preds]), axis=1)
    headline = full_metrics(y_t3_ref, mean_preds, label=f"t3_iter23_{feature_set}")

    # Comparator: iter5 A3_tier1 lockbox OOF on same N=98 SIDs
    iter5_aligned, comparator_name = _load_iter5_comparator(sids_ref)
    iter5_ccc_on_ref = float(ccc_fn(y_t3_ref, iter5_aligned))
    boot = _paired_bootstrap_delta(y_t3_ref, mean_preds, iter5_aligned, n_boot=5000, seed=42)

    canonical_update = bool(boot["frac_above_zero"] >= 0.95 and headline["ccc"] > PUBLISHED_ITER5_LOOCV_CCC)

    headline.update(
        {
            "feature_set": feature_set,
            "stage1_iter23_extras": list(extras),
            "alpha": alpha,
            "eval_mode": "loocv_3seed_mean",
            "n_seeds": len(seeds),
            "per_seed_ccc": [float(ccc_fn(y_t3_ref, p)) for _, p in all_preds],
            "per_seed_mae": [float(mae_fn(y_t3_ref, p)) for _, p in all_preds],
            "per_subject": {
                "sids": [str(s) for s in sids_ref.tolist()],
                "y_true": y_t3_ref.tolist(),
                "y_pred": mean_preds.tolist(),
            },
            "preregistration_file": prereg_path.name,
            "is_lockbox_headline": True,
            "comparator_file": comparator_name,
            "comparator_iter5_ccc_on_same_N98": round(iter5_ccc_on_ref, 4),
            "delta_vs_iter5": round(float(headline["ccc"]) - iter5_ccc_on_ref, 4),
            "bootstrap_delta_vs_iter5": boot,
            "canonical_update_flag": canonical_update,
        }
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"iter23_lockbox_{feature_set}_{ts}.json"
    out_oof = RESULTS_DIR / f"iter23_lockbox_{feature_set}_{ts}.oof.npy"
    out_sids = RESULTS_DIR / f"iter23_lockbox_{feature_set}_{ts}.sids.npy"
    np.save(out_oof, mean_preds)
    np.save(out_sids, np.asarray([str(s) for s in sids_ref], dtype=object))
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)

    print(
        f"\n=== HEADLINE: CCC={headline['ccc']:+.4f}, MAE={headline['mae']:.3f}, "
        f"r={headline['r']:+.4f}, slope={headline['cal_slope']:.3f} ===",
        flush=True,
    )
    print(f"  Δ vs iter5 (same N=98): {headline['delta_vs_iter5']:+.4f}", flush=True)
    print(
        f"  Bootstrap (n={boot['n_boot']}): mean Δ={boot['delta_mean']:+.4f}, "
        f"95% CI=[{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}], "
        f"frac > 0 = {boot['frac_above_zero']}, frac > 0.01 = {boot['frac_above_0p01']}",
        flush=True,
    )
    print(f"  Canonical update flag: {canonical_update}", flush=True)
    print(f"\nWrote {out_json}\nWrote {out_oof}\nWrote {out_sids}", flush=True)
    return headline


# ── CLI dispatch ─────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description="T3 iter23 — clinical extras ablation runner")
    ap.add_argument("--mode", choices=["ablate_5fold", "write_prereg", "lockbox"], required=True)
    ap.add_argument("--feature_set", default=None,
                    help="(write_prereg/lockbox) name from ABLATION_SETS")
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 1337, 7])
    ap.add_argument("--n_workers", type=int, default=int(os.getenv("ITER23_WORKERS", 11)))
    ap.add_argument("--preregistration_file", type=str, default=None)
    ap.add_argument("--alpha", type=float, default=ITER5_ALPHA_DEFAULT)
    args = ap.parse_args()

    if args.mode == "ablate_5fold":
        run_ablate_5fold(seeds=tuple(args.seeds), n_workers=args.n_workers, alpha=args.alpha)
        return

    if args.mode == "write_prereg":
        if not args.feature_set:
            raise SystemExit("--feature_set required for --mode write_prereg")
        if args.feature_set not in ABLATION_SETS:
            raise SystemExit(
                f"Unknown feature_set {args.feature_set!r}; choose from {list(ABLATION_SETS)}"
            )
        _write_preregistration(args.feature_set, args.alpha, tuple(args.seeds))
        return

    if args.mode == "lockbox":
        if not args.preregistration_file:
            raise SystemExit("--preregistration_file required for --mode lockbox")
        run_lockbox(Path(args.preregistration_file))
        return


if __name__ == "__main__":
    main()

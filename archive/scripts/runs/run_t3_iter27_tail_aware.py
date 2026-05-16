"""T3 iter27 — Tail-aware Stage-2 modifications for hy_residual + clinical.

iter5 architecture is frozen except inside Stage 2:
  - sample_weight passed to LGB (5 schemes; default quartile_balanced)
  - severity-stratified KFold for inner CV (qcut bins of TRAIN y)
  - optional custom CCC objective (off by default, per F50 methodology)

Motivation (F54): iter5 LOOCV residuals corr(residual, y_true)=-0.699;
Q1 +9.4, Q4 -7.6. iter25b post-hoc calibration FAILED at this N — must
attack tail shrinkage during training.

Modes:
  --mode screen                       5 schemes x 3 seeds, stratified 5-fold
  --mode write_prereg --weight_scheme NAME
  --mode lockbox --preregistration_file PATH    LOOCV + paired bootstrap vs iter5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

os.environ.setdefault("PD_IMU_N_CORES", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde
from sklearn.model_selection import LeaveOneOut, StratifiedKFold

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import (  # noqa: E402
    ccc as ccc_fn, full_metrics, mae as mae_fn, pearson_r,
)
from project_paths import RESULTS_DIR, ensure_dir  # noqa: E402
from run_t3_iter3 import load_full_pd_data  # noqa: E402
from run_t3_iter5_clinical import (  # noqa: E402
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features, fit_stage1, load_clinical_dict,
)
from run_t3_iter2 import feature_select_fold, impute_fold  # noqa: E402

ensure_dir(RESULTS_DIR)
ITER5_CANONICAL_CCC: float = 0.5227
ITER5_LOCKBOX_GLOB: str = "lockbox_t3_iter5_A3_tier1_*.json"


# ── Sample-weight schemes ────────────────────────────────────────────────────


def _w_uniform(y: np.ndarray) -> np.ndarray:
    return np.ones_like(y, dtype=np.float64)


def _w_inv_density(y: np.ndarray) -> np.ndarray:
    arr = np.asarray(y, dtype=np.float64)
    if arr.std() < 1e-9 or len(arr) < 5:
        return np.ones_like(arr)
    p = gaussian_kde(arr, bw_method="scott")(arr)
    w = np.clip(1.0 / (p + 1e-3), 0.5, 5.0)
    return w / w.mean()


def _w_abs_z(y: np.ndarray) -> np.ndarray:
    arr = np.asarray(y, dtype=np.float64)
    s = arr.std()
    if s < 1e-9:
        return np.ones_like(arr)
    w = 1.0 + np.abs(arr - arr.mean()) / s
    return w / w.mean()


def _w_tail_focused(y: np.ndarray) -> np.ndarray:
    arr = np.asarray(y, dtype=np.float64)
    s = arr.std()
    if s < 1e-9:
        return np.ones_like(arr)
    z = (arr - arr.mean()) / s
    w = 1.0 + z * z
    return w / w.mean()


def _w_quartile_balanced(y: np.ndarray) -> np.ndarray:
    arr = np.asarray(y, dtype=np.float64)
    if arr.std() < 1e-9:
        return np.ones_like(arr)
    try:
        bins = pd.qcut(arr, q=4, labels=False, duplicates="drop")
    except ValueError:
        return np.ones_like(arr)
    bins = np.asarray(bins, dtype=np.int64)
    w = np.zeros_like(arr)
    for b in np.unique(bins):
        mask = bins == b
        n_b = int(mask.sum())
        if n_b > 0:
            w[mask] = 1.0 / n_b
    return w * (len(arr) / w.sum()) if w.sum() > 0 else np.ones_like(arr)


WEIGHT_SCHEMES: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "uniform": _w_uniform,
    "inv_density": _w_inv_density,
    "abs_z": _w_abs_z,
    "tail_focused": _w_tail_focused,
    "quartile_balanced": _w_quartile_balanced,
}


# ── Stage-2 LGB ──────────────────────────────────────────────────────────────


def _lgb_params(seed: int) -> dict:
    """iter5 hyperparams except n_jobs=1 (workers handle parallelism)."""
    return dict(
        n_estimators=500, learning_rate=0.05, num_leaves=15, max_depth=-1,
        min_data_in_leaf=10, reg_alpha=0.1, reg_lambda=0.3,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5,
        n_jobs=1, random_state=seed, verbosity=-1,
    )


def _ccc_grad_hess(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """CCC custom objective; hessian=1.0 (per F50)."""
    yt, yp = y_true.astype(np.float64), y_pred.astype(np.float64)
    n = len(yt)
    if n < 2 or yt.std() < 1e-9 or yp.std() < 1e-9:
        return (yp - yt), np.ones_like(yp)
    mu_t, mu_p = yt.mean(), yp.mean()
    denom = max(yt.var() + yp.var() + (mu_t - mu_p) ** 2, 1e-9)
    grad = -2.0 / n * (yt - mu_t) / denom
    hess = np.ones_like(yp)
    return grad, hess


def _train_stage2_lgb(
    X_tr: np.ndarray, residual_tr: np.ndarray, X_te: np.ndarray,
    sample_weight: np.ndarray, seed: int, enable_ccc: bool,
) -> np.ndarray:
    import lightgbm as lgb

    params = _lgb_params(seed)
    if enable_ccc:
        # CCC objective + init_score + post-hoc affine calibration on TRAIN fold
        init_val = float(np.mean(residual_tr))
        params_ccc = {**params, "objective": _ccc_grad_hess}
        model = lgb.LGBMRegressor(**params_ccc)
        init_train = np.full_like(residual_tr, init_val, dtype=np.float64)
        model.fit(X_tr, residual_tr, sample_weight=sample_weight, init_score=init_train)
        s2_te = model.predict(X_te, raw_score=True) + init_val
        s2_tr = model.predict(X_tr, raw_score=True) + init_val
        if s2_tr.std() > 1e-9:
            slope, intercept = np.polyfit(s2_tr, residual_tr, 1)
            s2_te = slope * s2_te + intercept
        return s2_te

    model = lgb.LGBMRegressor(**params)
    model.fit(X_tr, residual_tr, sample_weight=sample_weight)
    return model.predict(X_te)


# ── Severity-stratified KFold ────────────────────────────────────────────────


def stratified_kfold_split(
    y: np.ndarray, n_splits: int = 5, seed: int = 42
) -> list[tuple[np.ndarray, np.ndarray]]:
    arr = np.asarray(y, dtype=np.float64)
    bins = None
    for q in (5, 4, 3):
        try:
            bins = pd.qcut(arr, q=q, labels=False, duplicates="drop")
            if len(np.unique(bins[~pd.isna(bins)])) >= n_splits:
                break
        except ValueError:
            continue
    if bins is None or len(np.unique(bins)) < n_splits:
        from sklearn.model_selection import KFold
        return list(KFold(n_splits=n_splits, shuffle=True, random_state=seed).split(arr))
    bins_arr = np.asarray(bins, dtype=np.int64)
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    return list(skf.split(np.arange(len(arr)), bins_arr))


# ── Fold pipeline ────────────────────────────────────────────────────────────


def _one_fold(
    tr: np.ndarray, te: np.ndarray, X: np.ndarray, y_t3: np.ndarray, X_s1: np.ndarray,
    seed: int, alpha: float, weight_fn: Callable, enable_ccc: bool,
) -> np.ndarray:
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=alpha)
    residual_tr = y_t3[tr] - s1_tr
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
    weights_tr = weight_fn(residual_tr)
    s2_te = _train_stage2_lgb(
        Xtr_sel, residual_tr, Xte_sel, weights_tr, seed=seed, enable_ccc=enable_ccc,
    )
    return s1_te + s2_te


def stratified_kfold_pipeline(
    seed: int, weight_scheme: str, feature_set: str, alpha: float, enable_ccc: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sids, X, _fc, y_t3, hy, _obs = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    weight_fn = WEIGHT_SCHEMES[weight_scheme]
    splits = stratified_kfold_split(y_t3, n_splits=5, seed=seed)
    preds = np.zeros(n, dtype=np.float64)
    for tr, te in splits:
        preds[te] = _one_fold(
            np.asarray(tr), np.asarray(te), X, y_t3, X_s1,
            seed, alpha, weight_fn, enable_ccc,
        )
    return sids, y_t3, preds


def loocv_pipeline_one_seed(
    seed: int, weight_scheme: str, feature_set: str, alpha: float, enable_ccc: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sids, X, _fc, y_t3, hy, _obs = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])
    weight_fn = WEIGHT_SCHEMES[weight_scheme]
    preds = np.zeros(n, dtype=np.float64)
    t0 = time.time()
    for fi, (tr, te) in enumerate(LeaveOneOut().split(np.arange(n))):
        preds[te] = _one_fold(
            np.asarray(tr), np.asarray(te), X, y_t3, X_s1,
            seed, alpha, weight_fn, enable_ccc,
        )
        if (fi + 1) % 10 == 0:
            print(f"  [seed={seed} {weight_scheme}] {fi+1}/{n} elapsed={time.time()-t0:.1f}s", flush=True)
    return sids, y_t3, preds


# ── Worker entry points (picklable) ──────────────────────────────────────────


def _screen_worker(args: tuple) -> dict:
    weight_scheme, seed, feature_set, alpha, enable_ccc = args
    t0 = time.time()
    sids, y_t3, preds = stratified_kfold_pipeline(
        seed, weight_scheme, feature_set, alpha, enable_ccc,
    )
    bins = pd.qcut(y_t3, q=4, labels=False, duplicates="drop")
    residuals = preds - y_t3
    q_res = {
        f"q{q+1}_residual": float(residuals[np.asarray(bins) == q].mean())
        if (np.asarray(bins) == q).any() else float("nan")
        for q in range(4)
    }
    return {
        "weight_scheme": weight_scheme, "seed": seed, "feature_set": feature_set,
        "alpha": alpha, "enable_ccc": enable_ccc,
        "ccc": round(float(ccc_fn(y_t3, preds)), 4),
        "mae": round(float(mae_fn(y_t3, preds)), 3),
        "r": round(float(pearson_r(y_t3, preds)), 4),
        "slope": round(float(np.polyfit(y_t3, preds, 1)[0]) if y_t3.std() > 1e-9 else 0.0, 4),
        **{k: round(v, 3) for k, v in q_res.items()},
        "wall_time_s": round(time.time() - t0, 1),
    }


def _loocv_worker(args: tuple) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    seed, weight_scheme, feature_set, alpha, enable_ccc = args
    sids, y_t3, preds = loocv_pipeline_one_seed(
        seed, weight_scheme, feature_set, alpha, enable_ccc,
    )
    return seed, sids, y_t3, preds


# ── Architecture hash ────────────────────────────────────────────────────────


def architecture_sha256(
    weight_scheme: str, feature_set: str, alpha: float,
    enable_ccc: bool, k_features: int = 500,
) -> str:
    spec = {
        "iter": "iter27_tail_aware",
        "stage1": {
            "alpha": alpha, "feature_set": feature_set,
            "extras": ITER5_FEATURE_SETS[feature_set],
            "fold_normalizer": "FoldNormalizer.fit(train).transform",
            "ridge_intercept": True,
        },
        "stage2": {
            "lgb_params": _lgb_params(0),
            "k_feature_select": k_features,
            "weight_scheme": weight_scheme,
            "enable_ccc_objective": enable_ccc,
            "imputer": "median (impute_fold)",
            "feature_selector": "LGB importance K=500",
        },
        "loocv_seeds_default": [42, 1337, 7],
    }
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()


# ── 5-fold screen ────────────────────────────────────────────────────────────


def run_screen(
    seeds: tuple[int, ...], feature_set: str, alpha: float,
    enable_ccc: bool, n_workers: int,
) -> pd.DataFrame:
    arg_list = [(ws, seed, feature_set, alpha, enable_ccc)
                for ws in WEIGHT_SCHEMES for seed in seeds]
    print(
        f"\n=== iter27 5-FOLD STRATIFIED SCREEN ({len(arg_list)} runs, "
        f"workers={n_workers}) ===\n"
        f"  feature_set={feature_set} alpha={alpha} enable_ccc={enable_ccc}\n"
        f"  iter5 5-fold reference ≈ 0.40; canonical LOOCV={ITER5_CANONICAL_CCC}",
        flush=True,
    )
    rows: list[dict] = []
    if n_workers <= 1:
        for args in arg_list:
            row = _screen_worker(args)
            print(
                f"  {row['weight_scheme']:20s} seed={row['seed']} CCC={row['ccc']:.4f} "
                f"MAE={row['mae']:.3f} ({row['wall_time_s']}s)", flush=True,
            )
            rows.append(row)
    else:
        with ProcessPoolExecutor(max_workers=n_workers) as exe:
            futs = {exe.submit(_screen_worker, a): a for a in arg_list}
            for fut in as_completed(futs):
                row = fut.result()
                print(
                    f"  done {row['weight_scheme']:20s} seed={row['seed']} "
                    f"CCC={row['ccc']:.4f} MAE={row['mae']:.3f} "
                    f"q1={row.get('q1_residual', float('nan')):+.2f} "
                    f"q4={row.get('q4_residual', float('nan')):+.2f} "
                    f"({row['wall_time_s']}s)", flush=True,
                )
                rows.append(row)

    df = pd.DataFrame(rows).sort_values(["weight_scheme", "seed"]).reset_index(drop=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = RESULTS_DIR / f"iter27_tailaware_5fold_screen_{ts}.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}", flush=True)

    grp = df.groupby("weight_scheme").agg(
        ccc_mean=("ccc", "mean"), ccc_std=("ccc", "std"),
        mae_mean=("mae", "mean"),
        q1_res_mean=("q1_residual", "mean"),
        q4_res_mean=("q4_residual", "mean"),
    )
    baseline = grp.loc["uniform", "ccc_mean"] if "uniform" in grp.index else np.nan
    grp["delta_vs_uniform"] = grp["ccc_mean"] - baseline
    grp = grp.sort_values("ccc_mean", ascending=False)
    print("\n=== iter27 SUMMARY (5-fold mean across seeds) ===", flush=True)
    print(grp.to_string(float_format=lambda x: f"{x:.4f}"), flush=True)
    return df


# ── Pre-registration ─────────────────────────────────────────────────────────


def write_preregistration(
    weight_scheme: str, feature_set: str, alpha: float,
    enable_ccc: bool, seeds: tuple[int, ...],
) -> Path:
    if weight_scheme not in WEIGHT_SCHEMES:
        raise ValueError(f"Unknown weight_scheme {weight_scheme!r}")
    if feature_set not in ITER5_FEATURE_SETS:
        raise ValueError(f"Unknown feature_set {feature_set!r}")
    formula_hash = architecture_sha256(weight_scheme, feature_set, alpha, enable_ccc)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "iter": "iter27_tail_aware",
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "experiment": "T3 iter27 — Tail-aware Stage-2 sample weighting on iter5",
        "feature_set": feature_set,
        "stage1_extras": ITER5_FEATURE_SETS[feature_set],
        "alpha": alpha,
        "weight_scheme": weight_scheme,
        "enable_ccc_objective": enable_ccc,
        "n_subjects": 98,
        "seeds": list(seeds),
        "eval_protocol": (
            "LOOCV (n=98). Stage-1 Ridge with intercept, fold-local FoldNormalizer; "
            "Stage-2 LGB on V2 residual with sample_weight. Per-fold median imputation, "
            "K=500 LGB-importance selection. 3-seed mean preds = headline."
        ),
        "comparator": {
            "iter5_canonical_ccc": ITER5_CANONICAL_CCC,
            "lockbox_oof_glob": ITER5_LOCKBOX_GLOB,
        },
        "lockbox_rules": [
            "ONE config pre-registered, ONE LOOCV run.",
            "Paired bootstrap (iter27 - iter5) on SAME 98 SIDs; canonical update "
            "requires frac>0 >= 0.95 AND iter27 CCC > 0.5227.",
            "Stage 1 + K=500 selector are BIT-IDENTICAL to iter5.",
        ],
        "tail_shrinkage_motivation": (
            "F54: corr(residual, y_true)=-0.699 in iter5 LOOCV; Q1 +9.4 / Q4 -7.6. "
            "iter25b post-hoc calibration FAILED (Δ ~ -0.08). iter27 attacks during training."
        ),
        "formula_sha256": formula_hash,
    }
    out = RESULTS_DIR / f"preregistration_t3_iter27_{weight_scheme}_{ts}.json"
    out.write_text(json.dumps(payload, indent=2))
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {formula_hash}", flush=True)
    return out


# ── Lockbox LOOCV ────────────────────────────────────────────────────────────


def _load_iter5_oof(sids_ref: np.ndarray) -> tuple[np.ndarray, str]:
    candidates = sorted(p for p in RESULTS_DIR.glob(ITER5_LOCKBOX_GLOB) if p.suffix == ".json")
    if not candidates:
        raise FileNotFoundError(
            f"No iter5 lockbox JSON matching {ITER5_LOCKBOX_GLOB} in {RESULTS_DIR}"
        )
    chosen = candidates[-1]
    data = json.loads(chosen.read_text())
    ps = data.get("per_subject", {})
    if not ps or "sids" not in ps or "y_pred" not in ps:
        raise ValueError(f"iter5 lockbox JSON {chosen} missing per_subject.sids/y_pred")
    sid_to_pred = dict(zip(list(ps["sids"]), np.asarray(ps["y_pred"], dtype=np.float64)))
    missing = [s for s in sids_ref if str(s) not in sid_to_pred]
    if missing:
        raise ValueError(f"iter5 lockbox missing {len(missing)} SIDs (e.g. {missing[:3]})")
    aligned = np.asarray([sid_to_pred[str(s)] for s in sids_ref], dtype=np.float64)
    return aligned, str(chosen)


def run_lockbox(preregistration_file: Path, n_workers: int) -> dict:
    payload = json.loads(preregistration_file.read_text())
    weight_scheme = payload["weight_scheme"]
    feature_set = payload["feature_set"]
    alpha = float(payload["alpha"])
    enable_ccc = bool(payload.get("enable_ccc_objective", False))
    seeds = tuple(int(s) for s in payload["seeds"])
    expected_hash = payload.get("formula_sha256")

    actual_hash = architecture_sha256(weight_scheme, feature_set, alpha, enable_ccc)
    if expected_hash and expected_hash != actual_hash:
        raise RuntimeError(
            f"formula_sha256 mismatch — code changed since prereg.\n"
            f"  preregistered: {expected_hash}\n  current:       {actual_hash}\n"
            f"Refusing to run lockbox."
        )
    print(
        f"\n=== iter27 LOCKBOX LOOCV ({weight_scheme}, fs={feature_set}, alpha={alpha}, "
        f"enable_ccc={enable_ccc}, seeds={seeds}) ===\n  formula_sha256={actual_hash}",
        flush=True,
    )

    arg_list = [(seed, weight_scheme, feature_set, alpha, enable_ccc) for seed in seeds]
    seed_to_preds: dict[int, np.ndarray] = {}
    sids_ref: np.ndarray | None = None
    y_t3_ref: np.ndarray | None = None

    if n_workers <= 1:
        for args in arg_list:
            t0 = time.time()
            seed, sids, y_t3, preds = _loocv_worker(args)
            print(f"  seed={seed} CCC={ccc_fn(y_t3, preds):.4f} ({time.time()-t0:.1f}s)", flush=True)
            seed_to_preds[seed] = preds
            sids_ref, y_t3_ref = sids, y_t3
    else:
        with ProcessPoolExecutor(max_workers=min(n_workers, len(seeds))) as exe:
            futs = {exe.submit(_loocv_worker, a): a for a in arg_list}
            for fut in as_completed(futs):
                seed, sids, y_t3, preds = fut.result()
                seed_to_preds[seed] = preds
                sids_ref, y_t3_ref = sids, y_t3
                print(f"  seed={seed} done CCC={ccc_fn(y_t3, preds):.4f}", flush=True)

    assert sids_ref is not None and y_t3_ref is not None
    seeds_sorted = sorted(seed_to_preds)
    pred_matrix = np.column_stack([seed_to_preds[s] for s in seeds_sorted])
    mean_preds = pred_matrix.mean(axis=1)
    headline = full_metrics(y_t3_ref, mean_preds, label=f"t3_iter27_{weight_scheme}")
    per_seed_ccc = [float(ccc_fn(y_t3_ref, seed_to_preds[s])) for s in seeds_sorted]
    per_seed_mae = [float(mae_fn(y_t3_ref, seed_to_preds[s])) for s in seeds_sorted]

    bins = pd.qcut(y_t3_ref, q=4, labels=False, duplicates="drop")
    residuals = mean_preds - y_t3_ref
    q_residuals = {
        f"q{int(q)+1}": float(residuals[np.asarray(bins) == q].mean())
        for q in range(4) if (np.asarray(bins) == q).any()
    }

    iter5_aligned, iter5_path = _load_iter5_oof(sids_ref)
    iter5_ccc_on_ref = float(ccc_fn(y_t3_ref, iter5_aligned))
    rng = np.random.RandomState(42)
    n_boot = 5000
    n = len(y_t3_ref)
    deltas = np.zeros(n_boot, dtype=np.float64)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        deltas[b] = (
            ccc_fn(y_t3_ref[idx], mean_preds[idx])
            - ccc_fn(y_t3_ref[idx], iter5_aligned[idx])
        )
    boot = {
        "n_boot": n_boot,
        "delta_mean": round(float(deltas.mean()), 4),
        "delta_ci_low": round(float(np.percentile(deltas, 2.5)), 4),
        "delta_ci_high": round(float(np.percentile(deltas, 97.5)), 4),
        "frac_above_zero": round(float((deltas > 0).mean()), 4),
        "frac_above_0p01": round(float((deltas > 0.01).mean()), 4),
    }
    delta_point = float(headline["ccc"]) - iter5_ccc_on_ref
    is_canonical_update = bool(
        boot["frac_above_zero"] >= 0.95 and float(headline["ccc"]) > ITER5_CANONICAL_CCC
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"iter27_lockbox_{weight_scheme}_{ts}.json"
    out_npy = RESULTS_DIR / f"iter27_lockbox_{weight_scheme}_{ts}.oof.npy"
    out_sids = RESULTS_DIR / f"iter27_lockbox_{weight_scheme}_{ts}.sids.npy"

    payload_out = {
        **headline,
        "ccc_iter27": float(headline["ccc"]),
        "ccc_iter5_canonical": ITER5_CANONICAL_CCC,
        "ccc_iter5_on_ref_n98": round(iter5_ccc_on_ref, 4),
        "delta_point": round(delta_point, 4),
        "bootstrap": boot,
        "is_canonical_update": is_canonical_update,
        "weight_scheme": weight_scheme,
        "feature_set": feature_set,
        "enable_ccc_objective": enable_ccc,
        "alpha": alpha,
        "n_seeds": len(seeds),
        "n_subjects": int(n),
        "per_seed_ccc": per_seed_ccc,
        "per_seed_mae": per_seed_mae,
        "q_residuals": q_residuals,
        "iter5_lockbox_source": iter5_path,
        "preregistration_file": str(preregistration_file),
        "formula_sha256": actual_hash,
        "per_subject": {
            "sids": [str(s) for s in sids_ref.tolist()],
            "y_true": y_t3_ref.tolist(),
            "y_pred": mean_preds.tolist(),
        },
        "is_lockbox_headline": True,
    }
    np.save(out_npy, mean_preds)
    np.save(out_sids, np.asarray([str(s) for s in sids_ref]))
    out_json.write_text(json.dumps(payload_out, indent=2, default=str))

    print(
        f"\n=== iter27 LOCKBOX HEADLINE ({weight_scheme}) ===\n"
        f"  CCC={headline['ccc']:.4f}  MAE={headline['mae']:.3f}  "
        f"r={headline['r']:.4f}  slope={headline['cal_slope']:.3f}\n"
        f"  Δ vs iter5 (point): {delta_point:+.4f}\n"
        f"  Bootstrap (n={n_boot}): mean Δ={boot['delta_mean']:+.4f}, "
        f"95% CI=[{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}], "
        f"frac>0={boot['frac_above_zero']:.3f}\n"
        f"  Quartile residuals: {q_residuals}\n"
        f"  is_canonical_update = {is_canonical_update}\n"
        f"Wrote {out_json}\nWrote {out_npy}\nWrote {out_sids}",
        flush=True,
    )
    return payload_out


# ── main ─────────────────────────────────────────────────────────────────────


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="T3 iter27 tail-aware runner")
    ap.add_argument("--mode", choices=["screen", "write_prereg", "lockbox"], required=True)
    ap.add_argument("--weight_scheme", default="quartile_balanced",
                    choices=sorted(WEIGHT_SCHEMES),
                    help="Sample-weight scheme for Stage-2 LGB")
    ap.add_argument("--enable_ccc_objective", action="store_true",
                    help="Enable custom CCC LGB objective (off by default)")
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 1337, 7])
    ap.add_argument("--feature_set", default="A3_tier1",
                    help="Stage-1 feature set (default A3_tier1 for iter5 parity)")
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--n_workers", type=int,
                    default=int(os.getenv("ITER27_WORKERS", 11)),
                    help="Process pool size (set 1 for serial)")
    ap.add_argument("--preregistration_file", type=str, default=None,
                    help="(lockbox mode) Path to immutable prereg JSON")
    return ap


def main() -> None:
    args = _build_argparser().parse_args()
    if args.feature_set not in ITER5_FEATURE_SETS:
        raise SystemExit(f"Unknown feature_set {args.feature_set!r}")
    if args.weight_scheme not in WEIGHT_SCHEMES:
        raise SystemExit(f"Unknown weight_scheme {args.weight_scheme!r}")
    seeds = tuple(args.seeds)

    if args.mode == "screen":
        run_screen(seeds, args.feature_set, args.alpha,
                   args.enable_ccc_objective, args.n_workers)
    elif args.mode == "write_prereg":
        write_preregistration(args.weight_scheme, args.feature_set, args.alpha,
                              args.enable_ccc_objective, seeds)
    elif args.mode == "lockbox":
        if not args.preregistration_file:
            raise SystemExit("--preregistration_file required for lockbox mode")
        prereg_path = Path(args.preregistration_file)
        if not prereg_path.exists():
            raise SystemExit(f"Preregistration file not found: {prereg_path}")
        run_lockbox(prereg_path, n_workers=args.n_workers)


if __name__ == "__main__":
    main()

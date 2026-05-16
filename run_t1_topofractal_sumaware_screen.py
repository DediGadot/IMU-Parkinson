"""Screen a target-free TopoFractal-8 sum-aware T1 residual composer.

This is a direct follow-through on `/tmp/pro-results.txt` after the May 15
D4 audit narrowed the real PH/MFDFA signal to item 13. It is deliberately a
5-fold screen, not a lockbox:

  * Build eight pre-fixed PH/MFDFA components without target selection.
  * Fit fold-local BayesianRidge corrections to the T1-sum residual.
  * Select only a correction scale lambda inside each train fold.
  * Promote to a future LOOCV only if the 5-fold gate is met.

The eight components are one train-fold PCA component per target-free subfamily:
PH trunk max/median, PH sacrum max/median, and four MFDFA trunk-pitch summaries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.linear_model import BayesianRidge
from sklearn.model_selection import KFold

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from eval_utils import lins_ccc  # noqa: E402
from inductive_lib import FoldImputer, FoldNormalizer, full_metrics  # noqa: E402


CACHE_PATH = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"
OOF_PATH = "results/t1_iter34_per_item_oof_20260511_044242.npz"

GROUP_SPECS: tuple[tuple[str, str], ...] = (
    ("ph_trunk_h1_max", "_ph_trunk_pitch_h1_max"),
    ("ph_trunk_h1_med", "_ph_trunk_pitch_h1_med"),
    ("ph_sacrum_h1_max", "_ph_sacrum_ang_h1_max"),
    ("ph_sacrum_h1_med", "_ph_sacrum_ang_h1_med"),
    ("mfdfa_delta_alpha", "_mfdfa_trunk_pitch_delta_alpha"),
    ("mfdfa_asymmetry", "_mfdfa_trunk_pitch_asymmetry"),
    ("mfdfa_hurst_q2", "_mfdfa_trunk_pitch_hurst_q2"),
    ("mfdfa_h_range", "_mfdfa_trunk_pitch_h_range"),
)
LAMBDA_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
INNER_FOLDS = 5
DEFAULT_SEEDS = (42, 1337, 7)
N_BOOT = 2000


@dataclass
class ComponentFit:
    name: str
    cols: list[str]
    explained_variance: float


def _json_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(type(obj).__name__)


def formula_sha256() -> str:
    payload = {
        "name": "t1_topofractal8_sumaware_screen",
        "group_specs": GROUP_SPECS,
        "lambda_grid": LAMBDA_GRID,
        "inner_folds": INNER_FOLDS,
        "model": "BayesianRidge default sklearn",
        "screen_only_gate": {
            "delta_ccc": 0.025,
            "bootstrap_frac_positive": 0.95,
            "seed_delta_std": 0.020,
            "no_material_mae_degradation": True,
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def load_aligned(feature_path: str, oof_path: str):
    df = pd.read_csv(feature_path)
    oof = dict(np.load(oof_path, allow_pickle=True))
    sids = oof["sids"].astype(str)

    df = df[df["sid"].astype(str).isin(sids)].copy()
    sid_to_row = {sid: i for i, sid in enumerate(df["sid"].astype(str).values)}
    missing = [sid for sid in sids if sid not in sid_to_row]
    if missing:
        raise ValueError(f"Missing feature rows for {len(missing)} SIDs: {missing[:5]}")
    df = df.iloc[[sid_to_row[sid] for sid in sids]].reset_index(drop=True)
    if not np.array_equal(df["sid"].astype(str).values, sids):
        raise AssertionError("Feature/OFF SID alignment failed")

    group_mats: dict[str, np.ndarray] = {}
    group_cols: dict[str, list[str]] = {}
    for name, pattern in GROUP_SPECS:
        cols = [c for c in df.columns if pattern in c]
        if not cols:
            raise ValueError(f"No columns found for group {name} pattern {pattern}")
        group_cols[name] = cols
        group_mats[name] = df[cols].to_numpy(dtype=np.float64)

    y_t1 = oof["y_t1"].astype(float)
    yhat_t1 = oof["t1_sum_pred"].astype(float)
    return df, oof, sids, group_mats, group_cols, y_t1, yhat_t1


def fit_topofractal_components(
    group_mats: dict[str, np.ndarray],
    group_cols: dict[str, list[str]],
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    include_canary: bool = False,
    canary_test_values: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, list[ComponentFit]]:
    z_train_parts: list[np.ndarray] = []
    z_test_parts: list[np.ndarray] = []
    fits: list[ComponentFit] = []

    for name, _ in GROUP_SPECS:
        X = group_mats[name]
        X_tr_raw = X[train_idx]
        X_te_raw = X[test_idx]
        imp = FoldImputer.fit(X_tr_raw)
        X_tr = imp.transform(X_tr_raw)
        X_te = imp.transform(X_te_raw)
        norm = FoldNormalizer.fit(X_tr)
        X_tr = norm.transform(X_tr)
        X_te = norm.transform(X_te)
        pca = PCA(n_components=1, random_state=0)
        z_tr = pca.fit_transform(X_tr)
        z_te = pca.transform(X_te)
        z_train_parts.append(z_tr)
        z_test_parts.append(z_te)
        fits.append(
            ComponentFit(
                name=name,
                cols=group_cols[name],
                explained_variance=float(pca.explained_variance_ratio_[0]),
            )
        )

    Z_tr = np.hstack(z_train_parts)
    Z_te = np.hstack(z_test_parts)
    if include_canary:
        if canary_test_values is None:
            raise ValueError("canary_test_values required when include_canary=True")
        Z_tr = np.hstack([Z_tr, np.zeros((len(train_idx), 1), dtype=np.float64)])
        Z_te = np.hstack([Z_te, canary_test_values.reshape(-1, 1).astype(np.float64)])
    return Z_tr, Z_te, fits


def inner_select_lambda(
    group_mats: dict[str, np.ndarray],
    group_cols: dict[str, list[str]],
    outer_train_idx: np.ndarray,
    y_fit: np.ndarray,
    yhat_base: np.ndarray,
    seed: int,
    include_canary: bool = False,
) -> tuple[float, dict[str, float]]:
    kf = KFold(n_splits=INNER_FOLDS, shuffle=True, random_state=seed)
    inner_corr = np.full(len(outer_train_idx), np.nan, dtype=np.float64)
    outer_train_idx = np.asarray(outer_train_idx)

    for tr_local, va_local in kf.split(np.arange(len(outer_train_idx))):
        tr_idx = outer_train_idx[tr_local]
        va_idx = outer_train_idx[va_local]
        canary = None
        if include_canary:
            canary = y_fit[va_idx] - yhat_base[va_idx]
        Z_tr, Z_va, _ = fit_topofractal_components(
            group_mats, group_cols, tr_idx, va_idx,
            include_canary=include_canary, canary_test_values=canary,
        )
        residual_tr = y_fit[tr_idx] - yhat_base[tr_idx]
        model = BayesianRidge()
        model.fit(Z_tr, residual_tr)
        inner_corr[va_local] = model.predict(Z_va)

    if np.isnan(inner_corr).any():
        raise RuntimeError("Inner correction OOF contains NaNs")

    scores = {}
    y_train = y_fit[outer_train_idx]
    yhat_train = yhat_base[outer_train_idx]
    for lam in LAMBDA_GRID:
        scores[str(lam)] = float(lins_ccc(y_train, yhat_train + lam * inner_corr))

    # Conservative tie-break: prefer smaller lambda for nearly identical scores.
    best_lam = min(
        LAMBDA_GRID,
        key=lambda lam: (-scores[str(lam)], lam),
    )
    return float(best_lam), scores


def screen_one_seed(
    group_mats: dict[str, np.ndarray],
    group_cols: dict[str, list[str]],
    y_true: np.ndarray,
    yhat_base: np.ndarray,
    seed: int,
    null_mode: str = "real",
    include_canary: bool = False,
) -> tuple[np.ndarray, list[dict]]:
    n = len(y_true)
    y_fit = y_true.copy()
    mats = group_mats
    if null_mode == "scrambled_y":
        rng = np.random.default_rng(seed + 5000)
        y_fit = rng.permutation(y_fit)
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(seed + 7000)
        perm = rng.permutation(n)
        mats = {name: X[perm] for name, X in group_mats.items()}
    elif null_mode != "real":
        raise ValueError(null_mode)

    preds = np.full(n, np.nan, dtype=np.float64)
    fold_rows: list[dict] = []
    kf = KFold(n_splits=5, shuffle=True, random_state=seed)
    for fold_idx, (tr_idx, te_idx) in enumerate(kf.split(np.arange(n))):
        lam, inner_scores = inner_select_lambda(
            mats, group_cols, tr_idx, y_fit, yhat_base, seed + fold_idx * 17,
            include_canary=include_canary,
        )
        canary = None
        if include_canary:
            canary = y_fit[te_idx] - yhat_base[te_idx]
        Z_tr, Z_te, fits = fit_topofractal_components(
            mats, group_cols, tr_idx, te_idx,
            include_canary=include_canary, canary_test_values=canary,
        )
        model = BayesianRidge()
        model.fit(Z_tr, y_fit[tr_idx] - yhat_base[tr_idx])
        correction = model.predict(Z_te)
        preds[te_idx] = yhat_base[te_idx] + lam * correction
        fold_rows.append(
            {
                "seed": int(seed),
                "fold": int(fold_idx),
                "null_mode": null_mode,
                "include_canary": bool(include_canary),
                "n_train": int(len(tr_idx)),
                "n_test": int(len(te_idx)),
                "lambda_star": float(lam),
                "inner_scores": inner_scores,
                "correction_mean": float(np.mean(correction)),
                "correction_std": float(np.std(correction)),
                "component_explained_variance": {
                    fit.name: fit.explained_variance for fit in fits
                },
            }
        )

    if np.isnan(preds).any():
        raise RuntimeError("5-fold OOF predictions contain NaNs")
    return preds, fold_rows


def bootstrap_delta(y: np.ndarray, base: np.ndarray, cand: np.ndarray,
                    n_boot: int = N_BOOT, seed: int = 20260515) -> dict:
    rng = np.random.default_rng(seed)
    n = len(y)
    deltas = np.empty(n_boot, dtype=np.float64)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        deltas[i] = lins_ccc(y[idx], cand[idx]) - lins_ccc(y[idx], base[idx])
    return {
        "n_boot": int(n_boot),
        "median_delta": float(np.median(deltas)),
        "ci95_lower": float(np.quantile(deltas, 0.025)),
        "ci95_upper": float(np.quantile(deltas, 0.975)),
        "frac_positive": float((deltas > 0).mean()),
    }


def summarize_prediction(y: np.ndarray, base: np.ndarray, cand: np.ndarray,
                         label: str, boot_seed: int) -> dict:
    base_m = full_metrics(y, base, f"{label}_baseline")
    cand_m = full_metrics(y, cand, f"{label}_candidate")
    return {
        "baseline": base_m,
        "candidate": cand_m,
        "delta_ccc": float(cand_m["ccc"] - base_m["ccc"]),
        "delta_mae": float(cand_m["mae"] - base_m["mae"]),
        "bootstrap": bootstrap_delta(y, base, cand, seed=boot_seed),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feature", default=CACHE_PATH)
    ap.add_argument("--oof", default=OOF_PATH)
    ap.add_argument("--seeds", default="42,1337,7")
    ap.add_argument("--skip-nulls", action="store_true")
    args = ap.parse_args()

    seeds = tuple(int(x) for x in args.seeds.split(",") if x.strip())
    _, _, sids, group_mats, group_cols, y_t1, yhat_base = load_aligned(args.feature, args.oof)
    n = len(y_t1)
    sha = formula_sha256()

    print("=" * 80)
    print("T1 TopoFractal-8 sum-aware 5-fold screen")
    print("=" * 80)
    print(f"N={n}; formula_sha256={sha}")
    for name, cols in group_cols.items():
        print(f"  {name}: {len(cols)} cols")
    print(f"Baseline iter34 CCC={lins_ccc(y_t1, yhat_base):.4f}")

    all_seed_preds = []
    all_fold_rows = []
    seed_summaries = {}
    for seed in seeds:
        print(f"\n[real] seed={seed}")
        pred, rows = screen_one_seed(group_mats, group_cols, y_t1, yhat_base, seed)
        all_seed_preds.append(pred)
        all_fold_rows.extend(rows)
        summary = summarize_prediction(y_t1, yhat_base, pred, f"seed_{seed}", seed)
        seed_summaries[str(seed)] = summary
        print(
            f"  CCC={summary['candidate']['ccc']:.4f} "
            f"delta={summary['delta_ccc']:+.4f} "
            f"MAE_delta={summary['delta_mae']:+.4f} "
            f"frac>0={summary['bootstrap']['frac_positive']:.4f}"
        )

    pred_matrix = np.vstack(all_seed_preds)
    pred_ensemble = pred_matrix.mean(axis=0)
    ensemble_summary = summarize_prediction(
        y_t1, yhat_base, pred_ensemble, "ensemble_mean", 424242
    )
    deltas = np.array([seed_summaries[str(seed)]["delta_ccc"] for seed in seeds])
    mean_delta = float(deltas.mean())
    seed_delta_std = float(deltas.std(ddof=0))
    mae_ok = bool(ensemble_summary["delta_mae"] <= 0.05)
    gate_pass = bool(
        mean_delta >= 0.025
        and seed_delta_std < 0.020
        and ensemble_summary["bootstrap"]["frac_positive"] >= 0.95
        and mae_ok
    )

    print("\n=== ENSEMBLE SCREEN SUMMARY ===")
    print(f"  baseline CCC={ensemble_summary['baseline']['ccc']:.4f}")
    print(f"  candidate CCC={ensemble_summary['candidate']['ccc']:.4f}")
    print(f"  ensemble delta={ensemble_summary['delta_ccc']:+.4f}")
    print(f"  seed mean delta={mean_delta:+.4f}; seed std={seed_delta_std:.4f}")
    print(f"  bootstrap frac>0={ensemble_summary['bootstrap']['frac_positive']:.4f}")
    print(f"  promotion gate={'PASS' if gate_pass else 'FAIL'}")

    null_results = {}
    if not args.skip_nulls:
        print("\n=== NULL CHECKS ===")
        null_pred, null_rows = screen_one_seed(
            group_mats, group_cols, y_t1, yhat_base, seeds[0], null_mode="scrambled_y"
        )
        null_results["scrambled_y"] = summarize_prediction(
            y_t1, yhat_base, null_pred, "scrambled_y", 111
        )
        all_fold_rows.extend(null_rows)
        print(
            f"  scrambled_y delta={null_results['scrambled_y']['delta_ccc']:+.4f} "
            f"frac>0={null_results['scrambled_y']['bootstrap']['frac_positive']:.4f}"
        )

        null_pred, null_rows = screen_one_seed(
            group_mats, group_cols, y_t1, yhat_base, seeds[0], null_mode="sid_shuffle"
        )
        null_results["sid_shuffle"] = summarize_prediction(
            y_t1, yhat_base, null_pred, "sid_shuffle", 222
        )
        all_fold_rows.extend(null_rows)
        print(
            f"  sid_shuffle delta={null_results['sid_shuffle']['delta_ccc']:+.4f} "
            f"frac>0={null_results['sid_shuffle']['bootstrap']['frac_positive']:.4f}"
        )

        canary_pred, canary_rows = screen_one_seed(
            group_mats, group_cols, y_t1, yhat_base, seeds[0],
            null_mode="real", include_canary=True,
        )
        null_results["test_only_canary"] = {
            "max_abs_prediction_diff_vs_real_seed": float(
                np.max(np.abs(canary_pred - all_seed_preds[0]))
            ),
            "passes": bool(np.max(np.abs(canary_pred - all_seed_preds[0])) < 1e-8),
        }
        all_fold_rows.extend(canary_rows)
        print(
            "  test_only_canary max_abs_diff="
            f"{null_results['test_only_canary']['max_abs_prediction_diff_vs_real_seed']:.6g}"
        )
        null_results["retrieval_library_exclusion"] = {
            "status": "not_applicable",
            "rationale": "No retrieval library, nearest-neighbor reference set, or recording library is used.",
        }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result = {
        "name": "screen_t1_topofractal8_sumaware",
        "created_at_utc": ts,
        "objective": "screen target-free TopoFractal-8 compression plus sum-aware Bayesian residual composer",
        "screen_only": True,
        "promotion_gate": {
            "mean_seed_delta_ccc_min": 0.025,
            "seed_delta_std_max": 0.020,
            "ensemble_bootstrap_frac_positive_min": 0.95,
            "max_material_mae_degradation": 0.05,
            "gate_pass": gate_pass,
        },
        "formula_sha256": sha,
        "feature_cache": args.feature,
        "oof_npz": args.oof,
        "n": int(n),
        "seeds": list(seeds),
        "group_specs": [
            {"name": name, "pattern": pattern, "columns": group_cols[name]}
            for name, pattern in GROUP_SPECS
        ],
        "lambda_grid": list(LAMBDA_GRID),
        "model": "BayesianRidge",
        "seed_summaries": seed_summaries,
        "ensemble_summary": ensemble_summary,
        "seed_mean_delta_ccc": mean_delta,
        "seed_delta_std": seed_delta_std,
        "null_results": null_results,
        "verdict": (
            "PROMOTE_TO_PREREG_LOOCV" if gate_pass
            else "SCREEN_FAIL_NO_LOOCV"
        ),
        "interpretation": (
            "If failed, this closes the remaining target-free TopoFractal-8 "
            "sum-aware composer wording from /tmp/pro-results.txt for internal "
            "T1 headline purposes without changing canonical numbers."
        ),
    }

    out_json = Path(f"results/screen_t1_topofractal8_sumaware_{ts}.json")
    out_json.write_text(json.dumps(result, indent=2, default=_json_default) + "\n")
    rows = pd.DataFrame(all_fold_rows)
    out_rows = Path(f"results/screen_t1_topofractal8_sumaware_rows_{ts}.csv")
    rows.to_csv(out_rows, index=False)

    print(f"\nWrote {out_json}")
    print(f"Wrote {out_rows}")
    return result


if __name__ == "__main__":
    main()

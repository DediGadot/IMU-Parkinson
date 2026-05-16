#!/usr/bin/env python3
"""T1 S9: fold-local sparse prototype regression over TopoFractal state.

This is a screen-only follow-through on `/tmp/pro-results.txt` rank #9.
It tests whether a small nonlinear prototype model in a fixed target-free
PH/MFDFA state can improve the T1 sum residual without returning to broad
feature fishing.

Screen policy:
  - 5-fold only across seeds [42, 1337, 7].
  - No LOOCV is run here.
  - Promote only if mean delta >= +0.025, seed std < 0.020, bootstrap frac>0
    >= 0.95, and MAE does not materially degrade.

Firewall:
  - FoldImputer/FoldNormalizer fit on train folds only.
  - Prototype medoids are selected from train rows only.
  - Ridge alpha is selected by inner 5-fold on the outer-train rows only.
  - Nulls include scrambled-y, SID-shuffle, and explicit library exclusion.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

from eval_utils import lins_ccc as ccc
from inductive_lib import FoldImputer, FoldNormalizer


ROOT = Path(__file__).resolve().parent
ITER34_OOF_NPZ = ROOT / "results" / "t1_iter34_per_item_oof_20260511_044242.npz"
FEATURE_CACHE = ROOT / "results" / "cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"
PREREG = ROOT / "results" / "preregistration_t1t3_proresults_ablation_20260515T133800Z.json"

MFDFA_SUFFIXES = (
    "_mfdfa_trunk_pitch_delta_alpha",
    "_mfdfa_trunk_pitch_hurst_q2",
    "_mfdfa_trunk_pitch_h_range",
    "_mfdfa_trunk_pitch_asymmetry",
)
PH_SUFFIXES = ("_ph_trunk_pitch_h1_", "_ph_sacrum_ang_h1_")

SEEDS = (42, 1337, 7)
INNER_FOLDS = 5
OUTER_FOLDS = 5
N_BOOT = 2000
BOOT_SEED = 20260515
N_PROTOTYPES = 5
ALPHA_GRID = (10.0, 100.0, 1000.0)
CORRECTION_CAP_FRAC = 0.5


def load_aligned() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    oof = dict(np.load(ITER34_OOF_NPZ, allow_pickle=True))
    sids = oof["sids"].astype(str)
    y_t1 = oof["y_t1"].astype(float)
    pred = oof["t1_sum_pred"].astype(float)

    df = pd.read_csv(FEATURE_CACHE)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    missing = [s for s in sids if s not in sid_to_row]
    if missing:
        raise ValueError(f"Missing feature-cache rows for {missing[:5]}")
    df = df.iloc[[sid_to_row[s] for s in sids]].reset_index(drop=True)
    if not np.array_equal(df["sid"].astype(str).values, sids):
        raise AssertionError("SID alignment failed")

    blocks: list[np.ndarray] = []
    names: list[str] = []
    cols = df.columns.tolist()
    for suffix in MFDFA_SUFFIXES:
        members = [c for c in cols if c.endswith(suffix)]
        if members:
            blocks.append(df[members].mean(axis=1).to_numpy(dtype=float))
            names.append(f"mean_task{suffix}")
    for suffix in PH_SUFFIXES:
        members = [c for c in cols if suffix in c]
        if members:
            blocks.append(df[members].mean(axis=1).to_numpy(dtype=float))
            names.append(f"mean_task_{suffix.strip('_')}_maxmed_pooled")
    if len(blocks) < 4:
        raise ValueError(f"Too few TopoFractal blocks found: {names}")
    z_raw = np.column_stack(blocks)
    return sids, y_t1, pred, z_raw, names


def fold_transform(
    z_raw: np.ndarray, train_idx: np.ndarray, test_idx: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    imp = FoldImputer.fit(z_raw[train_idx])
    z_train = imp.transform(z_raw[train_idx])
    z_test = imp.transform(z_raw[test_idx])
    norm = FoldNormalizer.fit(z_train)
    return norm.transform(z_train), norm.transform(z_test)


def select_quantile_medoids(z_train: np.ndarray, resid_train: np.ndarray) -> np.ndarray:
    order = np.argsort(resid_train)
    bins = np.array_split(order, N_PROTOTYPES)
    proto_indices: list[int] = []
    for group in bins:
        if len(group) == 0:
            continue
        centroid = z_train[group].mean(axis=0, keepdims=True)
        d2 = np.sum((z_train[group] - centroid) ** 2, axis=1)
        proto_indices.append(int(group[int(np.argmin(d2))]))
    unique = []
    for idx in proto_indices:
        if idx not in unique:
            unique.append(idx)
    return z_train[np.array(unique, dtype=int)]


def rbf_features(z: np.ndarray, prototypes: np.ndarray, gamma: float) -> np.ndarray:
    d2 = ((z[:, None, :] - prototypes[None, :, :]) ** 2).sum(axis=2)
    return np.exp(-gamma * d2)


def fit_predict_residual(
    z_train: np.ndarray,
    resid_train: np.ndarray,
    z_test: np.ndarray,
    alpha: float,
) -> np.ndarray:
    prototypes = select_quantile_medoids(z_train, resid_train)
    d2_train = ((z_train[:, None, :] - prototypes[None, :, :]) ** 2).sum(axis=2)
    med = float(np.median(d2_train[d2_train > 0])) if np.any(d2_train > 0) else 1.0
    gamma = 1.0 / max(med, 1e-6)
    x_train = rbf_features(z_train, prototypes, gamma)
    x_test = rbf_features(z_test, prototypes, gamma)
    model = Ridge(alpha=alpha, fit_intercept=True)
    model.fit(x_train, resid_train)
    return model.predict(x_test)


def inner_select_alpha(
    z_raw_train: np.ndarray,
    resid_train: np.ndarray,
    pred_train: np.ndarray,
    y_train: np.ndarray,
    seed: int,
) -> float:
    n = len(y_train)
    kf = KFold(n_splits=INNER_FOLDS, shuffle=True, random_state=seed)
    best_alpha = ALPHA_GRID[0]
    best_score = -np.inf
    for alpha in ALPHA_GRID:
        oof_delta = np.zeros(n)
        for tr, va in kf.split(np.arange(n)):
            z_tr, z_va = fold_transform(z_raw_train, tr, va)
            delta = fit_predict_residual(z_tr, resid_train[tr], z_va, alpha)
            cap = CORRECTION_CAP_FRAC * float(np.std(resid_train[tr]))
            if cap > 0:
                delta = np.clip(delta, -cap, cap)
            oof_delta[va] = delta
        score = float(ccc(y_train, pred_train + oof_delta))
        if score > best_score:
            best_score = score
            best_alpha = alpha
    return best_alpha


def fivefold_predictions(
    y: np.ndarray, pred: np.ndarray, z_raw: np.ndarray, seed: int
) -> tuple[np.ndarray, list[float]]:
    n = len(y)
    corrected = pred.copy()
    selected_alphas: list[float] = []
    kf = KFold(n_splits=OUTER_FOLDS, shuffle=True, random_state=seed)
    resid = y - pred
    for tr, te in kf.split(np.arange(n)):
        alpha = inner_select_alpha(z_raw[tr], resid[tr], pred[tr], y[tr], seed)
        selected_alphas.append(alpha)
        z_tr, z_te = fold_transform(z_raw, tr, te)
        delta = fit_predict_residual(z_tr, resid[tr], z_te, alpha)
        cap = CORRECTION_CAP_FRAC * float(np.std(resid[tr]))
        if cap > 0:
            delta = np.clip(delta, -cap, cap)
        corrected[te] = pred[te] + delta
    return corrected, selected_alphas


def basic_metrics(y: np.ndarray, pred: np.ndarray) -> dict:
    return {
        "ccc": round(float(ccc(y, pred)), 4),
        "mae": round(float(np.mean(np.abs(y - pred))), 4),
        "pred_mean": round(float(np.mean(pred)), 4),
        "pred_std": round(float(np.std(pred)), 4),
        "true_mean": round(float(np.mean(y)), 4),
        "true_std": round(float(np.std(y)), 4),
    }


def paired_bootstrap(y: np.ndarray, base: np.ndarray, candidate: np.ndarray) -> dict:
    rng = np.random.default_rng(BOOT_SEED)
    n = len(y)
    deltas = np.empty(N_BOOT)
    for i in range(N_BOOT):
        idx = rng.choice(n, n, replace=True)
        deltas[i] = float(ccc(y[idx], candidate[idx]) - ccc(y[idx], base[idx]))
    return {
        "n_boot": N_BOOT,
        "median_delta": round(float(np.median(deltas)), 4),
        "ci95": [round(float(np.percentile(deltas, 2.5)), 4), round(float(np.percentile(deltas, 97.5)), 4)],
        "frac_positive": round(float((deltas > 0).mean()), 4),
    }


def apply_null(
    y: np.ndarray, pred: np.ndarray, z_raw: np.ndarray, null_mode: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if null_mode in ("", "real"):
        return y, pred, z_raw
    if null_mode == "scrambled_y":
        perm = np.random.default_rng(20260515).permutation(len(y))
        return y[perm], pred[perm], z_raw
    if null_mode == "sid_shuffle":
        perm = np.random.default_rng(31415927).permutation(len(y))
        return y, pred, z_raw[perm]
    raise ValueError(f"unknown null mode: {null_mode}")


def screen_core(y: np.ndarray, pred: np.ndarray, z_raw: np.ndarray) -> dict:
    baseline = basic_metrics(y, pred)
    seed_rows: list[dict] = []
    preds: list[np.ndarray] = []
    alphas: dict[str, list[float]] = {}
    for seed in SEEDS:
        corrected, chosen = fivefold_predictions(y, pred, z_raw, seed)
        preds.append(corrected)
        alphas[str(seed)] = chosen
        metrics = basic_metrics(y, corrected)
        seed_rows.append(
            {
                "seed": seed,
                "candidate": metrics,
                "delta_ccc": round(metrics["ccc"] - baseline["ccc"], 4),
                "delta_mae": round(metrics["mae"] - baseline["mae"], 4),
                "selected_alpha_per_outer_fold": chosen,
            }
        )
        print(
            f"[S9 SCREEN] seed={seed} corrected CCC={metrics['ccc']:.4f} "
            f"delta={metrics['ccc'] - baseline['ccc']:+.4f}"
        )
    ensemble_pred = np.mean(np.vstack(preds), axis=0)
    ensemble = basic_metrics(y, ensemble_pred)
    deltas = np.array([row["delta_ccc"] for row in seed_rows], dtype=float)
    return {
        "baseline": baseline,
        "seed_summaries": seed_rows,
        "seed_mean_delta_ccc": round(float(np.mean(deltas)), 4),
        "seed_delta_std": round(float(np.std(deltas, ddof=1)), 4),
        "ensemble_summary": {
            "candidate": ensemble,
            "delta_ccc": round(ensemble["ccc"] - baseline["ccc"], 4),
            "delta_mae": round(ensemble["mae"] - baseline["mae"], 4),
            "bootstrap": paired_bootstrap(y, pred, ensemble_pred),
        },
        "ensemble_pred": ensemble_pred,
        "predictions_by_seed": preds,
        "selected_alphas": alphas,
    }


def main() -> None:
    sids, y_base, pred_base, z_base, z_names = load_aligned()
    print(f"[S9 SCREEN] N={len(sids)}, z_cols={len(z_names)} {z_names}")
    core = screen_core(y_base, pred_base, z_base)
    gate = {
        "mean_seed_delta_ccc_min": 0.025,
        "seed_delta_std_max": 0.020,
        "ensemble_bootstrap_frac_positive_min": 0.95,
        "max_material_mae_degradation": 0.05,
        "gate_pass": bool(
            core["seed_mean_delta_ccc"] >= 0.025
            and core["seed_delta_std"] < 0.020
            and core["ensemble_summary"]["bootstrap"]["frac_positive"] >= 0.95
            and core["ensemble_summary"]["delta_mae"] <= 0.05
        ),
    }
    verdict = (
        "SCREEN_PASS_PROMOTE_TO_SINGLE_PREREG_LOOCV"
        if gate["gate_pass"]
        else "SCREEN_FAIL_NO_LOOCV"
    )

    null_results: dict[str, dict] = {}
    for mode in ("scrambled_y", "sid_shuffle"):
        print(f"[S9 SCREEN NULL] {mode}")
        y_n, pred_n, z_n = apply_null(y_base, pred_base, z_base, mode)
        null_core = screen_core(y_n, pred_n, z_n)
        null_results[mode] = {
            "baseline": null_core["baseline"],
            "seed_mean_delta_ccc": null_core["seed_mean_delta_ccc"],
            "seed_delta_std": null_core["seed_delta_std"],
            "ensemble_summary": null_core["ensemble_summary"],
        }
    null_results["retrieval_library_test_exclusion"] = {
        "status": "enforced_by_construction",
        "rationale": (
            "Prototype medoids are selected after splitting and only from train "
            "indices in each outer/inner fold; held-out rows are never eligible "
            "for the prototype library."
        ),
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "name": "screen_t1_S9_topofractal_prototype",
        "created_at_utc": ts,
        "preregistration_source": str(PREREG.relative_to(ROOT)),
        "proposal_source": "/tmp/pro-results.txt rank #9",
        "screen_only": True,
        "n": int(len(sids)),
        "z_names": z_names,
        "n_prototypes": N_PROTOTYPES,
        "prototype_policy": "train-fold residual-quantile medoids in fold-local normalized TopoFractal state",
        "alpha_grid": list(ALPHA_GRID),
        "correction_cap_frac": CORRECTION_CAP_FRAC,
        "seeds": list(SEEDS),
        "baseline": core["baseline"],
        "seed_summaries": core["seed_summaries"],
        "seed_mean_delta_ccc": core["seed_mean_delta_ccc"],
        "seed_delta_std": core["seed_delta_std"],
        "ensemble_summary": core["ensemble_summary"],
        "promotion_gate": gate,
        "null_results": null_results,
        "verdict": verdict,
    }
    out_json = ROOT / "results" / f"screen_t1_S9_topofractal_prototype_{ts}.json"
    out_json.write_text(json.dumps(out, indent=2))
    out_npz = ROOT / "results" / f"screen_t1_S9_topofractal_prototype_{ts}.npz"
    np.savez(
        out_npz,
        sids=sids,
        y_t1=y_base,
        iter34_t1_pred=pred_base,
        t1_corrected_5fold_ensemble=core["ensemble_pred"],
        **{
            f"t1_corrected_5fold_seed_{seed}": pred
            for seed, pred in zip(SEEDS, core["predictions_by_seed"])
        },
    )
    print(
        f"[S9 SCREEN] verdict={verdict}, "
        f"ensemble_delta={core['ensemble_summary']['delta_ccc']:+.4f}, "
        f"frac>0={core['ensemble_summary']['bootstrap']['frac_positive']:.4f}"
    )
    print(f"[S9 SCREEN] Wrote {out_json.relative_to(ROOT)}")
    print(f"[S9 SCREEN] Wrote {out_npz.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

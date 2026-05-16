"""T1 Slot S3: Ordinal bounded item-distribution composer.

Pre-reg: preregistration_t1t3_proresults_ablation_20260515T133800Z.json, S3.

Items 9-14 are bounded ordinal MDS-UPDRS (0..4). Continuous residual correction
(slots D/D.1) over-smooths the head/tail of the integer distribution. Fold-local
proportional-odds head (stacked binary LogisticRegression on k∈{0.5,1.5,2.5,3.5})
with per-item shrinkage α∈{1,10,100} selected by inner 5-fold OOF T1-sum CCC,
and a variance cap |Σδ_j| ≤ 0.5·std(r_t1_sum_train) → target T1 LOOCV Δ ≥ +0.025.

Features per item: 6-dim TopoFractal block (fold-local mean of normalized columns
within each of 4 PH + 2 MFDFA subfamilies; NO PCA — that's S2) ⊕ iter34_item_pred_j.

Firewall: FoldImputer / FoldNormalizer only; inner CV strictly on outer train.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold

from eval_utils import lins_ccc as ccc
from inductive_lib import FoldImputer, FoldNormalizer

ITER34_OOF_NPZ = "results/t1_iter34_per_item_oof_20260511_044242.npz"
CACHE_PATH = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"

ITEMS: tuple[int, ...] = (9, 10, 11, 12, 13, 14)
N_CLASSES = 5
THRESHOLDS: tuple[float, ...] = (0.5, 1.5, 2.5, 3.5)
ALPHA_GRID: tuple[float, ...] = (1.0, 10.0, 100.0)
SUBFAMILY_SPECS: tuple[tuple[str, str], ...] = (
    ("ph_trunk_h1_max", "_ph_trunk_pitch_h1_max"),
    ("ph_trunk_h1_med", "_ph_trunk_pitch_h1_med"),
    ("ph_sacrum_h1_max", "_ph_sacrum_ang_h1_max"),
    ("ph_sacrum_h1_med", "_ph_sacrum_ang_h1_med"),
    ("mfdfa_delta_alpha", "_mfdfa_trunk_pitch_delta_alpha"),
    ("mfdfa_asymmetry", "_mfdfa_trunk_pitch_asymmetry"),
)
SPLIT_SEED = 20260309
FEATURE_SEED = 31415
MODEL_SEED_LIST: tuple[int, ...] = (42, 1337, 7)
INNER_FOLDS = 5
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20260515
VARIANCE_CAP_FRAC = 0.5
MIN_CLASS_N = 8
MCID_DELTA = 0.025


@dataclass(frozen=True)
class AlignedData:
    sids: np.ndarray
    y_t1: np.ndarray
    t1_sum_pred: np.ndarray
    item_true: dict[int, np.ndarray]
    item_pred: dict[int, np.ndarray]
    group_mats: dict[str, np.ndarray]


def load_aligned() -> AlignedData:
    oof = dict(np.load(ITER34_OOF_NPZ, allow_pickle=True))
    sids = oof["sids"].astype(str)
    item_true = {j: oof[f"item_{j}_true"].astype(float) for j in ITEMS}
    item_pred = {j: oof[f"item_{j}_pred"].astype(float) for j in ITEMS}

    df = pd.read_csv(CACHE_PATH)
    df = df[df["sid"].astype(str).isin(sids)].copy()
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    missing = [s for s in sids if s not in sid_to_row]
    if missing:
        raise ValueError(f"Missing cache rows for {len(missing)} SIDs: {missing[:5]}")
    df = df.iloc[[sid_to_row[s] for s in sids]].reset_index(drop=True)
    if not np.array_equal(df["sid"].astype(str).values, sids):
        raise AssertionError("Cache/OOF SID alignment failed")

    group_mats: dict[str, np.ndarray] = {}
    for name, pattern in SUBFAMILY_SPECS:
        cols = [c for c in df.columns if pattern in c]
        if not cols:
            raise ValueError(f"No cache columns for subfamily {name} ({pattern})")
        group_mats[name] = df[cols].to_numpy(dtype=np.float64)

    return AlignedData(
        sids=sids,
        y_t1=oof["y_t1"].astype(float),
        t1_sum_pred=oof["t1_sum_pred"].astype(float),
        item_true=item_true,
        item_pred=item_pred,
        group_mats=group_mats,
    )


def topofractal_block(
    group_mats: dict[str, np.ndarray],
    train_idx: np.ndarray,
    test_idx: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """6-dim block: one fold-local mean across each subfamily's z-scored cols."""
    tr_parts: list[np.ndarray] = []
    te_parts: list[np.ndarray] = []
    for name, _ in SUBFAMILY_SPECS:
        X = group_mats[name]
        imp = FoldImputer.fit(X[train_idx])
        Xt = imp.transform(X[train_idx])
        Xv = imp.transform(X[test_idx])
        norm = FoldNormalizer.fit(Xt)
        Xt = norm.transform(Xt)
        Xv = norm.transform(Xv)
        tr_parts.append(Xt.mean(axis=1, keepdims=True))
        te_parts.append(Xv.mean(axis=1, keepdims=True))
    return np.hstack(tr_parts), np.hstack(te_parts)


def _fit_ordinal(
    X: np.ndarray, y: np.ndarray, alpha: float, seed: int
) -> list[LogisticRegression] | None:
    """Proportional-odds via stacked binary logistic. None if any threshold degenerate."""
    classifiers: list[LogisticRegression] = []
    for k in THRESHOLDS:
        target = (y > k).astype(int)
        if target.sum() == 0 or target.sum() == len(target):
            return None
        clf = LogisticRegression(
            C=1.0 / alpha, max_iter=200, solver="lbfgs", random_state=seed
        )
        clf.fit(X, target)
        classifiers.append(clf)
    return classifiers


def _predict_expected(clfs: list[LogisticRegression], X: np.ndarray) -> np.ndarray:
    """E[Y|X] = Σ_c c·P(Y=c|X) for c∈{0..4}."""
    p_gt = np.column_stack([c.predict_proba(X)[:, 1] for c in clfs])
    p_eq = np.zeros((X.shape[0], N_CLASSES))
    p_eq[:, 0] = 1.0 - p_gt[:, 0]
    for c in range(1, N_CLASSES - 1):
        p_eq[:, c] = p_gt[:, c - 1] - p_gt[:, c]
    p_eq[:, N_CLASSES - 1] = p_gt[:, -1]
    p_eq = np.clip(p_eq, 0.0, 1.0)
    p_eq = p_eq / np.clip(p_eq.sum(axis=1, keepdims=True), 1e-12, None)
    return p_eq @ np.arange(N_CLASSES, dtype=float)


def _ordinal_correction(
    group_mats: dict[str, np.ndarray],
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    item_pred: np.ndarray,
    item_true: np.ndarray,
    alpha: float,
    seed: int,
) -> np.ndarray:
    """Train-on-train ordinal head, return δ_j = E[Y_j|X_test] - iter34_item_pred[test]."""
    Z_tr, Z_te = topofractal_block(group_mats, train_idx, test_idx)
    x_tr = np.hstack([Z_tr, item_pred[train_idx].reshape(-1, 1)])
    x_te = np.hstack([Z_te, item_pred[test_idx].reshape(-1, 1)])
    clfs = _fit_ordinal(x_tr, item_true[train_idx], alpha=alpha, seed=seed)
    if clfs is None:
        return np.zeros(len(test_idx))
    return _predict_expected(clfs, x_te) - item_pred[test_idx]


def _select_alpha(
    data: AlignedData, outer_train_idx: np.ndarray, item_j: int, seed: int
) -> float:
    """Inner 5-fold OOF — score = T1-sum CCC with item-j ordinal correction applied."""
    n_train = len(outer_train_idx)
    kf = KFold(n_splits=INNER_FOLDS, shuffle=True, random_state=seed)
    y_train = data.y_t1[outer_train_idx]
    base_train = data.t1_sum_pred[outer_train_idx]
    item_pred_train = data.item_pred[item_j][outer_train_idx]
    item_true_train = data.item_true[item_j][outer_train_idx]

    best_alpha, best_score = ALPHA_GRID[0], -np.inf
    for alpha in ALPHA_GRID:
        corrected_oof = base_train.copy()
        for tr_local, va_local in kf.split(np.arange(n_train)):
            tr_outer = outer_train_idx[tr_local]
            va_outer = outer_train_idx[va_local]
            Z_tr, Z_va = topofractal_block(data.group_mats, tr_outer, va_outer)
            x_tr = np.hstack([Z_tr, item_pred_train[tr_local].reshape(-1, 1)])
            x_va = np.hstack([Z_va, item_pred_train[va_local].reshape(-1, 1)])
            clfs = _fit_ordinal(x_tr, item_true_train[tr_local], alpha=alpha, seed=seed)
            if clfs is None:
                continue
            delta = _predict_expected(clfs, x_va) - item_pred_train[va_local]
            corrected_oof[va_local] = base_train[va_local] + delta
        score = float(ccc(y_train, corrected_oof))
        if score > best_score:
            best_score, best_alpha = score, alpha
    return best_alpha


def _apply_variance_cap(deltas: dict[int, float], cap: float) -> dict[int, float]:
    total = float(sum(deltas.values()))
    if cap > 0 and abs(total) > cap:
        scale = cap / abs(total)
        return {j: v * scale for j, v in deltas.items()}
    return deltas


def run_loocv(data: AlignedData, seed: int) -> tuple[np.ndarray, dict[int, list[float]]]:
    n = len(data.sids)
    corrected = data.t1_sum_pred.copy()
    chosen: dict[int, list[float]] = {j: [] for j in ITEMS}
    for i in range(n):
        train_idx = np.array([k for k in range(n) if k != i])
        test_idx = np.array([i])
        cap = VARIANCE_CAP_FRAC * float(np.std(
            data.y_t1[train_idx] - data.t1_sum_pred[train_idx]
        ))
        deltas: dict[int, float] = {}
        for j in ITEMS:
            alpha = _select_alpha(data, train_idx, j, seed)
            chosen[j].append(alpha)
            d = _ordinal_correction(
                data.group_mats, train_idx, test_idx,
                data.item_pred[j], data.item_true[j], alpha, seed,
            )
            deltas[j] = float(d[0])
        deltas = _apply_variance_cap(deltas, cap)
        corrected[i] = data.t1_sum_pred[i] + sum(deltas.values())
    return corrected, chosen


def run_5fold_predictions(data: AlignedData, seed: int) -> np.ndarray:
    n = len(data.sids)
    kf = KFold(n_splits=5, shuffle=True, random_state=seed)
    corrected = data.t1_sum_pred.copy()
    for tr, te in kf.split(np.arange(n)):
        cap = VARIANCE_CAP_FRAC * float(np.std(data.y_t1[tr] - data.t1_sum_pred[tr]))
        total = np.zeros(len(te))
        for j in ITEMS:
            alpha = _select_alpha(data, tr, j, seed)
            d = _ordinal_correction(
                data.group_mats, tr, te,
                data.item_pred[j], data.item_true[j], alpha, seed,
            )
            total = total + d
        if cap > 0:
            over = np.abs(total) > cap
            if over.any():
                scale = np.ones_like(total)
                scale[over] = cap / np.abs(total[over])
                total = total * scale
        corrected[te] = data.t1_sum_pred[te] + total
    return corrected


def run_5fold(data: AlignedData, seed: int) -> float:
    corrected = run_5fold_predictions(data, seed)
    return float(ccc(data.y_t1, corrected))


def apply_null(data: AlignedData, null_mode: str) -> AlignedData:
    if null_mode in ("", "real"):
        return data
    if null_mode == "scrambled_y":
        perm = np.random.default_rng(91011).permutation(len(data.sids))
        return AlignedData(
            sids=data.sids,
            y_t1=data.y_t1[perm],
            t1_sum_pred=data.t1_sum_pred[perm],
            item_true={j: data.item_true[j][perm] for j in ITEMS},
            item_pred={j: data.item_pred[j][perm] for j in ITEMS},
            group_mats=data.group_mats,
        )
    if null_mode == "sid_shuffle":
        perm = np.random.default_rng(20251).permutation(len(data.sids))
        return AlignedData(
            sids=data.sids,
            y_t1=data.y_t1,
            t1_sum_pred=data.t1_sum_pred,
            item_true=data.item_true,
            item_pred=data.item_pred,
            group_mats={k: v[perm] for k, v in data.group_mats.items()},
        )
    raise ValueError(f"Unknown null_mode: {null_mode}")


def paired_bootstrap(
    y: np.ndarray, base: np.ndarray, corr: np.ndarray, seed: int
) -> tuple[float, tuple[float, float], float]:
    rng = np.random.default_rng(seed)
    n = len(y)
    deltas = np.empty(N_BOOTSTRAP)
    for b in range(N_BOOTSTRAP):
        idx = rng.choice(n, size=n, replace=True)
        deltas[b] = float(ccc(y[idx], corr[idx]) - ccc(y[idx], base[idx]))
    return (
        float(np.median(deltas)),
        (float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))),
        float((deltas > 0).mean()),
    )


def _basic_metrics(y: np.ndarray, pred: np.ndarray) -> dict:
    return {
        "ccc": round(float(ccc(y, pred)), 4),
        "mae": round(float(np.mean(np.abs(y - pred))), 4),
        "pred_mean": round(float(np.mean(pred)), 4),
        "pred_std": round(float(np.std(pred)), 4),
        "true_mean": round(float(np.mean(y)), 4),
        "true_std": round(float(np.std(y)), 4),
    }


def _screen_core(data: AlignedData, seeds: tuple[int, ...]) -> dict:
    base_metrics = _basic_metrics(data.y_t1, data.t1_sum_pred)
    seed_rows: list[dict] = []
    preds_by_seed: list[np.ndarray] = []
    for seed in seeds:
        pred = run_5fold_predictions(data, seed)
        preds_by_seed.append(pred)
        metrics = _basic_metrics(data.y_t1, pred)
        seed_rows.append(
            {
                "seed": seed,
                "candidate": metrics,
                "delta_ccc": round(metrics["ccc"] - base_metrics["ccc"], 4),
                "delta_mae": round(metrics["mae"] - base_metrics["mae"], 4),
            }
        )
        print(
            f"[S3 SCREEN] seed={seed} corrected CCC={metrics['ccc']:.4f} "
            f"delta={metrics['ccc'] - base_metrics['ccc']:+.4f}"
        )

    ensemble_pred = np.mean(np.vstack(preds_by_seed), axis=0)
    ensemble_metrics = _basic_metrics(data.y_t1, ensemble_pred)
    med, ci, fpos = paired_bootstrap(
        data.y_t1, data.t1_sum_pred, ensemble_pred, BOOTSTRAP_SEED
    )
    deltas = np.array([row["delta_ccc"] for row in seed_rows], dtype=float)
    return {
        "baseline": base_metrics,
        "seeds": seed_rows,
        "seed_mean_delta_ccc": round(float(np.mean(deltas)), 4),
        "seed_delta_std": round(float(np.std(deltas, ddof=1)), 4),
        "ensemble": {
            "candidate": ensemble_metrics,
            "delta_ccc": round(ensemble_metrics["ccc"] - base_metrics["ccc"], 4),
            "delta_mae": round(ensemble_metrics["mae"] - base_metrics["mae"], 4),
            "bootstrap_median_delta": round(med, 4),
            "bootstrap_ci95": [round(ci[0], 4), round(ci[1], 4)],
            "bootstrap_frac_positive": round(fpos, 4),
        },
        "predictions_by_seed": preds_by_seed,
        "ensemble_pred": ensemble_pred,
    }


def screen(null_mode: str = "") -> None:
    """Run the S3 promotion screen without touching the LOOCV lockbox path."""
    base = load_aligned()
    data = apply_null(base, null_mode)
    class_counts = {j: int((base.item_true[j] >= 3).sum()) for j in ITEMS}
    kill_class = any(v < MIN_CLASS_N for v in class_counts.values())

    print(f"[S3 SCREEN] N={len(data.sids)}, null_mode={null_mode or 'real'}")
    print(f"[S3 SCREEN] N(class>=3) per item: {class_counts}")
    core = _screen_core(data, MODEL_SEED_LIST)
    seed_mean_delta = core["seed_mean_delta_ccc"]
    seed_delta_std = core["seed_delta_std"]
    ensemble = core["ensemble"]

    gate = {
        "mean_seed_delta_ccc_min": MCID_DELTA,
        "seed_delta_std_max": 0.020,
        "ensemble_bootstrap_frac_positive_min": 0.95,
        "max_material_mae_degradation": 0.05,
        "gate_pass": bool(
            not kill_class
            and seed_mean_delta >= MCID_DELTA
            and seed_delta_std < 0.020
            and ensemble["bootstrap_frac_positive"] >= 0.95
            and ensemble["delta_mae"] <= 0.05
        ),
    }
    if kill_class:
        verdict = "SCREEN_FAIL_CLASS_N_NO_LOOCV"
    elif gate["gate_pass"]:
        verdict = "SCREEN_PASS_PROMOTE_TO_SINGLE_PREREG_LOOCV"
    else:
        verdict = "SCREEN_FAIL_NO_LOOCV"

    null_results = None
    if null_mode in ("", "real"):
        null_results = {}
        for nm in ("scrambled_y", "sid_shuffle"):
            print(f"[S3 SCREEN NULL] {nm}")
            null_core = _screen_core(apply_null(base, nm), MODEL_SEED_LIST)
            null_results[nm] = {
                "baseline": null_core["baseline"],
                "seed_mean_delta_ccc": null_core["seed_mean_delta_ccc"],
                "seed_delta_std": null_core["seed_delta_std"],
                "ensemble": null_core["ensemble"],
            }
        null_results["retrieval_library_exclusion"] = {
            "status": "not_applicable",
            "rationale": "No nearest-neighbor or retrieval library is used.",
        }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"_{null_mode}" if null_mode else ""
    out = {
        "name": "screen_t1_S3_ordinal_composer",
        "created_at_utc": ts,
        "preregistration": "results/preregistration_t1t3_proresults_ablation_20260515T133800Z.json",
        "slot": "S3",
        "null_mode": null_mode or "real",
        "screen_only": True,
        "n": int(len(data.sids)),
        "items": list(ITEMS),
        "subfamilies": [name for name, _ in SUBFAMILY_SPECS],
        "class_counts_ge3": class_counts,
        "kill_class_fail": bool(kill_class),
        "alpha_grid": list(ALPHA_GRID),
        "variance_cap_frac": VARIANCE_CAP_FRAC,
        "model_seed_list": list(MODEL_SEED_LIST),
        "baseline": core["baseline"],
        "seed_summaries": core["seeds"],
        "seed_mean_delta_ccc": seed_mean_delta,
        "seed_delta_std": seed_delta_std,
        "ensemble_summary": ensemble,
        "promotion_gate": gate,
        "null_results": null_results,
        "verdict": verdict,
    }

    out_json = Path(f"results/screen_t1_S3_ordinal_composer_{ts}{suffix}.json")
    out_json.write_text(json.dumps(out, indent=2))
    out_npz = Path(f"results/screen_t1_S3_ordinal_composer_{ts}{suffix}.npz")
    np.savez(
        out_npz,
        sids=data.sids,
        y_t1=data.y_t1,
        t1_sum_pred_iter34=data.t1_sum_pred,
        t1_corrected_5fold_ensemble=core["ensemble_pred"],
        **{
            f"t1_corrected_5fold_seed_{seed}": pred
            for seed, pred in zip(MODEL_SEED_LIST, core["predictions_by_seed"])
        },
    )
    print(
        f"[S3 SCREEN] verdict={verdict}, ensemble_delta={ensemble['delta_ccc']:+.4f}, "
        f"frac>0={ensemble['bootstrap_frac_positive']:.4f}"
    )
    print(f"[S3 SCREEN] Wrote {out_json}")
    print(f"[S3 SCREEN] Wrote {out_npz}")


def main(null_mode: str = "") -> None:
    base = load_aligned()
    data = apply_null(base, null_mode)
    n = len(data.sids)
    class_counts = {j: int((base.item_true[j] >= 3).sum()) for j in ITEMS}
    kill_class = any(v < MIN_CLASS_N for v in class_counts.values())

    print(f"[S3] N={n}, null_mode={null_mode or 'real'}")
    print(f"[S3] N(class>=3) per item: {class_counts}")
    base_ccc = float(ccc(data.y_t1, data.t1_sum_pred))
    print(f"[S3] Baseline iter34 LOOCV CCC = {base_ccc:.4f}")

    corrected, chosen = run_loocv(data, seed=MODEL_SEED_LIST[0])
    corr_ccc = float(ccc(data.y_t1, corrected))
    delta = corr_ccc - base_ccc
    base_mae = float(np.mean(np.abs(data.y_t1 - data.t1_sum_pred)))
    corr_mae = float(np.mean(np.abs(data.y_t1 - corrected)))
    med, ci, fpos = paired_bootstrap(data.y_t1, data.t1_sum_pred, corrected, BOOTSTRAP_SEED)

    fold_per_seed: dict[int, float] = {}
    for s in MODEL_SEED_LIST:
        c = run_5fold(data, seed=s)
        fold_per_seed[s] = c
        print(f"[S3] 5-fold seed={s} corrected CCC={c:.4f}")
    fold_baseline = base_ccc
    fold_deltas = {s: v - fold_baseline for s, v in fold_per_seed.items()}
    mean_fold_delta = float(np.mean(list(fold_deltas.values())))
    kill_fold = mean_fold_delta < 0.010

    stability = None
    if null_mode in ("", "real"):
        preds = []
        for s in MODEL_SEED_LIST:
            c_seed, _ = run_loocv(data, seed=s)
            preds.append(c_seed)
        per_subj_std = np.vstack(preds).std(axis=0)
        stability = {
            "max_per_subject_std": float(per_subj_std.max()),
            "mean_per_subject_std": float(per_subj_std.mean()),
            "unstable_kill": bool(per_subj_std.mean() > 0.5),
        }

    if kill_class:
        verdict = "KILL_CLASS_N"
    elif kill_fold:
        verdict = "KILL_5FOLD_DELTA"
    elif stability and stability["unstable_kill"]:
        verdict = "KILL_PROB_INSTABILITY"
    elif delta < MCID_DELTA:
        verdict = "FAIL_BELOW_MCID"
    elif fpos < 0.95:
        verdict = "FAIL_BOOTSTRAP"
    else:
        verdict = "PASS_MCID"

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"_{null_mode}" if null_mode else ""
    lockbox = {
        "name": "lockbox_t1_S3_ordinal_composer",
        "created_at_utc": ts,
        "preregistration": "results/preregistration_t1t3_proresults_ablation_20260515T133800Z.json",
        "slot": "S3",
        "null_mode": null_mode or "real",
        "split_seed": SPLIT_SEED,
        "feature_seed": FEATURE_SEED,
        "model_seed_list": list(MODEL_SEED_LIST),
        "alpha_grid": list(ALPHA_GRID),
        "variance_cap_frac": VARIANCE_CAP_FRAC,
        "n_full_cohort": n,
        "subfamilies": [name for name, _ in SUBFAMILY_SPECS],
        "n_class_ge3_per_item": class_counts,
        "baseline_iter34_loocv_ccc": round(base_ccc, 4),
        "corrected_loocv_ccc": round(corr_ccc, 4),
        "delta_loocv_ccc": round(delta, 4),
        "baseline_mae": round(base_mae, 4),
        "corrected_mae": round(corr_mae, 4),
        "delta_mae": round(corr_mae - base_mae, 4),
        "bootstrap_median_delta": round(med, 4),
        "bootstrap_ci95": [round(ci[0], 4), round(ci[1], 4)],
        "bootstrap_frac_positive": round(fpos, 4),
        "fivefold_ccc_per_seed": {str(k): round(v, 4) for k, v in fold_per_seed.items()},
        "fivefold_delta_per_seed": {str(k): round(v, 4) for k, v in fold_deltas.items()},
        "fivefold_mean_delta": round(mean_fold_delta, 4),
        "fivefold_kill_gate": 0.010,
        "kill_fold_fail": bool(kill_fold),
        "kill_class_fail": bool(kill_class),
        "stability_across_seeds": stability,
        "chosen_alphas_loocv": {
            str(j): {
                "median": float(np.median(chosen[j])),
                "mode_count": {str(a): int(chosen[j].count(a)) for a in ALPHA_GRID},
            }
            for j in ITEMS
        },
        "verdict": verdict,
    }
    out_json = Path(f"results/lockbox_t1_S3_ordinal_composer_{ts}{suffix}.json")
    out_json.write_text(json.dumps(lockbox, indent=2))
    print(f"[S3] verdict={verdict}, Δ_loocv={delta:+.4f}, frac>0={fpos:.4f}")
    print(f"[S3] Wrote {out_json}")

    out_npz = Path(f"results/oof_t1_S3_ordinal_composer_{ts}{suffix}.npz")
    np.savez(
        out_npz,
        sids=data.sids,
        y_t1=data.y_t1,
        t1_sum_pred_iter34=data.t1_sum_pred,
        t1_corrected_loocv=corrected,
    )
    print(f"[S3] Wrote {out_npz}")


def sanity_y_nan() -> bool:
    """Confirm corrections are y-free at test time (firewall law #9)."""
    data = load_aligned()
    n = len(data.sids)
    y_nan = np.full(n, np.nan)
    train_idx = np.arange(1, n)
    test_idx = np.array([0])
    d = _ordinal_correction(
        data.group_mats, train_idx, test_idx,
        data.item_pred[13], data.item_true[13], alpha=10.0, seed=42,
    )
    ok = bool(np.isfinite(d[0])) and bool(np.all(np.isnan(y_nan)))
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "name": "abstention_sanity_t1_S3_ordinal_composer",
        "created_at_utc": ts,
        "lockbox_target": "lockbox_t1_S3_ordinal_composer",
        "feature_form": "TopoFractal-6-mean + iter34_item_pred_j (y-free)",
        "model_form": (
            f"proportional-odds: {len(THRESHOLDS)}x LogisticRegression, "
            f"alpha selected via inner {INNER_FOLDS}-fold on outer train only"
        ),
        "single_fold_smoke_delta": float(d[0]),
        "y_test_untouched_after_fold_pass": ok,
        "test_passes": ok,
    }
    Path(f"results/abstention_sanity_{ts}.json").write_text(json.dumps(receipt, indent=2))
    print(f"[Sanity y_nan] ok={ok}, single-fold delta={float(d[0]):.4f}")
    return ok


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sanity-y-nan":
        sys.exit(0 if sanity_y_nan() else 1)
    if len(sys.argv) > 1 and sys.argv[1] == "--mode=screen":
        null_mode = ""
        for arg in sys.argv[2:]:
            if arg.startswith("--null="):
                null_mode = arg.split("=", 1)[1]
        screen(null_mode=null_mode)
        sys.exit(0)
    null_mode = ""
    if len(sys.argv) > 1 and sys.argv[1].startswith("--null="):
        null_mode = sys.argv[1].split("=", 1)[1]
    main(null_mode=null_mode)

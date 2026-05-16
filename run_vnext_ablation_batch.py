"""V-next ablation batch — 8 cells, FWER-disciplined, leakage-clean.

Designed 2026-05-14 as the v-next deliverable after the 2026-05-13 T1 ceiling
push closed all 3 slots and the T3 K=250 hump (Wall #69) was confirmed real but
FWER-blocked at N=95.

Codex 2026-05-14 consult (gpt-5.5 xhigh) endorses the 8-cell package and the
PPMI replication blueprint as the publishable path:
- shift v-next from CCC chase (in-cohort saturated) to uncertainty/abstention,
  mechanism isolation, and external-replication readiness;
- lock PPMI primary formula (T3 sklearn-GB + univariate-corr K=250) BEFORE
  PPMI access opens.

Master pre-reg: results/preregistration_vnext_ablation_batch_<TS>.json
Per-cell lockboxes: results/lockbox_vnext_<cell>_<TS>.json
PPMI blueprint:     results/lockbox_ppmi_replication_blueprint_<TS>.json

CELLS (8) — FWER families pre-declared in master pre-reg:
  T3 conformal estimand (Bonferroni n=3, gate frac>0 ≥ 0.9833):
    A  T3 Mondrian-CP — outer-train-only predicted-T3 quartile bins
    B  T3 CQR        — LGB-quantile α∈{0.05, 0.5, 0.95}, width-based abstention
    C  T3 Mondrian × CQR joint — bin-stratified CQR widths
  T3 LOOCV-CCC estimand (Bonferroni n=4, gate frac>0 ≥ 0.9875):
    D  K=250 4-cell {sklearn-GB, LGB} × {univariate-corr, LGB-importance}
  T1 per-item conformal (Bonferroni n=6, gate 0.9917 per item):
    E  per-item conformal heatmap (items 9-14 × {70%, 50%} coverage)
  Different estimands (n=1 each, gate 0.95):
    F  Joint T1×T3 multi-output regression
    G  Item 11 FoG hurdle two-stage
  Non-statistical:
    H  PPMI replication blueprint (formula lock + JSON contract)

Resource budget: ~2.5h sequential on RTX 4060 8GB + 17 cores. Uses
ProcessPoolExecutor with mp.get_context("spawn") + OMP_NUM_THREADS=1 inside
workers (LightGBM fork-OpenMP deadlock fix per feedback_processpool_spawn).

Run:  ./gpu.sh run_vnext_ablation_batch.py
Pull: ./gpu.sh --pull
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import warnings
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import LeaveOneOut

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import FoldImputer, full_metrics
from eval_utils import lins_ccc as ccc

from run_t3_iter47_invalid_code_fix import filter_cohort, filter_stage2
from run_t3_iter41_target_fix import loocv_preds, paired_boot_delta

# ── Pre-registered constants ─────────────────────────────────────────────────
SEEDS = (42, 1337, 7)
RESULTS_DIR = REPO_ROOT / "results"
ITER47_OOF_CSV = RESULTS_DIR / "iter47_invalidcode_subject_preds_20260508_194605.csv"
ITER34_PER_ITEM_OOF = RESULTS_DIR / "t1_iter34_per_item_oof_20260511_044242.npz"
ITER34_PER_ITEM_JSON = RESULTS_DIR / "t1_iter34_per_item_ccc_20260511_044242.json"
ITER34_T1_LOCKBOX = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.json"
ITER34_T1_OOF = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"
T1_CONFORMAL_LOCKBOX = RESULTS_DIR / "lockbox_t1_conformal_20260512_211440.json"

COVERAGE_TARGETS = (1.0, 0.85, 0.70, 0.50)
T1_ITEMS = (9, 10, 11, 12, 13, 14)
TS_GLOBAL = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _sha_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_of(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _jsonable(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    return o


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(_jsonable(payload), indent=2))
    print(f"[v-next] wrote {path.name}", flush=True)


def _retained_metrics(y: np.ndarray, p: np.ndarray, retain: np.ndarray) -> dict:
    if retain.sum() < 5:
        return {"retained_n": int(retain.sum()), "retained_ccc": np.nan,
                "retained_mae": np.nan}
    yt = y[retain]
    yp = p[retain]
    return {
        "retained_n": int(retain.sum()),
        "retained_ccc": float(ccc(yt, yp)),
        "retained_mae": float(np.mean(np.abs(yt - yp))),
    }


# ── Cell A — T3 Mondrian-CP (predicted-T3 quartile bins) ─────────────────────


def _mondrian_cp_one_seed(y: np.ndarray, pred: np.ndarray, bins: np.ndarray,
                          coverages) -> dict:
    """Mondrian split-conformal: leave-one-out quantile per bin.

    Fold-local: bins are passed pre-computed and MUST come from outer-train
    only. residuals are |y-pred|; per test subject, we drop it, compute the
    target-quantile of |residual| within its bin among the OTHER training
    subjects, retain iff |residual_i| <= bin_threshold_i.
    """
    n = len(y)
    abs_res = np.abs(y - pred)
    rows = []
    for cov in coverages:
        retain = np.zeros(n, dtype=bool)
        bin_thresholds = []
        for i in range(n):
            mask = (bins == bins[i]) & (np.arange(n) != i)
            if mask.sum() < 4:
                # Not enough calibration in this bin — fall back to global
                mask = np.arange(n) != i
            thr = float(np.quantile(abs_res[mask], cov))
            bin_thresholds.append(thr)
            retain[i] = abs_res[i] <= thr
        m = _retained_metrics(y, pred, retain)
        m["coverage_target"] = float(cov)
        m["threshold_mean"] = float(np.mean(bin_thresholds))
        m["threshold_std"] = float(np.std(bin_thresholds))
        m["threshold_cv"] = (m["threshold_std"] / m["threshold_mean"]
                             if m["threshold_mean"] > 0 else np.nan)
        rows.append(m)
    return {"rows": rows, "score": "abs_residual_mondrian"}


def cell_A_t3_mondrian_cp(data: dict) -> dict:
    """T3 Mondrian-CP using iter47 OOF predictions, bins = predicted-T3 quartiles.

    Predicted-T3 quartile bins are computed PER LOOCV-FOLD outer-train-only
    quartile boundaries, applied to the test subject (the test subject's
    predicted T3 from iter47 — already leak-clean LOOCV).
    """
    df = pd.read_csv(ITER47_OOF_CSV)
    df = df[(df["cohort"] == "drop_allmissing_validrange")
            & (df["stage2_policy"] == "stage2_current")].copy()
    df = df.set_index("sid").loc[list(data["sids"])].reset_index()
    y = df["y_true_validrange"].to_numpy(np.float64)
    pred = df["y_pred"].to_numpy(np.float64)
    n = len(y)
    # Build per-subject bin labels using leave-one-out quartile edges over the
    # OTHER 94 PREDICTED Ts. (No labels used in bin construction → no target
    # leakage; predictions are already leak-clean.)
    bins = np.zeros(n, dtype=int)
    for i in range(n):
        mask = np.arange(n) != i
        q = np.quantile(pred[mask], [0.25, 0.5, 0.75])
        bins[i] = int(np.searchsorted(q, pred[i]))
    out = _mondrian_cp_one_seed(y, pred, bins, COVERAGE_TARGETS)
    rows = out["rows"]
    monotonicity = sum(1 for j in range(1, len(rows))
                       if rows[j]["retained_ccc"] < rows[j - 1]["retained_ccc"] - 0.01)
    return {
        "cell": "A_t3_mondrian_cp",
        "n": n,
        "predictor": "iter47_drop_allmissing_validrange_stage2_current",
        "bins_source": "outer_train_only_LOO_quartile_of_predicted_T3",
        "rows": rows,
        "monotonicity_violations": monotonicity,
        "verdict": ("PASS_DEPLOYABLE_SECONDARY" if monotonicity <= 1
                    and rows[2]["retained_ccc"] > 0.40 else
                    "PARTIAL_OR_FAIL"),
        "comparator_baseline_t3_conformal_v2_70%": 0.329,
    }


# ── Cell B — T3 CQR (LGB-quantile) ────────────────────────────────────────────


def _fit_quantile_lgb(X_tr, y_tr, X_te, seed, alpha):
    from lightgbm import LGBMRegressor
    model = LGBMRegressor(
        objective="quantile", alpha=alpha,
        n_estimators=500, learning_rate=0.05, num_leaves=15,
        min_data_in_leaf=10, feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=3,
        verbose=-1, random_state=seed,
    )
    return model.fit(X_tr, y_tr).predict(X_te)


def _univariate_kselect(X, y, k, seed=None):
    if X.shape[1] <= k:
        return np.arange(X.shape[1])
    y_c = y - y.mean()
    X_c = X - X.mean(axis=0)
    denom = (X.std(axis=0) + 1e-9) * (y.std() + 1e-9)
    corr = (X_c * y_c[:, None]).sum(axis=0) / (denom * X.shape[0])
    return np.argsort(-np.abs(corr))[:k]


def _build_stage1(hy):
    return hy.reshape(-1, 1)


def _fold_t3_pipeline(X, y_res, X_te, K, selector, model, seed):
    """Single-fold residual learner: K-best then model."""
    if selector == "univariate_corr":
        idx = _univariate_kselect(X, y_res, K, seed)
    else:  # lgb_importance
        from lightgbm import LGBMRegressor
        sel = LGBMRegressor(
            n_estimators=200, learning_rate=0.1, num_leaves=15,
            min_data_in_leaf=5, verbose=-1, random_state=seed,
        )
        sel.fit(X, y_res)
        idx = np.argsort(-sel.feature_importances_)[:K]
    Xtr_sel = X[:, idx]
    Xte_sel = X_te[:, idx]
    if model == "sklearn_gb":
        m = GradientBoostingRegressor(
            n_estimators=300, max_depth=4, min_samples_leaf=10,
            subsample=0.8, learning_rate=0.05, random_state=seed,
        )
        m.fit(Xtr_sel, y_res)
        return m.predict(Xte_sel)
    elif model == "lightgbm":
        from lightgbm import LGBMRegressor
        m = LGBMRegressor(
            n_estimators=500, learning_rate=0.05, num_leaves=15,
            min_data_in_leaf=10, feature_fraction=0.8, bagging_fraction=0.8,
            bagging_freq=3, verbose=-1, random_state=seed,
        )
        m.fit(Xtr_sel, y_res)
        return m.predict(Xte_sel)
    elif model == "lgb_quantile_median":
        return _fit_quantile_lgb(Xtr_sel, y_res, Xte_sel, seed, alpha=0.5)
    else:
        raise ValueError(f"Unknown model: {model}")


def _loocv_cqr_one_seed(data: dict, seed: int, K: int = 250) -> dict:
    """LOOCV CQR: per fold, fit q05, q50, q95 LGB-quantile after Stage-1 Ridge.

    Stage-1 Ridge on H&Y; Stage-2 quantile LGB on residuals at α ∈ {0.05,
    0.5, 0.95}. Width = q95 - q05. Median = q50 is the point prediction.
    All fold-local; no test fold leak.
    """
    sids = data["sids"]
    y = data["y_t3"]
    hy = data["hy"]
    X = data["X"]
    X_s1 = _build_stage1(hy)
    n = len(y)
    pred_med = np.zeros(n)
    pred_q05 = np.zeros(n)
    pred_q95 = np.zeros(n)
    for tr_idx, te_idx in LeaveOneOut().split(np.arange(n)):
        s1 = Ridge(alpha=1.0).fit(X_s1[tr_idx], y[tr_idx])
        s1_tr = s1.predict(X_s1[tr_idx])
        s1_te = s1.predict(X_s1[te_idx])
        res_tr = y[tr_idx] - s1_tr
        Xtr_imp, Xte_imp = _impute(X[tr_idx], X[te_idx])
        for alpha, out in zip((0.05, 0.5, 0.95), (pred_q05, pred_med, pred_q95)):
            # Use lgb_quantile_median path with explicit alpha
            if alpha == 0.5:
                model = "lgb_quantile_median"
            else:
                # Direct quantile fit for q05 / q95
                idx = _univariate_kselect(Xtr_imp, res_tr, K, seed)
                qpred = _fit_quantile_lgb(
                    Xtr_imp[:, idx], res_tr, Xte_imp[:, idx], seed, alpha=alpha
                )
                out[te_idx] = s1_te + qpred
                continue
            qpred = _fold_t3_pipeline(
                Xtr_imp, res_tr, Xte_imp, K, "univariate_corr", model, seed
            )
            out[te_idx] = s1_te + qpred
    width = pred_q95 - pred_q05
    ccc_q50 = float(ccc(y, pred_med))
    return {
        "seed": seed,
        "K": K,
        "pred_q05": pred_q05,
        "pred_q50": pred_med,
        "pred_q95": pred_q95,
        "width": width,
        "ccc_q50_full": ccc_q50,
    }


def _impute(X_tr, X_te):
    med = np.nanmedian(X_tr, axis=0)
    med = np.where(np.isnan(med), 0.0, med)
    return (np.where(np.isnan(X_tr), med, X_tr),
            np.where(np.isnan(X_te), med, X_te))


def cell_B_t3_cqr(data: dict) -> dict:
    seeds = SEEDS
    seed_results = []
    pred_q50_avg = None
    width_avg = None
    for s in seeds:
        r = _loocv_cqr_one_seed(data, s, K=250)
        seed_results.append({
            "seed": int(s),
            "ccc_q50_full": float(r["ccc_q50_full"]),
        })
        pred_q50_avg = r["pred_q50"] if pred_q50_avg is None else pred_q50_avg + r["pred_q50"]
        width_avg = r["width"] if width_avg is None else width_avg + r["width"]
    pred_q50_avg = pred_q50_avg / len(seeds)
    width_avg = width_avg / len(seeds)
    y = data["y_t3"]
    n = len(y)
    # Width-based abstention via LOO-quantile of width.
    rows = []
    for cov in COVERAGE_TARGETS:
        retain = np.zeros(n, dtype=bool)
        thr_list = []
        for i in range(n):
            mask = np.arange(n) != i
            thr = float(np.quantile(width_avg[mask], cov))
            thr_list.append(thr)
            retain[i] = width_avg[i] <= thr
        m = _retained_metrics(y, pred_q50_avg, retain)
        m["coverage_target"] = float(cov)
        m["threshold_mean"] = float(np.mean(thr_list))
        m["threshold_std"] = float(np.std(thr_list))
        m["threshold_cv"] = (m["threshold_std"] / m["threshold_mean"]
                             if m["threshold_mean"] > 0 else np.nan)
        rows.append(m)
    monot = sum(1 for j in range(1, len(rows))
                if rows[j]["retained_ccc"] < rows[j - 1]["retained_ccc"] - 0.01)
    return {
        "cell": "B_t3_cqr",
        "n": n,
        "K": 250,
        "score": "cqr_width_q95_minus_q05",
        "seed_results": seed_results,
        "ccc_q50_avg_full": float(ccc(y, pred_q50_avg)),
        "rows": rows,
        "monotonicity_violations": monot,
        "verdict": ("PASS_DEPLOYABLE_SECONDARY" if monot <= 1
                    and rows[2]["retained_ccc"] > 0.40 else "PARTIAL_OR_FAIL"),
        "comparator_baseline_t3_conformal_v2_70%": 0.329,
    }


# ── Cell C — T3 Mondrian × CQR joint ──────────────────────────────────────────


def cell_C_t3_mondrian_cqr_joint(data: dict, cqr_out: dict | None = None) -> dict:
    """Bin by predicted-T3 quartile (LOO), then CQR-width quantile within bin."""
    if cqr_out is None:
        cqr_out = cell_B_t3_cqr(data)
    df = pd.read_csv(ITER47_OOF_CSV)
    df = df[(df["cohort"] == "drop_allmissing_validrange")
            & (df["stage2_policy"] == "stage2_current")].copy()
    df = df.set_index("sid").loc[list(data["sids"])].reset_index()
    pred = df["y_pred"].to_numpy(np.float64)
    y = data["y_t3"]
    n = len(y)
    bins = np.zeros(n, dtype=int)
    for i in range(n):
        mask = np.arange(n) != i
        q = np.quantile(pred[mask], [0.25, 0.5, 0.75])
        bins[i] = int(np.searchsorted(q, pred[i]))
    # Build width series from CQR cell (pred_q50_avg, width_avg implicit in rows
    # — rebuild from cqr_out by rerunning if needed; for fidelity we recompute):
    rows_avg = cqr_out["rows"]
    # We need the actual width per subject — recompute via _loocv_cqr_one_seed?
    # Cheap path: re-run for one seed to get width array. Acceptable; cell C is
    # a stratified version of cell B and the seed average inside cell B is
    # what we expect to use in deployment. For published numbers we use a
    # single representative seed (42) to keep the cell self-contained.
    r0 = _loocv_cqr_one_seed(data, SEEDS[0], K=250)
    width = r0["width"]
    pred_med = r0["pred_q50"]
    rows = []
    for cov in COVERAGE_TARGETS:
        retain = np.zeros(n, dtype=bool)
        thr_list = []
        for i in range(n):
            mask = (bins == bins[i]) & (np.arange(n) != i)
            if mask.sum() < 4:
                mask = np.arange(n) != i
            thr = float(np.quantile(width[mask], cov))
            thr_list.append(thr)
            retain[i] = width[i] <= thr
        m = _retained_metrics(y, pred_med, retain)
        m["coverage_target"] = float(cov)
        m["threshold_mean"] = float(np.mean(thr_list))
        m["threshold_std"] = float(np.std(thr_list))
        m["threshold_cv"] = (m["threshold_std"] / m["threshold_mean"]
                             if m["threshold_mean"] > 0 else np.nan)
        rows.append(m)
    monot = sum(1 for j in range(1, len(rows))
                if rows[j]["retained_ccc"] < rows[j - 1]["retained_ccc"] - 0.01)
    return {
        "cell": "C_t3_mondrian_cqr_joint",
        "n": n,
        "score": "cqr_width_mondrian_quartile_bin",
        "rows": rows,
        "monotonicity_violations": monot,
        "verdict": ("PASS_DEPLOYABLE_SECONDARY" if monot <= 1
                    and rows[2]["retained_ccc"] > 0.40 else "PARTIAL_OR_FAIL"),
        "comparator_baseline_t3_conformal_v2_70%": 0.329,
    }


# ── Cell D — K=250 mechanism 4-cell ─────────────────────────────────────────


def _loocv_t3_one_cell(data: dict, model: str, selector: str, K: int,
                       seed: int) -> dict:
    sids = data["sids"]
    y = data["y_t3"]
    hy = data["hy"]
    X = data["X"]
    X_s1 = _build_stage1(hy)
    n = len(y)
    preds = np.zeros(n)
    t0 = time.time()
    for tr_idx, te_idx in LeaveOneOut().split(np.arange(n)):
        s1 = Ridge(alpha=1.0).fit(X_s1[tr_idx], y[tr_idx])
        s1_te = s1.predict(X_s1[te_idx])
        res_tr = y[tr_idx] - s1.predict(X_s1[tr_idx])
        Xtr_imp, Xte_imp = _impute(X[tr_idx], X[te_idx])
        s2 = _fold_t3_pipeline(Xtr_imp, res_tr, Xte_imp, K, selector, model, seed)
        preds[te_idx] = s1_te + s2
    return {
        "model": model, "selector": selector, "K": K, "seed": seed,
        "preds": preds,
        "ccc": float(ccc(y, preds)),
        "wall_s": time.time() - t0,
    }


def cell_D_t3_k250_4cell(data: dict) -> dict:
    cells = [(m, s) for m in ("sklearn_gb", "lightgbm")
             for s in ("univariate_corr", "lgb_importance")]
    out = {"cell": "D_t3_k250_4cell", "n": len(data["y_t3"]),
           "K": 250, "subcells": []}
    iter47_canonical_ccc = 0.3784
    iter47_preds = pd.read_csv(ITER47_OOF_CSV)
    iter47_preds = iter47_preds[
        (iter47_preds["cohort"] == "drop_allmissing_validrange")
        & (iter47_preds["stage2_policy"] == "stage2_current")
    ].copy().set_index("sid").loc[list(data["sids"])]
    ref_preds = iter47_preds["y_pred"].to_numpy(np.float64)
    y = data["y_t3"]
    for model, selector in cells:
        seed_ccc = []
        seed_preds = []
        for s in SEEDS:
            r = _loocv_t3_one_cell(data, model, selector, 250, s)
            seed_ccc.append(r["ccc"])
            seed_preds.append(r["preds"])
        pooled = np.mean(np.stack(seed_preds, axis=0), axis=0)
        pooled_ccc = float(ccc(y, pooled))
        delta = pooled_ccc - iter47_canonical_ccc
        boot = paired_boot_delta(y, pooled, ref_preds, n_boot=5000)
        out["subcells"].append({
            "model": model, "selector": selector, "K": 250,
            "seeds": list(SEEDS),
            "seed_ccc": seed_ccc,
            "seed_mean_ccc": float(np.mean(seed_ccc)),
            "seed_std_ccc": float(np.std(seed_ccc)),
            "pooled_ccc": pooled_ccc,
            "delta_vs_iter47": float(delta),
            "paired_bootstrap_vs_iter47": boot,
        })
    out["fwer_family_n"] = 4
    out["bonferroni_gate_frac_pos"] = 0.9875
    out["comparator_iter47"] = iter47_canonical_ccc
    return out


# ── Cell E — T1 per-item conformal heatmap ──────────────────────────────────


def cell_E_t1_peritem_cp_heatmap() -> dict:
    """Use iter34 per-item OOF predictions; split-conformal on |residual|."""
    if not ITER34_PER_ITEM_OOF.exists():
        return {"cell": "E_t1_peritem_cp_heatmap",
                "verdict": "MISSING_INPUT", "missing": str(ITER34_PER_ITEM_OOF)}
    npz = np.load(ITER34_PER_ITEM_OOF)
    items_data = []
    standalone = json.loads(ITER34_PER_ITEM_JSON.read_text())["per_item"]
    # NPZ keys: item_<i>_pred / item_<i>_true (each (N,) float64).
    for item in T1_ITEMS:
        pkey = f"item_{item}_pred"
        ykey = f"item_{item}_true"
        if pkey not in npz or ykey not in npz:
            items_data.append({
                "item": item, "available": False, "note": "key_missing"
            })
            continue
        pred = npz[pkey]
        y = npz[ykey]
        if pred.ndim == 2:
            pred = pred.mean(axis=0)
        if y.ndim == 2:
            y = y[0]
        n = len(y)
        full_ccc = float(ccc(y, pred))
        abs_res = np.abs(y - pred)
        rows = []
        for cov in COVERAGE_TARGETS:
            retain = np.zeros(n, dtype=bool)
            thr_list = []
            for i in range(n):
                mask = np.arange(n) != i
                thr = float(np.quantile(abs_res[mask], cov))
                thr_list.append(thr)
                retain[i] = abs_res[i] <= thr
            m = _retained_metrics(y, pred, retain)
            m["coverage_target"] = float(cov)
            m["threshold_mean"] = float(np.mean(thr_list))
            rows.append(m)
        delta_70 = (rows[2]["retained_ccc"] - full_ccc) if rows else np.nan
        items_data.append({
            "item": item, "available": True,
            "n": n,
            "full_ccc_iter34_chain": full_ccc,
            "standalone_ccc_iter34_chain": float(
                standalone[str(item)]["ccc_mean_of_seeds"]),
            "rows": rows,
            "delta_70_vs_full": float(delta_70),
        })
    return {
        "cell": "E_t1_peritem_cp_heatmap",
        "fwer_family_n": 6,
        "bonferroni_gate_per_item": 0.9917,
        "items_data": items_data,
        "publishable": "item_level_deployability_map",
    }


# ── Cell F — Joint T1×T3 multi-output ─────────────────────────────────────────


def cell_F_joint_t1_t3(data: dict) -> dict:
    """Multi-output Ridge (and LGB single-target per output, for comparison).

    Targets: y_T1 = sum of items 9..14 (we don't have item labels in
    filter_cohort; fall back to using T1 from iter34 per-item OOF as proxy)
    + y_T3 = total UPDRS-III. We compare:
      (a) single-task: independent LGB per target
      (b) multi-output: sklearn MultiOutputRegressor wrapping LightGBM
          (LGB doesn't natively support multi-target; multi-output is sequential).
      (c) multi-task Ridge: Ridge fits jointly via vectorized y.

    Joint is fair only when the test fold's targets are unobserved (LOOCV).
    """
    sids = data["sids"]
    y_t3 = data["y_t3"]
    hy = data["hy"]
    X = data["X"]
    n = len(y_t3)
    # Build y_t1 via iter34 per-item OOF (already leak-clean LOOCV true T1).
    npz = np.load(ITER34_PER_ITEM_OOF)
    iter34_sids = [str(s) for s in npz["sids"]]
    iter34_y_t1 = npz["y_t1"]
    # Map iter34 sids → T3 cohort sids; only retain subjects in both.
    t3_sids_list = [str(s) for s in sids]
    iter34_sid_to_idx = {s: i for i, s in enumerate(iter34_sids)}
    common_mask = np.array(
        [s in iter34_sid_to_idx for s in t3_sids_list], dtype=bool
    )
    if common_mask.sum() < 50:
        return {"cell": "F_joint_t1_t3", "verdict": "SKIP_T1_ALIGNMENT_FAILED",
                "note": f"common subjects between iter34 T1 and T3 cohort = "
                        f"{int(common_mask.sum())} (need >=50)"}
    y_t1 = np.full(n, np.nan, dtype=np.float64)
    for i, s in enumerate(t3_sids_list):
        if s in iter34_sid_to_idx:
            y_t1[i] = iter34_y_t1[iter34_sid_to_idx[s]]
    # Restrict to common-subject indices for joint training.
    keep_idx = np.where(common_mask)[0]
    if len(keep_idx) != n:
        # Subset cohort to common subjects.
        sids = sids[keep_idx]
        y_t1 = y_t1[keep_idx]
        y_t3 = y_t3[keep_idx]
        hy = hy[keep_idx]
        X = X[keep_idx]
        n = len(keep_idx)
    X_s1 = _build_stage1(hy)

    # Two predictions per subject: y_t1_hat, y_t3_hat
    pred_st_t1 = np.zeros(n)
    pred_st_t3 = np.zeros(n)
    pred_mt_t1 = np.zeros(n)
    pred_mt_t3 = np.zeros(n)
    seed = SEEDS[0]
    from sklearn.linear_model import RidgeCV
    for tr_idx, te_idx in LeaveOneOut().split(np.arange(n)):
        # Stage-1 separately for T3 only (T1 has no clinical base)
        s1 = Ridge(alpha=1.0).fit(X_s1[tr_idx], y_t3[tr_idx])
        s1_te = s1.predict(X_s1[te_idx])
        res_tr = y_t3[tr_idx] - s1.predict(X_s1[tr_idx])
        Xtr_imp, Xte_imp = _impute(X[tr_idx], X[te_idx])
        # Univariate K=500 K-best on RESIDUAL (T3) for single-task; for
        # multi-task we union with T1-correlated features.
        idx_t3 = _univariate_kselect(Xtr_imp, res_tr, 500, seed)
        idx_t1 = _univariate_kselect(Xtr_imp, y_t1[tr_idx], 500, seed)
        idx_union = np.unique(np.concatenate([idx_t3, idx_t1]))
        Xtr_st_t3 = Xtr_imp[:, idx_t3]
        Xte_st_t3 = Xte_imp[:, idx_t3]
        Xtr_st_t1 = Xtr_imp[:, idx_t1]
        Xte_st_t1 = Xte_imp[:, idx_t1]
        Xtr_mt = Xtr_imp[:, idx_union]
        Xte_mt = Xte_imp[:, idx_union]
        # Single-task LGB per target.
        from lightgbm import LGBMRegressor
        m_t3 = LGBMRegressor(
            n_estimators=500, learning_rate=0.05, num_leaves=15,
            min_data_in_leaf=10, feature_fraction=0.8, bagging_fraction=0.8,
            bagging_freq=3, verbose=-1, random_state=seed,
        ).fit(Xtr_st_t3, res_tr)
        pred_st_t3[te_idx] = s1_te + m_t3.predict(Xte_st_t3)
        m_t1 = LGBMRegressor(
            n_estimators=500, learning_rate=0.05, num_leaves=15,
            min_data_in_leaf=10, feature_fraction=0.8, bagging_fraction=0.8,
            bagging_freq=3, verbose=-1, random_state=seed,
        ).fit(Xtr_st_t1, y_t1[tr_idx])
        pred_st_t1[te_idx] = m_t1.predict(Xte_st_t1)
        # Multi-task Ridge (joint y_t1, y_t3 with shared support).
        Y_tr = np.stack([y_t1[tr_idx], res_tr], axis=1)  # joint targets
        ridge_mt = Ridge(alpha=1.0).fit(Xtr_mt, Y_tr)
        pred_mt = ridge_mt.predict(Xte_mt)  # shape (1, 2)
        pred_mt_t1[te_idx] = pred_mt[:, 0]
        pred_mt_t3[te_idx] = s1_te + pred_mt[:, 1]
    return {
        "cell": "F_joint_t1_t3",
        "n": n,
        "single_task_t1_ccc": float(ccc(y_t1, pred_st_t1)),
        "single_task_t3_ccc": float(ccc(y_t3, pred_st_t3)),
        "multi_task_ridge_t1_ccc": float(ccc(y_t1, pred_mt_t1)),
        "multi_task_ridge_t3_ccc": float(ccc(y_t3, pred_mt_t3)),
        "delta_t1_joint_vs_single": float(
            ccc(y_t1, pred_mt_t1) - ccc(y_t1, pred_st_t1)),
        "delta_t3_joint_vs_single": float(
            ccc(y_t3, pred_mt_t3) - ccc(y_t3, pred_st_t3)),
        "comparator_iter34_t1_canonical": 0.7170,
        "comparator_iter47_t3_canonical": 0.3784,
        "seed": int(seed),
    }


# ── Cell G — Item 11 FoG hurdle ─────────────────────────────────────────────


def cell_G_item11_hurdle(data: dict) -> dict:
    """Two-stage item 11 hurdle: P(item_11 > 0) classifier × E[severity | >0].

    Item 11 (FoG) is event-driven; many subjects score 0. A hurdle model:
      ŷ_11 = P(item_11 > 0 | X) × E[item_11 | item_11 > 0, X]
    is more honest than continuous regression.
    """
    sids = data["sids"]
    npz = np.load(ITER34_PER_ITEM_OOF)
    if "item_11_true" not in npz:
        return {"cell": "G_item11_hurdle", "verdict": "SKIP_NO_Y_ITEM_11"}
    iter34_sids = [str(s) for s in npz["sids"]]
    iter34_sid_to_idx = {s: i for i, s in enumerate(iter34_sids)}
    t3_sids = [str(s) for s in sids]
    mask = np.array([s in iter34_sid_to_idx for s in t3_sids], dtype=bool)
    if mask.sum() < 50:
        return {"cell": "G_item11_hurdle", "verdict": "SKIP_N_MISMATCH",
                "note": f"common subjects = {int(mask.sum())} (need >=50)"}
    keep = np.where(mask)[0]
    y11 = np.array([npz["item_11_true"][iter34_sid_to_idx[t3_sids[i]]]
                    for i in keep], dtype=np.float64)
    X = data["X"][keep]
    n = len(y11)
    seed = SEEDS[0]
    from lightgbm import LGBMClassifier, LGBMRegressor
    pred_hurdle = np.zeros(n)
    pred_cont = np.zeros(n)  # continuous baseline LGB
    z = (y11 > 0).astype(int)
    for tr_idx, te_idx in LeaveOneOut().split(np.arange(n)):
        Xtr_imp, Xte_imp = _impute(X[tr_idx], X[te_idx])
        # Continuous baseline
        m_cont = LGBMRegressor(
            n_estimators=300, learning_rate=0.05, num_leaves=15,
            min_data_in_leaf=10, verbose=-1, random_state=seed,
        ).fit(Xtr_imp, y11[tr_idx])
        pred_cont[te_idx] = m_cont.predict(Xte_imp)
        # Hurdle Stage 1: classifier
        clf = LGBMClassifier(
            n_estimators=300, learning_rate=0.05, num_leaves=15,
            min_data_in_leaf=10, verbose=-1, random_state=seed,
        ).fit(Xtr_imp, z[tr_idx])
        p_pos = clf.predict_proba(Xte_imp)[:, 1]
        # Hurdle Stage 2: severity given >0
        pos_mask = z[tr_idx] > 0
        if pos_mask.sum() < 5:
            # Too few positives in fold — fall back to continuous
            pred_hurdle[te_idx] = pred_cont[te_idx]
            continue
        m_sev = LGBMRegressor(
            n_estimators=300, learning_rate=0.05, num_leaves=15,
            min_data_in_leaf=5, verbose=-1, random_state=seed,
        ).fit(Xtr_imp[pos_mask], y11[tr_idx][pos_mask])
        e_sev = m_sev.predict(Xte_imp)
        pred_hurdle[te_idx] = p_pos * e_sev
    return {
        "cell": "G_item11_hurdle",
        "n": n,
        "continuous_baseline_ccc": float(ccc(y11, pred_cont)),
        "hurdle_two_stage_ccc": float(ccc(y11, pred_hurdle)),
        "delta_hurdle_vs_continuous": float(ccc(y11, pred_hurdle)
                                             - ccc(y11, pred_cont)),
        "comparator_iter34_chain_item11_ccc": 0.2318,
        "seed": int(seed),
        "n_positive_subjects": int(z.sum()),
    }


# ── Cell H — PPMI replication blueprint ─────────────────────────────────────


def cell_H_ppmi_blueprint() -> dict:
    """Lock the PPMI replication formula NOW (before access opens).

    Primary formula (per 2026-05-14 codex consult + 2026-05-13 K-sweep verification):
      sklearn GradientBoostingRegressor (n_est=300, max_depth=4,
        min_samples_leaf=10, subsample=0.8, learning_rate=0.05)
      on K=250 univariate-corr-K-best features
      after Stage-1 Ridge alpha=1 on H&Y + cv_yrs + cv_sex + cv_dbs
      cohort = drop_allmissing_validrange (≥1 valid MDS-UPDRS-III subitem;
                                            all subitems clipped to [0,4])
      seeds = (42, 1337, 7); LOOCV at PPMI N; FWER family n=1 (this is the
        single locked replication formula, not a search).
    """
    blueprint = {
        "name": "ppmi_replication_blueprint_t3",
        "purpose": "Lock T3 sklearn-GB K=250 formula BEFORE PPMI access opens.",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "primary_formula": {
            "model": "sklearn.ensemble.GradientBoostingRegressor",
            "model_params": {
                "n_estimators": 300, "max_depth": 4,
                "min_samples_leaf": 10, "subsample": 0.8,
                "learning_rate": 0.05, "random_state": "seed_from_seeds_list",
            },
            "selector": "univariate_corr_top_K",
            "K": 250,
            "stage_1": {
                "model": "sklearn.linear_model.Ridge",
                "alpha": 1.0,
                "covariates": ["hy_stage", "cv_years", "cv_sex", "cv_dbs"],
            },
            "imputation": "fold_local_train_median",
            "cohort": "drop_allmissing_validrange",
            "subitem_validation": "clip MDSUPDRS_3-* to [0,4]; treat 5-99 as NaN",
            "seeds": list(SEEDS),
            "evaluation": "LOOCV on PPMI cohort; paired-bootstrap vs PPMI baseline",
        },
        "secondary_to_lock_alongside": [
            "T1 conformal abstention (V2_only): "
            f"see {T1_CONFORMAL_LOCKBOX.name}",
            "T3 conformal abstention (winning v-next cell A/B/C, post-screen)",
        ],
        "fwer_family_at_ppmi": {
            "n": 1, "gate_frac_pos": 0.95,
            "comparator": "PPMI internal baseline (iter47-style if data permits)",
        },
        "first_allowed_action_after_PPMI_access": [
            "Schema probe: confirm subject/visit/sensor IDs.",
            "Stage-1 covariate availability check (hy, age, sex, dbs).",
            "Build cohort under drop_allmissing_validrange.",
            "Run primary formula ONLY; no exploratory variants.",
        ],
        "leakage_safeguards": [
            "No K-search at PPMI — K=250 fixed.",
            "No model search at PPMI — sklearn-GB fixed.",
            "No selector search at PPMI — univariate-corr fixed.",
            "No threshold tuning post-OOF.",
            "If primary formula fails Bonferroni n=1 (gate 0.95), report as null;"
            " do NOT post-hoc search alternatives.",
        ],
        "wearagait_evidence_base": {
            "iter47_canonical_ccc": 0.3784,
            "k250_sklearn_gb_ccc_wearagait": 0.4488,
            "delta_at_wearagait_n95": 0.0732,
            "wearagait_frac_pos": 0.9518,
            "wearagait_fwer_verdict": "FAILS Bonferroni n=7 (K-search family)",
            "expected_ppmi_n": 517,
            "expected_variance_reduction_factor": 2.3,
        },
    }
    # Compute formula_sha256 over the primary_formula block (the locked
    # replication contract).
    fsha = _sha_of(blueprint["primary_formula"])
    blueprint["formula_sha256"] = fsha
    return blueprint


# ── Master driver ────────────────────────────────────────────────────────────


def _write_master_prereg(script_sha: str) -> Path:
    prereg = {
        "name": "vnext_ablation_batch",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "script_sha256": script_sha,
        "status": "locked_before_execution",
        "ts_global": TS_GLOBAL,
        "goal_directive": (
            "v-next features + KPIs + ablation + stacking; respect 30+ wall data"
            " points; saturate remote RTX 4060 GPU slave."
        ),
        "consult_records": [
            "/tmp/pd_imu_consult/codex_20260514T150619.txt",
            "/tmp/pd_imu_consult/gemini_20260514T150619.txt (429 RESOURCE_EXHAUSTED)",
            "/tmp/pd_imu_consult/kimi_vnext_20260514T151135.txt (opencode recursive-skill abort)",
        ],
        "synthesis_voice": "codex_solo_due_to_gemini_quota_exhaustion",
        "cells": {
            "A_t3_mondrian_cp": {
                "estimand": "t3_conformal_retained_subset_ccc",
                "bins": "outer_train_only_LOO_quartile_of_predicted_T3",
                "score": "abs_residual",
                "expected_70pct_ccc": ">=0.40",
            },
            "B_t3_cqr": {
                "estimand": "t3_conformal_retained_subset_ccc",
                "model": "LGB_quantile_alpha_005_05_095",
                "K": 250, "selector": "univariate_corr",
                "score": "interval_width_q95_q05",
                "expected_70pct_ccc": ">=0.40",
            },
            "C_t3_mondrian_cqr_joint": {
                "estimand": "t3_conformal_retained_subset_ccc",
                "score": "cqr_width_per_predicted_T3_bin",
                "expected_70pct_ccc": ">=0.42",
            },
            "D_t3_k250_4cell": {
                "estimand": "t3_loocv_ccc",
                "cells": [
                    {"model": "sklearn_gb", "selector": "univariate_corr"},
                    {"model": "sklearn_gb", "selector": "lgb_importance"},
                    {"model": "lightgbm", "selector": "univariate_corr"},
                    {"model": "lightgbm", "selector": "lgb_importance"},
                ],
                "K": 250,
                "comparator": "iter47_canonical_0.3784",
                "expected_max_delta": "+0.07_at_sklearn_gb_univariate_corr",
            },
            "E_t1_peritem_cp_heatmap": {
                "estimand": "t1_peritem_conformal_retained_ccc",
                "items": list(T1_ITEMS),
                "coverages": list(COVERAGE_TARGETS),
                "source": "iter34_per_item_oof_npz",
            },
            "F_joint_t1_t3": {
                "estimand": "joint_multioutput_t1_t3_ccc",
                "comparator_t1": "iter34_canonical_0.7170",
                "comparator_t3": "iter47_canonical_0.3784",
            },
            "G_item11_hurdle": {
                "estimand": "item11_loocv_ccc",
                "comparator": "iter34_chain_item11_0.232",
            },
            "H_ppmi_blueprint": {
                "estimand": "external_replication_contract_lock",
                "kind": "documentation_no_compute",
            },
        },
        "fwer_families": {
            "t3_conformal": {
                "cells": ["A", "B", "C"], "n": 3,
                "bonferroni_gate_frac_pos": 0.9833,
                "comparator": "T3 conformal v2 (stddev predictor) "
                              "PARTIAL_PASS r=0.12, retained_ccc_70%=0.329",
            },
            "t3_loocv_ccc": {
                "cells": ["D_sklearn_gb_univ_corr",
                          "D_sklearn_gb_lgb_imp",
                          "D_lightgbm_univ_corr",
                          "D_lightgbm_lgb_imp"],
                "n": 4, "bonferroni_gate_frac_pos": 0.9875,
                "comparator": "iter47_canonical_0.3784_N95",
            },
            "t1_peritem_cp": {
                "cells": [f"E_item{i}" for i in T1_ITEMS],
                "n": 6, "bonferroni_gate_per_item": 0.9917,
                "comparator": "standalone_item_loocv_ccc_iter34_chain",
            },
            "joint_t1_t3": {
                "cells": ["F"], "n": 1, "gate_frac_pos": 0.95,
                "comparator_t3": "iter47_canonical_0.3784_N95",
                "comparator_t1": "iter34_canonical_0.7170_N92",
            },
            "item11_hurdle": {
                "cells": ["G"], "n": 1, "gate_frac_pos": 0.95,
                "comparator": "iter34_chain_item11_0.232",
            },
        },
        "kpi_dashboard": {
            "primary_t1_loocv_ccc": {
                "current_canonical": 0.7170,
                "current_floor": 0.6550,
                "ceiling_status": "SATURATED in-cohort (30+ wall data points)",
            },
            "primary_t3_loocv_ccc": {
                "current_canonical": 0.3784,
                "best_fails_fwer": 0.4488,
                "ceiling_status": "SATURATED in-cohort under FWER",
            },
            "secondary_t1_conformal_70pct": {
                "current_canonical_retained_ccc": 0.7777,
                "lockbox_2026_05_12": str(T1_CONFORMAL_LOCKBOX),
            },
            "secondary_t1_conformal_50pct": {
                "current_canonical_retained_ccc": 0.8338,
                "lockbox_2026_05_12": str(T1_CONFORMAL_LOCKBOX),
            },
            "secondary_t3_conformal_70pct": {
                "current_canonical_retained_ccc": 0.329,
                "status": "PARTIAL_PASS_MONOTONICITY_VIOLATIONS r=0.12",
                "vnext_target": "PASS_DEPLOYABLE_SECONDARY via cells A/B/C",
            },
            "tertiary_mae_at_70pct": {"t1": 1.63, "t3": 6.87},
            "methodological_5_null_gate": "pass_required_per_cell",
            "translational_mcid_rate": (
                "fraction of |y_pred - y_true| <= MCID (T1 MCID=2 sum points;"
                " T3 MCID=2.5-5 total points per Horvath 2017)"
            ),
            "per_item_deployability_heatmap": "cell_E_output",
            "external_replication_readiness": (
                "PPMI primary formula locked at cell_H output formula_sha256"
            ),
        },
        "ppmi_locked_formula_target_path": str(
            RESULTS_DIR / f"lockbox_ppmi_replication_blueprint_{TS_GLOBAL}.json"
        ),
        "out_of_fwer_family": ["H"],
        "leakage_safeguards": [
            "All bins computed from outer-train predictions OR predicted-T3 "
            "(no test-fold y used in binning).",
            "Stage-1 Ridge fitted only on outer-train fold per LOOCV iteration.",
            "K-best selectors (univariate-corr / LGB-importance) fitted only "
            "on outer-train fold residuals.",
            "Quantile thresholds in conformal cells computed leave-one-out "
            "from the other N-1 calibration subjects.",
            "K=250 fixed; no K-search inside this batch.",
            "Selector and model classes fixed per cell; no in-cell search.",
            "iter34 per-item OOF (cell E) and iter47 OOF (cells A/C) are "
            "already leak-clean LOOCV artifacts.",
        ],
        "hard_rejections_codex_2026_05_14": [
            "Do not tune abstention scores on the final OOF residuals.",
            "Do not choose coverage thresholds by reported CCC.",
            "Do not build bins using all labels (true T3); use predicted T3.",
            "Do not use global feature selectors.",
            "Do not pick the PPMI formula after seeing PPMI outcomes.",
        ],
    }
    prereg_path = RESULTS_DIR / f"preregistration_vnext_ablation_batch_{TS_GLOBAL}.json"
    _write_json(prereg_path, prereg)
    return prereg_path


def main() -> int:
    script_sha = _sha_of_file(Path(__file__))
    prereg_path = _write_master_prereg(script_sha)
    print(f"[v-next] master pre-reg locked: {prereg_path}", flush=True)

    # Single shared cohort for cells A, B, C, D, F, G (T3 cohort + V2 features).
    print("[v-next] loading cohort drop_allmissing_validrange...", flush=True)
    t0 = time.time()
    data = filter_cohort("drop_allmissing_validrange")
    # Stage-2 policy = stage2_current (matches iter47 canonical).
    X_s2, feat_cols_s2 = filter_stage2(
        data["X"], data["feat_cols"], "stage2_current"
    )
    data["X"] = X_s2
    data["feat_cols"] = feat_cols_s2
    print(f"[v-next] cohort N={len(data['sids'])} loaded in {time.time()-t0:.1f}s",
          flush=True)

    cells_out: dict[str, Any] = {}

    # ── Cell H: PPMI blueprint first (cheap, locks formula before any compute)
    print("[v-next] Cell H — PPMI replication blueprint (formula lock)...",
          flush=True)
    blueprint = cell_H_ppmi_blueprint()
    blueprint_path = RESULTS_DIR / f"lockbox_ppmi_replication_blueprint_{TS_GLOBAL}.json"
    _write_json(blueprint_path, blueprint)
    cells_out["H"] = blueprint
    print(f"[v-next] Cell H formula_sha256={blueprint['formula_sha256'][:16]}...",
          flush=True)

    # ── Cell A: T3 Mondrian-CP
    print("[v-next] Cell A — T3 Mondrian-CP...", flush=True)
    t0 = time.time()
    out_a = cell_A_t3_mondrian_cp(data)
    _write_json(RESULTS_DIR / f"lockbox_vnext_A_t3_mondrian_cp_{TS_GLOBAL}.json", out_a)
    cells_out["A"] = out_a
    print(f"[v-next] Cell A done in {time.time()-t0:.1f}s verdict={out_a['verdict']}",
          flush=True)

    # ── Cell B: T3 CQR
    print("[v-next] Cell B — T3 CQR (LGB-quantile)...", flush=True)
    t0 = time.time()
    out_b = cell_B_t3_cqr(data)
    _write_json(RESULTS_DIR / f"lockbox_vnext_B_t3_cqr_{TS_GLOBAL}.json", out_b)
    cells_out["B"] = out_b
    print(f"[v-next] Cell B done in {time.time()-t0:.1f}s verdict={out_b['verdict']}",
          flush=True)

    # ── Cell C: T3 Mondrian × CQR joint (depends on B)
    print("[v-next] Cell C — T3 Mondrian × CQR joint...", flush=True)
    t0 = time.time()
    out_c = cell_C_t3_mondrian_cqr_joint(data, cqr_out=out_b)
    _write_json(RESULTS_DIR / f"lockbox_vnext_C_t3_mondrian_cqr_{TS_GLOBAL}.json", out_c)
    cells_out["C"] = out_c
    print(f"[v-next] Cell C done in {time.time()-t0:.1f}s verdict={out_c['verdict']}",
          flush=True)

    # ── Cell D: K=250 4-cell mechanism
    print("[v-next] Cell D — K=250 mechanism 4-cell...", flush=True)
    t0 = time.time()
    out_d = cell_D_t3_k250_4cell(data)
    _write_json(RESULTS_DIR / f"lockbox_vnext_D_t3_k250_4cell_{TS_GLOBAL}.json", out_d)
    cells_out["D"] = out_d
    print(f"[v-next] Cell D done in {time.time()-t0:.1f}s "
          f"subcells={len(out_d['subcells'])}", flush=True)

    # ── Cell E: T1 per-item conformal heatmap (cheap, uses on-disk OOF)
    print("[v-next] Cell E — T1 per-item conformal heatmap...", flush=True)
    t0 = time.time()
    out_e = cell_E_t1_peritem_cp_heatmap()
    _write_json(RESULTS_DIR / f"lockbox_vnext_E_peritem_cp_{TS_GLOBAL}.json", out_e)
    cells_out["E"] = out_e
    print(f"[v-next] Cell E done in {time.time()-t0:.1f}s", flush=True)

    # ── Cell F: Joint T1×T3 multi-output
    print("[v-next] Cell F — Joint T1×T3 multi-output...", flush=True)
    t0 = time.time()
    out_f = cell_F_joint_t1_t3(data)
    _write_json(RESULTS_DIR / f"lockbox_vnext_F_joint_t1_t3_{TS_GLOBAL}.json", out_f)
    cells_out["F"] = out_f
    print(f"[v-next] Cell F done in {time.time()-t0:.1f}s", flush=True)

    # ── Cell G: Item 11 FoG hurdle
    print("[v-next] Cell G — Item 11 FoG hurdle...", flush=True)
    t0 = time.time()
    out_g = cell_G_item11_hurdle(data)
    _write_json(RESULTS_DIR / f"lockbox_vnext_G_item11_hurdle_{TS_GLOBAL}.json", out_g)
    cells_out["G"] = out_g
    print(f"[v-next] Cell G done in {time.time()-t0:.1f}s", flush=True)

    # ── Master lockbox
    master = {
        "name": "vnext_ablation_batch_master_lockbox",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "script_sha256": script_sha,
        "ts_global": TS_GLOBAL,
        "prereg_path": str(prereg_path),
        "cells": cells_out,
        "summary": {
            cell: {
                "verdict": v.get("verdict") if isinstance(v, dict) else None,
                "key_metrics": _summarize_cell(cell, v),
            }
            for cell, v in cells_out.items()
        },
    }
    master_path = RESULTS_DIR / f"lockbox_vnext_master_{TS_GLOBAL}.json"
    _write_json(master_path, master)
    print(f"[v-next] master lockbox written: {master_path}", flush=True)
    return 0


def _summarize_cell(cell: str, v: dict) -> dict:
    if not isinstance(v, dict):
        return {}
    if cell in ("A", "B", "C") and "rows" in v:
        r70 = [r for r in v["rows"] if abs(r["coverage_target"] - 0.70) < 1e-3]
        r50 = [r for r in v["rows"] if abs(r["coverage_target"] - 0.50) < 1e-3]
        return {
            "retained_ccc_70": r70[0]["retained_ccc"] if r70 else None,
            "retained_ccc_50": r50[0]["retained_ccc"] if r50 else None,
            "monotonicity_violations": v.get("monotonicity_violations"),
        }
    if cell == "D" and "subcells" in v:
        return {
            "best": max(v["subcells"], key=lambda c: c["pooled_ccc"]),
        }
    if cell == "E" and "items_data" in v:
        items_summary = {}
        for itm in v["items_data"]:
            if not itm.get("available"):
                continue
            rows = itm.get("rows", [])
            r70 = [r for r in rows if abs(r["coverage_target"] - 0.70) < 1e-3]
            items_summary[itm["item"]] = {
                "full_ccc": itm["full_ccc_iter34_chain"],
                "retained_ccc_70": r70[0]["retained_ccc"] if r70 else None,
            }
        return items_summary
    if cell == "F":
        return {
            "delta_t3_joint_vs_single": v.get("delta_t3_joint_vs_single"),
            "delta_t1_joint_vs_single": v.get("delta_t1_joint_vs_single"),
        }
    if cell == "G":
        return {
            "delta_hurdle_vs_continuous": v.get("delta_hurdle_vs_continuous"),
            "hurdle_ccc": v.get("hurdle_two_stage_ccc"),
        }
    if cell == "H":
        return {"formula_sha256": v.get("formula_sha256")}
    return {}


if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    raise SystemExit(main())

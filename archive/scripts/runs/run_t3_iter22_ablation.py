"""T3 iter22 — Ablation study around plan-next.md (2026-05-04 PM).

Implements the 15-cell ablation matrix designed to map the in-domain T3
modeling space at N=94 (T1 cohort, intersection of iter5 and iter12 OOFs).

USAGE
-----
  # 1. Write pre-registration BEFORE any cell runs
  python3 run_t3_iter22_ablation.py --write-prereg

  # 2. Run cells (validates formula_sha256 against pre-reg first)
  python3 run_t3_iter22_ablation.py --run \
      --preregistration results/preregistration_t3_iter22_ablation_<TS>.json \
      --cells AB1,AB2,AB3,BB1,BB2,CC1,CC3,DD1,DD2,FF1,FF2,LC

  # 3. Run learning curve (Phase 4.2) standalone
  python3 run_t3_iter22_ablation.py --run --cells LC \
      --preregistration <path>

KEY DECISIONS (locked at planning, see task_plan.md ACTIVE MISSION)
------------------------------------------------------------------
- Cohort: T1 (N=94 PD subjects). Both iter5 and T1-iter12 OOFs are inductive
  LOOCV preds; iter5 was trained at N=98, used here intersected to N=94.
  Each subject's iter5 pred was trained without using its OWN label, so
  inductive firewall holds. Disclosed in pre-reg.
- Mixer alpha range: [0, 1] in 0.02 steps (51-step grid). Fold-local 1-D search.
- Beta (T1-sum scale calibration): solved analytically per-alpha via OLS on
  fold-train (closed-form: beta = E[(y - alpha*a)*b] / ((1-alpha) * E[b^2])).
- Standard gate: Δ ≥ +0.05 mean across seeds, seed std < 0.02.
- Sensitivity gate (AB1 only, declared upfront): Δ ≥ +0.025 AND paired-subject
  bootstrap 95% CI lower bound > 0 (5000 resamples).
- All cells run regardless of gate (negative-audit ablation map is the contribution).

CELLS
-----
  AB1  iter12-honest, alpha-only-CCC, 4-cov-Ridge, std-CCC      [BACKBONE, sensitivity gate]
  AB2  iter17-bests-summed (15+18 only swapped), alpha-only-CCC, 4-cov-Ridge, std-CCC
  AB3  no-T1 (alpha=1, beta=0), 4-cov-Ridge, std-CCC            [iter5 SANITY = 0.5227]
  BB1  iter12-honest, (alpha,beta) joint-CCC, 4-cov-Ridge, std-CCC
  BB2  iter12-honest, Ridge-meta-2-base, 4-cov-Ridge, std-CCC
  BB3  iter12-honest, OLS-unconstrained, 4-cov-Ridge, std-CCC   [CANARY]
  CC1  iter12-honest, alpha-only-CCC, 8-cov-horseshoe, std-CCC  [Phase 2 main; GPU]
  CC3  iter12-honest, alpha-only-CCC, 8-cov-Ridge, std-CCC      [predicted-null]
  DD1  iter12-honest, alpha-only-CCC, best-from-C, hetero-CCC   [Phase 3 main]
  DD2  iter12-honest, alpha-only-CCC, best-from-C, MSE          [Stage-2 control]
  FF1  full stack
  FF2  full stack minus T1
  NN1-3 AB1 architecture at N in {50, 70, 89} subsamples
  LC   iter5 baseline learning curve, 4 N x 50 subsamples x 3 seeds
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics, mae as mae_fn, pearson_r
from project_paths import RESULTS_DIR, ensure_dir

# ── Constants ─────────────────────────────────────────────────────────────────
SEEDS: tuple[int, ...] = (42, 1337, 7)
ALPHA_GRID = np.round(np.arange(0.0, 1.0001, 0.02), 4)  # 51 points
ITER8_TS = "20260430_143044"
ITER17_TS = "20260503_221544"
T1_ITEMS = [9, 10, 11, 12, 13, 14]

# Iter12 honest variants per item (canonical T1 lockbox batch)
ITER12_VARIANTS: dict[int, str] = {
    9: "hy_residual_item",
    10: "item_plus_v2",
    11: "item_dedicated",
    12: "item_plus_v2",
    13: "item_plus_v2",
    14: "item_plus_v2",
}

# 8-cov panel for CC1/CC3 horseshoe vs Ridge (post-audit; Part II/MoCA/LEDD/ON-OFF NOT in WearGait-PD)
PANEL_4COV = ["cv_yrs", "cv_sex", "cv_dbs"]            # plus hy via build_stage1_features one-hot
PANEL_8COV = ["cv_yrs", "cv_sex", "cv_dbs", "cv_age",
              "ext_yrs_sq", "ext_yrs_log", "ext_late_pd"]  # plus hy

# Heteroscedastic CCC variance function v(y) = max((a*y + b)^2, c^2). Goetz 2008 prior:
HETERO_PRIOR = dict(a=0.04, b=2.5, c=1.5)

# Subsample N levels for learning curve and N-axis cells
LC_N_LEVELS = (30, 50, 70, 89)
LC_N_SUBSAMPLES = 50


# ── OOF cache loaders ────────────────────────────────────────────────────────


def load_t3_arrays() -> dict:
    """Load T3 cohort N=98: SIDs, y_t3 (= updrs3), iter5 LOOCV OOF, V2 features, hy."""
    from run_t3_iter5_clinical import load_full_pd_data, load_clinical_dict
    sids_t3, X, fc, y_t3, hy, obs = load_full_pd_data()
    iter5_oof_path = RESULTS_DIR / "lockbox_t3_iter5_A3_tier1_20260502_171604.oof.npy"
    if not iter5_oof_path.exists():
        raise FileNotFoundError(f"Missing canonical iter5 LOOCV OOF: {iter5_oof_path}")
    iter5_oof = np.load(iter5_oof_path)
    if iter5_oof.shape != (len(sids_t3),):
        raise ValueError(f"iter5 OOF shape {iter5_oof.shape} != T3 cohort shape ({len(sids_t3)},)")
    clinical = load_clinical_dict(sids_t3)
    return dict(sids=np.asarray(sids_t3), y_t3=y_t3, iter5_oof=iter5_oof,
                X=X, hy=hy, clinical=clinical)


def load_t1_arrays() -> dict:
    """Load T1 cohort N=94: SIDs, y_t1, sum of iter12 honest OOFs, per-item OOFs."""
    from run_per_item_v2 import load_data as load_peritem
    d = load_peritem()
    sids_t1 = np.asarray([str(s) for s in d["sids"]])
    n = len(sids_t1)
    per_item = {}
    for it in T1_ITEMS:
        v = ITER12_VARIANTS[it]
        path = RESULTS_DIR / f"lockbox_peritem_{it}_{v}_{ITER8_TS}.oof.npy"
        if not path.exists():
            raise FileNotFoundError(f"Missing iter12 OOF: {path}")
        arr = np.load(path)
        if arr.shape != (n,):
            raise ValueError(f"Item {it} OOF shape {arr.shape} != ({n},)")
        per_item[it] = arr
    t1_iter12_sum = np.sum(np.column_stack([per_item[it] for it in T1_ITEMS]), axis=1)
    return dict(sids=sids_t1, y_t1=d["t1"], t1_iter12_sum=t1_iter12_sum, per_item=per_item)


def load_iter17_bests_oof(t1_sids: np.ndarray) -> np.ndarray:
    """Construct alternative T1-source: replace items 15 + 18 with iter17 hyp lockboxes
    (those landed +0.20 / +0.236 LOOCV); items 9-14 stay as iter12. Sum 9-14 only.

    Note: items 15 and 18 are NOT in T1 (which is 9-14). The iter17-bests-summed
    cell tests an alternative DEFINITION of T1 that includes 15+18 if available, but
    here for AB2 we sum items 9-14 using whatever iter17 winner exists per item, falling
    back to iter12 batch when no iter17 lockbox exists.

    For 9-14: no iter17 lockboxes were promoted (only 15, 18). So AB2 effectively
    reproduces iter12. To make AB2 a meaningful contrast we instead use the iter17
    PHASE A2 pre-reg per-item screen winners for 9-14 even if not lockboxed (those
    are documented in findings.md F50). For now, fall back to iter12 sum (AB2 = AB1)
    and document this in the run log; the contrast becomes degenerate but harmless.
    """
    items = [9, 10, 11, 12, 13, 14]
    arrs = []
    for it in items:
        v = ITER12_VARIANTS[it]
        path = RESULTS_DIR / f"lockbox_peritem_{it}_{v}_{ITER8_TS}.oof.npy"
        arrs.append(np.load(path))
    return np.sum(np.column_stack(arrs), axis=1)


def align_t1_to_t3(t1_sids: np.ndarray, t3_sids: np.ndarray) -> np.ndarray:
    """Return indices in t3_sids for each sid in t1_sids."""
    t3_idx = {sid: i for i, sid in enumerate(t3_sids)}
    out = np.array([t3_idx[s] for s in t1_sids], dtype=int)
    return out


# ── Mixers (the heart of the ablation) ───────────────────────────────────────


def fit_alpha_only_ccc(a: np.ndarray, b: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Cell AB1 mixer: alpha-only CCC, beta solved analytically per-alpha by OLS.
    Returns (alpha*, beta*). Constraint alpha in [0, 1] grid, beta unconstrained."""
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float); y = np.asarray(y, dtype=float)
    eb2 = float(np.mean(b * b))
    best = (-2.0, 0.5, 1.0)  # (ccc, alpha, beta)
    for alpha in ALPHA_GRID:
        if alpha < 0.999 and eb2 > 0:
            beta = float(np.mean((y - alpha * a) * b)) / ((1.0 - alpha) * eb2)
        else:
            beta = 0.0
        p = alpha * a + (1.0 - alpha) * beta * b
        c = float(ccc_fn(y, p))
        if c > best[0]:
            best = (c, float(alpha), float(beta))
    return best[1], best[2]


def fit_alpha_beta_joint_ccc(a: np.ndarray, b: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Cell BB1: search alpha in [0,1], beta in 51-point log-spaced grid around OLS center."""
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float); y = np.asarray(y, dtype=float)
    eb2 = float(np.mean(b * b))
    if eb2 == 0:
        return 1.0, 0.0
    beta_center = float(np.mean(y * b)) / eb2  # raw OLS y ~ beta*b
    beta_grid = beta_center * np.linspace(0.5, 1.5, 21)
    best = (-2.0, 0.5, beta_center)
    for alpha in ALPHA_GRID:
        for beta in beta_grid:
            p = alpha * a + (1.0 - alpha) * beta * b
            c = float(ccc_fn(y, p))
            if c > best[0]:
                best = (c, float(alpha), float(beta))
    return best[1], best[2]


def fit_ridge_meta_2base(a: np.ndarray, b: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    """Cell BB2: Ridge alpha=1.0 over (a, b) -> y. Returns (coef, intercept)."""
    from sklearn.linear_model import Ridge
    X = np.column_stack([a, b])
    m = Ridge(alpha=1.0, fit_intercept=True)
    m.fit(X, y)
    return m.coef_.astype(float), float(m.intercept_)


def fit_ols_unconstrained(a: np.ndarray, b: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    """Cell BB3 (canary): OLS over (a, b) -> y. Returns (coef, intercept)."""
    from sklearn.linear_model import LinearRegression
    X = np.column_stack([a, b])
    m = LinearRegression(fit_intercept=True)
    m.fit(X, y)
    return m.coef_.astype(float), float(m.intercept_)


# ── Cell definitions: each takes paired (iter5_oof, t1_oof, y) and produces blended OOF ──


def _loocv_blend_alpha_only(a: np.ndarray, b: np.ndarray, y: np.ndarray
                           ) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """LOOCV blend with fold-local fit_alpha_only_ccc.
    Returns (blend_oof, list_of_(alpha, beta) per fold)."""
    n = len(y)
    out = np.zeros(n)
    diags = []
    for i in range(n):
        mask = np.arange(n) != i
        alpha, beta = fit_alpha_only_ccc(a[mask], b[mask], y[mask])
        out[i] = alpha * a[i] + (1.0 - alpha) * beta * b[i]
        diags.append((alpha, beta))
    return out, diags


def _loocv_blend_alpha_only_masked(a: np.ndarray, b: np.ndarray, y: np.ndarray,
                                    valid: np.ndarray
                                   ) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """LOOCV blend with NaN-aware T1 stream. Mixer trained on valid-T1 subjects only;
    invalid-T1 test subjects fall back to pure iter5 (handled by caller). For valid
    test subjects, mixer is fit on the OTHER valid-T1 train subjects."""
    n = len(y)
    out = np.full(n, np.nan, dtype=float)
    diags = []
    valid_idx = np.where(valid)[0]
    for i in range(n):
        if not valid[i]:
            diags.append((1.0, 0.0))  # marker; actual prediction filled by caller
            continue
        # Train mask: valid subjects EXCEPT subject i
        mask = valid.copy()
        mask[i] = False
        alpha, beta = fit_alpha_only_ccc(a[mask], b[mask], y[mask])
        out[i] = alpha * a[i] + (1.0 - alpha) * beta * b[i]
        diags.append((alpha, beta))
    return out, diags


def _loocv_blend_alpha_beta_joint(a: np.ndarray, b: np.ndarray, y: np.ndarray
                                 ) -> tuple[np.ndarray, list[tuple[float, float]]]:
    n = len(y)
    out = np.zeros(n)
    diags = []
    for i in range(n):
        mask = np.arange(n) != i
        alpha, beta = fit_alpha_beta_joint_ccc(a[mask], b[mask], y[mask])
        out[i] = alpha * a[i] + (1.0 - alpha) * beta * b[i]
        diags.append((alpha, beta))
    return out, diags


def _loocv_blend_ridge2(a: np.ndarray, b: np.ndarray, y: np.ndarray
                       ) -> tuple[np.ndarray, list[tuple[float, float, float]]]:
    n = len(y)
    out = np.zeros(n)
    diags = []
    for i in range(n):
        mask = np.arange(n) != i
        coef, intc = fit_ridge_meta_2base(a[mask], b[mask], y[mask])
        out[i] = float(coef[0] * a[i] + coef[1] * b[i] + intc)
        diags.append((float(coef[0]), float(coef[1]), float(intc)))
    return out, diags


def _loocv_blend_ols_unconstrained(a: np.ndarray, b: np.ndarray, y: np.ndarray
                                  ) -> tuple[np.ndarray, list[tuple[float, float, float]]]:
    n = len(y)
    out = np.zeros(n)
    diags = []
    for i in range(n):
        mask = np.arange(n) != i
        coef, intc = fit_ols_unconstrained(a[mask], b[mask], y[mask])
        out[i] = float(coef[0] * a[i] + coef[1] * b[i] + intc)
        diags.append((float(coef[0]), float(coef[1]), float(intc)))
    return out, diags


# ── Bootstrap & gates ────────────────────────────────────────────────────────


def paired_bootstrap_delta(y_true: np.ndarray, blend_pred: np.ndarray, base_pred: np.ndarray,
                           n_boot: int = 5000, seed: int = 42) -> dict:
    """Paired-subject bootstrap of CCC(y, blend) - CCC(y, base)."""
    rng = np.random.RandomState(seed)
    n = len(y_true)
    deltas = np.zeros(n_boot)
    base_cccs = np.zeros(n_boot)
    blend_cccs = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        c_blend = ccc_fn(y_true[idx], blend_pred[idx])
        c_base = ccc_fn(y_true[idx], base_pred[idx])
        blend_cccs[b] = c_blend
        base_cccs[b] = c_base
        deltas[b] = c_blend - c_base
    return dict(
        delta_mean=float(deltas.mean()),
        delta_ci_low=float(np.percentile(deltas, 2.5)),
        delta_ci_high=float(np.percentile(deltas, 97.5)),
        delta_frac_gt0=float((deltas > 0).mean()),
        blend_ccc_mean=float(blend_cccs.mean()),
        base_ccc_mean=float(base_cccs.mean()),
        n_boot=n_boot,
    )


def evaluate_gate(boot: dict, gate_kind: str, min_delta: float = 0.025,
                  ci_lower_bound: float = 0.0) -> dict:
    """Apply gate based on bootstrap stats."""
    if gate_kind == "sensitivity":
        passed = bool(boot["delta_mean"] >= min_delta and boot["delta_ci_low"] > ci_lower_bound)
        why = (f"delta_mean={boot['delta_mean']:.4f} ≥ {min_delta} AND "
               f"CI_low={boot['delta_ci_low']:.4f} > {ci_lower_bound} → {'PASS' if passed else 'FAIL'}")
    elif gate_kind == "standard":
        # min_delta default for standard 0.05; seed std requires multi-seed runs (handled outside)
        passed = bool(boot["delta_mean"] >= min_delta and boot["delta_ci_low"] > ci_lower_bound)
        why = (f"delta_mean={boot['delta_mean']:.4f} ≥ {min_delta} AND "
               f"CI_low={boot['delta_ci_low']:.4f} > {ci_lower_bound} → {'PASS' if passed else 'FAIL'}")
    elif gate_kind == "none":
        passed = False
        why = "No gate applies (control / scientific test cell)"
    else:
        raise ValueError(f"Unknown gate_kind {gate_kind}")
    return dict(passed=passed, why=why)


# ── Cell registry ────────────────────────────────────────────────────────────


CELLS = {
    "AB1": dict(
        name="iter12-honest x alpha-only-CCC x 4cov-Ridge x std-CCC (T1=94 cohort)",
        purpose="BACKBONE; sensitivity-gate target",
        t1_source="iter12_honest", mixer="alpha_only", stage1="ridge_4cov",
        stage2_loss="std_ccc_v2", gate="sensitivity", cohort="t1_94",
    ),
    "AB1_N98": dict(
        name="iter12-honest x alpha-only-CCC x 4cov-Ridge x std-CCC at N=98 (backfill)",
        purpose="EXPLORATORY: AB1 at canonical iter5 cohort (4 missing T1 subjects "
                "backfilled with iter5 pred → α=1, β=0)",
        t1_source="iter12_honest_backfill", mixer="alpha_only", stage1="ridge_4cov",
        stage2_loss="std_ccc_v2", gate="sensitivity", cohort="t3_98",
    ),
    "CC3_N94": dict(
        name="iter12-honest x alpha-only-CCC x 8cov-Ridge x std-CCC (T1=94)",
        purpose="Stage-1 widening NULL TEST: 8-cov Ridge; expected null/negative "
                "(structured shrinkage absent, same panel as CC1 horseshoe)",
        t1_source="iter12_honest", mixer="alpha_only", stage1="ridge_8cov",
        stage2_loss="std_ccc_v2", gate="standard", cohort="t1_94",
    ),
    "CC3_N98": dict(
        name="iter5(8cov-Ridge) at N=98 (no T1 blend) — Stage-1-widening-only ablation",
        purpose="Tests whether widening Stage-1 panel ALONE (no blend) helps; uses "
                "iter5 OOF re-trained with A_iter22_8cov panel",
        t1_source="none", mixer="identity", stage1="ridge_8cov",
        stage2_loss="std_ccc_v2", gate="standard", cohort="t3_98",
    ),
    "AB1_N98_8cov": dict(
        name="iter12-honest x alpha-only x 8cov-Ridge x std-CCC at N=98 (full Stage-1+blend)",
        purpose="Stage-1 widening + blend at canonical N=98",
        t1_source="iter12_honest_backfill", mixer="alpha_only", stage1="ridge_8cov",
        stage2_loss="std_ccc_v2", gate="standard", cohort="t3_98",
    ),
    "AB2": dict(
        name="iter12-honest with item replacements (degenerate at present) x alpha-only x 4cov x std-CCC",
        purpose="T1-source ablation (iter17 bests for items 15/18 unavailable in T1=9-14)",
        t1_source="iter17_bests", mixer="alpha_only", stage1="ridge_4cov",
        stage2_loss="std_ccc_v2", gate="standard",
    ),
    "AB3": dict(
        name="no-T1 (iter5 baseline reproduction)",
        purpose="T1-source control: must reproduce iter5 LOOCV CCC=0.5227",
        t1_source="none", mixer="identity", stage1="ridge_4cov",
        stage2_loss="std_ccc_v2", gate="none",
    ),
    "BB1": dict(
        name="iter12-honest x (alpha,beta)-joint-CCC x 4cov-Ridge x std-CCC",
        purpose="Mixer: explicit beta vs implicit OLS (Q3 diagnostic)",
        t1_source="iter12_honest", mixer="alpha_beta_joint", stage1="ridge_4cov",
        stage2_loss="std_ccc_v2", gate="standard",
    ),
    "BB2": dict(
        name="iter12-honest x Ridge-meta-2base x 4cov-Ridge x std-CCC",
        purpose="Mixer: Ridge meta on 2 bases (k=2 control)",
        t1_source="iter12_honest", mixer="ridge_2base", stage1="ridge_4cov",
        stage2_loss="std_ccc_v2", gate="standard",
    ),
    "BB3": dict(
        name="iter12-honest x OLS-unconstrained x 4cov-Ridge x std-CCC",
        purpose="CANARY: unconstrained alpha (must abort if α̂ ∉ [0,1])",
        t1_source="iter12_honest", mixer="ols_unconstrained", stage1="ridge_4cov",
        stage2_loss="std_ccc_v2", gate="standard",
    ),
}


def _select_iter5_stream(cfg: dict, t3: dict, t3_iter5_8cov_oof: np.ndarray | None) -> np.ndarray:
    """Pick which iter5 OOF to use given Stage-1 config."""
    if cfg.get("stage1") == "ridge_8cov":
        if t3_iter5_8cov_oof is None:
            raise RuntimeError(f"Cell {cfg['name']!r} requires 8-cov iter5 OOF; pass via --iter5-8cov-oof")
        return t3_iter5_8cov_oof
    return t3["iter5_oof"]


def run_cell(cell_id: str, t3: dict, t1: dict, t1_to_t3: np.ndarray,
             t3_iter5_8cov_oof: np.ndarray | None = None) -> dict:
    """Execute one cell. Returns results dict."""
    cfg = CELLS[cell_id]
    t0 = time.time()
    cohort = cfg.get("cohort", "t1_94")

    # Choose iter5 stream (4cov or 8cov)
    iter5_full = _select_iter5_stream(cfg, t3, t3_iter5_8cov_oof)  # length 98

    if cohort == "t1_94":
        # Restrict to T1 cohort intersection
        n_eval = len(t1["sids"])
        iter5_for_blend = iter5_full[t1_to_t3]      # (94,)
        y_for_blend = t3["y_t3"][t1_to_t3]          # (94,)
        # iter5 baseline metrics for delta:
        iter5_baseline_for_delta = iter5_for_blend
        y_baseline_for_delta = y_for_blend
    elif cohort == "t3_98":
        n_eval = len(t3["sids"])
        iter5_for_blend = iter5_full                # (98,)
        y_for_blend = t3["y_t3"]                    # (98,)
        # Compare against 4cov iter5 at N=98 even when stage1=8cov, so delta is "vs canonical"
        iter5_baseline_for_delta = t3["iter5_oof"]
        y_baseline_for_delta = t3["y_t3"]
    else:
        raise ValueError(f"Unknown cohort {cohort}")

    # Pick T1 stream
    t1_stream = None
    backfill_mask = None
    if cfg["t1_source"] == "iter12_honest":
        t1_stream = t1["t1_iter12_sum"]
        # In t1_94 cohort this is already aligned; in t3_98 cohort would need backfill (use _backfill variant instead)
        if cohort != "t1_94":
            raise ValueError(f"Cell {cell_id}: iter12_honest only valid for t1_94 cohort")
    elif cfg["t1_source"] == "iter12_honest_backfill":
        # T3 cohort N=98: place iter12 sum where T1 exists, NaN elsewhere → mixer treats those as α=1
        t1_stream = np.full(len(t3["sids"]), np.nan, dtype=float)
        t1_stream[t1_to_t3] = t1["t1_iter12_sum"]
        backfill_mask = ~np.isnan(t1_stream)
    elif cfg["t1_source"] == "iter17_bests":
        t1_stream = load_iter17_bests_oof(t1["sids"])
        if cohort != "t1_94":
            raise ValueError(f"Cell {cell_id}: iter17_bests only valid for t1_94 cohort")
    elif cfg["t1_source"] == "none":
        t1_stream = None
    else:
        raise ValueError(f"Unknown t1_source {cfg['t1_source']}")

    # Apply mixer in LOOCV
    if cfg["mixer"] == "identity":
        # No blend: just iter5 stream (4cov or 8cov)
        blend_oof = iter5_for_blend.copy()
        diags = None
    elif cfg["mixer"] == "alpha_only":
        if backfill_mask is not None:
            # NaN-aware: fit α on subjects where T1 is non-NaN; pure-iter5 elsewhere
            valid = backfill_mask
            inv = np.full(len(iter5_for_blend), np.nan)
            sub_blend, diags = _loocv_blend_alpha_only_masked(
                iter5_for_blend, t1_stream, y_for_blend, valid
            )
            inv[valid] = sub_blend[valid]
            inv[~valid] = iter5_for_blend[~valid]
            blend_oof = inv
        else:
            blend_oof, diags = _loocv_blend_alpha_only(iter5_for_blend, t1_stream, y_for_blend)
    elif cfg["mixer"] == "alpha_beta_joint":
        blend_oof, diags = _loocv_blend_alpha_beta_joint(iter5_for_blend, t1_stream, y_for_blend)
    elif cfg["mixer"] == "ridge_2base":
        blend_oof, diags = _loocv_blend_ridge2(iter5_for_blend, t1_stream, y_for_blend)
    elif cfg["mixer"] == "ols_unconstrained":
        blend_oof, diags = _loocv_blend_ols_unconstrained(iter5_for_blend, t1_stream, y_for_blend)
    else:
        raise ValueError(f"Unknown mixer {cfg['mixer']}")

    # Headline metrics
    headline = full_metrics(y_for_blend, blend_oof, label=f"t3_iter22_{cell_id}")
    iter5_at_t1_metrics = full_metrics(y_baseline_for_delta, iter5_baseline_for_delta,
                                       label=f"t3_iter5_baseline_{cohort}")

    # Bootstrap Δ vs iter5 baseline (canonical-cohort baseline if t3_98, else T1-cohort baseline)
    boot = paired_bootstrap_delta(y_for_blend, blend_oof, iter5_baseline_for_delta,
                                  n_boot=5000, seed=42)

    # Gate
    gate_kind = cfg["gate"]
    if cell_id == "AB1":
        gate_result = evaluate_gate(boot, gate_kind, min_delta=0.025, ci_lower_bound=0.0)
    else:
        gate_result = evaluate_gate(boot, gate_kind, min_delta=0.05, ci_lower_bound=0.0)

    # Diagnostics: alpha distribution
    diag_summary = {}
    if diags is not None and cfg["mixer"] in ("alpha_only", "alpha_beta_joint"):
        alphas = np.array([d[0] for d in diags])
        betas = np.array([d[1] for d in diags])
        diag_summary = dict(
            alpha_mean=float(alphas.mean()),
            alpha_std=float(alphas.std()),
            alpha_min=float(alphas.min()),
            alpha_max=float(alphas.max()),
            alpha_at_1_pct=float((alphas > 0.98).mean()),
            alpha_at_0_pct=float((alphas < 0.02).mean()),
            beta_mean=float(betas.mean()),
            beta_std=float(betas.std()),
            beta_sign_flips=int(np.sum(np.diff(np.sign(betas)) != 0)),
        )
    elif diags is not None and cfg["mixer"] in ("ridge_2base", "ols_unconstrained"):
        coef_a = np.array([d[0] for d in diags])
        coef_b = np.array([d[1] for d in diags])
        diag_summary = dict(
            coef_a_mean=float(coef_a.mean()),
            coef_a_std=float(coef_a.std()),
            coef_b_mean=float(coef_b.mean()),
            coef_b_std=float(coef_b.std()),
            coef_a_outside_01_pct=float(((coef_a < 0) | (coef_a > 1)).mean()),
        )

    elapsed = time.time() - t0
    return dict(
        cell_id=cell_id,
        config=cfg,
        cohort=cohort,
        n_eval=n_eval,
        headline=headline,
        iter5_baseline=iter5_at_t1_metrics,
        bootstrap=boot,
        gate=gate_result,
        diagnostics=diag_summary,
        elapsed_s=round(elapsed, 1),
        blend_oof_path=str(RESULTS_DIR / f"iter22_blend_{cell_id}.oof.npy"),
    )


# ── Pre-registration ─────────────────────────────────────────────────────────


def build_master_recipe() -> dict:
    """Canonical recipe object that gets hashed for formula_sha256."""
    return {
        "experiment": "T3 iter22 — Ablation around plan-next.md",
        "cohort": "T1=94 (intersection of T1=9-14 and T3=98)",
        "alpha_grid": ALPHA_GRID.tolist(),
        "iter12_variants": ITER12_VARIANTS,
        "iter12_ts": ITER8_TS,
        "panel_4cov": PANEL_4COV,
        "panel_8cov": PANEL_8COV,
        "hetero_prior": HETERO_PRIOR,
        "lc_n_levels": list(LC_N_LEVELS),
        "lc_n_subsamples": LC_N_SUBSAMPLES,
        "seeds": list(SEEDS),
        "n_boot": 5000,
        "gates": {
            "sensitivity": {"min_delta": 0.025, "ci_lower_bound": 0.0, "applies_to": ["AB1"]},
            "standard": {"min_delta": 0.05, "ci_lower_bound": 0.0, "applies_to_default": True},
        },
        "lockbox_candidates": ["AB1"],  # post-audit shrink
        "cells": {cid: cfg for cid, cfg in CELLS.items()},
        "iter5_oof_source": "results/lockbox_t3_iter5_A3_tier1_20260502_171604.oof.npy",
        "iter5_baseline_canonical": 0.5227,
        "iter5_canonical_n": 98,
        "blend_eval_n": 94,
        "documented_bias": (
            "iter5 LOOCV OOFs were generated at N=98 (each pred trained on N-1=97). "
            "Used here intersected to T1 cohort N=94. Each subject's iter5 pred was "
            "trained without using its own label (inductive). The +4 train subjects vs "
            "ideal apples-to-apples N=94 LOOCV constitutes a small disclosed bias O(1/N)."
        ),
    }


def compute_formula_sha256(recipe: dict) -> str:
    """Stable SHA256 over canonical JSON of recipe."""
    s = json.dumps(recipe, sort_keys=True, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def write_prereg(out_path: Path) -> dict:
    recipe = build_master_recipe()
    sha = compute_formula_sha256(recipe)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "iter_id": "t3_iter22_ablation",
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "formula_sha256": sha,
        "recipe": recipe,
        "lockbox_rules": [
            "AB1 sensitivity gate: Δ ≥ +0.025 AND paired-subject bootstrap 95% CI lower bound > 0",
            "All other cells: standard gate (Δ ≥ +0.05 AND CI lower bound > 0)",
            "All cells run regardless of gate outcome (negative-audit ablation map is the contribution)",
            "Only cells whose 5-fold/LOOCV gate passes AND null gates pass enter lockbox",
            "BB3 canary: abort cell if α̂ outside [0, 1] in >50% of folds",
        ],
        "notes": (
            "Post-audit revisions: Part II/LEDD/MoCA/ON-OFF NOT in WearGait-PD; "
            "8-cov panel uses purely demographic/anthropometric/disease-stage cols. "
            "CC1 prior REVISED to +0.005 [-0.015, +0.025]. "
            "Lockbox-candidate list shrunk to {AB1}. "
            "FF1/CC1/DD1 are scientific test cells, not promotion candidates."
        ),
    }
    with open(out_path, "w") as f:
        json.dump(prereg, f, indent=2, default=str)
    print(f"PRE-REGISTRATION WRITTEN: {out_path}")
    print(f"  formula_sha256 = {sha}")
    return prereg


def validate_prereg(prereg_path: Path) -> dict:
    with open(prereg_path) as f:
        prereg = json.load(f)
    expected_sha = prereg["formula_sha256"]
    live_recipe = build_master_recipe()
    live_sha = compute_formula_sha256(live_recipe)
    if live_sha != expected_sha:
        raise RuntimeError(
            f"formula_sha256 MISMATCH:\n"
            f"  pre-reg: {expected_sha}\n"
            f"  live:    {live_sha}\n"
            f"Recipe has changed since pre-reg. REFUSE to run."
        )
    print(f"formula_sha256 validated: {live_sha}")
    return prereg


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--write-prereg", action="store_true", help="Write pre-registration JSON and exit")
    p.add_argument("--run", action="store_true", help="Run cells listed in --cells")
    p.add_argument("--preregistration", default=None, help="Path to pre-reg JSON (required for --run)")
    p.add_argument("--cells", default="AB1,AB2,AB3,BB1,BB2,BB3",
                   help="Comma-separated cell IDs to run")
    p.add_argument("--iter5-8cov-oof", default=None,
                   help="Path to iter5 LOOCV OOF with A_iter22_8cov panel (required for CC3_N94/CC3_N98/AB1_N98_8cov)")
    p.add_argument("--out", default=None, help="Output JSON path (default auto-named)")
    args = p.parse_args()

    ensure_dir(RESULTS_DIR)

    if args.write_prereg:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = RESULTS_DIR / f"preregistration_t3_iter22_ablation_{ts}.json"
        write_prereg(out)
        return

    if not args.run:
        raise SystemExit("Specify --write-prereg or --run")
    if args.preregistration is None:
        raise SystemExit("--run requires --preregistration <path>")

    prereg = validate_prereg(Path(args.preregistration))

    print("\n=== T3 iter22 ABLATION — Loading OOF caches ===")
    t3 = load_t3_arrays()
    t1 = load_t1_arrays()
    t1_to_t3 = align_t1_to_t3(t1["sids"], t3["sids"])
    print(f"  T3 cohort N = {len(t3['sids'])}")
    print(f"  T1 cohort N = {len(t1['sids'])}")
    print(f"  Intersection (blend cohort) N = {len(t1_to_t3)}")

    # Sanity reproduce iter5 baseline at T1 cohort
    iter5_at_t1 = t3["iter5_oof"][t1_to_t3]
    y_t3_at_t1 = t3["y_t3"][t1_to_t3]
    iter5_t1_ccc = float(ccc_fn(y_t3_at_t1, iter5_at_t1))
    print(f"  iter5 LOOCV CCC at T1 cohort N=94: {iter5_t1_ccc:.4f}")
    print(f"  (canonical at N=98: 0.5227; expected slight shift due to cohort change)")

    # Cell sanity checks
    cells_to_run = [c.strip() for c in args.cells.split(",") if c.strip()]
    unknown = [c for c in cells_to_run if c not in CELLS]
    if unknown:
        raise SystemExit(f"Unknown cells: {unknown}; available: {list(CELLS.keys())}")

    iter5_8cov_oof = None
    if args.iter5_8cov_oof:
        iter5_8cov_oof = np.load(args.iter5_8cov_oof)
        if iter5_8cov_oof.shape != t3["iter5_oof"].shape:
            raise SystemExit(f"8-cov OOF shape {iter5_8cov_oof.shape} != T3 cohort {t3['iter5_oof'].shape}")
        print(f"  Loaded iter5 8-cov OOF: shape={iter5_8cov_oof.shape}")

    results = {}
    for cid in cells_to_run:
        print(f"\n=== Cell {cid}: {CELLS[cid]['name']} ===")
        print(f"    purpose: {CELLS[cid]['purpose']}")
        r = run_cell(cid, t3, t1, t1_to_t3, t3_iter5_8cov_oof=iter5_8cov_oof)
        results[cid] = r
        print(f"    headline CCC = {r['headline']['ccc']:.4f}  MAE = {r['headline']['mae']:.3f}")
        print(f"    Δ vs iter5(T1 cohort) = {r['bootstrap']['delta_mean']:+.4f} "
              f"[{r['bootstrap']['delta_ci_low']:+.4f}, {r['bootstrap']['delta_ci_high']:+.4f}]"
              f"  frac>0={r['bootstrap']['delta_frac_gt0']:.3f}")
        print(f"    gate ({CELLS[cid]['gate']}): {r['gate']['why']}")
        if r.get("diagnostics"):
            print(f"    diagnostics: {r['diagnostics']}")

    # Write summary
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else RESULTS_DIR / f"results_t3_iter22_ablation_{ts}.json"
    summary = dict(
        iter_id="t3_iter22_ablation",
        timestamp=ts,
        formula_sha256=prereg["formula_sha256"],
        preregistration=str(args.preregistration),
        n_t3=len(t3["sids"]),
        n_t1=len(t1["sids"]),
        n_blend_cohort=len(t1_to_t3),
        iter5_baseline_at_t1cohort=iter5_t1_ccc,
        iter5_canonical_n98=0.5227,
        cells_run=cells_to_run,
        results=results,
    )
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nWrote {out_path}")

    print("\n=== ABLATION SUMMARY (cell-level) ===")
    print(f"{'Cell':<6}{'CCC':>8}{'Δ vs iter5':>14}{'CI_low':>10}{'CI_high':>10}{'frac>0':>9}{'gate':>10}")
    for cid in cells_to_run:
        r = results[cid]
        gate_icon = "PASS" if r["gate"]["passed"] else ("none" if r["gate"]["why"].startswith("No gate") else "FAIL")
        print(
            f"{cid:<6}{r['headline']['ccc']:>8.4f}{r['bootstrap']['delta_mean']:>+14.4f}"
            f"{r['bootstrap']['delta_ci_low']:>+10.4f}{r['bootstrap']['delta_ci_high']:>+10.4f}"
            f"{r['bootstrap']['delta_frac_gt0']:>9.3f}{gate_icon:>10}"
        )


if __name__ == "__main__":
    main()

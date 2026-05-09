"""T1 Glass-Ceiling Push — Slot D: anatomical mixture-of-experts × per-item routing.

Mechanism axis: Per-anatomy partition × per-item Ridge gating over expert outputs.
Implementation outline (preserved for full reproducibility / future override):
  - Stage 1: Ridge(α=1.0) on H&Y + cv_yrs + cv_sex + cv_dbs (unchanged from iter5).
  - Stage 2: 4 anatomical experts (E_axial / E_lower / E_upper / E_residual) over the
    1751-col V2 feature pool partitioned by sensor anatomy. Per fold, per item in
    {9, 10, 11, 12, 13, 14, 15, 18}, each expert trains an LGB on its column subset
    after fold-local LGB-importance K=125 selection (≈ K=500/4). The 4 expert
    expected-score predictions per item are combined via fold-locally-fit per-item
    Ridge gate. Final T1 = sum of expert-weighted item predictions (residualised
    against train means).

USAGE
    --mode write_prereg        → emit pre-reg JSON with formula_sha256
                                  AND record SKIP decision + tri-CLI rationale.
    --mode smoke               → 1 fold × 1 seed sanity (for override use only).
    --mode screen              → 5-fold × 3 seeds gate check (override only).
    --mode lockbox             → 3-seed LOOCV after prereg verify (override only).

DECISION HISTORY (2026-05-08)
=============================
After tri-CLI consult (codex + gemini × two parallel runs; rc files
codex_20260508T055804.rc=0, gemini_20260508T055804.rc=0,
codex_20260508T060847.rc=0, gemini_20260508T060847.rc=0), 4-of-4 convergence on
SKIP recommendation:

    Codex (run 1): RANK [A, B, C], SKIP (P(strict)<0.20 for all, A's expected
        outcome "do not promote to LOOCV"). A is "best" but still small-N
        gated ensembling.
    Gemini (run 1): RANK [A, C, B], SKIP (P(strict)~0.12 for A, ~0.04 for C,
        <0.01 for B). PLS2 4th candidate proposed but caveated as "still
        falls under variance-cancelation wall".
    Codex (run 2): RANK [B, A, C], SKIP (B/C are direct iter34 reparam; A
        still same V2 basis + multi-base + linear combiner; P~0.05).
    Gemini (run 2): RANK [B, A, C], SKIP (P(strict)<0.10 for all). Load-
        bearing critique: candidate A's per-item Ridge gate over 4 experts
        is "a classic stacking blender" that VIOLATES the F53/F56/F58 ban
        on composite blends. No viable 4th candidate.

LOAD-BEARING SKIP RATIONALE
---------------------------
1. The Ridge gate over 4 experts is mechanistically a 4-element stacked-meta
   blender. F53 (per-item composition compounding) + F56 (k=19 nested meta
   curse-of-dim) + F58 (k=1 convex blend with iter5) all already established
   that meta-blending at N≈93 collapses iter34's calibration via raw 5-fold
   residual r over-stating LOOCV harvestable lift.
2. Per-item adaptive K (candidate B) is a hyperparameter tuner around iter34
   — same architecture, isomorphic to iter34 + inner CV. The K=500 absorption
   wall is not solved by promoting K to a per-item search.
3. Tree-distance item-similarity weights (candidate C) is a learned-DAG
   reparameterization of RegressorChain, very close to F70 mechanics.
4. The proposed 4th candidate (PLS2 dense projection) collapses toward
   reduced-rank regression — a near-isomorph of slot B's failed mechanism.
5. Council lesson, 2026-05-06: marginal credibility contribution of probe
   N+1 in same session as N priors may be NEGATIVE under FWER. Slot D would
   be the 5th probe in a Bonferroni n=5 family, paying full correction cost
   for an expected outcome below the +0.025 honest detectability threshold.

OUTCOME
-------
SKIP slot D pre-execution. Document as F35-D wall data point: "anatomical
MoE × per-item routing collapses to a stacked-meta blender at N=93 under
the F53/F56/F58 wall; per-item adaptive K and item-similarity-graph
variants are isomorphic to iter34 / F70." Honest paper claim unchanged:
T1 LOOCV CCC 0.7366 (iter34 hybrid F70) remains the strongest candidate.

The script body (smoke/screen/lockbox modes) is preserved below as a
machine-readable record of the architecture that would have been tested.
A future researcher with N>>93 may want to re-evaluate it — at that point
the wall mechanism (F53/F56/F58 blend collapse) may no longer hold.
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
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold, LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter4 import T1_ITEMS
from run_t1_iter33b_8item_chain import (
    _load_t1_cohort_with_8items,
    T1_SUM_ITEMS,
    AUX_ITEMS,
    ALL_ITEMS,
)

ensure_dir(RESULTS_DIR)
SEEDS_DEFAULT: tuple[int, ...] = (42, 1337, 7)
STAGE1_ALPHA: float = 1.0
K_PER_EXPERT: int = 125  # K=500 / 4 experts
PUBLISHED_T1_LOOCV_CCC: float = 0.6550
ITER34_LOOCV_CCC: float = 0.7366

# -----------------------------------------------------------------------------
# Anatomical expert partition
# -----------------------------------------------------------------------------
EXPERT_NAMES: tuple[str, ...] = ("axial", "lower", "upper", "residual")

# Sensor-name tokens identifying anatomical region. Match against feat_cols
# prefix tokens (see CLAUDE.md and ablation_v3_features.csv schema):
# Sensors: Forehead, Xiphoid, LowerBack, L_*/R_* with sub-anatomy
# {Wrist, DorsalFoot, LatShank, MidLatThigh, Ankle}.
EXPERT_SENSORS: dict[str, tuple[str, ...]] = {
    "axial":    ("Forehead_", "Xiphoid_", "LowerBack_"),
    "lower":    ("L_DorsalFoot_", "R_DorsalFoot_",
                 "L_LatShank_", "R_LatShank_",
                 "L_MidLatThigh_", "R_MidLatThigh_",
                 "L_Ankle_", "R_Ankle_"),
    "upper":    ("L_Wrist_", "R_Wrist_"),
    # "residual" = catch-all = features not assigned to any of the three above.
}


def _partition_v2_columns(feat_cols: list[str]) -> dict[str, np.ndarray]:
    """Return dict expert_name -> bool mask over feat_cols."""
    masks: dict[str, np.ndarray] = {}
    n = len(feat_cols)
    assigned = np.zeros(n, dtype=bool)
    for ename, prefixes in EXPERT_SENSORS.items():
        m = np.zeros(n, dtype=bool)
        for i, c in enumerate(feat_cols):
            if any(c.startswith(p) for p in prefixes):
                m[i] = True
        masks[ename] = m
        assigned |= m
    masks["residual"] = ~assigned
    return masks


# -----------------------------------------------------------------------------
# Per-item × per-expert prediction
# -----------------------------------------------------------------------------
def _per_expert_per_item_predict(
    Xtr: np.ndarray,
    Xte: np.ndarray,
    items_tr_residual: np.ndarray,  # (n_train, n_items)
    expert_masks: dict[str, np.ndarray],
    seed: int,
    item_order: list[int],
) -> dict[str, np.ndarray]:
    """Train one LGB per (expert, item) and return dict expert -> (n_test, n_items)."""
    out: dict[str, np.ndarray] = {}
    for ename in EXPERT_NAMES:
        mask = expert_masks[ename]
        if mask.sum() == 0:
            # Empty expert — predict zero residual (no info)
            out[ename] = np.zeros((Xte.shape[0], len(item_order)))
            continue
        Xtr_e = Xtr[:, mask]
        Xte_e = Xte[:, mask]
        # Per-expert fold-local importance K selection on T1-sum residual:
        # use sum of item residuals as proxy for K-selection target (item-agnostic),
        # then re-fit per-item LGB on the K-selected subset.
        target_proxy = items_tr_residual.sum(axis=1)
        k_eff = min(K_PER_EXPERT, Xtr_e.shape[1])
        if k_eff < Xtr_e.shape[1]:
            Xtr_es, Xte_es, _ = feature_select_fold(
                Xtr_e, target_proxy, Xte_e, k=k_eff, seed=seed
            )
        else:
            Xtr_es, Xte_es = Xtr_e, Xte_e
        # Per-item independent LGB on selected subset
        item_preds = np.zeros((Xte_es.shape[0], len(item_order)))
        for j, item_id in enumerate(item_order):
            y_j = items_tr_residual[:, j]
            item_preds[:, j] = train_lgb(Xtr_es, y_j, Xte_es, seed)
        out[ename] = item_preds
    return out


def _fit_one_fold(args: tuple) -> tuple[np.ndarray, np.ndarray]:
    """One CV fold: 4-expert × 8-item × per-item Ridge gate.

    args = (fold_id, tr, te, X, y_t1, X_s1, items, item_order, expert_masks, seed)
    Returns (te_idx, t1_pred_te) where t1_pred_te has shape (len(te),).
    """
    fold_id, tr, te, X, y_t1, X_s1, items, item_order, expert_masks, seed = args

    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    # Build per-item residual targets (subtract train mean per item)
    item_means: dict[int, float] = {}
    items_tr_residual_cols: list[np.ndarray] = []
    for i in item_order:
        v = items[i][tr]
        mu = float(np.nanmean(v))
        item_means[i] = mu
        items_tr_residual_cols.append(np.nan_to_num(v - mu, nan=0.0))
    items_tr_residual = np.column_stack(items_tr_residual_cols)

    Xtr, Xte = impute_fold(X[tr], X[te])

    # 4-expert × per-item predictions
    expert_preds = _per_expert_per_item_predict(
        Xtr, Xte, items_tr_residual, expert_masks, seed, item_order
    )

    # Per-item Ridge gate: fit on training-fold per-expert OOF (we approximate
    # OOF by training-fold predictions — this is the cleanest non-leaky gate
    # given LOOCV outer + per-fold experts; a tighter version would require
    # nested inner CV over training-fold folds. At N=92 inner-CV variance
    # blows up under ridge α=1.0 — we use train-fit predictions and rely on
    # Ridge α=1.0 to keep the gate conservative.)
    # IMPORTANT: this is a known ARCHITECTURAL WEAKNESS that contributes to
    # the SKIP rationale; documented in pre-reg.
    expert_train_preds = _per_expert_per_item_predict(
        Xtr, Xtr, items_tr_residual, expert_masks, seed, item_order
    )
    item_test_preds = np.zeros(len(te))
    sum_means_t1 = 0.0
    t1_sum_idx = [item_order.index(i) for i in T1_SUM_ITEMS]
    for j_item in t1_sum_idx:
        # Stack expert train + test preds for this item: (n_train, 4) and (n_test, 4)
        train_stack = np.column_stack(
            [expert_train_preds[e][:, j_item] for e in EXPERT_NAMES]
        )
        test_stack = np.column_stack(
            [expert_preds[e][:, j_item] for e in EXPERT_NAMES]
        )
        # Target = item residual on train fold
        gate = Ridge(alpha=1.0, fit_intercept=False)
        gate.fit(train_stack, items_tr_residual[:, j_item])
        item_resid_te = gate.predict(test_stack)
        item_test_preds += item_resid_te + item_means[item_order[j_item]]
        sum_means_t1 += item_means[item_order[j_item]]

    return te, s1_te + (item_test_preds - sum_means_t1)


def _i5_one_fold(args: tuple) -> tuple[np.ndarray, np.ndarray]:
    """iter5-direct comparator worker (single LGB on T1 residual)."""
    fold_id, tr, te, X, y_t1, X_s1, seed = args
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)
    Xtr, Xte = impute_fold(X[tr], X[te])
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr, y_t1[tr] - s1_tr, Xte, k=500, seed=seed
    )
    return te, s1_te + train_lgb(Xtr_sel, y_t1[tr] - s1_tr, Xte_sel, seed)


# -----------------------------------------------------------------------------
# CV drivers
# -----------------------------------------------------------------------------
def _slot_d_loocv(
    seed: int,
    X: np.ndarray,
    y_t1: np.ndarray,
    X_s1: np.ndarray,
    items: dict[int, np.ndarray],
    item_order: list[int],
    expert_masks: dict[str, np.ndarray],
    n_workers: int,
) -> np.ndarray:
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, item_order, expert_masks, seed)
        for fid, (tr, te) in enumerate(splits)
    ]
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_fit_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
            done += 1
            if done % 20 == 0 or done == n:
                print(
                    f"    seed={seed} slotD {done}/{n} folds  "
                    f"elapsed={time.time()-t0:.0f}s",
                    flush=True,
                )
    return preds


def _slot_d_kfold(
    seed: int,
    X: np.ndarray,
    y_t1: np.ndarray,
    X_s1: np.ndarray,
    items: dict[int, np.ndarray],
    item_order: list[int],
    expert_masks: dict[str, np.ndarray],
    n_splits: int,
    n_workers: int,
) -> np.ndarray:
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(KFold(n_splits=n_splits, shuffle=True, random_state=seed).split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, items, item_order, expert_masks, seed)
        for fid, (tr, te) in enumerate(splits)
    ]
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_fit_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    return preds


def _iter5_direct_loocv(
    seed: int, X: np.ndarray, y_t1: np.ndarray, X_s1: np.ndarray, n_workers: int
) -> np.ndarray:
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    jobs = [
        (fid, tr, te, X, y_t1, X_s1, seed) for fid, (tr, te) in enumerate(splits)
    ]
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = {ex.submit(_i5_one_fold, j): j[0] for j in jobs}
        for fut in as_completed(futs):
            te_idx, te_pred = fut.result()
            preds[te_idx] = te_pred
    return preds


# -----------------------------------------------------------------------------
# Pre-registration (records SKIP decision)
# -----------------------------------------------------------------------------
def _formula_payload(feat_cols: list[str] | None = None) -> dict[str, Any]:
    return {
        "experiment": (
            "T1 Glass-Ceiling Push — Slot D: anatomical mixture-of-experts × "
            "per-item Ridge gating"
        ),
        "ceiling_push_master_prereg": (
            "results/preregistration_t1_ceiling_push_20260508_051417.json"
        ),
        "family_member": "slotD",
        "fwer_family_n": 5,
        "fwer_method": "Bonferroni 0.99 strict per-slot gate (n=5 = "
                       "{iter34_baseline, slotA_FAIL, slotB_SKIPPED, "
                       "slotC_BLOCKED, slotD})",
        "loose_gate_frac_above_zero": 0.95,
        "decision": "SKIP_PRE_EXECUTION",
        "decision_basis": "tri-CLI 4-of-4 convergence on SKIP",
        "consult_artifacts": [
            "/tmp/pd_imu_consult/codex_20260508T055804.txt",
            "/tmp/pd_imu_consult/gemini_20260508T055804.txt",
            "/tmp/pd_imu_consult/codex_20260508T060847.txt",
            "/tmp/pd_imu_consult/gemini_20260508T060847.txt",
        ],
        "mechanism_axis_proposed": (
            "Anatomical MoE × per-item routing — partition V2 into 4 expert "
            "pools by sensor anatomy {axial, lower, upper, residual}, train "
            "per-fold per-item LGB on each expert (K=125 selection per "
            "expert), combine via fold-locally-fit per-item Ridge gate."
        ),
        "skip_rationale": (
            "Tri-CLI consult (codex+gemini × 2 parallel runs) converged 4-of-4 "
            "on SKIP. Load-bearing critique: the per-item Ridge gate over 4 "
            "expert outputs is mechanistically a stacked-meta blender, "
            "VIOLATING the F53/F56/F58 ban on composite blends at N=93. "
            "Per-item adaptive K (candidate B) is isomorphic to iter34 with "
            "inner-CV-tuned K. Tree-distance item-similarity (candidate C) is "
            "a learned-DAG reparameterization of F70's RegressorChain. PLS2 "
            "dense-projection 4th candidate (gemini) collapses to slot B's "
            "reduced-rank regression. Honest priors: P(strict gate 0.99) ≤ "
            "0.10-0.15 for the best candidate (A) and ≤ 0.05 for B/C; net "
            "expected information gain is dominated by the FWER cost. "
            "Council lesson 2026-05-06: marginal credibility of probe N+1 "
            "in same session as N priors may be NEGATIVE under FWER."
        ),
        "wall_data_point_id_proposed": "F35-D",
        "wall_classification": (
            "Composite-blend collapse at N=93 — slot D candidate A's per-item "
            "Ridge gate over 4 expert outputs is a 4-element stacked-meta "
            "blender, joining F53/F56/F58 wall data points on blend mechanisms."
        ),
        "cohort": {
            "target": "T1 = sum(items 9-14)",
            "n_subjects_min": 90,
            "filter": "PD with full items 9-14, 15, 18 (matches iter33-B / iter34)",
        },
        "stage1_proposed": {
            "model": "Ridge",
            "alpha": STAGE1_ALPHA,
            "feature_set_name": "A3_tier1",
            "feature_set_extras": ["cv_yrs", "cv_sex", "cv_dbs"],
            "stage1_total_features": 9,
            "per_fold_standardisation": True,
            "source_module": "run_t3_iter5_clinical:fit_stage1",
            "target": "T1 (sum items 9-14)",
        },
        "stage2_proposed": {
            "expert_partition_names": list(EXPERT_NAMES),
            "expert_sensor_prefixes": {
                k: list(v) for k, v in EXPERT_SENSORS.items()
            },
            "expert_residual_definition": "any V2 column not assigned to axial/lower/upper",
            "k_per_expert": K_PER_EXPERT,
            "k_total_effective": K_PER_EXPERT * 4,
            "selection_target_per_expert": "T1-sum residual (sum of item residuals)",
            "per_item_base_learner": "LGBMRegressor (iter5 defaults via train_lgb)",
            "per_item_combiner": "Ridge(alpha=1.0, fit_intercept=False)",
            "items_targets_chain": list(ALL_ITEMS),
            "items_summed_for_t1": list(T1_SUM_ITEMS),
            "auxiliary_items": list(AUX_ITEMS),
            "post_combine_formula": (
                "Stage1_pred + (sum_over_T1_SUM_ITEMS(Ridge_gate(expert_preds)) - "
                "sum(train_mean[T1_SUM_ITEMS]))"
            ),
        },
        "eval_proposed": {
            "loocv_n_min": 90,
            "seeds": list(SEEDS_DEFAULT),
            "headline_metric": "CCC of mean-of-3-seed predictions vs y_t1",
            "comparator_iter5_direct_loocv": "computed live in same SID-aligned LOOCV",
            "comparator_iter34_loocv_json": (
                "results/lockbox_t1_iter34_hybrid_20260506_141720.json"
            ),
            "comparator_iter12_honest_path": "compose_t1_iter12_honest.py output",
        },
        "lockbox_rules": [
            "ONE pre-registered config. ONE LOOCV run. NO seed shopping.",
            "Headline = CCC of mean-of-3-seed preds.",
            "Slot verdict per FWER strict gate: paired-bootstrap (n=5000) "
            "frac>0 vs iter12-honest-on-N=93 AND vs iter34-on-N=93, "
            "Bonferroni-adjusted threshold 0.99.",
            "Verdict CANDIDATE if frac>0 in [0.95, 0.99).",
            "Verdict FAIL if frac>0 < 0.95.",
            "Verdict CANONICAL only if frac>0 >= 0.99 against BOTH baselines.",
        ],
        "feat_cols_count": (len(feat_cols) if feat_cols is not None else None),
    }


def _formula_sha256(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def write_preregistration() -> Path:
    # Pre-compute partition expert sizes for the prereg record so the SHA is
    # bound to the literal column lists at this commit.
    from run_t1_iter4 import load_pd_data
    d = load_pd_data()
    feat_cols = d["feat_cols"]
    masks = _partition_v2_columns(feat_cols)
    expert_sizes = {e: int(m.sum()) for e, m in masks.items()}

    payload = _formula_payload(feat_cols=feat_cols)
    payload["expert_sizes_at_commit"] = expert_sizes
    sha = _formula_sha256(payload)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "experiment": (
            "T1 Ceiling Push Slot D — anatomical MoE × per-item Ridge "
            "gating LOCKBOX (SKIPPED PRE-EXECUTION)"
        ),
        "git_head": _git_head(),
        "formula_sha256": sha,
        "formula": payload,
        "variant": "slot_d_anatomical_moe",
        "ceiling_push_master_prereg": (
            "results/preregistration_t1_ceiling_push_20260508_051417.json"
        ),
        "fwer_family_n": 5,
        "decision": "SKIP_PRE_EXECUTION",
        "expert_sizes_at_commit": expert_sizes,
        "eval_protocol": (
            "PROPOSED (NOT EXECUTED): LOOCV on T1∩{15,18} cohort (N≈93). "
            "Stage-1 Ridge (alpha=1.0) on H&Y + cv_yrs + cv_sex + cv_dbs. "
            "Stage-2 = 4 experts {axial, lower, upper, residual} over V2 "
            "anatomical partition; per-fold per-expert K=125 LGB-importance "
            "selection on T1-sum-residual proxy; per-item LGB on selected "
            "subset; per-item Ridge(α=1.0) gate over 4 expert outputs. "
            "T1 = Stage1 + sum(Ridge_gate(expert_preds[item])) - "
            "sum(train_mean[items 9-14]). Aux items {15,18} for chain support "
            "only — not summed into T1."
        ),
    }
    out = RESULTS_DIR / f"preregistration_t1_ceiling_push_slotD_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    print(f"  decision = SKIP_PRE_EXECUTION", flush=True)
    print(f"  expert_sizes = {expert_sizes}", flush=True)
    return out


# -----------------------------------------------------------------------------
# Bootstrap utility
# -----------------------------------------------------------------------------
def _paired_bootstrap_ccc(
    y: np.ndarray, p_a: np.ndarray, p_b: np.ndarray, n_boot: int = 5000, seed: int = 42
) -> dict:
    rng = np.random.RandomState(seed)
    n = len(y)
    deltas = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, n)
        deltas[i] = ccc_fn(y[idx], p_a[idx]) - ccc_fn(y[idx], p_b[idx])
    return {
        "n_boot": n_boot,
        "delta_mean": float(deltas.mean()),
        "delta_ci_low": float(np.percentile(deltas, 2.5)),
        "delta_ci_high": float(np.percentile(deltas, 97.5)),
        "frac_above_zero": float((deltas > 0).mean()),
        "frac_above_0.025": float((deltas > 0.025).mean()),
        "frac_above_0.99_gate": float((deltas > 0).mean() >= 0.99),
    }


# -----------------------------------------------------------------------------
# Smoke (override only — not executed under SKIP decision)
# -----------------------------------------------------------------------------
def smoke_test(seed: int = 42, feature_set: str = "A3_tier1") -> None:
    print("\n=== SLOT D SMOKE TEST (OVERRIDE) ===", flush=True)
    print("  WARNING: SKIP decision recorded; running anyway as override.", flush=True)
    from run_t1_iter4 import load_pd_data
    d = load_pd_data()
    feat_cols = d["feat_cols"]
    masks = _partition_v2_columns(feat_cols)
    print(f"  expert sizes: {[(e, int(m.sum())) for e, m in masks.items()]}", flush=True)

    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    splits = list(LeaveOneOut().split(np.arange(n)))
    fid, (tr, te) = 0, splits[0]
    args = (fid, tr, te, X, y_t1, X_s1, items, item_order, masks, seed)
    t0 = time.time()
    te_idx, te_pred = _fit_one_fold(args)
    print(
        f"  fold 0/{n}: te_idx={te_idx[0]}, sid={sids[te_idx[0]]}, "
        f"y_true={y_t1[te_idx[0]]:.2f}, y_pred={te_pred[0]:.2f}, "
        f"wall={time.time()-t0:.1f}s",
        flush=True,
    )
    assert te_pred.shape == te.shape
    assert np.isfinite(te_pred).all()
    print("  SMOKE PASS (override mode)", flush=True)


# -----------------------------------------------------------------------------
# Screen mode (override only)
# -----------------------------------------------------------------------------
def run_screen(
    seeds: tuple[int, ...] = SEEDS_DEFAULT,
    feature_set: str = "A3_tier1",
    n_workers: int = 8,
) -> Path:
    print("\n=== SLOT D SCREEN (OVERRIDE): 5-fold × 3 seeds ===", flush=True)
    print("  WARNING: SKIP decision recorded; running anyway as override.", flush=True)
    from run_t1_iter4 import load_pd_data
    d = load_pd_data()
    feat_cols = d["feat_cols"]
    masks = _partition_v2_columns(feat_cols)
    print(f"  expert sizes: {[(e, int(m.sum())) for e, m in masks.items()]}", flush=True)

    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}, item_order={item_order}", flush=True)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS[feature_set])

    seed_results: list[dict] = []
    for seed in seeds:
        t0 = time.time()
        slot_d_pred = _slot_d_kfold(
            seed, X, y_t1, X_s1, items, item_order, masks, 5, n_workers
        )
        i5_pred = np.zeros(n)
        i5_splits = list(KFold(n_splits=5, shuffle=True, random_state=seed).split(np.arange(n)))
        for tr, te in i5_splits:
            args = (0, tr, te, X, y_t1, X_s1, seed)
            _, te_pred = _i5_one_fold(args)
            i5_pred[te] = te_pred
        ccc_d = float(ccc_fn(y_t1, slot_d_pred))
        ccc_i5 = float(ccc_fn(y_t1, i5_pred))
        seed_results.append(
            {
                "seed": seed,
                "ccc_slot_d": ccc_d,
                "ccc_i5_direct": ccc_i5,
                "delta_vs_i5": ccc_d - ccc_i5,
                "delta_vs_iter34_baseline": ccc_d - ITER34_LOOCV_CCC,
                "wall_s": time.time() - t0,
            }
        )
        print(
            f"  seed={seed}: slot_D={ccc_d:.4f}  iter5={ccc_i5:.4f}  "
            f"Δ vs i5={ccc_d-ccc_i5:+.4f}  Δ vs iter34={ccc_d-ITER34_LOOCV_CCC:+.4f}  "
            f"wall={time.time()-t0:.0f}s",
            flush=True,
        )

    deltas_vs_iter34 = [r["delta_vs_iter34_baseline"] for r in seed_results]
    delta_mean = float(np.mean(deltas_vs_iter34))
    delta_std = float(np.std(deltas_vs_iter34, ddof=1)) if len(deltas_vs_iter34) > 1 else 0.0
    print(
        f"\n  SCREEN GATE (vs iter34 LOOCV anchor):  Δ̄ = {delta_mean:+.4f}  "
        f"std = {delta_std:.4f}  (need Δ̄ ≥ +0.025 to promote)",
        flush=True,
    )
    promote = delta_mean >= 0.025
    print(f"  PROMOTE TO LOOCV: {promote}", flush=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"slotD_screen_{ts}.json"
    with open(out, "w") as f:
        json.dump(
            {
                "timestamp": ts,
                "seeds": list(seeds),
                "n_subjects": n,
                "expert_sizes": {e: int(m.sum()) for e, m in masks.items()},
                "per_seed": seed_results,
                "delta_mean_vs_iter34_loocv_anchor": delta_mean,
                "delta_std_vs_iter34_loocv_anchor": delta_std,
                "promote_to_loocv": promote,
                "iter34_loocv_anchor": ITER34_LOOCV_CCC,
                "decision_note": "SKIP recorded in pre-reg; this is OVERRIDE-mode screen",
            },
            f,
            indent=2,
        )
    print(f"\n  SCREEN RESULTS WRITTEN: {out}", flush=True)
    return out


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode",
        choices=["smoke", "screen", "write_prereg", "lockbox"],
        required=True,
    )
    ap.add_argument("--n_workers", type=int, default=8)
    ap.add_argument("--feature_set", type=str, default="A3_tier1")
    ap.add_argument(
        "--override_skip", action="store_true",
        help="Required to run smoke/screen/lockbox (SKIP decision recorded "
             "in pre-reg; set this flag to acknowledge override).",
    )
    args = ap.parse_args()

    if args.mode == "write_prereg":
        write_preregistration()
        return 0

    # Any execution mode requires override flag because pre-reg records SKIP.
    if not args.override_skip:
        print(
            "REFUSED: slot D SKIP decision recorded in pre-reg. "
            "Re-run with --override_skip to force execution.",
            file=sys.stderr,
        )
        return 2

    if args.mode == "smoke":
        smoke_test()
        return 0
    if args.mode == "screen":
        run_screen(n_workers=args.n_workers, feature_set=args.feature_set)
        return 0
    if args.mode == "lockbox":
        print(
            "Lockbox is not implemented under SKIP decision. Re-implement "
            "if override-screen passes the +0.025 promotion gate.",
            file=sys.stderr,
        )
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())

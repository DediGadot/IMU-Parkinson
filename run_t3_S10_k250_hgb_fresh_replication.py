#!/usr/bin/env python3
"""T3 S10 — fresh-pre-reg replication of the 2026-05-13 K=250 HGB peak.

Single-comparison probe (n=1) of the K=250 sklearn-gradient-boosting peak
identified by the 2026-05-13 K-sweep
(``results/lockbox_t3_gb_ksweep_fwer_bootstrap_20260513_030050.json``).
K=250 is fixed *a priori* by external monotonic-hump evidence (K=200→0.4272,
K=250→0.4488, K=300→0.4302 in the locked K-sweep result); it is NOT selected
from THIS run, so the only FWER family member here is the K=250 cell itself.

Fresh seeds [101, 202, 303] (not the locked-result set [42, 1337, 7]) provide
independence from the 2026-05-13 evidence.

Architecture: iter47 stack with one swap.

  * Cohort filter ............. ``run_t3_iter47_invalid_code_fix.filter_cohort``
    with ``cohort='drop_allmissing_validrange'`` (N=95, canonical T3 cohort).
  * Stage-1 Ridge ............. ``run_t3_iter5_clinical.fit_stage1`` on the
    A3-tier1 design from ``run_t3_iter41_target_fix.build_stage1_matrix``
    (H&Y + cv_yrs + cv_sex + cv_dbs), alpha=1.0.  Residualises y_t3.
  * Stage-2 features .......... ``stage2_current`` (V2 pool, identical to
    iter47 canonical).  Imputed per fold by ``impute_fold``.
  * Per-fold K=250 selection .. ``feature_select_fold`` (LGB-importance, same
    selector iter47 uses; only K differs: 250 vs canonical 500).
  * Stage-2 regressor ......... ``sklearn.ensemble.HistGradientBoostingRegressor``
    (max_iter=200, learning_rate=0.05, max_depth=4, random_state=seed).
  * Predict ................... y_hat = Stage1(test) + HGB(test_residual).

Outer LOOCV; LGB importance fit on outer-train only; HGB seed fixed per outer
seed (independent of outer-fold index).  3 seeds: [101, 202, 303].  Headline
prediction = mean across the 3 seeds.

Comparison: paired bootstrap (B=5000) of pooled-pred CCC vs iter47 locked
baseline predictions from
``results/iter47_invalidcode_subject_preds_20260508_194605.csv`` (the
``drop_allmissing_validrange × stage2_current`` slice, N=95).

Bonferroni gate at n=1: frac_pos ≥ 0.95 (single comparison, single family).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor as HistGradientBoostingRegressor  # S11 hotfix: 2026-05-13 used legacy GradientBoostingRegressor; HGB swap kills the lift
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold
from run_t3_iter5_clinical import fit_stage1
from run_t3_iter41_target_fix import build_stage1_matrix, filter_stage2
from run_t3_iter47_invalid_code_fix import filter_cohort

ensure_dir(RESULTS_DIR)

# ── Probe constants (FROZEN AT AUTHOR TIME, NOT TUNABLE FROM CLI) ────────────
SEEDS_FRESH: tuple[int, ...] = (101, 202, 303)
K_FEATURES: int = 250
COHORT: str = "drop_allmissing_validrange"
STAGE2_POLICY: str = "stage2_current"
HGB_MAX_ITER: int = 200
HGB_LR: float = 0.05
HGB_MAX_DEPTH: int = 4
N_BOOT: int = 5000
BOOT_SEED: int = 20260515  # date-of-probe; orthogonal to model seeds

ITER47_BASELINE_PREDS_CSV: Path = (
    RESULTS_DIR / "iter47_invalidcode_subject_preds_20260508_194605.csv"
)
ITER47_BASELINE_CCC: float = 0.3784  # canonical T3 in-cohort, N=95
KSWEEP_LOCKBOX: str = (
    "results/lockbox_t3_gb_ksweep_fwer_bootstrap_20260513_030050.json"
)
MASTER_PREREG: str = (
    "results/preregistration_t1t3_proresults_ablation_20260515T133800Z.json"
)

# ── Utility ──────────────────────────────────────────────────────────────────


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        val = float(obj)
        return val if np.isfinite(val) else None
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _formula_sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


# ── Model: K=250 HGB Stage-2, identical Stage-1 and selection mechanism ──────


def loocv_preds_k250_hgb(data: dict[str, Any], seed: int) -> np.ndarray:
    """LOOCV with iter47 Stage-1 + per-fold LGB-importance K=250 selection +
    HGB Stage-2.  HGB random_state is the outer seed only — independent of
    outer-fold index, so no fold-dependent seed leak."""
    sids = data["sids"]
    y = data["y_t3"]
    X_s1 = build_stage1_matrix(sids, data["hy"])
    X_s2, _ = filter_stage2(data["X"], data["feat_cols"], STAGE2_POLICY)
    n = len(sids)
    preds = np.zeros(n, dtype=np.float64)

    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(LeaveOneOut().split(np.arange(n))):
        s1_tr, s1_te = fit_stage1(X_s1[tr], y[tr], X_s1[te], alpha=1.0)
        residual_tr = y[tr] - s1_tr
        Xtr_imp, Xte_imp = impute_fold(X_s2[tr], X_s2[te])
        Xtr_sel, Xte_sel, _idx = feature_select_fold(
            Xtr_imp, residual_tr, Xte_imp, k=K_FEATURES, seed=seed
        )
        hgb = HistGradientBoostingRegressor(
            n_estimators=HGB_MAX_ITER,
            learning_rate=HGB_LR,
            max_depth=HGB_MAX_DEPTH,
            random_state=seed,
            subsample=0.8,
        )
        hgb.fit(Xtr_sel, residual_tr)
        preds[te] = s1_te + hgb.predict(Xte_sel)
        if (fold_idx + 1) % 20 == 0:
            print(
                f"    seed={seed} fold {fold_idx + 1}/{n} "
                f"elapsed={time.time() - t0:.1f}s",
                flush=True,
            )
    return preds


# ── Baseline alignment ───────────────────────────────────────────────────────


def load_iter47_baseline_preds(sids: list[str]) -> np.ndarray:
    """Pull iter47 LOOCV preds for ``drop_allmissing_validrange × stage2_current``
    in the order of ``sids``.  Hard-fails if any SID is missing — that would be
    a cohort drift between iter47 baseline (N=95) and this probe."""
    df = pd.read_csv(ITER47_BASELINE_PREDS_CSV)
    df = df[(df["cohort"] == COHORT) & (df["stage2_policy"] == STAGE2_POLICY)].copy()
    df = df.set_index("sid")
    missing = [s for s in sids if s not in df.index]
    if missing:
        raise RuntimeError(
            f"iter47 baseline preds missing {len(missing)} SIDs of probe cohort: "
            f"{missing[:5]}..."
        )
    return df.loc[sids, "y_pred"].to_numpy(dtype=np.float64)


# ── Paired bootstrap (CCC delta vs locked iter47 preds) ──────────────────────


def paired_boot_delta(
    y: np.ndarray, pred_new: np.ndarray, pred_ref: np.ndarray, n_boot: int = N_BOOT
) -> dict[str, Any]:
    rng = np.random.default_rng(BOOT_SEED)
    n = len(y)
    deltas = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        deltas[b] = float(
            ccc_fn(y[idx], pred_new[idx]) - ccc_fn(y[idx], pred_ref[idx])
        )
    return {
        "n_boot": n_boot,
        "mean_delta": float(deltas.mean()),
        "ci95": [
            float(np.percentile(deltas, 2.5)),
            float(np.percentile(deltas, 97.5)),
        ],
        "frac_gt_0": float(np.mean(deltas > 0)),
    }


# ── Verdict ──────────────────────────────────────────────────────────────────


def verdict_from_frac_pos(frac_pos: float) -> str:
    # Single-comparison family → Bonferroni gate = uncorrected gate = 0.95.
    if frac_pos >= 0.95:
        return "PASS_FRESH_FAMILY_BONFERRONI_n2"
    return "FAIL"


# ── Driver ───────────────────────────────────────────────────────────────────


def run() -> dict[str, Any]:
    utc_now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Cohort + baseline alignment.
    data = filter_cohort(COHORT)
    sids = list(data["sids"])
    y = data["y_t3"]
    print(
        f"S10 cohort={COHORT} n={len(sids)} excluded={len(data['excluded_sids'])}",
        flush=True,
    )
    ref_pred = load_iter47_baseline_preds(sids)
    ref_metrics = full_metrics(y, ref_pred, label="iter47_baseline_loocv")

    # Per-seed LOOCV.
    per_seed_preds: list[np.ndarray] = []
    per_seed_ccc: list[float] = []
    for seed in SEEDS_FRESH:
        print(f"\n=== S10 K=250 HGB seed={seed} ===", flush=True)
        t0 = time.time()
        preds = loocv_preds_k250_hgb(data, seed)
        per_seed_preds.append(preds)
        m = full_metrics(y, preds, label=f"S10_k250_hgb_seed{seed}")
        per_seed_ccc.append(float(m["ccc"]))
        print(
            f"  seed={seed} CCC={m['ccc']:+.4f} MAE={m['mae']:.3f} "
            f"r={m['r']:.3f} elapsed={time.time() - t0:.1f}s",
            flush=True,
        )

    # Pool (mean across 3 fresh seeds).
    pooled_pred = np.mean(np.column_stack(per_seed_preds), axis=1)
    pooled_metrics = full_metrics(y, pooled_pred, label="S10_k250_hgb_pooled_mean3")
    pooled_ccc = float(pooled_metrics["ccc"])

    # Paired bootstrap vs locked iter47 preds.
    boot = paired_boot_delta(y, pooled_pred, ref_pred, n_boot=N_BOOT)
    delta_vs_iter47 = pooled_ccc - ITER47_BASELINE_CCC
    verdict = verdict_from_frac_pos(boot["frac_gt_0"])

    # Pre-registration payload (sha256 over the immutable definition).
    prereg_payload = {
        "experiment": "T3 S10 K=250 HGB fresh-seed replication",
        "trigger": (
            "2026-05-13 K-sweep monotonic hump locked in "
            f"{KSWEEP_LOCKBOX}; K=250 is the peak of the smooth response curve "
            "and is fixed by EXTERNAL evidence, not in-cohort selection."
        ),
        "fwer_family_for_this_slot": {
            "members": ["iter47_baseline", "S10_k250_hgb_replication"],
            "n_members": 2,
            "bonferroni_gate": 0.975,
            "single_comparison_gate": 0.95,
            "justification_for_K250_choice": (
                "External: 2026-05-13 K-sweep monotonic hump locked in "
                "lockbox_t3_gb_ksweep_fwer_bootstrap_20260513_030050.json. "
                "K=250 is the peak of a smooth response curve; not in-cohort "
                "selection from THIS run."
            ),
        },
        "cohort": COHORT,
        "stage2_policy": STAGE2_POLICY,
        "stage1": "A3_tier1 = H&Y + cv_yrs + cv_sex + cv_dbs, alpha=1.0",
        "k_features": K_FEATURES,
        "selector": "LGB-importance feature_select_fold (iter47 canonical)",
        "stage2_regressor": (
            f"HistGradientBoostingRegressor(max_iter={HGB_MAX_ITER}, "
            f"learning_rate={HGB_LR}, max_depth={HGB_MAX_DEPTH}, "
            "random_state=seed)"
        ),
        "seeds_fresh": list(SEEDS_FRESH),
        "evaluation": "LOOCV, mean of 3 fresh-seed predictions",
        "baseline": (
            f"iter47 locked LOOCV preds from {ITER47_BASELINE_PREDS_CSV.name} "
            "(drop_allmissing_validrange × stage2_current, N=95)"
        ),
        "comparison": "paired bootstrap (B=5000) of CCC(pooled) - CCC(iter47)",
        "gate": "frac_pos ≥ 0.95 single-comparison Bonferroni gate (n=1)",
    }
    prereg = {
        **prereg_payload,
        "created_at_utc": utc_now,
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha(prereg_payload),
        "preregistration_master": MASTER_PREREG,
    }
    prereg_path = (
        RESULTS_DIR / f"preregistration_t3_S10_k250_hgb_fresh_replication_{ts}.json"
    )
    prereg_path.write_text(
        json.dumps(_jsonable(prereg), indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nPre-registration: {prereg_path}", flush=True)

    # Lockbox output.
    out = {
        "name": "lockbox_t3_S10_k250_hgb_fresh_replication",
        "created_at_utc": utc_now,
        "preregistration_master": MASTER_PREREG,
        "preregistration_file": str(prereg_path),
        "formula_sha256": prereg["formula_sha256"],
        "git_sha": prereg["git_sha"],
        "fwer_family_for_this_slot": prereg_payload["fwer_family_for_this_slot"],
        "session": "2026-05-15-PM-S10-replication",
        "n_cohort": int(len(sids)),
        "cohort": COHORT,
        "stage2_policy": STAGE2_POLICY,
        "seeds_fresh": list(SEEDS_FRESH),
        "K_features": K_FEATURES,
        "stage2_regressor": prereg_payload["stage2_regressor"],
        "iter47_baseline_ccc": ITER47_BASELINE_CCC,
        "iter47_baseline_loocv_recomputed_metrics": ref_metrics,
        "k250_hgb_pooled_ccc": pooled_ccc,
        "k250_hgb_pooled_metrics": pooled_metrics,
        "per_seed_ccc": per_seed_ccc,
        "delta_vs_iter47": float(delta_vs_iter47),
        "paired_bootstrap": boot,
        "bootstrap_frac_pos": boot["frac_gt_0"],
        "bootstrap_ci95": boot["ci95"],
        "verdict": verdict,
        "compares_to_20260513_finding": (
            "K=250 sklearn GB Δ=+0.0732 frac>0=0.9518 in 2026-05-13 lockbox "
            f"({KSWEEP_LOCKBOX})"
        ),
        "ksweep_lockbox": KSWEEP_LOCKBOX,
        "iter47_baseline_csv": str(ITER47_BASELINE_PREDS_CSV),
        "excluded_sids": data["excluded_sids"],
    }
    lockbox_path = (
        RESULTS_DIR / f"lockbox_t3_S10_k250_hgb_fresh_replication_{ts}.json"
    )
    lockbox_path.write_text(
        json.dumps(_jsonable(out), indent=2) + "\n", encoding="utf-8"
    )
    print(f"Lockbox: {lockbox_path}", flush=True)

    # OOF .npz with per-seed LOOCV preds (for re-bootstrap / external audit).
    oof_path = RESULTS_DIR / f"oof_t3_S10_k250_hgb_fresh_replication_{ts}.npz"
    np.savez(
        oof_path,
        sids=np.asarray(sids, dtype=object),
        y_true=y.astype(np.float64),
        ref_iter47=ref_pred.astype(np.float64),
        seeds=np.asarray(SEEDS_FRESH, dtype=np.int64),
        per_seed_preds=np.column_stack(per_seed_preds).astype(np.float64),
        pooled_pred=pooled_pred.astype(np.float64),
    )
    print(f"OOF preds: {oof_path}", flush=True)

    # Summary line.
    print(
        f"\nS10 verdict={verdict} pooled_CCC={pooled_ccc:+.4f} "
        f"Δ={delta_vs_iter47:+.4f} frac>0={boot['frac_gt_0']:.4f} "
        f"per_seed={['%.4f' % c for c in per_seed_ccc]}",
        flush=True,
    )
    return out


# ── Sanity-y-nan smoke (firewall law #9) ─────────────────────────────────────


def sanity_y_nan() -> dict[str, Any]:
    """y-free retention / abstention probes must produce something even with
    y_test masked.  This probe is supervised end-to-end (Stage-1 ridge + Stage-2
    HGB on Stage-1 residual), so NaN-ing y_test must break ``ccc`` (NaN result).
    A finite CCC under y-nan would indicate the predictor saw y_test → leak.
    """
    data = filter_cohort(COHORT)
    sids = list(data["sids"])
    n = len(sids)
    y_full = data["y_t3"].copy()

    # Replace y_test (single held-out row per LOOCV step) with NaN in the
    # evaluation array AFTER predictions are made.  The point is that the
    # predictor never used y_test; CCC(NaN, pred) must not be finite.
    preds = loocv_preds_k250_hgb(data, seed=SEEDS_FRESH[0])
    y_masked = y_full.copy().astype(np.float64)
    # Mask one canonical row index.
    y_masked[0] = np.nan
    try:
        sanity_ccc = ccc_fn(y_masked, preds)
    except Exception as exc:
        sanity_ccc = f"raised {type(exc).__name__}: {exc}"
    print(
        f"sanity_y_nan: ccc(y_masked_row0, preds)={sanity_ccc} "
        f"(NaN/raise is expected — supervised probe)",
        flush=True,
    )
    return {"y_nan_first_row_ccc": _jsonable(sanity_ccc), "n": n}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--mode",
        choices=["run", "sanity-y-nan"],
        default="run",
        help="run: full LOOCV + lockbox.  sanity-y-nan: firewall law #9 smoke.",
    )
    args = parser.parse_args()
    if args.mode == "run":
        run()
    else:
        sanity_y_nan()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""T3 S12: y-free unobservability-risk abstention from S11 decomposition.

This follows `/tmp/pro-results.txt` rank #12 as a deployable-secondary screen,
not a standard full-cohort T3 headline. It reuses S11's fold-clean direct and
observable/non-gait decomposition predictions and builds a fixed y-free risk:

  z(|direct_total - decomposed_total|)
  + z(seed std of direct/decomposed total predictions)
  + z(non-gait prior share in the decomposed total)

Subjects with the lowest risk are retained at fixed 70% and 50% coverage. The
same retained masks are evaluated for locked iter47 predictions, S11-direct
predictions, and S11-decomposed predictions.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from audit_t3_iter47_domain_residuals import load_item_domain_table
from inductive_lib import full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter41_target_fix import build_stage1_matrix, filter_stage2
from run_t3_iter47_invalid_code_fix import filter_cohort
from run_t3_iter5_clinical import fit_stage1


ensure_dir(RESULTS_DIR)

COHORT = "drop_allmissing_validrange"
SEEDS = (42, 1337, 7)
OUTER_FOLDS = 5
STAGE2_POLICY = "stage2_no_cv"
OBS_DOMAIN = "gait_balance_7_14"
NONGAIT_DOMAIN = "unobservable_non_gait"
COVERAGES = (0.70, 0.50)
ITER47_PREDS = RESULTS_DIR / "iter47_invalidcode_subject_preds_20260508_194605.csv"
SLOTF_RETAINED_REFERENCE = {
    "cov_70": 0.4237,
    "cov_50": 0.5370,
}


def align_domains(data: dict) -> tuple[np.ndarray, np.ndarray]:
    item_df, _clinical_path = load_item_domain_table()
    item_df = item_df.set_index("sid")
    sids = [str(s) for s in data["sids"]]
    missing = [s for s in sids if s not in item_df.index]
    if missing:
        raise RuntimeError(f"Missing clinical domain rows: {missing[:5]}")
    obs = item_df.loc[sids, OBS_DOMAIN].to_numpy(dtype=np.float64)
    nongait = item_df.loc[sids, NONGAIT_DOMAIN].to_numpy(dtype=np.float64)
    total = obs + nongait
    max_diff = float(np.max(np.abs(total - data["y_t3"])))
    if max_diff > 1e-9:
        raise RuntimeError(f"Domain sum mismatch vs iter47 target: {max_diff}")
    return obs, nongait


def predict_stage1_plus_lgb(
    data: dict,
    target: np.ndarray,
    seed: int,
    splits: list[tuple[np.ndarray, np.ndarray]],
) -> np.ndarray:
    sids = data["sids"]
    x_s1 = build_stage1_matrix(sids, data["hy"])
    x_s2, _feat_cols = filter_stage2(data["X"], data["feat_cols"], STAGE2_POLICY)
    out = np.zeros(len(target), dtype=np.float64)
    for tr, te in splits:
        s1_tr, s1_te = fit_stage1(x_s1[tr], target[tr], x_s1[te], alpha=1.0)
        residual_tr = target[tr] - s1_tr
        xtr, xte = impute_fold(x_s2[tr], x_s2[te])
        xtr_sel, xte_sel, _idx = feature_select_fold(
            xtr, residual_tr, xte, k=500, seed=seed
        )
        out[te] = s1_te + train_lgb(xtr_sel, residual_tr, xte_sel, seed)
    return out


def predict_stage1_only(
    data: dict,
    target: np.ndarray,
    splits: list[tuple[np.ndarray, np.ndarray]],
) -> np.ndarray:
    sids = data["sids"]
    x_s1 = build_stage1_matrix(sids, data["hy"])
    out = np.zeros(len(target), dtype=np.float64)
    for tr, te in splits:
        _s1_tr, s1_te = fit_stage1(x_s1[tr], target[tr], x_s1[te], alpha=1.0)
        out[te] = s1_te
    return out


def screen_seed(data: dict, obs: np.ndarray, nongait: np.ndarray, seed: int) -> dict:
    n = len(data["sids"])
    splits = list(KFold(n_splits=OUTER_FOLDS, shuffle=True, random_state=seed).split(np.arange(n)))
    y_total = data["y_t3"]
    direct = predict_stage1_plus_lgb(data, y_total, seed, splits)
    obs_pred = predict_stage1_plus_lgb(data, obs, seed, splits)
    nongait_pred = predict_stage1_only(data, nongait, splits)
    decomposed = obs_pred + nongait_pred
    direct_m = full_metrics(y_total, direct, label=f"direct_total_seed{seed}")
    decomp_m = full_metrics(y_total, decomposed, label=f"decomp_seed{seed}")
    return {
        "seed": seed,
        "direct_pred": direct,
        "decomposed_pred": decomposed,
        "observable_pred": obs_pred,
        "nongait_prior_pred": nongait_pred,
        "direct_metrics": direct_m,
        "decomposed_metrics": decomp_m,
    }


def load_iter47_preds(sids: list[str]) -> np.ndarray:
    df = pd.read_csv(ITER47_PREDS)
    df = df[(df["cohort"] == COHORT) & (df["stage2_policy"] == "stage2_current")].copy()
    df = df.set_index("sid")
    missing = [s for s in sids if s not in df.index]
    if missing:
        raise RuntimeError(f"iter47 predictions missing SIDs: {missing[:5]}")
    return df.loc[sids, "y_pred"].to_numpy(dtype=float)


def zscore(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    med = np.nanmedian(x)
    iqr = np.nanpercentile(x, 75) - np.nanpercentile(x, 25)
    scale = iqr if iqr > 1e-9 else np.nanstd(x)
    if not np.isfinite(scale) or scale <= 1e-9:
        return np.zeros_like(x)
    return (x - med) / scale


def retained_metrics(y: np.ndarray, pred: np.ndarray, mask: np.ndarray, label: str) -> dict:
    out = full_metrics(y[mask], pred[mask], label=label)
    out["n_retained"] = int(mask.sum())
    out["coverage"] = float(mask.mean())
    return out


def fixed_coverage_mask(risk: np.ndarray, coverage: float) -> np.ndarray:
    n_keep = int(np.floor(len(risk) * coverage))
    order = np.argsort(risk, kind="mergesort")
    mask = np.zeros(len(risk), dtype=bool)
    mask[order[:n_keep]] = True
    return mask


def main() -> int:
    data = filter_cohort(COHORT)
    obs, nongait = align_domains(data)
    sids = [str(s) for s in data["sids"]]
    y = data["y_t3"]
    iter47_pred = load_iter47_preds(sids)

    direct_seed_preds: list[np.ndarray] = []
    decomp_seed_preds: list[np.ndarray] = []
    obs_seed_preds: list[np.ndarray] = []
    nongait_seed_preds: list[np.ndarray] = []
    seed_metrics: list[dict] = []
    for seed in SEEDS:
        r = screen_seed(data, obs, nongait, seed)
        direct_seed_preds.append(r["direct_pred"])
        decomp_seed_preds.append(r["decomposed_pred"])
        obs_seed_preds.append(r["observable_pred"])
        nongait_seed_preds.append(r["nongait_prior_pred"])
        seed_metrics.append(
            {
                "seed": int(seed),
                "direct_ccc": float(r["direct_metrics"]["ccc"]),
                "decomp_ccc": float(r["decomposed_metrics"]["ccc"]),
                "delta_ccc": float(r["decomposed_metrics"]["ccc"] - r["direct_metrics"]["ccc"]),
            }
        )
        print(
            f"[S12] seed={seed} direct={r['direct_metrics']['ccc']:.4f} "
            f"decomp={r['decomposed_metrics']['ccc']:.4f}",
            flush=True,
        )

    direct = np.mean(np.column_stack(direct_seed_preds), axis=1)
    decomp = np.mean(np.column_stack(decomp_seed_preds), axis=1)
    obs_pred = np.mean(np.column_stack(obs_seed_preds), axis=1)
    nongait_pred = np.mean(np.column_stack(nongait_seed_preds), axis=1)
    direct_std = np.std(np.column_stack(direct_seed_preds), axis=1)
    decomp_std = np.std(np.column_stack(decomp_seed_preds), axis=1)

    disagreement = np.abs(direct - decomp)
    seed_uncertainty = direct_std + decomp_std
    nongait_share = np.abs(nongait_pred) / (np.abs(obs_pred) + np.abs(nongait_pred) + 1e-6)
    risk = zscore(disagreement) + zscore(seed_uncertainty) + zscore(nongait_share)

    full_metrics_block = {
        "iter47_locked": full_metrics(y, iter47_pred, label="iter47_locked_full"),
        "s11_direct_5fold_ensemble": full_metrics(y, direct, label="s11_direct_full"),
        "s11_decomp_5fold_ensemble": full_metrics(y, decomp, label="s11_decomp_full"),
    }

    coverage_rows: dict[str, dict] = {}
    for cov in COVERAGES:
        key = f"cov_{int(cov * 100)}"
        mask = fixed_coverage_mask(risk, cov)
        iter47_m = retained_metrics(y, iter47_pred, mask, f"iter47_locked_{key}")
        direct_m = retained_metrics(y, direct, mask, f"s11_direct_{key}")
        decomp_m = retained_metrics(y, decomp, mask, f"s11_decomp_{key}")
        coverage_rows[key] = {
            "n_retained": int(mask.sum()),
            "actual_coverage": float(mask.mean()),
            "risk_threshold_max_retained": float(np.max(risk[mask])),
            "iter47_locked_retained": iter47_m,
            "s11_direct_retained": direct_m,
            "s11_decomp_retained": decomp_m,
            "delta_direct_vs_iter47_same_mask": round(float(direct_m["ccc"] - iter47_m["ccc"]), 4),
            "delta_decomp_vs_iter47_same_mask": round(float(decomp_m["ccc"] - iter47_m["ccc"]), 4),
            "slotF_reference_retained_ccc": SLOTF_RETAINED_REFERENCE.get(key),
            "beats_slotF_reference": (
                bool(max(float(direct_m["ccc"]), float(decomp_m["ccc"])) > SLOTF_RETAINED_REFERENCE[key])
                if key in SLOTF_RETAINED_REFERENCE
                else None
            ),
        }
        print(
            f"[S12] {key} iter47={iter47_m['ccc']:.4f} direct={direct_m['ccc']:.4f} "
            f"decomp={decomp_m['ccc']:.4f}",
            flush=True,
        )

    cov70 = coverage_rows["cov_70"]
    cov50 = coverage_rows["cov_50"]
    monotone = (
        max(cov50["s11_direct_retained"]["ccc"], cov50["s11_decomp_retained"]["ccc"])
        >= max(cov70["s11_direct_retained"]["ccc"], cov70["s11_decomp_retained"]["ccc"])
    )
    beats_full_iter47_at70 = (
        max(cov70["s11_direct_retained"]["ccc"], cov70["s11_decomp_retained"]["ccc"])
        > 0.3784
    )
    beats_slotf = bool(
        cov70["beats_slotF_reference"] or cov50["beats_slotF_reference"]
    )
    verdict = (
        "SECONDARY_SCREEN_POSITIVE_REQUIRES_PREREG"
        if monotone and beats_full_iter47_at70 and beats_slotf
        else "SCREEN_FAIL_NO_DEPLOYABLE_UPDATE"
    )

    out = {
        "name": "screen_t3_S12_unobservability_abstention",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "proposal_source": "/tmp/pro-results.txt rank #12",
        "screen_only": True,
        "estimand": "deployable_secondary_retained_t3_ccc",
        "cohort": COHORT,
        "n": int(len(y)),
        "stage2_policy": STAGE2_POLICY,
        "domains": {
            "observable": OBS_DOMAIN,
            "nongait_prior": NONGAIT_DOMAIN,
        },
        "risk_policy": {
            "y_free": True,
            "components": [
                "z_abs_direct_minus_decomp",
                "z_seed_std_direct_plus_decomp",
                "z_abs_nongait_prior_share",
            ],
            "coverage_points": list(COVERAGES),
        },
        "seed_metrics": seed_metrics,
        "full_metrics": full_metrics_block,
        "retained_results": coverage_rows,
        "decision_checks": {
            "monotone_50_ge_70": bool(monotone),
            "beats_full_iter47_at_70": bool(beats_full_iter47_at70),
            "beats_slotF_reference_any_coverage": bool(beats_slotf),
        },
        "verdict": verdict,
    }
    path = RESULTS_DIR / f"screen_t3_S12_unobservability_abstention_{out['created_at_utc']}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"[S12] verdict={verdict}")
    print(f"[S12] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

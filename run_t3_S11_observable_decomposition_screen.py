#!/usr/bin/env python3
"""T3 S11 observable/non-gait target-decomposition screen.

This follows `/tmp/pro-results.txt` rank #11 as a target-representation
experiment, not a WearGait-only hyperparameter sweep. The question is whether
the corrected T3 target should be represented as:

    T3 = observable_gait_balance_7_14 + unobservable_non_gait

with the observable component receiving the usual IMU residual model, while the
non-gait component receives only a deployable clinical/intake prior. Domain
labels are used as training targets only; no true item/domain label is used at
prediction time.

Screen policy:
  - 5-fold only across seeds [42, 1337, 7].
  - Same folds compare direct total-T3 vs decomposed target representation.
  - No LOOCV/LOSO promotion unless delta >= +0.025 and bootstrap frac>0 >= 0.95.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from audit_t3_iter47_domain_residuals import DOMAINS, load_item_domain_table
from inductive_lib import full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter41_target_fix import build_stage1_matrix, filter_stage2
from run_t3_iter47_invalid_code_fix import filter_cohort
from run_t3_iter5_clinical import fit_stage1


ensure_dir(RESULTS_DIR)

SEEDS = (42, 1337, 7)
OUTER_FOLDS = 5
N_BOOT = 2000
BOOT_SEED = 20260515
STAGE2_POLICY = "stage2_no_cv"
OBS_DOMAIN = "gait_balance_7_14"
NONGAIT_DOMAIN = "unobservable_non_gait"
PROMOTION_DELTA = 0.025
PROMOTION_FRAC = 0.95


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
    x_s2, feat_cols = filter_stage2(data["X"], data["feat_cols"], STAGE2_POLICY)
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
        "delta_ccc": round(float(decomp_m["ccc"] - direct_m["ccc"]), 4),
        "delta_mae": round(float(decomp_m["mae"] - direct_m["mae"]), 4),
    }


def paired_bootstrap(y: np.ndarray, direct: np.ndarray, decomp: np.ndarray) -> dict:
    from eval_utils import lins_ccc

    rng = np.random.default_rng(BOOT_SEED)
    n = len(y)
    deltas = np.zeros(N_BOOT, dtype=np.float64)
    for i in range(N_BOOT):
        idx = rng.choice(n, n, replace=True)
        deltas[i] = float(lins_ccc(y[idx], decomp[idx]) - lins_ccc(y[idx], direct[idx]))
    return {
        "n_boot": N_BOOT,
        "median_delta": round(float(np.median(deltas)), 4),
        "ci95": [round(float(np.percentile(deltas, 2.5)), 4), round(float(np.percentile(deltas, 97.5)), 4)],
        "frac_positive": round(float((deltas > 0).mean()), 4),
    }


def apply_null(data: dict, obs: np.ndarray, nongait: np.ndarray, mode: str) -> tuple[dict, np.ndarray, np.ndarray]:
    if mode in ("", "real"):
        return data, obs, nongait
    out = dict(data)
    if mode == "scrambled_targets":
        perm = np.random.default_rng(20260515).permutation(len(obs))
        out["y_t3"] = data["y_t3"][perm]
        return out, obs[perm], nongait[perm]
    if mode == "sid_shuffle_features":
        perm = np.random.default_rng(31415927).permutation(len(obs))
        out["sids"] = data["sids"][perm]
        out["X"] = data["X"][perm]
        out["hy"] = data["hy"][perm]
        return out, obs, nongait
    raise ValueError(f"unknown null mode {mode}")


def screen_core(data: dict, obs: np.ndarray, nongait: np.ndarray) -> dict:
    seed_results = []
    direct_preds = []
    decomp_preds = []
    for seed in SEEDS:
        r = screen_seed(data, obs, nongait, seed)
        direct_preds.append(r.pop("direct_pred"))
        decomp_preds.append(r.pop("decomposed_pred"))
        r.pop("observable_pred")
        r.pop("nongait_prior_pred")
        seed_results.append(r)
        print(
            f"[S11] seed={seed} direct={r['direct_metrics']['ccc']:.4f} "
            f"decomp={r['decomposed_metrics']['ccc']:.4f} delta={r['delta_ccc']:+.4f}",
            flush=True,
        )
    direct_ens = np.mean(np.column_stack(direct_preds), axis=1)
    decomp_ens = np.mean(np.column_stack(decomp_preds), axis=1)
    y = data["y_t3"]
    direct_m = full_metrics(y, direct_ens, label="direct_total_ensemble")
    decomp_m = full_metrics(y, decomp_ens, label="observable_decomp_ensemble")
    deltas = np.array([r["delta_ccc"] for r in seed_results], dtype=float)
    return {
        "seed_results": seed_results,
        "seed_mean_delta_ccc": round(float(np.mean(deltas)), 4),
        "seed_delta_std": round(float(np.std(deltas, ddof=1)), 4),
        "ensemble": {
            "direct_metrics": direct_m,
            "decomposed_metrics": decomp_m,
            "delta_ccc": round(float(decomp_m["ccc"] - direct_m["ccc"]), 4),
            "delta_mae": round(float(decomp_m["mae"] - direct_m["mae"]), 4),
            "bootstrap": paired_bootstrap(y, direct_ens, decomp_ens),
        },
    }


def main() -> None:
    data = filter_cohort("drop_allmissing_validrange")
    obs, nongait = align_domains(data)
    print(
        f"[S11] N={len(data['sids'])}, domains={OBS_DOMAIN}+{NONGAIT_DOMAIN}, "
        f"stage2_policy={STAGE2_POLICY}",
        flush=True,
    )
    real = screen_core(data, obs, nongait)
    gate = {
        "delta_ccc_min": PROMOTION_DELTA,
        "bootstrap_frac_positive_min": PROMOTION_FRAC,
        "seed_delta_std_max": 0.020,
        "gate_pass": bool(
            real["ensemble"]["delta_ccc"] >= PROMOTION_DELTA
            and real["ensemble"]["bootstrap"]["frac_positive"] >= PROMOTION_FRAC
            and real["seed_delta_std"] < 0.020
        ),
    }
    nulls = {}
    for mode in ("scrambled_targets", "sid_shuffle_features"):
        print(f"[S11 NULL] {mode}", flush=True)
        d_null, obs_null, nongait_null = apply_null(data, obs, nongait, mode)
        nulls[mode] = screen_core(d_null, obs_null, nongait_null)

    verdict = (
        "SCREEN_PASS_PROMOTE_TO_PREREG_LOOCV_LOSO"
        if gate["gate_pass"]
        else "SCREEN_FAIL_NO_LOOCV_NO_LOSO"
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "name": "screen_t3_S11_observable_decomposition",
        "created_at_utc": ts,
        "proposal_source": "/tmp/pro-results.txt rank #11",
        "screen_only": True,
        "cohort": "drop_allmissing_validrange",
        "n": int(len(data["sids"])),
        "stage2_policy": STAGE2_POLICY,
        "domains": {
            "observable": {"name": OBS_DOMAIN, "items": DOMAINS[OBS_DOMAIN]},
            "nongait_prior": {"name": NONGAIT_DOMAIN, "items": DOMAINS[NONGAIT_DOMAIN]},
        },
        "prediction_policy": {
            "direct_total": "A3 clinical/intake Stage1 + no-cv V2 LGB residual",
            "observable_component": "A3 clinical/intake Stage1 + no-cv V2 LGB residual",
            "nongait_component": "A3 clinical/intake Stage1 only; no IMU residual",
            "test_time_true_domain_labels_used": False,
        },
        "real_screen": real,
        "promotion_gate": gate,
        "null_results": nulls,
        "verdict": verdict,
    }
    out_path = RESULTS_DIR / f"screen_t3_S11_observable_decomposition_{ts}.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(
        f"[S11] verdict={verdict}, ensemble_delta={real['ensemble']['delta_ccc']:+.4f}, "
        f"frac>0={real['ensemble']['bootstrap']['frac_positive']:.4f}",
        flush=True,
    )
    print(f"[S11] Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()

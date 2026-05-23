#!/usr/bin/env python3
"""Ablation #5 — T3 LOSO propensity-IPW (transductive site adaptation).

**LEAKAGE CLASS**: This is **unsupervised transductive site adaptation with
target-X access** — the propensity classifier is fit on JOINT NLS+WPD feature
distributions (NO LABELS). This is NOT canonical strict-inductive LOSO; it is
a covariate-shift adaptation method. Per codex 2026-05-16 advisory, this is
acceptable IF clearly labeled and the source-only zero-shot baseline is also
reported as a comparator.

**ORTHOGONALITY** to existing walls:
  - F-iter16 (count-IPW): w_i = N_train / (2 * N_site_i_train). Uniform within
    site. We use PROPENSITY logits per subject — strictly different.
  - F-iter17 (per-site feature centering): subtracts site mean from features.
    We do NOT modify features; we reweight samples. Different DA layer.

**Pre-registered comparison** (T3 LOSO two-way mean CCC):
  - ARM_A (canonical zero-shot LOSO): iter47 architecture (Stage-1 Ridge on
    H&Y+cv_yrs+cv_sex+cv_dbs, Stage-2 LGB on V2 K=500 residual) without IPW.
  - ARM_B (propensity-IPW): same architecture, Stage-2 LGB sample_weight =
    clip(P(target_site|x_pca) / P(source_site|x_pca), 0.1, 10).

**Pre-registered gate** (solo ablation, n=1 FWER pos): mean ΔCCC (B - A) ≥ +0.05
across BOTH directions (NLS→WPD AND WPD→NLS), paired-bootstrap frac>0 ≥ 0.95.

**5-null gate**: scrambled-label null on source site, propensity-IPW arm; expect
test-site CCC near zero.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from eval_utils import lins_ccc as ccc
from inductive_lib import full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter47_invalid_code_fix import filter_cohort
from run_t3_iter41_target_fix import (
    build_stage1_matrix,
    filter_stage2,
)
from run_t3_iter5_clinical import fit_stage1
from run_t3_iter2 import impute_fold, feature_select_fold, train_lgb

ensure_dir(RESULTS_DIR)

SEEDS = [42, 1337, 7]
STAGE2_POLICY = "stage2_current"  # iter47 canonical
PCA_DIMS = 30
WEIGHT_CLIP = (0.1, 10.0)


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _formula_sha(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def site_of(sid: str) -> str:
    sid = str(sid)
    if sid.startswith("NLS"):
        return "NLS"
    if sid.startswith("WPD"):
        return "WPD"
    return "OTHER"


def fit_propensity_weights(
    X_all: np.ndarray,
    sites: np.ndarray,
    target_site: str,
    source_site: str,
    tr_mask: np.ndarray,
    seed: int,
) -> tuple[np.ndarray, dict]:
    """Fit logistic propensity P(target | features) on joint feature distribution
    (no labels), return clip-weighted sample weights for the source training rows.

    Crucially: uses ONLY feature distribution (X), never UPDRS target y.

    Imputation is fit on SOURCE-SITE rows only (no target-distribution leak via
    median). Scaler/PCA are fit on joint features by design — this is the
    `target-X access` transductive label declared in pre-registration.
    """
    # Source-only median (no cross-site distribution leak via imputation)
    X_src = X_all[tr_mask]
    src_median = np.nanmedian(X_src, axis=0)
    src_median = np.where(np.isnan(src_median), 0.0, src_median)
    X_clean = np.where(np.isnan(X_all), src_median[None, :], X_all)

    # Scaler + PCA: fit on joint features (target-X access per pre-reg)
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X_clean)

    pca_seed = int(seed) * 11 + 1
    clf_seed = int(seed) * 13 + 2
    pca = PCA(n_components=min(PCA_DIMS, Xs.shape[1], Xs.shape[0] - 1), random_state=pca_seed)
    Z = pca.fit_transform(Xs)

    y_site = (sites == target_site).astype(np.int32)
    # Use both sites' features (target-X access). Source-site samples are class 0
    # (NLS), target-site samples are class 1 (WPD) — or vice-versa.
    clf = LogisticRegression(C=1.0, max_iter=2000, random_state=clf_seed)
    clf.fit(Z, y_site)
    p_target = clf.predict_proba(Z)[:, 1]
    p_target = np.clip(p_target, 1e-4, 1 - 1e-4)
    # Weights for source-site rows: P(target | x) / P(source | x)
    weights = p_target / (1.0 - p_target)
    weights = np.clip(weights, WEIGHT_CLIP[0], WEIGHT_CLIP[1])
    # Only training (source-site) rows get reweighted
    src_weights = weights[tr_mask]
    src_weights = src_weights / src_weights.mean()  # mean-normalize to keep effective N

    diag = {
        "propensity_pca_dims": int(Z.shape[1]),
        "weight_mean": float(weights.mean()),
        "weight_std": float(weights.std()),
        "weight_min": float(weights.min()),
        "weight_max": float(weights.max()),
        "frac_clipped_lo": float((weights == WEIGHT_CLIP[0]).mean()),
        "frac_clipped_hi": float((weights == WEIGHT_CLIP[1]).mean()),
        "source_n": int(tr_mask.sum()),
        "target_n": int((~tr_mask).sum()),
        "classifier_train_acc": float(clf.score(Z, y_site)),
    }
    return src_weights, diag


def loso_one_direction(
    data: dict,
    seed: int,
    train_site: str,
    test_site: str,
    use_propensity_ipw: bool,
    scrambled_y: bool = False,
) -> dict:
    sids = data["sids"]
    sites = np.array([site_of(s) for s in sids])
    tr_mask = sites == train_site
    te_mask = sites == test_site

    y = data["y_t3"].copy()
    if scrambled_y:
        rng = np.random.RandomState(seed * 7919)
        # Shuffle only source-site labels (preserves test-site labels for honest evaluation)
        src_idx = np.where(tr_mask)[0]
        shuffled = src_idx.copy()
        rng.shuffle(shuffled)
        y_src = y[src_idx].copy()
        y[src_idx] = y_src[np.argsort(np.argsort(shuffled))]  # permuted source labels

    X_s1 = build_stage1_matrix(sids, data["hy"])
    X_s2, feat_cols_s2 = filter_stage2(data["X"], data["feat_cols"], STAGE2_POLICY)

    tr = np.where(tr_mask)[0]
    te = np.where(te_mask)[0]

    # Stage 1: Ridge on H&Y + cv_yrs + cv_sex + cv_dbs (iter5 canonical)
    s1_tr, s1_te = fit_stage1(X_s1[tr], y[tr], X_s1[te], alpha=1.0)
    residual_tr = y[tr] - s1_tr

    Xtr, Xte = impute_fold(X_s2[tr], X_s2[te])
    Xtr_sel, Xte_sel, idx = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)

    # Propensity-IPW sample weights (only if treatment arm)
    sample_weight = None
    propensity_diag = {}
    if use_propensity_ipw:
        sample_weight, propensity_diag = fit_propensity_weights(
            X_s2, sites, target_site=test_site, source_site=train_site,
            tr_mask=tr_mask, seed=seed,
        )

    # Train LGB on residual with optional sample weights
    if sample_weight is not None:
        # train_lgb signature: (X_tr, y_tr, X_te, seed) — add sample_weight via lgbm directly
        import lightgbm as lgb
        params = {
            "n_estimators": 500,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "min_data_in_leaf": 5,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 1,
            "random_state": seed,
            "verbosity": -1,
            "n_jobs": 4,
        }
        model = lgb.LGBMRegressor(**params)
        model.fit(Xtr_sel, residual_tr, sample_weight=sample_weight)
        stage2_pred = model.predict(Xte_sel)
    else:
        stage2_pred = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)

    pred = s1_te + stage2_pred
    metrics = full_metrics(data["y_t3"][te], pred, label=f"{train_site}_to_{test_site}_seed{seed}")

    return {
        "train_site": train_site,
        "test_site": test_site,
        "seed": int(seed),
        "use_propensity_ipw": use_propensity_ipw,
        "scrambled_y": scrambled_y,
        "n_train": int(tr_mask.sum()),
        "n_test": int(te_mask.sum()),
        "metrics": metrics,
        "ccc": float(metrics["ccc"]),
        "mae": float(metrics["mae"]),
        "propensity_diag": propensity_diag,
        "preds": pred.tolist(),
        "y_true": data["y_t3"][te].tolist(),
    }


def paired_bootstrap_loso(
    preds_a: dict, preds_b: dict, n_boot: int = 5000, seed: int = 42
) -> dict:
    """Paired bootstrap on Δ across both LOSO directions combined.

    preds_a/preds_b: dict with keys 'NLS_to_WPD' and 'WPD_to_NLS', each holding
    (y_true, preds) tuple from mean-of-seeds.
    """
    rng = np.random.RandomState(seed)
    y_all_a, p_all_a, y_all_b, p_all_b = [], [], [], []
    for direction in ("NLS_to_WPD", "WPD_to_NLS"):
        y_all_a.extend(preds_a[direction][0])
        p_all_a.extend(preds_a[direction][1])
        y_all_b.extend(preds_b[direction][0])
        p_all_b.extend(preds_b[direction][1])
    y_a = np.asarray(y_all_a)
    p_a = np.asarray(p_all_a)
    y_b = np.asarray(y_all_b)
    p_b = np.asarray(p_all_b)
    assert (y_a == y_b).all(), "ARMs must share y_true"

    n = len(y_a)
    deltas = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        deltas[b] = ccc(y_b[idx], p_b[idx]) - ccc(y_a[idx], p_a[idx])
    return {
        "n_boot": n_boot,
        "delta_mean": float(np.mean(deltas)),
        "delta_ci_low": float(np.percentile(deltas, 2.5)),
        "delta_ci_high": float(np.percentile(deltas, 97.5)),
        "frac_above_zero": float(np.mean(deltas > 0)),
        "frac_above_mcid_005": float(np.mean(deltas > 0.005)),
        "frac_above_050": float(np.mean(deltas > 0.05)),
    }


def run_arm(data: dict, use_propensity_ipw: bool, scrambled_y: bool = False) -> dict:
    """Run both LOSO directions × 3 seeds, return per-direction mean-of-seeds preds + summary."""
    arm_results = {"NLS_to_WPD": [], "WPD_to_NLS": []}
    for seed in SEEDS:
        for direction in ("NLS_to_WPD", "WPD_to_NLS"):
            tr_site, te_site = direction.split("_to_")
            r = loso_one_direction(data, seed, tr_site, te_site, use_propensity_ipw, scrambled_y=scrambled_y)
            arm_results[direction].append(r)

    # Mean predictions per direction
    summary = {}
    for direction, runs in arm_results.items():
        preds_stack = np.stack([np.asarray(r["preds"]) for r in runs])
        pred_mean = preds_stack.mean(axis=0)
        y_true = np.asarray(runs[0]["y_true"])
        seed_cccs = [r["ccc"] for r in runs]
        summary[direction] = {
            "y_true": y_true.tolist(),
            "pred_mean": pred_mean.tolist(),
            "ccc_mean_of_seed_preds": float(ccc(y_true, pred_mean)),
            "per_seed_ccc": seed_cccs,
            "seed_std_ccc": float(np.std(seed_cccs)),
            "per_seed_runs": runs,
        }
    summary["two_way_mean_ccc"] = (
        summary["NLS_to_WPD"]["ccc_mean_of_seed_preds"]
        + summary["WPD_to_NLS"]["ccc_mean_of_seed_preds"]
    ) / 2.0
    return summary


def main():
    ts_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"\n=== Ablation #5 T3 LOSO Propensity-IPW (transductive, {ts_utc}) ===")

    # Load N=95 valid-range cohort
    data = filter_cohort("drop_allmissing_validrange")
    n = len(data["sids"])
    sites = np.array([site_of(s) for s in data["sids"]])
    n_nls = int((sites == "NLS").sum())
    n_wpd = int((sites == "WPD").sum())
    print(f"  N={n} (NLS={n_nls}, WPD={n_wpd})")

    # Pre-registration
    prereg_payload = {
        "experiment": "Ablation #5 — T3 LOSO propensity-IPW (transductive site adaptation)",
        "leakage_class": "unsupervised transductive site adaptation with target-X access",
        "leakage_caveat": (
            "Propensity classifier is fit on JOINT NLS+WPD feature distribution (no labels). "
            "Per codex advisory 2026-05-16, this uses test-fold feature distribution and is "
            "NOT canonical strict-inductive LOSO. It is acceptable as covariate-shift "
            "adaptation; the inductive zero-shot baseline is also reported as ARM_A comparator."
        ),
        "arm_a_baseline": "iter47 canonical (Stage-1 H&Y+cv_yrs+cv_sex+cv_dbs, Stage-2 LGB K=500 V2 residual), zero-shot LOSO",
        "arm_b_treatment": "ARM_A + propensity-IPW sample weights on Stage-2 LGB (clip 0.1..10)",
        "propensity": f"LogisticRegression on PCA-{PCA_DIMS} of V2 features (joint distribution, no labels)",
        "directions": ["NLS_to_WPD", "WPD_to_NLS"],
        "seeds": SEEDS,
        "cohort": "drop_allmissing_validrange",
        "n_subjects": n,
        "promotion_gate": "mean two-way ΔCCC ≥ +0.05 AND paired-bootstrap frac>0 ≥ 0.95",
        "orthogonality_F_iter16": "F-iter16 used count-IPW w=N/(2*N_site). We use propensity logits per subject — different DA mechanism.",
        "orthogonality_F_iter17": "F-iter17 centered features per-site. We reweight samples without modifying features.",
    }
    prereg = {
        **prereg_payload,
        "created_at_utc": ts_utc,
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha(prereg_payload),
    }
    prereg_path = RESULTS_DIR / f"preregistration_ablation_t3_loso_propensity_ipw_{ts_utc}.json"
    prereg_path.write_text(json.dumps(prereg, indent=2) + "\n")
    print(f"  Pre-reg: {prereg_path}")

    # ARM_A baseline (zero-shot LOSO)
    print("\n  Running ARM_A (canonical zero-shot LOSO, 3 seeds × 2 directions)...")
    arm_a = run_arm(data, use_propensity_ipw=False)
    print(f"    NLS→WPD CCC: {arm_a['NLS_to_WPD']['ccc_mean_of_seed_preds']:.4f}")
    print(f"    WPD→NLS CCC: {arm_a['WPD_to_NLS']['ccc_mean_of_seed_preds']:.4f}")
    print(f"    Two-way mean: {arm_a['two_way_mean_ccc']:.4f}")

    # ARM_B treatment (propensity-IPW)
    print("\n  Running ARM_B (propensity-IPW LOSO, 3 seeds × 2 directions)...")
    arm_b = run_arm(data, use_propensity_ipw=True)
    print(f"    NLS→WPD CCC: {arm_b['NLS_to_WPD']['ccc_mean_of_seed_preds']:.4f}")
    print(f"    WPD→NLS CCC: {arm_b['WPD_to_NLS']['ccc_mean_of_seed_preds']:.4f}")
    print(f"    Two-way mean: {arm_b['two_way_mean_ccc']:.4f}")

    delta_two_way = arm_b["two_way_mean_ccc"] - arm_a["two_way_mean_ccc"]

    # Paired bootstrap across both directions combined
    preds_a_dict = {
        "NLS_to_WPD": (arm_a["NLS_to_WPD"]["y_true"], arm_a["NLS_to_WPD"]["pred_mean"]),
        "WPD_to_NLS": (arm_a["WPD_to_NLS"]["y_true"], arm_a["WPD_to_NLS"]["pred_mean"]),
    }
    preds_b_dict = {
        "NLS_to_WPD": (arm_b["NLS_to_WPD"]["y_true"], arm_b["NLS_to_WPD"]["pred_mean"]),
        "WPD_to_NLS": (arm_b["WPD_to_NLS"]["y_true"], arm_b["WPD_to_NLS"]["pred_mean"]),
    }
    bootstrap = paired_bootstrap_loso(preds_a_dict, preds_b_dict, n_boot=5000, seed=42)

    # 5-null gate: scrambled-label source-site training
    print("\n  Running 5-null gate (scrambled-source-labels, IPW arm, single seed)...")
    null_results = {}
    for direction in ("NLS_to_WPD", "WPD_to_NLS"):
        tr_site, te_site = direction.split("_to_")
        r_null = loso_one_direction(data, 42, tr_site, te_site, use_propensity_ipw=True, scrambled_y=True)
        null_results[direction] = {
            "ccc": r_null["ccc"],
            "mae": r_null["mae"],
        }

    out = {
        "experiment": "ablation_t3_loso_propensity_ipw",
        "created_at_utc": ts_utc,
        "git_sha": _git_sha(),
        "formula_sha256": prereg["formula_sha256"],
        "preregistration": str(prereg_path.name),
        "leakage_class": "transductive_site_adaptation_target_X_access",
        "arm_a_baseline": arm_a,
        "arm_b_treatment": arm_b,
        "delta_two_way_ccc": delta_two_way,
        "paired_bootstrap": bootstrap,
        "promotion_gate": {
            "rule": "mean two-way ΔCCC ≥ +0.05 AND frac>0 ≥ 0.95",
            "delta_two_way": delta_two_way,
            "frac_above_zero": bootstrap["frac_above_zero"],
            "passes_delta_gate": delta_two_way >= 0.05,
            "passes_frac_gate": bootstrap["frac_above_zero"] >= 0.95,
            "PASSES_PROMOTION_GATE": (delta_two_way >= 0.05 and bootstrap["frac_above_zero"] >= 0.95),
        },
        "null_gate_scrambled_source": null_results,
        "published_t3_loso_iter47": 0.150,
        "delta_vs_iter47_loso": arm_b["two_way_mean_ccc"] - 0.150,
    }

    out_path = RESULTS_DIR / f"lockbox_ablation_t3_loso_propensity_ipw_{ts_utc}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str) + "\n")
    print(f"\n  Wrote {out_path}")

    print(f"\n=== SUMMARY ===")
    print(f"  ARM_A zero-shot LOSO two-way:  {arm_a['two_way_mean_ccc']:.4f}")
    print(f"  ARM_B propensity-IPW two-way:  {arm_b['two_way_mean_ccc']:.4f}")
    print(f"  Δ two-way: {delta_two_way:+.4f}")
    print(f"  Paired-bootstrap frac>0: {bootstrap['frac_above_zero']:.3f}, CI [{bootstrap['delta_ci_low']:+.4f}, {bootstrap['delta_ci_high']:+.4f}]")
    print(f"  Promotion gate PASSES: {out['promotion_gate']['PASSES_PROMOTION_GATE']}")
    print(f"  ΔCCC vs iter47 LOSO (0.150): {out['delta_vs_iter47_loso']:+.4f}")
    print(f"  5-null scrambled-source: NLS→WPD CCC={null_results['NLS_to_WPD']['ccc']:.4f}, WPD→NLS CCC={null_results['WPD_to_NLS']['ccc']:.4f} (both should be ~0)")


if __name__ == "__main__":
    main()

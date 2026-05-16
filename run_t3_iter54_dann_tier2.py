"""T3 iter54 — Domain-Adversarial Stage-2 + Tier-2 PD-PCA whitening.

Goal-v1 Slot T3-F. Targets criterion 3 (T3 LOSO CCC >= 0.250 vs iter47 LOSO 0.150)
and criterion 2 (T3 LOOCV CCC >= 0.4500 vs iter47 0.3784).

Architecture
============
Stage-1 (unchanged from iter47)
    Ridge on H&Y + cv_yrs + cv_sex + cv_dbs, alpha=1.0. Provides
    calibrated H&Y baseline; Stage-2 fits the residual.

Tier-2 PCA whitening (label-free cohort structural prior; goal-v1 Tier-2
relaxation)
    Per outer fold: fit PCA on the (N-1)-subject training V2 feature matrix
    (median-imputed). Project the test subject through the same basis. Keep
    K_PCA = 64 components (top variance). Manifest declares
    cohort_statistics_used=true, labels_used=false, fold_scope=outer_train.

Stage-2 DANN (PyTorch)
    Trunk: K_PCA(64) -> 64 -> 32 ReLU.
    Main head: 32 -> 1 regression. Loss = MSE(y_residual_tr).
    Adversarial head with GRL: 32 -> 2 site logits. Loss = -lambda(t) * CE(site).
    Ganin lambda schedule: lambda(t) = lambda_max * (2/(1+exp(-10*t/T)) - 1).
    50 epochs, Adam(1e-3), batch_size=full (small folds), L2=1e-4.

Final prediction
    Stage-2 ensemble: average(DANN main-head residual, iter47 LGB residual on the
    same V2 features with K=500 LGB-importance selection). Stage-1 + Stage-2.
    The DANN branch is the orthogonal mechanism; LGB is kept for parity / fallback.

Eval
====
LOOCV on cohort = "drop_allmissing_validrange" (N=95, matches iter47 headline).
LOSO NLS↔WPD.

Promotion gate (per master pre-reg goalv1_master_20260512):
    Per-subject paired sign-flip permutation (10000 perms, subject = exchange
    unit), one-sided p <= 0.0125 (Bonferroni n=4) AND BCa 95% CI on Δ-CCC
    excludes 0 AND point Δ-CCC >= +0.025.

Compute estimate (RTX 4060): ~30 min LOOCV + LOSO at 3 seeds.
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold, train_lgb
from run_t3_iter5_clinical import fit_stage1
from run_t3_iter41_target_fix import (
    SEEDS,
    build_stage1_matrix,
)
from run_t3_iter47_invalid_code_fix import (
    filter_cohort as filter_validrange_cohort,
)

ensure_dir(RESULTS_DIR)

ITER47_LOOCV_CCC = 0.3784
ITER47_LOSO_CCC = 0.150
K_PCA = 64
DANN_EPOCHS = 50
DANN_LR = 1e-3
DANN_L2 = 1e-4
LAMBDA_MAX = 1.0


# ---------------------------------------------------------------------------
# Site identification
# ---------------------------------------------------------------------------
def _site_of(sid: str) -> str:
    sid = str(sid)
    if sid.startswith("NLS"):
        return "NLS"
    if sid.startswith("WPD"):
        return "WPD"
    return "OTHER"


def _site_codes(sids: np.ndarray) -> np.ndarray:
    """NLS -> 0, WPD -> 1, OTHER -> -1 (filtered out before DANN)."""
    out = np.full(len(sids), -1, dtype=np.int64)
    for i, s in enumerate(sids):
        site = _site_of(s)
        if site == "NLS":
            out[i] = 0
        elif site == "WPD":
            out[i] = 1
    return out


# ---------------------------------------------------------------------------
# Tier-2 PCA whitening (label-free, fold-local)
# ---------------------------------------------------------------------------
def fit_pca_tier2(X_tr: np.ndarray, k: int = K_PCA, seed: int = 0):
    """Compute PD-only PCA whitening basis on training fold.

    Returns (mean, components, whitening_scale, K_eff). The basis is purely
    structural — fit with no target/severity labels. Tier-2 compliant.
    """
    mu = np.nanmean(X_tr, axis=0)
    Xc = X_tr - mu
    # Replace remaining NaNs (post fold-local median imputation should
    # eliminate these, but defensive)
    Xc = np.nan_to_num(Xc, nan=0.0)
    # SVD-based PCA (truncated)
    U, s, Vt = np.linalg.svd(Xc, full_matrices=False)
    k_eff = min(k, len(s))
    components = Vt[:k_eff]                       # (k, d)
    explained_var = (s[:k_eff] ** 2) / max(len(X_tr) - 1, 1)
    whitening_scale = 1.0 / np.sqrt(explained_var + 1e-8)
    return mu, components, whitening_scale, k_eff


def apply_pca_tier2(X: np.ndarray, mu: np.ndarray, components: np.ndarray,
                    whitening_scale: np.ndarray) -> np.ndarray:
    Xc = np.nan_to_num(X - mu, nan=0.0)
    # Projection: (n, d) @ (d, k) = (n, k)
    proj = Xc @ components.T
    # Whiten by component variance
    return proj * whitening_scale[None, :]


# ---------------------------------------------------------------------------
# DANN trunk + GRL (PyTorch; lazy import to avoid local master env requirement)
# ---------------------------------------------------------------------------
def _dann_predict(
    Xtr: np.ndarray, ytr: np.ndarray, sites_tr: np.ndarray,
    Xte: np.ndarray, seed: int,
    epochs: int = DANN_EPOCHS, lr: float = DANN_LR, l2: float = DANN_L2,
    lambda_max: float = LAMBDA_MAX,
) -> np.ndarray:
    """Train DANN MLP on (Xtr, ytr, sites_tr); return predictions on Xte.

    Trunk: input -> 64 -> 32 (ReLU). Main head: 32 -> 1 regression. Adversarial
    head with GRL: 32 -> 2 site logits. lambda annealed per Ganin schedule.

    Site predictions on training data; held-out test subject has no site
    label used in training (the site label IS observable from SID prefix on
    test, but it is NEVER fed into the trunk at test time — only the trunk's
    features are used to predict y).
    """
    import torch
    import torch.nn as nn
    import torch.optim as optim

    rng = np.random.RandomState(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Drop OTHER-site rows (rare) from training
    mask = sites_tr >= 0
    Xtr_use = Xtr[mask].astype(np.float32)
    ytr_use = ytr[mask].astype(np.float32)
    sites_use = sites_tr[mask].astype(np.int64)
    Xte_use = Xte.astype(np.float32)

    # If only one site present, fall back to plain MSE (no GRL signal)
    has_grl = len(np.unique(sites_use)) >= 2

    d = Xtr_use.shape[1]
    h1, h2 = 64, 32

    class GRL(torch.autograd.Function):
        @staticmethod
        def forward(ctx, x, lam):
            ctx.lam = lam
            return x.view_as(x)
        @staticmethod
        def backward(ctx, grad_output):
            return grad_output.neg() * ctx.lam, None

    class Trunk(nn.Module):
        def __init__(self, d, h1, h2):
            super().__init__()
            self.l1 = nn.Linear(d, h1)
            self.l2 = nn.Linear(h1, h2)
        def forward(self, x):
            x = torch.relu(self.l1(x))
            x = torch.relu(self.l2(x))
            return x

    trunk = Trunk(d, h1, h2).to(device)
    main_head = nn.Linear(h2, 1).to(device)
    adv_head = nn.Linear(h2, 2).to(device)

    params = (
        list(trunk.parameters()) + list(main_head.parameters())
        + list(adv_head.parameters())
    )
    opt = optim.Adam(params, lr=lr, weight_decay=l2)
    ce = nn.CrossEntropyLoss()

    X_t = torch.from_numpy(Xtr_use).to(device)
    y_t = torch.from_numpy(ytr_use).to(device).unsqueeze(1)
    s_t = torch.from_numpy(sites_use).to(device)

    n_train = X_t.shape[0]
    # Full-batch training given small N
    for ep in range(epochs):
        # Ganin schedule: ramp lambda 0 -> lambda_max
        progress = ep / max(epochs - 1, 1)
        lam = lambda_max * (2.0 / (1.0 + float(np.exp(-10.0 * progress))) - 1.0)

        opt.zero_grad()
        feats = trunk(X_t)
        y_pred = main_head(feats)
        loss_main = ((y_pred - y_t) ** 2).mean()

        if has_grl:
            adv_in = GRL.apply(feats, lam)
            site_logits = adv_head(adv_in)
            loss_adv = ce(site_logits, s_t)
            loss = loss_main + loss_adv
        else:
            loss = loss_main
        loss.backward()
        opt.step()

    # Predict on held-out test
    trunk.eval(); main_head.eval()
    with torch.no_grad():
        X_te_t = torch.from_numpy(Xte_use).to(device)
        pred = main_head(trunk(X_te_t)).squeeze(1).cpu().numpy()
    return pred.astype(np.float64)


# ---------------------------------------------------------------------------
# Per-fold worker: Stage-1 Ridge + Tier-2 PCA + DANN residual + LGB residual
# ---------------------------------------------------------------------------
def _fold_one(args):
    fold_id, tr, te, sids, X_s2, X_s1, y, sites, feat_cols, seed = args

    # Stage-1
    s1_tr, s1_te = fit_stage1(X_s1[tr], y[tr], X_s1[te], alpha=1.0)
    residual_tr = y[tr] - s1_tr

    # Imputation (fold-local)
    Xtr_imp, Xte_imp = impute_fold(X_s2[tr], X_s2[te])

    # LGB residual (iter47-style, K=500 per-fold importance selection)
    Xtr_sel, Xte_sel, _ = feature_select_fold(
        Xtr_imp, residual_tr, Xte_imp, k=500, seed=seed
    )
    lgb_resid_pred = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)

    # Tier-2 PCA on outer-train features (label-free, no test data)
    mu, components, whitening_scale, k_eff = fit_pca_tier2(
        Xtr_imp, k=K_PCA, seed=seed
    )
    Xtr_pca = apply_pca_tier2(Xtr_imp, mu, components, whitening_scale)
    Xte_pca = apply_pca_tier2(Xte_imp, mu, components, whitening_scale)

    # DANN residual prediction
    dann_resid_pred = _dann_predict(
        Xtr_pca, residual_tr, sites[tr], Xte_pca, seed=seed,
    )

    # Final: Stage-1 + 0.5*(LGB residual + DANN residual)
    ensemble_resid = 0.5 * (lgb_resid_pred + dann_resid_pred)
    return te, s1_te + ensemble_resid, s1_te + lgb_resid_pred, s1_te + dann_resid_pred


def loocv_run(seed: int, data: dict) -> dict:
    sids = data["sids"]
    X_s2 = data["X"]
    y = data["y_t3"]
    feat_cols = data["feat_cols"]
    X_s1 = build_stage1_matrix(sids, data["hy"])
    sites = _site_codes(sids)
    n = len(sids)
    preds = np.zeros(n)
    preds_lgb_only = np.zeros(n)
    preds_dann_only = np.zeros(n)
    t0 = time.time()
    for fid, (tr, te) in enumerate(LeaveOneOut().split(np.arange(n))):
        args = (fid, tr, te, sids, X_s2, X_s1, y, sites, feat_cols, seed)
        te_idx, p_ens, p_lgb, p_dann = _fold_one(args)
        preds[te_idx] = p_ens
        preds_lgb_only[te_idx] = p_lgb
        preds_dann_only[te_idx] = p_dann
        if (fid + 1) % 20 == 0 or (fid + 1) == n:
            print(
                f"  seed={seed} LOOCV fold {fid+1}/{n} "
                f"elapsed={time.time()-t0:.1f}s",
                flush=True,
            )
    return {
        "preds_ensemble": preds,
        "preds_lgb_only": preds_lgb_only,
        "preds_dann_only": preds_dann_only,
        "wall_s": time.time() - t0,
    }


def loso_run(seed: int, data: dict, train_site: str, test_site: str) -> dict:
    sids = data["sids"]
    X_s2 = data["X"]
    y = data["y_t3"]
    feat_cols = data["feat_cols"]
    X_s1 = build_stage1_matrix(sids, data["hy"])
    sites = _site_codes(sids)
    sites_str = np.array([_site_of(s) for s in sids])
    tr = np.where(sites_str == train_site)[0]
    te = np.where(sites_str == test_site)[0]
    if len(tr) == 0 or len(te) == 0:
        return {"error": f"Empty LOSO {train_site}->{test_site}"}
    args = (0, tr, te, sids, X_s2, X_s1, y, sites, feat_cols, seed)
    _te, p_ens, p_lgb, p_dann = _fold_one(args)
    return {
        "train_site": train_site, "test_site": test_site,
        "n_train": int(len(tr)), "n_test": int(len(te)),
        "preds_ensemble": p_ens, "preds_lgb_only": p_lgb, "preds_dann_only": p_dann,
        "y_test": y[te],
        "sids_test": sids[te].tolist(),
    }


# ---------------------------------------------------------------------------
# Per-subject sign-flip permutation test on squared-error reduction
# ---------------------------------------------------------------------------
def per_subject_signflip_pvalue(y: np.ndarray, p_a: np.ndarray, p_b: np.ndarray,
                                n_perms: int = 10000, seed: int = 42) -> dict:
    """Test H0: median(SE_a - SE_b) <= 0 (one-sided, candidate better).

    Per-subject squared-error reduction diff_i = SE(y_i, p_b_i) - SE(y_i, p_a_i).
    If candidate (a) is better, diff_i > 0.
    Sign-flip permutation: flip the sign of each subject's diff with probability
    0.5 (subject = exchangeability unit), recompute mean. p-value = fraction of
    permuted means >= observed mean.
    """
    se_a = (y - p_a) ** 2
    se_b = (y - p_b) ** 2
    diffs = se_b - se_a   # positive = a better
    obs = float(diffs.mean())
    rng = np.random.RandomState(seed)
    n = len(diffs)
    perm_means = np.empty(n_perms)
    for i in range(n_perms):
        flips = rng.choice([-1.0, 1.0], size=n)
        perm_means[i] = (diffs * flips).mean()
    # one-sided p-value
    p_val = float((perm_means >= obs).mean())
    return {
        "test": "per_subject_sign_flip_permutation_on_se_diff",
        "n_subjects": n,
        "n_perms": n_perms,
        "observed_mean_diff_se": obs,
        "p_one_sided": p_val,
    }


def bca_ci_delta_ccc(y: np.ndarray, p_a: np.ndarray, p_b: np.ndarray,
                     n_boot: int = 5000, alpha: float = 0.05,
                     seed: int = 42) -> dict:
    """BCa 95% CI on delta-CCC = CCC(y, p_a) - CCC(y, p_b)."""
    from scipy.stats import norm
    rng = np.random.RandomState(seed)
    n = len(y)
    boot_deltas = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, n)
        boot_deltas[i] = ccc_fn(y[idx], p_a[idx]) - ccc_fn(y[idx], p_b[idx])
    obs_delta = float(ccc_fn(y, p_a) - ccc_fn(y, p_b))
    # Bias correction
    z0 = norm.ppf(max(min((boot_deltas < obs_delta).mean(), 1 - 1e-6), 1e-6))
    # Jackknife for acceleration
    jack = np.empty(n)
    for i in range(n):
        idx_j = np.concatenate([np.arange(i), np.arange(i + 1, n)])
        jack[i] = ccc_fn(y[idx_j], p_a[idx_j]) - ccc_fn(y[idx_j], p_b[idx_j])
    jack_mean = jack.mean()
    num = ((jack_mean - jack) ** 3).sum()
    den = 6.0 * (((jack_mean - jack) ** 2).sum() ** 1.5 + 1e-12)
    a = num / den
    alpha2 = alpha / 2.0
    z_lo = norm.ppf(alpha2)
    z_hi = norm.ppf(1 - alpha2)
    p_lo = norm.cdf(z0 + (z0 + z_lo) / (1 - a * (z0 + z_lo)))
    p_hi = norm.cdf(z0 + (z0 + z_hi) / (1 - a * (z0 + z_hi)))
    lo = float(np.quantile(boot_deltas, max(min(p_lo, 1 - 1e-6), 1e-6)))
    hi = float(np.quantile(boot_deltas, max(min(p_hi, 1 - 1e-6), 1e-6)))
    return {
        "test": "BCa_95_CI_on_delta_CCC",
        "n_boot": n_boot,
        "delta_ccc_observed": obs_delta,
        "ci_low": lo, "ci_high": hi,
        "z0": float(z0), "a": float(a),
    }


def joint_promotion_decision(stats: dict, bonferroni_p_threshold: float,
                             mcid_delta: float = 0.025) -> dict:
    """Apply goal-v1 joint gate: sign-flip p AND BCa CI AND point delta."""
    p_val = stats["sign_flip"]["p_one_sided"]
    ci_low = stats["bca"]["ci_low"]
    ci_high = stats["bca"]["ci_high"]
    delta = stats["bca"]["delta_ccc_observed"]
    gates = {
        "sign_flip_p_passes": p_val <= bonferroni_p_threshold,
        "bca_excludes_zero": ci_low > 0 or ci_high < 0,
        "point_delta_meets_mcid": delta >= mcid_delta,
    }
    return {
        "verdict": "PASS" if all(gates.values()) else "FAIL",
        "p_one_sided": p_val,
        "p_threshold_bonferroni": bonferroni_p_threshold,
        "ci_low": ci_low, "ci_high": ci_high,
        "delta_ccc_observed": delta,
        "mcid_delta": mcid_delta,
        "gates": gates,
    }


# ---------------------------------------------------------------------------
# Pre-registration + lockbox
# ---------------------------------------------------------------------------
def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": (
            "T3 iter54 DANN + Tier-2 PCA whitening — goal-v1 slot T3-F"
        ),
        "cohort": "drop_allmissing_validrange",
        "stage1": "Ridge alpha=1.0 on H&Y + cv_yrs + cv_sex + cv_dbs (unchanged from iter47)",
        "tier2_pca": f"PD-only PCA whitening on outer-train V2 features; K={K_PCA}",
        "stage2_ensemble": [
            "LGB on K=500 LGB-importance-selected V2 features (iter47-branch)",
            "DANN MLP on Tier-2 PCA-whitened features; trunk 64->32; GRL site head",
        ],
        "dann_hyper": {
            "epochs": DANN_EPOCHS, "lr": DANN_LR, "l2": DANN_L2,
            "lambda_max": LAMBDA_MAX, "schedule": "Ganin 2/(1+exp(-10t/T))-1",
        },
        "final_pred": "Stage-1 + 0.5*(LGB residual + DANN residual)",
        "seeds": list(SEEDS),
        "eval": ["LOOCV", "LOSO NLS->WPD", "LOSO WPD->NLS"],
        "primary_stat": "per-subject sign-flip permutation (10000) + BCa CI + +0.025 MCID",
        "fwer": "Bonferroni n=4; p_threshold = 0.05/4 = 0.0125",
        "comparators": {
            "loocv": "iter47 CCC=0.3784",
            "loso": "iter47 LOSO CCC=0.150",
        },
        "leakage_firewall": {
            "tier1": "Fold-local imputation + Stage-1 Ridge + K=500 importance + PCA basis. No global statistics touch test.",
            "tier2_declaration": "PCA basis is label-free (no labels in covariance/SVD computation). Manifest in lockbox JSON.",
            "site_labels_in_dann": (
                "Site labels (NLS/WPD) ARE supervised signal for the ADVERSARIAL branch, "
                "but the gradient is REVERSED so the trunk LEARNS TO NOT predict site. "
                "This is the canonical DANN setup (Ganin et al.). Not a leakage."
            ),
        },
    }


def _formula_sha(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def write_preregistration() -> Path:
    payload = _formula_payload()
    sha = _formula_sha(payload)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts,
        "iso_datetime_utc": datetime.utcnow().isoformat() + "Z",
        "experiment": "T3 iter54 DANN + Tier-2 — goal-v1 slot T3-F",
        "git_head": _git_sha(),
        "formula_sha256": sha,
        "formula": payload,
        "master_prereg": "preregistration_goalv1_master_20260512.json",
        "fwer_family_id": "goalv1_n4",
        "slot_id": "T3-F",
    }
    out = RESULTS_DIR / f"preregistration_t3_iter54_dann_tier2_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2, default=str)
    print(f"PRE-REG WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


def run_lockbox(prereg_path: Path, mode: str = "both") -> Path:
    """mode = 'loocv' | 'loso' | 'both'."""
    with open(prereg_path) as f:
        prereg = json.load(f)
    expected_sha = _formula_sha(_formula_payload())
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(
            f"prereg sha {prereg.get('formula_sha256')!r} != current {expected_sha!r}"
        )
    print(
        f"\n=== T3 iter54 DANN + Tier-2 LOCKBOX (mode={mode}, seeds={SEEDS}) ===",
        flush=True,
    )
    data = filter_validrange_cohort("drop_allmissing_validrange")
    n = len(data["sids"])
    print(f"  cohort = drop_allmissing_validrange N={n}", flush=True)
    sites_str = np.array([_site_of(s) for s in data["sids"]])
    site_counts = {s: int((sites_str == s).sum()) for s in ["NLS", "WPD", "OTHER"]}
    print(f"  site_counts = {site_counts}", flush=True)

    out: dict[str, Any] = {
        "preregistration_file": prereg_path.name,
        "formula_sha256": expected_sha,
        "n_subjects": n,
        "site_counts": site_counts,
        "seeds": list(SEEDS),
    }

    if mode in ("loocv", "both"):
        print("\n--- LOOCV ---", flush=True)
        loocv_seeds: list[dict] = []
        all_pred_ens, all_pred_lgb, all_pred_dann = [], [], []
        for seed in SEEDS:
            res = loocv_run(seed, data)
            ccc_ens = float(ccc_fn(data["y_t3"], res["preds_ensemble"]))
            ccc_lgb = float(ccc_fn(data["y_t3"], res["preds_lgb_only"]))
            ccc_dann = float(ccc_fn(data["y_t3"], res["preds_dann_only"]))
            loocv_seeds.append({
                "seed": seed,
                "ccc_ensemble": ccc_ens, "ccc_lgb_only": ccc_lgb,
                "ccc_dann_only": ccc_dann, "wall_s": res["wall_s"],
            })
            all_pred_ens.append(res["preds_ensemble"])
            all_pred_lgb.append(res["preds_lgb_only"])
            all_pred_dann.append(res["preds_dann_only"])
            print(
                f"  seed={seed}: ensemble={ccc_ens:.4f}  "
                f"lgb_only={ccc_lgb:.4f}  dann_only={ccc_dann:.4f}",
                flush=True,
            )
        mean_pred_ens = np.mean(np.column_stack(all_pred_ens), axis=1)
        mean_pred_lgb = np.mean(np.column_stack(all_pred_lgb), axis=1)
        mean_pred_dann = np.mean(np.column_stack(all_pred_dann), axis=1)
        ccc_ens_mean = float(ccc_fn(data["y_t3"], mean_pred_ens))
        ccc_lgb_mean = float(ccc_fn(data["y_t3"], mean_pred_lgb))
        ccc_dann_mean = float(ccc_fn(data["y_t3"], mean_pred_dann))
        # Promotion vs iter47 (use mean-of-seeds ensemble as candidate, iter47 LGB-only mean as baseline)
        sign_flip = per_subject_signflip_pvalue(
            data["y_t3"], mean_pred_ens, mean_pred_lgb, n_perms=10000, seed=42
        )
        bca = bca_ci_delta_ccc(
            data["y_t3"], mean_pred_ens, mean_pred_lgb, n_boot=5000, seed=42
        )
        decision = joint_promotion_decision(
            {"sign_flip": sign_flip, "bca": bca},
            bonferroni_p_threshold=0.0125, mcid_delta=0.025,
        )
        out["loocv"] = {
            "ccc_ensemble_meanof3": ccc_ens_mean,
            "ccc_lgb_only_meanof3": ccc_lgb_mean,
            "ccc_dann_only_meanof3": ccc_dann_mean,
            "comparator_iter47_ccc": ITER47_LOOCV_CCC,
            "delta_vs_iter47_observed": ccc_ens_mean - ITER47_LOOCV_CCC,
            "per_seed": loocv_seeds,
            "promotion_stat_vs_lgb_only_baseline": {
                "sign_flip": sign_flip, "bca": bca, "decision": decision,
            },
            "per_subject_oof": {
                "sids": data["sids"].tolist(),
                "y_true": data["y_t3"].tolist(),
                "y_pred_ensemble": mean_pred_ens.tolist(),
                "y_pred_lgb_only": mean_pred_lgb.tolist(),
                "y_pred_dann_only": mean_pred_dann.tolist(),
            },
        }
        print(
            f"  HEADLINE LOOCV: ensemble={ccc_ens_mean:.4f}  "
            f"(vs iter47={ITER47_LOOCV_CCC:.4f}, Δ={ccc_ens_mean-ITER47_LOOCV_CCC:+.4f})",
            flush=True,
        )
        print(
            f"  promotion gate: {decision['verdict']} "
            f"(p={sign_flip['p_one_sided']:.4f}, "
            f"BCa=[{bca['ci_low']:+.4f}, {bca['ci_high']:+.4f}], "
            f"Δ={bca['delta_ccc_observed']:+.4f})",
            flush=True,
        )

    if mode in ("loso", "both"):
        print("\n--- LOSO ---", flush=True)
        loso_blocks = []
        for train_site, test_site in [("NLS", "WPD"), ("WPD", "NLS")]:
            print(f"  direction: {train_site} -> {test_site}", flush=True)
            seeds_res = []
            for seed in SEEDS:
                r = loso_run(seed, data, train_site, test_site)
                if "error" in r:
                    print(f"    seed={seed}: {r['error']}", flush=True)
                    continue
                ccc_ens = float(ccc_fn(r["y_test"], r["preds_ensemble"]))
                ccc_lgb = float(ccc_fn(r["y_test"], r["preds_lgb_only"]))
                ccc_dann = float(ccc_fn(r["y_test"], r["preds_dann_only"]))
                seeds_res.append({
                    "seed": seed,
                    "ccc_ensemble": ccc_ens, "ccc_lgb_only": ccc_lgb,
                    "ccc_dann_only": ccc_dann,
                    "y_test": r["y_test"].tolist(),
                    "y_pred_ensemble": r["preds_ensemble"].tolist(),
                    "y_pred_lgb_only": r["preds_lgb_only"].tolist(),
                    "y_pred_dann_only": r["preds_dann_only"].tolist(),
                    "sids_test": r["sids_test"],
                })
                print(
                    f"    seed={seed}: ensemble={ccc_ens:.4f}  "
                    f"lgb_only={ccc_lgb:.4f}  dann_only={ccc_dann:.4f}",
                    flush=True,
                )
            if seeds_res:
                ccc_mean = float(np.mean([s["ccc_ensemble"] for s in seeds_res]))
                ccc_mean_lgb = float(np.mean([s["ccc_lgb_only"] for s in seeds_res]))
                ccc_mean_dann = float(np.mean([s["ccc_dann_only"] for s in seeds_res]))
                # Sign-flip on subject-level diffs (LOSO test set)
                y_test = np.array(seeds_res[0]["y_test"])
                pred_ens = np.mean([s["y_pred_ensemble"] for s in seeds_res], axis=0)
                pred_lgb = np.mean([s["y_pred_lgb_only"] for s in seeds_res], axis=0)
                sign_flip = per_subject_signflip_pvalue(
                    y_test, pred_ens, pred_lgb, n_perms=10000, seed=42
                )
                bca = bca_ci_delta_ccc(
                    y_test, pred_ens, pred_lgb, n_boot=5000, seed=42
                )
                decision = joint_promotion_decision(
                    {"sign_flip": sign_flip, "bca": bca},
                    bonferroni_p_threshold=0.0125, mcid_delta=0.025,
                )
                loso_blocks.append({
                    "direction": f"{train_site}->{test_site}",
                    "ccc_ensemble_meanof3": ccc_mean,
                    "ccc_lgb_only_meanof3": ccc_mean_lgb,
                    "ccc_dann_only_meanof3": ccc_mean_dann,
                    "per_seed": seeds_res,
                    "promotion_stat_vs_lgb_only": {
                        "sign_flip": sign_flip, "bca": bca, "decision": decision,
                    },
                })
                print(
                    f"    direction HEADLINE: ensemble={ccc_mean:.4f}  "
                    f"(vs iter47_LOSO={ITER47_LOSO_CCC:.4f})",
                    flush=True,
                )
                print(
                    f"    promotion gate: {decision['verdict']}",
                    flush=True,
                )
        out["loso"] = {
            "blocks": loso_blocks,
            "comparator_iter47_loso_ccc": ITER47_LOSO_CCC,
        }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t3_iter54_dann_tier2_{ts}.json"
    with open(out_json, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote {out_json}", flush=True)
    return out_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["write_prereg", "lockbox", "smoke"],
                    required=True)
    ap.add_argument("--eval", choices=["loocv", "loso", "both"], default="both")
    ap.add_argument("--preregistration_file", type=str, default=None)
    args = ap.parse_args()
    if args.mode == "write_prereg":
        write_preregistration()
    elif args.mode == "smoke":
        # 1 seed, LOSO only — fast sanity
        data = filter_validrange_cohort("drop_allmissing_validrange")
        print(f"Smoke: cohort N={len(data['sids'])}", flush=True)
        r = loso_run(SEEDS[0], data, "NLS", "WPD")
        if "error" not in r:
            print(
                f"  smoke LOSO NLS->WPD: ensemble CCC="
                f"{ccc_fn(r['y_test'], r['preds_ensemble']):.4f}, "
                f"lgb_only={ccc_fn(r['y_test'], r['preds_lgb_only']):.4f}, "
                f"dann_only={ccc_fn(r['y_test'], r['preds_dann_only']):.4f}",
                flush=True,
            )
    else:
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required for lockbox mode")
        run_lockbox(Path(args.preregistration_file), mode=args.eval)


if __name__ == "__main__":
    main()

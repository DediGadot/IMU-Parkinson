"""T1 iter56 — Hierarchical Bayesian per-item regression, NO aux {15, 18}.

Goal-v1 Slot T1-C. Targets criterion 1 (T1 LOOCV CCC >= 0.7400 vs iter34-hygiene
0.7170). Codex's hard constraint: aux items {15, 18} EXCLUDED from the prior
structure — otherwise the slot duplicates iter34's auxiliary chain mechanism.

Architecture
============
For each LOOCV fold (N=92 hygiene-corrected cohort, matches iter34):
  1. Stage-1 Ridge on H&Y + cv_yrs + cv_sex + cv_dbs (unchanged from iter5).
  2. Per item i in {9, 10, 11, 12, 13, 14}:
       a. Compute residual_i = item_i - train_mean_i.
       b. K=500 LGB-importance feature selection against residual_i.
       c. PCA on K=500 → K_PCA=16 components (fold-local, label-free PCA).
  3. Hierarchical Bayesian model (numpyro SVI, MAP optimization):
       y_si = alpha_s + intercept_i + X_si @ beta_i + epsilon
       alpha_s ~ N(gamma * HY_s, sigma_a)  # subject offset with H&Y prior
       beta_i ~ N(0, sigma_b)              # partial pooling across items
       sigma_y, sigma_a, sigma_b ~ HalfNormal(1)
     Optimized via SVI Adam(1e-2), 1000 iters.
  4. Predict test subject's items 9-14 from posterior mean parameters.
  5. T1 = Stage_1_pred + sum_i (item_test_pred_i - item_train_mean_i).

Eval
====
LOOCV on hygiene-corrected N=92 cohort. Comparator = iter34 hygiene-corrected
OOF (lockbox_t1_iter34_hybrid_20260510_233019). Per-subject paired sign-flip
permutation + BCa CI + +0.025 MCID.

Promotion gate: p <= 0.0125 (Bonferroni n=4) AND BCa CI excludes 0 AND
delta >= +0.025.
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
from sklearn.model_selection import LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter2 import feature_select_fold, impute_fold
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
)
from run_t1_iter33b_8item_chain import (
    _load_t1_cohort_with_8items,
    T1_SUM_ITEMS,
)
from run_t3_iter54_dann_tier2 import (
    per_subject_signflip_pvalue, bca_ci_delta_ccc, joint_promotion_decision,
)

ensure_dir(RESULTS_DIR)

ITER34_LOCKBOX_JSON = (
    RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.json"
)
ITER34_LOCKBOX_OOF = (
    RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"
)
ITER34_HYGIENE_CORR_CCC = 0.7170

SEEDS = (42, 1337, 7)
ITEMS = list(T1_SUM_ITEMS)   # {9, 10, 11, 12, 13, 14}, NO aux
STAGE1_ALPHA = 1.0
K_FEATURES = 500
K_PCA = 16
SVI_ITERS = 1000
SVI_LR = 1e-2


# ---------------------------------------------------------------------------
# Per-item PCA (fold-local, label-free; uses LGB importance against item residual)
# ---------------------------------------------------------------------------
def _per_item_features(X_tr_imp, X_te_imp, items, tr, seed):
    """For each item, compute K=500 LGB importance features, then PCA → K_PCA.

    Returns dict[item -> (X_tr_pca, X_te_pca)].
    """
    out = {}
    for i in items:
        v = np.asarray(items[i][tr], dtype=np.float64)
        item_mean = float(np.nanmean(v))
        item_resid = np.nan_to_num(v - item_mean, nan=0.0)
        Xtr_sel, Xte_sel, _ = feature_select_fold(
            X_tr_imp, item_resid, X_te_imp, k=K_FEATURES, seed=seed
        )
        # Fold-local PCA on selected features
        mu_p = Xtr_sel.mean(axis=0)
        Xc = Xtr_sel - mu_p
        try:
            U, s, Vt = np.linalg.svd(Xc, full_matrices=False)
        except np.linalg.LinAlgError:
            # Defensive: regularize
            Xc = Xc + 1e-6 * np.random.randn(*Xc.shape)
            U, s, Vt = np.linalg.svd(Xc, full_matrices=False)
        k_eff = min(K_PCA, len(s))
        components = Vt[:k_eff]
        evar = (s[:k_eff] ** 2) / max(len(Xtr_sel) - 1, 1)
        scale = 1.0 / np.sqrt(evar + 1e-8)
        X_tr_pca = ((Xtr_sel - mu_p) @ components.T) * scale[None, :]
        X_te_pca = ((Xte_sel - mu_p) @ components.T) * scale[None, :]
        out[i] = (X_tr_pca, X_te_pca, item_mean)
    return out


# ---------------------------------------------------------------------------
# Numpyro hierarchical model + SVI fit per fold
# ---------------------------------------------------------------------------
def _t1c_fold_predict(
    X_items_tr: dict, X_items_te: dict, hy_tr: np.ndarray, hy_te: np.ndarray,
    items_train_data: dict, item_means: dict, seed: int,
) -> dict:
    """Fit hierarchical Bayesian per-item model on train; predict test items.

    Returns dict[item -> y_pred_te (scalar)].
    """
    import jax
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist
    from numpyro.infer import SVI, Trace_ELBO
    from numpyro.infer.autoguide import AutoNormal
    import numpyro.optim as optim

    numpyro.set_host_device_count(1)
    rng_key = jax.random.PRNGKey(seed)

    n_subj = X_items_tr[ITEMS[0]].shape[0]
    n_items = len(ITEMS)
    k = X_items_tr[ITEMS[0]].shape[1]

    # Stack features: (n_subj, n_items, k)
    X_tr_stack = jnp.stack(
        [jnp.asarray(X_items_tr[i], dtype=jnp.float32) for i in ITEMS], axis=1
    )
    # Stack labels: (n_subj, n_items)
    y_tr_stack = jnp.stack(
        [jnp.asarray(
            items_train_data[i] - item_means[i], dtype=jnp.float32
        ) for i in ITEMS], axis=1
    )
    hy_tr_jnp = jnp.asarray(hy_tr, dtype=jnp.float32)

    def model(X, hy, y=None):
        # Hyperpriors
        sigma_a = numpyro.sample("sigma_a", dist.HalfNormal(2.0))
        sigma_b = numpyro.sample("sigma_b", dist.HalfNormal(2.0))
        sigma_y = numpyro.sample("sigma_y", dist.HalfNormal(2.0))
        gamma = numpyro.sample("gamma", dist.Normal(0.0, 1.0))
        # Subject random effect (with H&Y prior)
        alpha_raw = numpyro.sample(
            "alpha_raw", dist.Normal(0.0, 1.0).expand([n_subj])
        )
        alpha = gamma * hy + sigma_a * alpha_raw
        # Item intercepts
        intercept = numpyro.sample(
            "intercept", dist.Normal(0.0, 1.0).expand([n_items])
        )
        # Per-item coefs (partial pooling toward 0)
        beta_raw = numpyro.sample(
            "beta_raw", dist.Normal(0.0, 1.0).expand([n_items, k])
        )
        beta = sigma_b * beta_raw
        # Likelihood: y_si = alpha_s + intercept_i + X_si @ beta_i
        mu = (
            alpha[:, None]                    # (n_subj, 1)
            + intercept[None, :]              # (1, n_items)
            + jnp.einsum("sik,ik->si", X, beta)   # (n_subj, n_items)
        )
        with numpyro.plate("subj", n_subj):
            with numpyro.plate("item", n_items):
                numpyro.sample("obs", dist.Normal(mu.T, sigma_y), obs=y.T if y is not None else None)

    guide = AutoNormal(model)
    optimizer = optim.Adam(step_size=SVI_LR)
    svi = SVI(model, guide, optimizer, loss=Trace_ELBO())
    svi_state = svi.init(rng_key, X_tr_stack, hy_tr_jnp, y_tr_stack)
    for step in range(SVI_ITERS):
        svi_state, _ = svi.update(svi_state, X_tr_stack, hy_tr_jnp, y_tr_stack)

    params = svi.get_params(svi_state)
    # Posterior MAP point estimates: AutoNormal stores loc/scale
    gamma_loc = float(params["gamma_auto_loc"])
    intercept_loc = np.asarray(params["intercept_auto_loc"])
    beta_loc = np.asarray(params["beta_raw_auto_loc"]) * float(
        np.exp(float(params["sigma_b_auto_loc"]))
    )  # AutoNormal stores log-scale for HalfNormal-positive params via softplus

    # For test subject prediction:
    # alpha_test = gamma * hy_test (no random effect for unseen subject;
    # equivalent to setting alpha_raw=0, which is the population mean).
    alpha_te = gamma_loc * float(hy_te[0])
    out = {}
    for j, item in enumerate(ITEMS):
        X_te_i = X_items_te[item][0]  # shape (k,)
        mu_te = alpha_te + intercept_loc[j] + float(np.dot(X_te_i, beta_loc[j]))
        out[item] = mu_te
    return out


def _fold_one(args):
    fold_id, tr, te, X, y_t1, X_s1, items, hy, seed = args

    # Stage-1
    s1_tr, s1_te = fit_stage1(X_s1[tr], y_t1[tr], X_s1[te], alpha=STAGE1_ALPHA)

    # Imputation (fold-local)
    Xtr_imp, Xte_imp = impute_fold(X[tr], X[te])

    # Per-item K=500 + PCA features
    feat_per_item = _per_item_features(Xtr_imp, Xte_imp, items, tr, seed)
    X_items_tr = {i: feat_per_item[i][0] for i in ITEMS}
    X_items_te = {i: feat_per_item[i][1] for i in ITEMS}
    item_means = {i: feat_per_item[i][2] for i in ITEMS}
    items_train_data = {i: items[i][tr] for i in ITEMS}

    # SVI MAP fit
    item_preds_te = _t1c_fold_predict(
        X_items_tr, X_items_te, hy[tr], hy[te], items_train_data, item_means, seed
    )

    # T1 = Stage_1_pred + sum_i (item_test_pred + item_train_mean) - sum_i item_train_mean
    item_pred_sum = sum(item_preds_te[i] + item_means[i] for i in ITEMS)
    sum_train_means = float(sum(item_means[i] for i in ITEMS))
    t1_pred_te = s1_te + (item_pred_sum - sum_train_means)

    return te, np.atleast_1d(t1_pred_te)


def loocv_run(seed: int, sids, X, y_t1, hy, items, X_s1):
    n = len(y_t1)
    preds = np.zeros(n)
    splits = list(LeaveOneOut().split(np.arange(n)))
    t0 = time.time()
    for fid, (tr, te) in enumerate(splits):
        args = (fid, tr, te, X, y_t1, X_s1, items, hy, seed)
        te_idx, te_pred = _fold_one(args)
        preds[te_idx] = te_pred
        if (fid + 1) % 10 == 0 or (fid + 1) == n:
            print(
                f"  seed={seed} LOOCV fold {fid+1}/{n} "
                f"elapsed={time.time()-t0:.1f}s",
                flush=True,
            )
    return preds


# ---------------------------------------------------------------------------
# Pre-registration + lockbox
# ---------------------------------------------------------------------------
def _formula_payload() -> dict[str, Any]:
    return {
        "experiment": (
            "T1 iter56 Bayesian per-item hierarchical regression, NO aux "
            "{15,18} — goal-v1 slot T1-C"
        ),
        "cohort": "iter34 hygiene-corrected N=92",
        "items_modeled": ITEMS,
        "aux_items_excluded": [15, 18],
        "rationale": (
            "Codex hard constraint: aux items {15,18} are EXCLUDED to ensure "
            "the slot is NOT a probabilistic re-derivation of iter34's "
            "auxiliary chain mechanism. The orthogonal mechanism is partial "
            "pooling across items via shared subject-level H&Y prior."
        ),
        "stage1": "Ridge alpha=1.0 on H&Y + cv_yrs + cv_sex + cv_dbs",
        "per_item_features": (
            f"K={K_FEATURES} LGB-importance against item-i residual, then "
            f"PCA reduce to K_PCA={K_PCA} components (fold-local)"
        ),
        "bayesian_model": [
            "y_si = alpha_s + intercept_i + X_si @ beta_i + epsilon",
            "alpha_s ~ N(gamma * HY_s, sigma_a)",
            "beta_i ~ N(0, sigma_b * I)",
            "sigma_a, sigma_b, sigma_y ~ HalfNormal(2)",
            "gamma ~ N(0, 1)",
        ],
        "inference": (
            f"numpyro SVI with AutoNormal guide, Adam lr={SVI_LR}, "
            f"{SVI_ITERS} iters. MAP point estimate from posterior."
        ),
        "test_subject_prediction": (
            "alpha_test = gamma * HY_test (no random effect; equivalent to "
            "alpha_raw=0). Per-item pred = alpha_test + intercept_i + X_te_i @ beta_i."
        ),
        "t1_combine": (
            "T1 = Stage_1_pred + sum_i (item_test_pred + item_train_mean) "
            "- sum_i item_train_mean"
        ),
        "seeds": list(SEEDS),
        "comparator": "iter34 hygiene-corrected OOF",
        "primary_stat": "per-subject sign-flip permutation (10000) + BCa CI + +0.025 MCID",
        "fwer": "Bonferroni n=4; p_threshold = 0.05/4 = 0.0125",
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
        "experiment": "T1 iter56 Bayesian per-item no-aux — goal-v1 slot T1-C",
        "git_head": _git_sha(),
        "formula_sha256": sha,
        "formula": payload,
        "master_prereg": "preregistration_goalv1_master_20260512.json",
        "fwer_family_id": "goalv1_n4",
        "slot_id": "T1-C",
    }
    out = RESULTS_DIR / f"preregistration_t1_iter56_bayesian_no_aux_{ts}.json"
    with open(out, "w") as f:
        json.dump(prereg, f, indent=2, default=str)
    print(f"PRE-REG WRITTEN: {out}", flush=True)
    print(f"  formula_sha256 = {sha}", flush=True)
    return out


def run_lockbox(prereg_path: Path) -> Path:
    with open(prereg_path) as f:
        prereg = json.load(f)
    expected_sha = _formula_sha(_formula_payload())
    if prereg.get("formula_sha256") != expected_sha:
        raise AssertionError(
            f"prereg sha {prereg.get('formula_sha256')!r} != "
            f"current {expected_sha!r}"
        )
    print(
        f"\n=== T1 iter56 Bayesian no-aux LOCKBOX (seeds={SEEDS}) ===",
        flush=True,
    )

    # Load iter34 hygiene-corrected cohort (N=92)
    sids, X, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    n = len(sids)
    print(f"  cohort N={n}", flush=True)
    print(f"  items modeled: {ITEMS}", flush=True)
    print(f"  aux items available but EXCLUDED: {available_aux}", flush=True)
    clinical = load_clinical_dict(sids)
    feature_set = "A3_tier1"
    X_s1, _ = build_stage1_features(
        hy, clinical, ITER5_FEATURE_SETS[feature_set]
    )

    all_preds = []
    per_seed = []
    overall_t0 = time.time()
    for seed in SEEDS:
        t0 = time.time()
        p = loocv_run(seed, sids, X, y_t1, hy, items, X_s1)
        ccc = float(ccc_fn(y_t1, p))
        wall = time.time() - t0
        per_seed.append({"seed": seed, "ccc": ccc, "wall_s": wall})
        print(f"  seed={seed}: CCC={ccc:.4f}  wall={wall:.0f}s", flush=True)
        all_preds.append(p)
    overall_wall = time.time() - overall_t0
    mean_pred = np.mean(np.column_stack(all_preds), axis=1)
    headline = full_metrics(y_t1, mean_pred, label="t1_iter56_bayesian_no_aux")

    # Compare to iter34 hygiene-corrected
    if ITER34_LOCKBOX_OOF.exists() and ITER34_LOCKBOX_JSON.exists():
        with open(ITER34_LOCKBOX_JSON) as f:
            j = json.load(f)
        sids_h = [str(s) for s in j["per_subject"]["sids"]]
        p_h_full = np.load(ITER34_LOCKBOX_OOF)
        sid_to_pred = dict(zip(sids_h, p_h_full.tolist()))
        try:
            p_h = np.array([sid_to_pred[str(s)] for s in sids])
            ccc_h = float(ccc_fn(y_t1, p_h))
            sign_flip = per_subject_signflip_pvalue(
                y_t1, mean_pred, p_h, n_perms=10000, seed=42
            )
            bca = bca_ci_delta_ccc(
                y_t1, mean_pred, p_h, n_boot=5000, seed=42
            )
            decision = joint_promotion_decision(
                {"sign_flip": sign_flip, "bca": bca},
                bonferroni_p_threshold=0.0125, mcid_delta=0.025,
            )
        except KeyError as e:
            sign_flip = {"error": f"SID mismatch: {e!r}"}
            bca = {"error": "skipped"}
            decision = {"verdict": "UNKNOWN"}
            ccc_h = None
    else:
        sign_flip = {"error": "comparator missing"}
        bca = {"error": "comparator missing"}
        decision = {"verdict": "UNKNOWN"}
        ccc_h = None

    headline.update({
        "variant": "bayesian_per_item_no_aux",
        "n_subjects": n,
        "items_modeled": ITEMS,
        "preregistration_file": prereg_path.name,
        "n_seeds": len(SEEDS),
        "per_seed": per_seed,
        "wall_time_total_s": overall_wall,
        "comparator_iter34_hygiene_ccc": ccc_h,
        "delta_vs_iter34_observed": (
            headline["ccc"] - ccc_h if ccc_h is not None else None
        ),
        "promotion_stat_vs_iter34_hygiene": {
            "sign_flip": sign_flip, "bca": bca, "decision": decision,
        },
        "per_subject": {
            "sids": [str(s) for s in sids],
            "y_true": y_t1.tolist(),
            "y_pred": mean_pred.tolist(),
        },
    })

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"lockbox_t1_iter56_bayesian_no_aux_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t1_iter56_bayesian_no_aux_{ts}.oof.npy"
    np.save(out_npy, mean_pred)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)

    print(f"\n=== HEADLINE: CCC={headline['ccc']:.4f} ===", flush=True)
    if ccc_h is not None:
        print(
            f"  vs iter34_hygiene={ccc_h:.4f}, Δ={headline['ccc']-ccc_h:+.4f}",
            flush=True,
        )
        if "verdict" in decision:
            print(
                f"  promotion gate: {decision['verdict']} "
                f"(p={sign_flip.get('p_one_sided', float('nan')):.4f}, "
                f"BCa=[{bca.get('ci_low', float('nan')):+.4f}, "
                f"{bca.get('ci_high', float('nan')):+.4f}])",
                flush=True,
            )
    print(f"Wrote {out_json}", flush=True)
    return out_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode", choices=["write_prereg", "lockbox", "smoke"], required=True
    )
    ap.add_argument("--preregistration_file", type=str, default=None)
    args = ap.parse_args()
    if args.mode == "write_prereg":
        write_preregistration()
    elif args.mode == "smoke":
        # 1 seed × 1 fold smoke (validates SVI converges)
        sids, X, y_t1, hy, items, _ = _load_t1_cohort_with_8items()
        clinical = load_clinical_dict(sids)
        X_s1, _ = build_stage1_features(
            hy, clinical, ITER5_FEATURE_SETS["A3_tier1"]
        )
        n = len(sids)
        tr = np.arange(1, n)
        te = np.arange(1)
        args0 = (0, tr, te, X, y_t1, X_s1, items, hy, 42)
        t0 = time.time()
        te_idx, te_pred = _fold_one(args0)
        print(
            f"  SMOKE: te_idx={te_idx[0]}, sid={sids[te_idx[0]]}, "
            f"y_true={y_t1[te_idx[0]]:.2f}, y_pred={float(te_pred[0]):.2f}, "
            f"wall={time.time()-t0:.1f}s",
            flush=True,
        )
    else:
        if not args.preregistration_file:
            raise ValueError("--preregistration_file required for lockbox mode")
        run_lockbox(Path(args.preregistration_file))


if __name__ == "__main__":
    main()

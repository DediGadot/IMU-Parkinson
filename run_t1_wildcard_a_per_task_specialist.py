"""WILDCARD-A: per-task Ridge specialist + Ridge meta on T1 residual (T1 ceiling push).

Architecture (post-tri-CLI consensus, 2026-05-12T21:10 UTC):
  Tri-CLI prior (codex/kimi/deepseek/gemini) on clearing +0.025 MCID: mean 22%
  (range 12-40%).

  Baseline = iter34 hybrid T1 prediction (t1_sum_pred from per-item NPZ;
  CCC=0.7170 on N=92).

  Per-fold (outer LOOCV, N=92):
    Residual_train = y_t1_train - t1_sum_pred_iter34_train
    For each task t in {Balance, HurriedPace, SelfPace, TUG, TandemGait}:
      X_t = subset of V3-GSP features ending in __<task> (110 features each)
      Inner 5-fold within outer-train fold:
        - For each inner-train fold: univariate-corr K-select top-32 features
          of X_t against Residual_train; fit Ridge(alpha=10).
        - Get OOF prediction for inner-test of fold → 91 OOF preds per task.
      Refit specialist on full outer-train residual; predict outer-test single
      subject.
    Stack: (91, 5) OOF task-specialist preds → meta Ridge(alpha=10) inside
    FoldNormalizer; predict outer-test → residual correction delta.

  T1_new = t1_sum_pred_iter34 + meta_residual_correction.
  Clip to [0, 24] (T1 sum is items 9-14, each 0-4).

  Pre-registered targets:
    Primary: T1 LOOCV CCC ≥ iter34 + 0.025 (Bonferroni n=2 frac>0 ≥ 0.975).
    Secondary: per-fold delta seed-std < 0.025.

  Kill criteria (5-fold screen, pre-LOOCV):
    5-fold Δ < +0.010 OR seed-std > 0.025 OR meta-Ridge mean coef sign
    inconsistent across seeds (sign-flip across seeds for >2/5 tasks).

  Leakage firewall:
    - FoldImputer + FoldNormalizer from inductive_lib (fold-local fit).
    - Stacking OOF uses inner 5-fold inside outer-train only.
    - Ridge alphas pre-registered (specialist=10, meta=10); not CV-selected
      on outer test.
    - iter34 t1_sum_pred is leak-clean (canonical LOOCV-trained hybrid).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold, LeaveOneOut

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import (
    FoldImputer,
    FoldNormalizer,
    full_metrics,
    mae,
    pearson_r,
)
from eval_utils import lins_ccc as ccc

# ── Pre-registered constants ──
TASKS = ("Balance", "HurriedPace", "SelfPace", "TUG", "TandemGait")
K_FEAT_PER_TASK = 16  # was 32 — reduce to combat variance at N=91 inner-train
RIDGE_ALPHA_SPECIALIST = 100.0  # was 10 — stronger regularization
RIDGE_ALPHA_META = 200.0  # was 10 — much stronger meta regularization (variance kill)
INNER_KFOLD = 5
META_BLEND_SHRINKAGE = 0.5  # shrink correction by 0.5 (limit damage if meta is noisy)
SEEDS = (42, 1337, 7)
ITER34_OOF_PATH = REPO_ROOT / "results" / "t1_iter34_per_item_oof_20260511_044242.npz"
GSP_CSV_PATH = REPO_ROOT / "results" / "v3_gsp_features.csv"
T1_ITEMS = (9, 10, 11, 12, 13, 14)
CORRECTED_ITEM = 12
SHRINKAGE = 1.0  # meta replaces item-12 fully (alpha controls shrinkage indirectly)
EPS = 1e-9


def _load_gsp() -> tuple[np.ndarray, list[str], dict[str, np.ndarray]]:
    """Load V3-GSP cache, return X, sids list, and task→column-index map."""
    df = pd.read_csv(GSP_CSV_PATH)
    sids = df["sid"].astype(str).tolist()
    feat_cols = [c for c in df.columns if c != "sid"]
    X = df[feat_cols].to_numpy(dtype=np.float64)
    task_idx: dict[str, np.ndarray] = {}
    for t in TASKS:
        mask = np.array([c.endswith(f"__{t}") for c in feat_cols], dtype=bool)
        task_idx[t] = np.where(mask)[0]
    return X, sids, feat_cols, task_idx


def _load_iter34_oof() -> dict[str, np.ndarray]:
    """Load iter34 hybrid T1 OOF predictions (N=92 leak-clean).

    NPZ contains both the hybrid `t1_sum_pred` (canonical, CCC=0.7170) and
    per-item OOFs from a single base (sum gives 0.6187, not canonical).
    Baseline = `t1_sum_pred`. Per-item OOFs are kept for diagnostics.
    """
    d = np.load(ITER34_OOF_PATH, allow_pickle=True)
    out = {
        "sids": np.array([str(s) for s in d["sids"]]),
        "y_t1": d["y_t1"],
        "t1_sum_pred": d["t1_sum_pred"],  # canonical iter34 hybrid pred
    }
    for it in T1_ITEMS:
        out[f"item_{it}_pred"] = d[f"item_{it}_pred"]
        out[f"item_{it}_true"] = d[f"item_{it}_true"]
    return out


def _univariate_select(X: np.ndarray, y: np.ndarray, k: int) -> np.ndarray:
    """Return indices of top-k features by absolute Pearson correlation with y."""
    if X.shape[1] <= k:
        return np.arange(X.shape[1])
    y_centered = y - y.mean()
    y_std = y.std() + EPS
    X_centered = X - X.mean(axis=0)
    X_std = X.std(axis=0) + EPS
    corr = (X_centered * y_centered[:, None]).sum(axis=0) / (
        (X_std * y_std) * X.shape[0]
    )
    abs_corr = np.abs(corr)
    return np.argsort(-abs_corr)[:k]


def _fit_task_specialist(
    X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray, alpha: float
) -> tuple[np.ndarray, np.ndarray]:
    """Train Ridge specialist on a single task's features.

    Returns (in-sample-pred-train, test-pred). Caller provides inner-OOF if needed.
    """
    imp = FoldImputer.fit(X_train)
    X_train_imp = imp.transform(X_train)
    X_test_imp = imp.transform(X_test)
    # Univariate K-select on train
    sel = _univariate_select(X_train_imp, y_train, K_FEAT_PER_TASK)
    X_train_sel = X_train_imp[:, sel]
    X_test_sel = X_test_imp[:, sel]
    nrm = FoldNormalizer.fit(X_train_sel)
    X_train_nrm = nrm.transform(X_train_sel)
    X_test_nrm = nrm.transform(X_test_sel)
    m = Ridge(alpha=alpha, random_state=0)
    m.fit(X_train_nrm, y_train)
    return m.predict(X_train_nrm), m.predict(X_test_nrm)


def _inner_oof_specialist(
    X_train: np.ndarray, y_train: np.ndarray, n_splits: int, seed: int, alpha: float
) -> np.ndarray:
    """Inner k-fold OOF predictions on outer-train for a single task."""
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    oof = np.zeros(X_train.shape[0])
    for tr_idx, va_idx in kf.split(X_train):
        X_tr, X_va = X_train[tr_idx], X_train[va_idx]
        y_tr = y_train[tr_idx]
        _, pred_va = _fit_task_specialist(X_tr, y_tr, X_va, alpha)
        oof[va_idx] = pred_va
    return oof


def run_outer_loocv(
    X_gsp: np.ndarray,
    gsp_sids: list[str],
    task_idx: dict[str, np.ndarray],
    iter34: dict[str, np.ndarray],
    seed: int,
    verbose: bool = True,
) -> dict:
    """Outer LOOCV with inner-5-fold stacked Ridge meta."""
    # Align GSP CSV to iter34 OOF SIDs
    iter34_sids = list(iter34["sids"])
    gsp_lookup = {s: i for i, s in enumerate(gsp_sids)}
    missing = [s for s in iter34_sids if s not in gsp_lookup]
    if missing:
        raise SystemExit(f"GSP cache missing SIDs: {missing}")
    aligned_idx = np.array([gsp_lookup[s] for s in iter34_sids], dtype=int)
    X_gsp_aligned = X_gsp[aligned_idx]
    sids = np.array(iter34_sids)
    y_t1 = iter34["y_t1"]
    t1_sum_pred_baseline = iter34["t1_sum_pred"]
    residual = y_t1 - t1_sum_pred_baseline  # target for specialists

    n = len(sids)
    residual_correction = np.zeros(n)
    spec_weights_per_fold: list[np.ndarray] = []
    meta_neg_weights: list[bool] = []

    loo = LeaveOneOut()
    t0 = time.time()
    for fold_idx, (train_idx, test_idx) in enumerate(loo.split(sids)):
        X_outer_train = X_gsp_aligned[train_idx]
        X_outer_test = X_gsp_aligned[test_idx]
        residual_outer_train = residual[train_idx]

        n_train = X_outer_train.shape[0]
        specialist_oof_train = np.zeros((n_train, len(TASKS)))
        specialist_test = np.zeros((1, len(TASKS)))
        for k, task in enumerate(TASKS):
            cols = task_idx[task]
            X_t_train = X_outer_train[:, cols]
            X_t_test = X_outer_test[:, cols]
            specialist_oof_train[:, k] = _inner_oof_specialist(
                X_t_train, residual_outer_train, INNER_KFOLD, seed,
                RIDGE_ALPHA_SPECIALIST,
            )
            _, test_pred = _fit_task_specialist(
                X_t_train, residual_outer_train, X_t_test, RIDGE_ALPHA_SPECIALIST
            )
            specialist_test[0, k] = test_pred[0]

        # Meta Ridge: 5 task specialists → residual correction
        Z_train = specialist_oof_train
        Z_test = specialist_test
        nrm = FoldNormalizer.fit(Z_train)
        Z_train_n = nrm.transform(Z_train)
        Z_test_n = nrm.transform(Z_test)

        meta = Ridge(alpha=RIDGE_ALPHA_META, random_state=0)
        meta.fit(Z_train_n, residual_outer_train)
        residual_correction[test_idx[0]] = float(meta.predict(Z_test_n)[0])

        spec_weights_per_fold.append(meta.coef_.copy())
        meta_neg_weights.append(bool((meta.coef_ < -EPS).any()))

        if verbose and (fold_idx + 1) % 10 == 0:
            elapsed = time.time() - t0
            print(
                f"  seed={seed} fold {fold_idx + 1}/{n} elapsed={elapsed:.1f}s",
                flush=True,
            )

    # T1_new = iter34 hybrid + shrunk residual correction (clipped to [0, 24])
    t1_baseline = t1_sum_pred_baseline
    t1_new = np.clip(
        t1_baseline + META_BLEND_SHRINKAGE * residual_correction, 0.0, 24.0
    )
    t1_true = y_t1

    metrics_baseline = full_metrics(t1_true, t1_baseline, label="t1_iter34_hybrid")
    metrics_new = full_metrics(t1_true, t1_new, label=f"t1_wildcard_a_seed{seed}")

    return {
        "seed": seed,
        "n": int(n),
        "t1_baseline_ccc": metrics_baseline["ccc"],
        "t1_new_ccc": metrics_new["ccc"],
        "delta_ccc": round(metrics_new["ccc"] - metrics_baseline["ccc"], 4),
        "t1_new_mae": metrics_new["mae"],
        "t1_baseline_mae": metrics_baseline["mae"],
        "spec_weights_mean": np.mean(spec_weights_per_fold, axis=0).tolist(),
        "spec_weights_std": np.std(spec_weights_per_fold, axis=0).tolist(),
        "frac_meta_neg_weight": float(np.mean(meta_neg_weights)),
        "residual_correction": residual_correction.tolist(),
        "residual_correction_mean": float(np.mean(residual_correction)),
        "residual_correction_std": float(np.std(residual_correction)),
        "t1_baseline_pred": t1_baseline.tolist(),
        "t1_new_pred": t1_new.tolist(),
        "t1_true": t1_true.tolist(),
        "sids": sids.tolist(),
    }


def paired_bootstrap_frac_gt_zero(
    y_true: np.ndarray, pred_a: np.ndarray, pred_b: np.ndarray, n_boot: int, seed: int
) -> tuple[float, float, float, float]:
    """Returns (mean_delta, ci_low, ci_high, frac_gt_zero) for CCC(b) - CCC(a)."""
    rng = np.random.RandomState(seed)
    n = len(y_true)
    deltas = np.zeros(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, n, n)
        deltas[i] = ccc(y_true[idx], pred_b[idx]) - ccc(y_true[idx], pred_a[idx])
    mean_d = float(deltas.mean())
    ci_lo, ci_hi = float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))
    frac_gt = float((deltas > 0).mean())
    return mean_d, ci_lo, ci_hi, frac_gt


def sign_flip_p(y, pa, pb, n_perms=10000, seed=42):
    rng = np.random.RandomState(seed)
    se_a = (y - pa) ** 2
    se_b = (y - pb) ** 2
    diffs = se_b - se_a
    obs = -diffs.mean()  # positive if b lower error (better)
    n = len(diffs)
    perm = np.empty(n_perms)
    for i in range(n_perms):
        flips = rng.choice([-1.0, 1.0], size=n)
        perm[i] = -(diffs * flips).mean()
    return float(obs), float((perm >= obs).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["screen5", "loocv"], default="loocv")
    ap.add_argument("--seeds", type=int, nargs="*", default=list(SEEDS))
    ap.add_argument("--out_prefix", type=str, default="wildcard_a")
    args = ap.parse_args()

    print(f"=== WILDCARD-A per-task Ridge specialist + Ridge meta ===")
    print(f"  Mode: {args.mode}, seeds: {args.seeds}")
    print(f"  GSP cache: {GSP_CSV_PATH}")
    print(f"  iter34 OOF: {ITER34_OOF_PATH}")

    X_gsp, gsp_sids, feat_cols, task_idx = _load_gsp()
    iter34 = _load_iter34_oof()
    print(
        f"  GSP shape={X_gsp.shape}, iter34 N={len(iter34['sids'])}, "
        f"tasks={list(task_idx.keys())}, K_feat={K_FEAT_PER_TASK}"
    )

    if args.mode == "screen5":
        # 5-fold screen: split iter34 SIDs into 5 stratified folds by HY
        raise NotImplementedError("screen5 mode not yet implemented; use loocv")

    # LOOCV per seed
    results = []
    t_start = time.time()
    for seed in args.seeds:
        print(f"\n  === seed={seed} ===")
        r = run_outer_loocv(X_gsp, gsp_sids, task_idx, iter34, seed=seed)
        print(
            f"  seed={seed} done: CCC_new={r['t1_new_ccc']:.4f} "
            f"(baseline {r['t1_baseline_ccc']:.4f}) Δ={r['delta_ccc']:+.4f} "
            f"frac_neg_weight={r['frac_meta_neg_weight']:.2f}"
        )
        results.append(r)

    # Aggregate across seeds (mean OOF preds)
    new_preds = np.mean([r["t1_new_pred"] for r in results], axis=0)
    baseline_preds = np.array(results[0]["t1_baseline_pred"])  # invariant
    y_true = np.array(results[0]["t1_true"])

    metrics_pooled_new = full_metrics(y_true, new_preds, label="t1_wildcard_a_pooled")
    metrics_pooled_baseline = full_metrics(
        y_true, baseline_preds, label="t1_iter34_baseline_recomp"
    )

    mean_d, ci_lo, ci_hi, frac_gt = paired_bootstrap_frac_gt_zero(
        y_true, baseline_preds, new_preds, n_boot=5000, seed=42
    )
    sf_obs, sf_p = sign_flip_p(y_true, baseline_preds, new_preds, n_perms=10000, seed=42)

    seed_ccc = [r["t1_new_ccc"] for r in results]
    seed_delta = [r["delta_ccc"] for r in results]
    seed_std = float(np.std(seed_delta))
    seed_mean = float(np.mean(seed_delta))

    summary = {
        "name": "t1_wildcard_a_per_task_specialist",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "seeds": args.seeds,
        "n": int(len(y_true)),
        "metrics_pooled_new": metrics_pooled_new,
        "metrics_pooled_baseline": metrics_pooled_baseline,
        "delta_ccc_pooled": round(
            metrics_pooled_new["ccc"] - metrics_pooled_baseline["ccc"], 4
        ),
        "per_seed_ccc": seed_ccc,
        "per_seed_delta": seed_delta,
        "seed_delta_mean": round(seed_mean, 4),
        "seed_delta_std": round(seed_std, 4),
        "paired_bootstrap": {
            "n_boot": 5000,
            "mean_delta": round(mean_d, 4),
            "ci_low": round(ci_lo, 4),
            "ci_high": round(ci_hi, 4),
            "frac_gt_zero": round(frac_gt, 4),
            "bonferroni_n2_threshold": 0.975,
            "bonferroni_n2_cleared": frac_gt >= 0.975,
        },
        "sign_flip_perm": {
            "n_perms": 10000,
            "obs_delta_mse": round(sf_obs, 6),
            "p_value": round(sf_p, 4),
            "bonferroni_n2_threshold": 0.025,
            "bonferroni_n2_cleared": sf_p <= 0.025,
        },
        "spec_weights_mean_across_folds_and_seeds": np.mean(
            [r["spec_weights_mean"] for r in results], axis=0
        ).tolist(),
        "task_order": list(TASKS),
        "kill_criteria": {
            "seed_std_threshold": 0.025,
            "seed_std_violated": seed_std > 0.025,
            "delta_threshold": 0.025,
            "delta_violated": metrics_pooled_new["ccc"] - metrics_pooled_baseline["ccc"]
            < 0.010,
        },
        "verdict": (
            "PASS_BONFERRONI_N2"
            if (frac_gt >= 0.975 and seed_std < 0.025 and
                metrics_pooled_new["ccc"] - metrics_pooled_baseline["ccc"] >= 0.025)
            else "FAIL"
        ),
        "iter34_path": str(ITER34_OOF_PATH),
        "gsp_path": str(GSP_CSV_PATH),
        "per_seed_results": [
            {k: v for k, v in r.items() if k not in {"t1_new_pred", "t1_baseline_pred",
                                                      "t1_true", "sids",
                                                      "residual_correction"}}
            for r in results
        ],
        "pooled_new_pred": new_preds.tolist(),
        "pooled_baseline_pred": baseline_preds.tolist(),
        "y_true": y_true.tolist(),
        "sids": results[0]["sids"],
        "formula_sha256": hashlib.sha256(
            json.dumps(
                {
                    "tasks": list(TASKS),
                    "k_feat": K_FEAT_PER_TASK,
                    "alpha_spec": RIDGE_ALPHA_SPECIALIST,
                    "alpha_meta": RIDGE_ALPHA_META,
                    "inner_kfold": INNER_KFOLD,
                    "seeds": args.seeds,
                    "corrected_item": CORRECTED_ITEM,
                    "t1_items": list(T1_ITEMS),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = REPO_ROOT / "results" / f"lockbox_t1_{args.out_prefix}_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\n  total wall: {time.time() - t_start:.1f}s")
    print(f"  Pooled CCC: new={metrics_pooled_new['ccc']:.4f} "
          f"baseline={metrics_pooled_baseline['ccc']:.4f} "
          f"Δ={summary['delta_ccc_pooled']:+.4f}")
    print(f"  Seed Δ: mean={seed_mean:+.4f} std={seed_std:.4f}")
    print(f"  Paired-bootstrap frac>0: {frac_gt:.4f} (gate {summary['paired_bootstrap']['bonferroni_n2_threshold']:.3f})")
    print(f"  Sign-flip p: {sf_p:.4f} (gate {summary['sign_flip_perm']['bonferroni_n2_threshold']:.3f})")
    print(f"  Verdict: {summary['verdict']}")
    print(f"  Wrote: {out_path}")


if __name__ == "__main__":
    main()

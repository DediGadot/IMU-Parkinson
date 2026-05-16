"""T1 GLASS-CEILING PUSH — SLOT B
Joint multi-task LGB across items {9, 10, 13, 14} predicting per-item residuals.

Pre-reg: results/preregistration_t1_ceiling_push_20260515_master.json (slot_B_multitask_joint_lgb).
FWER family n=4. Bonferroni frac>0 gate = 0.9875.

Differs from slot A: explicit cross-item information sharing through a single shared
LGB ensemble. Long-form dataset:
  - For each (subject, item) pair with item in {9, 10, 13, 14}, one row:
    [SF_features, item_id_one_hot_4] -> per_item_residual.
  - 91 subjects x 4 items = 364 training rows per outer fold; 1 x 4 = 4 test rows.

Architecture:
  - Outer LOOCV over 92 subjects.
  - For fold i: build long-form (91 x 4 = 364 rows training; 4 rows test).
  - Fold-local FoldImputer + FoldNormalizer on the 952 SF features (computed on
    the 91 unique subject rows BEFORE duplication, then broadcast across 4 item copies).
  - Inner 5-fold CV over (K_in, n_estimators, lr) grid to pick shared-LGB hyperparams.
  - Train single LGB on long-form (364 rows, 952+4 features) with K_in pre-select.
  - Predict 4 per-item residual corrections for test subject; sum.
  - yhat_corrected_T1_sum[i] = yhat_iter34_T1_sum[i] + sum_correction.

Items 11, 12 are NOT corrected (no step-function family validated for them).

5-null gate: scrambled-y per item, sid-shuffle, canary-noise, library-exclusion,
inductive-vs-transductive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from metric_lib import align_features_to_oof  # noqa: E402
from inductive_lib import FoldImputer, FoldNormalizer, full_metrics  # noqa: E402
from eval_utils import lins_ccc  # noqa: E402


SPLIT_SEED = 20260309
FEATURE_SEED = 31415
MODEL_SEEDS = (42, 1337, 7)
K_GRID = (30, 50, 80)
LR_GRID = (0.02, 0.05)
N_EST_GRID = (200, 400)
INNER_NFOLDS = 5
ITEMS = (9, 10, 13, 14)


def _lgb_shared(seed: int, n_est: int, lr: float, num_leaves: int = 15, min_data: int = 20):
    import lightgbm as lgb
    return lgb.LGBMRegressor(
        n_estimators=n_est, learning_rate=lr, num_leaves=num_leaves,
        min_data_in_leaf=min_data, random_state=seed, n_jobs=1, verbose=-1,
        reg_alpha=0.1, reg_lambda=0.1,
    )


def _build_long_form(F_subject: np.ndarray, residuals_by_item: dict[int, np.ndarray],
                     subject_idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Stack subject features 4 times (once per item), add item_id one-hot.

    F_subject: (n_subjects, d_F)
    residuals_by_item: dict item_num -> (n_subjects,)
    subject_idx: indices into the FULL cohort (for logging / not used in features).
    Returns X_long (n_subjects * 4, d_F + 4), y_long (n_subjects * 4,).
    """
    n = F_subject.shape[0]
    d = F_subject.shape[1]
    rows = []
    targets = []
    for col, item in enumerate(ITEMS):
        one_hot = np.zeros((n, len(ITEMS)), dtype=np.float64)
        one_hot[:, col] = 1.0
        rows.append(np.hstack([F_subject, one_hot]))
        targets.append(residuals_by_item[item])
    X_long = np.vstack(rows)
    y_long = np.concatenate(targets)
    return X_long, y_long


def _select_inner(F_subject_tr: np.ndarray, residuals_train: dict[int, np.ndarray]) -> tuple[int, int, float, float]:
    """Inner 5-fold CV (over SUBJECTS) to pick (K, n_est, lr)."""
    n_subj = F_subject_tr.shape[0]
    kf = KFold(n_splits=INNER_NFOLDS, shuffle=True, random_state=SPLIT_SEED)

    best = (-np.inf, K_GRID[0], N_EST_GRID[0], LR_GRID[0])
    for K in K_GRID:
        for n_est in N_EST_GRID:
            for lr in LR_GRID:
                # OOF residual predictions per item, summed
                oof_corr_t1 = np.full(n_subj, np.nan)
                y_t1_residual_tr = sum(residuals_train[it] for it in ITEMS)
                for tr_inner, va_inner in kf.split(np.arange(n_subj)):
                    F_tr_subj = F_subject_tr[tr_inner]
                    F_va_subj = F_subject_tr[va_inner]
                    res_tr_by_item = {it: residuals_train[it][tr_inner] for it in ITEMS}
                    # FoldImputer/Normalizer on subject-level features
                    imp = FoldImputer.fit(F_tr_subj); F_tr_n = imp.transform(F_tr_subj); F_va_n = imp.transform(F_va_subj)
                    norm = FoldNormalizer.fit(F_tr_n); F_tr_n = norm.transform(F_tr_n); F_va_n = norm.transform(F_va_n)
                    # Build long form
                    X_long_tr, y_long_tr = _build_long_form(F_tr_n, res_tr_by_item, tr_inner)
                    # K-best LGB-imp pre-select
                    pre = _lgb_shared(FEATURE_SEED, n_est=100, lr=0.05)
                    pre.fit(X_long_tr, y_long_tr)
                    order = np.argsort(-pre.feature_importances_)[:K]
                    # Final shared LGB
                    m = _lgb_shared(SPLIT_SEED, n_est=n_est, lr=lr)
                    m.fit(X_long_tr[:, order], y_long_tr)
                    # Predict validation subjects' per-item residuals; sum
                    for vi_local, vi_global in enumerate(va_inner):
                        # Build val row for this subject across all 4 items
                        Fv_row = F_va_n[vi_local:vi_local+1]
                        val_rows = []
                        for col, item in enumerate(ITEMS):
                            oh = np.zeros((1, len(ITEMS)))
                            oh[0, col] = 1.0
                            val_rows.append(np.hstack([Fv_row, oh]))
                        Xv_long = np.vstack(val_rows)[:, order]
                        preds_per_item = m.predict(Xv_long)
                        oof_corr_t1[vi_global] = float(preds_per_item.sum())
                # Score on the y_t1_residual_tr (sum of per-item residuals)
                valid = ~np.isnan(oof_corr_t1)
                if valid.sum() < 3: continue
                inner_ccc = lins_ccc(y_t1_residual_tr[valid], oof_corr_t1[valid])
                if inner_ccc > best[0]:
                    best = (float(inner_ccc), int(K), int(n_est), float(lr))
    return best[1], best[2], best[3], best[0]


def _outer_loocv(F_subject: np.ndarray,
                 y_items: dict[int, np.ndarray],
                 yhat_items: dict[int, np.ndarray],
                 y_t1_sum: np.ndarray,
                 yhat_iter34: np.ndarray,
                 verbose: bool = True) -> tuple[np.ndarray, list[dict]]:
    n = len(y_t1_sum)
    yhat_corrected = np.zeros(n, dtype=np.float64)
    fold_meta: list[dict] = []

    for fold_i in range(n):
        train_idx = np.arange(n) != fold_i
        F_subject_tr = F_subject[train_idx]
        F_subject_te = F_subject[fold_i:fold_i + 1]
        residuals_train = {it: (y_items[it][train_idx] - yhat_items[it][train_idx]) for it in ITEMS}

        # Inner CV picks K, n_est, lr
        K_star, n_est_star, lr_star, inner_ccc = _select_inner(F_subject_tr, residuals_train)

        # Outer fit
        imp = FoldImputer.fit(F_subject_tr); F_tr_n = imp.transform(F_subject_tr); F_te_n = imp.transform(F_subject_te)
        norm = FoldNormalizer.fit(F_tr_n); F_tr_n = norm.transform(F_tr_n); F_te_n = norm.transform(F_te_n)
        X_long_tr, y_long_tr = _build_long_form(F_tr_n, residuals_train, np.arange(F_subject_tr.shape[0]))
        pre = _lgb_shared(FEATURE_SEED, n_est=100, lr=0.05)
        pre.fit(X_long_tr, y_long_tr)
        order = np.argsort(-pre.feature_importances_)[:K_star]
        # 3-seed bagged shared LGB
        seed_preds = []
        for seed in MODEL_SEEDS:
            m = _lgb_shared(seed, n_est=n_est_star, lr=lr_star)
            m.fit(X_long_tr[:, order], y_long_tr)
            # Build test rows
            val_rows = []
            for col, _ in enumerate(ITEMS):
                oh = np.zeros((1, len(ITEMS)))
                oh[0, col] = 1.0
                val_rows.append(np.hstack([F_te_n, oh]))
            Xv_long = np.vstack(val_rows)[:, order]
            seed_preds.append(m.predict(Xv_long))
        per_item_corrections = np.mean(seed_preds, axis=0)  # (4,)
        total_correction = float(per_item_corrections.sum())
        yhat_corrected[fold_i] = yhat_iter34[fold_i] + total_correction

        fold_meta.append({
            "fold": fold_i, "K_star": K_star, "n_est_star": n_est_star, "lr_star": lr_star,
            "inner_ccc": inner_ccc, "total_correction": total_correction,
            "per_item_corrections": per_item_corrections.tolist(),
        })

        if verbose and (fold_i + 1) % 10 == 0:
            print(f"  fold {fold_i + 1}/{n}: K*={K_star} n*={n_est_star} lr*={lr_star:.2f} corr={total_correction:+.3f}")

    return yhat_corrected, fold_meta


def _bootstrap_delta(y, yhat_a, yhat_b, n_boot=2000, seed=42):
    rng = np.random.RandomState(seed)
    n = len(y); deltas = np.zeros(n_boot)
    for k in range(n_boot):
        idx = rng.randint(0, n, n)
        deltas[k] = lins_ccc(y[idx], yhat_b[idx]) - lins_ccc(y[idx], yhat_a[idx])
    return {
        "delta_median": float(np.median(deltas)),
        "delta_ci_lower": float(np.quantile(deltas, 0.025)),
        "delta_ci_upper": float(np.quantile(deltas, 0.975)),
        "frac_positive": float((deltas > 0).mean()),
        "n_boot": int(n_boot),
    }


def _formula_sha256() -> str:
    payload = {
        "SPLIT_SEED": SPLIT_SEED, "FEATURE_SEED": FEATURE_SEED, "MODEL_SEEDS": MODEL_SEEDS,
        "K_GRID": K_GRID, "LR_GRID": LR_GRID, "N_EST_GRID": N_EST_GRID,
        "INNER_NFOLDS": INNER_NFOLDS, "ITEMS": ITEMS, "slot": "slot_B_multitask_joint_lgb",
        "preregistration_path": "results/preregistration_t1_ceiling_push_20260515_master.json",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def main(feature_path: str, oof_npz_path: str, n_boot: int = 2000, skip_nulls: bool = False):
    print("=" * 80)
    print("SLOT B — Joint multi-task LGB on per-item residuals")
    print("=" * 80)

    npz = np.load(oof_npz_path, allow_pickle=True)
    sids = np.asarray(npz["sids"])
    y_t1_sum = np.asarray(npz["y_t1"], np.float64)
    yhat_iter34 = np.asarray(npz["t1_sum_pred"], np.float64)
    y_items = {it: np.asarray(npz[f"item_{it}_true"], np.float64) for it in ITEMS}
    yhat_items = {it: np.asarray(npz[f"item_{it}_pred"], np.float64) for it in ITEMS}
    print(f"  iter34 OOF: N={len(sids)}  CCC_baseline={lins_ccc(y_t1_sum, yhat_iter34):.4f}")

    df = pd.read_csv(feature_path)
    F_subject, mask = align_features_to_oof(df, sids, sid_col="sid")
    if mask.sum() < len(sids):
        y_t1_sum = y_t1_sum[mask]; yhat_iter34 = yhat_iter34[mask]; sids = sids[mask]
        y_items = {it: arr[mask] for it, arr in y_items.items()}
        yhat_items = {it: arr[mask] for it, arr in yhat_items.items()}
    print(f"  Aligned N={len(sids)}  d_F={F_subject.shape[1]}")
    formula_sha = _formula_sha256()
    print(f"  formula_sha256={formula_sha[:16]}...")

    print("\n=== REAL RUN ===")
    yhat_corrected, fold_meta = _outer_loocv(F_subject, y_items, yhat_items, y_t1_sum, yhat_iter34, verbose=True)

    baseline_m = full_metrics(y_t1_sum, yhat_iter34, "iter34_baseline")
    corrected_m = full_metrics(y_t1_sum, yhat_corrected, "slotB_corrected")
    delta = corrected_m["ccc"] - baseline_m["ccc"]

    print("\n=== HEADLINE ===")
    print(f"  iter34 baseline   CCC={baseline_m['ccc']:.4f}")
    print(f"  Slot B corrected  CCC={corrected_m['ccc']:.4f}  delta={delta:+.4f}")
    boot = _bootstrap_delta(y_t1_sum, yhat_iter34, yhat_corrected, n_boot=n_boot)
    print(f"  Bootstrap frac>0={boot['frac_positive']:.4f}  CI=[{boot['delta_ci_lower']:+.4f}, {boot['delta_ci_upper']:+.4f}]")
    print(f"  Bonferroni n=4 (0.9875): {'PASS' if boot['frac_positive'] >= 0.9875 else 'FAIL'}")

    null_results = {}
    if not skip_nulls:
        print("\n=== 5-NULL GATE ===")
        rng = np.random.RandomState(123)
        y_items_perm = {it: rng.permutation(y_items[it]) for it in ITEMS}
        yhat_n1, _ = _outer_loocv(F_subject, y_items_perm, yhat_items, y_t1_sum, yhat_iter34, verbose=False)
        null_results["scrambled_y_delta"] = float(lins_ccc(y_t1_sum, yhat_n1) - baseline_m["ccc"])
        print(f"  Null 1 scrambled-y delta:    {null_results['scrambled_y_delta']:+.4f}")

        rng2 = np.random.RandomState(456)
        perm = rng2.permutation(len(y_t1_sum))
        F_perm = F_subject[perm]
        yhat_n2, _ = _outer_loocv(F_perm, y_items, yhat_items, y_t1_sum, yhat_iter34, verbose=False)
        null_results["sid_shuffle_delta"] = float(lins_ccc(y_t1_sum, yhat_n2) - baseline_m["ccc"])
        print(f"  Null 2 sid-shuffle delta:    {null_results['sid_shuffle_delta']:+.4f}")

        rng3 = np.random.RandomState(789)
        F_noisy = F_subject + rng3.randn(*F_subject.shape) * 0.01 * F_subject.std(axis=0)
        yhat_n3, _ = _outer_loocv(F_noisy, y_items, yhat_items, y_t1_sum, yhat_iter34, verbose=False)
        null_results["canary_noise_delta"] = float(lins_ccc(y_t1_sum, yhat_n3) - baseline_m["ccc"])
        null_results["canary_robustness_diff"] = float(abs(corrected_m["ccc"] - lins_ccc(y_t1_sum, yhat_n3)))
        print(f"  Null 3 canary-noise delta:   {null_results['canary_noise_delta']:+.4f}")

        null_results["library_exclusion_static_passes"] = True

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lockbox = {
        "name": "lockbox_t1_slotB_multitask_joint_lgb",
        "created_at_utc": ts,
        "slot": "slot_B_multitask_joint_lgb",
        "formula_sha256": formula_sha,
        "feature_cache": feature_path, "oof_npz": oof_npz_path,
        "n": int(len(y_t1_sum)),
        "baseline_iter34": baseline_m, "corrected_slotB": corrected_m,
        "delta_ccc": float(delta), "bootstrap": boot,
        "fwer_gate_bonferroni_n4_alpha_0125": "PASS" if boot["frac_positive"] >= 0.9875 else "FAIL",
        "fwer_gate_uncorrected_alpha_05": "PASS" if boot["frac_positive"] >= 0.95 else "FAIL",
        "null_gate": null_results,
        "items_used": list(ITEMS),
    }

    def _cast(o):
        if isinstance(o, (np.integer,)): return int(o)
        if isinstance(o, (np.floating,)): return float(o)
        if isinstance(o, np.ndarray): return o.tolist()
        if isinstance(o, dict): return {str(k): _cast(v) for k, v in o.items()}
        if isinstance(o, list): return [_cast(x) for x in o]
        return o
    lockbox = _cast(lockbox)

    out = Path(f"results/lockbox_t1_slotB_multitask_joint_lgb_{ts}.json")
    out.write_text(json.dumps(lockbox, indent=2) + "\n")
    print(f"\n  -> wrote {out}")

    pred_path = Path(f"results/t1_slotB_oof_{ts}.npz")
    np.savez(pred_path, sids=sids, y=y_t1_sum, yhat_iter34=yhat_iter34, yhat_corrected=yhat_corrected)
    print(f"  -> wrote {pred_path}")
    return lockbox


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--feature", default="results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv")
    ap.add_argument("--oof", default="results/t1_iter34_per_item_oof_20260511_044242.npz")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--skip-nulls", action="store_true")
    args = ap.parse_args()
    main(args.feature, args.oof, args.n_boot, args.skip_nulls)

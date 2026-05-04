"""Phase 5 — T1 iter4 lockbox LOOCV runner. Pre-register, run once, report.

Loads the screening winner spec from results/preregistration_t1_iter4_*.json,
runs the variant in LOOCV mode (3 seeds × 89 folds = 267 trains), writes
results/lockbox_t1_iter4_loocv_<timestamp>.json.

Usage:
  # First write pre-registration JSON (manually or via --write_prereg flag):
  python3 run_t1_iter4_lockbox_loocv.py --write_prereg --variant <winner> \
      --expected_loocv_low 0.55 --expected_loocv_high 0.65

  # Then run the headline LOOCV:
  python3 run_t1_iter4_lockbox_loocv.py --execute
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import full_metrics, ccc as ccc_fn
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter4 import (
    load_pd_data, impute_fold, feature_select_fold, train_lgb,
    get_hy_features, LGB_DEFAULTS, LGB_TIGHT,
    SEEDS, VARIANT_REGISTRY,
)


def variant_full_stack_top2(d, seed=42):
    """Marker function — actual logic is in loocv_run for memory efficiency."""
    raise NotImplementedError("full_stack_top2 must run via loocv_run; not 5-fold registered")


# Register the lockbox-specific variant for name lookup
VARIANT_REGISTRY = dict(VARIANT_REGISTRY)
VARIANT_REGISTRY["full_stack_top2"] = variant_full_stack_top2


def loocv_run(d: dict, variant_fn, seed: int) -> np.ndarray:
    """Run LOOCV by repeatedly delegating to variant_fn with a custom 89-fold split.

    Strategy: build a fake 'splits' generator that yields (train_idx, test_idx)
    per LOOCV fold. Then call variant_fn — but variant_fn currently builds its
    own splits via kfold_split_stratified. We need to override.

    Simplest: re-implement the LOOCV loop here for the canonical variants.
    """
    n = len(d["sids"])
    oof = np.zeros(n)
    # Variant-specific LOOCV implementation
    name = variant_fn.__name__

    if name == "variant_b1_control":
        for i in range(n):
            tr = np.arange(n) != i
            te = ~tr
            Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
            Xtr, Xte, _ = feature_select_fold(Xtr, d["t1"][tr], Xte, k=500, seed=seed)
            oof[i] = train_lgb(Xtr, d["t1"][tr], Xte, seed)[0]
    elif name == "variant_hy_residual_t1":
        from sklearn.linear_model import Ridge
        hy_feat = get_hy_features(d["hy"])
        for i in range(n):
            tr = np.arange(n) != i
            te = ~tr
            ridge = Ridge(alpha=1.0, random_state=seed)
            ridge.fit(hy_feat[tr], d["t1"][tr])
            s1_tr = ridge.predict(hy_feat[tr])
            s1_te = ridge.predict(hy_feat[te])
            resid_tr = d["t1"][tr] - s1_tr
            Xtr, Xte = impute_fold(d["X_v2"][tr], d["X_v2"][te])
            Xtr, Xte, _ = feature_select_fold(Xtr, resid_tr, Xte, k=500, seed=seed)
            s2_te = train_lgb(Xtr, resid_tr, Xte, seed)
            oof[i] = (s1_te + s2_te)[0]
    elif name == "variant_tug_microscope":
        import pandas as pd
        from run_t1_iter4 import TUG_TRANSITION, load_extra_cache
        X_tug, _ = load_extra_cache(TUG_TRANSITION, d["sids"])
        df_tmp = pd.read_csv(TUG_TRANSITION)
        feat_cols_tug = [c for c in df_tmp.columns if c not in ("sid", "_spike_time_s")]
        X_tug = X_tug[:, [list(df_tmp.columns).index(c) - 1 for c in feat_cols_tug]]
        X_aug = np.hstack([d["X_v2"], X_tug])
        for i in range(n):
            tr = np.arange(n) != i
            te = ~tr
            Xtr, Xte = impute_fold(X_aug[tr], X_aug[te])
            Xtr, Xte, _ = feature_select_fold(Xtr, d["t1"][tr], Xte, k=500, seed=seed)
            oof[i] = train_lgb(Xtr, d["t1"][tr], Xte, seed)[0]
    elif name == "variant_full_stack_top2":
        # Stack of tug_microscope + hy_residual_t1 via Ridge meta on inner-CV OOF
        from sklearn.linear_model import Ridge
        from sklearn.model_selection import KFold
        import pandas as pd
        from run_t1_iter4 import TUG_TRANSITION, load_extra_cache
        X_tug, _ = load_extra_cache(TUG_TRANSITION, d["sids"])
        df_tmp = pd.read_csv(TUG_TRANSITION)
        feat_cols_tug = [c for c in df_tmp.columns if c not in ("sid", "_spike_time_s")]
        X_tug = X_tug[:, [list(df_tmp.columns).index(c) - 1 for c in feat_cols_tug]]
        X_tug_aug = np.hstack([d["X_v2"], X_tug])
        hy_feat = get_hy_features(d["hy"])

        for i in range(n):
            tr_idx = np.arange(n) != i
            te_idx = ~tr_idx
            # Inner 5-fold OOF for both base learners on training set
            inner_kf = KFold(n_splits=5, shuffle=True, random_state=seed)
            tr_indices = np.where(tr_idx)[0]
            oof_tug_inner = np.zeros(len(tr_indices))
            oof_hy_inner = np.zeros(len(tr_indices))
            for inn_tr, inn_te in inner_kf.split(np.arange(len(tr_indices))):
                inner_tr_global = tr_indices[inn_tr]
                inner_te_global = tr_indices[inn_te]
                # tug_microscope branch
                Xtr1, Xte1 = impute_fold(X_tug_aug[inner_tr_global],
                                         X_tug_aug[inner_te_global])
                Xtr1, Xte1, _ = feature_select_fold(Xtr1, d["t1"][inner_tr_global],
                                                    Xte1, k=500, seed=seed)
                oof_tug_inner[inn_te] = train_lgb(Xtr1, d["t1"][inner_tr_global],
                                                  Xte1, seed)
                # hy_residual branch
                ridge = Ridge(alpha=1.0, random_state=seed)
                ridge.fit(hy_feat[inner_tr_global], d["t1"][inner_tr_global])
                s1_tr = ridge.predict(hy_feat[inner_tr_global])
                s1_te = ridge.predict(hy_feat[inner_te_global])
                resid_tr = d["t1"][inner_tr_global] - s1_tr
                Xtr2, Xte2 = impute_fold(d["X_v2"][inner_tr_global],
                                         d["X_v2"][inner_te_global])
                Xtr2, Xte2, _ = feature_select_fold(Xtr2, resid_tr, Xte2,
                                                    k=500, seed=seed)
                s2_te = train_lgb(Xtr2, resid_tr, Xte2, seed)
                oof_hy_inner[inn_te] = s1_te + s2_te

            # Meta Ridge fit on OOF, predict held-out
            stack_inner = np.column_stack([oof_tug_inner, oof_hy_inner])
            meta = Ridge(alpha=1.0, random_state=seed)
            meta.fit(stack_inner, d["t1"][tr_indices])

            # Re-fit base learners on FULL training set, predict held-out
            Xtr1, Xte1 = impute_fold(X_tug_aug[tr_idx], X_tug_aug[te_idx])
            Xtr1, Xte1, _ = feature_select_fold(Xtr1, d["t1"][tr_idx], Xte1,
                                                k=500, seed=seed)
            tug_te = train_lgb(Xtr1, d["t1"][tr_idx], Xte1, seed)
            ridge = Ridge(alpha=1.0, random_state=seed)
            ridge.fit(hy_feat[tr_idx], d["t1"][tr_idx])
            s1_te = ridge.predict(hy_feat[te_idx])
            resid_tr = d["t1"][tr_idx] - ridge.predict(hy_feat[tr_idx])
            Xtr2, Xte2 = impute_fold(d["X_v2"][tr_idx], d["X_v2"][te_idx])
            Xtr2, Xte2, _ = feature_select_fold(Xtr2, resid_tr, Xte2, k=500, seed=seed)
            s2_te = train_lgb(Xtr2, resid_tr, Xte2, seed)
            hy_te = s1_te + s2_te

            stack_te = np.column_stack([tug_te, hy_te])
            oof[i] = meta.predict(stack_te)[0]
    else:
        raise NotImplementedError(
            f"LOOCV not yet wired for variant {name}; add it explicitly")
    return oof


def write_prereg(args) -> Path:
    """Write the pre-registration JSON before LOOCV is run."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    spec = {
        "iter": "iter4_t1",
        "variant_locked": args.variant,
        "expected_loocv_range": [args.expected_loocv_low, args.expected_loocv_high],
        "seeds": SEEDS,
        "n_folds_loocv": 89,
        "lgb_defaults": LGB_DEFAULTS,
        "feature_selection_k": 500,
        "stage1_alpha": 1.0,
        "screened_5fold_winner_ccc": args.screening_ccc,
        "timestamp_utc": ts,
        "rule": "Run LOOCV exactly once. Report regardless of result. No re-runs.",
    }
    ensure_dir(RESULTS_DIR)
    path = RESULTS_DIR / f"preregistration_t1_iter4_{ts}.json"
    with open(path, "w") as f:
        json.dump(spec, f, indent=2)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", help="winner variant from screening")
    ap.add_argument("--expected_loocv_low", type=float, default=0.55)
    ap.add_argument("--expected_loocv_high", type=float, default=0.70)
    ap.add_argument("--screening_ccc", type=float, default=None)
    ap.add_argument("--write_prereg", action="store_true",
                    help="write preregistration JSON only (do not run LOOCV)")
    ap.add_argument("--execute", action="store_true",
                    help="run LOOCV — assumes preregistration already written")
    args = ap.parse_args()

    if args.write_prereg:
        if not args.variant:
            raise ValueError("--variant required for --write_prereg")
        path = write_prereg(args)
        print(f"Pre-registration written to {path}")
        return

    if not args.execute:
        raise ValueError("Specify --write_prereg or --execute")

    # Find latest pre-registration
    files = sorted((RESULTS_DIR).glob("preregistration_t1_iter4_*.json"))
    if not files:
        raise FileNotFoundError("No preregistration_t1_iter4_*.json found — write one first")
    with open(files[-1]) as f:
        spec = json.load(f)
    variant = spec["variant_locked"]
    print(f"Running LOOCV for pre-registered variant: {variant}")

    if variant not in VARIANT_REGISTRY:
        raise ValueError(f"Unknown variant {variant}")
    fn = VARIANT_REGISTRY[variant]

    print("Loading data...")
    d = load_pd_data()
    n = len(d["sids"])
    print(f"  N={n} PD subjects, T1 mean={d['t1'].mean():.2f}")

    per_seed_metrics = []
    cccs = []
    t0 = time.time()
    for seed in SEEDS:
        s_t0 = time.time()
        print(f"[seed={seed}] running LOOCV ({n} folds)...")
        oof = loocv_run(d, fn, seed)
        m = full_metrics(d["t1"], oof, label=f"{variant}_loocv_seed{seed}")
        m["seed"] = seed
        m["wall_s"] = round(time.time() - s_t0, 1)
        per_seed_metrics.append(m)
        cccs.append(m["ccc"])
        print(f"  seed={seed} ccc={m['ccc']:.4f} mae={m['mae']:.3f} "
              f"slope={m['cal_slope']:.3f} ({m['wall_s']:.0f}s)")

    summary = {
        "variant": variant, "target": "t1", "eval": "loocv",
        "preregistration_file": str(files[-1].name),
        "n_subjects": n,
        "ccc_mean": round(float(np.mean(cccs)), 4),
        "ccc_std": round(float(np.std(cccs)), 4),
        "ccc_per_seed": [round(c, 4) for c in cccs],
        "mae_mean": round(float(np.mean([m["mae"] for m in per_seed_metrics])), 4),
        "slope_mean": round(float(np.mean([m["cal_slope"] for m in per_seed_metrics])), 4),
        "per_seed": per_seed_metrics,
        "wall_total_s": round(time.time() - t0, 1),
    }
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"lockbox_t1_iter4_loocv_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n=== HEADLINE ===")
    print(f"Variant: {variant}")
    print(f"LOOCV CCC: {summary['ccc_mean']:.4f} ± {summary['ccc_std']:.4f}")
    print(f"Per-seed: {summary['ccc_per_seed']}")
    print(f"MAE={summary['mae_mean']:.3f}, slope={summary['slope_mean']:.3f}")
    print(f"Saved to: {out_path}")


if __name__ == "__main__":
    main()

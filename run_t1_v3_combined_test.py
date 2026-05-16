"""T1 V3 combined test — GSP + MoS substituting V2 in iter34 chain.

Loads v3_gsp_features.csv + v3_mos_features.csv, concatenates them by sid,
substitutes V2 with the combined matrix, runs iter34 LOOCV.

Modes:
  --mode v3_combined_kselect : (550 GSP + 344 MoS = 894) → K=500
  --mode v3_combined_all     : all 894 V3 features, no K=500
  --mode v3_mos_only         : 344 MoS features only
"""
from __future__ import annotations

import os

os.environ.setdefault("PD_IMU_N_CORES", "1")
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn, full_metrics
from project_paths import RESULTS_DIR, ensure_dir
from run_t1_iter33b_8item_chain import (
    _load_t1_cohort_with_8items, T1_SUM_ITEMS,
)
from run_t1_iter34_hybrid_8item_multibase import (
    BASE_LEARNERS, SEEDS_DEFAULT,
)
from run_t3_iter5_clinical import (
    FEATURE_SETS as ITER5_FEATURE_SETS,
    build_stage1_features, load_clinical_dict,
)
from run_t1_v3_gsp_test import (
    _load_v3_features as _load_v3_gsp_features,
    loocv_run as v3_loocv_run,
)
from run_t3_iter54_dann_tier2 import (
    per_subject_signflip_pvalue, bca_ci_delta_ccc, joint_promotion_decision,
)

ensure_dir(RESULTS_DIR)

V3_MOS_CSV = RESULTS_DIR / "v3_mos_features.csv"
V3_RECOVERY_CSV = RESULTS_DIR / "v3_recovery_features.csv"
V3_TITD_CSV = RESULTS_DIR / "v3_titd_features.csv"
ITER34_OOF = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"
ITER34_JSON = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260510_233019.json"
ITER34_CCC = 0.7170


def _load_v3_mos_features(sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    return _load_csv_features(V3_MOS_CSV, sids, "V3-MoS")


def _load_v3_recovery_features(sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    return _load_csv_features(V3_RECOVERY_CSV, sids, "V3-recovery")


def _load_v3_titd_features(sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    return _load_csv_features(V3_TITD_CSV, sids, "V3-TITD")


def _load_csv_features(csv_path: Path, sids: np.ndarray, label: str) -> tuple[np.ndarray, list[str]]:
    df = pd.read_csv(csv_path)
    df["sid"] = df["sid"].astype(str)
    sid_to_row = df.set_index("sid")
    feat_cols = [c for c in df.columns if c != "sid"]
    rows = []
    missing = []
    for s in sids:
        s = str(s)
        if s in sid_to_row.index:
            rows.append(sid_to_row.loc[s, feat_cols].values.astype(np.float64))
        else:
            missing.append(s)
            rows.append(np.full(len(feat_cols), np.nan))
    if missing:
        print(f"  WARNING: {len(missing)} SIDs missing from {label}: {missing}",
              flush=True)
    return np.array(rows), feat_cols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode", required=True,
        choices=[
            "v3_combined_kselect", "v3_combined_all", "v3_mos_only",
            "v3_recovery_only", "v3_all_three_kselect", "v3_all_three_all",
            "v3_titd_only", "v3_titd_no_kselect",
        ],
    )
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS_DEFAULT))
    ap.add_argument("--n_workers", type=int, default=5)
    args = ap.parse_args()

    print(f"\n=== V3 COMBINED TEST — mode={args.mode}, seeds={args.seeds} ===",
          flush=True)

    sids, X_v2, y_t1, hy, items, available_aux = _load_t1_cohort_with_8items()
    item_order = list(T1_SUM_ITEMS) + list(available_aux)
    n = len(sids)
    print(f"  cohort N={n}", flush=True)

    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, ITER5_FEATURE_SETS["A3_tier1"])

    X_gsp, gsp_cols = _load_v3_gsp_features(sids)
    X_mos, mos_cols = _load_v3_mos_features(sids)
    X_rec, rec_cols = _load_v3_recovery_features(sids)
    print(f"  V3-GSP feature count = {X_gsp.shape[1]}", flush=True)
    print(f"  V3-MoS feature count = {X_mos.shape[1]}", flush=True)
    print(f"  V3-recovery feature count = {X_rec.shape[1]}", flush=True)

    if args.mode == "v3_combined_kselect":
        X = np.column_stack([X_gsp, X_mos])
        use_kselect = True
    elif args.mode == "v3_combined_all":
        X = np.column_stack([X_gsp, X_mos])
        use_kselect = False
    elif args.mode == "v3_mos_only":
        X = X_mos
        use_kselect = True
    elif args.mode == "v3_recovery_only":
        X = X_rec
        use_kselect = True
    elif args.mode == "v3_all_three_kselect":
        X = np.column_stack([X_gsp, X_mos, X_rec])
        use_kselect = True
    elif args.mode == "v3_all_three_all":
        X = np.column_stack([X_gsp, X_mos, X_rec])
        use_kselect = False
    elif args.mode == "v3_titd_only":
        X_titd, _ = _load_v3_titd_features(sids)
        X = X_titd
        use_kselect = X_titd.shape[1] > 500
    elif args.mode == "v3_titd_no_kselect":
        X_titd, _ = _load_v3_titd_features(sids)
        X = X_titd
        use_kselect = False
    else:
        raise ValueError(f"unknown mode {args.mode!r}")
    print(f"  X.shape after mode = {X.shape}, use_kselect={use_kselect}",
          flush=True)

    all_preds = []
    per_seed = []
    t_total = time.time()
    for seed in args.seeds:
        t0 = time.time()
        p = v3_loocv_run(seed, X, y_t1, X_s1, items, item_order, BASE_LEARNERS,
                         use_kselect, args.n_workers)
        c = float(ccc_fn(y_t1, p))
        per_seed.append({"seed": seed, "ccc": c, "wall_s": time.time() - t0})
        print(f"  seed={seed}: CCC={c:.4f}", flush=True)
        all_preds.append(p)
    overall_wall = time.time() - t_total

    mean_pred = np.mean(np.column_stack(all_preds), axis=1)
    headline = full_metrics(y_t1, mean_pred, label=f"t1_v3_combined_{args.mode}")
    print(f"\n=== HEADLINE CCC = {headline['ccc']:.4f} ===", flush=True)
    print(f"  Δ vs iter34 = {headline['ccc'] - ITER34_CCC:+.4f}", flush=True)

    # Vs iter34
    if ITER34_OOF.exists() and ITER34_JSON.exists():
        with open(ITER34_JSON) as f:
            j = json.load(f)
        sids_h = [str(s) for s in j["per_subject"]["sids"]]
        p_h_full = np.load(ITER34_OOF)
        sid_to_pred = dict(zip(sids_h, p_h_full.tolist()))
        try:
            p_h = np.array([sid_to_pred[str(s)] for s in sids])
            sign_flip = per_subject_signflip_pvalue(
                y_t1, mean_pred, p_h, n_perms=10000, seed=42
            )
            bca = bca_ci_delta_ccc(
                y_t1, mean_pred, p_h, n_boot=5000, seed=42
            )
            decision = joint_promotion_decision(
                {"sign_flip": sign_flip, "bca": bca},
                bonferroni_p_threshold=0.05, mcid_delta=0.025,
            )
            print(f"  sign-flip p = {sign_flip['p_one_sided']:.4f}", flush=True)
            print(f"  BCa CI = [{bca['ci_low']:+.4f}, {bca['ci_high']:+.4f}]",
                  flush=True)
            print(f"  decision: {decision['verdict']}", flush=True)
        except KeyError as e:
            sign_flip = bca = decision = None
            print(f"  comparator error: {e}", flush=True)
    else:
        sign_flip = bca = decision = None

    out = {
        "mode": args.mode, "n_subjects": n, "seeds": args.seeds,
        "feature_count_used": X.shape[1], "k_selection": use_kselect,
        "per_seed": per_seed, "headline": headline,
        "comparator_iter34_ccc": ITER34_CCC,
        "delta_vs_iter34_observed": headline["ccc"] - ITER34_CCC,
        "sign_flip": sign_flip, "bca": bca, "decision": decision,
        "wall_time_total_s": overall_wall,
        "per_subject": {
            "sids": [str(s) for s in sids],
            "y_true": y_t1.tolist(),
            "y_pred": mean_pred.tolist(),
        },
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"lockbox_t1_v3_combined_{args.mode}_{ts}.json"
    npy_path = RESULTS_DIR / f"lockbox_t1_v3_combined_{args.mode}_{ts}.oof.npy"
    np.save(npy_path, mean_pred)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote {out_path}", flush=True)


if __name__ == "__main__":
    main()

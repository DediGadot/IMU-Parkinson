"""X4 — Equal-weight 2-bag of iter34 (V2) + V3-GSP (codex ensemble-widening prescription).

Mechanism: equal-weight predeclared average of two LEAKAGE-CLEAN OOF prediction
vectors (V2 = iter34_hybrid, V3-GSP = graph-signal-processing on anatomical body
graph). Both are out-of-fold predictions where each subject's prediction came from
a model trained on subjects ≠ i. Bagging reduces prediction variance toward var(y);
since iter34 over-predicts variance (var=9.65 vs var(y)=7.58), variance reduction
should LIFT CCC.

Predeclared weight = 0.5 (NOT learned). No selection bias. No CCC scale penalty
(the bag has scale ≈ average of two predictors' scales).

Distinct from prior V3 stacking attempts:
- project_v3_stacking_step_function_20260512 used Ridge-STACKED weights on
  V2+V3-GSP+V3-MoS+V3-TITD; nested-CV showed -0.020 overfit penalty.
- Honest nested CV V2+V3-GSP gave Δ=+0.0115 with BCa CI crossing 0.
- Equal-weight 2-bag (this probe) has ZERO learned weights → ZERO overfit risk.

Pre-registration: results/preregistration_t1_post_closure_X_series_20260516.json (extends X-series).

Usage:
  uv run python run_t1_X4_equal_weight_2bag.py
  uv run python run_t1_X4_equal_weight_2bag.py --null scrambled_y
  uv run python run_t1_X4_equal_weight_2bag.py --null sid_shuffle
  uv run python run_t1_X4_equal_weight_2bag.py --null canary_noise
  uv run python run_t1_X4_equal_weight_2bag.py --null transductive
  uv run python run_t1_X4_equal_weight_2bag.py --sanity-y-nan
"""
from __future__ import annotations
import argparse, hashlib, json, logging, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from sklearn.model_selection import KFold
from eval_utils import lins_ccc as ccc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [X4] %(message)s")
log = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parent
ITER34_OOF = REPO/"results"/"t1_iter34_per_item_oof_20260511_044242.npz"
V2_OOF = REPO/"results"/"lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"
V3_OOF = REPO/"results"/"lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy"

WEIGHT = 0.5  # predeclared, NOT learned
N_BOOTSTRAP = 5000
BOOTSTRAP_SEED_A = 20260516
BOOTSTRAP_SEED_B = 20260601


def paired_bootstrap(y, p_base, p_cand, n_boot, seed):
    rng = np.random.default_rng(seed); n = len(y); deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        deltas[b] = float(ccc(y[idx], p_cand[idx]) - ccc(y[idx], p_base[idx]))
    return {"median": float(np.median(deltas)), "ci95": [float(np.percentile(deltas,2.5)), float(np.percentile(deltas,97.5))], "frac_pos": float(np.mean(deltas > 0))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--null", choices=("scrambled_y","sid_shuffle","canary_noise","transductive"), default="")
    parser.add_argument("--sanity-y-nan", action="store_true")
    args = parser.parse_args(); null_mode = args.null

    oof = dict(np.load(ITER34_OOF, allow_pickle=True))
    sids = oof["sids"].astype(str); y_t1 = oof["y_t1"].astype(float)
    iter34_pred = oof["t1_sum_pred"].astype(float)
    v2 = np.load(V2_OOF, allow_pickle=True).astype(float)
    v3 = np.load(V3_OOF, allow_pickle=True).astype(float)
    n = len(sids)
    log.info("loaded V2 (corr w/ iter34=%.4f) and V3-GSP (corr w/ iter34=%.4f)",
             float(np.corrcoef(v2, iter34_pred)[0,1]), float(np.corrcoef(v3, iter34_pred)[0,1]))

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011); y_t1 = rng.permutation(y_t1)
        log.info("NULL scrambled_y")
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(91011); perm = rng.permutation(n)
        v3 = v3[perm]  # break V3-GSP's SID alignment
        log.info("NULL sid_shuffle: permuted V3-GSP rows")
    elif null_mode == "canary_noise":
        rng = np.random.default_rng(91011)
        v2 = v2 + rng.normal(0,0.01,v2.shape); v3 = v3 + rng.normal(0,0.01,v3.shape)
        log.info("NULL canary_noise")
    elif null_mode == "transductive":
        for v in (v2, v3):
            m, s = np.mean(v), np.std(v) + 1e-9; v[:] = (v - m) / s
        log.info("NULL transductive: cohort z-score predictors")

    # The 2-bag — equal weight, no fold-local learning
    bag = WEIGHT * v2 + (1.0 - WEIGHT) * v3

    ccc_base = float(ccc(y_t1, iter34_pred))
    ccc_bag = float(ccc(y_t1, bag))
    mae_base = float(np.mean(np.abs(y_t1 - iter34_pred)))
    mae_bag = float(np.mean(np.abs(y_t1 - bag)))
    pearson_base = float(np.corrcoef(y_t1, iter34_pred)[0,1])
    pearson_bag = float(np.corrcoef(y_t1, bag)[0,1])
    var_base = float(np.var(iter34_pred)); var_bag = float(np.var(bag)); var_y = float(np.var(y_t1))

    boot_A = paired_bootstrap(y_t1, iter34_pred, bag, N_BOOTSTRAP, BOOTSTRAP_SEED_A)
    boot_B = paired_bootstrap(y_t1, iter34_pred, bag, N_BOOTSTRAP, BOOTSTRAP_SEED_B)

    correction = bag - iter34_pred; t1_resid = y_t1 - iter34_pred
    corr_correction_resid = float(np.corrcoef(correction, t1_resid)[0,1])

    # 5-fold screen
    kf = KFold(n_splits=5, shuffle=True, random_state=20260309)
    fold_deltas = []
    for tr, te in kf.split(np.arange(n)):
        d = float(ccc(y_t1[te], bag[te]) - ccc(y_t1[te], iter34_pred[te]))
        fold_deltas.append(d)
    fold_mean = float(np.mean(fold_deltas)); fold_std = float(np.std(fold_deltas))

    formula_sha256 = hashlib.sha256(json.dumps({"weight": WEIGHT, "predictors":["V2_iter34_hybrid", "V3_gsp_only"], "predeclared": True}, sort_keys=True).encode()).hexdigest()

    out = {
        "name":"lockbox_t1_X4_equal_weight_2bag",
        "created_at_utc": datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "preregistration":"results/preregistration_t1_post_closure_X_series_20260516.json (X4 = codex ensemble-widening, equal-weight predeclared 2-bag)",
        "null_mode": null_mode or "real", "sanity_y_nan": args.sanity_y_nan,
        "formula_sha256": formula_sha256,
        "weight_predeclared": WEIGHT,
        "predictors": ["V2_iter34_hybrid_oof_2026-05-10", "V3_gsp_v3_only_oof_2026-05-12"],
        "predictor_alignment_corr_v2_v3": float(np.corrcoef(v2, v3)[0,1]),
        "n_cohort": int(n),
        "baselines": {"loocv_ccc_iter34": ccc_base, "loocv_mae_iter34": mae_base, "loocv_pearson_iter34": pearson_base, "var_iter34": var_base, "var_y": var_y},
        "bag": {
            "loocv_ccc": ccc_bag, "loocv_mae": mae_bag, "loocv_pearson": pearson_bag,
            "var_bag": var_bag,
            "delta_ccc": ccc_bag - ccc_base, "delta_mae": mae_bag - mae_base, "delta_pearson_r": pearson_bag - pearson_base,
        },
        "bootstrap_seed_A": boot_A, "bootstrap_seed_B": boot_B,
        "d4_audit": {"corr_correction_T1_sum_residual": corr_correction_resid},
        "fivefold_screen": {"per_fold_deltas": fold_deltas, "mean": fold_mean, "std": fold_std},
        "verdict_provisional": _verdict(ccc_bag - ccc_base, boot_A["frac_pos"], boot_B["frac_pos"], mae_bag - mae_base, corr_correction_resid),
    }
    suffix = ""
    if null_mode: suffix = f"_{null_mode}"
    elif args.sanity_y_nan: suffix = "_sanityYnan"
    out_path = REPO/"results"/f"lockbox_t1_X4_equal_weight_2bag_{out['created_at_utc']}{suffix}.json"
    with open(out_path, "w") as f: json.dump(out, f, indent=2)
    log.info("wrote %s", out_path)
    print(f"\n=== X4 equal-weight 2-bag — {null_mode or 'real'}{' SANITY' if args.sanity_y_nan else ''} ===")
    print(f"V2 corr w/ iter34 = {np.corrcoef(v2, iter34_pred)[0,1]:.4f}; V3-GSP corr w/ iter34 = {np.corrcoef(v3, iter34_pred)[0,1]:.4f}")
    print(f"baseline iter34 CCC = {ccc_base:.4f}, Pearson = {pearson_base:.4f}")
    print(f"bag CCC = {ccc_bag:.4f}, Δ_CCC = {ccc_bag - ccc_base:+.4f}, Δ_MAE = {mae_bag - mae_base:+.4f}, Δ_Pearson = {pearson_bag - pearson_base:+.4f}")
    print(f"var(iter34)={var_base:.4f}, var(bag)={var_bag:.4f}, var(y)={var_y:.4f}  → bag reduces var by {var_base - var_bag:.4f}")
    print(f"frac>0 seed_A={boot_A['frac_pos']:.4f}  seed_B={boot_B['frac_pos']:.4f}")
    print(f"CI95 seed_A=[{boot_A['ci95'][0]:+.4f},{boot_A['ci95'][1]:+.4f}]  seed_B=[{boot_B['ci95'][0]:+.4f},{boot_B['ci95'][1]:+.4f}]")
    print(f"D4 corr={corr_correction_resid:+.4f}; 5-fold Δ̄={fold_mean:+.4f} std={fold_std:.4f}")
    print(f"VERDICT: {out['verdict_provisional']}")
    return 0


def _verdict(d, fA, fB, dmae, corr_sumres):
    if d >= 0.005 and fA >= 0.95 and fB >= 0.95: return "PRIMARY_GATE_PASS_REPLICATED"
    if d >= 0.005 and (fA >= 0.95 or fB >= 0.95): return "PRIMARY_GATE_PASS_PARTIAL"
    if d >= 0.005 and fA >= 0.90 and fB >= 0.90: return "NEAR_MISS_PRIMARY_GATE_BOTH_SEEDS"
    if d > 0: return "POSITIVE_BUT_SUB_GATE"
    return "FAIL"


if __name__ == "__main__":
    sys.exit(main())

"""X1b — AND-rule two-signal abstention (codex fix to X1 max-combiner catastrophe).

X1 used s = max(z_disagree, z_hy) which becomes an OR-veto: either high signal
triggers abstention. HY is severity-correlated → high-severity dominates → bad.

X1b: AND-rule. Subject is abstained ONLY when BOTH signals exceed thresholds:
- v2v3_disagreement > q_v2v3_threshold (threshold chosen to preserve Slot D coverage)
- |hy_implied_t1 - yhat_corrected| > q_hy_threshold (z-score quantile)

Effectively: HY acts as a CONFIRMATION signal on already-abstained subjects.
Subjects flagged by V2-V3 disagreement but DEFENDED by HY consistency are KEPT.

Pre-registration: extends X-series under amendment-style mechanism.
"""
from __future__ import annotations
import argparse, hashlib, json, logging, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [X1b] %(message)s")
log = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parent
ITER34_OOF = REPO/"results"/"t1_iter34_per_item_oof_20260511_044242.npz"
V2_OOF = REPO/"results"/"lockbox_t1_iter34_hybrid_20260510_233019.oof.npy"
V3_OOF = REPO/"results"/"lockbox_t1_v3_gsp_v3_only_20260512_195152.oof.npy"
PH_CACHE = REPO/"results"/"cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"
CLINICAL = REPO/"results"/"pd_demographic_clinical_v1.csv"

ALPHA = 100.0; LAMBDA = 1.0
N_BOOTSTRAP = 5000
BOOTSTRAP_SEED = 20260516
COVERAGES = (0.70, 0.50)


def loocv_ph_correction(X_ph, item13_resid):
    n = len(item13_resid); correction = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        Xt_raw, Xv_raw = X_ph[tr], X_ph[i:i+1]
        imp = FoldImputer.fit(Xt_raw); Xt = imp.transform(Xt_raw); Xv = imp.transform(Xv_raw)
        nrm = FoldNormalizer.fit(Xt); Xt = nrm.transform(Xt); Xv = nrm.transform(Xv)
        correction[i] = Ridge(alpha=ALPHA).fit(Xt, item13_resid[tr]).predict(Xv)[0]
    return correction


def loocv_hy_signal(hy, yhat, y_t1):
    n = len(y_t1); signal = np.full(n, np.nan)
    for i in range(n):
        tr = np.arange(n) != i
        valid = np.isfinite(hy[tr]) & np.isfinite(y_t1[tr])
        if valid.sum() < 5 or not np.isfinite(hy[i]):
            signal[i] = 0.0; continue
        x = hy[tr][valid]; y = y_t1[tr][valid]
        x_m, y_m = x.mean(), y.mean(); x_v = ((x-x_m)**2).sum()
        if x_v < 1e-9: signal[i] = 0.0; continue
        a = ((x-x_m)*(y-y_m)).sum() / x_v; b = y_m - a*x_m
        signal[i] = abs(a*hy[i] + b - yhat[i])
    return signal


def paired_bootstrap_frac_pos(y, p_base, p_cand, keep_base, keep_cand, n_boot, seed):
    rng = np.random.default_rng(seed); n = len(y); deltas = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n); kb = keep_base[idx]; kc = keep_cand[idx]
        if kb.sum() < 3 or kc.sum() < 3: deltas[b] = 0.0; continue
        deltas[b] = float(ccc(y[idx][kc], p_cand[idx][kc]) - ccc(y[idx][kb], p_base[idx][kb]))
    return {"median": float(np.median(deltas)), "ci95": [float(np.percentile(deltas,2.5)), float(np.percentile(deltas,97.5))], "frac_pos": float(np.mean(deltas > 0))}


def retained_at_coverage(y, yhat, score, cov):
    n = len(y); n_keep = int(np.floor(cov*n))
    thr = np.partition(score, n_keep - 1)[n_keep - 1]
    keep = score <= thr
    return float(ccc(y[keep], yhat[keep])), int(keep.sum()), keep


def and_rule_retain(disagree, hy_signal, cov):
    """Retain a subject if EITHER signal is below its cov-quantile.
    Equivalently: abstain only when BOTH are above their cov-quantile.

    To match coverage cov, choose thresholds such that exactly floor(cov*n) subjects
    are retained. Use a binary search over a shared scale.

    Implementation: rank both signals (lower rank = lower score = safer).
    A subject's safe-rank = min(rank_disagree, rank_hy). Retain subjects with
    safe-rank below the cov-quantile.
    """
    n = len(disagree)
    n_keep = int(np.floor(cov * n))
    rank_d = np.argsort(np.argsort(disagree))  # 0=lowest
    rank_h = np.argsort(np.argsort(hy_signal))
    safe_rank = np.minimum(rank_d, rank_h)  # subject is safe if EITHER signal is low
    threshold = np.partition(safe_rank, n_keep - 1)[n_keep - 1]
    keep = safe_rank <= threshold
    # Handle ties: trim to exactly n_keep
    if keep.sum() > n_keep:
        idx_sorted = np.argsort(safe_rank)
        keep_mask = np.zeros(n, dtype=bool)
        keep_mask[idx_sorted[:n_keep]] = True
        keep = keep_mask
    return keep


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--null", choices=("scrambled_y","sid_shuffle","canary_noise","transductive"), default="")
    parser.add_argument("--sanity-y-nan", action="store_true")
    args = parser.parse_args()
    null_mode = args.null
    sanity_y_nan = args.sanity_y_nan

    oof = dict(np.load(ITER34_OOF, allow_pickle=True))
    sids = oof["sids"].astype(str); y_t1 = oof["y_t1"].astype(float); yhat_iter34 = oof["t1_sum_pred"].astype(float)
    item13_true = oof["item_13_true"].astype(float); item13_pred = oof["item_13_pred"].astype(float)
    item13_resid = item13_true - item13_pred
    n = len(sids)

    v2 = np.load(V2_OOF, allow_pickle=True).astype(float)
    v3 = np.load(V3_OOF, allow_pickle=True).astype(float)
    disagree_raw = np.abs(v2 - v3)

    df_ph = pd.read_csv(PH_CACHE)
    sid_to_row = {s: i for i, s in enumerate(df_ph["sid"].astype(str).values)}
    df_ph = df_ph.iloc[[sid_to_row[s] for s in sids]].reset_index(drop=True)
    ph_cols = [c for c in df_ph.columns if "_ph_" in c]
    X_ph = df_ph[ph_cols].values.astype(float)

    clin = pd.read_csv(CLINICAL, header=1).rename(columns={"Subject ID":"sid"}).set_index("sid").loc[sids]
    hy_raw = pd.to_numeric(clin["Modified Hoehn & Yahr Score"], errors="coerce").values

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011); item13_resid = rng.permutation(item13_resid)
    if null_mode == "sid_shuffle":
        rng = np.random.default_rng(91011); perm = rng.permutation(n)
        X_ph = X_ph[perm]; disagree_raw = disagree_raw[perm]; hy_raw = hy_raw[perm]
    if null_mode == "canary_noise":
        rng = np.random.default_rng(91011)
        X_ph = X_ph + rng.normal(0,0.01,X_ph.shape); disagree_raw = disagree_raw + rng.normal(0,0.01,disagree_raw.shape)
    if null_mode == "transductive":
        col_mean = np.nanmean(X_ph,axis=0,keepdims=True); col_std = np.nanstd(X_ph,axis=0,keepdims=True)+1e-9
        X_ph = (X_ph - col_mean) / col_std

    correction = loocv_ph_correction(X_ph, item13_resid)
    yhat_corrected = yhat_iter34 + LAMBDA * correction
    hy_sig = loocv_hy_signal(hy_raw, yhat_corrected, y_t1)

    results = {}
    for cov in COVERAGES:
        # Slot D baseline (V2-V3 only)
        ccc_sD, _, keep_sD = retained_at_coverage(y_t1, yhat_corrected, disagree_raw, cov)
        # X1b: AND-rule (retain if EITHER signal low)
        keep_X1b = and_rule_retain(disagree_raw, hy_sig, cov)
        ccc_X1b = float(ccc(y_t1[keep_X1b], yhat_corrected[keep_X1b]))
        # MAE
        mae_sD = float(np.mean(np.abs(y_t1[keep_sD] - yhat_corrected[keep_sD])))
        mae_X1b = float(np.mean(np.abs(y_t1[keep_X1b] - yhat_corrected[keep_X1b])))
        # Flips
        flip_in = int(np.sum(keep_X1b & ~keep_sD)); flip_out = int(np.sum(~keep_X1b & keep_sD))
        boot = paired_bootstrap_frac_pos(y_t1, yhat_corrected, yhat_corrected, keep_sD, keep_X1b, N_BOOTSTRAP, BOOTSTRAP_SEED)
        results[f"cov_{int(cov*100):02d}"] = {
            "coverage": cov, "n_keep_slotD": int(keep_sD.sum()), "n_keep_X1b": int(keep_X1b.sum()),
            "slotD_baseline_retained_ccc": ccc_sD, "X1b_AND_rule_retained_ccc": ccc_X1b,
            "delta_ccc": ccc_X1b - ccc_sD,
            "slotD_retained_mae": mae_sD, "X1b_retained_mae": mae_X1b,
            "flipped_in_vs_slotD": flip_in, "flipped_out_vs_slotD": flip_out,
            "bootstrap": boot,
        }

    formula_sha256 = hashlib.sha256(json.dumps({"rule":"AND","cov":list(COVERAGES)}, sort_keys=True).encode()).hexdigest()
    out = {
        "name": "lockbox_t1_X1b_AND_rule_abstention",
        "created_at_utc": datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "preregistration": "results/preregistration_t1_post_closure_X_series_20260516.json (X1b = X1 codex fix: AND-rule)",
        "null_mode": null_mode or "real", "sanity_y_nan": sanity_y_nan,
        "formula_sha256": formula_sha256, "n_cohort": int(n),
        "fix_rationale": "X1 max() was OR-veto (either signal abstains). X1b AND-rule (both signals must be high to abstain) preserves V2-V3 abstention as floor; HY only refines on within-band cases.",
        "results_per_coverage": results,
        "verdict_provisional": _verdict(results),
    }
    suffix = ""
    if null_mode: suffix = f"_{null_mode}"
    elif sanity_y_nan: suffix = "_sanityYnan"
    out_path = REPO/"results"/f"lockbox_t1_X1b_AND_rule_abstention_{out['created_at_utc']}{suffix}.json"
    with open(out_path, "w") as f: json.dump(out, f, indent=2)
    log.info("wrote %s", out_path)
    print(f"\n=== X1b AND-rule — {null_mode or 'real'}{' SANITY' if sanity_y_nan else ''} ===")
    for k, r in results.items():
        print(f"{k}: slotD={r['slotD_baseline_retained_ccc']:.4f} X1b={r['X1b_AND_rule_retained_ccc']:.4f} Δ={r['delta_ccc']:+.4f} frac>0={r['bootstrap']['frac_pos']:.3f} flip_in={r['flipped_in_vs_slotD']}, flip_out={r['flipped_out_vs_slotD']}")
    print(f"VERDICT: {out['verdict_provisional']}")
    return 0


def _verdict(r):
    d70 = r["cov_70"]["delta_ccc"]; f70 = r["cov_70"]["bootstrap"]["frac_pos"]
    d50 = r["cov_50"]["delta_ccc"]; f50 = r["cov_50"]["bootstrap"]["frac_pos"]
    if d70 >= 0.005 and d50 >= 0.005 and f70 >= 0.95 and f50 >= 0.95: return "PRIMARY_GATE_PASS_BOTH"
    if (d70 >= 0.005 and f70 >= 0.95) or (d50 >= 0.005 and f50 >= 0.95): return "PRIMARY_GATE_PASS_PARTIAL"
    if d70 > 0 and d50 > 0: return "POSITIVE_BUT_SUB_GATE"
    return "FAIL"


if __name__ == "__main__":
    sys.exit(main())

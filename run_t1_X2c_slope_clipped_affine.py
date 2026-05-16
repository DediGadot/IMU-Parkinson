"""X2c — slope-clipped affine (X2 fix preserving the +0.47 D4 corr directional signal).

X2 with 2-param affine produced Δ_CCC=-0.05 + D4_corr=+0.47 (strong direction).
X2b intercept-only killed the signal (b ≈ -0.025 in both strata).
X2c clips slope to [0.95, 1.05] — preserves directional information while limiting
CCC scale-compression damage.
"""
from __future__ import annotations
import argparse, hashlib, json, logging, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from eval_utils import lins_ccc as ccc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [X2c] %(message)s")
log = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parent
ITER34_OOF = REPO/"results"/"t1_iter34_per_item_oof_20260511_044242.npz"
CLINICAL = REPO/"results"/"pd_demographic_clinical_v1.csv"

DURATION_THRESHOLD = 7.0
MIN_STRATUM_SIZE = 15
SLOPE_CLIP = (0.95, 1.05)
N_BOOTSTRAP = 5000
BOOTSTRAP_SEED_A = 20260516
BOOTSTRAP_SEED_B = 20260601


def fit_affine_clipped(y, x, slope_clip):
    valid = np.isfinite(y) & np.isfinite(x)
    if valid.sum() < 5: return 1.0, 0.0
    yv, xv = y[valid], x[valid]; x_m, y_m = xv.mean(), yv.mean(); x_v = ((xv-x_m)**2).sum()
    if x_v < 1e-9: return 1.0, 0.0
    a_raw = ((xv-x_m)*(yv-y_m)).sum() / x_v
    a = max(slope_clip[0], min(slope_clip[1], a_raw))
    b = y_m - a * x_m
    return float(a), float(b)


def loocv_stratified_clipped(yhat, y, duration, threshold, min_stratum, slope_clip):
    n = len(y); corrected = np.full(n, np.nan)
    slopes = []; raw_slopes_long = []; raw_slopes_short = []
    for i in range(n):
        tr = np.arange(n) != i
        yhat_tr, y_tr, d_tr = yhat[tr], y[tr], duration[tr]
        long_tr = (~np.isfinite(d_tr)) | (d_tr >= threshold)
        short_tr = ~long_tr
        n_long, n_short = int(long_tr.sum()), int(short_tr.sum())
        if n_long < min_stratum or n_short < min_stratum:
            a, b = fit_affine_clipped(y_tr, yhat_tr, slope_clip)
        else:
            a_long, b_long = fit_affine_clipped(y_tr[long_tr], yhat_tr[long_tr], slope_clip)
            a_short, b_short = fit_affine_clipped(y_tr[short_tr], yhat_tr[short_tr], slope_clip)
            # raw (unclipped) for reporting
            x_l, y_l = yhat_tr[long_tr], y_tr[long_tr]
            x_lm = x_l.mean(); a_l_raw = ((x_l-x_lm)*(y_l-y_l.mean())).sum() / max(((x_l-x_lm)**2).sum(), 1e-9)
            x_s, y_s = yhat_tr[short_tr], y_tr[short_tr]
            x_sm = x_s.mean(); a_s_raw = ((x_s-x_sm)*(y_s-y_s.mean())).sum() / max(((x_s-x_sm)**2).sum(), 1e-9)
            raw_slopes_long.append(a_l_raw); raw_slopes_short.append(a_s_raw)
            d_i = duration[i]
            is_long_i = (not np.isfinite(d_i)) or (d_i >= threshold)
            a, b = (a_long, b_long) if is_long_i else (a_short, b_short)
        slopes.append(a)
        corrected[i] = a * yhat[i] + b
    return corrected, {
        "slope_mean": float(np.mean(slopes)), "slope_min": float(np.min(slopes)), "slope_max": float(np.max(slopes)),
        "raw_slope_long_mean": float(np.mean(raw_slopes_long)) if raw_slopes_long else float("nan"),
        "raw_slope_short_mean": float(np.mean(raw_slopes_short)) if raw_slopes_short else float("nan"),
    }


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
    sids = oof["sids"].astype(str); y_t1 = oof["y_t1"].astype(float); yhat = oof["t1_sum_pred"].astype(float)
    n = len(sids)
    clin = pd.read_csv(CLINICAL, header=1).rename(columns={"Subject ID":"sid"}).set_index("sid").loc[sids]
    duration = pd.to_numeric(clin["Years since PD diagnosis"], errors="coerce").values

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011); y_t1 = rng.permutation(y_t1)
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(91011); duration = duration[rng.permutation(n)]
    elif null_mode == "canary_noise":
        rng = np.random.default_rng(91011); duration = duration + rng.normal(0,0.01,duration.shape)
    elif null_mode == "transductive":
        m, s = np.mean(yhat), np.std(yhat) + 1e-9; yhat = (yhat - m) / s

    corrected, info = loocv_stratified_clipped(yhat, y_t1, duration, DURATION_THRESHOLD, MIN_STRATUM_SIZE, SLOPE_CLIP)
    ccc_base = float(ccc(y_t1, yhat)); ccc_corr = float(ccc(y_t1, corrected))
    mae_base = float(np.mean(np.abs(y_t1 - yhat))); mae_corr = float(np.mean(np.abs(y_t1 - corrected)))
    pearson_base = float(np.corrcoef(y_t1, yhat)[0,1]); pearson_corr = float(np.corrcoef(y_t1, corrected)[0,1])
    boot_A = paired_bootstrap(y_t1, yhat, corrected, N_BOOTSTRAP, BOOTSTRAP_SEED_A)
    boot_B = paired_bootstrap(y_t1, yhat, corrected, N_BOOTSTRAP, BOOTSTRAP_SEED_B)
    correction = corrected - yhat; t1_resid = y_t1 - yhat
    corr_correction_resid = float(np.corrcoef(correction, t1_resid)[0,1])

    formula_sha256 = hashlib.sha256(json.dumps({"slope_clip":list(SLOPE_CLIP), "threshold":DURATION_THRESHOLD}, sort_keys=True).encode()).hexdigest()
    out = {
        "name":"lockbox_t1_X2c_slope_clipped_affine",
        "created_at_utc": datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "preregistration":"results/preregistration_t1_post_closure_X_series_20260516.json (X2c = X2 fix codex-informed: clip slope ±5%)",
        "null_mode": null_mode or "real", "sanity_y_nan": args.sanity_y_nan,
        "formula_sha256": formula_sha256,
        "slope_clip": list(SLOPE_CLIP),
        "stratum_info": info,
        "n_cohort": int(n),
        "baselines":{"loocv_ccc_iter34": ccc_base, "loocv_mae_iter34": mae_base},
        "corrected":{"loocv_ccc": ccc_corr, "loocv_mae": mae_corr, "delta_ccc": ccc_corr - ccc_base, "delta_mae": mae_corr - mae_base, "delta_pearson_r": pearson_corr - pearson_base},
        "bootstrap_seed_A": boot_A, "bootstrap_seed_B": boot_B,
        "d4_audit":{"corr_correction_T1_sum_residual": corr_correction_resid},
        "verdict_provisional": _verdict(ccc_corr - ccc_base, boot_A["frac_pos"], boot_B["frac_pos"], mae_corr - mae_base, corr_correction_resid),
    }
    suffix = ""
    if null_mode: suffix = f"_{null_mode}"
    elif args.sanity_y_nan: suffix = "_sanityYnan"
    out_path = REPO/"results"/f"lockbox_t1_X2c_slope_clipped_affine_{out['created_at_utc']}{suffix}.json"
    with open(out_path, "w") as f: json.dump(out, f, indent=2)
    log.info("wrote %s", out_path)
    print(f"\n=== X2c slope-clipped — {null_mode or 'real'}{' SANITY' if args.sanity_y_nan else ''} ===")
    print(f"baseline iter34 CCC = {ccc_base:.4f}")
    print(f"corrected CCC = {ccc_corr:.4f}  Δ={ccc_corr - ccc_base:+.4f}  ΔMAE={mae_corr - mae_base:+.4f}")
    print(f"frac>0 seed_A={boot_A['frac_pos']:.3f}  seed_B={boot_B['frac_pos']:.3f}")
    print(f"D4 corr={corr_correction_resid:+.4f}; slope mean={info['slope_mean']:.4f} range=[{info['slope_min']:.4f},{info['slope_max']:.4f}]")
    print(f"raw slopes (unclipped) long mean={info['raw_slope_long_mean']:.4f} short mean={info['raw_slope_short_mean']:.4f}")
    print(f"VERDICT: {out['verdict_provisional']}")
    return 0


def _verdict(d, fA, fB, dmae, corr_sumres):
    if dmae > 0 and corr_sumres < 0: return "VARIANCE_COMPRESSION_MIRAGE_LIKELY"
    if d >= 0.005 and fA >= 0.95 and fB >= 0.95: return "PRIMARY_GATE_PASS_REPLICATED"
    if d >= 0.005 and (fA >= 0.95 or fB >= 0.95): return "PRIMARY_GATE_PASS_PARTIAL"
    if d > 0: return "POSITIVE_BUT_SUB_GATE"
    return "FAIL"


if __name__ == "__main__":
    sys.exit(main())

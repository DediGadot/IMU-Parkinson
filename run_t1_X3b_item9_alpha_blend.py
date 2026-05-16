"""X3b — item-9 alone with constrained alpha blend (codex fix to X3).

X3 had: corr(c9, item9_resid) = +0.159 (weak positive), corr(c12, item12_resid) = -0.028 (zero).
Codex prescription: drop item 12, item 9 alone, constrained alpha grid {0, 0.25, 0.5},
alpha selected inside train fold (inner CV) with non-negative constraint.

T1_sum_corrected = iter34.t1_sum_pred + alpha * Ridge_alpha_grid_inner_cv(item-9-PL → item-9-resid)
where blending coefficient alpha selected per outer fold via inner 5-fold CV.
"""
from __future__ import annotations
import argparse, hashlib, json, logging, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from inductive_lib import FoldImputer, FoldNormalizer
from eval_utils import lins_ccc as ccc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [X3b] %(message)s")
log = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parent
ITER34_OOF = REPO/"results"/"t1_iter34_per_item_oof_20260511_044242.npz"
CACHE_ITEM9 = REPO/"results"/"phaselocked_item9_features.csv"

ALPHA_GRID = (10.0, 30.0, 100.0, 300.0, 1000.0)
BLEND_GRID = (0.0, 0.25, 0.5)   # codex prescription
INNER_FOLDS = 5
INNER_SEED = 31415
MODEL_SEEDS_SET_A = (42, 1337, 7)
MODEL_SEEDS_SET_B = (101, 202, 303)
N_BOOTSTRAP = 5000
BOOTSTRAP_SEED = 20260516


def align(df, sids):
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    missing = [s for s in sids if s not in sid_to_row]
    if missing:
        feat_cols_all = [c for c in df.columns if c != "sid"]
        rows = [{"sid": s, **{c: np.nan for c in feat_cols_all}} for s in missing]
        df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
        sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids])
    df = df.iloc[order].reset_index(drop=True)
    return df


def fold_local_ridge(X_tr, y_tr, X_te, alpha):
    imp = FoldImputer.fit(X_tr); Xt = imp.transform(X_tr); Xv = imp.transform(X_te)
    nrm = FoldNormalizer.fit(Xt); Xt = nrm.transform(Xt); Xv = nrm.transform(Xv)
    return Ridge(alpha=alpha).fit(Xt, y_tr).predict(Xv)


def inner_cv_select_alpha_and_blend(X_tr, y_t1_tr, yhat_t1sum_tr, item9_resid_tr, seed):
    """Inner 5-fold: jointly select Ridge alpha AND blend coefficient."""
    n = len(item9_resid_tr)
    kf = KFold(n_splits=INNER_FOLDS, shuffle=True, random_state=seed)
    best_score = -np.inf; best_alpha = ALPHA_GRID[0]; best_blend = 0.0
    for alpha in ALPHA_GRID:
        oof_c9 = np.full(n, np.nan)
        for tr_idx, va_idx in kf.split(np.arange(n)):
            oof_c9[va_idx] = fold_local_ridge(X_tr[tr_idx], item9_resid_tr[tr_idx], X_tr[va_idx], alpha)
        for blend in BLEND_GRID:
            t1_corrected_oof = yhat_t1sum_tr + blend * oof_c9
            score = float(ccc(y_t1_tr, t1_corrected_oof))
            if score > best_score:
                best_score = score; best_alpha = alpha; best_blend = blend
    return best_alpha, best_blend


def loocv_correction(X9, item9_resid, y_t1, yhat_t1sum, seed):
    n = len(item9_resid)
    correction = np.full(n, np.nan); chosen_alpha = np.zeros(n); chosen_blend = np.zeros(n)
    for i in range(n):
        tr = np.arange(n) != i
        X_tr, X_te = X9[tr], X9[i:i+1]
        item9_resid_tr = item9_resid[tr]; y_t1_tr = y_t1[tr]; yhat_tr = yhat_t1sum[tr]
        best_alpha, best_blend = inner_cv_select_alpha_and_blend(X_tr, y_t1_tr, yhat_tr, item9_resid_tr, seed=seed)
        chosen_alpha[i] = best_alpha; chosen_blend[i] = best_blend
        c9 = fold_local_ridge(X_tr, item9_resid_tr, X_te, best_alpha)[0]
        correction[i] = best_blend * c9
    return correction, chosen_alpha, chosen_blend


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
    item9_true = oof["item_9_true"].astype(float); item9_pred = oof["item_9_pred"].astype(float)
    item9_resid = item9_true - item9_pred
    n = len(sids)
    df9 = align(pd.read_csv(CACHE_ITEM9), sids)
    feat9 = [c for c in df9.columns if c != "sid"]
    X9 = df9[feat9].values.astype(float)

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011); item9_resid = rng.permutation(item9_resid)
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(91011); X9 = X9[rng.permutation(n)]
    elif null_mode == "canary_noise":
        rng = np.random.default_rng(91011); X9 = X9 + rng.normal(0,0.01,X9.shape)
    elif null_mode == "transductive":
        m = np.nanmean(X9,axis=0,keepdims=True); s = np.nanstd(X9,axis=0,keepdims=True)+1e-9
        X9 = (X9 - m) / s

    preds = {}; chosen_blends_all = {}
    for seed in (*MODEL_SEEDS_SET_A, *MODEL_SEEDS_SET_B):
        corr, alpha_chosen, blend_chosen = loocv_correction(X9, item9_resid, y_t1, yhat, seed=seed)
        preds[seed] = corr
        chosen_blends_all[seed] = blend_chosen

    def avg(seeds): return np.mean([preds[s] for s in seeds], axis=0)
    correction_A = avg(MODEL_SEEDS_SET_A); correction_B = avg(MODEL_SEEDS_SET_B)
    correction_avg = (correction_A + correction_B) / 2.0

    t1_A = yhat + correction_A; t1_B = yhat + correction_B; t1_avg = yhat + correction_avg
    ccc_base = float(ccc(y_t1, yhat))
    mae_base = float(np.mean(np.abs(y_t1 - yhat)))

    def headline(t1_cand, label):
        ccc_t1 = float(ccc(y_t1, t1_cand)); mae_t1 = float(np.mean(np.abs(y_t1 - t1_cand)))
        boot = paired_bootstrap(y_t1, yhat, t1_cand, N_BOOTSTRAP, BOOTSTRAP_SEED)
        return {"label": label, "ccc": ccc_t1, "delta_ccc": ccc_t1 - ccc_base, "mae": mae_t1, "delta_mae": mae_t1 - mae_base, "bootstrap": boot}
    h_A = headline(t1_A, "seed_set_A"); h_B = headline(t1_B, "seed_set_B")

    t1_resid = y_t1 - yhat
    corr_correction_sum = float(np.corrcoef(correction_avg, t1_resid)[0,1])
    delta_mae_avg = float(np.mean(np.abs(y_t1 - t1_avg)) - mae_base)

    # Blend distribution (how often did inner-CV pick alpha=0, 0.25, 0.5?)
    all_blends = np.concatenate([chosen_blends_all[s] for s in MODEL_SEEDS_SET_A])
    blend_hist = {f"blend_{b}": int((all_blends == b).sum()) for b in BLEND_GRID}

    formula_sha256 = hashlib.sha256(json.dumps({"blend_grid":list(BLEND_GRID),"alpha_grid":list(ALPHA_GRID),"item":9}, sort_keys=True).encode()).hexdigest()
    out = {
        "name":"lockbox_t1_X3b_item9_alpha_blend",
        "created_at_utc": datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "preregistration":"results/preregistration_t1_post_closure_X_series_20260516.json (X3b = X3 codex fix: item-9 only, alpha blend)",
        "null_mode": null_mode or "real", "sanity_y_nan": args.sanity_y_nan,
        "formula_sha256": formula_sha256,
        "n_cohort": int(n), "n_features": len(feat9),
        "blend_grid": list(BLEND_GRID), "alpha_grid": list(ALPHA_GRID),
        "blend_histogram_seedA": blend_hist,
        "baselines": {"loocv_ccc_iter34": ccc_base, "loocv_mae_iter34": mae_base},
        "seed_set_A": h_A, "seed_set_B": h_B,
        "d4_audit": {"corr_correction_T1_sum_residual": corr_correction_sum, "delta_mae_avg": delta_mae_avg},
        "verdict_provisional": _verdict(h_A["delta_ccc"], h_B["delta_ccc"], h_A["bootstrap"]["frac_pos"], h_B["bootstrap"]["frac_pos"], corr_correction_sum, delta_mae_avg),
    }
    suffix = ""
    if null_mode: suffix = f"_{null_mode}"
    elif args.sanity_y_nan: suffix = "_sanityYnan"
    out_path = REPO/"results"/f"lockbox_t1_X3b_item9_alpha_blend_{out['created_at_utc']}{suffix}.json"
    with open(out_path, "w") as f: json.dump(out, f, indent=2)
    log.info("wrote %s", out_path)
    print(f"\n=== X3b item-9 alpha-blend — {null_mode or 'real'}{' SANITY' if args.sanity_y_nan else ''} ===")
    print(f"baseline iter34 CCC = {ccc_base:.4f}")
    print(f"seed_A Δ={h_A['delta_ccc']:+.4f} frac>0={h_A['bootstrap']['frac_pos']:.3f}; seed_B Δ={h_B['delta_ccc']:+.4f} frac>0={h_B['bootstrap']['frac_pos']:.3f}")
    print(f"D4 corr(corr_avg, sum_resid) = {corr_correction_sum:+.4f}; ΔMAE_avg = {delta_mae_avg:+.4f}")
    print(f"Blend hist seed_A: {blend_hist}")
    print(f"VERDICT: {out['verdict_provisional']}")
    return 0


def _verdict(dA, dB, fA, fB, corr_sumres, dmae):
    if dmae > 0 and corr_sumres < 0: return "VARIANCE_COMPRESSION_MIRAGE_LIKELY"
    if dA >= 0.005 and dB >= 0.005 and fA >= 0.95 and fB >= 0.95: return "PRIMARY_GATE_PASS_REPLICATED"
    if (dA >= 0.005 or dB >= 0.005) and (fA >= 0.95 or fB >= 0.95): return "PRIMARY_GATE_PASS_PARTIAL"
    if dA > 0 and dB > 0: return "POSITIVE_BUT_SUB_GATE"
    return "FAIL"


if __name__ == "__main__":
    sys.exit(main())

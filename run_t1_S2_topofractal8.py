"""T1 Slot S2: Topo-Fractal-8 target-free 6-component correction on iter34 residual.

Hypothesis (preregistration_t1t3_proresults_ablation_20260515T133800Z.json, slot S2):
A target-free fixed 6-dim PH/MFDFA representation feeding a fold-local Ridge
correction on iter34 T1_sum residual yields LOOCV CCC delta of +0.005..+0.020.
Demonstrates biomechanical primitives compressed by FAMILY (not by LGB importance)
carry residual signal.

Six subfamilies (exactly 1 PCA component each, pooled across tasks):
  1. PH_trunk_pitch_h1            (max+med variants, ~10 cols)
  2. PH_sacrum_ang_h1              (max+med variants, ~10 cols)
  3. MFDFA_trunk_pitch_delta_alpha
  4. MFDFA_trunk_pitch_hurst_q2
  5. MFDFA_trunk_pitch_h_range     (singularity-width proxy)
  6. MFDFA_trunk_pitch_asymmetry

Firewall discipline (single source of truth = inductive_lib):
  * FoldImputer + FoldNormalizer fit on TRAIN rows only.
  * sklearn PCA(n_components=1) fit on TRAIN rows only; loadings frozen and then
    applied to the test row.
  * PCA is target-free (no y).
  * Sign-alignment rule: force corr(PC1_train, normalized-train-column-mean) > 0
    by flipping the score and the loadings if needed. Documented so downstream
    consumers can reproduce.

5-null gate: --null=scrambled_y permutes y_t1; --null=sid_shuffle permutes cache
rows after the sid alignment. Real CCC must collapse under each null.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

from eval_utils import lins_ccc as ccc
from inductive_lib import FoldImputer, FoldNormalizer

ITER34_OOF_NPZ = "results/t1_iter34_per_item_oof_20260511_044242.npz"
CACHE_PATH = "results/cache_stepfunction_spd_klc_crqa_mfdfa_ph_20260515T072624Z.csv"

SPLIT_SEED = 20260309
FEATURE_SEED = 31415
MODEL_SEED_LIST = (42, 1337, 7)

RIDGE_ALPHA = 100.0
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20260515
N_FOLDS_SCREEN = 5

SUBFAMILY_PATTERNS: dict[str, str] = {
    "ph_trunk_pitch_h1": "_ph_trunk_pitch_h1_",
    "ph_sacrum_ang_h1": "_ph_sacrum_ang_h1_",
    "mfdfa_trunk_pitch_delta_alpha": "mfdfa_trunk_pitch_delta_alpha",
    "mfdfa_trunk_pitch_hurst_q2": "mfdfa_trunk_pitch_hurst_q2",
    "mfdfa_trunk_pitch_h_range": "mfdfa_trunk_pitch_h_range",
    "mfdfa_trunk_pitch_asymmetry": "mfdfa_trunk_pitch_asymmetry",
}


def load_aligned() -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DataFrame, dict[str, list[str]]]:
    iter34 = dict(np.load(ITER34_OOF_NPZ, allow_pickle=True))
    sids = iter34["sids"].astype(str)
    y_t1 = iter34["y_t1"].astype(float)
    yhat = iter34["t1_sum_pred"].astype(float)

    df = pd.read_csv(CACHE_PATH)
    df = df[df["sid"].isin(sids)].reset_index(drop=True)
    sid_to_row = {s: i for i, s in enumerate(df["sid"].astype(str).values)}
    order = np.array([sid_to_row[s] for s in sids])
    df = df.iloc[order].reset_index(drop=True)
    assert (df["sid"].astype(str).values == sids).all(), "sid alignment failed"

    groups: dict[str, list[str]] = {}
    for name, pat in SUBFAMILY_PATTERNS.items():
        cols = [c for c in df.columns if pat in c and c != "sid"]
        if len(cols) == 0:
            raise RuntimeError(f"subfamily '{name}' matched 0 cols with pattern '{pat}'")
        if len(cols) > 25:
            raise RuntimeError(f"subfamily '{name}' matched {len(cols)} cols (suspicious — pattern too broad)")
        groups[name] = cols
    return sids, y_t1, yhat, df, groups


def fold_compress_one(X_train_raw: np.ndarray, X_test_raw: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Fit FoldImputer + FoldNormalizer + PCA(1) on train; return (z_train, z_test, evr).

    Sign-alignment: force corr(z_train, mean(normalized_train_cols, axis=1)) > 0
    by flipping z_train, z_test, and the component loadings together.
    """
    imp = FoldImputer.fit(X_train_raw)
    Xt = imp.transform(X_train_raw)
    Xv = imp.transform(X_test_raw)
    nrm = FoldNormalizer.fit(Xt)
    Xt = nrm.transform(Xt)
    Xv = nrm.transform(Xv)
    pca = PCA(n_components=1, random_state=seed)
    z_train = pca.fit_transform(Xt).ravel()
    z_test = pca.transform(Xv).ravel()
    evr = float(pca.explained_variance_ratio_[0])
    col_mean_train = Xt.mean(axis=1)
    if np.corrcoef(z_train, col_mean_train)[0, 1] < 0:
        z_train = -z_train
        z_test = -z_test
    return z_train, z_test, evr


def loocv_correct(
    yhat_iter34: np.ndarray,
    residual: np.ndarray,
    df: pd.DataFrame,
    groups: dict[str, list[str]],
    seed: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, list[float]], dict[str, list[int]]]:
    n = len(residual)
    corrected = yhat_iter34.copy()
    Z_full = np.full((n, len(groups)), np.nan)
    evr_per_sub: dict[str, list[float]] = {k: [] for k in groups}
    sign_per_sub: dict[str, list[int]] = {k: [] for k in groups}
    for i in range(n):
        tr = np.arange(n) != i
        z_train_stack = np.empty((n - 1, len(groups)))
        z_test_row = np.empty(len(groups))
        for k_idx, (name, cols) in enumerate(groups.items()):
            X = df[cols].values.astype(float)
            z_tr, z_te, evr = fold_compress_one(X[tr], X[i:i + 1], seed)
            z_train_stack[:, k_idx] = z_tr
            z_test_row[k_idx] = z_te[0]
            evr_per_sub[name].append(evr)
            sign_per_sub[name].append(1 if z_tr.sum() >= 0 else -1)
        m = Ridge(alpha=RIDGE_ALPHA, random_state=seed).fit(z_train_stack, residual[tr])
        corrected[i] = yhat_iter34[i] + float(m.predict(z_test_row.reshape(1, -1))[0])
        Z_full[i] = z_test_row
    return corrected, Z_full, evr_per_sub, sign_per_sub


def kfold_delta(
    yhat_iter34: np.ndarray,
    y_t1: np.ndarray,
    df: pd.DataFrame,
    groups: dict[str, list[str]],
    seed: int,
    n_splits: int = N_FOLDS_SCREEN,
) -> float:
    n = len(y_t1)
    residual = y_t1 - yhat_iter34
    corrected = yhat_iter34.copy()
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for tr_idx, te_idx in kf.split(np.arange(n)):
        z_tr_stack = np.empty((len(tr_idx), len(groups)))
        z_te_stack = np.empty((len(te_idx), len(groups)))
        for k_idx, (_name, cols) in enumerate(groups.items()):
            X = df[cols].values.astype(float)
            z_tr, z_te, _ = fold_compress_one(X[tr_idx], X[te_idx], seed)
            z_tr_stack[:, k_idx] = z_tr
            z_te_stack[:, k_idx] = z_te
        m = Ridge(alpha=RIDGE_ALPHA, random_state=seed).fit(z_tr_stack, residual[tr_idx])
        corrected[te_idx] = yhat_iter34[te_idx] + m.predict(z_te_stack)
    return float(ccc(y_t1, corrected) - ccc(y_t1, yhat_iter34))


def sign_flip_rate(sign_lists: dict[str, list[int]]) -> float:
    """Fraction of fold-pairs (i, i+1) with sign disagreement, averaged across subfamilies."""
    rates = []
    for _name, signs in sign_lists.items():
        arr = np.array(signs)
        if len(arr) < 2:
            rates.append(0.0)
            continue
        flips = (arr[1:] != arr[:-1]).mean()
        rates.append(float(flips))
    return float(np.mean(rates))


def main(null_mode: str = "") -> None:
    sids, y_t1, yhat_iter34, df, groups = load_aligned()
    n = len(sids)
    counts = {k: len(v) for k, v in groups.items()}
    print(f"[S2] N={n}, subfamily column counts: {counts}, null_mode={null_mode or 'none'}")

    if null_mode == "scrambled_y":
        rng = np.random.default_rng(91011)
        perm = rng.permutation(n)
        y_t1 = y_t1[perm]
        yhat_iter34 = yhat_iter34[perm]
        print("[S2 NULL] permuted y_t1 and iter34 yhat together (preserves baseline CCC)")
    elif null_mode == "sid_shuffle":
        rng = np.random.default_rng(91012)
        perm = rng.permutation(n)
        df = df.iloc[perm].reset_index(drop=True)
        print("[S2 NULL] permuted cache rows post-alignment (breaks sid<->features link)")

    residual = y_t1 - yhat_iter34
    baseline = float(ccc(y_t1, yhat_iter34))
    print(f"[S2] iter34 baseline LOOCV CCC = {baseline:.4f}")

    corrected, Z_full, evr_per_sub, sign_per_sub = loocv_correct(
        yhat_iter34, residual, df, groups, seed=FEATURE_SEED
    )
    corrected_ccc = float(ccc(y_t1, corrected))
    delta = corrected_ccc - baseline
    mean_evr = {k: float(np.mean(v)) for k, v in evr_per_sub.items()}
    sf_rate = sign_flip_rate(sign_per_sub)
    print(f"[S2] corrected LOOCV CCC = {corrected_ccc:.4f}, Δ = {delta:+.4f}")
    print(f"[S2] mean explained variance per subfamily: {mean_evr}")
    print(f"[S2] mean sign-flip rate across folds = {sf_rate:.3f}")

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    deltas = np.empty(N_BOOTSTRAP)
    idx_all = np.arange(n)
    for b in range(N_BOOTSTRAP):
        idx = rng.choice(idx_all, size=n, replace=True)
        deltas[b] = float(ccc(y_t1[idx], corrected[idx]) - ccc(y_t1[idx], yhat_iter34[idx]))
    ci95 = (float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)))
    frac_pos = float((deltas > 0).mean())

    seed_deltas = [kfold_delta(yhat_iter34, y_t1, df, groups, seed=s) for s in MODEL_SEED_LIST]
    mean_5fold = float(np.mean(seed_deltas))
    std_5fold = float(np.std(seed_deltas, ddof=1)) if len(seed_deltas) > 1 else 0.0

    min_evr = min(mean_evr.values())
    evr_pass = min_evr >= 0.30
    sign_pass = sf_rate < 0.05
    fivefold_pass = mean_5fold >= 0.005
    if evr_pass and sign_pass and fivefold_pass and delta >= 0.005 and frac_pos >= 0.95:
        verdict = "PASS_S2_TOPOFRACTAL8"
    elif fivefold_pass and delta >= 0.005:
        verdict = "PASS_SCREEN_FAILS_STABILITY"
    else:
        verdict = "FAIL"

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "name": "lockbox_t1_S2_topofractal8",
        "created_at_utc": ts,
        "preregistration_master": "results/preregistration_t1t3_proresults_ablation_20260515T133800Z.json",
        "null_mode": null_mode or "real",
        "n_cohort": n,
        "seeds": {"split": SPLIT_SEED, "feature": FEATURE_SEED, "models": list(MODEL_SEED_LIST)},
        "ridge_alpha": RIDGE_ALPHA,
        "subfamily_column_counts": counts,
        "mean_explained_variance_per_subfamily": {k: round(v, 4) for k, v in mean_evr.items()},
        "sign_flip_rate": round(sf_rate, 4),
        "loocv_ccc_baseline_iter34": round(baseline, 4),
        "loocv_ccc_corrected": round(corrected_ccc, 4),
        "delta_ccc": round(delta, 4),
        "frac_pos_bootstrap": round(frac_pos, 4),
        "ci95": [round(ci95[0], 4), round(ci95[1], 4)],
        "5fold_mean_delta_3seeds": round(mean_5fold, 4),
        "5fold_seed_std": round(std_5fold, 4),
        "5fold_per_seed_deltas": [round(d, 4) for d in seed_deltas],
        "kill_thresholds": {"min_5fold_delta": 0.005, "min_evr_per_sub": 0.30, "max_sign_flip_rate": 0.05},
        "verdict": verdict,
    }
    suffix = f"_{null_mode}" if null_mode else ""
    json_path = Path(f"results/lockbox_t1_S2_topofractal8_{ts}{suffix}.json")
    json_path.write_text(json.dumps(out, indent=2))
    npz_path = Path(f"results/oof_t1_S2_topofractal8_{ts}{suffix}.npz")
    np.savez(
        npz_path,
        sids=sids,
        y_t1=y_t1,
        yhat_iter34=yhat_iter34,
        corrected=corrected,
        Z=Z_full,
        subfamily_names=np.array(list(groups.keys())),
    )
    print(f"\n[S2] verdict={verdict}")
    print(f"[S2] wrote {json_path}")
    print(f"[S2] wrote {npz_path}")


if __name__ == "__main__":
    nm = ""
    if len(sys.argv) > 1 and sys.argv[1].startswith("--null="):
        nm = sys.argv[1].split("=", 1)[1]
        if nm not in {"scrambled_y", "sid_shuffle"}:
            raise SystemExit(f"unsupported --null value: {nm}")
    main(null_mode=nm)

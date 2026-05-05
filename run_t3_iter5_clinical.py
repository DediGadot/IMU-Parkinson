"""T3 iter5 — Clinical-augmented Stage 1 of hy_residual.

The architecture mirrors the canonical T3 hy_residual but ADDS patient-level
clinical covariates to the Stage 1 Ridge:

  Stage 1 (Ridge alpha=1.0): T3 ~ H&Y(linear+1hot) + clinical covariates
  Stage 2 (LGB on V2 residual): UNCHANGED from canonical hy_residual

All clinical covariates are intake values (set BEFORE the gait session);
no derivation from the rated UPDRS-III. Per-fold imputation/standardisation;
nothing fits on outer-test data.

Two modes:

    python3 run_t3_iter5_clinical.py --mode screen
        5-fold (3 seeds) screening across feature sets A0..A6 at alpha=1.0.
        Writes results/t3_iter5_clinical_5fold_screen.csv.

    python3 run_t3_iter5_clinical.py --mode lockbox --feature_set A3_tier1
        Pre-registers the chosen set and runs ONE LOOCV (3 seeds, mean preds).
        Writes results/preregistration_t3_iter5_<ts>.json + lockbox files.

Compare directly to the published hy_residual T3 LOOCV CCC = 0.4092.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
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
    ccc as ccc_fn,
    full_metrics,
    mae as mae_fn,
    pearson_r,
)
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter3 import load_full_pd_data, get_hy_features
from run_t3_iter2 import impute_fold, feature_select_fold, train_lgb

ensure_dir(RESULTS_DIR)
SEEDS = [42, 1337, 7]
V2_FEATURES = RESULTS_DIR / "ablation_v3_features.csv"
PUBLISHED_HY_RESIDUAL_CCC = 0.4092


# ── Clinical feature loading ─────────────────────────────────────────────────


CLINICAL_COLS_CONTINUOUS: list[str] = ["cv_yrs", "cv_age", "ext_yrs_sq", "ext_yrs_log"]
CLINICAL_COLS_BINARY: list[str] = ["cv_sex", "cv_dbs", "ext_late_pd"]


def load_clinical_dict(sids: np.ndarray) -> dict[str, np.ndarray]:
    """Return {column_name: array_of_length_n} aligned to `sids`."""
    df = pd.read_csv(V2_FEATURES)
    df = df.set_index("sid")
    out: dict[str, np.ndarray] = {}
    for col in CLINICAL_COLS_CONTINUOUS + CLINICAL_COLS_BINARY:
        if col not in df.columns:
            raise KeyError(f"Required clinical column missing from V2_FEATURES: {col!r}")
        vals = np.array([df.loc[s, col] for s in sids], dtype=np.float64)
        out[col] = vals
    # Site (derived from sid prefix; safe per CLAUDE.md "NLS"/"WPD" convention)
    out["site_nls"] = np.array([1.0 if str(s).startswith("NLS") else 0.0 for s in sids])
    return out


# ── Feature sets to screen ──────────────────────────────────────────────────


FEATURE_SETS: dict[str, list[str]] = {
    "A0_hy_only_repro": [],  # H&Y only; sanity reproduction of canonical
    "A1_hy_yrs": ["cv_yrs"],
    "A2_hy_yrs_sex": ["cv_yrs", "cv_sex"],
    "A3_tier1": ["cv_yrs", "cv_sex", "cv_dbs"],
    "A4_tier1_plus": ["cv_yrs", "cv_sex", "cv_dbs", "cv_age", "ext_late_pd"],
    "A5_tier1_plus_site": ["cv_yrs", "cv_sex", "cv_dbs", "cv_age", "ext_late_pd", "site_nls"],
    "A6_yrs_dbs_only": ["cv_yrs", "cv_dbs"],  # parsimony test
    # Iter22 ablation Stage-1 widening test (CC3 = Ridge widening, predicted-null vs A3_tier1):
    "A_iter22_8cov": ["cv_yrs", "cv_sex", "cv_dbs", "cv_age", "ext_yrs_sq", "ext_yrs_log", "ext_late_pd"],
}


def build_stage1_features(
    hy_arr: np.ndarray, clinical: dict[str, np.ndarray], extra_cols: list[str]
) -> tuple[np.ndarray, list[str]]:
    """Concatenate H&Y features + selected clinical extras into a single Stage-1 matrix.
    NO standardisation here — done per-fold in fit_stage1."""
    hy_feat = get_hy_features(hy_arr)  # shape (n, 6)
    parts = [hy_feat]
    names = [f"hy_{i}" for i in range(hy_feat.shape[1])]
    for col in extra_cols:
        parts.append(clinical[col].reshape(-1, 1))
        names.append(col)
    X = np.column_stack(parts)
    return X, names


def fit_stage1(
    X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray, alpha: float = 1.0
) -> tuple[np.ndarray, np.ndarray]:
    """Fold-local Ridge Stage 1 with per-fold standardisation of continuous-style features.
    Standardise the WHOLE X_tr (binary cols just have small scale change — Ridge is
    invariant to global rescaling with intercept, so this is safe)."""
    # Standardise per-fold (fit on train only)
    nrm = FoldNormalizer.fit(X_tr)
    Xtr_s = nrm.transform(X_tr)
    Xte_s = nrm.transform(X_te)
    m = Ridge(alpha=alpha, fit_intercept=True)
    m.fit(Xtr_s, y_tr)
    return m.predict(Xtr_s), m.predict(Xte_s)


# ── LOOCV pipeline (matches canonical hy_residual structure) ─────────────────


def clinical_residual_loocv(
    seed: int, feature_set: str, alpha: float = 1.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Full LOOCV: returns (sids, y_t3, preds)."""
    sids, X, fc, y_t3, hy, obs = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    extra_cols = FEATURE_SETS[feature_set]
    X_s1, _ = build_stage1_features(hy, clinical, extra_cols)
    preds = np.zeros(n)
    loo = LeaveOneOut()
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(loo.split(np.arange(n))):
        # Stage 1: Ridge on H&Y + clinical → T3 (per-fold standardise)
        s1_pred_tr, s1_pred_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=alpha)
        residual_tr = y_t3[tr] - s1_pred_tr
        # Stage 2: LGB on V2 features → residual (UNCHANGED from canonical hy_residual)
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        s2_pred_te = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        preds[te] = s1_pred_te + s2_pred_te
        if (fold_idx + 1) % 10 == 0:
            print(
                f"  [{feature_set} seed={seed}] fold {fold_idx+1}/{n}, elapsed {time.time()-t0:.1f}s",
                flush=True,
            )
    return sids, y_t3, preds


# ── 5-fold screening (3 seeds, all feature sets) ─────────────────────────────


def kfold_split(n: int, n_splits: int = 5, seed: int = 42):
    """Stratified-like KFold on indices, matching the project's 5-fold convention.
    For T3 this is just KFold(shuffle=True, random_state=seed) on indices (no stratification
    by quartile — keeping it simple for apples-to-apples with run_t3_iter3 5-fold)."""
    return list(KFold(n_splits=n_splits, shuffle=True, random_state=seed).split(np.arange(n)))


def clinical_residual_kfold(seed: int, feature_set: str, alpha: float = 1.0) -> np.ndarray:
    """5-fold variant of the LOOCV pipeline."""
    sids, X, fc, y_t3, hy, obs = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    extra_cols = FEATURE_SETS[feature_set]
    X_s1, _ = build_stage1_features(hy, clinical, extra_cols)
    preds = np.zeros(n)
    splits = kfold_split(n, n_splits=5, seed=seed)
    for tr, te in splits:
        s1_pred_tr, s1_pred_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=alpha)
        residual_tr = y_t3[tr] - s1_pred_tr
        Xtr, Xte = impute_fold(X[tr], X[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        s2_pred_te = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        preds[te] = s1_pred_te + s2_pred_te
    return preds


def run_screen(alpha: float = 1.0, seeds: tuple[int, ...] = (42, 1337, 7)) -> pd.DataFrame:
    print(
        f"\n=== T3 iter5 5-FOLD SCREEN (alpha={alpha}, {len(seeds)} seeds × "
        f"{len(FEATURE_SETS)} feature sets) ===\nPublished hy_residual LOOCV CCC = "
        f"{PUBLISHED_HY_RESIDUAL_CCC} (apples-to-apples reference for 5-fold ≈ same).",
        flush=True,
    )
    rows = []
    for fs_name in FEATURE_SETS:
        ccc_per_seed: list[float] = []
        for seed in seeds:
            t0 = time.time()
            sids, X, fc, y_t3, hy, obs = load_full_pd_data()
            preds = clinical_residual_kfold(seed, fs_name, alpha=alpha)
            elapsed = time.time() - t0
            c = ccc_fn(y_t3, preds)
            ccc_per_seed.append(c)
            rows.append(
                {
                    "feature_set": fs_name,
                    "extras": "+".join(FEATURE_SETS[fs_name]) or "(hy_only)",
                    "n_extra": len(FEATURE_SETS[fs_name]),
                    "alpha": alpha,
                    "seed": seed,
                    "ccc": round(c, 4),
                    "mae": round(mae_fn(y_t3, preds), 3),
                    "r": round(pearson_r(y_t3, preds), 4),
                    "wall_time_s": round(elapsed, 1),
                }
            )
        print(
            f"  {fs_name:25s}  extras={('+'.join(FEATURE_SETS[fs_name]) or '(hy_only)'):40s}  "
            f"5-fold CCC = {np.mean(ccc_per_seed):.4f} ± {np.std(ccc_per_seed):.4f}",
            flush=True,
        )

    df = pd.DataFrame(rows)
    out_csv = RESULTS_DIR / "t3_iter5_clinical_5fold_screen.csv"
    df.to_csv(out_csv, index=False)
    print(f"Wrote {out_csv}", flush=True)
    # Pick winner: highest mean CCC across seeds
    means = df.groupby("feature_set")["ccc"].mean().sort_values(ascending=False)
    print("\nMean 5-fold CCC ranking:", flush=True)
    for fs, m in means.items():
        print(f"  {fs:25s}  {m:.4f}", flush=True)
    print(f"\nRecommended lockbox config: {means.index[0]}", flush=True)
    return df


# ── Lockbox LOOCV ────────────────────────────────────────────────────────────


def run_lockbox(feature_set: str, alpha: float = 1.0, seeds: tuple[int, ...] = (42, 1337, 7)) -> dict:
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"Unknown feature_set {feature_set!r}; choose from {list(FEATURE_SETS)}")
    extras = FEATURE_SETS[feature_set]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    prereg = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "experiment": "T3 iter5 — Clinical-augmented Stage 1 of hy_residual",
        "feature_set": feature_set,
        "stage1_extras": extras,
        "stage1_total_features": 6 + len(extras),  # 6 H&Y + extras
        "alpha": alpha,
        "n_subjects": 98,  # full PD cohort (same as published baseline)
        "eval_protocol": (
            "LOOCV (n=98), Stage-1 Ridge with intercept + per-fold standardisation. "
            "Stage-2 LGB on V2 residual (per-fold median imputation, K=500 LGB-importance "
            "feature selection, identical params to canonical hy_residual). "
            "3-seed mean preds = headline."
        ),
        "headline_metric": "CCC of mean-of-3-seed predictions",
        "lockbox_rules": [
            "ONE config pre-registered. ONE LOOCV run. Headline = result, no cherry-picking.",
            "Apples-to-apples baseline: published hy_residual LOOCV CCC = 0.4092 (same N=98).",
            "Stage 2 is BIT-IDENTICAL to canonical hy_residual (impute_fold + feature_select_fold + train_lgb).",
            "If LOOCV CCC <= 0.4092 + 0.005 (within noise), report as null result; do not select runner-up.",
            "Bootstrap CI of (iter5 CCC - iter3 CCC) on the same 98 subjects must straddle zero LESS than 30% to claim significance.",
        ],
        "covariate_safety_argument": (
            "All clinical extras are patient-level intake values (cv_yrs, cv_sex, cv_age, cv_dbs, "
            "ext_late_pd, site_nls). They are NOT derived from the UPDRS-III rating session; "
            "they are recorded at clinical visit BEFORE the gait IMU session. Same status as "
            "H&Y stage in the canonical pipeline."
        ),
    }
    prereg_path = RESULTS_DIR / f"preregistration_t3_iter5_{ts}.json"
    with open(prereg_path, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {prereg_path}", flush=True)

    print(
        f"\n=== T3 iter5 LOCKBOX LOOCV ({feature_set}, alpha={alpha}, "
        f"extras={extras}, {len(seeds)} seeds) ===",
        flush=True,
    )
    all_preds = []
    sids_ref = None
    y_t3_ref = None
    for seed in seeds:
        t0 = time.time()
        sids, y_t3, preds = clinical_residual_loocv(seed=seed, feature_set=feature_set, alpha=alpha)
        elapsed = time.time() - t0
        c = ccc_fn(y_t3, preds)
        m = mae_fn(y_t3, preds)
        r = pearson_r(y_t3, preds)
        print(
            f"  seed {seed}: CCC={c:.4f}, MAE={m:.3f}, r={r:.3f}, time={elapsed:.1f}s",
            flush=True,
        )
        all_preds.append((seed, preds))
        sids_ref = sids
        y_t3_ref = y_t3

    mean_preds = np.mean(np.column_stack([p for _, p in all_preds]), axis=1)
    headline = full_metrics(y_t3_ref, mean_preds, label=f"t3_iter5_{feature_set}")

    # Bootstrap CI of (iter5_ccc - iter3_ccc) on same 98 subjects
    with open(RESULTS_DIR / "iter3_hy_residual_t3_loocv.json") as f:
        iter3 = json.load(f)
    # Harden comparator contract: must be LOOCV not 5-fold/transductive
    assert iter3.get("eval_mode") == "loocv", (
        f"Comparator file must be LOOCV; found eval_mode={iter3.get('eval_mode')!r}"
    )
    sid_to_iter3 = dict(zip(iter3["per_subject"]["sids"], iter3["per_subject"]["y_pred"]))
    iter3_preds_aligned = np.array([sid_to_iter3[str(s)] for s in sids_ref])
    iter3_ccc_on_ref = float(ccc_fn(y_t3_ref, iter3_preds_aligned))

    rng = np.random.RandomState(42)
    n_boot = 2000
    deltas = []
    for _ in range(n_boot):
        idx = rng.randint(0, len(y_t3_ref), size=len(y_t3_ref))
        d = ccc_fn(y_t3_ref[idx], mean_preds[idx]) - ccc_fn(y_t3_ref[idx], iter3_preds_aligned[idx])
        deltas.append(d)
    deltas = np.array(deltas)
    boot = {
        "n_boot": n_boot,
        "delta_mean": round(float(deltas.mean()), 4),
        "delta_ci_low": round(float(np.percentile(deltas, 2.5)), 4),
        "delta_ci_high": round(float(np.percentile(deltas, 97.5)), 4),
        "frac_positive": round(float((deltas > 0).mean()), 3),
        "frac_above_0p01": round(float((deltas > 0.01).mean()), 3),
    }

    headline.update(
        {
            "feature_set": feature_set,
            "stage1_extras": extras,
            "alpha": alpha,
            "eval_mode": "loocv_3seed_mean",
            "n_seeds": len(seeds),
            "per_seed_ccc": [float(ccc_fn(y_t3_ref, p)) for _, p in all_preds],
            "per_seed_mae": [float(mae_fn(y_t3_ref, p)) for _, p in all_preds],
            "per_subject": {
                "sids": sids_ref.tolist(),
                "y_true": y_t3_ref.tolist(),
                "y_pred": mean_preds.tolist(),
            },
            "preregistration_file": prereg_path.name,
            "is_lockbox_headline": True,
            "baseline_iter3_hy_residual_ccc_on_same_98": round(iter3_ccc_on_ref, 4),
            "baseline_published_hy_residual_ccc": PUBLISHED_HY_RESIDUAL_CCC,
            "delta_vs_baseline_iter3": round(float(headline["ccc"]) - iter3_ccc_on_ref, 4),
            "bootstrap_delta_vs_iter3": boot,
        }
    )
    out_json = RESULTS_DIR / f"lockbox_t3_iter5_{feature_set}_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t3_iter5_{feature_set}_{ts}.oof.npy"
    np.save(out_npy, mean_preds)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)

    print(
        f"\n=== HEADLINE (lockbox): CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f}, "
        f"r={headline['r']:.4f}, slope={headline['cal_slope']:.3f} ===",
        flush=True,
    )
    print(
        f"  Δ vs iter3 hy_residual on same N=98: {headline['delta_vs_baseline_iter3']:+.4f}",
        flush=True,
    )
    print(
        f"  Bootstrap (n={n_boot}): mean Δ={boot['delta_mean']:+.4f}, "
        f"95% CI=[{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}], "
        f"frac > 0 = {boot['frac_positive']}, frac > 0.01 = {boot['frac_above_0p01']}",
        flush=True,
    )
    print(f"Wrote {out_json}\nWrote {out_npy}", flush=True)
    return headline


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["screen", "lockbox"], required=True)
    p.add_argument("--feature_set", default=None, help="lockbox feature set (default: A3_tier1)")
    p.add_argument("--alpha", type=float, default=1.0, help="Stage 1 Ridge alpha (default 1.0 = canonical)")
    p.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    args = p.parse_args()

    if args.mode == "screen":
        run_screen(alpha=args.alpha, seeds=tuple(args.seeds))
    else:
        fs = args.feature_set or "A3_tier1"
        run_lockbox(fs, alpha=args.alpha, seeds=tuple(args.seeds))


if __name__ == "__main__":
    main()

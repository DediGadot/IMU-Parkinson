"""T3 iter6 — Iter5 architecture + new IMU feature caches.

Same Stage 1 as iter5 (Ridge on H&Y + cv_yrs + cv_sex + cv_dbs). Stage 2 LGB
expanded from V2-only (1752 features) to V2 + event-axial + unsigned-asymmetry
(~3372 features). Per-fold K=500 LightGBM-importance selection picks the best
features inside each fold; nothing fits on outer-test data.

Origin of the new caches (codex+gemini consilience):
- event_axial_features.csv (450 cols): axial sensors × directional channels
  (Pitch/Yaw/FreeAcc_U) gated to GeneralEvent windows (Sitting, SitToStand, Walk,
  Turn, TurnToSit) per task. Mechanism: V2 magnitude features erase direction;
  T3 is axial-heavy; event-gating strips background noise.
- unsigned_asymmetry_features.csv (1170 cols): max(L,R) and min(L,R) of every
  L/R-paired V2 feature. Encodes most-affected vs least-affected limb without
  requiring cohort-aligned dominance (the failure mode of signed L-R asymmetry).

Two modes: --mode {screen,lockbox}. screen = 5-fold (3 seeds × cache configs);
lockbox = single LOOCV on pre-registered config.
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
    FoldNormalizer,
    ccc as ccc_fn,
    full_metrics,
    mae as mae_fn,
    pearson_r,
)
from project_paths import RESULTS_DIR, ensure_dir
from run_t3_iter3 import load_full_pd_data, get_hy_features
from run_t3_iter2 import impute_fold, feature_select_fold, train_lgb
from run_t3_iter5_clinical import (
    CLINICAL_COLS_CONTINUOUS,
    CLINICAL_COLS_BINARY,
    FEATURE_SETS as CLINICAL_FEATURE_SETS,
    PUBLISHED_HY_RESIDUAL_CCC,
    build_stage1_features,
    fit_stage1,
    load_clinical_dict,
    kfold_split,
)

ensure_dir(RESULTS_DIR)
SEEDS = [42, 1337, 7]
ITER5_LOCKBOX_CCC = 0.5227  # iter5 canonical headline (apples-to-apples comparator)

EVENT_AXIAL_CACHE = RESULTS_DIR / "event_axial_features.csv"
UNSIGNED_ASYM_CACHE = RESULTS_DIR / "unsigned_asymmetry_features.csv"


# ── Cache loaders aligned to the canonical SID order ─────────────────────────


def _load_cache_aligned(cache_path: Path, sids: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Load a per-subject cache CSV and align rows to the given SID order.
    Returns (X, feat_cols). Missing subjects get NaN rows."""
    if not cache_path.exists():
        raise FileNotFoundError(f"Required cache missing: {cache_path}")
    df = pd.read_csv(cache_path).set_index("sid")
    feat_cols = [c for c in df.columns]
    X = np.full((len(sids), len(feat_cols)), np.nan, dtype=np.float64)
    matched = 0
    for i, sid in enumerate(sids):
        if sid in df.index:
            X[i] = df.loc[sid, feat_cols].to_numpy(dtype=np.float64)
            matched += 1
    print(
        f"  Cache {cache_path.name}: matched {matched}/{len(sids)} subjects, "
        f"{len(feat_cols)} features",
        flush=True,
    )
    return X, feat_cols


# ── Cache subset configs ─────────────────────────────────────────────────────


CACHE_SETS: dict[str, list[Path]] = {
    "B0_v2_only": [],  # baseline reproduction (= iter5)
    "B1_v2_event_axial": [EVENT_AXIAL_CACHE],
    "B2_v2_unsigned_asym": [UNSIGNED_ASYM_CACHE],
    "B3_v2_event_axial_unsigned_asym": [EVENT_AXIAL_CACHE, UNSIGNED_ASYM_CACHE],
}


def build_stage2_X(sids: np.ndarray, X_v2: np.ndarray, fc_v2: list[str], cache_set: str) -> tuple[np.ndarray, list[str]]:
    """Concat V2 with extra IMU caches. Returns (X_stage2, feat_cols)."""
    parts = [X_v2]
    cols = list(fc_v2)
    for cache_path in CACHE_SETS[cache_set]:
        Xc, fc_c = _load_cache_aligned(cache_path, sids)
        parts.append(Xc)
        # Prefix to keep names unique and traceable to source cache
        prefix = cache_path.stem.replace("_features", "") + "::"
        cols.extend(prefix + c for c in fc_c)
    return np.column_stack(parts), cols


# ── Pipeline (mirrors iter5; only Stage 2 X changes) ─────────────────────────


def imu_residual_loocv(
    seed: int, feature_set: str, cache_set: str, alpha: float = 1.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sids, X_v2, fc_v2, y_t3, hy, obs = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, CLINICAL_FEATURE_SETS[feature_set])
    X_s2, fc_s2 = build_stage2_X(sids, X_v2, fc_v2, cache_set)
    print(
        f"  Stage1 features = {X_s1.shape[1]}, Stage2 features (post-concat) = {X_s2.shape[1]}",
        flush=True,
    )
    preds = np.zeros(n)
    loo = LeaveOneOut()
    t0 = time.time()
    for fold_idx, (tr, te) in enumerate(loo.split(np.arange(n))):
        s1_pred_tr, s1_pred_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=alpha)
        residual_tr = y_t3[tr] - s1_pred_tr
        Xtr, Xte = impute_fold(X_s2[tr], X_s2[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        s2_pred_te = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        preds[te] = s1_pred_te + s2_pred_te
        if (fold_idx + 1) % 10 == 0:
            print(
                f"  [{cache_set} seed={seed}] fold {fold_idx+1}/{n}, elapsed {time.time()-t0:.1f}s",
                flush=True,
            )
    return sids, y_t3, preds


def imu_residual_kfold(seed: int, feature_set: str, cache_set: str, alpha: float = 1.0) -> np.ndarray:
    sids, X_v2, fc_v2, y_t3, hy, obs = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1, _ = build_stage1_features(hy, clinical, CLINICAL_FEATURE_SETS[feature_set])
    X_s2, _ = build_stage2_X(sids, X_v2, fc_v2, cache_set)
    preds = np.zeros(n)
    splits = kfold_split(n, n_splits=5, seed=seed)
    for tr, te in splits:
        s1_pred_tr, s1_pred_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=alpha)
        residual_tr = y_t3[tr] - s1_pred_tr
        Xtr, Xte = impute_fold(X_s2[tr], X_s2[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        s2_pred_te = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        preds[te] = s1_pred_te + s2_pred_te
    return preds


# ── Screening ────────────────────────────────────────────────────────────────


def run_screen(
    feature_set: str = "A3_tier1", alpha: float = 1.0, seeds: tuple[int, ...] = (42, 1337, 7)
) -> pd.DataFrame:
    print(
        f"\n=== T3 iter6 5-FOLD SCREEN (Stage1={feature_set}, alpha={alpha}, "
        f"{len(seeds)} seeds × {len(CACHE_SETS)} cache sets) ===\n"
        f"Iter5 canonical LOOCV CCC = {ITER5_LOCKBOX_CCC} (apples-to-apples reference).",
        flush=True,
    )
    rows: list[dict] = []
    for cs in CACHE_SETS:
        ccc_per_seed: list[float] = []
        for seed in seeds:
            t0 = time.time()
            sids, X_v2, fc_v2, y_t3, hy, obs = load_full_pd_data()
            preds = imu_residual_kfold(seed, feature_set, cs, alpha=alpha)
            elapsed = time.time() - t0
            c = ccc_fn(y_t3, preds)
            ccc_per_seed.append(c)
            rows.append(
                {
                    "cache_set": cs,
                    "feature_set": feature_set,
                    "alpha": alpha,
                    "seed": seed,
                    "ccc": round(c, 4),
                    "mae": round(mae_fn(y_t3, preds), 3),
                    "r": round(pearson_r(y_t3, preds), 4),
                    "wall_time_s": round(elapsed, 1),
                }
            )
        print(
            f"  {cs:38s}  5-fold CCC = {np.mean(ccc_per_seed):.4f} ± {np.std(ccc_per_seed):.4f}",
            flush=True,
        )
    df = pd.DataFrame(rows)
    out_csv = RESULTS_DIR / "t3_iter6_imu_5fold_screen.csv"
    df.to_csv(out_csv, index=False)
    print(f"Wrote {out_csv}", flush=True)
    means = df.groupby("cache_set")["ccc"].mean().sort_values(ascending=False)
    print("\nMean 5-fold CCC ranking:", flush=True)
    for cs, m in means.items():
        print(f"  {cs:38s}  {m:.4f}", flush=True)
    print(f"\nRecommended lockbox cache_set: {means.index[0]}", flush=True)
    return df


# ── Lockbox LOOCV ────────────────────────────────────────────────────────────


def run_lockbox(
    cache_set: str,
    feature_set: str = "A3_tier1",
    alpha: float = 1.0,
    seeds: tuple[int, ...] = (42, 1337, 7),
) -> dict:
    if cache_set not in CACHE_SETS:
        raise ValueError(f"Unknown cache_set {cache_set!r}; choose from {list(CACHE_SETS)}")
    extras = [p.name for p in CACHE_SETS[cache_set]]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    prereg = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "experiment": "T3 iter6 — IMU feature additions on top of iter5 architecture",
        "cache_set": cache_set,
        "stage2_extra_caches": extras,
        "feature_set_stage1": feature_set,
        "alpha": alpha,
        "n_subjects": 98,
        "eval_protocol": (
            "LOOCV (n=98), Stage-1 Ridge with intercept + per-fold standardisation. "
            "Stage-2 LGB on V2 + extra IMU caches (event-axial, unsigned-asymmetry). "
            "Per-fold K=500 LGB-importance selection inside each fold. "
            "3-seed mean preds = headline."
        ),
        "headline_metric": "CCC of mean-of-3-seed predictions",
        "lockbox_rules": [
            "ONE config pre-registered. ONE LOOCV run. Headline = result, no cherry-picking.",
            f"Apples-to-apples baseline: iter5 LOOCV CCC = {ITER5_LOCKBOX_CCC} (same N=98).",
            "Stage 1 + Stage 2 architecture identical to iter5 except for added Stage 2 features.",
            "If LOOCV CCC <= iter5 + 0.005 (within noise), report as null result; do not select runner-up.",
            "Bootstrap CI of (iter6 - iter5) on the same 98 subjects must straddle zero LESS than 30% to claim significance.",
        ],
        "feature_safety_argument": (
            "event_axial: extracted from raw IMU + GeneralEvent annotations recorded during the "
            "same gait session as the UPDRS-III rating. Same safety status as V2 (raw signal, "
            "no derivation from rated scores). unsigned_asymmetry: derived from existing V2 "
            "features by max/min L/R aggregation; no new external information."
        ),
    }
    prereg_path = RESULTS_DIR / f"preregistration_t3_iter6_{ts}.json"
    with open(prereg_path, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {prereg_path}", flush=True)

    print(
        f"\n=== T3 iter6 LOCKBOX LOOCV ({cache_set}, alpha={alpha}, "
        f"extras={extras}, {len(seeds)} seeds) ===",
        flush=True,
    )
    all_preds = []
    sids_ref = None
    y_t3_ref = None
    for seed in seeds:
        t0 = time.time()
        sids, y_t3, preds = imu_residual_loocv(
            seed=seed, feature_set=feature_set, cache_set=cache_set, alpha=alpha
        )
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
    headline = full_metrics(y_t3_ref, mean_preds, label=f"t3_iter6_{cache_set}")

    # Bootstrap CI of (iter6 - iter5) — load iter5 OOF for the comparator
    iter5_files = sorted((RESULTS_DIR).glob("lockbox_t3_iter5_A3_tier1_*.json"))
    if not iter5_files:
        raise FileNotFoundError("Cannot find iter5 lockbox JSON for bootstrap baseline")
    with open(iter5_files[-1]) as f:
        iter5 = json.load(f)
    assert iter5.get("eval_mode") == "loocv_3seed_mean", (
        f"iter5 comparator must be loocv_3seed_mean; found {iter5.get('eval_mode')!r}"
    )
    sid_to_iter5 = dict(zip(iter5["per_subject"]["sids"], iter5["per_subject"]["y_pred"]))
    iter5_preds_aligned = np.array([sid_to_iter5[str(s)] for s in sids_ref])
    iter5_ccc_on_ref = float(ccc_fn(y_t3_ref, iter5_preds_aligned))

    rng = np.random.RandomState(42)
    n_boot = 2000
    deltas = []
    for _ in range(n_boot):
        idx = rng.randint(0, len(y_t3_ref), size=len(y_t3_ref))
        d = ccc_fn(y_t3_ref[idx], mean_preds[idx]) - ccc_fn(y_t3_ref[idx], iter5_preds_aligned[idx])
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
            "cache_set": cache_set,
            "stage2_extra_caches": extras,
            "feature_set_stage1": feature_set,
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
            "baseline_iter5_ccc_on_same_98": round(iter5_ccc_on_ref, 4),
            "baseline_published_hy_residual_ccc": PUBLISHED_HY_RESIDUAL_CCC,
            "delta_vs_iter5": round(float(headline["ccc"]) - iter5_ccc_on_ref, 4),
            "bootstrap_delta_vs_iter5": boot,
        }
    )
    out_json = RESULTS_DIR / f"lockbox_t3_iter6_{cache_set}_{ts}.json"
    out_npy = RESULTS_DIR / f"lockbox_t3_iter6_{cache_set}_{ts}.oof.npy"
    np.save(out_npy, mean_preds)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)

    print(
        f"\n=== HEADLINE (lockbox): CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f}, "
        f"r={headline['r']:.4f}, slope={headline['cal_slope']:.3f} ===",
        flush=True,
    )
    print(f"  Δ vs iter5 on same N=98: {headline['delta_vs_iter5']:+.4f}", flush=True)
    print(
        f"  Bootstrap (n={n_boot}): mean Δ={boot['delta_mean']:+.4f}, "
        f"95% CI=[{boot['delta_ci_low']:+.4f}, {boot['delta_ci_high']:+.4f}], "
        f"frac > 0 = {boot['frac_positive']}, frac > 0.01 = {boot['frac_above_0p01']}",
        flush=True,
    )
    print(f"Wrote {out_json}\nWrote {out_npy}", flush=True)
    return headline


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["screen", "lockbox"], required=True)
    p.add_argument("--cache_set", default="B3_v2_event_axial_unsigned_asym")
    p.add_argument("--feature_set", default="A3_tier1")
    p.add_argument("--alpha", type=float, default=1.0)
    p.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    args = p.parse_args()

    if args.mode == "screen":
        run_screen(feature_set=args.feature_set, alpha=args.alpha, seeds=tuple(args.seeds))
    else:
        run_lockbox(
            cache_set=args.cache_set,
            feature_set=args.feature_set,
            alpha=args.alpha,
            seeds=tuple(args.seeds),
        )


if __name__ == "__main__":
    main()

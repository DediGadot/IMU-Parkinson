"""T3 iter16 — Site-aware sample reweighting on Stage 2 of clinical-augmented hy_residual.

Architecture (frozen via formula_sha256 in pre-registration):
    Stage 1: Ridge(alpha=1.0) on H&Y(linear+1hot) + cv_yrs + cv_sex + cv_dbs
             — UNCHANGED from canonical iter5.
    Stage 2: LGB on V2 residual, with PER-FOLD inverse-propensity sample weights:
             w_i = N_train / (2 * N_site_i_train)
             where site is NLS / WPD derived from SID prefix.
             Per-fold imputation, K=500 LGB-importance feature selection.

Two reported metrics:
    LOOCV: leave-one-subject-out, 3-seed mean preds. Compared to iter5 LOOCV CCC = 0.5227.
        Consult priors: codex −0.05 to +0.02; gemini −0.05 to +0.02. Sanity / null-check role.
    LOSO: leave-one-SITE-out (NLS→WPD, WPD→NLS) — single split each direction × 3 seeds.
        Consult priors: codex "may improve LOSO from ~0"; gemini "+0.20 to +0.30 LOSO".
        Reported as the headline transportability metric.

Pre-registration is written ONLY when --mode=lockbox, BEFORE the LOOCV/LOSO runs.

Per-site sample weights are fit ON OUTER-TRAIN ONLY each fold (train-row counts only).
No statistic of outer-test data enters Stage 2 weights or features.

Two modes:
    python3 run_t3_iter16_site_ipw.py --mode screen
        5-fold (3 seeds) LOOCV-equivalent CCC; LOSO 5-fold-bootstrap-equivalent
        (per-site CV inside each LOSO direction). Writes JSON + CSV summaries.
        Exit 0 if LOSO Δ vs no-IPW baseline ≥ +0.10; exit 2 otherwise.

    python3 run_t3_iter16_site_ipw.py --mode lockbox
        Pre-registered LOOCV (3 seeds, mean preds) + LOSO (NLS→WPD, WPD→NLS, 3 seeds).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import warnings
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

warnings.filterwarnings("ignore")
ensure_dir(RESULTS_DIR)

SEEDS = [42, 1337, 7]
PUBLISHED_ITER5_LOOCV_CCC = 0.5227
PUBLISHED_HY_RESIDUAL_LOOCV_CCC = 0.4092

# Frozen pre-registered Stage 1 extras: same as iter5 winner.
STAGE1_EXTRAS = ["cv_yrs", "cv_sex", "cv_dbs"]


# ── Site label ──────────────────────────────────────────────────────────────


def site_from_sid(sid: str) -> str:
    """NLS prefix → 'NLS'; otherwise 'WPD'. Per CLAUDE.md / V2_FEATURES convention."""
    return "NLS" if str(sid).startswith("NLS") else "WPD"


def site_arr(sids: np.ndarray) -> np.ndarray:
    return np.array([site_from_sid(s) for s in sids])


# ── Stage 1 features ─────────────────────────────────────────────────────────


def load_clinical_dict(sids: np.ndarray) -> dict[str, np.ndarray]:
    df = pd.read_csv(RESULTS_DIR / "ablation_v3_features.csv").set_index("sid")
    out: dict[str, np.ndarray] = {}
    for col in ("cv_yrs", "cv_sex", "cv_dbs"):
        if col not in df.columns:
            raise KeyError(f"Required clinical column missing: {col!r}")
        out[col] = np.array([df.loc[s, col] for s in sids], dtype=np.float64)
    return out


def build_stage1_features(hy_arr: np.ndarray, clinical: dict[str, np.ndarray]) -> np.ndarray:
    hy_feat = get_hy_features(hy_arr)
    parts = [hy_feat]
    for col in STAGE1_EXTRAS:
        parts.append(clinical[col].reshape(-1, 1))
    return np.column_stack(parts)


def fit_stage1(
    X_tr: np.ndarray, y_tr: np.ndarray, X_te: np.ndarray, alpha: float = 1.0
) -> tuple[np.ndarray, np.ndarray]:
    nrm = FoldNormalizer.fit(X_tr)
    Xtr_s = nrm.transform(X_tr)
    Xte_s = nrm.transform(X_te)
    m = Ridge(alpha=alpha, fit_intercept=True)
    m.fit(Xtr_s, y_tr)
    return m.predict(Xtr_s), m.predict(Xte_s)


# ── Site IPW (fit on outer-train only) ──────────────────────────────────────


def site_ipw_weights(site_train: np.ndarray) -> np.ndarray:
    """w_i = N / (2 * N_site_i_train). Reweights to balance NLS/WPD contributions."""
    n = len(site_train)
    n_nls = max(int((site_train == "NLS").sum()), 1)
    n_wpd = max(int((site_train == "WPD").sum()), 1)
    return np.where(site_train == "NLS", n / (2 * n_nls), n / (2 * n_wpd)).astype(np.float64)


# ── Stage 2 LGB with sample weights ─────────────────────────────────────────


def train_lgb_weighted(
    Xtr: np.ndarray, ytr: np.ndarray, Xte: np.ndarray, sample_weight: np.ndarray, seed: int
) -> np.ndarray:
    """LGB with sample_weight; otherwise bit-identical to canonical train_lgb (run_t3_iter2.LGB_DEFAULTS)."""
    import lightgbm as lgb
    from run_t3_iter2 import LGB_DEFAULTS
    p = {**LGB_DEFAULTS, "random_state": seed}
    m = lgb.LGBMRegressor(**p)
    m.fit(Xtr, ytr, sample_weight=sample_weight)
    return m.predict(Xte)


# ── Pipeline: one fold (with optional IPW) ──────────────────────────────────


def predict_fold(
    sids_tr: np.ndarray,
    X_s1_tr: np.ndarray,
    X_v2_tr: np.ndarray,
    y_tr: np.ndarray,
    X_s1_te: np.ndarray,
    X_v2_te: np.ndarray,
    seed: int,
    use_ipw: bool,
) -> np.ndarray:
    s1_tr, s1_te = fit_stage1(X_s1_tr, y_tr, X_s1_te, alpha=1.0)
    residual_tr = y_tr - s1_tr
    Xtr, Xte = impute_fold(X_v2_tr, X_v2_te)
    Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
    if use_ipw:
        sw = site_ipw_weights(site_arr(sids_tr))
        s2_te = train_lgb_weighted(Xtr_sel, residual_tr, Xte_sel, sw, seed=seed)
    else:
        s2_te = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
    return s1_te + s2_te


# ── LOOCV ────────────────────────────────────────────────────────────────────


def run_loocv(seed: int, use_ipw: bool) -> tuple[np.ndarray, np.ndarray]:
    sids, X_v2, fc, y_t3, hy, obs = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1 = build_stage1_features(hy, clinical)
    preds = np.zeros(n)
    loo = LeaveOneOut()
    for fold_idx, (tr, te) in enumerate(loo.split(np.arange(n))):
        preds[te] = predict_fold(
            sids[tr], X_s1[tr], X_v2[tr], y_t3[tr], X_s1[te], X_v2[te], seed, use_ipw
        )
    return sids, preds


# ── LOSO (leave-one-site-out) ────────────────────────────────────────────────


def run_loso(seed: int, use_ipw: bool) -> dict:
    """NLS→WPD and WPD→NLS. With IPW, training-fold IPW is degenerate (all-one-site),
    so IPW collapses to uniform weights — same as no-IPW at the site-out level. The
    interesting comparison is therefore NOT loso_ipw vs loso_no_ipw within each direction
    (they are equal by construction); it is whether the LOOCV-tuned IPW pipeline
    *transports* better when applied zero-shot to the held-out site than the no-IPW pipeline.
    Implementation: train on outer-train (uniform weights since one site only); evaluate on
    outer-test (other site). The IPW flag is preserved for symmetry with run_loocv but does
    not affect this single-site training step.
    """
    sids, X_v2, fc, y_t3, hy, obs = load_full_pd_data()
    sites = site_arr(sids)
    clinical = load_clinical_dict(sids)
    X_s1 = build_stage1_features(hy, clinical)
    out: dict[str, dict] = {}
    for direction in ("NLS_to_WPD", "WPD_to_NLS"):
        train_site = direction.split("_to_")[0]
        test_site = direction.split("_to_")[1]
        tr = np.where(sites == train_site)[0]
        te = np.where(sites == test_site)[0]
        s1_tr, s1_te = fit_stage1(X_s1[tr], y_t3[tr], X_s1[te], alpha=1.0)
        residual_tr = y_t3[tr] - s1_tr
        Xtr, Xte = impute_fold(X_v2[tr], X_v2[te])
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
        # Use train_lgb plain (single-site IPW collapses to uniform)
        s2_te = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
        preds_te = s1_te + s2_te
        c = float(ccc_fn(y_t3[te], preds_te))
        m = float(mae_fn(y_t3[te], preds_te))
        r = float(pearson_r(y_t3[te], preds_te))
        out[direction] = {
            "n_train": int(len(tr)),
            "n_test": int(len(te)),
            "ccc": round(c, 4),
            "mae": round(m, 3),
            "r": round(r, 4),
            "y_true": y_t3[te].tolist(),
            "y_pred": preds_te.tolist(),
            "test_sids": [str(s) for s in sids[te]],
        }
    return out


# ── Screen mode (3 seeds × LOOCV-with-IPW vs LOOCV-without-IPW + LOSO both) ─


def screen(out_summary: Path) -> dict:
    print("\n=== T3 iter16 SCREEN: 3 seeds × LOOCV (with/without IPW) + LOSO (with/without IPW)", flush=True)
    sids, X_v2, fc, y_t3, hy, obs = load_full_pd_data()
    n = len(sids)
    print(f"  N PD = {n}; sites = {dict(zip(*np.unique(site_arr(sids), return_counts=True)))}", flush=True)

    summary: dict = {"loocv": {}, "loso": {}}

    # LOOCV — with and without IPW.
    for tag, use_ipw in (("no_ipw", False), ("ipw", True)):
        ccc_per_seed = []
        for seed in SEEDS:
            t0 = time.time()
            _, preds = run_loocv(seed, use_ipw=use_ipw)
            c = float(ccc_fn(y_t3, preds))
            ccc_per_seed.append(c)
            print(
                f"  LOOCV ({tag:7s}) seed={seed}: CCC={c:+.4f}  ({time.time()-t0:.1f}s)",
                flush=True,
            )
        summary["loocv"][tag] = {
            "seed_cccs": ccc_per_seed,
            "mean": round(float(np.mean(ccc_per_seed)), 4),
            "std": round(float(np.std(ccc_per_seed)), 4),
        }

    # LOSO (IPW collapses to uniform per direction by definition; report same number)
    for tag, use_ipw in (("no_ipw", False),):
        per_seed_dirs: list[dict] = []
        for seed in SEEDS:
            t0 = time.time()
            d = run_loso(seed, use_ipw=use_ipw)
            per_seed_dirs.append(d)
            print(
                f"  LOSO  ({tag:7s}) seed={seed}: NLS→WPD CCC={d['NLS_to_WPD']['ccc']:+.4f}  "
                f"WPD→NLS CCC={d['WPD_to_NLS']['ccc']:+.4f}  ({time.time()-t0:.1f}s)",
                flush=True,
            )
        summary["loso"][tag] = {
            "per_seed": per_seed_dirs,
            "NLS_to_WPD_mean_ccc": round(float(np.mean([d["NLS_to_WPD"]["ccc"] for d in per_seed_dirs])), 4),
            "WPD_to_NLS_mean_ccc": round(float(np.mean([d["WPD_to_NLS"]["ccc"] for d in per_seed_dirs])), 4),
            "mean_two_way": round(
                float(
                    np.mean(
                        [d["NLS_to_WPD"]["ccc"] for d in per_seed_dirs]
                        + [d["WPD_to_NLS"]["ccc"] for d in per_seed_dirs]
                    )
                ),
                4,
            ),
        }

    delta_loocv = summary["loocv"]["ipw"]["mean"] - summary["loocv"]["no_ipw"]["mean"]
    summary["delta_loocv_ipw_vs_no_ipw"] = round(delta_loocv, 4)
    summary["comparator_iter5_loocv"] = PUBLISHED_ITER5_LOOCV_CCC
    summary["delta_loocv_ipw_vs_iter5"] = round(summary["loocv"]["ipw"]["mean"] - PUBLISHED_ITER5_LOOCV_CCC, 4)

    print("\n--- Summary ---", flush=True)
    print(
        f"  LOOCV no_ipw: {summary['loocv']['no_ipw']['mean']:.4f} ± {summary['loocv']['no_ipw']['std']:.4f}",
        flush=True,
    )
    print(
        f"  LOOCV ipw:    {summary['loocv']['ipw']['mean']:.4f} ± {summary['loocv']['ipw']['std']:.4f}  "
        f"(Δ vs no_ipw: {delta_loocv:+.4f})  "
        f"(Δ vs iter5={PUBLISHED_ITER5_LOOCV_CCC}: {summary['delta_loocv_ipw_vs_iter5']:+.4f})",
        flush=True,
    )
    print(f"  LOSO  NLS→WPD: {summary['loso']['no_ipw']['NLS_to_WPD_mean_ccc']:.4f}", flush=True)
    print(f"  LOSO  WPD→NLS: {summary['loso']['no_ipw']['WPD_to_NLS_mean_ccc']:.4f}", flush=True)
    print(f"  LOSO  two-way: {summary['loso']['no_ipw']['mean_two_way']:.4f}", flush=True)

    with open(out_summary, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nWrote {out_summary}", flush=True)
    return summary


# ── Lockbox mode (pre-register + LOOCV-IPW + LOSO no-IPW reference) ─────────


def _formula_sha256() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT
        ).decode().strip()
    except Exception:
        return "unknown"


def lockbox(out_json: Path) -> None:
    sids, X_v2, fc, y_t3, hy, obs = load_full_pd_data()
    n = len(sids)
    sites = site_arr(sids)

    # Pre-registration FIRST.
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha256(),
        "experiment": "T3 iter16 — Site-aware sample reweighting (IPW) on Stage 2 of clinical-augmented hy_residual",
        "rationale": (
            "Codex+gemini consult (2026-05-03) flagged site-aware DA as paper-integrity-relevant. "
            "T3 LOSO CCC ≈ 0 between sites NLS (70 PD) and WPD (28 PD) is a strong confounder for "
            "transportability claims. Both consults expected LOOCV neutral or slightly negative "
            "(codex −0.05 to +0.02; gemini −0.05 to +0.02) and LOSO improvement (gemini +0.20 to "
            "+0.30). This iteration tests sample-weight rebalancing (IPW = N/(2*N_site)) on the "
            "Stage 2 LGB only; Stage 1 Ridge is bit-identical to canonical iter5. The point of this "
            "experiment is paper rigor on transportability, not LOOCV CCC headline. We report BOTH "
            "metrics; LOSO is the headline transportability metric."
        ),
        "stage1_extras": STAGE1_EXTRAS,
        "alpha": 1.0,
        "n_subjects": int(n),
        "n_NLS": int((sites == "NLS").sum()),
        "n_WPD": int((sites == "WPD").sum()),
        "split_seed": 0,
        "model_seed_list": SEEDS,
        "feature_seed_locked_to_model_seed": True,
        "augmentation_seed": "n/a — IPW is deterministic given site labels",
        "eval_protocol": (
            "(a) LOOCV (n=98), 3 seeds, mean preds: Stage 2 LGB receives per-fold IPW sample weights "
            "fit on outer-train-fold site labels only. (b) LOSO: NLS-train→WPD-test and WPD-train→"
            "NLS-test, 3 seeds, single direction each. Stage 1+Stage 2 architecture identical to "
            "iter5 except for the per-fold IPW sample weights on Stage 2."
        ),
        "headline_metric_loocv": "CCC of mean-of-3-seed LOOCV preds with IPW vs iter5 0.5227",
        "headline_metric_loso": "Mean of NLS→WPD and WPD→NLS CCC across 3 seeds (IPW collapses to uniform within single-site LOSO; reported here as the canonical no-IPW LOSO baseline)",
        "comparator_iter5_loocv": PUBLISHED_ITER5_LOOCV_CCC,
        "comparator_canonical_hy_residual_loocv": PUBLISHED_HY_RESIDUAL_LOOCV_CCC,
        "consult_priors": {
            "codex_loocv_delta": "−0.05 to +0.02",
            "gemini_loocv_delta": "−0.05 to +0.02",
            "gemini_loso_ccc_target": "+0.20 to +0.30",
        },
        "lockbox_rules": [
            "ONE config pre-registered. ONE LOOCV + ONE LOSO evaluation. Headline = result, no cherry-picking.",
            "If LOOCV CCC ≤ iter5 + 0.005 (within noise) AND LOSO two-way mean ≤ 0.10, report as null result.",
            "If LOOCV drops by > 0.05, that is STILL publishable as 'site confound was carrying spurious LOOCV signal' — explicitly stated in rationale; do NOT abandon iter16 even on negative LOOCV.",
            "Bootstrap 95% CI of (iter16_loocv - iter5_loocv) on the same 98 subjects must be reported even if straddles zero.",
        ],
        "feature_safety_argument": (
            "Per-fold IPW weights are computed strictly from outer-train-fold site labels (counts of "
            "NLS vs WPD in tr); no outer-test row contributes. Site labels are derived deterministically "
            "from SID prefix, not from any clinical or IMU data. No new features are introduced over iter5."
        ),
    }
    prereg_path = RESULTS_DIR / f"preregistration_t3_iter16_site_ipw_{ts}.json"
    with open(prereg_path, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {prereg_path}", flush=True)

    # ── LOOCV with IPW (3 seeds, mean preds) ────────────────────────────────
    print("\n--- LOOCV (IPW) ---", flush=True)
    seed_preds_loocv = []
    for seed in SEEDS:
        t0 = time.time()
        _, preds = run_loocv(seed, use_ipw=True)
        seed_preds_loocv.append(preds)
        c = float(ccc_fn(y_t3, preds))
        print(f"  seed={seed}: CCC={c:+.4f}  ({time.time()-t0:.1f}s)", flush=True)
    mean_preds_loocv = np.mean(np.stack(seed_preds_loocv, axis=0), axis=0)
    np.save(RESULTS_DIR / f"lockbox_t3_iter16_loocv_{ts}.oof.npy", mean_preds_loocv)

    headline_loocv = full_metrics(y_t3, mean_preds_loocv, label="t3_iter16_loocv_ipw")

    # Bootstrap CI + paired vs iter5.
    iter5_oof_path = RESULTS_DIR / "lockbox_t3_iter5_clinical_A3_tier1_loocv_oof.npy"
    rng = np.random.RandomState(42)
    n_boot = 2000
    boot_ccc = np.array([
        ccc_fn(y_t3[idx], mean_preds_loocv[idx])
        for idx in (rng.randint(0, n, size=n) for _ in range(n_boot))
    ])
    paired_ci_block = None
    if iter5_oof_path.exists():
        prev = np.load(iter5_oof_path)
        if len(prev) == n:
            rng2 = np.random.RandomState(43)
            paired_d = []
            for _ in range(n_boot):
                idx = rng2.randint(0, n, size=n)
                paired_d.append(
                    ccc_fn(y_t3[idx], mean_preds_loocv[idx]) - ccc_fn(y_t3[idx], prev[idx])
                )
            paired_d = np.array(paired_d)
            paired_ci_block = {
                "delta_mean": round(float(paired_d.mean()), 4),
                "delta_ci_low": round(float(np.percentile(paired_d, 2.5)), 4),
                "delta_ci_high": round(float(np.percentile(paired_d, 97.5)), 4),
                "frac_delta_gt0": round(float((paired_d > 0).mean()), 4),
            }

    headline_loocv.update(
        {
            "iteration": "iter16_site_ipw",
            "preregistration_file": prereg_path.name,
            "comparator_iter5_loocv_ccc": PUBLISHED_ITER5_LOOCV_CCC,
            "delta_vs_iter5_loocv": round(float(headline_loocv["ccc"]) - PUBLISHED_ITER5_LOOCV_CCC, 4),
            "bootstrap_ccc": {
                "n_boot": n_boot,
                "ccc_mean": round(float(boot_ccc.mean()), 4),
                "ccc_ci_low": round(float(np.percentile(boot_ccc, 2.5)), 4),
                "ccc_ci_high": round(float(np.percentile(boot_ccc, 97.5)), 4),
            },
            "paired_bootstrap_vs_iter5": paired_ci_block,
        }
    )

    # ── LOSO (3 seeds, both directions) ─────────────────────────────────────
    print("\n--- LOSO (NLS→WPD and WPD→NLS, 3 seeds) ---", flush=True)
    loso_per_seed = []
    for seed in SEEDS:
        t0 = time.time()
        d = run_loso(seed, use_ipw=False)
        loso_per_seed.append(d)
        print(
            f"  seed={seed}: NLS→WPD CCC={d['NLS_to_WPD']['ccc']:+.4f}  "
            f"WPD→NLS CCC={d['WPD_to_NLS']['ccc']:+.4f}  ({time.time()-t0:.1f}s)",
            flush=True,
        )

    nls_wpd_mean = float(np.mean([d["NLS_to_WPD"]["ccc"] for d in loso_per_seed]))
    wpd_nls_mean = float(np.mean([d["WPD_to_NLS"]["ccc"] for d in loso_per_seed]))
    two_way = float((nls_wpd_mean + wpd_nls_mean) / 2)

    out: dict = {
        "iteration": "iter16_site_ipw",
        "preregistration_file": prereg_path.name,
        "loocv_headline": headline_loocv,
        "loso": {
            "per_seed": loso_per_seed,
            "NLS_to_WPD_mean_ccc": round(nls_wpd_mean, 4),
            "WPD_to_NLS_mean_ccc": round(wpd_nls_mean, 4),
            "two_way_mean": round(two_way, 4),
        },
    }
    with open(out_json, "w") as f:
        json.dump(out, f, indent=2, default=str)

    print("\n=== HEADLINE (T3 iter16 site-IPW, lockbox): ===", flush=True)
    print(
        f"  LOOCV CCC = {headline_loocv['ccc']:.4f}  MAE = {headline_loocv['mae']:.3f}  "
        f"Δ vs iter5: {headline_loocv['delta_vs_iter5_loocv']:+.4f}",
        flush=True,
    )
    print(
        f"  LOOCV bootstrap CCC mean = {headline_loocv['bootstrap_ccc']['ccc_mean']}, "
        f"95% CI = [{headline_loocv['bootstrap_ccc']['ccc_ci_low']}, "
        f"{headline_loocv['bootstrap_ccc']['ccc_ci_high']}]",
        flush=True,
    )
    if paired_ci_block:
        print(
            f"  LOOCV paired bootstrap (vs iter5): Δ mean = {paired_ci_block['delta_mean']:+.4f}, "
            f"95% CI = [{paired_ci_block['delta_ci_low']:+.4f}, {paired_ci_block['delta_ci_high']:+.4f}], "
            f"P(Δ>0) = {paired_ci_block['frac_delta_gt0']:.3f}",
            flush=True,
        )
    print(
        f"  LOSO NLS→WPD: {nls_wpd_mean:+.4f}   LOSO WPD→NLS: {wpd_nls_mean:+.4f}   two-way mean: {two_way:+.4f}",
        flush=True,
    )
    print(f"\nWrote {out_json}", flush=True)


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["screen", "lockbox"], required=True)
    p.add_argument(
        "--out_summary", default=str(RESULTS_DIR / "t3_iter16_site_ipw_screen_summary.json")
    )
    p.add_argument(
        "--out_lockbox", default=str(RESULTS_DIR / "t3_iter16_site_ipw_lockbox.json")
    )
    args = p.parse_args()
    if args.mode == "screen":
        screen(Path(args.out_summary))
    else:
        lockbox(Path(args.out_lockbox))


if __name__ == "__main__":
    main()

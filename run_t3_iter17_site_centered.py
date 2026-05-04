"""T3 iter17 — Site-centered Stage 2 of clinical-augmented hy_residual.

Phase A3 of the 100x researcher CCC-push (2026-05-03 PM, see task_plan.md ACTIVE MISSION).

Architecture (all relative to iter5 / iter16):
  Stage 1 (Ridge, alpha=1.0): T3 ~ H&Y (linear+1hot) + cv_yrs + cv_sex + cv_dbs
    BIT-IDENTICAL to iter5.

  Stage 2 (LGB on V2 IMU residual): per-fold SITE-CENTERED V2 features.
    For each outer-fold train set, we compute per-site means of every V2 feature
    column on the training fold ONLY, then SUBTRACT each subject's site mean
    from their feature row. The same per-site mean (computed on training fold)
    is applied to outer-test rows according to the test subject's site.
    This is a fold-local, label-free, train-fitted transform that removes
    site-coupled offsets (mounting variation, walkway geometry, hardware
    calibration) without label leakage.

Why this is novel:
  - iter16 tried IPW (sample-weight rebalancing). LOOCV dropped by 0.05;
    LOSO unchanged at 0.341.
  - iter17 attacks the SAME confound (site shift) at a different layer
    (feature transform vs. sample weight). The IPW failure mechanism (upweighting
    smaller-cohort noisy samples) does not apply here.
  - Per-site centering is a textbook DA technique that is NOT on the dead list.

Two metrics reported:
  (a) LOOCV CCC with site-centered Stage 2 (sensitivity / null check).
      Expected per consult priors: ±0.02 vs iter5 (small, neutral).
  (b) LOSO two-way mean CCC (NLS→WPD + WPD→NLS) — the headline transportability metric.
      Expected: +0.05 to +0.15 over iter16's 0.341 if the site-centering hypothesis holds.

Two modes:

    python3 run_t3_iter17_site_centered.py --mode screen
        3 seeds × LOOCV (with/without centering) + LOSO (with/without centering).
        Writes results/t3_iter17_site_centered_screen.json.

    python3 run_t3_iter17_site_centered.py --mode lockbox
        Pre-registers + runs ONE LOOCV + LOSO (3 seeds, mean preds).
        Writes results/preregistration_t3_iter17_site_centered_<ts>.json + lockbox files.
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
from sklearn.model_selection import LeaveOneOut

warnings.filterwarnings("ignore")

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
PUBLISHED_ITER5_LOOCV_CCC = 0.5227
PUBLISHED_ITER16_LOSO_TWO_WAY = 0.341
STAGE1_EXTRAS = ["cv_yrs", "cv_sex", "cv_dbs"]


# ── Site label ──────────────────────────────────────────────────────────────


def site_from_sid(sid: str) -> str:
    return "NLS" if str(sid).startswith("NLS") else "WPD"


def site_arr(sids: np.ndarray) -> np.ndarray:
    return np.array([site_from_sid(s) for s in sids])


# ── Stage 1 features (bit-identical to iter5) ────────────────────────────────


def load_clinical_dict(sids: np.ndarray) -> dict[str, np.ndarray]:
    df = pd.read_csv(RESULTS_DIR / "ablation_v3_features.csv").set_index("sid")
    out: dict[str, np.ndarray] = {}
    for col in STAGE1_EXTRAS:
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


# ── Site centering (the new piece) ──────────────────────────────────────────


def site_center_fold(
    X_tr: np.ndarray, sites_tr: np.ndarray, X_te: np.ndarray, sites_te: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Subtract per-site mean (computed on TRAIN ONLY) from train and test rows.

    For each site s:
      mu_s = X_tr[sites_tr == s].mean(axis=0)
    For each row i in train:  X_tr[i] -= mu_{sites_tr[i]}
    For each row i in test:   X_te[i] -= mu_{sites_te[i]}

    If a test subject's site is absent from train (LOSO), use the OVERALL train
    mean as a fallback (cross-site centering reduces to global centering for
    the missing site — this is the cleanest definition under cohort shift).
    """
    sites_unique = np.unique(sites_tr)
    site_means: dict[str, np.ndarray] = {}
    for s in sites_unique:
        mask = sites_tr == s
        if mask.sum() == 0:
            continue
        # NaN-safe per-site mean
        site_means[s] = np.nanmean(X_tr[mask], axis=0)
    # Global train mean for fallback
    global_mean = np.nanmean(X_tr, axis=0)

    Xtr_c = X_tr.copy()
    for s, mu in site_means.items():
        mask = sites_tr == s
        Xtr_c[mask] = Xtr_c[mask] - mu

    Xte_c = X_te.copy()
    for i in range(X_te.shape[0]):
        s = sites_te[i]
        mu = site_means.get(s, global_mean)
        Xte_c[i] = Xte_c[i] - mu
    return Xtr_c, Xte_c


# ── One fold (with optional site centering) ─────────────────────────────────


def predict_fold(
    sids_tr: np.ndarray,
    X_s1_tr: np.ndarray,
    X_v2_tr: np.ndarray,
    y_tr: np.ndarray,
    sids_te: np.ndarray,
    X_s1_te: np.ndarray,
    X_v2_te: np.ndarray,
    seed: int,
    use_site_centering: bool,
) -> np.ndarray:
    s1_tr, s1_te = fit_stage1(X_s1_tr, y_tr, X_s1_te, alpha=1.0)
    residual_tr = y_tr - s1_tr
    Xtr, Xte = impute_fold(X_v2_tr, X_v2_te)
    if use_site_centering:
        sites_tr = site_arr(sids_tr)
        sites_te = site_arr(sids_te)
        Xtr, Xte = site_center_fold(Xtr, sites_tr, Xte, sites_te)
    Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
    s2_te = train_lgb(Xtr_sel, residual_tr, Xte_sel, seed)
    return s1_te + s2_te


# ── LOOCV ────────────────────────────────────────────────────────────────────


def run_loocv(seed: int, use_site_centering: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sids, X_v2, fc, y_t3, hy, obs = load_full_pd_data()
    n = len(sids)
    clinical = load_clinical_dict(sids)
    X_s1 = build_stage1_features(hy, clinical)
    preds = np.zeros(n)
    loo = LeaveOneOut()
    for fold_idx, (tr, te) in enumerate(loo.split(np.arange(n))):
        preds[te] = predict_fold(
            sids[tr], X_s1[tr], X_v2[tr], y_t3[tr],
            sids[te], X_s1[te], X_v2[te],
            seed, use_site_centering,
        )
    return sids, y_t3, preds


# ── LOSO (NLS→WPD and WPD→NLS) ───────────────────────────────────────────────


def run_loso(seed: int, use_site_centering: bool) -> dict:
    """Two-way LOSO. Note: when training on a single site, site_center_fold
    sees only one site in train; site centering becomes equivalent to global
    centering (subtract the only train mean). For LOSO, the test rows use
    the TEST site's identity but fall back to the global train mean (the
    only available mean from the train fold). This is the cleanest definition
    of fold-local centering under single-site training.
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
        if use_site_centering:
            sites_tr = site_arr(sids[tr])
            sites_te = site_arr(sids[te])
            Xtr, Xte = site_center_fold(Xtr, sites_tr, Xte, sites_te)
        Xtr_sel, Xte_sel, _ = feature_select_fold(Xtr, residual_tr, Xte, k=500, seed=seed)
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


# ── Screen mode ──────────────────────────────────────────────────────────────


def screen(out_summary: Path) -> dict:
    print(
        "\n=== T3 iter17 SCREEN: 3 seeds × LOOCV (with/without site-centering) + LOSO (with/without)",
        flush=True,
    )
    sids, X_v2, fc, y_t3, hy, obs = load_full_pd_data()
    n = len(sids)
    print(
        f"  N PD = {n}; sites = "
        f"{dict(zip(*np.unique(site_arr(sids), return_counts=True)))}",
        flush=True,
    )

    summary: dict = {"loocv": {}, "loso": {}}

    # LOOCV — with and without site centering.
    for tag, use_sc in (("no_sc", False), ("site_centered", True)):
        ccc_per_seed = []
        for seed in SEEDS:
            t0 = time.time()
            _, _, preds = run_loocv(seed, use_site_centering=use_sc)
            c = float(ccc_fn(y_t3, preds))
            ccc_per_seed.append(c)
            print(
                f"  LOOCV ({tag:14s}) seed={seed}: CCC={c:+.4f}  ({time.time()-t0:.1f}s)",
                flush=True,
            )
        summary["loocv"][tag] = {
            "seed_cccs": ccc_per_seed,
            "mean": round(float(np.mean(ccc_per_seed)), 4),
            "std": round(float(np.std(ccc_per_seed)), 4),
        }

    # LOSO — with and without.
    for tag, use_sc in (("no_sc", False), ("site_centered", True)):
        per_seed_dirs: list[dict] = []
        for seed in SEEDS:
            t0 = time.time()
            d = run_loso(seed, use_site_centering=use_sc)
            per_seed_dirs.append(d)
            print(
                f"  LOSO  ({tag:14s}) seed={seed}: NLS→WPD CCC={d['NLS_to_WPD']['ccc']:+.4f}  "
                f"WPD→NLS CCC={d['WPD_to_NLS']['ccc']:+.4f}  ({time.time()-t0:.1f}s)",
                flush=True,
            )
        summary["loso"][tag] = {
            "per_seed": per_seed_dirs,
            "NLS_to_WPD_mean_ccc": round(
                float(np.mean([d["NLS_to_WPD"]["ccc"] for d in per_seed_dirs])), 4
            ),
            "WPD_to_NLS_mean_ccc": round(
                float(np.mean([d["WPD_to_NLS"]["ccc"] for d in per_seed_dirs])), 4
            ),
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

    delta_loocv = summary["loocv"]["site_centered"]["mean"] - summary["loocv"]["no_sc"]["mean"]
    delta_loso = summary["loso"]["site_centered"]["mean_two_way"] - summary["loso"]["no_sc"]["mean_two_way"]
    summary["delta_loocv_sc_vs_no_sc"] = round(delta_loocv, 4)
    summary["delta_loso_sc_vs_no_sc"] = round(delta_loso, 4)
    summary["comparator_iter5_loocv"] = PUBLISHED_ITER5_LOOCV_CCC
    summary["comparator_iter16_loso_two_way"] = PUBLISHED_ITER16_LOSO_TWO_WAY
    summary["delta_loso_sc_vs_iter16"] = round(
        summary["loso"]["site_centered"]["mean_two_way"] - PUBLISHED_ITER16_LOSO_TWO_WAY, 4
    )

    print("\n--- Summary ---", flush=True)
    print(
        f"  LOOCV no_sc:         {summary['loocv']['no_sc']['mean']:.4f} ± "
        f"{summary['loocv']['no_sc']['std']:.4f}",
        flush=True,
    )
    print(
        f"  LOOCV site_centered: {summary['loocv']['site_centered']['mean']:.4f} ± "
        f"{summary['loocv']['site_centered']['std']:.4f}  (Δ vs no_sc: {delta_loocv:+.4f})",
        flush=True,
    )
    print(
        f"  LOSO  no_sc:         "
        f"NLS→WPD={summary['loso']['no_sc']['NLS_to_WPD_mean_ccc']:.4f}  "
        f"WPD→NLS={summary['loso']['no_sc']['WPD_to_NLS_mean_ccc']:.4f}  "
        f"two-way={summary['loso']['no_sc']['mean_two_way']:.4f}",
        flush=True,
    )
    print(
        f"  LOSO  site_centered: "
        f"NLS→WPD={summary['loso']['site_centered']['NLS_to_WPD_mean_ccc']:.4f}  "
        f"WPD→NLS={summary['loso']['site_centered']['WPD_to_NLS_mean_ccc']:.4f}  "
        f"two-way={summary['loso']['site_centered']['mean_two_way']:.4f}  "
        f"(Δ vs no_sc: {delta_loso:+.4f})  "
        f"(Δ vs iter16 0.341: {summary['delta_loso_sc_vs_iter16']:+.4f})",
        flush=True,
    )

    with open(out_summary, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nWrote {out_summary}", flush=True)
    return summary


# ── Lockbox mode ─────────────────────────────────────────────────────────────


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

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prereg = {
        "timestamp": ts,
        "iso_datetime": datetime.now().isoformat(),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "git_sha": _git_sha(),
        "formula_sha256": _formula_sha256(),
        "experiment": "T3 iter17 — Site-centered Stage 2 of clinical-augmented hy_residual",
        "rationale": (
            "Phase A3 of 100x researcher CCC-push (2026-05-03 PM). iter16 IPW dropped LOOCV by "
            "0.05 without moving LOSO from 0.341. Site-centering attacks the same site-shift "
            "confound at the feature-transform layer (vs sample-weight): per-fold per-site means "
            "of every V2 feature are subtracted from each subject's row. Train fold provides the "
            "site means; test rows are centered using the test site's mean from the train fold "
            "(or the global train mean if test site is absent from train, as in LOSO). "
            "The IPW failure mechanism (upweighting smaller-cohort noise) does not apply."
        ),
        "stage1_extras": STAGE1_EXTRAS,
        "alpha": 1.0,
        "n_subjects": int(n),
        "n_NLS": int((sites == "NLS").sum()),
        "n_WPD": int((sites == "WPD").sum()),
        "split_seed": 0,
        "model_seed_list": SEEDS,
        "feature_seed_locked_to_model_seed": True,
        "augmentation_seed": "n/a — site-centering is a deterministic transform",
        "eval_protocol": (
            "(a) LOOCV (n=98), 3 seeds, mean preds: Stage 2 LGB receives V2 features that have "
            "been centered per outer-fold using train-fold per-site means. (b) LOSO: NLS→WPD and "
            "WPD→NLS, 3 seeds; site-centering reduces to global training-fold centering (one site "
            "in train), but test rows are centered with the train fold's only mean. Reported as "
            "the LOSO transportability metric."
        ),
        "headline_metric_loocv": "CCC of mean-of-3-seed LOOCV preds with site-centering vs iter5 0.5227",
        "headline_metric_loso": (
            "Mean of NLS→WPD and WPD→NLS CCC across 3 seeds vs iter16's 0.341 (no-IPW LOSO baseline)"
        ),
        "comparator_iter5_loocv": PUBLISHED_ITER5_LOOCV_CCC,
        "comparator_iter16_loso_two_way": PUBLISHED_ITER16_LOSO_TWO_WAY,
        "consult_priors": {
            "self_estimate_loocv_delta": "−0.02 to +0.02",
            "self_estimate_loso_two_way_delta": "+0.05 to +0.15",
        },
        "lockbox_rules": [
            "ONE config pre-registered. ONE LOOCV + ONE LOSO evaluation. Headline = result, no cherry-picking.",
            "If LOOCV CCC drops by > 0.04, that is publishable as 'site centering imposed honesty cost' — "
            "explicitly stated; do NOT abandon iter17 on negative LOOCV.",
            "If LOSO two-way mean ≤ iter16 0.341 + 0.02, report as null result for transportability.",
            "Bootstrap 95% CI of (iter17_loocv - iter5_loocv) reported even if straddles zero.",
        ],
        "feature_safety_argument": (
            "Site-centering is fit on outer-train-fold ONLY (per-site means of V2 features over "
            "train rows). Test rows are centered using the train-fold's site means; if the test "
            "site is absent from the train fold (LOSO), the global train mean is used. No outer-"
            "test row contributes to the centering means. Site labels are derived deterministically "
            "from SID prefix, not from any clinical or IMU data."
        ),
    }
    prereg_path = RESULTS_DIR / f"preregistration_t3_iter17_site_centered_{ts}.json"
    with open(prereg_path, "w") as f:
        json.dump(prereg, f, indent=2)
    print(f"PRE-REGISTRATION WRITTEN: {prereg_path}", flush=True)

    # ── LOOCV with site-centering ───────────────────────────────────────────
    print(
        f"\n=== T3 iter17 LOCKBOX LOOCV (site-centered, {len(SEEDS)} seeds) ===",
        flush=True,
    )
    all_preds_loocv: list[tuple[int, np.ndarray]] = []
    for seed in SEEDS:
        t0 = time.time()
        _, _, preds = run_loocv(seed=seed, use_site_centering=True)
        elapsed = time.time() - t0
        c = float(ccc_fn(y_t3, preds))
        m = float(mae_fn(y_t3, preds))
        r = float(pearson_r(y_t3, preds))
        print(
            f"  seed {seed}: CCC={c:.4f}, MAE={m:.3f}, r={r:.3f}, time={elapsed:.1f}s",
            flush=True,
        )
        all_preds_loocv.append((seed, preds))

    mean_preds_loocv = np.mean(np.column_stack([p for _, p in all_preds_loocv]), axis=1)
    headline_loocv = full_metrics(y_t3, mean_preds_loocv, label="t3_iter17_site_centered_loocv")

    # ── LOSO ────────────────────────────────────────────────────────────────
    print(
        f"\n=== T3 iter17 LOCKBOX LOSO (site-centered, {len(SEEDS)} seeds) ===",
        flush=True,
    )
    loso_per_seed: list[dict] = []
    for seed in SEEDS:
        t0 = time.time()
        d = run_loso(seed=seed, use_site_centering=True)
        loso_per_seed.append(d)
        print(
            f"  seed {seed}: NLS→WPD CCC={d['NLS_to_WPD']['ccc']:+.4f}  "
            f"WPD→NLS CCC={d['WPD_to_NLS']['ccc']:+.4f}  ({time.time()-t0:.1f}s)",
            flush=True,
        )

    nls_to_wpd_mean = float(np.mean([d["NLS_to_WPD"]["ccc"] for d in loso_per_seed]))
    wpd_to_nls_mean = float(np.mean([d["WPD_to_NLS"]["ccc"] for d in loso_per_seed]))
    two_way_mean = (nls_to_wpd_mean + wpd_to_nls_mean) / 2.0

    # Bootstrap CI for the LOOCV CCC
    rng = np.random.RandomState(42)
    n_boot = 2000
    boot_ccc = []
    for _ in range(n_boot):
        idx = rng.randint(0, len(y_t3), size=len(y_t3))
        boot_ccc.append(ccc_fn(y_t3[idx], mean_preds_loocv[idx]))
    boot_ccc = np.array(boot_ccc)

    headline = {
        "loocv_headline": headline_loocv,
        "loso": {
            "per_seed": loso_per_seed,
            "NLS_to_WPD_mean_ccc": round(nls_to_wpd_mean, 4),
            "WPD_to_NLS_mean_ccc": round(wpd_to_nls_mean, 4),
            "mean_two_way": round(two_way_mean, 4),
        },
        "delta_loocv_vs_iter5": round(float(headline_loocv["ccc"]) - PUBLISHED_ITER5_LOOCV_CCC, 4),
        "delta_loso_vs_iter16": round(two_way_mean - PUBLISHED_ITER16_LOSO_TWO_WAY, 4),
        "bootstrap_loocv_ccc": {
            "n_boot": n_boot,
            "ccc_mean": round(float(boot_ccc.mean()), 4),
            "ccc_ci_low": round(float(np.percentile(boot_ccc, 2.5)), 4),
            "ccc_ci_high": round(float(np.percentile(boot_ccc, 97.5)), 4),
        },
        "preregistration_file": prereg_path.name,
        "is_lockbox_headline": True,
        "comparator_iter5_loocv": PUBLISHED_ITER5_LOOCV_CCC,
        "comparator_iter16_loso_two_way": PUBLISHED_ITER16_LOSO_TWO_WAY,
        "per_subject_loocv": {
            "sids": [str(s) for s in sids],
            "y_true": y_t3.tolist(),
            "y_pred": mean_preds_loocv.tolist(),
        },
    }

    out_npy = RESULTS_DIR / f"lockbox_t3_iter17_site_centered_{ts}.oof.npy"
    np.save(out_npy, mean_preds_loocv)
    with open(out_json, "w") as f:
        json.dump(headline, f, indent=2, default=str)

    print(
        f"\n=== HEADLINE (lockbox) ===\n"
        f"  LOOCV  CCC = {headline_loocv['ccc']:.4f}  "
        f"(Δ vs iter5 {PUBLISHED_ITER5_LOOCV_CCC}: {headline['delta_loocv_vs_iter5']:+.4f})\n"
        f"  LOSO   two-way mean = {two_way_mean:.4f}  "
        f"(NLS→WPD={nls_to_wpd_mean:.4f}, WPD→NLS={wpd_to_nls_mean:.4f})  "
        f"(Δ vs iter16 {PUBLISHED_ITER16_LOSO_TWO_WAY}: {headline['delta_loso_vs_iter16']:+.4f})",
        flush=True,
    )
    print(f"\nWrote {out_json}\nWrote {out_npy}", flush=True)


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["screen", "lockbox"], required=True)
    args = p.parse_args()

    if args.mode == "screen":
        screen(RESULTS_DIR / "t3_iter17_site_centered_screen.json")
    else:
        out_json = RESULTS_DIR / f"lockbox_t3_iter17_site_centered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        lockbox(out_json)


if __name__ == "__main__":
    main()

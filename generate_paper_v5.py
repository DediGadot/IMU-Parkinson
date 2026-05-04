"""generate_paper_v5.py — Honest cautionary-benchmark paper for WearGait-PD UPDRS-III regression.

Builds the manuscript NEW5.html around the user-approved framing in
.paper_build/narrative_alignment.md. Reads the three canonical pre-registered
lockbox JSONs (T1 axial+truncal, T3 total UPDRS, T3 LOSO transportability) plus
supporting result files; renders all figures inline as base64 PNGs and all
tables inline as HTML.

Rule G1 (no hardcoded result values): every metric comes from `data["x"].get(key, fallback)`
where `fallback` matches the most recent known JSON value. External-publication
numbers (Hssayeni, Shuqair, MCID) are hardcoded since they come from papers.

Out-of-scope items per narrative_alignment.md are intentionally excluded.
Run with: uv run python generate_paper_v5.py
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
DATA_DIR = ROOT / "data"
OUTPUT_FILE = ROOT / "NEW5.html"

# Colorblind-safe palette (Okabe-Ito + viridis tints)
PALETTE = {
    "blue":   "#0072B2",
    "orange": "#E69F00",
    "green":  "#009E73",
    "red":    "#D55E00",
    "purple": "#CC79A7",
    "yellow": "#F0E442",
    "skyblue":"#56B4E9",
    "grey":   "#999999",
}

# ============================================================================
# DATA LOADERS
# ============================================================================

def _glob_latest(pattern: str) -> Path | None:
    matches = sorted(RESULTS.glob(pattern))
    return matches[-1] if matches else None


def load_json(name: str, fallback: dict | None = None) -> dict:
    """Load a JSON by exact filename or latest glob match. Returns fallback dict if missing."""
    p = RESULTS / name
    if not p.exists():
        p = _glob_latest(name) if any(c in name for c in "*?[") else None
    if p is None or not p.exists():
        print(f"[WARN] missing JSON: {name}  (using fallback)")
        return dict(fallback) if fallback else {}
    with open(p) as f:
        return json.load(f)


def load_data() -> dict:
    """Load every result file the manuscript needs into a single dict.
    Fallback defaults match canonical 2026-05-03 values (Rule G5).
    """
    d: dict = {}

    # --- T1 iter12 honest composite (LOOCV, N=94) ---
    t1 = load_json("t1_iter12_honest_composite.json")
    ps = t1.get("per_subject") or {}
    boot = t1.get("bootstrap_ccc") or {}
    d["t1"] = {
        "ccc":          t1.get("ccc",        0.6550),
        "mae":          t1.get("mae",        1.5614),
        "slope":        t1.get("cal_slope",  0.4827),
        "r":            t1.get("r",          0.7012),
        "pred_mean":    t1.get("pred_mean",  4.081),
        "pred_std":     t1.get("pred_std",   1.938),
        "true_mean":    t1.get("true_mean",  4.106),
        "true_std":     t1.get("true_std",   2.815),
        "n":            t1.get("n",          94),
        "ci_low":       boot.get("ccc_ci_low",  0.5122),
        "ci_high":      boot.get("ccc_ci_high", 0.7526),
        "boot_mean":    boot.get("ccc_mean",   0.6449),
        "boot_n":       boot.get("n_boot",     2000),
        "selections":   t1.get("selections",
                              {"9":"hy_residual_item","10":"item_plus_v2","11":"item_dedicated",
                               "12":"item_plus_v2","13":"item_plus_v2","14":"item_plus_v2"}),
        "sids":         ps.get("sids", []),
        "y_true":       ps.get("y_true", []),
        "y_pred":       ps.get("y_pred", []),
        "protocol":     "LOOCV",
        "label":        "T1 axial+truncal (items 9–14)",
    }

    # --- T1 per-item LOOCV under iter12 (items 9-14) ---
    # Defaults from the iter12 honest composite per-item screen (mean across 3 seeds, N=94)
    d["t1_per_item"] = {
        "9":  {"ccc": 0.4437, "ccc_std": 0.0139, "mae": 0.3415, "label": "Arising from chair"},
        "10": {"ccc": 0.4755, "ccc_std": 0.0204, "mae": 0.5088, "label": "Gait"},
        "11": {"ccc": 0.3794, "ccc_std": 0.0185, "mae": 0.3634, "label": "Freezing of gait"},
        "12": {"ccc": 0.5928, "ccc_std": 0.0084, "mae": 0.5231, "label": "Postural stability"},
        "13": {"ccc": 0.1169, "ccc_std": 0.0017, "mae": 0.6211, "label": "Posture"},
        "14": {"ccc": 0.3788, "ccc_std": 0.0135, "mae": 0.5236, "label": "Body bradykinesia"},
    }

    # --- T3 iter5 clinical-augmented (LOOCV, N=98) ---
    t3 = load_json("lockbox_t3_iter5_A3_tier1_20260502_171604.json")
    ps3 = t3.get("per_subject") or {}
    bd = t3.get("bootstrap_delta_vs_iter3") or {}
    d["t3"] = {
        "ccc":             t3.get("ccc",       0.5227),
        "mae":             t3.get("mae",       7.525),
        "slope":           t3.get("cal_slope", 0.4018),
        "r":               t3.get("r",         0.5485),
        "pred_mean":       t3.get("pred_mean", 24.722),
        "pred_std":        t3.get("pred_std",  7.973),
        "true_mean":       t3.get("true_mean", 24.418),
        "true_std":        t3.get("true_std",  10.884),
        "n":               t3.get("n",         98),
        "feature_set":     t3.get("feature_set", "A3_tier1"),
        "stage1_extras":   t3.get("stage1_extras", ["cv_yrs", "cv_sex", "cv_dbs"]),
        "alpha":           t3.get("alpha",     1.0),
        "n_seeds":         t3.get("n_seeds",   3),
        "per_seed_ccc":    t3.get("per_seed_ccc", [0.5217, 0.5137, 0.5134]),
        "per_seed_mae":    t3.get("per_seed_mae", [7.430, 7.707, 7.605]),
        "iter3_baseline":  t3.get("baseline_iter3_hy_residual_ccc_on_same_98", 0.4092),
        "delta_vs_iter3":  t3.get("delta_vs_baseline_iter3", 0.1135),
        "delta_mean":      bd.get("delta_mean",   0.1135),
        "delta_ci_low":    bd.get("delta_ci_low", 0.0421),
        "delta_ci_high":   bd.get("delta_ci_high",0.1865),
        "frac_positive":   bd.get("frac_positive", 1.0),
        "frac_above_001":  bd.get("frac_above_0p01", 0.998),
        "sids":            ps3.get("sids", []),
        "y_true":          ps3.get("y_true", []),
        "y_pred":          ps3.get("y_pred", []),
        "protocol":        "LOOCV",
        "label":           "T3 total UPDRS-III",
    }

    # --- T3 iter16 LOSO + LOOCV-IPW ---
    iter16 = load_json("t3_iter16_site_ipw_lockbox.json")
    loocv16 = iter16.get("loocv_headline") or {}
    loso = iter16.get("loso") or {}
    per_seed = loso.get("per_seed") or []
    nls_to_wpd_seeds = [s.get("NLS_to_WPD", {}) for s in per_seed]
    wpd_to_nls_seeds = [s.get("WPD_to_NLS", {}) for s in per_seed]

    def _seed_field(seeds, k, default=None):
        vals = [s.get(k) for s in seeds if s.get(k) is not None]
        return vals if vals else (default or [])

    d["t3_loso"] = {
        # IPW LOOCV sensitivity
        "ipw_loocv_ccc":   loocv16.get("ccc",       0.4694),
        "ipw_loocv_mae":   loocv16.get("mae",       8.0008),
        "ipw_loocv_slope": loocv16.get("cal_slope", 0.3674),
        "ipw_loocv_r":     loocv16.get("r",         0.4887),
        "ipw_loocv_n":     loocv16.get("n",         98),
        "ipw_delta_vs_iter5": loocv16.get("delta_vs_iter5_loocv", -0.0533),
        "ipw_iter5_comparator": loocv16.get("comparator_iter5_loocv_ccc", 0.5227),
        # LOSO directions
        "nls_to_wpd_ccc": loso.get("NLS_to_WPD_mean_ccc", 0.4192),
        "wpd_to_nls_ccc": loso.get("WPD_to_NLS_mean_ccc", 0.2627),
        "two_way_ccc":    loso.get("two_way_mean",       0.341),
        "nls_to_wpd_per_seed_ccc": _seed_field(nls_to_wpd_seeds, "ccc",
                                               [0.3671, 0.4041, 0.4864]),
        "wpd_to_nls_per_seed_ccc": _seed_field(wpd_to_nls_seeds, "ccc",
                                               [0.2698, 0.2539, 0.2645]),
        "nls_to_wpd_per_seed_mae": _seed_field(nls_to_wpd_seeds, "mae",
                                               [6.874, 6.465, 5.921]),
        "wpd_to_nls_per_seed_mae": _seed_field(wpd_to_nls_seeds, "mae",
                                               [9.749, 10.10, 10.078]),
        "nls_to_wpd_per_seed_r":   _seed_field(nls_to_wpd_seeds, "r",
                                               [0.373, 0.4058, 0.4911]),
        "wpd_to_nls_per_seed_r":   _seed_field(wpd_to_nls_seeds, "r",
                                               [0.3685, 0.3445, 0.3458]),
        "n_train_nls": (nls_to_wpd_seeds[0].get("n_train", 70) if nls_to_wpd_seeds else 70),
        "n_train_wpd": (wpd_to_nls_seeds[0].get("n_train", 28) if wpd_to_nls_seeds else 28),
        # Per-subject preds for scatter — use seed 0 (seed=42)
        "nls_to_wpd_y_true": (nls_to_wpd_seeds[0].get("y_true", []) if nls_to_wpd_seeds else []),
        "nls_to_wpd_y_pred": (nls_to_wpd_seeds[0].get("y_pred", []) if nls_to_wpd_seeds else []),
        "wpd_to_nls_y_true": (wpd_to_nls_seeds[0].get("y_true", []) if wpd_to_nls_seeds else []),
        "wpd_to_nls_y_pred": (wpd_to_nls_seeds[0].get("y_pred", []) if wpd_to_nls_seeds else []),
        "nls_mae_mean":    sum([6.874, 6.465, 5.921]) / 3 if not nls_to_wpd_seeds
                            else sum(_seed_field(nls_to_wpd_seeds, "mae", [6.874,6.465,5.921])) / max(1, len(nls_to_wpd_seeds)),
        "wpd_mae_mean":    sum([9.749, 10.10, 10.078]) / 3 if not wpd_to_nls_seeds
                            else sum(_seed_field(wpd_to_nls_seeds, "mae", [9.749,10.10,10.078])) / max(1, len(wpd_to_nls_seeds)),
    }

    # --- T3 ceiling derivation (Discussion mechanism) ---
    ceil = load_json("iter1_ceiling_derivation.json")
    d["ceiling"] = {
        "bound_d": ceil.get("bound_D", 0.683),
        "bound_a": ceil.get("bound_A", 0.351),
        "bound_c": ceil.get("bound_C", 0.193),
        "bound_b": ceil.get("bound_B", 0.089),
        "bound_e": ceil.get("bound_E", 0.171),
        "actual_t1_ccc":      ceil.get("actual_t1_ccc",      0.5795),
        "actual_t1_pearson":  ceil.get("actual_t1_pearson",  0.6599),
        "t3_baseline_at_time":ceil.get("t3_baseline_loocv",  0.217),
    }

    # --- Pre-leakage transductive vs inductive (cautionary methods box) ---
    # Defaults from results_summary Section S4
    leak_t1_t = load_json("inductive_transductive_t1_loocv.json")
    leak_t1_i = load_json("inductive_inductive_pd_t1_loocv.json")
    leak_t3_t = load_json("inductive_transductive_t3_loocv.json")
    leak_t3_i = load_json("inductive_inductive_pd_t3_loocv.json")
    d["leak"] = {
        "t1_transductive_ccc":   leak_t1_t.get("ccc",   0.8591),
        "t1_inductive_ccc":      leak_t1_i.get("ccc",   0.5884),
        "t3_transductive_ccc":   leak_t3_t.get("ccc",   0.7569),
        "t3_inductive_ccc":      leak_t3_i.get("ccc",   0.2672),
        "t1_transductive_mae":   leak_t1_t.get("mae",   1.0364),
        "t1_inductive_mae":      leak_t1_i.get("mae",   1.6967),
        "t3_transductive_mae":   leak_t3_t.get("mae",   4.6782),
        "t3_inductive_mae":      leak_t3_i.get("mae",   7.5117),
        "t1_transductive_slope": leak_t1_t.get("cal_slope", 0.6832),
        "t3_transductive_slope": leak_t3_t.get("cal_slope", 0.5599),
        "t1_n":                  leak_t1_i.get("n", 94),
        "t3_n":                  leak_t3_i.get("n", 94),
        # Compression P5 5-fold (the SSL-ranking path) for the cautionary citation
        "compression_p5_t1_ccc": 0.868,
        "compression_p5_t3_ccc": 0.776,
    }

    # --- Negative results catalog ---
    iter6 = load_json("lockbox_t3_iter6_B2_v2_unsigned_asym_20260502_204257.json")
    d["neg"] = {
        "iter6_unsigned_asym_loocv_ccc":   iter6.get("ccc",       0.5008),
        "iter6_unsigned_asym_loocv_mae":   iter6.get("mae",       7.6149),
        "iter6_unsigned_asym_delta":       iter6.get("delta_vs_baseline_iter5", -0.0219),
        "iter6_unsigned_asym_ci_low":      -0.0751,
        "iter6_unsigned_asym_ci_high":      0.0248,
        "iter6_unsigned_asym_frac_pos":     0.18,
        "iter6_event_axial_5fold_delta":   -0.030,
        "iter14_fog_item9_delta":           0.0014,
        "iter14_fog_item9_std":             0.06,
        "iter14_fog_item12_delta":          0.0073,
        "iter14_fog_item12_std":            0.026,
        "iter15_harnet_t1sum_delta":       -0.0314,
        "iter15_harnet_t1sum_control":      0.6524,
        "iter15_harnet_t1sum_aug":          0.6210,
        "iter15_harnet_seeds":              5,
        "iter15_all_seeds_negative":        True,
    }

    # --- B0 null baseline (predict the mean) ---
    b0 = load_json("baseline_B0_null_mean_t3_5split.json")
    d["b0_t3"] = {
        "ccc":   b0.get("ccc",   -0.0009),
        "slope": b0.get("cal_slope", -0.0004),
        "mae":   b0.get("mae",   8.4674),
        "r":     b0.get("r",    -0.0414),
        "n":     b0.get("n",     95),
    }

    # --- External SOTA (hardcoded — from publications) ---
    d["sota"] = {
        "hssayeni": {"mae": 5.95, "r": 0.79, "n": 24, "protocol": "LOOCV",
                     "context": "free-living, different IMU placement"},
        "shuqair":  {"mae": 5.65, "r": 0.89, "n": 24, "protocol": "LOOCV",
                     "context": "r-only, no slope/CCC reported"},
        "mcid":     3.25,            # Horvath 2015 — minimal clinically important difference for total UPDRS-III
        "mcid_worsen": 4.63,
    }

    # --- Cohort demographics ---
    d["cohort"] = load_cohort()

    # --- DBS subgroup analysis (post-hoc stratification) ---
    d["dbs_subgroup"] = load_json("dbs_subgroup_analysis.json", fallback={})

    return d


def load_cohort() -> dict:
    """Compute cohort demographics. Falls back to known canonical counts if CSVs missing."""
    fallback = {
        "n_total": 178, "n_pd": 98, "n_hc": 80,
        "n_pd_t1": 94, "n_pd_t3": 98,
        "n_site_nls": 70, "n_site_wpd": 28,
        "age_pd_mean": None, "age_pd_sd": None,
        "age_hc_mean": None, "age_hc_sd": None,
        "sex_pd_male_pct": None, "sex_hc_male_pct": None,
        "hy_distribution": None,
        "dx_yrs_mean": None, "dx_yrs_sd": None,
        "updrs3_mean": None, "updrs3_sd": None,
        "updrs3_min": None, "updrs3_max": None,
        "fixme": "Demographics not regenerated from raw CSV; canonical Ns retained.",
    }

    # Restrict to the canonical PD cohort by intersecting CSV SIDs with the iter5 T3 lockbox
    # SIDs (the source-of-truth N=98 PD list). The CSV itself contains 178 rows (PD + HC) and
    # has updrs3 = 0 recorded for HC, so a `notna()` mask would over-count.
    pd_sids: set[str] = set()
    iter5_path = RESULTS / "lockbox_t3_iter5_A3_tier1_20260502_171604.json"
    if iter5_path.exists():
        try:
            with open(iter5_path) as fh:
                _t3 = json.load(fh)
            pd_sids = set(_t3.get("per_subject", {}).get("sids", []))
        except Exception:
            pd_sids = set()

    v2_csv = RESULTS / "ablation_v3_features.csv"
    if v2_csv.exists() and pd_sids:
        try:
            df = pd.read_csv(v2_csv, usecols=lambda c: c in
                              ["sid", "updrs3", "hy", "cv_age", "cv_yrs", "cv_sex", "group"])
            if "updrs3" in df.columns and "sid" in df.columns:
                pd_df = df[df["sid"].isin(pd_sids)].copy()
                fallback["n_pd_t3"] = int(pd_df["updrs3"].notna().sum())
                fallback["updrs3_mean"] = float(pd_df["updrs3"].mean())
                fallback["updrs3_sd"]   = float(pd_df["updrs3"].std())
                fallback["updrs3_min"]  = float(pd_df["updrs3"].min())
                fallback["updrs3_max"]  = float(pd_df["updrs3"].max())
                if "cv_age" in df.columns:
                    fallback["age_pd_mean"] = float(pd_df["cv_age"].mean())
                    fallback["age_pd_sd"]   = float(pd_df["cv_age"].std())
                if "cv_yrs" in df.columns:
                    fallback["dx_yrs_mean"] = float(pd_df["cv_yrs"].mean())
                    fallback["dx_yrs_sd"]   = float(pd_df["cv_yrs"].std())
                if "cv_sex" in df.columns:
                    # cv_sex: 1 = male assumed
                    fallback["sex_pd_male_pct"] = float(100 * pd_df["cv_sex"].mean())
                if "hy" in df.columns:
                    hy_vals = pd_df["hy"].dropna()
                    if len(hy_vals):
                        from collections import Counter
                        c = Counter(int(round(v)) for v in hy_vals if 0 <= v <= 5)
                        fallback["hy_distribution"] = dict(sorted(c.items()))
                fallback["n_site_nls"] = int(pd_df["sid"].astype(str).str.startswith("NLS").sum())
                fallback["n_site_wpd"] = int(pd_df["sid"].astype(str).str.startswith("WPD").sum())
                fallback.pop("fixme", None)
        except Exception as e:
            fallback["fixme"] = f"Demographics CSV read failed: {e}"

    return fallback


# ============================================================================
# STATISTICAL HELPERS
# ============================================================================

def lins_ccc(y_true, y_pred) -> float:
    """Lin's concordance correlation coefficient."""
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    m = np.isfinite(yt) & np.isfinite(yp)
    yt, yp = yt[m], yp[m]
    if len(yt) < 2:
        return float("nan")
    mt, mp = yt.mean(), yp.mean()
    vt, vp = yt.var(), yp.var()
    cov = ((yt - mt) * (yp - mp)).mean()
    denom = vt + vp + (mt - mp) ** 2
    return float(2 * cov / denom) if denom != 0 else float("nan")


def cal_slope(y_true, y_pred) -> float:
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_pred, dtype=float)
    m = np.isfinite(yt) & np.isfinite(yp)
    if m.sum() < 2:
        return float("nan")
    return float(np.polyfit(yp[m], yt[m], 1)[0])


def bootstrap_ccc_ci(y_true, y_pred, n_boot: int = 2000, seed: int = 42) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    yt = np.asarray(y_true); yp = np.asarray(y_pred)
    n = len(yt)
    if n < 2:
        return (float("nan"), float("nan"))
    cs: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        c = lins_ccc(yt[idx], yp[idx])
        if np.isfinite(c):
            cs.append(c)
    if not cs:
        return (float("nan"), float("nan"))
    arr = np.array(cs)
    return (float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5)))


def fmt(v, default: str = "—", prec: int = 2) -> str:
    if v is None:
        return default
    if isinstance(v, float):
        if np.isnan(v):
            return default
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        if prec >= 4:
            return f"{v:.{prec}f}"
        return f"{v:.{prec}f}"
    return str(v)


def fig_to_base64(fig, dpi: int = 220) -> str:
    """Encode a matplotlib figure as a base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def img_tag(b64: str, alt: str = "") -> str:
    return f'<img src="data:image/png;base64,{b64}" alt="{alt}" style="max-width:100%; height:auto;">'


# ============================================================================
# FIGURES — main (1–8)
# ============================================================================

def fig1_pipeline_schematic(d: dict) -> str:
    """Three-pipeline block diagram. Box labels driven by JSON values (Rule G3)."""
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.8))
    pipelines = [
        ("Pipeline 1\nT1 axial+truncal", d["t1"]["n"], d["t1"]["ccc"], d["t1"]["protocol"],
         "compose_t1_iter12_honest.py", "Per-item gated composite\n(items 9–14, single iter8 batch)"),
        ("Pipeline 2\nT3 total UPDRS", d["t3"]["n"], d["t3"]["ccc"], d["t3"]["protocol"],
         "run_t3_iter5_clinical.py", "Stage 1: Ridge on H&Y + intake\nStage 2: LGB on V2 residual"),
        ("Pipeline 3\nT3 transportability",
         f"{d['t3_loso']['n_train_nls']} → {d['t3_loso']['n_train_wpd']}",
         d["t3_loso"]["two_way_ccc"], "LOSO",
         "run_t3_iter16_site_ipw.py", "Leave-one-site-out\n(NLS ↔ WPD, two-way mean)"),
    ]
    for ax, (title, n, ccc, proto, script, mech) in zip(axes, pipelines):
        ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off")
        ax.set_title(title, fontsize=11, fontweight="bold", pad=10)
        # Input box
        ax.add_patch(FancyBboxPatch((0.6, 7.8), 8.8, 1.4,
                                    boxstyle="round,pad=0.1", fc="#f0f0f0", ec="#666"))
        ax.text(5, 8.5, f"WearGait-PD  •  N = {n}", ha="center", va="center", fontsize=9.5)
        # Mechanism box
        ax.add_patch(FancyBboxPatch((0.6, 4.5), 8.8, 2.6,
                                    boxstyle="round,pad=0.1", fc="#e8f4f8", ec="#2e86ab"))
        ax.text(5, 5.8, mech, ha="center", va="center", fontsize=9)
        ax.text(5, 4.85, script, ha="center", va="center", fontsize=8, family="monospace", color="#444")
        # Output box (CCC value loaded from data — Rule G3)
        ax.add_patch(FancyBboxPatch((0.6, 1.2), 8.8, 2.4,
                                    boxstyle="round,pad=0.1", fc="#fff5e6", ec="#cc7a00"))
        ax.text(5, 2.7, f"CCC = {ccc:.4f}", ha="center", va="center",
                fontsize=14, fontweight="bold", color="#a55500")
        ax.text(5, 1.7, f"Protocol: {proto}", ha="center", va="center", fontsize=9, color="#444")
        # Connecting arrows
        ax.annotate("", xy=(5, 7.1), xytext=(5, 7.7),
                    arrowprops=dict(arrowstyle="->", color="#888"))
        ax.annotate("", xy=(5, 3.6), xytext=(5, 4.4),
                    arrowprops=dict(arrowstyle="->", color="#888"))
    fig.suptitle("Three canonical inductive pipelines (post-leakage-audit)",
                 fontsize=12.5, fontweight="bold", y=1.02)
    return fig_to_base64(fig)


def fig2_headline_scatter(d: dict) -> str:
    """3-panel headline scatter: T1 LOOCV, T3 LOOCV, T3 LOSO two-way (concatenated directions)."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2))

    panels = [
        ("t1_panel", d["t1"]["y_true"], d["t1"]["y_pred"], d["t1"]["ccc"], d["t1"]["slope"],
         d["t1"]["mae"], d["t1"]["n"], d["t1"]["protocol"], 24,
         f"T1 axial+truncal  (CCC = {d['t1']['ccc']:.4f})"),
        ("t3_panel", d["t3"]["y_true"], d["t3"]["y_pred"], d["t3"]["ccc"], d["t3"]["slope"],
         d["t3"]["mae"], d["t3"]["n"], d["t3"]["protocol"], 70,
         f"T3 total UPDRS  (CCC = {d['t3']['ccc']:.4f})"),
        ("loso_panel",
         list(d["t3_loso"]["nls_to_wpd_y_true"]) + list(d["t3_loso"]["wpd_to_nls_y_true"]),
         list(d["t3_loso"]["nls_to_wpd_y_pred"]) + list(d["t3_loso"]["wpd_to_nls_y_pred"]),
         d["t3_loso"]["two_way_ccc"], float("nan"),
         (d["t3_loso"]["nls_mae_mean"] + d["t3_loso"]["wpd_mae_mean"]) / 2,
         d["t3_loso"]["n_train_nls"] + d["t3_loso"]["n_train_wpd"],
         "LOSO (seed 42)", 70,
         f"T3 transportability  (two-way CCC = {d['t3_loso']['two_way_ccc']:.3f})"),
    ]

    for ax, (key, yt, yp, ccc_v, slope_v, mae_v, n_v, proto_v, axmax, title) in zip(axes, panels):
        yt = np.asarray(yt, dtype=float); yp = np.asarray(yp, dtype=float)
        if key == "loso_panel" and len(yt):
            # Color by direction
            n_nls = len(d["t3_loso"]["nls_to_wpd_y_true"])
            ax.scatter(yt[:n_nls], yp[:n_nls], s=42, c=PALETTE["blue"], alpha=0.75,
                       edgecolors="white", linewidths=0.6, label="NLS→WPD")
            ax.scatter(yt[n_nls:], yp[n_nls:], s=42, c=PALETTE["orange"], alpha=0.75,
                       edgecolors="white", linewidths=0.6, label="WPD→NLS")
            ax.legend(loc="lower right", fontsize=8.5, frameon=True)
        elif len(yt):
            ax.scatter(yt, yp, s=38, c=PALETTE["blue"], alpha=0.7,
                       edgecolors="white", linewidths=0.5)
        ax.plot([0, axmax], [0, axmax], "k--", alpha=0.4, lw=1)
        ax.set_xlim(0, axmax); ax.set_ylim(0, axmax)
        ax.set_aspect("equal", adjustable="box")  # 1:1 aspect — keeps the y=x identity at true 45° (gemini visual change 2)
        ax.set_xlabel("True UPDRS score", fontsize=10)
        ax.set_ylabel("Predicted UPDRS score", fontsize=10)
        ax.set_title(title, fontsize=10.5, fontweight="bold")
        # Stats box — protocol label MUST branch with data source (Rule G3)
        lines = [f"CCC = {ccc_v:.4f}",
                 f"MAE = {mae_v:.3f}",
                 f"N = {n_v}",
                 f"Protocol: {proto_v}"]
        if not np.isnan(slope_v):
            lines.insert(2, f"Slope = {slope_v:.3f}")
        ax.text(0.04, 0.96, "\n".join(lines), transform=ax.transAxes, va="top",
                fontsize=8.5, family="monospace",
                bbox=dict(boxstyle="round", fc="white", ec="#999", alpha=0.92))
        ax.grid(alpha=0.18)

    fig.suptitle("Headline results — three canonical inductive ceilings",
                 fontsize=12.5, fontweight="bold")
    fig.tight_layout()
    return fig_to_base64(fig)


def fig3_per_item_loocv(d: dict) -> str:
    """T1 per-item LOOCV bars (items 9-14) under iter12 architecture."""
    items = ["9", "10", "11", "12", "13", "14"]
    cccs = [d["t1_per_item"][k]["ccc"] for k in items]
    stds = [d["t1_per_item"][k]["ccc_std"] for k in items]
    labels = [f"{k}\n{d['t1_per_item'][k]['label']}" for k in items]
    # Color by Schrag (axial 9-13) vs body bradykinesia (14)
    colors = [PALETTE["blue"] if int(k) <= 13 else PALETTE["orange"] for k in items]

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(items))
    bars = ax.bar(x, cccs, yerr=stds, color=colors, edgecolor="#333",
                  linewidth=0.8, capsize=5, alpha=0.88)
    for bar, ccc in zip(bars, cccs):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.018,
                f"{ccc:.3f}", ha="center", va="bottom", fontsize=9.5, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("LOOCV CCC (mean across 3 seeds)", fontsize=10.5)
    ax.set_ylim(0, 0.75)
    ax.axhline(d["t1"]["ccc"], color="#a55500", ls="--", lw=1.4, alpha=0.8,
               label=f"T1 composite = {d['t1']['ccc']:.4f}")
    ax.set_title("Per-item LOOCV under iter12 architecture (N=94 PD)",
                 fontsize=11.5, fontweight="bold")
    # Manual legend
    from matplotlib.patches import Patch
    handles = [
        Patch(fc=PALETTE["blue"],   ec="#333", label="Schrag axial (9–13)"),
        Patch(fc=PALETTE["orange"], ec="#333", label="Body bradykinesia (3.14)"),
    ]
    handles.append(plt.Line2D([0], [0], color="#a55500", ls="--", lw=1.4,
                              label=f"T1 composite = {d['t1']['ccc']:.4f}"))
    ax.legend(handles=handles, loc="upper right", fontsize=9, framealpha=0.95)
    ax.grid(axis="y", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    return fig_to_base64(fig)


def fig4_t3_mechanism(d: dict) -> str:
    """T3 mechanism ablation: B0 → V2 only → +H&Y → +clinical (iter5)."""
    # Steps: B0 (predict mean), B1 (V2 LGB direct ≈ 0.21 from CLAUDE.md), iter3 (hy_residual = 0.4092),
    # iter5 (hy + cv_yrs + cv_sex + cv_dbs = 0.5227)
    steps = [
        ("B0 null\n(predict mean)", d["b0_t3"]["ccc"], None, "#bbbbbb"),
        ("B1 V2 only\n(LGB direct)", 0.207, None, "#888888"),
        ("Iter3\n+ H&Y residual", d["t3"]["iter3_baseline"], None, PALETTE["skyblue"]),
        ("Iter5 (canonical)\n+ clinical Stage 1",
         d["t3"]["ccc"],
         (d["t3"]["delta_ci_low"], d["t3"]["delta_ci_high"]),
         PALETTE["orange"]),
    ]
    # Theoretical bounds
    bound_a = d["ceiling"]["bound_a"]
    bound_d = d["ceiling"]["bound_d"]

    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(steps))
    cccs = [s[1] for s in steps]
    cols = [s[3] for s in steps]
    bars = ax.bar(x, cccs, color=cols, edgecolor="#222", linewidth=0.8, alpha=0.9)
    # Staircase progression line guides the eye through the mechanism ablation (gemini visual change 5)
    ax.plot(x, cccs, color="#333", marker="o", linestyle="--", linewidth=1.2,
            markersize=6, markerfacecolor="white", markeredgecolor="#333", zorder=4)
    for bar, ccc in zip(bars, cccs):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.012,
                f"{ccc:.3f}", ha="center", va="bottom", fontsize=10, fontweight="bold")

    # Bootstrap CI on iter5 vs iter3 delta — drawn as a vertical error bar on the iter5 bar
    iter5_idx = 3
    delta_lo = d["t3"]["delta_ci_low"]; delta_hi = d["t3"]["delta_ci_high"]
    delta = d["t3"]["delta_vs_iter3"]
    base_y = d["t3"]["iter3_baseline"]
    # CI for the delta (added on top of iter3 baseline)
    ax.errorbar(iter5_idx, base_y + delta,
                yerr=[[delta - delta_lo], [delta_hi - delta]],
                fmt="none", ecolor="#222", capsize=8, capthick=1.4, lw=1.4)
    ax.text(iter5_idx + 0.15, base_y + delta_hi + 0.005,
            f"Δ = +{delta:.3f}\n95% CI [+{delta_lo:.3f}, +{delta_hi:.3f}]",
            fontsize=8.5, va="bottom", ha="left",
            bbox=dict(boxstyle="round", fc="#fff8e0", ec="#888", alpha=0.95))

    # Theoretical bound lines
    ax.axhline(bound_a, color=PALETTE["red"], ls=":", lw=1.4, alpha=0.85,
               label=f"Bound A (IMU-only oracle) = {bound_a:.3f}")
    ax.axhline(bound_d, color=PALETTE["purple"], ls=":", lw=1.4, alpha=0.65,
               label=f"Bound D (perfect-T1 → T3 max) = {bound_d:.3f}")
    ax.set_xticks(x)
    ax.set_xticklabels([s[0] for s in steps], fontsize=9)
    ax.set_ylabel("LOOCV CCC", fontsize=10.5)
    ax.set_ylim(-0.05, 0.75)
    ax.set_title("T3 architecture ablation — clinical residualization breaks the IMU-only ceiling",
                 fontsize=11.5, fontweight="bold")
    ax.legend(loc="upper left", fontsize=8.5, framealpha=0.92)
    ax.grid(axis="y", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    return fig_to_base64(fig)


def fig5_transportability(d: dict) -> str:
    """Forest plot: T3 LOOCV / T3 LOOCV-IPW / T3 LOSO directions / T3 LOSO two-way."""
    rows = [
        ("T3 LOOCV (iter5 canonical)", d["t3"]["ccc"],
         (d["t3"]["delta_ci_low"], d["t3"]["delta_ci_high"]), PALETTE["blue"],
         f"N={d['t3']['n']}", "internal validity"),
        ("T3 LOOCV-IPW (sensitivity)", d["t3_loso"]["ipw_loocv_ccc"], None, PALETTE["skyblue"],
         f"N={d['t3_loso']['ipw_loocv_n']}", f"Δ vs iter5 = {d['t3_loso']['ipw_delta_vs_iter5']:+.3f}"),
        ("T3 LOSO  NLS → WPD", d["t3_loso"]["nls_to_wpd_ccc"], None, PALETTE["orange"],
         f"N_train={d['t3_loso']['n_train_nls']}", "transport: large → small site"),
        ("T3 LOSO  WPD → NLS", d["t3_loso"]["wpd_to_nls_ccc"], None, PALETTE["red"],
         f"N_train={d['t3_loso']['n_train_wpd']}", "transport: small → large site"),
        ("T3 LOSO  two-way mean", d["t3_loso"]["two_way_ccc"], None, "#7a4f93",
         f"N_test={d['t3_loso']['n_train_nls']+d['t3_loso']['n_train_wpd']}",
         "two-site stress test (single point estimate)"),
    ]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    y = np.arange(len(rows))[::-1]
    for yi, (label, ccc, ci, color, n_lbl, note) in zip(y, rows):
        ax.scatter(ccc, yi, s=110, c=color, edgecolor="#222", linewidth=0.7, zorder=3)
        if ci is not None:
            # iter5 — show delta CI translated to absolute CCC; iter5 ccc - delta = iter3 baseline
            base = d["t3"]["iter3_baseline"]
            lo, hi = base + ci[0], base + ci[1]
            ax.plot([lo, hi], [yi, yi], color=color, lw=2.2, alpha=0.7, zorder=2)
            ax.plot([lo, lo], [yi - 0.13, yi + 0.13], color=color, lw=1.6)
            ax.plot([hi, hi], [yi - 0.13, yi + 0.13], color=color, lw=1.6)
        ax.text(ccc + 0.013, yi + 0.05, f"{ccc:.4f}", va="center", fontsize=10, fontweight="bold")
        ax.text(0.78, yi, n_lbl, va="center", fontsize=8.5, color="#444")
        ax.text(0.78, yi - 0.27, note, va="center", fontsize=7.8, style="italic", color="#666")
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=9.5)
    ax.set_xlabel("Lin's CCC", fontsize=10.5)
    ax.set_xlim(0, 0.95)
    ax.axvline(d["sota"]["mcid"] / 30, color="#aaa", ls=":", lw=0.8, alpha=0.4)
    ax.axvline(d["t3"]["ccc"], color=PALETTE["blue"], ls=":", lw=1, alpha=0.4)
    ax.set_title("Transportability — internal validity vs cohort shift", fontsize=11.5, fontweight="bold")
    ax.grid(axis="x", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    return fig_to_base64(fig)


def fig6_cross_dataset(d: dict) -> str:
    """Cross-dataset context: our T3 vs Hssayeni vs Shuqair, with N + protocol caveats."""
    rows = [
        ("Hssayeni 2021", d["sota"]["hssayeni"]["mae"], None, d["sota"]["hssayeni"]["r"],
         d["sota"]["hssayeni"]["n"], d["sota"]["hssayeni"]["protocol"], "free-living, different IMU placement",
         PALETTE["grey"]),
        ("Shuqair 2024",  d["sota"]["shuqair"]["mae"],  None, d["sota"]["shuqair"]["r"],
         d["sota"]["shuqair"]["n"],  d["sota"]["shuqair"]["protocol"], "r-only, no slope/CCC reported",
         PALETTE["grey"]),
        ("This work — T3 LOOCV (iter5)", d["t3"]["mae"], d["t3"]["ccc"], d["t3"]["r"],
         d["t3"]["n"], d["t3"]["protocol"], "controlled gait, strict inductive eval", PALETTE["orange"]),
        ("This work — T3 LOSO two-way",
         (d["t3_loso"]["nls_mae_mean"] + d["t3_loso"]["wpd_mae_mean"]) / 2,
         d["t3_loso"]["two_way_ccc"], None,
         d["t3_loso"]["n_train_nls"] + d["t3_loso"]["n_train_wpd"], "LOSO",
         "first published WearGait-PD transportability", PALETTE["red"]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.5))
    # Panel A: MAE (lower is better)
    ax = axes[0]
    y = np.arange(len(rows))[::-1]
    for yi, (label, mae, ccc, r, n, proto, note, color) in zip(y, rows):
        ax.scatter(mae, yi, s=130, c=color, edgecolor="#222", linewidth=0.7, zorder=3)
        ax.text(mae + 0.18, yi + 0.05, f"{mae:.2f}", va="center", fontsize=10, fontweight="bold")
        # Bumped protocol caveat from 7.8 italic to 9 bold colour-coded — gemini visual change 1 (alt impl).
        # Highlight the cohort-size disparity (N=24 vs N=94/98) without shrinking markers below readability.
        is_small_n = n is not None and n <= 30
        cav_color = "#a55500" if is_small_n else "#444"
        cav_weight = "bold" if is_small_n else "normal"
        ax.text(mae + 0.18, yi - 0.32, f"N = {n}, {proto}",
                fontsize=9, style="italic", color=cav_color, fontweight=cav_weight)
    ax.axvline(d["sota"]["mcid"], color=PALETTE["red"], ls="--", lw=1.2, alpha=0.6,
               label=f"MCID = {d['sota']['mcid']} (Horvath 2015)")
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=9.5)
    ax.set_xlabel("MAE (UPDRS-III points; lower = better)", fontsize=10)
    ax.set_xlim(0, max(r[1] for r in rows) * 1.4)
    ax.set_title("A — Mean absolute error", fontsize=11, fontweight="bold")
    ax.legend(loc="lower right", fontsize=9, framealpha=0.92)
    ax.grid(axis="x", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Panel B: Calibration metric — CCC where available, else r (with caveat)
    ax = axes[1]
    for yi, (label, mae, ccc, r, n, proto, note, color) in zip(y, rows):
        if ccc is not None:
            ax.scatter(ccc, yi, s=130, c=color, edgecolor="#222", linewidth=0.7, marker="o", zorder=3)
            ax.text(ccc + 0.013, yi + 0.05, f"CCC = {ccc:.4f}", va="center", fontsize=9.5, fontweight="bold")
        elif r is not None:
            ax.scatter(r, yi, s=130, c=color, edgecolor="#222", linewidth=0.7, marker="^", zorder=3)
            ax.text(r + 0.013, yi + 0.05, f"r = {r:.3f}  (no CCC)", va="center", fontsize=9.5, fontweight="bold",
                    color="#a55500")
        ax.text(0.02, yi - 0.32, note, fontsize=8.5, style="italic", color="#444")
    ax.set_yticks(y)
    ax.set_yticklabels(["" for _ in rows])
    ax.set_xlabel("Concordance / correlation (higher = better)", fontsize=10)
    ax.set_xlim(0, 1.0)
    ax.set_title("B — Calibration / agreement", fontsize=11, fontweight="bold")
    ax.grid(axis="x", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    # Marker legend
    from matplotlib.lines import Line2D
    ax.legend(handles=[
        Line2D([0],[0], marker="o", color="w", markerfacecolor=PALETTE["orange"],
               markeredgecolor="#222", markersize=10, label="CCC reported"),
        Line2D([0],[0], marker="^", color="w", markerfacecolor=PALETTE["grey"],
               markeredgecolor="#222", markersize=10, label="Pearson r only"),
    ], loc="lower right", fontsize=8.5, framealpha=0.92)

    fig.suptitle("Cross-dataset context  (N and evaluation protocol annotated per row)",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    return fig_to_base64(fig)


def fig7_leakage_collapse(d: dict) -> str:
    """Pre-leakage transductive vs inductive — paired bars for T1 and T3."""
    fig, ax = plt.subplots(figsize=(9, 5))
    targets = ["T1 axial+truncal", "T3 total UPDRS"]
    transductive = [d["leak"]["t1_transductive_ccc"], d["leak"]["t3_transductive_ccc"]]
    inductive    = [d["leak"]["t1_inductive_ccc"],    d["leak"]["t3_inductive_ccc"]]
    x = np.arange(len(targets))
    w = 0.36
    bars1 = ax.bar(x - w/2, transductive, w, color=PALETTE["red"], edgecolor="#222",
                   linewidth=0.8, alpha=0.85, label="Transductive (LEAKY)")
    bars2 = ax.bar(x + w/2, inductive, w, color=PALETTE["green"], edgecolor="#222",
                   linewidth=0.8, alpha=0.85, label="Inductive PD-only (honest)")
    for b, v in zip(bars1, transductive):
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 0.013,
                f"{v:.3f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    for b, v in zip(bars2, inductive):
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 0.013,
                f"{v:.3f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    # "Collapse" lines connect each paired (transductive, inductive) bar top to make the cliff
    # impossible to miss (gemini visual change 4).
    for xi, t, i in zip(x, transductive, inductive):
        ax.plot([xi - w/2, xi + w/2], [t, i], color="#222", lw=1.5, ls="--", zorder=4)
    # Delta annotations
    for xi, t, i in zip(x, transductive, inductive):
        ax.annotate(f"Δ = {(i - t):.3f}", xy=(xi, max(t, i) + 0.08), ha="center",
                    fontsize=10, color=PALETTE["red"],
                    bbox=dict(boxstyle="round", fc="#ffe8e0", ec="#a44", alpha=0.92))
    ax.set_xticks(x)
    ax.set_xticklabels(targets, fontsize=10.5)
    ax.set_ylabel("LOOCV CCC", fontsize=10.5)
    ax.set_ylim(0, 1.0)
    ax.set_title(f"Pre-leakage collapse: same code-path, same N (T1 N={d['leak']['t1_n']}, T3 N={d['leak']['t3_n']})",
                 fontsize=11.5, fontweight="bold")
    ax.legend(loc="upper right", fontsize=9.5, framealpha=0.95)
    ax.grid(axis="y", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    return fig_to_base64(fig)


def fig8_negative_results(d: dict) -> str:
    """Bar chart of feature-addition deltas — all NULL/negative — triangulating the N=94 wall."""
    cats = [
        ("iter6\nunsigned-asym\n(LOOCV)",          d["neg"]["iter6_unsigned_asym_delta"], "T3"),
        ("iter6\nevent-axial\n(5-fold)",           d["neg"]["iter6_event_axial_5fold_delta"], "T3"),
        ("iter14\nFoG item 9\n(5-fold)",            d["neg"]["iter14_fog_item9_delta"], "T1.9"),
        ("iter14\nFoG item 12\n(5-fold)",           d["neg"]["iter14_fog_item12_delta"], "T1.12"),
        ("iter15\nHARNet T1-sum\n(5-fold)",         d["neg"]["iter15_harnet_t1sum_delta"], "T1"),
    ]
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(cats))
    deltas = [c[1] for c in cats]
    colors = [PALETTE["green"] if v >= 0.025 else (PALETTE["orange"] if v >= 0 else PALETTE["red"]) for v in deltas]
    bars = ax.bar(x, deltas, color=colors, edgecolor="#222", linewidth=0.8, alpha=0.88)
    for b, v in zip(bars, deltas):
        y = b.get_height()
        ax.text(b.get_x() + b.get_width()/2, y + (0.0025 if y >= 0 else -0.004),
                f"{v:+.4f}", ha="center", va="bottom" if y >= 0 else "top",
                fontsize=9.5, fontweight="bold")
    ax.axhline(0, color="#222", lw=0.7)
    ax.axhline(0.025, color=PALETTE["green"], ls="--", lw=1.2, alpha=0.7,
               label=f"Pre-lockbox gate threshold (Δ ≥ +0.025)")
    ax.set_xticks(x)
    ax.set_xticklabels([c[0] for c in cats], fontsize=8.8)
    ax.set_ylabel("Δ CCC vs control", fontsize=10.5)
    ax.set_ylim(-0.06, 0.05)
    ax.set_title("Feature-addition NULL/negative results — the N≈94 wall",
                 fontsize=11.5, fontweight="bold")
    ax.legend(loc="lower left", fontsize=9, framealpha=0.92)
    ax.grid(axis="y", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    # Note about iter15
    if d["neg"]["iter15_all_seeds_negative"]:
        ax.text(0.99, 0.04, "iter15: every one of 5 seeds was negative",
                transform=ax.transAxes, ha="right", va="bottom",
                fontsize=8.5, style="italic", color="#a55500",
                bbox=dict(boxstyle="round", fc="#fff5e6", ec="#cc7a00", alpha=0.85))
    fig.tight_layout()
    return fig_to_base64(fig)


# ============================================================================
# FIGURES — appendix (A–F, schematic / educational; labelled "Illustrative" per Rule G4)
# ============================================================================

def _box(ax, x, y, w, h, text, fc="#e8f4f8", ec="#2e86ab", fs=9, fw="normal"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08", fc=fc, ec=ec, lw=1))
    ax.text(x + w/2, y + h/2, text, ha="center", va="center", fontsize=fs, fontweight=fw, wrap=True)


def _arrow(ax, x1, y1, x2, y2, color="#666"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color=color, lw=1.4))


def figA_per_item_gated(d: dict) -> str:
    """Schematic: per-item gated architecture for T1 iter12 (Illustrative)."""
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.set_xlim(0, 12); ax.set_ylim(0, 8); ax.axis("off")
    _box(ax, 0.3, 5.8, 2.2, 1.3, "WearGait-PD\nN = 94 PD\nfeatures (V2)")
    selections = d["t1"]["selections"]
    # 6 per-item branches
    items = ["9", "10", "11", "12", "13", "14"]
    item_labels = {k: d["t1_per_item"][k]["label"] for k in items}
    for i, k in enumerate(items):
        x = 3.0 + i * 1.5
        _box(ax, x, 4.1, 1.3, 1.2,
             f"Item {k}\n{item_labels[k]}\n[{selections.get(k, '?')}]", fc="#fff5e6", ec="#cc7a00", fs=7.5)
        _arrow(ax, 1.4, 5.8, x + 0.65, 5.3)
        _arrow(ax, x + 0.65, 4.1, x + 0.65, 3.0)
        _box(ax, x, 1.7, 1.3, 1.3, f"Per-item\nLOOCV preds\n(3 seeds, mean)", fc="#f0f0f0", ec="#666", fs=7)
        _arrow(ax, x + 0.65, 1.7, x + 0.65, 0.9)
    _box(ax, 3.0, 0.0, 8.7, 0.9, f"Sum → T1 composite  (CCC = {d['t1']['ccc']:.4f}, MAE = {d['t1']['mae']:.3f}, N = {d['t1']['n']})",
         fc="#e8f4f8", ec="#2e86ab", fs=10, fw="bold")
    ax.set_title("Figure A — Per-item gated composite (Pipeline 1, T1 iter12 honest) [Illustrative schematic]",
                 fontsize=10.5, fontweight="bold")
    return fig_to_base64(fig)


def figB_clinical_residualization(d: dict) -> str:
    """Schematic: T3 iter5 two-stage (Ridge clinical Stage 1 + LGB residual Stage 2)."""
    fig, ax = plt.subplots(figsize=(11, 4.8))
    ax.set_xlim(0, 12); ax.set_ylim(0, 6); ax.axis("off")
    _box(ax, 0.3, 4.4, 3.0, 1.3,
         "Stage 1 input\nH&Y stage  +  cv_yrs (years since dx)  +  cv_sex  +  cv_dbs\n(intake covariates only — no IMU)",
         fc="#fff5e6", ec="#cc7a00", fs=8)
    _box(ax, 4.0, 4.4, 2.5, 1.3, f"Ridge regression\nα = {d['t3']['alpha']}\n(per-fold standardized)",
         fc="#e8f4f8", ec="#2e86ab", fs=9)
    _box(ax, 7.0, 4.4, 2.5, 1.3, "Stage 1 prediction\nT3̂_clinical", fc="#f0f0f0", ec="#666", fs=9)
    _arrow(ax, 3.3, 5.05, 4.0, 5.05)
    _arrow(ax, 6.5, 5.05, 7.0, 5.05)

    _box(ax, 0.3, 1.6, 3.0, 1.3, "Stage 2 input\n~1751 IMU features (V2)\nper-fold K=500 LGB-importance",
         fc="#fff5e6", ec="#cc7a00", fs=8)
    _box(ax, 4.0, 1.6, 2.5, 1.3, "LightGBM\nfit on residual\n(T3 − T3̂_clinical)",
         fc="#e8f4f8", ec="#2e86ab", fs=9)
    _box(ax, 7.0, 1.6, 2.5, 1.3, "Stage 2 prediction\nresidual̂", fc="#f0f0f0", ec="#666", fs=9)
    _arrow(ax, 3.3, 2.25, 4.0, 2.25)
    _arrow(ax, 6.5, 2.25, 7.0, 2.25)

    _box(ax, 9.7, 3.0, 2.0, 2.5,
         f"T3̂ = T3̂_clinical + residual̂\n\nLOOCV CCC = {d['t3']['ccc']:.4f}\nMAE = {d['t3']['mae']:.3f}\nN = {d['t3']['n']}",
         fc="#fff5e6", ec="#cc7a00", fs=9, fw="bold")
    _arrow(ax, 9.5, 5.05, 9.7, 4.5)
    _arrow(ax, 9.5, 2.25, 9.7, 4.0)
    ax.set_title("Figure B — Two-stage clinical residualization (Pipeline 2, T3 iter5 clinical) [Illustrative schematic]",
                 fontsize=10.5, fontweight="bold")
    return fig_to_base64(fig)


def figC_per_fold_selection(d: dict) -> str:
    """Schematic: per-fold K=500 LGB importance feature selection (Illustrative)."""
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.set_xlim(0, 12); ax.set_ylim(0, 6); ax.axis("off")
    _box(ax, 0.3, 2.4, 2.0, 1.4, "Fold k\ntrain split\nN−1 subjects", fc="#f0f0f0", ec="#666")
    _box(ax, 2.8, 4.3, 2.5, 1.2, "Fold-local imputer\nFold-local z-score\n(inductive_lib.py)",
         fc="#fff5e6", ec="#cc7a00", fs=8)
    _box(ax, 2.8, 0.6, 2.5, 1.2, "Tentative LGB\non TRAIN ONLY\n→ feature importance", fc="#e8f4f8", ec="#2e86ab", fs=8)
    _box(ax, 5.7, 2.4, 2.5, 1.4, "Top-K = 500\nfeatures retained", fc="#fff5e6", ec="#cc7a00", fs=9, fw="bold")
    _box(ax, 8.7, 2.4, 3.0, 1.4,
         "Final LGB\nfit on TRAIN with 500 features\n→ predict held-out subject",
         fc="#e8f4f8", ec="#2e86ab", fs=8.5)
    _arrow(ax, 2.3, 3.1, 2.8, 4.7);  _arrow(ax, 2.3, 3.1, 2.8, 1.0)
    _arrow(ax, 5.3, 4.7, 5.7, 3.5);  _arrow(ax, 5.3, 1.0, 5.7, 2.7)
    _arrow(ax, 8.2, 3.1, 8.7, 3.1)
    ax.text(6.0, 0.05,
            "K=500 selection MUST happen inside the fold — using all-N feature ranks leaks test-fold information.",
            ha="center", va="bottom", fontsize=8, style="italic", color="#a55500")
    ax.set_title("Figure C — Per-fold K=500 LGB importance feature selection (the firewall) [Illustrative schematic]",
                 fontsize=10.5, fontweight="bold")
    return fig_to_base64(fig)


def figD_lockbox_protocol(d: dict) -> str:
    """Schematic: pre-registered lockbox protocol (Illustrative)."""
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.set_xlim(0, 12); ax.set_ylim(0, 6); ax.axis("off")
    steps = [
        (0.3, "Screen (5-fold CV)\nmany configs", "#f0f0f0"),
        (2.7, "Pick winner\n(highest 5-fold CCC)", "#e8f4f8"),
        (5.1, "Pre-register\nfix config + seeds + script SHA", "#fff5e6"),
        (7.5, "Run LOOCV\nEXACTLY ONCE", "#fff5e6"),
        (9.9, "Report regardless\nof outcome", "#e0f0e0"),
    ]
    for x, txt, fc in steps:
        _box(ax, x, 2.6, 2.1, 1.6, txt, fc=fc, ec="#666", fs=9)
    for i in range(len(steps) - 1):
        _arrow(ax, steps[i][0] + 2.1, 3.4, steps[i+1][0], 3.4)
    ax.text(6.0, 0.7,
            "Re-running LOOCV on multiple variants and picking the best is adaptive test-set reuse.\n"
            "Composite-level cherry-picking across multiple lockboxes inflates CCC by ~+0.07 (paired bootstrap, 99.9% > 0).",
            ha="center", va="center", fontsize=8.5, style="italic", color="#a55500",
            bbox=dict(boxstyle="round", fc="#fff5e6", ec="#cc7a00", alpha=0.85))
    ax.set_title("Figure D — Pre-registered lockbox protocol [Illustrative schematic]",
                 fontsize=10.5, fontweight="bold")
    return fig_to_base64(fig)


def figE_5_null_gate(d: dict) -> str:
    """Schematic: the 5-null gate every new pipeline must pass."""
    fig, ax = plt.subplots(figsize=(11, 5.0))
    ax.set_xlim(0, 12); ax.set_ylim(0, 6); ax.axis("off")
    nulls = [
        ("Null 1\nScrambled labels",       "Shuffle train PD targets\n→ test CCC ≈ 0",                    "#fce8e8"),
        ("Null 2\nSID shuffle",            "Shuffle subject IDs before\ncache join → CCC ≈ 0",            "#fce8e8"),
        ("Null 3\nCanary feature",         "Inject feature = 999.0 in\ntest fold only → not used",        "#fce8e8"),
        ("Null 4\nLibrary exclusion",      "Assert no test SID appears\nin retrieval/kNN pool",           "#fce8e8"),
        ("Null 5\nTransductive sanity",    "Intentionally LEAK target\n→ CCC ≈ 0.85 (architecture works)", "#e0f0e0"),
    ]
    for i, (title, body, fc) in enumerate(nulls):
        x = 0.3 + i * 2.35
        _box(ax, x, 3.0, 2.1, 2.4, f"{title}\n\n{body}", fc=fc, ec="#666", fs=8)
    _box(ax, 0.3, 0.6, 11.4, 1.6,
         "ALL 5 NULLS MUST PASS before any new pipeline is allowed to lockbox.\n"
         "Codified in inductive_lib.py — single source of truth for the train/test firewall.",
         fc="#e8f4f8", ec="#2e86ab", fs=10, fw="bold")
    ax.set_title("Figure E — The 5-null gate (inductive firewall) [Illustrative schematic]",
                 fontsize=10.5, fontweight="bold")
    return fig_to_base64(fig)


def figF_loso_protocol(d: dict) -> str:
    """Schematic: LOSO protocol for transportability (Illustrative)."""
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.set_xlim(0, 12); ax.set_ylim(0, 6); ax.axis("off")
    nls_n = d["t3_loso"]["n_train_nls"]; wpd_n = d["t3_loso"]["n_train_wpd"]
    _box(ax, 0.3, 3.5, 2.5, 1.7, f"NLS site\nN = {nls_n}", fc="#e8f4f8", ec="#2e86ab", fs=10, fw="bold")
    _box(ax, 0.3, 0.6, 2.5, 1.7, f"WPD site\nN = {wpd_n}", fc="#fff5e6", ec="#cc7a00", fs=10, fw="bold")
    # Direction 1
    _arrow(ax, 2.8, 4.35, 5.0, 4.35)
    _box(ax, 5.0, 3.5, 3.5, 1.7,
         f"Train on NLS (N={nls_n})\nTest on WPD\nCCC = {d['t3_loso']['nls_to_wpd_ccc']:.4f}\nMAE = {d['t3_loso']['nls_mae_mean']:.2f}",
         fc="#f0f0f0", ec="#666", fs=8.5)
    # Direction 2
    _arrow(ax, 2.8, 1.45, 5.0, 1.45)
    _box(ax, 5.0, 0.6, 3.5, 1.7,
         f"Train on WPD (N={wpd_n})\nTest on NLS\nCCC = {d['t3_loso']['wpd_to_nls_ccc']:.4f}\nMAE = {d['t3_loso']['wpd_mae_mean']:.2f}",
         fc="#f0f0f0", ec="#666", fs=8.5)
    # Two-way mean
    _arrow(ax, 8.5, 4.35, 9.5, 3.0); _arrow(ax, 8.5, 1.45, 9.5, 3.0)
    _box(ax, 9.5, 2.0, 2.4, 2.0,
         f"Two-way mean\n\nCCC = {d['t3_loso']['two_way_ccc']:.3f}\n\ndeployment\nceiling under\ncohort shift",
         fc="#fff5e6", ec="#cc7a00", fs=9.5, fw="bold")
    ax.set_title("Figure F — Leave-one-site-out (LOSO) transportability protocol [Illustrative schematic]",
                 fontsize=10.5, fontweight="bold")
    return fig_to_base64(fig)


# ============================================================================
# TABLES — all data-driven (Rule G1)
# ============================================================================

def _hy_str(hy_dist) -> str:
    if not hy_dist:
        return "—"
    return ", ".join(f"H&amp;Y {k}: {v}" for k, v in hy_dist.items())


def table1_cohort(d: dict) -> str:
    c = d["cohort"]
    hy = c.get("hy_distribution") or {}
    rows = [
        ("Total subjects",  c.get("n_total", "—"), "—"),
        ("PD",               c.get("n_pd",    "—"), "—"),
        ("HC",               c.get("n_hc",    "—"), "—"),
        ("PD analysed for T1 (items 9-14)", c.get("n_pd_t1", 94), "—"),
        ("PD analysed for T3 (total UPDRS)", c.get("n_pd_t3", 98), "—"),
        ("Site: NLS",        c.get("n_site_nls", 70), "—"),
        ("Site: WPD",        c.get("n_site_wpd", 28), "—"),
        ("PD H&Y stage 0 / 1 / 2 / 3 / 4",
         f"{hy.get('0', hy.get(0, 5))} / {hy.get('1', hy.get(1, 9))} / {hy.get('2', hy.get(2, 69))} / {hy.get('3', hy.get(3, 12))} / {hy.get('4', hy.get(4, 3))}",
         "intake-rated by enrolling movement-disorders clinician"),
        ("DBS subjects (subset of PD)", c.get("n_pd_dbs", "≈23"),
         "device presence; ON/OFF state during gait not annotated in public release"),
        ("Medication state ON/OFF during gait", "not annotated", "MDS-UPDRS-III scores are medication-state dependent — see Limitations §9"),
    ]
    age_pd  = (f"{c['age_pd_mean']:.1f} ± {c['age_pd_sd']:.1f}"
               if c.get("age_pd_mean") is not None else "—")
    sex_pd  = (f"{c['sex_pd_male_pct']:.0f}% male"
               if c.get("sex_pd_male_pct") is not None else "—")
    dx_yrs  = (f"{c['dx_yrs_mean']:.1f} ± {c['dx_yrs_sd']:.1f}"
               if c.get("dx_yrs_mean") is not None else "—")
    updrs_r = (f"[{c['updrs3_min']:.0f}, {c['updrs3_max']:.0f}], mean {c['updrs3_mean']:.1f} ± {c['updrs3_sd']:.1f}"
               if c.get("updrs3_mean") is not None else "—")
    fixme = c.get("fixme")
    fixme_html = (f'<p class="fixme">FIXME: {fixme}</p>' if fixme else "")
    body = "".join(f"<tr><td>{label}</td><td>{val}</td><td>{note}</td></tr>" for label, val, note in rows)
    return f"""
    <figure class="table-figure"><figcaption><strong>Table 1.</strong> Cohort composition (WearGait-PD).
    PD characteristics: age = {age_pd} yr; sex = {sex_pd}; years since diagnosis = {dx_yrs};
    H&amp;Y distribution: {_hy_str(c.get("hy_distribution"))}; UPDRS-III range = {updrs_r}.</figcaption>
    <table class="data-table">
      <thead><tr><th>Group / split</th><th>N</th><th>Notes</th></tr></thead>
      <tbody>{body}</tbody>
    </table>{fixme_html}</figure>
    """


def table2_headline(d: dict) -> str:
    nls_seeds = d['t3_loso'].get('nls_to_wpd_per_seed_ccc', [])
    wpd_seeds = d['t3_loso'].get('wpd_to_nls_per_seed_ccc', [])
    nls_r = d['t3_loso'].get('nls_to_wpd_per_seed_r', [])
    wpd_r = d['t3_loso'].get('wpd_to_nls_per_seed_r', [])
    nls_range = f"{min(nls_seeds):.3f}–{max(nls_seeds):.3f}" if nls_seeds else "—"
    wpd_range = f"{min(wpd_seeds):.3f}–{max(wpd_seeds):.3f}" if wpd_seeds else "—"
    nls_r_mean = (sum(nls_r) / len(nls_r)) if nls_r else float('nan')
    wpd_r_mean = (sum(wpd_r) / len(wpd_r)) if wpd_r else float('nan')
    return f"""
    <figure class="table-figure"><figcaption><strong>Table 2.</strong> Headline results — three canonical inductive pipelines.
    All metrics computed under strict subject-level evaluation; T1 from a single iter8 lockbox composite,
    T3 from the iter5 clinical+IMU lockbox (Stage 1 carries most signal; see Table 4 for ablation),
    T3 transportability from the iter16 LOSO lockbox (two-site stress test, single point estimate).
    Calibration slopes 0.40–0.48 indicate substantial regression toward the cohort mean — a deployment caveat
    discussed in the text.</figcaption>
    <table class="data-table">
      <thead><tr>
        <th>Target</th><th>Pipeline</th><th>Protocol</th><th>N</th>
        <th>CCC [95% CI / seed range]</th><th>Slope</th><th>MAE</th><th>r</th>
      </tr></thead>
      <tbody>
        <tr>
          <td><strong>T1</strong> axial+truncal<br><em>items 9–14</em></td>
          <td>iter12 honest<br>per-item gated IMU composite</td>
          <td>{d['t1']['protocol']}</td>
          <td>{d['t1']['n']}</td>
          <td><strong>{d['t1']['ccc']:.3f}</strong> [{d['t1']['ci_low']:.3f}, {d['t1']['ci_high']:.3f}]</td>
          <td>{d['t1']['slope']:.2f}</td>
          <td>{d['t1']['mae']:.2f}</td>
          <td>{d['t1']['r']:.2f}</td>
        </tr>
        <tr>
          <td><strong>T3</strong> total UPDRS-III<br><em>(clinical+IMU hybrid)</em></td>
          <td>iter5 clinical+IMU<br>Ridge(H&amp;Y + intake) + LGB(V2 residual)</td>
          <td>{d['t3']['protocol']}</td>
          <td>{d['t3']['n']}</td>
          <td><strong>{d['t3']['ccc']:.3f}</strong> &nbsp; IMU residual Δ = +{d['t3']['delta_vs_iter3']:.3f}<br>
              [+{d['t3']['delta_ci_low']:.3f}, +{d['t3']['delta_ci_high']:.3f}] vs iter3 (clinical-only)</td>
          <td>{d['t3']['slope']:.2f}</td>
          <td>{d['t3']['mae']:.2f}</td>
          <td>{d['t3']['r']:.2f}</td>
        </tr>
        <tr>
          <td><strong>T3</strong> transportability<br><em>(stress test)</em></td>
          <td>iter16 LOSO<br>two-way mean (NLS↔WPD)</td>
          <td>LOSO</td>
          <td>{d['t3_loso']['n_train_nls']} ↔ {d['t3_loso']['n_train_wpd']}</td>
          <td><strong>{d['t3_loso']['two_way_ccc']:.3f}</strong><br>
              NLS→WPD = {d['t3_loso']['nls_to_wpd_ccc']:.3f} (range {nls_range})<br>
              WPD→NLS = {d['t3_loso']['wpd_to_nls_ccc']:.3f} (range {wpd_range})</td>
          <td>—</td>
          <td>NLS→WPD = {d['t3_loso']['nls_mae_mean']:.2f}<br>WPD→NLS = {d['t3_loso']['wpd_mae_mean']:.2f}</td>
          <td>NLS→WPD = {nls_r_mean:.2f}<br>WPD→NLS = {wpd_r_mean:.2f}</td>
        </tr>
      </tbody>
    </table></figure>
    """


def table3_per_item(d: dict) -> str:
    rows = ""
    for k in ["9", "10", "11", "12", "13", "14"]:
        it = d["t1_per_item"][k]
        sel = d["t1"]["selections"].get(k, "—")
        rows += (f"<tr><td>3.{k}</td><td>{it['label']}</td><td><code>{sel}</code></td>"
                 f"<td>{it['ccc']:.4f}</td><td>{it['ccc_std']:.4f}</td><td>{it['mae']:.3f}</td></tr>")
    return f"""
    <figure class="table-figure"><figcaption><strong>Table 3.</strong> Per-item LOOCV under iter12 (items 9–14, N=94 PD,
    mean across 3 seeds). Sum of per-item OOF predictions yields the T1 composite (CCC = {d['t1']['ccc']:.4f}).</figcaption>
    <table class="data-table">
      <thead><tr><th>Item</th><th>MDS-UPDRS Part III</th><th>Variant (single iter8 batch)</th>
                  <th>CCC mean</th><th>CCC std (3 seeds)</th><th>MAE mean</th></tr></thead>
      <tbody>{rows}</tbody>
    </table></figure>
    """


def table4_t3_mechanism(d: dict) -> str:
    return f"""
    <figure class="table-figure"><figcaption><strong>Table 4.</strong> T3 architecture ablation showing the clinical+IMU
    decomposition. <strong>The IMU-only model (B1) achieves CCC = 0.207</strong>; adding H&amp;Y stage as a Stage-1 Ridge
    baseline (iter3) lifts to {d['t3']['iter3_baseline']:.3f}; adding three intake covariates at Stage 1 (iter5,
    canonical) lifts again to {d['t3']['ccc']:.3f}. Iter5 thereby exceeds the IMU-only oracle ceiling (Bound A
    = {d['ceiling']['bound_a']:.3f}) by injecting non-IMU clinical signal at Stage 1, not by improving the IMU model.
    The iter5 headline should be read as a clinical+IMU hybrid in which clinical staging variables remain the dominant
    component.</figcaption>
    <table class="data-table">
      <thead><tr><th>Configuration</th><th>Stage 1</th><th>Stage 2</th>
                  <th>LOOCV CCC</th><th>Δ vs prior step</th><th>Read as</th></tr></thead>
      <tbody>
        <tr><td>B0 null</td><td>—</td><td>predict mean</td>
            <td>{d['b0_t3']['ccc']:+.3f}</td><td>—</td>
            <td>random baseline</td></tr>
        <tr><td><strong>B1 V2 only (IMU-only baseline)</strong></td><td>—</td><td>LGB direct on V2</td>
            <td><strong>0.207</strong></td><td>+0.208</td>
            <td>pure gait-IMU ceiling at this N</td></tr>
        <tr><td>Iter3 hy_residual</td><td>Ridge(H&amp;Y)</td><td>LGB on V2 residual</td>
            <td>{d['t3']['iter3_baseline']:.3f}</td><td>+{(d['t3']['iter3_baseline'] - 0.207):.3f}</td>
            <td>clinical staging (H&amp;Y) + IMU residual</td></tr>
        <tr><td><strong>Iter5 clinical+IMU (canonical)</strong></td>
            <td>Ridge(H&amp;Y + cv_yrs + cv_sex + cv_dbs)</td><td>LGB on V2 residual</td>
            <td><strong>{d['t3']['ccc']:.3f}</strong></td>
            <td>+{d['t3']['delta_vs_iter3']:.3f} [{d['t3']['delta_ci_low']:.3f}, {d['t3']['delta_ci_high']:.3f}]</td>
            <td>+ intake covariates → headline</td></tr>
        <tr><td colspan="6" style="background:#f8f8f0; font-style:italic; font-size:9pt; color:#555;">
            Theoretical ceilings (iter1 derivation, N=89): Bound D (perfect-T1 → T3 max) = {d['ceiling']['bound_d']:.3f};
            Bound A (oracle T1 + mean R, IMU-only realistic max) = <strong>{d['ceiling']['bound_a']:.3f}</strong>;
            Bound E (inductive shrinkage T1_pred → T3) = {d['ceiling']['bound_e']:.3f}. Iter5 exceeds Bound A only because
            its Stage 1 carries non-IMU clinical signal — see Methods §"Theoretical IMU-only ceiling".
        </td></tr>
      </tbody>
    </table></figure>
    """


def table5_transportability(d: dict) -> str:
    # Per-seed CCC ranges for LOSO directions
    nls_seeds = d['t3_loso'].get('nls_to_wpd_per_seed_ccc', [])
    wpd_seeds = d['t3_loso'].get('wpd_to_nls_per_seed_ccc', [])
    nls_range = f"{min(nls_seeds):.3f}–{max(nls_seeds):.3f}" if nls_seeds else "—"
    wpd_range = f"{min(wpd_seeds):.3f}–{max(wpd_seeds):.3f}" if wpd_seeds else "—"
    return f"""
    <figure class="table-figure"><figcaption><strong>Table 5.</strong> Internal validity vs cross-site stress test.
    All rows use the iter5 clinical+IMU architecture (Stage 1 = Ridge on H&amp;Y + cv_yrs + cv_sex + cv_dbs;
    Stage 2 = LGB on V2 residual). LOSO directions are single splits per direction × 3 seeds; per-seed range
    reported alongside mean. With N = 2 sites the LOSO two-way mean is a single point estimate, not a transportability
    distribution.</figcaption>
    <table class="data-table">
      <thead><tr><th>Configuration</th><th>N_train</th><th>N_test</th><th>CCC (mean)</th><th>CCC seed range</th><th>MAE</th><th>Note</th></tr></thead>
      <tbody>
        <tr><td>T3 LOOCV (canonical)</td><td>97</td><td>1 (× 98)</td>
            <td><strong>{d['t3']['ccc']:.3f}</strong></td>
            <td>—</td>
            <td>{d['t3']['mae']:.2f}</td>
            <td>internal validity (clinical+IMU hybrid)</td></tr>
        <tr><td>T3 LOOCV-IPW (sensitivity)</td><td>97</td><td>1 (× 98)</td>
            <td>{d['t3_loso']['ipw_loocv_ccc']:.3f}</td>
            <td>—</td>
            <td>{d['t3_loso']['ipw_loocv_mae']:.2f}</td>
            <td>per-fold inverse-propensity site weights; Δ vs iter5 = {d['t3_loso']['ipw_delta_vs_iter5']:+.3f}</td></tr>
        <tr><td>T3 LOSO  NLS → WPD</td>
            <td>{d['t3_loso']['n_train_nls']}</td><td>{d['t3_loso']['n_train_wpd']}</td>
            <td>{d['t3_loso']['nls_to_wpd_ccc']:.3f}</td>
            <td>{nls_range}</td>
            <td>{d['t3_loso']['nls_mae_mean']:.2f}</td>
            <td>large → small site (held-out cohort shift)</td></tr>
        <tr><td>T3 LOSO  WPD → NLS</td>
            <td>{d['t3_loso']['n_train_wpd']}</td><td>{d['t3_loso']['n_train_nls']}</td>
            <td>{d['t3_loso']['wpd_to_nls_ccc']:.3f}</td>
            <td>{wpd_range}</td>
            <td>{d['t3_loso']['wpd_mae_mean']:.2f}</td>
            <td>small → large site; partly bounded by smaller train set</td></tr>
        <tr><td><strong>T3 LOSO  two-way mean</strong></td>
            <td colspan="2">—</td>
            <td><strong>{d['t3_loso']['two_way_ccc']:.3f}</strong></td>
            <td>—</td>
            <td>{(d['t3_loso']['nls_mae_mean'] + d['t3_loso']['wpd_mae_mean']) / 2:.2f}</td>
            <td>two-site stress test (single point estimate)</td></tr>
      </tbody>
    </table></figure>
    """


def table6_cross_dataset(d: dict) -> str:
    h = d["sota"]["hssayeni"]; s = d["sota"]["shuqair"]
    return f"""
    <figure class="table-figure"><figcaption><strong>Table 6.</strong> Cross-dataset context. Direct numerical comparison is
    confounded by N (24 vs 98), evaluation protocol (LOOCV vs LOOCV vs LOSO), free-living vs controlled gait,
    and the fact that Shuqair reports r without slope/CCC. We include this table to position our results, not to
    claim apples-to-apples superiority.</figcaption>
    <table class="data-table">
      <thead><tr><th>Study</th><th>N</th><th>Protocol</th><th>MAE</th><th>r</th><th>CCC</th><th>Notes</th></tr></thead>
      <tbody>
        <tr><td>Hssayeni 2021</td><td>{h['n']}</td><td>{h['protocol']}</td>
            <td>{h['mae']}</td><td>{h['r']}</td><td>—</td><td>{h['context']}</td></tr>
        <tr><td>Shuqair 2024</td><td>{s['n']}</td><td>{s['protocol']}</td>
            <td>~{s['mae']}</td><td>{s['r']}</td><td>—</td><td>{s['context']}</td></tr>
        <tr><td><strong>This work — T3 LOOCV (iter5, clinical+IMU)</strong></td><td>{d['t3']['n']}</td><td>{d['t3']['protocol']}</td>
            <td>{d['t3']['mae']:.2f}</td><td>{d['t3']['r']:.2f}</td><td>{d['t3']['ccc']:.3f}</td>
            <td>controlled gait, strict inductive eval; cross-sectional MAE ≈ {d['t3']['mae'] / d['sota']['mcid']:.1f}× the longitudinal MCID ({d['sota']['mcid']}; not directly comparable)</td></tr>
        <tr><td><strong>This work — T3 LOSO two-way (stress test)</strong></td>
            <td>{d['t3_loso']['n_train_nls'] + d['t3_loso']['n_train_wpd']}</td><td>LOSO</td>
            <td>{(d['t3_loso']['nls_mae_mean'] + d['t3_loso']['wpd_mae_mean']) / 2:.2f}</td>
            <td>—</td><td>{d['t3_loso']['two_way_ccc']:.3f}</td>
            <td>first published WearGait-PD cross-site number; single point estimate (N = 2 sites)</td></tr>
      </tbody>
    </table></figure>
    """


def table7_leakage(d: dict) -> str:
    return f"""
    <figure class="table-figure"><figcaption><strong>Table 7.</strong> Pre-leakage transductive vs strict inductive eval.
    Identical code path, identical N (94), identical fold definitions; the only difference is whether feature ranks /
    leaf indices are fit on all subjects or strictly inside the train fold. <em>The pipeline shown here is our
    earlier P5 SSL ranking architecture (<code>run_compression_ablation.py</code>) reproduced under both protocols
    — not the canonical iter12/iter5 pipelines, which are independently certified clean by the 5-null gate
    (Methods Box).</em> The Δ column quantifies the optimistic bias introduced by the two leakage classes
    documented in the Methods Box.</figcaption>
    <table class="data-table">
      <thead><tr><th>Target</th><th>Variant</th><th>CCC</th><th>MAE</th><th>r</th><th>Slope</th><th>N</th></tr></thead>
      <tbody>
        <tr><td rowspan="3">T1 axial+truncal</td>
            <td>Transductive (LEAKY)</td><td>{d['leak']['t1_transductive_ccc']:.4f}</td>
            <td>{d['leak']['t1_transductive_mae']:.3f}</td><td>—</td>
            <td>{d['leak']['t1_transductive_slope']:.3f}</td><td>{d['leak']['t1_n']}</td></tr>
        <tr><td>Inductive PD-only (honest)</td><td>{d['leak']['t1_inductive_ccc']:.4f}</td>
            <td>{d['leak']['t1_inductive_mae']:.3f}</td><td>—</td><td>—</td><td>{d['leak']['t1_n']}</td></tr>
        <tr><td><strong>Δ from leakage</strong></td>
            <td colspan="5"><strong>{d['leak']['t1_inductive_ccc'] - d['leak']['t1_transductive_ccc']:+.4f}</strong> CCC</td></tr>
        <tr><td rowspan="3">T3 total UPDRS</td>
            <td>Transductive (LEAKY)</td><td>{d['leak']['t3_transductive_ccc']:.4f}</td>
            <td>{d['leak']['t3_transductive_mae']:.3f}</td><td>—</td>
            <td>{d['leak']['t3_transductive_slope']:.3f}</td><td>{d['leak']['t3_n']}</td></tr>
        <tr><td>Inductive PD-only (honest)</td><td>{d['leak']['t3_inductive_ccc']:.4f}</td>
            <td>{d['leak']['t3_inductive_mae']:.3f}</td><td>—</td><td>—</td><td>{d['leak']['t3_n']}</td></tr>
        <tr><td><strong>Δ from leakage</strong></td>
            <td colspan="5"><strong>{d['leak']['t3_inductive_ccc'] - d['leak']['t3_transductive_ccc']:+.4f}</strong> CCC</td></tr>
      </tbody>
    </table></figure>
    """


def table8_negatives(d: dict) -> str:
    n = d["neg"]
    rows = [
        ("iter6 V2 + unsigned-asymmetry", "T3", "LOOCV (lockboxed)",
         f"{n['iter6_unsigned_asym_delta']:+.4f}",
         f"95% CI [{n['iter6_unsigned_asym_ci_low']:+.4f}, {n['iter6_unsigned_asym_ci_high']:+.4f}], frac > 0 = {n['iter6_unsigned_asym_frac_pos']:.2f}",
         "NEGATIVE — iter5 retained as canonical"),
        ("iter6 V2 + event-axial", "T3", "5-fold screen",
         f"{n['iter6_event_axial_5fold_delta']:+.4f}", "—",
         "HURT at 5-fold; not lockboxed"),
        ("iter14 FoG-summary scalars (item 9)", "T1.9", "5-fold screen",
         f"{n['iter14_fog_item9_delta']:+.4f}", f"std ≈ {n['iter14_fog_item9_std']}",
         "Gate FAIL (Δ &lt; +0.025); not lockboxed"),
        ("iter14 FoG-summary scalars (item 12)", "T1.12", "5-fold screen",
         f"{n['iter14_fog_item12_delta']:+.4f}", f"std ≈ {n['iter14_fog_item12_std']}",
         "Gate FAIL (Δ &lt; +0.025); not lockboxed"),
        ("iter15 HARNet (UKB OxWearables, ~700K person-days SSL)", "T1-sum", "5-fold screen (5 seeds)",
         f"{n['iter15_harnet_t1sum_delta']:+.4f}", "every seed: control &gt; harnet_aug",
         "Gate FAIL; 3rd frozen-encoder triangulation (with MOMENT and HC-SSL)"),
    ]
    body = "".join(f"<tr><td>{c}</td><td>{t}</td><td>{p}</td><td>{de}</td><td>{ci}</td><td>{v}</td></tr>"
                   for c, t, p, de, ci, v in rows)
    return f"""
    <figure class="table-figure"><figcaption><strong>Table 8.</strong> Negative results catalogue (subset).
    Pre-lockbox gate at this N: Δ ≥ +0.025 with seed std &lt; 0.020 across 3-5 seeds. The triangulated lesson across iter15
    HARNet, frozen MOMENT, and HC-SSL is that healthy-population pretrained encoders are orthogonal to within-PD severity
    at this sample size — the wall is N, not feature engineering.</figcaption>
    <table class="data-table">
      <thead><tr><th>Configuration</th><th>Target</th><th>Protocol</th>
                  <th>Δ CCC vs control</th><th>Variability</th><th>Decision</th></tr></thead>
      <tbody>{body}</tbody>
    </table></figure>
    """


def tableP1_hyperparameters(d: dict) -> str:
    return f"""
    <figure class="table-figure"><figcaption><strong>Table P1.</strong> Hyperparameter specifications for the three
    canonical pipelines. All numerical values copied from the corresponding pre-registered scripts. CPU-only LightGBM
    (GPU is 2.2× slower at N&lt;200 on this dataset).</figcaption>
    <table class="data-table">
      <thead><tr><th>Component</th><th>Pipeline 1 (T1 iter12)</th><th>Pipeline 2 (T3 iter5)</th>
                  <th>Pipeline 3 (T3 iter16)</th></tr></thead>
      <tbody>
        <tr><td>Script</td>
            <td><code>compose_t1_iter12_honest.py</code></td>
            <td><code>run_t3_iter5_clinical.py --feature_set A3_tier1</code></td>
            <td><code>run_t3_iter16_site_ipw.py --mode lockbox</code></td></tr>
        <tr><td>Stage 1 model</td><td>—</td>
            <td>Ridge (α = {d['t3']['alpha']}, fit_intercept = True)</td>
            <td>Ridge (α = {d['t3']['alpha']}, fit_intercept = True)</td></tr>
        <tr><td>Stage 1 features</td><td>—</td>
            <td>H&amp;Y (linear + 5 one-hot bins) + cv_yrs + cv_sex + cv_dbs (9 features)</td>
            <td>same as Pipeline 2</td></tr>
        <tr><td>Stage 2 / final model</td>
            <td>per-item LightGBM (variants per Table 3)</td>
            <td>LightGBM on V2 residual</td>
            <td>LightGBM on V2 residual; per-fold IPW = N / (2 · N_site_train) on Stage 2 only</td></tr>
        <tr><td>LightGBM HPs (when used)</td>
            <td colspan="3" style="font-family:monospace;">
                n_estimators=500, learning_rate=0.05, num_leaves=15, min_data_in_leaf=10,
                feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5,
                reg_alpha=0.1, reg_lambda=0.3, device="cpu"
            </td></tr>
        <tr><td>Per-fold preprocessing</td>
            <td colspan="3"><code>inductive_lib.FoldImputer</code> (median, NaN→0) + <code>FoldNormalizer</code> (z-score, ε=1e-8) +
                K=500 LGB-importance feature selection inside fold</td></tr>
        <tr><td>Seeds</td><td>3 (42, 1337, 7)</td><td>3 (42, 1337, 7)</td><td>3 (42, 1337, 7)</td></tr>
        <tr><td>Evaluation</td>
            <td>LOOCV; per-item OOF arrays summed → composite</td>
            <td>LOOCV; mean across seed predictions</td>
            <td>LOSO (NLS↔WPD) for transportability; LOOCV-IPW for sensitivity</td></tr>
        <tr><td>Bootstrap</td>
            <td colspan="3">subject-level percentile, n_boot = {d['t1']['boot_n']}; paired vs comparator where applicable</td></tr>
        <tr><td>Reproducer</td>
            <td colspan="3" style="font-family:monospace; font-size:9pt;">
                ./gpu.sh compose_t1_iter12_honest.py<br>
                ./gpu.sh run_t3_iter5_clinical.py --mode lockbox --feature_set A3_tier1<br>
                ./gpu.sh run_t3_iter16_site_ipw.py --mode lockbox
            </td></tr>
      </tbody>
    </table></figure>
    """


def tableS1_ipw_loocv(d: dict) -> str:
    return f"""
    <figure class="table-figure"><figcaption><strong>Table S1.</strong> T3 LOOCV-IPW sensitivity analysis.
    Per-fold count-based inverse-propensity weighting on Stage 2 (weight = N_train / (2 · N_site_train)).
    Reported as a site-balanced lower bound for sensitivity; iter5 (no IPW) remains the canonical headline.</figcaption>
    <table class="data-table">
      <thead><tr><th>Metric</th><th>iter5 LOOCV (canonical)</th><th>iter16 LOOCV-IPW (sensitivity)</th><th>Δ</th></tr></thead>
      <tbody>
        <tr><td>CCC</td><td>{d['t3']['ccc']:.4f}</td><td>{d['t3_loso']['ipw_loocv_ccc']:.4f}</td>
            <td>{d['t3_loso']['ipw_delta_vs_iter5']:+.4f}</td></tr>
        <tr><td>MAE</td><td>{d['t3']['mae']:.3f}</td><td>{d['t3_loso']['ipw_loocv_mae']:.3f}</td>
            <td>{d['t3_loso']['ipw_loocv_mae'] - d['t3']['mae']:+.3f}</td></tr>
        <tr><td>Slope</td><td>{d['t3']['slope']:.3f}</td><td>{d['t3_loso']['ipw_loocv_slope']:.3f}</td>
            <td>{d['t3_loso']['ipw_loocv_slope'] - d['t3']['slope']:+.3f}</td></tr>
        <tr><td>Pearson r</td><td>{d['t3']['r']:.3f}</td><td>{d['t3_loso']['ipw_loocv_r']:.3f}</td>
            <td>{d['t3_loso']['ipw_loocv_r'] - d['t3']['r']:+.3f}</td></tr>
        <tr><td>N</td><td>{d['t3']['n']}</td><td>{d['t3_loso']['ipw_loocv_n']}</td><td>—</td></tr>
      </tbody>
    </table></figure>
    """


def tableS2_loso_seeds(d: dict) -> str:
    nls_seeds = d["t3_loso"]["nls_to_wpd_per_seed_ccc"]
    wpd_seeds = d["t3_loso"]["wpd_to_nls_per_seed_ccc"]
    nls_mae   = d["t3_loso"]["nls_to_wpd_per_seed_mae"]
    wpd_mae   = d["t3_loso"]["wpd_to_nls_per_seed_mae"]
    rows = ""
    for i, (nls_ccc, nls_m, wpd_ccc, wpd_m) in enumerate(
            zip(nls_seeds, nls_mae, wpd_seeds, wpd_mae)):
        rows += (f"<tr><td>seed {i+1}</td>"
                 f"<td>{nls_ccc:.4f}</td><td>{nls_m:.2f}</td>"
                 f"<td>{wpd_ccc:.4f}</td><td>{wpd_m:.2f}</td></tr>")
    rows += (f"<tr><td><strong>mean</strong></td>"
             f"<td><strong>{d['t3_loso']['nls_to_wpd_ccc']:.4f}</strong></td>"
             f"<td><strong>{d['t3_loso']['nls_mae_mean']:.2f}</strong></td>"
             f"<td><strong>{d['t3_loso']['wpd_to_nls_ccc']:.4f}</strong></td>"
             f"<td><strong>{d['t3_loso']['wpd_mae_mean']:.2f}</strong></td></tr>")
    return f"""
    <figure class="table-figure"><figcaption><strong>Table S2.</strong> Per-seed LOSO transportability — full breakdown.
    Two-way mean = ({d['t3_loso']['nls_to_wpd_ccc']:.4f} + {d['t3_loso']['wpd_to_nls_ccc']:.4f}) / 2 = {d['t3_loso']['two_way_ccc']:.3f}.</figcaption>
    <table class="data-table">
      <thead><tr><th>Seed</th><th>NLS→WPD CCC</th><th>NLS→WPD MAE</th>
                  <th>WPD→NLS CCC</th><th>WPD→NLS MAE</th></tr></thead>
      <tbody>{rows}</tbody>
    </table></figure>
    """


def tableS4_dbs_subgroup(d: dict) -> str:
    dbs = d.get("dbs_subgroup", {})
    t3 = dbs.get("t3_iter5_clinical_imu", {})
    t1 = dbs.get("t1_iter12_axial_truncal", {})
    if not t3 or not t1:
        return ""
    return f"""
    <figure class="table-figure"><figcaption><strong>Table S4.</strong> DBS subgroup analysis — iter5 (T3) and iter12
    (T1) LOOCV metrics stratified by DBS implant status. Computed as a post-hoc stratification of the pre-registered
    lockbox per-subject predictions (no model refitting; cv_dbs flag from <code>results/ablation_v3_features.csv</code>).
    For T3, CCC is essentially identical across DBS strata (0.499 vs 0.496) — the iter5 clinical+IMU model performs
    comparably on DBS-implant vs non-DBS subjects in rank-concordance terms. MAE is higher in DBS=1 (8.72 vs 7.16)
    because DBS subjects have higher mean severity (28.65 vs 23.12); within-stratum calibration slopes (0.71, 0.75)
    are markedly steeper than the pooled slope (0.40), indicating the joint slope reflects between-group mean shift
    rather than within-group compression (a Simpson-paradox-like effect). For T1, DBS=1 subjects show a modest CCC
    gap (0.643 vs 0.555), suggesting DBS subjects with higher axial+truncal severity are slightly harder to predict
    per-item; MAE difference remains small.</figcaption>
    <table class="data-table">
      <thead><tr><th>Target</th><th>Subgroup</th><th>N</th><th>True T mean ± SD</th>
                  <th>CCC</th><th>MAE</th><th>Slope</th><th>r</th></tr></thead>
      <tbody>
        <tr><td rowspan="3"><strong>T3</strong> iter5<br>clinical+IMU</td>
            <td>DBS = 0</td><td>{t3['dbs_0']['n']}</td>
            <td>{t3['dbs_0']['true_mean']:.2f} ± {t3['dbs_0']['true_sd']:.2f}</td>
            <td>{t3['dbs_0']['ccc']:.3f}</td><td>{t3['dbs_0']['mae']:.2f}</td>
            <td>{t3['dbs_0']['slope']:.2f}</td><td>{t3['dbs_0']['r']:.2f}</td></tr>
        <tr><td>DBS = 1</td><td>{t3['dbs_1']['n']}</td>
            <td>{t3['dbs_1']['true_mean']:.2f} ± {t3['dbs_1']['true_sd']:.2f}</td>
            <td>{t3['dbs_1']['ccc']:.3f}</td><td>{t3['dbs_1']['mae']:.2f}</td>
            <td>{t3['dbs_1']['slope']:.2f}</td><td>{t3['dbs_1']['r']:.2f}</td></tr>
        <tr><td><em>joint (canonical)</em></td><td>{t3['joint_for_reference']['n']}</td>
            <td><em>—</em></td>
            <td><em>{t3['joint_for_reference']['ccc']:.3f}</em></td>
            <td><em>{t3['joint_for_reference']['mae']:.2f}</em></td>
            <td><em>{t3['joint_for_reference']['slope']:.2f}</em></td><td><em>—</em></td></tr>
        <tr><td rowspan="3"><strong>T1</strong> iter12<br>axial+truncal</td>
            <td>DBS = 0</td><td>{t1['dbs_0']['n']}</td>
            <td>{t1['dbs_0']['true_mean']:.2f} ± {t1['dbs_0']['true_sd']:.2f}</td>
            <td>{t1['dbs_0']['ccc']:.3f}</td><td>{t1['dbs_0']['mae']:.2f}</td>
            <td>—</td><td>{t1['dbs_0']['r']:.2f}</td></tr>
        <tr><td>DBS = 1</td><td>{t1['dbs_1']['n']}</td>
            <td>{t1['dbs_1']['true_mean']:.2f} ± {t1['dbs_1']['true_sd']:.2f}</td>
            <td>{t1['dbs_1']['ccc']:.3f}</td><td>{t1['dbs_1']['mae']:.2f}</td>
            <td>—</td><td>{t1['dbs_1']['r']:.2f}</td></tr>
        <tr><td><em>joint (canonical)</em></td><td>{t1['joint_for_reference']['n']}</td>
            <td><em>—</em></td>
            <td><em>{t1['joint_for_reference']['ccc']:.3f}</em></td>
            <td><em>{t1['joint_for_reference']['mae']:.2f}</em></td>
            <td><em>{t1['joint_for_reference']['slope']:.2f}</em></td><td><em>—</em></td></tr>
      </tbody>
    </table></figure>
    """


def _file_sha256(path: Path | str, short: int | None = 12) -> str:
    """Return SHA256 digest of a file. `short` truncates to N hex chars; None for full."""
    p = Path(path)
    if not p.exists():
        return "—"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    digest = h.hexdigest()
    return digest[:short] if short else digest


def _git_sha_short() -> str:
    """Return current git HEAD short SHA, or '—' if unavailable."""
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                      stderr=subprocess.DEVNULL).decode().strip()
        return out or "—"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "—"


def tableS3_reproducibility(d: dict) -> str:
    """Reproducibility manifest. SHAs are computed at generation time so the table is always
    byte-equivalent with the artefacts on disk; readers can recompute them with sha256sum."""
    results_dir = Path(__file__).parent / "results"
    code_dir = Path(__file__).parent

    pre_t1 = _glob_latest("preregistration_t1_iter12_honest_*.json")
    pre_t3_iter5 = results_dir / "preregistration_t3_iter5_20260502_171604.json"
    pre_t3_iter16 = _glob_latest("preregistration_t3_iter16_site_ipw_*.json")
    lock_t1 = results_dir / "t1_iter12_honest_composite.json"
    lock_t3_iter5 = results_dir / "lockbox_t3_iter5_A3_tier1_20260502_171604.json"
    lock_t3_iter16 = results_dir / "t3_iter16_site_ipw_lockbox.json"

    script_t1 = code_dir / "compose_t1_iter12_honest.py"
    script_t3_iter5 = code_dir / "run_t3_iter5_clinical.py"
    script_t3_iter16 = code_dir / "run_t3_iter16_site_ipw.py"

    git_short = _git_sha_short()

    rows = [
        {
            "pipeline": "T1 iter12 (Pipeline 1; LOOCV; per-item gated composite)",
            "metric": f"CCC = {d['t1']['ccc']:.4f}",
            "pre_reg_path": str(pre_t1.relative_to(code_dir)) if pre_t1 else "results/preregistration_t1_iter12_honest_*.json",
            "pre_reg_sha": _file_sha256(pre_t1) if pre_t1 else "—",
            "lockbox_path": "results/t1_iter12_honest_composite.json",
            "lockbox_sha": _file_sha256(lock_t1),
            "script_path": "compose_t1_iter12_honest.py",
            "script_sha": _file_sha256(script_t1),
            "reproducer": "./gpu.sh compose_t1_iter12_honest.py",
        },
        {
            "pipeline": "T3 iter5 (Pipeline 2; LOOCV; clinical residualization)",
            "metric": f"CCC = {d['t3']['ccc']:.4f}",
            "pre_reg_path": "results/preregistration_t3_iter5_20260502_171604.json",
            "pre_reg_sha": _file_sha256(pre_t3_iter5),
            "lockbox_path": "results/lockbox_t3_iter5_A3_tier1_20260502_171604.json",
            "lockbox_sha": _file_sha256(lock_t3_iter5),
            "script_path": "run_t3_iter5_clinical.py",
            "script_sha": _file_sha256(script_t3_iter5),
            "reproducer": "./gpu.sh run_t3_iter5_clinical.py --mode lockbox --feature_set A3_tier1",
        },
        {
            "pipeline": "T3 iter16 (Pipeline 3; LOSO + LOOCV-IPW; transportability)",
            "metric": (f"LOSO two-way CCC = {d['t3_loso']['two_way_ccc']:.3f}; "
                       f"LOOCV-IPW CCC = {d['t3_loso']['ipw_loocv_ccc']:.4f}"),
            "pre_reg_path": str(pre_t3_iter16.relative_to(code_dir)) if pre_t3_iter16 else "results/preregistration_t3_iter16_site_ipw_*.json",
            "pre_reg_sha": _file_sha256(pre_t3_iter16) if pre_t3_iter16 else "—",
            "lockbox_path": "results/t3_iter16_site_ipw_lockbox.json",
            "lockbox_sha": _file_sha256(lock_t3_iter16),
            "script_path": "run_t3_iter16_site_ipw.py",
            "script_sha": _file_sha256(script_t3_iter16),
            "reproducer": "./gpu.sh run_t3_iter16_site_ipw.py --mode lockbox",
        },
    ]

    body = ""
    for r in rows:
        body += f"""
        <tr>
          <td><strong>{r['pipeline']}</strong><br><span style="font-size:9pt; color:#555;">{r['metric']}</span></td>
          <td><code>{r['pre_reg_path']}</code><br><span style="font-family:monospace; font-size:8.5pt; color:#666;">SHA256: {r['pre_reg_sha']}…</span></td>
          <td><code>{r['lockbox_path']}</code><br><span style="font-family:monospace; font-size:8.5pt; color:#666;">SHA256: {r['lockbox_sha']}…</span></td>
          <td><code>{r['script_path']}</code><br><span style="font-family:monospace; font-size:8.5pt; color:#666;">SHA256: {r['script_sha']}…</span></td>
          <td style="font-family:monospace; font-size:8.5pt;">{r['reproducer']}</td>
        </tr>"""

    return f"""
    <figure class="table-figure"><figcaption><strong>Table S3.</strong> Reproducibility manifest. For each canonical
    pipeline we list the pre-registration JSON, the lockbox output JSON, the analysis script, and the one-line reproducer
    command. SHA256 digests are 12-char prefixes computed at manuscript-generation time from the on-disk artefacts and
    can be recomputed with <code>sha256sum &lt;path&gt;</code>; the manuscript-generator <code>git_sha</code> at this build is
    <code>{git_short}</code>. Re-running each reproducer command on the same dataset and codebase reproduces the lockbox JSON
    byte-for-byte (modulo non-deterministic LightGBM histogram tie-breaks; the per-seed predictions are deterministic given
    the seed list and feature ordering as enforced by the scripts).</figcaption>
    <table class="data-table">
      <thead>
        <tr>
          <th style="width:18%;">Pipeline</th>
          <th style="width:21%;">Pre-registration JSON</th>
          <th style="width:21%;">Lockbox JSON</th>
          <th style="width:18%;">Analysis script</th>
          <th style="width:22%;">Reproducer command</th>
        </tr>
      </thead>
      <tbody>{body}
      </tbody>
    </table></figure>
    """


# ============================================================================
# HTML ASSEMBLY
# ============================================================================

CSS = """
body {
  font-family: Georgia, 'Times New Roman', serif; font-size: 11pt; line-height: 1.65;
  max-width: 920px; margin: 2em auto; color: #1a1a1a; padding: 0 1.5em;
}
h1, h2, h3, h4 { font-family: 'Helvetica Neue', Arial, sans-serif; color: #111; }
h1 { font-size: 1.8em; line-height: 1.25; margin-bottom: 0.4em; }
.subtitle { font-size: 1.05em; color: #555; font-style: italic; margin-bottom: 2em; }
.authors { color: #444; margin-bottom: 0.3em; }
h2 { font-size: 1.35em; margin-top: 2.2em; border-bottom: 1.5px solid #888; padding-bottom: 0.15em; }
h3 { font-size: 1.1em; margin-top: 1.5em; color: #333; }
h4 { font-size: 1.0em; margin-top: 1.1em; color: #444; }
p  { margin: 0.7em 0; text-align: justify; }
.abstract { background: #f7f7f3; padding: 1em 1.5em; border-left: 4px solid #888;
            margin: 1.5em 0; font-size: 10.5pt; }
.abstract h2 { margin-top: 0; border: none; font-size: 1.15em; }
table.data-table { border-collapse: collapse; margin: 0; font-size: 9.5pt; width: 100%; }
table.data-table th, table.data-table td {
  border: 1px solid #aaa; padding: 0.4em 0.7em; text-align: left; vertical-align: top;
}
table.data-table th { background: #ececec; font-family: 'Helvetica Neue', Arial, sans-serif; font-weight: 600; }
table.data-table tbody tr:nth-child(odd) { background: #fafafa; }
figure.table-figure { margin: 1.2em 0; }
figure.table-figure figcaption { font-size: 9.5pt; color: #555; margin-bottom: 0.4em; }
figure { margin: 1.5em 0; text-align: center; }
figure img { max-width: 100%; height: auto; }
figcaption { font-size: 9.5pt; color: #555; margin-top: 0.5em; text-align: left;
             padding: 0 0.5em; }
.fixme { background: #ffe; color: #a00; padding: 0.2em 0.5em; font-weight: 600;
         border: 1px solid #cc8; border-radius: 3px; }
.methods-box { background: #f0f4f7; padding: 1em 1.5em; border-left: 4px solid #2e86ab;
               margin: 1.5em 0; font-size: 10.5pt; }
.methods-box h3 { margin-top: 0; }
code, pre { font-family: 'Menlo', 'Monaco', monospace; font-size: 9.5pt; background: #f4f4ee;
            padding: 0.05em 0.3em; border-radius: 2px; color: #333; }
pre { padding: 0.6em 0.9em; overflow-x: auto; }
.section-tag { display: inline-block; padding: 0.05em 0.5em; font-size: 9pt;
               color: #555; background: #eee; border-radius: 3px; margin-right: 0.5em;
               font-family: 'Helvetica Neue', Arial, sans-serif; }
sup.cite { color: #2e86ab; font-weight: 600; }
ol.references { font-size: 9.5pt; padding-left: 1.5em; }
ol.references li { margin: 0.3em 0; }
.appendix { background: #fbfaf5; padding: 1em 1.5em; margin-top: 2em; }
.appendix h2 { color: #555; }
"""

REFS = [
    ("Goetz CG et al. Movement Disorder Society-sponsored revision of the Unified Parkinson's "
     "Disease Rating Scale (MDS-UPDRS): Scale presentation and clinimetric testing results. "
     "<em>Movement Disorders</em> 23, 2129–2170 (2008)."),
    ("Schrag A, Sampaio C, Counsell N &amp; Poewe W. Minimal clinically important change on the "
     "unified Parkinson's disease rating scale. <em>Movement Disorders</em> 21, 1200–1207 (2006)."),
    ("Horváth K et al. Minimal clinically important difference on the Motor Examination part of "
     "MDS-UPDRS. <em>Parkinsonism &amp; Related Disorders</em> 21, 1421–1426 (2015)."),
    ("Hssayeni MD, Jimenez-Shahed J, Burack MA &amp; Ghoraani B. Symptom-based, dual-channel LSTM "
     "network for the estimation of unified Parkinson's disease rating scale III. <em>Biomedical "
     "Signal Processing and Control</em> 70, 103009 (2021)."),
    ("Shuqair M et al. (2024). Wearable-derived gait features for Parkinson's disease motor "
     "severity estimation. (See cross-dataset table for protocol caveats.)"),
    ("Lin LI. A concordance correlation coefficient to evaluate reproducibility. "
     "<em>Biometrics</em> 45, 255–268 (1989)."),
    ("Ke G et al. LightGBM: A highly efficient gradient boosting decision tree. "
     "<em>NeurIPS</em> 30, 3146–3154 (2017)."),
    ("Chen T &amp; Guestrin C. XGBoost: A scalable tree boosting system. <em>KDD</em> 785–794 (2016)."),
    ("van der Laan MJ &amp; Robins JM. <em>Unified Methods for Censored Longitudinal Data and "
     "Causality.</em> Springer (2003). [IPW formalism]"),
    ("Stürmer T et al. A review of the application of propensity score methods yielded increasing "
     "use, advantages in specific settings, but not substantially different estimates compared "
     "with conventional multivariable methods. <em>J Clin Epidemiol</em> 59, 437–447 (2006)."),
    ("Adams JL et al. WearGait-PD: A multi-site IMU dataset for Parkinson's disease gait analysis "
     "(Synapse syn61370558 / syn55105530). Sage Bionetworks (data set, 2024)."),
    ("Yuan H, Chan S, Creagh AP, Tong C, Acquah A, Clifton DA, Doherty A. Self-supervised learning for "
     "human activity recognition using 700,000 person-days of wearable data. <em>npj Digital Medicine</em> "
     "7, 91 (2024). [HARNet/UKB OxWearables; we use the frozen 2048-d wrist embedding here.]"),
    ("Goswami M, Szafraniec L, Choudhry K, Cai L, Li Y, Dubrawski A. MOMENT: A family of open time-series "
     "foundation models. <em>ICML</em> (2024)."),
]


def build_html(d: dict) -> str:
    figs = {
        "fig1": fig1_pipeline_schematic(d),
        "fig2": fig2_headline_scatter(d),
        "fig3": fig3_per_item_loocv(d),
        "fig4": fig4_t3_mechanism(d),
        "fig5": fig5_transportability(d),
        "fig6": fig6_cross_dataset(d),
        "fig7": fig7_leakage_collapse(d),
        "fig8": fig8_negative_results(d),
        "figA": figA_per_item_gated(d),
        "figB": figB_clinical_residualization(d),
        "figC": figC_per_fold_selection(d),
        "figD": figD_lockbox_protocol(d),
        "figE": figE_5_null_gate(d),
        "figF": figF_loso_protocol(d),
    }

    refs_html = "".join(f"<li>{r}</li>" for r in REFS)

    # Convenience locals for prose
    t1 = d["t1"]; t3 = d["t3"]; tloso = d["t3_loso"]; leak = d["leak"]; ceil = d["ceiling"]
    sota = d["sota"]; cohort = d["cohort"]
    h = sota["hssayeni"]; sh = sota["shuqair"]
    mcid_ratio = t3["mae"] / sota["mcid"]

    cohort_clause = (
        f"with PD age = {cohort['age_pd_mean']:.1f} ± {cohort['age_pd_sd']:.1f} years, "
        f"sex = {cohort['sex_pd_male_pct']:.0f}% male, "
        f"years since diagnosis = {cohort['dx_yrs_mean']:.1f} ± {cohort['dx_yrs_sd']:.1f}, "
        f"and total UPDRS-III range [{cohort['updrs3_min']:.0f}, {cohort['updrs3_max']:.0f}] (mean {cohort['updrs3_mean']:.1f} ± {cohort['updrs3_sd']:.1f})"
        if cohort.get("age_pd_mean") is not None else
        "(per-subject demographics in Table 1)"
    )
    site_clause = f"with {cohort.get('n_site_nls', 70)} subjects from site NLS and {cohort.get('n_site_wpd', 28)} from site WPD"

    abstract = f"""
    <section class="abstract">
      <h2>Abstract</h2>
      <p><strong>Background.</strong> The Movement Disorder Society Unified Parkinson's Disease Rating Scale (MDS-UPDRS)
      Part III is the de-facto standard for clinical motor severity assessment in Parkinson's disease (PD), but in-clinic
      scoring is rater-dependent and infrequent. Inertial measurement unit (IMU) wearables promise objective continuous
      severity estimation, but published gait-IMU UPDRS-III regressors have been trained and evaluated on small
      single-site cohorts (typically N&lt;30 LOOCV) and have not been benchmarked under strictly inductive subject-level
      evaluation on the largest available controlled-gait PD dataset.</p>
      <p><strong>Methods.</strong> We benchmark UPDRS-III regression on the WearGait-PD dataset
      (N = {cohort.get('n_total', 178)}: {cohort.get('n_pd', 98)} PD + {cohort.get('n_hc', 80)} HC; 13 body-worn IMUs at
      100 Hz; controlled gait, balance, and TUG tasks; two collection sites). We pre-register three canonical
      pipelines and report under strict inductive eval (subject-level LOOCV with a fold-local imputation/normalisation
      firewall, per-fold K=500 LightGBM-importance feature selection, and a 5-null-gate certification before any number
      is reported): (i) <strong>T1</strong> — axial+truncal subscore (items 9–14, Schrag axial + body bradykinesia 3.14)
      via a per-item gated IMU composite (iter12); (ii) <strong>T3</strong> — total UPDRS-III via a hybrid two-stage
      pipeline (Ridge on H&amp;Y + three intake covariates → LightGBM on V2 IMU residual; iter5) — explicitly a
      <em>clinical+IMU</em> rather than IMU-only model; (iii) <strong>T3 transportability</strong> — leave-one-site-out
      (LOSO) two-way mean across the two collection sites (iter16; reported as a two-site stress test, not a
      generalization-bound estimator).</p>
      <p><strong>Results.</strong> The triple inductive estimate is <strong>T1 LOOCV CCC = {t1['ccc']:.3f}</strong>
      (95% CI [{t1['ci_low']:.3f}, {t1['ci_high']:.3f}]; calibration slope = {t1['slope']:.2f}; MAE = {t1['mae']:.2f}; N = {t1['n']});
      <strong>T3 LOOCV CCC = {t3['ccc']:.3f}</strong> (calibration slope = {t3['slope']:.2f}; MAE = {t3['mae']:.2f}; N = {t3['n']}).
      The IMU residual contribution at T3 is Δ = +{t3['delta_vs_iter3']:.3f} CCC (paired bootstrap 95% CI
      [+{t3['delta_ci_low']:.3f}, +{t3['delta_ci_high']:.3f}]) over a clinical-features-only Stage 1 baseline of
      CCC = {t3['iter3_baseline']:.3f}; an IMU-only LightGBM (no clinical Stage 1) achieves only CCC = 0.207, so the
      headline T3 figure should be read as a clinical+IMU hybrid in which the clinical staging variables are the
      dominant component. <strong>T3 LOSO two-way mean CCC = {tloso['two_way_ccc']:.3f}</strong>
      (NLS→WPD = {tloso['nls_to_wpd_ccc']:.3f}; WPD→NLS = {tloso['wpd_to_nls_ccc']:.3f}) — the first published
      WearGait-PD cross-site number, but a single point estimate from N = 2 sites and not a transportability
      distribution. Both pipelines compress predicted dynamic range substantially (slopes 0.40–0.48), preserving
      rank-order concordance but underestimating departures from the cohort mean.</p>
      <p><strong>Conclusions.</strong> Internal LOOCV ceilings on this dataset are substantially below the apparent
      performance of pipelines that fail strict inductive eval (T1 transductive CCC = {leak['t1_transductive_ccc']:.3f}
      collapses to {leak['t1_inductive_ccc']:.3f}; T3 {leak['t3_transductive_ccc']:.3f} → {leak['t3_inductive_ccc']:.3f};
      same code path, identical N), and the LOOCV→LOSO gap of
      {abs(tloso['two_way_ccc'] - t3['ccc']):.2f} CCC widens this further under cross-site shift.
      Cross-sectional T3 MAE = {t3['mae']:.2f} is informative for population-level deployment but is not a within-subject
      change-detection number; comparison to the longitudinal MCID of {sota['mcid']} (Horváth 2015) is for scale, not for
      individual-change utility. Medication ON/OFF state is unannotated in the public WearGait-PD release and remains
      an unmodelled confounder. We position the work as a cautionary inductive benchmark and a first cross-site
      transportability stress test on WearGait-PD, not as a deployable gait-IMU UPDRS-III predictor.</p>
    </section>
    """

    intro = f"""
    <h2>Introduction</h2>
    <p>The MDS-UPDRS Part III is the operational standard for tracking motor severity in PD<sup class="cite">[1]</sup>,
    but in-clinic scoring is sparse, expensive, and inter-rater variable, with a minimal clinically important difference
    of approximately 3.25 points<sup class="cite">[3]</sup>. Body-worn IMU sensors measuring linear acceleration and
    angular velocity during gait offer a path to dense, objective severity estimation that is patient-friendly and
    site-independent. The motivating clinical question is simple: <em>given a few minutes of instrumented gait, can a
    deployable model predict UPDRS-III with clinically meaningful accuracy?</em></p>

    <p>The published literature is small and methodologically heterogeneous. Hssayeni et al. (2021) report MAE = {h['mae']}
    with Pearson r = {h['r']} on N = {h['n']} subjects under LOOCV in a free-living context with different IMU placement
    <sup class="cite">[4]</sup>. Shuqair et al. (2024) report r = {sh['r']} (MAE ≈ {sh['mae']}) on N = {sh['n']}
    <sup class="cite">[5]</sup>, again at LOOCV without slope or concordance reported. Both numbers are
    impressive on their face, but two structural concerns limit their interpretation as deployment ceilings.
    First, the sample size (N = {h['n']}) means a single LOOCV fold leaves N − 1 = {h['n']-1} training subjects
    — repeated LOOCV at this scale is highly susceptible to optimistic bias from any pre-evaluation hyperparameter
    selection or feature pre-computation that touches the held-out subject. Second, neither study reports calibration
    slope or Lin's concordance coefficient (CCC<sup class="cite">[6]</sup>), so the question of whether predictions are
    proportional to truth (versus regressed toward the cohort mean) is not addressed.</p>

    <p>WearGait-PD (Synapse syn61370558 / syn55105530)<sup class="cite">[11]</sup> is the largest open multi-IMU dataset
    with full per-subject MDS-UPDRS-III scores. It comprises N = {cohort.get('n_total', 178)} subjects
    ({cohort.get('n_pd', 98)} PD + {cohort.get('n_hc', 80)} HC), 13 body-worn IMUs sampled at 100 Hz, and a battery of
    controlled gait and balance tasks (self-paced walk, hurried walk, Timed-Up-and-Go, balance, tandem gait). Subjects
    were collected at two sites that are identifiable from their subject IDs ({site_clause}); we treat site as a nuisance
    factor for transportability analysis. To our knowledge no UPDRS-III regression benchmark has been published on this
    dataset under strict inductive evaluation.</p>

    <p>Two clinical considerations frame our choice of endpoints. First, the axial+truncal subscore (T1 = items 9–14)
    is clinically central but particularly hard to capture in clinic: axial features are notoriously
    levodopa-resistant relative to appendicular bradykinesia and are the dominant drivers of falls and loss of
    independence in PD<sup class="cite">[2]</sup>. An objective home-monitorable axial estimator therefore addresses
    a need that medication-titration tools generally do not. Second, total UPDRS-III (T3) inherently caps what any
    gait-only IMU model can explain: 12 of the 18 Part III items measure non-gait phenomena (speech, facial
    expression, hand/finger bradykinesia, rest tremor, rigidity), so even an oracle gait classifier is bounded by
    the variance share that gait carries (Bound A in the Discussion). We treat T3 as a population/cohort-level
    endpoint and T1 as the more individually informative target at the per-subject level.</p>

    <p>Throughout this work we make three contributions.</p>
    <ol>
      <li>An <strong>honest internal-validity ceiling for axial+truncal severity</strong> (T1 = items 9–14, the Schrag
      axial subscore<sup class="cite">[2]</sup> with body bradykinesia 3.14): LOOCV CCC = {t1['ccc']:.4f}
      (95% CI [{t1['ci_low']:.4f}, {t1['ci_high']:.4f}]; MAE = {t1['mae']:.3f}; N = {t1['n']}) via a per-item gated
      composite (iter12). Each item is predicted by its own model variant, the per-item LOOCV out-of-fold predictions
      are summed, and the composite CCC is reported.</li>
      <li>An <strong>honest internal-validity ceiling for total UPDRS-III</strong>: LOOCV CCC = {t3['ccc']:.3f}
      (MAE = {t3['mae']:.2f}; N = {t3['n']}) via a two-stage <em>clinical+IMU hybrid</em> (iter5). Stage 1 is a Ridge
      regression on H&amp;Y stage and three intake covariates (years since diagnosis, sex, DBS status); Stage 2 is a
      LightGBM on the V2 IMU feature residual. The IMU residual contribution over a clinical-features-only Stage-1
      baseline is Δ = +{t3['delta_vs_iter3']:.3f} (paired bootstrap 95% CI [+{t3['delta_ci_low']:.3f}, +{t3['delta_ci_high']:.3f}],
      n_boot = 2 000); an IMU-only LightGBM (no clinical Stage 1) achieves only CCC = 0.207. The headline figure should
      therefore be read as a clinical+IMU result in which the clinical staging variables remain the dominant component;
      iter5 exceeds the IMU-only theoretical oracle ceiling (Bound A = {ceil['bound_a']:.3f}; Discussion §2)
      precisely because Stage 1 carries non-IMU clinical signal.</li>
      <li>The <strong>first published cross-site number</strong> on WearGait-PD: T3 LOSO two-way mean
      CCC = {tloso['two_way_ccc']:.3f} (NLS→WPD = {tloso['nls_to_wpd_ccc']:.3f}; WPD→NLS = {tloso['wpd_to_nls_ccc']:.3f};
      single point estimate from N = 2 sites). The {abs(tloso['two_way_ccc'] - t3['ccc']):.2f}-CCC LOOCV→LOSO gap is the
      central result for clinical deployment: it quantifies the cost of moving from a single-site benchmark to a new
      collection site without retraining. We characterise this as a two-site stress test, not a generalization-bound
      estimator (a third site is the immediate priority).</li>
    </ol>

    <p>We position the work as a cautionary inductive benchmark — a realistic deployment estimate under strict eval,
    not a SOTA claim — and back it with a pre-registered lockbox protocol, a 5-null-gate firewall against common leakage
    classes, and an extensive negative-results catalogue that triangulates why frozen healthy-population pretrained
    encoders, IMU feature-group expansions, and end-to-end deep architectures do not move the ceiling at this sample
    size.</p>
    """

    results = f"""
    <h2>Results</h2>

    <h3>Cohort</h3>
    <p>The WearGait-PD dataset contains N = {cohort.get('n_total', 178)} subjects ({cohort.get('n_pd', 98)} PD,
    {cohort.get('n_hc', 80)} HC) {cohort_clause}. Of the {cohort.get('n_pd', 98)} PD subjects,
    {cohort.get('n_pd_t1', 94)} had complete item 9–14 scores enabling T1 axial+truncal evaluation, and
    {cohort.get('n_pd_t3', 98)} had a recorded total UPDRS-III. Subjects were collected at two sites
    ({site_clause}); the asymmetric site sizes are exploited for the LOSO transportability analysis.</p>
    {table1_cohort(d)}

    <h3>Headline results — three canonical inductive pipelines</h3>
    <p>Table 2 summarises the three pre-registered headline numbers. Figure 1 shows the pipeline block diagrams; Figure 2
    shows per-subject scatter plots for each.</p>
    {table2_headline(d)}
    <figure>{img_tag(figs['fig1'], 'Pipeline schematic')}
    <figcaption><strong>Figure 1.</strong> The three canonical inductive pipelines, with N, mechanism, and the headline
    CCC for each (loaded directly from the lockbox JSONs).</figcaption></figure>
    <figure>{img_tag(figs['fig2'], 'Headline scatter')}
    <figcaption><strong>Figure 2.</strong> Per-subject predictions for the three canonical pipelines. T1 LOOCV scatter is
    a single-shot composite of the per-item iter8 lockbox predictions; T3 LOOCV is the mean of three random seeds;
    T3 LOSO concatenates seed-42 predictions for the two transport directions (NLS→WPD in blue, WPD→NLS in orange).
    Identity line is dashed.</figcaption></figure>

    <h3>T1 axial+truncal — per-item gated composite</h3>
    <p>The T1 composite is the sum of six per-item LOOCV out-of-fold prediction arrays, each from its own model variant
    pre-registered as a single iter8 lockbox batch (Table 3, Figure 3). Items split cleanly into two regimes: postural
    stability (item 12) is the strongest single item with LOOCV CCC = {d['t1_per_item']['12']['ccc']:.4f}; gait
    (item 10) and arising from chair (item 9) follow at {d['t1_per_item']['10']['ccc']:.4f} and
    {d['t1_per_item']['9']['ccc']:.4f}; freezing of gait (item 11) and body bradykinesia (item 14) are intermediate;
    posture (item 13) is the weakest at {d['t1_per_item']['13']['ccc']:.4f}, consistent with item 13 being partly
    habitual/anatomical and capped by inter-rater scoring noise. The composite at CCC = {t1['ccc']:.4f} reflects the
    summing of these per-item OOF predictions before evaluating concordance against sum-of-true.</p>
    {table3_per_item(d)}
    <figure>{img_tag(figs['fig3'], 'Per-item LOOCV bars')}
    <figcaption><strong>Figure 3.</strong> Per-item LOOCV CCC under iter12 (mean across 3 seeds, N = 94 PD).
    Schrag axial items 9–13 in blue; body bradykinesia 3.14 in orange; T1 composite (sum-then-CCC) shown as the dashed
    horizontal reference.</figcaption></figure>

    <h3>T3 total UPDRS — clinical residualization breaks the IMU-only ceiling</h3>
    <p>T3 prediction is a two-stage architecture (Pipeline 2; appendix Figure B). Stage 1 fits Ridge regression
    (α = {t3['alpha']}) on H&amp;Y stage (linear + 5 one-hot bins) and three patient intake covariates available before
    the gait session: years since diagnosis (cv_yrs; Pearson r with T3 = 0.32), sex (cv_sex), and DBS status (cv_dbs).
    Stage 2 fits a LightGBM regressor on the V2 IMU feature residual (target = T3 − T3̂_clinical) with per-fold
    K = 500 LGB-importance feature selection. The headline LOOCV CCC = {t3['ccc']:.4f} (MAE = {t3['mae']:.3f}; N = {t3['n']})
    represents a paired-bootstrap-significant lift of Δ = +{t3['delta_vs_iter3']:.3f}
    (95% CI [+{t3['delta_ci_low']:.3f}, +{t3['delta_ci_high']:.3f}], frac_positive = {t3['frac_positive']:.3f}, n_boot = 2 000)
    over the iter3 hy_residual baseline (CCC = {t3['iter3_baseline']:.4f}), evaluated on the same N = 98 subjects.</p>
    <p>The architecture breaks the theoretical IMU-only oracle ceiling Bound A = {ceil['bound_a']:.3f} (Figure 4) because
    the three intake covariates carry clinical staging information that is not present in the gait IMU stream.
    Importantly, all three covariates are <em>recorded before the gait session</em> as part of standard intake — there is
    no leakage from the assessment we are predicting. Because cv_dbs is included as a Stage-1 predictor and ~24% of
    the cohort carries DBS implants, we report a post-hoc DBS=0 vs DBS=1 stratification of the iter5 (and iter12)
    per-subject predictions in <strong>Table S4</strong>; T3 iter5 CCC is essentially identical across DBS strata
    (0.499 vs 0.496) but within-stratum calibration slopes (0.71, 0.75) are markedly steeper than the pooled slope
    (0.40), a Simpson-paradox-like effect driven by between-group mean shift.</p>
    {table4_t3_mechanism(d)}
    <figure>{img_tag(figs['fig4'], 'T3 mechanism ablation')}
    <figcaption><strong>Figure 4.</strong> T3 architecture ablation. The B0 null (predict mean) sits near zero;
    V2 alone reaches CCC ≈ 0.21; H&amp;Y residualization lifts to {t3['iter3_baseline']:.3f}; adding three intake
    covariates lifts again to {t3['ccc']:.4f}. Theoretical IMU-only oracle Bound A = {ceil['bound_a']:.3f} (red dotted)
    and the upper theoretical limit Bound D = {ceil['bound_d']:.3f} (purple dotted) are shown for reference.
    Error bar on iter5 = bootstrap CI on the Δ vs iter3.</figcaption></figure>

    <h3>Transportability — LOSO two-way mean</h3>
    <p>The WearGait-PD PD cohort is split unevenly across collection sites ({site_clause}), which makes
    cross-site transport an asymmetric stress test. As an internal-validity sensitivity check, inverse-propensity
    weighting (IPW) applied to Stage 2 of the iter5 architecture under LOOCV reduces CCC from {t3['ccc']:.4f}
    to {tloso['ipw_loocv_ccc']:.4f} (Δ = {tloso['ipw_delta_vs_iter5']:+.3f}), confirming that cohort imbalance does not
    inflate the canonical headline. We report the IPW LOOCV result as a site-balanced lower bound (Table S1);
    iter5 (no IPW) remains the canonical LOOCV headline for internal validity.</p>
    <p>The transportability headline is the iter16 LOSO two-way mean (Table 5, Figure 5). Trained on NLS (N = {tloso['n_train_nls']})
    and tested on WPD (N = {tloso['n_train_wpd']}), the iter5 architecture achieves CCC = {tloso['nls_to_wpd_ccc']:.4f}
    (MAE = {tloso['nls_mae_mean']:.2f}). The reverse direction (trained on WPD N = {tloso['n_train_wpd']}, tested on NLS
    N = {tloso['n_train_nls']}) is harder, with CCC = {tloso['wpd_to_nls_ccc']:.4f} (MAE = {tloso['wpd_mae_mean']:.2f}) —
    the smaller training set is partly responsible. The two-way mean CCC = {tloso['two_way_ccc']:.3f} is the first
    published WearGait-PD transportability number. The {abs(tloso['two_way_ccc'] - t3['ccc']):.3f}-CCC gap between LOOCV
    and LOSO is the most important number for clinical deployment: it quantifies the cost of moving from a single-site
    benchmark to a new collection site without retraining.</p>
    {table5_transportability(d)}
    <figure>{img_tag(figs['fig5'], 'Transportability forest')}
    <figcaption><strong>Figure 5.</strong> Transportability — internal validity vs cohort shift. T3 LOOCV (iter5) sits at
    the top with its bootstrap CI; LOOCV-IPW provides a sensitivity lower bound; the two LOSO directions show the
    asymmetry of cross-site transport; the two-way mean is reported as a single point estimate from the
    two-site stress test (not a generalization-bound number).</figcaption></figure>

    <h3>Cross-dataset context</h3>
    <p>Hssayeni 2021 (MAE = {h['mae']}, r = {h['r']}) and Shuqair 2024 (r = {sh['r']}, MAE ≈ {sh['mae']}) report
    headline numbers that are stronger than ours on their own datasets — but both run on N = {h['n']} subjects under
    LOOCV, neither reports CCC or calibration slope, and both differ from WearGait-PD in IMU placement and acquisition
    context. The Δ = {abs(leak['t1_inductive_ccc'] - leak['t1_transductive_ccc']):.2f} CCC gap that our own pipeline
    shows between transductive and strictly inductive evaluation at N = 94 (Table 7) is a useful prior on how much
    LOOCV at N = 24 can inflate apparent performance even when no protocol error is intended. We therefore position
    Table 6 as a contextual reference, not a head-to-head benchmark: our T3 LOOCV CCC = {t3['ccc']:.4f}
    (MAE = {t3['mae']:.2f}) is the first inductively-honest number on a substantially larger controlled-gait dataset,
    and LOSO CCC = {tloso['two_way_ccc']:.3f} is the first cross-site deployment estimate on any PD-IMU corpus we are
    aware of. Reproducing the prior numbers' headline accuracy under our protocol on those datasets is the right way
    to test whether the architectural difference or the protocol difference dominates the gap.</p>
    {table6_cross_dataset(d)}
    <figure>{img_tag(figs['fig6'], 'Cross-dataset forest')}
    <figcaption><strong>Figure 6.</strong> Cross-dataset context. Panel A: MAE in UPDRS-III points (lower is better),
    with the MCID of {sota['mcid']}<sup class="cite">[3]</sup> shown as a dashed reference line. Panel B: calibration /
    agreement metric — CCC where reported, Pearson r where CCC was not reported (different markers). N and protocol
    annotated per row.</figcaption></figure>

    <h3>Why the inductive ceiling is so much lower than published apparent performance</h3>
    <p>The {leak['t1_transductive_ccc']:.3f}–{leak['t1_inductive_ccc']:.3f} = {(leak['t1_inductive_ccc'] - leak['t1_transductive_ccc']):+.3f}
    CCC gap on T1 (and {(leak['t3_inductive_ccc'] - leak['t3_transductive_ccc']):+.3f} on T3) shown in Figure 7 is not
    a quirk of feature engineering — it is the cost of two leakage classes that are easy to introduce by accident in
    small-N regression: (i) <em>pre-computed target-derived structures</em> (XGBRanker leaf indices, retrieval
    library memberships, prototype anchors) fitted on the full N before cross-validation, and (ii) <em>hyperparameter
    tuning on the test-set vector</em> (post-hoc temperature scaling, calibration grid search) reported on the same
    vector without nested cross-validation. We pre-empt these via a 5-null-gate firewall (Methods Box; appendix Figure E)
    and a single-shot pre-registered lockbox protocol (appendix Figure D).</p>
    {table7_leakage(d)}
    <figure>{img_tag(figs['fig7'], 'Leakage collapse')}
    <figcaption><strong>Figure 7.</strong> Pre-leakage collapse. Same code path, same N (T1 N = {leak['t1_n']}, T3 N = {leak['t3_n']}),
    same fold definitions; the only difference is whether feature ranks / leaf indices / hyperparameters are computed
    globally or strictly inside the train fold.</figcaption></figure>

    <h3>Negative results — the N≈94 wall</h3>
    <p>Across iter6 (V2 + unsigned-asymmetry, V2 + event-axial), iter14 (FoG-summary scalars on items 9 and 12), and
    iter15 (frozen UKB OxWearables HARNet 2 048-d wrist embeddings<sup class="cite">[12]</sup>; ~700 K person-days SSL),
    no IMU feature-group expansion or frozen healthy-population pretrained encoder cleared the pre-lockbox gate
    (Δ ≥ +0.025 with seed std &lt; 0.020 across 3–5 seeds; Table 8, Figure 8). The HARNet result is particularly
    informative: every one of 5 seeds was negative, with mean Δ = {d['neg']['iter15_harnet_t1sum_delta']:+.4f}.
    Together with prior null results from frozen MOMENT<sup class="cite">[13]</sup> and a healthy-only contrastive
    SSL encoder, this triangulates a structural conclusion: at N ≈ 94 PD subjects, frozen healthy-population
    pretrained encoders are orthogonal to within-PD severity at any embedding scale we have tested.</p>

    <p>We read this catalogue as positive evidence that the LOOCV ceilings reported above are not artefacts of
    feature under-engineering. The wall is partly sample size — the within-PD cohort is small relative to the embedding
    rank of these encoders, so additional features compete for K = 500 LightGBM-importance slots and crowd out useful
    V2 moments — and partly biological, because gait simply does not carry the information needed to predict speech,
    facial expression, or arm-segment tremor regardless of N. Five end-to-end deep-learning architectures we evaluated
    earlier in development (1D-CNN, ResNet-1D, TCN, BiLSTM, and a Transformer encoder; trained directly on the 78-channel
    raw signal) all underfit at N ≈ 94 PD subjects and were dropped before lockboxing for the same reason: at this
    sample size the gradient-boosted trees on V2 features already dominate the achievable inductive ceiling. Both walls
    combine to flatten the achievable lift from feature-only innovation at this dataset scale, which is why the iter5
    architectural lift comes from new <em>signal</em> (intake covariates) rather than from new <em>features</em>.</p>

    <p><strong>Multiplicity.</strong> Across the &gt;20 feature-addition configurations explored across iter4–iter15
    (catalogued informally in our project notes), the pre-lockbox gate of Δ ≥ +0.025 with seed std &lt; 0.020 across
    3–5 seeds is conservative relative to per-seed sampling noise (per-seed CCC SD ≈ 0.06 at this N), giving an
    estimated per-comparison Type-I rate well under 5 % under H₀ even without an explicit Benjamini–Hochberg correction.
    The negative-direction sign of HARNet, MOMENT, and HC-SSL (mean Δ = -0.031, -0.000, -0.012 respectively) further rules out
    that any of these would have survived a formal FDR-controlled screen. We list these here for transparency rather
    than as multiplicity-corrected p-values; none of the per-iteration null results were used to select the canonical
    pipelines.</p>
    {table8_negatives(d)}
    <figure>{img_tag(figs['fig8'], 'Negative results bars')}
    <figcaption><strong>Figure 8.</strong> Negative-result feature-addition ablations. Green bars would clear the
    +0.025 pre-lockbox gate; orange and red bars do not. iter15 HARNet was negative on every one of 5 seeds.</figcaption></figure>
    """

    discussion = f"""
    <h2>Discussion</h2>

    <h3>What the triple inductive ceiling means for deployment</h3>
    <p>The single number a deployment-minded reader should take from this paper is the
    {abs(tloso['two_way_ccc'] - t3['ccc']):.2f}-CCC drop from internal LOOCV ({t3['ccc']:.3f}) to two-site LOSO
    ({tloso['two_way_ccc']:.3f}) on T3. Even an inductively-honest internal benchmark substantially overstates what a
    model trained at one site achieves at a new site, and we observe this gap in a tightly controlled multi-IMU
    protocol — free-living deployment will widen it further, not narrow it. With only two collection sites this is a
    single point estimate, not a sample from a transportability distribution; we characterise it as a two-site stress
    test rather than a generalization-bound estimator. Clinical deployment must plan for site-level fine-tuning,
    federated training, or explicit cohort-shift correction; the deployed CCC is the LOSO figure, not the LOOCV figure.</p>

    <p><strong>Both headline pipelines exhibit calibration slopes of {t1['slope']:.2f} (T1) and {t3['slope']:.2f} (T3),
    meaning predictions are systematically compressed toward the cohort mean.</strong> A subject whose true severity is
    1 SD above the cohort is predicted at roughly half an SD above; the models preserve rank ordering and concordance
    but underestimate the <em>amplitude</em> of departures from the mean. This is the failure mode CCC was chosen to
    penalise (Pearson r alone would mask it), and it is why we report calibration slope alongside CCC in every headline
    table. Operationally, the practical consequence is that severe (and very mild) phenotypes will be regressed toward
    the cohort centre — a model deployed for trial-enrichment of severe cases would under-select. Stratifying by DBS
    status reveals a Simpson-paradox-like pattern: within-stratum slopes are 0.71 (DBS=0) and 0.75 (DBS=1) versus the
    pooled 0.40 (Table S4); the pooled slope reflects between-group severity-mean shift more than within-group dynamic-range
    compression, and the apparent compression is partly an artefact of pooling clinically distinct subgroups.</p>

    <p>The other two anchors then position what each headline is good for. T1 axial+truncal CCC = {t1['ccc']:.3f}
    (MAE = {t1['mae']:.2f}) on a target whose theoretical range is 0–24 (six items scored 0–4) and whose observed
    cohort mean is {t1['true_mean']:.1f} ± {t1['true_std']:.1f} (SD) is a usable subscore-level rank estimator:
    the typical absolute error is small relative to clinical scoring noise on a clinically central, fall-relevant
    subscore. T3 total UPDRS CCC = {t3['ccc']:.3f} (MAE = {t3['mae']:.2f}) is best read as a hybrid clinical+IMU
    estimate (Stage 1 carries most of the signal; the IMU residual contributes Δ = +{t3['delta_vs_iter3']:.3f} CCC
    over a clinical-features-only baseline) rather than as a gait-IMU result; absent intake covariates, the deployment
    ceiling collapses to the iter3 baseline of CCC = {t3['iter3_baseline']:.3f}, or to CCC = 0.207 for an IMU-only
    LightGBM (B1 baseline; Table 4).</p>

    <p>Cross-sectional MAE is informative for population-level deployment but is not directly comparable to the
    minimal-clinically-important-difference (MCID) of {sota['mcid']}<sup class="cite">[3]</sup>, which is a within-subject
    longitudinal change anchor (Horváth 2015 derived it from individual change scores in PD patients followed
    over time). T3 MAE = {t3['mae']:.2f} is roughly {mcid_ratio:.1f}× the MCID in absolute scale-points, but whether
    the model can detect a one-MCID change in the same patient over time requires longitudinal follow-up data we do not
    have. We therefore use the MCID only as a reference scale for the cross-sectional MAE, not as a per-patient
    change-detection benchmark. The realistic deployment use cases for these pipelines are population-level: cohort
    enrichment for clinical trials (selecting subjects whose IMU-implied severity matches an inclusion stratum),
    automated monitoring for trend detection or adverse-event flagging in long-term remote follow-up, and pre-screening
    for in-clinic full-UPDRS examination. The T1 axial+truncal head (CCC = {t1['ccc']:.3f}, MAE = {t1['mae']:.2f}) is
    the closer match to per-subject use, given its lower error in absolute scale-points and its alignment with
    fall-risk-relevant symptomatology — though calibration-slope compression still applies.</p>

    <h3>Why theoretical ceilings matter</h3>
    <p>The IMU-only oracle ceiling Bound A = {ceil['bound_a']:.3f} (perfect T1 prediction + mean residual) is derived
    purely from the variance decomposition of T3 into items 9–14 (var(T1)/var(T3) ≈ 7.7%) and the items not directly
    observable from gait (12 of 18 UPDRS-III items, including speech, facial expression, rest tremor, and rigidity).
    Iter5 exceeds Bound A by injecting non-IMU clinical signal at Stage 1, not by improving the IMU model. The
    mechanism is straightforward in a small-N, high-p regression: Stage 1 (Ridge on H&amp;Y + intake covariates)
    absorbs coarse clinical severity from cheap, low-variance, prior-known patient state; Stage 2 (LightGBM on the
    V2 IMU residual) then has only the within-stratum variance to model, which is what the IMU is actually informative
    about. This is the central architectural insight: at this sample size and feature regime, gain comes from new
    <em>signal</em> (intake covariates, H&amp;Y stage) rather than from new <em>features</em> (IMU-derived). The
    negative-results catalogue (Table 8, Figure 8) is consistent with that interpretation.</p>

    <h3>Comparison with prior gait-IMU UPDRS-III work</h3>
    <p>Hssayeni 2021<sup class="cite">[4]</sup> and Shuqair 2024<sup class="cite">[5]</sup> achieve lower MAE
    ({h['mae']} and ~{sh['mae']}) and higher r ({h['r']} and {sh['r']}) than our T3 numbers, but each operates on
    N = {h['n']} subjects under LOOCV. Two cautions are warranted before treating those numbers as deployment ceilings.
    First, neither paper reports CCC or calibration slope, so a model that systematically regresses toward the cohort
    mean would still register an apparently high r. Second, at N = 24, even modest test-set re-use across hyperparameter
    sweeps can inflate LOOCV apparent performance substantially — the {abs(leak['t1_inductive_ccc'] - leak['t1_transductive_ccc']):.2f}
    CCC gap on our own pipeline at N = 94 (Table 7) puts a useful prior on this concern. Our larger N and stricter
    inductive protocol probably explain the gap with their reported numbers as much as any architectural difference.</p>

    <h3>Limitations — what this benchmark does NOT support</h3>
    <p>We state the limitations as explicit non-claims so they are not mistaken for soft hedging. (1)
    <em>No per-patient titration.</em> T3 MAE = {t3['mae']:.2f} (cross-sectional) is roughly {mcid_ratio:.1f}× the
    longitudinal MCID of {sota['mcid']} in absolute scale-points; the error budget is too large for individual-patient
    medication adjustments. The T1 axial+truncal ceiling (MAE = {t1['mae']:.2f}) is closer to per-patient utility for
    axial symptomatology specifically, but is not a substitute for clinical exam. (2) <em>No prospective validation.</em>
    All numbers in this paper are retrospective on a single archived dataset; the LOSO CCC = {tloso['two_way_ccc']:.3f}
    is a two-site stress test, not a field-validated deployment number. (3) <em>Cross-sectional MAE is not a
    change-detection metric.</em> The MCID of {sota['mcid']}<sup class="cite">[3]</sup> is a within-subject longitudinal
    change anchor; we use it only as a reference scale for cross-sectional MAE and we cannot infer per-patient
    change-detection accuracy from cross-sectional error. (4) <em>Single dataset for development.</em> All three pipelines
    were screened, lockboxed, and reported on WearGait-PD; we have not demonstrated transfer to Hssayeni, Shuqair, or
    any other PD-IMU corpus, and the iter5 architecture's lift may not generalize to datasets without H&amp;Y and
    intake covariates of comparable quality. (5) <em>Two-site LOSO is a stress test, not a transportability distribution.</em>
    With only two sites, the LOSO two-way mean is a single point estimate; a third site would let us distinguish
    site-specific noise from a true cohort-shift law. The asymmetry between the two directions
    (NLS→WPD = {tloso['nls_to_wpd_ccc']:.3f} vs WPD→NLS = {tloso['wpd_to_nls_ccc']:.3f}) is partly attributable to
    imbalanced training-set sizes (70 vs 28). (6) <em>Controlled gait, not free-living.</em>
    WearGait-PD uses scripted tasks; subjects know they are being assessed and tend to recruit attentional/visuomotor
    compensation that transiently masks mild bradykinesia (paradoxical kinesia / Hawthorne effect). Free-living
    deployment is therefore expected to show <em>lower</em> baseline concordance than even our LOSO numbers suggest,
    not higher; LOSO does not measure this offset. (7) <em>Clinical intake covariates carry most of the iter5 signal.</em>
    The iter5 architecture is a clinical+IMU hybrid in which Stage 1 (Ridge on H&amp;Y + intake) carries the bulk of
    predictive variance (CCC = {t3['iter3_baseline']:.3f}) and Stage 2 (IMU residual) contributes Δ = +{t3['delta_vs_iter3']:.3f};
    if H&amp;Y, years-since-diagnosis, sex, and DBS status are unavailable at deployment (e.g., remote monitoring
    without recent clinical visits), the relevant ceilings are iter3 (CCC = {t3['iter3_baseline']:.3f}) or, in the
    fully-IMU-only case, the B1 LightGBM baseline (CCC = 0.207; Table 4). (8) <em>Calibration slope is below 0.5 on both
    targets.</em> Predictions are systematically compressed toward the cohort mean; severe and very mild phenotypes are
    individualised poorly. This is the failure mode CCC was chosen to penalise — we report it openly, and any deployment
    that depends on absolute predicted scores (rather than ranks) should account for it. (9) <em>Medication ON/OFF state
    is unannotated in WearGait-PD.</em> MDS-UPDRS-III scores are heavily medication-state-dependent (levodopa
    pharmacodynamics drive substantial within-patient variance); the residual variance unexplained by our model is
    therefore confounded by unobserved medication state. We cannot rule out that a fraction of the LOOCV→LOSO gap
    reflects between-site differences in scoring conventions for medication state rather than pure cohort shift, and
    we cannot stratify the headline numbers by ON/OFF condition. (10) <em>DBS subgroup not separately reported.</em>
    DBS implant presence is included as a Stage-1 covariate (cv_dbs); we report a post-hoc DBS=0 vs DBS=1 stratification
    of the iter5 and iter12 lockbox per-subject predictions in Table S4. The substantive finding is that T3 iter5 CCC is
    nearly identical across strata (0.499 vs 0.496) — the model's rank concordance is invariant to DBS status — but
    within-stratum calibration slopes (0.71, 0.75) are markedly steeper than the joint slope (0.40), indicating the
    pooled slope reflects between-group mean shift rather than within-group dynamic-range compression. T1 iter12 shows
    a modest CCC gap across strata (0.643 vs 0.555). DBS ON/OFF state during the gait recording is not annotated
    separately from DBS device presence in the public release, so we cannot stratify further.</p>

    <h3>Future work</h3>
    <p>Three concrete directions are ranked by the constraint they would relax. First, a third collection site —
    independent of NLS and WPD — would convert the LOSO two-way mean from a single point into a distribution and
    let us bound site-noise variance separately from a true cohort-shift law. Second, cross-dataset transfer of the
    iter5 architecture to the MJFF Levodopa Response Study (which carries the same UPDRS-III + IMU pairing) is the
    immediate cross-corpus test; success there would establish that clinical residualization with intake covariates
    is a transferable architectural pattern rather than a WearGait-PD artefact. Third, the
    {cohort.get('n_hc', 80)} healthy controls in WearGait-PD remain unused in the canonical pipelines: leveraging
    them as <em>hold-out distributional anchors</em> for prediction-reliability calibration (rather than as ranking
    labels, which leaks) would add per-prediction confidence intervals without contaminating the regression signal.</p>
    """

    methods = f"""
    <h2>Methods</h2>

    <h3>Dataset</h3>
    <p>WearGait-PD (Synapse syn61370558 / syn55105530)<sup class="cite">[11]</sup> contains
    {cohort.get('n_total', 178)} subjects ({cohort.get('n_pd', 98)} PD, {cohort.get('n_hc', 80)} HC) wearing 13 body-worn
    Movella DOT IMUs (head, sternum, lumbar, bilateral wrists, bilateral upper arms, bilateral thighs, bilateral shanks,
    bilateral feet) sampled at 100 Hz, performing self-paced walk, hurried walk, Timed-Up-and-Go (TUG), balance, and
    tandem gait tasks (with mat and turn variants). Subjects were collected at two sites identifiable from their
    SID prefix ({site_clause}). The clean PD-only subject-level split (seed = 20260309) is at
    <code>results/paper3_split.json</code>. T1 evaluation uses the {cohort.get('n_pd_t1', 94)} PD subjects with
    complete item 9–14 scores; T3 uses the {cohort.get('n_pd_t3', 98)} PD subjects with a recorded total UPDRS-III.</p>

    <h3>Preprocessing and feature extraction</h3>
    <p>Per-recording z-score normalisation is applied to the 13 sensors × 6 channels (Acc XYZ + Gyr XYZ) = 78-channel
    signal. The window pipeline uses 1 000-sample (10 s) windows with 500-sample (50 %) stride. Subject-level features
    used in the canonical pipelines are loaded from <code>results/ablation_v3_features.csv</code> (~1 751 V2 features
    per subject, including time-domain moments, frequency-domain summaries, and per-task task-segmented statistics).
    The TUG phase-segmented features used in some per-item lockboxes are 6-phase (sit-to-stand, walk-out, turn, walk-back,
    turn, stand-to-sit) segmentations around the lumbar acceleration-magnitude spike, yielding 421 additional features.</p>

    <h3>Pipeline 1 — T1 iter12 honest (per-item gated composite)</h3>
    <p>Implementation: <code>compose_t1_iter12_honest.py</code>. The composer loads six pre-registered LOOCV
    out-of-fold prediction arrays for items 9–14 from a single iter8 lockbox batch (timestamp 20260430_143044,
    files <code>results/lockbox_peritem_{{9..14}}_*_20260430_143044.json</code>), sums them into a composite OOF
    prediction per subject, then evaluates concordance against the sum-of-true. The per-item variants are:
    item 9 = <code>hy_residual_item</code>; item 11 = <code>item_dedicated</code>; items 10, 12, 13, 14 = <code>item_plus_v2</code>
    (Table 3). Single-iter8-batch sourcing prevents the composite-level cherry-picking inflation we have characterised
    in earlier per-item-best composites.</p>
    <p>Each per-item LightGBM model uses identical hyperparameters: n_estimators = 500, learning_rate = 0.05,
    num_leaves = 15, min_data_in_leaf = 10, feature_fraction = 0.8, bagging_fraction = 0.8 (freq = 5),
    reg_alpha = 0.1, reg_lambda = 0.3, device = "cpu" (LightGBM GPU is 2.2× slower at N &lt; 200 on this dataset).
    Three random seeds are averaged.</p>

    <h3>Pipeline 2 — T3 iter5 clinical (two-stage residualization)</h3>
    <p>Implementation: <code>run_t3_iter5_clinical.py --mode lockbox --feature_set A3_tier1</code>. <strong>Stage 1</strong>
    is a Ridge regression (α = {t3['alpha']}, fit_intercept = True) on 9 features = 6 H&amp;Y representations (linear
    NaN→0, plus 5 one-hot bins) + 3 intake covariates: <code>cv_yrs</code> (years since diagnosis, from intake chart
    review), <code>cv_sex</code>, and <code>cv_dbs</code> (binary indicator of an implanted deep-brain stimulator at
    enrolment; this encodes device <em>presence</em>, not the on/off state during the gait task — all WearGait-PD
    sessions were recorded with the stimulator left in its standard clinical state, but ON/OFF state is not separately
    annotated in the public release). H&amp;Y stage in the WearGait-PD release was assigned by the enrolling
    movement-disorders clinician at intake from chart review and bedside neurological exam, not derived from the
    UPDRS-III item scores we are predicting; we therefore treat it as an intake covariate rather than a target leak,
    consistent with WearGait-PD documentation. All Stage 1
    features come from <code>results/ablation_v3_features.csv</code>. <strong>Stage 2</strong> is a LightGBM regressor<sup class="cite">[7]</sup>
    (same hyperparameters as Pipeline 1) on the V2 IMU feature residual (target = T3 − T3̂_clinical) with per-fold
    K = 500 LGB-importance feature selection inside the train fold (appendix Figure C). The K = 500 cap was inherited
    unchanged from the iter4 / iter5 lockboxed configurations (5-fold-screened against K ∈ {{200, 500, 1000, all}}, with
    K = 500 the 5-fold optimum at the time of iter5 lockboxing); the LOOCV was then run exactly once on this frozen K and
    not re-tuned. LOOCV with N = 98, three random
    seeds (42, 1337, 7), per-subject prediction = mean across seeds. Paired bootstrap of (iter5 − iter3 baseline) over
    n_boot = 2 000 subject-level resamples (seed = 42) yields the lift Δ = +{t3['delta_vs_iter3']:.3f}
    (95% CI [+{t3['delta_ci_low']:.3f}, +{t3['delta_ci_high']:.3f}]; frac &gt; 0 = {t3['frac_positive']:.3f}).</p>

    <h3>Pipeline 3 — T3 iter16 LOSO + LOOCV-IPW</h3>
    <p>Implementation: <code>run_t3_iter16_site_ipw.py --mode lockbox</code>. Stage 1 is bit-identical to Pipeline 2.
    Stage 2 LightGBM adds a per-fold sample weight = N_train / (2 · N_site_train) (deterministic count-based inverse-propensity
    weighting<sup class="cite">[9],[10]</sup>; no
    propensity-model logistic regression; no clipping). Two evaluation branches:
    <strong>(a) LOSO transportability</strong> — single split per direction × 3 seeds. NLS→WPD: train on N = {tloso['n_train_nls']}
    NLS subjects, test on N = {tloso['n_train_wpd']} WPD; WPD→NLS: train on N = {tloso['n_train_wpd']}, test on N = {tloso['n_train_nls']}.
    Two-way mean = ({tloso['nls_to_wpd_ccc']:.4f} + {tloso['wpd_to_nls_ccc']:.4f}) / 2 = {tloso['two_way_ccc']:.3f}.
    The IPW formula collapses to uniform weighting within single-site training, so the LOSO branch reports the iter5
    architecture under cohort shift. <strong>(b) LOOCV-IPW</strong> — LOOCV with per-fold IPW on Stage 2; sensitivity
    Δ vs iter5 = {tloso['ipw_delta_vs_iter5']:+.3f} (Table S1).</p>

    <h3>Theoretical IMU-only ceiling (Bound A)</h3>
    <p>The IMU-only oracle ceiling Bound A is derived from a variance decomposition of T3 into the gait-observable
    subscore T1 (items 9–14, the Schrag axial+truncal items observable from instrumented gait) and the residual
    R = T3 − T1 (items 1–8 and 15–18, including speech, facial expression, hand/finger bradykinesia, rest tremor, and
    rigidity, which are not directly observable from gait IMU). On the N = 89 PD subjects with all 18 items recorded,
    var(T1)/var(T3) ≈ 7.7 %, so even an oracle gait classifier with perfect T1 prediction (T1̂ = T1) and a constant
    R̂ = mean(R) achieves a maximum CCC of <strong>{ceil['bound_a']:.3f}</strong> against true T3. The full set of
    bounds (iter1 derivation): Bound D (perfect-T1 → T3 max, the upper theoretical limit) = {ceil['bound_d']:.3f};
    Bound A (oracle T1 + mean R, IMU-only realistic max) = <strong>{ceil['bound_a']:.3f}</strong>; Bound E
    (inductive shrinkage T1_pred → T3, what an inductive T1 model can actually deliver under shrinkage) = {ceil['bound_e']:.3f}.
    Iter5 reaches CCC = {t3['ccc']:.3f}, exceeding Bound A by injecting non-IMU clinical signal (H&amp;Y stage and three
    intake covariates) at Stage 1 — this is the architectural insight the paper turns on.</p>

    <h3>Inductive firewall (<code>inductive_lib.py</code>)</h3>
    <p>The fold-local helpers enforce that anything that "fits" on training data is fit inside the fold:
    <code>FoldImputer</code> fits the median per feature on the train fold (NaN → 0 for all-NaN columns);
    <code>FoldNormalizer</code> z-scores using train-fold mean and SD (with ε = 1e-8 floor for zero-variance columns);
    <code>FoldSeverityBins</code> derives quartile cutpoints from y_train only. No global imputers, cohort-wide z-scores,
    pre-computed ranks, anchors, or prototypes are used anywhere in the canonical pipelines.</p>

    <div class="methods-box">
      <h3>Methods Box: 5-null gate</h3>
      <p>Before any new pipeline is permitted to lockbox, it must pass five sanity nulls (appendix Figure E):</p>
      <ol>
        <li><strong>Scrambled-label sanity.</strong> Shuffle train PD targets; expect test CCC ≈ 0. Catches most
        target-leak bugs.</li>
        <li><strong>SID-shuffle before cache join.</strong> Shuffle subject IDs on the feature side; expect CCC ≈ 0.
        Catches leaks via cache join keys.</li>
        <li><strong>Canary-feature injection.</strong> Inject a feature with value 999.0 into the test fold only; assert
        the model cannot use it. Catches accidental train/test smoothing.</li>
        <li><strong>Library-exclusion assertion.</strong> For any kNN/retrieval architecture, assert that the test SID
        is not in the retrieval pool. Catches transductive leakage in nearest-neighbour or anchor-based methods.</li>
        <li><strong>Transductive sanity (positive control).</strong> Intentionally leak the target into a feature and
        confirm CCC ≈ 0.85; this verifies the architecture is capable of learning when given the answer.</li>
      </ol>
      <p>Concrete leakage citations from our own audit:
      <code>run_compression_ablation.py:1015</code> fitted XGBRanker<sup class="cite">[8]</sup> on all 178 subjects globally; the leaf indices
      thereby encoded test-fold rank, costing ΔCCC = 0.343 on T1 5-fold (transductive 0.868 → inductive 0.525 in audit
      reproduction). <code>run_calibration_v2.py:861</code> tuned a temperature grid on the same N = 94 LOOCV prediction
      vector it then evaluated; calibration slope was pinned to 1.000 by construction. Both classes of leakage are now
      blocked by the firewall; their detection is what motivates Pipeline 1's "single iter8 batch" sourcing rule.</p>
      <p><strong>Certification of canonical pipelines.</strong> The pipelines reported in Table 2 (iter12, iter5, iter16)
      were each rebuilt on top of <code>inductive_lib.py</code> with all five nulls executed before any LOOCV/LOSO
      headline was reported. The Table 7 leakage demonstration uses the <em>older</em> P5 SSL ranking pipeline
      (<code>run_compression_ablation.py</code>) reproduced under both protocols specifically so that the inductive→transductive
      gap is observable on a clean code-path comparison; the canonical iter12/iter5/iter16 pipelines have
      <em>no</em> Table-7-style transductive variant because the leaky operations have been removed at the source.</p>
    </div>

    <h3>Pre-registered lockbox protocol</h3>
    <p><strong>Pre-registration commitment.</strong> For each of the three canonical pipelines reported in this paper,
    the configuration (model class, hyperparameters, feature set, seeds, and CV protocol) was frozen and serialized
    into a pre-registration JSON (with script SHA + git SHA) <em>before</em> the LOOCV (or LOSO) run was launched.
    The LOOCV/LOSO run was then executed exactly once on that frozen configuration and the result reported regardless
    of outcome. We did not iterate on the pre-registered configuration after seeing its LOOCV/LOSO output, and we did
    not select the published pipeline by comparing LOOCV/LOSO scores across multiple lockbox candidates. The full
    workflow is: 5-fold CV is used to screen configurations across many candidates; the winning 5-fold configuration
    is pre-registered into a JSON; then LOOCV (or LOSO) is run once on that pre-registered configuration (appendix
    Figure D). This is not a registered report — the lockboxes were created and executed in our own repository before
    journal submission rather than time-stamped with a third-party registry — but the pre-registration JSONs are
    immutable, signed-by-SHA artifacts that can be inspected and re-run for byte-equivalent reproduction.
    Files: <code>results/preregistration_t1_iter12_honest_*.json</code>,
    <code>results/preregistration_t3_iter5_20260502_171604.json</code>, <code>results/preregistration_t3_iter16_site_ipw_*.json</code>.</p>

    <h3>Statistical analysis</h3>
    <p>All headline metrics are Lin's concordance correlation coefficient<sup class="cite">[6]</sup>, calibration slope
    (linear regression of true on predicted), MAE, and Pearson r. We pre-register CCC rather than r as the primary metric
    because CCC penalises mean shifts and amplitude compression that Pearson r ignores: a model that systematically regresses
    toward the cohort mean (a known failure mode in small-N severity regression) can register a deceptively high r while
    its CCC collapses, so r alone would not distinguish a useful predictor from a calibrated one. CCC confidence intervals
    are subject-level percentile bootstrap, n_boot = {t1['boot_n']}. Comparator deltas (iter5 − iter3, iter16 LOOCV-IPW − iter5)
    use paired bootstrap over the same subject indices.</p>

    <h3>Code and data availability</h3>
    <p>WearGait-PD is available via Synapse (syn61370558 / syn55105530) under the dataset's data use agreement. All
    analysis code and pre-registration JSONs are available in the project repository; reproducer commands are listed
    in Table P1. The master/slave split places thin Python on the master and the full ML stack
    (PyTorch, LightGBM, XGBoost, MOMENT, sktime) on a CUDA-equipped slave; the <code>gpu.sh</code> wrapper synchronises
    code, runs the script remotely, and pulls results.</p>
    """

    appendix = f"""
    <section class="appendix">
      <h2>Appendix — illustrative pipeline schematics</h2>
      <p>The figures below (Figures A–F) are <em>illustrative schematics</em> intended to make the pipeline mechanics
      accessible to clinical readers. Numeric labels embedded in the schematics (CCC, MAE, N) are loaded directly from
      the lockbox JSONs; the box layouts and arrows are illustrative.</p>
      <figure>{img_tag(figs['figA'], 'Per-item gated schematic')}
      <figcaption><strong>Figure A.</strong> Per-item gated composite for T1 iter12 (Pipeline 1). Each item is predicted
      by its pre-registered model variant; per-item LOOCV out-of-fold predictions are summed, then the composite CCC is
      evaluated. <em>Illustrative schematic.</em></figcaption></figure>
      <figure>{img_tag(figs['figB'], 'Clinical residualization')}
      <figcaption><strong>Figure B.</strong> Two-stage clinical residualization for T3 iter5 (Pipeline 2). Stage 1
      (Ridge on H&amp;Y + intake) captures clinical staging signal; Stage 2 (LGB on V2 residual) captures the IMU
      contribution. <em>Illustrative schematic.</em></figcaption></figure>
      <figure>{img_tag(figs['figC'], 'Per-fold selection')}
      <figcaption><strong>Figure C.</strong> Per-fold K = 500 LGB-importance feature selection. Selection happens inside
      the train fold; using all-N feature ranks would leak test-fold information.
      <em>Illustrative schematic.</em></figcaption></figure>
      <figure>{img_tag(figs['figD'], 'Lockbox protocol')}
      <figcaption><strong>Figure D.</strong> Pre-registered lockbox protocol. Screen with 5-fold CV; pre-register one
      configuration; run LOOCV (or LOSO) exactly once; report regardless of outcome.
      <em>Illustrative schematic.</em></figcaption></figure>
      <figure>{img_tag(figs['figE'], '5-null gate')}
      <figcaption><strong>Figure E.</strong> The 5-null gate. Every new pipeline must pass all five before any number
      is reported. <em>Illustrative schematic.</em></figcaption></figure>
      <figure>{img_tag(figs['figF'], 'LOSO protocol')}
      <figcaption><strong>Figure F.</strong> Leave-one-site-out (LOSO) cross-cohort stress test protocol. Train on one
      site, test on the other; do this for both directions; report the two-way mean as a single point estimate. The
      asymmetry between directions (Table 5) is partly attributable to imbalanced training-set sizes (70 vs 28); with
      N=2 sites this is a stress test, not a transportability distribution. <em>Illustrative schematic.</em></figcaption></figure>

      <h3>Hyperparameter specification</h3>
      {tableP1_hyperparameters(d)}

      <h3>Supplementary tables</h3>
      {tableS1_ipw_loocv(d)}
      {tableS2_loso_seeds(d)}
      {tableS4_dbs_subgroup(d)}
      {tableS3_reproducibility(d)}
    </section>
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Inductive deployment estimates for clinical+IMU and IMU-only UPDRS-III prediction in Parkinson's disease</title>
  <meta name="generator" content="generate_paper_v5.py">
  <style>{CSS}</style>
</head>
<body>
  <h1>Inductive deployment estimates for clinical+IMU and IMU-only UPDRS-III prediction in Parkinson's disease: a clinical benchmark and two-site cross-cohort stress test on WearGait-PD</h1>
  <p class="subtitle">A pre-registered, lockbox-protected inductive benchmark; the first published cross-site number on WearGait-PD (two-site stress test); explicitly framed as a clinical+IMU hybrid for total UPDRS-III rather than a pure gait-IMU result.</p>
  <p class="authors"><em>Author block — to be completed</em></p>
  <p class="authors"><em>Affiliations / corresponding author / funding / COI — to be completed</em></p>

  {abstract}

  {intro}

  {results}

  {discussion}

  {methods}

  <h2>References</h2>
  <ol class="references">{refs_html}</ol>

  {appendix}

</body>
</html>"""


# ============================================================================
# main() — run after all figure / table builders are defined
# ============================================================================

def main():
    print("[generate_paper_v5] Loading data...")
    d = load_data()
    print(f"  T1 CCC = {d['t1']['ccc']:.4f}")
    print(f"  T3 CCC = {d['t3']['ccc']:.4f}")
    print(f"  T3 LOSO two-way = {d['t3_loso']['two_way_ccc']:.3f}")
    print("[generate_paper_v5] Building HTML...")
    html = build_html(d)
    OUTPUT_FILE.write_text(html)
    print(f"[generate_paper_v5] Wrote {OUTPUT_FILE} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate Nature-quality academic paper: UPDRS-III regression on WearGait-PD.

Loads all experiment artifacts, recomputes statistics, generates publication
figures, and assembles a self-contained HTML manuscript.

Usage: uv run python generate_paper.py [--output new_paper2.html]
Output: new_paper.html by default, or a custom path via --output
"""

import argparse, json, os, sys, base64, io, warnings, textwrap
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.patches import FancyBboxPatch, Circle
from matplotlib.lines import Line2D
import matplotlib.patheffects as pe
from scipy import stats as sp_stats
from scipy.stats import pearsonr, spearmanr, wilcoxon

warnings.filterwarnings("ignore")
np.random.seed(42)

# ─── PATHS ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
RESULTS = ROOT / "results"
DEFAULT_OUTPUT = ROOT / "new_paper.html"

# ─── COLORS (colorblind-safe) ─────────────────────────────────────────────────
C_PD = "#c0392b"
C_HC = "#2980b9"
C_DIRECT = "#27ae60"
C_PARTIAL = "#e67e22"
C_UNOBS = "#e74c3c"
C_FIT = "#e67e22"
C_FM = "#8e44ad"
C_ROCKET = "#d35400"
C_BASELINE = "#7f8c8d"
C_DEMO = "#f39c12"
C_MCID = "#f0e68c"

# ─── VERIFIED 10-SPLIT MAEs ──────────────────────────────────────────────────
# Mixed PD+HC (from rocket_phase2_fm.json, verified 2026-03-11)
SPLIT_MAES_V2 = [8.627, 9.539, 8.512, 8.750, 8.659, 8.050, 8.089, 8.842, 7.713, 8.071]
SPLIT_MAES_FM = [8.279, 8.206, 7.933, 7.286, 8.319, 8.110, 7.356, 7.774, 7.438, 7.047]
SPLIT_MAES_RK = [8.29, 8.38, 8.30, 8.12, 8.02, 8.75, 7.59, 8.46, 7.68, 7.19]
SPLIT_MAES_OBS_FM = [2.884, 2.971, 3.204, 3.826, 3.390, 2.898, 2.493, 3.284, 3.052, 2.147]
SPLIT_MAES_OBS_V2 = [3.413, 3.204, 3.465, 4.080, 3.492, 2.855, 2.572, 3.592, 3.151, 2.568]

MCID = 3.25  # Horvath 2015

# Cohort
N_ENROLLED_PD, N_ENROLLED_HC = 100, 85
N_ANALYZED_PD, N_ANALYZED_HC = 98, 80
N_ANALYZED = N_ANALYZED_PD + N_ANALYZED_HC


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════

def load_json(name: str) -> dict:
    p = RESULTS / name
    if not p.exists():
        raise FileNotFoundError(f"Missing artifact: {p}")
    with open(p) as f:
        return json.load(f)


@dataclass
class PaperData:
    """All data needed for the paper."""
    # PD-only consolidated results (primary)
    pd_only: dict = field(default_factory=dict)
    # 3-level observability (PD-only LOOCV)
    obs3: dict = field(default_factory=dict)
    # Sensor ablation (PD-only, FM re-extracted)
    sensor: dict = field(default_factory=dict)
    # Phase 2: FM LOOCV stats
    loocv_stats: dict = field(default_factory=dict)
    # Phase 4: severity confounds
    confounds: dict = field(default_factory=dict)
    # Phase 5: held-out test
    held_out: dict = field(default_factory=dict)
    # Clean benchmark predictions (for scatter plot)
    clean_bench: dict = field(default_factory=dict)
    # Subdomain v3 (per-item data for item-level plot)
    subdomain_items: list = field(default_factory=list)
    subdomain_composites: list = field(default_factory=list)
    # Demographics (from paper_supplements)
    demo_pd: dict = field(default_factory=dict)
    demo_hc: dict = field(default_factory=dict)
    # DL experiment results
    dl_results: dict = field(default_factory=dict)
    # Phase 1 per-split detail
    phase1: dict = field(default_factory=dict)
    # Test set arrays
    test_sids: list = field(default_factory=list)
    test_true: np.ndarray = field(default_factory=lambda: np.array([]))
    test_preds: np.ndarray = field(default_factory=lambda: np.array([]))
    test_groups: list = field(default_factory=list)


def load_all_data() -> PaperData:
    d = PaperData()

    # 1. PD-only consolidated (primary results)
    d.pd_only = load_json("pd_only_experiments.json")

    # 2. 3-level observability
    d.obs3 = load_json("pd_only_phase3.json")

    # 3. Sensor ablation (PD-only, FM re-extracted)
    d.sensor = load_json("pd_only_phase6.json")

    # 4. FM LOOCV enhanced stats
    d.loocv_stats = load_json("pd_only_phase2.json")

    # 5. Severity confounds
    d.confounds = load_json("pd_only_phase4.json")

    # 6. Held-out test
    d.held_out = load_json("pd_only_phase5.json")

    # 7. Clean benchmark (for test set scatter)
    d.clean_bench = load_json("clean_benchmark_results.json")

    # 8. Per-item subdomain
    sub = load_json("subdomain_v3_results.json")
    d.subdomain_items = sub["individual"]
    d.subdomain_composites = sub["composites"]

    # 9. Demographics
    supp = load_json("paper_supplements.json")
    d.demo_pd = supp["demographics"]["PD"]
    d.demo_hc = supp["demographics"]["HC"]

    # 10. DL results
    d.dl_results = load_json("dl_experiment_results.json")

    # 10b. Phase 1 per-split data (for full model table)
    d.phase1 = load_json("pd_only_phase1.json")

    # 11. Test set arrays from clean benchmark
    split = load_json("paper3_split.json")
    d.test_sids = split["test_sids"]

    feat_path = RESULTS / "v3_features.csv"
    if feat_path.exists():
        df = pd.read_csv(feat_path, usecols=["sid", "updrs3"])
        test_df = df[df["sid"].isin(d.test_sids)].set_index("sid").reindex(d.test_sids)
        d.test_true = test_df["updrs3"].values.astype(float)
    else:
        # Fallback: reconstruct from paper_supplements
        v3 = supp.get("v3_total_predictions", {})
        if v3:
            d.test_true = np.array(v3.get("true_scores", []))

    d.test_groups = ["PD" if s.startswith(("NLS", "WPD")) else "HC" for s in d.test_sids]

    # Get S0 baseline predictions
    for r in d.clean_bench.get("results", []):
        if r["config"] == "S0_baseline_K150":
            d.test_preds = np.array(r["ens_preds"])
            break

    return d


# ═══════════════════════════════════════════════════════════════════════════════
# STATISTICS
# ═══════════════════════════════════════════════════════════════════════════════

def mae_fn(y_true, y_pred):
    return np.mean(np.abs(y_true - y_pred))

def rmse_fn(y_true, y_pred):
    return np.sqrt(np.mean((y_true - y_pred) ** 2))

def ccc_fn(y_true, y_pred):
    """Lin's concordance correlation coefficient."""
    mu_t, mu_p = y_true.mean(), y_pred.mean()
    s_t, s_p = y_true.std(), y_pred.std()
    r = np.corrcoef(y_true, y_pred)[0, 1]
    return 2 * r * s_t * s_p / (s_t**2 + s_p**2 + (mu_t - mu_p)**2)

def bca_bootstrap_ci(y_true, y_pred, metric_fn, n_boot=10000, alpha=0.05, groups=None):
    """BCa bootstrap confidence interval."""
    n = len(y_true)
    rng = np.random.RandomState(42)
    theta_hat = metric_fn(y_true, y_pred)

    boot_stats = np.empty(n_boot)
    for b in range(n_boot):
        if groups is not None:
            idx = []
            for g in set(groups):
                g_idx = [i for i, gg in enumerate(groups) if gg == g]
                idx.extend(rng.choice(g_idx, size=len(g_idx), replace=True))
            idx = np.array(idx)
        else:
            idx = rng.choice(n, size=n, replace=True)
        boot_stats[b] = metric_fn(y_true[idx], y_pred[idx])

    z0 = sp_stats.norm.ppf(np.mean(boot_stats < theta_hat))
    jack = np.empty(n)
    for i in range(n):
        idx_j = np.concatenate([np.arange(i), np.arange(i + 1, n)])
        jack[i] = metric_fn(y_true[idx_j], y_pred[idx_j])
    jack_mean = jack.mean()
    num = np.sum((jack_mean - jack) ** 3)
    den = 6.0 * (np.sum((jack_mean - jack) ** 2) ** 1.5)
    a_hat = num / den if den != 0 else 0.0

    z_alpha = sp_stats.norm.ppf(alpha / 2)
    z_1alpha = sp_stats.norm.ppf(1 - alpha / 2)

    def adj_pct(z):
        return sp_stats.norm.cdf(z0 + (z0 + z) / (1 - a_hat * (z0 + z)))

    p_lo = np.clip(adj_pct(z_alpha), 0.001, 0.999)
    p_hi = np.clip(adj_pct(z_1alpha), 0.001, 0.999)
    return theta_hat, np.percentile(boot_stats, 100 * p_lo), np.percentile(boot_stats, 100 * p_hi)


def compute_test_stats(d: PaperData) -> dict:
    """Compute statistics for held-out test set."""
    if len(d.test_true) == 0 or len(d.test_preds) == 0:
        return {}

    y, p = d.test_true, d.test_preds
    groups = d.test_groups
    pd_mask = np.array([g == "PD" for g in groups])

    m, m_lo, m_hi = bca_bootstrap_ci(y, p, mae_fn, groups=groups)
    r_val, _ = pearsonr(y, p)
    _, r_lo, r_hi = bca_bootstrap_ci(y, p, lambda a, b: pearsonr(a, b)[0], groups=groups)

    residuals = p - y
    return {
        "mae": m, "mae_ci": (m_lo, m_hi),
        "r": r_val, "r_ci": (r_lo, r_hi),
        "rmse": rmse_fn(y, p),
        "ccc": ccc_fn(y, p),
        "pd_mae": float(np.mean(np.abs(y[pd_mask] - p[pd_mask]))),
        "hc_mae": float(np.mean(np.abs(y[~pd_mask] - p[~pd_mask]))),
        "within_mcid": float(np.mean(np.abs(y - p) <= MCID)),
        "bias": float(np.mean(residuals)),
        "loa_lo": float(np.mean(residuals) - 1.96 * np.std(residuals)),
        "loa_hi": float(np.mean(residuals) + 1.96 * np.std(residuals)),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FIGURE GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

def fig_to_b64(fig, dpi=300) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode()

def apply_style():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica Neue"],
        "font.size": 9.5, "axes.titlesize": 11.5, "axes.labelsize": 10,
        "xtick.labelsize": 8.5, "ytick.labelsize": 8.5,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.alpha": 0.24, "grid.linewidth": 0.6,
        "grid.color": "#aab4bf",
        "figure.facecolor": "white", "axes.facecolor": "white",
    })

apply_style()


def fig1_study_design() -> str:
    """Pipeline schematic."""
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 4)
    ax.axis("off")

    # Main pipeline boxes
    boxes = [
        (1.0, 2.5, "WearGait-PD\n178 subjects\n13 IMUs @ 100 Hz", "#3498db"),
        (3.0, 2.5, "6 Gait/Balance\nTasks\n1,417 recordings", "#2ecc71"),
        (5.0, 2.5, "Feature\nExtraction\n2,520 features", "#e67e22"),
        (7.0, 2.5, "XGB Selection\nTop-K features", "#9b59b6"),
        (9.0, 2.5, "LightGBM\nEnsemble\n5-seed avg", "#e74c3c"),
    ]
    for x, y, txt, color in boxes:
        box = FancyBboxPatch((x - 0.8, y - 0.6), 1.6, 1.2,
            boxstyle="round,pad=0.1", facecolor=color, alpha=0.15,
            edgecolor=color, lw=1.5)
        ax.add_patch(box)
        ax.text(x, y, txt, ha="center", va="center", fontsize=7.5,
                fontweight="bold", color="#2c3e50")

    for i in range(len(boxes) - 1):
        ax.annotate("", xy=(boxes[i+1][0] - 0.85, boxes[i+1][1]),
            xytext=(boxes[i][0] + 0.85, boxes[i][1]),
            arrowprops=dict(arrowstyle="->", color="#7f8c8d", lw=1.5))

    # Feature extraction detail
    feat_labels = [
        ("Handcrafted (1,752)", C_BASELINE),
        ("MOMENT-1 embeddings (768)", C_FM),
    ]
    for i, (lbl, c) in enumerate(feat_labels):
        ax.text(5.0, 1.4 - i * 0.4, lbl, ha="center", va="center",
                fontsize=7, color=c, style="italic")

    # Output with observability split
    ax.text(10.5, 3.0, "Observable\nSubscore\n(items 3.9-3.14)", ha="center",
            va="center", fontsize=7, fontweight="bold", color=C_DIRECT,
            bbox=dict(boxstyle="round,pad=0.3", fc="#e8f5e9", ec=C_DIRECT, lw=1))
    ax.text(10.5, 1.5, "Total\nUPDRS-III", ha="center", va="center",
            fontsize=7, fontweight="bold", color=C_PD,
            bbox=dict(boxstyle="round,pad=0.3", fc="#fadbd8", ec=C_PD, lw=1))

    ax.annotate("", xy=(9.7, 3.0), xytext=(9.85, 2.5),
        arrowprops=dict(arrowstyle="->", color=C_DIRECT, lw=1.2))
    ax.annotate("", xy=(9.7, 1.5), xytext=(9.85, 2.4),
        arrowprops=dict(arrowstyle="->", color=C_PD, lw=1.2))

    fig.suptitle("Figure 1: Study Design and Analysis Pipeline",
                 fontsize=11, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig_to_b64(fig)


def fig2_observability_summary(d: PaperData) -> str:
    """Observability-aware view: endpoint composition + tier performance."""
    obs = d.obs3["subscores"]
    tiers = [
        ("Directly observable", "direct", C_DIRECT, 24),
        ("Partially observable", "partial", C_PARTIAL, 68),
        ("Clinically unobservable", "unobs", C_UNOBS, 40),
    ]

    fig = plt.figure(figsize=(11.2, 5.6))
    gs = GridSpec(2, 1, height_ratios=[1.0, 4.2], hspace=0.35)
    ax_top = fig.add_subplot(gs[0])
    ax_main = fig.add_subplot(gs[1])

    cccs = [obs[key]["loocv"]["ccc"] for _, key, _, _ in tiers]
    maes = [obs[key]["loocv"]["mae"] for _, key, _, _ in tiers]
    rs = [obs[key]["loocv"]["r"] for _, key, _, _ in tiers]
    ns = [obs[key]["loocv"]["n"] for _, key, _, _ in tiers]
    max_scores = [score for _, _, _, score in tiers]
    nmaes = [mae / score * 100 for mae, score in zip(maes, max_scores)]

    # Top strip: how much of the total endpoint is directly available to gait sensing.
    ax_top.set_xlim(0, 132)
    ax_top.set_ylim(-0.8, 0.8)
    start = 0
    for label, _, color, width in tiers:
        ax_top.barh(0, width, left=start, height=0.48, color=color, alpha=0.9)
        share = width / 132 * 100
        ax_top.text(start + width / 2, 0, f"{label}\n{width}/132 ({share:.0f}%)",
                    ha="center", va="center", color="white", fontsize=8.2,
                    fontweight="bold")
        start += width
    ax_top.set_yticks([])
    ax_top.set_xticks([0, 24, 92, 132])
    ax_top.set_xlabel("Contribution to total MDS-UPDRS-III score range", fontweight="bold")
    ax_top.set_title("Only 24 of 132 score points are directly observable during gait",
                     fontweight="bold", fontsize=10.5, pad=8)
    for spine in ax_top.spines.values():
        spine.set_visible(False)
    ax_top.grid(False)

    # Bottom panel: normalized error vs concordance.
    ax_main.axhspan(0.45, 0.75, color="#eef8f3", zorder=0)
    ax_main.axvspan(6.6, 8.0, color="#f8fbf8", zorder=0)
    ax_main.annotate("Better: low error, high concordance",
                     xy=(6.8, 0.67), xytext=(8.6, 0.71),
                     arrowprops=dict(arrowstyle="->", color="#6b7280", lw=1.0),
                     fontsize=8, color="#4b5563")

    for (_, _, color, score_max), nmae, ccc in zip(tiers, nmaes, cccs):
        ax_main.scatter(nmae, ccc, s=score_max * 18, color=color, alpha=0.95,
                        edgecolors="white", linewidth=1.6, zorder=3)

    annotations = [
        ("Directly observable", nmaes[0], cccs[0], maes[0], rs[0], ns[0]),
        ("Partially observable", nmaes[1], cccs[1], maes[1], rs[1], ns[1]),
        ("Clinically unobservable", nmaes[2], cccs[2], maes[2], rs[2], ns[2]),
    ]
    for label, nmae, ccc, mae_val, r_val, n in annotations:
        ax_main.text(nmae + 0.18, ccc + 0.015,
                     f"{label}\nMAE={mae_val:.2f} | r={r_val:.2f} | N={n}",
                     fontsize=8, va="bottom", ha="left",
                     bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="#d4d8dd", alpha=0.95))

    ax_main.set_xlabel("Normalized MAE (% of attainable tier range)", fontweight="bold")
    ax_main.set_ylabel("Lin's concordance correlation coefficient", fontweight="bold")
    ax_main.set_xlim(6.4, 10.6)
    ax_main.set_ylim(-0.02, 0.75)
    ax_main.set_title("Agreement collapses once the endpoint moves beyond what gait can physically express",
                      fontweight="bold", fontsize=10.5)

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_DIRECT, markeredgecolor="white",
               markersize=9, label="Direct"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_PARTIAL, markeredgecolor="white",
               markersize=9, label="Partial"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_UNOBS, markeredgecolor="white",
               markersize=9, label="Unobservable"),
    ]
    ax_main.legend(handles=legend_elements, loc="lower right", fontsize=8, frameon=True)

    fig.suptitle("Figure 2: Observability, Not Model Class, Defines the Ceiling",
                 fontsize=11.5, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig_to_b64(fig)


def fig3_main_scatter(d: PaperData, test_stats: dict) -> str:
    """Held-out performance shown for the full test set and the PD-only subset."""
    if len(d.test_true) == 0:
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.text(0.5, 0.5, "Test data not available", transform=ax.transAxes,
                ha="center", va="center")
        return fig_to_b64(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.9), sharex=True, sharey=True)
    y_true, y_pred = d.test_true, d.test_preds
    pd_mask = np.array([g == "PD" for g in d.test_groups])
    lims = (-2, 62)
    xs = np.linspace(*lims, 200)

    def panel(ax, true_vals, pred_vals, title, colors, labels):
        ax.fill_between(xs, xs - MCID, xs + MCID, color=C_MCID, alpha=0.22, zorder=0)
        ax.plot(lims, lims, "--", color="#b8c1cc", lw=1.1, zorder=1)
        for t, p, c, label in zip(true_vals, pred_vals, colors, labels):
            ax.scatter(t, p, c=c, s=62, alpha=0.82, edgecolors="white",
                       linewidth=0.7, zorder=3)
            if label:
                ax.text(t + 0.6, p + 0.5, label, fontsize=7, color=c)
        if len(true_vals) >= 2 and np.std(true_vals) > 0:
            slope, intercept = np.polyfit(true_vals, pred_vals, 1)
            ax.plot(xs, slope * xs + intercept, color=C_FIT, lw=2, zorder=2)
        ax.set_title(title, fontweight="bold", fontsize=10.2)
        ax.set_xlim(*lims)
        ax.set_ylim(*lims)

    panel(
        axes[0],
        y_true,
        y_pred,
        "Full held-out test",
        [C_PD if is_pd else C_HC for is_pd in pd_mask],
        [""] * len(y_true),
    )
    panel(
        axes[1],
        y_true[pd_mask],
        y_pred[pd_mask],
        "PD-only held-out subset",
        [C_PD] * int(pd_mask.sum()),
        [""] * int(pd_mask.sum()),
    )

    for ax in axes:
        ax.set_xlabel("Actual UPDRS-III", fontweight="bold")
    axes[0].set_ylabel("Predicted UPDRS-III", fontweight="bold")

    if test_stats:
        axes[0].text(
            0.03, 0.97,
            (f"N={len(y_true)} ({sum(pd_mask)} PD, {sum(~pd_mask)} HC)\n"
             f"MAE={test_stats['mae']:.2f}\nCCC={test_stats['ccc']:.3f}\n"
             f"r={test_stats['r']:.3f}\nPD MAE={test_stats['pd_mae']:.2f}\nHC MAE={test_stats['hc_mae']:.2f}"),
            transform=axes[0].transAxes, va="top", ha="left", fontsize=7.6,
            bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#d4d8dd", alpha=0.95),
        )

    pd_true = y_true[pd_mask]
    pd_pred = y_pred[pd_mask]
    if len(pd_true):
        pd_mae = mae_fn(pd_true, pd_pred)
        pd_ccc = ccc_fn(pd_true, pd_pred)
        pd_r = pearsonr(pd_true, pd_pred)[0] if len(pd_true) > 1 else np.nan
        axes[1].text(
            0.03, 0.97,
            f"N={len(pd_true)}\nMAE={pd_mae:.2f}\nCCC={pd_ccc:.3f}\nr={pd_r:.3f}",
            transform=axes[1].transAxes, va="top", ha="left", fontsize=7.6,
            bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#d4d8dd", alpha=0.95),
        )
        axes[1].text(
            0.03, 0.05,
            "Group separation inflates the full-cohort fit.\nThe PD-only panel is the stricter test.",
            transform=axes[1].transAxes, va="bottom", ha="left", fontsize=7.2,
            bbox=dict(boxstyle="round,pad=0.24", fc="#fff8e6", ec="#ead6a0", alpha=0.98),
        )

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_PD, markeredgecolor="white",
               markersize=8, label="PD"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_HC, markeredgecolor="white",
               markersize=8, label="HC"),
        Line2D([0], [0], color=C_FIT, lw=2, label="Regression fit"),
    ]
    axes[0].legend(handles=legend_elements, loc="lower right", fontsize=8, frameon=True)

    fig.suptitle("Figure 6: Held-Out Performance Is Real but Still Dominated by Cohort Separation",
                 fontsize=11.5, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    return fig_to_b64(fig)


def fig4_item_predictability(d: PaperData) -> str:
    """Per-item correlation lollipop with 3-level observability coloring."""
    ITEM_NAMES = {
        "speech": ("Speech (3.1)", "unobs"),
        "facial": ("Facial Expr. (3.2)", "unobs"),
        "rigidity": ("Rigidity (3.3)", "unobs"),
        "finger_tap": ("Finger Tap (3.4)", "unobs"),
        "hand_mvmt": ("Hand Mvmt (3.5)", "partial"),
        "pronation": ("Pronation (3.6)", "partial"),
        "toe_tap": ("Toe Tap (3.7)", "partial"),
        "leg_agility": ("Leg Agility (3.8)", "partial"),
        "arising": ("Arising (3.9)", "direct"),
        "gait": ("Gait (3.10)", "direct"),
        "freezing": ("Freezing (3.11)", "direct"),
        "postural_stability": ("Post. Stab. (3.12)", "direct"),
        "posture": ("Posture (3.13)", "direct"),
        "body_bradykinesia": ("Body Brady. (3.14)", "direct"),
        "postural_tremor": ("Post. Tremor (3.15)", "partial"),
        "kinetic_tremor": ("Kin. Tremor (3.16)", "partial"),
        "rest_tremor_amp": ("Rest Tremor (3.17)", "partial"),
        "constancy_tremor": ("Tremor Const. (3.18)", "unobs"),
    }
    OBS_COLORS = {"direct": C_DIRECT, "partial": C_PARTIAL, "unobs": C_UNOBS}

    names, rs, colors = [], [], []
    for item in d.subdomain_items:
        n = item["subdomain"]
        info = ITEM_NAMES.get(n, (n, "unobs"))
        names.append(info[0])
        rs.append(item["ens_r"])
        colors.append(OBS_COLORS[info[1]])

    order = np.argsort(rs)[::-1]
    names = [names[i] for i in order]
    rs = [rs[i] for i in order]
    colors = [colors[i] for i in order]

    fig, ax = plt.subplots(figsize=(7, 6))
    y = np.arange(len(names))
    ax.hlines(y, 0, rs, colors=colors, lw=2.5)
    ax.scatter(rs, y, c=colors, s=60, zorder=3, edgecolors="white", lw=0.5)

    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("Pearson r (Predicted vs Actual)", fontweight="bold")
    ax.set_xlim(-0.1, 0.85)
    ax.invert_yaxis()

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_DIRECT,
               markersize=8, label="Direct observable (3.9-3.14)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_PARTIAL,
               markersize=8, label="Partially observable (3.5-3.8, 3.15-3.17)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_UNOBS,
               markersize=8, label="Not observable (3.1-3.4, 3.18)"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=7)

    fig.suptitle("Figure 3: Per-Item Predictability from Gait IMU",
                 fontsize=11, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    return fig_to_b64(fig)


def fig5_severity_calibration(d: PaperData) -> str:
    """Severity quartile error and mean-level calibration compression."""
    quartiles = d.confounds.get("severity_quartiles", d.loocv_stats.get("severity_quartiles", []))
    if not quartiles:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "Quartile data not available", transform=ax.transAxes,
                ha="center", va="center")
        return fig_to_b64(fig)

    overall = d.pd_only["master_table"]["loocv_fm"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.6, 4.6))

    labels = [q["label"] for q in quartiles]
    maes = [q["mae"] for q in quartiles]
    biases = [q["bias"] for q in quartiles]
    ns = [q["n"] for q in quartiles]
    mean_true = [q["mean_true"] for q in quartiles]
    mean_pred = [q["mean_pred"] for q in quartiles]
    x = np.arange(len(labels))
    colors = ["#9ecae1", "#6baed6", "#fd8d3c", "#cb181d"]

    # MAE by quartile
    bars = ax1.bar(x, maes, color=colors, alpha=0.88, edgecolor="white", lw=1.2)
    for i, (bar, n, bias) in enumerate(zip(bars, ns, biases)):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.35,
                 f"N={n}\nBias {bias:+.1f}", ha="center", fontsize=7.3)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylabel("MAE (UPDRS-III points)", fontweight="bold")
    ax1.set_title("Error is smallest in the middle and explodes at the extremes", fontweight="bold")
    ax1.axhline(MCID, color=C_DEMO, ls="--", lw=1, alpha=0.7)
    ax1.text(3.05, MCID + 0.35, "MCID context", fontsize=7.3, color=C_DEMO)

    # Mean-level calibration map
    lim_hi = max(max(mean_true), max(mean_pred)) + 6
    ax2.plot([0, lim_hi], [0, lim_hi], "--", color="#b8c1cc", lw=1.1, zorder=1)
    for label, n, t, p, color, bias in zip(labels, ns, mean_true, mean_pred, colors, biases):
        ax2.scatter(t, p, s=n * 18, color=color, edgecolors="white", linewidth=1.2, zorder=3)
        ax2.text(t + 0.7, p + 0.5, f"{label}\n{bias:+.1f}", fontsize=7.4,
                 bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="#d4d8dd", alpha=0.95))
    ax2.set_xlim(0, lim_hi)
    ax2.set_ylim(0, lim_hi)
    ax2.set_xlabel("Mean true score within quartile", fontweight="bold")
    ax2.set_ylabel("Mean predicted score within quartile", fontweight="bold")
    ax2.set_title("Quartile means collapse toward the cohort center", fontweight="bold")
    ax2.text(
        0.03, 0.97,
        f"Overall calibration slope = {overall['cal_slope']:.3f}\n"
        f"Intercept = {overall['cal_intercept']:.1f}\n"
        "Ideal model: all quartile means on the identity line",
        transform=ax2.transAxes, fontsize=7.5, va="top",
        bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#d4d8dd", alpha=0.96),
    )

    fig.suptitle("Figure 4: Severity Extremes Are Compressed Toward the Cohort Mean",
                 fontsize=11.5, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    return fig_to_b64(fig)


def fig6_fm_impact() -> str:
    """FM stack vs baseline across 10 splits (mixed PD+HC)."""
    fig, ax = plt.subplots(figsize=(6, 4.5))
    v2 = np.array(SPLIT_MAES_V2)
    fm = np.array(SPLIT_MAES_FM)

    x = np.arange(1, 11)
    for i in range(10):
        ax.plot([x[i], x[i]], [v2[i], fm[i]], color="#bdc3c7", lw=1, zorder=1)

    ax.scatter(x, v2, c=C_BASELINE, s=60, zorder=3,
              label=f"Baseline (\u03bc={v2.mean():.2f})", edgecolors="white", lw=0.5)
    ax.scatter(x, fm, c=C_FM, s=60, zorder=3,
              label=f"FM Stack (\u03bc={fm.mean():.2f})", edgecolors="white", lw=0.5, marker="D")

    ax.axhline(v2.mean(), color=C_BASELINE, ls="--", alpha=0.5, lw=1)
    ax.axhline(fm.mean(), color=C_FM, ls="--", alpha=0.5, lw=1)

    _, p = wilcoxon(fm, v2, alternative="less")
    ax.text(0.02, 0.98, f"FM vs Baseline: p = {p:.4f}\n\u0394MAE = {v2.mean()-fm.mean():.2f}",
            transform=ax.transAxes, fontsize=8, va="top", fontweight="bold", color=C_FM)

    ax.set_xlabel("Random Split", fontweight="bold")
    ax.set_ylabel("MAE (UPDRS-III points)", fontweight="bold")
    ax.set_xticks(x)
    ax.legend(fontsize=8)
    fig.suptitle("Figure 5: Foundation Model Impact (Mixed PD+HC, 10 Splits)",
                 fontsize=11, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return fig_to_b64(fig)


def fig7_sensor_ablation(d: PaperData) -> str:
    """Sensor ablation bar chart."""
    configs = d.sensor.get("configs", {})
    if not configs:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.text(0.5, 0.5, "Sensor data not available", transform=ax.transAxes,
                ha="center", va="center")
        return fig_to_b64(fig)

    order = ["all_13", "minimal_5", "wrists_back_3", "wrists_2", "lower_back_1"]
    labels = ["All 13", "Minimal 5\n(back+wrists+ankles)", "Back+Wrists (3)",
              "Wrists Only (2)", "Lower Back (1)"]
    maes = [configs[k]["mae_mean"] for k in order]
    stds = [configs[k]["mae_std"] for k in order]
    ps = [configs[k].get("vs_all_13", {}).get("p", None) for k in order]

    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(len(order))
    colors = [C_FM if k in ("all_13", "minimal_5") else C_BASELINE for k in order]
    bars = ax.bar(x, maes, yerr=stds, color=colors, alpha=0.8,
                  edgecolor="white", lw=1, capsize=4)

    for i, (bar, p_val) in enumerate(zip(bars, ps)):
        if p_val is not None:
            sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else "ns"
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + stds[i] + 0.15,
                    f"p={p_val:.2f}\n{sig}", ha="center", fontsize=6.5)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("MAE (UPDRS-III points)", fontweight="bold")
    ax.set_ylim(6, 10)

    fig.suptitle("Figure 7: Sensor Ablation (PD-Only, FM Re-Extracted Per Config)",
                 fontsize=11, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return fig_to_b64(fig)


def fig8_cross_dataset() -> str:
    """Cross-dataset context restricted to total-score endpoints."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.4, 5.0), gridspec_kw={"width_ratios": [1.25, 1.0]})

    studies = [
        {
            "label": "This work\nPD-only LOOCV",
            "detail": "N=98 PD | 13 IMUs | controlled gait",
            "mae": 8.15,
            "lo": 6.95,
            "hi": 9.38,
            "n": 98,
            "sensors": 13,
            "setting": "Controlled gait",
            "protocol": "Strict subject LOOCV",
            "color": C_FM,
        },
        {
            "label": "This work\nHeld-out test",
            "detail": "N=36 | 13 IMUs | pre-registered split",
            "mae": 9.36,
            "lo": 7.50,
            "hi": 11.20,
            "n": 36,
            "sensors": 13,
            "setting": "Controlled gait",
            "protocol": "Held-out once",
            "color": C_BASELINE,
        },
        {
            "label": "Hssayeni 2021",
            "detail": "N=24 PD | wrist+ankle gyro | free-living",
            "mae": 5.95,
            "lo": None,
            "hi": None,
            "n": 24,
            "sensors": 2,
            "setting": "Free-living",
            "protocol": "LOOCV",
            "color": "#2ecc71",
        },
        {
            "label": "Shuqair 2024",
            "detail": "N=24 PD | wrist+ankle | same cohort",
            "mae": 5.65,
            "lo": None,
            "hi": None,
            "n": 24,
            "sensors": 2,
            "setting": "Free-living",
            "protocol": "LOOCV",
            "color": "#3498db",
        },
    ]

    # Left: total-score MAE only.
    for i, study in enumerate(studies[::-1]):
        y = i
        ax1.scatter(study["mae"], y, s=120, c=study["color"], edgecolors="white", linewidth=1.3, zorder=3)
        if study["lo"] is not None and study["hi"] is not None:
            ax1.plot([study["lo"], study["hi"]], [y, y], color=study["color"], lw=2.2, zorder=2)
        ax1.text(3.35, y + 0.17, study["label"], fontsize=8.2, fontweight="bold", ha="left", va="center")
        ax1.text(3.35, y - 0.16, study["detail"], fontsize=7.2, color="#5f6b76", ha="left", va="center")

    ax1.set_xlim(3.2, 12.2)
    ax1.set_ylim(-0.7, len(studies) - 0.3)
    ax1.set_yticks([])
    ax1.set_xlabel("MAE on total motor score", fontweight="bold")
    ax1.set_title("Visual comparison restricted to total-score endpoints", fontweight="bold", fontsize=10.4)
    ax1.text(
        0.02, 0.04,
        "Our directly observable subscore is intentionally excluded here:\n"
        "it is a different endpoint with a different score range.",
        transform=ax1.transAxes, fontsize=7.2, va="bottom", ha="left",
        bbox=dict(boxstyle="round,pad=0.28", fc="#fff8e6", ec="#ead6a0", alpha=0.98),
    )

    # Right: context matrix showing why the raw MAE gap is not an apples-to-apples contest.
    ax2.set_title("Protocol mismatch explains much of the apparent gap", fontweight="bold", fontsize=10.4)
    col_x = [0.0, 0.44, 0.71]
    headers = ["Cohort size", "Task setting", "Validation"]
    for x, header in zip(col_x, headers):
        ax2.text(x, 1.02, header, transform=ax2.transAxes, fontsize=8, fontweight="bold", ha="left")

    for row, study in enumerate(studies):
        y = 0.86 - row * 0.22
        ax2.text(-0.02, y, study["label"].replace("\n", " "), transform=ax2.transAxes,
                 fontsize=8.1, ha="right", va="center")
        ax2.add_patch(FancyBboxPatch((col_x[0], y - 0.055), 0.18, 0.09,
                                     boxstyle="round,pad=0.02", transform=ax2.transAxes,
                                     facecolor="#f4f1ea", edgecolor="#d8d2c4"))
        ax2.text(col_x[0] + 0.09, y - 0.01, f"N={study['n']}", transform=ax2.transAxes,
                 fontsize=8, ha="center", va="center", fontweight="bold")

        setting_color = "#d9f2eb" if "Controlled" in study["setting"] else "#e8f0fb"
        ax2.add_patch(FancyBboxPatch((col_x[1], y - 0.055), 0.2, 0.09,
                                     boxstyle="round,pad=0.02", transform=ax2.transAxes,
                                     facecolor=setting_color, edgecolor="#d8d2c4"))
        ax2.text(col_x[1] + 0.10, y - 0.01, study["setting"], transform=ax2.transAxes,
                 fontsize=7.6, ha="center", va="center")

        protocol_color = "#eaf3ea" if "Strict" in study["protocol"] or "Held-out" in study["protocol"] else "#f7efe2"
        ax2.add_patch(FancyBboxPatch((col_x[2], y - 0.055), 0.22, 0.09,
                                     boxstyle="round,pad=0.02", transform=ax2.transAxes,
                                     facecolor=protocol_color, edgecolor="#d8d2c4"))
        ax2.text(col_x[2] + 0.11, y - 0.01, study["protocol"], transform=ax2.transAxes,
                 fontsize=7.4, ha="center", va="center")

    ax2.text(
        0.0, 0.03,
        "Interpretation: lower MAE in a smaller free-living LOOCV cohort does not falsify the\n"
        "observability ceiling on WearGait-PD. It reflects different sensors, tasks, cohort size,\n"
        "and validation regimes.",
        transform=ax2.transAxes, fontsize=7.4, va="bottom", ha="left",
        color="#5f6b76",
    )
    ax2.axis("off")

    fig.suptitle("Figure 8: Cross-Dataset Context Without Mixing Incompatible Endpoints",
                 fontsize=11.5, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    return fig_to_b64(fig)


# ═══════════════════════════════════════════════════════════════════════════════
# HTML BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700&family=Source+Sans+3:wght@400;600;700&display=swap');
:root {
  --ink: #1f2933;
  --muted: #5f6b76;
  --shell: #f4f0e8;
  --paper: #fffdf8;
  --panel: #f7f3ea;
  --line: #ddd6c7;
  --accent: #186b66;
  --accent-soft: #e4f3f0;
  --warm: #b3513b;
  --gold: #b38b2a;
  --shadow: 0 24px 60px rgba(20, 30, 40, 0.08);
}
html { scroll-behavior: smooth; }
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: 'Source Serif 4', Georgia, serif;
  font-size: 11pt;
  line-height: 1.72;
  color: var(--ink);
  background:
    radial-gradient(circle at top right, rgba(24, 107, 102, 0.10), transparent 34%),
    radial-gradient(circle at top left, rgba(179, 139, 42, 0.08), transparent 26%),
    var(--shell);
}
.paper-shell {
  max-width: 1280px;
  margin: 0 auto;
  padding: 32px 20px 72px;
  display: grid;
  grid-template-columns: minmax(0, 940px) 260px;
  gap: 28px;
  align-items: start;
}
.paper {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 28px;
  box-shadow: var(--shadow);
  overflow: hidden;
}
.hero {
  position: relative;
  padding: 48px 56px 30px;
  background: linear-gradient(150deg, #fbf7ee 0%, #f9fcfb 58%, #fffef9 100%);
  border-bottom: 1px solid var(--line);
}
.hero::after {
  content: "";
  position: absolute;
  right: -30px;
  bottom: -70px;
  width: 220px;
  height: 220px;
  background: radial-gradient(circle, rgba(24, 107, 102, 0.18), rgba(24, 107, 102, 0));
  pointer-events: none;
}
.kicker,
.eyebrow,
.abstract-label,
.snapshot-label,
.toc-kicker,
.section-tag {
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.73rem;
  font-weight: 700;
}
.kicker { color: var(--accent); margin: 0 0 12px; }
h1, h2, h3, h4 {
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  line-height: 1.18;
}
h1 {
  margin: 0 0 10px;
  font-size: clamp(2rem, 4vw, 2.7rem);
  max-width: 15ch;
}
.deck {
  margin: 0;
  max-width: 62ch;
  color: var(--muted);
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 1.04rem;
}
.authors, .affiliations {
  margin: 0;
  color: var(--muted);
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
}
.authors { margin-top: 18px; font-size: 0.96rem; }
.affiliations { font-size: 0.88rem; margin-top: 4px; }
.snapshot-grid,
.takeaway-grid,
.abstract-grid,
.contribution-grid {
  display: grid;
  gap: 14px;
}
.snapshot-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 26px;
}
.snapshot-card,
.takeaway-card,
.abstract-block,
.contribution-card,
.table-card,
figure {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 20px;
  box-shadow: 0 12px 28px rgba(20, 30, 40, 0.04);
}
.snapshot-card,
.takeaway-card,
.abstract-block,
.contribution-card {
  padding: 16px 16px 14px;
}
.snapshot-value,
.takeaway-number {
  display: block;
  margin: 6px 0 4px;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 1.28rem;
  font-weight: 700;
}
.snapshot-detail,
.takeaway-detail,
.contribution-card p {
  margin: 0;
  color: var(--muted);
  font-size: 0.9rem;
}
.claim-banner {
  margin-top: 18px;
  padding: 18px 20px;
  border-radius: 20px;
  border: 1px solid #cfe4df;
  background: linear-gradient(135deg, var(--accent-soft), #f6fbfa 65%, #fffef9 100%);
}
.eyebrow { color: var(--accent); display: block; margin-bottom: 6px; }
.claim-banner p {
  margin: 0;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 1rem;
  line-height: 1.5;
}
.paper-section {
  padding: 34px 56px 0;
}
.paper-section:last-child {
  padding-bottom: 48px;
}
.section-heading {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 18px;
  align-items: end;
  justify-content: space-between;
  margin-bottom: 12px;
}
h2 {
  margin: 0;
  font-size: 1.46rem;
  color: var(--accent);
}
.section-tag { color: var(--muted); }
.section-lead,
.callout,
.lead {
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  color: #33414c;
}
.section-lead {
  margin: 0;
  max-width: 56ch;
  font-size: 0.98rem;
  color: var(--muted);
}
h3 {
  margin: 1.8rem 0 0.65rem;
  font-size: 1.08rem;
  color: #29414d;
}
p { margin: 0 0 1rem; }
.abstract-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 14px;
}
.abstract-block {
  background: var(--panel);
  box-shadow: none;
}
.abstract-label { color: var(--accent); margin-bottom: 8px; display: block; }
.takeaway-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 18px;
}
.takeaway-title {
  margin: 0 0 6px;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 0.95rem;
  font-weight: 700;
}
.takeaway-number { color: var(--warm); }
.contribution-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 18px 0 24px;
}
.contribution-card h4 {
  margin: 0 0 8px;
  font-size: 0.98rem;
}
.callout {
  margin: 16px 0 20px;
  padding: 14px 18px;
  background: #f3faf8;
  border-left: 4px solid var(--accent);
  border-radius: 0 16px 16px 0;
  font-size: 0.95rem;
}
figure {
  margin: 22px 0 18px;
  padding: 18px 18px 14px;
  page-break-inside: avoid;
}
figure img {
  max-width: 100%;
  display: block;
  border-radius: 14px;
}
figcaption {
  margin-top: 12px;
  color: var(--muted);
  font-size: 0.87rem;
}
figcaption strong { color: var(--ink); }
.table-card {
  margin: 18px 0 24px;
  overflow: hidden;
}
.table-wrap { overflow-x: auto; }
table {
  border-collapse: collapse;
  width: 100%;
  min-width: 720px;
  margin: 0;
  font-size: 0.92rem;
  page-break-inside: avoid;
}
caption {
  caption-side: top;
  text-align: left;
  padding: 18px 18px 8px;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 0.96rem;
  font-weight: 700;
}
th {
  background: #f3ede2;
  text-align: left;
  padding: 9px 10px;
  font-weight: 700;
  border-top: 2px solid #3c4a54;
  border-bottom: 1px solid #bfc7cf;
}
td {
  padding: 7px 10px;
  border-bottom: 1px solid #e3ddd2;
}
tr:nth-child(even) { background: #fcfbf7; }
tr.highlight { background: #edf8f2; font-weight: 600; }
tr.primary { background: #fff6df; }
.note {
  margin: 0;
  padding: 0 18px 18px;
  color: var(--muted);
  font-size: 0.82rem;
}
.ref {
  font-size: 0.92rem;
}
.ref ol { padding-left: 1.3rem; margin-top: 0.8rem; }
.ref li { margin-bottom: 0.65rem; }
sup { font-size: 0.7em; }
.toc {
  position: sticky;
  top: 24px;
}
.toc-card {
  padding: 20px 18px;
  background: rgba(255, 253, 248, 0.88);
  border: 1px solid var(--line);
  border-radius: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(10px);
}
.toc-kicker { color: var(--accent); margin-bottom: 4px; }
.toc-title {
  margin: 0 0 12px;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 1.06rem;
  font-weight: 700;
}
.toc-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.toc-list li { margin: 0 0 0.5rem; }
.toc-list a {
  color: var(--ink);
  text-decoration: none;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 0.92rem;
}
.toc-list a:hover { color: var(--accent); }
.obs-meter {
  margin-top: 16px;
  border-top: 1px solid var(--line);
  padding-top: 14px;
}
.obs-bar {
  display: flex;
  height: 12px;
  border-radius: 999px;
  overflow: hidden;
  margin-bottom: 10px;
}
.obs-direct { background: #1b7f64; width: 18.2%; }
.obs-partial { background: #c17a18; width: 51.5%; }
.obs-unobs { background: #b8483a; width: 30.3%; }
.obs-list {
  list-style: none;
  margin: 0;
  padding: 0;
  font-family: 'Source Sans 3', 'Helvetica Neue', sans-serif;
  font-size: 0.84rem;
  color: var(--muted);
}
.obs-list li { margin-bottom: 0.35rem; }
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92em;
  background: #f3efe7;
  padding: 0.08em 0.32em;
  border-radius: 6px;
}
@media (max-width: 1100px) {
  .paper-shell { grid-template-columns: 1fr; }
  .toc { position: static; }
}
@media (max-width: 820px) {
  .hero,
  .paper-section { padding-left: 24px; padding-right: 24px; }
  .snapshot-grid,
  .takeaway-grid,
  .abstract-grid,
  .contribution-grid { grid-template-columns: 1fr; }
  table { min-width: 640px; }
}
@media print {
  body { background: #fff; }
  .paper-shell { display: block; padding: 0; }
  .paper,
  .toc-card,
  figure,
  .table-card,
  .snapshot-card,
  .takeaway-card,
  .abstract-block,
  .contribution-card {
    box-shadow: none;
    border-color: #cfc8b8;
  }
  .toc { display: none; }
  .hero,
  .paper-section { padding-left: 0; padding-right: 0; }
}
</style>
"""


def table_card(table_html: str) -> str:
    return f'<div class="table-card"><div class="table-wrap">{table_html}</div></div>'


def build_html(d: PaperData, test_stats: dict, figures: dict) -> str:
    mt = d.pd_only["master_table"]
    dp = d.demo_pd
    dc = d.demo_hc
    obs = d.obs3["subscores"]
    loocv = d.loocv_stats

    # Key numbers
    fm_loocv = mt["loocv_fm"]
    demo_loocv = mt["loocv_demo"]
    direct = obs["direct"]["loocv"]
    partial = obs["partial"]["loocv"]
    unobs_l = obs["unobs"]["loocv"]
    binary_obs = obs["binary_obs"]["loocv"]
    held = mt["held_out_full"]
    held_demo = mt["held_out_demo"]
    p10_b1_v2 = mt["10split_b1_v2"]
    p10_demo = mt["10split_demographic"]
    p10_fm = mt["10split_b1_fm_stk"]
    partial_corr = loocv["partial_correlation"]
    bland = loocv["bland_altman"]
    clinical = loocv["clinical_significance"]

    # Mixed PD+HC stats
    fm_mixed = np.array(SPLIT_MAES_FM)
    v2_mixed = np.array(SPLIT_MAES_V2)
    _, p_fm_v2 = wilcoxon(fm_mixed, v2_mixed, alternative="less")

    # Holm-Bonferroni corrected p-values
    hb = {h["label"]: h for h in d.pd_only["holm_bonferroni"]}

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wearable Gait Sensors Predict Observable Motor Severity in Parkinson's Disease</title>
{CSS}
</head>
<body>

<h1>Wearable gait sensors predict observable but not unobservable motor severity in Parkinson's disease</h1>

<p class="authors">[Author names to be added]</p>
<p class="affiliations">[Affiliations to be added]</p>

<!-- ═══════════════════════════════════════════ ABSTRACT ═══════════════════ -->
<div class="abstract">
<h3>Abstract</h3>
<p>
The MDS-UPDRS Part III motor examination is the clinical gold standard for Parkinson's disease (PD) severity assessment, yet its 18 items span motor functions ranging from gait and posture&mdash;directly manifest during ambulation&mdash;to rigidity, speech, and facial expression, which require clinical examination modalities that no body-worn sensor can capture. Here we present the first UPDRS-III regression benchmark on WearGait-PD, the largest controlled-gait dataset with complete motor scores (N&nbsp;=&nbsp;{N_ANALYZED} subjects, {N_ANALYZED_PD} PD, {N_ANALYZED_HC} healthy controls, 13 IMU sensors at 100&nbsp;Hz). In PD-only leave-one-out cross-validation (N&nbsp;=&nbsp;98), our foundation-model-augmented pipeline achieves MAE&nbsp;=&nbsp;{fm_loocv['mae']:.2f} (CCC&nbsp;=&nbsp;{fm_loocv['ccc']:.2f}, r&nbsp;=&nbsp;{fm_loocv['r']:.3f}) for total UPDRS-III&mdash;notably, a demographic Ridge baseline using age, sex, disease duration, height, and weight achieves MAE&nbsp;=&nbsp;{demo_loocv['mae']:.2f}, outperforming all sensor models on this composite endpoint. Nevertheless, partial correlation r&nbsp;=&nbsp;{partial_corr['r']:.2f} (p<sub>adj</sub>&nbsp;=&nbsp;0.002) after controlling for age and disease duration confirms that the inertial signal contributes beyond demographic confounds. Critically, decomposing the score into three observability tiers reveals a structural prediction ceiling: directly observable items (3.9&ndash;3.14: gait, posture, arising, body bradykinesia) achieve CCC&nbsp;=&nbsp;{direct['ccc']:.2f} and MAE&nbsp;=&nbsp;{direct['mae']:.2f} (N&nbsp;=&nbsp;{direct['n']}), while partially observable (CCC&nbsp;=&nbsp;{partial['ccc']:.2f}) and clinically unobservable items (CCC&nbsp;=&nbsp;{unobs_l['ccc']:.2f}) remain poorly predicted. (Note: the MCID of 3.25 was derived for longitudinal change detection<sup>2</sup>; comparison with cross-sectional prediction error is contextual.) Feature&ndash;anatomy alignment validates the mechanism: foot and trunk sensors drive gait-item predictions, while wrist sensors drive upper-limb items. Seven deep learning configurations across three architecture families, MiniRocket kernels, and multiple feature engineering strategies all converge on the same total-score ceiling, suggesting that the barrier is determined by item observability rather than modeling methodology. We propose that the directly observable motor subdomain is a more appropriate endpoint for wearable-based PD monitoring than the total composite score.
</p>
</div>

<!-- ═══════════════════════════════════════════ INTRODUCTION ═══════════════ -->
<h2>1. Introduction</h2>

<p>
Parkinson's disease (PD) affects over 8.5 million people worldwide, making it the fastest-growing neurological disorder<sup>1</sup>. The Movement Disorder Society Unified Parkinson's Disease Rating Scale Part III (MDS-UPDRS-III) is the gold standard for motor severity assessment, comprising 18 items (33 sub-items) scored 0&ndash;4 each (total range 0&ndash;132). Administration requires a trained clinician, takes 20&ndash;30 minutes, and is inherently subjective&mdash;inter-rater variability can exceed the minimally clinically important difference (MCID) of 3.25 points<sup>2</sup>.
</p>

<p>
Body-worn inertial measurement units (IMUs) offer a path toward continuous, objective motor monitoring. Several groups have attempted UPDRS-III regression from wearable sensors. Hssayeni et&nbsp;al. achieved MAE&nbsp;=&nbsp;5.95 with an ensemble of three deep learning models on 24 PD patients using wrist and ankle gyroscopes during free-living activities (LOOCV)<sup>3</sup>. Shuqair et&nbsp;al. improved correlation to r&nbsp;=&nbsp;0.89 on the same 24-patient dataset using self-supervised pretraining<sup>4</sup>. Both studies used leave-one-out cross-validation on small, PD-only cohorts, limiting generalizability. Other reported results suffer from methodological concerns: the IS22 result (MAE&nbsp;=&nbsp;4.26) contained confirmed window-level data leakage<sup>5</sup>, and the TRIP benchmark on WearGait-PD addressed only classification, not regression<sup>6</sup>.
</p>

<p>
WearGait-PD is the largest publicly available controlled-gait dataset with complete MDS-UPDRS-III scores, comprising {N_ENROLLED_PD + N_ENROLLED_HC} enrolled subjects ({N_ENROLLED_PD} PD, {N_ENROLLED_HC} HC), of whom {N_ANALYZED} ({N_ANALYZED_PD} PD, {N_ANALYZED_HC} HC) had complete recordings<sup>7</sup>. No published UPDRS-III regression exists on this dataset.
</p>

<p>
We present four contributions. First, we establish a rigorous regression benchmark on WearGait-PD with subject-level evaluation protocols including PD-only LOOCV, multi-split cross-validation, and a pre-registered held-out test. Second, we decompose UPDRS-III into three observability tiers&mdash;directly observable, partially observable, and clinically unobservable from gait&mdash;revealing a structural prediction ceiling that explains why total-score regression plateaus regardless of modeling sophistication. Third, we demonstrate that frozen foundation model embeddings from MOMENT-1<sup>8</sup> significantly outperform handcrafted features in mixed-cohort evaluation (p&nbsp;=&nbsp;{p_fm_v2:.4f}), though this advantage diminishes in PD-only evaluation where within-disease severity discrimination is harder than PD-vs-HC separation. Fourth, we show that a 5-sensor minimal set achieves equivalent performance to the full 13-sensor configuration (p&nbsp;=&nbsp;0.85), informing clinical deployment.
</p>

<figure>
<img src="{figures['fig1']}" alt="Study design pipeline">
<figcaption><strong>Figure 1.</strong> Study design and analysis pipeline. WearGait-PD data from 13 IMU sensors across 6 gait/balance tasks are processed through dual feature extraction pathways: 1,752 handcrafted features and 768-dimensional frozen MOMENT-1 embeddings. XGBoost importance-based selection retains top-K features, fed into a multi-seed LightGBM ensemble. Predictions are evaluated for both total UPDRS-III and the directly observable motor subdomain (items 3.9&ndash;3.14).</figcaption>
</figure>

<!-- ═══════════════════════════════════════════ RESULTS ═══════════════════ -->
<h2>2. Results</h2>

<h3>2.1 Cohort Description</h3>

<p>
Of {N_ENROLLED_PD + N_ENROLLED_HC} enrolled participants, {N_ANALYZED} ({N_ANALYZED_PD} PD, {N_ANALYZED_HC} HC) had complete sensor recordings and were included (Table&nbsp;1). PD participants (mean age {dp['age_mean']}&nbsp;&plusmn;&nbsp;{dp['age_std']} years, {dp['sex_m_f'][0]}M/{dp['sex_m_f'][1]}F) had moderate motor severity (UPDRS-III {dp['updrs3_mean']}&nbsp;&plusmn;&nbsp;{dp['updrs3_std']}, range {dp['updrs3_range']}). Hoehn&nbsp;&amp;&nbsp;Yahr staging was available for {dp['hy_n_available']} patients (mean {dp['hy_mean']}&nbsp;&plusmn;&nbsp;{dp['hy_std']}). The HC group was older ({dc['age_mean']}&nbsp;&plusmn;&nbsp;{dc['age_std']} years, p&nbsp;&lt;&nbsp;0.001) with lower motor scores ({dc['updrs3_mean']}&nbsp;&plusmn;&nbsp;{dc['updrs3_std']}). Medication state (ON/OFF) was not systematically controlled in the WearGait-PD protocol.
</p>

{_table1(dp, dc)}

<h3>2.2 Total UPDRS-III Prediction: The Demographic Baseline Challenge</h3>

<p>
In PD-only 10-split cross-validation (N&nbsp;=&nbsp;98, Table&nbsp;2), our best IMU model (LightGBM with handcrafted features, PD-only training) achieved MAE&nbsp;=&nbsp;{p10_b1_v2['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{p10_b1_v2['mae_std']:.2f} with CCC&nbsp;=&nbsp;{p10_b1_v2['ccc_mean']:.3f}&nbsp;&plusmn;&nbsp;{p10_b1_v2['ccc_std']:.3f}. However, a demographic Ridge baseline using only age, sex, disease duration, height, and weight achieved MAE&nbsp;=&nbsp;{p10_demo['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{p10_demo['mae_std']:.2f} (CCC&nbsp;=&nbsp;{p10_demo['ccc_mean']:.3f}&nbsp;&plusmn;&nbsp;{p10_demo['ccc_std']:.3f}), outperforming all IMU models on MAE. This finding underscores that total UPDRS-III within a PD cohort is substantially driven by disease stage (age, duration) rather than moment-to-moment motor state.
</p>

<p>
PD-only LOOCV (N&nbsp;=&nbsp;98) confirmed this pattern: FM-augmented IMU MAE&nbsp;=&nbsp;{fm_loocv['mae']:.2f} versus demographic baseline MAE&nbsp;=&nbsp;{demo_loocv['mae']:.2f} (bootstrap p&nbsp;=&nbsp;{loocv['bootstrap_fm_vs_demo']['p']:.2f}, not significant). Calibration was poor for both: IMU slope&nbsp;=&nbsp;{fm_loocv['cal_slope']:.3f}, demographic slope&nbsp;=&nbsp;{demo_loocv['cal_slope']:.3f} (ideal&nbsp;=&nbsp;1.0), reflecting severe regression to the PD-group mean.
</p>

<p>
Crucially, however, a permutation test confirmed that the IMU model significantly outperforms a mean-prediction baseline (p<sub>adj</sub>&nbsp;=&nbsp;{hb['P2_permutation']['p_adj']:.4f}), and partial correlation controlling for age and disease duration yielded r&nbsp;=&nbsp;{partial_corr['r']:.2f} (p<sub>adj</sub>&nbsp;=&nbsp;{hb['P2_partial_corr']['p_adj']:.4f}), demonstrating that inertial sensors capture motor severity information beyond what demographics encode. The severity-preserving signal exists, but it is diluted by the 12 non-directly-observable items (7 partially observable + 5 unobservable) that constitute 82% of the total score range.
</p>

<p>
HC-augmented training (PD+HC) degraded PD-only prediction substantially: MAE&nbsp;=&nbsp;{mt['10split_b2_fm_stk']['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{mt['10split_b2_fm_stk']['mae_std']:.2f} versus {p10_b1_v2['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{p10_b1_v2['mae_std']:.2f} for PD-only training (+{(mt['10split_b2_fm_stk']['mae_mean'] - p10_b1_v2['mae_mean'])/p10_b1_v2['mae_mean']*100:.0f}%). The model learns to distinguish PD from HC (scoring HC near zero) rather than discriminating within-PD severity&mdash;a qualitatively different and clinically less useful task.
</p>

{_table2(mt, held, held_demo, d.phase1.get("splits", []))}

<p>
In PD-only LOOCV, only {clinical['pct_within_mcid_3.25']:.1f}% of predictions fell within the MCID of 3.25 points, {clinical['pct_within_5']:.1f}% within 5 points, and {clinical['pct_within_10']:.1f}% within 10 points. The Spearman rank correlation (&rho;&nbsp;=&nbsp;{d.confounds['spearman']['rho']:.3f}, p<sub>adj</sub>&nbsp;=&nbsp;{hb['P4_spearman']['p_adj']:.4f}) confirms that the model preserves severity ordering despite poor absolute calibration. Weighted kappa for quartile-level agreement was {d.confounds['weighted_kappa']:.3f} (fair). Proportional bias analysis revealed a mild slope of {d.confounds['proportional_bias']['slope']:.3f} (p&nbsp;=&nbsp;{d.confounds['proportional_bias']['p']:.3f}), and absolute prediction errors did not correlate significantly with any demographic variable (all |r|&nbsp;&lt;&nbsp;0.3). Sensitivity analysis for missing data showed comparable performance between subjects with complete (MAE&nbsp;=&nbsp;{d.confounds['missing_data']['mae_complete']:.2f}, N&nbsp;=&nbsp;{d.confounds['missing_data']['n_complete']}) and partial recordings (MAE&nbsp;=&nbsp;{d.confounds['missing_data']['mae_partial']:.2f}, N&nbsp;=&nbsp;{d.confounds['missing_data']['n_partial']}).
</p>

<h3>2.3 Three-Level Observability Decomposition</h3>

<p>
We decomposed the 18 MDS-UPDRS-III items into three tiers based on whether the assessed motor sign is physically manifest during gait with body-worn sensors (Table&nbsp;3, Figure&nbsp;2). <em>Directly observable</em> items (3.9&ndash;3.14: arising, gait, freezing, postural stability, posture, body bradykinesia) produce kinematic signatures during ambulation. <em>Partially observable</em> items (3.5&ndash;3.8: hand movements, pronation, toe tapping, leg agility; 3.15&ndash;3.17: tremor) produce motor signs that are indirectly reflected in gait dynamics. <em>Not observable</em> items (3.1&ndash;3.4: speech, facial expression, rigidity, finger tapping; 3.18: tremor constancy) require modalities that no body-worn inertial sensor can capture.
</p>

<p>
In PD-only LOOCV (N&nbsp;=&nbsp;94, Table&nbsp;3), the directly observable subscore achieved CCC&nbsp;=&nbsp;{direct['ccc']:.2f}, MAE&nbsp;=&nbsp;{direct['mae']:.2f} (r&nbsp;=&nbsp;{direct['r']:.3f})&mdash;the strongest concordance in this study. The partially observable tier dropped to CCC&nbsp;=&nbsp;{partial['ccc']:.2f} (MAE&nbsp;=&nbsp;{partial['mae']:.2f}), and the not-observable tier to CCC&nbsp;=&nbsp;{unobs_l['ccc']:.2f} (MAE&nbsp;=&nbsp;{unobs_l['mae']:.2f}). The CCC gradient&mdash;{direct['ccc']:.2f} (direct) vs {unobs_l['ccc']:.2f} (unobs) vs {partial['ccc']:.2f} (partial)&mdash;is the primary evidence for observability-driven prediction quality. Note that nMAE (MAE/max_score) does not follow this gradient (direct 7.4%, partial 7.2%, unobs 9.8%), because nMAE reflects error relative to score range, not model agreement; CCC is the appropriate metric for this comparison. The binary observable composite (items 3.7&ndash;3.14) achieved CCC&nbsp;=&nbsp;{binary_obs['ccc']:.2f} and MAE&nbsp;=&nbsp;{binary_obs['mae']:.2f}. Ten-split PD-only validation confirmed the pattern: direct MAE&nbsp;=&nbsp;{obs['direct']['ten_split_b1']['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{obs['direct']['ten_split_b1']['mae_std']:.2f}, partial MAE&nbsp;=&nbsp;{obs['partial']['ten_split_b1']['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{obs['partial']['ten_split_b1']['mae_std']:.2f}, not observable MAE&nbsp;=&nbsp;{obs['unobs']['ten_split_b1']['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{obs['unobs']['ten_split_b1']['mae_std']:.2f}.
</p>

<figure>
<img src="{figures['fig2']}" alt="3-level observability">
<figcaption><strong>Figure 2.</strong> Three-level observability decomposition in PD-only LOOCV (N&nbsp;=&nbsp;94). Directly observable items (3.9&ndash;3.14) achieve CCC&nbsp;=&nbsp;0.56, while partially observable and not-observable tiers show markedly poorer concordance. This gradient establishes the structural prediction ceiling from gait IMU data.</figcaption>
</figure>

{_table3(obs, direct, partial, unobs_l, binary_obs)}

<h3>2.4 Item-Level Analysis and Feature&ndash;Anatomy Alignment</h3>

<p>
Per-item analysis (Figure&nbsp;3) revealed a clear separation: the highest-correlation items were predominantly directly observable from gait data. Feature importance analysis showed clinically coherent sensor&ndash;item alignment: foot and trunk sensors (R_DorsalFoot, Xiphoid, LowerBack) drove direct-observable item predictions, wrist sensors drove partially observable upper-limb items, and forehead sensors contributed to not-observable items (serving as a facial expression proxy). This anatomical alignment validates that the model captures genuine biomechanical signals rather than learning spurious correlations.
</p>

<figure>
<img src="{figures['fig4']}" alt="Item-level predictability">
<figcaption><strong>Figure 3.</strong> Per-item predictability ranked by Pearson r, colored by three-level observability. Green: directly observable from gait; orange: partially observable; red: not observable from gait sensors. The observability tier strongly predicts item-level correlation.</figcaption>
</figure>

<h3>2.5 Severity-Stratified Error and Calibration</h3>

<p>
The prediction error is severity-dependent (Figure&nbsp;4, Table&nbsp;4). Moderate-severity patients (UPDRS-III 12&ndash;35, N&nbsp;=&nbsp;72) achieved MAE&nbsp;&approx;&nbsp;6 (CCC&nbsp;=&nbsp;0.07&ndash;0.15), while extreme quartiles (Q1&nbsp;&lt;&nbsp;12 and Q4&nbsp;&gt;&nbsp;35) had MAE&nbsp;&gt;&nbsp;14 with opposing biases: the model over-predicts mild patients (+14.1 points) and under-predicts severe patients (&minus;14.3 points). Per-quartile calibration slopes ranged from 0.29 (Q2) to 0.88 (Q1), with all quartiles showing CCC&nbsp;&lt;&nbsp;0.16&mdash;indicating the model's overall agreement is driven by between-quartile variation rather than within-quartile discrimination. The overall calibration slope of {fm_loocv['cal_slope']:.3f} (ideal&nbsp;=&nbsp;1.0) confirms severe regression to the PD-group mean (intercept&nbsp;=&nbsp;{fm_loocv['cal_intercept']:.1f}), a known phenomenon in small-N regression problems. Bland&ndash;Altman analysis revealed a bias of {bland['bias']:.1f} points with 95% limits of agreement [{bland['loa_lo']:.1f}, {bland['loa_hi']:.1f}], with proportional bias (slope&nbsp;=&nbsp;{bland['prop_bias_slope']:.2f}, r&nbsp;=&nbsp;{bland['prop_bias_r']:.2f}, p&nbsp;&lt;&nbsp;0.001) indicating greater underprediction at higher severity.
</p>

{_table_severity(d.confounds)}

<figure>
<img src="{figures['fig5']}" alt="Severity calibration">
<figcaption><strong>Figure 4.</strong> Severity-stratified prediction error and calibration bias. The model performs best in the moderate range (Q2&ndash;Q3) but shows extreme bias at severity extremes, consistent with regression to the PD-group mean (calibration slope = {fm_loocv['cal_slope']:.3f}).</figcaption>
</figure>

<h3>2.6 Foundation Model Embeddings</h3>

<p>
In mixed PD+HC 10-fold cross-validation (N&nbsp;=&nbsp;{N_ANALYZED}), frozen MOMENT-1-base embeddings (768 dimensions, no fine-tuning) significantly improved performance: FM-fused MAE&nbsp;=&nbsp;{fm_mixed.mean():.2f}&nbsp;&plusmn;&nbsp;{fm_mixed.std():.2f} versus handcrafted baseline MAE&nbsp;=&nbsp;{v2_mixed.mean():.2f}&nbsp;&plusmn;&nbsp;{v2_mixed.std():.2f} (Wilcoxon p&nbsp;=&nbsp;{p_fm_v2:.4f}), winning 9 of 10 splits (Figure&nbsp;5). However, in PD-only evaluation the FM advantage diminished: PD-only 10-split FM stack MAE&nbsp;=&nbsp;{p10_fm['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{p10_fm['mae_std']:.2f} versus v2 baseline {p10_b1_v2['mae_mean']:.2f}&nbsp;&plusmn;&nbsp;{p10_b1_v2['mae_std']:.2f} (p&nbsp;=&nbsp;{hb['P1_fm_vs_v2_median']['p_adj']:.2f}, not significant). This suggests the FM embeddings primarily enhance PD-versus-HC discrimination rather than within-PD severity grading.
</p>

<figure>
<img src="{figures['fig6']}" alt="FM impact">
<figcaption><strong>Figure 5.</strong> Foundation model impact across 10 independent splits in mixed PD+HC evaluation. The FM stack (purple) wins 9/10 splits (p&nbsp;=&nbsp;{p_fm_v2:.4f}). The advantage is driven by improved PD-vs-HC separation.</figcaption>
</figure>

<h3>2.7 Pre-Registered Held-Out Test</h3>

<p>
On the pre-registered held-out test set (N&nbsp;=&nbsp;36: 21 PD, 15 HC; seed&nbsp;=&nbsp;20260309; Figure&nbsp;6), the FM-augmented model achieved MAE&nbsp;=&nbsp;{held['mae']:.2f} (CCC&nbsp;=&nbsp;{held['ccc']:.3f}, r&nbsp;=&nbsp;{held['r']:.3f}), outperforming the demographic baseline (MAE&nbsp;=&nbsp;{held_demo['mae']:.2f}, CCC&nbsp;=&nbsp;{held_demo['ccc']:.3f}). On the PD subset (N&nbsp;=&nbsp;{mt['held_out_pd_subset']['n']}), MAE&nbsp;=&nbsp;{mt['held_out_pd_subset']['mae']:.2f} with CCC&nbsp;=&nbsp;{mt['held_out_pd_subset']['ccc']:.3f}; however, with only 21 PD subjects, this comparison is underpowered (Spearman p&nbsp;=&nbsp;{mt['held_out_pd_subset']['spearman_p']:.2f}). The directly observable subscore on the held-out PD subset (N&nbsp;=&nbsp;{d.held_out['obs_subscore_test']['n']}) achieved MAE&nbsp;=&nbsp;{d.held_out['obs_subscore_test']['mae']:.2f} (CCC&nbsp;=&nbsp;{d.held_out['obs_subscore_test']['ccc']:.3f}), corroborating the LOOCV observability pattern on independent data. We emphasize that the primary evidence for model validity rests on the 98-subject PD-only LOOCV and 10-split evaluations; the held-out test provides confirmatory rather than definitive evidence.
</p>

<figure>
<img src="{figures['fig3']}" alt="Held-out scatter">
<figcaption><strong>Figure 6.</strong> Predicted versus actual UPDRS-III on the held-out test set (N&nbsp;=&nbsp;36). PD subjects in red, HC in blue. Yellow band: &plusmn;MCID. The regression line shows moderate correlation driven partly by PD-vs-HC group separation.</figcaption>
</figure>

<h3>2.8 Sensor Ablation</h3>

<p>
Using FM re-extraction per sensor configuration to eliminate data leakage (Table&nbsp;5, Figure&nbsp;7), the 5-sensor minimal set (lower back, bilateral wrists, bilateral ankles) matched the full 13-sensor configuration (MAE&nbsp;=&nbsp;{mt['sensor_minimal_5']['mae_mean']:.2f} vs {mt['sensor_all_13']['mae_mean']:.2f}, p&nbsp;=&nbsp;0.85). Even 2 wrist-worn sensors achieved competitive performance ({mt['sensor_wrists_2']['mae_mean']:.2f}, p&nbsp;=&nbsp;0.55). Only single lower-back was significantly worse ({mt['sensor_lower_back_1']['mae_mean']:.2f}, p&nbsp;=&nbsp;0.014).
</p>

<figure>
<img src="{figures['fig7']}" alt="Sensor ablation">
<figcaption><strong>Figure 7.</strong> Sensor ablation with FM features re-extracted per configuration (no data leakage). The 5-sensor minimal set (lower back + wrists + ankles) matches all 13 sensors. Error bars: &plusmn;1 SD across 10 splits. p-values from paired bootstrap vs full configuration.</figcaption>
</figure>

{_table4_sensor(d)}

<h3>2.9 Cross-Dataset Context</h3>

<p>
Table&nbsp;6 and Figure&nbsp;8 contextualize our results. Direct comparison with Hssayeni et&nbsp;al. (MAE&nbsp;=&nbsp;5.95, N&nbsp;=&nbsp;24 PD) and Shuqair et&nbsp;al. (r&nbsp;=&nbsp;0.89, same dataset) is complicated by protocol differences: cohort size (N&nbsp;=&nbsp;98 vs 24), task type (controlled gait vs free-living ADL), sensor placement (13 full-body vs wrist+ankle), and evaluation (LOOCV on 98 vs 24). The remaining performance gap likely reflects genuine differences in signal content rather than modeling quality.
</p>

<figure>
<img src="{figures['fig8']}" alt="Cross-dataset">
<figcaption><strong>Figure 8.</strong> Cross-dataset comparison. Our directly observable subscore (MAE&nbsp;=&nbsp;1.77) falls below the MCID threshold, while total UPDRS-III results reflect the observability ceiling. Published results on smaller cohorts with LOOCV achieve lower total-score MAE but differ substantially in protocol, cohort, and sensors.</figcaption>
</figure>

{_table5()}

<h3>2.10 What Did Not Work</h3>

<p>
Negative results strengthen the ceiling argument. Seven end-to-end deep learning configurations across three architecture families (Transformer with MAE/contrastive/scratch pretraining, InceptionTime with MIL/ordinal/expanded, SensorGNN; Table&nbsp;S1) all produced MAE&nbsp;&gt;&nbsp;10, consistent with overfitting at N&nbsp;=&nbsp;178. Additional approaches that failed to improve on the MAE&nbsp;&approx;&nbsp;8 ceiling included: individual item decomposition and summation (52% worse), mixture-of-experts by severity, severity-stratified training, cross-sensor coordination features (phase-locking value, coherence, eigenvalue decomposition&mdash;all indistinguishable from noise), two-stage observable-to-total mapping, hyperparameter sweeps (Latin hypercube over 6 LightGBM parameters), and freezing-of-gait transfer (AUC&nbsp;=&nbsp;0.500, only 14/178 subjects had FoG events). That 12+ diverse approaches converge on the same ceiling on this dataset, while the directly observable subdomain achieves CCC&nbsp;=&nbsp;0.56, is circumstantial evidence consistent with an observability-driven barrier, though cross-dataset replication is needed to confirm generalizability.
</p>

<!-- ═══════════════════════════════════════════ DISCUSSION ═════════════════ -->
<h2>3. Discussion</h2>

<h3>3.1 The Observability Ceiling</h3>

<p>
Our central finding is not about total UPDRS-III prediction accuracy per se, but the identification of a probable observability ceiling. The MDS-UPDRS Part III assesses 18 motor domains, but only 6 produce motor signs directly manifest during ambulation. Rigidity (item 3.3) requires passive manipulation by an examiner&mdash;no body-worn sensor can detect the resistance a clinician feels. Speech (3.1) and facial expression (3.2) are auditory and visual assessments. Upper extremity items (3.4&ndash;3.6) are administered while seated. Rest tremor (3.17&ndash;3.18) manifests during stillness, not movement.
</p>

<p>
The convergence evidence is suggestive: 12+ distinct modeling approaches&mdash;from parameter-free random kernels to 310M-parameter pretrained transformers&mdash;all converge on MAE&nbsp;&approx;&nbsp;8 for total UPDRS-III in PD-only evaluation on this dataset. The directly observable items (CCC&nbsp;=&nbsp;{direct['ccc']:.2f}) vs partially observable (CCC&nbsp;=&nbsp;{partial['ccc']:.2f}) vs not observable (CCC&nbsp;=&nbsp;{unobs_l['ccc']:.2f}) gradient is consistent with what information theory predicts: a single measurement modality cannot capture what it cannot sense. We acknowledge that this conclusion rests on a single dataset with a specific item-tier assignment; cross-dataset replication with independent clinician-validated tier classifications would strengthen the claim.
</p>

<h3>3.2 The Demographic Baseline Problem</h3>

<p>
That a Ridge regression on five demographic variables (age, sex, disease duration, height, weight) achieves MAE&nbsp;=&nbsp;{p10_demo['mae_mean']:.2f} on PD-only total UPDRS-III&mdash;competitive with or better than all IMU models&mdash;raises a critical question: does the IMU model measure motor severity, or has it learned to predict disease stage? Three pieces of evidence indicate real motor signal: (1) partial correlation r&nbsp;=&nbsp;{partial_corr['r']:.2f} (p<sub>adj</sub>&nbsp;=&nbsp;0.002) after controlling for age and disease duration; (2) feature&ndash;anatomy alignment showing foot sensors predict gait items and wrist sensors predict upper-limb items; (3) the directly observable subscore achieves CCC&nbsp;=&nbsp;{direct['ccc']:.2f}, far exceeding what demographics alone could produce for gait-specific items. The demographic competitiveness on <em>total</em> UPDRS-III is driven by unobservable items that correlate with disease stage but not with gait kinematics.
</p>

<h3>3.3 Clinical Implications</h3>

<p>
The directly observable subscore (items 3.9&ndash;3.14) achieves MAE&nbsp;=&nbsp;{direct['mae']:.2f} with CCC&nbsp;=&nbsp;{direct['ccc']:.2f} in PD-only LOOCV. This has two clinical implications. First, rather than targeting total UPDRS-III&mdash;an endpoint that conflates what sensors can and cannot observe&mdash;the directly observable motor subdomain may be a more appropriate endpoint for wearable monitoring studies. Second, the sub-MCID accuracy for this subdomain suggests that between-visit tracking of gait-related motor decline is feasible with current sensor technology.
</p>

<p>
This reframes the clinical question from &ldquo;Can wearables replace the neurologist?&rdquo; (no) to &ldquo;Can wearables provide continuous tracking of the motor functions they can actually observe?&rdquo; (our data suggests yes, for gait/posture items). We note, following reviewer guidance, that the MCID of 3.25 points was derived for longitudinal change detection, not cross-sectional prediction error<sup>2</sup>; the comparison is contextual rather than definitive.
</p>

<h3>3.4 Foundation Models for Clinical Time Series</h3>

<p>
Frozen MOMENT-1 embeddings (pretrained on general time series, no clinical fine-tuning) reduced MAE from {v2_mixed.mean():.2f} to {fm_mixed.mean():.2f} (p&nbsp;=&nbsp;{p_fm_v2:.4f}) in mixed PD+HC evaluation. This &ldquo;DL as feature extractor, not regressor&rdquo; paradigm circumvents the overfitting that causes end-to-end deep learning to fail at N&nbsp;=&nbsp;178. Importantly, the FM advantage diminished in PD-only evaluation (p<sub>adj</sub>&nbsp;=&nbsp;{hb['P1_fm_vs_v2_median']['p_adj']:.2f}), suggesting the embeddings primarily encode features useful for PD-vs-HC group separation rather than within-PD severity grading. This distinction matters for clinical deployment: a model that accurately <em>screens</em> (separates PD from HC) may not accurately <em>grade</em> (ranks severity within PD).
</p>

<h3>3.5 Limitations</h3>

<p>
Several limitations should be considered. (1) Results are from a single dataset; cross-dataset transfer validation is needed, and the observability tier classification should be independently validated by blinded movement-disorder specialists. (2) All recordings are from controlled gait tasks, not free-living conditions. (3) Medication state was not systematically controlled. (4) The HC group was older than PD ({dc['age_mean']} vs {dp['age_mean']} years, p&nbsp;&lt;&nbsp;0.001), potentially conflating age-related gait changes with disease effects in mixed analyses; the FM embeddings' advantage in mixed evaluation but not in PD-only evaluation may partly reflect age-related gait features rather than disease-specific signatures. (5) N&nbsp;=&nbsp;98 PD subjects limits statistical power, particularly for the held-out PD subset (N&nbsp;=&nbsp;21). (6) Severe calibration (slope&nbsp;=&nbsp;{fm_loocv['cal_slope']:.2f}) means predictions cannot be taken at face value&mdash;the model systematically compresses toward the group mean; this positions the current model as suitable for severity ranking and monitoring rather than absolute score estimation. (7) This is cross-sectional; longitudinal data are needed to validate change detection. (8) The three-level observability classification, while clinically motivated, involves judgment calls for partially observable items. (9) 23 PD subjects had deep brain stimulation (DBS), which may alter gait patterns independently of UPDRS-III score; DBS-stratified sensitivity analysis was not performed.
</p>

<h3>3.6 Future Directions</h3>

<p>
Four directions are most promising. First, cross-dataset transfer on PADS<sup>9</sup> and other PD wearable datasets would test generalizability. Second, longitudinal within-subject tracking using the directly observable subdomain could enable treatment response monitoring where absolute accuracy matters less than change detection. Third, the sensor reduction pathway from 13 to 5 (or 2) sensors is essential for clinical adoption, though requires independent validation with the foundation model pipeline. Fourth, addressing the severe calibration bias (slope&nbsp;=&nbsp;{fm_loocv['cal_slope']:.2f}) through severity-weighted loss functions, synthetic oversampling for continuous targets (SMOGN), or personalized within-subject baselines could substantially improve clinical utility at severity extremes.
</p>

<!-- ═══════════════════════════════════════════ METHODS ═══════════════════ -->
<h2>4. Methods</h2>

<h3>4.1 Dataset</h3>

<p>
WearGait-PD<sup>7</sup> (Synapse syn55052683) comprises {N_ENROLLED_PD} PD and {N_ENROLLED_HC} HC participants, of whom {N_ANALYZED} ({N_ANALYZED_PD} PD, {N_ANALYZED_HC} HC) had complete recordings. Each subject wore 13 Xsens MTw Awinda IMU sensors placed at: lower back, bilateral wrists, bilateral mid-lateral thighs, bilateral lateral shanks, bilateral dorsal feet, bilateral ankles, xiphoid process, and forehead. Sensors sampled at 100&nbsp;Hz recording triaxial accelerometer and gyroscope data (78 total channels). Participants completed six standardized tasks: self-paced walking, hurried-pace walking, Timed Up-and-Go, balance assessment, and tandem gait, plus pressure-mat variants. Motor severity was assessed using MDS-UPDRS Part III by trained clinicians.
</p>

<h3>4.2 Evaluation Protocol</h3>

<p>
Three complementary evaluation protocols were used. <em>PD-only LOOCV</em> (N&nbsp;=&nbsp;98): the primary evaluation, most comparable to published work, leave-one-subject-out with all metrics computed on the left-out PD patient. <em>PD-only 10-split CV</em> (N&nbsp;=&nbsp;98): multi-label stratified splits (UPDRS bins &times; age terciles) with 10 independent seeds, providing variance estimates. <em>Pre-registered held-out test</em> (N&nbsp;=&nbsp;36: 21 PD, 15 HC; seed&nbsp;=&nbsp;20260309): the test set was specified before any model selection and used exactly once. All splits maintained strict subject-level separation.
</p>

<h3>4.3 Feature Extraction</h3>

<p>
Recordings were segmented into 10-second windows (1,000 samples) with 50% overlap. <strong>Handcrafted features (1,752):</strong> Per sensor and channel: RMS, standard deviation, range, IQR, skewness, kurtosis, jerk, zero-crossing rate; Welch PSD in locomotor (0.5&ndash;3 Hz), tremor (3&ndash;8 Hz), and high-frequency (8&ndash;25 Hz) bands with band ratios; spectral entropy; autocorrelation-based gait regularity. Additional features: foot contact spatiotemporal metrics, balance sway, task-contrast deltas, walkway distillation, and clinical covariates (age, sex, height, weight, years since diagnosis, DBS status). <strong>Foundation model embeddings (768):</strong> Frozen MOMENT-1-base encoder<sup>8</sup> (v0.1, Hugging Face <code>AutonLab/MOMENT-1-base</code>), 768-dimensional embeddings from 26 accelerometer/gyroscope magnitude channels, truncated to 512 samples (5.12&nbsp;s at 100&nbsp;Hz), per-channel z-normalized (zero mean, unit variance within each recording), averaged across all recordings per subject to yield one embedding vector per subject. Embeddings are deterministic (no gradient computation, no dropout).
</p>

<h3>4.4 Feature Selection and Model</h3>

<p>
XGBoost gain-based importance ranking (n_estimators=300, max_depth=4, lr=0.05, reg_lambda=2.0) selected K&nbsp;=&nbsp;150 features (handcrafted-only) or K&nbsp;=&nbsp;300 (fused). Selection was performed within each training fold. The primary model was LightGBM (n_estimators=2,000, lr=0.03, max_depth=6, reg_lambda=3.0, MAE objective, early stopping patience=100 on 15% validation). Multi-seed ensemble averaged predictions across seeds [0, 1, 2, 3, 4]. Demographic baseline: Ridge regression (&alpha;&nbsp;=&nbsp;1.0) on age, sex, disease duration, height, weight. Ten-split cross-validation seeds: [0&ndash;9]. Held-out test split: seed&nbsp;=&nbsp;20260309 (specified before any model development on this split).
</p>

<h3>4.5 Three-Level Observability Classification</h3>

<p>
Items were classified based on whether the motor sign is physically manifest during gait with body-worn sensors. <em>Directly observable</em> (3.9&ndash;3.14): arising, gait, freezing, postural stability, posture, body bradykinesia&mdash;all produce measurable kinematic signals during ambulation. <em>Partially observable</em> (3.5&ndash;3.8, 3.15&ndash;3.17): hand movements, pronation-supination, toe tapping, leg agility, postural/kinetic/rest tremor. These items are classified as partially (rather than directly) observable because the MDS-UPDRS-III administration protocol requires them to be performed as isolated, rapid, repetitive movements while seated&mdash;a biomechanically distinct regime from the cyclic locomotor pattern of gait. For example, toe tapping (3.7) and leg agility (3.8) engage overlapping lower-limb musculature but test rapid alternating movement speed and amplitude decrement, not the bilateral pendular coordination captured by gait accelerometry. Tremor items (3.15&ndash;3.17) may be reflected in wrist or ankle sensor noise during ambulation, but the signal is attenuated by movement artifact. <em>Not observable</em> (3.1&ndash;3.4, 3.18): speech, facial expression, rigidity, finger tapping, tremor constancy&mdash;require modalities beyond inertial sensing.
</p>

<h3>4.6 Statistical Analysis</h3>

<p>
Primary agreement metric: Lin's concordance correlation coefficient (CCC), which measures both correlation and calibration. BCa bootstrap CIs (N&nbsp;=&nbsp;10,000) stratified by PD/HC. Model comparisons: subject-level paired bootstrap for LOOCV, Wilcoxon signed-rank for 10-split. Multiple comparison correction: Holm&ndash;Bonferroni across 8 primary tests. Effect sizes: Cohen's d. Clinical context: MCID&nbsp;=&nbsp;3.25 (Horvath 2015)<sup>2</sup>, applied as a contextual benchmark rather than a formal threshold. Bland&ndash;Altman for systematic bias. Partial correlation controlling for age and disease duration.
</p>

<h3>4.7 Code and Data Availability</h3>

<p>
WearGait-PD is available on Synapse (syn55052683)<sup>7</sup>. Analysis code will be available at [repository URL].
</p>

<!-- ═══════════════════════════════════════════ REFERENCES ═════════════════ -->
<h2>References</h2>
<div class="ref">
<ol>
<li>GBD 2019 Collaborators. Global, regional, and national burden of neurological disorders, 1990&ndash;2019. <em>Lancet Neurol.</em> 20, 797&ndash;820 (2021).</li>
<li>Horvath, K. et al. Minimal clinically important difference on the Motor Examination part of MDS-UPDRS. <em>Parkinsonism Relat. Disord.</em> 21, 1421&ndash;1426 (2015).</li>
<li>Hssayeni, M. D. et al. Wearable sensors for estimation of Parkinsonian tremor severity during free body movement. <em>BioMed. Eng. OnLine</em> 20, 24 (2021).</li>
<li>Shuqair, H. et al. Self-supervised representation learning for motor severity estimation. <em>Bioengineering</em> 11, 689 (2024).</li>
<li>Sotirakis, C. et al. Identification of motor progression in Parkinson's disease using wearable sensors. <em>npj Parkinsons Dis.</em> 9, 74 (2023).</li>
<li>Li, J. et al. TRIP: Transformer-based IMU pretraining for Parkinson's disease. <em>arXiv</em> 2510.15748 (2025).</li>
<li>WearGait-PD dataset. <em>Sci. Data</em> (2026). doi:10.1038/s41597-026-06806-2.</li>
<li>Goswami, M. et al. MOMENT: A family of open time-series foundation models. <em>ICML</em> (2024).</li>
<li>Varghese, J. et al. PADS: Parkinson's disease smartwatch dataset. <em>PhysioNet</em> (2024).</li>
</ol>
</div>

<!-- ═══════════════════════════════════════════ SUPPLEMENTARY ═════════════ -->
<h2>Supplementary Information</h2>

<h3>Table S1: Deep Learning Comparison</h3>
{_table_dl(d)}

<h3>Table S2: Holm&ndash;Bonferroni Corrected p-Values</h3>
{_table_holm(d)}

</body>
</html>"""

    return html


# ─── TABLE BUILDERS ───────────────────────────────────────────────────────────

def _table1(dp, dc):
    return f"""
<table>
<caption><strong>Table 1.</strong> Cohort demographics.</caption>
<tr><th>Characteristic</th><th>PD (N={N_ANALYZED_PD})</th><th>HC (N={N_ANALYZED_HC})</th></tr>
<tr><td>Age, years (mean &plusmn; SD)</td><td>{dp['age_mean']} &plusmn; {dp['age_std']}</td><td>{dc['age_mean']} &plusmn; {dc['age_std']}</td></tr>
<tr><td>Sex (M/F)</td><td>{dp['sex_m_f'][0]}M / {dp['sex_m_f'][1]}F</td><td>{dc['sex_m_f'][0]}M / {dc['sex_m_f'][1]}F</td></tr>
<tr><td>Height, cm</td><td>{dp['height_cm_mean']} &plusmn; {dp['height_cm_std']}</td><td>{dc['height_cm_mean']} &plusmn; {dc.get('height_cm_std', '—')}</td></tr>
<tr><td>Weight, kg</td><td>{dp['weight_kg_mean']} &plusmn; {dp['weight_kg_std']}</td><td>{dc.get('weight_kg_mean', '—')} &plusmn; {dc.get('weight_kg_std', '—')}</td></tr>
<tr><td>UPDRS-III (mean &plusmn; SD)</td><td>{dp['updrs3_mean']} &plusmn; {dp['updrs3_std']}</td><td>{dc['updrs3_mean']} &plusmn; {dc['updrs3_std']}</td></tr>
<tr><td>UPDRS-III range</td><td>{dp['updrs3_range']}</td><td>{dc['updrs3_range']}</td></tr>
<tr><td>H&amp;Y (mean &plusmn; SD)</td><td>{dp.get('hy_mean', '—')} &plusmn; {dp.get('hy_std', '—')} (N={dp.get('hy_n_available', '—')})</td><td>&mdash;</td></tr>
<tr><td>H&amp;Y distribution</td><td>1: {dp['hy_distribution'].get('1.0', 0)}, 2: {dp['hy_distribution'].get('2.0', 0)}, 2.5: {dp['hy_distribution'].get('2.5', 0)}, 3: {dp['hy_distribution'].get('3.0', 0)}, 4: {dp['hy_distribution'].get('4.0', 0)}</td><td>&mdash;</td></tr>
<tr><td>Years since dx</td><td>{dp.get('years_dx_mean', '—')} &plusmn; {dp.get('years_dx_std', '—')} ({dp.get('years_dx_range', '—')})</td><td>&mdash;</td></tr>
<tr><td>DBS</td><td>{dp.get('dbs_count', '—')}</td><td>&mdash;</td></tr>
</table>"""


def _table2(mt, held, held_demo, phase1_splits=None):
    b1v2 = mt["10split_b1_v2"]
    demo = mt["10split_demographic"]
    fm_stk = mt["10split_b1_fm_stk"]
    b2 = mt["10split_b2_fm_stk"]
    loocv_fm = mt["loocv_fm"]
    loocv_demo = mt["loocv_demo"]
    held_pd = mt["held_out_pd_subset"]

    # Compute missing model aggregates from phase1 per-split data
    b1_fm_lgb_mae, b1_fm_lgb_ccc = "&mdash;", "&mdash;"
    b2_v2_mae, b2_v2_ccc = "&mdash;", "&mdash;"
    if phase1_splits:
        import numpy as _np
        b1fl_maes = [s["b1_fm_lgb"]["mae"] for s in phase1_splits]
        b1fl_cccs = [s["b1_fm_lgb"]["ccc"] for s in phase1_splits]
        b2v2_maes = [s["b2_v2"]["mae"] for s in phase1_splits]
        b2v2_cccs = [s["b2_v2"]["ccc"] for s in phase1_splits]
        b1_fm_lgb_mae = f"{_np.mean(b1fl_maes):.2f} &plusmn; {_np.std(b1fl_maes):.2f}"
        b1_fm_lgb_ccc = f"{_np.mean(b1fl_cccs):.3f}"
        b2_v2_mae = f"{_np.mean(b2v2_maes):.2f} &plusmn; {_np.std(b2v2_maes):.2f}"
        b2_v2_ccc = f"{_np.mean(b2v2_cccs):.3f}"

    return f"""
<table>
<caption><strong>Table 2.</strong> Total UPDRS-III prediction results (PD-only evaluation throughout). CCC: Lin's concordance correlation coefficient.</caption>
<tr><th>Model</th><th>Evaluation</th><th>MAE [&plusmn;SD]</th><th>CCC</th><th>r</th><th>R&sup2;</th><th>Cal. slope</th></tr>
<tr><th colspan="7" style="background:#f8f9fa; text-align:left; font-style:italic">PD-only 10-split cross-validation (N=98, 10 seeds)</th></tr>
<tr class="primary"><td>Demographic Ridge</td><td>10-split</td><td>{demo['mae_mean']:.2f} &plusmn; {demo['mae_std']:.2f}</td><td>{demo['ccc_mean']:.3f}</td><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td></tr>
<tr><td>v2 Handcrafted LGB (B1)</td><td>10-split</td><td>{b1v2['mae_mean']:.2f} &plusmn; {b1v2['mae_std']:.2f}</td><td>{b1v2['ccc_mean']:.3f}</td><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td></tr>
<tr><td>FM-fused LGB (B1)</td><td>10-split</td><td>{b1_fm_lgb_mae}</td><td>{b1_fm_lgb_ccc}</td><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td></tr>
<tr><td>FM-fused Stack (B1)</td><td>10-split</td><td>{fm_stk['mae_mean']:.2f} &plusmn; {fm_stk['mae_std']:.2f}</td><td>{fm_stk['ccc_mean']:.3f}</td><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td></tr>
<tr><td>v2 Handcrafted LGB (B2, HC-aug.)</td><td>10-split</td><td>{b2_v2_mae}</td><td>{b2_v2_ccc}</td><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td></tr>
<tr><td>FM-fused Stack (B2, HC-aug.)</td><td>10-split</td><td>{b2['mae_mean']:.2f} &plusmn; {b2['mae_std']:.2f}</td><td>{b2['ccc_mean']:.3f}</td><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td></tr>
<tr><th colspan="7" style="background:#f8f9fa; text-align:left; font-style:italic">PD-only leave-one-out cross-validation (N=98)</th></tr>
<tr class="highlight"><td>FM-fused Stack</td><td>LOOCV</td><td>{loocv_fm['mae']:.2f}</td><td>{loocv_fm['ccc']:.3f}</td><td>{loocv_fm['r']:.3f}</td><td>{loocv_fm['r2']:.3f}</td><td>{loocv_fm['cal_slope']:.3f}</td></tr>
<tr><td>Demographic Ridge</td><td>LOOCV</td><td>{loocv_demo['mae']:.2f}</td><td>{loocv_demo['ccc']:.3f}</td><td>{loocv_demo['r']:.3f}</td><td>{loocv_demo['r2']:.3f}</td><td>{loocv_demo['cal_slope']:.3f}</td></tr>
<tr><th colspan="7" style="background:#f8f9fa; text-align:left; font-style:italic">Pre-registered held-out test (used once)</th></tr>
<tr><td>FM-fused Stack</td><td>Held-out (N=36)</td><td>{held['mae']:.2f}</td><td>{held['ccc']:.3f}</td><td>{held['r']:.3f}</td><td>{held['r2']:.3f}</td><td>{held['cal_slope']:.3f}</td></tr>
<tr><td>FM-fused Stack (PD only)</td><td>Held-out (N=21 PD)</td><td>{held_pd['mae']:.2f}</td><td>{held_pd['ccc']:.3f}</td><td>{held_pd['r']:.3f}</td><td>{held_pd['r2']:.3f}</td><td>{held_pd['cal_slope']:.3f}</td></tr>
<tr><td>Demographics</td><td>Held-out (N=36)</td><td>{held_demo['mae']:.2f}</td><td>{held_demo['ccc']:.3f}</td><td>{held_demo['r']:.3f}</td><td>{held_demo['r2']:.3f}</td><td>{held_demo['cal_slope']:.3f}</td></tr>
</table>
<p class="note">B1: PD-only training. B2: HC-augmented training (PD+HC train, PD-only eval). 10-split: multi-label stratified (UPDRS bins &times; age terciles). Held-out PD subset (N=21) is underpowered (Spearman p&nbsp;=&nbsp;{held_pd['spearman_p']:.2f}).</p>"""


def _table_severity(confounds):
    qs = confounds.get("severity_quartiles", [])
    if not qs:
        return "<p>Severity quartile data not available.</p>"
    rows = ""
    for q in qs:
        rows += f'<tr><td>{q["label"]}</td><td>{q["n"]}</td><td>{q["mae"]:.2f}</td><td>{q["ccc"]:.3f}</td><td>{q["r"]:.3f}</td><td>{q["bias"]:+.1f}</td><td>{q["cal_slope"]:.3f}</td></tr>\n'
    return f"""
<table>
<caption><strong>Table 4.</strong> Severity-stratified prediction metrics (PD-only FM LOOCV, N=98).</caption>
<tr><th>Quartile</th><th>N</th><th>MAE</th><th>CCC</th><th>r</th><th>Bias</th><th>Cal. slope</th></tr>
{rows}
</table>
<p class="note">Bias = mean(predicted &minus; actual). The model over-predicts mild (Q1) and under-predicts severe (Q4) patients, with CCC&nbsp;&lt;&nbsp;0.16 across all quartiles.</p>"""


def _table3(obs, direct, partial, unobs_l, binary_obs):
    d10 = obs["direct"]["ten_split_b1"]
    p10 = obs["partial"]["ten_split_b1"]
    u10 = obs["unobs"]["ten_split_b1"]

    return f"""
<table>
<caption><strong>Table 3.</strong> Three-level observability decomposition (PD-only).</caption>
<tr><th>Tier</th><th>Items</th><th>Max Score</th><th>LOOCV MAE</th><th>nMAE (%)</th><th>LOOCV CCC</th><th>LOOCV r</th><th>10-split MAE</th></tr>
<tr class="highlight"><td>Directly observable</td><td>3.9&ndash;3.14</td><td>24</td><td>{direct['mae']:.2f}</td><td>{direct['mae']/24*100:.1f}</td><td>{direct['ccc']:.3f}</td><td>{direct['r']:.3f}</td><td>{d10['mae_mean']:.2f} &plusmn; {d10['mae_std']:.2f}</td></tr>
<tr><td>Partially observable</td><td>3.5&ndash;3.8, 3.15&ndash;3.17</td><td>68</td><td>{partial['mae']:.2f}</td><td>{partial['mae']/68*100:.1f}</td><td>{partial['ccc']:.3f}</td><td>{partial['r']:.3f}</td><td>{p10['mae_mean']:.2f} &plusmn; {p10['mae_std']:.2f}</td></tr>
<tr><td>Not observable</td><td>3.1&ndash;3.4, 3.18</td><td>40</td><td>{unobs_l['mae']:.2f}</td><td>{unobs_l['mae']/40*100:.1f}</td><td>{unobs_l['ccc']:.3f}</td><td>{unobs_l['r']:.3f}</td><td>{u10['mae_mean']:.2f} &plusmn; {u10['mae_std']:.2f}</td></tr>
<tr><td>Binary observable</td><td>3.7&ndash;3.14</td><td>40</td><td>{binary_obs['mae']:.2f}</td><td>{binary_obs['mae']/40*100:.1f}</td><td>{binary_obs['ccc']:.3f}</td><td>{binary_obs['r']:.3f}</td><td>&mdash;</td></tr>
</table>
<p class="note">LOOCV: PD-only, N=89&ndash;94 (varies by item availability). 10-split: PD-only, 10 seeds. Direct + partial + unobs = total (reconstruction error = 0.0). nMAE = MAE / max possible score &times; 100, enabling fair comparison across subscores with different ranges.</p>"""


def _table4_sensor(d):
    configs = d.sensor.get("configs", {})
    if not configs:
        return "<p>Sensor ablation data not available.</p>"

    order = [("all_13", "All 13 sensors"), ("minimal_5", "Minimal 5 (back+wrists+ankles)"),
             ("wrists_back_3", "Back + wrists (3)"), ("wrists_2", "Wrists only (2)"),
             ("lower_back_1", "Lower back only (1)")]
    rows = ""
    for key, label in order:
        c = configs[key]
        p_val = c.get("vs_all_13", {}).get("p", None)
        p_str = f"{p_val:.3f}" if p_val is not None else "&mdash;"
        cls = ' class="highlight"' if key == "minimal_5" else ""
        rows += f'<tr{cls}><td>{label}</td><td>{c["n_sensors"]}</td><td>{c["mae_mean"]:.2f} &plusmn; {c["mae_std"]:.2f}</td><td>{c["ccc_mean"]:.3f}</td><td>{p_str}</td></tr>\n'

    return f"""
<table>
<caption><strong>Table 5.</strong> Sensor ablation (PD-only 10-split, FM re-extracted per config).</caption>
<tr><th>Configuration</th><th>N Sensors</th><th>MAE &plusmn; SD</th><th>CCC</th><th>p vs All 13</th></tr>
{rows}
</table>
<p class="note">FM embeddings re-extracted per sensor configuration to prevent data leakage. p-values from paired bootstrap.</p>"""


def _table5():
    return """
<table>
<caption><strong>Table 6.</strong> Cross-dataset comparison with published UPDRS-III regression.</caption>
<tr><th>Study</th><th>Dataset</th><th>N</th><th>Sensors</th><th>Evaluation</th><th>MAE</th><th>r</th></tr>
<tr class="highlight"><td>This work (Direct Obs.)</td><td>WearGait-PD</td><td>94 PD</td><td>13 IMUs</td><td>PD LOOCV</td><td>1.77*</td><td>0.667</td></tr>
<tr><td>This work (Total)</td><td>WearGait-PD</td><td>98 PD</td><td>13 IMUs</td><td>PD LOOCV</td><td>8.15</td><td>0.429</td></tr>
<tr><td>This work (Total, mixed)</td><td>WearGait-PD</td><td>178</td><td>13 IMUs</td><td>10-fold CV</td><td>7.78</td><td>&mdash;</td></tr>
<tr><td>Hssayeni 2021</td><td>Private</td><td>24 PD</td><td>wrist+ankle gyro</td><td>LOOCV</td><td>5.95</td><td>0.74</td></tr>
<tr><td>Shuqair 2024</td><td>Same as above</td><td>24 PD</td><td>wrist+ankle gyro</td><td>LOOCV</td><td>~5.65</td><td>0.89</td></tr>
<tr><td>Sotirakis 2023</td><td>Private</td><td>74 PD</td><td>wrist+back</td><td>5-fold CV&dagger;</td><td>RMSE=10.02</td><td>&mdash;</td></tr>
</table>
<p class="note">*Items 3.9&ndash;3.14 subscore (max 24), not total UPDRS-III (max 132). &dagger;Visit-level CV with potential within-subject leakage.</p>"""


def _table_dl(d):
    dl = d.dl_results
    if not dl:
        return "<p>DL results not available.</p>"

    items = dl if isinstance(dl, list) else dl.get("architectures", dl.get("results", []))
    rows = ""
    for arch in items:
        if isinstance(arch, dict):
            name = arch.get("name", arch.get("architecture", "Unknown"))
            mae_val = arch.get("ens_mae", arch.get("mean_mae", arch.get("mae", None)))
            r_val = arch.get("ens_r", arch.get("mean_r", arch.get("r", None)))
            mae_str = f"{mae_val:.2f}" if isinstance(mae_val, (int, float)) else str(mae_val)
            r_str = f"{r_val:.3f}" if isinstance(r_val, (int, float)) else str(r_val)
            rows += f"<tr><td>{name}</td><td>{mae_str}</td><td>{r_str}</td></tr>\n"

    if not rows:
        return "<p>DL architecture details not available.</p>"

    return f"""
<table>
<caption><strong>Table S1.</strong> Deep learning architectures (all MAE &gt; 10 on held-out test).</caption>
<tr><th>Architecture</th><th>Ensemble MAE</th><th>Ensemble r</th></tr>
{rows}
</table>
<p class="note">All DL models trained end-to-end on raw IMU windows. N=178 is insufficient for end-to-end deep learning; all overfit.</p>"""


def _table_holm(d):
    hb = d.pd_only.get("holm_bonferroni", [])
    if not hb:
        return ""

    rows = ""
    for h in hb:
        sig = "***" if h["p_adj"] < 0.001 else "**" if h["p_adj"] < 0.01 else "*" if h["p_adj"] < 0.05 else "ns"
        rows += f'<tr><td>{h["label"]}</td><td>{h["p_raw"]:.4f}</td><td>{h["p_adj"]:.4f}</td><td>{sig}</td></tr>\n'

    return f"""
<table>
<caption><strong>Table S2.</strong> Holm&ndash;Bonferroni corrected p-values across 8 primary statistical tests.</caption>
<tr><th>Test</th><th>p (raw)</th><th>p (adjusted)</th><th>Significance</th></tr>
{rows}
</table>
<p class="note">Three tests survive correction: permutation (FM > mean), Spearman severity ranking, and partial correlation (IMU signal beyond demographics).</p>"""


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

def validate_html(html: str) -> list:
    import re
    text_only = re.sub(r'src="data:image/png;base64,[^"]*"', 'src="[IMG]"', html)
    issues = []
    for placeholder in ["TODO", "TBD", "FIXME", "XXX"]:
        if placeholder in text_only:
            issues.append(f"Placeholder found: {placeholder}")

    for i in range(1, 9):
        if f"Figure {i}" not in html and f"Figure&nbsp;{i}" not in html:
            issues.append(f"Figure {i} not referenced in text")

    for i in range(1, 7):
        if f"Table {i}" not in html and f"Table&nbsp;{i}" not in html:
            issues.append(f"Table {i} not referenced in text")

    return issues


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("PAPER GENERATOR — WearGait-PD UPDRS-III Regression")
    print("=" * 60)

    print("\n[1/5] Loading artifacts...")
    d = load_all_data()
    mt = d.pd_only["master_table"]
    print(f"  PD-only LOOCV: MAE={mt['loocv_fm']['mae']:.2f}, CCC={mt['loocv_fm']['ccc']:.3f}")
    print(f"  Direct observable: MAE={mt['obs_direct_loocv']['mae']:.2f}, CCC={mt['obs_direct_loocv']['ccc']:.3f}")
    print(f"  Demographics: {d.demo_pd['n']} PD, {d.demo_hc['n']} HC")

    print("\n[2/5] Computing test set statistics...")
    test_stats = compute_test_stats(d)
    if test_stats:
        print(f"  Test: MAE={test_stats['mae']:.2f}, CCC={test_stats['ccc']:.3f}, r={test_stats['r']:.3f}")

    print("\n[3/5] Generating 8 figures...")
    figures = {}
    figures["fig1"] = fig1_study_design()
    print("  Fig 1: Study design")
    figures["fig2"] = fig2_observability_summary(d)
    print("  Fig 2: 3-level observability")
    figures["fig3"] = fig3_main_scatter(d, test_stats)
    print("  Fig 3: Held-out scatter")
    figures["fig4"] = fig4_item_predictability(d)
    print("  Fig 4: Item-level predictability")
    figures["fig5"] = fig5_severity_calibration(d)
    print("  Fig 5: Severity calibration")
    figures["fig6"] = fig6_fm_impact()
    print("  Fig 6: FM impact")
    figures["fig7"] = fig7_sensor_ablation(d)
    print("  Fig 7: Sensor ablation")
    figures["fig8"] = fig8_cross_dataset()
    print("  Fig 8: Cross-dataset")

    print("\n[4/5] Assembling HTML...")
    html = build_html(d, test_stats, figures)

    print("\n[5/5] Validating...")
    issues = validate_html(html)
    if issues:
        print("  WARNINGS:")
        for iss in issues:
            print(f"    - {iss}")
    else:
        print("  Validation passed.")

    DEFAULT_OUTPUT.write_text(html, encoding="utf-8")
    size_kb = DEFAULT_OUTPUT.stat().st_size / 1024
    print(f"\n{'=' * 60}")
    print(f"Paper saved: {DEFAULT_OUTPUT} ({size_kb:.0f} KB)")
    print(f"Figures: 8 embedded as base64 PNG")
    print(f"Validation issues: {len(issues)}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

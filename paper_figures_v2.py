#!/usr/bin/env python3
"""
Generate publication-quality figures for PD-IMU UPDRS-III prediction paper.

Reads results from JSON files and produces 6 matplotlib figures as base64 PNG
strings, saved to results/paper_figures_v2.json.

Self-contained: only uses json, numpy, matplotlib, base64, io.
"""

import json
import base64
import io
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from scipy import stats as sp_stats

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

SUBDOMAIN_PATH = RESULTS / "subdomain_v3_results.json"
STATS_PATH = RESULTS / "stats_report.json"
FOLLOWUP_PATH = RESULTS / "followup_v3_results.json"
OUTPUT_PATH = RESULTS / "paper_figures_v2.json"

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
C_PD = "#c0392b"
C_HC = "#2980b9"
C_OBS = "#27ae60"
C_UNOBS = "#c0392b"
C_MIXED = "#2980b9"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    """Load a JSON file, fail fast if missing."""
    if not path.exists():
        print(f"FATAL: {path} not found", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def classify_group(sid: str) -> str:
    """Classify a subject ID as PD or HC based on naming convention.

    NLS* and WPD* are PD patients.
    HC* and WHC* are healthy controls.
    """
    if sid.startswith("NLS") or sid.startswith("WPD"):
        return "PD"
    if sid.startswith("HC") or sid.startswith("WHC"):
        return "HC"
    raise ValueError(f"Cannot classify subject ID: {sid}")


def fig_to_base64(fig: plt.Figure, dpi: int = 150) -> str:
    """Render a matplotlib figure to a base64 data URI string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    size_kb = len(b64) * 3 / 4 / 1024  # approximate decoded size
    plt.close(fig)
    return f"data:image/png;base64,{b64}", size_kb


def apply_style():
    """Set up clean academic matplotlib style."""
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.color": "#cccccc",
        "axes.edgecolor": "#333333",
        "axes.labelcolor": "#333333",
        "xtick.color": "#333333",
        "ytick.color": "#333333",
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.labelsize": 12,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
    })


# ---------------------------------------------------------------------------
# Load all data once
# ---------------------------------------------------------------------------

subdomain_data = load_json(SUBDOMAIN_PATH)
stats_data = load_json(STATS_PATH)
followup_data = load_json(FOLLOWUP_PATH)

apply_style()

# ---------------------------------------------------------------------------
# Figure 1: Predicted vs Actual — Observable Gait Subdomain
# ---------------------------------------------------------------------------

def make_fig1() -> tuple:
    """Scatter plot: observable gait subdomain predictions vs actual."""
    obs_gait = None
    for c in subdomain_data["composites"]:
        if c["subdomain"] == "observable_gait":
            obs_gait = c
            break
    if obs_gait is None:
        raise RuntimeError("observable_gait composite not found in subdomain data")

    y_true = np.array(obs_gait["test_true"])
    y_pred = np.array(obs_gait["test_pred"])
    sids = obs_gait["test_sids"]
    groups = [classify_group(s) for s in sids]

    mae = obs_gait["ens_mae"]
    r_val = obs_gait["ens_r"]

    fig, ax = plt.subplots(figsize=(7, 6))

    # Scatter by group
    for grp, colour, label in [("PD", C_PD, "PD"), ("HC", C_HC, "HC")]:
        mask = np.array([g == grp for g in groups])
        ax.scatter(y_true[mask], y_pred[mask], c=colour, s=60, alpha=0.7,
                   edgecolors="white", linewidths=0.5, label=label, zorder=3)

    # Identity line
    lo = min(y_true.min(), y_pred.min()) - 1
    hi = max(y_true.max(), y_pred.max()) + 1
    ax.plot([lo, hi], [lo, hi], "--", color="#888888", linewidth=1, label="y = x", zorder=1)

    # Regression line
    slope, intercept, _, _, _ = sp_stats.linregress(y_true, y_pred)
    x_line = np.linspace(lo, hi, 100)
    ax.plot(x_line, slope * x_line + intercept, "-", color="#e67e22", linewidth=2,
            label="Regression fit", zorder=2)

    ax.set_xlabel("Actual Score")
    ax.set_ylabel("Predicted Score")
    ax.set_title("Observable Gait Subdomain (Items 7\u201314)")
    ax.legend(loc="upper left", framealpha=0.9)

    # Annotation box
    textstr = f"r = {r_val:.3f}\nMAE = {mae:.2f}"
    ax.text(0.97, 0.05, textstr, transform=ax.transAxes, fontsize=11,
            verticalalignment="bottom", horizontalalignment="right",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="#cccccc", alpha=0.9))

    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal", adjustable="box")

    return fig_to_base64(fig)


# ---------------------------------------------------------------------------
# Figure 2: Predicted vs Actual — Total UPDRS-III
# ---------------------------------------------------------------------------

def make_fig2() -> tuple:
    """Scatter plot: total UPDRS-III predictions vs actual."""
    meta = stats_data["meta"]
    y_true = np.array(meta["test_true"])
    y_pred = np.array(stats_data["model_predictions"]["stack"]["ens_pred"])
    groups = meta["test_groups"]

    mae = stats_data["model_predictions"]["stack"]["ens_mae"]
    r_val = stats_data["model_predictions"]["stack"]["ens_r"]

    fig, ax = plt.subplots(figsize=(7, 6))

    for grp, colour, label in [("PD", C_PD, "PD"), ("HC", C_HC, "HC")]:
        mask = np.array([g == grp for g in groups])
        ax.scatter(y_true[mask], y_pred[mask], c=colour, s=60, alpha=0.7,
                   edgecolors="white", linewidths=0.5, label=label, zorder=3)

    lo = min(y_true.min(), y_pred.min()) - 2
    hi = max(y_true.max(), y_pred.max()) + 2
    ax.plot([lo, hi], [lo, hi], "--", color="#888888", linewidth=1, label="y = x", zorder=1)

    slope, intercept, _, _, _ = sp_stats.linregress(y_true, y_pred)
    x_line = np.linspace(lo, hi, 100)
    ax.plot(x_line, slope * x_line + intercept, "-", color="#e67e22", linewidth=2,
            label="Regression fit", zorder=2)

    ax.set_xlabel("Actual UPDRS-III Score")
    ax.set_ylabel("Predicted UPDRS-III Score")
    ax.set_title("Total UPDRS-III (IMU-Only)")
    ax.legend(loc="upper left", framealpha=0.9)

    textstr = f"r = {r_val:.3f}\nMAE = {mae:.2f}"
    ax.text(0.97, 0.05, textstr, transform=ax.transAxes, fontsize=11,
            verticalalignment="bottom", horizontalalignment="right",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="#cccccc", alpha=0.9))

    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal", adjustable="box")

    return fig_to_base64(fig)


# ---------------------------------------------------------------------------
# Figure 3: Individual Item r-value Lollipop Chart
# ---------------------------------------------------------------------------

ITEM_NAMES = {
    1: "Speech",
    2: "Facial Expression",
    3: "Rigidity",
    4: "Finger Tapping",
    5: "Hand Movements",
    6: "Pronation-Supination",
    7: "Toe Tapping",
    8: "Leg Agility",
    9: "Arising from Chair",
    10: "Gait",
    11: "Freezing of Gait",
    12: "Postural Stability",
    13: "Posture",
    14: "Body Bradykinesia",
    15: "Postural Tremor",
    16: "Kinetic Tremor",
    17: "Rest Tremor Amplitude",
    18: "Constancy of Tremor",
}


def make_fig3() -> tuple:
    """Horizontal lollipop chart of individual item r-values."""
    items = subdomain_data["individual"]

    # Sort by r descending
    items_sorted = sorted(items, key=lambda x: x["ens_r"], reverse=True)

    labels = []
    r_vals = []
    colours = []
    for item in items_sorted:
        item_num = item["items"][0]
        name = ITEM_NAMES.get(item_num, item["subdomain"].replace("_", " ").title())
        labels.append(f"Item {item_num}: {name}")
        r_vals.append(item["ens_r"])
        colours.append(C_OBS if item["observability"] == "OBSERVABLE" else C_UNOBS)

    y_pos = np.arange(len(labels))
    r_arr = np.array(r_vals)

    fig, ax = plt.subplots(figsize=(8, 8))

    # Stems
    for i, (r, colour) in enumerate(zip(r_vals, colours)):
        ax.plot([0, r], [i, i], color=colour, linewidth=1.8, zorder=2)
    # Dots
    ax.scatter(r_arr, y_pos, c=colours, s=80, zorder=3, edgecolors="white", linewidths=0.5)

    # Vertical dashed line at r=0
    ax.axvline(x=0, color="#888888", linestyle="--", linewidth=1, zorder=1)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("Pearson r")
    ax.set_title("Individual UPDRS-III Item Prediction Accuracy")

    # Legend
    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_OBS, markersize=10,
               label="Observable"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=C_UNOBS, markersize=10,
               label="Unobservable"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", framealpha=0.9)

    ax.set_xlim(-0.1, max(r_vals) + 0.1)

    return fig_to_base64(fig)


# ---------------------------------------------------------------------------
# Figure 4: Composite Subdomain MAE Comparison
# ---------------------------------------------------------------------------

def make_fig4() -> tuple:
    """Horizontal bar chart of composite subdomain MAE values."""
    composites = subdomain_data["composites"]

    # Sort by MAE ascending
    composites_sorted = sorted(composites, key=lambda x: x["ens_mae"])

    labels = []
    maes = []
    colours = []
    for c in composites_sorted:
        name = c["subdomain"].replace("_", " ").title()
        labels.append(name)
        maes.append(c["ens_mae"])
        obs = c["observability"]
        if obs == "OBSERVABLE":
            colours.append(C_OBS)
        elif obs == "UNOBSERVABLE":
            colours.append(C_UNOBS)
        else:
            colours.append(C_MIXED)

    y_pos = np.arange(len(labels))
    mae_arr = np.array(maes)

    fig, ax = plt.subplots(figsize=(8, 5))

    bars = ax.barh(y_pos, mae_arr, color=colours, height=0.6, edgecolor="white",
                   linewidth=0.5, zorder=2)

    # MAE value labels at end of bars
    for i, (bar, mae) in enumerate(zip(bars, maes)):
        ax.text(bar.get_width() + 0.08, bar.get_y() + bar.get_height() / 2,
                f"{mae:.2f}", va="center", ha="left", fontsize=10, color="#333333")

    # MCID line
    ax.axvline(x=3.25, color="#e74c3c", linestyle="--", linewidth=1.5,
               label="MCID (3.25)", zorder=1)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("Mean Absolute Error (MAE)")
    ax.set_title("Composite Subdomain Prediction Error")

    # Legend
    legend_elements = [
        Line2D([0], [0], marker="s", color="w", markerfacecolor=C_OBS, markersize=10,
               label="Observable"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor=C_UNOBS, markersize=10,
               label="Unobservable"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor=C_MIXED, markersize=10,
               label="Mixed"),
        Line2D([0], [0], color="#e74c3c", linestyle="--", linewidth=1.5,
               label="MCID (3.25)"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", framealpha=0.9)

    ax.set_xlim(0, max(maes) + 0.8)

    return fig_to_base64(fig)


# ---------------------------------------------------------------------------
# Figure 5: 10-Split MAE Distribution
# ---------------------------------------------------------------------------

def make_fig5() -> tuple:
    """Strip/jitter plot of 10-split MAE values for Stack and LGB."""
    exp1 = followup_data["exp1_stride_var_10split"]
    stk_vals = np.array(exp1["baseline_v2"]["stk"]["values"])
    lgb_vals = np.array(exp1["baseline_v2"]["lgb"]["values"])

    fig, ax = plt.subplots(figsize=(8, 3.5))

    # Jitter
    rng = np.random.default_rng(42)
    jitter_stk = rng.uniform(-0.08, 0.08, len(stk_vals))
    jitter_lgb = rng.uniform(-0.08, 0.08, len(lgb_vals))

    y_stk = 1
    y_lgb = 0

    # Strip points
    ax.scatter(stk_vals, np.full_like(stk_vals, y_stk) + jitter_stk,
               c=C_PD, s=70, alpha=0.7, edgecolors="white", linewidths=0.5, zorder=3)
    ax.scatter(lgb_vals, np.full_like(lgb_vals, y_lgb) + jitter_lgb,
               c=C_HC, s=70, alpha=0.7, edgecolors="white", linewidths=0.5, zorder=3)

    # Mean diamonds
    ax.scatter([stk_vals.mean()], [y_stk], marker="D", c="#e67e22", s=120,
               edgecolors="black", linewidths=1, zorder=4, label=f"Mean")
    ax.scatter([lgb_vals.mean()], [y_lgb], marker="D", c="#e67e22", s=120,
               edgecolors="black", linewidths=1, zorder=4)

    # Mean labels
    ax.text(stk_vals.mean(), y_stk + 0.22, f"{stk_vals.mean():.2f} \u00b1 {stk_vals.std():.2f}",
            ha="center", fontsize=10, color="#333333")
    ax.text(lgb_vals.mean(), y_lgb - 0.22, f"{lgb_vals.mean():.2f} \u00b1 {lgb_vals.std():.2f}",
            ha="center", fontsize=10, color="#333333", va="top")

    ax.set_yticks([y_lgb, y_stk])
    ax.set_yticklabels(["LightGBM", "Stack"], fontsize=11)
    ax.set_xlabel("Mean Absolute Error (MAE)")
    ax.set_title("10-Split Cross-Validation MAE Distribution (Total UPDRS-III)")
    ax.set_ylim(-0.5, 1.7)

    # Light reference lines
    ax.axhline(y=y_stk, color="#eeeeee", linewidth=0.8, zorder=0)
    ax.axhline(y=y_lgb, color="#eeeeee", linewidth=0.8, zorder=0)

    return fig_to_base64(fig)


# ---------------------------------------------------------------------------
# Figure 6: Score Distribution by Group
# ---------------------------------------------------------------------------

def make_fig6() -> tuple:
    """Side-by-side histograms of UPDRS-III and observable gait scores by PD/HC."""
    # Total UPDRS-III from stats_report
    meta = stats_data["meta"]
    total_true = np.array(meta["test_true"])
    total_groups = meta["test_groups"]

    # Observable gait from subdomain
    obs_gait = None
    for c in subdomain_data["composites"]:
        if c["subdomain"] == "observable_gait":
            obs_gait = c
            break
    if obs_gait is None:
        raise RuntimeError("observable_gait composite not found")

    obs_true = np.array(obs_gait["test_true"])
    obs_sids = obs_gait["test_sids"]
    obs_groups = [classify_group(s) for s in obs_sids]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Panel 1: Total UPDRS-III
    pd_mask_total = np.array([g == "PD" for g in total_groups])
    hc_mask_total = ~pd_mask_total

    bins_total = np.linspace(0, max(total_true) + 2, 15)
    ax1.hist(total_true[pd_mask_total], bins=bins_total, color=C_PD, alpha=0.6,
             label=f"PD (n={pd_mask_total.sum()})", edgecolor="white", linewidth=0.5)
    ax1.hist(total_true[hc_mask_total], bins=bins_total, color=C_HC, alpha=0.6,
             label=f"HC (n={hc_mask_total.sum()})", edgecolor="white", linewidth=0.5)

    pd_mean_total = total_true[pd_mask_total].mean()
    hc_mean_total = total_true[hc_mask_total].mean()
    ax1.axvline(pd_mean_total, color=C_PD, linestyle="--", linewidth=1.5, alpha=0.9)
    ax1.axvline(hc_mean_total, color=C_HC, linestyle="--", linewidth=1.5, alpha=0.9)

    ax1.set_xlabel("Total UPDRS-III Score")
    ax1.set_ylabel("Count")
    ax1.set_title("Total UPDRS-III Distribution\n(Test Set, N=36)")
    ax1.legend(loc="upper right", framealpha=0.9)

    # Panel 2: Observable gait subdomain
    pd_mask_obs = np.array([g == "PD" for g in obs_groups])
    hc_mask_obs = ~pd_mask_obs

    bins_obs = np.linspace(0, max(obs_true) + 1, 12)
    ax2.hist(obs_true[pd_mask_obs], bins=bins_obs, color=C_PD, alpha=0.6,
             label=f"PD (n={pd_mask_obs.sum()})", edgecolor="white", linewidth=0.5)
    ax2.hist(obs_true[hc_mask_obs], bins=bins_obs, color=C_HC, alpha=0.6,
             label=f"HC (n={hc_mask_obs.sum()})", edgecolor="white", linewidth=0.5)

    pd_mean_obs = obs_true[pd_mask_obs].mean()
    hc_mean_obs = obs_true[hc_mask_obs].mean()
    ax2.axvline(pd_mean_obs, color=C_PD, linestyle="--", linewidth=1.5, alpha=0.9)
    ax2.axvline(hc_mean_obs, color=C_HC, linestyle="--", linewidth=1.5, alpha=0.9)

    ax2.set_xlabel("Observable Gait Score (Items 7\u201314)")
    ax2.set_ylabel("Count")
    ax2.set_title("Observable Gait Distribution\n(Test Set, N=36)")
    ax2.legend(loc="upper right", framealpha=0.9)

    fig.tight_layout(w_pad=3)

    return fig_to_base64(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Generating publication figures...")
    print()

    output = {}
    summary = []

    fig_specs = [
        ("fig1_scatter_obs", "Fig 1: Observable Gait Scatter", make_fig1),
        ("fig2_scatter_total", "Fig 2: Total UPDRS-III Scatter", make_fig2),
        ("fig3_item_lollipop", "Fig 3: Item r-value Lollipop", make_fig3),
        ("fig4_composite_mae", "Fig 4: Composite MAE Bars", make_fig4),
        ("fig5_split_strip", "Fig 5: 10-Split MAE Strip", make_fig5),
        ("fig6_distribution", "Fig 6: Score Distribution", make_fig6),
    ]

    for key, desc, make_fn in fig_specs:
        b64_str, size_kb = make_fn()
        output[key] = b64_str
        summary.append((desc, size_kb))
        print(f"  {desc}: {size_kb:.1f} KB")

    # Save output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f)

    total_kb = sum(s for _, s in summary)
    print()
    print(f"Total output size: {total_kb:.1f} KB")
    print(f"Saved to: {OUTPUT_PATH}")
    print()

    # Print figure summary table
    print("Figure Summary:")
    print("-" * 50)
    for desc, size_kb in summary:
        print(f"  {desc:40s} {size_kb:8.1f} KB")
    print("-" * 50)
    print(f"  {'TOTAL':40s} {total_kb:8.1f} KB")


if __name__ == "__main__":
    main()

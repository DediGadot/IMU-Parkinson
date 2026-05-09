"""iter34 paper figure generator — publication-quality PNGs from iter34 lockbox.

Adapted from visualize_iter29.py. Generates 5 figures into results/iter34_figures/:

  fig1_oof_calibration_iter34.png   — y_true vs y_pred scatter + diagonal + cal line
                                       (3-seed mean of iter34 hybrid; CCC=0.7366)
  fig2_residual_by_quartile_iter34.png — box+strip of residuals per T1 quartile
                                          (Q1-Q4); annotates per-quartile mean ± std
  fig3_per_subject_delta_iter34.png — bar of |err_iter12_honest|-|err_iter34| sorted by
                                       improvement; green=iter34 better, red=iter12 better
  fig4_seed_consistency_iter34.png  — per-seed CCC strip plot for iter33-A (n=7), iter33-B
                                       (n=3), iter33-C (n=3), iter34 (n=3) with bootstrap CI
  fig5_iter_progression.png         — horizontal bar chart of all iter33+iter34 LOOCV CCCs
                                       with frac>0 vs iter5 + Bonferroni gate lines

Run: uv run python visualize_iter34.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn  # noqa: E402

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

RESULTS_DIR = REPO_ROOT / "results"
FIG_DIR = RESULTS_DIR / "iter34_figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

# Okabe-Ito deuteranopia-safe palette
OK_BLACK = "#000000"
OK_ORANGE = "#E69F00"
OK_SKYBLUE = "#56B4E9"
OK_GREEN = "#009E73"
OK_YELLOW = "#F0E442"
OK_BLUE = "#0072B2"
OK_VERMILION = "#D55E00"
OK_PURPLE = "#CC79A7"
OK_GREY = "#999999"

# Fix matplotlib defaults to publication style
plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "DejaVu Sans", "Liberation Sans", "Helvetica"],
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)

# Lockbox JSON paths (canonical sources for iter34)
ITER34_PATH = RESULTS_DIR / "lockbox_t1_iter34_hybrid_20260506_141720.json"
ITER33A_PATH = RESULTS_DIR / "lockbox_t1_iter33a_v1_7seed_20260506_080627.json"
ITER33B_PATH = RESULTS_DIR / "lockbox_t1_iter33b_8item_20260506_071631.json"
ITER33C_PATH = RESULTS_DIR / "lockbox_t1_iter33c_multibase_20260506_085830.json"
ITER12_HONEST_PATH = RESULTS_DIR / "t1_iter12_honest_composite.json"
ITER34_VS_12_PAIRED = RESULTS_DIR / "iter34_vs_iter12_honest_n93_paired_2026_05_06.json"


# ----------------------------------------------------------------------------
# IO helpers
# ----------------------------------------------------------------------------


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


# ----------------------------------------------------------------------------
# Figure 1: OOF calibration
# ----------------------------------------------------------------------------


def fig1_oof_calibration(d34: dict, save_path: Path) -> None:
    """Scatter y_true vs y_pred for iter34 (3-seed mean preds), diagonal + cal line.

    Annotates CCC=0.7366, MAE=1.731, r=0.7406, slope=0.8215, n=93.
    """
    y = np.asarray(d34["per_subject"]["y_true"])
    p = np.asarray(d34["per_subject"]["y_pred"])
    n = int(d34["n"])
    ccc = float(d34["ccc"])
    mae = float(d34["mae"])
    r = float(d34["r"])
    slope = float(d34["cal_slope"])

    # Calibration intercept from y = slope * p + intercept on the means
    intercept = float(np.mean(y)) - slope * float(np.mean(p))

    fig, ax = plt.subplots(figsize=(6.0, 6.0))
    ax.scatter(
        y,
        p,
        s=42,
        c=OK_BLUE,
        alpha=0.78,
        edgecolor="white",
        linewidth=0.6,
        zorder=3,
    )

    lo = float(min(np.min(y), np.min(p))) - 0.5
    hi = float(max(np.max(y), np.max(p))) + 0.5
    xs = np.linspace(lo, hi, 100)

    # Identity line
    ax.plot(xs, xs, "--", color=OK_GREY, lw=1.4, alpha=0.85, label="y = x", zorder=2)

    # Linear fit (pred = a*true + b) for visual reference
    fit_a, fit_b = np.polyfit(y, p, 1)
    ax.plot(
        xs,
        fit_a * xs + fit_b,
        "-",
        color=OK_VERMILION,
        lw=2.0,
        alpha=0.92,
        label=f"linear fit (pred on true)  a={fit_a:.3f}",
        zorder=4,
    )

    # Calibration slope reported in JSON (LGB cal_slope on 3-seed-mean)
    ax.plot(
        xs,
        slope * xs + intercept,
        ":",
        color=OK_PURPLE,
        lw=1.8,
        alpha=0.85,
        label=f"reported cal_slope = {slope:.3f}",
        zorder=4,
    )

    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("True T1 (sum items 9–14)")
    ax.set_ylabel("Predicted T1 (iter34 hybrid, mean of 3 seeds)")

    title = (
        "iter34 hybrid OOF calibration "
        f"(LOOCV, n={n})\n"
        f"CCC = {ccc:.4f}    MAE = {mae:.3f}    r = {r:.4f}    slope = {slope:.4f}"
    )
    ax.set_title(title, pad=10)

    # Annotation box for headline numbers
    txt = (
        f"n           = {n}\n"
        f"CCC      = {ccc:.4f}\n"
        f"MAE     = {mae:.3f}\n"
        f"r            = {r:.4f}\n"
        f"slope    = {slope:.4f}"
    )
    ax.text(
        0.03,
        0.97,
        txt,
        transform=ax.transAxes,
        fontsize=9,
        family="monospace",
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.45", fc="white", ec=OK_GREY, alpha=0.9),
    )

    ax.grid(alpha=0.25, zorder=0)
    ax.legend(loc="lower right", framealpha=0.9)

    fig.tight_layout()
    fig.savefig(save_path)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Figure 2: Residual by quartile
# ----------------------------------------------------------------------------


def fig2_residual_by_quartile(d34: dict, save_path: Path) -> None:
    """Box + strip plot of (pred - true) residuals per T1 quartile (Q1..Q4).

    Annotates per-quartile mean ± std and highlights tail bias.
    """
    y = np.asarray(d34["per_subject"]["y_true"])
    p = np.asarray(d34["per_subject"]["y_pred"])
    residuals = p - y

    q1, q2, q3 = np.percentile(y, [25, 50, 75])
    masks = [
        ("Q1\n(low T1)", y <= q1),
        ("Q2", (y > q1) & (y <= q2)),
        ("Q3", (y > q2) & (y <= q3)),
        ("Q4\n(high T1)", y > q3),
    ]
    box_data = [residuals[m] for _, m in masks]
    box_labels = [lab for lab, _ in masks]
    quartile_colors = [OK_SKYBLUE, OK_GREEN, OK_ORANGE, OK_VERMILION]

    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    bp = ax.boxplot(
        box_data,
        patch_artist=True,
        widths=0.55,
        showfliers=False,
        medianprops={"color": "black", "linewidth": 1.5},
        boxprops={"linewidth": 1.0, "edgecolor": "black"},
        whiskerprops={"linewidth": 1.0},
        capprops={"linewidth": 1.0},
    )
    for patch, color in zip(bp["boxes"], quartile_colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.45)

    # Strip plot overlay (jittered points)
    rng = np.random.default_rng(20260506)
    for i, (data, color) in enumerate(zip(box_data, quartile_colors)):
        x_jit = rng.uniform(-0.13, 0.13, size=len(data)) + (i + 1)
        ax.scatter(
            x_jit,
            data,
            s=28,
            color=color,
            alpha=0.85,
            edgecolor="black",
            linewidth=0.5,
            zorder=3,
        )

    ax.axhline(0, color="black", linestyle="--", lw=1.0, alpha=0.6)
    ax.set_xticks(np.arange(1, 5))
    ax.set_xticklabels(box_labels)
    ax.set_xlabel("True-T1 quartile")
    ax.set_ylabel("Residual  (predicted − true)")

    # Annotations: per-quartile mean ± std + count
    annotations = []
    y_max_overall = max(np.max(d) for d in box_data) if box_data else 1.0
    y_min_overall = min(np.min(d) for d in box_data) if box_data else -1.0
    y_pad = 0.12 * (y_max_overall - y_min_overall + 1e-6)

    for i, (lab, d) in enumerate(zip(box_labels, box_data), start=1):
        mu = float(np.mean(d))
        sd = float(np.std(d, ddof=1)) if len(d) > 1 else 0.0
        n_q = len(d)
        ax.text(
            i,
            y_max_overall + y_pad,
            f"n={n_q}\n{mu:+.2f}\n±{sd:.2f}",
            ha="center",
            va="bottom",
            fontsize=8.5,
            family="monospace",
        )
        annotations.append((lab.replace("\n", " "), mu, sd, n_q))

    ax.set_ylim(y_min_overall - y_pad * 0.5, y_max_overall + y_pad * 3.2)

    # Highlight tail bias if Q1 mean > +0.5 (over-predict) or Q4 mean < -0.5 (under-predict)
    q1_mean = annotations[0][1]
    q4_mean = annotations[-1][1]
    bias_msg_lines = []
    if q1_mean > 0.5:
        bias_msg_lines.append(
            f"Q1 mean residual = {q1_mean:+.2f}  →  over-prediction at low end"
        )
    if q4_mean < -0.5:
        bias_msg_lines.append(
            f"Q4 mean residual = {q4_mean:+.2f}  →  under-prediction at high end"
        )
    if not bias_msg_lines:
        bias_msg_lines.append("No tail bias > 0.5 absolute UPDRS — residuals well-centered")
    bias_msg = "\n".join(bias_msg_lines)

    ax.text(
        0.5,
        -0.21,
        bias_msg,
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=9,
        bbox=dict(boxstyle="round,pad=0.4", fc=OK_YELLOW, ec=OK_GREY, alpha=0.4),
    )

    ax.grid(alpha=0.25, axis="y", zorder=0)
    title = (
        "iter34 hybrid: residual distribution by true-T1 quartile (n=93)\n"
        "Box = IQR + median; points = individual subjects"
    )
    ax.set_title(title, pad=10)

    fig.tight_layout()
    fig.savefig(save_path)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Figure 3: Per-subject delta vs iter12 honest
# ----------------------------------------------------------------------------


def fig3_per_subject_delta(d34: dict, d12: dict, save_path: Path) -> None:
    """For each common SID, compute |err_iter12_honest| - |err_iter34|.

    Positive = iter34 reduces absolute error vs iter12 honest. Bars sorted by improvement.
    """
    sids34 = d34["per_subject"]["sids"]
    y34 = np.asarray(d34["per_subject"]["y_true"], dtype=float)
    p34 = np.asarray(d34["per_subject"]["y_pred"], dtype=float)

    sids12 = d12["per_subject"]["sids"]
    y12 = np.asarray(d12["per_subject"]["y_true"], dtype=float)
    p12 = np.asarray(d12["per_subject"]["y_pred"], dtype=float)

    # Restrict iter12 to the n=93 iter34 cohort (drop WPD002 if absent in iter34)
    sid12_to_idx = {s: i for i, s in enumerate(sids12)}
    keep_mask = np.array([s in sid12_to_idx for s in sids34], dtype=bool)
    if not keep_mask.all():
        missing = [s for s in sids34 if s not in sid12_to_idx]
        raise RuntimeError(f"iter34 SIDs missing from iter12: {missing[:5]}")

    p12_aligned = np.array([p12[sid12_to_idx[s]] for s in sids34])
    y12_aligned = np.array([y12[sid12_to_idx[s]] for s in sids34])
    if not np.allclose(y12_aligned, y34):
        raise RuntimeError(
            f"y_true mismatch between iter12 and iter34 (max abs = "
            f"{np.max(np.abs(y12_aligned - y34)):.3f})"
        )

    err34 = np.abs(p34 - y34)
    err12 = np.abs(p12_aligned - y34)
    improvement = err12 - err34  # > 0 means iter34 better
    order = np.argsort(improvement)[::-1]  # most improved first

    n_better = int((improvement > 0).sum())
    n_worse = int((improvement < 0).sum())
    n_tie = int((improvement == 0).sum())
    net = float(improvement.sum())
    frac_better = n_better / len(improvement)

    fig, ax = plt.subplots(figsize=(11.5, 5.4))
    x = np.arange(len(improvement))
    colors = [OK_GREEN if v > 0 else OK_VERMILION if v < 0 else OK_GREY for v in improvement[order]]
    ax.bar(x, improvement[order], color=colors, alpha=0.82, width=0.85, edgecolor="black", linewidth=0.3)

    ax.axhline(0, color="black", lw=1.0)
    ax.set_xlabel("Subject (sorted by error reduction; left = iter34 wins most)")
    ax.set_ylabel(
        "|err iter12 honest| − |err iter34|\n(positive = iter34 better)"
    )
    title = (
        "iter34 hybrid vs iter12 honest — per-subject error reduction (n=93)\n"
        f"iter34 better on {n_better}/{len(improvement)} ({100*frac_better:.1f}%);  "
        f"iter12 better on {n_worse};  ties: {n_tie};  net Σ |Δerr| = {net:+.2f} UPDRS"
    )
    ax.set_title(title, pad=10)

    # Annotate top 3 winners and top 3 losers
    sids_sorted = [sids34[i] for i in order]
    top_n_label = 3
    for i in range(min(top_n_label, len(order))):
        ax.annotate(
            sids_sorted[i],
            xy=(i, improvement[order][i]),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=7.5,
            color=OK_GREEN,
        )
    for i in range(1, min(top_n_label + 1, len(order) + 1)):
        idx = len(order) - i
        ax.annotate(
            sids_sorted[idx],
            xy=(idx, improvement[order][idx]),
            xytext=(0, -10),
            textcoords="offset points",
            ha="center",
            fontsize=7.5,
            color=OK_VERMILION,
        )

    # Custom legend
    from matplotlib.patches import Patch

    handles = [
        Patch(facecolor=OK_GREEN, alpha=0.82, label=f"iter34 better (n={n_better})"),
        Patch(facecolor=OK_VERMILION, alpha=0.82, label=f"iter12 honest better (n={n_worse})"),
    ]
    if n_tie:
        handles.append(Patch(facecolor=OK_GREY, alpha=0.82, label=f"tie (n={n_tie})"))
    ax.legend(handles=handles, loc="upper right", framealpha=0.9)

    ax.grid(alpha=0.25, axis="y", zorder=0)

    fig.tight_layout()
    fig.savefig(save_path)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Figure 4: Seed consistency across iter33 family + iter34
# ----------------------------------------------------------------------------


def fig4_seed_consistency(
    d34: dict, d33a: dict, d33b: dict, d33c: dict, save_path: Path
) -> None:
    """Per-seed CCC strip plot for iter33-A (n=7), iter33-B (n=3), iter33-C (n=3),
    iter34 (n=3). Show iter34 at top of family.
    """
    runs = [
        ("iter33-A\nF65 reanchor\n(n=94, 7 seeds)", d33a, OK_SKYBLUE),
        ("iter33-B\n8-item chain\n(n=93, 3 seeds)", d33b, OK_ORANGE),
        ("iter33-C\nmulti-base\n(n=94, 3 seeds)", d33c, OK_GREEN),
        ("iter34\nhybrid (8-item +\nmulti-base) (n=93, 3 seeds)", d34, OK_VERMILION),
    ]

    fig, ax = plt.subplots(figsize=(9.5, 5.6))

    # Iter12 honest reference
    iter12_ccc = 0.6550
    iter5_baseline = 0.6496  # lockbox baseline used in iter33/iter34

    rng = np.random.default_rng(20260506)
    for i, (label, d, color) in enumerate(runs):
        seeds_data = d["per_seed"]
        cccs = [r["ccc_mt"] for r in seeds_data]
        mean_ccc = float(d["ccc"])

        x_jit = rng.uniform(-0.18, 0.18, size=len(cccs)) + i
        ax.scatter(
            x_jit,
            cccs,
            s=80,
            c=color,
            alpha=0.85,
            edgecolor="black",
            linewidth=0.7,
            zorder=4,
        )
        # Mean marker
        ax.scatter(
            [i],
            [mean_ccc],
            s=240,
            marker="D",
            c=color,
            edgecolor="black",
            linewidth=1.3,
            zorder=5,
            label=f"{label.splitlines()[0]}: mean = {mean_ccc:.4f}",
        )
        # Annotate mean numerically
        ax.text(
            i + 0.32,
            mean_ccc,
            f"{mean_ccc:.4f}",
            ha="left",
            va="center",
            fontsize=9,
            family="monospace",
            color="black",
        )

    # Bootstrap CI for iter34 vs iter5
    boot = d34["bootstrap_delta_vs_iter5"]
    iter34_mean = float(d34["ccc"])
    boot_lo_abs = iter34_mean - boot["delta_mean"] + boot["delta_ci_low"]
    boot_hi_abs = iter34_mean - boot["delta_mean"] + boot["delta_ci_high"]
    # Draw the 95% CI band on the iter34 column (i = 3)
    ax.fill_between(
        [3 - 0.32, 3 + 0.32],
        [boot_lo_abs, boot_lo_abs],
        [boot_hi_abs, boot_hi_abs],
        color=OK_VERMILION,
        alpha=0.13,
        zorder=1,
        label=(
            f"iter34 vs iter5 95% bootstrap CI on Δ (mapped to absolute CCC):\n"
            f"   [{boot_lo_abs:.4f}, {boot_hi_abs:.4f}]"
        ),
    )

    # Reference horizontal lines
    ax.axhline(
        iter12_ccc,
        ls="--",
        lw=1.2,
        color=OK_PURPLE,
        alpha=0.8,
        label=f"iter12 honest canonical (CCC = {iter12_ccc:.4f}, n=94)",
    )
    ax.axhline(
        iter5_baseline,
        ls=":",
        lw=1.2,
        color=OK_GREY,
        alpha=0.85,
        label=f"iter5-direct LOOCV baseline (CCC = {iter5_baseline:.4f})",
    )

    ax.set_xticks(np.arange(len(runs)))
    ax.set_xticklabels([r[0] for r in runs], fontsize=8.5)
    ax.set_ylabel("LOOCV CCC")
    ax.set_xlim(-0.5, len(runs) - 0.5 + 0.5)
    ax.set_ylim(0.61, 0.755)

    title = (
        "Per-seed LOOCV CCC across iter33 family + iter34 hybrid\n"
        "Diamonds = run mean; circles = individual seeds; iter34 sits at top of family"
    )
    ax.set_title(title, pad=10)
    ax.grid(alpha=0.25, axis="y", zorder=0)
    ax.legend(loc="lower right", fontsize=7.8, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(save_path)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Figure 5: iter progression
# ----------------------------------------------------------------------------


def fig5_iter_progression(
    d34: dict, d33a: dict, d33b: dict, d33c: dict, save_path: Path
) -> None:
    """Horizontal bar chart of iter12 honest, iter33-A/B/C, iter34 LOOCV CCCs.

    Annotate each bar with frac>0 vs iter5; mark Bonferroni-adjusted significance
    thresholds (n=3, n=8, n=9) as vertical dashed lines.
    """
    iter5_baseline_ccc = 0.6496
    iter12_honest_ccc = 0.6550
    rows = [
        (
            "iter12 honest",
            iter12_honest_ccc,
            None,  # no bootstrap-vs-iter5 in this script
            None,
            "n=94 (canonical pre-iter34)",
            OK_PURPLE,
        ),
        (
            "iter33-A (F65 reanchor, 7 seeds)",
            float(d33a["ccc"]),
            float(d33a["bootstrap_delta_vs_iter5"]["frac_above_zero"]),
            float(d33a["bootstrap_delta_vs_iter5"]["frac_above_0.025"]),
            "n=94, multi-task chain",
            OK_SKYBLUE,
        ),
        (
            "iter33-B (8-item chain)",
            float(d33b["ccc"]),
            float(d33b["bootstrap_delta_vs_iter5"]["frac_above_zero"]),
            float(d33b["bootstrap_delta_vs_iter5"]["frac_above_0.025"]),
            "n=93, items 9-14 + 15 + 18",
            OK_ORANGE,
        ),
        (
            "iter33-C (multi-base)",
            float(d33c["ccc"]),
            float(d33c["bootstrap_delta_vs_iter5"]["frac_above_zero"]),
            float(d33c["bootstrap_delta_vs_iter5"]["frac_above_0.025"]),
            "n=94, lgb+xgb+et",
            OK_GREEN,
        ),
        (
            "iter34 hybrid (8-item + multi-base)",
            float(d34["ccc"]),
            float(d34["bootstrap_delta_vs_iter5"]["frac_above_zero"]),
            float(d34["bootstrap_delta_vs_iter5"]["frac_above_0.025"]),
            "n=93, post-publication target",
            OK_VERMILION,
        ),
    ]

    labels = [r[0] for r in rows]
    cccs = np.array([r[1] for r in rows])
    fracs0 = [r[2] for r in rows]
    descs = [r[4] for r in rows]
    colors = [r[5] for r in rows]

    # Plot bars on a zoomed x-axis [0.62, 0.76] so differences are visible.
    # CCC labels are drawn just to the right of each bar tip; descriptive text goes in a
    # right-side panel beyond the plotted axis.
    fig, ax = plt.subplots(figsize=(13.5, 5.8))
    y_pos = np.arange(len(rows))
    x_axis_lo = 0.62
    x_axis_hi = 0.76
    bar_origin = x_axis_lo
    bar_widths = cccs - bar_origin
    ax.barh(
        y_pos,
        bar_widths,
        left=bar_origin,
        color=colors,
        alpha=0.82,
        edgecolor="black",
        linewidth=0.6,
    )

    # Reference line: iter5 baseline
    ax.axvline(
        iter5_baseline_ccc,
        ls=":",
        lw=1.4,
        color=OK_GREY,
        label=f"iter5-direct LOOCV (CCC = {iter5_baseline_ccc:.4f})",
    )
    ax.axvline(
        iter12_honest_ccc,
        ls="--",
        lw=1.2,
        color=OK_PURPLE,
        alpha=0.7,
        label=f"iter12 honest canonical (CCC = {iter12_honest_ccc:.4f})",
    )

    # Bonferroni-adjusted gate lines (we map Bonferroni alpha to the CCC axis only via labels;
    # gate semantics are in *probability* space — we annotate them as text on the right edge)
    # Strict gate: frac>0 ≥ 0.95
    # Bonferroni n=3: 1 - 0.05/3 = 0.9833
    # Bonferroni n=8: 1 - 0.05/8 = 0.9938
    # Bonferroni n=9: 1 - 0.05/9 = 0.9944
    gate_thresholds = [
        ("strict (α=0.05)", 0.95),
        ("Bonf n=3", 0.9833),
        ("Bonf n=8", 0.9938),
        ("Bonf n=9", 0.9944),
    ]

    # CCC label drawn just past each bar tip
    text_x_offset_plot = 0.001
    # Right-side text panel starts beyond x_axis_hi
    text_panel_x = x_axis_hi + 0.001

    for yi, (label, ccc, frac0, frac025, desc, _color) in zip(y_pos, rows):
        # CCC label on the bar
        ax.text(
            ccc + text_x_offset_plot,
            yi,
            f"{ccc:.4f}",
            va="center",
            ha="left",
            fontsize=10,
            family="monospace",
            fontweight="bold",
            zorder=6,
        )

        # Right-side info column
        if frac0 is not None:
            gates_str_parts = []
            for g_name, g_val in gate_thresholds:
                mark = "PASS" if frac0 >= g_val else "fail"
                gates_str_parts.append(f"{g_name}={mark}")
            frac_str = f"frac>0 = {frac0:.3f}    frac>+0.025 = {frac025:.3f}"
            gates_str = "    ".join(gates_str_parts)
            info = f"{desc}\n{frac_str}\n{gates_str}"
        else:
            info = f"{desc}\n(no bootstrap vs iter5 in this script)"
        ax.text(
            text_panel_x,
            yi,
            info,
            va="center",
            ha="left",
            fontsize=8.4,
            family="monospace",
            transform=ax.get_yaxis_transform()
            if False
            else ax.transData,
            clip_on=False,
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("LOOCV CCC")
    ax.set_xlim(x_axis_lo, x_axis_hi)
    # Reserve right-panel space without clipping
    fig.subplots_adjust(right=0.55)

    title = (
        "iter33 family + iter34 hybrid — LOOCV CCC progression with Bonferroni gate status\n"
        "Bonferroni gates apply to multiple-comparison correction across the iter33-A/B/C family of three; "
        "iter34 is independent (n=1)"
    )
    ax.set_title(title, pad=10)
    ax.legend(loc="lower right", framealpha=0.9)
    ax.grid(alpha=0.25, axis="x", zorder=0)

    fig.tight_layout()
    fig.savefig(save_path)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------


def main() -> None:
    print(f"Loading iter34 lockbox: {ITER34_PATH}")
    d34 = load_json(ITER34_PATH)
    print(f"  iter34 ccc={d34['ccc']:.4f}  n={d34['n']}  seeds={d34['n_seeds']}")

    print(f"Loading iter33-A: {ITER33A_PATH}")
    d33a = load_json(ITER33A_PATH)
    print(f"  iter33-A ccc={d33a['ccc']:.4f}  n={d33a['n']}  seeds={d33a['n_seeds']}")

    print(f"Loading iter33-B: {ITER33B_PATH}")
    d33b = load_json(ITER33B_PATH)
    print(f"  iter33-B ccc={d33b['ccc']:.4f}  n={d33b['n']}  seeds={d33b['n_seeds']}")

    print(f"Loading iter33-C: {ITER33C_PATH}")
    d33c = load_json(ITER33C_PATH)
    print(f"  iter33-C ccc={d33c['ccc']:.4f}  n={d33c['n']}  seeds={d33c['n_seeds']}")

    print(f"Loading iter12 honest: {ITER12_HONEST_PATH}")
    d12 = load_json(ITER12_HONEST_PATH)
    print(f"  iter12 honest ccc={d12['ccc']:.4f}  n={d12['n']}")

    # Sanity: recompute iter34 CCC on per_subject preds and confirm it matches reported ccc
    y34 = np.asarray(d34["per_subject"]["y_true"], dtype=float)
    p34 = np.asarray(d34["per_subject"]["y_pred"], dtype=float)
    ccc_recomputed = float(ccc_fn(y34, p34))
    print(f"  recomputed CCC on per_subject = {ccc_recomputed:.4f}  (reported = {d34['ccc']:.4f})")
    if abs(ccc_recomputed - d34["ccc"]) > 0.003:
        raise RuntimeError(
            f"Recomputed CCC ({ccc_recomputed:.4f}) does not match reported ({d34['ccc']:.4f})"
        )

    print()
    print("Generating figures...")

    out1 = FIG_DIR / "fig1_oof_calibration_iter34.png"
    fig1_oof_calibration(d34, out1)
    print(f"  wrote {out1}")

    out2 = FIG_DIR / "fig2_residual_by_quartile_iter34.png"
    fig2_residual_by_quartile(d34, out2)
    print(f"  wrote {out2}")

    out3 = FIG_DIR / "fig3_per_subject_delta_iter34.png"
    fig3_per_subject_delta(d34, d12, out3)
    print(f"  wrote {out3}")

    out4 = FIG_DIR / "fig4_seed_consistency_iter34.png"
    fig4_seed_consistency(d34, d33a, d33b, d33c, out4)
    print(f"  wrote {out4}")

    out5 = FIG_DIR / "fig5_iter_progression.png"
    fig5_iter_progression(d34, d33a, d33b, d33c, out5)
    print(f"  wrote {out5}")

    print()
    print(f"All 5 figures written to {FIG_DIR}/")


if __name__ == "__main__":
    main()

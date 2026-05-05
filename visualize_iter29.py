"""Iter29 visualization — generate PNG figures + summary stats from all iter29 OOF JSONs.

Figures (all saved to results/iter29_figures/):
  fig1_oof_calibration.png       — predicted vs true T1 scatter, all 4 angles overlaid (3 seeds)
  fig2_residual_by_quartile.png  — boxplot of residuals by T1 quartile, per angle
  fig3_per_subject_delta.png     — per-subject Δ(angle - iter5) bar chart, sorted by T1
  fig4_seed_consistency.png      — Δ(angle - iter5) per seed, bar chart
  fig5_pairwise_rank_corr.png    — predicted-vs-true Spearman ρ per angle
  fig6_loocv_vs_5fold.png        — for iter29b: 5-fold vs LOOCV CCC, paired-bootstrap dist

A markdown summary (iter29_summary.md) is also written.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from inductive_lib import ccc as ccc_fn

RESULTS_DIR = REPO_ROOT / "results"
FIG_DIR = RESULTS_DIR / "iter29_figures"
FIG_DIR.mkdir(exist_ok=True)


def _latest(pattern: str) -> Path | None:
    """Return the most recent file matching a glob pattern under results/."""
    matches = sorted(RESULTS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None


def _load_oof_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def fig_oof_calibration(oof_data: dict, save_path: Path):
    """Predicted vs true T1, color-coded by angle, overlaying 3 seeds."""
    fig, axes = plt.subplots(1, len(oof_data), figsize=(5 * len(oof_data), 5), squeeze=False)
    for col_i, (angle, data) in enumerate(oof_data.items()):
        ax = axes[0, col_i]
        for seed_key, color in zip(["seed42", "seed1337", "seed7"], ["#1f77b4", "#ff7f0e", "#2ca02c"]):
            y = np.asarray(data[f"{seed_key}_y"])
            p = np.asarray(data[f"{seed_key}_pred"])
            ax.scatter(y, p, alpha=0.5, color=color, s=25, label=seed_key)
        # Identity line + 95% CI band approximation (visual aid)
        lo, hi = float(np.min(y)), float(np.max(y))
        ax.plot([lo, hi], [lo, hi], "k--", alpha=0.5, lw=1)
        # Fit line with seed42 for reference
        y42 = np.asarray(data["seed42_y"])
        p42 = np.asarray(data["seed42_pred"])
        slope, intercept = np.polyfit(y42, p42, 1)
        xs = np.linspace(lo, hi, 50)
        ax.plot(xs, slope * xs + intercept, color="#1f77b4", lw=2, alpha=0.7,
                label=f"slope={slope:.2f}")
        ax.set_xlabel("True T1 (sum items 9-14)")
        ax.set_ylabel("Predicted T1")
        ccc_42 = float(ccc_fn(y42, p42))
        ax.set_title(f"{angle}\nseed42 CCC={ccc_42:.3f}")
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(alpha=0.3)
    fig.suptitle("OOF Predicted vs True T1 — calibration & dispersion", fontsize=14, y=1.02)
    fig.tight_layout()
    fig.savefig(save_path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def fig_residual_by_quartile(oof_data: dict, save_path: Path):
    """Boxplot of residuals (pred - true) by T1 quartile, per angle, seed42 only."""
    angles = list(oof_data.keys())
    fig, ax = plt.subplots(1, 1, figsize=(max(7, 2.5 * len(angles)), 5))
    box_data = []
    box_labels = []
    box_colors = []
    palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
    for ang_i, angle in enumerate(angles):
        y = np.asarray(oof_data[angle]["seed42_y"])
        p = np.asarray(oof_data[angle]["seed42_pred"])
        residuals = p - y
        q1, q2, q3 = np.percentile(y, [25, 50, 75])
        for q_label, q_mask, q_offset in [
            ("Q1 (low)", y <= q1, -0.3),
            ("Q2", (y > q1) & (y <= q2), -0.1),
            ("Q3", (y > q2) & (y <= q3), 0.1),
            ("Q4 (high)", y > q3, 0.3),
        ]:
            box_data.append(residuals[q_mask])
            box_labels.append(f"{angle}\n{q_label}")
            box_colors.append(palette[ang_i % len(palette)])
    bp = ax.boxplot(box_data, patch_artist=True, widths=0.6, showfliers=True,
                    medianprops={"color": "black", "linewidth": 1.5})
    for patch, color in zip(bp["boxes"], box_colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.55)
    ax.axhline(0, color="black", linestyle="--", lw=1, alpha=0.5)
    ax.set_xticklabels(box_labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Residual (pred − true)")
    ax.set_title("Per-quartile residual distribution (seed=42)")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(save_path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def fig_per_subject_delta(oof_data: dict, save_path: Path):
    """For each angle, plot Δ_subject = |pred_angle - true| - |pred_iter5 - true|, sorted by T1."""
    angles = list(oof_data.keys())
    fig, axes = plt.subplots(len(angles), 1, figsize=(11, 3.2 * len(angles)), squeeze=False)
    for row_i, angle in enumerate(angles):
        ax = axes[row_i, 0]
        y = np.asarray(oof_data[angle]["seed42_y"])
        p_a = np.asarray(oof_data[angle]["seed42_pred"])
        p_i5 = np.asarray(oof_data[angle]["seed42_iter5"])
        improvement = np.abs(p_i5 - y) - np.abs(p_a - y)
        order = np.argsort(y)
        x = np.arange(len(y))
        colors = ["#2ca02c" if v > 0 else "#d62728" for v in improvement[order]]
        ax.bar(x, improvement[order], color=colors, alpha=0.7, width=0.85)
        ax.axhline(0, color="black", lw=1)
        ax.set_xlabel("Subject (sorted by true T1)")
        ax.set_ylabel("|err iter5| − |err angle|\n(pos = angle better)")
        n_better = int((improvement > 0).sum())
        net = float(improvement.sum())
        ax.set_title(
            f"{angle} — per-subject improvement (seed=42).  "
            f"Net abs-error reduction = {net:+.2f}; "
            f"angle better on {n_better}/{len(y)} subjects"
        )
        # Add annotations for tail subjects (low/high T1)
        ax.text(0.02, 0.95, f"low-T1 ←", transform=ax.transAxes, fontsize=9, alpha=0.6)
        ax.text(0.92, 0.95, f"→ high-T1", transform=ax.transAxes, fontsize=9, alpha=0.6)
        ax.grid(alpha=0.3, axis="y")
    fig.suptitle("Where does each angle help vs iter5? Per-subject error reduction", fontsize=12, y=1.001)
    fig.tight_layout()
    fig.savefig(save_path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def fig_seed_consistency(angle_csvs: dict[str, Path], save_path: Path):
    """Bar chart of Δ per seed for each angle."""
    angles = list(angle_csvs.keys())
    seeds = [42, 1337, 7]
    fig, ax = plt.subplots(1, 1, figsize=(max(8, 1.7 * len(angles) * len(seeds)), 5))
    x = np.arange(len(angles) * len(seeds))
    deltas = []
    labels = []
    palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
    colors = []
    for ang_i, (angle, csv) in enumerate(angle_csvs.items()):
        df = pd.read_csv(csv)
        for seed in seeds:
            row = df[df["seed"] == seed]
            if len(row) == 0:
                continue
            d = float(row["delta"].iloc[0])
            deltas.append(d)
            labels.append(f"{angle}\nseed={seed}")
            colors.append(palette[ang_i % len(palette)])
    bars = ax.bar(np.arange(len(deltas)), deltas, color=colors, alpha=0.75)
    for b, d in zip(bars, deltas):
        ax.text(b.get_x() + b.get_width() / 2, d + (0.001 if d >= 0 else -0.003),
                f"{d:+.4f}", ha="center", fontsize=8,
                color="black" if d >= 0 else "darkred")
    ax.axhline(0, color="black", lw=1)
    ax.axhline(0.025, color="green", linestyle="--", lw=1, alpha=0.5,
               label="+0.025 gate floor")
    ax.set_xticks(np.arange(len(deltas)))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Δ vs iter5-direct-T1 (5-fold CCC)")
    ax.set_title("Per-seed Δ across iter29 angles — gate at +0.025 (green dashed)")
    ax.legend()
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(save_path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def fig_loocv_vs_5fold_for_29b(validation_path: Path, save_path: Path):
    """For iter29b only: 5-fold and LOOCV side-by-side + bootstrap distribution."""
    if not validation_path.exists():
        return
    with open(validation_path) as f:
        v = json.load(f)
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # (1) 5-fold per-seed CCCs
    if "five_fold" in v:
        seeds = [r["seed"] for r in v["five_fold"]]
        mt = [r["ccc_mt"] for r in v["five_fold"]]
        i5 = [r["ccc_i5"] for r in v["five_fold"]]
        x = np.arange(len(seeds))
        axes[0].bar(x - 0.2, i5, 0.4, label="iter5-direct", color="#1f77b4", alpha=0.75)
        axes[0].bar(x + 0.2, mt, 0.4, label="multi-task", color="#2ca02c", alpha=0.75)
        for i, (a, b) in enumerate(zip(i5, mt)):
            axes[0].text(i - 0.2, a + 0.005, f"{a:.3f}", ha="center", fontsize=8)
            axes[0].text(i + 0.2, b + 0.005, f"{b:.3f}", ha="center", fontsize=8)
        axes[0].set_xticks(x)
        axes[0].set_xticklabels([f"seed={s}" for s in seeds])
        axes[0].set_ylabel("5-fold CCC")
        axes[0].set_title("5-fold per-seed (iter29b vs iter5-direct)")
        axes[0].legend()
        axes[0].grid(alpha=0.3, axis="y")

    # (2) LOOCV per-seed + 3-seed-mean
    if "loocv" in v:
        loo = v["loocv"]
        seeds = [r["seed"] for r in loo["per_seed"]]
        mt = [r["ccc_mt"] for r in loo["per_seed"]]
        i5 = [r["ccc_i5"] for r in loo["per_seed"]]
        x = np.arange(len(seeds) + 1)
        labels = [f"seed={s}" for s in seeds] + ["3-seed-mean"]
        i5_all = i5 + [loo["ccc_i5_mean"]]
        mt_all = mt + [loo["ccc_mt_mean"]]
        axes[1].bar(x - 0.2, i5_all, 0.4, label="iter5-direct LOOCV", color="#1f77b4", alpha=0.75)
        axes[1].bar(x + 0.2, mt_all, 0.4, label="multi-task LOOCV", color="#2ca02c", alpha=0.75)
        for i, (a, b) in enumerate(zip(i5_all, mt_all)):
            axes[1].text(i - 0.2, a + 0.005, f"{a:.3f}", ha="center", fontsize=8)
            axes[1].text(i + 0.2, b + 0.005, f"{b:.3f}", ha="center", fontsize=8)
        axes[1].set_xticks(x)
        axes[1].set_xticklabels(labels, rotation=15, ha="right")
        axes[1].set_ylabel("LOOCV CCC")
        axes[1].set_title("LOOCV per-seed + 3-seed-mean")
        axes[1].legend()
        axes[1].grid(alpha=0.3, axis="y")

        # (3) Bootstrap distribution
        boot = loo.get("bootstrap", {})
        if "delta_mean" in boot:
            # Approximate the distribution from the summary (no raw samples in JSON)
            mu = boot["delta_mean"]; lo = boot["delta_ci_low"]; hi = boot["delta_ci_high"]
            axes[2].axvspan(lo, hi, alpha=0.3, color="#2ca02c", label=f"95% CI [{lo:+.3f}, {hi:+.3f}]")
            axes[2].axvline(mu, color="black", lw=2, label=f"mean Δ = {mu:+.4f}")
            axes[2].axvline(0, color="red", linestyle="--", lw=1)
            axes[2].axvline(0.025, color="green", linestyle="--", lw=1, label="+0.025 gate")
            axes[2].set_xlim(min(-0.05, lo - 0.01), max(hi + 0.01, 0.05))
            axes[2].set_ylim(0, 1)
            axes[2].set_yticks([])
            axes[2].set_xlabel("Δ CCC (iter29b − iter5-direct)")
            axes[2].set_title(
                f"Bootstrap (n=5000): frac>0={boot['frac_above_zero']:.3f}, "
                f"frac>+0.025={boot['frac_above_0.025']:.3f}"
            )
            axes[2].legend(fontsize=9)

    fig.suptitle("iter29b multi-task LGB validation: 5-fold + LOOCV + paired bootstrap",
                 fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(save_path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def write_markdown_summary(oof_data, csvs, validation_path, out_path):
    lines = ["# iter29 — T1 SOTA shootout summary",
             "",
             f"Generated: {pd.Timestamp.now().isoformat()}",
             "",
             "## 5-fold per-angle results",
             "",
             "| Angle | seed=42 | seed=1337 | seed=7 | Mean Δ vs iter5 | Notes |",
             "| --- | --- | --- | --- | --- | --- |"]
    for angle, csv_path in csvs.items():
        df = pd.read_csv(csv_path)
        # CCC column varies per angle; compute the angle's primary CCC col
        ccc_col = next((c for c in df.columns if c.startswith("ccc_") and c != "ccc_iter5_direct"), None)
        d_col = next((c for c in df.columns if c == "delta"), None)
        if ccc_col is None or d_col is None:
            lines.append(f"| {angle} | (no parsable CCC col) | | | | |")
            continue
        cells = [
            angle,
            f"{df.loc[df['seed']==42, ccc_col].iloc[0]:.4f} (Δ={df.loc[df['seed']==42, d_col].iloc[0]:+.4f})"
            if 42 in df['seed'].values else "—",
            f"{df.loc[df['seed']==1337, ccc_col].iloc[0]:.4f} (Δ={df.loc[df['seed']==1337, d_col].iloc[0]:+.4f})"
            if 1337 in df['seed'].values else "—",
            f"{df.loc[df['seed']==7, ccc_col].iloc[0]:.4f} (Δ={df.loc[df['seed']==7, d_col].iloc[0]:+.4f})"
            if 7 in df['seed'].values else "—",
            f"{df[d_col].mean():+.4f}",
            f"std(Δ)={df[d_col].std():.4f}",
        ]
        lines.append("| " + " | ".join(cells) + " |")

    if validation_path is not None and validation_path.exists():
        with open(validation_path) as f:
            v = json.load(f)
        lines += ["", "## iter29b validation"]
        if "scrambled" in v:
            lines.append("\n### Scrambled-label null gate (5-fold)")
            for r in v["scrambled"]:
                lines.append(f"- seed={r['seed']}: mt_scram={r['ccc_mt_scram']:+.4f}, "
                             f"i5_scram={r['ccc_i5_scram']:+.4f}  (expected ≈ 0)")
        if "loocv" in v:
            loo = v["loocv"]
            lines += ["", "### LOOCV (3-seed mean of preds)",
                      f"- mt = {loo['ccc_mt_mean']:.4f}",
                      f"- i5-direct = {loo['ccc_i5_mean']:.4f}",
                      f"- **Δ = {loo['delta_mean']:+.4f}**"]
            if "bootstrap" in loo:
                b = loo["bootstrap"]
                lines += [
                    "",
                    "### Paired bootstrap (n=5000) on LOOCV mean preds",
                    f"- mean Δ = {b['delta_mean']:+.4f}",
                    f"- 95% CI = [{b['delta_ci_low']:+.4f}, {b['delta_ci_high']:+.4f}]",
                    f"- frac>0 = {b['frac_above_zero']:.3f}",
                    f"- frac>+0.025 = {b['frac_above_0.025']:.3f}",
                ]

    out_path.write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    args = ap.parse_args()

    csv_a = _latest("iter29a_pairwise_5fold_*.csv")
    csv_b = _latest("iter29b_multitask_5fold_*.csv")
    csv_c = _latest("iter29c_ccc_direct_5fold_*.csv")
    oof_a = _latest("iter29a_pairwise_5fold_*.oof.json")
    oof_b = _latest("iter29b_multitask_5fold_*.oof.json")
    oof_c = _latest("iter29c_ccc_direct_5fold_*.oof.json")
    validate_b = _latest("iter29b_validate_*.json")

    # Build oof_data dict for whichever angles have completed
    oof_data: dict = {}
    csvs: dict = {}
    if oof_a is not None and csv_a is not None:
        oof_data["iter29a_pairwise"] = _load_oof_json(oof_a)
        csvs["iter29a_pairwise"] = csv_a
    if oof_b is not None and csv_b is not None:
        oof_data["iter29b_multitask"] = _load_oof_json(oof_b)
        csvs["iter29b_multitask"] = csv_b
    if oof_c is not None and csv_c is not None:
        # iter29c has variant×seed structure; flatten "with_stage1" only
        raw = _load_oof_json(oof_c)
        sub = {k.replace("with_stage1_", ""): v for k, v in raw.items() if k.startswith("with_stage1_")}
        if all(f"seed{s}_y" in sub for s in [42, 1337, 7]):
            oof_data["iter29c_ccc_direct"] = sub
            csvs["iter29c_ccc_direct"] = csv_c
    if not oof_data:
        print("No iter29 OOF JSONs found yet; skipping figures.")
        return

    print(f"Found {len(oof_data)} angles with OOF data: {list(oof_data.keys())}")
    fig_oof_calibration(oof_data, FIG_DIR / "fig1_oof_calibration.png")
    fig_residual_by_quartile(oof_data, FIG_DIR / "fig2_residual_by_quartile.png")
    fig_per_subject_delta(oof_data, FIG_DIR / "fig3_per_subject_delta.png")
    fig_seed_consistency(csvs, FIG_DIR / "fig4_seed_consistency.png")
    if validate_b is not None:
        fig_loocv_vs_5fold_for_29b(validate_b, FIG_DIR / "fig5_iter29b_validation.png")
    write_markdown_summary(oof_data, csvs, validate_b, FIG_DIR / "iter29_summary.md")

    print(f"\nFigures + summary written to {FIG_DIR}/")


if __name__ == "__main__":
    main()

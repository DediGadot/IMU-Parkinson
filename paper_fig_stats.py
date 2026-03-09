"""
Generate stats figures (scatter with CIs, Bland-Altman) from stacking results.
These produce fig8 (scatter), fig9 (residuals), fig8b (ceiling scatter).

Uses proven_stack_results.json (S6 = best stacking MAE=6.89) and
ceiling_stack_results.json (C2 = best ceiling MAE=6.43) for the actual
model predictions used in the paper.

The output filenames keep their legacy numbering; generate_html_paper.py
assigns final manuscript figure numbers in appearance order.
"""
import json
from pathlib import Path

import numpy as np
from scipy import stats as sp_stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

MCID_WORSEN = 4.63
ROOT = Path(__file__).resolve().parent
FIG_DIR = ROOT / "figures"

# Load test ground truth from stats_report (has test_true, groups, sids)
with open(ROOT / "stats_report.json") as f:
    report = json.load(f)

y_true = np.array(report["meta"]["test_true"])
groups = np.array(report["meta"]["test_groups"])

# Load stacking predictions
with open(ROOT / "proven_stack_results.json") as f:
    ps = json.load(f)
with open(ROOT / "ceiling_stack_results.json") as f:
    cs = json.load(f)

s6 = [r for r in ps["results"] if r["config"] == "S6_stack_orig_K150"][0]
c2 = [r for r in cs["results"] if r["config"] == "C2_stack_HY_K160"][0]

stack_pred = np.array(s6["ens_preds"])
ceil_pred = np.array(c2["ens_preds"])

# Verify
assert len(stack_pred) == len(y_true) == 36, f"Mismatch: {len(stack_pred)} vs {len(y_true)}"
assert len(ceil_pred) == len(y_true) == 36


def bootstrap_cis(y_true, y_pred, n_boot=10000, seed=42):
    """Compute bootstrap CIs for MAE and r."""
    rng = np.random.RandomState(seed)
    n = len(y_true)
    boot_maes, boot_rs = [], []
    for _ in range(n_boot):
        bi = rng.choice(n, size=n, replace=True)
        boot_maes.append(np.mean(np.abs(y_true[bi] - y_pred[bi])))
        if np.std(y_true[bi]) > 0 and np.std(y_pred[bi]) > 0:
            boot_rs.append(sp_stats.pearsonr(y_true[bi], y_pred[bi])[0])
        else:
            boot_rs.append(0.0)
    boot_maes = np.array(boot_maes)
    boot_rs = np.array(boot_rs)
    mae_ci = [np.percentile(boot_maes, 2.5), np.percentile(boot_maes, 97.5)]
    r_ci = [np.percentile(boot_rs, 2.5), np.percentile(boot_rs, 97.5)]
    return mae_ci, r_ci


def plot_scatter(y_true, y_pred, groups, title, path, mae_ci=None, r_ci=None):
    fig, ax = plt.subplots(1, 1, figsize=(7, 6))
    mn = min(y_true.min(), y_pred.min()) - 3
    mx = max(y_true.max(), y_pred.max()) + 3

    # Identity line
    ax.plot([mn, mx], [mn, mx], "k--", alpha=0.5, linewidth=1, label="Identity")

    # MCID band
    ax.fill_between([mn, mx], [mn - MCID_WORSEN, mx - MCID_WORSEN],
                    [mn + MCID_WORSEN, mx + MCID_WORSEN],
                    alpha=0.08, color="green", label=f"$\\pm${MCID_WORSEN} (MCID worsening)")

    # Scatter
    pd_mask = groups == "PD"
    hc_mask = groups == "HC"
    ax.scatter(y_true[pd_mask], y_pred[pd_mask], c="#d62728", s=55, alpha=0.85,
              edgecolors="k", linewidths=0.5, label=f"PD (n={pd_mask.sum()})", zorder=5)
    ax.scatter(y_true[hc_mask], y_pred[hc_mask], c="#1f77b4", s=55, alpha=0.85,
              edgecolors="k", linewidths=0.5, label=f"HC (n={hc_mask.sum()})", zorder=5)

    # Regression line + bootstrap CI
    slope, intercept = np.polyfit(y_true, y_pred, 1)
    x_line = np.linspace(mn, mx, 100)
    ax.plot(x_line, slope * x_line + intercept, "r-", alpha=0.6, linewidth=1.5,
            label=f"Regression (slope={slope:.2f})")

    rng = np.random.RandomState(42)
    n = len(y_true)
    boot_lines = []
    for _ in range(500):
        bi = rng.choice(n, size=n, replace=True)
        s, i_ = np.polyfit(y_true[bi], y_pred[bi], 1)
        boot_lines.append(s * x_line + i_)
    boot_lines = np.array(boot_lines)
    ax.fill_between(x_line, np.percentile(boot_lines, 2.5, axis=0),
                    np.percentile(boot_lines, 97.5, axis=0),
                    alpha=0.12, color="red", label="95% CI")

    mae = np.mean(np.abs(y_true - y_pred))
    r, p = sp_stats.pearsonr(y_true, y_pred)

    # Build annotation with CIs
    if mae_ci and r_ci:
        ann = f"MAE = {mae:.2f} [{mae_ci[0]:.2f}, {mae_ci[1]:.2f}]\nr = {r:.3f} [{r_ci[0]:.3f}, {r_ci[1]:.3f}]"
    else:
        ann = f"MAE = {mae:.2f}\nr = {r:.3f}"
    ax.text(0.05, 0.95, ann,
            transform=ax.transAxes, fontsize=10.5, verticalalignment="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="wheat", alpha=0.85),
            fontfamily="monospace")

    ax.set_xlabel("Actual UPDRS-III", fontsize=12)
    ax.set_ylabel("Predicted UPDRS-III", fontsize=12)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.legend(loc="lower right", fontsize=8.5)
    ax.set_xlim(mn, mx)
    ax.set_ylim(mn, mx)
    ax.set_aspect("equal")
    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


def plot_bland_altman(y_true, y_pred, groups, title, path):
    means = (y_true + y_pred) / 2
    diffs = y_pred - y_true
    bias = diffs.mean()
    sd = diffs.std(ddof=1)
    loa_lo = bias - 1.96 * sd
    loa_hi = bias + 1.96 * sd

    fig, ax = plt.subplots(1, 1, figsize=(7, 5))

    pd_mask = groups == "PD"
    hc_mask = groups == "HC"
    ax.scatter(means[pd_mask], diffs[pd_mask], c="#d62728", s=55, alpha=0.85,
              edgecolors="k", linewidths=0.5, label="PD", zorder=5)
    ax.scatter(means[hc_mask], diffs[hc_mask], c="#1f77b4", s=55, alpha=0.85,
              edgecolors="k", linewidths=0.5, label="HC", zorder=5)

    ax.axhline(bias, color="k", linestyle="-", linewidth=1.2,
              label=f"Bias = {bias:.2f}")
    ax.axhline(loa_lo, color="gray", linestyle="--", linewidth=1,
              label=f"95% LoA = [{loa_lo:.1f}, {loa_hi:.1f}]")
    ax.axhline(loa_hi, color="gray", linestyle="--", linewidth=1)

    ax.axhline(MCID_WORSEN, color="green", linestyle=":", alpha=0.5,
              label=f"$\\pm${MCID_WORSEN} (MCID worsening)")
    ax.axhline(-MCID_WORSEN, color="green", linestyle=":", alpha=0.5)
    ax.axhline(0, color="k", alpha=0.15, linewidth=0.5)

    ax.set_xlabel("Mean of Actual and Predicted UPDRS-III", fontsize=12)
    ax.set_ylabel("Predicted $-$ Actual (Residual)", fontsize=12)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.legend(loc="upper left", fontsize=8.5)
    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


# === Compute bootstrap CIs ===
print("Computing bootstrap CIs for stacking model (10k resamples)...")
stack_mae_ci, stack_r_ci = bootstrap_cis(y_true, stack_pred)
print(f"  Stacking: MAE={np.mean(np.abs(y_true - stack_pred)):.2f} [{stack_mae_ci[0]:.2f}, {stack_mae_ci[1]:.2f}]")
print(f"            r={sp_stats.pearsonr(y_true, stack_pred)[0]:.3f} [{stack_r_ci[0]:.3f}, {stack_r_ci[1]:.3f}]")

print("Computing bootstrap CIs for ceiling model (10k resamples)...")
ceil_mae_ci, ceil_r_ci = bootstrap_cis(y_true, ceil_pred)
print(f"  Ceiling:  MAE={np.mean(np.abs(y_true - ceil_pred)):.2f} [{ceil_mae_ci[0]:.2f}, {ceil_mae_ci[1]:.2f}]")
print(f"            r={sp_stats.pearsonr(y_true, ceil_pred)[0]:.3f} [{ceil_r_ci[0]:.3f}, {ceil_r_ci[1]:.3f}]")

# === Generate figures ===
plot_scatter(y_true, stack_pred, groups,
            "LGB+XGB Stacking (150 features): Predicted vs Actual UPDRS-III",
            FIG_DIR / "fig8_scatter.png",
            mae_ci=stack_mae_ci, r_ci=stack_r_ci)

plot_bland_altman(y_true, stack_pred, groups,
                 "LGB+XGB Stacking (150 features): Bland-Altman Agreement",
                 FIG_DIR / "fig9_residuals.png")

plot_scatter(y_true, ceil_pred, groups,
            "Ceiling (LGB+XGB Stacking + H&Y, K=160): Predicted vs Actual UPDRS-III",
            FIG_DIR / "fig8b_scatter_ceiling.png",
            mae_ci=ceil_mae_ci, r_ci=ceil_r_ci)

# === Print diagnostic stats for paper text ===
print("\n=== STACKING MODEL DIAGNOSTICS (for paper Section 4.6) ===")
residuals = stack_pred - y_true
bias = residuals.mean()
sd = residuals.std(ddof=1)
print(f"Bland-Altman: bias={bias:.2f}, LoA=[{bias-1.96*sd:.1f}, {bias+1.96*sd:.1f}]")
from scipy.stats import shapiro, skew, kurtosis
sw, sw_p = shapiro(residuals)
print(f"Shapiro-Wilk: stat={sw:.3f}, p={sw_p:.4f}")
print(f"Skewness: {skew(residuals):.2f}, Kurtosis: {kurtosis(residuals):.2f}")
rho, p_het = sp_stats.spearmanr(residuals**2, y_true)
print(f"Heteroscedasticity (Spearman |res|^2 vs true): rho={rho:.3f}, p={p_het:.4f}")

ae = np.abs(y_true - stack_pred)
print(f"\nWithin MCID 3.25: {np.mean(ae <= 3.25):.1%}")
print(f"Within MCID 4.63: {np.mean(ae <= 4.63):.1%}")

print("\nSeverity breakdown:")
for name, lo, hi in [("Mild 0-9", 0, 10), ("Moderate 10-19", 10, 20),
                      ("Mod-severe 20-34", 20, 35), ("Severe 35+", 35, 200)]:
    mask = (y_true >= lo) & (y_true < hi)
    if mask.sum() > 0:
        print(f"  {name} (n={mask.sum()}): MAE={ae[mask].mean():.2f}, bias={residuals[mask].mean():.2f}")

print("\n=== CEILING MODEL DIAGNOSTICS ===")
res_c = ceil_pred - y_true
bias_c = res_c.mean()
sd_c = res_c.std(ddof=1)
print(f"Bland-Altman: bias={bias_c:.2f}, LoA=[{bias_c-1.96*sd_c:.1f}, {bias_c+1.96*sd_c:.1f}]")

print("\nAll stats figures generated.")

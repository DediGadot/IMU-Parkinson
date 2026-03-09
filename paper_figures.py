"""
Generate all figures for the academic paper.
Produces publication-quality matplotlib figures.
Updated to reflect stacking results (MAE=6.89 best, 6.43 ceiling).

Note: figure filenames retain their historical numbering. The final
manuscript numbers are assigned in generate_html_paper.py based on order
of appearance in the paper.
"""
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# Style for academic papers
plt.rcParams.update({
    'font.size': 10,
    'font.family': 'serif',
    'axes.labelsize': 11,
    'axes.titlesize': 12,
    'xtick.labelsize': 9,
    'ytick.labelsize': 9,
    'legend.fontsize': 9,
    'figure.dpi': 300,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight',
    'axes.grid': True,
    'grid.alpha': 0.3,
})

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "figures"


def fig10_updrs_distribution():
    """Figure asset used in Methods: dev/test UPDRS-III distribution."""
    bins = ["0–5", "6–10", "11–20", "21–35", "36–50", "51+"]
    dev_counts = np.array([37, 15, 33, 41, 15, 1])
    test_counts = np.array([10, 2, 9, 11, 3, 1])
    x = np.arange(len(bins))
    width = 0.38

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(x - width / 2, dev_counts, width, color="#1f77b4", alpha=0.8,
           edgecolor="black", linewidth=0.5, label="Development (N=142)")
    ax.bar(x + width / 2, test_counts, width, color="#d62728", alpha=0.8,
           edgecolor="black", linewidth=0.5, label="Test (N=36)")

    for i, (dev, test) in enumerate(zip(dev_counts, test_counts)):
        ax.text(i - width / 2, dev + 0.6, f"{dev}", ha="center", va="bottom", fontsize=9)
        ax.text(i + width / 2, test + 0.6, f"{test}", ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(bins)
    ax.set_xlabel("UPDRS-III Bin")
    ax.set_ylabel("Subjects")
    ax.set_title("UPDRS-III Distribution Across Development and Test Sets")
    ax.legend()
    ax.set_ylim(0, 46)

    plt.tight_layout()
    plt.savefig(OUT_DIR / "fig10_updrs_dist.png")
    plt.close()
    print("  Fig 10 asset: UPDRS distribution")


def fig1_ablation_progression():
    """Figure 1: Progressive ablation study — MAE (bars) and r (line) across experiments."""
    # v2 results (XGBoost 200 features, MI-based feature selection)
    experiments = [
        ("E0\nBaseline", 9.64, 0.673),
        ("E1\nTask\nContrasts", 9.48, 0.715),
        ("E2\nEvents", 9.51, 0.694),
        ("E3\nContact", 9.44, 0.726),
        ("E4\nKinematics", 9.22, 0.741),
        ("E5\nTurns", 9.09, 0.745),
        ("E6\nTransitions", 9.15, 0.693),
        ("E7\nDistributions", 9.17, 0.734),
        ("E8\nClinical\nCovariates", 8.57, 0.802),
        ("E9\nWalkway\nOracle", 8.47, 0.819),
        ("E10\nWalkway\nDistillation", 8.25, 0.818),
        ("E11\nInsole", 8.21, 0.825),
        ("E12\nFused", 8.17, 0.815),
        ("E13\nCeiling\n(+H&Y)", 6.63, 0.850),
    ]

    names = [e[0] for e in experiments]
    maes = [e[1] for e in experiments]
    rs = [e[2] for e in experiments]

    # Color coding by phase
    phase_colors = ['#2196F3'] * 2 + ['#4CAF50'] * 4 + ['#FF9800'] * 3 + \
                   ['#9C27B0'] * 3 + ['#F44336'] * 2
    x = np.arange(len(names))

    fig, ax1 = plt.subplots(figsize=(13, 5.5))

    # --- MAE bars (left axis) with truncated bottom ---
    bar_bottom = 6.0  # start bars from 6.0 to show meaningful differences
    bar_heights = [m - bar_bottom for m in maes]
    bars = ax1.bar(x, bar_heights, bottom=bar_bottom, color=phase_colors,
                   alpha=0.8, edgecolor='white', linewidth=0.5, zorder=3)
    ax1.set_ylabel('Ensemble MAE (\u2193 better)', fontsize=11)
    ax1.set_title('Progressive Feature Ablation: UPDRS-III Prediction on WearGait-PD',
                   fontsize=13, fontweight='bold')

    # Reference lines
    ax1.axhline(y=7.97, color='gray', linestyle='--', alpha=0.5, linewidth=1,
                label='LGB MI-selection best (7.97)')
    ax1.axhline(y=6.89, color='red', linestyle='--', alpha=0.6, linewidth=1,
                label='LGB+XGB stacking best (6.89)')

    # MAE annotations
    for i, m in enumerate(maes):
        ax1.text(i, m + 0.08, f'{m:.2f}', ha='center', va='bottom',
                 fontsize=7, fontweight='bold', color='#333')
    ax1.set_ylim(5.8, 10.5)
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, fontsize=7)
    ax1.invert_yaxis()  # lower MAE = better = higher bar visually

    # --- Pearson r line (right axis) ---
    ax2 = ax1.twinx()
    ax2.plot(x, rs, 'o-', color='#333', linewidth=1.8, markersize=7, zorder=5,
             markerfacecolor='white', markeredgewidth=1.5, label='Pearson r')
    # Color the markers by phase
    for i, (r_val, c) in enumerate(zip(rs, phase_colors)):
        ax2.plot(x[i], r_val, 'o', color=c, markersize=6, zorder=6,
                 markeredgecolor='#333', markeredgewidth=1)
        ax2.text(i, r_val + 0.012, f'{r_val:.3f}', ha='center', va='bottom',
                 fontsize=6.5, color='#555')
    ax2.axhline(y=0.860, color='red', linestyle=':', alpha=0.4, linewidth=1,
                label='Stacking r = 0.860')
    ax2.set_ylabel('Pearson r (\u2191 better)', fontsize=11)
    ax2.set_ylim(0.62, 0.92)

    # Combined legend
    phase_patches = [
        mpatches.Patch(color='#2196F3', label='Phase 1: Aggregation'),
        mpatches.Patch(color='#4CAF50', label='Phase 2: Biomechanics'),
        mpatches.Patch(color='#FF9800', label='Phase 3: Context & Covariates'),
        mpatches.Patch(color='#9C27B0', label='Phase 4: Privileged Data'),
        mpatches.Patch(color='#F44336', label='Phase 5: Fusion'),
    ]
    import matplotlib.lines as mlines
    r_line = mlines.Line2D([], [], color='#333', marker='o', linewidth=1.5,
                           markersize=6, markerfacecolor='white',
                           markeredgewidth=1.5, label='Pearson r (right axis)')
    mae_ref = mlines.Line2D([], [], color='gray', linestyle='--', linewidth=1,
                             label='LGB MI-selection best (7.97)')
    stack_ref = mlines.Line2D([], [], color='red', linestyle='--', linewidth=1,
                               label='LGB+XGB stacking best (6.89)')
    all_handles = phase_patches + [r_line, mae_ref, stack_ref]
    ax1.legend(handles=all_handles, loc='upper left', ncol=2, fontsize=7,
               framealpha=0.9)

    plt.tight_layout()
    plt.savefig(OUT_DIR / 'fig1_ablation_progression.png')
    plt.close()
    print("  Fig 1: Ablation progression")


def fig2_booster_sweep():
    """Figure 2: Multi-booster sweep heatmap (MI-based selection, ablation phase). 4 model configs × 4 feature counts."""
    boosters = ['XGBoost', 'LightGBM', 'CatBoost', 'Cross-Booster']
    feat_counts = [100, 150, 200, 300]

    # Deployable results (MI-based feature selection)
    deploy_mae = np.array([
        [8.47, 8.54, 8.30, 8.72],  # XGBoost
        [8.15, 7.97, 8.15, 8.69],  # LightGBM
        [8.95, 8.75, 9.17, 9.03],  # CatBoost
        [8.46, 8.39, 8.52, 8.81],  # Cross
    ])

    # Ceiling results (MI-based feature selection)
    ceil_mae = np.array([
        [6.79, 6.72, 6.82, 7.07],  # XGBoost
        [7.02, 7.22, 7.11, 7.08],  # LightGBM
        [7.38, 7.60, 7.63, 7.81],  # CatBoost
        [6.90, 7.09, 7.15, 7.25],  # Cross
    ])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))

    # Deployable heatmap
    im1 = ax1.imshow(deploy_mae, cmap='RdYlGn_r', aspect='auto', vmin=7.8, vmax=9.2)
    ax1.set_xticks(range(4))
    ax1.set_xticklabels(feat_counts)
    ax1.set_yticks(range(4))
    ax1.set_yticklabels(boosters)
    ax1.set_xlabel('Number of Selected Features')
    ax1.set_title('(a) Deployable Model \u2014 MI Selection (Ens MAE)')
    for i in range(4):
        for j in range(4):
            val = deploy_mae[i, j]
            color = 'white' if val > 8.8 or val < 8.1 else 'black'
            weight = 'bold' if val == deploy_mae.min() else 'normal'
            ax1.text(j, i, f'{val:.2f}', ha='center', va='center', color=color,
                     fontsize=10, fontweight=weight)
    plt.colorbar(im1, ax=ax1, shrink=0.8)

    # Ceiling heatmap
    im2 = ax2.imshow(ceil_mae, cmap='RdYlGn_r', aspect='auto', vmin=6.5, vmax=8.0)
    ax2.set_xticks(range(4))
    ax2.set_xticklabels(feat_counts)
    ax2.set_yticks(range(4))
    ax2.set_yticklabels(boosters)
    ax2.set_xlabel('Number of Selected Features')
    ax2.set_title('(b) Ceiling Model with H&Y \u2014 MI Selection (Ens MAE)')
    for i in range(4):
        for j in range(4):
            val = ceil_mae[i, j]
            color = 'white' if val > 7.5 or val < 6.8 else 'black'
            weight = 'bold' if val == ceil_mae.min() else 'normal'
            ax2.text(j, i, f'{val:.2f}', ha='center', va='center', color=color,
                     fontsize=10, fontweight=weight)
    plt.colorbar(im2, ax=ax2, shrink=0.8)

    plt.tight_layout()
    plt.savefig(OUT_DIR / 'fig2_booster_sweep.png')
    plt.close()
    print("  Fig 2: Booster sweep heatmap")


def fig3_seed_stability():
    """Figure 3: Per-seed MAE distributions across pipeline stages."""
    # Ablation stages (MI-selection, from stats_report)
    seed_data = {
        'E0\nBaseline\n(MI sel.)': [10.34, 9.23, 10.10, 10.19, 9.26],
        'E8\n+Clinical\n(MI sel.)': [8.75, 8.67, 8.63, 8.92, 8.65],
        'E12\nFused\n(MI sel.)': [8.43, 8.03, 8.83, 9.02, 7.39],
        'LGB\nXGB sel.\nK=150': [7.745, 6.783, 7.334, 8.108, 6.687],
        'LGB+XGB\nStacking\nK=150': [6.739, 6.897, 6.849, 7.492, 6.676],
        'Ceiling\nStack+H&Y\nK=160': [6.206, 6.301, 7.052, 6.539, 6.370],
    }

    fig, ax = plt.subplots(figsize=(10, 5))
    positions = np.arange(len(seed_data))
    labels = list(seed_data.keys())
    data = [seed_data[k] for k in labels]

    bp = ax.boxplot(data, positions=positions, widths=0.5, patch_artist=True,
                    medianprops={'color': 'black', 'linewidth': 2})

    colors = ['#2196F3', '#FF9800', '#F44336', '#4CAF50', '#1B5E20', '#E91E63']
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    # Scatter individual seeds
    for i, vals in enumerate(data):
        ax.scatter([i] * len(vals), vals, color=colors[i], zorder=3, s=40,
                   edgecolors='black', linewidth=0.5)

    ax.set_xticks(positions)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel('Test MAE')
    ax.set_title('Per-Seed MAE Distribution Across Pipeline Stages')

    # Reference lines
    ax.axhline(y=7.97, color='gray', linestyle='--', alpha=0.4, label='MI-sel. best (7.97)')
    ax.axhline(y=6.89, color='red', linestyle='--', alpha=0.4, label='Stacking best (6.89)')
    ax.legend(fontsize=8)

    # Annotate std
    for i, vals in enumerate(data):
        std = np.std(vals)
        ax.annotate(f'\u03c3={std:.2f}', (i, max(vals) + 0.15), ha='center', fontsize=7,
                    color=colors[i])

    plt.tight_layout()
    plt.savefig(OUT_DIR / 'fig3_seed_stability.png')
    plt.close()
    print("  Fig 3: Seed stability")


def fig5_pipeline_diagram():
    """Figure 5: Pipeline/methodology diagram with stacking."""
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 6)
    ax.axis('off')

    # Boxes
    boxes = [
        (0.5, 3.5, 2.5, 2.0, 'Raw IMU\n13 sensors\n22 ch/sensor\n5 tasks', '#E3F2FD'),
        (3.5, 4.0, 2.5, 1.5, 'Sensor Features\n(time/freq domain)\n~1,752 features', '#E8F5E9'),
        (3.5, 2.0, 2.5, 1.5, 'Gait Events\n(foot contact,\nturns, transitions)', '#FFF3E0'),
        (6.5, 3.0, 2.5, 2.5, 'Feature\nAggregation\n+ Task Contrasts\n+ Clinical Covs\n+ Walkway Distill', '#F3E5F5'),
        (9.5, 3.5, 2.0, 2.0, 'XGBoost\nImportance\nSelection\n(top 150)', '#FFEBEE'),
        (12.0, 3.5, 1.5, 2.0, 'LGB+XGB\nStacking\n(5-fold OOF\n+ Ridge meta)', '#FFF9C4'),
    ]

    for x_, y_, w, h, text, color in boxes:
        rect = mpatches.FancyBboxPatch((x_, y_), w, h, boxstyle="round,pad=0.1",
                                        facecolor=color, edgecolor='black', linewidth=1.5)
        ax.add_patch(rect)
        ax.text(x_ + w/2, y_ + h/2, text, ha='center', va='center', fontsize=8,
                fontweight='bold')

    # Arrows
    arrow_props = dict(arrowstyle='->', color='black', lw=1.5)
    ax.annotate('', xy=(3.4, 4.5), xytext=(3.0, 4.5), arrowprops=arrow_props)
    ax.annotate('', xy=(3.4, 2.5), xytext=(3.0, 3.0), arrowprops=arrow_props)
    ax.annotate('', xy=(6.4, 4.0), xytext=(6.0, 4.5), arrowprops=arrow_props)
    ax.annotate('', xy=(6.4, 3.5), xytext=(6.0, 2.5), arrowprops=arrow_props)
    ax.annotate('', xy=(9.4, 4.5), xytext=(9.0, 4.5), arrowprops=arrow_props)
    ax.annotate('', xy=(11.9, 4.5), xytext=(11.5, 4.5), arrowprops=arrow_props)

    # Output
    ax.text(12.75, 3.2, 'MAE = 6.89\nr = 0.860', ha='center', fontsize=10,
            fontweight='bold', color='#D32F2F')

    ax.set_title('Proposed Pipeline for UPDRS-III Regression from Body-Worn IMUs',
                 fontsize=13, fontweight='bold', pad=20)

    plt.tight_layout()
    plt.savefig(OUT_DIR / 'fig5_pipeline.png')
    plt.close()
    print("  Fig 5: Pipeline diagram")


def fig6_comparison_with_sota():
    """Figure 6: Comparison with published results (cross-dataset)."""
    studies = [
        ("Hssayeni 2021\n(N=24, LOOCV)", 5.95, 0.74, '#FFB74D'),
        ("Shuqair 2024\n(N=24, LOOCV)", None, 0.89, '#FFB74D'),
        ("Ours: Deployable\n(N=178, held-out)", 6.89, 0.860, '#4CAF50'),
        ("Ours: Ceiling\n(N=178, held-out)", 6.43, 0.848, '#2196F3'),
    ]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))

    # MAE comparison (only studies with MAE)
    mae_studies = [(s[0], s[1], s[3]) for s in studies if s[1] is not None]
    x = np.arange(len(mae_studies))
    ax1.bar(x, [s[1] for s in mae_studies], color=[s[2] for s in mae_studies],
            alpha=0.8, edgecolor='black', linewidth=0.5)
    ax1.set_xticks(x)
    ax1.set_xticklabels([s[0] for s in mae_studies], fontsize=8)
    ax1.set_ylabel('MAE (\u2193 better)')
    ax1.set_title('(a) MAE Comparison')
    for i, s in enumerate(mae_studies):
        ax1.text(i, s[1] + 0.1, f'{s[1]:.2f}', ha='center', fontweight='bold')

    # r comparison
    r_studies = [(s[0], s[2], s[3]) for s in studies if s[2] is not None]
    x = np.arange(len(r_studies))
    ax2.bar(x, [s[1] for s in r_studies], color=[s[2] for s in r_studies],
            alpha=0.8, edgecolor='black', linewidth=0.5)
    ax2.set_xticks(x)
    ax2.set_xticklabels([s[0] for s in r_studies], fontsize=8)
    ax2.set_ylabel('Pearson r (\u2191 better)')
    ax2.set_title('(b) Correlation Comparison')
    for i, s in enumerate(r_studies):
        ax2.text(i, s[1] + 0.01, f'{s[1]:.3f}', ha='center', fontweight='bold')

    # Add annotations about evaluation rigor
    ax1.annotate('LOOCV\n(N=24)', (0, 4.5), fontsize=7, color='gray', ha='center')
    ax1.annotate('Held-out\ntest set', (1, 5.5), fontsize=7, color='gray', ha='center')

    plt.tight_layout()
    plt.savefig(OUT_DIR / 'fig6_sota_comparison.png')
    plt.close()
    print("  Fig 6: SOTA comparison")


def fig7_distillation_vs_oracle():
    """Figure 7: Walkway distillation vs oracle comparison."""
    configs = ['E8\nBase\n(no walkway)', 'E9\nWalkway\nOracle\n(135/178)', 'E10\nWalkway\nDistillation\n(178/178)']
    maes = [8.57, 8.47, 8.25]
    rs = [0.802, 0.819, 0.818]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 4))

    colors = ['#607D8B', '#FF9800', '#4CAF50']
    x = np.arange(3)

    ax1.bar(x, maes, color=colors, alpha=0.8, edgecolor='black', linewidth=0.5)
    ax1.set_xticks(x)
    ax1.set_xticklabels(configs, fontsize=8)
    ax1.set_ylabel('Ensemble MAE')
    ax1.set_title('(a) MAE: Distillation Beats Oracle')
    for i, m in enumerate(maes):
        ax1.text(i, m + 0.02, f'{m:.2f}', ha='center', fontweight='bold')

    ax2.bar(x, rs, color=colors, alpha=0.8, edgecolor='black', linewidth=0.5)
    ax2.set_xticks(x)
    ax2.set_xticklabels(configs, fontsize=8)
    ax2.set_ylabel('Pearson r')
    ax2.set_title('(b) Correlation')
    for i, r in enumerate(rs):
        ax2.text(i, r + 0.002, f'{r:.3f}', ha='center', fontweight='bold')

    plt.tight_layout()
    plt.savefig(OUT_DIR / 'fig7_distillation.png')
    plt.close()
    print("  Fig 7: Distillation vs oracle")


def main():
    OUT_DIR.mkdir(exist_ok=True)
    print("Generating paper figures...")
    fig10_updrs_distribution()
    fig1_ablation_progression()
    fig2_booster_sweep()
    fig3_seed_stability()
    fig5_pipeline_diagram()
    fig6_comparison_with_sota()
    fig7_distillation_vs_oracle()
    print(f"\nAll figures saved to {OUT_DIR}/")


if __name__ == "__main__":
    main()

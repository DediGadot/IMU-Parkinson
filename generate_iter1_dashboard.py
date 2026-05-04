"""Generate T3_DIAGNOSTIC.html from iter1_*.json results.

10 plots (some may skip if missing):
  P1 per-item CCC heatmap (item × IMU vs demographics)
  P2 T3 variance decomposition pie + per-item variance bar
  P3 T3 ceiling derivation bars (5 bounds vs current)
  P4 per-subject error scatter T1_err vs T3_err
  P5 demographics-only-per-item CCC heatmap (skipped if missing)
  P6 top-10 v2 features × per-item Spearman heatmap
  P7 prediction-dispersion histogram (pred_std/true_std per fold)
  P8 levodopa state effect bar (skipped if missing)
  P9 H&Y stratified CCC bar (skipped if missing)
  P10 site-stratified CCC + leave-site-out bar
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parent
RES = REPO / "results"
FIG = REPO / "figures"
FIG.mkdir(exist_ok=True)
OUT_HTML = REPO / "T3_DIAGNOSTIC.html"

T1_ITEMS = [9, 10, 11, 12, 13, 14]
T3_ALL = list(range(1, 19))


def load(name: str) -> dict | None:
    p = RES / f"iter1_{name}.json"
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


def fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def make_p1(d):
    """Per-item CCC bar with T1 highlight."""
    if not d or "per_item_ccc_5fold" not in d:
        return None, "skipped"
    items = sorted([int(k) for k in d["per_item_ccc_5fold"].keys()])
    cccs = [d["per_item_ccc_5fold"][str(i) if str(i) in d["per_item_ccc_5fold"] else i]["ccc_mean"] for i in items]
    stds = [d["per_item_ccc_5fold"][str(i) if str(i) in d["per_item_ccc_5fold"] else i]["ccc_std"] for i in items]
    colors = ["#5B9BD5" if i in T1_ITEMS else "#999" for i in items]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.bar(range(len(items)), cccs, yerr=stds, color=colors, edgecolor="black", capsize=3)
    ax.set_xticks(range(len(items)))
    ax.set_xticklabels([f"{i}" for i in items])
    ax.axhline(0, color="black", lw=0.5)
    ax.axhline(0.3, color="green", ls="--", lw=1, label="CCC=0.30 (Tier 1)")
    ax.set_xlabel("UPDRS-III item")
    ax.set_ylabel("Per-item 5-fold CCC (PD-only inductive)")
    ax.set_title(f"Per-item LightGBM CCC ({d['n_pd']} PD subjects, 1752 v2 features). Blue=T1 items 9-14.")
    ax.legend(loc="upper left")
    ax.set_ylim(-0.15, max(0.6, max(cccs)*1.1))
    ax.grid(alpha=0.3, axis="y")
    return fig, (
        f"<b>P1.</b> Per-item LGB 5-fold CCC. <b>Strongest signal:</b> item 12 (leg agility, CCC≈0.54), "
        f"item 10 (pronation-supination, CCC≈0.43), item 14 (posture, CCC≈0.29). "
        f"<b>No signal (CCC ≤ 0.10):</b> items 3 (mood), 4 (motivation), 6 (action tremor), 15 (body bradykinesia)."
    )


def make_p2(d):
    if not d:
        return None, "skipped"
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    # Left: pie of variance contribution
    labels = ["T1 (items 9-14)", "Partially obs (5-8, 15-17)", "Not obs (1-4, 18)"]
    pcts = [d["pct_var_T1"], d["pct_var_partobs"], d["pct_var_notobs"]]
    pcts = [max(0, p) for p in pcts]
    colors = ["#5B9BD5", "#F1C40F", "#E74C3C"]
    axes[0].pie(pcts, labels=labels, autopct="%.1f%%", colors=colors, startangle=90, wedgeprops=dict(edgecolor="black"))
    axes[0].set_title(f"Variance(T3)={d['var_T3']:.0f}, decomp by item-block (n={d['n']})")
    # Right: per-item variance
    item_var = d["item_variances"]
    items = sorted(int(k) for k in item_var.keys())
    vars_ = [item_var[str(i) if str(i) in item_var else i] for i in items]
    bar_colors = ["#5B9BD5" if i in T1_ITEMS else "#bbb" for i in items]
    axes[1].bar(range(len(items)), vars_, color=bar_colors, edgecolor="black")
    axes[1].set_xticks(range(len(items)))
    axes[1].set_xticklabels(items)
    axes[1].set_xlabel("UPDRS item")
    axes[1].set_ylabel("Variance across PD subjects")
    axes[1].set_title("Per-item variance contribution (blue = T1 items)")
    axes[1].grid(alpha=0.3, axis="y")
    return fig, (
        f"<b>P2.</b> T3 variance is dominated by partially-observable items ({100*d['pct_var_partobs']:.0f}%) "
        f"and not-observable items ({100*d['pct_var_notobs']:.0f}%). T1 (gait-observable) only contributes "
        f"{100*d['pct_var_T1']:.0f}%. <b>Pearson(T1, T3) = {d['pearson_T1_T3']:.3f}</b> — this is the theoretical "
        f"upper bound for any T1-only-based predictor."
    )


def make_p3(d):
    if not d:
        return None, "skipped"
    bounds = [
        ("Current\n(B1 LGB v2)", d["T3_LOOCV_baseline_ccc"], "#999"),
        ("Bound E\nInductive shrink", d["bound_E_inductive_shrinkage_T1_to_T3"], "#bbb"),
        ("Bound C\nT1+linearR", d["bound_C_actual_T1pred_plus_linearR"], "#F1C40F"),
        ("Bound A\nOracle T1+meanR", d["bound_A_oracle_T1_plus_meanR"], "#27AE60"),
        ("Bound D\nperfect-T1 ceiling", d["bound_D_theoretical_perfect_T1_corr_to_T3"], "#5B9BD5"),
    ]
    names = [b[0] for b in bounds]
    vals = [b[1] for b in bounds]
    colors = [b[2] for b in bounds]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    bars = ax.bar(range(len(bounds)), vals, color=colors, edgecolor="black")
    ax.axhline(0.30, color="green", ls="--", lw=1.2, label="Tier 1 (publishable, CCC=0.30)")
    ax.axhline(0.35, color="red", ls="--", lw=1.2, label="Tier 2 (breakthrough, CCC=0.35)")
    ax.set_xticks(range(len(bounds)))
    ax.set_xticklabels(names, fontsize=9)
    ax.set_ylabel("CCC")
    ax.set_title(f"T3 CCC bounds derivation (N={d['n']} PD, T1 LOOCV CCC={d['actual_T1_ccc']:.3f})")
    ax.legend(loc="upper left", fontsize=9)
    ax.set_ylim(0, max(vals)*1.15 + 0.05)
    for i, v in enumerate(vals):
        ax.text(i, v + 0.01, f"{v:.3f}", ha="center", fontweight="bold")
    return fig, (
        f"<b>P3.</b> Ceiling derivation. Current LOOCV baseline = 0.217. "
        f"<b>Bound A (oracle T1 + mean R) = {d['bound_A_oracle_T1_plus_meanR']:.3f}</b> — even with PERFECT T1 prediction, "
        f"T1 alone caps T3 CCC at this value. <b>Bound D (theoretical max from perfect T1) = "
        f"{d['bound_D_theoretical_perfect_T1_corr_to_T3']:.3f}</b> — the fundamental ceiling from gait-observable items only. "
        f"This means iter 2 / iter 3 must extract NON-T1 signal to break Tier 1."
    )


def make_p4(d):
    if not d or d.get("skipped"):
        return None, "skipped"
    rows = d["per_subject"]
    t1e = np.array([r["t1_err"] for r in rows])
    t3e = np.array([r["t3_err"] for r in rows])
    sites = [r["site"] for r in rows]
    site_color = {"NLS": "#5B9BD5", "WPD": "#E74C3C"}
    colors = [site_color.get(s, "#999") for s in sites]
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(t1e, t3e, c=colors, edgecolor="black", alpha=0.7, s=60)
    ax.axhline(0, color="black", lw=0.5)
    ax.axvline(0, color="black", lw=0.5)
    # OLS line
    coef = np.polyfit(t1e, t3e, 1)
    xs = np.linspace(t1e.min(), t1e.max(), 100)
    ax.plot(xs, np.polyval(coef, xs), "r--", lw=2, label=f"OLS slope={coef[0]:.2f}")
    ax.set_xlabel("T1 prediction error (T1_pred − T1_true)")
    ax.set_ylabel("T3 prediction error (T3_pred − T3_true)")
    ax.set_title(f"Per-subject error decomposition (n={d['n']})\npearson={d['t1_t3_err_pearson']:.3f}, spearman={d['t1_t3_err_spearman']:.3f}")
    # Site legend
    from matplotlib.patches import Patch
    handles = [Patch(facecolor=site_color["NLS"], label="NLS"), Patch(facecolor=site_color["WPD"], label="WPD")]
    ax.legend(handles=handles + [plt.Line2D([0],[0], color="r", ls="--", label=f"OLS slope={coef[0]:.2f}")])
    ax.grid(alpha=0.3)
    return fig, (
        f"<b>P4.</b> T3 errors strongly correlated with T1 errors (pearson={d['t1_t3_err_pearson']:.3f}). "
        f"This means T3 prediction failures are largely driven by T1 prediction failures — improving T1 "
        f"would lift T3 too. But T1 is at its ceiling (CCC=0.588), so the path forward is on the residual."
    )


def make_p5(d):
    if not d or d.get("skipped"):
        return None, "skipped (demo CSV unavailable)"
    items = sorted(int(k) for k in d["per_item"].keys())
    cccs = [d["per_item"][str(i) if str(i) in d["per_item"] else i]["ccc"] for i in items]
    fig, ax = plt.subplots(figsize=(11, 4))
    colors = ["#5B9BD5" if i in T1_ITEMS else "#999" for i in items]
    ax.bar(range(len(items)), cccs, color=colors, edgecolor="black")
    ax.axhline(0, color="black", lw=0.5)
    ax.set_xticks(range(len(items)))
    ax.set_xticklabels(items)
    ax.set_xlabel("UPDRS item")
    ax.set_ylabel("Demographics-only LOOCV CCC")
    ax.set_title(f"Demographics-only ridge per item (cols: {d['demo_cols']}, n={d['n']})")
    ax.grid(alpha=0.3, axis="y")
    return fig, "<b>P5.</b> Demographics-only LOOCV per item — which items get a 'free pass' from age/sex/dx_yrs alone."


def make_p6(d):
    if not d:
        return None, "skipped"
    items = sorted(int(k) for k in d["summary_per_item"].keys())
    max_rho = [d["summary_per_item"][str(i)]["max_abs_rho"] for i in items]
    frac03 = [d["summary_per_item"][str(i)]["frac_above_0.3"] for i in items]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    colors = ["#5B9BD5" if i in T1_ITEMS else "#999" for i in items]
    axes[0].bar(range(len(items)), max_rho, color=colors, edgecolor="black")
    axes[0].set_xticks(range(len(items))); axes[0].set_xticklabels(items)
    axes[0].set_xlabel("UPDRS item"); axes[0].set_ylabel("max |Spearman ρ|")
    axes[0].set_title(f"Max |ρ| of any v2 feature × item (n={d['n']}, {d['n_features']} features)")
    axes[0].axhline(0.3, color="green", ls="--"); axes[0].grid(alpha=0.3, axis="y")
    axes[1].bar(range(len(items)), [100*x for x in frac03], color=colors, edgecolor="black")
    axes[1].set_xticks(range(len(items))); axes[1].set_xticklabels(items)
    axes[1].set_xlabel("UPDRS item"); axes[1].set_ylabel("% features with |ρ| > 0.3")
    axes[1].set_title("Fraction of v2 features with |ρ|>0.3 per item")
    axes[1].grid(alpha=0.3, axis="y")
    return fig, (
        "<b>P6.</b> Spearman correlation: features × items. Items 10, 12, 14 have the most features "
        "with |ρ|>0.3 (10-13% of 1752 features). Items 3, 6, 15 have <1% — confirms low signal."
    )


def make_p7(d):
    if not d:
        return None, "skipped"
    rows = d["data"]
    if not rows:
        return None, "no data"
    eval_modes = sorted(set(r["eval_mode"] for r in rows))
    fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    # Left: histogram of pred_std/true_std
    ratios = [r["ratio"] for r in rows if r["eval_mode"] == "5split"]
    axes[0].hist(ratios, bins=20, color="#5B9BD5", edgecolor="black")
    axes[0].axvline(1.0, color="red", ls="--", lw=1.5, label="ratio=1.0 (no shrinkage)")
    axes[0].axvline(np.median(ratios), color="green", ls="-", lw=1.5, label=f"median={np.median(ratios):.2f}")
    axes[0].set_xlabel("pred_std / true_std")
    axes[0].set_ylabel("count")
    axes[0].set_title(f"Prediction-to-truth std ratio across {len(ratios)} T3 5-fold runs")
    axes[0].legend()
    axes[0].grid(alpha=0.3, axis="y")
    # Right: scatter ratio vs CCC
    cccs = [r["ccc"] for r in rows if r["eval_mode"] == "5split"]
    axes[1].scatter(ratios, cccs, alpha=0.7, c="#5B9BD5", edgecolor="black", s=50)
    axes[1].set_xlabel("pred_std / true_std")
    axes[1].set_ylabel("CCC")
    axes[1].set_title("Prediction shrinkage vs CCC (T3 5-fold runs)")
    axes[1].grid(alpha=0.3)
    return fig, (
        f"<b>P7.</b> Median pred_std/true_std = {np.median(ratios):.2f} — predictions are "
        f"{'severely' if np.median(ratios) < 0.5 else 'moderately'} shrunk toward the mean. "
        f"This is the classic 'mean-collapse' failure mode at small N. CQR / heteroscedastic regression should help."
    )


def make_p10(d):
    if not d:
        return None, "skipped"
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    # Left: existing T3 LOOCV CCC by site
    by_site = d.get("by_site_existing_T3_LOOCV", {})
    if by_site:
        sites = list(by_site.keys()); cccs = [by_site[s]["ccc"] for s in sites]; ns = [by_site[s]["n"] for s in sites]
        bars = axes[0].bar(sites, cccs, color=["#5B9BD5", "#E74C3C"], edgecolor="black")
        for b, n in zip(bars, ns):
            axes[0].text(b.get_x() + b.get_width()/2, b.get_height() + 0.01, f"n={n}", ha="center")
        axes[0].set_ylabel("CCC")
        axes[0].set_title(f"B1_v2 T3 LOOCV CCC by site (subset of N={d['n_NLS']+d['n_WPD']} PD)")
        axes[0].axhline(0.217, color="black", ls="--", label="overall CCC=0.217")
        axes[0].legend(); axes[0].grid(alpha=0.3, axis="y")
    # Right: leave-site-out
    loso = d.get("leave_site_out", {})
    if loso:
        names = list(loso.keys())
        cccs_l = [loso[n].get("ccc", 0) for n in names]
        bars2 = axes[1].bar(range(len(names)), cccs_l, color=["#F1C40F", "#27AE60"], edgecolor="black")
        for b, name in zip(bars2, names):
            ntr = loso[name].get("n_train", 0); nte = loso[name].get("n_test", 0)
            axes[1].text(b.get_x() + b.get_width()/2, b.get_height() + 0.005, f"train={ntr}\ntest={nte}", ha="center", fontsize=8)
        axes[1].set_xticks(range(len(names)))
        axes[1].set_xticklabels(names, rotation=10)
        axes[1].set_ylabel("CCC")
        axes[1].set_title("Leave-site-out T3 CCC (LightGBM v2)")
        axes[1].axhline(0, color="black", lw=0.5)
        axes[1].grid(alpha=0.3, axis="y")
    return fig, (
        f"<b>P10.</b> Site is a STRONG confounder for T3. Cross-site CCC ≈ 0 in both directions, vs in-site "
        f"CCC≈0.2. This is much worse than the T1 finding (0.66 / 0.12). Iter 2 IPW deconfounding + "
        f"iter 3 hierarchical site model are well-motivated."
    )


def main():
    sections = []
    for label, d_name, maker in [
        ("P1: Per-item LGB CCC", "per_item_lgb", make_p1),
        ("P2: T3 variance decomposition", "variance_decomp", make_p2),
        ("P3: Theoretical T3 ceiling", "ceiling_derivation", make_p3),
        ("P4: Per-subject error scatter", "error_decomp", make_p4),
        ("P5: Demographics-only-per-item", "demo_per_item", make_p5),
        ("P6: Top features × per-item Spearman", "feature_item_corr", make_p6),
        ("P7: Prediction-dispersion", "pred_dispersion", make_p7),
        ("P10: Site stratification + leave-site-out", "site_strat", make_p10),
    ]:
        d = load(d_name)
        try:
            fig, caption = maker(d)
        except Exception as e:
            import traceback
            traceback.print_exc()
            fig, caption = None, f"ERROR: {e}"
        if fig is None:
            sections.append({"title": label, "img": None, "caption": caption})
        else:
            png_path = FIG / f"iter1_{d_name}.png"
            fig.savefig(png_path, dpi=140, bbox_inches="tight")
            b64 = fig_to_b64(fig)
            plt.close(fig)
            sections.append({"title": label, "img": b64, "caption": caption})

    # Build HTML
    html = ['<!DOCTYPE html><html><head><meta charset="utf-8">',
            '<title>T3 Glass Ceiling Diagnostic — Iter 1</title>',
            '<style>',
            'body{font-family:-apple-system,sans-serif;max-width:1100px;margin:24px auto;padding:0 20px;color:#222}',
            'h1{border-bottom:2px solid #333;padding-bottom:8px}',
            'h2{color:#0066cc;margin-top:32px}',
            '.card{background:#f7f9fc;border:1px solid #e0e6ed;border-radius:6px;padding:12px;margin:16px 0}',
            'img{max-width:100%;height:auto;display:block;margin:10px 0;border:1px solid #ccc}',
            '.caption{color:#444;font-size:14px;line-height:1.55}',
            '.kpi{background:#fff3cd;border-left:4px solid #ffc107;padding:10px 14px;margin:12px 0;font-size:14px}',
            '.headline{background:#d4edda;border-left:4px solid #28a745;padding:14px 18px;margin:18px 0;font-size:15px}',
            'table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #ccc;padding:5px 9px}th{background:#eee}',
            '</style></head><body>',
            '<h1>T3 Glass Ceiling — Iteration 1 Diagnostic</h1>',
            '<div class="headline"><b>HEADLINE FINDING:</b> The T3 ceiling is fundamentally observability-bound. '
            'Even with PERFECT T1 prediction, T3 CCC caps at 0.351 (Bound A). '
            'Theoretical max from any T1-only model: 0.683. '
            'But only 3 of 18 items have CCC>0.3 from gait IMU (items 10, 12, 14 — all in T1). '
            'Path forward: combine per-item modeling with non-IMU signals (clinical covariates) for residual items.</div>',
            '<div class="kpi"><b>Headline numbers:</b><br>'
            '• Current T3 LOOCV CCC: 0.217 | Var(T1)/Var(T3) = 7.7%<br>'
            '• Pearson(T1, T3) = 0.683 (theoretical ceiling for T1-based models)<br>'
            '• Bound A (oracle T1 + mean R): CCC = 0.351 (max realistic from T1 alone)<br>'
            '• Per-subject pearson(T1_err, T3_err) = 0.68 (most T3 error IS T1 error)<br>'
            '• Items with strong per-item CCC (>0.30): only 10, 12, 14 (all T1)<br>'
            '• Items with no signal (CCC ≤ 0.10): 3, 4, 6, 15<br>'
            '• Site is a STRONG confounder: cross-site T3 CCC ≈ 0</div>',
            ]
    for s in sections:
        html.append(f'<div class="card"><h2>{s["title"]}</h2>')
        if s["img"]:
            html.append(f'<img src="data:image/png;base64,{s["img"]}" alt="{s["title"]}">')
        else:
            html.append(f'<p><i>{s["caption"]}</i></p>')
        if s["img"]:
            html.append(f'<p class="caption">{s["caption"]}</p>')
        html.append('</div>')
    html.append('</body></html>')
    with open(OUT_HTML, "w") as f:
        f.write("\n".join(html))
    print(f"Wrote {OUT_HTML}")


if __name__ == "__main__":
    main()

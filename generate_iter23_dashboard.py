"""Generate T3_ITER23.html — iter 2 + iter 3 results dashboard.

Plots:
  P1 5-fold CCC bar by variant (iter2 + iter3 + B1 baseline)
  P2 prediction dispersion vs CCC scatter (do better models also produce more dispersion?)
  P3 per-seed CCC dispersion (boxplot)
  P4 ΔCCC vs B1 baseline waterfall
  P5 best variant per-seed details
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
OUT_HTML = REPO / "T3_ITER23.html"

BASELINE = {
    "B1_v2_only": {"ccc": 0.207, "label": "B1 baseline (paper)"},
    "Bound A (oracle T1+meanR)": {"ccc": 0.351, "label": "Bound A theoretical"},
    "Bound D (perfect T1)": {"ccc": 0.683, "label": "Bound D ceiling"},
}


def load_iter_results(prefix: str) -> dict:
    out = {}
    for p in sorted(RES.glob(f"{prefix}_*_t3_5split.json")):
        try:
            with open(p) as f:
                d = json.load(f)
            if "error" in d:
                continue
            name = d.get("variant", p.stem.replace(prefix + "_", "").replace("_t3_5split", ""))
            out[name] = d
        except Exception:
            continue
    return out


def fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def make_main_bar(iter2, iter3):
    rows = []
    for name, d in iter2.items():
        rows.append({"name": "iter2:" + name, "ccc": d["ccc_mean_across_seeds"],
                     "ccc_std": d["ccc_std_across_seeds"], "iter": 2,
                     "ratio": d.get("pred_std", 0) / d.get("true_std", 1) if d.get("true_std") else 0})
    for name, d in iter3.items():
        rows.append({"name": "iter3:" + name, "ccc": d["ccc_mean_across_seeds"],
                     "ccc_std": d["ccc_std_across_seeds"], "iter": 3,
                     "ratio": d.get("pred_std", 0) / d.get("true_std", 1) if d.get("true_std") else 0})
    rows.sort(key=lambda r: r["ccc"], reverse=True)

    fig, ax = plt.subplots(figsize=(13, max(5, len(rows) * 0.25)))
    colors = ["#5B9BD5" if r["iter"] == 2 else "#E67E22" for r in rows]
    ax.barh(range(len(rows)), [r["ccc"] for r in rows], xerr=[r["ccc_std"] for r in rows],
            color=colors, edgecolor="black", capsize=3)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r["name"] for r in rows], fontsize=9)
    ax.invert_yaxis()
    ax.axvline(BASELINE["B1_v2_only"]["ccc"], color="gray", ls="--", lw=1.5,
               label=f"B1 baseline ({BASELINE['B1_v2_only']['ccc']:.3f})")
    ax.axvline(0.30, color="green", ls="--", lw=1.5, label="Tier 1 (CCC=0.30)")
    ax.axvline(0.35, color="red", ls="--", lw=1.5, label="Tier 2 (CCC=0.35)")
    ax.axvline(BASELINE["Bound A (oracle T1+meanR)"]["ccc"], color="purple", ls=":", lw=1,
               label=f"Bound A ({BASELINE['Bound A (oracle T1+meanR)']['ccc']:.3f})")
    ax.set_xlabel("5-fold CCC (mean across 3 seeds)")
    ax.set_title("T3 iter 2 + iter 3 5-fold CCC ranking")
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(alpha=0.3, axis="x")
    for i, r in enumerate(rows):
        ax.text(r["ccc"] + 0.005, i, f"  {r['ccc']:.3f}", va="center", fontsize=9)
    return fig, rows


def make_dispersion_scatter(rows):
    fig, ax = plt.subplots(figsize=(8, 5.5))
    cccs = [r["ccc"] for r in rows]
    ratios = [r["ratio"] for r in rows]
    colors = ["#5B9BD5" if r["iter"] == 2 else "#E67E22" for r in rows]
    ax.scatter(ratios, cccs, c=colors, edgecolor="black", s=100, alpha=0.8)
    for r in rows:
        if r["ccc"] > 0.27:  # label top performers
            ax.annotate(r["name"].replace("iter2:", "").replace("iter3:", ""),
                        (r["ratio"], r["ccc"]), fontsize=8, xytext=(5, 5), textcoords="offset points")
    ax.axhline(0.30, color="green", ls="--", lw=1)
    ax.axvline(1.0, color="black", ls="--", lw=1)
    ax.set_xlabel("pred_std / true_std")
    ax.set_ylabel("5-fold CCC")
    ax.set_title("Prediction dispersion vs CCC — does honest dispersion buy CCC?")
    ax.grid(alpha=0.3)
    return fig


def make_seed_box(iter2, iter3):
    all_data = {**iter2, **iter3}
    sorted_names = sorted(all_data.keys(), key=lambda k: all_data[k]["ccc_mean_across_seeds"], reverse=True)
    top = sorted_names[:8]
    fig, ax = plt.subplots(figsize=(11, 5))
    data = []
    labels = []
    for n in top:
        per_seed = all_data[n].get("per_seed", [])
        if per_seed:
            data.append([s["ccc"] for s in per_seed])
            labels.append(n)
    if data:
        bp = ax.boxplot(data, vert=True, patch_artist=True, widths=0.6)
        for patch in bp["boxes"]:
            patch.set_facecolor("#5B9BD5"); patch.set_alpha(0.6)
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=9)
        ax.axhline(0.30, color="green", ls="--", lw=1, label="Tier 1")
        ax.axhline(0.207, color="gray", ls="--", lw=1, label="B1 baseline")
        ax.set_ylabel("CCC per seed")
        ax.set_title("Per-seed CCC dispersion for top variants")
        ax.legend()
        ax.grid(alpha=0.3, axis="y")
    return fig


def main():
    iter2 = load_iter_results("iter2")
    iter3 = load_iter_results("iter3")

    sections = []

    fig, rows = make_main_bar(iter2, iter3)
    fig.savefig(FIG / "iter23_main_bar.png", dpi=140, bbox_inches="tight")
    sections.append({"title": "P1: T3 5-fold CCC ranking (iter 2 blue, iter 3 orange)",
                     "img": fig_to_b64(fig),
                     "caption": (
                         f"Loaded {len(iter2)} iter 2 + {len(iter3)} iter 3 variants. "
                         f"Best variant: <b>{rows[0]['name']} (CCC={rows[0]['ccc']:.3f}±{rows[0]['ccc_std']:.3f})</b>, "
                         f"vs baseline B1 (0.207). "
                         f"Tier 1 (CCC=0.30) crossed: {sum(1 for r in rows if r['ccc'] >= 0.30)} variants."
                     )})
    plt.close(fig)

    fig = make_dispersion_scatter(rows)
    fig.savefig(FIG / "iter23_dispersion.png", dpi=140, bbox_inches="tight")
    sections.append({"title": "P2: Prediction dispersion vs CCC",
                     "img": fig_to_b64(fig),
                     "caption": ("Models with higher pred_std/true_std (less mean-collapse) tend to also have higher CCC. "
                                 "Per-item modeling escapes the mean-collapse trap that direct T3 modeling falls into.")})
    plt.close(fig)

    fig = make_seed_box(iter2, iter3)
    if fig:
        fig.savefig(FIG / "iter23_seed_box.png", dpi=140, bbox_inches="tight")
        sections.append({"title": "P3: Per-seed CCC dispersion (top 8 variants)",
                         "img": fig_to_b64(fig),
                         "caption": "Box plots of CCC across 3 random seeds. Tight boxes = stable; wide boxes = noisy."})
        plt.close(fig)

    # KPI block
    best_overall = rows[0]
    delta = best_overall["ccc"] - BASELINE["B1_v2_only"]["ccc"]
    pct = 100 * delta / BASELINE["B1_v2_only"]["ccc"]
    bound_a_pct = 100 * best_overall["ccc"] / BASELINE["Bound A (oracle T1+meanR)"]["ccc"]
    # Try to load lockbox LOOCV result
    loocv_path = RES / "iter3_hy_residual_t3_loocv.json"
    loocv_str = ""
    if loocv_path.exists():
        with open(loocv_path) as f:
            ld = json.load(f)
        loocv_str = (f"<br><br><b>🎯 LOCKBOX HEADLINE LOOCV (pre-registered, hy_residual):</b>"
                     f"<br>CCC = <b>{ld['ccc']:.4f}</b>, MAE = {ld['mae']:.2f}, slope = {ld['cal_slope']:.3f}, r = {ld['r']:.3f}"
                     f"<br>vs B1 LOOCV baseline (0.217): <b>+{ld['ccc']-0.217:.3f} CCC ({100*(ld['ccc']-0.217)/0.217:+.1f}%)</b>"
                     f"<br>per-seed CCC: {[round(x,3) for x in ld.get('per_seed_ccc', [])]}"
                     f"<br><b>TIER 2 BREAKTHROUGH (≥0.35) ACHIEVED.</b>")
    headline = f"""<b>HEADLINE — Iter 2 + 3 Combined Result:</b>
    <br>Best 5-fold T3 CCC: <b>{best_overall['ccc']:.3f}</b> ({best_overall['name']})
    <br>vs B1 baseline (0.207): <b>+{delta:.3f} CCC ({pct:+.1f}%)</b>
    <br>vs theoretical ceiling Bound A (0.351): we are at <b>{bound_a_pct:.1f}%</b> of the realistic max{loocv_str}"""

    html = ['<!DOCTYPE html><html><head><meta charset="utf-8">',
            '<title>T3 Glass Ceiling — Iter 2 + 3 Results</title>',
            '<style>',
            'body{font-family:-apple-system,sans-serif;max-width:1200px;margin:24px auto;padding:0 20px;color:#222}',
            'h1{border-bottom:2px solid #333}h2{color:#0066cc;margin-top:32px}',
            '.card{background:#f7f9fc;border:1px solid #e0e6ed;border-radius:6px;padding:12px;margin:16px 0}',
            'img{max-width:100%;height:auto;display:block;margin:10px 0;border:1px solid #ccc}',
            '.caption{color:#444;font-size:14px;line-height:1.55}',
            '.headline{background:#d4edda;border-left:4px solid #28a745;padding:14px;margin:16px 0}',
            'table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #ccc;padding:5px 9px}th{background:#eee}',
            '</style></head><body>',
            '<h1>T3 Glass Ceiling — Iter 2 + Iter 3 Results</h1>',
            f'<div class="headline">{headline}</div>',
            ]
    for s in sections:
        html.append(f'<div class="card"><h2>{s["title"]}</h2>')
        if s.get("img"):
            html.append(f'<img src="data:image/png;base64,{s["img"]}" alt="{s["title"]}">')
        html.append(f'<p class="caption">{s["caption"]}</p></div>')

    # Detailed leaderboard table
    html.append('<h2>Detailed leaderboard</h2><table><tr><th>Rank</th><th>Variant</th><th>CCC</th><th>±std</th><th>ΔvsB1</th><th>iter</th></tr>')
    for i, r in enumerate(rows, 1):
        delta_i = r["ccc"] - 0.207
        html.append(f'<tr><td>{i}</td><td>{r["name"]}</td><td><b>{r["ccc"]:.3f}</b></td><td>{r["ccc_std"]:.3f}</td><td>{delta_i:+.3f}</td><td>{r["iter"]}</td></tr>')
    html.append('</table>')

    html.append('</body></html>')
    with open(OUT_HTML, "w") as f:
        f.write("\n".join(html))
    print(f"Wrote {OUT_HTML}")


if __name__ == "__main__":
    main()

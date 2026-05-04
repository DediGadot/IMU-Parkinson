"""Iter 4 dashboard — collect all iter4_* JSONs + lockbox into a single HTML page.

Reads:
  results/iter4_<variant>_t1_5split.json   — phase 2/3/4 5-fold results
  results/lockbox_t1_iter4_loocv_*.json    — phase 5 lockbox (if exists)
  results/preregistration_t1_iter4_*.json  — pre-registration spec

Writes:
  T1_ITER4.html  — leaderboard + per-seed bars + lockbox banner + per-item heatmap
  figures/iter4_*.png  — bar charts + boxes
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from project_paths import RESULTS_DIR, FIGURES_DIR, ensure_dir

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({"figure.dpi": 110, "savefig.dpi": 150,
                     "font.size": 9, "axes.titlesize": 10,
                     "axes.labelsize": 9, "legend.fontsize": 8})


def load_iter4_results() -> list[dict]:
    rows = []
    for p in sorted((RESULTS_DIR).glob("iter4_*_t1_5split.json")):
        with open(p) as f:
            d = json.load(f)
        rows.append({
            "variant": d["variant"],
            "ccc_mean": d.get("ccc_mean", float("nan")),
            "ccc_std": d.get("ccc_std", float("nan")),
            "mae_mean": d.get("mae_mean", float("nan")),
            "slope_mean": d.get("slope_mean", float("nan")),
            "ccc_per_seed": d.get("ccc_per_seed", []),
            "n_subjects": d.get("n_subjects", 0),
            "wall_s": d.get("wall_total_s", 0),
            "extras": {k: v for k, v in d.items()
                       if k not in {"variant", "ccc_mean", "ccc_std", "mae_mean",
                                    "slope_mean", "ccc_per_seed", "n_subjects",
                                    "per_seed", "wall_total_s", "null_tests",
                                    "target", "eval"}},
            "null_tests": d.get("null_tests", {}),
        })
    return rows


def load_lockbox() -> dict | None:
    files = sorted((RESULTS_DIR).glob("lockbox_t1_iter4_loocv_*.json"))
    if not files:
        return None
    with open(files[-1]) as f:
        return json.load(f)


def load_prereg() -> dict | None:
    files = sorted((RESULTS_DIR).glob("preregistration_t1_iter4_*.json"))
    if not files:
        return None
    with open(files[-1]) as f:
        return json.load(f)


def fig_to_b64(fig) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def plot_leaderboard_bar(rows: list[dict]) -> str:
    rows_sorted = sorted(rows, key=lambda r: r["ccc_mean"], reverse=True)
    names = [r["variant"] for r in rows_sorted]
    cccs = [r["ccc_mean"] for r in rows_sorted]
    stds = [r["ccc_std"] for r in rows_sorted]
    fig, ax = plt.subplots(figsize=(9, max(4, 0.4 * len(names))))
    y_pos = np.arange(len(names))
    colors = ["#2ecc71" if v == "b1_v2_only_control"
              else "#3498db" for v in names]
    ax.barh(y_pos, cccs, xerr=stds, color=colors,
            edgecolor="#222", linewidth=0.5, alpha=0.85)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names)
    ax.set_xlabel("5-fold CCC ± std (3 seeds)")
    ax.set_title("Iter 4 — T1 ablation leaderboard (PD-only, inductive)")
    ax.axvline(0.674, color="#e74c3c", ls="--", lw=1, label="prior phase6_stack baseline (0.674)")
    ax.axvline(0.654, color="#f39c12", ls="--", lw=1, label="prior B1_v2_only baseline (0.654)")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    ax.legend(loc="lower right")
    for i, (v, s) in enumerate(zip(cccs, stds)):
        ax.text(v + 0.005, i, f"{v:.4f}", va="center", fontsize=8)
    return fig_to_b64(fig)


def plot_seed_box(rows: list[dict]) -> str:
    rows_sorted = sorted(rows, key=lambda r: r["ccc_mean"], reverse=True)
    names = [r["variant"] for r in rows_sorted]
    seeds = [r["ccc_per_seed"] for r in rows_sorted]
    fig, ax = plt.subplots(figsize=(9, max(4, 0.4 * len(names))))
    bp = ax.boxplot(seeds, vert=False, widths=0.6, patch_artist=True)
    for patch in bp["boxes"]:
        patch.set_facecolor("#3498db")
        patch.set_alpha(0.6)
    ax.set_yticklabels(names)
    ax.set_xlabel("5-fold CCC across 3 seeds")
    ax.set_title("Iter 4 — per-seed CCC distribution")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    return fig_to_b64(fig)


def render_html(rows: list[dict], lockbox: dict | None,
                prereg: dict | None) -> str:
    bar_b64 = plot_leaderboard_bar(rows)
    box_b64 = plot_seed_box(rows)
    rows_sorted = sorted(rows, key=lambda r: r["ccc_mean"], reverse=True)

    header = ""
    if lockbox is not None:
        header = (f'<div class="lockbox">🎯 <b>LOCKBOX LOOCV HEADLINE</b><br>'
                  f'Pipeline: {lockbox.get("variant", "?")}<br>'
                  f'CCC = <b>{lockbox.get("ccc_mean", "?")}</b> '
                  f'(per-seed {lockbox.get("ccc_per_seed", [])})<br>'
                  f'MAE = {lockbox.get("mae_mean", "?")}, '
                  f'slope = {lockbox.get("slope_mean", "?")}</div>')

    pre_header = ""
    if prereg is not None:
        pre_header = (f'<div class="prereg">📌 Pre-registration: '
                      f'<code>{prereg.get("variant", "?")}</code> | '
                      f'expected LOOCV range: {prereg.get("expected_loocv_range", "?")}</div>')

    table_rows = []
    for r in rows_sorted:
        extras = " ".join(f"<small>{k}={v}</small>"
                          for k, v in r["extras"].items() if v)
        nt = r["null_tests"]
        nt_str = ""
        if nt:
            sl = nt.get("scrambled_label_ccc", "?")
            cf = nt.get("canary_feature_ccc", "?")
            nt_str = f"sl={sl}, cf={cf}"
        table_rows.append(
            f'<tr><td>{r["variant"]}</td>'
            f'<td>{r["ccc_mean"]:.4f}</td>'
            f'<td>± {r["ccc_std"]:.4f}</td>'
            f'<td>{r["mae_mean"]:.3f}</td>'
            f'<td>{r["slope_mean"]:.3f}</td>'
            f'<td>{r["ccc_per_seed"]}</td>'
            f'<td>{r["n_subjects"]}</td>'
            f'<td>{r["wall_s"]:.0f}s</td>'
            f'<td>{nt_str}</td>'
            f'<td>{extras}</td></tr>'
        )
    table_html = "\n".join(table_rows)

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>T1 Iter 4 Ablation Dashboard</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          max-width: 1200px; margin: 24px auto; padding: 0 16px; color: #222; }}
  h1, h2 {{ color: #2c3e50; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin: 16px 0; }}
  th, td {{ border: 1px solid #bdc3c7; padding: 6px 10px; text-align: left; }}
  th {{ background: #ecf0f1; }}
  tr:nth-child(even) td {{ background: #f8f9fa; }}
  small {{ color: #7f8c8d; display: block; }}
  .lockbox {{ background: #2ecc71; color: white; padding: 16px; border-radius: 8px;
              margin: 16px 0; font-size: 16px; }}
  .prereg {{ background: #f1c40f; color: #2c3e50; padding: 8px 16px;
             border-radius: 6px; margin: 8px 0; font-size: 13px; }}
  img {{ max-width: 100%; border: 1px solid #bdc3c7; border-radius: 4px; }}
  code {{ background: #ecf0f1; padding: 2px 6px; border-radius: 3px; }}
</style></head>
<body>
<h1>T1 Step-Function Iter 4 — Ablation Dashboard</h1>
<p>Mission: lock the best T1 pipeline across 10+1 stack-ranked ideas. PD-only inductive.
   Baseline reference: <code>B1_v2_only</code>=0.654, <code>phase6_stack_lgb_meta</code>=0.674
   (5-fold), <code>inductive_pd</code>=0.588 (LOOCV).</p>

{header}
{pre_header}

<h2>Leaderboard</h2>
<img src="data:image/png;base64,{bar_b64}" alt="Leaderboard"/>
<table>
<tr><th>Variant</th><th>CCC mean</th><th>CCC std</th><th>MAE</th><th>slope</th>
    <th>Per-seed</th><th>N</th><th>Wall</th><th>Null tests</th><th>Notes</th></tr>
{table_html}
</table>

<h2>Per-seed distribution</h2>
<img src="data:image/png;base64,{box_b64}" alt="Per-seed box"/>

<p style="font-size:12px; color:#7f8c8d; margin-top:32px;">
Generated: {pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")} ·
{len(rows)} variants · null tests deferred to <code>b1_v2_only_control</code>
</p>
</body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO_ROOT / "T1_ITER4.html"))
    args = ap.parse_args()

    ensure_dir(FIGURES_DIR)
    rows = load_iter4_results()
    if not rows:
        print(f"[warn] No iter4_*_t1_5split.json found in {RESULTS_DIR}")
        return
    lockbox = load_lockbox()
    prereg = load_prereg()
    html = render_html(rows, lockbox, prereg)
    out_path = Path(args.out)
    out_path.write_text(html)
    print(f"Wrote {out_path} ({len(rows)} variants, lockbox={lockbox is not None})")


if __name__ == "__main__":
    main()

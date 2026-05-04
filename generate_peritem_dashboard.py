"""Generate T1_PERITEM.html dashboard from per-item screening + lockbox results."""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))


ITEM_NAMES = {
    1: "Speech (3.1)", 2: "Facial expression (3.2)", 3: "Rigidity (3.3)",
    4: "Finger tap (3.4)", 5: "Hand movement (3.5)", 6: "Pron-supination (3.6)",
    7: "Toe tap (3.7)", 8: "Leg agility (3.8)",
    9: "Arising from chair (3.9)", 10: "Gait (3.10)", 11: "Freezing of gait (3.11)",
    12: "Postural stability (3.12)", 13: "Posture (3.13)", 14: "Body bradykinesia (3.14)",
    15: "Postural tremor (3.15)", 16: "Kinetic tremor (3.16)",
    17: "Rest tremor amp (3.17)", 18: "Rest tremor constancy (3.18)",
}

CEILING = {
    1: 0.30, 2: 0.32, 3: 0.20,
    4: 0.25, 5: 0.35, 6: 0.30,
    7: 0.42, 8: 0.42, 9: 0.60, 10: 0.65, 11: 0.45,
    12: 0.74, 13: 0.30, 14: 0.62, 15: 0.18, 16: 0.15, 17: 0.30, 18: 0.40,
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--screening_csv", default="results/peritem_v2_screening_5split.csv")
    p.add_argument("--lockbox_summary", default="")
    p.add_argument("--composite_json", default="")
    p.add_argument("--out", default="T1_PERITEM.html")
    args = p.parse_args()

    df_scr = pd.read_csv(args.screening_csv) if Path(args.screening_csv).exists() else pd.DataFrame()

    lockbox_df = None
    if args.lockbox_summary and Path(args.lockbox_summary).exists():
        lockbox_df = pd.read_csv(args.lockbox_summary)
    else:
        # Auto-detect newest peritem_lockbox_summary_*.csv
        files = sorted(glob.glob("results/peritem_lockbox_summary_*.csv"))
        if files:
            lockbox_df = pd.read_csv(files[-1])

    composite = None
    if args.composite_json and Path(args.composite_json).exists():
        with open(args.composite_json) as f:
            composite = json.load(f)
    else:
        files = sorted(glob.glob("results/peritem_composite_*.json"))
        if files:
            with open(files[-1]) as f:
                composite = json.load(f)

    rows = []
    for item in range(1, 19):
        row = {
            "item": item,
            "name": ITEM_NAMES[item],
            "ceiling_target": CEILING.get(item, np.nan),
        }
        if not df_scr.empty:
            sub = df_scr[df_scr["item"] == item].sort_values("ccc_mean", ascending=False)
            if not sub.empty:
                row["best_5fold_variant"] = sub.iloc[0]["variant"]
                row["best_5fold_ccc"] = float(sub.iloc[0]["ccc_mean"])
                row["best_5fold_std"] = float(sub.iloc[0]["ccc_std"])
                row["null_scrambled_ccc"] = float(sub.iloc[0].get("scrambled_label_ccc", np.nan))
        if lockbox_df is not None:
            sub2 = lockbox_df[lockbox_df["item"] == item]
            if not sub2.empty:
                row["loocv_ccc"] = float(sub2.iloc[0]["loocv_ccc_mean"])
                row["loocv_mae"] = float(sub2.iloc[0]["loocv_mae_mean"])
                row["lockbox_variant"] = str(sub2.iloc[0]["variant"])
        rows.append(row)
    df_out = pd.DataFrame(rows)

    # Build HTML
    html_parts = ["""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>UPDRS-III Per-Item Deep Dive — Lockbox Results</title>
<style>
:root {
  --bg: #0a0a0c;
  --surface: #14141a;
  --text: #e9e9ee;
  --muted: #9a9aa6;
  --accent: #4dd0e1;
  --hit: #66bb6a;
  --warn: #ffb74d;
  --dead: #ef5350;
  --grid: #1f1f28;
}
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       background: var(--bg); color: var(--text); margin: 0; padding: 32px; line-height: 1.6; }
h1 { font-weight: 200; font-size: 2.4rem; margin: 0 0 4px; letter-spacing: -0.02em; }
h2 { font-weight: 300; font-size: 1.4rem; color: var(--accent); margin: 32px 0 12px;
     border-bottom: 1px solid var(--grid); padding-bottom: 4px; }
.subtitle { color: var(--muted); font-size: 1rem; margin: 0 0 24px; }
.banner { background: var(--surface); padding: 20px 24px; border-left: 3px solid var(--accent);
          border-radius: 4px; margin: 16px 0 32px; }
table { width: 100%; border-collapse: collapse; font-size: 0.92rem; margin: 12px 0; }
th { text-align: left; padding: 10px 12px; background: var(--surface); color: var(--accent);
     font-weight: 500; border-bottom: 1px solid var(--grid); }
td { padding: 10px 12px; border-bottom: 1px solid var(--grid); vertical-align: top; }
tr:hover td { background: rgba(77, 208, 225, 0.04); }
.ccc-bar { display: inline-block; height: 8px; background: var(--grid); border-radius: 4px; vertical-align: middle;
           width: 100px; margin-right: 8px; position: relative; overflow: hidden; }
.ccc-fill { display: block; height: 100%; background: linear-gradient(90deg, var(--warn), var(--hit));
            border-radius: 4px; }
.delta-pos { color: var(--hit); }
.delta-neg { color: var(--dead); }
.delta-zero { color: var(--muted); }
.muted { color: var(--muted); }
.composite-card { background: var(--surface); padding: 20px 28px; border-radius: 6px;
                  display: inline-block; margin: 8px; min-width: 180px; }
.composite-card h3 { margin: 0 0 4px; font-weight: 400; color: var(--accent); }
.composite-card .ccc { font-size: 2rem; font-weight: 200; color: var(--hit); }
.composite-card .mae { color: var(--muted); font-size: 0.88rem; }
.unobservable { color: var(--muted); font-style: italic; }
</style>
</head>
<body>
<h1>UPDRS-III Per-Item Deep Dive</h1>
<p class="subtitle">Per-item lockbox LOOCV CCC for all 18 items × composite scoring (T1, T3, PIGD, axial, brady, tremor)</p>
"""]

    # Composite cards
    if composite and "composites" in composite:
        html_parts.append('<div class="banner"><strong>Composite scores:</strong></div>')
        html_parts.append('<div>')
        for name in ["T1", "T1_stack", "T3", "T3_stack", "PIGD", "axial", "brady", "tremor"]:
            for k, v in composite["composites"].items():
                if k.startswith(name) and (k == name or k.endswith("_sum") or k.endswith("_stack")):
                    if k == f"{name}_sum" or k == f"{name}_stack":
                        html_parts.append(f'<div class="composite-card"><h3>{k}</h3>')
                        html_parts.append(f'<div class="ccc">{v["ccc"]:.4f}</div>')
                        html_parts.append(f'<div class="mae">MAE = {v["mae"]:.3f}, n={v.get("n_items",0)}</div></div>')
        html_parts.append('</div>')

    # Per-item table
    html_parts.append('<h2>Per-Item Lockbox LOOCV CCC</h2>')
    html_parts.append('<table>')
    html_parts.append('<tr><th>Item</th><th>Symptom</th><th>5-fold winner variant</th>'
                      '<th>5-fold CCC</th><th>LOOCV CCC</th><th>LOOCV MAE</th>'
                      '<th>Ceiling target</th><th>Δ (LOOCV − target)</th></tr>')
    for _, r in df_out.iterrows():
        ccc_5f = r.get("best_5fold_ccc")
        ccc_loo = r.get("loocv_ccc")
        ceiling = r.get("ceiling_target")
        delta = (ccc_loo - ceiling) if (ccc_loo is not None and ceiling is not None and not pd.isna(ccc_loo) and not pd.isna(ceiling)) else None
        delta_class = "delta-zero"
        delta_str = "—"
        if delta is not None:
            if delta > 0.01:
                delta_class = "delta-pos"
                delta_str = f"+{delta:.3f}"
            elif delta < -0.01:
                delta_class = "delta-neg"
                delta_str = f"{delta:.3f}"
            else:
                delta_str = f"{delta:+.3f}"
        unobs = r["item"] in (1, 2, 3)
        html_parts.append('<tr>')
        html_parts.append(f'<td><strong>{int(r["item"])}</strong></td>')
        if unobs:
            html_parts.append(f'<td class="unobservable">{r["name"]} (severity-proxy)</td>')
        else:
            html_parts.append(f'<td>{r["name"]}</td>')
        html_parts.append(f'<td>{r.get("best_5fold_variant", "—")}</td>')
        if ccc_5f is not None and not pd.isna(ccc_5f):
            html_parts.append(f'<td><span class="ccc-bar"><span class="ccc-fill" style="width:{max(0,min(100,ccc_5f*100))}%"></span></span> {ccc_5f:.3f}</td>')
        else:
            html_parts.append('<td>—</td>')
        if ccc_loo is not None and not pd.isna(ccc_loo):
            html_parts.append(f'<td><span class="ccc-bar"><span class="ccc-fill" style="width:{max(0,min(100,ccc_loo*100))}%"></span></span> <strong>{ccc_loo:.3f}</strong></td>')
        else:
            html_parts.append('<td class="muted">pending</td>')
        html_parts.append(f'<td>{r.get("loocv_mae", "—") if not pd.isna(r.get("loocv_mae", np.nan)) else "—"}</td>')
        html_parts.append(f'<td class="muted">{ceiling if not pd.isna(ceiling) else "—"}</td>')
        html_parts.append(f'<td class="{delta_class}">{delta_str}</td>')
        html_parts.append('</tr>')
    html_parts.append('</table>')

    # Methods note
    html_parts.append('''<h2>Methods</h2>
<ul>
<li><strong>Inductive only:</strong> fold-local fit/transform via <code>inductive_lib.py</code>.</li>
<li><strong>Per-fold feature selection:</strong> LightGBM importance, K=500.</li>
<li><strong>Subject splits:</strong> <code>paper3_split.json</code> (seed=20260309).</li>
<li><strong>Lockbox protocol:</strong> 5-fold for screening, single LOOCV per item, 3 seeds.</li>
<li><strong>Per-item features:</strong> 1305 features extracted from raw 22-channel CSVs (Lumbar/Sternum/Forehead + R/L Wrist/Foot/Shank/Thigh/Ankle), motor-signature-grounded per item.</li>
<li><strong>Variants per item:</strong> v2_baseline, item_dedicated, item_plus_v2, hy_residual_item (severity-correlated only), hurdle_fog (item 11), lr_multitask (paired items).</li>
<li><strong>Composite:</strong> Sum-of-OOFs and Ridge meta-stack on item OOFs.</li>
</ul>
''')

    html_parts.append('</body></html>')

    with open(args.out, "w") as f:
        f.write("\n".join(html_parts))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()

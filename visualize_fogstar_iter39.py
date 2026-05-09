#!/usr/bin/env python3
"""Visualize FoG-STAR iter39 zero-shot external validation."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_DIR = RESULTS / "iter39_fogstar_zeroshot"
OUT_HTML = RESULTS / "iter39_fogstar_zeroshot.html"
RESULT_JSON = RESULTS / "iter39_fogstar_zeroshot_20260508_143717.json"
ROWS_CSV = RESULTS / "iter39_fogstar_zeroshot_rows_20260508_143717.csv"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result = load_json(RESULT_JSON)
    rows = pd.read_csv(ROWS_CSV)

    tracks = [
        ("track_a_pred", "A: WG Wrist Direct", result["track_a_wg_wrist_direct"]),
        ("track_b_pred", "B: iter5 Clinical + Wrist", result["track_b_iter5_style_clinical_plus_wrist"]),
        ("track_c_fogstar_loo_pred", "C: FoG-STAR LOO Sanity", result["track_c_fogstar_only_loo_sanity"]),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2), sharex=True, sharey=True)
    lo = min(rows["updrs3"].min(), *(rows[col].min() for col, _, _ in tracks)) - 4
    hi = max(rows["updrs3"].max(), *(rows[col].max() for col, _, _ in tracks)) + 4
    for ax, (col, title, metrics) in zip(axes, tracks):
        ax.scatter(rows["updrs3"], rows[col], s=42, color="#176f6b", edgecolor="white", linewidth=0.7)
        ax.plot([lo, hi], [lo, hi], color="#8a1c1c", linestyle="--", linewidth=1)
        ax.set_title(f"{title}\nCCC {metrics['ccc']:.3f}, MAE {metrics['mae']:.1f}")
        ax.set_xlabel("True UPDRS-III")
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("Predicted UPDRS-III")
    for ax in axes:
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
    fig.suptitle("FoG-STAR Iter39 Zero-Shot External Validation", y=1.03, fontsize=13)
    fig.tight_layout()
    fig_path = OUT_DIR / "fig1_iter39_fogstar_scatter.png"
    fig.savefig(fig_path, dpi=180, bbox_inches="tight")
    plt.close(fig)

    residual_df = pd.DataFrame(
        {
            "track": ["A wrist direct", "B clinical+wrist", "C FoG-STAR LOO"],
            "ccc": [m["ccc"] for _, _, m in tracks],
            "mae": [m["mae"] for _, _, m in tracks],
            "ci_low": [m["ccc_ci95"][0] for _, _, m in tracks],
            "ci_high": [m["ccc_ci95"][1] for _, _, m in tracks],
        }
    )
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.bar(residual_df["track"], residual_df["ccc"], color=["#596573", "#176f6b", "#9b4d00"])
    ax.errorbar(
        residual_df["track"],
        residual_df["ccc"],
        yerr=[
            residual_df["ccc"] - residual_df["ci_low"],
            residual_df["ci_high"] - residual_df["ccc"],
        ],
        fmt="none",
        ecolor="#17202a",
        capsize=4,
        linewidth=1.2,
    )
    ax.axhline(0, color="#17202a", linewidth=0.9)
    ax.axhline(0.35, color="#176f6b", linestyle="--", linewidth=0.9)
    ax.set_ylabel("CCC with 95% bootstrap CI")
    ax.set_title("FoG-STAR External CCC: partial signal only in clinical + wrist track")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig2_path = OUT_DIR / "fig2_iter39_fogstar_ccc_ci.png"
    fig.savefig(fig2_path, dpi=180, bbox_inches="tight")
    plt.close(fig)

    metric_rows = []
    for _, title, metrics in tracks:
        metric_rows.append(
            "<tr>"
            f"<td>{html.escape(title)}</td>"
            f"<td>{metrics['ccc']:.4f}</td>"
            f"<td>[{metrics['ccc_ci95'][0]:.4f}, {metrics['ccc_ci95'][1]:.4f}]</td>"
            f"<td>{metrics['mae']:.2f}</td>"
            f"<td>{metrics['r']:.4f}</td>"
            f"<td>{metrics['cal_slope']:.4f}</td>"
            "</tr>"
        )

    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FoG-STAR Iter39 Zero-Shot External Validation</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #17202a; }}
    header, section {{ padding: 28px clamp(20px, 5vw, 72px); border-bottom: 1px solid #d9dee7; }}
    header {{ background: #eef4f3; }}
    h1 {{ margin: 0 0 12px; font-size: 2rem; letter-spacing: 0; }}
    p {{ max-width: 1060px; line-height: 1.45; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 1060px; margin: 16px 0; }}
    th, td {{ border-bottom: 1px solid #d9dee7; padding: 9px 8px; text-align: left; }}
    th {{ background: #f7f8fb; }}
    img {{ max-width: 100%; height: auto; border: 1px solid #d9dee7; }}
    .note {{ border-left: 4px solid #9b4d00; background: #fff7ed; padding: 12px 14px; max-width: 1060px; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
  </style>
</head>
<body>
  <header>
    <p>Generated {html.escape(generated)}</p>
    <h1>FoG-STAR Iter39 Zero-Shot External Validation</h1>
    <p>Pre-registered WearGait-PD-to-FoG-STAR evaluation. Tracks A/B train only on WearGait-PD and score all FoG-STAR subjects with total <code>updrs_iii</code>. Track C is an explicitly within-FoG-STAR LOOCV sanity ceiling.</p>
    <div class="note"><strong>Interpretation:</strong> This is external-validity evidence only. It does not alter the internal WearGait-PD T3 canonical CCC of 0.5227.</div>
  </header>
  <section>
    <h2>Metrics</h2>
    <table><thead><tr><th>Track</th><th>CCC</th><th>95% CI</th><th>MAE</th><th>r</th><th>Calibration slope</th></tr></thead><tbody>{''.join(metric_rows)}</tbody></table>
  </section>
  <section>
    <h2>Scatter</h2>
    <img src="iter39_fogstar_zeroshot/fig1_iter39_fogstar_scatter.png" alt="FoG-STAR scatter plots">
  </section>
  <section>
    <h2>CCC CI</h2>
    <img src="iter39_fogstar_zeroshot/fig2_iter39_fogstar_ccc_ci.png" alt="FoG-STAR CCC confidence intervals">
  </section>
</body>
</html>
"""
    OUT_HTML.write_text(doc, encoding="utf-8")
    manifest = {
        "generated_at_utc": generated,
        "script": "visualize_fogstar_iter39.py",
        "result_json": str(RESULT_JSON.relative_to(ROOT)),
        "rows_csv": str(ROWS_CSV.relative_to(ROOT)),
        "figures": [str(fig_path.relative_to(ROOT)), str(fig2_path.relative_to(ROOT))],
        "html": str(OUT_HTML.relative_to(ROOT)),
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_HTML.relative_to(ROOT)}")
    print(f"Wrote {(OUT_DIR / 'manifest.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()

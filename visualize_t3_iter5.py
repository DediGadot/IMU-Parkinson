"""Generate T3 iter5 sit-with-data figures and a compact HTML report.

Inputs are existing lockbox artifacts only:
  - results/lockbox_t3_iter5_A3_tier1_20260502_171604.json
  - results/t3_iter16_site_ipw_lockbox.json
  - results/t3_conformal_abstention_20260505.json

Run:
  uv run python visualize_t3_iter5.py
"""
from __future__ import annotations

import html
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

RESULTS_DIR = REPO_ROOT / "results"
FIG_DIR = RESULTS_DIR / "t3_iter5_deepdive"
FIG_DIR.mkdir(parents=True, exist_ok=True)

LOCKBOX_PATH = RESULTS_DIR / "lockbox_t3_iter5_A3_tier1_20260502_171604.json"
LOSO_PATH = RESULTS_DIR / "t3_iter16_site_ipw_lockbox.json"
CONFORMAL_PATH = RESULTS_DIR / "t3_conformal_abstention_20260505.json"
HTML_PATH = RESULTS_DIR / "t3_iter5_deepdive.html"
SUMMARY_PATH = FIG_DIR / "summary.json"

BLUE = "#0072B2"
ORANGE = "#E69F00"
GREEN = "#009E73"
RED = "#D55E00"
PURPLE = "#CC79A7"
GREY = "#999999"

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
        "figure.dpi": 180,
        "savefig.dpi": 180,
        "savefig.bbox": "tight",
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _ccc(y: np.ndarray, p: np.ndarray) -> float:
    return float(ccc_fn(y, p))


def _metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    return {
        "n": int(len(y)),
        "ccc": _ccc(y, p),
        "mae": float(np.mean(np.abs(p - y))),
        "r": float(np.corrcoef(y, p)[0, 1]) if len(y) > 1 else float("nan"),
        "bias_pred_minus_true": float(np.mean(p - y)),
        "pred_std": float(np.std(p, ddof=0)),
        "true_std": float(np.std(y, ddof=0)),
    }


def _quartile_masks(y: np.ndarray) -> list[tuple[str, np.ndarray]]:
    q1, q2, q3 = np.percentile(y, [25, 50, 75])
    return [
        ("Q1 low", y <= q1),
        ("Q2", (y > q1) & (y <= q2)),
        ("Q3", (y > q2) & (y <= q3)),
        ("Q4 high", y > q3),
    ]


def fig1_calibration(y: np.ndarray, p: np.ndarray, save_path: Path, headline: dict) -> None:
    fig, ax = plt.subplots(figsize=(6.1, 6.0))
    sites = np.array(headline["sites"])
    for site, color in [("NLS", BLUE), ("WPD", ORANGE)]:
        mask = sites == site
        ax.scatter(y[mask], p[mask], s=42, alpha=0.78, color=color, edgecolor="white", linewidth=0.6, label=site)

    lo = float(min(y.min(), p.min())) - 2
    hi = float(max(y.max(), p.max())) + 2
    xs = np.linspace(lo, hi, 100)
    ax.plot(xs, xs, "--", color=GREY, lw=1.5, label="identity")
    fit_a, fit_b = np.polyfit(y, p, 1)
    ax.plot(xs, fit_a * xs + fit_b, color=RED, lw=2.0, label=f"pred-on-true fit slope={fit_a:.2f}")

    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("True UPDRS-III")
    ax.set_ylabel("Predicted UPDRS-III")
    ax.set_title(
        "T3 iter5 lockbox calibration\n"
        f"CCC={headline['ccc']:.4f}  MAE={headline['mae']:.3f}  r={headline['r']:.4f}  cal_slope={headline['cal_slope']:.4f}"
    )
    ax.legend(loc="lower right", framealpha=0.9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(save_path)
    plt.close(fig)


def fig2_residual_quartiles(y: np.ndarray, p: np.ndarray, save_path: Path) -> list[dict]:
    residual = p - y
    masks = _quartile_masks(y)
    labels = [name for name, _ in masks]
    data = [residual[mask] for _, mask in masks]
    colors = [BLUE, GREEN, ORANGE, RED]

    fig, ax = plt.subplots(figsize=(7.0, 4.8))
    bp = ax.boxplot(data, tick_labels=labels, patch_artist=True, showfliers=False)
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.42)
    rng = np.random.default_rng(20260508)
    for i, (vals, color) in enumerate(zip(data, colors), start=1):
        x = i + rng.uniform(-0.12, 0.12, size=len(vals))
        ax.scatter(x, vals, s=24, color=color, alpha=0.70, edgecolor="white", linewidth=0.4)
        ax.text(i, max(vals) + 1.0, f"mean={np.mean(vals):+.1f}\nn={len(vals)}", ha="center", fontsize=8)
    ax.axhline(0, color="black", lw=1, ls="--", alpha=0.65)
    ax.set_ylabel("Residual (pred - true)")
    ax.set_title("T3 iter5 residuals by true-severity quartile")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(save_path)
    plt.close(fig)

    rows = []
    for name, mask in masks:
        vals = residual[mask]
        rows.append(
            {
                "quartile": name,
                "n": int(mask.sum()),
                "true_mean": float(np.mean(y[mask])),
                "pred_mean": float(np.mean(p[mask])),
                "residual_mean": float(np.mean(vals)),
                "mae": float(np.mean(np.abs(vals))),
            }
        )
    return rows


def fig3_site_and_loso(y: np.ndarray, p: np.ndarray, sids: np.ndarray, loso: dict, save_path: Path) -> dict:
    sites = np.array(["WPD" if str(s).startswith("WPD") else "NLS" for s in sids])
    site_rows = []
    for site in ["NLS", "WPD"]:
        mask = sites == site
        row = {"site": site, **_metrics(y[mask], p[mask])}
        site_rows.append(row)

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.6))

    x = np.arange(2)
    axes[0].bar(x, [r["ccc"] for r in site_rows], color=[BLUE, ORANGE], alpha=0.82)
    axes[0].set_xticks(x, [r["site"] for r in site_rows])
    axes[0].set_ylim(0, 0.8)
    axes[0].set_ylabel("LOOCV CCC within site")
    axes[0].set_title("Internal validity stratified by site")
    for i, r in enumerate(site_rows):
        axes[0].text(i, r["ccc"] + 0.02, f"{r['ccc']:.3f}\nn={r['n']}", ha="center", fontsize=9)
    axes[0].grid(axis="y", alpha=0.25)

    loso_vals = [
        float(loso["NLS_to_WPD_mean_ccc"]),
        float(loso["WPD_to_NLS_mean_ccc"]),
        float(loso["two_way_mean"]),
    ]
    labels = ["NLS->WPD", "WPD->NLS", "two-way"]
    axes[1].bar(np.arange(3), loso_vals, color=[BLUE, ORANGE, PURPLE], alpha=0.82)
    axes[1].axhline(0.5227, color=GREY, ls="--", lw=1.2, label="iter5 LOOCV 0.5227")
    axes[1].set_xticks(np.arange(3), labels, rotation=12)
    axes[1].set_ylim(0, 0.62)
    axes[1].set_ylabel("CCC")
    axes[1].set_title("Transportability cliff")
    for i, v in enumerate(loso_vals):
        axes[1].text(i, v + 0.02, f"{v:.3f}", ha="center", fontsize=9)
    axes[1].legend(framealpha=0.9)
    axes[1].grid(axis="y", alpha=0.25)

    fig.tight_layout()
    fig.savefig(save_path)
    plt.close(fig)

    return {
        "site_rows": site_rows,
        "loso": {
            "NLS_to_WPD_mean_ccc": loso_vals[0],
            "WPD_to_NLS_mean_ccc": loso_vals[1],
            "two_way_mean": loso_vals[2],
            "loocv_minus_loso_two_way": float(0.5227 - loso_vals[2]),
        },
    }


def fig4_conformal(conformal: dict, save_path: Path) -> None:
    conf = conformal["conformal"]
    abst = conformal["abstention"]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.5))

    labels = [f"{int(c['nominal_coverage'] * 100)}%" for c in conf]
    empirical = [c["empirical_coverage"] for c in conf]
    widths = [c["interval_width"] for c in conf]
    x = np.arange(len(conf))
    axes[0].bar(x - 0.18, [c["nominal_coverage"] for c in conf], width=0.36, color=GREY, alpha=0.60, label="nominal")
    axes[0].bar(x + 0.18, empirical, width=0.36, color=GREEN, alpha=0.82, label="empirical")
    axes[0].set_xticks(x, labels)
    axes[0].set_ylim(0, 1.02)
    axes[0].set_ylabel("Coverage")
    axes[0].set_title("Split conformal coverage")
    for i, w in enumerate(widths):
        axes[0].text(i, 0.06, f"width\n{w:.1f}", ha="center", fontsize=8)
    axes[0].legend(framealpha=0.9)
    axes[0].grid(axis="y", alpha=0.25)

    discard = [a["discard_frac"] for a in abst]
    cccs = [a["ccc"] for a in abst]
    maes = [a["mae"] for a in abst]
    ax2 = axes[1]
    ax2.plot(discard, cccs, marker="o", color=BLUE, label="CCC")
    ax2.set_xlabel("Discard fraction")
    ax2.set_ylabel("CCC", color=BLUE)
    ax2.tick_params(axis="y", labelcolor=BLUE)
    ax2.set_title("Abstention curve from existing OOF")
    ax2.grid(alpha=0.25)
    ax2b = ax2.twinx()
    ax2b.plot(discard, maes, marker="s", color=RED, label="MAE")
    ax2b.set_ylabel("MAE", color=RED)
    ax2b.tick_params(axis="y", labelcolor=RED)

    fig.tight_layout()
    fig.savefig(save_path)
    plt.close(fig)


def fig5_subject_error(y: np.ndarray, p: np.ndarray, sids: np.ndarray, save_path: Path) -> list[dict]:
    err = p - y
    order = np.argsort(y)
    colors = [RED if e > 0 else BLUE for e in err[order]]
    fig, ax = plt.subplots(figsize=(11.0, 4.6))
    ax.bar(np.arange(len(y)), err[order], color=colors, alpha=0.78, width=0.88)
    ax.axhline(0, color="black", lw=1.0)
    ax.set_xlabel("Subject sorted by true UPDRS-III")
    ax.set_ylabel("Residual (pred - true)")
    ax.set_title("T3 iter5 subject-level errors: low-end overprediction and high-end underprediction")
    ax.text(0.01, 0.94, "low severity", transform=ax.transAxes, fontsize=9, color=GREY)
    ax.text(0.89, 0.94, "high severity", transform=ax.transAxes, fontsize=9, color=GREY)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(save_path)
    plt.close(fig)

    ranked = []
    for sid, yt, yp, e in sorted(zip(sids, y, p, err), key=lambda t: abs(t[3]), reverse=True)[:12]:
        ranked.append(
            {
                "sid": str(sid),
                "site": "WPD" if str(sid).startswith("WPD") else "NLS",
                "y_true": float(yt),
                "y_pred": float(yp),
                "residual": float(e),
                "abs_error": float(abs(e)),
            }
        )
    return ranked


def _table(headers: list[str], rows: list[dict], digits: int = 3) -> str:
    out = ["<table>", "<thead><tr>"]
    out.extend(f"<th>{html.escape(h)}</th>" for h in headers)
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        for h in headers:
            v = row.get(h, "")
            if isinstance(v, float):
                text = f"{v:.{digits}f}"
            else:
                text = str(v)
            out.append(f"<td>{html.escape(text)}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def write_html(summary: dict, figures: list[tuple[str, Path]]) -> None:
    rel_figs = [(title, f"t3_iter5_deepdive/{path.name}") for title, path in figures]
    headline = summary["headline"]
    residual_corr = summary["residual_corr_with_true"]
    html_body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>T3 iter5 deep dive</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px auto; max-width: 1120px; color: #111; line-height: 1.45; }}
    h1, h2 {{ margin-bottom: 0.25rem; }}
    .meta {{ color: #555; margin-top: 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 22px; align-items: start; }}
    figure {{ margin: 0; }}
    img {{ width: 100%; border: 1px solid #ddd; }}
    figcaption {{ font-size: 0.92rem; color: #444; margin-top: 6px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; font-size: 0.92rem; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ background: #f5f5f5; }}
    .callout {{ background: #f7f7f7; border-left: 4px solid #0072B2; padding: 12px 16px; margin: 18px 0; }}
    code {{ background: #f4f4f4; padding: 1px 4px; }}
  </style>
</head>
<body>
  <h1>T3 iter5 best-pipeline deep dive</h1>
  <p class="meta">Generated from existing lockbox artifacts. No model fitting; no new headline number.</p>
  <div class="callout">
    <strong>Headline:</strong> T3 iter5 lockbox CCC={headline['ccc']:.4f}, MAE={headline['mae']:.3f}, r={headline['r']:.4f}, calibration slope={headline['cal_slope']:.4f}, n={headline['n']}.
    Residual-vs-true correlation is {residual_corr:.3f}, so the main failure mode is tail shrinkage rather than calibration scale alone.
  </div>

  <h2>Figures</h2>
  <div class="grid">
"""
    for title, rel in rel_figs:
        html_body += f"""    <figure>
      <img src="{html.escape(rel)}" alt="{html.escape(title)}">
      <figcaption>{html.escape(title)}</figcaption>
    </figure>
"""
    html_body += """  </div>

  <h2>Quartile Residuals</h2>
"""
    html_body += _table(["quartile", "n", "true_mean", "pred_mean", "residual_mean", "mae"], summary["quartile_rows"])
    html_body += """
  <h2>Site Metrics</h2>
"""
    html_body += _table(["site", "n", "ccc", "mae", "r", "bias_pred_minus_true", "true_std", "pred_std"], summary["site_rows"])
    html_body += """
  <h2>Largest Absolute Errors</h2>
"""
    html_body += _table(["sid", "site", "y_true", "y_pred", "residual", "abs_error"], summary["largest_errors"])
    html_body += f"""
  <h2>Artifact Sources</h2>
  <ul>
    <li><code>{html.escape(str(LOCKBOX_PATH.relative_to(REPO_ROOT)))}</code></li>
    <li><code>{html.escape(str(LOSO_PATH.relative_to(REPO_ROOT)))}</code></li>
    <li><code>{html.escape(str(CONFORMAL_PATH.relative_to(REPO_ROOT)))}</code></li>
    <li><code>{html.escape(str(SUMMARY_PATH.relative_to(REPO_ROOT)))}</code></li>
  </ul>
</body>
</html>
"""
    HTML_PATH.write_text(html_body)


def main() -> None:
    lockbox = _load_json(LOCKBOX_PATH)
    loso = _load_json(LOSO_PATH)["loso"]
    conformal = _load_json(CONFORMAL_PATH)

    ps = lockbox["per_subject"]
    sids = np.asarray(ps["sids"], dtype=object)
    y = np.asarray(ps["y_true"], dtype=float)
    p = np.asarray(ps["y_pred"], dtype=float)
    sites = np.array(["WPD" if str(s).startswith("WPD") else "NLS" for s in sids])

    headline = {
        "n": int(lockbox["n"]),
        "ccc": float(lockbox["ccc"]),
        "mae": float(lockbox["mae"]),
        "r": float(lockbox["r"]),
        "cal_slope": float(lockbox["cal_slope"]),
        "sites": sites.tolist(),
    }

    f1 = FIG_DIR / "fig1_t3_iter5_calibration.png"
    f2 = FIG_DIR / "fig2_t3_iter5_residual_quartiles.png"
    f3 = FIG_DIR / "fig3_t3_iter5_site_loso_cliff.png"
    f4 = FIG_DIR / "fig4_t3_iter5_conformal_abstention.png"
    f5 = FIG_DIR / "fig5_t3_iter5_subject_errors.png"

    fig1_calibration(y, p, f1, headline)
    quartile_rows = fig2_residual_quartiles(y, p, f2)
    site_loso = fig3_site_and_loso(y, p, sids, loso, f3)
    fig4_conformal(conformal, f4)
    largest_errors = fig5_subject_error(y, p, sids, f5)

    residual = p - y
    summary = {
        "headline": {k: v for k, v in headline.items() if k != "sites"},
        "artifact_sources": {
            "lockbox": str(LOCKBOX_PATH.relative_to(REPO_ROOT)),
            "loso": str(LOSO_PATH.relative_to(REPO_ROOT)),
            "conformal": str(CONFORMAL_PATH.relative_to(REPO_ROOT)),
        },
        "residual_corr_with_true": float(np.corrcoef(y, residual)[0, 1]),
        "overall": _metrics(y, p),
        "quartile_rows": quartile_rows,
        "site_rows": site_loso["site_rows"],
        "loso": site_loso["loso"],
        "largest_errors": largest_errors,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2))

    figures = [
        ("T3 iter5 OOF calibration by site", f1),
        ("Residuals by true UPDRS-III quartile", f2),
        ("Site-stratified LOOCV and LOSO transportability cliff", f3),
        ("Split conformal coverage and abstention curve", f4),
        ("Subject-level residuals sorted by true UPDRS-III", f5),
    ]
    write_html(summary, figures)

    print(f"Wrote {HTML_PATH.relative_to(REPO_ROOT)}")
    print(f"Wrote {SUMMARY_PATH.relative_to(REPO_ROOT)}")
    for _, path in figures:
        print(f"Wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

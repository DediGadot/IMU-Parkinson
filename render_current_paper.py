#!/usr/bin/env python3
"""Render the current markdown manuscript without using stale legacy generator text."""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "paper.md"
OUTPUT = ROOT / "CURRENT_PAPER.html"
OUT_DIR = ROOT / "results" / "current_paper_export"
MANIFEST = OUT_DIR / "manifest.json"


REQUIRED_SNIPPETS = [
    "T1 LOOCV CCC = 0.6550",
    "valid-range-corrected T3 LOOCV CCC = 0.3784",
    "iter34 multi-task hybrid",
    "auxiliary-label caveat",
    "T3 Total UPDRS-III: Error Anatomy and Transportability Cliff",
    "no longer cited as deployment results",
    "valid-range LOSO transportability falling to CCC = 0.150",
    "target-contaminated",
    "nominal 80% intervals achieved empirical coverage 0.800 with mean width 25.94",
    "deployable abstention proxy based only on prediction extremeness did not rescue the T3 ceiling",
    "Removing only dst_* from the iter47 valid-range Stage 2 gave CCC = 0.3766",
    "not fold-local",
    "cache provenance audit marks four reusable cache artifacts as complete-clean",
    "companion item11_multiscale_recordings.csv",
    "dedicated ablation_v3_features.csv provenance audit",
    "not to synthesize a clean manifest",
    "non-destructive regeneration probe",
    "blocked_missing_regeneration_inputs",
    "control clinical file, control CSV directory, and walkway metrics",
    "control clinical syn55105521",
    "control CSV folder syn61370552",
    "--confirm-large-control-csvs",
    "git_sha = \"unknown\"",
    "cache-consumer guard audit",
    "four current safe-cache consumers",
    "53 model/composer scripts remain diagnostic-only",
    "transitive/runtime cache dependency audits",
    "only diagnostic/partial cache opened at runtime is results/ablation_v3_features.csv",
    "missing-manifest origin audit covers 33 still-missing sidecars",
    "does not make any artifact headline-safe by itself",
    "manual cache backfill evidence audit",
    "leave_missing_no_patch",
    "broken rocket_recordings.npz symlink",
    "Direct cache-consumer guard status is therefore not enough",
    "headline metric recompute audit",
    "CCC metric integrity audit",
    "Lin's population-moment convention",
    "OOF artifact integrity audit",
    "pre-registration temporal integrity audit",
    "passing 9/9 with no hard failures",
    "pre-audit claim labeling audit",
    "passes with zero findings",
    "Historical Pre-Audit Subdomain Prediction",
    "Historical pre-audit sensor ablation",
    "historical auxiliary analyses as deployment evidence",
    "Historical Pre-Audit Seed Stability",
    "candidate claim labeling audit",
    "iter34 is locally framed as a strongest candidate",
    "reportable artifact flag audit",
    "archived raw lockbox booleans are not current claim policy",
    "is_canonical_update = true",
    "RegressorChain(order=\"random\")",
    "common-subject CCC delta of only -0.0008",
    "auxiliary-label/order caveat",
    "per-item evidence map audit",
    "historical 18-item T3 sum is explicitly dead-route",
    "per-item OOF companion scope audit",
    "six current T1 item OOF companions sum exactly to the canonical iter12 OOF",
    "T1 iter12 batch-integrity audit",
    "max summed-OOF difference 0.0",
    "T3 iter47 target-integrity audit",
    "T3 complete33 claim labeling audit",
    "complete33 N = 88 sensitivity-only",
    "External result claim labeling audit",
    "external-only numbers cannot update the internal T3 headline",
    "subject-CSV recomputed CCC = 0.3784",
    "LOSO-row recomputed two-way CCC = 0.1498",
    "residual corr = -0.7771",
    "WPD within-site CCC = 0.0515",
    "top post-hoc residual-feature |r| = 0.290",
    "OOF-level variance matching raises CCC to 0.3996",
    "MAE worsens by +1.1398",
    "not a fully nested meta-model",
    "T3 max absolute leave-one CCC delta is 0.0381",
    "T1 iter34-minus-iter12 matched delta stays positive",
    "influence remains severity-tail concentrated",
    "unobservable non-gait burden has residual r = -0.8004",
    "multidomain Ridge oracle reaches CCC = 0.8533",
    "require true Part III domain labels at prediction time",
    "item-level companion audit",
    "item 6 pronation/supination",
    "best gait/balance-observable items",
    "Mean |r(item,residual)| is 0.247",
    "no valid next WearGait-only model route to break T3 CCC",
    "iter50 low-degree convex mix",
    "nested-convex CCC = 0.3083",
    "screen_fail_no_loocv_no_canonical_change",
    "TLVMC/DeFOG as another public direct T3 route",
    "137 medication-matched recordings across 45 subjects",
    "iter51 zero-shot result",
    "Track A lower-back magnitude CCC = +0.2695",
    "95% CI [+0.1693, +0.3600]",
    "665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd",
    "PDFE turning-in-place refresh",
    "Track A WearGait shank-to-PDFE CCC = -0.101",
    "PDFE-only LOOCV sanity reaches CCC = +0.402",
    "f0eb5985a15b271a333b3d9e1d093e32889814a0f48d0ca4f5131b9674c7b2f2",
    "Harmonized Upper/Lower Limb Accelerometry",
    "daily-life ActiGraph summaries",
    "Monipar and BIOCLITE are public consumer-smartwatch exercise datasets",
    "neither can form the full T1 9-14 composite",
    "Zenodo 14848598 is also public",
    "derived CSF/clinical/gait-summary benchmark table",
    "advanced Parkinson's disease smartwatch home-monitoring study",
    "marital-dyad social-actigraphy study",
    "author-request-only small-N/schema-hidden rows",
    "Personalized Parkinson Project / PD Virtual Motor Exam",
    "RDSRC-gated and schema-hidden",
]

FORBIDDEN_STALE_SNIPPETS = [
    "SSL ranking achieves CCC",
    "T1 CCC&nbsp;=&nbsp;0.868",
    "T3 CCC&nbsp;=&nbsp;0.776",
    "Ordinal ranking also improves broader targets",
    "healthy control subjects (N&nbsp;=&nbsp;80) as calibration anchors",
]


CSS = """
body {
  color: #1d2733;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.55;
  margin: 0 auto;
  max-width: 1180px;
  padding: 32px 24px 72px;
}
h1, h2, h3, h4 { line-height: 1.2; letter-spacing: 0; }
h1 { font-size: 2.1rem; }
h2 { margin-top: 2.2rem; border-top: 1px solid #d9dee7; padding-top: 1.1rem; }
h3 { margin-top: 1.6rem; }
table { border-collapse: collapse; display: block; overflow-x: auto; width: 100%; }
th, td { border: 1px solid #d9dee7; padding: 7px 9px; vertical-align: top; }
th { background: #f4f6f9; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
blockquote { border-left: 4px solid #176f6b; margin-left: 0; padding-left: 16px; color: #43505e; }
.audit-banner {
  background: #eef7f6;
  border-left: 5px solid #176f6b;
  margin: 0 0 24px;
  padding: 14px 16px;
}
.audit-banner strong { display: block; margin-bottom: 4px; }
"""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_pandoc() -> str:
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        raise RuntimeError("pandoc is required to render CURRENT_PAPER.html but was not found on PATH")
    version = subprocess.run(
        [pandoc, "--version"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.splitlines()[0]
    subprocess.run(
        [
            pandoc,
            str(SOURCE),
            "--from",
            "gfm",
            "--to",
            "html5",
            "--standalone",
            "--toc",
            "--metadata",
            "title=WearGait-PD Current Post-Audit Manuscript",
            "--output",
            str(OUTPUT),
        ],
        check=True,
    )
    return version


def inject_css_and_banner(html: str, generated_at: str) -> str:
    style = f"<style>{CSS}</style>"
    if "</head>" in html:
        html = html.replace("</head>", f"{style}\n</head>", 1)
    banner = (
        '<div class="audit-banner">'
        "<strong>Current post-audit render from paper.md.</strong>"
        f"Generated {generated_at}. Use this export instead of NEW4.html for current T1/T3 framing; "
        "NEW4.html is a legacy generator output with stale pre-leakage narrative fragments."
        "</div>"
    )
    if "<body>" in html:
        html = html.replace("<body>", f"<body>\n{banner}", 1)
    else:
        html = banner + html
    return html


def validate(html: str) -> list[str]:
    issues: list[str] = []
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"\s+", " ", text)
    for snippet in REQUIRED_SNIPPETS:
        if snippet not in text:
            issues.append(f"missing required snippet: {snippet}")
    for snippet in FORBIDDEN_STALE_SNIPPETS:
        stale = html_lib.unescape(snippet)
        if stale in text or snippet in html:
            issues.append(f"forbidden stale snippet present: {snippet}")
    return issues


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    pandoc_version = run_pandoc()
    html = OUTPUT.read_text(encoding="utf-8")
    html = inject_css_and_banner(html, generated_at)
    OUTPUT.write_text(html, encoding="utf-8")
    issues = validate(html)
    manifest = {
        "generated_at_utc": generated_at,
        "script": "render_current_paper.py",
        "source": str(SOURCE.relative_to(ROOT)),
        "output": str(OUTPUT.relative_to(ROOT)),
        "pandoc_version": pandoc_version,
        "source_sha256": sha256(SOURCE),
        "output_sha256": sha256(OUTPUT),
        "required_snippets": REQUIRED_SNIPPETS,
        "forbidden_stale_snippets": FORBIDDEN_STALE_SNIPPETS,
        "validation_issues": issues,
        "status": "passed" if not issues else "failed",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if issues:
        for issue in issues:
            print(f"VALIDATION: {issue}")
        raise SystemExit(1)
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    print(f"Wrote {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

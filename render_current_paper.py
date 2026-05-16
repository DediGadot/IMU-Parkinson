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
    "T1 LOOCV CCC = 0.7170",
    "T1 LOSO transportability mean CCC = 0.456",
    "T3 LOOCV CCC = 0.3784",
    "T3 LOSO transportability mean CCC = 0.150",
    "theoretical oracle T1 plus mean R bound CCC = 0.351",
    "theoretical perfect T1 to T3 bound CCC = 0.683",
    "theoretical inductive shrinkage T1 pred to T3 bound CCC = 0.171",
    "strict-inductive cautionary benchmark",
    "strongest candidate",
    "post-publication replication target",
    "target-contaminated",
    "historical pre-audit",
    "OOD fragility, not transductive leakage",
    "paired-bootstrap",
    "multiple-comparisons",
    "Pareto-asymptote",
]

FORBIDDEN_STALE_SNIPPETS = [
    "deployment-ready UPDRS",
    "SSL ranking achieves CCC",
    "T1 CCC = 0.868",
    "T3 CCC = 0.776",
    "MAE = 6.89, r = 0.860 deployable",
    "iter11A 0.7241 canonical",
    "T3 iter5 CCC = 0.5227 canonical",
    "T3 iter16 CCC = 0.341 canonical",
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

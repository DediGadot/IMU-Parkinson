#!/usr/bin/env python3
"""Export the PPMI / Verily Tier-3 packet template to Word format.

The official PPMI instructions allow Tier-3 requests as PDF or Word documents.
This exporter keeps the checked-in Markdown as source of truth and creates a
ready-to-fill `.docx` template with placeholders still intact. It must not be
run on a completed packet containing personal details.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
SOURCE = ROOT / "scripts" / "ppmi_verily_tier3_request_packet.md"
DOCX = RESULTS / "ppmi_verily_tier3_request_packet_template_20260515.docx"
MANIFEST = RESULTS / "ppmi_verily_tier3_request_packet_template_20260515.manifest.json"

PLACEHOLDER_RE = re.compile(r"\[[A-Z0-9_]+\]")
REQUIRED_TERMS = [
    "ready-to-fill template",
    "Verily Raw Device Data",
    "Tier 3",
    "resources@michaeljfox.org",
    "PDF or Word",
    "Version 7.0",
    "15 Feb 2026",
    "30 days",
    "persistent homology",
    "multifractal detrended fluctuation analysis",
    "TopoFractal",
    "K=250",
    "GradientBoostingRegressor",
    "No K-search",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source packet: {SOURCE}")

    text = SOURCE.read_text(encoding="utf-8")
    missing = [term for term in REQUIRED_TERMS if term.lower() not in text.lower()]
    placeholders = sorted(set(PLACEHOLDER_RE.findall(text)))
    if missing:
        raise SystemExit(f"source packet is missing required terms: {missing}")
    if len(placeholders) < 10:
        raise SystemExit("source packet has too few user-fill placeholders")

    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise SystemExit("pandoc is required to export the Word template")

    RESULTS.mkdir(exist_ok=True)
    command = [
        pandoc,
        str(SOURCE),
        "--from",
        "markdown",
        "--to",
        "docx",
        "--standalone",
        "--metadata",
        "title=PPMI / Verily Study Watch Tier-3 Request Packet Template",
        "--output",
        str(DOCX),
    ]
    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=120,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stdout[-4000:])

    manifest: dict[str, Any] = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": rel(Path(__file__).resolve()),
        "source": rel(SOURCE),
        "output_docx": rel(DOCX),
        "source_sha256": sha256(SOURCE),
        "output_docx_sha256": sha256(DOCX),
        "command": command,
        "pandoc_version": subprocess.run(
            [pandoc, "--version"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=10,
        ).stdout.splitlines()[0],
        "placeholder_count": len(placeholders),
        "placeholders": placeholders,
        "status": "ready_to_fill_word_template",
        "protected_data_included": False,
        "not_a_model_result": True,
        "goal_complete": False,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote {DOCX}")
    print(f"Wrote {MANIFEST}")
    print(json.dumps({"placeholder_count": len(placeholders), "output_docx": rel(DOCX)}, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Classify partial cache manifests by whether provenance can be backfilled.

This does not modify any manifests. It records evidence for future manual
backfill, keeping the runtime guard fail-closed until a human chooses to patch a
sidecar from concrete evidence.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CACHE_AUDIT = RESULTS / "cache_manifest_audit_20260508.json"
OUT_JSON = RESULTS / "cache_backfill_candidates_20260508.json"
OUT_MD = RESULTS / "cache_backfill_candidates_20260508.md"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_git(args: list[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def git_commits_for_path(path: str) -> list[str]:
    proc = run_git(["log", "--all", "--format=%H", "--", path])
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def git_show_blob(commit: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_manifest(row: dict[str, Any]) -> dict[str, Any] | None:
    manifest = row.get("manifest")
    if not manifest:
        return None
    path = ROOT / manifest
    if not path.exists():
        return None
    return load_json(path)


def script_name_from_manifest(manifest: dict[str, Any] | None) -> str | None:
    if not manifest:
        return None
    script = manifest.get("script") or manifest.get("produced_by")
    if isinstance(script, str) and script.endswith(".py"):
        return script
    return None


def script_sha_from_manifest(manifest: dict[str, Any] | None) -> str | None:
    if not manifest:
        return None
    value = manifest.get("script_sha256")
    return value if isinstance(value, str) and value else None


def classify(row: dict[str, Any]) -> dict[str, Any]:
    manifest = load_manifest(row)
    script = script_name_from_manifest(manifest)
    expected_script_sha = script_sha_from_manifest(manifest)
    current_script_sha = sha256_file(ROOT / script) if script else None
    git_matches: list[dict[str, str]] = []

    if script and expected_script_sha:
        for commit in git_commits_for_path(script):
            blob = git_show_blob(commit, script)
            if blob is None:
                continue
            actual = sha256_bytes(blob)
            if actual == expected_script_sha:
                short = run_git(["rev-parse", "--short", commit]).stdout.strip()
                subject = run_git(["show", "-s", "--format=%s", commit]).stdout.strip()
                git_matches.append({"commit": commit, "short": short, "subject": subject})

    labels_used = row.get("labels_used")
    leakage_status = row.get("leakage_status")
    missing = row.get("missing_required_fields", [])
    nullish = row.get("nullish_required_fields", [])

    if labels_used is not False or leakage_status != "clean_by_construction":
        recommendation = "do_not_backfill_for_internal_headline"
        rationale = "Manifest describes labels used or non-clean leakage status; this cache is external/diagnostic even if metadata is completed."
    elif git_matches:
        recommendation = "manual_backfill_candidate"
        rationale = "Manifest script_sha256 matches committed script code. Backfill may be defensible if command/runtime evidence is also accepted."
    elif script and expected_script_sha and current_script_sha == expected_script_sha:
        recommendation = "needs_commit_before_backfill"
        rationale = "Manifest script_sha256 matches the working-tree script, but no committed git SHA contains that exact file."
    else:
        recommendation = "insufficient_evidence"
        rationale = "No committed script hash evidence was found."

    return {
        "artifact": row["artifact"],
        "manifest": row.get("manifest"),
        "status": row.get("status"),
        "missing_required_fields": missing,
        "nullish_required_fields": nullish,
        "labels_used": labels_used,
        "leakage_status": leakage_status,
        "script": script,
        "manifest_script_sha256": expected_script_sha,
        "current_script_sha256": current_script_sha,
        "git_script_sha_matches": git_matches,
        "recommendation": recommendation,
        "rationale": rationale,
    }


def main() -> None:
    audit = load_json(CACHE_AUDIT)
    rows = [
        row
        for row in audit.get("artifacts", [])
        if row.get("status") == "partial_manifest_diagnostic_only"
    ]
    classified = [classify(row) for row in rows]
    counts: dict[str, int] = {}
    for row in classified:
        counts[row["recommendation"]] = counts.get(row["recommendation"], 0) + 1

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_cache_backfill_candidates.py",
        "source_audit": str(CACHE_AUDIT.relative_to(ROOT)),
        "policy": "No manifests are modified. Backfill requires concrete evidence; current guards remain fail-closed.",
        "counts": counts,
        "artifacts": classified,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Cache Backfill Candidate Audit - 2026-05-08",
        "",
        "This report classifies partial cache manifests by recoverable provenance evidence. It does not modify manifests and does not make any artifact headline-safe.",
        "",
        "## Summary",
        "",
    ]
    for key, value in sorted(counts.items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Artifacts", ""])
    for row in classified:
        match = row["git_script_sha_matches"][0]["short"] if row["git_script_sha_matches"] else "none"
        lines.append(
            f"- `{row['artifact']}` - `{row['recommendation']}`; "
            f"script `{row.get('script')}`; git script match `{match}`; "
            f"missing={row['missing_required_fields']}; nullish={row['nullish_required_fields']}. "
            f"{row['rationale']}"
        )
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({"counts": counts, "n_partial": len(classified)}, indent=2))


if __name__ == "__main__":
    main()

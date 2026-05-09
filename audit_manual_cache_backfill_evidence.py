#!/usr/bin/env python3
"""Audit manual missing-manifest cache candidates for backfill evidence.

This is deliberately non-mutating. The missing-origin audit can identify caches
with a plausible committed producer script, but clean sidecar backfill still
requires concrete evidence for the exact command/runtime inputs. This audit
records why the remaining manual candidates stay diagnostic-only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SOURCE_AUDIT = RESULTS / "missing_cache_manifest_origin_audit_20260509.json"
OUT_JSON = RESULTS / "manual_cache_backfill_evidence_20260509.json"
OUT_MD = RESULTS / "manual_cache_backfill_evidence_20260509.md"

REMOTE_FILES = [
    "results/rocket_recordings.npz",
    "results/hc_ssl_subj_embeddings.csv",
    "results/moment_subj_embeddings.csv",
    "results/joints_v2_subj.csv",
    "results/stride_locked_subj.csv",
    "results/tug_transition_features.csv",
    "results/cache_features.log",
]

REMOTE_DIR_CANDIDATES = [
    "/home/fiod/pd-imu",
    "/root/pd-imu",
]

DEPENDENCY_MAP = {
    "results/hc_ssl_subj_embeddings.csv": [
        {
            "path": "results/rocket_recordings.npz",
            "kind": "source_npz",
            "purpose": "recordings/sids/tasks source for HC-only SSL extraction",
        }
    ],
    "results/moment_subj_embeddings.csv": [
        {
            "path": "results/rocket_recordings.npz",
            "kind": "source_npz",
            "purpose": "recordings/sids/tasks source for MOMENT extraction",
        }
    ],
    "results/tug_transition_features.csv": [
        {
            "path": "results/rocket_recordings.npz",
            "kind": "source_npz",
            "purpose": "recordings/sids/tasks source for TUG phase extraction",
        }
    ],
    "results/joints_v2_subj.csv": [
        {
            "path": "data/raw/weargait-pd/PD PARTICIPANTS/CSV files",
            "kind": "raw_csv_dir",
            "purpose": "raw 100 Hz WearGait CSV input directory required by --csv_dir",
        }
    ],
    "results/stride_locked_subj.csv": [
        {
            "path": "data/raw/weargait-pd/PD PARTICIPANTS/CSV files",
            "kind": "raw_csv_dir",
            "purpose": "raw 100 Hz WearGait CSV input directory required by --csv_dir",
        }
    ],
}

EXPECTED_COMMAND_GAPS = {
    "results/hc_ssl_subj_embeddings.csv": (
        "No exact invocation was found, and narrative context says 80 epochs while "
        "the committed producer default is 50 epochs."
    ),
    "results/moment_subj_embeddings.csv": "No exact invocation/runtime log was found.",
    "results/tug_transition_features.csv": "No exact invocation/runtime log was found.",
    "results/joints_v2_subj.csv": "No exact --csv_dir/--out_strides/--out_subj invocation was found.",
    "results/stride_locked_subj.csv": "No exact --csv_dir/--out invocation was found.",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def mtime_utc(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    return datetime.fromtimestamp(path.lstat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()


def csv_shape(path: Path) -> dict[str, int | None]:
    if not path.exists() or path.suffix != ".csv":
        return {"rows": None, "columns": None}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return {"rows": 0, "columns": 0}
        rows = sum(1 for _ in reader)
    return {"rows": rows, "columns": len(header)}


def path_status(rel_path: str) -> dict[str, Any]:
    path = ROOT / rel_path
    symlink_target = None
    symlink_resolve_error = None
    if path.is_symlink():
        try:
            symlink_target = os.readlink(path)
        except OSError as exc:
            symlink_target = f"<readlink failed: {exc}>"
        try:
            path.resolve(strict=True)
        except OSError as exc:
            symlink_resolve_error = str(exc)
        except RuntimeError as exc:
            symlink_resolve_error = str(exc)
    status = {
        "path": rel_path,
        "exists": path.exists(),
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
        "is_symlink": path.is_symlink(),
        "symlink_target": symlink_target,
        "symlink_resolve_error": symlink_resolve_error,
        "bytes": path.stat().st_size if path.exists() and path.is_file() else None,
        "mtime_utc": mtime_utc(path),
        "sha256": sha256_file(path),
    }
    if path.is_dir():
        try:
            status["dir_entries_sample"] = sorted(p.name for p in path.iterdir())[:10]
        except OSError as exc:
            status["dir_entries_error"] = str(exc)
    return status


def iter_context_files() -> list[Path]:
    files = [
        ROOT / "progress.md",
        ROOT / "findings.md",
        ROOT / "task_plan.md",
        ROOT / "CLAUDE.md",
        ROOT / "AGENTS.md",
    ]
    files.extend(sorted(RESULTS.glob("*.md")))
    files.extend(sorted(RESULTS.glob("*.log")))
    files.extend(sorted((RESULTS / "remote_logs").glob("*.log")) if (RESULTS / "remote_logs").exists() else [])
    skip = {OUT_MD.resolve()}
    return [p for p in files if p.exists() and p.resolve() not in skip]


def context_hits(artifact: str, producer: str, max_hits: int = 12) -> list[dict[str, Any]]:
    needles = {artifact, Path(artifact).name, producer, Path(producer).name}
    hits: list[dict[str, Any]] = []
    for path in iter_context_files():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            if any(needle and needle in line for needle in needles):
                hits.append(
                    {
                        "path": str(path.relative_to(ROOT)),
                        "line": lineno,
                        "text": line.strip()[:260],
                    }
                )
                if len(hits) >= max_hits:
                    return hits
    return hits


def command_like_hits(hits: list[dict[str, Any]], producer: str) -> list[dict[str, Any]]:
    producer_name = Path(producer).name
    command_tokens = ("uv run python", "python3 ", "python ")
    out = []
    for hit in hits:
        text = hit["text"]
        if producer_name in text and any(token in text for token in command_tokens):
            out.append(hit)
    return out


def remote_probe(enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "status": "skipped"}
    remote = os.environ.get("GPU_REMOTE", "fiod@165.22.71.91")
    port = os.environ.get("GPU_PORT", "2243")
    quoted_files = " ".join(f"'{name}'" for name in REMOTE_FILES)
    remote_dirs = " ".join(f"'{name}'" for name in REMOTE_DIR_CANDIDATES)
    remote_cmd = (
        "ROOT=''; "
        f"for d in {remote_dirs}; do "
        "if [ -d \"$d\" ] && cd \"$d\" 2>/dev/null; then ROOT=\"$d\"; break; fi; "
        "done; "
        "if [ -z \"$ROOT\" ]; then exit 2; fi; "
        "printf 'REMOTE_ROOT %s\\n' \"$ROOT\"; "
        f"for f in {quoted_files}; do "
        "if [ -L \"$f\" ]; then "
        "target=$(readlink \"$f\" 2>/dev/null || true); "
        "if [ -e \"$f\" ]; then printf 'FOUND_SYMLINK %s -> %s ' \"$f\" \"$target\"; "
        "else printf 'BROKEN_SYMLINK %s -> %s ' \"$f\" \"$target\"; fi; "
        "stat -Lc '%s bytes mtime=%y' \"$f\" 2>/dev/null || stat -c '%s bytes mtime=%y' \"$f\"; "
        "elif [ -e \"$f\" ]; then "
        "printf 'FOUND %s ' \"$f\"; stat -c '%s bytes mtime=%y' \"$f\"; "
        "else printf 'MISSING %s\\n' \"$f\"; fi; done"
    )
    cmd = [
        "ssh",
        "-p",
        port,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        remote,
        remote_cmd,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )
        return {
            "enabled": True,
            "remote": remote,
            "port": port,
            "returncode": proc.returncode,
            "output": proc.stdout.strip().splitlines(),
        }
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        return {
            "enabled": True,
            "remote": remote,
            "port": port,
            "returncode": "timeout",
            "output": out.strip().splitlines(),
        }


def evaluate_candidate(row: dict[str, Any]) -> dict[str, Any]:
    artifact = row["artifact"]
    producer = row.get("producer", {}).get("path") if row.get("producer") else None
    artifact_path = ROOT / artifact
    artifact_stats = path_status(artifact)
    artifact_stats.update(csv_shape(artifact_path))
    hits = context_hits(artifact, producer or "")
    cmd_hits = command_like_hits(hits, producer or "")
    deps = [path_status(dep["path"]) | {"kind": dep["kind"], "purpose": dep["purpose"]} for dep in DEPENDENCY_MAP.get(artifact, [])]

    dependency_blockers = []
    for dep in deps:
        if not dep["exists"]:
            if dep["is_symlink"]:
                dependency_blockers.append(f"{dep['path']} is a broken/unresolvable symlink")
            else:
                dependency_blockers.append(f"{dep['path']} is missing locally")
        elif dep["is_symlink"] and dep["symlink_resolve_error"]:
            dependency_blockers.append(f"{dep['path']} is an unresolvable symlink")

    command_blocker = EXPECTED_COMMAND_GAPS.get(artifact, "No exact invocation/runtime log was found.")
    if cmd_hits:
        command_blocker += " Context command-like mentions exist, but this audit does not treat narrative/docstring usage as exact runtime provenance."

    blockers = ["exact command/runtime evidence missing", *dependency_blockers]
    if artifact == "results/hc_ssl_subj_embeddings.csv":
        blockers.append("80-epoch narrative conflicts with 50-epoch producer default")

    return {
        "artifact": artifact,
        "producer": producer,
        "producer_git_match": row.get("producer_git_match"),
        "artifact_stats": artifact_stats,
        "source_dependencies": deps,
        "context_hits": hits,
        "command_like_context_hits": cmd_hits,
        "command_evidence_status": "insufficient",
        "command_evidence_rationale": command_blocker,
        "required_evidence_gaps": sorted(set(blockers)),
        "decision": "leave_missing_no_patch",
        "rationale": (
            "Committed producer-script evidence plus artifact hash/mtime is not enough "
            "to synthesize a clean cache manifest. Required command/runtime/source "
            "evidence is missing or currently unrecoverable."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-remote", action="store_true", help="skip the bounded SSH recovery probe")
    args = parser.parse_args()

    source = load_json(SOURCE_AUDIT)
    candidates = [
        row
        for row in source.get("artifacts", [])
        if row.get("decision") == "manual_backfill_candidate_needs_human_patch"
    ]
    evaluated = [evaluate_candidate(row) for row in candidates]
    counts = Counter(row["decision"] for row in evaluated)
    remote = remote_probe(enabled=not args.skip_remote)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_manual_cache_backfill_evidence.py",
        "source_audit": str(SOURCE_AUDIT.relative_to(ROOT)),
        "policy": (
            "Do not backfill a clean manifest unless exact command/runtime/source-data "
            "evidence is concrete. Committed producer scripts and artifact hashes are "
            "candidate evidence only."
        ),
        "n_candidates": len(evaluated),
        "decision_counts": dict(sorted(counts.items())),
        "remote_recovery_probe": remote,
        "artifacts": evaluated,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Manual Cache Backfill Evidence Audit - 2026-05-09",
        "",
        "This non-mutating audit inspects the five missing-manifest artifacts that the origin audit classified as manual backfill candidates.",
        "It does not create any sidecar manifests.",
        "",
        "## Summary",
        "",
        f"- Manual candidates audited: `{len(evaluated)}`",
    ]
    for decision, count in sorted(counts.items()):
        lines.append(f"- `{decision}`: `{count}`")
    if remote["enabled"]:
        lines.append(f"- Remote recovery probe return code: `{remote['returncode']}`")
    else:
        lines.append("- Remote recovery probe: skipped")
    if remote.get("output"):
        lines.append("- Remote recovery probe output: see section below")
    lines.extend(["", "## Decisions", ""])
    for row in evaluated:
        deps = []
        for dep in row["source_dependencies"]:
            if dep["is_symlink"]:
                status = "broken symlink" if not dep["exists"] or dep["symlink_resolve_error"] else "symlink"
            elif dep["exists"]:
                status = "present"
            else:
                status = "missing"
            deps.append(f"{dep['path']}={status}")
        deps_text = ", ".join(deps) or "no explicit local dependency map"
        git_match = row["producer_git_match"]["short"] if row.get("producer_git_match") else "none"
        lines.append(
            f"- `{row['artifact']}` - `{row['decision']}`; producer `{row['producer']}`; "
            f"git match `{git_match}`; shape `{row['artifact_stats']['rows']}x{row['artifact_stats']['columns']}`; "
            f"source status `{deps_text}`. {row['command_evidence_rationale']}"
        )
    lines.extend(
        [
            "",
            "## Remote Recovery Probe",
            "",
        ]
    )
    if remote.get("output"):
        lines.extend(f"- `{line}`" for line in remote["output"])
    else:
        lines.append("- No remote output captured.")
    lines.extend(
        [
            "",
            "## Policy Decision",
            "",
            "All five artifacts remain diagnostic-only. Backfilling a clean manifest would require concrete exact command/runtime evidence and recoverable source-input hashes; those fields are not safely inferable from committed producer scripts or narrative notes.",
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({"n_candidates": len(evaluated), "decision_counts": dict(sorted(counts.items())), "remote_returncode": remote.get("returncode")}, indent=2))


if __name__ == "__main__":
    main()

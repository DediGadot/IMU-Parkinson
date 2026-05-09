#!/usr/bin/env python3
"""Classify remaining missing cache manifests by producer evidence.

The audit is intentionally non-mutating. It is meant to prevent the open
"manifest backfill" task from becoming provenance fabrication: only sidecars
with concrete command/script/git/file evidence should be patched separately.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CACHE_AUDIT = RESULTS / "cache_manifest_audit_20260508.json"
OUT_JSON = RESULTS / "missing_cache_manifest_origin_audit_20260509.json"
OUT_MD = RESULTS / "missing_cache_manifest_origin_audit_20260509.md"

TARGET_TOKENS = (
    "updrs",
    "mdsupdrs",
    "obs_subscore",
    "hoehn",
    "hy",
    "target",
    "label",
)

OUTPUT_HINTS = (
    "output",
    "creates",
    "wrote",
    "write",
    "to_csv",
    "np.save",
    "np.savez",
    "out_path",
    "default_output",
    "feature_cache",
    "add_argument(\"--out",
    "add_argument('--out",
)

SOURCE_HINTS = (
    "source:",
    "load",
    "loading",
    "from ",
    "required",
    "v2_features",
    "v2_cache",
    "fm_cache",
    "cache =",
)


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def latest_git_match(path: Path, expected_sha: str | None) -> dict[str, str] | None:
    if expected_sha is None:
        return None
    rel = str(path.relative_to(ROOT))
    for commit in git_commits_for_path(rel):
        blob = git_show_blob(commit, rel)
        if blob is None:
            continue
        if sha256_bytes(blob) == expected_sha:
            short = run_git(["rev-parse", "--short", commit]).stdout.strip()
            subject = run_git(["show", "-s", "--format=%s", commit]).stdout.strip()
            return {"commit": commit, "short": short, "subject": subject}
    return None


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def iter_repo_text_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if rel.parts[0] in {".git", ".venv", "__pycache__"}:
            continue
        if path.suffix in {".py", ".sh", ".md", ".txt", ".log"}:
            files.append(path)
    return files


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def mentions_for(needle: str, files: list[Path]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in files:
        text = read_text(path)
        if needle not in text:
            continue
        lines = []
        for i, line in enumerate(text.splitlines(), start=1):
            if needle in line:
                lines.append({"line": i, "text": line.strip()[:220]})
                if len(lines) >= 5:
                    break
        out.append(
            {
                "path": str(path.relative_to(ROOT)),
                "suffix": path.suffix,
                "is_cache_script": path.name.startswith("cache_") and path.suffix == ".py",
                "is_run_script": path.name.startswith("run_") and path.suffix == ".py",
                "mentions": lines,
            }
        )
    return out


def output_hint_in_lines(lines: list[dict[str, Any]]) -> bool:
    for line in lines:
        lower = line["text"].lower()
        if any(hint in lower for hint in OUTPUT_HINTS):
            if "source:" not in lower:
                return True
    return False


def source_hint_in_lines(lines: list[dict[str, Any]]) -> bool:
    for line in lines:
        lower = line["text"].lower()
        if any(hint in lower for hint in SOURCE_HINTS):
            return True
    return False


def token_overlap_score(path: str, artifact_name: str) -> int:
    script_stem = Path(path).stem
    for prefix in ("cache_", "run_"):
        if script_stem.startswith(prefix):
            script_stem = script_stem[len(prefix):]
    artifact_stem = Path(artifact_name).stem
    for suffix in ("_features", "_subj", "_recordings", "_recording"):
        script_stem = script_stem.replace(suffix, "")
        artifact_stem = artifact_stem.replace(suffix, "")
    script_tokens = {tok for tok in script_stem.split("_") if tok}
    artifact_tokens = {tok for tok in artifact_stem.split("_") if tok}
    return len(script_tokens & artifact_tokens)


def producer_score(mention: dict[str, Any], artifact_name: str) -> int:
    score = 0
    if mention["is_cache_script"]:
        score += 3
    if mention["is_run_script"]:
        score += 1
    score += 2 * token_overlap_score(mention["path"], artifact_name)
    if output_hint_in_lines(mention["mentions"]):
        score += 5
    if source_hint_in_lines(mention["mentions"]) and not output_hint_in_lines(mention["mentions"]):
        score -= 4
    return score


def likely_producer_mentions(py_mentions: list[dict[str, Any]], artifact_name: str) -> list[dict[str, Any]]:
    scored = []
    for mention in py_mentions:
        score = producer_score(mention, artifact_name)
        if score > 0:
            scored.append((score, mention))
    scored.sort(key=lambda item: (-item[0], item[1]["path"]))
    return [mention for _, mention in scored]


def script_output_artifacts(script_text: str, diagnostic_artifacts: set[str]) -> set[str]:
    produced: set[str] = set()
    for artifact in diagnostic_artifacts:
        name = Path(artifact).name
        for line in script_text.splitlines():
            if name not in line:
                continue
            lower = line.lower()
            if any(hint in lower for hint in OUTPUT_HINTS) and "source:" not in lower:
                produced.add(artifact)
    return produced


def classify(row: dict[str, Any], files: list[Path], diagnostic_artifacts: set[str]) -> dict[str, Any]:
    artifact = row["artifact"]
    name = Path(artifact).name
    mentions = mentions_for(name, files)
    py_mentions = [m for m in mentions if m["path"].endswith(".py")]
    producer_mentions = likely_producer_mentions(py_mentions, name)
    producer = producer_mentions[0] if producer_mentions else None
    producer_path = ROOT / producer["path"] if producer else None
    producer_text = read_text(producer_path) if producer_path else ""
    producer_sha = sha256_file(producer_path) if producer_path else None
    producer_git_match = latest_git_match(producer_path, producer_sha) if producer_path else None
    produced_by_same_script = script_output_artifacts(producer_text, diagnostic_artifacts)

    upstream_refs = sorted(
        artifact_name
        for artifact_name in diagnostic_artifacts
        if artifact_name != artifact
        and artifact_name not in produced_by_same_script
        and Path(artifact_name).name in producer_text
    )
    target_token_hits = sorted({tok for tok in TARGET_TOKENS if tok in producer_text.lower()})
    has_log_or_doc_mentions = any(not m["path"].endswith(".py") for m in mentions)

    if not producer:
        decision = "insufficient_producer_evidence"
        rationale = "No Python producer mention was found for this artifact name."
    elif upstream_refs:
        decision = "blocked_by_upstream_diagnostic_cache"
        rationale = "Producer depends on cache artifacts that are themselves missing/partial-manifest diagnostic-only."
    elif target_token_hits:
        decision = "manual_review_label_or_clinical_tokens"
        rationale = "Producer text contains target/clinical-label-like tokens; labels_used cannot be asserted false automatically."
    elif not producer_git_match:
        decision = "needs_committed_producer_before_backfill"
        rationale = "Producer exists locally but the current bytes were not found in git history."
    elif not has_log_or_doc_mentions:
        decision = "needs_command_runtime_evidence"
        rationale = "Producer is committed and mentions the artifact, but exact command/time/runtime evidence is absent."
    else:
        decision = "manual_backfill_candidate_needs_human_patch"
        rationale = "Producer is committed and context mentions exist, but a human must verify command, timestamp, fold scope, and leakage rationale before patching."

    return {
        "artifact": artifact,
        "bytes": row.get("bytes"),
        "sha256": row.get("sha256"),
        "shape": {"rows": row.get("rows"), "columns": row.get("columns")},
        "producer": producer,
        "producer_alternatives": producer_mentions[1:4],
        "producer_sha256": producer_sha,
        "producer_git_match": producer_git_match,
        "same_script_outputs": sorted(produced_by_same_script),
        "n_mentions": len(mentions),
        "upstream_diagnostic_refs": upstream_refs,
        "target_token_hits": target_token_hits,
        "decision": decision,
        "rationale": rationale,
    }


def main() -> None:
    audit = load_json(CACHE_AUDIT)
    diagnostic_artifacts = {
        row["artifact"]
        for row in audit.get("artifacts", [])
        if row.get("status") != "manifest_complete_clean_by_construction"
    }
    rows = [
        row
        for row in audit.get("artifacts", [])
        if row.get("status") == "missing_manifest_diagnostic_only"
    ]
    files = iter_repo_text_files()
    classified = [classify(row, files, diagnostic_artifacts) for row in rows]
    counts = Counter(row["decision"] for row in classified)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_missing_cache_manifest_origins.py",
        "source_audit": str(CACHE_AUDIT.relative_to(ROOT)),
        "policy": "Non-mutating origin map. Do not create clean manifests from this audit alone; exact command/runtime/git/data-hash evidence must still be concrete.",
        "n_missing_manifests": len(classified),
        "decision_counts": dict(sorted(counts.items())),
        "artifacts": classified,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Missing Cache Manifest Origin Audit - 2026-05-09",
        "",
        "This is a non-mutating origin map for cache-like artifacts that still have no sidecar manifest.",
        "It does not make any artifact headline-safe by itself.",
        "",
        "## Summary",
        "",
        f"- Missing manifests audited: `{len(classified)}`",
    ]
    for key, value in sorted(counts.items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Artifacts", ""])
    for row in classified:
        producer = row["producer"]["path"] if row["producer"] else "none"
        git_match = row["producer_git_match"]["short"] if row["producer_git_match"] else "none"
        upstream = ", ".join(row["upstream_diagnostic_refs"][:5]) or "none"
        if len(row["upstream_diagnostic_refs"]) > 5:
            upstream += f", +{len(row['upstream_diagnostic_refs']) - 5} more"
        tokens = ", ".join(row["target_token_hits"]) or "none"
        lines.append(
            f"- `{row['artifact']}` - `{row['decision']}`; producer `{producer}`; "
            f"git match `{git_match}`; upstream diagnostic refs `{upstream}`; "
            f"target-token hits `{tokens}`. {row['rationale']}"
        )
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({"n_missing_manifests": len(classified), "decision_counts": dict(sorted(counts.items()))}, indent=2))


if __name__ == "__main__":
    main()

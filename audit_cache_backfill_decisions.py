#!/usr/bin/env python3
"""Record backfill decisions for partial cache manifests.

This is deliberately stricter than the candidate classifier: a committed script
hash can make a sidecar a candidate, but it is not enough to synthesize missing
runtime fields such as the exact command. This script records the no-patch
decision for remaining manual candidates so future agents do not treat a
candidate list as permission to fabricate provenance.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CANDIDATES = RESULTS / "cache_backfill_candidates_20260508.json"
OUT_JSON = RESULTS / "cache_backfill_decisions_20260508.json"
OUT_MD = RESULTS / "cache_backfill_decisions_20260508.md"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def decide(row: dict[str, Any]) -> dict[str, Any]:
    missing = list(row.get("missing_required_fields", []))
    nullish = list(row.get("nullish_required_fields", []))
    git_matches = row.get("git_script_sha_matches", [])
    blocking = sorted(set(missing + nullish))
    exact_command_missing = "command" in blocking
    schema_fields_missing = bool(
        {
            "script",
            "created_at_utc",
            "fold_scope",
            "cohort_statistics_used",
            "normalization_scope",
            "leakage_rationale",
        }.intersection(blocking)
    )
    if exact_command_missing or schema_fields_missing:
        decision = "leave_partial_no_patch"
        rationale = (
            "Committed script-hash evidence is insufficient to promote this "
            "older-schema manifest because exact command/runtime schema fields "
            "are missing. Do not infer them from narrative docs."
        )
    else:
        decision = "eligible_for_manual_patch"
        rationale = "No command/schema blocker remains; inspect manually before patching."
    return {
        "artifact": row.get("artifact"),
        "manifest": row.get("manifest"),
        "script": row.get("script"),
        "candidate_recommendation": row.get("recommendation"),
        "decision": decision,
        "rationale": rationale,
        "blocking_fields": blocking,
        "git_script_sha_matches": git_matches,
    }


def main() -> None:
    candidates = load_json(CANDIDATES)
    manual_rows = [
        row
        for row in candidates.get("artifacts", [])
        if row.get("recommendation") == "manual_backfill_candidate"
    ]
    decisions = [decide(row) for row in manual_rows]
    counts: dict[str, int] = {}
    for row in decisions:
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_cache_backfill_decisions.py",
        "source_candidates": str(CANDIDATES.relative_to(ROOT)),
        "policy": (
            "Do not synthesize missing manifest fields. A committed script hash "
            "is candidate evidence only; command/runtime fields need concrete evidence."
        ),
        "searched_context": [
            "progress.md",
            "findings.md",
            "task_plan.md",
            "results/cache_backfill_candidates_20260508.json",
            "results/cache_manifest_audit_20260508.json",
            "duplicate sidecars under results/results/",
            "results/cache_features.log",
        ],
        "counts": counts,
        "decisions": decisions,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Cache Backfill Decisions - 2026-05-08",
        "",
        "This report records why remaining manual backfill candidates were left partial.",
        "It does not modify manifests.",
        "",
        "## Summary",
        "",
    ]
    for key, value in sorted(counts.items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Decisions", ""])
    for row in decisions:
        matches = ", ".join(m["short"] for m in row.get("git_script_sha_matches", [])) or "none"
        lines.append(
            f"- `{row['artifact']}` - `{row['decision']}`; "
            f"script `{row['script']}`; git script match `{matches}`; "
            f"blocking fields={row['blocking_fields']}. {row['rationale']}"
        )
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({"counts": counts, "n_manual_candidates": len(decisions)}, indent=2))


if __name__ == "__main__":
    main()

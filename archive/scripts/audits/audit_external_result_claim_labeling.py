#!/usr/bin/env python3
"""Audit external-validation result wording for internal-headline overclaim."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "external_result_claim_labeling_audit_20260509.json"
OUT_MD = RESULTS / "external_result_claim_labeling_audit_20260509.md"

FILES = [
    ROOT / "paper.md",
    ROOT / "CURRENT_PAPER.html",
    ROOT / "CLAUDE.md",
    ROOT / "AGENTS.md",
    ROOT / "task_plan.md",
    ROOT / "progress.md",
    ROOT / "findings.md",
    RESULTS / "thread_goal_completion_audit_20260508.md",
    RESULTS / "current_best_pipeline_artifact_index_20260508.md",
]

EXTERNAL_ARTIFACTS = [
    RESULTS / "iter39_fogstar_zeroshot_20260508_143717.json",
    RESULTS / "iter49_cops_zeroshot.json",
    RESULTS / "iter51_tlvmc_defog_zeroshot.json",
    RESULTS / "iter52_pdfe_turning_zeroshot.json",
]

MENTION = re.compile(
    r"\b("
    r"FoG[- ]?STAR|COPS|TLVMC|DeFOG|PDFE|PADS|iter39|iter49|iter51|iter52|"
    r"0\.2499|0\.2412|0\.2535|0\.2695|0\.4020|0\.3100|0\.3450|-0\.1008"
    r")\b",
    re.IGNORECASE,
)
DANGEROUS = re.compile(
    r"\b("
    r"headline|canonical|canonicals|audit[- ]truth|current\s+T3|deployment|deployable|"
    r"breakthrough|ceiling break|ceiling-break|booster|promote|promotable|"
    r"replacement|update|move|internal|complete|achieved|goal_complete|best|SOTA"
    r")\b",
    re.IGNORECASE,
)
ALLOWED = re.compile(
    r"\b("
    r"external|external-only|external-validity|transportability|zero-shot|"
    r"sanity|sanity-only|within-protocol|within-cohort|within-COPS|within-PDFE|"
    r"document-only|request-gated|access-gated|DUA|blocked|partial|negative|weak|"
    r"null|failed|fails|no internal|not internal|not a new internal|"
    r"no canonical|no internal .*canonical|cannot update|does not update|"
    r"does not change|does not move|cannot move|not a headline|not a breakthrough|"
    r"not.*ceiling|no.*ceiling|do not use|do not update|not promotable|"
    r"paper transportability|paper-rigor|clinical-plus-wrist|clinical\+wrist|"
    r"wrist-only.*null|transfer fails|failed WearGait transfer|"
    r"does not break|not complete|not achieved|route audit|claim-label"
    r")\b",
    re.IGNORECASE,
)

REQUIRED_SNIPPETS = {
    "paper.md": [
        "This is external-validity evidence, not an internal CCC breakthrough.",
        "It does not update the internal WearGait-PD T3 headline.",
        "TLVMC/DeFOG remains external-validity evidence only",
        "iter52 is external transportability evidence only",
    ],
    "CLAUDE.md": [
        "PARTIAL external validity, no internal ceiling movement",
        "no TLVMC/DeFOG result may update the internal WearGait-PD T3 canonical",
        "no internal WearGait-PD T3 canonical update",
    ],
    "AGENTS.md": [
        "partial, not a new internal T3 route",
        "do not update internal T3 canonicals from any external result",
        "no internal T3 canonical update",
    ],
    "results/thread_goal_completion_audit_20260508.md": [
        "external transportability evidence only",
        "no internal CCC update",
        "No internal WearGait-PD T3 canonical update is allowed",
    ],
    "results/current_best_pipeline_artifact_index_20260508.md": [
        "partial external-validity evidence only",
        "external-validity evidence only and does not change the internal T3 headline",
        "external evidence only and does not move the internal T3 headline",
    ],
}


def strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


def normalize_html(text: str) -> str:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "\n", text, flags=re.IGNORECASE | re.DOTALL)

    def heading(match: re.Match[str]) -> str:
        level = int(match.group(1))
        title = re.sub(r"\s+", " ", strip_tags(match.group(2))).strip()
        return "\n" + ("#" * level) + f" {title}\n"

    text = re.sub(
        r"<h([1-6])\b[^>]*>(.*?)</h\1>",
        heading,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    def table_row(match: re.Match[str]) -> str:
        cells = [
            re.sub(r"\s+", " ", strip_tags(cell)).strip()
            for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", match.group(1), flags=re.IGNORECASE | re.DOTALL)
        ]
        cells = [cell for cell in cells if cell]
        return "\n" + " | ".join(cells) + "\n" if cells else "\n"

    text = re.sub(r"<tr\b[^>]*>(.*?)</tr>", table_row, text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"</(p|li|tr|blockquote|div|section|header|table)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</t[dh]>", " | ", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def read(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return normalize_html(text) if path.suffix == ".html" else text


def current_scope(path: Path, text: str) -> str:
    rel = str(path.relative_to(ROOT))
    if rel == "task_plan.md":
        marker = "\n---\n\n# ACTIVE MISSION"
        return text.split(marker, 1)[0]
    if rel == "progress.md":
        marker = "\n## Session: 2026-05-05"
        return text.split(marker, 1)[0]
    if rel == "findings.md":
        early = text.split("\n## F31", 1)[0]
        tail_marker = "\n## F-iter39-fogstar-20260508"
        tail = text.split(tail_marker, 1)[1] if tail_marker in text else ""
        return early + "\n## F-iter39-fogstar-20260508" + tail
    return text


def current_section(lines: list[str], idx: int) -> str:
    for j in range(idx, -1, -1):
        line = lines[j].strip()
        if re.match(r"^#{1,6}\s+\S", line):
            return line
    return ""


def context(lines: list[str], idx: int, radius: int = 6) -> str:
    start = max(0, idx - radius)
    end = min(len(lines), idx + radius + 1)
    return " ".join(lines[start:end])


def audit_file(path: Path) -> dict[str, Any]:
    text = current_scope(path, read(path))
    rel = str(path.relative_to(ROOT))
    lines = text.splitlines()
    findings = []
    mentions = 0
    for idx, line in enumerate(lines):
        if not MENTION.search(line):
            continue
        mentions += 1
        ctx = context(lines, idx)
        section = current_section(lines, idx)
        trigger_text = f"{line} {section}"
        if not DANGEROUS.search(trigger_text):
            continue
        if ALLOWED.search(ctx) or ALLOWED.search(section):
            continue
        findings.append(
            {
                "path": rel,
                "line": idx + 1,
                "section": section,
                "line_text": line.strip(),
                "context": ctx.strip(),
            }
        )
    missing = [
        snippet
        for snippet in REQUIRED_SNIPPETS.get(rel, [])
        if snippet not in text
    ]
    return {
        "path": rel,
        "current_scope_lines": len(lines),
        "mentions": mentions,
        "findings": findings,
        "missing_required_snippets": missing,
    }


def flatten_json(value: Any) -> str:
    parts: list[str] = []
    if isinstance(value, dict):
        for key, inner in value.items():
            parts.append(str(key))
            parts.append(flatten_json(inner))
    elif isinstance(value, list):
        for inner in value:
            parts.append(flatten_json(inner))
    elif value is not None:
        parts.append(str(value))
    return " ".join(parts)


def has_internal_update_false(value: Any) -> bool:
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in {
                "internal_t3_canonical_update_allowed",
                "internal_canonical_update_allowed",
                "no_internal_canonical_change",
            }:
                if inner is False and key != "no_internal_canonical_change":
                    return True
                if inner is True and key == "no_internal_canonical_change":
                    return True
            if has_internal_update_false(inner):
                return True
    elif isinstance(value, list):
        return any(has_internal_update_false(inner) for inner in value)
    return False


def audit_external_artifact(path: Path) -> dict[str, Any]:
    rel = str(path.relative_to(ROOT))
    if not path.exists():
        return {
            "path": rel,
            "exists": False,
            "has_external_only_decision": False,
            "hard_failures": ["missing external-result artifact"],
        }
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    flat = flatten_json(data).lower()
    has_external_only_decision = (
        has_internal_update_false(data)
        or "no_internal" in flat
        or "external_zero_shot_only" in flat
        or "zero_shot_external_validation_only" in flat
        or "external transportability" in flat
        or "external-validation route only" in flat
    )
    suspicious_promotion = any(
        phrase in flat
        for phrase in [
            "canonical_update_allowed true",
            "internal_t3_canonical_update_allowed true",
            "internal canonical update allowed true",
            "promote_to_internal true",
            "is_canonical_update true",
        ]
    )
    hard_failures = []
    if not has_external_only_decision:
        hard_failures.append("missing external-only / no-internal-canonical-change decision")
    if suspicious_promotion:
        hard_failures.append("artifact appears to permit internal/canonical promotion")
    return {
        "path": rel,
        "exists": True,
        "has_external_only_decision": has_external_only_decision,
        "suspicious_promotion": suspicious_promotion,
        "decision": data.get("decision"),
        "policy": data.get("policy"),
        "interpretation": data.get("interpretation"),
        "hard_failures": hard_failures,
    }


def build_report() -> dict[str, Any]:
    docs = [audit_file(path) for path in FILES if path.exists()]
    artifact_checks = [audit_external_artifact(path) for path in EXTERNAL_ARTIFACTS]
    findings = [row for doc in docs for row in doc["findings"]]
    missing = [
        {"path": doc["path"], "missing_required_snippet": snippet}
        for doc in docs
        for snippet in doc["missing_required_snippets"]
    ]
    artifact_failures = [
        {"path": row["path"], "failure": failure}
        for row in artifact_checks
        for failure in row["hard_failures"]
    ]
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_result_claim_labeling.py",
        "policy": (
            "External FoG-STAR, COPS, TLVMC/DeFOG, PDFE, and PADS results may "
            "support transportability or within-dataset sanity claims only. They "
            "must not be framed as internal WearGait-PD T3 headline, canonical, "
            "deployment, or ceiling-break updates."
        ),
        "passed": not findings and not missing and not artifact_failures,
        "claim_patterns": [
            "FoG-STAR",
            "COPS",
            "TLVMC/DeFOG",
            "PDFE",
            "PADS",
            "0.2499",
            "0.2412",
            "0.2535",
            "0.2695",
            "0.4020",
        ],
        "findings": findings,
        "missing_required_snippets": missing,
        "artifact_failures": artifact_failures,
        "artifact_checks": artifact_checks,
        "docs": docs,
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# External Result Claim Labeling Audit - 2026-05-09",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Findings: `{len(report['findings'])}`",
        f"- Missing required snippets: `{len(report['missing_required_snippets'])}`",
        f"- Artifact failures: `{len(report['artifact_failures'])}`",
        "",
    ]
    if report["findings"]:
        lines.extend(["## Findings", ""])
        for row in report["findings"]:
            lines.append(
                f"- `{row['path']}:{row['line']}` in section `{row['section']}`: {row['line_text']}"
            )
    if report["missing_required_snippets"]:
        lines.extend(["## Missing Required Snippets", ""])
        for row in report["missing_required_snippets"]:
            lines.append(f"- `{row['path']}` missing `{row['missing_required_snippet']}`")
    if report["artifact_failures"]:
        lines.extend(["## Artifact Failures", ""])
        for row in report["artifact_failures"]:
            lines.append(f"- `{row['path']}`: {row['failure']}")
    lines.extend(["", "## External Artifact Checks", ""])
    for row in report["artifact_checks"]:
        lines.append(
            f"- `{row['path']}`: external-only decision `{row['has_external_only_decision']}`, "
            f"hard failures `{len(row['hard_failures'])}`"
        )
    lines.extend(["", "## Scanned Documents", ""])
    for doc in report["docs"]:
        lines.append(
            f"- `{doc['path']}`: mentions `{doc['mentions']}`, findings `{len(doc['findings'])}`, "
            f"missing snippets `{len(doc['missing_required_snippets'])}`"
        )
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({
        "passed": report["passed"],
        "findings": len(report["findings"]),
        "missing_required_snippets": len(report["missing_required_snippets"]),
        "artifact_failures": len(report["artifact_failures"]),
    }, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

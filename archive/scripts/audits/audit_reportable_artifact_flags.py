#!/usr/bin/env python3
"""Audit raw reportable-artifact flags against current claim policy.

Some historical lockbox JSONs contain fields that were true at the time of the
run but are no longer the current paper policy after later leakage/target/caveat
audits. This script does not mutate those artifacts. It records the current
interpretation layer explicitly so downstream automation does not promote an
archived flag into a current canonical claim.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "reportable_artifact_flag_audit_20260509.json"
OUT_MD = RESULTS / "reportable_artifact_flag_audit_20260509.md"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def approx(value: Any, expected: float, tol: float = 5e-4) -> bool:
    try:
        return abs(float(value) - expected) <= tol
    except (TypeError, ValueError):
        return False


def get_path(obj: dict[str, Any], dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def doc_has_all(text: str, snippets: list[str]) -> bool:
    return all(snippet in text for snippet in snippets)


def build_report() -> dict[str, Any]:
    docs = {
        "CLAUDE.md": read_text(ROOT / "CLAUDE.md"),
        "paper.md": read_text(ROOT / "paper.md"),
        "artifact_index": read_text(RESULTS / "current_best_pipeline_artifact_index_20260508.md"),
        "completion_audit": read_text(RESULTS / "thread_goal_completion_audit_20260508.md"),
    }
    joined_docs = "\n".join(docs.values())

    policies = [
        {
            "id": "t1_iter12_honest_floor",
            "path": "results/t1_iter12_honest_composite.json",
            "current_claim_status": "canonical_floor",
            "metric_checks": {"ccc": 0.6550, "mae": 1.5614, "n": 94},
            "raw_flag_paths": ["is_lockbox_headline", "is_canonical_update"],
            "required_doc_snippets": [
                "T1 LOOCV CCC = 0.6550",
                "canonical floor",
            ],
            "stale_raw_flags_allowed": {},
        },
        {
            "id": "t1_iter34_hybrid_candidate",
            "path": "results/lockbox_t1_iter34_hybrid_20260506_141720.json",
            "current_claim_status": "strongest_candidate_caveated_not_canonical_replacement",
            "metric_checks": {"ccc": 0.7366, "mae": 1.731, "n": 93},
            "raw_flag_paths": [
                "is_lockbox_headline",
                "is_canonical_update",
                "is_post_publication_replication_target",
                "verdict_vs_iter33b",
            ],
            "required_doc_snippets": [
                "STRONGEST CANDIDATE",
                "iter34 is locally framed as a strongest candidate",
                "iter12-honest 0.6550 as the canonical floor",
                "auxiliary-label/order caveat",
                "not as an all-null-gates-green canonical replacement",
            ],
            "stale_raw_flags_allowed": {
                "is_canonical_update": {
                    "raw_value": True,
                    "current_value": False,
                    "reason": (
                        "Later P2, auxiliary-label/order, and claim-labeling audits "
                        "demote iter34 to strongest candidate; the archived boolean "
                        "must not be used as current claim policy."
                    ),
                }
            },
        },
        {
            "id": "t1_iter46_etrobust_diagnostic",
            "path": "results/lockbox_t1_iter46_etrobust_20260508_162825.json",
            "current_claim_status": "negative_diagnostic_not_canonical",
            "metric_checks": {"ccc": 0.7269, "mae": 1.7578, "n": 93},
            "raw_flag_paths": [
                "verdict.is_lockbox_headline",
                "verdict.is_canonical_update",
                "verdict.breaks_iter34_ceiling",
                "verdict.decision",
            ],
            "required_doc_snippets": [
                "T1 iter46 ET-only robustification",
                "not a ceiling break and not a canonical update",
                "Diagnostic only",
            ],
            "stale_raw_flags_allowed": {
                "verdict.is_lockbox_headline": {
                    "raw_value": True,
                    "current_value": "diagnostic_lockbox_only",
                    "reason": "The lockbox ran as a diagnostic follow-up, but its own verdict is negative.",
                }
            },
        },
        {
            "id": "t3_iter5_historical_target_contaminated",
            "path": "results/lockbox_t3_iter5_A3_tier1_20260502_171604.json",
            "current_claim_status": "historical_target_contaminated_not_current",
            "metric_checks": {"ccc": 0.5227, "mae": 7.525, "n": 98},
            "raw_flag_paths": ["is_lockbox_headline", "is_canonical_update"],
            "required_doc_snippets": [
                "T3 iter5 (2026-05-02) — historical clinical-augmented Stage 1 result, now target-contaminated",
                "Do not cite iter5 `0.5227` as a deployable result",
                "target-contaminated historical artifacts",
            ],
            "stale_raw_flags_allowed": {
                "is_lockbox_headline": {
                    "raw_value": True,
                    "current_value": "historical_only",
                    "reason": "Later iter41/iter47 target-construction audits supersede this lockbox.",
                }
            },
        },
        {
            "id": "t3_iter47_validrange_current",
            "path": "results/iter47_invalidcode_20260508_194605.json",
            "current_claim_status": "canonical_audit_truth",
            "metric_checks": {"cells.drop_allmissing_validrange.stage2_current.ccc": 0.3784},
            "raw_flag_paths": ["decision", "formula_sha256"],
            "required_doc_snippets": [
                "T3 corrected target (total UPDRS-III) — CANONICAL AUDIT TRUTH",
                "valid-range-corrected T3 LOOCV CCC = 0.3784",
                "valid-range corrected LOSO two-way",
            ],
            "stale_raw_flags_allowed": {},
        },
    ]

    checks: list[dict[str, Any]] = []
    stale_raw_flags: list[dict[str, Any]] = []
    hard_failures: list[dict[str, Any]] = []

    for policy in policies:
        path = ROOT / policy["path"]
        exists = path.exists()
        artifact = load_json(path) if exists else {}
        raw_flags = {flag: get_path(artifact, flag) for flag in policy["raw_flag_paths"]}

        metric_results = {}
        metrics_pass = True
        for key, expected in policy["metric_checks"].items():
            if key == "cells.drop_allmissing_validrange.stage2_current.ccc":
                value = None
                for cell in artifact.get("cells", []):
                    if (
                        cell.get("cohort") == "drop_allmissing_validrange"
                        and cell.get("stage2_policy") == "stage2_current"
                    ):
                        value = cell.get("new_refit_metrics", {}).get("ccc")
                        break
            else:
                value = artifact.get(key)
            passed = approx(value, expected)
            metric_results[key] = {
                "value": value,
                "expected": expected,
                "passed": passed,
            }
            metrics_pass = metrics_pass and passed

        docs_pass = doc_has_all(joined_docs, policy["required_doc_snippets"])
        stale_allowed = policy["stale_raw_flags_allowed"]
        stale_ok = True
        for flag, rule in stale_allowed.items():
            raw_value = get_path(artifact, flag)
            matched = raw_value == rule["raw_value"]
            stale_ok = stale_ok and matched
            stale_raw_flags.append(
                {
                    "artifact": policy["id"],
                    "path": policy["path"],
                    "flag": flag,
                    "raw_value": raw_value,
                    "current_claim_value": rule["current_value"],
                    "matched_expected_raw_value": matched,
                    "reason": rule["reason"],
                }
            )

        check = {
            "id": policy["id"],
            "path": policy["path"],
            "exists": exists,
            "current_claim_status": policy["current_claim_status"],
            "raw_flags": raw_flags,
            "metric_results": metric_results,
            "required_doc_snippets": policy["required_doc_snippets"],
            "docs_pass": docs_pass,
            "stale_raw_flags_allowed": stale_allowed,
            "passed": bool(exists and metrics_pass and docs_pass and stale_ok),
        }
        checks.append(check)
        if not check["passed"]:
            hard_failures.append(check)

    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_reportable_artifact_flags.py",
        "policy": (
            "Current claim status is defined by the post-audit policy layer, not "
            "by archived lockbox booleans alone. Superseded raw flags are retained "
            "for reproducibility but must be explicitly overridden."
        ),
        "passed": not hard_failures,
        "checks": checks,
        "stale_raw_flags": stale_raw_flags,
        "hard_failures": hard_failures,
    }


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Reportable Artifact Flag Audit - 2026-05-09",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Checks: `{len(report['checks'])}`",
        f"- Superseded raw flags recorded: `{len(report['stale_raw_flags'])}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Checks",
        "",
        "| Artifact | Current status | Passed | Raw flags |",
        "|---|---|---:|---|",
    ]
    for check in report["checks"]:
        flags = ", ".join(
            f"{k}={v!r}" for k, v in check["raw_flags"].items()
        )
        lines.append(
            f"| `{check['id']}` | `{check['current_claim_status']}` | "
            f"`{check['passed']}` | {flags} |"
        )
    lines.extend(["", "## Superseded Raw Flags", ""])
    for row in report["stale_raw_flags"]:
        lines.append(
            f"- `{row['artifact']}` has raw `{row['flag']}={row['raw_value']!r}`; "
            f"current claim value is `{row['current_claim_value']}`. {row['reason']}"
        )
    if report["hard_failures"]:
        lines.extend(["", "## Hard Failures", ""])
        for row in report["hard_failures"]:
            lines.append(f"- `{row['id']}` failed; inspect `{row['path']}`")
    lines.extend(["", f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`", ""])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "checks": len(report["checks"]),
                "stale_raw_flags": len(report["stale_raw_flags"]),
                "hard_failures": len(report["hard_failures"]),
            },
            indent=2,
        )
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

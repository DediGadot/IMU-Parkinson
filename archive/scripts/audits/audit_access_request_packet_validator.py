#!/usr/bin/env python3
"""Audit the generic external access request packet validator."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TRACKER = RESULTS / "access_submission_tracker_20260509.json"
VALIDATOR = ROOT / "scripts" / "validate_access_request_packet.py"
OUT_JSON = RESULTS / "access_request_packet_validator_audit_20260515.json"
OUT_MD = RESULTS / "access_request_packet_validator_audit_20260515.md"

PLACEHOLDER_RE = re.compile(r"\[[A-Z0-9_]+\]")
SYNTH_DIR = RESULTS / "access_request_packet_validator_synthetic"
EXPECTED_ROUTE_IDS = [
    "ppmi_verily",
    "ppp_pd_vme",
    "watchpd",
    "cns_portugal_lobo",
    "hssayeni_mjff",
    "icicle_gait",
]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{rel(path)} must contain a JSON object")
    return payload


def replace_placeholders(text: str, route_id: str) -> str:
    for placeholder in sorted(set(PLACEHOLDER_RE.findall(text))):
        key = placeholder.strip("[]")
        value = f"Synthetic {route_id} value for {key}"
        if key == "EMAIL" or key.endswith("_EMAIL"):
            value = f"synthetic.{route_id}.{key.lower()}@example.edu"
        if key in {"YES_NO", "YES_NO_DATE"}:
            value = "Yes, synthetic confirmation"
        text = text.replace(placeholder, value)
    return text


def run_validator(route_id: str, packet: Path, *, allow_placeholders: bool = False) -> dict[str, Any]:
    cmd = [
        "uv",
        "run",
        "python",
        str(VALIDATOR),
        "--route-id",
        route_id,
        "--packet",
        str(packet),
    ]
    if allow_placeholders:
        cmd.append("--allow-placeholders")
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=120,
    )
    parsed: dict[str, Any] | None = None
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = None
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "parsed": parsed,
        "output_tail": proc.stdout[-1200:],
    }


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Access Request Packet Validator Audit - 2026-05-15",
        "",
        "This audits the generic content-free completed-packet validator for the gated external access queue. It is not a submission, approval, schema probe, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Validator: `{report['validator']}`",
        f"- Route count: `{len(report['route_results'])}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Route Results",
        "",
        "| Route | Synthetic pass | Template fail | Allow-template pass |",
        "|---|---:|---:|---:|",
    ]
    for route_id, result in report["route_results"].items():
        lines.append(
            "| "
            f"`{route_id}` | "
            f"`{result['synthetic_passed']}` | "
            f"`{result['template_failed']}` | "
            f"`{result['template_allowed_passed']}` |"
        )
    lines.extend(["", "## Checks", ""])
    for row in report["checks"]:
        lines.append(f"- `{row['passed']}` {row['name']}")
    if report["hard_failures"]:
        lines.extend(["", "## Hard Failures", ""])
        for failure in report["hard_failures"]:
            lines.append(f"- {failure['name']}: {failure['evidence']}")
    else:
        lines.extend(["", "## Hard Failures", "", "- None."])
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "The generic route-packet preflight is ready for user-side completed-packet checks across the six submit-ready routes. It prints only redacted pass/fail evidence and does not unlock protected-data work.",
        ]
    )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    SYNTH_DIR.mkdir(exist_ok=True)
    tracker = load_json(TRACKER)
    routes = {row.get("id"): row for row in tracker.get("routes", [])}

    checks: list[dict[str, Any]] = [
        check(
            "validator script exists",
            VALIDATOR.exists(),
            {"validator": rel(VALIDATOR)},
        ),
        check(
            "tracker exposes expected six route ids",
            list(routes.keys())[: len(EXPECTED_ROUTE_IDS)] == EXPECTED_ROUTE_IDS,
            {"route_ids": list(routes.keys())},
        ),
    ]
    route_results: dict[str, dict[str, Any]] = {}

    for route_id in EXPECTED_ROUTE_IDS:
        row = routes.get(route_id) or {}
        source = ROOT / str((row.get("packet") or {}).get("path", ""))
        synthetic = SYNTH_DIR / f"{route_id}_completed.md"
        synthetic.write_text(replace_placeholders(source.read_text(encoding="utf-8"), route_id), encoding="utf-8")

        synthetic_result = run_validator(route_id, synthetic)
        template_result = run_validator(route_id, source)
        template_allowed_result = run_validator(route_id, source, allow_placeholders=True)

        synthetic_parsed = synthetic_result.get("parsed") or {}
        template_parsed = template_result.get("parsed") or {}
        template_allowed_parsed = template_allowed_result.get("parsed") or {}
        route_results[route_id] = {
            "synthetic_passed": synthetic_result["returncode"] == 0
            and synthetic_parsed.get("passed") is True,
            "template_failed": template_result["returncode"] != 0
            and template_parsed.get("checks", {}).get("placeholders_replaced", {}).get("passed")
            is False,
            "template_allowed_passed": template_allowed_result["returncode"] == 0
            and template_allowed_parsed.get("passed") is True,
            "template_allowed_decision": template_allowed_parsed.get("decision"),
            "template_allowed_pre_submission_preflight_valid": template_allowed_parsed.get(
                "pre_submission_preflight_valid"
            ),
            "template_allowed_not_valid_for_submission": template_allowed_parsed.get(
                "not_valid_for_submission"
            ),
            "synthetic_decision": synthetic_parsed.get("decision"),
            "synthetic_hard_failures": synthetic_parsed.get("hard_failures"),
            "template_decision": template_parsed.get("decision"),
            "template_remaining_placeholders": template_parsed.get("checks", {})
            .get("placeholders_replaced", {})
            .get("remaining_placeholder_count"),
            "redaction_passed": (
                str(synthetic) not in synthetic_result["output_tail"]
                and synthetic.name not in synthetic_result["output_tail"]
                and str(source) not in template_result["output_tail"]
                and source.name not in template_result["output_tail"]
            ),
        }
        checks.extend(
            [
                check(
                    f"{route_id} synthetic completed packet passes",
                    route_results[route_id]["synthetic_passed"]
                    and synthetic_parsed.get("decision")
                    == "access_request_packet_preflight_passed"
                    and synthetic_parsed.get("allow_placeholders_used") is False
                    and synthetic_parsed.get("pre_submission_preflight_valid") is True
                    and synthetic_parsed.get("not_valid_for_submission") is False
                    and synthetic_parsed.get("content_not_recorded") is True
                    and synthetic_parsed.get("packet_identity_redacted") is True
                    and synthetic_parsed.get("packet_path_reported") is False
                    and synthetic_parsed.get("completed_packet_included") is False
                    and synthetic_parsed.get("protected_data_included") is False
                    and synthetic_parsed.get("credentials_or_tokens_included") is False
                    and synthetic_parsed.get("not_a_submission_record") is True
                    and synthetic_parsed.get("not_access_approval") is True
                    and synthetic_parsed.get("not_a_schema_probe_artifact") is True
                    and synthetic_parsed.get("not_a_model_result") is True
                    and synthetic_parsed.get("goal_complete") is False,
                    {
                        "decision": synthetic_parsed.get("decision"),
                        "hard_failures": synthetic_parsed.get("hard_failures"),
                        "returncode": synthetic_result["returncode"],
                    },
                ),
                check(
                    f"{route_id} unfinished template fails without allow-placeholders",
                    route_results[route_id]["template_failed"],
                    {
                        "decision": template_parsed.get("decision"),
                        "remaining_placeholders": route_results[route_id][
                            "template_remaining_placeholders"
                        ],
                        "returncode": template_result["returncode"],
                    },
                ),
                check(
                    f"{route_id} template passes only with explicit audit flag",
                    route_results[route_id]["template_allowed_passed"]
                    and template_allowed_parsed.get("decision")
                    == "placeholder_tolerant_access_packet_audit_passed"
                    and template_allowed_parsed.get("allow_placeholders_used") is True
                    and template_allowed_parsed.get("pre_submission_preflight_valid") is False
                    and template_allowed_parsed.get("not_valid_for_submission") is True,
                    {
                        "decision": template_allowed_parsed.get("decision"),
                        "allow_placeholders_used": template_allowed_parsed.get(
                            "allow_placeholders_used"
                        ),
                        "pre_submission_preflight_valid": template_allowed_parsed.get(
                            "pre_submission_preflight_valid"
                        ),
                        "not_valid_for_submission": template_allowed_parsed.get(
                            "not_valid_for_submission"
                        ),
                        "returncode": template_allowed_result["returncode"],
                    },
                ),
                check(
                    f"{route_id} output redacts packet path and filename",
                    route_results[route_id]["redaction_passed"],
                    {
                        "synthetic_output_contains_full_path": str(synthetic)
                        in synthetic_result["output_tail"],
                        "synthetic_output_contains_filename": synthetic.name
                        in synthetic_result["output_tail"],
                        "template_output_contains_full_path": str(source)
                        in template_result["output_tail"],
                        "template_output_contains_filename": source.name
                        in template_result["output_tail"],
                    },
                ),
            ]
        )

    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": Path(__file__).relative_to(ROOT).as_posix(),
        "validator": "scripts/validate_access_request_packet.py",
        "synthetic_dir": "results/access_request_packet_validator_synthetic",
        "passed": not hard_failures,
        "decision": (
            "access_request_packet_validator_ready"
            if not hard_failures
            else "access_request_packet_validator_failed"
        ),
        "checks": checks,
        "route_results": route_results,
        "hard_failures": hard_failures,
        "not_a_model_result": True,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "hard_failure_count": len(hard_failures),
                "route_count": len(route_results),
            },
            indent=2,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

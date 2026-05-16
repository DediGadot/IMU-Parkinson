#!/usr/bin/env python3
"""Audit generic all-route target-free manifest templates."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.datasets import external_schema_probe_specs
from pd_imu.experiments import SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SCRIPT = ROOT / "scripts" / "write_external_target_free_manifest_templates.py"
VALIDATOR = ROOT / "scripts" / "validate_target_free_manifest.py"
TEMPLATES_JSON = RESULTS / "external_target_free_manifest_templates_20260515.json"
TEMPLATES_MD = RESULTS / "external_target_free_manifest_templates_20260515.md"
TEMPLATE_DIR = RESULTS / "external_target_free_manifest_templates_20260515"
SYNTH_DIR = RESULTS / "external_target_free_manifest_templates_synthetic"
PPMI_TARGET_FREE_AUDIT = RESULTS / "ppmi_verily_target_free_manifest_validator_audit_20260515.json"
OUT_JSON = RESULTS / "external_target_free_manifest_templates_audit_20260515.json"
OUT_MD = RESULTS / "external_target_free_manifest_templates_audit_20260515.md"

EXPECTED_ROUTE_IDS = [
    "ppmi_verily",
    "ppp_pd_vme",
    "watchpd",
    "cns_portugal_lobo",
    "hssayeni_mjff",
    "icicle_gait",
]
EXPECTED_POST_SCHEMA_WORKFLOW_STEP_IDS = [
    "validate_target_free_manifest",
    "validate_formula_sha_record",
    "validate_zeroshot_result_record",
]
FALSE_BOUNDARY_KEYS = {
    "protected_data_included",
    "credentials_or_tokens_included",
    "raw_rows_or_samples_included",
    "feature_matrix_included",
    "target_values_included",
    "model_predictions_included",
    "local_paths_included",
}
FORBIDDEN_SNIPPETS = [
    ".access_",
    "_submission.json",
    "_approval.json",
    "_schema_probe.json",
    "LOCAL_COMPLETED",
    "password",
    "api_key",
    "private_key",
    "secret_key",
    "raw sample",
    "raw rows",
]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{rel(path)} must contain a JSON object")
    return payload


def run_writer() -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
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
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "parsed": parsed,
    }


def run_validator(route_id: str, manifest: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(VALIDATOR),
            "--route-id",
            route_id,
            "--manifest",
            str(manifest),
        ],
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
        "returncode": proc.returncode,
        "parsed": parsed,
        "output_tail": proc.stdout[-1200:],
    }


def forbidden_found(text: str) -> list[str]:
    lower = text.lower()
    return [snippet for snippet in FORBIDDEN_SNIPPETS if snippet.lower() in lower]


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def placeholder_count(obj: Any) -> int:
    text = json.dumps(obj, sort_keys=True)
    return len(re.findall(r"(\[[A-Z0-9_]+\]|<[^>\n]+>)", text))


def filled_manifest(template: dict[str, Any], route_id: str) -> dict[str, Any]:
    payload = deepcopy(template)
    payload.update(
        {
            "schema_probe_metadata_recorded": True,
            "schema_probe_artifact_reference": (
                f"synthetic_non_protected_{route_id}_schema_probe_record_hash"
            ),
            "script": f"scripts/extract_{route_id}_features_after_approval.py",
            "git_sha": "0" * 40,
            "command": (
                f"uv run python scripts/extract_{route_id}_features_after_approval.py "
                "--schema-record synthetic_non_protected_record"
            ),
            "created_at_utc": "2026-05-15T00:00:00+00:00",
            "data_version_or_download_date": "synthetic-no-protected-data",
            "data_sha256_or_file_manifest": "synthetic-aggregate-sha256-only",
        }
    )
    for block in payload.get("feature_blocks", []):
        if isinstance(block, dict):
            block["columns_or_schema_reference"] = "synthetic_schema_reference_without_values"
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def row_matches_spec(row: dict[str, Any], template: dict[str, Any], spec: Any) -> bool:
    feature_blocks = template.get("feature_blocks")
    feature_sources = [
        block.get("source_modality")
        for block in feature_blocks
        if isinstance(block, dict)
    ] if isinstance(feature_blocks, list) else []
    return (
        row.get("id") == spec.route_id
        and row.get("name") == spec.name
        and tuple(row.get("required_grouping_keys") or ()) == spec.required_grouping_keys
        and tuple(row.get("required_target_columns") or ()) == spec.required_target_columns
        and tuple(row.get("required_sensor_modalities") or ())
        == spec.required_sensor_modalities
        and row.get("min_subjects") == spec.min_subjects
        and template.get("route_id") == spec.route_id
        and tuple(template.get("grouping_keys") or ()) == spec.required_grouping_keys
        and tuple(template.get("target_columns_reserved_for_final_scoring") or ())
        == spec.required_target_columns
        and tuple(feature_sources) == spec.required_sensor_modalities
    )


def validator_command_valid(row: dict[str, Any]) -> bool:
    route_id = row.get("id")
    command = str(row.get("validator_command") or "")
    if route_id == "ppmi_verily":
        return (
            command
            == (
                "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                "--manifest <completed_target_free_manifest_path_outside_git>"
            )
            and "scripts/validate_target_free_manifest.py --route-id ppmi_verily"
            not in command
        )
    return (
        command
        == (
            "uv run python scripts/validate_target_free_manifest.py "
            f"--route-id {route_id} "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        )
    )


def expected_workflow_commands(route_id: str, validator_command: str) -> dict[str, str]:
    return {
        "validate_target_free_manifest": validator_command,
        "validate_formula_sha_record": (
            "uv run python scripts/validate_external_formula_sha_record.py "
            f"--route-id {route_id} "
            "--record <completed_formula_sha_record_path_outside_git>"
        ),
        "validate_zeroshot_result_record": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            f"--route-id {route_id} "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
    }


def post_schema_workflow_valid(row: dict[str, Any]) -> bool:
    route_id = str(row.get("id"))
    validator_command = str(row.get("validator_command") or "")
    commands = expected_workflow_commands(route_id, validator_command)
    return row.get("post_schema_workflow_sequence") == [
        {"step_id": step_id, "command": commands[step_id]}
        for step_id in EXPECTED_POST_SCHEMA_WORKFLOW_STEP_IDS
    ]


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# External Target-Free Manifest Templates Audit - 2026-05-15",
        "",
        "This audits the generic blank target-free manifest templates. It is not an approval, schema probe, completed manifest, preregistration, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Templates JSON: `{report['templates_json']}`",
        f"- Templates Markdown: `{report['templates_markdown']}`",
        f"- Template directory: `{report['template_dir']}`",
        f"- Route count: `{report['route_count']}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Route Results",
        "",
        "| Route | Placeholder template fails | Synthetic fill passes |",
        "|---|---:|---:|",
    ]
    for route_id, result in report["route_results"].items():
        lines.append(
            f"| `{route_id}` | `{result['placeholder_template_failed']}` | "
            f"`{result['synthetic_fill_passed']}` |"
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
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    writer = run_writer()
    templates_payload = load_json(TEMPLATES_JSON) if TEMPLATES_JSON.exists() else {}
    ppmi_target_free_audit = load_json(PPMI_TARGET_FREE_AUDIT)
    md_text = TEMPLATES_MD.read_text(encoding="utf-8") if TEMPLATES_MD.exists() else ""
    specs = external_schema_probe_specs()
    routes = templates_payload.get("routes") or []
    route_ids = [row.get("id") for row in routes]
    route_by_id = {row.get("id"): row for row in routes}
    boundary = templates_payload.get("content_boundary") or {}
    combined_text = (
        json.dumps(templates_payload, sort_keys=True)
        + "\n"
        + md_text
        + "\n"
        + writer["stdout"]
    )
    found_forbidden = forbidden_found(combined_text)
    route_results: dict[str, dict[str, Any]] = {}

    for spec in specs:
        row = route_by_id.get(spec.route_id, {})
        template_path = ROOT / str(row.get("template_path", ""))
        template = load_json(template_path) if template_path.exists() else {}
        template_result = run_validator(spec.route_id, template_path) if template_path.exists() else {}
        template_parsed = template_result.get("parsed") or {}
        filled_path = SYNTH_DIR / f"{spec.route_id}_filled_target_free_manifest.json"
        write_json(filled_path, filled_manifest(template, spec.route_id))
        filled_result = run_validator(spec.route_id, filled_path)
        filled_parsed = filled_result.get("parsed") or {}
        route_results[spec.route_id] = {
            "template_path": rel(template_path) if template_path.exists() else None,
            "placeholder_count": placeholder_count(template),
            "placeholder_template_failed": template_result.get("returncode") != 0
            and "placeholders_replaced" in template_parsed.get("hard_failures", []),
            "synthetic_fill_passed": filled_result.get("returncode") == 0
            and filled_parsed.get("passed") is True
            and filled_parsed.get("decision")
            == "target_free_feature_manifest_preflight_passed",
            "template_hard_failures": template_parsed.get("hard_failures"),
            "synthetic_fill_hard_failures": filled_parsed.get("hard_failures"),
            "redaction_passed": (
                str(template_path) not in str(template_result.get("output_tail", ""))
                and template_path.name not in str(template_result.get("output_tail", ""))
                and str(filled_path) not in str(filled_result.get("output_tail", ""))
                and filled_path.name not in str(filled_result.get("output_tail", ""))
            ),
        }

    checks = [
        check(
            "writer command succeeds and writes template outputs",
            writer["returncode"] == 0
            and (writer.get("parsed") or {}).get("json") == rel(TEMPLATES_JSON)
            and (writer.get("parsed") or {}).get("markdown") == rel(TEMPLATES_MD)
            and (writer.get("parsed") or {}).get("template_dir") == rel(TEMPLATE_DIR)
            and TEMPLATES_JSON.exists()
            and TEMPLATES_MD.exists()
            and TEMPLATE_DIR.exists(),
            {"returncode": writer["returncode"], "stdout": writer["stdout"][-800:]},
        ),
        check(
            "templates cover six schema-probe routes in contract order",
            templates_payload.get("decision")
            == "external_target_free_manifest_templates_ready"
            and templates_payload.get("route_count") == 6
            and route_ids == EXPECTED_ROUTE_IDS
            and route_ids == [spec.route_id for spec in specs]
            and templates_payload.get("goal_complete") is False,
            {"route_ids": route_ids, "spec_route_ids": [spec.route_id for spec in specs]},
        ),
        check(
            "template route rows mirror schema contracts",
            all(
                row_matches_spec(
                    route_by_id.get(spec.route_id, {}),
                    load_json(ROOT / str(route_by_id.get(spec.route_id, {}).get("template_path", ""))),
                    spec,
                )
                for spec in specs
            ),
            {
                "route_contracts": {
                    spec.route_id: route_results.get(spec.route_id, {})
                    for spec in specs
                }
            },
        ),
        check(
            "validator commands use PPMI-specific override and generic commands elsewhere",
            all(validator_command_valid(row) for row in routes),
            {
                "validator_commands": {
                    row.get("id"): row.get("validator_command") for row in routes
                }
            },
        ),
        check(
            "every route exposes an ordered post-schema workflow sequence",
            all(post_schema_workflow_valid(row) for row in routes)
            and "Post-schema workflow sequence:" in md_text
            and "1. `validate_target_free_manifest`" in md_text
            and "2. `validate_formula_sha_record`" in md_text
            and "3. `validate_zeroshot_result_record`" in md_text,
            {
                "expected_step_ids": EXPECTED_POST_SCHEMA_WORKFLOW_STEP_IDS,
                "workflow_by_route": {
                    row.get("id"): [
                        step.get("step_id")
                        for step in row.get("post_schema_workflow_sequence", [])
                    ]
                    for row in routes
                },
                "ppmi_workflow": route_by_id.get("ppmi_verily", {}).get(
                    "post_schema_workflow_sequence"
                ),
            },
        ),
        check(
            "markdown PPMI route uses PPMI-specific target-free manifest validator",
            "Validator: `uv run python scripts/validate_ppmi_verily_target_free_manifest.py --manifest <completed_target_free_manifest_path_outside_git>`"
            in md_text
            and "scripts/validate_target_free_manifest.py --route-id ppmi_verily"
            not in md_text,
            {"ppmi_markdown": md_text.split("### Personalized", 1)[0][-1200:]},
        ),
        check(
            "all templates are unfinished placeholders and synthetic fills pass",
            all(
                result["placeholder_count"] > 0
                and result["placeholder_template_failed"]
                and result["synthetic_fill_passed"]
                and result["redaction_passed"]
                for result in route_results.values()
            ),
            {"route_results": route_results},
        ),
        check(
            "template boundary flags are false and target-free",
            all(
                route_by_id.get(spec.route_id, {}).get("template", {}).get("labels_used")
                is False
                and route_by_id.get(spec.route_id, {}).get("template", {}).get(
                    "target_columns_used_for_feature_selection"
                )
                == []
                and all(
                    route_by_id.get(spec.route_id, {}).get("template", {}).get(key)
                    is False
                    for key in FALSE_BOUNDARY_KEYS
                )
                and route_by_id.get(spec.route_id, {}).get("template", {}).get(
                    "leakage_status"
                )
                == "target_free_pre_scoring"
                for spec in specs
            ),
            {
                "false_boundary_keys": sorted(FALSE_BOUNDARY_KEYS),
                "route_ids": route_ids,
            },
        ),
        check(
            "blocked actions remain explicit until manifest preflight passes",
            all(
                tuple(row.get("blocked_until_manifest_preflight_passes") or ())
                == SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS
                and "model run" in (row.get("blocked_until_manifest_preflight_passes") or [])
                and "canonical T1/T3 claim update"
                in (row.get("blocked_until_manifest_preflight_passes") or [])
                for row in routes
            ),
            {"blocked_until_manifest_preflight": list(SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS)},
        ),
        check(
            "PPMI existing target-free manifest template remains wired and audited",
            templates_payload.get("ppmi_specific_support", {}).get("existing_ppmi_template")
            == "scripts/ppmi_verily_target_free_manifest_template.json"
            and templates_payload.get("ppmi_specific_support", {}).get("existing_ppmi_validator")
            == "scripts/validate_ppmi_verily_target_free_manifest.py"
            and templates_payload.get("ppmi_specific_support", {}).get(
                "existing_ppmi_validator_command"
            )
            == (
                "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                "--manifest <completed_target_free_manifest_path_outside_git>"
            )
            and templates_payload.get("ppmi_specific_support", {}).get(
                "existing_ppmi_template_audit"
            )
            == "results/ppmi_verily_target_free_manifest_validator_audit_20260515.json"
            and ppmi_target_free_audit.get("passed") is True
            and ppmi_target_free_audit.get("decision")
            == "ppmi_verily_target_free_manifest_validator_ready"
            and ppmi_target_free_audit.get("not_a_feature_manifest_artifact") is True
            and ppmi_target_free_audit.get("protected_data_included") is False,
            {
                "ppmi_specific_support": templates_payload.get("ppmi_specific_support"),
                "ppmi_target_free_decision": ppmi_target_free_audit.get("decision"),
            },
        ),
        check(
            "content boundary blocks completed/protected artifacts",
            templates_payload.get("not_a_submission_record") is True
            and templates_payload.get("not_access_approval") is True
            and templates_payload.get("not_a_schema_probe_artifact") is True
            and templates_payload.get("not_a_feature_manifest_artifact") is True
            and templates_payload.get("not_a_preregistration") is True
            and templates_payload.get("not_a_model_result") is True
            and boundary.get("completed_manifest_included") is False
            and boundary.get("protected_data_included") is False
            and boundary.get("approval_evidence_included") is False
            and boundary.get("schema_probe_artifacts_included") is False
            and boundary.get("feature_manifest_artifacts_included") is False
            and boundary.get("credentials_or_tokens_included") is False
            and boundary.get("target_values_included") is False
            and boundary.get("row_level_data_included") is False
            and boundary.get("feature_matrix_included") is False
            and boundary.get("model_outputs_included") is False
            and boundary.get("local_paths_included") is False
            and boundary.get("path_like_values_allowed") is False
            and boundary.get("completed_file_references_in_values_allowed") is False
            and boundary.get("subject_visit_identifier_value_dumps_allowed") is False,
            {"content_boundary": boundary},
        ),
        check(
            "markdown boundary documents stricter value-scrubbing policy",
            "path-like values inside otherwise allowed fields" in md_text
            and "completed-file extensions" in md_text
            and "download/file-path strings" in md_text
            and "subject/visit identifier value dumps" in md_text
            and "Validators fail closed" in md_text,
            {"boundary_excerpt": md_text.split("## Boundary", 1)[-1][:1200]},
        ),
        check(
            "template output does not expose private artifacts",
            not found_forbidden,
            {"forbidden_snippets_found": found_forbidden},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_target_free_manifest_templates.py",
        "writer": "scripts/write_external_target_free_manifest_templates.py",
        "templates_json": rel(TEMPLATES_JSON),
        "templates_markdown": rel(TEMPLATES_MD),
        "template_dir": rel(TEMPLATE_DIR),
        "source_schema_contract": "pd_imu.datasets.external_schema_probe_specs",
        "passed": not hard_failures,
        "decision": (
            "external_target_free_manifest_templates_ready"
            if not hard_failures
            else "external_target_free_manifest_templates_failed"
        ),
        "route_count": len(routes),
        "route_ids": route_ids,
        "route_results": route_results,
        "post_schema_workflow_step_ids_by_route": {
            row.get("id"): [
                step.get("step_id")
                for step in row.get("post_schema_workflow_sequence", [])
            ]
            for row in routes
        },
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_feature_manifest_artifact": True,
        "not_a_preregistration": True,
        "not_a_model_result": True,
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
                "route_count": report["route_count"],
            },
            indent=2,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

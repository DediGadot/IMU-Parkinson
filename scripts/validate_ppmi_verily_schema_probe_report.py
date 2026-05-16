#!/usr/bin/env python3
"""Validate a locally completed PPMI / Verily schema-probe report.

This is a post-approval preflight for a local scratch report. It reads a
key-value report, checks that only schema/aggregate facts are present, and
prints a content-free JSON summary. It does not record protected rows, target
values, local paths, credentials, approval identities, or model evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pd_imu.datasets import SchemaProbeReport, schema_probe_spec_for_route
from pd_imu.datasets.probe import SCHEMA_PROBE_PROHIBITED_PAYLOAD_KEYS


PLACEHOLDER_RE = re.compile(r"(\[[A-Z0-9_]+\]|<[^>\n]+>)")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ALLOWED_SUFFIXES = {".md", ".txt"}
ALLOWED_KEYS = {
    "sections_present",
    "grouping_keys_found",
    "target_columns_found",
    "sensor_modalities_found",
    "valid_subject_count",
    "ppmi_x4_multinode_anatomical_sensors_present",
    "ppmi_x4_v3_gsp_formula_eligible",
    "ppmi_x4_external_label_selection_allowed",
    "hard_stops",
}
REQUIRED_KEYS = {
    "sections_present",
    "grouping_keys_found",
    "target_columns_found",
    "sensor_modalities_found",
    "valid_subject_count",
    "ppmi_x4_multinode_anatomical_sensors_present",
    "ppmi_x4_v3_gsp_formula_eligible",
    "ppmi_x4_external_label_selection_allowed",
}
FORBIDDEN_TEXT_SNIPPETS = (
    ".access_",
    ".schema_probes/",
    "~/",
    "/home/",
    "\\users\\",
    "approval.json",
    ".docx",
    ".pdf",
    ".csv",
    ".json",
    ".zip",
    "download_path=",
    "file_path=",
    "local_approval_path",
    "local approval path",
    "access_token",
    "api_key",
    "private_key",
    "secret_key",
    "synapse_auth_token",
    "password=",
    "raw_rows=",
    "raw_samples=",
    "target_values=",
    "label_values=",
    "feature_matrix=",
    "participant_ids=",
    "sid_values=",
    "subject_ids=",
    "time_series=",
    "visit_values=",
)


def normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def parse_csv(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def parse_bool_field(fields: dict[str, str], key: str) -> tuple[bool | None, str | None]:
    value = fields.get(key)
    if value is None:
        return None, None
    normalized = value.strip().lower()
    if normalized == "true":
        return True, None
    if normalized == "false":
        return False, None
    return None, f"{key} must be true or false"


def parse_report_text(text: str) -> dict[str, Any]:
    fields: dict[str, str] = {}
    duplicate_keys: list[str] = []
    unknown_keys: list[str] = []
    prohibited_keys: list[str] = []
    narrative_line_count = 0
    forbidden_keys = set(SCHEMA_PROBE_PROHIBITED_PAYLOAD_KEYS)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            narrative_line_count += 1
            continue
        key, value = line.split("=", 1)
        key = normalize_key(key)
        if not KEY_RE.match(key):
            unknown_keys.append(key)
            continue
        if key in forbidden_keys:
            prohibited_keys.append(key)
            continue
        if key not in ALLOWED_KEYS:
            unknown_keys.append(key)
            continue
        if key in fields:
            duplicate_keys.append(key)
        fields[key] = value.strip()

    return {
        "fields": fields,
        "duplicate_keys": sorted(set(duplicate_keys)),
        "unknown_keys": sorted(set(unknown_keys)),
        "prohibited_keys": sorted(set(prohibited_keys)),
        "narrative_line_count": narrative_line_count,
    }


def validate_report(path: Path, *, route_id: str = "ppmi_verily") -> dict[str, Any]:
    if not path.exists():
        raise ValueError("schema-probe report path does not exist")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported schema-probe report extension {path.suffix!r}")

    text = path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_report_text(text)
    fields: dict[str, str] = parsed["fields"]
    placeholders = sorted(set(match.group(0) for match in PLACEHOLDER_RE.finditer(text)))
    missing_keys = sorted(REQUIRED_KEYS - set(fields))
    forbidden_terms_found = [
        snippet for snippet in FORBIDDEN_TEXT_SNIPPETS if snippet.lower() in text.lower()
    ]

    subject_count: int | None = None
    subject_count_error: str | None = None
    if "valid_subject_count" in fields:
        try:
            subject_count = int(fields["valid_subject_count"])
        except ValueError:
            subject_count_error = "valid_subject_count must be an integer"

    x4_multinode_present, x4_multinode_error = parse_bool_field(
        fields, "ppmi_x4_multinode_anatomical_sensors_present"
    )
    x4_formula_eligible, x4_eligible_error = parse_bool_field(
        fields, "ppmi_x4_v3_gsp_formula_eligible"
    )
    x4_external_labels_allowed, x4_external_labels_error = parse_bool_field(
        fields, "ppmi_x4_external_label_selection_allowed"
    )
    x4_policy_errors = [
        error
        for error in (
            x4_multinode_error,
            x4_eligible_error,
            x4_external_labels_error,
        )
        if error
    ]
    if x4_external_labels_allowed is not None and x4_external_labels_allowed:
        x4_policy_errors.append(
            "ppmi_x4_external_label_selection_allowed must remain false"
        )
    if x4_formula_eligible and not x4_multinode_present:
        x4_policy_errors.append(
            "ppmi_x4_v3_gsp_formula_eligible requires "
            "ppmi_x4_multinode_anatomical_sensors_present=true"
        )
    if x4_formula_eligible and "weargait_compatible_13node_imu" not in parse_csv(
        fields.get("sensor_modalities_found")
    ):
        x4_policy_errors.append(
            "ppmi_x4_v3_gsp_formula_eligible requires "
            "sensor_modalities_found to include weargait_compatible_13node_imu"
        )

    spec = schema_probe_spec_for_route(route_id)
    report_errors: list[str]
    if subject_count is None:
        report_errors = [subject_count_error or "valid_subject_count is required"]
    else:
        report = SchemaProbeReport(
            spec=spec,
            approved_access=True,
            sections_present=parse_csv(fields.get("sections_present")),
            grouping_keys_found=parse_csv(fields.get("grouping_keys_found")),
            target_columns_found=parse_csv(fields.get("target_columns_found")),
            sensor_modalities_found=parse_csv(fields.get("sensor_modalities_found")),
            valid_subject_count=subject_count,
            protected_row_dump_included=False,
            preregistration_written=False,
            model_run_started=False,
            artifact_path=f".schema_probes/{route_id}_schema_probe.json",
        )
        report_errors = report.validation_errors()

    checks = {
        "path_exists": {"passed": True, "suffix": path.suffix.lower()},
        "placeholders_replaced": {
            "passed": not placeholders,
            "remaining_placeholder_count": len(placeholders),
        },
        "required_keys_present": {
            "passed": not missing_keys,
            "missing_keys": missing_keys,
        },
        "only_allowed_key_value_fields": {
            "passed": not parsed["unknown_keys"]
            and not parsed["duplicate_keys"]
            and parsed["narrative_line_count"] == 0,
            "unknown_keys": parsed["unknown_keys"],
            "duplicate_keys": parsed["duplicate_keys"],
            "narrative_line_count": parsed["narrative_line_count"],
        },
        "protected_payload_keys_absent": {
            "passed": not parsed["prohibited_keys"],
            "prohibited_keys": parsed["prohibited_keys"],
        },
        "forbidden_text_absent": {
            "passed": not forbidden_terms_found,
            "forbidden_terms_found": forbidden_terms_found,
        },
        "schema_probe_contract_valid": {
            "passed": not report_errors,
            "validation_error_count": len(report_errors),
            "validation_errors": report_errors,
        },
        "ppmi_x4_v3_gsp_policy_declared": {
            "passed": not x4_policy_errors,
            "validation_error_count": len(x4_policy_errors),
            "validation_errors": x4_policy_errors,
            "multinode_anatomical_sensors_present": x4_multinode_present,
            "v3_gsp_formula_eligible": x4_formula_eligible,
            "external_label_selection_allowed": x4_external_labels_allowed,
        },
    }
    hard_failures = [name for name, row in checks.items() if not row.get("passed")]
    return {
        "validated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "route_id": route_id,
        "report_identity_redacted": True,
        "report_path_reported": False,
        "report_suffix": path.suffix.lower(),
        "report_size_bytes": path.stat().st_size,
        "field_counts": {
            "sections_present": len(parse_csv(fields.get("sections_present"))),
            "grouping_keys_found": len(parse_csv(fields.get("grouping_keys_found"))),
            "target_columns_found": len(parse_csv(fields.get("target_columns_found"))),
            "sensor_modalities_found": len(parse_csv(fields.get("sensor_modalities_found"))),
        },
        "ppmi_x4_v3_gsp_policy": {
            "requires_sensor_layout": "WearGait-compatible 13-node anatomical IMU graph",
            "multinode_anatomical_sensors_present": x4_multinode_present,
            "v3_gsp_formula_eligible": x4_formula_eligible,
            "external_label_selection_allowed": x4_external_labels_allowed,
        },
        "passed": not hard_failures,
        "decision": (
            "completed_schema_probe_report_preflight_passed"
            if not hard_failures
            else "completed_schema_probe_report_preflight_failed"
        ),
        "checks": checks,
        "hard_failures": hard_failures,
        "content_not_recorded": True,
        "not_a_schema_probe_artifact": True,
        "not_access_approval": True,
        "not_a_model_result": True,
        "goal_complete": False,
        "next_action": (
            "If this is a real approved schema-probe report, record only scrubbed "
            "metadata with scripts/record_schema_probe_report.py."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="Path to a completed local .md or .txt report")
    parser.add_argument("--route-id", default="ppmi_verily")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = validate_report(Path(args.report), route_id=args.route_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

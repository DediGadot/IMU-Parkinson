#!/usr/bin/env python3
"""Verify the local schema-probe recorder stays scrubbed and post-approval only."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.datasets import SchemaProbeArtifactEvidence, SchemaProbeReport, schema_probe_spec_for_route
from pd_imu.experiments import SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SCRIPT = ROOT / "scripts" / "record_schema_probe_report.py"
APPROVAL_SCRIPT = ROOT / "scripts" / "record_access_approval.py"
TMP_APPROVAL = ROOT / ".access_approvals" / "schema_probe_recorder_audit_approval.json"
SYNTHETIC_APPROVAL = ROOT / ".access_approvals" / "schema_probe_recorder_synthetic_approval.json"
MISSING_APPROVAL = ROOT / ".access_approvals" / "schema_probe_recorder_missing_approval.json"
BAD_APPROVAL = ROOT / ".access_approvals" / "schema_probe_recorder_bad_approval.json"
OUT_JSON = RESULTS / "schema_probe_recorder_audit_20260510.json"
OUT_MD = RESULTS / "schema_probe_recorder_audit_20260510.md"


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def parse_record(stdout: str) -> dict[str, Any]:
    return json.loads(stdout)


def report_from_record(record: dict[str, Any]) -> SchemaProbeReport:
    spec_payload = record.get("spec", {})
    spec = schema_probe_spec_for_route(str(spec_payload.get("route_id", "")))
    return SchemaProbeReport(
        spec=spec,
        approved_access=bool(record.get("approved_access")),
        sections_present=tuple(record.get("sections_present", ())),
        grouping_keys_found=tuple(record.get("grouping_keys_found", ())),
        target_columns_found=tuple(record.get("target_columns_found", ())),
        sensor_modalities_found=tuple(record.get("sensor_modalities_found", ())),
        valid_subject_count=record.get("valid_subject_count"),
        protected_row_dump_included=bool(record.get("protected_row_dump_included")),
        preregistration_written=bool(record.get("preregistration_written")),
        model_run_started=bool(record.get("model_run_started")),
        artifact_path=record.get("artifact_path"),
    )


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    dry_run_args = [
        "uv",
        "run",
        "python",
        str(SCRIPT.relative_to(ROOT)),
        "--route-id",
        "ppmi_verily",
        "--sections-present",
        "file_inventory,subject_linkage,visit_or_session_linkage,sensor_metadata,target_metadata,missingness_policy,grouping_policy,hard_stops",
        "--grouping-keys-found",
        "sid,visit_id",
        "--target-columns-found",
        "updrs3,hy",
        "--sensor-modalities-found",
        "wrist_accelerometer",
        "--valid-subject-count",
        "120",
        "--ppmi-x4-multinode-anatomical-sensors-present",
        "false",
        "--ppmi-x4-v3-gsp-formula-eligible",
        "false",
        "--ppmi-x4-external-label-selection-allowed",
        "false",
        "--dry-run",
        "--allow-synthetic-approval",
    ]
    dry_run = run_cmd(dry_run_args)
    record = parse_record(dry_run.stdout) if dry_run.returncode == 0 else {}
    report = report_from_record(record) if record else None
    evidence_errors = (
        SchemaProbeArtifactEvidence(path=record.get("artifact_path", ""), payload=record).validation_errors_for(report)
        if record and report is not None
        else ["dry-run failed"]
    )

    prereg_attempt = run_cmd([*dry_run_args[:-2], "--dry-run", "--allow-synthetic-approval", "--preregistration-written"])
    protected_rows_attempt = run_cmd(
        [*dry_run_args[:-2], "--dry-run", "--allow-synthetic-approval", "--protected-row-dump-included"]
    )
    low_n_args = list(dry_run_args)
    low_n_args[low_n_args.index("--valid-subject-count") + 1] = "19"
    low_n_attempt = run_cmd(low_n_args)
    placeholder_field_attempt = run_cmd(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT.relative_to(ROOT)),
            "--route-id",
            "ppmi_verily",
            "--sections-present",
            "file_inventory,subject_linkage,visit_or_session_linkage,sensor_metadata,target_metadata,missingness_policy,grouping_policy,hard_stops",
            "--grouping-keys-found",
            "sid,visit_id,<additional_non_protected_grouping_keys_if_needed>",
            "--target-columns-found",
            "updrs3",
            "--sensor-modalities-found",
            "wrist_accelerometer",
            "--valid-subject-count",
            "120",
            "--ppmi-x4-multinode-anatomical-sensors-present",
            "false",
            "--ppmi-x4-v3-gsp-formula-eligible",
            "false",
            "--ppmi-x4-external-label-selection-allowed",
            "false",
            "--dry-run",
            "--allow-synthetic-approval",
        ]
    )
    missing_approval_attempt = run_cmd(
        [
            *dry_run_args[:-2],
            "--approval-record",
            str(MISSING_APPROVAL.relative_to(ROOT)),
            "--dry-run",
        ]
    )
    BAD_APPROVAL.parent.mkdir(parents=True, exist_ok=True)
    BAD_APPROVAL.write_text("{not-json", encoding="utf-8")
    bad_approval_attempt = run_cmd(
        [
            *dry_run_args[:-2],
            "--approval-record",
            str(BAD_APPROVAL.relative_to(ROOT)),
            "--dry-run",
        ]
    )
    BAD_APPROVAL.unlink(missing_ok=True)

    TMP_APPROVAL.parent.mkdir(parents=True, exist_ok=True)
    SYNTHETIC_APPROVAL.write_text(
        json.dumps(
            {
                "approval_evidence": {
                    "approved_access": True,
                    "approved_at_utc": "2026-05-10T00:00:00Z",
                    "credentials_or_tokens_included": False,
                    "data_use_terms_accepted": True,
                    "notes": "Synthetic evidence fixture for schema-probe recorder audit.",
                    "protected_row_dump_included": False,
                    "route_id": "ppmi_verily",
                    "source": "synthetic approval metadata for schema-probe recorder audit",
                    "storage_plan_documented": True,
                }
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    synthetic_approval_attempt = run_cmd(
        [
            *dry_run_args[:-2],
            "--approval-record",
            str(SYNTHETIC_APPROVAL.relative_to(ROOT)),
            "--dry-run",
        ]
    )
    SYNTHETIC_APPROVAL.unlink(missing_ok=True)

    approval_record = run_cmd(
        [
            "uv",
            "run",
            "python",
            str(APPROVAL_SCRIPT.relative_to(ROOT)),
            "--route-id",
            "ppmi_verily",
            "--approved-at-utc",
            "2026-05-10T00:00:00Z",
            "--source",
            "non-protected data-owner approval notice metadata",
            "--out",
            str(TMP_APPROVAL.relative_to(ROOT)),
        ]
    )
    outside_write = run_cmd(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT.relative_to(ROOT)),
            "--route-id",
            "ppmi_verily",
            "--sections-present",
            "file_inventory,subject_linkage,visit_or_session_linkage,sensor_metadata,target_metadata,missingness_policy,grouping_policy,hard_stops",
            "--grouping-keys-found",
            "sid,visit_id",
            "--target-columns-found",
            "updrs3",
            "--sensor-modalities-found",
            "wrist_accelerometer",
            "--valid-subject-count",
            "120",
            "--ppmi-x4-multinode-anatomical-sensors-present",
            "false",
            "--ppmi-x4-v3-gsp-formula-eligible",
            "false",
            "--ppmi-x4-external-label-selection-allowed",
            "false",
            "--approval-record",
            str(TMP_APPROVAL.relative_to(ROOT)),
            "--out",
            "results/unsafe_schema_probe_record.json",
        ]
    )
    TMP_APPROVAL.unlink(missing_ok=True)

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    next_action = record.get("next_action_before_recording", {})
    unsafe_path = ROOT / "results" / "unsafe_schema_probe_record.json"
    checks = [
        check(
            "recorder dry-run emits valid PPMI schema-probe artifact payload",
            dry_run.returncode == 0
            and record.get("spec", {}).get("route_id") == "ppmi_verily"
            and record.get("artifact_path") == ".schema_probes/ppmi_verily_schema_probe.json"
            and report is not None
            and report.validation_errors() == []
            and evidence_errors == []
            and report.can_preregister(),
            {
                "returncode": dry_run.returncode,
                "report_errors": report.validation_errors() if report is not None else ["no report"],
                "evidence_errors": evidence_errors,
            },
        ),
        check(
            "PPMI X4 V3-GSP eligibility policy is recorded as schema metadata",
            record.get("ppmi_x4_v3_gsp_policy", {}).get(
                "requires_sensor_layout"
            )
            == "WearGait-compatible 13-node anatomical IMU graph"
            and record.get("ppmi_x4_v3_gsp_policy", {}).get(
                "multinode_anatomical_sensors_present"
            )
            is False
            and record.get("ppmi_x4_v3_gsp_policy", {}).get(
                "v3_gsp_formula_eligible"
            )
            is False
            and record.get("ppmi_x4_v3_gsp_policy", {}).get(
                "external_label_selection_allowed"
            )
            is False,
            {"ppmi_x4_v3_gsp_policy": record.get("ppmi_x4_v3_gsp_policy")},
        ),
        check(
            "schema-probe artifact remains metadata-only",
            record.get("schema_probe_metadata_only") is True
            and record.get("protected_data_included") is False
            and record.get("credentials_or_tokens_included") is False
            and record.get("protected_row_dump_included") is False
            and record.get("preregistration_written") is False
            and record.get("model_run_started") is False
            and record.get("canonical_update_allowed") is False,
            {
                "schema_probe_metadata_only": record.get("schema_probe_metadata_only"),
                "protected_data_included": record.get("protected_data_included"),
                "credentials_or_tokens_included": record.get("credentials_or_tokens_included"),
                "protected_row_dump_included": record.get("protected_row_dump_included"),
                "preregistration_written": record.get("preregistration_written"),
                "model_run_started": record.get("model_run_started"),
                "canonical_update_allowed": record.get("canonical_update_allowed"),
            },
        ),
        check(
            "approval record identity is redacted in schema-probe artifact and errors",
            "approval_record_path" not in record
            and record.get("approval_record_identity_redacted") is True
            and record.get("approval_record_path_reported") is False
            and str(MISSING_APPROVAL) not in missing_approval_attempt.stdout
            and MISSING_APPROVAL.name not in missing_approval_attempt.stdout
            and str(BAD_APPROVAL) not in bad_approval_attempt.stdout
            and BAD_APPROVAL.name not in bad_approval_attempt.stdout,
            {
                "approval_record_identity_redacted": record.get("approval_record_identity_redacted"),
                "approval_record_path_reported": record.get("approval_record_path_reported"),
                "approval_record_path_present": "approval_record_path" in record,
                "missing_error_path_echoed": str(MISSING_APPROVAL) in missing_approval_attempt.stdout,
                "missing_error_filename_echoed": MISSING_APPROVAL.name in missing_approval_attempt.stdout,
                "bad_error_path_echoed": str(BAD_APPROVAL) in bad_approval_attempt.stdout,
                "bad_error_filename_echoed": BAD_APPROVAL.name in bad_approval_attempt.stdout,
            },
        ),
        check(
            "approval lifecycle is schema-probe-only before recording",
            tuple(next_action.get("blocked_actions_now", ())) == SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS
            and next_action.get("action") == "run_read_only_schema_probe"
            and next_action.get("safe_to_execute_code") is True,
            {"next_action": next_action},
        ),
        check(
            "recorder rejects preregistration, protected rows, and low-N probes",
            prereg_attempt.returncode != 0
            and "schema probe must not write preregistration" in prereg_attempt.stdout
            and protected_rows_attempt.returncode != 0
            and "probe artifact includes protected row dump" in protected_rows_attempt.stdout
            and low_n_attempt.returncode != 0
            and "valid_subject_count is below minimum 20" in low_n_attempt.stdout,
            {
                "prereg_tail": prereg_attempt.stdout[-800:],
                "protected_rows_tail": protected_rows_attempt.stdout[-800:],
                "low_n_tail": low_n_attempt.stdout[-800:],
            },
        ),
        check(
            "recorder refuses unfilled schema-probe command-template placeholders",
            placeholder_field_attempt.returncode != 0
            and "contains an unfilled placeholder" in placeholder_field_attempt.stdout
            and "Traceback" not in placeholder_field_attempt.stdout,
            {
                "returncode": placeholder_field_attempt.returncode,
                "output_tail": placeholder_field_attempt.stdout[-800:],
            },
        ),
        check(
            "real recording requires an approval record",
            missing_approval_attempt.returncode != 0 and "approval record not found" in missing_approval_attempt.stdout,
            {"returncode": missing_approval_attempt.returncode, "output_tail": missing_approval_attempt.stdout[-800:]},
        ),
        check(
            "recorder input JSON loader errors fail closed",
            bad_approval_attempt.returncode != 0
            and "approval record source is not valid JSON" in bad_approval_attempt.stdout
            and "Traceback" not in bad_approval_attempt.stdout,
            {"returncode": bad_approval_attempt.returncode, "output_tail": bad_approval_attempt.stdout[-800:]},
        ),
        check(
            "synthetic approval record cannot unlock schema-probe recording",
            SYNTHETIC_APPROVAL.exists() is False
            and synthetic_approval_attempt.returncode != 0
            and "approval record appears to be synthetic or audit-only metadata" in synthetic_approval_attempt.stdout
            and str(SYNTHETIC_APPROVAL) not in synthetic_approval_attempt.stdout
            and SYNTHETIC_APPROVAL.name not in synthetic_approval_attempt.stdout
            and "Traceback" not in synthetic_approval_attempt.stdout,
            {
                "synthetic_fixture_removed": SYNTHETIC_APPROVAL.exists() is False,
                "attempt_returncode": synthetic_approval_attempt.returncode,
                "output_tail": synthetic_approval_attempt.stdout[-800:],
                "synthetic_error_path_echoed": str(SYNTHETIC_APPROVAL) in synthetic_approval_attempt.stdout,
                "synthetic_error_filename_echoed": SYNTHETIC_APPROVAL.name in synthetic_approval_attempt.stdout,
            },
        ),
        check(
            "default schema-probe output directory is gitignored",
            ".schema_probes/" in gitignore,
            {"gitignore": ".gitignore"},
        ),
        check(
            "recorder refuses non-ignored output path by default",
            approval_record.returncode == 0
            and outside_write.returncode != 0
            and "refusing to write schema-probe evidence outside .schema_probes/" in outside_write.stdout
            and not unsafe_path.exists(),
            {
                "approval_returncode": approval_record.returncode,
                "outside_returncode": outside_write.returncode,
                "outside_tail": outside_write.stdout[-1000:],
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report_payload = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_schema_probe_recorder.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "schema_probe_recorder_passed" if not hard_failures else "schema_probe_recorder_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": (
            "A post-approval schema-probe report can now be recorded as a scrubbed "
            "SchemaProbeArtifactEvidence payload in .schema_probes/. The recorder requires "
            "approval evidence for real writes, rejects row dumps, preregistration, model "
            "starts, low-N probes, and non-ignored output paths, and does not change any "
            "T1/T3 result. Malformed approval/tracker input JSON fails closed without a traceback, "
            "approval-record local identity is redacted from emitted payloads and errors, "
            "synthetic audit-only approval records cannot unlock schema-probe recording, "
            "and unfilled schema-probe command-template placeholders are rejected."
        ),
    }
    OUT_JSON.write_text(json.dumps(report_payload, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Schema Probe Recorder Audit - 2026-05-10",
        "",
        "This verifies the local schema-probe recorder. It is not a model result and contains no protected data.",
        "",
        f"- Passed: `{report_payload['passed']}`",
        f"- Decision: `{report_payload['decision']}`",
        f"- Hard failures: `{len(hard_failures)}`",
        "",
        "## Checks",
        "",
    ]
    for row in checks:
        lines.append(f"- `{row['passed']}` {row['name']}")
    lines.extend(
        [
            "",
            "## Claim",
            "",
            report_payload["claim"],
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(
        json.dumps(
            {
                "passed": report_payload["passed"],
                "decision": report_payload["decision"],
                "hard_failures": len(hard_failures),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

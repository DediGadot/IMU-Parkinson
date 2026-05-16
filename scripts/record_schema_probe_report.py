#!/usr/bin/env python3
"""Record scrubbed read-only external schema-probe metadata.

This script is for the first code action after data-owner approval. It records a
typed schema inventory only. It does not connect to protected data, store row
dumps, write preregistrations, start model runs, or update canonical claims.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pd_imu.datasets import (  # noqa: E402
    SchemaProbeArtifactEvidence,
    SchemaProbeReport,
    schema_probe_spec_for_route,
)
from pd_imu.experiments import (  # noqa: E402
    SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS,
    AccessApprovalEvidence,
    AccessPacketSpec,
    AccessRouteLifecycle,
)


DEFAULT_TRACKER = ROOT / "results" / "access_submission_tracker_20260509.json"
DEFAULT_APPROVAL_DIR = ROOT / ".access_approvals"
DEFAULT_OUTPUT_DIR = ROOT / ".schema_probes"


def load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} source is missing") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} source is not valid JSON") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} source is not valid UTF-8 JSON") from exc
    except OSError as exc:
        raise ValueError(f"{label} source could not be read") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} source must contain a JSON object")
    return payload


def looks_like_synthetic_approval(approval: AccessApprovalEvidence) -> bool:
    text = " ".join(
        value
        for value in (approval.source, approval.notes)
        if isinstance(value, str)
    ).lower()
    return any(
        marker in text
        for marker in (
            "synthetic",
            "dry-run",
            "dry run",
            "audit-only",
            "audit only",
            "for recorder audit",
            "test approval",
        )
    )


def packet_for_route(tracker: dict[str, Any], route_id: str) -> AccessPacketSpec:
    for row in tracker.get("routes", []):
        if str(row.get("id")) == route_id:
            return AccessPacketSpec.from_tracker_row(row)
    raise ValueError(f"route_id {route_id!r} not found in tracker")


def approval_from_record(path: Path, route_id: str) -> AccessApprovalEvidence:
    if not path.exists():
        raise ValueError("approval record not found")
    payload = load_json(path, label="approval record")
    evidence = payload.get("approval_evidence")
    if not isinstance(evidence, dict):
        raise ValueError("approval record has no approval_evidence object")
    approval = AccessApprovalEvidence(**evidence)
    if approval.route_id != route_id:
        raise ValueError(f"approval record route_id {approval.route_id!r} != {route_id!r}")
    if looks_like_synthetic_approval(approval):
        raise ValueError("approval record appears to be synthetic or audit-only metadata")
    return approval


def synthetic_approval(route_id: str) -> AccessApprovalEvidence:
    return AccessApprovalEvidence(
        route_id=route_id,
        source="synthetic dry-run approval for recorder audit only",
        approved_at_utc="2026-05-10T00:00:00Z",
        approved_access=True,
        data_use_terms_accepted=True,
        storage_plan_documented=True,
        notes="Synthetic evidence is accepted only with --allow-synthetic-approval.",
    )


def default_approval_path(route_id: str) -> Path:
    return DEFAULT_APPROVAL_DIR / f"{route_id}_approval.json"


def default_output_path(route_id: str) -> Path:
    return DEFAULT_OUTPUT_DIR / f"{route_id}_schema_probe.json"


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def parse_csv(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def parse_bool_token(value: str | None, *, field: str) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"{field} must be true or false")


def build_record(
    *,
    packet: AccessPacketSpec,
    approval: AccessApprovalEvidence,
    approval_record_path: Path | None,
    output_path: Path,
    sections_present: tuple[str, ...],
    grouping_keys_found: tuple[str, ...],
    target_columns_found: tuple[str, ...],
    sensor_modalities_found: tuple[str, ...],
    valid_subject_count: int,
    ppmi_x4_multinode_anatomical_sensors_present: bool | None,
    ppmi_x4_v3_gsp_formula_eligible: bool | None,
    ppmi_x4_external_label_selection_allowed: bool | None,
    protected_row_dump_included: bool,
    preregistration_written: bool,
    model_run_started: bool,
) -> dict[str, Any]:
    lifecycle = AccessRouteLifecycle(packet, approval_evidence=approval)
    lifecycle_errors = lifecycle.validation_errors()
    next_action = lifecycle.next_action()
    next_action_errors = next_action.validation_errors()
    if lifecycle_errors or next_action_errors:
        raise ValueError("invalid approval lifecycle: " + "; ".join([*lifecycle_errors, *next_action_errors]))
    if lifecycle.state() != "approved_for_schema_probe":
        raise ValueError(f"schema-probe recording requires approved_for_schema_probe, got {lifecycle.state()!r}")
    if next_action.action != "run_read_only_schema_probe":
        raise ValueError(f"approval lifecycle did not allow schema probing, got {next_action.action!r}")
    if tuple(next_action.blocked_actions_now) != SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS:
        raise ValueError("schema-probe lifecycle must keep post-approval modeling actions blocked")

    artifact_path = output_path.relative_to(ROOT).as_posix() if output_path.is_absolute() else output_path.as_posix()
    spec = schema_probe_spec_for_route(packet.route_id)
    report = SchemaProbeReport(
        spec=spec,
        approved_access=True,
        sections_present=sections_present,
        grouping_keys_found=grouping_keys_found,
        target_columns_found=target_columns_found,
        sensor_modalities_found=sensor_modalities_found,
        valid_subject_count=valid_subject_count,
        protected_row_dump_included=protected_row_dump_included,
        preregistration_written=preregistration_written,
        model_run_started=model_run_started,
        artifact_path=artifact_path,
    )
    report_errors = report.validation_errors()
    if report_errors:
        raise ValueError("invalid schema-probe report: " + "; ".join(report_errors))

    ppmi_x4_policy: dict[str, Any] | None = None
    if packet.route_id == "ppmi_verily":
        if ppmi_x4_multinode_anatomical_sensors_present is None:
            raise ValueError(
                "ppmi_x4_multinode_anatomical_sensors_present is required for ppmi_verily"
            )
        if ppmi_x4_v3_gsp_formula_eligible is None:
            raise ValueError(
                "ppmi_x4_v3_gsp_formula_eligible is required for ppmi_verily"
            )
        if ppmi_x4_external_label_selection_allowed is None:
            raise ValueError(
                "ppmi_x4_external_label_selection_allowed is required for ppmi_verily"
            )
        if ppmi_x4_external_label_selection_allowed:
            raise ValueError("ppmi_x4_external_label_selection_allowed must remain false")
        if (
            ppmi_x4_v3_gsp_formula_eligible
            and not ppmi_x4_multinode_anatomical_sensors_present
        ):
            raise ValueError(
                "ppmi_x4_v3_gsp_formula_eligible requires "
                "ppmi_x4_multinode_anatomical_sensors_present=true"
            )
        if (
            ppmi_x4_v3_gsp_formula_eligible
            and "weargait_compatible_13node_imu" not in sensor_modalities_found
        ):
            raise ValueError(
                "ppmi_x4_v3_gsp_formula_eligible requires "
                "sensor_modalities_found to include weargait_compatible_13node_imu"
            )
        ppmi_x4_policy = {
            "requires_sensor_layout": "WearGait-compatible 13-node anatomical IMU graph",
            "multinode_anatomical_sensors_present": ppmi_x4_multinode_anatomical_sensors_present,
            "v3_gsp_formula_eligible": ppmi_x4_v3_gsp_formula_eligible,
            "external_label_selection_allowed": ppmi_x4_external_label_selection_allowed,
        }

    record = {
        **report.to_dict(),
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "route_name": packet.name,
        "schema_probe_metadata_only": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "approval_record_present": approval_record_path is not None and approval_record_path.exists(),
        "approval_record_identity_redacted": True,
        "approval_record_path_reported": False,
        "next_action_before_recording": next_action.to_dict(),
        "blocked_after_schema_probe": list(SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS),
        "allowed_now": ["preregistration only if later gates accept this schema-probe artifact"],
        "ppmi_x4_v3_gsp_policy": ppmi_x4_policy,
        "not_a_model_result": True,
        "canonical_update_allowed": False,
    }
    evidence_errors = SchemaProbeArtifactEvidence(path=artifact_path, payload=record).validation_errors_for(report)
    if evidence_errors:
        raise ValueError("invalid schema-probe artifact evidence: " + "; ".join(evidence_errors))
    if not report.can_preregister():
        raise ValueError("schema probe must be preregistration-ready before recording")
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-id", default="ppmi_verily")
    parser.add_argument("--sections-present", required=True)
    parser.add_argument("--grouping-keys-found", required=True)
    parser.add_argument("--target-columns-found", required=True)
    parser.add_argument("--sensor-modalities-found", required=True)
    parser.add_argument("--valid-subject-count", type=int, required=True)
    parser.add_argument("--ppmi-x4-multinode-anatomical-sensors-present")
    parser.add_argument("--ppmi-x4-v3-gsp-formula-eligible")
    parser.add_argument("--ppmi-x4-external-label-selection-allowed")
    parser.add_argument("--tracker", default=str(DEFAULT_TRACKER))
    parser.add_argument("--approval-record", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-synthetic-approval",
        action="store_true",
        help="Use only for dry-run/audit tests; real writes require an approval record.",
    )
    parser.add_argument("--protected-row-dump-included", action="store_true")
    parser.add_argument("--preregistration-written", action="store_true")
    parser.add_argument("--model-run-started", action="store_true")
    parser.add_argument(
        "--allow-output-outside-ignored-dir",
        action="store_true",
        help="Allow writing outside .schema_probes/. Use only after separately confirming the artifact is scrubbed.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tracker = load_json(Path(args.tracker), label="tracker")
    packet = packet_for_route(tracker, args.route_id)

    approval_record_path: Path | None
    if args.allow_synthetic_approval:
        if not args.dry_run:
            raise SystemExit("--allow-synthetic-approval is only allowed with --dry-run")
        approval_record_path = None
        approval = synthetic_approval(args.route_id)
    else:
        approval_record_path = Path(args.approval_record) if args.approval_record else default_approval_path(args.route_id)
        if not approval_record_path.is_absolute():
            approval_record_path = ROOT / approval_record_path
        approval = approval_from_record(approval_record_path, args.route_id)

    out_path = Path(args.out) if args.out else default_output_path(args.route_id)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    record = build_record(
        packet=packet,
        approval=approval,
        approval_record_path=approval_record_path,
        output_path=out_path,
        sections_present=parse_csv(args.sections_present),
        grouping_keys_found=parse_csv(args.grouping_keys_found),
        target_columns_found=parse_csv(args.target_columns_found),
        sensor_modalities_found=parse_csv(args.sensor_modalities_found),
        valid_subject_count=args.valid_subject_count,
        ppmi_x4_multinode_anatomical_sensors_present=parse_bool_token(
            args.ppmi_x4_multinode_anatomical_sensors_present,
            field="ppmi_x4_multinode_anatomical_sensors_present",
        ),
        ppmi_x4_v3_gsp_formula_eligible=parse_bool_token(
            args.ppmi_x4_v3_gsp_formula_eligible,
            field="ppmi_x4_v3_gsp_formula_eligible",
        ),
        ppmi_x4_external_label_selection_allowed=parse_bool_token(
            args.ppmi_x4_external_label_selection_allowed,
            field="ppmi_x4_external_label_selection_allowed",
        ),
        protected_row_dump_included=args.protected_row_dump_included,
        preregistration_written=args.preregistration_written,
        model_run_started=args.model_run_started,
    )
    if args.dry_run:
        print(json.dumps(record, indent=2, sort_keys=True))
        return

    if not args.allow_output_outside_ignored_dir and not is_under(out_path, DEFAULT_OUTPUT_DIR):
        raise SystemExit(
            "refusing to write schema-probe evidence outside .schema_probes/ "
            "without --allow-output-outside-ignored-dir"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

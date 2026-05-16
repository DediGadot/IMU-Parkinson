#!/usr/bin/env python3
"""Record non-protected external access-approval metadata.

Approval is not data access material. This script records only safe approval
metadata and verifies that the route lifecycle unlocks read-only schema probing
while downloads, caches, preregistration, model runs, and canonical updates stay
blocked.
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

from pd_imu.experiments import (  # noqa: E402
    SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS,
    AccessApprovalEvidence,
    AccessPacketSpec,
    AccessRouteLifecycle,
    AccessSubmissionEvidence,
)


DEFAULT_TRACKER = ROOT / "results" / "access_submission_tracker_20260509.json"
DEFAULT_OUTPUT_DIR = ROOT / ".access_approvals"
DEFAULT_SUBMISSION_DIR = ROOT / ".access_submissions"


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


def packet_for_route(tracker: dict[str, Any], route_id: str) -> AccessPacketSpec:
    for row in tracker.get("routes", []):
        if str(row.get("id")) == route_id:
            return AccessPacketSpec.from_tracker_row(row)
    raise ValueError(f"route_id {route_id!r} not found in tracker")


def default_output_path(route_id: str) -> Path:
    return DEFAULT_OUTPUT_DIR / f"{route_id}_approval.json"


def default_submission_path(route_id: str) -> Path:
    return DEFAULT_SUBMISSION_DIR / f"{route_id}_submission.json"


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


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


def submission_from_record(path: Path, route_id: str) -> AccessSubmissionEvidence | None:
    if not path.exists():
        return None
    payload = load_json(path, label="submission record")
    evidence = payload.get("submission_evidence")
    if not isinstance(evidence, dict):
        raise ValueError("submission record has no submission_evidence object")
    submission = AccessSubmissionEvidence(**evidence)
    if submission.route_id != route_id:
        raise ValueError(f"submission record route_id {submission.route_id!r} != {route_id!r}")
    return submission


def build_record(
    packet: AccessPacketSpec,
    approval: AccessApprovalEvidence,
    submission: AccessSubmissionEvidence | None,
    *,
    submission_record_path: Path | None,
) -> dict[str, Any]:
    approval_errors = approval.validation_errors_for_route(packet.route_id)
    lifecycle = AccessRouteLifecycle(packet, submission_evidence=submission, approval_evidence=approval)
    lifecycle_errors = lifecycle.validation_errors()
    next_action = lifecycle.next_action()
    next_action_errors = next_action.validation_errors()
    if looks_like_synthetic_approval(approval):
        raise ValueError("approval evidence appears to be synthetic or audit-only metadata")
    if approval_errors or lifecycle_errors or next_action_errors:
        raise ValueError(
            "invalid approval evidence: "
            + "; ".join([*approval_errors, *lifecycle_errors, *next_action_errors])
        )
    if lifecycle.state() != "approved_for_schema_probe":
        raise ValueError(f"approval lifecycle must be approved_for_schema_probe, got {lifecycle.state()!r}")
    if next_action.action != "run_read_only_schema_probe":
        raise ValueError(f"approved lifecycle must allow read-only schema probe, got {next_action.action!r}")
    if not next_action.safe_to_execute_code:
        raise ValueError("approved lifecycle must mark schema-probe code execution safe")
    if tuple(next_action.blocked_actions_now) != SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS:
        raise ValueError("approved lifecycle must keep post-approval modeling actions blocked")
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "route_id": packet.route_id,
        "route_name": packet.name,
        "approval_metadata_only": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "protected_row_dump_included": False,
        "submission_record_present": submission_record_path is not None and submission_record_path.exists(),
        "submission_record_identity_redacted": True,
        "submission_record_path_reported": False,
        "approval_evidence": approval.to_dict(),
        "lifecycle": lifecycle.to_dict(),
        "next_action": next_action.to_dict(),
        "blocked_after_approval": list(SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS),
        "allowed_now": ["read-only schema probe"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-id", default="ppmi_verily")
    parser.add_argument("--approved-at-utc", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--tracker", default=str(DEFAULT_TRACKER))
    parser.add_argument("--submission-record", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-output-outside-ignored-dir",
        action="store_true",
        help="Allow writing outside .access_approvals/. Use only for temporary local experiments.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tracker = load_json(Path(args.tracker), label="tracker")
    packet = packet_for_route(tracker, args.route_id)
    submission_record_path = (
        Path(args.submission_record)
        if args.submission_record is not None
        else default_submission_path(args.route_id)
    )
    if not submission_record_path.is_absolute():
        submission_record_path = ROOT / submission_record_path
    submission = submission_from_record(submission_record_path, args.route_id)
    approval = AccessApprovalEvidence(
        route_id=args.route_id,
        source=args.source,
        approved_at_utc=args.approved_at_utc,
        approved_access=True,
        data_use_terms_accepted=True,
        storage_plan_documented=True,
        notes=args.notes,
    )
    record = build_record(
        packet,
        approval,
        submission,
        submission_record_path=submission_record_path,
    )
    if args.dry_run:
        print(json.dumps(record, indent=2, sort_keys=True))
        return

    out_path = Path(args.out) if args.out else default_output_path(args.route_id)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    if not args.allow_output_outside_ignored_dir and not is_under(out_path, DEFAULT_OUTPUT_DIR):
        raise SystemExit(
            "refusing to write approval evidence outside .access_approvals/ "
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

#!/usr/bin/env python3
"""Record non-protected external access-submission metadata.

This script records that a gated external-data packet was submitted. It does not
record completed packets, signatures, credentials, protected rows, or approval.
Submission remains pre-access: the next action is waiting for approval.
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
    REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS,
    AccessPacketSpec,
    AccessRouteLifecycle,
    AccessSubmissionEvidence,
)


DEFAULT_TRACKER = ROOT / "results" / "access_submission_tracker_20260509.json"
DEFAULT_OUTPUT_DIR = ROOT / ".access_submissions"


def load_tracker(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("tracker source is missing") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("tracker source is not valid JSON") from exc
    except UnicodeDecodeError as exc:
        raise ValueError("tracker source is not valid UTF-8 JSON") from exc
    except OSError as exc:
        raise ValueError("tracker source could not be read") from exc
    if not isinstance(payload, dict):
        raise ValueError("tracker source must contain a JSON object")
    return payload


def packet_for_route(tracker: dict[str, Any], route_id: str) -> AccessPacketSpec:
    for row in tracker.get("routes", []):
        if str(row.get("id")) == route_id:
            return AccessPacketSpec.from_tracker_row(row)
    raise ValueError(f"route_id {route_id!r} not found in tracker")


def default_output_path(route_id: str) -> Path:
    return DEFAULT_OUTPUT_DIR / f"{route_id}_submission.json"


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def looks_like_synthetic_submission(evidence: AccessSubmissionEvidence) -> bool:
    text = " ".join(
        value
        for value in (
            evidence.submission_channel,
            evidence.submitted_by,
            evidence.confirmation_reference,
            evidence.notes,
        )
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
            "test submission",
            "test receipt",
        )
    )


def build_record(packet: AccessPacketSpec, evidence: AccessSubmissionEvidence) -> dict[str, Any]:
    errors = evidence.validation_errors_for_packet(packet)
    lifecycle = AccessRouteLifecycle(packet, submission_evidence=evidence)
    lifecycle_errors = lifecycle.validation_errors()
    next_action = lifecycle.next_action()
    next_action_errors = next_action.validation_errors()
    if looks_like_synthetic_submission(evidence):
        raise ValueError("submission evidence appears to be synthetic or audit-only metadata")
    if errors or lifecycle_errors or next_action_errors:
        raise ValueError(
            "invalid submission evidence: "
            + "; ".join([*errors, *lifecycle_errors, *next_action_errors])
        )
    if lifecycle.state() != "submitted_pending_approval":
        raise ValueError(f"submission lifecycle must be submitted_pending_approval, got {lifecycle.state()!r}")
    if next_action.action != "wait_for_access_approval":
        raise ValueError(f"submitted lifecycle must wait for approval, got {next_action.action!r}")
    if next_action.safe_to_execute_code:
        raise ValueError("submitted lifecycle must not mark code execution safe")
    if tuple(next_action.blocked_actions_now) != REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS:
        raise ValueError("submitted lifecycle must keep all pre-access compute actions blocked")
    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "route_id": packet.route_id,
        "route_name": packet.name,
        "not_approval": True,
        "protected_data_included": False,
        "completed_packet_included": False,
        "credentials_or_tokens_included": False,
        "submission_evidence": evidence.to_dict(),
        "lifecycle": lifecycle.to_dict(),
        "next_action": next_action.to_dict(),
        "blocked_until_approval": list(REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS),
        "allowed_now": ["wait for access approval"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-id", default="ppmi_verily")
    parser.add_argument("--submitted-at-utc", required=True)
    parser.add_argument("--submission-channel", required=True)
    parser.add_argument("--submitted-by", required=True)
    parser.add_argument("--confirmation-reference", default=None)
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--pre-submission-preflight-passed",
        action="store_true",
        help=(
            "Assert the route's content-free completed-packet/package preflight "
            "passed before submission. For PPMI/Verily this means the combined "
            "packet+email package validator passed."
        ),
    )
    parser.add_argument("--tracker", default=str(DEFAULT_TRACKER))
    parser.add_argument("--out", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-output-outside-ignored-dir",
        action="store_true",
        help="Allow writing outside .access_submissions/. Use only for temporary local experiments.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tracker = load_tracker(Path(args.tracker))
    packet = packet_for_route(tracker, args.route_id)
    evidence = AccessSubmissionEvidence(
        route_id=args.route_id,
        submitted_at_utc=args.submitted_at_utc,
        submission_channel=args.submission_channel,
        submitted_by=args.submitted_by,
        confirmation_reference=args.confirmation_reference,
        pre_submission_preflight_passed=args.pre_submission_preflight_passed,
        notes=args.notes,
    )
    record = build_record(packet, evidence)
    if args.dry_run:
        print(json.dumps(record, indent=2, sort_keys=True))
        return

    out_path = Path(args.out) if args.out else default_output_path(args.route_id)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    if not args.allow_output_outside_ignored_dir and not is_under(out_path, DEFAULT_OUTPUT_DIR):
        raise SystemExit(
            "refusing to write submission evidence outside .access_submissions/ "
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

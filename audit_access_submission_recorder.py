#!/usr/bin/env python3
"""Verify the local access-submission recorder is safe and fail-closed."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.experiments import REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SCRIPT = ROOT / "scripts" / "record_access_submission.py"
OUT_JSON = RESULTS / "access_submission_recorder_audit_20260510.json"
OUT_MD = RESULTS / "access_submission_recorder_audit_20260510.md"
BAD_TRACKER = RESULTS / "_access_submission_recorder_bad_tracker.json"
MISSING_TRACKER = RESULTS / "_access_submission_recorder_missing_tracker.json"


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


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    dry_run = run_cmd(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT.relative_to(ROOT)),
            "--route-id",
            "ppmi_verily",
            "--submitted-at-utc",
            "2026-05-10T00:00:00Z",
            "--submission-channel",
            "PPMI access workflow plus Tier-3 Verily packet email",
            "--submitted-by",
            "institutional PI or approved delegate",
            "--confirmation-reference",
            "non-protected confirmation id",
            "--pre-submission-preflight-passed",
            "--dry-run",
        ]
    )
    record = json.loads(dry_run.stdout) if dry_run.returncode == 0 else {}

    outside_write = run_cmd(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT.relative_to(ROOT)),
            "--route-id",
            "ppmi_verily",
            "--submitted-at-utc",
            "2026-05-10T00:00:00Z",
            "--submission-channel",
            "PPMI access workflow plus Tier-3 Verily packet email",
            "--submitted-by",
            "institutional PI or approved delegate",
            "--pre-submission-preflight-passed",
            "--out",
            "results/unsafe_submission_record.json",
        ]
    )
    synthetic_source_attempt = run_cmd(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT.relative_to(ROOT)),
            "--route-id",
            "ppmi_verily",
            "--submitted-at-utc",
            "2026-05-10T00:00:00Z",
            "--submission-channel",
            "synthetic test submission channel for recorder audit",
            "--submitted-by",
            "institutional PI or approved delegate",
            "--confirmation-reference",
            "test receipt",
            "--pre-submission-preflight-passed",
            "--dry-run",
        ]
    )
    placeholder_attempt = run_cmd(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT.relative_to(ROOT)),
            "--route-id",
            "ppmi_verily",
            "--submitted-at-utc",
            "<ISO8601_UTC>",
            "--submission-channel",
            "<non_protected_channel>",
            "--submitted-by",
            "<non_protected_submitter>",
            "--confirmation-reference",
            "<non_protected_receipt>",
            "--pre-submission-preflight-passed",
            "--dry-run",
        ]
    )
    missing_preflight_attempt = run_cmd(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT.relative_to(ROOT)),
            "--route-id",
            "ppmi_verily",
            "--submitted-at-utc",
            "2026-05-10T00:00:00Z",
            "--submission-channel",
            "PPMI access workflow plus Tier-3 Verily packet email",
            "--submitted-by",
            "institutional PI or approved delegate",
            "--confirmation-reference",
            "non-protected confirmation id",
            "--dry-run",
        ]
    )
    unsafe_metadata_attempt = run_cmd(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT.relative_to(ROOT)),
            "--route-id",
            "ppmi_verily",
            "--submitted-at-utc",
            "2026-05-10T00:00:00Z",
            "--submission-channel",
            "PPMI access workflow plus Tier-3 Verily packet email",
            "--submitted-by",
            "institutional PI or approved delegate",
            "--confirmation-reference",
            "/home/pi/completed_packet.docx",
            "--notes",
            "api_key=secret",
            "--pre-submission-preflight-passed",
            "--dry-run",
        ]
    )
    BAD_TRACKER.write_text("{not-json", encoding="utf-8")
    bad_tracker_attempt = run_cmd(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT.relative_to(ROOT)),
            "--route-id",
            "ppmi_verily",
            "--submitted-at-utc",
            "2026-05-10T00:00:00Z",
            "--submission-channel",
            "PPMI access workflow plus Tier-3 Verily packet email",
            "--submitted-by",
            "institutional PI or approved delegate",
            "--pre-submission-preflight-passed",
            "--tracker",
            str(BAD_TRACKER.relative_to(ROOT)),
            "--dry-run",
        ]
    )
    BAD_TRACKER.unlink(missing_ok=True)
    missing_tracker_attempt = run_cmd(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT.relative_to(ROOT)),
            "--route-id",
            "ppmi_verily",
            "--submitted-at-utc",
            "2026-05-10T00:00:00Z",
            "--submission-channel",
            "PPMI access workflow plus Tier-3 Verily packet email",
            "--submitted-by",
            "institutional PI or approved delegate",
            "--pre-submission-preflight-passed",
            "--tracker",
            str(MISSING_TRACKER.relative_to(ROOT)),
            "--dry-run",
        ]
    )

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    lifecycle = record.get("lifecycle", {})
    next_action = record.get("next_action", {})
    checks = [
        check(
            "recorder dry-run emits valid PPMI submitted-pending record",
            dry_run.returncode == 0
            and record.get("route_id") == "ppmi_verily"
            and lifecycle.get("state") == "submitted_pending_approval"
            and next_action.get("action") == "wait_for_access_approval",
            {"returncode": dry_run.returncode, "record": record},
        ),
        check(
            "submission record remains non-protected and not approval",
            record.get("not_approval") is True
            and record.get("protected_data_included") is False
            and record.get("completed_packet_included") is False
            and record.get("credentials_or_tokens_included") is False
            and record.get("submission_evidence", {}).get("approval_claimed") is False
            and record.get("submission_evidence", {}).get("pre_submission_preflight_passed") is True,
            {
                "not_approval": record.get("not_approval"),
                "protected_data_included": record.get("protected_data_included"),
                "completed_packet_included": record.get("completed_packet_included"),
                "credentials_or_tokens_included": record.get("credentials_or_tokens_included"),
                "approval_claimed": record.get("submission_evidence", {}).get("approval_claimed"),
                "pre_submission_preflight_passed": record.get("submission_evidence", {}).get(
                    "pre_submission_preflight_passed"
                ),
            },
        ),
        check(
            "submitted route keeps all pre-access compute actions blocked",
            tuple(next_action.get("blocked_actions_now", ())) == REQUIRED_PRE_ACCESS_BLOCKED_ACTIONS
            and next_action.get("safe_to_execute_code") is False,
            {"next_action": next_action},
        ),
        check(
            "default submission output directory is gitignored",
            ".access_submissions/" in gitignore,
            {"gitignore": ".gitignore"},
        ),
        check(
            "recorder refuses non-ignored output path by default",
            outside_write.returncode != 0
            and "refusing to write submission evidence outside .access_submissions/" in outside_write.stdout
            and not (ROOT / "results" / "unsafe_submission_record.json").exists(),
            {"returncode": outside_write.returncode, "output_tail": outside_write.stdout[-1000:]},
        ),
        check(
            "recorder refuses synthetic or audit-only submission sources",
            synthetic_source_attempt.returncode != 0
            and "submission evidence appears to be synthetic or audit-only metadata"
            in synthetic_source_attempt.stdout
            and "Traceback" not in synthetic_source_attempt.stdout,
            {
                "returncode": synthetic_source_attempt.returncode,
                "output_tail": synthetic_source_attempt.stdout[-1000:],
            },
        ),
        check(
            "recorder refuses unfilled submission command-template placeholders",
            placeholder_attempt.returncode != 0
            and "contains an unfilled placeholder" in placeholder_attempt.stdout
            and "Traceback" not in placeholder_attempt.stdout,
            {
                "returncode": placeholder_attempt.returncode,
                "output_tail": placeholder_attempt.stdout[-1000:],
            },
        ),
        check(
            "recorder refuses submission metadata without pre-submission preflight assertion",
            missing_preflight_attempt.returncode != 0
            and "pre-submission completed-packet/package preflight must have passed"
            in missing_preflight_attempt.stdout
            and "Traceback" not in missing_preflight_attempt.stdout,
            {
                "returncode": missing_preflight_attempt.returncode,
                "output_tail": missing_preflight_attempt.stdout[-1000:],
            },
        ),
        check(
            "recorder refuses local completed-file references and token-like metadata",
            unsafe_metadata_attempt.returncode != 0
            and "confirmation_reference must not contain local paths or completed-file references"
            in unsafe_metadata_attempt.stdout
            and "notes must not contain credentials or token-like strings" in unsafe_metadata_attempt.stdout
            and "/home/pi/completed_packet.docx" not in unsafe_metadata_attempt.stdout
            and "api_key=secret" not in unsafe_metadata_attempt.stdout
            and "Traceback" not in unsafe_metadata_attempt.stdout,
            {
                "returncode": unsafe_metadata_attempt.returncode,
                "output_tail": unsafe_metadata_attempt.stdout[-1000:],
                "path_echoed": "/home/pi/completed_packet.docx" in unsafe_metadata_attempt.stdout,
                "secret_echoed": "api_key=secret" in unsafe_metadata_attempt.stdout,
            },
        ),
        check(
            "recorder input JSON loader errors fail closed with tracker identity redacted",
            bad_tracker_attempt.returncode != 0
            and "tracker source is not valid JSON" in bad_tracker_attempt.stdout
            and str(BAD_TRACKER) not in bad_tracker_attempt.stdout
            and BAD_TRACKER.name not in bad_tracker_attempt.stdout
            and missing_tracker_attempt.returncode != 0
            and "tracker source is missing" in missing_tracker_attempt.stdout
            and str(MISSING_TRACKER) not in missing_tracker_attempt.stdout
            and MISSING_TRACKER.name not in missing_tracker_attempt.stdout
            and "Traceback" not in bad_tracker_attempt.stdout,
            {
                "bad_returncode": bad_tracker_attempt.returncode,
                "bad_output_tail": bad_tracker_attempt.stdout[-1000:],
                "bad_error_path_echoed": str(BAD_TRACKER) in bad_tracker_attempt.stdout,
                "bad_error_filename_echoed": BAD_TRACKER.name in bad_tracker_attempt.stdout,
                "missing_returncode": missing_tracker_attempt.returncode,
                "missing_output_tail": missing_tracker_attempt.stdout[-1000:],
                "missing_error_path_echoed": str(MISSING_TRACKER) in missing_tracker_attempt.stdout,
                "missing_error_filename_echoed": MISSING_TRACKER.name in missing_tracker_attempt.stdout,
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_access_submission_recorder.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "access_submission_recorder_passed" if not hard_failures else "access_submission_recorder_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": (
            "A top-priority PPMI submission can now be recorded in an ignored local file "
            "after user submission, while the lifecycle remains submitted-pending-approval "
            "and all protected-data/model actions stay blocked. Malformed tracker JSON fails "
            "closed without a traceback or tracker path/name echo, synthetic or audit-only "
            "submission sources are rejected, unfilled command-template placeholders are rejected, "
            "and local completed-file references or token-like metadata are rejected without echoing "
            "the sensitive value."
        ),
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Access Submission Recorder Audit - 2026-05-10",
        "",
        "This verifies the local submission recorder. It is not a model result and not approval evidence.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
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
            report["claim"],
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
                "passed": report["passed"],
                "decision": report["decision"],
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

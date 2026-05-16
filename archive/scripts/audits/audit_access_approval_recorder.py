#!/usr/bin/env python3
"""Verify the local access-approval recorder unlocks only schema probing."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.experiments import SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SCRIPT = ROOT / "scripts" / "record_access_approval.py"
OUT_JSON = RESULTS / "access_approval_recorder_audit_20260510.json"
OUT_MD = RESULTS / "access_approval_recorder_audit_20260510.md"
BAD_SUBMISSION = ROOT / ".access_submissions" / "access_approval_recorder_bad_submission.json"


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
            "--approved-at-utc",
            "2026-05-10T00:00:00Z",
            "--source",
            "non-protected PPMI approval notice metadata",
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
            "--approved-at-utc",
            "2026-05-10T00:00:00Z",
            "--source",
            "non-protected PPMI approval notice metadata",
            "--out",
            "results/unsafe_approval_record.json",
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
            "--approved-at-utc",
            "2026-05-10T00:00:00Z",
            "--source",
            "synthetic approval metadata for recorder audit",
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
            "--approved-at-utc",
            "<ISO8601_UTC>",
            "--source",
            "<non_protected_approval_source>",
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
            "--approved-at-utc",
            "2026-05-10T00:00:00Z",
            "--source",
            "/home/pi/approval_notice.pdf",
            "--notes",
            "access_token=secret",
            "--dry-run",
        ]
    )
    BAD_SUBMISSION.parent.mkdir(parents=True, exist_ok=True)
    BAD_SUBMISSION.write_text("{not-json", encoding="utf-8")
    bad_submission_attempt = run_cmd(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT.relative_to(ROOT)),
            "--route-id",
            "ppmi_verily",
            "--approved-at-utc",
            "2026-05-10T00:00:00Z",
            "--source",
            "non-protected PPMI approval notice metadata",
            "--submission-record",
            str(BAD_SUBMISSION.relative_to(ROOT)),
            "--dry-run",
        ]
    )
    BAD_SUBMISSION.unlink(missing_ok=True)

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    lifecycle = record.get("lifecycle", {})
    next_action = record.get("next_action", {})
    checks = [
        check(
            "recorder dry-run emits valid PPMI approved-for-schema-probe record",
            dry_run.returncode == 0
            and record.get("route_id") == "ppmi_verily"
            and lifecycle.get("state") == "approved_for_schema_probe"
            and next_action.get("action") == "run_read_only_schema_probe",
            {"returncode": dry_run.returncode, "record": record},
        ),
        check(
            "approval record remains metadata-only and excludes protected content",
            record.get("approval_metadata_only") is True
            and record.get("protected_data_included") is False
            and record.get("credentials_or_tokens_included") is False
            and record.get("protected_row_dump_included") is False
            and "submission_record_path" not in record
            and record.get("submission_record_identity_redacted") is True
            and record.get("submission_record_path_reported") is False
            and record.get("approval_evidence", {}).get("approved_access") is True
            and record.get("approval_evidence", {}).get("data_use_terms_accepted") is True
            and record.get("approval_evidence", {}).get("storage_plan_documented") is True,
            {
                "approval_metadata_only": record.get("approval_metadata_only"),
                "protected_data_included": record.get("protected_data_included"),
                "credentials_or_tokens_included": record.get("credentials_or_tokens_included"),
                "protected_row_dump_included": record.get("protected_row_dump_included"),
                "submission_record_path_present": "submission_record_path" in record,
                "submission_record_identity_redacted": record.get("submission_record_identity_redacted"),
                "submission_record_path_reported": record.get("submission_record_path_reported"),
                "approval_evidence": record.get("approval_evidence"),
            },
        ),
        check(
            "approved route unlocks only read-only schema probe",
            tuple(next_action.get("blocked_actions_now", ())) == SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS
            and next_action.get("safe_to_execute_code") is True
            and next_action.get("allowed_now") == ["read-only schema probe"],
            {"next_action": next_action},
        ),
        check(
            "default approval output directory is gitignored",
            ".access_approvals/" in gitignore,
            {"gitignore": ".gitignore"},
        ),
        check(
            "recorder refuses non-ignored output path by default",
            outside_write.returncode != 0
            and "refusing to write approval evidence outside .access_approvals/" in outside_write.stdout
            and not (ROOT / "results" / "unsafe_approval_record.json").exists(),
            {"returncode": outside_write.returncode, "output_tail": outside_write.stdout[-1000:]},
        ),
        check(
            "recorder refuses synthetic or audit-only approval sources",
            synthetic_source_attempt.returncode != 0
            and "approval evidence appears to be synthetic or audit-only metadata"
            in synthetic_source_attempt.stdout
            and "Traceback" not in synthetic_source_attempt.stdout,
            {
                "returncode": synthetic_source_attempt.returncode,
                "output_tail": synthetic_source_attempt.stdout[-1000:],
            },
        ),
        check(
            "recorder refuses unfilled approval command-template placeholders",
            placeholder_attempt.returncode != 0
            and "contains an unfilled placeholder" in placeholder_attempt.stdout
            and "Traceback" not in placeholder_attempt.stdout,
            {
                "returncode": placeholder_attempt.returncode,
                "output_tail": placeholder_attempt.stdout[-1000:],
            },
        ),
        check(
            "recorder refuses local approval-file references and token-like metadata",
            unsafe_metadata_attempt.returncode != 0
            and "approval source must not contain local paths or completed-file references"
            in unsafe_metadata_attempt.stdout
            and "notes must not contain credentials or token-like strings" in unsafe_metadata_attempt.stdout
            and "/home/pi/approval_notice.pdf" not in unsafe_metadata_attempt.stdout
            and "access_token=secret" not in unsafe_metadata_attempt.stdout
            and "Traceback" not in unsafe_metadata_attempt.stdout,
            {
                "returncode": unsafe_metadata_attempt.returncode,
                "output_tail": unsafe_metadata_attempt.stdout[-1000:],
                "path_echoed": "/home/pi/approval_notice.pdf" in unsafe_metadata_attempt.stdout,
                "secret_echoed": "access_token=secret" in unsafe_metadata_attempt.stdout,
            },
        ),
        check(
            "recorder input JSON loader errors fail closed with submission identity redacted",
            bad_submission_attempt.returncode != 0
            and "submission record source is not valid JSON" in bad_submission_attempt.stdout
            and str(BAD_SUBMISSION) not in bad_submission_attempt.stdout
            and BAD_SUBMISSION.name not in bad_submission_attempt.stdout
            and "Traceback" not in bad_submission_attempt.stdout,
            {
                "returncode": bad_submission_attempt.returncode,
                "output_tail": bad_submission_attempt.stdout[-1000:],
                "bad_error_path_echoed": str(BAD_SUBMISSION) in bad_submission_attempt.stdout,
                "bad_error_filename_echoed": BAD_SUBMISSION.name in bad_submission_attempt.stdout,
            },
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_access_approval_recorder.py",
        "not_a_model_result": True,
        "goal_complete": False,
        "passed": not hard_failures,
        "decision": "access_approval_recorder_passed" if not hard_failures else "access_approval_recorder_failed",
        "checks": checks,
        "hard_failures": hard_failures,
        "claim": (
            "A top-priority PPMI approval can now be recorded in an ignored local file "
            "as metadata-only evidence. Approval unlocks only read-only schema probing; "
            "downloads, caches, preregistration, remote jobs, model runs, and canonical "
            "updates remain blocked. Malformed submission/approval input JSON fails closed "
            "without a traceback or submission-record path/name echo, synthetic or audit-only "
            "approval sources are rejected, unfilled command-template placeholders are rejected, "
            "and local approval-file references or token-like metadata are rejected without echoing "
            "the sensitive value."
        ),
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Access Approval Recorder Audit - 2026-05-10",
        "",
        "This verifies the local approval recorder. It is not a model result and contains no protected data.",
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

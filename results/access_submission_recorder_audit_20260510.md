# Access Submission Recorder Audit - 2026-05-10

This verifies the local submission recorder. It is not a model result and not approval evidence.

- Passed: `True`
- Decision: `access_submission_recorder_passed`
- Hard failures: `0`

## Checks

- `True` recorder dry-run emits valid PPMI submitted-pending record
- `True` submission record remains non-protected and not approval
- `True` submitted route keeps all pre-access compute actions blocked
- `True` default submission output directory is gitignored
- `True` recorder refuses non-ignored output path by default
- `True` recorder refuses synthetic or audit-only submission sources
- `True` recorder refuses unfilled submission command-template placeholders
- `True` recorder refuses submission metadata without pre-submission preflight assertion
- `True` recorder refuses local completed-file references and token-like metadata
- `True` recorder input JSON loader errors fail closed with tracker identity redacted

## Claim

A top-priority PPMI submission can now be recorded in an ignored local file after user submission, while the lifecycle remains submitted-pending-approval and all protected-data/model actions stay blocked. Malformed tracker JSON fails closed without a traceback or tracker path/name echo, synthetic or audit-only submission sources are rejected, unfilled command-template placeholders are rejected, and local completed-file references or token-like metadata are rejected without echoing the sensitive value.

Machine-readable report: `results/access_submission_recorder_audit_20260510.json`

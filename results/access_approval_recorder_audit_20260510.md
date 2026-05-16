# Access Approval Recorder Audit - 2026-05-10

This verifies the local approval recorder. It is not a model result and contains no protected data.

- Passed: `True`
- Decision: `access_approval_recorder_passed`
- Hard failures: `0`

## Checks

- `True` recorder dry-run emits valid PPMI approved-for-schema-probe record
- `True` approval record remains metadata-only and excludes protected content
- `True` approved route unlocks only read-only schema probe
- `True` default approval output directory is gitignored
- `True` recorder refuses non-ignored output path by default
- `True` recorder refuses synthetic or audit-only approval sources
- `True` recorder refuses unfilled approval command-template placeholders
- `True` recorder refuses local approval-file references and token-like metadata
- `True` recorder input JSON loader errors fail closed with submission identity redacted

## Claim

A top-priority PPMI approval can now be recorded in an ignored local file as metadata-only evidence. Approval unlocks only read-only schema probing; downloads, caches, preregistration, remote jobs, model runs, and canonical updates remain blocked. Malformed submission/approval input JSON fails closed without a traceback or submission-record path/name echo, synthetic or audit-only approval sources are rejected, unfilled command-template placeholders are rejected, and local approval-file references or token-like metadata are rejected without echoing the sensitive value.

Machine-readable report: `results/access_approval_recorder_audit_20260510.json`

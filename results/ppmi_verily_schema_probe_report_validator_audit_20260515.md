# PPMI / Verily Schema-Probe Report Validator Audit - 2026-05-15

This audits a content-free completed-report validator. It is not an approval, schema-probe artifact, or model result.

- Passed: `True`
- Decision: `ppmi_verily_schema_probe_report_validator_ready`
- Validator: `scripts/validate_ppmi_verily_schema_probe_report.py`
- Hard failures: `0`

## Checks

- `True` validator script exists
- `True` synthetic completed schema-probe report passes without recording content
- `True` unfinished report template fails preflight
- `True` low subject count fails schema-probe contract
- `True` protected row-like content fails preflight
- `True` local paths and completed-file references fail preflight
- `True` missing X4 eligibility fields fail preflight
- `True` X4 formula eligibility requires comparable multi-node sensors
- `True` validator output does not echo report paths or filenames

## Decision

The validator is ready for post-approval local schema-probe report preflight. It prints only redacted pass/fail evidence and does not unlock modeling.

Machine-readable report: `results/ppmi_verily_schema_probe_report_validator_audit_20260515.json`

# Schema Probe Recorder Audit - 2026-05-10

This verifies the local schema-probe recorder. It is not a model result and contains no protected data.

- Passed: `True`
- Decision: `schema_probe_recorder_passed`
- Hard failures: `0`

## Checks

- `True` recorder dry-run emits valid PPMI schema-probe artifact payload
- `True` PPMI X4 V3-GSP eligibility policy is recorded as schema metadata
- `True` schema-probe artifact remains metadata-only
- `True` approval record identity is redacted in schema-probe artifact and errors
- `True` approval lifecycle is schema-probe-only before recording
- `True` recorder rejects preregistration, protected rows, and low-N probes
- `True` recorder refuses unfilled schema-probe command-template placeholders
- `True` real recording requires an approval record
- `True` recorder input JSON loader errors fail closed
- `True` synthetic approval record cannot unlock schema-probe recording
- `True` default schema-probe output directory is gitignored
- `True` recorder refuses non-ignored output path by default

## Claim

A post-approval schema-probe report can now be recorded as a scrubbed SchemaProbeArtifactEvidence payload in .schema_probes/. The recorder requires approval evidence for real writes, rejects row dumps, preregistration, model starts, low-N probes, and non-ignored output paths, and does not change any T1/T3 result. Malformed approval/tracker input JSON fails closed without a traceback, approval-record local identity is redacted from emitted payloads and errors, synthetic audit-only approval records cannot unlock schema-probe recording, and unfilled schema-probe command-template placeholders are rejected.

Machine-readable report: `results/schema_probe_recorder_audit_20260510.json`

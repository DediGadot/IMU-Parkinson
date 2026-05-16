# Schema Probe Artifact Gate Audit - 2026-05-10

This verifies schema-probe artifact content evidence before protected preregistration/run stages. It is not a model result.

- Passed: `True`
- Decision: `schema_probe_artifact_gate_passed`
- Hard failures: `0`

## Checks

- `True` clean schema-probe evidence matches report
- `True` stale subject count is rejected
- `True` stale route id is rejected
- `True` protected row dump in schema artifact is rejected
- `True` hidden row-shaped schema payload is rejected
- `True` credential-like schema payload is rejected
- `True` malformed schema-probe artifact field types fail closed
- `True` schema-probe artifact loader errors fail closed
- `True` protected preregistration requires schema-probe content evidence
- `True` protected run requires schema-probe content evidence

## Claim

Protected external preregistration and run stages now require SchemaProbeArtifactEvidence, so an observed schema-probe path alone cannot unlock modeling when the probe artifact content is stale, mismatched, malformed, missing or invalid at load time, contaminated, or contains row-like or credential-like payload keys.

Machine-readable report: `results/schema_probe_artifact_gate_audit_20260510.json`

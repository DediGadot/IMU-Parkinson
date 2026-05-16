# Preregistration Artifact Gate Audit - 2026-05-10

This verifies content validation for preregistration artifacts before future runs. It is not a model result.

- Passed: `True`
- Decision: `preregistration_artifact_gate_passed`
- Hard failures: `0`

## Checks

- `True` matching preregistration file validates against experiment spec
- `True` stale formula hash is rejected
- `True` malformed preregistration fields fail closed
- `True` preregistration artifact loader errors fail closed
- `True` row-like preregistration payload is rejected
- `True` credential-like preregistration payload is rejected
- `True` undeclared preregistration path is rejected
- `True` run stage requires preregistration content evidence

## Claim

Run-stage execution now requires preregistration content evidence, not only an observed preregistration path. Preregistration artifacts also fail closed on malformed scalar fields, missing or invalid source JSON, and row-like or credential-like payload keys.

Machine-readable report: `results/preregistration_artifact_gate_audit_20260510.json`

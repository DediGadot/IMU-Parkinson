# Experiment Execution Gate Audit - 2026-05-10

This verifies execution-stage gating for future runners. It is not a model result.

- Passed: `True`
- Decision: `experiment_execution_gate_passed`
- Hard failures: `0`

## Checks

- `True` pre-access state allows access request only
- `True` approved access allows schema probe without binding experiment
- `True` access lifecycle is consumed by schema-probe execution gate
- `True` external preregistration requires observed schema-probe artifact
- `True` run requires observed preregistration artifact
- `True` protected external experiments cannot update internal canonical claims
- `True` execution gate delegates canonical updates to reporting gate
- `True` malformed execution gate objects fail closed

## Claim

Future external experiment runners have a reusable execution-stage gate: access request, schema probe, preregistration, and run stages are allowed only when route readiness, approved access lifecycle or approval evidence, clean schema-probe evidence, and observed prerequisite artifacts support that stage. Malformed top-level route, experiment, evidence, artifact-ledger, or observed-path inputs fail closed as validation errors. Canonical-claim updates are deliberately delegated to CanonicalClaimUpdateGate rather than authorized by ExperimentExecutionGate.

Machine-readable report: `results/experiment_execution_gate_audit_20260510.json`

# Canonical Claim Update Gate Audit - 2026-05-10

This is an architecture guard, not a model result.

- Passed: `True`
- Decision: `canonical_claim_update_gate_passed`
- Hard failures: `0`

## Checks

- `True` complete_internal_bundle_can_update
- `True` metric_source_requires_metric_artifact_evidence
- `True` missing_required_bundle_artifact_blocks_update
- `True` claim_source_must_come_from_bundle
- `True` malformed canonical update gate objects fail closed

A canonical update now needs a complete `ExperimentResultBundle`, a passing `ReportingEvidenceGate`, and a canonical claim whose source artifact belongs to the bundle. When that source is a metrics JSON artifact, the update also needs `MetricArtifactEvidence` that recomputes the metrics from the required OOF predictions.

Machine-readable report: `results/canonical_claim_update_gate_audit_20260510.json`

# Reporting Evidence Gate Audit - 2026-05-10

This verifies claim-source artifact gating for reporting surfaces. It is not a model result.

- Passed: `True`
- Decision: `reporting_evidence_gate_passed`
- Hard failures: `0`

## Checks

- `True` source artifacts used in audit exist locally
- `True` internal reporting claims come from current truth registry
- `True` complete reporting evidence gate can emit
- `True` missing source artifact blocks emission
- `True` missing required framing text blocks emission
- `True` stale metric evidence blocks emission
- `True` hashed source artifacts require matching metric evidence hashes
- `True` claim metric evidence hashes must be hex
- `True` claim metric evidence JSON path syntax errors fail closed
- `True` claim metric evidence JSON paths reject empty segments
- `True` claim metric evidence malformed/protected payloads fail closed
- `True` claim metric evidence loader errors fail closed
- `True` duplicate claim names block ambiguous metric evidence
- `True` duplicate metric evidence names block silent overwrite
- `True` metric evidence for unknown claims blocks emission
- `True` malformed reporting gate objects fail closed

## Claim

Reporting surfaces now have a reusable evidence gate: a surface can emit claims only when claim labels/framing validate, current internal truth claims come from the typed registry, claim names and metric-evidence names are unique, every metric-evidence entry belongs to a surface claim, every claim source artifact is present, metric-evidence hashes are true hex SHA-256 values, malformed metric-evidence JSON paths fail closed, including empty path segments, row-like or credential-like claim metric payload keys fail closed, malformed claim metric payloads fail closed, claim metric evidence loader errors fail closed, malformed reporting surface/gate objects fail closed, hashed source artifacts match metric-evidence hashes, and metric/value/N claims match parsed source-artifact evidence.

Machine-readable report: `results/reporting_evidence_gate_audit_20260510.json`

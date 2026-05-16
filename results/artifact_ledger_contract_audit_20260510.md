# Artifact Ledger Contract Audit - 2026-05-10

This verifies filesystem-backed artifact observation for architecture gates. It is not a model result.

- Passed: `True`
- Decision: `artifact_ledger_contract_passed`
- Hard failures: `0`

## Checks

- `True` ledger observes existing artifacts and missing paths
- `True` ledger records hashes for existing artifacts
- `True` reporting evidence gate accepts ledger-observed source artifact
- `True` execution gate accepts ledger-observed schema and preregistration artifacts
- `True` ledger rejects blank or duplicate artifact observations
- `True` ledger rejects malformed record fields and hashes
- `True` ledger observation and hash failures fail closed

## Claim

Execution and reporting gates can now consume a filesystem-backed ArtifactLedger instead of ad hoc observed path tuples; the ledger also flags blank, duplicate, malformed, fake-hash, or unhashable artifact observations.

Machine-readable report: `results/artifact_ledger_contract_audit_20260510.json`

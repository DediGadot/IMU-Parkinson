# Dataset And Feature Contract Audit - 2026-05-10

This verifies dataset/schema/feature declaration validation. It is not a model result.

- Passed: `True`
- Decision: `dataset_feature_contract_passed`
- Hard failures: `0`

## Checks

- `True` subject table rejects blank and duplicate columns
- `True` cohort schema rejects blank and duplicate identity fields
- `True` feature matrix rejects blank and duplicate join declarations
- `True` malformed dataset and feature field types fail closed
- `True` clean manifest-backed feature matrix validates
- `True` schema probe spec rejects blank and duplicate requirements
- `True` schema probe report rejects blank and duplicate observed fields

## Claim

Dataset and feature contracts now fail closed on blank, duplicate, or malformed field-type schema, probe, and feature identifiers while still accepting a clean manifest-backed feature matrix.

Machine-readable report: `results/dataset_feature_contract_audit_20260510.json`

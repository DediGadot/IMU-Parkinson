# PipelineSpec Contract Audit - 2026-05-10

This verifies pipeline declaration validation. It is not a model result.

- Passed: `True`
- Decision: `pipeline_spec_contract_passed`
- Hard failures: `0`

## Checks

- `True` valid pipeline spec has stable formula hash
- `True` blank component identities are rejected
- `True` duplicate grouping keys are rejected
- `True` duplicate feature names are rejected
- `True` blank feature name or source is rejected
- `True` label-using feature blocks remain rejected
- `True` malformed pipeline field types fail closed

## Claim

PipelineSpec now fails closed on blank component identities, malformed field types, duplicate grouping keys, duplicate feature block names, blank feature declarations, and label-using feature blocks before preregistration hashes or experiment specs are accepted.

Machine-readable report: `results/pipeline_spec_contract_audit_20260510.json`

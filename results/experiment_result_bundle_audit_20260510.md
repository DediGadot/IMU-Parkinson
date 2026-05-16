# Experiment Result Bundle Audit - 2026-05-10

This verifies completed-experiment artifact bundles. It is not a model result.

- Passed: `True`
- Decision: `experiment_result_bundle_passed`
- Hard failures: `0`

## Checks

- `True` complete bundle validates
- `True` missing result artifacts are rejected
- `True` stale preregistration evidence is rejected
- `True` ledger hashes are available for completed bundle artifacts
- `True` feature manifest content evidence is required
- `True` feature manifest malformed fields and protected payloads fail closed
- `True` feature manifest loader errors fail closed
- `True` prediction artifact content evidence is required
- `True` prediction artifact loader errors fail closed
- `True` metric artifact evidence is bound to OOF predictions
- `True` metric artifact content evidence is required
- `True` metric artifacts must match recomputed OOF metrics
- `True` metric artifact JSON path syntax errors fail closed
- `True` metric artifact JSON paths reject empty segments
- `True` metric artifact malformed OOF source fails closed
- `True` metric artifact missing OOF source fails closed
- `True` metric artifact unreadable/malformed OOF source fails closed
- `True` metric artifact JSON source loader errors fail closed
- `True` metric artifact malformed/protected payloads fail closed
- `True` OOF and row prediction group sets must match
- `True` malformed prediction artifact content is rejected
- `True` visit-level prediction grouping keys are validated
- `True` missing visit-level grouping columns are rejected
- `True` blank prediction grouping values are rejected
- `True` ragged prediction rows are rejected
- `True` nonnumeric or nonfinite prediction values are rejected
- `True` prediction digests must be hex sha256 values
- `True` out-of-range OOF target values are rejected
- `True` invalid OOF fold values are rejected
- `True` incomplete OOF fold coverage is rejected
- `True` duplicate singleton artifact kinds are rejected
- `True` blank artifact kind or path is rejected
- `True` malformed experiment command/owner/artifact metadata is rejected
- `True` malformed nested experiment contract objects are rejected
- `True` malformed result-bundle nested evidence objects are rejected

## Claim

Completed experiments now have a reusable ExperimentResultBundle that ties ExperimentSpec, observed artifacts, matching preregistration evidence, feature manifest content evidence, parsed OOF/row prediction artifact evidence, and metric artifact evidence together; result bundles reject malformed nested evidence objects and malformed artifact ledgers before downstream checks dereference them; feature manifest evidence rejects malformed manifest fields, missing or invalid manifest source JSON, and row-like or credential-like payload keys; metric artifacts must match metrics recomputed from the required OOF prediction artifact, reject malformed JSON metric paths including empty path segments, reject malformed fields plus row-like or credential-like metric payload keys, and fail closed on missing, unreadable, or malformed OOF prediction sources plus missing or invalid metric JSON sources; prediction evidence now fails closed on missing or unreadable prediction CSV sources and validates pipeline grouping keys, nonblank grouping values, non-ragged CSV rows, unique group counts, matching OOF/row group fingerprints, required columns, numeric finite prediction values, OOF target valid ranges, OOF fold ids and fold coverage, row counts, and hex SHA-256 digests for prediction files; experiment specs also reject malformed command/owner/artifact metadata, malformed nested contract objects, blank artifact declarations, and duplicate required singleton artifact kinds.

Machine-readable report: `results/experiment_result_bundle_audit_20260510.json`

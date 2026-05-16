# Current Truth Registry Audit - 2026-05-10

This verifies the typed current-result registry. It is not a model result.

- Passed: `True`
- Decision: `current_truth_registry_passed`
- Hard failures: `0`

## Checks

- `True` registry has the expected current internal truth entries
- `True` registry preserves canonical vs candidate labels
- `True` registry artifact paths exist and claim specs validate
- `True` registered metric evidence matches source JSON artifacts
- `True` registry rejects malformed command/path/artifact metadata
- `True` registry rejects malformed nested claim objects
- `True` registry artifact root/path observation errors fail closed
- `True` registry values match the current CLAUDE.md truth table

## Claim

Current internal WearGait-PD result claims now have a reusable typed registry that binds canonical/candidate labels, source artifacts, commands, preregistration artifacts, JSON metric paths, and validated supporting-artifact metadata before reporting gates consume them. Malformed nested claim objects fail closed before registry helpers dereference claim fields. Malformed registry roots or artifact observation failures also fail closed as validation errors.

Machine-readable report: `results/current_truth_registry_audit_20260510.json`

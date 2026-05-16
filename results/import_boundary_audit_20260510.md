# Import Boundary Audit - 2026-05-10

New work should import shared core/facade modules instead of importing historical `run_*`, `compose_*`, or `cache_*` scripts. Existing edges in the baseline remain grandfathered as audit archaeology.

- Passed: `True`
- Decision: `import_boundary_guard_passed`
- Baseline: `results/import_boundary_baseline_20260510.json`
- Baseline created this run: `False`
- Baseline edge count: `401`
- Current edge count: `401`
- New edges: `0`
- Removed baseline edges: `0`
- Unauthorized `pd_imu` legacy imports: `0`

## New Edges

None.

## pd_imu Package Boundary

The pd_imu package may only import historical experiment scripts through pd_imu/core/legacy_experiment_api.py. Any other pd_imu -> run/compose/cache edge fails.

No unauthorized package-to-legacy imports.

## Interpretation

A passing result does not mean the current architecture is clean. It means no new cross-script coupling has been introduced beyond the baseline. The baseline documents historical debt while allowing the new layered-facade architecture to be enforced going forward.

Machine-readable report: `results/import_boundary_audit_20260510.json`

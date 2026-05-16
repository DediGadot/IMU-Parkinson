# External Schema Probe Contract Audit - 2026-05-10

This verifies the post-approval read-only schema-probe contract. It is not a model result.

- Passed: `True`
- Decision: `external_schema_probe_contract_passed`
- Hard failures: `0`

## Checks

- `True` schema-probe specs cover all packet-ready external routes
- `True` specs validate for priority external routes
- `True` incomplete pre-access probe cannot preregister
- `True` complete read-only schema probe can unlock preregistration
- `True` probe contract rejects protected dumps or premature modeling
- `True` protected external ExperimentSpec requires clean schema probe
- `True` protected external ExperimentSpec accepts clean schema probe artifact

## Claim

After external access approval, all six packet-ready external routes have typed read-only schema-probe specs; only a clean probe can unlock preregistration, protected row dumps, preregistration, and model runs remain prohibited inside the probe artifact, and protected external ExperimentSpec objects must carry that clean probe evidence before preregistration or run commands validate.

Machine-readable report: `results/external_schema_probe_contract_audit_20260510.json`

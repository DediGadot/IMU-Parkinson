# External Schema-Probe Report Validator Audit - 2026-05-15

This audits a content-free post-approval completed-report validator for the six gated external routes. It is not an approval, schema-probe artifact, model result, or completion marker.

- Passed: `True`
- Decision: `external_schema_probe_report_validator_ready`
- Validator: `scripts/validate_schema_probe_report.py`
- Route count: `6`
- Hard failures: `0`

## Route Results

| Route | Synthetic pass | Low-N fail | Protected fail | Redacted |
|---|---:|---:|---:|---:|
| `ppmi_verily` | `True` | `True` | `True` | `True` |
| `ppp_pd_vme` | `True` | `True` | `True` | `True` |
| `watchpd` | `True` | `True` | `True` | `True` |
| `cns_portugal_lobo` | `True` | `True` | `True` | `True` |
| `hssayeni_mjff` | `True` | `True` | `True` | `True` |
| `icicle_gait` | `True` | `True` | `True` | `True` |

## Checks

- `True` validator script exists
- `True` schema contracts expose six external route specs
- `True` ppmi_verily synthetic completed schema report passes
- `True` ppmi_verily low subject count fails contract
- `True` ppmi_verily protected row-like content fails
- `True` ppmi_verily output redacts report paths and filenames
- `True` ppp_pd_vme synthetic completed schema report passes
- `True` ppp_pd_vme low subject count fails contract
- `True` ppp_pd_vme protected row-like content fails
- `True` ppp_pd_vme output redacts report paths and filenames
- `True` watchpd synthetic completed schema report passes
- `True` watchpd low subject count fails contract
- `True` watchpd protected row-like content fails
- `True` watchpd output redacts report paths and filenames
- `True` cns_portugal_lobo synthetic completed schema report passes
- `True` cns_portugal_lobo low subject count fails contract
- `True` cns_portugal_lobo protected row-like content fails
- `True` cns_portugal_lobo output redacts report paths and filenames
- `True` hssayeni_mjff synthetic completed schema report passes
- `True` hssayeni_mjff low subject count fails contract
- `True` hssayeni_mjff protected row-like content fails
- `True` hssayeni_mjff output redacts report paths and filenames
- `True` icicle_gait synthetic completed schema report passes
- `True` icicle_gait low subject count fails contract
- `True` icicle_gait protected row-like content fails
- `True` icicle_gait output redacts report paths and filenames

## Hard Failures

- None.

## Decision

The generic schema-probe report validator is ready for post-approval local preflight across all six queued routes. It prints only redacted pass/fail evidence and does not unlock modeling.

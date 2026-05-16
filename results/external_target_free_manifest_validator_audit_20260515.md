# External Target-Free Manifest Validator Audit - 2026-05-15

This audits a content-free post-schema/pre-scoring manifest validator for the six gated external routes. It is not an approval, schema-probe artifact, feature manifest artifact, preregistration, model result, or completion marker.

- Passed: `True`
- Decision: `external_target_free_manifest_validator_ready`
- Validator: `scripts/validate_target_free_manifest.py`
- Route count: `6`
- Hard failures: `0`

## Route Results

| Route | Synthetic pass | Label-use fail | Protected fail | Local-path fail | Redacted |
|---|---:|---:|---:|---:|---:|
| `ppmi_verily` | `True` | `True` | `True` | `True` | `True` |
| `ppp_pd_vme` | `True` | `True` | `True` | `True` | `True` |
| `watchpd` | `True` | `True` | `True` | `True` | `True` |
| `cns_portugal_lobo` | `True` | `True` | `True` | `True` | `True` |
| `hssayeni_mjff` | `True` | `True` | `True` | `True` | `True` |
| `icicle_gait` | `True` | `True` | `True` | `True` | `True` |

## Checks

- `True` validator script exists
- `True` schema contracts expose six external route specs
- `True` ppmi_verily synthetic target-free manifest passes
- `True` ppmi_verily label use and target-derived selection fail
- `True` ppmi_verily protected row-like and credential-like payloads fail
- `True` ppmi_verily local path-like values fail
- `True` ppmi_verily output redacts manifest paths, filenames, and secret-like values
- `True` ppp_pd_vme synthetic target-free manifest passes
- `True` ppp_pd_vme label use and target-derived selection fail
- `True` ppp_pd_vme protected row-like and credential-like payloads fail
- `True` ppp_pd_vme local path-like values fail
- `True` ppp_pd_vme output redacts manifest paths, filenames, and secret-like values
- `True` watchpd synthetic target-free manifest passes
- `True` watchpd label use and target-derived selection fail
- `True` watchpd protected row-like and credential-like payloads fail
- `True` watchpd local path-like values fail
- `True` watchpd output redacts manifest paths, filenames, and secret-like values
- `True` cns_portugal_lobo synthetic target-free manifest passes
- `True` cns_portugal_lobo label use and target-derived selection fail
- `True` cns_portugal_lobo protected row-like and credential-like payloads fail
- `True` cns_portugal_lobo local path-like values fail
- `True` cns_portugal_lobo output redacts manifest paths, filenames, and secret-like values
- `True` hssayeni_mjff synthetic target-free manifest passes
- `True` hssayeni_mjff label use and target-derived selection fail
- `True` hssayeni_mjff protected row-like and credential-like payloads fail
- `True` hssayeni_mjff local path-like values fail
- `True` hssayeni_mjff output redacts manifest paths, filenames, and secret-like values
- `True` icicle_gait synthetic target-free manifest passes
- `True` icicle_gait label use and target-derived selection fail
- `True` icicle_gait protected row-like and credential-like payloads fail
- `True` icicle_gait local path-like values fail
- `True` icicle_gait output redacts manifest paths, filenames, and secret-like values

## Hard Failures

- None.

## Decision

The generic target-free manifest validator is ready for post-schema local preflight across all six queued routes. It prints only redacted pass/fail evidence and does not unlock scoring by itself.

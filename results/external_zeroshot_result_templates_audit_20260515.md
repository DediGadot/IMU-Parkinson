# External Zero-Shot Result Templates Audit - 2026-05-15

This audits the generic blank external zero-shot result templates and validator. It is not an approval, schema probe, completed result record, feature manifest, preregistration, model result, or completion marker.

- Passed: `True`
- Decision: `external_zeroshot_result_templates_ready`
- Templates JSON: `results/external_zeroshot_result_templates_20260515.json`
- Templates Markdown: `results/external_zeroshot_result_templates_20260515.md`
- Template directory: `results/external_zeroshot_result_templates_20260515`
- Validator: `scripts/validate_external_zeroshot_result_record.py`
- Route count: `6`
- Hard failures: `0`

## Route Results

| Route | Placeholder fails | Synthetic passes | Internal update fails | Protected fails | Low N fails | Local-path fails | PPMI contract fails |
|---|---:|---:|---:|---:|---:|---:|---:|
| `ppmi_verily` | `True` | `True` | `True` | `True` | `True` | `True` | `True` |
| `ppp_pd_vme` | `True` | `True` | `True` | `True` | `True` | `True` | `True` |
| `watchpd` | `True` | `True` | `True` | `True` | `True` | `True` | `True` |
| `cns_portugal_lobo` | `True` | `True` | `True` | `True` | `True` | `True` | `True` |
| `hssayeni_mjff` | `True` | `True` | `True` | `True` | `True` | `True` | `True` |
| `icicle_gait` | `True` | `True` | `True` | `True` | `True` | `True` | `True` |

## Checks

- `True` writer command succeeds and writes zero-shot result template outputs
- `True` templates cover six schema-probe routes in contract order
- `True` template route rows mirror schema contracts
- `True` blank result templates are post-score gated and not completed records
- `True` every route exposes an ordered post-score reporting workflow sequence
- `True` all templates are unfinished placeholders and synthetic fills pass
- `True` PPMI result template carries route-specific track and formula-gate contract
- `True` template boundary flags are false and external-only
- `True` formula-SHA template audit remains ready
- `True` content boundary blocks completed/protected artifacts
- `True` markdown boundary documents stricter value-scrubbing policy
- `True` template output does not expose private artifacts

## Hard Failures

- None.

# PPMI / Verily Submit-Format Audit - 2026-05-15

This is an access-packet format audit, not a model result, schema probe, or approval record.

- Passed: `True`
- Decision: `ppmi_verily_word_template_ready_to_fill`
- Word template: `results/ppmi_verily_tier3_request_packet_template_20260515.docx`
- Manifest: `results/ppmi_verily_tier3_request_packet_template_20260515.manifest.json`
- Hard failures: `0`

## Checks

| Check | Status | Missing Terms |
|---|---|---|
| `source_exists` | `True` | - |
| `docx_exists` | `True` | - |
| `manifest_exists` | `True` | - |
| `docx_is_zip_package` | `True` | - |
| `manifest_hashes_match` | `True` | - |
| `placeholders_preserved` | `True` | - |
| `protected_data_absent` | `True` | - |
| `official_tier3_terms` | `True` | - |
| `required_packet_fields` | `True` | - |
| `proresults_blueprint_terms` | `True` | - |
| `compute_boundary_terms` | `True` | - |

## Decision

Fill user-side placeholders locally and submit through the PPMI access workflow; do not run protected-data compute before approval.

Machine-readable report: `results/ppmi_verily_submit_format_audit_20260515.json`

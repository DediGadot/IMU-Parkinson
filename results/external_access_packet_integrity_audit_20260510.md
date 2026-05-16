# External Access Packet Integrity Audit - 2026-05-10

This is an operational architecture-readiness audit, not a model result.

- Passed: `True`
- Decision: `external_access_packets_integrity_passed_no_compute`
- Submit-ready routes: `6`
- Compute-ready routes: `0`
- Top priority route: `PPMI / Verily Study Watch`
- Hard failures: `0`

## Sub-Audits

| Audit | Script | Return code |
|---|---|---:|
| `ppmi_verily_packet` | `audit_ppmi_verily_request_packet.py` | `0` |
| `ppmi_verily_submit_format` | `audit_ppmi_verily_submit_format.py` | `0` |
| `ppmi_verily_submission_email` | `audit_ppmi_verily_submission_email_template.py` | `0` |
| `ppmi_verily_submission_email_validator` | `audit_ppmi_verily_submission_email_validator.py` | `0` |
| `ppmi_verily_submission_package_validator` | `audit_ppmi_verily_submission_package_validator.py` | `0` |
| `ppmi_verily_user_fill_checklist` | `audit_ppmi_verily_user_fill_checklist.py` | `0` |
| `ppmi_verily_schema_probe_report_template` | `audit_ppmi_verily_schema_probe_report_template.py` | `0` |
| `ppmi_verily_completed_packet_validator` | `audit_ppmi_verily_completed_packet_validator.py` | `0` |
| `ppmi_verily_submission_bundle` | `audit_ppmi_verily_submission_bundle.py` | `0` |
| `ppp_pd_vme_packet` | `audit_ppp_pd_vme_request_packet.py` | `0` |
| `watchpd_packet` | `audit_watchpd_request_packet.py` | `0` |
| `cns_portugal_packet` | `audit_cns_portugal_request_packet.py` | `0` |
| `hssayeni_mjff_packet` | `audit_hssayeni_mjff_dua_request_packet.py` | `0` |
| `icicle_packet` | `audit_icicle_request_packet.py` | `0` |
| `external_access_readiness` | `audit_external_access_readiness.py` | `0` |
| `access_submission_tracker` | `audit_access_submission_tracker.py` | `0` |
| `external_architecture_route_plan` | `audit_external_architecture_route_plan.py` | `0` |

## Decision

Fill and submit the PPMI / Verily packet through the data-owner workflow; after approval, run a read-only schema probe before any preregistration or model run.

Protected-data probes, downloads, cache extraction, preregistrations using new labels, remote jobs, model runs, and canonical claim updates remain blocked.

Machine-readable report: `results/external_access_packet_integrity_audit_20260510.json`

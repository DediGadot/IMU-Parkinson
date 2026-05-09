# TUM ROCKET/InceptionTime Route Refresh — 2026-05-09

- decision: `document_only_no_scaffold_no_preregistration_no_remote_job`
- status: `document_only_hssayeni_alias_algorithm_dead_no_scaffold`
- consults: Kimi recommended document-only alias; Claude failed low-credit; `glmcode` was unavailable on PATH.

## Route

The Scientific Reports 2025 Donié et al. paper uses a 27-patient subset of the MJFF Levodopa Response Study (`syn20681023`). The public code repository implements ROCKET and InceptionTime workflows for task-level wrist accelerometer symptom classification.

The labels are tremor severity and bradykinesia/dyskinesia presence or absence for task windows, not T1 items 9-14 or total MDS-UPDRS Part III regression. The paper's data availability points back to MJFF/Synapse, and the code README requires Synapse credentials for data download.

## Decision

This is not a new scaffold or algorithm experiment. It is an alias to the existing Hssayeni/MJFF access gate plus already-negative local ROCKET/MultiROCKET and learned time-series fine-tuning branches.

No code clone, access runbook, preregistration, download, scaffold, remote job, or model run is justified for the active T1/T3 CCC objective.

## Sources

- https://www.nature.com/articles/s41598-025-04263-2
- https://pubmed.ncbi.nlm.nih.gov/40450120/
- https://github.com/cedricdonie/tsc-for-wrist-motion-pd-detection
- https://doi.org/10.7303/syn20681023
- `results/external_dataset_route_audit_20260508.json`
- `findings.md`

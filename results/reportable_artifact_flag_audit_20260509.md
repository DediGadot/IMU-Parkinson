# Reportable Artifact Flag Audit - 2026-05-09

Current claim status is defined by the post-audit policy layer, not by archived lockbox booleans alone. Superseded raw flags are retained for reproducibility but must be explicitly overridden.

- Passed: `True`
- Checks: `5`
- Superseded raw flags recorded: `3`
- Hard failures: `0`

## Checks

| Artifact | Current status | Passed | Raw flags |
|---|---|---:|---|
| `t1_iter12_honest_floor` | `canonical_floor` | `True` | is_lockbox_headline=True, is_canonical_update=None |
| `t1_iter34_hybrid_candidate` | `strongest_candidate_caveated_not_canonical_replacement` | `True` | is_lockbox_headline=True, is_canonical_update=True, is_post_publication_replication_target=True, verdict_vs_iter33b='LIFT (frac>0 vs iter33-B ≥ 0.95)' |
| `t1_iter46_etrobust_diagnostic` | `negative_diagnostic_not_canonical` | `True` | verdict.is_lockbox_headline=True, verdict.is_canonical_update=False, verdict.breaks_iter34_ceiling=False, verdict.decision='lockbox_negative_stop_branch' |
| `t3_iter5_historical_target_contaminated` | `historical_target_contaminated_not_current` | `True` | is_lockbox_headline=True, is_canonical_update=None |
| `t3_iter47_validrange_current` | `canonical_audit_truth` | `True` | decision='fixed_battery_target_audit_no_selection', formula_sha256='0107b7297073900785692a0cfee28f44b2abaad8094a9a371a20f12e03efa439' |

## Superseded Raw Flags

- `t1_iter34_hybrid_candidate` has raw `is_canonical_update=True`; current claim value is `False`. Later P2, auxiliary-label/order, and claim-labeling audits demote iter34 to strongest candidate; the archived boolean must not be used as current claim policy.
- `t1_iter46_etrobust_diagnostic` has raw `verdict.is_lockbox_headline=True`; current claim value is `diagnostic_lockbox_only`. The lockbox ran as a diagnostic follow-up, but its own verdict is negative.
- `t3_iter5_historical_target_contaminated` has raw `is_lockbox_headline=True`; current claim value is `historical_only`. Later iter41/iter47 target-construction audits supersede this lockbox.

Machine-readable report: `results/reportable_artifact_flag_audit_20260509.json`

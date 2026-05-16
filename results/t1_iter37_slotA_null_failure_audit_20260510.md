# T1 Iter37 Slot-A Corrected Null Failure Audit - 2026-05-10

This is a failure/guardrail artifact, not a model headline.

- Normal split CCC: `+0.5790`
- Input artifact: `results/t1_iter37_slotA_nulls_corrected_20260510_145355.json`
- Scrambled-label CCC: `-0.0139`
- Canary-feature CCC: `+0.5788`
- Canary max prediction delta: `0.202759`
- Canary mean prediction delta: `0.057397`
- Transductive sanity CCC: `+0.8056`
- Null gate pass: `False`
- Decision: `corrected_null_gate_failed_canary_instability_do_not_screen_or_promote`

## Interpretation

The corrected target-shuffle null is near zero, superseding the earlier flawed target-shuffle interpretation. The route still fails because a test-only canary column changes predictions materially.

Machine-readable report: `results/t1_iter37_slotA_null_failure_audit_20260510.json`

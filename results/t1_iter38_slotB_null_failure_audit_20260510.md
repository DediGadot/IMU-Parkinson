# T1 Iter38 Slot-B Corrected Null Failure Audit - 2026-05-10

This is a failure/guardrail artifact, not a model headline.

- Input artifact: `results/t1_iter38_slotB_nulls_corrected_20260510_145507.json`
- Normal split CCC: `+0.5831`
- Scrambled-label CCC: `-0.0225`
- Canary-feature CCC: `+0.5781`
- Canary max prediction delta: `0.153661`
- Canary mean prediction delta: `0.050815`
- Transductive sanity CCC: `+0.8044`
- Null gate pass: `False`
- Decision: `corrected_null_gate_failed_canary_instability_do_not_screen_or_promote`

## Interpretation

The corrected target-shuffle null is near zero, superseding the earlier flawed target-shuffle interpretation. The route still fails because a test-only canary column changes predictions materially. Slot B is closed before 5-fold screening.

Machine-readable report: `results/t1_iter38_slotB_null_failure_audit_20260510.json`

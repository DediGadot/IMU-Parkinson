# T1 Iter39 Slot-C Null Failure Audit - 2026-05-10

This is a failure/guardrail artifact, not a model headline.

- Input artifact: `results/t1_iter39_slotC_nulls_20260510_144649.json`
- Normal split CCC: `+0.6125`
- Scrambled-label CCC: `-0.1169`
- Canary max prediction delta: `0.405494`
- Canary mean prediction delta: `0.111513`
- Transductive sanity CCC: `+0.8065`
- Null gate pass: `False`
- Decision: `corrected_null_gate_failed_do_not_screen_or_promote`

## Interpretation

The corrected target-shuffle null is outside the near-zero threshold, and adding a test-only canary column changes predictions materially. Slot C is closed before 5-fold screening.

Machine-readable report: `results/t1_iter39_slotC_null_failure_audit_20260510.json`

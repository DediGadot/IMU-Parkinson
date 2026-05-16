# T1 Ceiling-Push Closure Audit - 2026-05-10

This verifies failure/closure artifacts, not a new model headline.

- Passed: `True`
- Decision: `t1_ceiling_push_closed_iter34_holds`
- Screen gate: `delta_mean >= +0.025 and paired-bootstrap frac_above_zero >= 0.95`

## Slots

| Slot | Delta vs iter34 | frac>0 | Gate pass | Screen |
|---|---:|---:|---|---|
| A | `-0.0021` | `0.172` | `False` | `results/screen_t1_iter37_slotA_20260510_142637.json` |
| B | `-0.0002` | `0.498` | `False` | `results/screen_t1_iter38_slotB_20260510_143503.json` |
| C | `-0.0202` | `0.056` | `False` | `results/screen_t1_iter39_slotC_20260510_144445.json` |

## Decision

All executed T1 ceiling-push slots failed the 5-fold screen; no LOOCV promotion; iter34 remains strongest candidate.

Machine-readable report: `results/t1_ceiling_push_closure_audit_20260510.json`

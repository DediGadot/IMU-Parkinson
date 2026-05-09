# CCC Metric Integrity Audit - 2026-05-09

Reportable CCC uses Lin's population-moment concordance formula: 2*cov_pop(y,p)/(var_pop(y)+var_pop(p)+(mean(y)-mean(p))^2). Sample-moment CCC is recorded only as a convention sensitivity.

- Passed: `True`
- Hard failures: `0`
- Warnings: `1`
- Max absolute sample-minus-population shift on headline vectors: `0.00000270`

## Headline Vectors

| ID | Scope | N | Claimed CCC | Population CCC | Sample CCC | Sample - Population | Passed |
|---|---|---:|---:|---:|---:|---:|---|
| t1_iter12_honest_floor | canonical T1 floor | 94 | 0.6550 | 0.65498352 | 0.65498392 | +0.00000040 | `True` |
| t1_iter34_hybrid_candidate | strongest caveated T1 candidate, not canonical replacement | 93 | 0.7366 | 0.73659437 | 0.73659451 | +0.00000015 | `True` |
| t1_iter46_etrobust_diagnostic | diagnostic negative stop branch | 93 | 0.7269 | 0.72688569 | 0.72688688 | +0.00000119 | `True` |
| t3_iter47_validrange_current | current corrected valid-range T3 internal headline | 95 | 0.3784 | 0.37836712 | 0.37836810 | +0.00000098 | `True` |
| t3_iter47_validrange_no_cv_sensitivity | corrected T3 no-cv sensitivity | 95 | 0.3771 | 0.37708497 | 0.37708620 | +0.00000124 | `True` |
| t3_iter47_complete33_current_sensitivity | corrected T3 complete33 sensitivity, not headline | 88 | 0.4281 | 0.42812881 | 0.42812917 | +0.00000036 | `True` |
| t3_iter5_historical_target_contaminated | historical target-contaminated artifact only | 98 | 0.5227 | 0.52271969 | 0.52272239 | +0.00000270 | `True` |

## Implementation Checks

### identity

- Passed: `True`
- Requires exact current implementation match: `True`
- Max abs diff current implementations vs reference: `0.0`
- `population_reference`: `1.0`
- `sample_convention`: `1.0`
- `inductive_lib.ccc`: `1.0`
- `eval_utils.lins_ccc`: `1.0`

### shifted

- Passed: `True`
- Requires exact current implementation match: `True`
- Max abs diff current implementations vs reference: `0.0`
- `population_reference`: `0.714285714286`
- `sample_convention`: `0.769230769231`
- `inductive_lib.ccc`: `0.714285714286`
- `eval_utils.lins_ccc`: `0.714285714286`

### scaled

- Passed: `True`
- Requires exact current implementation match: `True`
- Max abs diff current implementations vs reference: `0.0`
- `population_reference`: `0.588235294118`
- `sample_convention`: `0.629921259843`
- `inductive_lib.ccc`: `0.588235294118`
- `eval_utils.lins_ccc`: `0.588235294118`

### anti_correlated

- Passed: `True`
- Requires exact current implementation match: `True`
- Max abs diff current implementations vs reference: `0.0`
- `population_reference`: `-1.0`
- `sample_convention`: `-1.0`
- `inductive_lib.ccc`: `-1.0`
- `eval_utils.lins_ccc`: `-1.0`

### constant_prediction

- Passed: `True`
- Requires exact current implementation match: `True`
- Max abs diff current implementations vs reference: `0.0`
- `population_reference`: `0.0`
- `sample_convention`: `0.0`
- `inductive_lib.ccc`: `0.0`
- `eval_utils.lins_ccc`: `0.0`

### n2_nonconstant

- Passed: `True`
- Requires exact current implementation match: `False`
- Max abs diff current implementations vs reference: `0.9230769230769231`
- `population_reference`: `0.923076923077`
- `sample_convention`: `0.0`
- `inductive_lib.ccc`: `0.0`
- `eval_utils.lins_ccc`: `0.0`

### nan_inf_masked

- Passed: `True`
- Requires exact current implementation match: `False`
- Max abs diff current implementations vs reference: `0.0`
- `population_reference`: `0.990712074303`
- `sample_convention`: `0.990712074303`
- `inductive_lib.ccc`: `0.990712074303`
- `eval_utils.lins_ccc`: `0.990712074303`

## Warnings

- `degenerate_n2_policy_returns_zero`: Shared helpers intentionally return 0.0 for fewer than three finite pairs; headline vectors are unaffected.

Machine-readable report: `results/ccc_metric_integrity_audit_20260509.json`

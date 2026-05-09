# T3 Iter47 Residual Anatomy

- Created: `2026-05-09T03:06:25+00:00`
- Scope: diagnostic only; no model selection or promotion.
- Cohort: `drop_allmissing_validrange` / `stage2_current` / N=95

## Overall

- CCC: `0.3784`
- MAE: `7.5280`
- Calibration slope pred-on-true: `0.2692`
- Residual correlation with true severity: `-0.7771`
- Prediction SD / target SD: `6.4462` / `9.9133`

## Interpretation

- Tail shrinkage remains the dominant corrected-target failure mode: residuals are strongly negative-correlated with true severity.
- WPD rank ordering is still near-collapsed under the corrected target, matching the broader LOSO transportability warning.
- No single post-hoc IMU feature has a large residual correlation; this supports the current stop rule against another scalar feature-fishing pass.

## Severity Quartiles

- `Q1_low`: n=26, mean_y=13.38, mean_pred=23.41, mean_residual=10.02, MAE=10.32
- `Q2`: n=26, mean_y=22.46, mean_pred=21.94, mean_residual=-0.52, MAE=4.60
- `Q3`: n=19, mean_y=27.74, mean_pred=25.42, mean_residual=-2.32, MAE=3.91
- `Q4_high`: n=24, mean_y=38.17, mean_pred=28.97, mean_residual=-9.20, MAE=10.55

## Site Summary

- `NLS`: n=68, mean_y=26.06, mean_pred=25.63, mean_residual=-0.42, CCC=0.4068
- `WPD`: n=27, mean_y=22.33, mean_pred=22.75, mean_residual=0.42, CCC=0.0515

## Top Global Residual-Feature Correlations

- `fq_R_Wris_dw5`: corr(residual)=-0.290, corr(target)=0.340, corr(prediction)=0.104
- `R_Wrist_ax_dom`: corr(residual)=-0.280, corr(target)=0.324, corr(prediction)=0.093
- `R_LatShank_am_trem_r`: corr(residual)=-0.275, corr(target)=0.296, corr(prediction)=0.057
- `Forehead_ay_se`: corr(residual)=-0.265, corr(target)=0.413, corr(prediction)=0.251
- `Forehead_ay_trem_r`: corr(residual)=-0.262, corr(target)=0.423, corr(prediction)=0.272
- `d_tug_R_Wrist_ax_jerk`: corr(residual)=0.262, corr(target)=-0.260, corr(prediction)=-0.022
- `L_Wrist_ro_kurt`: corr(residual)=0.254, corr(target)=-0.247, corr(prediction)=-0.012
- `Forehead_ay_loco_r`: corr(residual)=0.250, corr(target)=-0.263, corr(prediction)=-0.043

## Guardrail

These feature correlations are global post-hoc diagnostics from saved OOF residuals. They are not fold-local feature selection and must not be used as a headline or lockbox gate.

Machine-readable report: `results/t3_iter47_residual_anatomy_20260509.json`

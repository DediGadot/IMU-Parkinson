# T3 iter51 TLVMC/DeFOG Zero-Shot Preregistration

- Created UTC: `2026-05-09T01:04:08+00:00`
- Formula SHA256: `665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd`
- Git SHA: `b82d6a67c4e775f8e4256c83217d4d149a5f6f24`
- External dataset: TLVMC / DeFOG Parkinson's Freezing of Gait Prediction (10.5281/zenodo.10959560)
- Internal anchor unchanged: CCC `0.3784`, MAE `7.528`, N `95`

## Primary Analysis

- Target: Use only defog_metadata rows with Medication == 'off' and non-missing UPDRSIII_Off after Subject/Visit join.
- Expected primary N: 68 records from 44 subjects.
- Unit: Subject/Visit/Medication. If a future raw-data parse yields multiple files for the same unit, aggregate predictions by median before computing headline metrics.
- Sensor policy: {'AccV': 'vertical', 'AccML': 'mediolateral', 'AccAP': 'anteroposterior'}
- Feature policy: Magnitude-only lower-back accelerometry features shared with WearGait: time-domain and frequency-domain summaries over non-overlapping 5-second windows, then median/IQR aggregation to the subject/visit/medication unit.

## Tracks

- `A_zero_shot_lumbar_acc_magnitude`: WearGait-to-DeFOG zero-shot lower-back transportability; train = WearGait-PD only, LowerBack accelerometer magnitude features; test = DeFOG lower-back accelerometer magnitude features.
- `B_zero_shot_wrist_to_lumbar_stress`: cross-sensor stress test only; expected to underperform Track A; train = WearGait-PD only, right-wrist accelerometer magnitude features; test = DeFOG lower-back accelerometer magnitude features.
- `C_defog_only_loso_sanity`: within-DeFOG feasibility ceiling, not external transportability; train = DeFOG training subjects only; test = held-out DeFOG subjects.

## Interpretation Gates

- Transportability cliff: Track A OFF-state CCC <= 0.10 or bootstrap upper CI <= 0.
- Partial external validity: Track A OFF-state CCC > 0.20 with bootstrap lower CI > 0.
- Unexpected high-signal audit trigger: Track A OFF-state CCC > 0.38 must be treated as a leakage/grouping/unit audit trigger before any narrative use.
- No internal canonical change: `True`

# Ablation V3 Regeneration Probe - 2026-05-09

This is a non-destructive regeneration/provenance probe. It does not promote
`results/ablation_v3_features.csv` to cache-manifest-clean headline use.

## Summary

- Status: `blocked_missing_regeneration_inputs`
- Frozen cache SHA before: `b405d90a6a35808d556d726b58bf7d9361d26e020a79091e52c868ee98f9c2b4`
- Frozen cache SHA after: `b405d90a6a35808d556d726b58bf7d9361d26e020a79091e52c868ee98f9c2b4`
- Frozen cache unchanged: `True`
- Regenerated cache: `None`
- Regenerated SHA: `None`
- Same shape: `None`
- Same column order: `None`
- Same SID order: `None`
- Max abs numeric diff: `None`
- Changed numeric columns >1e-9: `None`

## Promotion Decision

No regenerated cache was written. The current remote lacks the full WearGait raw-data inputs needed to reproduce the frozen 178-subject cache. Do not synthesize a clean manifest or promote the historical cache; keep using the existing provenance caveats until the full raw data are restored and a non-destructive regeneration succeeds.

## Guardrail Rationale

- The regenerated cache still contains `cv_*` clinical/intake columns.
- The regenerated cache still contains `dst_*` walkway-distiller columns from a once-trained historical dev-split distiller.
- `updrs3`, `hy`, and `obs_subscore` are present for compatibility and must not be treated as deployable IMU features.
- A hash/schema match is reproducibility evidence only; it is not a fold-locality proof.

Machine-readable report: `results/ablation_v3_regeneration_probe_20260509.json`

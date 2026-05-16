# PPMI / Verily Zero-Shot Blueprint Audit - 2026-05-15

This audit validates a content-free route blueprint. It is not a model result, schema probe, access approval, or preregistration.

- Passed: `True`
- Decision: `ppmi_verily_zeroshot_blueprint_ready`
- Hard failures: `0`
- Blueprint SHA256: `4540fbc00a3bb92b6bedca34e954bb0e8ae00cbee30ee6f9651c56229591e13f`

## Checks

| Check | Passed |
|---|---:|
| writer runs and writes blueprint | `True` |
| blueprint is content-free and not a completion marker | `True` |
| blueprint is anchored to exact pro-results prompt and rank4 directive | `True` |
| source trace records X4 as current failed T1 near-miss | `True` |
| current T1 references use X4 near-miss with iter34 baseline | `True` |
| route and access prerequisites are explicit | `True` |
| rank4 topology-first analysis order is locked | `True` |
| schema requirements cover linkage, labels, wrist sensor, and minimum N | `True` |
| X4 sensor boundary excludes 13-sensor GSP from wrist-only PPMI formula | `True` |
| Track A is WearGait-trained wrist TopoFractal zero-shot | `True` |
| Track B is canonical comparator plus wrist branch | `True` |
| Track C preserves fixed K250 GradientBoostingRegressor branch for T3 only | `True` |
| Track D is blocked until zero-shot evidence and fresh formula preregistration | `True` |
| no-search and claim-boundary rules are explicit | `True` |
| manifest and reporting gates are explicit | `True` |
| aggregate result-record preflight is explicit before reporting | `True` |

Machine-readable report: `results/ppmi_verily_zeroshot_blueprint_audit_20260515.json`

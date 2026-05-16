# README Claim Routing Audit - 2026-05-09

README.md must route readers to current post-audit T1/T3 claims and may mention old SSL/XGBRanker numbers only when locally guarded as legacy/retracted/pre-audit or target-contaminated.

- Passed: `True`
- Decision: `readme_current_claim_route_guard_passed`
- Unguarded stale hits: `0`
- Missing required snippets: `0`
- Bad current-route hits: `0`

## Required Current README Claims

- `Current Post-Audit WearGait-PD Benchmark`: present
- `T1 canonical floor`: present
- `0.6550`: present
- `T1 corrected candidate`: present
- `0.7170`: present
- `N=92`: present
- `T3 current`: present
- `0.3784`: present
- `0.150`: present
- `run_t3_iter47_invalid_code_fix.py`: present
- `render_current_paper.py`: present
- `CURRENT_PAPER.html`: present
- `legacy/retracted/pre-audit`: present
- `0.868`: present
- `0.776`: present
- `target-contaminated`: present

## Dangerous Hits

- `5` `0\.868` guarded: The old XGBRanker/healthy-control-anchor results, including T1 CCC `0.868` and T3 CCC `0.776`, are legacy/retracted/pre-audit archaeology. They were target-contaminated because the ranking representation was trained with all subjects before the reported LOOCV evaluation. Do not cite them as deployable or current results.
- `5` `0\.776` guarded: The old XGBRanker/healthy-control-anchor results, including T1 CCC `0.868` and T3 CCC `0.776`, are legacy/retracted/pre-audit archaeology. They were target-contaminated because the ranking representation was trained with all subjects before the reported LOOCV evaluation. Do not cite them as deployable or current results.
- `5` `\bXGBRanker\b` guarded: The old XGBRanker/healthy-control-anchor results, including T1 CCC `0.868` and T3 CCC `0.776`, are legacy/retracted/pre-audit archaeology. They were target-contaminated because the ranking representation was trained with all subjects before the reported LOOCV evaluation. Do not cite them as deployable or current results.
- `59` `\bSSL ranking\b` guarded: ├── run_compression_ablation.py             # Historical pre-audit SSL ranking reproduction only
- `162` `\bXGBRanker\b` guarded: - Do not use global XGBRanker ranks or leaf features for an inductive/deployment claim; that route is invalid/target-contaminated for current claims.
- `170` `\bSSL ranking\b` guarded: ### Historical SSL Ranking Pipeline
- `172` `\bXGBRanker\b` guarded: The old two-stage semi-supervised learning (SSL) ranking pipeline trained an XGBRanker on all 178 subjects, including healthy controls and the held-out PD subject's rank label, then used the leaf features in a PD-only LOOCV LightGBM regressor. That transductive Stage 1 was later judged target-contaminated for deployment-style claims.
- `178` `0\.868` guarded: | T1 direct observable | `0.868` | target-contaminated SSL/ranking route; superseded by T1 iter12 `0.6550` canonical floor and iter34 `0.7366` candidate |
- `179` `0\.852` guarded: | T2 broad observable | `0.852` | target-contaminated SSL/ranking route |
- `180` `0\.776` guarded: | T3 total UPDRS-III | `0.776` | target-contaminated SSL/ranking route; superseded by corrected T3 iter47 `0.3784` |
- `189` `\bSSL ranking\b` guarded: ./gpu.sh run_compression_ablation.py --phase 5   # historical P5 SSL ranking, not current evidence
- `189` `P5 SSL Ranking` guarded: ./gpu.sh run_compression_ablation.py --phase 5   # historical P5 SSL ranking, not current evidence
- `196` `0\.868` guarded: Rows such as "This work (T3, SSL)" with CCC `0.776`, "This work (T1, SSL)" with CCC `0.868`, and T1 MAE `0.986` are legacy/retracted/pre-audit claims. They should appear only with local context saying historical, target-contaminated, not current, or do not cite.
- `196` `0\.776` guarded: Rows such as "This work (T3, SSL)" with CCC `0.776`, "This work (T1, SSL)" with CCC `0.868`, and T1 MAE `0.986` are legacy/retracted/pre-audit claims. They should appear only with local context saying historical, target-contaminated, not current, or do not cite.
- `196` `This work \(T3, SSL\)` guarded: Rows such as "This work (T3, SSL)" with CCC `0.776`, "This work (T1, SSL)" with CCC `0.868`, and T1 MAE `0.986` are legacy/retracted/pre-audit claims. They should appear only with local context saying historical, target-contaminated, not current, or do not cite.
- `196` `This work \(T1, SSL\)` guarded: Rows such as "This work (T3, SSL)" with CCC `0.776`, "This work (T1, SSL)" with CCC `0.868`, and T1 MAE `0.986` are legacy/retracted/pre-audit claims. They should appear only with local context saying historical, target-contaminated, not current, or do not cite.

Machine-readable report: `results/readme_claim_routing_audit_20260509.json`

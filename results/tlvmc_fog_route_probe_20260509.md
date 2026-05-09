# TLVMC / DeFOG Route Probe

- Created: `2026-05-09T00:52:48+00:00`
- Zenodo DOI: `10.5281/zenodo.10959560`
- License: `cc-by-4.0`
- Row-level metadata persisted in repo: `False`

## T3 Eligibility

- Direct T3 eligible: `True`
- Reason: Public metadata includes Subject/Visit rows with UPDRSIII_On and UPDRSIII_Off totals. DeFOG recording metadata links sensor file ids to Subject/Visit plus medication state, yielding medication-matched UPDRS-III targets for all 137 DeFOG recordings. Daily metadata also joins to visit-level UPDRS-III targets but lacks medication state. tdcsfog metadata does not join to subjects.csv targets in this public metadata probe and is not counted as a direct T3 target route.
- Next step: Write a separate zero-shot external-validation preregistration/probe before any model run; do not use this as another WearGait internal variant screen.

## Metadata Counts

- `subjects.csv`: 173 rows, 136 unique subjects, 173 rows with an UPDRS-III target.
- `UPDRSIII_On`: N=172, range 5.0-79.0.
- `UPDRSIII_Off`: N=132, range 15.0-91.0.
- `defog_metadata.csv`: 137 recordings, 45 subjects, 70 subject-visits, 137 medication-matched targets.
- `daily_metadata.csv`: 65 recordings, 65 visit-level targets, no medication-state column.
- `tdcsfog_metadata.csv`: 833 recordings, 0 joined UPDRS-III targets in this probe.
- Raw DeFOG sample `train/defog/02ea782681.csv`: 162907 rows, columns `Time, AccV, AccML, AccAP, StartHesitation, Turn, Walking, Valid, Task`.

## Sources

- Zenodo record: https://zenodo.org/records/10959560
- Kaggle competition: https://www.kaggle.com/competitions/tlvmc-parkinsons-freezing-gait-prediction
- Nature Communications article: https://www.nature.com/articles/s41467-024-49027-0

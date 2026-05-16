# External Dataset Route Audit — 2026-05-08

Purpose: determine whether any newly surfaced public external dataset can directly advance the active objective: break WearGait-PD T1/T3 CCC under the repo's strict leakage rules.

## Eligibility Rule

A dataset is directly eligible for a T1/T3 ceiling-breaking experiment only if it has:

- subject-level Parkinson cohort data;
- wearable IMU or a modality that can be aligned to the WearGait-PD feature space without changing the prediction target;
- clinical labels that can support either T1 items 9-14 or total MDS-UPDRS Part III;
- public or already-approved access;
- enough metadata to run strict subject-level splits without label leakage.

## Findings

| Dataset / route | Access status on 2026-05-08 | Clinical label | Modality | Directly eligible for T1/T3 CCC? | Verdict |
|---|---|---|---|---|---|
| CARE-PD | Public via project page, GitHub, Hugging Face, and Dataverse links | `UPDRS_GAIT` only in the released data structure | Harmonized SMPL 3D gait meshes from RGB / MoCap | No | Useful SOTA comparator and future gait-score benchmark, but not a WearGait-PD T1/T3 ceiling-break route |
| FoG-STAR | Public on Zenodo, CC-BY 4.0 | `updrs_iii` total MDS-UPDRS Part III | IMUs on ankles, back, wrist | Yes for small-N T3 external probes | Direct public route; iter38 Stage-1 augmentation failed, iter39 zero-shot shows partial clinical+IMU external validity only |
| COPS | Public on OSF `5xvwn` | UPDRS-III OFF/ON total and item CSVs | Bilateral wrist GENEActiv accelerometry, 100 Hz, free-living | Yes for T3 external zero-shot | Direct public route; iter49 zero-shot complete: wrist-only null, clinical+wrist partial |
| TLVMC / DeFOG Parkinson's Freezing of Gait Prediction | Public via Kaggle competition files and Zenodo archived dataset | `UPDRSIII_On`, `UPDRSIII_Off`, and `NFOGQ` in `subjects.csv`; DeFOG metadata joins recordings to `Subject`/`Visit`/`Medication` | Lower-back/trunk accelerometry (`AccV`, `AccML`, `AccAP`) during structured FoG tasks plus daily free-living recordings | Yes for external T3 zero-shot only | Iter51 zero-shot complete: Track A lower-back magnitude OFF CCC `+0.2695`; partial external validity only, no internal T3 canonical update |
| PDFE turning-in-place | Public on Figshare `14984667`, CC-BY 4.0 | Session-level UPDRS-III total in `PDFEinfo.csv` | Shank IMU acceleration/gyroscope during turning-in-place | Yes for external T3 zero-shot only | Iter52 zero-shot complete: Track A WearGait shank transfer negative, clinical+shank weak/uncertain, PDFE-only sanity positive; no internal T3 canonical update |
| Public overground walking full-body biomechanics | Public on Figshare `14896881`, CC-BY 4.0 | ON/OFF UPDRS-III totals/items in `PDGinfo.xlsx` | 3D motion capture and force plates during overground walking, not wearable IMU | No | Document-only gait-biomechanics context; target exists but modality is not WearGait-aligned IMU |
| ALAMEDA Parkinson's Disease Accelerometer Dataset | Public on Zenodo | MDS-UPDRS III annotations, but N=11 PD | Wrist-worn GENEActiv raw accelerometer Parquet over longitudinal monitoring periods | Technically yes for tiny T3 external probes | Skipped: underpowered and low-value after COPS/FoG-STAR/PADS; no iter50 prereg/download |
| Comprehensive Multi-Modal Dataset for Parkinson's Disease Prediction | Public on Zenodo | UPDRS part totals in a derived clinical/gait table; no raw item-level Part III subitems | CSF protein/peptide features plus scalar gait summaries (`gait_time`, `gait_steps`, `freezing`), not raw wearable IMU | No | Derived benchmark table mixing Kaggle AMP and a Mendeley gait repository; no trustworthy raw wearable-to-UPDRS subject alignment; no prereg/download |
| Monipar | Public on Zenodo, CC-BY 4.0 | Exercise-level MDS-UPDRS subitem labels for the supervised group only; no confirmed total Part III | Single consumer-smartwatch triaxial accelerometer at 50 Hz during eight structured exercises | No | Public subitem-only route; 6 supervised PD subjects / 46 labeled trials, no full T1 items 9-14 composite, no T3 total; no prereg/download |
| BIOCLITE | Public on Zenodo, CC-BY 4.0 | Per-exercise MDS-UPDRS 0-4 scores when a clinical evaluation is available; no total Part III endpoint | Single consumer-smartwatch triaxial accelerometer + gyroscope at 50 Hz across supervised/unsupervised exercise sessions | No | Public Monipar follow-up; useful related work for exercise-level subitems, but not a T1/T3 CCC route; no prereg/download |
| mPower | Synapse DUA plus MDS-UPDRS copyright/permission friction | Self-reported subset of MDS-UPDRS patient-questionnaire items, not clinician-rated Part III total | iPhone handheld/pocket accelerometer/gyroscope tasks | No | Large cohort but not a direct T1/T3 CCC route; skip prereg/download |
| Papadopoulos phone-call tremor | Public on Zenodo, CC-BY 4.0 | Tremor-related item labels only: UPDRS II item 16 and Part III item 20/21 left/right hand tremor for the clinically examined group | Smartphone embedded IMU during phone calls, in-the-wild | No | Useful tremor-subitem context, but not total UPDRS-III/T1 and not a gait/balance WearGait feature-space route; no prereg/download |
| Harmonized Upper/Lower Limb Accelerometry | Controlled-access NICHD DASH Part1/Part2; code public on GitHub/Zenodo | Demographic/clinical survey fields; no confirmed total MDS-UPDRS Part III or T1 items 9-14 | Daily-life ActiGraph upper/lower-limb recordings and processed summary variables | No | Useful rehab accelerometry resource, but target/modality mismatch for WearGait-PD T1/T3 CCC; no prereg/download |
| REMAP Bristol | Controlled data application required for accelerometry and individual clinical ranges | Motor MDS-UPDRS / Part III values released as ranges plus STS/turn labels | Open coarsened skeleton; controlled bilateral wrist accelerometry | No for current CCC objective | N=12 PD and controlled/range-label target; skip after stronger COPS/FoG-STAR evidence |
| Oxford OPDC / OxQUIP wearable progression lead | OPDC requires DPUK application; OxQUIP wearable study data not public | MDS-UPDRS III in OxQUIP paper; OPDC catalogue has clinical variables but no confirmed public aligned IMU files | OxQUIP six APDM IMUs; OPDC is primarily clinical/genetic/imaging metadata | No | No public aligned sensor route; do not preregister |
| PD-BioStampRC21 | Open via IEEE DataPort DOI; Kaggle mirrors exist | MDS-UPDRS assessment annotations and demographic/clinical assessment data; published analysis emphasizes Part III and rest-tremor items | BioStampRC sensors on chest, thighs, and forearms, not wrists | No for current WearGait wrist route | N=17 PD and wrong sensor geometry; not a CCC breaker |
| MJFF Levodopa Response / Hssayeni (`syn20681023`) | Project metadata visible; child data still Synapse DUA/READ-gated | MDS-UPDRS / symptom labels | Wearable sensors on wrist, waist, forearm, shank, back | Yes, if DUA is approved | Larger direct external wearable UPDRS-III path; still blocked |
| PPMI / Verily Study Watch | PPMI qualified-researcher DUA/application required; no local credentials configured | MDS-UPDRS Part III and H&Y in PPMI clinical data; npj 2025 uses MDS-UPDRS within 90 days of wearable data | Verily Study Watch wrist accelerometer, 100 Hz, free-living longitudinal monitoring | Yes, if PPMI access is approved | Priority access-gated route; document and wait for user DUA/account action before scaffold |
| Personalized Parkinson Project / PD Virtual Motor Exam | RDSRC request-gated; no local access or schema; data release fees may apply | MDS-UPDRS Part III at clinic visits and consensus subitem ratings for PD-VME validation subsets | Verily Study Watch wrist sensors during passive monitoring and active motor tasks | Yes, if RDSRC access is approved | Strong gated Verily-watch peer to PPMI, but access/schema-gated; no scaffold before approval |
| WATCH-PD | C-Path 3DT Stage 2 membership or WATCH-PD Steering Committee proposal required; no local files/schema; C-Path Integrated Parkinson's Database excludes DHT data | MDS-UPDRS Parts I-III; APDM sensors worn during MDS-UPDRS Part III; mean PD Part III 24.1 | Apple Watch, iPhone BrainBaseline, and APDM Opal inertial sensors during in-clinic MDS-UPDRS Part III plus at-home assessments | Yes, if access is approved | Protocol-relevant wrist/APDM T3 route, but request-gated/document-only; no scaffold before access and row-level schema |
| Advanced PD smartwatch home monitoring / Fay-Karmon 2024 | Author request only; no local files/schema | MDS-UPDRS Part II and Part III in ON/OFF states plus Part IV, daily motor-task labels, diaries | Intel Pharma Analytics Platform smartwatch + iPhone/app; proprietary SWA algorithm outputs | No for current objective; possible external T3 only after access/schema | Request-only N=21 advanced-PD route; proprietary/schema-hidden and below stronger already-tested external rows; no scaffold/prereg/download |
| Marital-dyad social actigraphy / Sensors 2023 | Author request only; no local files/schema | Clinician MDS-UPDRS Part III total for the PD participant | Non-dominant wrist GeneActiv, 100 Hz, seven-day daily-life actigraphy in PD/spouse dyads | No for current objective; possible external T3 only after access/schema | Request-only N=27 PD daily-life/social-actigraphy route; not a structured gait/balance protocol and no T1 endpoint; no scaffold/prereg/download |
| ICICLE-PD / ICICLE-GAIT | Request-gated via Newcastle / data available on request; no local agreement or files | MDS-UPDRS Part III and Hoehn & Yahr at clinical visits | Lower-back Axivity AX3 triaxial accelerometer, 100 Hz, +/-8g, 7-day free-living gait at longitudinal visits | Yes, if access is approved | Direct longitudinal external T3 route, but document-only until access; no scaffold before schema is visible |
| Mobilise-D TVS / CVS | TVS public on Zenodo; CVS row-level public wearable/clinical release or schema not found | TVS includes demographic/clinical variables but is explicitly for algorithm validation; CVS reports MDS-UPDRS in a 600+ PD longitudinal cohort | TVS/CVS lower-back wearable monitoring, with some TVS wrist recordings | No for current public TVS; possible future CVS route if access/release exists | Skip TVS for UPDRS-III regression; watch/request CVS only, no scaffold before row-level wearable plus MDS-UPDRS schema |
| CNS Portugal / Lobo IS2022 AX3 gait | Request-gated through authors/CNS; related CNS Sensors 2022 article states raw data available from authors on request | MDS-UPDRS Part III total; H&Y 2-4 | Axivity AX3 wrist + lower back, 100 Hz, structured 10-meter walk protocol | Yes, if access is approved | Direct T3 external route; document-only, no scaffold until files/schema confirmed |
| PADS | Public and already evaluated | Diagnosis / cohort class, not UPDRS-III | Wrist smartwatch IMU | No for T1/T3 regression | Already used for zero-shot transportability; no CCC target |
| Luxembourg upper-limb subitem study | Paper public; datasets request-only under national/institutional rules | MDS-UPDRS III upper-limb subitems; no total Part III endpoint | Two compact hand IMUs during elicited upper-limb tasks | No | Document-only observability context for items 4/5/6; request-only, ON-medication, subitem-only, and not a T3/full-T1 route; no runbook/scaffold/preregistration |
| Pre-QuantiPark / ActiMyo levodopa-challenge pilot | Paper public; data request-gated for academic non-commercial proposal review and data access agreement | Repeated MDS-UPDRS Part III total during 90-minute levodopa challenge; no visible T1 items 9-14 endpoint | ActiMyo wrist + ankle magneto-inertial sensors, 130.69 Hz, controlled levodopa-challenge setting | No for current objective; possible external T3 only after access/schema | Document-only levodopa-challenge context; request-only, N=10, within-subject trajectory rather than stable cross-sectional severity, and too small for a lockbox; no runbook/scaffold/preregistration |
| TUM Donié ROCKET/InceptionTime wrist symptom classification | Paper and code public; underlying data are MJFF/Hssayeni `syn20681023` and remain Synapse DUA-gated | Task-level tremor severity plus bradykinesia/dyskinesia presence labels; not total Part III and not T1 items 9-14 | GENEActiv wrist accelerometer on most affected limb, 50 Hz, predefined motor tasks | No | Document-only alias to existing Hssayeni/MJFF gate plus already-negative local ROCKET/MultiROCKET and learned time-series fine-tuning branches; no clone/scaffold/preregistration |
| ParaDigMa PD digital biomarker toolbox | Public GitHub/JOSS 2026/Zenodo; Apache-2.0 | No cohort or clinical labels; feature-extraction software only | Wrist accelerometer, gyroscope, PPG during daily-life passive monitoring | No | Open validated toolbox, not a labeled cohort; applying it to WearGait would be a local scalar feature addition, explicitly dead at N=94; no prereg/download/scaffold |
| Yin et al Frontiers Neurology 2025 gait-parameter regression | Paper public; raw data available from corresponding author on request | Total MDS-UPDRS III, tremor part score, non-tremor part score in OFF/ON states | Plantar angles, stride length, foot clearance, velocity, cadence — likely motion-capture or instrumented-walkway derived, not raw wearable IMU | No | Request-only N=20 PD; underpowered versus already-tested routes; no public schema; no scaffold/runbook/preregistration |

## Source Evidence

CARE-PD:

- Project page says CARE-PD is a multi-site anonymized clinical gait dataset, supports supervised clinical score prediction, and links the dataset and code: https://neurips2025.care-pd.ca/
- GitHub README says recordings are converted to anonymized SMPL body gait meshes and the supervised task estimates UPDRS gait scores: https://github.com/TaatiTeam/CARE-PD
- Hugging Face card states the data structure has `UPDRS_GAIT` and lists 9 harmonized datasets. Total file size is about 2.24 GB on the dataset card / about 1.12 GB in the file tree due to storage representation: https://huggingface.co/datasets/vida-adl/CARE-PD
- arXiv abstract states CARE-PD estimates UPDRS gait scores and evaluates within/cross/LODO protocols: https://arxiv.org/abs/2510.04312

FoG-STAR:

- Scientific Data abstract states FoG-STAR contains 22 PD participants wearing four IMUs on ankles, wrist, and lower back, each with tri-axial accelerometer and gyroscope data: https://www.nature.com/articles/s41597-026-06645-1
- The same article states the clinical file includes `updrs_iii` MDS-UPDRS Part III: https://www.nature.com/articles/s41597-026-06645-1
- Zenodo record `17838806` is public, CC-BY 4.0, and exposes `sensor_data.csv` plus `clinical_data.csv` with `updrs_iii`: https://zenodo.org/records/17838806
- Local route probe and screen artifacts: `results/iter38_fogstar_probe_20260508_112546.json`, `results/iter38_fogstar_stage1_screen_20260508_142623.json`.
- Pre-registered zero-shot external-validation artifacts: `results/preregistration_t3_iter39_fogstar_zeroshot_20260508_143717.json`, `results/iter39_fogstar_zeroshot_20260508_143717.json`, `results/iter39_fogstar_zeroshot.html`.

COPS:

- Scientific Data article describes COPS as continuous observation of Parkinsonian symptoms with bilateral wrist GENEActiv accelerometers and clinical/symptom annotations: https://www.nature.com/articles/s41597-026-06999-6
- OSF node `5xvwn` exposes `Demographics.csv`, a `Data` folder with subject ZIP archives, symptom diaries, and scripts: https://osf.io/5xvwn/
- Local artifacts: `run_t3_iter49_cops.py`, `results/preregistration_t3_iter49_cops.json`, `results/iter49_cops_probe.json`, `results/iter49_cops_download_manifest.json`, `results/iter49_cops_features_full.csv`, `results/iter49_cops_zeroshot_20260508_185226.json`, stable `results/iter49_cops_zeroshot.json`.
- Probe/download result: 66 OSF subject-ZIP records totaling 47.89 GB, 64 unique local ZIP filenames because `COPS-54.zip` appears three times, demographics N=66, feature cache N=64, OFF-label N=62.
- Primary OFF zero-shot result: Track A right-wrist magnitude-only CCC `-0.0193` (CI `[-0.1030,+0.0704]`), Track B right clinical+wrist CCC `+0.2412` (CI `[+0.1061,+0.3916]`), Track D bilateral clinical+wrist CCC `+0.2535`, Track C COPS-only LOOCV sanity CCC `+0.3100`.

TLVMC / DeFOG Parkinson's Freezing of Gait Prediction:

- Zenodo record `10959560` is public under CC-BY 4.0 and archives `Source_Data.zip`, `Competition Dataset.zip`, and `Competition Code.zip` for the Nature Communications TLVMC FoG competition paper: https://zenodo.org/records/10959560
- Kaggle competition metadata exposes `subjects.csv`, `defog_metadata.csv`, `tdcsfog_metadata.csv`, `daily_metadata.csv`, and `tasks.csv`: https://www.kaggle.com/competitions/tlvmc-parkinsons-freezing-gait-prediction
- Local route probe artifact `results/tlvmc_fog_route_probe_20260509.json` downloaded only small metadata to `/tmp` and persisted aggregate counts. It confirms `subjects.csv` has 173 subject-visit rows, 136 unique subjects, 172 `UPDRSIII_On` targets, 132 `UPDRSIII_Off` targets, and 173 rows with at least one UPDRS-III target.
- DeFOG is the clean target-joined subset: `defog_metadata.csv` has 137 recordings, 45 subjects, 70 subject-visits, and 137 medication-matched UPDRS-III targets. The medication split is 68 OFF records from 44 subjects and 69 ON records from 45 subjects. `daily_metadata.csv` has 65 visit-level targets but no medication-state column. `tdcsfog_metadata.csv` has 833 recordings but 0 joined UPDRS-III targets in this public metadata probe.
- A single raw DeFOG sample file (`train/defog/02ea782681.csv`) has 162,907 rows and columns `Time`, `AccV`, `AccML`, `AccAP`, `StartHesitation`, `Turn`, `Walking`, `Valid`, and `Task`; this is enough to freeze the raw-axis/schema boundary in a future preregistration.
- Iter51 preregistration artifacts: `scripts/write_tlvmc_defog_prereg.py`, stable `results/preregistration_t3_iter51_tlvmc_defog_zeroshot.json`, timestamped `results/preregistration_t3_iter51_tlvmc_defog_zeroshot_20260509_010408.json`, and summary `results/preregistration_t3_iter51_tlvmc_defog_zeroshot.md`.
- Iter51 formula SHA256: `665479765911e8192e4db570babeb5fcef3e2b6553dfd6259187f76685ec08cd`. Primary Track A is WearGait lower-back accelerometer magnitude features zero-shot to DeFOG lower-back OFF-state UPDRSIII_Off; ON, pooled medication-matched, and subject-visit mean-state metrics are sensitivities only.
- Iter51 full-run artifacts: `run_t3_iter51_tlvmc_defog.py`, `results/iter51_tlvmc_defog_download_manifest.json`, `results/iter51_tlvmc_defog_features.csv`, `results/iter51_tlvmc_defog_features.csv.manifest.json`, `results/iter51_tlvmc_defog_zeroshot_20260509_013357.json`, stable `results/iter51_tlvmc_defog_zeroshot.json`, and `results/iter51_tlvmc_defog_zeroshot_rows_20260509_013357.csv`.
- Iter51 result: 136 modeled DeFOG rows across 45 subjects, 68 OFF primary rows, 68 ON sensitivity rows, and 54 common magnitude features. Track A lower-back magnitude zero-shot CCC `+0.2695` (95% CI `[+0.1693,+0.3600]`, MAE `8.07`, Pearson r `0.5635`); Track B wrist-to-lumbar stress CCC `+0.0485`; Track C DeFOG-only subject-grouped LOSO sanity CCC `+0.3450`. ON Track A sensitivity CCC `+0.0548`, pooled medication-matched Track A CCC `+0.1660`, subject-visit mean-state Track A CCC `+0.1731`. Nulls stayed low: target-shuffle Track A CCC `+0.0404`, scrambled-label Track C CCC `+0.1206`; transductive DeFOG diagnostic CCC `+0.5969`.
- Decision: public direct external T3 route, but not an internal WearGait-PD ceiling-break screen. Iter51 is partial external-validity evidence only, with no internal canonical T3 update allowed under any outcome.

PDFE turning-in-place:

- Figshare article `14984667` is public CC-BY 4.0 and exposes `PDFEinfo.csv` plus `IMU.zip`: https://api.figshare.com/v2/articles/14984667
- Frontiers paper describes the PDFE turning-in-place dataset as video, acceleration, angular velocity, and clinical scales in individuals with Parkinson's disease during turning-in-place: https://www.frontiersin.org/articles/10.3389/fnins.2022.832463/full
- Direct metadata inspection found `PDFEinfo.csv` has 41 rows, 35 session-1 UPDRS-III targets, 23 session-2 targets, and 13 session-3 targets. The IMU text files have columns `Frame #`, `Time [s]`, `ACC ML [g]`, `ACC AP [g]`, `ACC SI [g]`, `GYR ML [deg/s]`, `GYR AP [deg/s]`, `GYR SI [deg/s]`, and `Freezing event [flag]`.
- Iter52 preregistration artifacts: `results/preregistration_t3_iter52_pdfe_turning_zeroshot.json` and `.md`; formula SHA256 `f0eb5985a15b271a333b3d9e1d093e32889814a0f48d0ca4f5131b9674c7b2f2`.
- Iter52 full-run artifacts: `run_t3_iter52_pdfe_turning.py`, `results/iter52_pdfe_turning_probe.json`, `results/iter52_pdfe_turning_download_manifest.json`, `results/iter52_pdfe_turning_features.csv`, `results/iter52_pdfe_turning_features.csv.manifest.json`, stable `results/iter52_pdfe_turning_zeroshot.json`, `results/iter52_pdfe_turning_zeroshot_20260509_092223.json`, and `results/iter52_pdfe_turning_zeroshot_rows_20260509_092223.csv`.
- Iter52 result: 95 WearGait valid-range T3 train subjects, 35 PDFE external subjects, and 54 common shank magnitude features. Track A WearGait shank-to-PDFE CCC `-0.1008` (95% CI `[-0.2877,+0.0554]`, MAE `14.15`); Track B clinical+shank CCC `+0.1340` (CI `[-0.0426,+0.3369]`, MAE `12.59`); Track C PDFE-only LOOCV sanity CCC `+0.4020` (CI `[+0.1569,+0.6519]`, MAE `10.28`).
- Decision: public direct external T3 route, but transfer is negative/weak and protocol-specific. Iter52 is external-validity evidence only, with no internal WearGait-PD T3 canonical update allowed.

Public overground walking full-body biomechanics:

- Figshare article `14896881` is public CC-BY 4.0 and exposes `C3Dfiles.zip`, `Gait cycles.zip`, `PDGinfo.xlsx`, and supplementary material: https://api.figshare.com/v2/articles/14896881
- The dataset paper describes overground walking full-body kinematics and kinetics in individuals with Parkinson's disease: https://pmc.ncbi.nlm.nih.gov/articles/PMC9978741/
- Direct `PDGinfo.xlsx` inspection found ON/OFF UPDRS-III totals and item columns, H&Y, gait scores, rigidity scores, and related clinical metadata.
- Decision: document-only for this objective. The target is useful context, but the modality is motion-capture/force-plate biomechanics rather than wearable IMU, so it is not a WearGait-PD T1/T3 CCC external validation route.

ALAMEDA:

- Zenodo `15769959` describes a 2025 raw wrist GENEActiv accelerometer dataset from 11 PD patients with clinical annotations including MDS-UPDRS III: https://zenodo.org/records/15769959
- Zenodo API metadata confirms one public ZIP (`PD GeneActiv Dataset.zip`) of about 4.8 GB: https://zenodo.org/api/records/15769959
- The separate ALAMEDA tremor CSV (`10782573`) contains precomputed features and binary tremor labels, not a T1/T3 regression target: https://zenodo.org/records/10782573
- Kimi advised no iter50 preregistration or download: N=11 is below the external augmentation variance floor and adds little paper-rigor value after COPS/FoG-STAR/PADS.

Comprehensive Multi-Modal Dataset:

- Zenodo `14848598` is public and describes a derived multimodal table that integrates AMP Parkinson's Disease Progression Prediction Data from Kaggle with a Mendeley gait repository: https://zenodo.org/records/14848598
- Zenodo API metadata confirms two small CSV files: `Updated_Clinical_Gait_Dataset.csv` (81 kB) and `Final_Integrated_MultiModal_Dataset.csv` (10.5 MB): https://zenodo.org/api/records/14848598
- Direct CSV inspection found `Updated_Clinical_Gait_Dataset.csv` has 2,223 rows / 771 patient IDs and only UPDRS part totals plus scalar gait summaries (`gait_time`, `gait_steps`, `freezing`). `Final_Integrated_MultiModal_Dataset.csv` has 1,113 rows / 1,196 columns keyed by `visit_id`, dominated by CSF protein/peptide features and no raw wearable IMU columns.
- Kimi advised `NO-PREREG / DOCUMENT-ONLY` because the co-observation is a derived benchmark artifact, not a contemporaneous sensor-clinical cohort, and there is no raw wearable feature space or T1 item granularity. Snapshot artifact: `results/derivative_multimodal_route_refresh_20260509.{json,md}`.
- Decision: no preregistration/download/scaffold. This is public related-work context only, not a WearGait-PD T1/T3 external validation route.

Monipar:

- Zenodo `8104853` is public CC-BY 4.0 and contains 21 PD / 7 HC subjects, smartwatch triaxial accelerometer data at 50 Hz, and files including `MONIPAR SUBJECTS DATA.xlsx`, supervised/remote/control `.mat` files, and tremor-label companions: https://zenodo.org/records/8104853
- The Frontiers article states that the supervised group had 6 PD subjects and 46 single trials with MDS-UPDRS evaluations; labels were assigned only for exercises 1, 2, 4, 5, 6, and 8, corresponding to items 3.17, 3.15, 3.4, 3.5, 3.6, and 3.10. Exercise 7 / 3.9 was excluded from the correlation analysis due to limited signal duration: https://www.frontiersin.org/journals/neurology/articles/10.3389/fneur.2023.1326640/full
- Kimi advised `document_only_no_prereg_no_download_no_remote_job`; Claude failed with low credit and `glmcode` is unavailable. Snapshot artifact: `results/smartwatch_subitem_route_refresh_20260509.{json,md}`; Kimi note: `results/external_route_audit_monipar_bioclite_20260509.md`.
- Decision: no preregistration/download/scaffold. Monipar is related work for consumer-smartwatch subitem monitoring, not a WearGait-PD T1/T3 CCC route.

BIOCLITE:

- Zenodo `16408199` is public CC-BY 4.0 and contains 24 PD / 16 healthy participants with smartwatch triaxial accelerometer and gyroscope data at 50 Hz across initial supervised, seven unsupervised, and final supervised exercise sessions: https://zenodo.org/records/16408199
- The BIOCLITE README maps exercise columns to MDS-UPDRS items 3.17, 3.15, 3.4, 3.5, 3.6, 3.9, and 3.10, and states that each exercise record includes the corresponding MDS-UPDRS score when clinical evaluation is available, using 99 when no clinical evaluation is available: https://zenodo.org/records/16408199/preview/Bioclite_README.txt?include_deleted=0
- The protocol paper describes BIOCLITE as a supervised/unsupervised smartwatch follow-up for MDS-UPDRS exercise sequences and free-living activity, with public data planned/released: https://doi.org/10.2196/72820
- Decision: no preregistration/download/scaffold. BIOCLITE is item-level and small; it cannot provide total T3 or the full T1 9-14 composite.

mPower:

- Synapse portal `syn4993293` describes mPower as an iPhone-based cohort with touchscreen, accelerometer, microphone, gyroscope, and magnetometer data; reported outcomes include medication report, PDQ-8, MDS-UPDRS, demographics survey, and 8,320 participants: https://www.synapse.org/Synapse:syn4993293
- The Scientific Data descriptor says mPower used only a subset of MDS-UPDRS patient questionnaire items focused on self-evaluation, and all surveys are self-reported outcomes: https://www.nature.com/articles/sdata201611
- A Synapse discussion confirms extra MDS-UPDRS permission/copyright workflow beyond ordinary data access: https://www.synapse.org/Synapse%3Asyn8717496/discussion/threadId%3D2202
- Decision: no preregistration or download. The labels are not clinician-rated MDS-UPDRS Part III total, and phone-held/pocket tasks are not an aligned WearGait-PD wrist-IMU gait/balance feature space.

Papadopoulos phone-call tremor:

- Zenodo record `7273759` is public and describes in-the-wild smartphone accelerometer recordings captured during phone calls. The clinically examined file has 45 subjects; the larger self-reported file has 454 subjects: https://zenodo.org/records/7273759
- The Zenodo metadata states that the clinical annotations are tremor-specific: UPDRS II item 16, right/left Part III item 20 rest tremor, right/left Part III item 21 action/postural tremor, a binary signal-expert tremor annotation, and PD status: https://zenodo.org/records/7273759
- Decision: no preregistration or download for the active T1/T3 CCC objective. This is a phone-call tremor-subitem dataset, not total UPDRS-III, not the T1 items 9-14, and not aligned to WearGait-PD gait/balance IMU tasks. It can be cited only as tremor-subitem / free-living context.

Harmonized Upper/Lower Limb Accelerometry:

- Data in Brief / PMC article describes a harmonized dataset of 790 people, 2,885 recording days, about 7% Parkinson's disease, demographic/clinical data, and upper/lower limb accelerometry organized on NICHD DASH: https://pmc.ncbi.nlm.nih.gov/articles/PMC12681975/
- The same article's data-access section says Part1 and Part2 are controlled-access DASH studies and that users submit a form; Part1 is limited to neurological/movement-disorder research: https://pmc.ncbi.nlm.nih.gov/articles/PMC12681975/
- GitHub `keithlohse/HarmonizedAccelData` documents R processing code for daily-life bilateral-wrist ActiGraph data and 26 upper-limb summary variables such as movement time, magnitude, entropy, jerk, and frequency: https://github.com/keithlohse/HarmonizedAccelData
- Zenodo `10999195` archives only the processing code ZIP, not a ready T1/T3 target table: https://zenodo.org/records/10999195
- Kimi and Gemini both advised document-only/no-scaffold because no total MDS-UPDRS Part III or T1 items 9-14 are confirmed, the data are daily-life ActiGraph summaries rather than WearGait task-aligned raw IMU, and the PD subgroup is only about 55 subjects. Claude failed with low credit; `glmcode` is unavailable.
- Decision: no preregistration, download, scaffold, or remote job for the active T1/T3 CCC objective. Cite only as a rehab/free-living accelerometry resource if needed.

REMAP Bristol:

- The Scientific Data article describes 24 participants, including 12 with PD, and separates open anonymous/coarsened skeleton data from controlled accelerometry and uncoarsened skeleton data: https://www.nature.com/articles/s41597-023-02663-5
- The article states the controlled dataset contains bilateral wrist accelerometry and individual-level demographic/clinical rating scale outcomes given in ranges, with access by application and controlled-data agreement: https://www.nature.com/articles/s41597-023-02663-5
- Open dataset landing page confirms the controlled sister dataset is where the accelerometry is available by application: https://data.bris.ac.uk/data/dataset/21h9f9e30v9cl2fapjggz4q1x7
- Decision: skip. This is not an unblocked exact continuous T3 CCC target, and N=12 PD cannot improve the internal ceiling after COPS/FoG-STAR/PADS.

Oxford OPDC / OxQUIP wearable lead:

- The OxQUIP wearable progression article reports 91 recruited PD participants, MDS-UPDRS-III scoring, and six APDM IMUs during walking and postural sway: https://www.nature.com/articles/s41531-023-00581-2
- The same paper's data-availability statement says original data from the ongoing OxQUIP study could not be shared at publication, and the code/training data were not public: https://www.nature.com/articles/s41531-023-00581-2
- The DPUK OPDC Discovery catalogue describes a large clinical cohort and application path, but does not expose a confirmed public aligned wearable-IMU file route: https://data.dpuk.ukserp.ac.uk/cohortdirectory/Item?fingerPrintID=OPDC+Discovery
- Decision: no preregistration. A DPUK query can ask whether aligned IMU + clinician Part III files exist, but there is no current public/approved route to download.

PD-BioStampRC21:

- The npj Parkinson's Disease article reports 17 PD and 17 control participants wearing five BioStampRC accelerometers for about two days, with MDS-UPDRS Part III clinical assessments and rest-tremor item analyses: https://www.nature.com/articles/s41531-021-00248-w
- Data availability points to IEEE DataPort DOI `10.21227/g2g8-1503` for sensor accelerometry, MDS-UPDRS assessment-task annotation data, and demographic/clinical assessment data: https://doi.org/10.21227/g2g8-1503
- DBLP indexes that DOI as `PD-BioStampRC21: Parkinson's Disease Accelerometry Dataset from Five Wearable Sensor Study`: https://dblp.org/rec/data/10/AdamsDSXTSDS22
- Decision: skip. It is open, but the sensors are chest/thigh/forearm rather than wrist, N=17 PD is too small for augmentation, and it is best treated as a forearm/tremor robustness dataset rather than a WearGait-PD T1/T3 CCC route.

MJFF / Hssayeni:

- Synapse project metadata for `syn20681023` lists device locations `wrist waist forearm shank back`, sensor type accelerometer, and reported outcomes including MDS-UPDRS: https://www.synapse.org/Synapse%3Asyn20681023/wiki/597164
- Synapse child `syn20681939` is an UPDRS Responses clinical table, but access instructions point back to the parent DUA gate: https://www.synapse.org/Synapse%3Asyn20681939
- The Scientific Data 2021 minimum-set and limb/trunk accelerometry papers are aliases for this same MJFF Levodopa Response / Synapse `syn20681023` route, not separate unblocked datasets: https://doi.org/10.1038/s41597-021-00830-0 and https://doi.org/10.1038/s41597-021-00831-z
- Local authenticated probe artifact remains `results/iter26_dua_status_20260508.json`.

PPMI / Verily Study Watch:

- PPMI access page states qualified researchers may obtain individual-level clinical, sensor, biomarker, genetic, imaging, and other data after signing the Data Use Agreement, submitting an online application, and complying with the publication policy; applications are reviewed within one week: https://www.ppmi-info.org/access-data-specimens/download-data
- PPMI FAQ says first-time users complete registration, sign the DUA, undergo DPC screening, and that clinical data include MDS-UPDRS scores including Part III and Hoehn & Yahr: https://www.ppmi-info.org/help-and-resources/faqs
- The 2025 npj Parkinson's Disease Verily paper used PPMI Verily Study Watch 100 Hz wrist accelerometer data, chunked into one-week sessions, and associated MDS-UPDRS assessments within 3 months / 90 days of wearable data collection: https://www.nature.com/articles/s41531-025-01034-8
- Fresh consult status: Kimi recommended documenting PPMI as an access-gated priority route and not building a scaffold before credentials exist; Claude CLI failed with low credit and `glmcode` was unavailable on PATH.
- Access runbook now exists at `scripts/ppmi_verily_setup.md`. It records the no-scaffold/no-remote-job rule, access request fields, post-approval probe checklist, and leakage rules for any future zero-shot or augmentation track.

Personalized Parkinson Project / PD Virtual Motor Exam:

- The PD-VME paper reports 388 early-stage PD participants in the smartwatch-based virtual motor exam substudy and states that sensor data were collected during yearly in-clinic MDS-UPDRS Part III motor exams, with Verily Study Watch passive monitoring and active self-guided motor tasks: https://pmc.ncbi.nlm.nih.gov/articles/PMC9126938/
- The PPP data-sharing page lists 517 PD participants with clinical assessments, biospecimens, MRI/ECG, questionnaires, and Verily Study Watch physiological/environmental data over two years: https://www.personalizedparkinsonproject.com/data-sharing/available-data/overview-of-the-project-and-available-data/ppp
- PPP data access is governed by a Research and Data Sharing Review Committee and the public cost page lists start-up and review fees; there is no local approval, credential, or row-level schema: https://www.personalizedparkinsonproject.com/data-sharing/requesting-data/additional-information-on-the-procedure/costs-of-data-release
- Access runbook: `scripts/ppp_pd_vme_request_setup.md`.
- Decision: add as a strong gated Verily-watch peer route to PPMI. Do not scaffold, preregister, download, or run until RDSRC approval and schema exist.

WATCH-PD:

- The MDS 2021 baseline abstract reports 132 participants (82 PD, 50 controls) across 17 sites, early untreated PD, 12-month design, Apple Watch/iPhone BrainBaseline tasks, APDM Mobility Lab inertial sensors worn during MDS-UPDRS Part III, and mean MDS-UPDRS motor scores of 24.1 in PD vs 2.7 in controls: https://www.mdsabstracts.org/abstract/watch-pd-wearable-assessments-in-the-clinic-and-home-in-parkinsons-disease-baseline-analyses/
- The npj Parkinson's Disease 2024 longitudinal paper describes the three-device design (APDM Opal sensors, Apple Watch, iPhone BrainBaseline) and confirms traditional rating scales included MDS-UPDRS Parts I-III: https://www.nature.com/articles/s41531-024-00721-2
- The Frontiers/PMC acceptability paper's data availability statement says WATCH-PD datasets are not readily available; they are available to C-Path 3DT Stage 2 members, while non-members may submit proposals to the WATCH-PD Steering Committee for de-identified datasets: https://pmc.ncbi.nlm.nih.gov/articles/PMC11381495/
- C-Path's Integrated Parkinson's Database page says the integrated database does not include digital health technology data at this time, so ordinary C-Path database access is not enough for WATCH-PD sensor files: https://c-path.org/tools-platforms/integrated-parkisons-database/
- Kimi and Gemini recommendations: add WATCH-PD to the route audit as request-gated/document-only; do not scaffold before accepted access and row-level schema. PPMI remains higher priority because it is larger and already has a Verily/MDS-UPDRS publication trail. Claude CLI still failed with low credit and `glmcode` was unavailable on PATH.
- Access checklist: `scripts/watchpd_request_setup.md`.

Advanced PD smartwatch home monitoring / Fay-Karmon 2024:

- The Scientific Reports article describes home-based monitoring of advanced Parkinson's disease using smartwatch-smartphone technology, with 21 advanced-PD participants and Intel Pharma Analytics Platform smartwatch/iPhone monitoring: https://www.nature.com/articles/s41598-023-48209-y
- The methods report an in-clinic visit with MDS-UPDRS Part II and Part III in ON/OFF states plus Part IV, followed by approximately two weeks of home monitoring, daily motor tasks, symptom diaries, and medication/food intake diaries: https://www.nature.com/articles/s41598-023-48209-y
- The paper's data availability statement says the datasets are available from the corresponding author upon reasonable request. There are no public row-level sensor files, label schema, or open SWA algorithm outputs in the repo.
- Kimi recommendation: `NO-PREREG / DOCUMENT-ONLY / ACCESS-REQUEST-ONLY`. N=21 is below stronger external rows already tested, the Intel/SWA scoring is proprietary/schema-hidden, and no T1 item-level route is visible. Claude CLI failed with low credit and `glmcode` was unavailable on PATH.
- Snapshot artifact: `results/request_only_actigraphy_route_refresh_20260509.{json,md}`.

Marital-dyad social actigraphy / Sensors 2023:

- The Sensors/PMC article reports 27 marital dyads where one partner had Parkinson's disease, with 54 total participants and seven days of synchronized motor-activity monitoring: https://pmc.ncbi.nlm.nih.gov/articles/PMC9921738/
- The methods describe non-dominant wrist GeneActiv triaxial accelerometry at 100 Hz and a PD clinical visit including MDS-UPDRS Part III before the recording period: https://pmc.ncbi.nlm.nih.gov/articles/PMC9921738/
- The article says source data are available to researchers upon request to the authors, and code is also available upon request. There are no public row-level sensor files or schema in the repo.
- Kimi recommendation: `NO-PREREG / DOCUMENT-ONLY / ACCESS-REQUEST-ONLY`. N=27 PD participants is underpowered after stronger external rows, the endpoint is daily-life/social actigraphy rather than structured WearGait-like gait/balance, and no T1 item-level route is visible. Claude CLI failed with low credit and `glmcode` was unavailable on PATH.
- Snapshot artifact: `results/request_only_actigraphy_route_refresh_20260509.{json,md}`.

CNS Portugal / Lobo IS2022 AX3 gait:

- Information Society 2022 / PHSS paper: 74 PD patients at Campus Neurologico (CNS) Portugal, Axivity AX3 on wrist and lower back, 100 Hz, 267 gait instances from 104 evaluation sessions of a 10-meter walk test, MDS-UPDRS Part III and H&Y 2-4 labels. Four models were compared (RF, XGBoost, SVM, Linear Regression) with 59 statistical/spectral/temporal features and 2.5/5 s non-overlapping windows. Best 10% heldout-window MAE was 4.26 (RF, 2.5 s, both sensors); best LOSO MAE was 9.99 (SVM, 5 s, both sensors). PDF: https://techandpeople.github.io/downloads/updrs_is22.pdf
- The paper's 10% heldout result is not a clean deployment result: the methods describe a 90% training subset used for LOSO/grid search and a remaining 10% validation set testing windows from patients already seen by those models. Any future use here must use subject/session-grouped validation only.
- The Tech & People publication page lists the same paper, authors, and PHSS 2022 venue: https://techandpeople.github.io/publications/
- A related CNS 2022 Sensors article from the same group and data-collection infrastructure states raw data are available from the corresponding author on request. This supports requestability, but is not treated as proof that the exact 74-patient T3 dataset is public: https://www.mdpi.com/1424-8220/22/11/3980
- Kimi and Gemini recommendations: add to audit as a request-gated direct T3 route; do not scaffold code before schema and access are confirmed. Treat as external-validity evidence only, not an internal WearGait-PD ceiling-breaker. Claude CLI still failed with low credit and `glmcode` was unavailable on PATH.
- Access runbook: `scripts/cns_portugal_request_setup.md`.

Luxembourg upper-limb MDS-UPDRS III subitem study:

- Sensors 2024 / NCER-PD paper reports 33 PD patients and 12 controls performing six hand/arm MDS-UPDRS III tasks with compact bilateral hand IMUs: https://www.mdpi.com/1424-8220/24/7/2195
- The paper's data-availability statement says the datasets are not publicly available and can be requested only under national and institutional regulations; requests go to `request.ncer-pd@uni.lu`.
- Kimi recommendation: skip runbook/scaffold/preregistration; use as document-only upper-limb observability context. Claude CLI failed with low credit and `glmcode` was unavailable on PATH.
- Snapshot artifact: `results/luxembourg_upper_limb_route_refresh_20260509.{json,md}`.
- Decision: no access runbook, preregistration, download, scaffold, or remote job. The route maps to T3 residual-burden items 4/5/6, but it is request-only, ON-medication, subitem-only, and cannot provide a total T3 or full T1 endpoint.

Pre-QuantiPark / ActiMyo levodopa-challenge wearable IMU pilot:

- Scientific Reports 2025 reports 10 people with PD undergoing a single-dose L-dopa challenge while wearing ActiMyo sensors on the most affected wrist and ankle, with MDS-UPDRS Part III collected before drug intake and every 15 minutes for 90 minutes: https://www.nature.com/articles/s41598-025-28927-1
- The same paper states the ActiMyo sensors recorded acceleration and angular velocity at 130.69 Hz and that data may be made available only for academic, non-commercial purposes after written proposal review and a data access agreement: https://www.nature.com/articles/s41598-025-28927-1
- Kimi recommendation: document-only/no runbook/no preregistration/no scaffold because N=10 makes a subject-level 5-fold gate incoherent and the levodopa-challenge endpoint is a within-subject trajectory rather than the WearGait-PD cross-sectional severity target. Claude CLI failed with low credit and `glmcode` was unavailable on PATH.
- Snapshot artifact: `results/prequantipark_route_refresh_20260509.{json,md}`.
- Decision: no access runbook, preregistration, download, scaffold, request packet, or remote job. This route is related work for pharmacological motor-fluctuation monitoring only.

TUM Donié ROCKET/InceptionTime wrist symptom-classification alias:

- Scientific Reports 2025 reports ROCKET and InceptionTime experiments on a 27-patient subset of the 2021 MJFF Levodopa Response Study, with GENEActiv smartwatch data on the most affected limb during predefined tasks: https://www.nature.com/articles/s41598-025-04263-2
- The labels are task-level tremor severity plus bradykinesia/dyskinesia presence or absence, not total UPDRS-III or T1 items 9-14; the data availability statement points back to MJFF/Synapse `syn20681023`: https://www.nature.com/articles/s41598-025-04263-2
- Public code exists, but the repository README says each user must download the raw data from Synapse with configured credentials: https://github.com/cedricdonie/tsc-for-wrist-motion-pd-detection
- Kimi recommendation: document-only alias/no scaffold because this is the same Hssayeni/MJFF DUA gate, the target is not T1/T3 regression, and local ROCKET/MultiROCKET plus small-N learned time-series fine-tuning routes are already negative. Claude CLI failed with low credit and `glmcode` was unavailable on PATH.
- Snapshot artifact: `results/tum_rocket_inception_route_refresh_20260509.{json,md}`.
- Decision: no access runbook, code clone, preregistration, download, scaffold, or remote job. Cite only as related work for small-N wrist-IMU symptom classification.

ICICLE-PD / ICICLE-GAIT:

- The 2026 Frontiers article reports 89 people with PD, lower-back accelerometer wear at home for 7 days, 18-month intervals over 6 years, patient characteristics, and clinical measures including MDS-UPDRS Part III: https://www.frontiersin.org/journals/aging-neuroscience/articles/10.3389/fnagi.2026.1766599/full
- The methods identify ICICLE-GAIT / ICICLE-PD participants and an Axivity AX3 lower-back accelerometer sampled at 100 Hz with +/-8g range: https://www.frontiersin.org/journals/aging-neuroscience/articles/10.3389/fnagi.2026.1766599/full
- The results report N=89 PD participants and 1,476 daily samples across visits, with MDS-UPDRS Part III scores ranging roughly 10-70; traditional ML achieved MAE 10.43, r 0.26, ICC 0.389, and the best global FL variant achieved MAE 9.26, r 0.43, ICC 0.438: https://pmc.ncbi.nlm.nih.gov/articles/PMC13006630/
- The data-availability statement says the data are not readily available and requests should be directed to the named author, so this is request-gated rather than public-download: https://www.frontiersin.org/journals/aging-neuroscience/articles/10.3389/fnagi.2026.1766599/full
- Kimi and Gemini both recommended adding ICICLE as a request-gated external route only and not scaffolding code before the file schema and access agreement exist; Claude CLI failed with low credit and `glmcode` was unavailable on PATH.
- Access runbook: `scripts/icicle_request_setup.md`.

Mobilise-D TVS / CVS:

- Mobilise-D's data page points users to Zenodo/GitHub releases as Mobilise-D data become available: https://mobilise-d.eu/data/
- Zenodo record `15861907` makes the Mobilise-D Technical Validation Study public and states the TVS dataset is designed to validate algorithms, not derive clinical insights from patient cohorts: https://zenodo.org/records/15861907
- The TVS record contains N=108 across healthy adults plus PD, MS, PFF, COPD, and CHF cohorts, with large lower-back IMU/reference-system archives including a PD ZIP: https://zenodo.org/records/15861907
- The 2024 MDS abstract for the Mobilise-D PD cohort reports a 2-year longitudinal observational study with 600 people with PD at baseline, MDS-UPDRS in the clinical battery, and continuous lower-back wearable monitoring for 7 days after each visit: https://www.mdsabstracts.org/abstract/baseline-data-of-the-mobilise-d-parkinson-cohort/
- The UK HRA summary reports the full CVS recruited 602 people with PD within 2,388 total participants, collected clinical and disease-specific outcomes at up to five visits, and used a lower-back wearable for seven days after each visit: https://www.hra.nhs.uk/planning-and-improving-research/application-summaries/research-summaries/mobilise-d-clinical-validation-study/
- Kimi and Gemini agreed on the decision: skip the public TVS for UPDRS-III regression; keep CVS as watch-list/request only; do not scaffold code until row-level wearable data and MDS-UPDRS schema/access are confirmed. Claude CLI failed with low credit and `glmcode` was unavailable on PATH.

ParaDigMa:

- JOSS 2026 paper: https://doi.org/10.21105/joss.09502
- GitHub repository: https://github.com/biomarkersParkinson/paradigma
- Zenodo archive: https://doi.org/10.5281/zenodo.19207320
- ParaDigMa is an open-source Python toolbox for extracting PD digital biomarkers from wrist sensor data during passive daily-life monitoring. It provides validated pipelines for arm swing during gait, tremor, and pulse rate.
- It has been empirically validated on Verily Study Watch, Axivity AX6, Gait-up Physilog 4, and Empatica EmbracePlus.
- Despite external validation, applying ParaDigMa to WearGait would constitute a local scalar handcrafted feature addition. The repo closes this path: iter14 FoG-summary scalars were NULL, T3 IMU feature additions are dead, and `verify_current_goal_state.py` records "0 local model actions remain."
- Snapshot artifact: `results/paradigma_yin_route_refresh_20260509.{json,md}`.
- Decision: no preregistration, download, scaffold, or remote job. Cite only as related work for standardized wrist-IMU PD biomarker extraction.

Yin et al Frontiers Neurology 2025:

- Frontiers in Neurology article: https://www.frontiersin.org/journals/neurology/articles/10.3389/fneur.2025.1527020/full
- PMC version: https://pmc.ncbi.nlm.nih.gov/articles/PMC12435819/
- The study analyzed gait parameters (plantar dorsiflexion angle, plantar flexion angle, stride length, foot clearance, velocity, cadence, stride time) in 20 PD patients and 17 healthy controls in OFF and ON medication states.
- The authors report LOOCV R²=0.675 for total MDS-UPDRS III, R²=0.775 for non-tremor part score, and R²=0.138 for tremor part score.
- Raw data is stated to be available from the corresponding author on request. No public row-level dataset or schema exists.
- The input gait parameters are likely motion-capture or instrumented-walkway derived, not WearGait-aligned raw wearable IMU. Even with data access, there is no direct path to extract WearGait V2 features or run a zero-shot IMU transfer.
- N=20 PD is underpowered versus already-tested routes (FoG-STAR N=22, COPS N=62). The repo constraint "no scaffold before data/schema for request-only routes" applies.
- Snapshot artifact: `results/paradigma_yin_route_refresh_20260509.{json,md}`.
- Decision: no access runbook, preregistration, download, scaffold, or remote job. Cite only as related work for small-N gait-parameter correlation with MDS-UPDRS III.

Parkinson@Home arm-swing validation:

- DOI landing page: https://doi.org/10.34973/fr4z-a489
- Public WebDAV distribution: https://webdav.data.ru.nl/dcmn/DSC_pdhasq_t0000123a_971_v1/
- Code repository: https://github.com/biomarkersParkinson/pdathome_gait
- Related open-source arm-swing paper: https://jneuroengrehab.biomedcentral.com/articles/10.1186/s12984-025-01625-x
- Route facts: 25 PD participants and 25 controls; PD participants have OFF and ON medication recordings, bilateral wrist accelerometer/gyroscope data at 200 Hz, prepared per-subject parquet files, and public `patient_info.csv` fields with MDS-UPDRS Part III subitems.
- Probe artifact: `results/iter53_parkinsonathome_probe.json`. Metadata probe found 50 clinical rows, 25 valid PD OFF T3 targets, OFF target range 17-67, public UPDRS subitems, no public H&Y/disease-duration/sex/DBS covariates for Track B, and a sample prepared parquet whose acceleration magnitude required g-to-m/s^2 conversion.
- Preregistration: `results/preregistration_t3_iter53_parkinsonathome_zeroshot.json`, formula SHA256 `417fdfe0bd2f07c8c5415bd49c87b70725979a26517fe353ca376e2b85387888`. It froze Track A WearGait-to-Parkinson@Home wrist zero-shot, Track C Parkinson@Home-only LOOCV sanity, Track D OFF/ON response sensitivity, and a hard stop requiring at least 20 valid OFF PD subjects after target and feature-readability filtering.
- Extraction artifact: `results/iter53_parkinsonathome_features.csv` plus `results/iter53_parkinsonathome_features.csv.manifest.json`. Extraction retained 18 valid OFF PD subjects / 36 OFF+ON rows. Seven subjects were skipped: four had too-short right-wrist clean-gait segments for the frozen 30 s window policy, and three lacked a right-wrist side mapping in the public distribution file.
- Kimi recommendation before scoring: probe-gated preregistration; no internal canonical update under any outcome. Claude failed low-credit; `glmcode` was not on PATH.
- Decision: public direct T3 route, but iter53 hard-stopped before scoring at N=18 vs the frozen N>=20 rule. No Track A/C/D CCC or MAE exists, no Parkinson@Home labels entered WearGait training, and no internal WearGait-PD T1/T3 canonical can change. Do not rerun under the same preregistration; any shorter-window or alternate fallback policy requires a fresh preregistration and remains external-validity-only.

## Recent Post-Tracker Web Leads

Fresh web search after the access-submission tracker found no new compute-ready route.

### Perioperative MDS-UPDRS-III tremor accelerometry / Smid 2026

- Decision: `document_only_no_scaffold_no_preregistration_no_remote_job`
- Status: `document_only_tremor_subitems_no_t1_t3_endpoint`
- Label: MDS-UPDRS-III tremor items 3.15-3.18 only
- Modality: wired tri-axial index-finger accelerometers at 200 Hz during 10-second tremor tasks
- N: PD `64`, controls `64`
- Rationale:
  - The endpoint is tremor subitems 3.15-3.18, not T1 items 9-14 or total MDS-UPDRS Part III.
  - Sensors are index-finger accelerometers in a perioperative seated tremor protocol, not WearGait-aligned wrist/lower-back gait or balance data.
  - Thresholds use healthy-control accelerometry; that is useful method context but not a fold-clean WearGait deployment route.
  - No public row-level data or reusable schema was visible from the opened article page.
- Sources:
  - https://link.springer.com/article/10.1007/s00702-026-03132-0

### PDAssist de novo smartphone UPDRS Part III / Guo 2025

- Decision: `document_only_no_scaffold_no_preregistration_no_remote_job`
- Status: `document_only_smartphone_protocol_not_weargait_aligned`
- Label: UPDRS Part III total and task/subitem scores in untreated de novo PD
- Modality: smartphone accelerometer/gyroscope/touchscreen/camera/microphone tasks
- N: PD `282`, controls `110`
- Rationale:
  - The cohort is larger and clinically interesting, but the modality is smartphone active tasks plus camera/audio rather than wearable IMU comparable to WearGait.
  - The article page says data are available, but no direct row-level public download/schema was visible in the opened evidence.
  - The methods used severity-stratified truncation based on feature correlations with UPDRS-III; that is a methodology warning for leakage-sensitive benchmarking, not a route to reuse.
  - Any future use would need data-owner access plus a fresh protocol and would be external-validity only, not an internal WearGait-PD canonical update.
- Sources:
  - https://journals.sagepub.com/doi/10.1177/1877718X251359494

### Yin et al Frontiers Neurology 2025 gait-parameter regression

- Decision: `already_recorded_no_new_action`
- Status: `already_recorded_request_only_underpowered_no_public_schema`
- Label: MDS-UPDRS III total, tremor part score, non-tremor part score
- Modality: bilateral ankle IMU-derived gait parameters during 10-meter walking
- N: PD `20`, controls `17`
- Rationale:
  - This lead is already represented in the external route ledger via the ParaDigMa/Yin refresh.
  - The paper states raw data are available from authors upon request, but no public row-level schema exists.
  - N=20 PD and request-only schema make it weaker than public routes already tested and closed.
- Sources:
  - https://www.frontiersin.org/journals/neurology/articles/10.3389/fneur.2025.1527020/full
  - https://www.frontiersin.org/journals/neurology/articles/10.3389/fneur.2025.1527020/pdf

Decision: no scaffold, preregistration, download, remote job, or model run follows from these leads. They are related-work / route-ledger entries only.

## Current External Route Sweep - 2026-05-10

Fresh web search after the architecture result-bundle work found no new compute-ready route.

### ProPark home tremor wrist-worn AX6 / Hepp 2025

- Decision: `document_only_no_new_packet_no_scaffold_no_preregistration_no_remote_job`
- Status: `request_only_tremor_endpoint_not_top_queue`
- Label: MDS-UPDRS Part III total plus tremor subitems in the ProPark cohort
- Modality: single wrist Newcastle AX6 acceleration and gyroscope at 100 Hz over seven home-monitoring days
- N: PD `195`, controls `24`
- Rationale:
  - The dataset is available only from the ProPark consortium on reasonable request, so no local probe, scaffold, download, or model run is allowed now.
  - The published analysis is tremor-focused: MDS-UPDRS III items 15-18 and wearable tremor amplitude/duration/volume, not WearGait-style gait/balance regression.
  - Although the cohort includes total MDS-UPDRS III and is larger than several tested external rows, it is lower priority than the existing six access packets because schema, redistributability, raw-file structure, and usable total-score linkage are uninspected.
  - If access is ever approved, it should enter through the existing read-only schema-probe gate and remain external-validity only until a separate preregistered augmentation screen clears.
- Sources:
  - https://www.nature.com/articles/s41531-025-01163-0
  - mailto:propark@amsterdamumc.nl

### DeFoG phase-specific FoG biomechanics / Gait & Posture 2026

- Decision: `already_recorded_no_new_action`
- Status: `alias_to_iter51_tlvmc_defog_external_route`
- Label: UPDRS-III baseline metadata and nFoGQ in the public DeFoG dataset
- Modality: lower-back Axivity acceleration during home-like FoG provocation tasks
- N: PD `35`, controls `n/a`
- Rationale:
  - The paper explicitly analyzes the public DeFoG dataset, already represented by the TLVMC/DeFOG route.
  - Iter51 already ran the WearGait-to-DeFoG zero-shot route and closed it as partial external-validity evidence only.
  - This secondary event-level FoG analysis is useful related work for phase-specific features, but it does not reopen an internal T1/T3 ceiling-break route.
- Sources:
  - https://www.sciencedirect.com/science/article/pii/S0966636226000810
  - https://zenodo.org/records/10959560

### COPS Scientific Data 2026

- Decision: `already_recorded_no_new_action`
- Status: `already_tested_iter49_external_validity_only`
- Label: UPDRS-III OFF/ON total and item CSVs
- Modality: bilateral wrist GENEActiv accelerometry at 100 Hz over free-living days
- N: PD `66`, controls `n/a`
- Rationale:
  - The current web search resurfaced COPS, but iter49 already completed the public download, feature extraction, and zero-shot battery.
  - The result remains external-validity only: wrist-only transfer was null and clinical+wrist transfer was partial.
- Sources:
  - https://www.nature.com/articles/s41597-026-06999-6
  - https://osf.io/5xvwn/

Decision: no scaffold, preregistration, download, remote job, model run, or canonical claim update follows from these leads.

## Decision

Do not launch a CARE-PD download or training job for the current T1/T3 CCC objective. It would consume remote resources but cannot produce a directly comparable T1 or T3 CCC number:

- CARE-PD target is gait severity (`UPDRS_GAIT`, 0-3), not T1 sum items 9-14 or total MDS-UPDRS III.
- CARE-PD modality is 3D body mesh, not WearGait-PD IMU. A mesh encoder cannot be directly fine-tuned or fused with the current IMU feature pipeline without introducing a new cross-modal representation problem.
- The repo already has a WearGait-only HARNet fine-tuning negative (iter37), so another representation-learning detour without matching labels is low-value.

FoG-STAR corrects the earlier "Hssayeni only" routing assumption: it is a direct public T3 external dataset. The first conservative internal-ceiling use, iter38 Stage-1 augmentation, failed its 5-fold gate (seed-mean delta `+0.0008`; bootstrap frac>0 `0.4938`), so it does not change the canonical T3 pipeline. The pre-registered iter39 zero-shot external validation found no wrist-only transfer (CCC `-0.0180`), a partial clinical+wrist signal (CCC `+0.2499`, CI `[+0.0281,+0.5028]`), and a weak FoG-STAR-only LOOCV sanity result (CCC `+0.0821`). OpenRouter Grok 4.3 and DeepSeek V4 Pro both advised treating FoG-STAR as partial external-validity evidence only.

COPS is a public, unblocked direct T3 external route and now has a completed iter49 zero-shot result. It is external-validity evidence only: wrist-only transfer is null, clinical+wrist transfer is partial and similar to FoG-STAR, and within-COPS learning is modest. TLVMC/DeFOG is also public and unblocked: iter51 zero-shot is complete with Track A lower-back magnitude zero-shot CCC `+0.2695` (CI `[+0.1693,+0.3600]`), Track B wrist-to-lumbar stress CCC `+0.0485`, and Track C DeFOG-only LOSO sanity CCC `+0.3450`. This is partial external-validity evidence only and does not change the internal WearGait-PD T3 canonical. WATCH-PD is a direct and protocol-relevant wrist/APDM T3 route, but it is request-gated through C-Path 3DT or Steering Committee proposal and has no public row-level schema; no scaffold, preregistration, download, or remote run is justified until access exists. The Fay-Karmon advanced-PD smartwatch study and the Sensors marital-dyad actigraphy study are also request-only and schema-hidden, but they are lower-priority context rows because they are smaller (N=21 and N=27 PD), not public compute routes, and do not expose T1 item-level targets. Mobilise-D TVS is public but should be skipped for UPDRS-III regression because it is explicitly an algorithm-validation dataset rather than a clinical-inference target. Mobilise-D CVS is a plausible future lower-back longitudinal T3 route, but it remains a release/access/schema watch item; no scaffold, preregistration, download, or remote run is justified until row-level wearable plus MDS-UPDRS data access is confirmed. The remaining direct external-data routes are access/request/release-gated: PPMI/Verily, WATCH-PD, ICICLE-PD/ICICLE-GAIT, CNS Portugal/Lobo AX3 gait, Mobilise-D CVS, and MJFF/Hssayeni.

ALAMEDA is technically public/direct but was not pursued. At N=11, any cross-sectional zero-shot CCC would be dominated by interval width, and the longitudinal/free-living protocol would require a separate pre-registered change-analysis endpoint to avoid post-hoc visit/endpoint selection. It should not consume remote bandwidth for this objective.

mPower, Papadopoulos phone-call tremor, Harmonized Upper/Lower Limb Accelerometry, the Fay-Karmon advanced-PD smartwatch study, the marital-dyad social-actigraphy study, TUM Donié ROCKET/InceptionTime, REMAP Bristol, Oxford OPDC/OxQUIP, and PD-BioStampRC21 were also audited after ALAMEDA. None warrants preregistration or download for the active T1/T3 CCC objective. mPower is phone-based and self-reported; Papadopoulos is smartphone phone-call accelerometry with tremor-subitem labels only; the harmonized accelerometry dataset is daily-life ActiGraph rehab data with no confirmed Part III/T1 targets; Fay-Karmon is N=21, author-request-only, proprietary/schema-hidden, and no T1 route is visible; marital-dyad social actigraphy is N=27 PD, author-request-only, dyad/social-activity oriented, and no T1 route is visible; TUM Donié is a public-code alias to DUA-gated `syn20681023` with task-level symptom-classification labels and already-negative local ROCKET/InceptionTime-style algorithms; REMAP is controlled, tiny, and range-labeled; Oxford wearable data are not publicly shared and OPDC has no confirmed public aligned IMU route; PD-BioStampRC21 is open but N=17 with forearm/chest/thigh sensors. Hssayeni/MJFF, PPMI/Verily, PPP/PD-VME, WATCH-PD, ICICLE-PD/ICICLE-GAIT, CNS Portugal/Lobo, and Mobilise-D CVS remain direct or plausible external wearable-UPDRS routes, but all are access/request/release-gated. If the user applies for only one new gated route, PPMI is still the higher-priority candidate because it is wrist-native, larger, longitudinal, and already has a 2025 Verily/MDS-UPDRS publication trail. PPP/PD-VME is the strongest Verily-watch peer after PPMI, now with access runbook `scripts/ppp_pd_vme_request_setup.md`; WATCH-PD is a strong protocol-matched second/peer route because APDM sensors were worn during MDS-UPDRS Part III and Apple Watch/iPhone data were collected longitudinally, but it is smaller (82 PD), early untreated, and consortium/proposal-gated. CNS Portugal/Lobo is a strong structured-gait peer route because it has wrist + lower-back AX3 and MDS-UPDRS III, but it is author-request-gated and the published 10% validation result is window-level optimistic. ICICLE and Mobilise-D CVS are valuable lower-back longitudinal gait routes once access/release exists, but they should remain document-only until data owners provide files and schemas. TLVMC/DeFOG is public and iter51 is now complete as external-only partial validation; no further TLVMC design selection is justified. The setup runbooks/checklists are `scripts/ppmi_verily_setup.md`, `scripts/ppp_pd_vme_request_setup.md`, `scripts/watchpd_request_setup.md`, `scripts/icicle_request_setup.md`, `scripts/cns_portugal_request_setup.md`, and `scripts/synapse_hssayeni_setup.md`; do not build scaffolds for gated routes until credentials/data access and schemas exist.

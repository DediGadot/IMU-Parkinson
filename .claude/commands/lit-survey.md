---
description: Search PubMed and arXiv for new papers on UPDRS regression from IMU/wearable sensors. Detect scooping threats.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch]
argument-hint: [--since YYYY-MM] [--alert]
---

# Literature Surveillance

Scan PubMed and arXiv for new publications in the PD-IMU UPDRS regression domain.

## Arguments

The user invoked with: $ARGUMENTS

- `--since YYYY-MM`: Only show papers published after this date
- `--alert`: Only show previously-unseen papers

## Context

- We are building the FIRST published UPDRS-III regression on WearGait-PD
- No published WearGait-PD regression exists as of 2026-03-08
- Verified SOTA (see CLAUDE.md for full details):
  - Hssayeni 2021: MAE=5.95, r=0.74, N=24, LOOCV
  - Shuqair 2024: r=0.89, N=24, SSL, LOOCV
  - IS22 MAE=4.26: DISQUALIFIED (window-level leakage)
  - He 2024: NOT UPDRS regression (predicts levodopa response)
- Seen papers list: `/root/pd-imu/lit_survey_seen.json`

## Instructions

### Step 1: Search

Use web search to query for recent papers. Run these searches:

1. `"UPDRS" "regression" "IMU" "gait" site:pubmed.ncbi.nlm.nih.gov`
2. `"UPDRS-III" "prediction" "wearable" "Parkinson" site:pubmed.ncbi.nlm.nih.gov`
3. `"WearGait-PD" site:pubmed.ncbi.nlm.nih.gov OR site:arxiv.org`
4. `"MDS-UPDRS" "Part III" "machine learning" "accelerometer"`
5. `"Parkinson" "motor severity" "inertial" "regression" 2025 OR 2026`
6. `"UPDRS" "deep learning" "gait" "MAE" site:arxiv.org`

Also check arXiv directly:
7. Search arxiv.org for: `UPDRS regression IMU gait Parkinson`

### Step 2: Score Relevance

For each paper found, assign a relevance score (0-100):

**High relevance (50+):**
- Claims UPDRS-III regression from IMU/wearable data
- Uses WearGait-PD dataset
- Reports MAE on UPDRS-III total score
- Direct competitor to our work

**Medium relevance (20-49):**
- UPDRS prediction from any sensor modality
- Gait analysis + Parkinson severity (even if classification)
- New PD-IMU datasets with UPDRS labels

**Low relevance (0-19):**
- Only classification (PD vs HC)
- Only UPDRS subscores without total
- Different modality entirely (voice, handwriting)

### Step 3: Verify Claims

For any paper scoring 50+, VERIFY the actual claims:
- Fetch the paper abstract via WebFetch
- Check: Is it actually UPDRS regression or something else? (Codex/GPT previously hallucinated He 2024 as UPDRS regression when it predicts levodopa response)
- Check: What evaluation protocol? (LOOCV vs held-out test)
- Check: What N? (small N with LOOCV is not comparable to our N=178)
- Check: Any data leakage concerns? (window-level splits, same-subject across folds)

### Step 4: Report

Print a structured report:

```
LITERATURE SURVEILLANCE REPORT
==============================
Date: YYYY-MM-DD
New papers since last scan: X

HIGH RELEVANCE (score >= 50):
  [85] Title of paper
       Authors (Year) — Journal
       Claims: UPDRS-III MAE=X.XX from IMU, N=YY
       Evaluation: LOOCV / held-out / 5-fold CV
       THREAT LEVEL: HIGH/MEDIUM/LOW
       URL: ...

MEDIUM RELEVANCE (score 20-49):
  [35] Title of paper
       ...

THREAT ASSESSMENT:
  - No new papers claim WearGait-PD regression → Our novelty claim is SAFE
  OR
  - WARNING: Paper X claims WearGait-PD UPDRS regression → VERIFY IMMEDIATELY
```

### Step 5: Update Seen List

Save newly found paper IDs to the seen list so they're not flagged again next time.

### Critical Rules

- ALWAYS verify claims from paper abstracts — LLMs hallucinate SOTA results
- A paper doing UPDRS *classification* is NOT a regression competitor
- A paper predicting *levodopa response* is NOT predicting UPDRS-III total
- Papers using z-normalized UPDRS targets have meaningless MAE values
- LOOCV on N=24 is not comparable to held-out test on N=178
- The primary threat is someone publishing WearGait-PD UPDRS regression before us

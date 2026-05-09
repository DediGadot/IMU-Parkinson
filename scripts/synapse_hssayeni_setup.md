# Hssayeni MJFF Levodopa Response Trial — Synapse Setup

> **Mission:** iter26 cross-dataset bridge for the WearGait-PD UPDRS-III regression
> task. The MJFF Levodopa Response Trial Dataset is the **only** public dataset
> we know of that has BOTH wrist accelerometer recordings AND
> MDS-UPDRS Part-III scores — so it is the only fair test of whether
> wrist-IMU UPDRS regression transfers across cohorts when the **task protocol
> is matched** (the iter25b PADS comparison failed, AUROC=0.4975, because PADS
> records mostly stationary upper-limb tasks while WearGait records gait/balance).
>
> **Synapse parent ID:** `syn20681023`
> https://www.synapse.org/Synapse:syn20681023
>
> **Reference paper:** Hssayeni et al. 2021,
> *Symptom Severity Estimation of Parkinson's Disease from Wrist Worn Sensor
> Data Using Deep Learning Methods*, Sensors 21(14):4865.
>
> This file is a copy-paste runbook. Each command is verified against
> the public synapseclient docs as of 2026-05. The actual file layout
> inside `syn20681023` cannot be confirmed until the DUA is granted; the
> exact entity IDs for the wrist accelerometer + UPDRS-III subset must
> be discovered with `syn.getChildren("syn20681023")` after login.

## Current access boundary

Status: Synapse DUA/READ-gated. Do not run a download, feature cache, new
pre-registration, or remote model job until access to `syn20681023` is approved
and the child file/schema listing is visible. The existing iter26 scripts are
scaffolding only while the DUA gate remains closed.

Fillable DUA/request packet: `scripts/hssayeni_mjff_dua_request_packet.md`.
Use it only for the Synapse/MJFF access step; do not commit a completed copy
with personal details, signatures, Synapse credentials, access approvals,
protected schema dumps, or data-use terms.

After access exists, the first action should be a read-only probe that records:

- the child entity tree and file sizes;
- which files contain wrist accelerometer samples;
- which files contain MDS-UPDRS Part III total/item labels;
- subject and visit identifiers linking sensors to labels;
- sampling rates, units, axis conventions, and medication timing;
- label valid ranges and missing-code policy.

Stop before modeling if DUA approval is absent, sensor/label IDs cannot be
linked by subject and visit, raw wrist samples are unavailable, Part III labels
are unavailable, or license terms prohibit aggregate validation artifacts.

## TL;DR runbook

```bash
# 1. Register at https://accounts.synapse.org/register/email (free)
# 2. Apply for DUA at https://www.synapse.org/Synapse:syn20681023 (1-3 days)
# 3. Once approved:
uv pip install synapseclient
python3 -c "import synapseclient; synapseclient.Synapse().login()"   # creates ~/.synapseConfig
mkdir -p /root/pd-imu/data/raw/hssayeni
python3 scripts/sync_hssayeni.py    # see template at the end of this file
ls /root/pd-imu/data/raw/hssayeni/
python3 cache_hssayeni_features.py  # produces results/hssayeni_features.csv
```

The rest of this guide breaks each step out.

---

## Step 1 — Register a Synapse account

1. Open https://accounts.synapse.org/register/email in a browser.
2. Verify the email; pick a username + password.
3. (Recommended) Generate a Personal Access Token (PAT) for headless use:
   - Go to https://www.synapse.org/Profile:v/settings → "Personal Access Tokens".
   - Click **Create New Token**.
   - Scopes: tick **view**, **download**, and **modify** if you plan to upload
     anything; for this project **view + download** is enough.
   - Copy the token string somewhere safe — Synapse only shows it once.

## Step 2 — Apply for the DUA

The MJFF Levodopa Response Trial Dataset (`syn20681023`) is governed by a
Data Use Agreement (DUA) maintained by The Michael J. Fox Foundation.
Approval is typically 1–3 business days.

1. Open https://www.synapse.org/Synapse:syn20681023 while logged in.
2. Click **Request Access**.
3. Read the DUA terms. Confirm your IRB / institutional context. For an
   independent academic-style benchmark study, declare:
   - **Intended use:** Methodological benchmarking — testing transportability
     of an UPDRS-III regression model trained on body-worn IMUs (WearGait-PD,
     `syn26474053` upstream provenance) onto a wrist-only cohort to assess
     cross-dataset generalization.
   - **Outputs:** Aggregate cross-dataset performance metrics (CCC, MAE,
     AUROC). No subject-level data, no derived raw signals, no re-shareable
     features will be published or redistributed.
   - **Storage:** Single private compute server, restricted shell access,
     deletion on study completion.
4. Submit. The MJFF team reviews and emails the decision.

## Step 3 — Install the Synapse Python client

```bash
# The medical/ project uses uv for env mgmt.
cd /home/fiod/medical
uv pip install synapseclient pandas
```

Or in the remote slave context (where the data ultimately lives):

```bash
# On the GPU slave — same env that runs the cache script.
pip install synapseclient pandas
```

## Step 4 — Authenticate the client

Cache credentials once into `~/.synapseConfig` so subsequent runs are
non-interactive.

```python
import synapseclient
syn = synapseclient.Synapse()
# Either: interactive (prompts for username + password)
syn.login()
# Or: PAT-based, recommended for CI/headless:
# syn.login(authToken="<paste-PAT-here>", rememberMe=True)
```

Or shell-equivalent:

```bash
synapse login --rememberMe
# you will be prompted; this writes ~/.synapseConfig
```

After this you should be able to run `syn.login()` with no args.

## Step 5 — Map the dataset

> **Until the DUA is granted, the entity IDs below are placeholders. Run the
> discovery snippet below to enumerate them.**

```python
import synapseclient
syn = synapseclient.Synapse(); syn.login()

PARENT = "syn20681023"

def walk(parent_id, depth=0):
    children = list(syn.getChildren(parent_id))
    for c in children:
        print("  " * depth, c["id"], c["type"], c["name"])
        if c["type"] in ("org.sagebionetworks.repo.model.Folder",
                         "org.sagebionetworks.repo.model.Project"):
            walk(c["id"], depth + 1)

walk(PARENT)
```

Save the output to a file — it will become the manifest of which subset to
download.

### What we expect to find (per Hssayeni 2021)

| Modality                                | Source device      | Sampling | Use in iter26 |
|-----------------------------------------|--------------------|----------|---------------|
| Wrist tri-axial accelerometer           | Apple Watch        | 100 Hz   | **YES**       |
| Wrist tri-axial accelerometer           | Pebble Smartwatch  | 100 Hz   | optional      |
| Trunk accelerometer (Shimmer3)          | Shimmer3 IMU       | 64 Hz    | NO            |
| Clinical assessments (MDS-UPDRS Part-III) | Hand-scored      | per visit | **YES** (target) |
| Visit metadata (time-relative-to-meds)  | CSV / spreadsheet  | -        | **YES**       |

Approximate cohort size: **~30 PD subjects**, multiple sessions each (defOFF,
30 / 60 / 90 / 120 min post-levodopa). Total dataset is small; expect
~< 1 GB raw signals + a few KB metadata.

> The exact subset IDs (e.g. `syn23187XXX` for "Wrist Apple Watch",
> `syn23187XXX` for "UPDRS Scoring") **must be discovered after DUA grant**.
> The cache_hssayeni_features.py script reads from
> `/root/pd-imu/data/raw/hssayeni/...` and is robust to several plausible
> on-disk layouts (see its docstring).

## Step 6 — Download the data

Once you have the wrist-accelerometer + clinical-assessment subset IDs,
download into `/root/pd-imu/data/raw/hssayeni/`:

```python
import os, synapseclient
from pathlib import Path

OUT = Path("/root/pd-imu/data/raw/hssayeni")
OUT.mkdir(parents=True, exist_ok=True)

syn = synapseclient.Synapse(); syn.login()

# Examples — REPLACE with IDs discovered in Step 5.
WRIST_FOLDERS = [
    # ("syn23187XXX", "AppleWatch"),
    # ("syn23187XXX", "PebbleSmartwatch"),
]
CLINICAL_FILES = [
    # "syn23187XXX",  # MDS-UPDRS-III scoring sheet
]

for folder_id, label in WRIST_FOLDERS:
    sub = OUT / label
    sub.mkdir(exist_ok=True)
    for child in syn.getChildren(folder_id):
        if child["type"].endswith("FileEntity"):
            entity = syn.get(child["id"], downloadLocation=str(sub))
            print(f"{label}: {entity.path}")

for file_id in CLINICAL_FILES:
    entity = syn.get(file_id, downloadLocation=str(OUT))
    print(f"clinical: {entity.path}")
```

Or via the CLI:

```bash
mkdir -p /root/pd-imu/data/raw/hssayeni
synapse get -r syn20681023 --downloadLocation /root/pd-imu/data/raw/hssayeni
# (-r = recursive; will respect DUA scope)
```

### Storage plan

Target on the **remote GPU slave**:

```
/root/pd-imu/data/raw/hssayeni/
├── AppleWatch/                       # raw wrist Acc CSV/TXT per recording
│   ├── subj01_off/accelerometer.csv
│   ├── subj01_30min/accelerometer.csv
│   ├── subj01_60min/accelerometer.csv
│   └── ...
├── PebbleSmartwatch/                 # optional secondary wrist sensor
│   └── ...
├── clinical/
│   └── updrs_scores.csv              # subject_id, session_id, time_relative_to_med_min, MDS-UPDRS_3_total
└── README.txt                        # whatever Hssayeni shipped
```

Total expected size: **≤ 1 GB**.

## Step 7 — Verify the download

```bash
ls -lhR /root/pd-imu/data/raw/hssayeni/ | head -50
du -sh /root/pd-imu/data/raw/hssayeni/
```

Expected: subject-level subdirs or flat per-recording CSV/TXT files,
plus a clinical-scores CSV/XLSX.

## Step 8 — Run the feature cache

```bash
cd /home/fiod/medical
uv run python -m py_compile cache_hssayeni_features.py        # syntax check
./gpu.sh cache_hssayeni_features.py                            # extract on remote
./gpu.sh --pull                                                # fetch results back
ls results/hssayeni_features.csv*                              # csv + manifest sidecar
```

The cache produces `results/hssayeni_features.csv` with columns
`sid, task, time_relative_to_med_min, updrs3, wrist_*` and the standard
manifest sidecar `results/hssayeni_features.csv.manifest.json`.

`updrs3` is the **target column**, not a feature — downstream scripts must
treat it as a label and apply fold-local handling per the inductive-firewall
rules in `inductive_lib.py`.

## Step 9 — Sanity-check the cache

After `cache_hssayeni_features.py` runs, do a quick manifest + leak check:

```bash
python3 - <<'PY'
import json, hashlib, pandas as pd
df = pd.read_csv("results/hssayeni_features.csv")
print(df.shape, list(df.columns)[:6], "...", list(df.columns)[-3:])
print("UPDRS-III dist:", df["updrs3"].describe())
print("subjects:", df["sid"].nunique())
print("sessions per subject:", df.groupby("sid").size().describe())

m = json.load(open("results/hssayeni_features.csv.manifest.json"))
assert m["labels_used"] is False, "labels_used must be False at cache layer"
assert m["target_column"] == "updrs3", "target column must be updrs3"
assert m["leakage_status"] == "clean_by_construction"
print("manifest OK")
PY
```

## Step 10 — Pre-register iter26

Once the cache exists, write the iter26 pre-registration JSON
(`results/preregistration_t3_iter26_hssayeni_*.json`) **before** running any
LOOCV / LOSO. Pre-reg fields per the leakage protocol in `AGENTS.md`:

- WG → Hssayeni transfer (zero-shot).
- Hssayeni-only LOOCV (within-cohort upper bound).
- Joint training with site indicator (sensitivity).

---

## Appendix A — Optional `scripts/sync_hssayeni.py` template

A self-contained download wrapper. Adjust IDs after Step 5.

```python
"""Hssayeni MJFF wrist + clinical sync — run after DUA grant."""
from __future__ import annotations
from pathlib import Path
import synapseclient

OUT = Path("/root/pd-imu/data/raw/hssayeni")
OUT.mkdir(parents=True, exist_ok=True)

# Replace once Step 5 reveals the actual layout.
SUBSETS: list[tuple[str, str]] = [
    # ("syn23187XXX", "AppleWatch"),
    # ("syn23187XXX", "PebbleSmartwatch"),
    # ("syn23187XXX", "clinical"),
]

def main() -> None:
    if not SUBSETS:
        raise SystemExit(
            "Edit scripts/sync_hssayeni.py: fill SUBSETS with the subset Synapse IDs "
            "discovered via syn.getChildren('syn20681023') after DUA grant."
        )
    syn = synapseclient.Synapse()
    syn.login()
    for syn_id, label in SUBSETS:
        sub = OUT / label
        sub.mkdir(exist_ok=True)
        try:
            children = list(syn.getChildren(syn_id))
        except Exception:
            children = []
        if children:
            for c in children:
                if c["type"].endswith("FileEntity"):
                    e = syn.get(c["id"], downloadLocation=str(sub))
                    print(f"{label}: {e.path}", flush=True)
        else:
            e = syn.get(syn_id, downloadLocation=str(sub))
            print(f"{label}: {e.path}", flush=True)

if __name__ == "__main__":
    main()
```

## Appendix B — Troubleshooting

- **`synapseclient.exceptions.SynapseHTTPError: 403 Client Error: Forbidden`**:
  DUA not granted, or token lacks `download` scope. Re-check the project
  page status and regenerate the PAT with the right scopes.
- **`KeyError: 'subject_id'` when reading clinical CSV**: the upstream column
  names may differ; inspect the file with `head -3` and adjust the
  `LABEL_COL_CANDIDATES` list at the top of `cache_hssayeni_features.py`.
- **Apple Watch acc magnitude near 1.0 g**: file is gravity-INCLUDED
  (CMAcceleration). The cache script asserts gravity-removed (CMUserAcceleration,
  Hssayeni paper convention) and will fail fast. Filter to the
  user-acceleration channel or subtract gravity before retrying.
- **No UPDRS-III scores for a session**: the cache script keeps the
  features row but with `updrs3 = NaN`; downstream lockbox skips NaN rows.

## Appendix C — Provenance reminder

Per `AGENTS.md`: the cache script writes a `*.manifest.json` sidecar with
`script_sha256`, `git_sha`, `data_sha256`, `created_at_utc`, and
`leakage_status="clean_by_construction"`. Downstream lockbox scripts MUST
verify the manifest before reusing the cache. UPDRS-III appears in the cache
as the regression target — it is not a feature — so `labels_used=False`
applies at the cache layer.
